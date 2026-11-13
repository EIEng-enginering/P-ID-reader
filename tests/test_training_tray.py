"""Tray controller: icon per state, tooltip text, menu enabling, start/pause/stop through confirmations, start-with-Windows toggle, single instance. Fake tray, offscreen Qt."""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from test_trainer_service import cfg_for  # noqa: E402
from test_wp456_gui import qapp  # noqa: E402,F401  (fixture)

from pid_reader.engineering.trainer_service import service  # noqa: E402
from pid_reader.ui import training_tray as T  # noqa: E402


class FakeSignal:
    def connect(self, fn):
        self.fn = fn


class FakeTray:
    def __init__(self):
        self.icons, self.tips, self.messages, self.menu, self.hidden = [], [], [], None, False
        self.activated = FakeSignal()

    def setIcon(self, icon):
        self.icons.append(icon)

    def setToolTip(self, text):
        self.tips.append(text)

    def setContextMenu(self, menu):
        self.menu = menu

    def showMessage(self, title, text, icon, ms):
        self.messages.append((title, text))

    def hide(self):
        self.hidden = True


def write_state(state_dir, **fields):
    state_dir.mkdir(parents=True, exist_ok=True)
    service.write_json(state_dir / "service.json", dict(dict(state="RUNNING", pid=os.getpid(), heartbeat_utc=service.now()), **fields))


def controller(tmp_path, confirm=True, **kw):
    warned = []
    c = T.TrayController(tmp_path / "state", tray=FakeTray(), startup=tmp_path / "startup", confirm=lambda t, x: confirm, warn=lambda t, x: warned.append(x), **kw)
    c.warned = warned
    return c


def image_bytes(state, fraction=None):
    img = T.make_icon(state, fraction).pixmap(64, 64).toImage()
    return bytes(img.constBits())


def test_every_state_has_its_own_icon_and_progress_changes_the_ring(qapp):
    states = ["NOT_STARTED", "RUNNING", "PAUSED", "COMPLETED", "FAILED", "CANCELLED"]
    images = {s: image_bytes(s, .5 if s in ("RUNNING", "PAUSED") else None) for s in states}
    assert images["NOT_STARTED"] == images["CANCELLED"]                 # idle and stopped share the grey hollow ring by design
    assert len(set(images.values())) == 5                              # idle, training, paused/waiting, finished, failed all look different
    assert image_bytes("WAITING", .5) == image_bytes("PAUSED", .5)     # waiting and paused share the amber pause glyph
    assert image_bytes("RUNNING", .1) != image_bytes("RUNNING", .9)
    assert not T.make_icon("RUNNING", .3).isNull()


def test_tooltip_is_short_and_informative(qapp):
    s = dict(state="RUNNING", progress=dict(iter=410, iters_total=850, epoch=2, epochs=6, eta_s=3 * 3600 + 300))
    text = T.describe(s)
    assert "Training" in text and "epoch 2/6" in text and "48%" in text and "3 h 05 min left" in text and len(text) <= 127
    assert "(on battery)" in T.describe(dict(state="WAITING", reason="ON_BATTERY"))
    assert T.describe(dict(state="NOT_STARTED")) == "PID Reader training: Idle"
    assert len(T.describe(dict(state="RUNNING", progress=dict(iter=1, iters_total=2, epoch=1, epochs=1, eta_s=10 ** 7)))) <= 127


def test_menu_follows_the_state(qapp, tmp_path):
    c = controller(tmp_path)
    assert c.start_action.isEnabled() and not c.pause_action.isEnabled() and not c.stop_action.isEnabled()
    write_state(c.state_dir, state="RUNNING")
    c.refresh()
    assert not c.start_action.isEnabled() and c.pause_action.isEnabled() and c.stop_action.isEnabled() and c.pause_action.text() == "Pause"
    (c.state_dir / "PAUSE").write_text("x")
    write_state(c.state_dir, state="PAUSED")
    c.refresh()
    assert c.pause_action.text() == "Resume" and "Paused" in c.tray.tips[-1]
    write_state(c.state_dir, state="COMPLETED")
    c.refresh()
    assert c.start_action.isEnabled() and not c.pause_action.isEnabled()


def test_pause_resume_and_stop_use_the_control_files_and_ask_before_stopping(qapp, tmp_path):
    c = controller(tmp_path, confirm=False)
    write_state(c.state_dir)
    c.pause_or_resume()
    assert (c.state_dir / "PAUSE").exists()
    c.pause_or_resume()
    assert not (c.state_dir / "PAUSE").exists()
    c.stop()                                                        # confirmation declined
    assert not (c.state_dir / "CANCEL").exists()
    c.confirm = lambda t, x: True
    c.stop()
    assert (c.state_dir / "CANCEL").exists()


def test_start_is_refused_with_reasons_when_the_setup_is_invalid(qapp, tmp_path, monkeypatch):
    c = controller(tmp_path)
    monkeypatch.setattr(service, "default_config", lambda state_dir=None: dict(state_dir=str(c.state_dir), tiles_dir=str(tmp_path / "none"), torch_python=sys.executable))
    started = []
    monkeypatch.setattr(service, "start", lambda cfg, **k: started.append(cfg))
    assert c.start() is False and started == [] and any("TILES_MANIFEST" in w for w in c.warned)


def test_start_asks_first_repeats_the_last_settings_and_never_launches_a_second_icon(qapp, tmp_path, monkeypatch):
    good = cfg_for(tmp_path, steps=10)
    c = controller(tmp_path)
    good["state_dir"] = str(c.state_dir)
    c.state_dir.mkdir(parents=True)
    service.write_json(c.state_dir / "config.json", dict(service.DEFAULTS, **{k: v for k, v in good.items()}))
    seen = []
    monkeypatch.setattr(service, "start", lambda cfg, **k: seen.append((cfg, k)) or dict(pid=1))
    c.confirm = lambda t, x: False
    assert c.start() is False and seen == []                       # declined: nothing starts
    c.confirm = lambda t, x: True
    assert c.start() is True
    cfg, kw = seen[0]
    assert cfg["epochs"] == good["epochs"] and kw == {"tray": False}
    assert "_command" not in service.last_config(c.state_dir)      # test hooks are never carried into a real repeat


def test_a_finished_or_failed_run_raises_one_notification(qapp, tmp_path):
    c = controller(tmp_path)
    write_state(c.state_dir, state="RUNNING")
    c.refresh()
    write_state(c.state_dir, state="COMPLETED")
    c.refresh()
    c.refresh()
    assert len(c.tray.messages) == 1 and "Finished" in c.tray.messages[0][1]


def test_start_with_windows_is_off_until_the_user_ticks_it(qapp, tmp_path):
    c = controller(tmp_path)
    assert not c.startup_enabled() and not c.startup_file().exists()
    c.set_startup(True)
    text = c.startup_file().read_text(encoding="utf8")
    assert c.startup_enabled() and "training_tray" in text and str(c.state_dir) in text and "pythonw" in text.lower()
    c.set_startup(False)
    assert not c.startup_file().exists()


def test_only_one_icon_runs(qapp, tmp_path, monkeypatch):
    info = tmp_path / "tray.json"
    service.write_json(info, dict(pid=os.getpid() + 0))
    monkeypatch.setattr(service, "TRAY_INFO", info)
    assert service.tray_running()
    monkeypatch.delenv("PID_TRAINER_NO_TRAY", raising=False)
    assert service.ensure_tray(tmp_path / "s") is False            # already running: not launched again
    monkeypatch.setattr(service, "TRAY_INFO", tmp_path / "other.json")
    monkeypatch.setenv("PID_TRAINER_NO_TRAY", "1")
    assert service.ensure_tray(tmp_path / "s") is False            # the test switch never opens a real icon
    service.write_json(info, dict(pid=os.getpid() + 7777777))
    monkeypatch.setattr(service, "TRAY_INFO", info)
    assert service.tray_running() is False


def test_a_completed_run_is_archived_and_a_new_start_begins_fresh(tmp_path):
    cfg = cfg_for(tmp_path, steps=15, delay=0.02)
    state = cfg["state_dir"]
    service.start(cfg, tray=False)
    assert service.wait_for(state, ("COMPLETED", "FAILED"), timeout=60)["state"] == "COMPLETED"
    service.start(cfg, tray=False)
    assert service.wait_for(state, ("COMPLETED", "FAILED"), timeout=60)["state"] == "COMPLETED"
    assert (Path(state) / "run.completed.1" / "weights_final.pt").is_file()              # the first model is kept, never deleted
    assert len((Path(state) / "run" / "loss_log.jsonl").read_text().splitlines()) == 15  # the second run started from zero


def test_the_icon_can_register_itself_when_its_folder_does_not_exist_yet(tmp_path):
    info = tmp_path / "does" / "not" / "exist" / "tray.json"
    assert service.write_json(info, dict(pid=os.getpid()), strict=False) is True      # a missing parent folder once made this silently fail
    assert service.read_json(info)["pid"] == os.getpid()


@pytest.mark.skipif(os.name != "nt", reason="Windows shortcuts")
def test_the_desktop_shortcut_starts_the_icon_without_a_console_and_has_its_own_icon(qapp, tmp_path):
    import subprocess
    lnk = T.make_desktop_shortcut(tmp_path / "desk", state_dir=tmp_path / "state")
    assert lnk.name == "PID Reader Training.lnk" and lnk.is_file()
    ps = "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK); @($s.TargetPath,$s.Arguments,$s.WorkingDirectory,$s.IconLocation,$s.WindowStyle) -join '|'"
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, env=dict(os.environ, LNK=str(lnk))).stdout.strip().split("|")
    target, args, workdir, icon, style = out[0], out[1], out[2], out[3], out[4]
    assert target.lower().endswith("pythonw.exe")                       # no console window
    assert "pid_reader.ui.training_tray" in args and "--interactive" in args and str(tmp_path / "state") in args
    assert Path(workdir) == T.ROOT and icon.lower().endswith("training_tray.ico,0") or icon.lower().endswith("training_tray.ico")
    ico = Path(icon.split(",")[0])
    assert ico.is_file() and ico.read_bytes()[:4] == b"\x00\x00\x01\x00"      # a real ICO file
    again = T.make_desktop_shortcut(tmp_path / "desk", state_dir=tmp_path / "state")      # re-creating replaces it (no duplicates)
    assert again == lnk and len(list((tmp_path / "desk").iterdir())) == 1


def test_a_second_interactive_start_explains_instead_of_doing_nothing(qapp, tmp_path, monkeypatch):
    info = tmp_path / "tray.json"
    service.write_json(info, dict(pid=os.getpid() + 0))
    monkeypatch.setattr(service, "TRAY_INFO", info)
    shown = []
    monkeypatch.setattr(T.QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    # the pid in the file is this process itself, which the check treats as 'me'; use a live different pid instead
    import subprocess
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        service.write_json(info, dict(pid=other.pid))
        assert T.main(["--interactive", "--state-dir", str(tmp_path / "s")]) == 0
        assert shown and "already running" in shown[0]
        shown.clear()
        assert T.main(["--state-dir", str(tmp_path / "s")]) == 0 and shown == []              # non-interactive: silent
    finally:
        other.kill()
