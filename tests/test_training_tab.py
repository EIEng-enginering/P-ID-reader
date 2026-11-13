"""Training tab (offscreen Qt): start, pause/resume, cancel and refusal through the buttons, against the fake trainer (no torch)."""
import os
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from test_trainer_service import cfg_for  # noqa: E402
from test_wp456_gui import qapp, win  # noqa: E402,F401  (fixtures)

from pid_reader.engineering.trainer_service import service  # noqa: E402
from pid_reader.ui import training_tab as tt  # noqa: E402


def make_tab(qapp, tmp_path, monkeypatch, **kw):
    cfg = cfg_for(tmp_path, **kw)
    tab = tt.TrainingTab(main=None)
    tab.state_dir.setText(cfg["state_dir"])
    tab.tiles.setText(cfg["tiles_dir"])
    tab.torch_python.setText(sys.executable)
    tab.init.setText("")
    tab.hours.setValue(0)
    tab.extra_config = {k: v for k, v in cfg.items() if k.startswith("_") or k in ("min_free_memory_mb", "min_free_disk_mb", "require_ac", "attempt_wall_s", "batch")}
    monkeypatch.setattr(tt.QMessageBox, "question", lambda *a, **k: tt.QMessageBox.StandardButton.Yes)
    shown = []
    monkeypatch.setattr(tt.QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    tab.shown = shown
    return tab


def wait_label(tab, qapp, text, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        qapp.processEvents()
        tab.refresh()
        if text in tab.state_label.text():
            return True
        time.sleep(0.15)
    return False


def test_start_runs_in_the_background_and_the_tab_reports_completion(qapp, tmp_path, monkeypatch):
    tab = make_tab(qapp, tmp_path, monkeypatch, steps=40, delay=0.03)
    tab.start()
    assert not tab.shown
    assert wait_label(tab, qapp, "Completed")
    assert tab.bar.value() == 1000 and "candidate weights" in tab.detail.text()
    assert tab.start_button.isEnabled() and not tab.pause_button.isEnabled()
    assert tab.log.toPlainText()                                    # the event log is shown


def test_pause_and_resume_buttons_and_cancel(qapp, tmp_path, monkeypatch):
    tab = make_tab(qapp, tmp_path, monkeypatch, steps=400, delay=0.05)
    tab.start()
    assert wait_label(tab, qapp, "Training")
    assert tab.pause_button.isEnabled() and tab.pause_button.text() == "Pause" and not tab.start_button.isEnabled()
    tab.pause_or_resume()
    assert wait_label(tab, qapp, "Paused") and tab.pause_button.text() == "Resume"
    tab.pause_or_resume()
    assert wait_label(tab, qapp, "Training") and tab.pause_button.text() == "Pause"
    tab.cancel()
    assert wait_label(tab, qapp, "Cancelled")
    assert tab.start_button.isEnabled()


def test_a_waiting_run_explains_why(qapp, tmp_path, monkeypatch):
    tab = make_tab(qapp, tmp_path, monkeypatch, steps=40, delay=0.03)
    tab.extra_config["min_free_disk_mb"] = 10 ** 9
    tab.start()
    assert wait_label(tab, qapp, "Waiting")
    assert "disk" in tab.reason_label.text()
    tab.cancel()
    assert wait_label(tab, qapp, "Cancelled")


def test_an_invalid_setup_is_refused_with_reasons_and_nothing_starts(qapp, tmp_path, monkeypatch):
    tab = make_tab(qapp, tmp_path, monkeypatch)
    tab.tiles.setText(str(tmp_path / "no_tiles_here"))
    tab.start()
    assert tab.shown and "TILES_MANIFEST" in tab.shown[0]
    assert service.status(tab._state_dir())["state"] == "NOT_STARTED"


def test_the_main_window_has_the_training_tab(win, qapp):
    names = [win.tabs.tabText(i) for i in range(win.tabs.count())]
    assert "Training" in names
    win.tabs.setCurrentWidget(win.training_tab)
    qapp.processEvents()
    assert win.training_tab.timer.isActive()                       # polls only while visible
    win.tabs.setCurrentIndex(0)
    qapp.processEvents()
    assert not win.training_tab.timer.isActive()
