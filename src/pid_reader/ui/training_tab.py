"""Training tab: start, pause, resume and cancel a background detector-training run, and watch it, without blocking the Reader.

The run itself is a separate detached, low-priority process (engineering/trainer_service): this tab only starts it and reads/writes small state files
on a timer (only while the tab is visible), so it never freezes the window and a run keeps going if the Reader is closed. Candidate models only: nothing
here changes the active detector, the project database or any engineering data.
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

from ..engineering.trainer_service import service

ROOT = Path(__file__).resolve().parents[3]
STATE_LABELS = {
    "NOT_STARTED": "Not started", "STARTING": "Starting…", "RUNNING": "Training", "PAUSING": "Pausing (saving a checkpoint)…", "PAUSED": "Paused",
    "WAITING": "Waiting", "STOPPING": "Stopping…", "CANCELLING": "Cancelling…", "CANCELLED": "Cancelled (checkpoints kept)", "COMPLETED": "Completed (candidate model)",
    "FAILED": "Failed", "STOPPED_UNEXPECTEDLY": "Stopped unexpectedly - press Start to resume",
}
REASONS = {"ON_BATTERY": "on battery power (training runs on AC power only)", "LOW_FREE_MEMORY": "low free memory", "LOW_FREE_DISK": "low free disk space",
           "DAILY_BUDGET_REACHED": "today's compute-hours limit was reached (it continues tomorrow, Perth time)"}
ACTIVE = ("STARTING", "RUNNING", "PAUSING", "PAUSED", "WAITING", "STOPPING", "CANCELLING")


def _minutes(seconds):
    if not seconds and seconds != 0:
        return "-"
    h, m = divmod(int(seconds) // 60, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


class TrainingTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.extra_config = {}                                     # test hook: merged into the run configuration
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.refresh)
        layout = QVBoxLayout(self)
        note = QLabel("Trains the learned symbol detector in the background at low priority (2 CPU threads by default), so you can keep working. It keeps running if you close "
                      "the Reader and resumes from its last checkpoint after a restart. The result is a candidate model only; it never replaces the active detector.")
        note.setWordWrap(True)
        layout.addWidget(note)

        box = QGroupBox("Status")
        form = QFormLayout(box)
        self.state_label = QLabel("Not started")
        self.state_label.setStyleSheet("font-size:16px;font-weight:600")
        self.reason_label = QLabel("")
        self.reason_label.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        form.addRow("State", self.state_label)
        form.addRow("", self.reason_label)
        form.addRow("Progress", self.bar)
        form.addRow("Details", self.detail)
        layout.addWidget(box)

        buttons = QHBoxLayout()
        self.start_button = QPushButton("Start training…")
        self.start_button.clicked.connect(self.start)
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self.pause_or_resume)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        self.folder_button = QPushButton("Open run folder")
        self.folder_button.clicked.connect(self.open_folder)
        for b in (self.start_button, self.pause_button, self.cancel_button, self.folder_button):
            buttons.addWidget(b)
        layout.addLayout(buttons)

        settings = QGroupBox("Settings for the next run")
        sform = QFormLayout(settings)
        self.epochs = QSpinBox()
        self.epochs.setRange(1, 200)
        self.epochs.setValue(6)
        self.threads = QSpinBox()
        self.threads.setRange(1, 4)
        self.threads.setValue(2)
        self.hours = QDoubleSpinBox()
        self.hours.setRange(0, 24)
        self.hours.setSingleStep(0.5)
        self.hours.setValue(0)
        self.hours.setSpecialValueText("no daily limit")
        self.lr = QDoubleSpinBox()
        self.lr.setDecimals(4)
        self.lr.setRange(0.0001, 0.05)
        self.lr.setSingleStep(0.001)
        self.lr.setValue(0.005)
        self.tiles = QLineEdit(str(Path(os.environ.get("PIDLAB_TR1_TILES", r"C:\PIDWork\tr1\tiles"))))
        self.init = QLineEdit("auto")
        self.init.setToolTip("auto = build on the newest finished run (the repo's E5 weights the first time), so the work adds up. Or browse to a weights file.")
        self.torch_python = QLineEdit(os.environ.get("PIDLAB_TR1_PYTHON", r"C:\PIDWork\venv312_torch\Scripts\python.exe"))
        self.state_dir = QLineEdit(str(service.default_state_dir()))
        sform.addRow("Epochs", self.epochs)
        sform.addRow("CPU threads", self.threads)
        sform.addRow("Compute hours per day", self.hours)
        sform.addRow("Learning rate", self.lr)
        sform.addRow("Tiles folder", self._with_browse(self.tiles))
        sform.addRow("Start from weights", self._with_browse(self.init, file=True))
        sform.addRow("Torch Python", self._with_browse(self.torch_python, file=True))
        sform.addRow("Run folder (not OneDrive)", self._with_browse(self.state_dir))
        layout.addWidget(settings)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(400)
        layout.addWidget(self.log, 1)
        self.refresh()

    # ------------------------------------------------------------------------------------------------ helpers
    def _with_browse(self, edit, file=False):
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit, 1)
        b = QPushButton("Browse…")
        b.clicked.connect(lambda: self._browse(edit, file))
        row.addWidget(b)
        return w

    def _browse(self, edit, file):
        start = edit.text() or str(Path.home())
        path = QFileDialog.getOpenFileName(self, "Choose file", start)[0] if file else QFileDialog.getExistingDirectory(self, "Choose folder", start)
        if path:
            edit.setText(path)

    def _state_dir(self):
        return Path(self.state_dir.text().strip() or str(service.default_state_dir()))

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self.timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.timer.stop()

    def reset(self):
        """No-op: a training run is independent of the open drawing."""

    # ------------------------------------------------------------------------------------------------ status
    def refresh(self):
        s = service.status(self._state_dir())
        state = s.get("state", "NOT_STARTED")
        self.state_label.setText(STATE_LABELS.get(state, state))
        reason = s.get("reason")
        self.reason_label.setText(REASONS.get(reason, reason or s.get("message") or ""))
        p = s.get("progress") or {}
        total, it = p.get("iters_total"), p.get("iter")
        self.bar.setValue(1000 if state == "COMPLETED" else int(min(1.0, it / total) * 1000) if total and it else 0)
        parts = []
        if it is not None:
            parts.append(f"epoch {p.get('epoch')}/{p.get('epochs')}, iteration {it}" + (f" of {total}" if total else ""))
        if p.get("loss_recent_mean") is not None:
            parts.append(f"recent loss {p['loss_recent_mean']}")
        if p.get("iters_per_min"):
            parts.append(f"{p['iters_per_min']} iterations/min")
        if p.get("eta_s"):
            parts.append(f"about {_minutes(p['eta_s'])} left (at today's pace; pauses extend it)")
        b = s.get("budget") or {}
        if b.get("used_s") is not None:
            parts.append(f"compute used today {_minutes(b['used_s'])}")
        result = s.get("result") or {}
        ev = s.get("evaluation") or {}
        if ev.get("message") and s.get("state") == "COMPLETED":
            parts.append(f"scoring on held-out plans ({str(ev.get('state')).lower()}): {ev['message']}")
        if result.get("weights"):
            parts.append(f"candidate weights: {result['weights']} (sha256 {str(result.get('weights_sha256'))[:12]}…)")
        self.detail.setText("; ".join(parts) or "-")
        active = state in ACTIVE and s.get("alive", False)
        paused = state in ("PAUSED", "PAUSING") or s.get("controls", {}).get("pause")
        self.start_button.setEnabled(not active)
        self.pause_button.setEnabled(active)
        self.pause_button.setText("Resume" if paused else "Pause")
        self.cancel_button.setEnabled(active)
        self.folder_button.setEnabled(self._state_dir().exists())
        self._tail_log()

    def _tail_log(self):
        lines = []
        for name in ("runner.log",):
            f = self._state_dir() / name
            try:
                data = f.read_bytes()[-3000:].decode("utf8", "replace").splitlines()[-12:]
                lines += [f"[{name}] {x}" for x in data if x.strip()]
            except OSError:
                pass
        ev = self._state_dir() / "service_events.jsonl"
        try:
            import json
            import time
            for raw in ev.read_text(encoding="utf8").splitlines()[-12:]:
                e = json.loads(raw)
                stamp = time.strftime("%H:%M:%S", time.localtime(e["t"])) if isinstance(e.get("t"), (int, float)) else ""
                extra = " ".join(f"{k}={v}" for k, v in e.items() if k not in ("t", "state", "seq", "prev", "sha256") and v is not None)
                lines.append(f"{stamp}  {e.get('state', '')}  {extra}")
        except (OSError, ValueError):
            pass
        text = "\n".join(lines)
        if text != self.log.toPlainText():
            self.log.setPlainText(text)

    # ------------------------------------------------------------------------------------------------ actions
    def config(self):
        cfg = dict(state_dir=str(self._state_dir()), tiles_dir=self.tiles.text().strip(), torch_python=self.torch_python.text().strip(), epochs=self.epochs.value(),
                   threads=self.threads.value(), daily_budget_s=int(self.hours.value() * 3600), lr=self.lr.value(), init=self.init.text().strip() or None, init_trained=True)
        cfg.update(self.extra_config)
        return cfg

    def _start_from(self, cfg):
        path, parent = service.resolve_init(cfg["state_dir"], cfg.get("init") or "auto")
        return (f"finished run {parent}'s weights (building on earlier work)" if parent else Path(path).name)

    def start(self):
        cfg = self.config()
        problems = service.validate(cfg)
        if problems:
            QMessageBox.warning(self, "Cannot start training", "\n".join("• " + p for p in problems))
            return
        hours = "no daily limit" if not cfg["daily_budget_s"] else f"up to {cfg['daily_budget_s'] / 3600:g} compute hours per day"
        text = (f"Start background training of the symbol detector?\n\n• {cfg['epochs']} epochs, {cfg['threads']} CPU threads at low priority, {hours}\n"
                f"• starts from: {self._start_from(cfg)}\n• runs only on AC power; pauses itself when memory or disk is low\n• keeps going if you close the Reader; resumes from the last checkpoint\n"
                "• the result is a CANDIDATE model; the active detector is not changed")
        if QMessageBox.question(self, "Start training", text) != QMessageBox.StandardButton.Yes:
            return
        try:
            service.start(cfg)
        except (ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "Cannot start training", str(exc))
            return
        self.refresh()

    def pause_or_resume(self):
        state_dir = self._state_dir()
        if (state_dir / "PAUSE").exists():
            service.resume(state_dir)
        else:
            service.pause(state_dir)
        self.refresh()

    def cancel(self):
        if QMessageBox.question(self, "Cancel training", "Stop this training run? Checkpoints are kept, but this run will not continue (start again to resume from the last checkpoint).") \
                != QMessageBox.StandardButton.Yes:
            return
        service.cancel(self._state_dir())
        self.refresh()

    def open_folder(self):
        path = self._state_dir()
        if path.exists() and os.name == "nt":
            os.startfile(str(path))                               # noqa: S606 - the user's own run folder
