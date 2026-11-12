"""WP-01..03 proposal register (unverified): text-to-engineering readings, detector triage and circle evidence for the open page.

A separate tab. Nothing here is written to the extraction, the standalone project tables or the Worksheet R1 contract: proposals and the
engineer's named, reasoned decisions live in the WP123 sidecar database (hash-chained, append-only). Accepting a reading only records that the
printed text reads like this; it never verifies a tag, a connection or the plant.
"""
from __future__ import annotations

import csv
import io

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..api import canonical_json
from ..engineering import wp123_session as S

LAYER = "wp123"
COLUMNS = ("Proposal", "Kind", "Status", "Page", "Evidence", "Reviewed by", "Id")
# accept / correct make sense only where the proposal is a reading of printed text; detector boxes and circles are geometry evidence.
READING_GROUPS = (S.GROUPS[0], S.GROUPS[1], S.GROUPS[2])


class Wp123Tab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.analysis_id: str | None = None
        self.rows: list[dict] = []
        self.shown: list[dict] = []
        self.doc: dict | None = None
        lay = QVBoxLayout(self)
        note = QLabel(S.NOTICE + " Detector boxes are shown with the reason they were withheld; none is used to attach a tag automatically.")
        note.setWordWrap(True)
        lay.addWidget(note)
        top = QHBoxLayout()
        self.build_btn = QPushButton("Build proposals for this page")
        self.build_btn.setToolTip("Reads the stored OCR words (or native text) of the open page, plus any saved learned-detector run, with the offline WP-01..03 rules.")
        self.build_btn.clicked.connect(self.build)
        top.addWidget(self.build_btn)
        self.circles = QCheckBox("Also look for circles near instrument-style text (slower)")
        top.addWidget(self.circles)
        self.profile = QComboBox()
        self.profile.addItem("Layout: automatic", "auto")
        self.profile.addItem("Layout: none", "none")
        self.profile.setToolTip("The drawing-specific S418 frame profile is available only from the command line; it must not be applied to other drawings.")
        top.addWidget(self.profile)
        self.load_btn = QPushButton("Show last saved analysis")
        self.load_btn.clicked.connect(self.load_last)
        top.addWidget(self.load_btn)
        top.addStretch(1)
        lay.addLayout(top)
        self.summary = QLabel("No proposals built for this drawing yet.")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        flt = QHBoxLayout()
        self.group = QComboBox()
        self.group.addItems(S.GROUPS)
        self.group.currentIndexChanged.connect(self.refresh_table)
        flt.addWidget(self.group)
        self.state = QComboBox()
        self.state.addItems(["All states", "Not reviewed", "Accepted / corrected", "Rejected", "Left unresolved"])
        self.state.currentIndexChanged.connect(self.refresh_table)
        flt.addWidget(self.state)
        self.text = QLineEdit()
        self.text.setPlaceholderText("Filter by text")
        self.text.setClearButtonEnabled(True)
        self.text.textChanged.connect(self.refresh_table)
        flt.addWidget(self.text, 1)
        lay.addLayout(flt)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.on_select)
        self.table.itemDoubleClicked.connect(lambda _i: self.show_on_drawing())
        self.table.setAccessibleName("WP-01 to WP-03 proposals")
        lay.addWidget(self.table, 1)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(130)
        lay.addWidget(self.details)
        row = QHBoxLayout()
        self.buttons: dict[str, QPushButton] = {}
        for key, text, fn in (("show", "Show on drawing", self.show_on_drawing), ("accept", "Accept as printed", lambda: self.decide("accept")),
                              ("correct", "Correct reading…", lambda: self.decide("correct")), ("reject", "Reject", lambda: self.decide("reject")),
                              ("unresolved", "Leave unresolved", lambda: self.decide("unresolved"))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
            self.buttons[key] = b
        row.addStretch(1)
        vb = QPushButton("Verify decision chain")
        vb.clicked.connect(self.verify)
        row.addWidget(vb)
        eb = QPushButton("Export this view (CSV)…")
        eb.clicked.connect(self.export_csv)
        row.addWidget(eb)
        lay.addLayout(row)
        self.result_label = QLabel("")
        lay.addWidget(self.result_label)
        self._update_buttons()

    # ------------------------------------------------------------ data
    def _sidecar(self) -> S.Wp123Sidecar:
        return S.Wp123Sidecar()

    def reset(self) -> None:
        """A different drawing was opened: forget the loaded analysis (stored analyses and decisions are untouched)."""
        self.analysis_id, self.doc, self.rows = None, None, []
        self.summary.setText("No proposals built for this drawing yet.")
        self.refresh_table()
        self.main.viewer.set_overlay(LAYER, [])

    def build(self) -> None:
        m = self.main
        if not m.current_extraction_id or not m.current_pdf:
            QMessageBox.information(self, "No drawing open", "Open a drawing first.")
            return
        pdf, page = m.current_pdf, m.page
        try:
            words, origin = S.words_from_project(m.db, m.current_extraction_id, page, m.current_result)
            dets, det_origin = S.detections_for_page(pdf, page)
        except Exception as exc:
            QMessageBox.warning(self, "Cannot gather evidence", f"{type(exc).__name__}: {exc}")
            return
        if not words:
            QMessageBox.information(self, "Nothing to read", "This page has no stored OCR words or text. Run the analysis (with OCR for scanned sheets) first.")
            return
        circles, profile = self.circles.isChecked(), self.profile.currentData()

        def job(report, is_cancelled):
            report(0.1, "Reading proposals from the stored words")
            res = S.analyse_page(pdf, page, words, dets, scan_bubbles=circles, profile=profile)
            report(0.9, "Saving the analysis (sidecar)")
            return res

        def done(res):
            sc = self._sidecar()
            try:
                self.analysis_id = sc.add(res)
                self.doc, self.rows = sc.rows(self.analysis_id)
            finally:
                sc.close()
            self._after_load(f"Evidence: {origin}; {det_origin}.")

        m.run_task("WP-01..03 proposals (unverified)", job, done)

    def load_last(self) -> None:
        import hashlib
        if not self.main.current_pdf:
            QMessageBox.information(self, "No drawing open", "Open a drawing first.")
            return
        sc = self._sidecar()
        try:
            aid = sc.latest_analysis_for(hashlib.sha256(self.main.current_pdf).hexdigest())
            if not aid:
                QMessageBox.information(self, "Nothing saved", "No WP-01..03 analysis has been saved for this drawing yet.")
                return
            self.analysis_id = aid
            self.doc, self.rows = sc.rows(aid)
        finally:
            sc.close()
        self._after_load("Showing the last saved analysis.")

    def _after_load(self, origin: str) -> None:
        t = S.triage_summary(self.doc)
        why = ", ".join(f"{k.replace('_', ' ').lower()} {v}" for k, v in sorted(t["detector_withheld_reasons"].items()))
        self.summary.setText(
            f"{origin} {t['readings_proposed']} reading(s) ({t['tags_proposed']} tag, {t['line_numbers_proposed']} line number), "
            f"{t['line_number_fragments']} incomplete line string(s), {t['document_fields_proposed']} document field(s), {t['raster_bubble_candidates']} circle(s); "
            f"detector boxes {t['detectors_total']} ({t['detectors_reviewable']} reviewable; withheld: {why or 'none'}); "
            f"{t['associations_proposed']} tag-to-symbol association(s). Nothing is verified.")
        self.refresh_table()
        self._refresh_overlay()

    # ------------------------------------------------------------ display
    def _passes_filters(self, r: dict) -> bool:
        if r["group"] != self.group.currentText():
            return False
        st = self.state.currentIndex()
        d = r["decision"]
        if st == 1 and d is not None:
            return False
        if st == 2 and d not in ("ACCEPTED_AS_READING", "CORRECTED_READING"):
            return False
        if st == 3 and d != "REJECTED":
            return False
        if st == 4 and d != "UNRESOLVED":
            return False
        q = self.text.text().strip().lower()
        return not q or q in (r["text"] + " " + (r["corrected_text"] or "")).lower()

    def refresh_table(self) -> None:
        keep = self.selected()["id"] if self.selected() else None
        self.shown = [r for r in self.rows if self._passes_filters(r)]
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.shown))
        sel = -1
        for i, r in enumerate(self.shown):
            text = r["text"] if not r["corrected_text"] else f"{r['corrected_text']}  (printed: {r['text']})"
            vals = (text, r["kind"], r["state_text"], str(r["page"]), r["evidence"], r["decided_by"], r["id"])
            for c, v in enumerate(vals):
                self.table.setItem(i, c, QTableWidgetItem(v))
            if r["id"] == keep:
                sel = i
        self.table.resizeColumnsToContents()
        self.table.blockSignals(False)
        if sel >= 0:
            self.table.selectRow(sel)
        self.on_select()
        self._refresh_overlay()

    def _refresh_overlay(self) -> None:
        page = self.main.page
        items = [{"id": r["id"], "bbox": r["bbox"], "tip": f"{r['kind']}: {r['text']} - {r['state_text']} (unverified proposal)"}
                 for r in self.rows if r["page"] == page and r["group"] in READING_GROUPS + (S.GROUPS[3],)]
        self.main.viewer.set_overlay(LAYER, items)
        self.main.viewer.set_layer_visible(LAYER, bool(items))

    def select_id(self, item_id: str) -> None:
        """Select a proposal clicked on the sheet (switches the group filter if needed)."""
        r = next((x for x in self.rows if x["id"] == item_id), None)
        if not r:
            return
        self.main.tabs.setCurrentWidget(self)
        self.state.setCurrentIndex(0)
        self.text.clear()
        self.group.setCurrentIndex(S.GROUPS.index(r["group"]))
        for i, s in enumerate(self.shown):
            if s["id"] == item_id:
                self.table.selectRow(i)
                break

    def selected(self) -> dict | None:
        i = self.table.currentRow()
        return self.shown[i] if 0 <= i < len(self.shown) else None

    def on_select(self) -> None:
        r = self.selected()
        self.details.setPlainText("" if not r else canonical_json({"proposal": r["detail"], "review": {"state": r["state_text"], "by": r["decided_by"], "reason": r["reason"]},
                                                                  "note": "Unverified proposal with its source evidence ids; compare with the drawing before deciding."}))
        self._update_buttons()

    def _update_buttons(self) -> None:
        r = self.selected()
        reading = bool(r) and r["group"] in READING_GROUPS
        self.buttons["show"].setEnabled(bool(r))
        self.buttons["accept"].setEnabled(reading)
        self.buttons["correct"].setEnabled(reading)
        self.buttons["reject"].setEnabled(bool(r))
        self.buttons["unresolved"].setEnabled(bool(r))

    def show_on_drawing(self) -> None:
        r = self.selected()
        if not r:
            return
        m = self.main
        m.tabs.setCurrentIndex(0)
        if r["page"] != m.page:
            m.goto_page(r["page"])
        m.viewer.highlight(r["bbox"])

    # ------------------------------------------------------------ decisions
    def decide(self, action: str) -> None:
        r = self.selected()
        if not r or not self.analysis_id:
            return
        actor = self.main.reviewer()
        if not actor:
            return
        corrected = None
        if action == "correct":
            corrected, ok = QInputDialog.getText(self, "Correct reading", f"The printed text was read as “{r['text']}”.\nWhat does the drawing actually show?",
                                                 text=r["corrected_text"] or r["text"])
            if not ok or not corrected.strip():
                return
            corrected = corrected.strip()
        label = {"accept": "Accept as printed", "correct": "Correct reading", "reject": "Reject", "unresolved": "Leave unresolved"}[action]
        reason, ok = QInputDialog.getText(self, label, "Reason / what you checked on the drawing (required, recorded with your name):")
        if not ok or not reason.strip():
            return
        sc = self._sidecar()
        try:
            sc.decide(self.analysis_id, r["id"], action, actor=actor, reason=reason.strip(), corrected_text=corrected)
            self.doc, self.rows = sc.rows(self.analysis_id)
        except Exception as exc:
            QMessageBox.warning(self, "Decision not recorded", f"{type(exc).__name__}: {exc}")
            return
        finally:
            sc.close()
        self.main.info(f"WP-01..03 decision recorded ({label.lower()}): {r['text']}")
        self.refresh_table()

    def verify(self) -> None:
        sc = self._sidecar()
        try:
            errors = sc.verify()
        finally:
            sc.close()
        ok = not errors
        self.result_label.setText("Decision chain intact." if ok else "DECISION CHAIN BROKEN: " + "; ".join(errors[:3]))
        self.result_label.setStyleSheet("color: #2e7d32" if ok else "color: #c62828; font-weight: bold")

    def export_csv(self) -> None:
        if not self.shown:
            QMessageBox.information(self, "Nothing to export", "The current view is empty.")
            return
        start = self.main.settings.value("export_folder", "", str) or ""
        path, _ = QFileDialog.getSaveFileName(self, "Export WP-01..03 view (CSV)", start, "CSV (*.csv)")
        if not path:
            return
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["proposal", "kind", "status", "corrected_text", "reviewed_by", "reason", "page", "evidence", "id", "notice"])
        for r in self.shown:
            # spreadsheet-safe: never let a cell start as a formula
            def safe(v):
                v = "" if v is None else str(v)
                return "'" + v if v[:1] in ("=", "+", "-", "@") else v
            w.writerow([safe(r["text"]), r["kind"], r["state_text"], safe(r["corrected_text"]), r["decided_by"], safe(r["reason"]), r["page"], r["evidence"], r["id"],
                        "unverified proposal"])
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            f.write(buf.getvalue())
        self.main.info(f"WP-01..03 view exported: {path}")
