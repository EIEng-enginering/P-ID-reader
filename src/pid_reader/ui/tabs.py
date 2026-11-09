"""Secondary workspace tabs: revisions, batch, libraries, reports, audit.

Each tab talks to the main window through a small context object (``ctx``):
``ctx.db`` (GUI-thread store), ``ctx.db_path``, ``ctx.reviewer()``, ``ctx.run_task(...)``,
``ctx.ocr_engine()``, ``ctx.refresh_all()`` and ``ctx.info(text)``.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel,
                               QListWidget, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..api import canonical_json


def _table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setAlternatingRowColors(False)
    t.horizontalHeader().setStretchLastSection(True)
    t.verticalHeader().setVisible(False)
    return t


def _fill(t: QTableWidget, rows: list[list]) -> None:
    t.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            t.setItem(r, c, QTableWidgetItem("" if v is None else str(v)))
    t.resizeColumnsToContents()


class RevisionTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.before, self.after = QComboBox(), QComboBox()
        for box in (self.before, self.after):   # long drawing names must not widen the whole window
            box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            box.setMinimumContentsLength(22)
        for lab, box in (("Before:", self.before), ("After:", self.after)):
            row.addWidget(QLabel(lab))
            row.addWidget(box, 1)
        btn = QPushButton("Compare readings")
        btn.clicked.connect(self.compare)
        row.addWidget(btn)
        lay.addLayout(row)
        self.table = _table(["Change", "Tag", "Class", "Detail"])
        lay.addWidget(self.table, 1)
        self.note = QLabel("Compares source readings between two imported drawing revisions. Matching uses unique "
                           "(class, tag) pairs only; renamed or untagged items are listed unmatched, never merged. "
                           "Acceptance is not carried between revisions.")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)

    def refresh(self) -> None:
        rows = self.ctx.db.db.execute(
            """SELECT e.extraction_id, d.source_name, e.imported_utc,
               (SELECT r.drawing_no||' rev '||r.revision_label FROM drawing_registration r
                WHERE r.extraction_id=e.extraction_id ORDER BY r.rowid DESC LIMIT 1) AS reg
               FROM extraction e JOIN document_revision d ON d.sha256=e.document_sha256
               ORDER BY e.imported_utc DESC""").fetchall()
        for box in (self.before, self.after):
            box.clear()
            for r in rows:
                box.addItem(f"{r['reg'] or r['source_name']}  ({r['imported_utc'][:16]})", r["extraction_id"])
        if self.after.count() > 1:
            self.after.setCurrentIndex(0)
            self.before.setCurrentIndex(1)

    def compare(self) -> None:
        old, new = self.before.currentData(), self.after.currentData()
        if not old or not new or old == new:
            QMessageBox.information(self, "Choose two revisions", "Pick two different imported drawings.")
            return
        try:
            _cid, data = self.ctx.db.compare_revisions(old, new)
        except Exception as exc:
            QMessageBox.warning(self, "Comparison refused", str(exc))
            return
        rows = []
        for ev in data.get("events", []):
            if ev["kind"] == "SAME_READING":
                continue
            rows.append([ev["kind"].replace("_", " ").title(), ev["tag"], ev["class"], ", ".join(ev["changed_fields"])])
        for key, label in (("unmatched_before", "Unmatched (before only)"), ("unmatched_after", "Unmatched (after only)")):
            for ev in data.get(key, []):
                rows.append([label, ev.get("text") or ev.get("tag") or "", ev.get("class", ""), ev.get("reason", "")])
        _fill(self.table, rows)
        changed = sum(1 for e in data.get("events", []) if e["kind"] != "SAME_READING")
        self.ctx.info(f"Revision comparison: {changed} differences, {len(data.get('unmatched_before', []))}/"
                      f"{len(data.get('unmatched_after', []))} unmatched.")


class BatchTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.paths: list[Path] = []
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        for text, fn in (("Add PDFs…", self.add_files), ("Add folder…", self.add_folder),
                         ("Clear list", self.clear)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        self.start_btn = QPushButton("Start batch import")
        self.start_btn.clicked.connect(self.start)
        row.addWidget(self.start_btn)
        lay.addLayout(row)
        self.queue = QListWidget()
        self.queue.setMaximumHeight(120)
        lay.addWidget(self.queue)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Earlier batches:"))
        self.history = QComboBox()
        self.history.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.history.setMinimumContentsLength(22)
        row2.addWidget(self.history, 1)
        rb = QPushButton("Resume selected")
        rb.clicked.connect(self.resume)
        row2.addWidget(rb)
        lay.addLayout(row2)
        self.table = _table(["#", "File", "Result", "Detail"])
        lay.addWidget(self.table, 1)
        info = QLabel("Each PDF is read in its own time- and memory-limited process. Cancel keeps finished files; "
                      "an unfinished batch can be resumed and re-checks that the source bytes did not change.")
        info.setWordWrap(True)
        lay.addWidget(info)

    def refresh(self) -> None:
        self.history.clear()
        for r in self.ctx.db.db.execute("SELECT batch_id,actor,created_utc FROM batch_import_run ORDER BY rowid DESC LIMIT 50"):
            job = self.ctx.db.get_batch(r["batch_id"])
            self.history.addItem(f"{r['created_utc'][:16]}  {job['state']}  "
                                 f"({job['counts']['completed']}/{job['counts']['total']})", r["batch_id"])
        if self.history.count():
            self.show_batch(self.history.currentData())

    def add_files(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(self, "Add PDFs", "", "PDF files (*.pdf)")
        self._add([Path(n) for n in names])

    def add_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Add folder of PDFs")
        if d:
            self._add(sorted(Path(d).glob("*.pdf")))

    def _add(self, paths: list[Path]) -> None:
        for p in paths:
            if p not in self.paths:
                self.paths.append(p)
                self.queue.addItem(str(p))

    def clear(self) -> None:
        self.paths.clear()
        self.queue.clear()

    def show_batch(self, batch_id: str) -> None:
        job = self.ctx.db.get_batch(batch_id)
        by = {o["ordinal"]: o for o in job["outcomes"]}
        rows = []
        for item in job["manifest"]:
            o = by.get(item["ordinal"])
            rows.append([item["ordinal"] + 1, item["name"], o["status"] if o else "PENDING", o["detail"] if o else ""])
        _fill(self.table, rows)

    def start(self) -> None:
        if not self.paths:
            QMessageBox.information(self, "Nothing queued", "Add PDFs or a folder first.")
            return
        actor = self.ctx.reviewer()
        if not actor:
            return
        paths, db_path, ocr = list(self.paths), self.ctx.db_path, self.ctx.ocr_engine()

        def job(report, cancelled):
            from ..engineering.batch import resume_batch, start_batch
            from ..engineering.project import ProjectStore
            with ProjectStore(db_path) as db:
                bid = start_batch(db, paths, actor=actor)
                report(0.0, f"Batch {bid[-8:]} created")
                out = resume_batch(db, bid, isolated=True, should_cancel=cancelled, ocr_engine=ocr,
                                   progress=lambda d, t, n: report(d / max(1, t), f"Reading {n} ({d + 1}/{t})"))
                return bid, out["state"], out["counts"]

        def done(result):
            self.clear()
            self.ctx.info(f"Batch finished: {result[1]} {result[2]}")
            self.ctx.refresh_all()

        self.ctx.run_task("Batch import", job, done)

    def resume(self) -> None:
        bid = self.history.currentData()
        if not bid:
            return
        db_path, ocr = self.ctx.db_path, self.ctx.ocr_engine()

        def job(report, cancelled):
            from ..engineering.batch import resume_batch
            from ..engineering.project import ProjectStore
            with ProjectStore(db_path) as db:
                out = resume_batch(db, bid, isolated=True, should_cancel=cancelled, ocr_engine=ocr,
                                   progress=lambda d, t, n: report(d / max(1, t), f"Reading {n} ({d + 1}/{t})"))
                return out["state"], out["counts"]

        self.ctx.run_task("Resume batch", job, lambda r: (self.ctx.info(f"Batch: {r[0]} {r[1]}"), self.ctx.refresh_all()))


class LibraryTab(QWidget):
    """Project-specific tag conventions and symbol templates (declarative, no model training)."""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        lay = QHBoxLayout(self)
        lay.addWidget(self._group("Tag profile (site naming rules)", "tag"), 1)
        lay.addWidget(self._group("Symbol template catalogue", "cat"), 1)

    def _group(self, title: str, kind: str) -> QGroupBox:
        box = QGroupBox(title)
        v = QVBoxLayout(box)
        editor = QPlainTextEdit()
        editor.setPlaceholderText("JSON definition")
        editor.setAccessibleName(title)
        setattr(self, kind + "_edit", editor)
        v.addWidget(editor, 1)
        row = QHBoxLayout()
        for text, fn in (("Load example", lambda: self.example(kind)), ("Open file…", lambda: self.open_file(kind)),
                         ("Validate", lambda: self.validate(kind)), ("Save to project", lambda: self.save(kind))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        v.addLayout(row)
        status = QLabel("")
        status.setWordWrap(True)
        setattr(self, kind + "_status", status)
        v.addWidget(status)
        blurb = QLabel("Edits are versioned, hashed and audited. Adding a definition configures matching rules; "
                       "it is not model training and says nothing about accuracy.")
        blurb.setWordWrap(True)
        v.addWidget(blurb)
        return box

    def refresh(self) -> None:
        rows = self.ctx.db.db.execute("SELECT count(*) FROM symbol_catalogue").fetchone()[0]
        prof = self.ctx.db.db.execute("SELECT count(*) FROM tag_profile").fetchone()[0]
        self.cat_status.setText(f"{rows} catalogue(s) registered in this project.")
        self.tag_status.setText(f"{prof} tag profile(s) registered in this project.")

    def example(self, kind: str) -> None:
        if kind == "tag":
            from ..engineering.tag_profiles import example_profile
            data = example_profile()
        else:
            from ..engineering.symbol_catalog import example_catalog
            data = example_catalog()
        getattr(self, kind + "_edit").setPlainText(json.dumps(data, indent=2))

    def open_file(self, kind: str) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "Open JSON", "", "JSON (*.json)")
        if name:
            getattr(self, kind + "_edit").setPlainText(Path(name).read_text(encoding="utf-8"))

    def _parse(self, kind: str):
        try:
            data = json.loads(getattr(self, kind + "_edit").toPlainText())
            if kind == "tag":
                from ..engineering.tag_profiles import validate_profile
                validate_profile(data)
            else:
                from ..engineering.symbol_catalog import validate_catalog
                problems = validate_catalog(data)
                if problems:
                    raise ValueError("; ".join(problems[:4]))
            return data
        except Exception as exc:
            getattr(self, kind + "_status").setText(f"Not valid: {exc}")
            return None

    def validate(self, kind: str) -> None:
        if self._parse(kind) is not None:
            getattr(self, kind + "_status").setText("Valid.")

    def save(self, kind: str) -> None:
        data = self._parse(kind)
        if data is None:
            return
        try:
            ident = (self.ctx.db.register_tag_profile(data) if kind == "tag" else self.ctx.db.register_symbol_catalogue(data))
        except Exception as exc:
            getattr(self, kind + "_status").setText(f"Not saved: {exc}")
            return
        self.refresh()
        getattr(self, kind + "_status").setText(f"Saved as {ident}.")
        self.ctx.settings_set("catalogue_id" if kind == "cat" else "tag_profile_id", ident)


class SheetInfoTab(QWidget):
    """Read-only view of the open drawing: title block and text items, instrument loops, reading checks."""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        self.heading = QLabel("Open a drawing to see its sheet information.")
        self.heading.setWordWrap(True)
        lay.addWidget(self.heading)
        self.fields = _table(["Item", "Value", "Page", "x", "y"])
        lay.addWidget(QLabel("Title block, line sizes and numbers, set-points (candidates read from the drawing text)"))
        lay.addWidget(self.fields, 3)
        self.loops = _table(["Loop no.", "Tags on this drawing", "Count"])
        lay.addWidget(QLabel("Instrument tags grouped by printed loop number (a reading aid, not a safety loop)"))
        lay.addWidget(self.loops, 1)
        self.checks = _table(["Level", "Check", "Message", "Page"])
        lay.addWidget(QLabel("Reading checks: prompts to look at the drawing, not plant facts"))
        lay.addWidget(self.checks, 2)
        for t in (self.fields, self.checks):
            t.itemSelectionChanged.connect(lambda t=t: self._pick(t))
        self._positions = {}

    def show(self, name: str, fields: dict, loops: list, checks: list) -> None:
        from ..engineering.sheet_fields import flatten
        rows = flatten(fields)
        self.heading.setText(f"{name}: {len(rows)} sheet items, {len(loops)} loop groups, {len(checks)} checks. "
                             "Everything is an unverified proposal.")
        _fill(self.fields, [[f"{r['group']}: {r['field']}" if r["group"] == "Title block" else r["group"], r["value"][:200],
                             r["page"], r["x"], r["y"]] for r in rows])
        _fill(self.loops, [[lp["loop"], ", ".join(m["tag"] for m in lp["members"]), lp["member_count"]] for lp in loops])
        _fill(self.checks, [[c["severity"], c["check"].replace("_", " ").lower(), c["message"], c["page"] or ""] for c in checks])
        self._positions = {id(self.fields): [(r["page"], r["x"], r["y"]) for r in rows],
                           id(self.checks): [(c["page"], (c["bbox"] or {}).get("x0"), (c["bbox"] or {}).get("y0")) for c in checks]}
        self._boxes = {"checks": [c["bbox"] for c in checks]}

    def _pick(self, table) -> None:
        sel = table.selectionModel().selectedRows() if table.selectionModel() else []
        if not sel:
            return
        page, x, y = self._positions.get(id(table), [])[sel[0].row()]
        if page and x is not None:
            self.ctx.show_position(page, x, y)


class QualityTab(QWidget):
    """Run health of the open drawing: status, per-stage outcomes, page text status and unresolved issues. Never a success claim."""

    COLOURS = {"COMPLETE_CANDIDATES": "#2e7d32", "PARTIAL": "#ef6c00", "INCOMPLETE": "#c62828", "FAILED": "#c62828", "NOT_RUN": "#616161"}

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        self.banner = QLabel("Analyse a drawing to see its run health.")
        self.banner.setWordWrap(True)
        lay.addWidget(self.banner)
        self.stages = _table(["Stage", "Status", "Candidates", "ms", "Detail"])
        lay.addWidget(QLabel("Stages: \u201cdid not run\u201d, \u201cfailed\u201d and \u201cran and found nothing\u201d are different results"))
        lay.addWidget(self.stages, 3)
        self.pages = _table(["Page", "Encoding", "Text status", "Native words", "OCR words", "Blocker"])
        lay.addWidget(QLabel("Pages: an empty result on a page with drawn content is never read as an empty drawing"))
        lay.addWidget(self.pages, 2)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)

    def refresh(self) -> None:
        eid = getattr(self.ctx, "current_extraction_id", None)
        if not eid or not self.ctx.db:
            return
        from ..engineering import intelligence_store as istore
        run = istore.latest_run(self.ctx.db, eid)
        if run is None:
            self.banner.setText("No analysis has been run for this drawing yet (Drawing \u25b8 Analyse).")
            self.banner.setStyleSheet("")
            _fill(self.stages, [])
            _fill(self.pages, [])
            return
        health = run["summary"].get("health", {})
        status = run["status"]
        self.banner.setText(f"Status: {status}" + (f"  \u2014 first blocker: {health.get('primary_blocker')}" if health.get("primary_blocker") else "") +
                            f"   ({run['preset']} depth, {run['engine_version']})")
        self.banner.setStyleSheet(f"color: {self.COLOURS.get(status, '#000')}; font-weight: bold")
        _fill(self.stages, [[o["stage_id"], o["status"], o.get("candidates", 0), o.get("runtime_ms", 0),
                             (o.get("error_summary") or o.get("diagnostics", {}).get("detail", ""))[:160]] for o in run["outcomes"]])
        _fill(self.pages, [[p["page"], p["classification"], p["text_status"], p["words_native"], p["words_ocr"], p["primary_blocker"]]
                           for p in health.get("pages", [])])
        self.note.setText(health.get("notice", ""))


class ReportTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        self.scope = QComboBox()
        self.scope.addItems(["Entire project", "Current drawing only"])
        lay.addWidget(QLabel("Scope"))
        lay.addWidget(self.scope)
        each = QPushButton("Save each drawing as its own files (named after the PDF)…")
        each.setToolTip("Per drawing: NAME.json, NAME.html, NAME.graph.json, NAME.graphml in a folder you choose. "
                        "Uses the scope above; existing files are never overwritten.")
        each.clicked.connect(lambda: self.ctx.export_drawing_files(self.scope.currentIndex() == 0))
        lay.addWidget(each)
        pkg = QPushButton("Export AI-ready engineering package (JSON, registers, evidence, prompt)\u2026")
        pkg.setToolTip("Writes a new sub-folder in a folder you choose, for the open drawing. Nothing is uploaded; existing folders are never overwritten.")
        pkg.clicked.connect(lambda: self.ctx.export_ai_package())
        lay.addWidget(pkg)
        for fmt, text in (("html", "Export readings report (HTML, printable)"), ("csv", "Export readings register (CSV)"),
                          ("json", "Export readings report (JSON)")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fmt: self.export(f))
            lay.addWidget(b)
        for text, key in (("Export Excel workbook (.xlsx): registers, loops, lines, findings, checks", "xlsx"),
                          ("Export proposed connectivity graph (canonical JSON)", "graph-json"),
                          ("Export proposed connectivity graph (GraphML)", "graphml")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, k=key: self.export_other(k))
            lay.addWidget(b)
        note = QLabel("Reports list what was read from the drawings, with source file hash, page, box and review state. "
                      "They are not engineering approvals and do not verify the plant.")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch(1)

    def export_other(self, kind: str) -> None:
        if kind == "xlsx":
            ids = None if self.scope.currentIndex() == 0 else ([self.ctx.current_extraction_id] if self.ctx.current_extraction_id else [])
            if ids == []:
                QMessageBox.information(self, "No drawing open", "Open a drawing first, or choose 'Entire project'.")
                return
            dest, _ = QFileDialog.getSaveFileName(self, "Save workbook", "pid_readings.xlsx", "Excel workbook (*.xlsx)")
            if not dest:
                return
            try:
                from ..engineering.xlsx_export import export_xlsx
                export_xlsx(self.ctx.db, dest, extraction_ids=ids)
                self.ctx.info(f"Workbook saved: {dest}")
            except Exception as exc:
                QMessageBox.warning(self, "Workbook not saved", f"{type(exc).__name__}: {exc}")
            return
        if not self.ctx.current_extraction_id:
            QMessageBox.information(self, "No drawing open", "Open a drawing first.")
            return
        graphml = kind == "graphml"
        dest, _ = QFileDialog.getSaveFileName(self, "Save graph", "connectivity." + ("graphml" if graphml else "json"),
                                              "GraphML (*.graphml)" if graphml else "JSON (*.json)")
        if not dest:
            return
        try:
            from ..engineering.graph_export import canonical_graph, to_graphml
            graph = canonical_graph(self.ctx.db, self.ctx.current_extraction_id)
            Path(dest).write_text(to_graphml(graph) if graphml else canonical_json(graph), encoding="utf-8")
            self.ctx.info(f"Graph saved: {dest} ({len(graph['nodes'])} nodes, {len(graph['edges'])} proposed connections)")
        except Exception as exc:
            QMessageBox.warning(self, "Graph not saved", f"{type(exc).__name__}: {exc}")

    def export(self, fmt: str) -> None:
        from ..engineering.reports import make_report, save_report
        ids = None
        if self.scope.currentIndex() == 1:
            if not self.ctx.current_extraction_id:
                QMessageBox.information(self, "No drawing open", "Open a drawing first.")
                return
            ids = [self.ctx.current_extraction_id]
        dest, _ = QFileDialog.getSaveFileName(self, "Save report", f"drawing_readings.{fmt}", f"{fmt.upper()} (*.{fmt})")
        if not dest:
            return
        try:
            doc = make_report(self.ctx.db, extraction_ids=ids)
            save_report(doc, dest, fmt=fmt, overwrite=True)
            self.ctx.info(f"Report saved: {dest} ({doc['summary']['reading_count']} readings).")
        except Exception as exc:
            QMessageBox.warning(self, "Report not saved", str(exc))


class AuditTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        b = QPushButton("Verify audit chain")
        b.clicked.connect(self.verify)
        row.addWidget(b)
        bk = QPushButton("Back up project…")
        bk.clicked.connect(ctx.backup_project)
        row.addWidget(bk)
        self.result = QLabel("")
        row.addWidget(self.result, 1)
        lay.addLayout(row)
        self.table = _table(["#", "UTC", "Event", "Entity"])
        lay.addWidget(self.table, 1)

    def refresh(self) -> None:
        rows = [[r["event_id"], r["created_utc"], r["event_type"], r["entity_id"][:40]] for r in
                self.ctx.db.db.execute("SELECT event_id,created_utc,event_type,entity_id FROM audit_event "
                                       "ORDER BY event_id DESC LIMIT 500")]
        _fill(self.table, rows)

    def verify(self) -> None:
        ok = self.ctx.db.verify_audit_chain()
        self.result.setText("Audit hash chain intact." if ok else "AUDIT CHAIN BROKEN — records were altered.")
        self.result.setStyleSheet("color: #2e7d32" if ok else "color: #c62828; font-weight: bold")
