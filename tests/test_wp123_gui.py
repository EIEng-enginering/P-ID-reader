"""Windows review tab for the WP-01..03 proposals (offscreen Qt): build, see on the sheet, record named decisions, nothing leaks into the project."""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

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


def test_tab_build_review_and_isolation(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from pid_reader.ui import main_window as mw, wp123_tab
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
    win = mw.MainWindow(str(tmp_path / "gui.sqlite"))
    win.show()
    shown = []
    monkeypatch.setattr(mw.QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    monkeypatch.setattr(mw.QMessageBox, "warning", lambda *a, **k: shown.append("WARN " + a[2]))
    monkeypatch.setattr(wp123_tab.QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    monkeypatch.setattr(wp123_tab.QMessageBox, "warning", lambda *a, **k: shown.append("WARN " + a[2]))
    try:
        titles = [win.tabs.tabText(i) for i in range(win.tabs.count())]
        assert "WP-01–03 proposals" in titles
        tab = win.wp123_tab
        tab.build()
        assert "Open a drawing first" in shown[-1]                     # nothing open: refused, not guessed
        win._import([pdf])
        wait_idle(win, qapp)
        before = win.db.db.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0]
        results_before = win.db.db.execute("SELECT COUNT(*) FROM extraction").fetchone()[0]

        tab.build()
        wait_idle(win, qapp)
        assert tab.analysis_id and tab.rows, shown
        assert "Nothing is verified" in tab.summary.text() and "native text layer" in tab.summary.text()
        assert tab.table.rowCount() >= 2
        texts = {tab.table.item(r, 0).text() for r in range(tab.table.rowCount())}
        assert {"FE-2202", "V-2201"} <= texts
        assert all(tab.table.item(r, 2).text() == "Proposed (not reviewed)" for r in range(tab.table.rowCount()))
        assert len(win.viewer._layers["wp123"]) >= 2                    # drawn on the sheet
        assert "unverified proposal" in win.viewer._layers["wp123"][0].toolTip()

        # evidence-to-source navigation
        tab.table.selectRow(0)
        assert tab.buttons["accept"].isEnabled() and "PROPOSED_UNVERIFIED" in tab.details.toPlainText()
        win.tabs.setCurrentWidget(tab)
        tab.show_on_drawing()
        assert win.tabs.currentIndex() == 0 and win.viewer._highlight is not None

        # named, reasoned decision with a correction; reason is required
        answers = iter([("FE-2202A", True), ("Zero, not letter O", True)])
        monkeypatch.setattr(wp123_tab.QInputDialog, "getText", lambda *a, **k: next(answers))
        row = next(r for r in range(tab.table.rowCount()) if tab.table.item(r, 0).text() == "FE-2202")
        tab.table.selectRow(row)
        tab.decide("correct")
        row = next(r for r in range(tab.table.rowCount()) if "FE-2202A" in tab.table.item(r, 0).text())
        assert tab.table.item(row, 2).text() == "Reading corrected" and tab.table.item(row, 5).text() == "GUI Reviewer"
        monkeypatch.setattr(wp123_tab.QInputDialog, "getText", lambda *a, **k: ("", True))      # empty reason: nothing is recorded
        tab.decide("reject")
        sc = tab._sidecar()
        try:
            assert len(sc.store.decisions(tab.analysis_id)) == 1
        finally:
            sc.close()
        tab.verify()
        assert tab.result_label.text() == "Decision chain intact."

        # detector rows can only be rejected or left unresolved, never accepted as readings
        tab.group.setCurrentIndex(4)
        if tab.table.rowCount():
            tab.table.selectRow(0)
            assert not tab.buttons["accept"].isEnabled() and not tab.buttons["correct"].isEnabled()

        # filters, other drawing resets, saved analysis comes back, project untouched
        tab.group.setCurrentIndex(0)
        tab.state.setCurrentIndex(1)
        assert all(tab.table.item(r, 2).text() == "Proposed (not reviewed)" for r in range(tab.table.rowCount()))
        tab.reset()
        assert not tab.rows and tab.table.rowCount() == 0
        assert not win.viewer._layers.get("wp123")
        tab.state.setCurrentIndex(0)
        tab.load_last()
        assert tab.rows and any(r["decision"] == "CORRECTED_READING" for r in tab.rows)
        assert win.db.db.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0] == before
        assert win.db.db.execute("SELECT COUNT(*) FROM extraction").fetchone()[0] == results_before
        assert not any(t.startswith("WARN") for t in shown), shown
    finally:
        win.close()
