"""P&ID Reader main window (PySide6).

Layout: drawing list (left dock) | tabs: Drawing, Registers, Graph, Revisions,
Batch, Libraries, Reports, Audit (centre) | findings + details (right dock).
Every reading, symbol, link and connection shown is a *proposal read from the
drawing*; review decisions are recorded with a named reviewer and are append-only.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDockWidget, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox,
                               QMenu, QTableWidget, QTableWidgetItem, QTabWidget, QToolButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget, QRadioButton, QButtonGroup)

from .. import __version__
from ..engineering import findings as F
from ..engineering.connectivity import drawing_connectivity
from ..engineering.project import ProjectStore
from ..engineering.workspace import register_page
from .graphview import GraphView
from .tabs import AuditTab, BatchTab, LibraryTab, QualityTab, ReportTab, RevisionTab, SheetInfoTab, _fill, _table
from .tasks import CallbackCancelToken, Task
from .viewer import LAYER_COLOURS, LAYER_LABELS, DrawingView
from .wp123_tab import Wp123Tab

ORG, APP = "EnhanceIntegrationEngineering", "PIDReader"
LIMITS_TEXT = (
    "P&ID Reader reads what is printed on a drawing revision and proposes interpretations.\n\n"
    "• Nothing it shows verifies the plant, a drawing's currency, or its as-built status.\n"
    "• It never approves safeguards, assigns SIL, establishes IPL independence or accepts HAZOP/LOPA findings.\n"
    "• Symbol, valve and connection results are geometric proposals; unknown shapes stay unknown.\n"
    "• OCR confidence is a raw engine score, not measured accuracy.\n"
    "• Accuracy on industrial drawings has NOT been independently measured.\n"
    "• A human reviewer must accept, edit or reject each reading; every decision is audited.")

REGISTER_GROUPS = {
    "All named readings": dict(named_only=True),
    "Equipment": dict(object_classes=("VESSEL", "TANK", "COLUMN", "HEAT_EXCHANGER", "PUMP", "COMPRESSOR", "FILTER")),
    "Valves": dict(object_classes=("VALVE_ONOFF", "VALVE_MANUAL", "VALVE_CONTROL", "PSV", "RUPTURE_DISC")),
    "Instruments": dict(object_classes=("INSTRUMENT",)),
    "Piping lines": dict(object_classes=("LINE",), named_only=True),
    "Notes": dict(object_classes=("NOTE",)),
    "Unlabelled line strokes": dict(object_classes=("LINE",)),
}
READING_DECISIONS = ("ACCEPTED_AS_READING", "EDITED_AND_ACCEPTED", "REJECTED", "IGNORED_REGION")
DECISION_TEXT = {
    "ACCEPTED_AS_READING": "Accept as printed on the drawing", "EDITED_AND_ACCEPTED": "Accept with corrected text",
    "REJECTED": "Reject (wrong / not what it says)", "IGNORED_REGION": "Ignore this region",
    "UNRESOLVED": "Leave unresolved", "CONNECTED_AS_DRAWN": "Connected as drawn", "NOT_CONNECTED_AS_DRAWN": "Not connected as drawn",
    "SUPPORTED_AS_DRAWN": "Supported as drawn",
}
STATE_COLOURS = {"PROPOSED": "#6d6d6d", "REJECTED": "#c62828", "UNRESOLVED": "#ef6c00"}


class ReviewDialog(QDialog):
    def __init__(self, parent, title: str, decisions: tuple[str, ...], *, text_options: list[str] | None = None,
                 allow_edit_text: bool = False, current_text: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QRadioButton] = {}
        for d in decisions:
            rb = QRadioButton(DECISION_TEXT.get(d, d.replace("_", " ").capitalize()))
            self.group.addButton(rb)
            self.buttons[d] = rb
            lay.addWidget(rb)
        self.buttons[decisions[0]].setChecked(True)
        self.text = QComboBox()
        self.text.setEditable(True)
        if text_options is not None:
            lay.addWidget(QLabel("Tag text (choose an option read from the drawing, or type a correction)"))
            self.text.addItems(text_options)
            lay.addWidget(self.text)
        elif allow_edit_text:
            lay.addWidget(QLabel("Corrected text (only for “Accept with corrected text”)"))
            self.text.addItem(current_text)
            lay.addWidget(self.text)
        else:
            self.text.hide()
        lay.addWidget(QLabel("Reason / evidence checked (required except for a plain acceptance)"))
        self.reason = QPlainTextEdit()
        self.reason.setFixedHeight(70)
        lay.addWidget(self.reason)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def decision(self) -> str:
        return next(d for d, b in self.buttons.items() if b.isChecked())

    def values(self) -> tuple[str, str, str]:
        return self.decision(), self.reason.toPlainText().strip(), self.text.currentText().strip()


class MainWindow(QMainWindow):
    def __init__(self, db_path: str | None = None):
        super().__init__()
        self.settings = QSettings(ORG, APP)
        self.db: ProjectStore | None = None
        self.db_path = ""
        self.current_extraction_id = ""
        self.current_pdf: bytes | None = None
        self.current_result: dict | None = None
        self.page = 1
        self.page_count = 1
        self.findings: dict[str, list[dict]] = {}
        self.finding_rows: list[dict] = []
        self.register_rows: list[dict] = []
        self.register_offset = 0
        self.register_total = 0
        self.task: Task | None = None
        self.drawing_items: dict[str, str] = {}
        self.setWindowTitle("P&ID Reader")
        self.resize(1500, 900)
        self._build_ui()
        self._build_menus()
        self.resizeDocks([self.dock_drawings, self.dock_findings], [240, 380], Qt.Orientation.Horizontal)
        self.statusBar().showMessage("Open or create a project to begin.")
        remembered = self.settings.value("last_project", "", str) or ""
        if db_path:                      # explicitly requested: create it if needed
            self.open_project(db_path)
        elif remembered and Path(remembered).exists():
            self.open_project(remembered)
        else:
            self._set_enabled(False)

    # ------------------------------------------------------------------ context API (used by tabs)
    def reviewer(self) -> str:
        name = self.settings.value("reviewer", "", str)
        if not name:
            name, ok = QInputDialog.getText(self, "Reviewer name", "Your name (recorded on every review decision):")
            if not ok or not name.strip():
                return ""
            self.settings.setValue("reviewer", name.strip())
            name = name.strip()
        return name

    def ocr_engine(self) -> str:
        """Saved choice, but never an engine that is not installed (that makes scanned sheets fail)."""
        saved = self.settings.value("ocr_engine", "auto", str)
        if saved in ("tesseract", "rapidocr"):
            from ..formats.ocr_source import available_engines
            if saved not in available_engines():
                if not getattr(self, "_warned_engine", False):
                    self._warned_engine = True
                    self.statusBar().showMessage(f"The {saved} OCR engine is not installed; using Automatic instead.", 15000)
                return "auto"
        return saved

    def settings_set(self, key: str, value) -> None:
        self.settings.setValue(key, value)

    def info(self, text: str) -> None:
        self.statusBar().showMessage(text, 15000)
        self.details.appendPlainText(text)

    def refresh_all(self) -> None:
        if not self.db:
            return
        self.refresh_drawings()
        self.refresh_register()
        self.revision_tab.refresh()
        self.batch_tab.refresh()
        self.library_tab.refresh()
        self.audit_tab.refresh()

    def backup_project(self) -> None:
        if not self.db:
            return
        dest, _ = QFileDialog.getSaveFileName(self, "Back up project", "project-backup.sqlite", "SQLite (*.sqlite)")
        if dest:
            try:
                out = self.db.backup(dest)
                self.info(f"Backup written: {out}")
            except Exception as exc:
                QMessageBox.warning(self, "Backup failed", str(exc))

    def export_drawing_files(self, all_drawings: bool) -> None:
        """Save each drawing as its own JSON, HTML and graph files, named after the original PDF."""
        if not self.db:
            QMessageBox.information(self, "No project", "Open or create a project first.")
            return
        ids = None
        if not all_drawings:
            if not self.current_extraction_id:
                QMessageBox.information(self, "No drawing open", "Open a drawing first, or export all drawings.")
                return
            ids = [self.current_extraction_id]
        start = self.settings.value("export_folder", "", str) or ""
        folder = QFileDialog.getExistingDirectory(self, "Choose the folder to save the drawing files in", start)
        if not folder:
            return
        self.settings_set("export_folder", folder)  # only the picker's starting point; it is asked again every time
        db_path = self.db_path

        def job(report, cancelled):
            from ..engineering.drawing_export import export_drawings
            with ProjectStore(db_path) as db:
                return export_drawings(db, ids, folder, progress=lambda i, n, name: report(i / n, f"Saving {name} ({i}/{n})"),
                                       should_stop=cancelled)

        def done(res):
            saved, failed = res["saved"], res["failed"]
            lines = [f"Saved {len(saved)} drawing(s) to {res['folder']}"]
            lines += [f"  {name}: " + ", ".join(p.name for p in paths) for name, paths in saved]
            lines += [f"FAILED {name}: {reason}" for name, reason in failed]
            self.details.setPlainText("\n".join(lines + ["", "These files are unverified readings, not engineering approvals."]))
            self.info(f"Saved {len(saved)} drawing(s) to {res['folder']}" + (f"; {len(failed)} failed" if failed else ""))
            if failed:
                QMessageBox.warning(self, "Some drawings were not saved", "\n".join(f"{n}: {r}" for n, r in failed[:10]))

        self.run_task("Saving drawing files", job, done)

    def run_task(self, title: str, fn, on_done) -> None:
        if self.task is not None:
            frac, msg = getattr(self, "_task_progress", (0.0, ""))
            QMessageBox.information(self, "Busy", f"\u201c{self.task.title}\u201d is still running ({int(frac * 100)} %: {msg or 'working'}).\n\n"
                                                  "Wait for it to finish, or press Cancel (next to the progress bar) and try again. "
                                                  "Finished work is kept.")
            return
        task = Task(title, fn, self)
        self.task = task
        self.progress.setVisible(True)
        self.cancel_btn.setVisible(True)
        self.progress.setValue(0)
        self.statusBar().showMessage(title + "…")
        self._task_progress = (0.0, "starting")
        task.progress.connect(lambda f, m: (setattr(self, "_task_progress", (f, m)), self.progress.setValue(int(f * 100)), self.statusBar().showMessage(m)))

        def finish():
            self.task = None
            self.progress.setVisible(False)
            self.cancel_btn.setVisible(False)
            task.deleteLater()

        def ok(result):
            finish()
            try:
                on_done(result)
            except Exception as exc:
                QMessageBox.warning(self, title, f"{type(exc).__name__}: {exc}")

        task.result.connect(ok)
        task.error.connect(lambda m: (finish(), QMessageBox.warning(self, title + " failed", m)))
        task.stopped.connect(lambda: (finish(), self.statusBar().showMessage(title + " cancelled; finished work was kept."),
                                      self.refresh_all()))
        task.start()

    def cancel_task(self) -> None:
        if self.task:
            self.task.cancel()
            self.statusBar().showMessage("Cancelling…")

    # ------------------------------------------------------------------ UI construction
    def _build_ui(self) -> None:
        # left dock: drawings
        self.drawing_tree = QTreeWidget()
        self.drawing_tree.setHeaderLabels(["Drawing", "Pages"])
        self.drawing_tree.setAccessibleName("Drawings in project")
        self.drawing_tree.setMinimumWidth(230)
        self.drawing_tree.itemActivated.connect(self._drawing_activated)
        self.drawing_tree.itemDoubleClicked.connect(self._drawing_activated)
        dock = QDockWidget("Drawings", self)
        dock.setObjectName("dock_drawings")
        dock.setWidget(self.drawing_tree)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self.dock_drawings = dock

        # centre tabs
        self.tabs = QTabWidget()
        self.viewer = DrawingView()
        self.viewer.itemActivated.connect(self._overlay_clicked)
        self.viewer.pageStep.connect(self.step_page)
        self.viewer.boxDrawn.connect(self.teach_symbol)
        self.viewer.zoomChanged.connect(lambda z: self.zoom_label.setText(f"{z * 100:.0f}%"))
        draw = QWidget()
        dl = QVBoxLayout(draw)
        dl.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.prev_btn = QToolButton(); self.prev_btn.setText("◀"); self.prev_btn.setToolTip("Previous page (PgUp)")
        self.next_btn = QToolButton(); self.next_btn.setText("▶"); self.next_btn.setToolTip("Next page (PgDn)")
        self.prev_btn.clicked.connect(lambda: self.step_page(-1))
        self.next_btn.clicked.connect(lambda: self.step_page(1))
        self.page_spin = QSpinBox(); self.page_spin.setMinimum(1); self.page_spin.setAccessibleName("Page number")
        self.page_spin.valueChanged.connect(self.goto_page)
        self.page_label = QLabel("/ 1")
        bar.addWidget(self.prev_btn); bar.addWidget(self.page_spin); bar.addWidget(self.page_label); bar.addWidget(self.next_btn)
        for text, fn, tip in (("−", lambda: self.viewer.zoom_by(1 / 1.25), "Zoom out (-)"),
                              ("+", lambda: self.viewer.zoom_by(1.25), "Zoom in (+)"),
                              ("Fit", self.viewer.fit, "Fit page (0)"), ("100%", lambda: self._zoom_100(), "Actual pixels (1)")):
            b = QToolButton(); b.setText(text); b.setToolTip(tip); b.clicked.connect(fn); bar.addWidget(b)
        self.zoom_label = QLabel("100%")
        bar.addWidget(self.zoom_label)
        bar.addSpacing(12)
        # One compact "Layers" menu instead of nine checkboxes: the toolbar must fit a normal laptop screen.
        self.layer_boxes: dict[str, QAction] = {}
        layers_btn = QToolButton()
        layers_btn.setText("Layers ▾")
        layers_btn.setToolTip("Choose which detections are drawn on the sheet")
        layers_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        layer_menu = QMenu(layers_btn)
        for layer in ("readings", "symbols", "linework", "catalogue", "text_links", "geometry", "signals", "raster", "examples"):
            act = QAction(LAYER_LABELS[layer], layer_menu)
            act.setCheckable(True)
            act.setChecked(self.viewer.layer_visible(layer))
            swatch = QPixmap(12, 12)
            swatch.fill(QColor(LAYER_COLOURS[layer]))
            act.setIcon(QIcon(swatch))   # colour key that stays legible in light and dark themes
            act.toggled.connect(lambda on, l=layer: self.viewer.set_layer_visible(l, on))
            layer_menu.addAction(act)
            self.layer_boxes[layer] = act
        layers_btn.setMenu(layer_menu)
        bar.addWidget(layers_btn)
        self.teach_btn = QToolButton()
        self.teach_btn.setText("Teach symbol")
        self.teach_btn.setCheckable(True)
        self.teach_btn.setToolTip("Draw a box round ONE symbol (a valve, bubble, anything); the program then proposes "
                                  "look-alikes on this sheet for you to review. No training involved.")
        self.teach_btn.toggled.connect(self.viewer.set_teach_mode)
        bar.addWidget(self.teach_btn)
        bar.addStretch(1)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Find tag / text on this page and in project (Ctrl+F)")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setMinimumWidth(180)
        self.search_box.returnPressed.connect(self.run_search)
        bar.addWidget(self.search_box)
        dl.addLayout(bar)
        dl.addWidget(self.viewer, 1)
        self.tabs.addTab(draw, "Drawing")

        # registers
        reg = QWidget()
        rl = QVBoxLayout(reg)
        rb = QHBoxLayout()
        self.reg_group = QComboBox(); self.reg_group.addItems(list(REGISTER_GROUPS))
        self.reg_state = QComboBox(); self.reg_state.addItems(["All states", "PROPOSED", "ACCEPTED_AS_READING",
                                                               "EDITED_AND_ACCEPTED", "REJECTED", "IGNORED_REGION"])
        self.reg_scope = QComboBox(); self.reg_scope.addItems(["Whole project", "Open drawing"])
        self.reg_text = QLineEdit(); self.reg_text.setPlaceholderText("Filter by tag or text"); self.reg_text.setClearButtonEnabled(True)
        self.reg_text.returnPressed.connect(self._reg_reset)
        for w in (self.reg_group, self.reg_state, self.reg_scope):
            w.currentIndexChanged.connect(self._reg_reset)
        rb.addWidget(self.reg_group); rb.addWidget(self.reg_state); rb.addWidget(self.reg_scope); rb.addWidget(self.reg_text, 1)
        for text, fn in (("Find", self._reg_reset), ("◀ Prev", lambda: self._reg_page(-1)), ("Next ▶", lambda: self._reg_page(1))):
            b = QPushButton(text); b.clicked.connect(fn); rb.addWidget(b)
        rl.addLayout(rb)
        self.reg_table = _table(["Tag / text", "Class", "Page", "Drawing", "Rev", "Review", "Reviewed by", "Source file"])
        self.reg_table.itemSelectionChanged.connect(self._register_selected)
        rl.addWidget(self.reg_table, 1)
        rb2 = QHBoxLayout()
        self.reg_label = QLabel("")
        rb2.addWidget(self.reg_label, 1)
        for text, dec in (("Accept", "ACCEPTED_AS_READING"), ("Correct…", "EDITED_AND_ACCEPTED"), ("Reject", "REJECTED")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, d=dec: self.review_reading(d))
            rb2.addWidget(b)
        exp = QPushButton("Export this view (CSV)"); exp.clicked.connect(self.export_register_csv); rb2.addWidget(exp)
        rl.addLayout(rb2)
        self.tabs.addTab(reg, "Registers")

        # graph
        gw = QWidget()
        gl = QVBoxLayout(gw)
        gb = QHBoxLayout()
        graph_note = QLabel("Proposed connectivity for the open drawing, drawn at the items' page positions. "
                            "Squares: outline symbols • diamonds: valve glyphs • dots: line networks "
                            "• dashed red: through a tee junction.")
        graph_note.setWordWrap(True)
        gb.addWidget(graph_note, 1)
        gref = QPushButton("Refresh"); gref.clicked.connect(self.refresh_graph); gb.addWidget(gref)
        gl.addLayout(gb)
        self.graph = GraphView()
        self.graph.nodeClicked.connect(self._graph_node)
        gl.addWidget(self.graph, 1)
        self.path_table = _table(["From", "To", "Via valve glyphs", "Through tee", "Status"])
        self.path_table.setMaximumHeight(170)
        gl.addWidget(self.path_table)
        self.tabs.addTab(gw, "Graph")
        self.wp123_tab = Wp123Tab(self); self.tabs.addTab(self.wp123_tab, "WP-01–03 proposals")

        self.sheet_tab = SheetInfoTab(self); self.tabs.addTab(self.sheet_tab, "Sheet info")
        self.quality_tab = QualityTab(self); self.tabs.addTab(self.quality_tab, "Quality")
        self.revision_tab = RevisionTab(self); self.tabs.addTab(self.revision_tab, "Revisions")
        self.batch_tab = BatchTab(self); self.tabs.addTab(self.batch_tab, "Batch import")
        self.library_tab = LibraryTab(self); self.tabs.addTab(self.library_tab, "Libraries")
        self.report_tab = ReportTab(self); self.tabs.addTab(self.report_tab, "Reports")
        self.audit_tab = AuditTab(self); self.tabs.addTab(self.audit_tab, "Audit")
        self.setCentralWidget(self.tabs)

        # right dock: findings + details
        side = QWidget()
        sl = QVBoxLayout(side)
        fr = QHBoxLayout()
        self.layer_combo = QComboBox()
        for layer in F.LAYERS:
            self.layer_combo.addItem(F.LAYER_TITLES[layer], layer)
        self.layer_combo.currentIndexChanged.connect(self.show_findings)
        self.state_combo = QComboBox()
        self.state_combo.addItems(["All", "Unreviewed", "Reviewed"])
        self.state_combo.currentIndexChanged.connect(self.show_findings)
        fr.addWidget(self.layer_combo, 1); fr.addWidget(self.state_combo)
        sl.addLayout(fr)
        self.finding_table = _table(["Finding", "Page", "State"])
        self.finding_table.itemSelectionChanged.connect(self._finding_selected)
        sl.addWidget(self.finding_table, 2)
        self.review_btn = QPushButton("Review selected…  (Ctrl+Return)")
        self.review_btn.clicked.connect(self.review_finding)
        sl.addWidget(self.review_btn)
        self.details = QPlainTextEdit(); self.details.setReadOnly(True)
        self.details.setAccessibleName("Details of selection")
        sl.addWidget(self.details, 1)
        d2 = QDockWidget("Findings and details", self)
        d2.setObjectName("dock_findings")
        d2.setWidget(side)
        d2.setMinimumWidth(340)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, d2)
        self.dock_findings = d2

        self.progress = QProgressBar(); self.progress.setMaximumWidth(220); self.progress.setVisible(False)
        self.cancel_btn = QPushButton("Cancel"); self.cancel_btn.setVisible(False); self.cancel_btn.clicked.connect(self.cancel_task)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addPermanentWidget(self.cancel_btn)

    def _build_menus(self) -> None:
        def act(menu, text, fn, shortcut=None):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.triggered.connect(lambda _=False: fn())
            menu.addAction(a)
            self._actions.append(a)
            return a
        self._actions: list[QAction] = []
        m = self.menuBar().addMenu("&File")
        act(m, "&New project…", self.new_project, "Ctrl+N")
        act(m, "&Open project…", lambda: self.open_project(), "Ctrl+O")
        self.recent_menu = m.addMenu("Open &recent")
        m.addSeparator()
        self.import_act = act(m, "&Import PDF(s)…", self.import_pdfs, "Ctrl+I")
        self.import_dir_act = act(m, "Import &folder…", self.import_folder, "Ctrl+Shift+I")
        m.addSeparator()
        act(m, "Export open drawing as &AI package…", self.export_ai_package, "Ctrl+Alt+E")
        act(m, "&Export open drawing as files…", lambda: self.export_drawing_files(False), "Ctrl+E")
        act(m, "Export &all drawings as files…", lambda: self.export_drawing_files(True), "Ctrl+Shift+E")
        m.addSeparator()
        act(m, "&Back up project…", self.backup_project, "Ctrl+B")
        act(m, "E&xit", self.close, "Ctrl+Q")
        m = self.menuBar().addMenu("&Drawing")
        self.analyze_act = act(m, "&Analyse open drawing", self.analyze, "F5")
        self.register_act = act(m, "&Register drawing (number, revision)…", self.register_drawing, "Ctrl+R")
        m.addSeparator()
        act(m, "Next page", lambda: self.step_page(1), "Ctrl+Right")
        act(m, "Previous page", lambda: self.step_page(-1), "Ctrl+Left")
        act(m, "Fit page", self.viewer.fit, "Ctrl+0")
        act(m, "Find…", lambda: (self.tabs.setCurrentIndex(0), self.search_box.setFocus()), "Ctrl+F")
        act(m, "Review selected finding…", self.review_finding, "Ctrl+Return")
        m = self.menuBar().addMenu("&Tools")
        act(m, "Reviewer &name…", self.set_reviewer)
        om = m.addMenu("&OCR engine for scanned pages")
        grp = QActionGroup(self)
        from ..formats.ocr_source import available_engines
        installed = set(available_engines())
        for label, val in (("Automatic (Tesseract if installed, else RapidOCR)", "auto"), ("RapidOCR (bundled)", "rapidocr"),
                           ("Tesseract", "tesseract"), ("Off (refuse scanned pages)", "off")):
            missing = val in ("tesseract", "rapidocr") and val not in installed
            a = QAction(label + (" \u2014 not installed" if missing else ""), self, checkable=True)
            a.setEnabled(not missing)
            a.setChecked(self.ocr_engine() == val)
            a.triggered.connect(lambda _=False, v=val: self.settings.setValue("ocr_engine", v))
            grp.addAction(a)
            om.addAction(a)
        act(m, "&Reconcile sheets (off-page matches, same-tag proposals)…", self.reconcile_sheets)
        dm = m.addMenu("Analysis &depth (CPU time)")
        dgrp = QActionGroup(self)
        for label, val in (("Quick: valves only, coarse size search, no re-reads", "quick"), ("Standard: valves, actuators, instruments, one re-read", "standard"),
                           ("Deep: adds equipment, finer size search, more re-reads (slowest)", "deep")):
            a = QAction(label, self, checkable=True)
            a.setChecked(self.analysis_depth() == val)
            a.triggered.connect(lambda _=False, v=val: self.settings.setValue("analysis_depth", v))
            dgrp.addAction(a)
            dm.addAction(a)
        act(m, "&Verify audit chain", lambda: (self.tabs.setCurrentWidget(self.audit_tab), self.audit_tab.verify()))
        m = self.menuBar().addMenu("&R5 update (proposed)")
        from ..engineering import r5_features
        self._r5_actions = {}
        for key, label in (("DEXPI", "Proposed DEXPI export (off by default)"), ("PAGE_FRAME", "Record PDF page metadata and block unverified lengths"),
                           ("REVIEW_LEDGER", "Connection review ledger (ambiguous / blocked candidates)")):
            a = QAction(label, self, checkable=True)
            a.setChecked(r5_features.mode(key) == r5_features.ON)
            a.triggered.connect(lambda checked=False, k=key: self.toggle_r5(k, checked))
            m.addAction(a)
            self._r5_actions[key] = a
        m.addSeparator()
        act(m, "Export open drawing as proposed &DEXPI…", self.export_dexpi_gui)
        act(m, "Show connection review &ledger…", self.show_review_ledger)
        m = self.menuBar().addMenu("&Learned detector (TR1, proposed)")
        from ..tr1 import flags as tr1_flags
        self._tr1_actions = {}
        for key, label in (("PIDLAB_SYMBOL_FRCNN_TR1", "Learned symbol detector (proposals only; needs the optional torch component)"),
                           ("PIDLAB_SYMBOL_CATALOGUE_TR1", "Symbol catalogue v1.0.0 for reviews"),
                           ("PIDLAB_CORRECTION_QUEUE_TR1", "Record my confirm / reject / edit decisions as training data"),
                           ("PIDLAB_TRAINING_BATCH_TR1", "Allow training batches from final reviews"),
                           ("PIDLAB_TAG_ASSIGN_R3", "Propose which tag belongs to which detection (abstains when unsure)"),
                           ("PIDLAB_GRAPH_CONSERVATIVE_R3", "Show conservative join hints between detections (hints, not connections)"),
                           ("PIDLAB_FINE_CLASS_R3", "Propose a subtype id for each detection (names unverified)")):
            a = QAction(label, self, checkable=True)
            a.setChecked(tr1_flags.enabled(key))
            a.triggered.connect(lambda checked=False, k=key: self.toggle_tr1(k, checked))
            m.addAction(a)
            self._tr1_actions[key] = a
        merge_menu = m.addMenu("Tile-seam merge policy")
        self._tr1_merge_actions = {}
        mgrp = QActionGroup(self)
        for val, label in (("r1_drop_inner_edge", "R1 rule (default): drop boxes touching an inner tile edge"), ("edge_safe", "Edge-safe: keep and stitch large objects across seams"),
                           ("edge_safe+coarse", "Edge-safe plus a coarse pass for very large objects (slower)")):
            a = QAction(label, self, checkable=True)
            a.setChecked(tr1_flags.choice("PIDLAB_TILE_MERGE_R3") == val)
            a.triggered.connect(lambda checked=False, v=val: self.set_tr1_merge(v))
            mgrp.addAction(a)
            merge_menu.addAction(a)
            self._tr1_merge_actions[val] = a
        m.addSeparator()
        act(m, "Open learned detections for this &page…", self.open_tr1_dialog)
        act(m, "Detector &status…", self.show_tr1_status)
        m = self.menuBar().addMenu("&Help")
        act(m, "What this software does and does not do", self.show_limits, "F1")
        act(m, "&About", self.show_about)

    def _set_enabled(self, on: bool) -> None:
        for w in (self.tabs, self.dock_drawings, self.dock_findings):
            w.setEnabled(on)
        for a in (self.import_act, self.import_dir_act, self.analyze_act, self.register_act):
            a.setEnabled(on)

    # ------------------------------------------------------------------ project
    def _recent(self) -> list[str]:
        return [p for p in (self.settings.value("recent", [], list) or []) if isinstance(p, str)]

    def _remember(self, path: str) -> None:
        recent = [path] + [p for p in self._recent() if p != path]
        self.settings.setValue("recent", recent[:8])
        self.settings.setValue("last_project", path)
        self.recent_menu.clear()
        for p in recent[:8]:
            a = QAction(p, self)
            a.triggered.connect(lambda _=False, q=p: self.open_project(q))
            self.recent_menu.addAction(a)

    def default_project_dir(self) -> Path:
        import os
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "PIDReader" / "projects"
        base.mkdir(parents=True, exist_ok=True)
        return base

    def new_project(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "New project database", str(self.default_project_dir() / "project.sqlite"),
                                              "P&ID Reader project (*.sqlite)")
        if path:
            if Path(path).exists():
                QMessageBox.warning(self, "Already exists", "Choose a new file name or use Open project.")
                return
            self.open_project(path)

    def open_project(self, path: str | None = None) -> None:
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open project", str(self.default_project_dir()),
                                                  "P&ID Reader project (*.sqlite)")
        if not path:
            return
        if self.task:
            QMessageBox.information(self, "Busy", "Wait for or cancel the running task first.")
            return
        try:
            new = ProjectStore(path)
        except Exception as exc:
            QMessageBox.critical(self, "Cannot open project", f"{type(exc).__name__}: {exc}")
            return
        if self.db:
            self.db.close()
        self.db, self.db_path = new, str(path)
        self.current_extraction_id = ""
        self.current_pdf = None
        self.viewer.clear_page()
        self.findings = {}
        self.setWindowTitle(f"P&ID Reader — {Path(path).name}")
        self._remember(self.db_path)
        self._set_enabled(True)
        if "OneDrive" in self.db_path or "Dropbox" in self.db_path:
            self.statusBar().showMessage("Warning: this project lives in a synced folder; frequent database writes there can "
                                         "conflict with sync. Local app-data is safer.", 20000)
        self.refresh_all()
        count = self.db.db.execute("SELECT count(*) FROM extraction").fetchone()[0]
        self.statusBar().showMessage(
            f"Project opened: {count} drawing(s). Double-click a drawing on the left to view it; F5 analyses it; "
            "everything shown is an unverified proposal." if count else
            "New project. Import PDFs with Ctrl+I (File menu).", 20000)
        if self.db.migration_backup:
            self.info(f"Project upgraded; previous copy kept at {self.db.migration_backup}")

    def set_reviewer(self) -> None:
        name, ok = QInputDialog.getText(self, "Reviewer name", "Name recorded on review decisions:",
                                        text=self.settings.value("reviewer", "", str))
        if ok and name.strip():
            self.settings.setValue("reviewer", name.strip())

    # ------------------------------------------------------------------ drawings
    def refresh_drawings(self) -> None:
        self.drawing_tree.clear()
        rows = self.db.db.execute(
            """SELECT e.extraction_id, d.source_name, d.page_count, d.source_bytes IS NOT NULL AS has_pdf,
               (SELECT r.drawing_no FROM drawing_registration r WHERE r.extraction_id=e.extraction_id ORDER BY r.rowid DESC LIMIT 1) dno,
               (SELECT r.revision_label FROM drawing_registration r WHERE r.extraction_id=e.extraction_id ORDER BY r.rowid DESC LIMIT 1) rev,
               (SELECT r.facility FROM drawing_registration r WHERE r.extraction_id=e.extraction_id ORDER BY r.rowid DESC LIMIT 1) fac,
               (SELECT r.area FROM drawing_registration r WHERE r.extraction_id=e.extraction_id ORDER BY r.rowid DESC LIMIT 1) area
               FROM extraction e JOIN document_revision d ON d.sha256=e.document_sha256
               ORDER BY fac, area, dno, e.imported_utc""").fetchall()
        groups: dict[str, QTreeWidgetItem] = {}
        self.drawing_items = {}
        for r in rows:
            key = f"{r['fac']} / {r['area']}" if r["fac"] else "Not yet registered"
            if key not in groups:
                groups[key] = QTreeWidgetItem(self.drawing_tree, [key, ""])
                groups[key].setExpanded(True)
            label = f"{r['dno']} rev {r['rev']}" if r["dno"] else r["source_name"]
            it = QTreeWidgetItem(groups[key], [label, str(r["page_count"])])
            it.setData(0, Qt.ItemDataRole.UserRole, r["extraction_id"])
            it.setToolTip(0, r["source_name"] + ("" if r["has_pdf"] else "  (PDF bytes not stored)"))
            self.drawing_items[r["extraction_id"]] = label
            if r["extraction_id"] == self.current_extraction_id:
                self.drawing_tree.setCurrentItem(it)
        self.drawing_tree.resizeColumnToContents(0)

    def _drawing_activated(self, item, _col=0) -> None:
        eid = item.data(0, Qt.ItemDataRole.UserRole)
        if eid:
            self.open_drawing(eid)

    def open_drawing(self, extraction_id: str, page: int = 1) -> None:
        try:
            result = self.db.export_extraction(extraction_id)
            pdf = self.db.get_source_pdf(result["document"]["sha256"])
        except Exception as exc:
            QMessageBox.warning(self, "Cannot open drawing", f"{type(exc).__name__}: {exc}")
            return
        self.current_extraction_id, self.current_result, self.current_pdf = extraction_id, result, pdf
        self.page_count = result["document"]["page_count"]
        self.page_spin.blockSignals(True)
        self.page_spin.setMaximum(self.page_count)
        self.page_spin.blockSignals(False)
        self.page_label.setText(f"/ {self.page_count}")
        self.findings = {layer: F.list_findings(self.db, extraction_id, layer, limit=2000) for layer in F.LAYERS}
        self.wp123_tab.reset()
        self.tabs.setCurrentIndex(0)
        self.goto_page(page)
        self.show_findings()
        self.refresh_graph()
        self.refresh_sheet_info()
        try:
            self.quality_tab.refresh()
        except Exception as exc:
            self.info(f"Quality view unavailable: {type(exc).__name__}: {exc}")
        unread = [p["page"] for p in result["pages"] if p["read_status"] != "READ"]
        msg = f"Opened {self.drawing_items.get(extraction_id, '')}: {result['summary']['object_count']} readings."
        if unread:
            msg += f" Pages not read: {unread} (image-only; enable OCR or check Tools → OCR engine)."
        self.info(msg)

    def refresh_sheet_info(self) -> None:
        if not self.current_result:
            return
        try:
            from ..engineering.checks import consistency_checks, instrument_loops
            from ..engineering.sheet_fields import sheet_fields
            ids = F.latest_analysis_ids(self.db, self.current_extraction_id)
            words = self.db.list_ocr_words(ids["ocr"], limit=2000) if "ocr" in ids else []
            fields = sheet_fields(self.current_result, words)
            symbols = [f["detail"] for f in self.findings.get("symbols", [])]
            self.sheet_tab.show(self.drawing_items.get(self.current_extraction_id, ""), fields,
                                instrument_loops(self.current_result), consistency_checks(self.current_result, symbols, fields))
        except Exception as exc:
            self.info(f"Sheet information unavailable: {type(exc).__name__}: {exc}")

    def show_position(self, page: int, x: float, y: float) -> None:
        """Jump the drawing view to a normalised position (used by the Sheet info tables)."""
        self.tabs.setCurrentIndex(0)
        if page != self.page:
            self.goto_page(page)
        self.viewer.highlight({"x0": x, "y0": y, "x1": min(1.0, x + 0.02), "y1": min(1.0, y + 0.012)})

    def goto_page(self, page: int) -> None:
        if not self.current_extraction_id:
            return
        page = max(1, min(self.page_count, int(page)))
        self.page = page
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(page)
        self.page_spin.blockSignals(False)
        self.viewer.load_page(self.current_pdf, page)
        self._apply_overlays()
        self.prev_btn.setEnabled(page > 1)
        self.next_btn.setEnabled(page < self.page_count)

    def step_page(self, delta: int) -> None:
        self.goto_page(self.page + delta)

    def _zoom_100(self) -> None:
        self.viewer.resetTransform()
        self.viewer.zoomChanged.emit(1.0)

    def _apply_overlays(self) -> None:
        if not self.current_result:
            return
        page = self.page
        readings = []
        for o in self.current_result["objects"]:
            if o["page"] == page and o["class"] != "LINE" or (o["page"] == page and o["text"]):
                readings.append({"id": o["id"], "bbox": o["bbox"], "tip": f"{o['class']}: {o['text']}"})
        self.viewer.set_overlay("readings", readings)
        for layer in F.LAYERS:
            items = [{"id": f["id"], "bbox": f["bbox"], "tip": f"{f['label']} — {f['state'].replace('_', ' ').lower()}"}
                     for f in self.findings.get(layer, []) if f["page"] == page and f["bbox"]]
            self.viewer.set_overlay(layer, items)
        if getattr(self, "tr1_dialog", None) is not None:
            self.tr1_dialog.load_saved()
        if getattr(self, "wp123_tab", None) is not None:
            self.wp123_tab._refresh_overlay()

    def _overlay_clicked(self, layer: str, item_id: str) -> None:
        if layer == "readings":
            o = next((x for x in self.current_result["objects"] if x["id"] == item_id), None)
            if o:
                self.details.setPlainText(json.dumps({"reading": o, "note": "Unverified reading from the drawing."}, indent=2))
            return
        if layer == "wp123":
            self.wp123_tab.select_id(item_id)
            return
        idx = self.layer_combo.findData(layer)
        self.layer_combo.setCurrentIndex(idx)
        for r, f in enumerate(self.finding_rows):
            if f["id"] == item_id:
                self.finding_table.selectRow(r)
                return
        self.state_combo.setCurrentIndex(0)
        self.show_findings()
        for r, f in enumerate(self.finding_rows):
            if f["id"] == item_id:
                self.finding_table.selectRow(r)
                return

    def teach_symbol(self, bbox: dict) -> None:
        """A box was drawn in teach mode: ask what it is, search for look-alikes in the background, show them."""
        if not self.current_extraction_id:
            return
        actor = self.reviewer()
        self.teach_btn.setChecked(False)
        if not actor:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Teach symbol")
        form = QFormLayout(dlg)
        label = QLineEdit()
        label.setPlaceholderText("e.g. Gate valve, Block valve, Pressure gauge")
        hint = QComboBox()
        hint.addItems(["VALVE", "INSTRUMENT", "EQUIPMENT", "FITTING", "ANNOTATION", "OTHER"])
        thr = QSpinBox()
        thr.setRange(40, 98)
        thr.setValue(72)
        thr.setSuffix(" % similarity")
        form.addRow("What is this symbol?", label)
        form.addRow("Kind", hint)
        form.addRow("Find matches at least", thr)
        form.addRow(QLabel("The search covers this page at about \u00b115 % size and all four rotations."))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted or not label.text().strip():
            return
        db_path, eid, page = self.db_path, self.current_extraction_id, self.page
        name, kind, threshold = label.text().strip(), hint.currentText(), thr.value() / 100.0

        def job(report, cancelled):
            from ..engineering.examples import teach_symbol
            with ProjectStore(db_path) as db:
                report(0.1, "Searching the page for look-alikes")
                aid, result = teach_symbol(db, eid, page=page, bbox=bbox, label=name, class_hint=kind, actor=actor,
                                           threshold=threshold, cancel=CallbackCancelToken(cancelled))
                return len(result["matches"])

        def done(n):
            self.findings["examples"] = F.list_findings(self.db, eid, "examples", limit=2000)
            self.layer_boxes["examples"].setChecked(True)
            self.layer_combo.setCurrentIndex(self.layer_combo.findData("examples"))
            self._apply_overlays()
            self.show_findings()
            self.info(f"Taught \u201c{name}\u201d: {n} look-alike(s) proposed on page {page}. Review them in the Findings panel "
                      "(accept the right ones, reject the rest).")

        self.run_task("Searching for look-alikes", job, done)

    def run_search(self) -> None:
        q = self.search_box.text().strip()
        if not q:
            self.viewer.set_overlay("search", [])
            return
        hits = []
        if self.current_result:
            hits = [{"id": o["id"], "bbox": o["bbox"], "tip": o["text"]} for o in self.current_result["objects"]
                    if o["page"] == self.page and q.lower() in o["text"].lower()]
        self.viewer.set_overlay("search", hits)
        self.viewer.set_layer_visible("search", True)
        if hits:
            self.viewer.highlight(hits[0]["bbox"])
        self.reg_text.setText(q)
        self.reg_scope.setCurrentIndex(0)
        self._reg_reset()
        self.statusBar().showMessage(f"{len(hits)} match(es) on this page; project-wide results in Registers.", 8000)

    # ------------------------------------------------------------------ import / analysis
    def import_pdfs(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(self, "Import P&ID PDFs", "", "PDF files (*.pdf)")
        if names:
            self._import([Path(n) for n in names])

    def import_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Import all PDFs in folder")
        if d:
            files = sorted(Path(d).glob("*.pdf"))
            if not files:
                QMessageBox.information(self, "No PDFs", "That folder has no PDF files.")
                return
            self._import(files)

    def _import(self, paths: list[Path]) -> None:
        db_path, ocr = self.db_path, self.ocr_engine()

        def job(report, cancelled):
            from ..api import ReadParams
            from ..engineering.isolation import read_pid_isolated
            ids = []
            with ProjectStore(db_path) as db:
                for i, p in enumerate(paths):
                    if cancelled():
                        break
                    report(i / len(paths), f"Reading {p.name} ({i + 1}/{len(paths)})")
                    data = p.read_bytes()
                    try:
                        result = read_pid_isolated(data, ReadParams(), filename=p.name, ocr_engine=ocr,
                                                   should_cancel=cancelled, timeout_s=600)
                    except Exception as exc:
                        if cancelled():
                            break
                        ids.append((None, p.name, f"{getattr(exc, 'code', type(exc).__name__)}: {exc}"))
                        continue
                    ids.append((db.add_extraction(result, source_pdf_bytes=data), p.name, ""))
            return ids

        def done(ids):
            ok = [i for i in ids if i[0]]
            bad = [i for i in ids if not i[0]]
            self.refresh_all()
            if ok:
                self.open_drawing(ok[0][0])
            if bad:
                QMessageBox.warning(self, "Some files were not imported",
                                    "\n".join(f"{n}: {why}" for _i, n, why in bad[:12]))
            self.info(f"Imported {len(ok)} drawing(s); {len(bad)} refused or failed. Run Analyse (F5) to find symbols, valves and links.")

        self.run_task("Importing PDFs", job, done)

    def analyze(self) -> None:
        eid = self.current_extraction_id
        if not eid:
            QMessageBox.information(self, "No drawing open", "Import or open a drawing first.")
            return
        db_path, ocr = self.db_path, self.ocr_engine()
        catalogue = self.settings.value("catalogue_id", None, str) or None
        depth = self.analysis_depth()

        def job(report, cancelled):
            from ..engineering.pipeline import analyze_drawing
            with ProjectStore(db_path) as db:
                return analyze_drawing(db, eid, ocr_engine=None if ocr == "off" else ocr, catalogue_id=catalogue, preset=depth,
                                       library_symbols=True, progress=lambda s, f, m: report(f, m), cancel=CallbackCancelToken(cancelled))

        def done(out):
            lines = [f"{k}: {v['status']} {v['detail']}" for k, v in out["stages"].items()]
            h = out["health"]
            head = f"Drawing status: {h['drawing_status']}" + (f" (first blocker: {h['primary_blocker']})" if h["primary_blocker"] else "")
            extra = [f"{o['stage_id']}: {o['status']} {o['error_summary'] or o['diagnostics'].get('detail', '')}".strip()
                     for o in out["outcomes"] if o["stage_id"] in ("classify", "symbol_library", "engineering_graph", "control_loops", "doc_text")]
            self.details.setPlainText(head + "\nAnalysis finished (all results are unreviewed proposals):\n" + "\n".join(lines + extra))
            self.open_drawing(eid, self.page)

        self.run_task("Analysing drawing", job, done)

    def reconcile_sheets(self) -> None:
        if not self.db:
            return
        db_path = self.db_path

        def job(report, cancelled):
            from ..engineering.crosssheet import reconcile_project
            with ProjectStore(db_path) as db:
                return reconcile_project(db)

        def done(res):
            lines = [f"Sheets compared: {len(res['sheets'])}; off-page connectors read: {len(res['connectors'])}",
                     f"Match candidates (two independent observations each): {len(res['candidates'])}",
                     f"Conflicts: {len(res['conflicts'])}; insufficient evidence: {len(res['insufficient'])}",
                     f"Same-tag identity proposals: {len(res['identity']['proposals'])}; tag-only, NOT merged: {len(res['identity']['tag_only_not_merged'])}",
                     "Everything here is a proposal for review; a shared tag or line name alone never merges anything."]
            self.details.setPlainText("\n".join(lines))
            self.info("Sheet reconciliation finished (proposals only).")

        self.run_task("Reconciling sheets", job, done)

    def analysis_depth(self) -> str:
        v = self.settings.value("analysis_depth", "standard", str)
        return v if v in ("quick", "standard", "deep") else "standard"

    def export_ai_package(self) -> None:
        """AI-ready engineering package for the open drawing, into a sub-folder of a folder chosen now (never automatic)."""
        eid = self.current_extraction_id
        if not eid or not self.db:
            QMessageBox.information(self, "No drawing open", "Open and analyse a drawing first.")
            return
        start = self.settings.value("export_folder", "", str) or ""
        folder = QFileDialog.getExistingDirectory(self, "Choose the folder for the AI-ready package", start)
        if not folder:
            return
        self.settings_set("export_folder", folder)
        try:
            from ..engineering.intelligence import export_package
            out = export_package(self.db, eid, folder)
            self.info(f"AI package saved: {out}")
            QMessageBox.information(self, "AI package saved", f"{out}\n\nNothing was uploaded. It describes a drawing revision, not the constructed plant.")
        except Exception as exc:
            QMessageBox.warning(self, "AI package not saved", f"{type(exc).__name__}: {exc}")

    def toggle_r5(self, key: str, on: bool) -> None:
        from ..engineering import r5_features
        import os
        try:
            r5_features.set_mode(key, "ON" if on else "OFF")
        except Exception as exc:
            QMessageBox.warning(self, "Setting not saved", f"{type(exc).__name__}: {exc}")
            return
        if os.environ.get("PID_R5_" + key):
            QMessageBox.information(self, "Environment overrides", f"PID_R5_{key} is set in the environment and wins over this setting.")
        self.info(f"R5 {key}: {r5_features.mode(key)} (applies to the next analysis / export; recorded analyses are not changed)")

    def toggle_tr1(self, key: str, on: bool) -> None:
        from ..tr1 import flags as tr1_flags
        try:
            tr1_flags.set_flag(key, on)
        except Exception as exc:
            QMessageBox.warning(self, "Setting not saved", f"{type(exc).__name__}: {exc}")
            return
        if tr1_flags.source(key) == "environment":
            QMessageBox.information(self, "Environment overrides", f"{key} is set in the environment and wins over this setting.")
        self._tr1_actions[key].setChecked(tr1_flags.enabled(key))
        self.info(f"TR1 {key}: {'on' if tr1_flags.enabled(key) else 'off'} (the normal analysis is not affected either way)")
        dlg = getattr(self, "tr1_dialog", None)
        if dlg is not None:
            dlg.refresh_status()

    def set_tr1_merge(self, value: str) -> None:
        from ..tr1 import flags as tr1_flags
        try:
            tr1_flags.set_choice("PIDLAB_TILE_MERGE_R3", value)
        except Exception as exc:
            QMessageBox.warning(self, "Setting not saved", f"{type(exc).__name__}: {exc}")
            return
        if tr1_flags.source("PIDLAB_TILE_MERGE_R3") == "environment":
            QMessageBox.information(self, "Environment overrides", "PIDLAB_TILE_MERGE_R3 is set in the environment and wins over this setting.")
        self.info(f"TR1 tile-seam merge policy: {tr1_flags.choice('PIDLAB_TILE_MERGE_R3')} (applies to the next detector run)")

    def show_tr1_status(self) -> None:
        from ..tr1 import detector, flags as tr1_flags
        st = detector.status()
        lines = [f"{n}: {'on' if v['on'] else 'off'} ({v['source']})" for n, v in tr1_flags.inventory()["switches"].items()]
        lines += ["", st["message"], f"State: {st['state']}", f"Model card: {st.get('card') or '-'}", f"Weights: {st.get('weights') or '-'}",
                  f"Torch component: {st.get('python') or '-'}", st["fallback"]]
        QMessageBox.information(self, "Learned detector status", chr(10).join(lines))

    def open_tr1_dialog(self) -> None:
        from ..tr1 import flags as tr1_flags
        if not tr1_flags.enabled("PIDLAB_SYMBOL_FRCNN_TR1"):
            QMessageBox.information(self, "Switched off", "The learned detector is switched off. Tick it in the Learned detector menu first.")
            return
        if not self.current_extraction_id:
            QMessageBox.information(self, "No drawing open", "Open a drawing first.")
            return
        from .tr1_dialog import Tr1Dialog
        dlg = getattr(self, "tr1_dialog", None)
        if dlg is None:
            dlg = self.tr1_dialog = Tr1Dialog(self)
        dlg.refresh_status()
        dlg.load_saved()
        dlg.show()
        dlg.raise_()

    def export_dexpi_gui(self) -> None:
        """Proposed DEXPI export of the open drawing (off unless switched on). Class mapping comes from human-reviewed readings only."""
        from ..engineering import r5_features
        eid = self.current_extraction_id
        if not eid or not self.db:
            QMessageBox.information(self, "No drawing open", "Open and analyse a drawing first.")
            return
        if r5_features.mode("DEXPI") == r5_features.OFF:
            QMessageBox.information(self, "Switched off", "The proposed DEXPI export is switched off. Tick it in the R5 update menu first.")
            return
        start = self.settings.value("export_folder", "", str) or ""
        folder = QFileDialog.getExistingDirectory(self, "Choose the folder for the proposed DEXPI files", start)
        if not folder:
            return
        self.settings_set("export_folder", folder)
        try:
            from ..engineering.dexpi_proposed import export_dexpi_proposed
            from ..engineering.intelligence import build_snapshot
            res = export_dexpi_proposed(build_snapshot(self.db, eid), folder)
            counts = ", ".join(f"{k}: {v}" for k, v in sorted(res["fate_counts"].items()))
            chk = ", ".join(f"{k}: {v}" for k, v in res["checks"].items() if k != "conformance")
            self.info(f"Proposed DEXPI saved: {res['xml']}")
            QMessageBox.information(self, "Proposed DEXPI saved", f"{res['xml']}\n\nWhat happened to each drawing object: {counts}\nChecks (separate): {chk}\n\n"
                                    "This is a proposal from unverified drawing readings. It is NOT a DEXPI conformance claim; unreviewed classes stay in the sidecar file.")
        except Exception as exc:
            QMessageBox.warning(self, "DEXPI not saved", f"{type(exc).__name__}: {exc}")

    def show_review_ledger(self) -> None:
        from ..engineering import r5_features
        eid = self.current_extraction_id
        if not eid or not self.db:
            QMessageBox.information(self, "No drawing open", "Open and analyse a drawing first.")
            return
        if r5_features.mode("REVIEW_LEDGER") == r5_features.OFF:
            QMessageBox.information(self, "Switched off", "The connection review ledger is switched off. Tick it in the R5 update menu first.")
            return
        try:
            from ..engineering.connection_review import ledger_for_run
            led = ledger_for_run(self.db, eid)
        except Exception as exc:
            QMessageBox.warning(self, "No ledger", f"{type(exc).__name__}: {exc}")
            return
        from PySide6.QtWidgets import QPlainTextEdit
        dlg = QDialog(self)
        dlg.setWindowTitle("Connection review ledger (candidates only)")
        lay = QVBoxLayout(dlg)
        note = QLabel(led["note"])
        note.setWordWrap(True)
        lay.addWidget(note)
        box = QPlainTextEdit()
        box.setReadOnly(True)
        box.setPlainText("\n\n".join(f"{e['review_id']}  [{e['state']}]  {e['candidate_kind']}  page {e.get('page')}\n  ports: {', '.join(e['ports'])}\n  strokes: {', '.join(e['stroke_ids'][:8])}\n  why: {'; '.join(e['reasons'])}"
                                       for e in led["entries"]) or "No ambiguous or blocked candidates were found in the latest run.")
        lay.addWidget(box)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        dlg.resize(760, 520)
        dlg.exec()

    def register_drawing(self) -> None:
        eid = self.current_extraction_id
        if not eid:
            QMessageBox.information(self, "No drawing open", "Open a drawing first.")
            return
        actor = self.reviewer()
        if not actor:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Register drawing")
        form = QFormLayout(dlg)
        fields = {k: QLineEdit() for k in ("drawing_no", "revision_label", "facility", "area")}
        form.addRow("Drawing number (as printed)", fields["drawing_no"])
        form.addRow("Revision (as printed)", fields["revision_label"])
        form.addRow("Facility", fields["facility"])
        form.addRow("Area / unit", fields["area"])
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.db.register_drawing(eid, actor=actor, reason="Catalogue entry from GUI",
                                     **{k: v.text().strip() for k, v in fields.items()})
        except Exception as exc:
            QMessageBox.warning(self, "Not registered", str(exc))
            return
        self.refresh_all()
        self.info("Drawing registered. Registration is a catalogue entry, not proof it is the current or as-built revision.")

    # ------------------------------------------------------------------ findings
    def show_findings(self) -> None:
        layer = self.layer_combo.currentData()
        items = list(self.findings.get(layer, []))
        mode = self.state_combo.currentText()
        if mode == "Unreviewed":
            items = [f for f in items if f["state"] == "PROPOSED"]
        elif mode == "Reviewed":
            items = [f for f in items if f["state"] != "PROPOSED"]
        self.finding_rows = items
        t = self.finding_table
        t.setRowCount(len(items))
        for r, f in enumerate(items):
            for c, v in enumerate((f["label"], f["page"], f["state"].replace("_", " ").title())):
                it = QTableWidgetItem(str(v))
                if c == 2:
                    it.setForeground(QColor(STATE_COLOURS.get(f["state"], "#2e7d32")))
                t.setItem(r, c, it)
        t.resizeColumnsToContents()
        total = len(self.findings.get(layer, []))
        self.layer_combo.setItemText(self.layer_combo.currentIndex(),
                                     f"{F.LAYER_TITLES[layer]} ({total})")

    def _selected_finding(self) -> dict | None:
        rows = self.finding_table.selectionModel().selectedRows() if self.finding_table.selectionModel() else []
        if rows and 0 <= rows[0].row() < len(self.finding_rows):
            return self.finding_rows[rows[0].row()]
        return None

    def _finding_selected(self) -> None:
        f = self._selected_finding()
        if not f:
            return
        self.details.setPlainText(json.dumps({"layer": f["layer"], "state": f["state"], "proposal": f["detail"],
                                              "note": "Proposal read from the drawing; not verified."}, indent=2, default=str))
        if f["page"] != self.page:
            self.goto_page(f["page"])
        self.viewer.highlight(f["bbox"])

    def review_finding(self) -> None:
        f = self._selected_finding()
        if not f:
            QMessageBox.information(self, "Nothing selected", "Select a finding first.")
            return
        actor = self.reviewer()
        if not actor:
            return
        options = [o["text_candidate"] for o in f["detail"].get("options", [])] if f["layer"] == "text_links" else None
        dlg = ReviewDialog(self, f"Review: {f['label']}", F.DECISIONS[f["layer"]], text_options=options)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        decision, reason, text = dlg.values()
        if not reason and decision != "ACCEPTED_AS_READING":
            reason = "Reviewed in desktop application"
        if len(reason) < 5:
            reason = "Checked against printed drawing"
        try:
            F.review_finding(self.db, f["layer"], f["id"], actor=actor, decision=decision, reason=reason,
                             selected_text=text if f["layer"] == "text_links" and decision in
                             ("ACCEPTED_AS_READING", "EDITED_AND_ACCEPTED") else None)
        except Exception as exc:
            QMessageBox.warning(self, "Review refused", str(exc))
            return
        self.findings[f["layer"]] = F.list_findings(self.db, self.current_extraction_id, f["layer"], limit=2000)
        self.show_findings()
        self._apply_overlays()
        self.statusBar().showMessage("Decision recorded (append-only audit).", 6000)

    # ------------------------------------------------------------------ registers
    def _reg_reset(self) -> None:
        self.register_offset = 0
        self.refresh_register()

    def _reg_page(self, d: int) -> None:
        new = self.register_offset + d * 100
        if 0 <= new < max(1, self.register_total):
            self.register_offset = new
            self.refresh_register()

    def _reg_query(self, **extra) -> dict:
        kw = dict(REGISTER_GROUPS[self.reg_group.currentText()])
        state = self.reg_state.currentText()
        kw.update(text=self.reg_text.text().strip(), state="" if state == "All states" else state)
        if self.reg_scope.currentIndex() == 1 and self.current_extraction_id:
            kw["extraction_id"] = self.current_extraction_id
        kw.update(extra)
        return kw

    def refresh_register(self) -> None:
        if not self.db:
            return
        try:
            page = register_page(self.db, limit=100, offset=self.register_offset, **self._reg_query())
        except Exception as exc:
            self.reg_label.setText(f"Query refused: {exc}")
            return
        self.register_rows, self.register_total = page["rows"], page["total"]
        _fill(self.reg_table, [[(r["reviewed_edit"] or {}).get("text") or r["tag_text"], r["object_class"], r["page"],
                                r["drawing_no"] or "", r["revision_label"] or "", r["state"].replace("_", " ").title(),
                                r["reviewed_by"] or "", r["source_name"]] for r in self.register_rows])
        first = self.register_offset + 1 if self.register_rows else 0
        self.reg_label.setText(f"{first}–{self.register_offset + len(self.register_rows)} of {self.register_total} "
                               "readings (unverified)")

    def _selected_reading(self) -> dict | None:
        rows = self.reg_table.selectionModel().selectedRows() if self.reg_table.selectionModel() else []
        return self.register_rows[rows[0].row()] if rows and rows[0].row() < len(self.register_rows) else None

    def _register_selected(self) -> None:
        row = self._selected_reading()
        if not row:
            return
        self.details.setPlainText(json.dumps({"source": {k: row[k] for k in ("source_name", "page", "document_sha256",
                                              "drawing_no", "revision_label")}, "reading": row["tag_text"],
                                              "class": row["object_class"], "review": row["state"],
                                              "reviewed_by": row["reviewed_by"]}, indent=2))
        if row["extraction_id"] != self.current_extraction_id:
            self.open_drawing(row["extraction_id"], row["page"])
            self.tabs.setCurrentWidget(self.reg_table.parentWidget())
        elif row["page"] != self.page:
            self.goto_page(row["page"])
        self.viewer.highlight(row["bbox"])

    def review_reading(self, decision: str) -> None:
        row = self._selected_reading()
        if not row:
            QMessageBox.information(self, "Nothing selected", "Select a reading in the table first.")
            return
        actor = self.reviewer()
        if not actor:
            return
        edited, reason = None, ""
        if decision != "ACCEPTED_AS_READING":
            dlg = ReviewDialog(self, f"{DECISION_TEXT[decision]}: {row['tag_text']}", (decision,),
                               allow_edit_text=decision == "EDITED_AND_ACCEPTED", current_text=row["tag_text"])
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            _d, reason, text = dlg.values()
            if decision == "EDITED_AND_ACCEPTED":
                if not text or text == row["tag_text"]:
                    QMessageBox.information(self, "Nothing corrected", "Type the corrected text first.")
                    return
                edited = {"text": text}
            if len(reason) < 5:
                reason = "Reviewed in desktop application"
        try:
            self.db.review(row["observation_id"], actor=actor, decision=decision, reason=reason, edited=edited)
        except Exception as exc:
            QMessageBox.warning(self, "Review refused", str(exc))
            return
        keep = self.reg_table.currentRow()
        self.refresh_register()
        if 0 <= keep < self.reg_table.rowCount():
            self.reg_table.selectRow(keep)
        self.statusBar().showMessage("Reading review recorded (original text is kept; append-only audit).", 6000)

    def export_register_csv(self) -> None:
        import csv
        from ..engineering.reports import _spreadsheet_safe
        dest, _ = QFileDialog.getSaveFileName(self, "Export register view", "register.csv", "CSV (*.csv)")
        if not dest:
            return
        try:
            offset, rows = 0, []
            while True:
                page = register_page(self.db, limit=250, offset=offset, **self._reg_query())
                rows.extend(page["rows"])
                offset += 250
                if offset >= page["total"] or offset > 100000:
                    break
            with open(dest, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh)
                w.writerow(["tag_or_text", "class", "page", "drawing_no", "revision", "review_state", "reviewed_by",
                            "source_file", "source_sha256", "unverified_notice"])
                for r in rows:
                    w.writerow([_spreadsheet_safe(v) for v in (
                        (r["reviewed_edit"] or {}).get("text") or r["tag_text"], r["object_class"], r["page"],
                        r["drawing_no"] or "", r["revision_label"] or "", r["state"], r["reviewed_by"] or "",
                        r["source_name"], r["document_sha256"], "Reading from drawing; not verified")])
            self.info(f"Exported {len(rows)} rows to {dest}")
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

    # ------------------------------------------------------------------ graph
    def refresh_graph(self) -> None:
        if not self.current_extraction_id:
            return
        try:
            g = drawing_connectivity(self.db, self.current_extraction_id)
        except Exception as exc:
            self.info(f"Graph unavailable: {type(exc).__name__}: {exc}")
            return
        self.graph.set_graph(g)
        _fill(self.path_table, [[p["a_label"], p["b_label"], len(p["via_valve_glyphs"]), "yes" if p["via_tee"] else "no",
                                 "proposed, unverified"] for p in g.get("paths", [])])
        self._graph = g

    def _graph_node(self, node_id: str) -> None:
        node = next((n for n in getattr(self, "_graph", {}).get("nodes", []) if n["id"] == node_id), None)
        if not node:
            return
        self.details.setPlainText(json.dumps({"node": node, "note": "Proposed from drawn lines; not verified."}, indent=2))
        self.tabs.setCurrentIndex(0)
        if node["page"] != self.page:
            self.goto_page(node["page"])
        self.viewer.highlight(node["bbox"])

    # ------------------------------------------------------------------ help
    def show_limits(self) -> None:
        QMessageBox.information(self, "What this software does and does not do", LIMITS_TEXT)

    def show_about(self) -> None:
        from ..formats.ocr_source import available_engines
        QMessageBox.about(self, "About P&ID Reader",
                          f"<b>P&amp;ID Reader</b> {__version__}<br>Development build — not engineering validated.<br><br>"
                          f"Offline OCR engines available: {', '.join(available_engines()) or 'none'}<br>"
                          f"Project: {self.db_path or '(none)'}<br><br>" + LIMITS_TEXT.replace("\n", "<br>"))

    def closeEvent(self, event) -> None:
        if self.task:
            if QMessageBox.question(self, "Task running", "A task is still running. Cancel it and exit?") != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.task.cancel()
            self.task.wait(8000)
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("state", self.saveState())
        if self.db:
            self.db.close()
        event.accept()
