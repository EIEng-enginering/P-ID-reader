"""Learned detector (TR1) window: run the detector on the open page, see its PROPOSED detections on the sheet, record the engineer's decisions.

Opened from the "Learned detector (TR1, proposed)" menu. Every detection is a proposal from a model trained on public drawings, with a coarse
class only; nothing here verifies anything, and nothing is written to the project database. Decisions go to the TR1 correction queue.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
                               QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..tr1 import batch_export, detector, flags, mapping, proposals, review, store

LAYER = "tr1_frcnn"
COLUMNS = ("Score", "Detector says", "Suggested family", "Detector status", "Subtype id (names unverified)", "Tag (proposal)", "Your review", "Id")


class ClassPicker(QDialog):
    def __init__(self, parent, catalogue: dict, coarse: str | None, title: str, preset: str | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Catalogue class (the detector only knows a coarse class; choose what the drawing shows):"))
        self.combo = QComboBox()
        for c in mapping.class_choices(catalogue, coarse):
            self.combo.addItem(f"{c['name']}  [{c['class_id']}]", c["class_id"])
        if preset:
            i = self.combo.findData(preset)
            if i >= 0:
                self.combo.setCurrentIndex(i)
        lay.addWidget(self.combo)
        self.note = QPlainTextEdit()
        self.note.setPlaceholderText("Note (optional): what you checked on the drawing")
        self.note.setFixedHeight(60)
        lay.addWidget(self.note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self) -> tuple[str, str]:
        return self.combo.currentData(), self.note.toPlainText().strip()


class Tr1Dialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Learned detector (TR1) - proposed detections")
        self.setModal(False)
        self.record: dict | None = None
        self.states: dict = {}
        lay = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        self.run_btn = QPushButton("Run detector on this page")
        self.run_btn.clicked.connect(self.run_detector)
        row.addWidget(self.run_btn)
        self.reload_btn = QPushButton("Show saved detections")
        self.reload_btn.clicked.connect(self.load_saved)
        row.addWidget(self.reload_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.on_select)
        self.table.setAccessibleName("Proposed detections")
        lay.addWidget(self.table, 1)
        self.buttons: dict[str, QPushButton] = {}
        row = QHBoxLayout()
        for key, text, fn in (("confirm", "Confirm as drawn", self.do_confirm), ("edit", "Change class…", self.do_edit), ("reject", "Not a symbol", self.do_reject),
                              ("unresolved", "Leave unresolved", self.do_unresolved), ("second", "Second review…", self.do_second)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
            self.buttons[key] = b
        lay.addLayout(row)
        row = QHBoxLayout()
        self.hints_btn = QPushButton("Join hints…")
        self.hints_btn.setToolTip("Conservative hints about which detections one drawn line joins. Hints only, not connections.")
        self.hints_btn.clicked.connect(self.show_join_hints)
        row.addWidget(self.hints_btn)
        self.batch_btn = QPushButton("Build training batch from final reviews…")
        self.batch_btn.clicked.connect(self.do_batch)
        row.addWidget(self.batch_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.hint = QLabel("These are proposals from a model trained on public drawings. They are not verified and say nothing about connections. "
                           "Your decisions are saved as training data only.")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        self.resize(900, 560)
        self.refresh_status()
        self.load_saved()

    # ------------------------------------------------------------------ helpers
    def _sha(self) -> str | None:
        pdf = self.main.current_pdf
        return hashlib.sha256(pdf).hexdigest() if pdf else None

    def refresh_status(self) -> None:
        st = detector.status(verify_weights=False)
        ok, why = review.available()
        self.status.setText(f"Detector: {st['message']}\nReview recording: " + ("on" if ok else why + " (decisions cannot be saved)"))
        self.run_btn.setEnabled(st["state"] == "READY" and bool(self.main.current_pdf) and self.main.task is None)
        for b in self.buttons.values():
            b.setEnabled(ok)
        self.batch_btn.setEnabled(ok and flags.enabled(batch_export.SWITCH))
        self.hints_btn.setEnabled(flags.enabled(proposals.HINT_SWITCH) and bool(self.record))

    def selected(self) -> dict | None:
        r = self.table.currentRow()
        if r < 0 or not self.record or r >= len(self.record["detections"]):
            return None
        return self.record["detections"][r]

    # ------------------------------------------------------------------ data
    def load_saved(self) -> None:
        sha = self._sha()
        self.record = detector.load_sidecar(sha, self.main.page) if sha else None
        self.refresh_table()

    def refresh_table(self) -> None:
        self.table.setRowCount(0)
        self.states = {}
        if not self.record:
            self.table.setRowCount(0)
            self.main.viewer.set_overlay(LAYER, [])
            return
        ok, _ = review.available()
        if ok:
            try:
                self.states = review.review_states(self.record)
            except Exception as exc:
                self.main.info(f"Review state unavailable: {type(exc).__name__}: {exc}")
        dets = self.record["detections"]
        tags = self._tag_proposals(dets)
        self.table.setRowCount(len(dets))
        for r, d in enumerate(dets):
            fine = d.get("fine")
            fine_text = "-" if not fine else (f"id {fine['subtype_id']} ({fine['confidence']:.2f})" if fine["status"] == "PROPOSED" else "abstained")
            tg = tags.get(d["id"])
            tag_text = "-" if not tg else f"{tg['tag_text']} [{tg['status'].lower()}]"
            status = d["confidence_status"].replace("_", " ").lower() + (" / seam-stitched" if d.get("edge_partial") else "")
            vals = (f"{d['raw_score']:.2f}", d["coarse_class"], d.get("suggested_family") or "-", status, fine_text, tag_text,
                    self.states.get(d["id"], {}).get("state", "UNREVIEWED").replace("_", " ").lower(), d["id"])
            for c, v in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.refresh_overlay()

    def _tag_proposals(self, dets: list) -> dict:
        if not flags.enabled(proposals.TAG_SWITCH) or not self.main.current_result:
            return {}
        try:
            res = proposals.propose_tags(dets, self.main.current_result["objects"], self.main.page, self.main.viewer.page_size,
                                         getattr(self.main.viewer, "_page_frame", None))
            return res["per_symbol"]
        except Exception as exc:
            self.main.info(f"Tag proposals unavailable: {type(exc).__name__}: {exc}")
            return {}

    def show_join_hints(self) -> None:
        if not self.record or not self.main.current_pdf:
            return
        try:
            import numpy as np
            import pypdfium2 as pdfium
            pg = pdfium.PdfDocument(self.main.current_pdf)[self.main.page - 1]
            gray = np.asarray(pg.render(scale=2.5, grayscale=True).to_pil().convert("L"), dtype=np.uint8)   # the detector's frame and scale
            res = proposals.join_hints(self.record["detections"], gray)
        except Exception as exc:
            QMessageBox.information(self, "Join hints", f"{type(exc).__name__}: {exc}")
            return
        lines = [f"{a}  --  {b}" for a, b in res["pairs"]] or ["No pair of detections is touched by exactly one drawn line."]
        QMessageBox.information(self, "Join hints (not connections)",
                                f"{len(res['pairs'])} hinted pair(s); {res['unresolved_junction_components']} junction(s) left unresolved.\n\n" + "\n".join(lines[:40]) + "\n\n" + res["note"])

    def refresh_overlay(self) -> None:
        if not self.record or self.record.get("page") != self.main.page:
            self.main.viewer.set_overlay(LAYER, [])
            return
        frame = getattr(self.main.viewer, "_page_frame", None)
        items = []
        for d in self.record["detections"]:
            b = frame.bbox_to_media(d["bbox"]) if frame is not None else d["bbox"]   # detections are in the rendered frame, the viewer maps from the media frame
            st = self.states.get(d["id"], {}).get("state", "UNREVIEWED").replace("_", " ").lower()
            items.append({"id": d["id"], "bbox": b, "tip": f"PROPOSED {d['coarse_class']} (score {d['raw_score']:.2f}, {st}) - not verified"})
        self.main.viewer.set_overlay(LAYER, items)
        self.main.viewer.set_layer_visible(LAYER, True)

    def on_select(self) -> None:
        d = self.selected()
        if d:
            frame = getattr(self.main.viewer, "_page_frame", None)
            self.main.viewer.highlight(frame.bbox_to_media(d["bbox"]) if frame is not None else d["bbox"])

    # ------------------------------------------------------------------ detector
    def run_detector(self) -> None:
        pdf, page = self.main.current_pdf, self.main.page
        if not pdf:
            QMessageBox.information(self, "No drawing", "Open a drawing first.")
            return
        sha = hashlib.sha256(pdf).hexdigest()
        tmp = store.home() / "tmp" / f"{sha}.pdf"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        if not tmp.exists():
            tmp.write_bytes(pdf)

        def job(report, is_cancelled):
            report(0.05, "Learned detector: loading the model")
            return detector.detect(tmp, page, cancel=is_cancelled)

        def done(res):
            self.refresh_status()
            if res["status"] == "DONE":
                self.record = res["record"]
                self.main.info(res["message"])
                self.refresh_table()
            else:
                self.main.info(f"Learned detector: {res['message']}")
                QMessageBox.information(self, "Learned detector", res["message"] + ("\n\n" + res["fallback"] if res.get("fallback") else ""))

        self.run_btn.setEnabled(False)
        self.main.run_task("Learned detector (proposals only)", job, done)

    # ------------------------------------------------------------------ decisions
    def _decide(self, fn, *a, **k) -> None:
        d = self.selected()
        if not d or not self.record:
            QMessageBox.information(self, "Choose a detection", "Select a row first.")
            return
        who = self.main.reviewer()
        if not who:
            return
        try:
            res = fn(self.record, d, who, *a, **k)
        except Exception as exc:
            QMessageBox.warning(self, "Not recorded", f"{type(exc).__name__}: {exc}")
            return
        msg = "recorded" if res["status"] == "ACCEPTED_FINAL" else "recorded; needs an independent second reviewer (" + ", ".join(res["second_review_required"]).lower().replace("_", " ") + ")"
        self.main.info(f"Review {msg}: {d['id']}")
        keep = self.table.currentRow()
        self.refresh_table()
        self.table.selectRow(keep)

    def do_confirm(self) -> None:
        d = self.selected()
        if d and not d.get("suggested_class_id"):
            dlg = ClassPicker(self, review.catalogue(), d.get("coarse_class"), "Confirm - choose the class")
            if dlg.exec():
                cid, note = dlg.values()
                self._decide(review.confirm, class_id=cid, note=note)
            return
        self._decide(review.confirm)

    def do_edit(self) -> None:
        d = self.selected()
        if not d:
            QMessageBox.information(self, "Choose a detection", "Select a row first.")
            return
        dlg = ClassPicker(self, review.catalogue(), d.get("coarse_class"), "Change class", d.get("suggested_class_id"))
        if dlg.exec():
            cid, note = dlg.values()
            self._decide(review.edit_class, cid, note=note)

    def do_reject(self) -> None:
        self._decide(review.reject)

    def do_unresolved(self) -> None:
        self._decide(review.mark_unresolved)

    def do_second(self) -> None:
        try:
            waiting = review.awaiting_second_review()
        except Exception as exc:
            QMessageBox.warning(self, "Second review", f"{type(exc).__name__}: {exc}")
            return
        d = self.selected()
        mine = None
        if d:
            mine = self.states.get(d["id"], {}).get("correction_id")
        pick = next((c for c in waiting if c["id"] == mine), None)
        if not pick:
            QMessageBox.information(self, "Second review", "The selected detection is not waiting for a second review." if d else "Select a detection first.")
            return
        who = self.main.reviewer()
        if not who:
            return
        if who == pick["submitted_by"]:
            who, ok = QInputDialog.getText(self, "Second reviewer", "A second review must be done by a different person. Name of the second reviewer:")
            if not ok or not who.strip():
                return
        agree = QMessageBox.question(self, "Second review", f"Do you agree with the first reviewer's decision ({pick['kind'].lower().replace('_', ' ')})?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
        try:
            review.second_review(pick["id"], who.strip(), agree)
        except Exception as exc:
            QMessageBox.warning(self, "Not recorded", f"{type(exc).__name__}: {exc}")
            return
        self.main.info("Second review recorded")
        self.refresh_table()

    def do_batch(self) -> None:
        fam, ok = QInputDialog.getText(self, "Training batch", "Project family (all revisions of one project share it, so they stay in one split):")
        if not ok or not fam.strip():
            return
        appr, ok = QInputDialog.getText(self, "Training batch", "Usage approval id for training on these drawings (issued by the drawing owner):")
        if not ok or not appr.strip():
            return
        who, ok = QInputDialog.getText(self, "Training batch", "Name of the person who approved that use:")
        if not ok or not who.strip():
            return
        version, ok = QInputDialog.getText(self, "Training batch", "Batch version (never reused):", text="B1")
        if not ok or not version.strip():
            return
        names = {}
        if self.record:
            names[self.record["source_sha256"]] = self.record.get("source_name", "")
        try:
            m = batch_export.build(version.strip(), project_family=fam.strip(), approval_id=appr.strip(), approved_by=who.strip(), source_names=names)
        except Exception as exc:
            QMessageBox.warning(self, "No batch built", f"{type(exc).__name__}: {exc}")
            return
        QMessageBox.information(self, "Training batch saved", f"{m['path']}\n\nItems: {m['item_count']} (rejected: {m['rejected_count']})\nbatch sha256: {m['batch_sha256']}\n\n"
                                "The batch is immutable; nothing has been trained.")
