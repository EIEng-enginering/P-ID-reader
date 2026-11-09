"""Headless (offscreen Qt) GUI workflow tests. Windows display/DPI checks are separate manual gates."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("pypdfium2")

FIX = Path(__file__).resolve().parents[1] / "fixtures"
SHOTS = Path(__file__).resolve().parents[1] / "TEST_RESULTS" / "WIN312_R01" / "screenshots"


@pytest.fixture(scope="module")
def qapp():
    from pid_reader.ui.app import make_application
    return make_application([])


def wait_idle(window, qapp, timeout=180):
    t0 = time.time()
    while window.task is not None and time.time() - t0 < timeout:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()
    assert window.task is None, "background task did not finish"


@pytest.fixture()
def window(qapp, tmp_path, monkeypatch):
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
    yield w
    w.close()


def _import_fixture(window, qapp, name):
    window._import([FIX / name])
    wait_idle(window, qapp)


def test_empty_state_is_disabled_until_project(qapp, tmp_path):
    from pid_reader.ui import main_window as mw
    w = mw.MainWindow(None)
    w.settings.setValue("last_project", "")
    assert not w.tabs.isEnabled() or w.db is not None
    w.close()


def test_import_analyse_review_register_graph_flow(window, qapp, monkeypatch):
    from pid_reader.ui import main_window as mw
    window.db  # project auto-created on first open
    assert window.db is not None
    _import_fixture(window, qapp, "synthetic_catalog_symbols.pdf")
    assert window.current_extraction_id, "imported drawing should open"
    assert window.drawing_tree.topLevelItemCount() == 1
    assert window.viewer.page_size[0] > 0, "page should be rendered"

    window.analyze()
    wait_idle(window, qapp)
    totals = {l: len(v) for l, v in window.findings.items()}
    assert totals["symbols"] > 0 and totals["geometry"] > 0

    # review the first symbol finding through the same code path as the dialog
    window.layer_combo.setCurrentIndex(window.layer_combo.findData("symbols"))
    window.show_findings()
    window.finding_table.selectRow(0)
    monkeypatch.setattr(mw.ReviewDialog, "exec", lambda self: mw.QDialog.DialogCode.Accepted)
    monkeypatch.setattr(mw.ReviewDialog, "values", lambda self: ("REJECTED", "Not a symbol on the printed sheet", ""))
    window.review_finding()
    assert window.findings["symbols"][0]["state"] == "REJECTED"
    assert window.db.verify_audit_chain()

    # registers: filter equipment, accept first reading
    window.tabs.setCurrentWidget(window.reg_table.parentWidget())
    window.reg_group.setCurrentText("Equipment")
    window._reg_reset()
    assert window.register_total >= 1
    window.reg_table.selectRow(0)
    window.review_reading("ACCEPTED_AS_READING")
    assert window.register_rows[0]["state"] == "ACCEPTED_AS_READING"

    # graph builds without error and lists nodes
    window.refresh_graph()
    assert window._graph["nodes"]
    SHOTS.mkdir(parents=True, exist_ok=True)
    window.tabs.setCurrentIndex(0)
    qapp.processEvents()
    window.grab().save(str(SHOTS / "main_drawing_offscreen.png"))
    window.tabs.setCurrentIndex(1)
    qapp.processEvents()
    window.grab().save(str(SHOTS / "main_registers_offscreen.png"))
    window.tabs.setCurrentIndex(2)
    qapp.processEvents()
    window.grab().save(str(SHOTS / "main_graph_offscreen.png"))


def test_scanned_import_needs_ocr_engine_choice(window, qapp, tmp_path):
    from pid_reader.engineering.pipeline import analyze_drawing  # noqa: F401
    import io
    import pypdfium2 as pdfium
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    src = (FIX / "synthetic_pid_vector.pdf").read_bytes()
    image = pdfium.PdfDocument(src)[0].render(scale=2.0).to_pil().convert("L")
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=(595, 842), pageCompression=0, invariant=1)
    c.drawImage(ImageReader(image), 0, 0, 595, 842)
    c.save()
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(out.getvalue())
    window._import([pdf])           # OCR off: page stays unread, visible as refusal
    wait_idle(window, qapp)
    assert window.current_result["pages"][0]["read_status"] == "REFUSED"


def test_cancel_batch_keeps_state_resumable(window, qapp, tmp_path):
    import shutil
    files = []
    for n in ("synthetic_pid_vector.pdf", "synthetic_rev_o_a.pdf", "synthetic_rev_o_b.pdf"):
        shutil.copy(FIX / n, tmp_path / n)
        files.append(tmp_path / n)
    window.batch_tab._add(files)
    window.batch_tab.start()
    t0 = time.time()
    while window.task is None and time.time() - t0 < 5:
        qapp.processEvents()
    if window.task is not None:
        window.cancel_task()
    wait_idle(window, qapp)
    window.refresh_all()
    assert window.batch_tab.history.count() >= 1
    window.batch_tab.resume()
    wait_idle(window, qapp)
    window.refresh_all()
    bid = window.batch_tab.history.currentData()
    assert window.db.get_batch(bid)["state"] == "COMPLETE"


def test_sheet_info_tab_and_taught_symbol_overlay(window, qapp, tmp_path):
    import io
    from reportlab.pdfgen import canvas
    from pid_reader.engineering.examples import teach_symbol
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=(842, 595), pageCompression=0, invariant=1)
    for x, y in ((150, 400), (350, 400), (550, 400)):
        c.line(x - 60, y, x - 14, y); c.line(x + 14, y, x + 60, y)
        for dx, dy in ((-14, -10), (-14, 10), (14, -10), (14, 10)):
            c.line(x, y, x + dx, y + dy)
        c.line(x - 14, y - 10, x - 14, y + 10); c.line(x + 14, y - 10, x + 14, y + 10)
    c.drawString(700, 30, 'Page 1 of 3'); c.save()
    pdf = tmp_path / 'valves.pdf'
    pdf.write_bytes(out.getvalue())
    window._import([pdf])
    wait_idle(window, qapp)
    assert window.sheet_tab.fields.rowCount() >= 1                       # title block / text items shown
    assert any('1 of 3' in (window.sheet_tab.fields.item(r, 1).text()) for r in range(window.sheet_tab.fields.rowCount()))
    box = {"x0": (150 - 17) / 842, "y0": 1 - (400 + 13) / 595, "x1": (150 + 17) / 842, "y1": 1 - (400 - 13) / 595}
    teach_symbol(window.db, window.current_extraction_id, page=1, bbox=box, label='Block valve', class_hint='VALVE',
                 actor='GUI Tester', threshold=0.75)
    from pid_reader.engineering import findings as F
    window.findings['examples'] = F.list_findings(window.db, window.current_extraction_id, 'examples')
    window._apply_overlays()
    assert len(window.viewer._layers.get('examples', [])) >= 2
    window.layer_combo.setCurrentIndex(window.layer_combo.findData('examples'))
    window.show_findings()
    assert window.finding_table.rowCount() >= 2
    window.viewer.set_teach_mode(True)                                    # teach mode toggles drag mode without error
    assert window.viewer._teach
    window.viewer.set_teach_mode(False)


def test_teach_mode_mouse_drag_emits_normalised_box(qapp):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from pid_reader.ui.viewer import DrawingView
    v = DrawingView()
    v.resize(900, 650)
    v.show()
    assert v.load_page((FIX / 'synthetic_catalog_symbols.pdf').read_bytes(), 1)
    qapp.processEvents()
    got = []
    v.boxDrawn.connect(got.append)
    v.set_teach_mode(True)
    vp = v.viewport()
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(300, 250))
    QTest.mouseMove(vp, QPoint(350, 300))
    QTest.mouseMove(vp, QPoint(400, 340))
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(400, 340))
    qapp.processEvents()
    assert len(got) == 1
    b = got[0]
    assert 0 <= b['x0'] < b['x1'] <= 1 and 0 <= b['y0'] < b['y1'] <= 1
    v.set_teach_mode(False)
    v.close()


def test_window_larger_than_screen_is_fitted(qapp, tmp_path):
    from PySide6.QtGui import QGuiApplication
    from pid_reader.ui import main_window as mw
    from pid_reader.ui.app import fit_window_to_screen
    w = mw.MainWindow(str(tmp_path / 'f.sqlite'))
    w.resize(6000, 4000)
    w.show()
    fit_window_to_screen(w)
    area = QGuiApplication.primaryScreen().availableGeometry()
    # the headless screen can be smaller than the window's minimum size, so check it was shrunk toward the screen
    assert w.width() < 6000 and w.height() < 4000
    assert w.width() <= max(area.width(), w.minimumSizeHint().width()) + 2
    w.close()



def test_saved_but_missing_ocr_engine_falls_back_to_automatic(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from pid_reader.formats.ocr_source import available_engines
    from pid_reader.ui import main_window as mw
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'qs2'))
    s = QSettings(mw.ORG, mw.APP)
    s.clear()
    missing = next((e for e in ('tesseract', 'rapidocr') if e not in available_engines()), None)
    if missing is None:
        pytest.skip('both OCR engines are installed')
    s.setValue('ocr_engine', missing)
    w = mw.MainWindow(str(tmp_path / 'o.sqlite'))
    assert w.ocr_engine() == 'auto'
    s.setValue('ocr_engine', 'off')
    assert w.ocr_engine() == 'off'
    w.close()


def test_export_drawing_files_asks_for_folder_every_time(window, qapp, tmp_path, monkeypatch):
    from pid_reader.ui import main_window as mw
    _import_fixture(window, qapp, "synthetic_catalog_symbols.pdf")
    asked = []
    out = tmp_path / "saved"
    out.mkdir()
    monkeypatch.setattr(mw.QFileDialog, "getExistingDirectory", lambda *a, **k: (asked.append(1), str(out))[1])
    window.export_drawing_files(False)
    wait_idle(window, qapp)
    window.export_drawing_files(True)
    wait_idle(window, qapp)
    assert len(asked) == 2                                              # folder requested on every export
    names = sorted(p.name for p in out.iterdir())
    assert "synthetic_catalog_symbols.json" in names and "synthetic_catalog_symbols (2).html" in names
    assert len(names) == 8
    monkeypatch.setattr(mw.QFileDialog, "getExistingDirectory", lambda *a, **k: "")
    window.export_drawing_files(True)                                   # cancelled picker writes nothing
    assert len(list(out.iterdir())) == 8
