"""Windows tab for WP04-06 (offscreen Qt): task lifecycle, stale-result guard, cancellation, reviewer scope rules, separate sidecar, export safety.

Synthetic evidence only. Nothing here measures drawing accuracy.
"""
from __future__ import annotations

import json
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("pypdfium2")

from test_wp123_integration import pdf_two_pages  # noqa: E402


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


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from pid_reader.ui import main_window as mw, wp456_tab
    monkeypatch.setenv("PID_WP456_STORE", str(tmp_path / "wp456.sqlite"))
    monkeypatch.setenv("PID_WP123_STORE", str(tmp_path / "wp123.sqlite"))
    monkeypatch.setenv("PIDLAB_TR1_HOME", str(tmp_path / "tr1home"))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "qs"))
    s = QSettings(mw.ORG, mw.APP)
    s.clear()
    s.setValue("reviewer", "GUI Reviewer")
    s.setValue("ocr_engine", "off")
    pdf = tmp_path / "two_pages.pdf"
    pdf.write_bytes(pdf_two_pages())
    w = mw.MainWindow(str(tmp_path / "gui.sqlite"))
    w.show()
    w.shown = []
    for mod in (mw, wp456_tab):
        monkeypatch.setattr(mod.QMessageBox, "information", lambda *a, **k: w.shown.append(a[2]))
        monkeypatch.setattr(mod.QMessageBox, "warning", lambda *a, **k: w.shown.append("WARN " + a[2]))
    w._import([pdf])
    wait_idle(w, qapp)
    yield w
    w.close()


def test_build_review_scope_and_isolation(win, qapp, tmp_path, monkeypatch):
    from pid_reader.ui import wp456_tab
    tab = win.wp456_tab
    assert "WP-04–06 proposals" in [win.tabs.tabText(i) for i in range(win.tabs.count())]
    before = (win.db.db.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0], win.db.db.execute("SELECT COUNT(*) FROM extraction").fetchone()[0])
    tab.build(False)
    wait_idle(win, qapp)
    assert tab.result and tab.analysis_id and tab.rows and tab._busy is False
    assert tab.build_button.isEnabled() and tab.reread_button.isEnabled()
    assert tab.result["review_state"] == "PROPOSED_UNVERIFIED" and tab.result["wp06"]["worksheet_r1_status"] == "UNCHANGED_NOT_EXPORTED"
    texts = [tab.table.item(r, 1).text() for r in range(tab.table.rowCount())]
    assert "FE-2202" in texts and "V-2201" in texts

    answers = iter([("Zero not O", True), ("FE-2202A", True)])
    monkeypatch.setattr(wp456_tab.QInputDialog, "getText", lambda *a, **k: next(answers))
    row = texts.index("FE-2202")
    tab.table.selectRow(row)
    tab.decide("CORRECTED_READING")
    assert tab.table.item(row, 3).text() == "CORRECTED_READING"
    st = tab._store()
    try:
        d = st.decisions(tab.analysis_id)
        assert len(d) == 1 and d[0]["actor"] == "GUI Reviewer" and d[0]["corrected_text"] == "FE-2202A" and st.verify() == []
    finally:
        st.close()

    # a drawing hypothesis can never be accepted with the printed-text action
    hyp = next((i for i, q in enumerate(tab.rows) if q["display_group"] in ("Symbol", "Association", "contacts", "gaps")), None)
    if hyp is not None:
        tab.table.selectRow(hyp)
        tab.decide("ACCEPTED_AS_READING")
        assert any("hypothesis" in m.lower() or "evidence" in m.lower() for m in win.shown)

    # navigation to the source box
    win.tabs.setCurrentWidget(tab)
    tab.table.selectRow(row)
    tab.show_on_drawing()
    assert win.tabs.currentIndex() == 0 and win.viewer._highlight is not None

    # export is formula-safe and writes no host data
    out = tmp_path / "export"
    out.mkdir()
    monkeypatch.setattr(wp456_tab.QFileDialog, "getExistingDirectory", lambda *a, **k: str(out))
    tab.export_result()
    assert (out / "wp456_result.json").is_file() and (out / "wp456_review_decisions.json").is_file()
    assert json.loads((out / "wp456_review_decisions.json").read_text())[0]["action"] == "CORRECTED_READING"

    tab.audit()
    assert "agree" in win.shown[-1]
    win.open_drawing(win.current_extraction_id)                     # opening a drawing resets the tab, the sidecar keeps its record
    assert tab.result is None and tab.table.rowCount() == 0
    after = (win.db.db.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0], win.db.db.execute("SELECT COUNT(*) FROM extraction").fetchone()[0])
    assert after == before                                          # nothing written to the project
    assert not [m for m in win.shown if m.startswith("WARN")], win.shown


def test_stale_result_does_not_populate_another_page(win, qapp, monkeypatch):
    from pid_reader.engineering.wp456 import host
    tab = win.wp456_tab
    real = host.analyse

    def slow(*a, **k):
        time.sleep(0.5)
        return real(*a, **k)
    monkeypatch.setattr(host, "analyse", slow)
    tab.build(False)
    assert tab._busy and not tab.build_button.isEnabled()
    win.goto_page(2)                                                # user moves on while the worker runs
    wait_idle(win, qapp)
    assert tab.result is None and tab.rows == [] and tab._busy is False and tab.build_button.isEnabled()


def test_cancel_releases_busy_and_keeps_nothing(win, qapp, monkeypatch):
    from pid_reader.engineering.wp456 import host
    tab = win.wp456_tab

    def spin(*a, cancelled=lambda: False, **k):
        t0 = time.time()
        while not cancelled() and time.time() - t0 < 30:
            time.sleep(0.01)
        return {}
    monkeypatch.setattr(host, "analyse", spin)
    tab.build(False)
    t0 = time.time()
    while win.task is None and time.time() - t0 < 5:
        qapp.processEvents()
    qapp.processEvents()
    win.task.cancel()
    wait_idle(win, qapp)
    assert tab.result is None and tab._busy is False and tab.build_button.isEnabled()
    st = tab._store()
    try:
        assert st.con.execute("SELECT COUNT(*) FROM wp456_analyses").fetchone()[0] == 0
    finally:
        st.close()


def test_reread_without_tesseract_is_a_message_not_a_task(win, qapp, monkeypatch):
    from pid_reader.engineering.wp456 import ocr
    tab = win.wp456_tab
    monkeypatch.setattr(ocr, "locate_tesseract", lambda: None)
    tab.build(True)
    assert "Tesseract unavailable" not in win.shown and any("Tesseract" in m for m in win.shown)
    assert win.task is None and tab._busy is False and tab.result is None


def test_reread_passes_selection_and_budgets_to_the_worker(win, qapp, monkeypatch):
    from pid_reader.engineering.wp456 import host, ocr
    tab = win.wp456_tab
    tab.build(False)
    wait_idle(win, qapp)
    seen = {}
    real = host.analyse

    def spy(*a, **k):
        seen.update(k)
        return real(*a, **k)
    monkeypatch.setattr(ocr, "locate_tesseract", lambda: "tesseract-stub")
    monkeypatch.setattr(host, "analyse", spy)
    monkeypatch.setattr(host, "pdf_renderer", lambda pdf: (_ for _ in ()).throw(ValueError("renderer must not run here")) )
    tab.table.selectRow(0)
    tab.build(True)
    wait_idle(win, qapp)
    assert seen["reread_enabled"] is True and seen["selected"]["page"] == 1 and set(seen["selected"]["bbox"]) == {"x0", "y0", "x1", "y1"}
    assert callable(seen["cancelled"])
