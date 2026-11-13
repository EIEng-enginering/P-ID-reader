"""Notification-area (system tray) controller for the background training service.

A small separate program: it needs neither the Reader window nor a terminal. The icon's colour and progress ring show the state, the tooltip shows epoch / percent /
time left, and the menu starts, pauses, resumes and stops the run. It only reads the service's status files and creates/removes its control files (through
`engineering.trainer_service.service`), so closing it never affects a run, and a run keeps going if it is closed. Candidate models only.

    python -m pid_reader.ui.training_tray [--state-dir DIR]     (started automatically when a training run starts)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QCursor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from ..engineering.trainer_service import policy, service

ROOT = Path(__file__).resolve().parents[3]
ACTIVE = ("STARTING", "RUNNING", "PAUSING", "PAUSED", "WAITING", "STOPPING", "CANCELLING")
GREEN, AMBER, BLUE, RED, GREY = "#2e9d4f", "#e0a100", "#2f6fdd", "#cc3333", "#8b95a1"
COLOURS = {"RUNNING": GREEN, "STARTING": GREEN, "PAUSING": AMBER, "PAUSED": AMBER, "WAITING": AMBER, "STOPPING": AMBER, "CANCELLING": AMBER, "COMPLETED": BLUE,
           "FAILED": RED, "STOPPED_UNEXPECTEDLY": RED, "CANCELLED": GREY, "NOT_STARTED": GREY}
WORDS = {"NOT_STARTED": "Idle", "STARTING": "Starting", "RUNNING": "Training", "PAUSING": "Pausing", "PAUSED": "Paused", "WAITING": "Waiting", "STOPPING": "Stopping",
         "CANCELLING": "Stopping", "CANCELLED": "Stopped", "COMPLETED": "Finished (candidate model ready)", "FAILED": "Failed", "STOPPED_UNEXPECTEDLY": "Stopped unexpectedly"}
REASONS = {"ON_BATTERY": "on battery", "LOW_FREE_MEMORY": "low memory", "LOW_FREE_DISK": "low disk space", "DAILY_BUDGET_REACHED": "today's hours used"}
NOTIFY = ("COMPLETED", "FAILED", "STOPPED_UNEXPECTEDLY")
STARTUP_NAME = "PIDReaderTrainingTray.vbs"


def make_icon(state, fraction=None, size=64):
    """A round icon: dark disc, a progress ring in the state's colour, and a glyph (play, pause, check, exclamation or hollow circle)."""
    colour = QColor(COLOURS.get(state, GREY))
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#1f2933"))
    p.drawEllipse(2, 2, size - 4, size - 4)
    ring = QRectF(7, 7, size - 14, size - 14)
    width = max(4, size // 9)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor("#4b5563"), width))
    p.drawArc(ring, 0, 360 * 16)
    p.setPen(QPen(colour, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
    if state in ACTIVE and fraction is not None:
        p.drawArc(ring, 90 * 16, -int(360 * 16 * max(0.02, min(1.0, fraction))))
    elif state in ("COMPLETED", "FAILED", "STOPPED_UNEXPECTEDLY"):
        p.drawArc(ring, 0, 360 * 16)
    c = size / 2
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(colour)
    if state in ("RUNNING", "STARTING"):
        p.drawPolygon(QPolygonF([QPointF(c - size * .09, c - size * .15), QPointF(c - size * .09, c + size * .15), QPointF(c + size * .17, c)]))
    elif state in ("PAUSED", "PAUSING", "WAITING", "STOPPING", "CANCELLING"):
        p.drawRect(QRectF(c - size * .15, c - size * .15, size * .1, size * .3))
        p.drawRect(QRectF(c + size * .05, c - size * .15, size * .1, size * .3))
    elif state == "COMPLETED":
        p.setPen(QPen(colour, max(3, size // 12), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline(QPolygonF([QPointF(c - size * .14, c), QPointF(c - size * .03, c + size * .11), QPointF(c + size * .16, c - size * .11)]))
    elif state in ("FAILED", "STOPPED_UNEXPECTEDLY"):
        p.drawRect(QRectF(c - size * .04, c - size * .17, size * .08, size * .22))
        p.drawEllipse(QRectF(c - size * .05, c + size * .09, size * .1, size * .1))
    else:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(colour, max(3, size // 14)))
        p.drawEllipse(QRectF(c - size * .13, c - size * .13, size * .26, size * .26))
    p.end()
    return QIcon(pix)


def describe(status):
    """One line for the tooltip (Windows allows 127 characters)."""
    state = status.get("state", "NOT_STARTED")
    text = "PID Reader training: " + WORDS.get(state, state)
    reason = REASONS.get(status.get("reason"))
    if state == "WAITING" and reason:
        text += f" ({reason})"
    pr = status.get("progress") or {}
    if state in ACTIVE and pr.get("iter") is not None:
        total = pr.get("iters_total")
        text += f" - epoch {pr.get('epoch')}/{pr.get('epochs')}"
        if total:
            text += f", {100 * pr['iter'] / total:.0f}%"
        if pr.get("eta_s"):
            h, m = divmod(int(pr["eta_s"]) // 60, 60)
            text += f", ~{h} h {m:02d} min left" if h else f", ~{m} min left"
    return text[:127]


def fraction_of(status):
    pr = status.get("progress") or {}
    return pr["iter"] / pr["iters_total"] if pr.get("iter") is not None and pr.get("iters_total") else None


def pythonw():
    exe = Path(sys.executable)
    return str(exe.with_name("pythonw.exe")) if os.name == "nt" and exe.with_name("pythonw.exe").is_file() else str(exe)


def desktop_dir():
    """The real Desktop folder (it can be redirected, e.g. into OneDrive)."""
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"], capture_output=True, text=True, timeout=30).stdout.strip()
        if out:
            return Path(out)
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.home() / "Desktop"


def write_ico(path):
    """The training icon (green play with a ring) as a multi-size .ico for a shortcut."""
    from io import BytesIO

    from PIL import Image
    from PySide6.QtCore import QBuffer, QIODevice
    pix = make_icon("RUNNING", .66, 256).pixmap(256, 256)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pix.save(buf, "PNG")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.open(BytesIO(bytes(buf.data()))).save(path, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return path


def make_desktop_shortcut(desktop=None, state_dir=None):
    """Create 'PID Reader Training.lnk': it starts the tray icon (no console window). Returns the shortcut path. Windows only."""
    if os.name != "nt":
        raise OSError("desktop shortcuts are created on Windows only")
    state_dir = str(state_dir or service.default_state_dir())
    lnk = Path(desktop or desktop_dir()) / "PID Reader Training.lnk"
    lnk.parent.mkdir(parents=True, exist_ok=True)
    ico = write_ico(service.default_state_dir().parent / "training_tray.ico")
    code = (f"import sys; sys.path.insert(0, r'{ROOT / 'src'}'); from pid_reader.ui.training_tray import main; "
            f"sys.exit(main(['--interactive', '--state-dir', r'{state_dir}']))")
    env = dict(os.environ, LNK=str(lnk), TARGET=pythonw(), ARGS=f'-c "{code}"', WORKDIR=str(ROOT), ICO=str(ico))
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK); $s.TargetPath=$env:TARGET; $s.Arguments=$env:ARGS; $s.WorkingDirectory=$env:WORKDIR; "
          "$s.IconLocation=$env:ICO; $s.Description='Control the background training of the P&ID symbol detector (start, pause, stop)'; $s.WindowStyle=7; $s.Save()")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, env=env, timeout=60)
    if r.returncode != 0 or not lnk.is_file():
        raise OSError("could not create the shortcut: " + (r.stderr or r.stdout).strip()[:300])
    return lnk


def startup_dir():
    return Path(os.environ.get("APPDATA", str(Path.home()))) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


class TrayController(QObject):
    def __init__(self, state_dir, tray=None, startup=None, interval_ms=3000, confirm=None, warn=None):
        super().__init__()
        self.state_dir = Path(state_dir)
        self.startup = Path(startup) if startup else startup_dir()
        self.tray = tray if tray is not None else QSystemTrayIcon()
        self.confirm = confirm or (lambda title, text: QMessageBox.question(None, title, text) == QMessageBox.StandardButton.Yes)
        self.warn = warn or (lambda title, text: QMessageBox.warning(None, title, text))
        self.last_state = None
        self.menu = QMenu()
        self.status_action = QAction("", self.menu)
        self.status_action.setEnabled(False)
        self.start_action = QAction("Start training…", self.menu)
        self.pause_action = QAction("Pause", self.menu)
        self.stop_action = QAction("Stop training…", self.menu)
        self.reader_action = QAction("Open the Reader", self.menu)
        self.folder_action = QAction("Open run folder", self.menu)
        self.startup_action = QAction("Start this icon with Windows", self.menu)
        self.startup_action.setCheckable(True)
        self.quit_action = QAction("Close this icon (training keeps running)", self.menu)
        for a in (self.status_action, self.start_action, self.pause_action, self.stop_action):
            self.menu.addAction(a)
        self.menu.addSeparator()
        for a in (self.reader_action, self.folder_action, self.startup_action):
            self.menu.addAction(a)
        self.menu.addSeparator()
        self.menu.addAction(self.quit_action)
        self.start_action.triggered.connect(self.start)
        self.pause_action.triggered.connect(self.pause_or_resume)
        self.stop_action.triggered.connect(self.stop)
        self.reader_action.triggered.connect(self.open_reader)
        self.folder_action.triggered.connect(self.open_folder)
        self.startup_action.triggered.connect(self.set_startup)
        self.quit_action.triggered.connect(self.quit)
        self.tray.setContextMenu(self.menu)
        if hasattr(self.tray, "activated"):
            self.tray.activated.connect(self._activated)
        self.timer = QTimer(self)
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------------------------------------------ view
    def refresh(self):
        s = service.status(self.state_dir)
        state = s.get("state", "NOT_STARTED")
        self.tray.setIcon(make_icon(state, fraction_of(s)))
        text = describe(s)
        self.tray.setToolTip(text)
        self.status_action.setText(text.replace("PID Reader training: ", ""))
        active = state in ACTIVE and s.get("alive", False)
        paused = state in ("PAUSED", "PAUSING") or bool(s.get("controls", {}).get("pause"))
        self.start_action.setEnabled(not active)
        self.pause_action.setEnabled(active)
        self.pause_action.setText("Resume" if paused else "Pause")
        self.stop_action.setEnabled(active)
        self.startup_action.setChecked(self.startup_enabled())
        if self.last_state is not None and state != self.last_state and state in NOTIFY and hasattr(self.tray, "showMessage"):
            self.tray.showMessage("PID Reader training", text.replace("PID Reader training: ", ""), QSystemTrayIcon.MessageIcon.Information if state == "COMPLETED"
                                  else QSystemTrayIcon.MessageIcon.Warning, 8000)
        self.last_state = state
        return s

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.refresh()
            self.menu.popup(QCursor.pos())

    # ------------------------------------------------------------------------------------------------ actions
    def start(self):
        cfg = service.last_config(self.state_dir) or service.default_config(self.state_dir)
        cfg["state_dir"] = str(self.state_dir)
        problems = service.validate(cfg)
        if problems:
            self.warn("Cannot start training", "\n".join("• " + p for p in problems))
            return False
        hours = "no daily limit" if not cfg.get("daily_budget_s", service.DEFAULTS["daily_budget_s"]) else f"up to {cfg.get('daily_budget_s', service.DEFAULTS['daily_budget_s']) / 3600:g} compute hours a day"
        if not self.confirm("Start training", f"Start (or resume) background training of the symbol detector?\n\n• {cfg.get('epochs', service.DEFAULTS['epochs'])} epochs, "
                            f"{cfg.get('threads', service.DEFAULTS['threads'])} CPU threads at low priority, {hours}\n• AC power only; pauses itself when memory or disk is low\n"
                            "• keeps going if you close the Reader or this icon\n• the result is a candidate model; the active detector is not changed"):
            return False
        try:
            service.start(cfg, tray=False)
        except (ValueError, RuntimeError) as exc:
            self.warn("Cannot start training", str(exc))
            return False
        self.refresh()
        return True

    def pause_or_resume(self):
        if (self.state_dir / "PAUSE").exists():
            service.resume(self.state_dir)
        else:
            service.pause(self.state_dir)
        self.refresh()

    def stop(self):
        if self.confirm("Stop training", "Stop this training run? Checkpoints are kept; Start continues from the last checkpoint."):
            service.cancel(self.state_dir)
            self.refresh()

    def open_reader(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""))
        flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
        subprocess.Popen([pythonw(), "-m", "pid_reader.cli", "gui"], cwd=str(ROOT), env=env, creationflags=flags, close_fds=True)

    def open_folder(self):
        if self.state_dir.exists() and os.name == "nt":
            os.startfile(str(self.state_dir))                     # noqa: S606 - the user's own run folder

    # ------------------------------------------------------------------------------------------------ start with Windows (only on the user's click)
    def startup_file(self):
        return self.startup / STARTUP_NAME

    def startup_enabled(self):
        return self.startup_file().is_file()

    def set_startup(self, enabled):
        f = self.startup_file()
        if enabled:
            f.parent.mkdir(parents=True, exist_ok=True)
            q = lambda s: str(s).replace('"', '""')
            f.write_text('Set s = CreateObject("WScript.Shell")\r\n'
                         f's.CurrentDirectory = "{q(ROOT)}"\r\n'
                         f's.Environment("Process")("PYTHONPATH") = "{q(ROOT / "src")}"\r\n'
                         f's.Run """{q(pythonw())}"" -m pid_reader.ui.training_tray --state-dir ""{q(self.state_dir)}""", 0, False\r\n', encoding="utf8")
        elif f.exists():
            f.unlink()
        self.startup_action.setChecked(self.startup_enabled())

    def quit(self):
        self.timer.stop()
        self.tray.hide()
        app = QApplication.instance()
        if app is not None:
            app.quit()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default=str(service.default_state_dir()))
    ap.add_argument("--interactive", action="store_true", help="started by the user (desktop shortcut): explain what happened instead of exiting silently")
    a = ap.parse_args(argv)
    info = service.read_json(service.TRAY_INFO, {}) or {}
    if policy.pid_alive(info.get("pid")) and info.get("pid") != os.getpid():
        if a.interactive:
            app = QApplication.instance() or QApplication(sys.argv[:1])
            QMessageBox.information(None, "PID Reader training", "The training icon is already running in the notification area (bottom right; it may be under the ^ arrow).\n\n"
                                    "Click it to start, pause or stop training.")
        return 0                                                       # one icon is enough
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("No system tray is available on this desktop.", file=sys.stderr)
        return 2
    service.write_json(service.TRAY_INFO, dict(pid=os.getpid(), state_dir=a.state_dir, started_utc=service.now()), strict=False)
    controller = TrayController(a.state_dir)
    controller.tray.show()
    controller.timer.start()
    if a.interactive:
        controller.tray.showMessage("PID Reader training", "Ready. Click this icon to start, pause or stop training.", QSystemTrayIcon.MessageIcon.Information, 6000)
    code = app.exec()
    try:
        service.TRAY_INFO.unlink()
    except OSError:
        pass
    return code


if __name__ == "__main__":
    raise SystemExit(main())
