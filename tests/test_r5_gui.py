"""R5 update: the R5 menu, its persisted switches, DEXPI export and ledger dialog in the real (offscreen) window, plus switch persistence."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("pypdfium2")

from pid_reader.engineering import r5_features  # noqa: E402

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def test_switch_file_round_trip_env_wins_and_bad_values_are_refused(monkeypatch, tmp_path):
    f = tmp_path / "s.json"
    monkeypatch.setenv("PID_R5_SETTINGS", str(f))
    monkeypatch.delenv("PID_R5_DEXPI", raising=False)
    assert r5_features.mode("DEXPI") == "OFF"                                   # no file -> OFF
    assert r5_features.set_mode("DEXPI", "on") == "ON" and r5_features.mode("DEXPI") == "ON"
    assert json.loads(f.read_text(encoding="utf-8")) == {"DEXPI": "ON"}
    monkeypatch.setenv("PID_R5_DEXPI", "off")
    assert r5_features.mode("DEXPI") == "OFF"                                   # the environment wins over the file
    assert r5_features.mode("DEXPI", "shadow") == "SHADOW"                      # an explicit argument wins over both
    monkeypatch.delenv("PID_R5_DEXPI")
    with pytest.raises(ValueError):
        r5_features.set_mode("DEXPI", "maybe")
    with pytest.raises(ValueError):
        r5_features.set_mode("NOPE", "on")
    f.write_text("{not json", encoding="utf-8")                                   # a corrupt file is OFF, never an error or ON
    assert r5_features.mode("DEXPI") == "OFF"
    f.write_text(json.dumps({"DEXPI": "bogus"}), encoding="utf-8")
    with pytest.raises(ValueError):
        r5_features.mode("DEXPI")                                               # an invalid stored value is refused loudly


@pytest.fixture(scope="module")
def qapp():
    from pid_reader.ui.app import make_application
    return make_application([])


def wait_idle(window, qapp, timeout=240):
    t0 = time.time()
    while window.task is not None and time.time() - t0 < timeout:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()
    assert window.task is None


def test_r5_menu_export_and_ledger_in_the_window(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from pid_reader.ui import main_window as mw
    monkeypatch.delenv("PID_R5_DEXPI", raising=False)
    monkeypatch.delenv("PID_R5_REVIEW_LEDGER", raising=False)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "qs"))
    s = QSettings(mw.ORG, mw.APP)
    s.clear()
    s.setValue("reviewer", "GUI Tester")
    s.setValue("ocr_engine", "off")
    w = mw.MainWindow(str(tmp_path / "gui.sqlite"))
    w.show()
    try:
        titles = [a.text() for a in w.menuBar().actions()]
        assert "&R5 update (proposed)" in titles
        assert {k: a.isChecked() for k, a in w._r5_actions.items()} == {"DEXPI": False, "PAGE_FRAME": False, "REVIEW_LEDGER": False}
        shown = []
        monkeypatch.setattr(mw.QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
        monkeypatch.setattr(mw.QMessageBox, "warning", lambda *a, **k: shown.append("WARN " + a[2]))
        w.export_dexpi_gui()                                                    # nothing is open yet
        assert shown[-1].startswith("Open and analyse")
        w._import([FIX / "synthetic_catalog_symbols.pdf"])
        wait_idle(w, qapp)
        w.analyze()
        wait_idle(w, qapp)
        w.export_dexpi_gui()                                                    # open, but switched off
        assert "switched off" in shown[-1]
        w.show_review_ledger()
        assert "switched off" in shown[-1]
        w._r5_actions["DEXPI"].trigger()
        w._r5_actions["REVIEW_LEDGER"].trigger()
        assert r5_features.mode("DEXPI") == "ON" and r5_features.mode("REVIEW_LEDGER") == "ON"
        dest = tmp_path / "out"
        dest.mkdir()
        monkeypatch.setattr(mw.QFileDialog, "getExistingDirectory", lambda *a, **k: str(dest))
        w.export_dexpi_gui()
        assert "NOT a DEXPI conformance claim" in shown[-1]
        names = sorted(p.name for p in dest.iterdir())
        assert len(names) == 3 and any(n.endswith(".dexpi.xml") for n in names) and any(n.endswith(".sidecar.json") for n in names)
        opened = []
        monkeypatch.setattr(mw.QDialog, "exec", lambda self: opened.append(self.windowTitle()) or 0)
        w.show_review_ledger()
        assert opened == ["Connection review ledger (candidates only)"]
        w._r5_actions["DEXPI"].trigger()
        assert r5_features.mode("DEXPI") == "OFF"
    finally:
        w.close()
