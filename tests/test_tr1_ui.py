"""TR1 UI smoke test (offscreen Qt): toggle the switch, run the detector task, see detections on the sheet and in the table, record decisions.

The detector run itself is replaced by a stand-in that returns a finished result (the real detector is covered by test_tr1_flags_and_detector.py);
everything else - menu, switch persistence, background task, overlay layer, table, queue writes - is the real code.
"""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("pypdfium2")

from pid_reader.tr1 import detector, flags, mapping, review, store  # noqa: E402

FIX = Path(__file__).resolve().parents[1] / "fixtures"


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


def _det(i, coarse, score, status, box):
    return mapping.enrich({"id": i, "page": 1, "bbox": dict(zip(("x0", "y0", "x1", "y1"), box)), "catalogue_class": coarse, "raw_score": score,
                           "score_kind": "UNCALIBRATED_FRCNN_SOFTMAX", "confidence_status": status, "review_state": "PROPOSED",
                           "evidence": {"producer": "tr1-frcnn-e5", "weights_sha256": "c" * 64, "truth_class": "MODEL_PROPOSAL"}})


def test_switch_run_display_and_record_corrections(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from pid_reader.ui import main_window as mw
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "qs"))
    s = QSettings(mw.ORG, mw.APP)
    s.clear()
    s.setValue("reviewer", "GUI Tester")
    s.setValue("ocr_engine", "off")
    w = mw.MainWindow(str(tmp_path / "gui.sqlite"))
    w.show()
    shown = []
    monkeypatch.setattr(mw.QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    monkeypatch.setattr(mw.QMessageBox, "warning", lambda *a, **k: shown.append("WARN " + a[2]))
    try:
        assert "&Learned detector (TR1, proposed)" in [a.text() for a in w.menuBar().actions()]
        assert {k: a.isChecked() for k, a in w._tr1_actions.items()} == {"PIDLAB_SYMBOL_FRCNN_TR1": False, "PIDLAB_SYMBOL_CATALOGUE_TR1": False,
                                                                       "PIDLAB_CORRECTION_QUEUE_TR1": False, "PIDLAB_TRAINING_BATCH_TR1": False}
        w._import([FIX / "synthetic_catalog_symbols.pdf"])
        wait_idle(w, qapp)
        w.open_tr1_dialog()                                                     # a drawing is open, the switch is off
        assert "switched off" in shown[-1]
        assert not store.home().exists()                                       # off writes nothing

        for key in ("PIDLAB_SYMBOL_FRCNN_TR1", "PIDLAB_SYMBOL_CATALOGUE_TR1", "PIDLAB_CORRECTION_QUEUE_TR1"):
            w._tr1_actions[key].trigger()                                      # ticking the menu item persists the switch
            assert flags.enabled(key) and flags.source(key) == "settings file"

        sha = hashlib.sha256(w.current_pdf).hexdigest()
        dets = [_det("frc-aaa", "valve", 0.95, "LEADING", (0.10, 0.10, 0.14, 0.13)), _det("frc-bbb", "instrumentation", 0.80, "LEADING", (0.40, 0.40, 0.44, 0.44)),
                _det("frc-ccc", "general", 0.30, "WEAK_CLASS_WITHHELD", (0.60, 0.60, 0.70, 0.70))]
        record = {"schema": detector.SCHEMA_OUT, "source_sha256": sha, "page": 1, "source_name": "synthetic.pdf", "detections": dets, "model": "stand-in",
                  "diagnostics": {}}
        real_status = detector.status
        monkeypatch.setattr(detector, "status", lambda *a, **k: {"state": "READY", "message": "Learned detector ready.", "fallback": "x", "python": "py", "card": "c", "weights": "w"})
        monkeypatch.setattr(detector, "detect", lambda *a, **k: {"status": "DONE", "message": "3 proposed detection(s)", "detections": dets, "record": record})

        w.open_tr1_dialog()
        dlg = w.tr1_dialog
        assert dlg.run_btn.isEnabled() and dlg.table.rowCount() == 0
        dlg.run_detector()                                                      # background task, progress bar, cancel button
        wait_idle(w, qapp)
        assert dlg.table.rowCount() == 3
        assert len(w.viewer._layers["tr1_frcnn"]) == 3                          # drawn on the sheet as an overlay layer
        assert "PROPOSED" in w.viewer._layers["tr1_frcnn"][0].toolTip()
        assert dlg.table.item(0, 4).text() == "unreviewed"

        dlg.table.selectRow(0)
        dlg.do_confirm()
        assert dlg.table.item(0, 4).text() == "confirmed"
        dlg.table.selectRow(1)
        dlg.do_reject()
        assert dlg.table.item(1, 4).text() == "rejected"
        dlg.table.selectRow(2)
        dlg.do_confirm()                                                        # the detector withheld this one -> needs a second person
        assert dlg.table.item(2, 4).text() == "awaiting second review"
        assert "second reviewer" in w.details.toPlainText()

        events = review._queue().events()
        assert [e["action"] for e in events].count("SUBMIT") == 3 and review._queue().verify() == []
        assert all(e["actor"] in ("GUI Tester", "tr1-detector") for e in events)

        w._tr1_actions["PIDLAB_SYMBOL_FRCNN_TR1"].trigger()                    # switching it off again changes nothing else
        assert not flags.enabled("PIDLAB_SYMBOL_FRCNN_TR1")
        monkeypatch.setattr(detector, "status", real_status)
        dlg.refresh_status()
        assert "switched off" in dlg.status.text() and not dlg.run_btn.isEnabled()
        assert review._queue().verify() == []                                   # the recorded decisions are untouched
    finally:
        w.close()
