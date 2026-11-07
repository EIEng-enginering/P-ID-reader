"""Optional development PySide6 viewer, imported only when the GUI is requested.

Shows actual PDF pages and extraction rectangles where the source PDF is supplied.
No software proposal is silently accepted. Not yet verified on real Windows.
"""
from __future__ import annotations
import json
from pathlib import Path


def run_ui(database: str) -> int:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
        QSplitter, QListWidget, QTextEdit, QPushButton, QFileDialog,
        QMessageBox, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
        QGraphicsRectItem, QInputDialog, QTabWidget, QTableView, QLineEdit,
        QComboBox, QLabel, QAbstractItemView,
    )
    from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QRectF
    from PySide6.QtGui import QPixmap, QColor, QPen, QBrush, QImage
    from ..api import ReadParams, read_pid
    from ..engineering.project import ProjectStore
    from ..engineering.topology import analyze_pdf_topology
    from ..engineering.symbols import build_symbol_proposals
    from ..engineering.linework import build_linework_proposals
    from ..engineering.workspace import register_page, drawing_graph_view, crosssheet_graph_view
    from ..engineering.reports import make_report, save_report

    class ReadonlyTableModel(QAbstractTableModel):
        """Virtualisable Qt model; holds only the current database page in memory."""
        def __init__(self, columns, parent=None):
            super().__init__(parent)
            self.columns=columns  # (label, field_name)
            self.rows=[]

        def rowCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else len(self.rows)

        def columnCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else len(self.columns)

        def data(self, index, role=Qt.DisplayRole):
            if not index.isValid() or role != Qt.DisplayRole:
                return None
            value=self.rows[index.row()].get(self.columns[index.column()][1])
            if isinstance(value,(dict,list)):
                return json.dumps(value,ensure_ascii=False)
            return "" if value is None else str(value)

        def headerData(self, section, orientation, role=Qt.DisplayRole):
            if role == Qt.DisplayRole and orientation == Qt.Horizontal:
                return self.columns[section][0]
            return None

        def replace(self, rows):
            self.beginResetModel()
            self.rows=list(rows)
            self.endResetModel()

    class ReaderWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.db=ProjectStore(database)
            self.setWindowTitle("P&ID Reader — Development Preview (proposals only)")
            self.resize(1350,820)
            self.objects=[]
            self.current_result=None
            self.current_pdf=None
            self.current_extraction_id=None
            self.topology_analysis_id=None
            self.topology_candidates=[]
            self.highlighted_contact=None
            self.symbol_analysis_id=None
            self.symbol_candidates=[]
            self.highlighted_symbol=None
            self.linework_analysis_id=None
            self.linework_candidates=[]
            self.highlighted_linework=None
            self.text_link_analysis_id=None
            self.text_link_proposals=[]
            self.highlighted_text_link=None
            self.project_drawings=[]
            self.register_offset=0
            self.register_rows=[]
            self.graph_rows=[]
            self.register_bbox=None
            self.register_page_no=None
            self.register_total=0
            root=QWidget()
            layout=QVBoxLayout(root)
            bar=QHBoxLayout()
            open_button=QPushButton("Import a vector PDF")
            open_button.clicked.connect(self.open_pdf)
            bar.addWidget(open_button)
            inspect_btn=QPushButton("Inspect vector junctions (unverified)")
            inspect_btn.clicked.connect(self.inspect_geometry)
            bar.addWidget(inspect_btn)
            symbols_btn=QPushButton("Inspect outline symbols (unverified)")
            symbols_btn.clicked.connect(self.inspect_symbols)
            bar.addWidget(symbols_btn)
            linework_btn=QPushButton("Inspect valve and line styles (unverified)")
            linework_btn.clicked.connect(self.inspect_linework)
            bar.addWidget(linework_btn)
            text_btn=QPushButton("Show saved OCR/tag links")
            text_btn.clicked.connect(self.inspect_text_links)
            bar.addWidget(text_btn)
            save_meta_btn=QPushButton("Register source in project")
            save_meta_btn.clicked.connect(self.register_current_drawing)
            bar.addWidget(save_meta_btn)
            refresh_project_btn=QPushButton("Refresh drawing set")
            refresh_project_btn.clicked.connect(self.refresh_drawing_catalogue)
            bar.addWidget(refresh_project_btn)
            bar.addStretch()
            layout.addLayout(bar)
            split=QSplitter(Qt.Horizontal)
            self.lst=QListWidget();self.lst.setMinimumWidth(280)
            self.lst.currentRowChanged.connect(self.select_record)
            self.contact_lst=QListWidget()
            self.contact_lst.currentRowChanged.connect(self.select_contact)
            self.symbol_lst=QListWidget()
            self.symbol_lst.currentRowChanged.connect(self.select_symbol)
            self.linework_lst=QListWidget()
            self.linework_lst.currentRowChanged.connect(self.select_linework)
            self.text_lst=QListWidget()
            self.text_lst.currentRowChanged.connect(self.select_text_link)
            tabs=QTabWidget();tabs.addTab(self.lst,"Extracted objects")
            tabs.addTab(self.contact_lst,"Geometry candidates")
            tabs.addTab(self.symbol_lst,"Symbol outlines")
            tabs.addTab(self.linework_lst,"Valve / line styles")
            tabs.addTab(self.text_lst,"OCR / tag links")
            self.project_lst=QListWidget()
            self.project_lst.itemDoubleClicked.connect(self.open_registered_drawing)
            tabs.addTab(self.project_lst,"Project drawings")
            # Rev P: search and pagination use the reusable, Qt-free workspace API.
            register_panel=QWidget(); reglayout=QVBoxLayout(register_panel)
            self.reg_search=QLineEdit()
            self.reg_search.setPlaceholderText("Filter original tag or text")
            reglayout.addWidget(self.reg_search)
            self.reg_state=QComboBox()
            self.reg_state.addItems(["All states","PROPOSED","ACCEPTED_AS_READING",
                                     "EDITED_AND_ACCEPTED","REJECTED","IGNORED_REGION"])
            reglayout.addWidget(self.reg_state)
            self.reg_table=QTableView()
            self.reg_model=ReadonlyTableModel([("Tag / text","tag_text"),
                ("Class","object_class"),("Page","page"),("Drawing","drawing_no"),
                ("Review","state")])
            self.reg_table.setModel(self.reg_model)
            self.reg_table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.reg_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.reg_table.setAlternatingRowColors(True)
            self.reg_table.clicked.connect(self.select_register_row)
            self.reg_table.horizontalHeader().setStretchLastSection(True)
            reglayout.addWidget(self.reg_table)
            reg_buttons=QHBoxLayout()
            reg_find=QPushButton("Find");reg_find.clicked.connect(self.search_register)
            reg_buttons.addWidget(reg_find)
            reg_prev=QPushButton("Previous");reg_prev.clicked.connect(self.previous_register_page)
            reg_buttons.addWidget(reg_prev)
            reg_next=QPushButton("Next");reg_next.clicked.connect(self.next_register_page)
            reg_buttons.addWidget(reg_next)
            reglayout.addLayout(reg_buttons)
            self.reg_page_label=QLabel("Source readings only")
            reglayout.addWidget(self.reg_page_label)
            tabs.addTab(register_panel,"Engineering register")
            # Read-only graph edge list. Edge status stays SOURCE_PROPOSAL_UNVERIFIED.
            graph_panel=QWidget();graph_layout=QVBoxLayout(graph_panel)
            self.graph_scope=QComboBox()
            self.graph_scope.addItems(["Current source", "Entire project", "Cross-sheet proposals"])
            graph_layout.addWidget(self.graph_scope)
            graph_btn=QPushButton("Refresh proposed graph")
            graph_btn.clicked.connect(self.refresh_graph)
            graph_layout.addWidget(graph_btn)
            self.graph_table=QTableView()
            self.graph_model=ReadonlyTableModel([("From","from_text"),
                ("To","to_text"),("Type","connection_type"),("Extraction","extraction_id")])
            self.graph_table.setModel(self.graph_model)
            self.graph_table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.graph_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.graph_table.clicked.connect(self.select_graph_edge)
            self.graph_table.horizontalHeader().setStretchLastSection(True)
            graph_layout.addWidget(self.graph_table)
            tabs.addTab(graph_panel,"Graph explorer")
            # Drawing comparison uses the immutable snapshots and never transfers acceptance.
            revision_panel=QWidget();revision_layout=QVBoxLayout(revision_panel)
            self.revision_before=QComboBox();self.revision_after=QComboBox()
            revision_layout.addWidget(QLabel("Before drawing revision"))
            revision_layout.addWidget(self.revision_before)
            revision_layout.addWidget(QLabel("After drawing revision"))
            revision_layout.addWidget(self.revision_after)
            rev_button=QPushButton("Compare selected source revisions")
            rev_button.clicked.connect(self.compare_selected_revisions)
            revision_layout.addWidget(rev_button)
            self.revision_details=QTextEdit();self.revision_details.setReadOnly(True)
            revision_layout.addWidget(self.revision_details)
            tabs.addTab(revision_panel,"Revision comparison")
            # Standalone, offline, source-linked exports. No safety approval claims.
            report_panel=QWidget(); report_layout=QVBoxLayout(report_panel)
            self.report_scope=QComboBox()
            self.report_scope.addItems(["Entire project","Current source only"])
            report_layout.addWidget(self.report_scope)
            for fmt in ("html","csv","json"):
                btn=QPushButton("Export drawing-readings report ("+fmt.upper()+")")
                btn.clicked.connect(lambda checked=False, kind=fmt:self.export_project_report(kind))
                report_layout.addWidget(btn)
            report_layout.addWidget(QLabel("Exports are source readings; no plant verification."))
            tabs.addTab(report_panel,"Reports")
            tabs.setMinimumWidth(330)
            split.addWidget(tabs)
            self.scene=QGraphicsScene()
            self.view=QGraphicsView(self.scene)
            split.addWidget(self.view)
            right=QWidget(); right_layout=QVBoxLayout(right)
            self.detail=QTextEdit(); self.detail.setReadOnly(True)
            right_layout.addWidget(self.detail)
            accepted=QPushButton("Accept reading (named reviewer)")
            accepted.clicked.connect(self.accept_selected)
            right_layout.addWidget(accepted)
            mark=QPushButton("Review selected junction (as drawn)")
            mark.clicked.connect(self.review_selected_contact)
            right_layout.addWidget(mark)
            symreview=QPushButton("Review selected symbol (as drawn)")
            symreview.clicked.connect(self.review_selected_symbol)
            right_layout.addWidget(symreview)
            lreview=QPushButton("Review selected valve/line candidate (as drawn)")
            lreview.clicked.connect(self.review_selected_linework)
            right_layout.addWidget(lreview)
            treview=QPushButton("Review selected OCR/tag link")
            treview.clicked.connect(self.review_selected_text_link)
            right_layout.addWidget(treview)
            split.addWidget(right)
            split.setSizes([280,780,290])
            layout.addWidget(split)
            self.setCentralWidget(root)
            self.statusBar().showMessage("Readings are proposals from software. Nothing here verifies the drawing or the plant.")
            self.refresh_drawing_catalogue()
            self.refresh_register()

        def refresh_register(self):
            try:
                state=self.reg_state.currentText()
                state="" if state=="All states" else state
                page=register_page(self.db,text=self.reg_search.text().strip(),state=state,
                                   limit=100,offset=self.register_offset)
                self.register_total=page["total"]
                self.register_rows=page["rows"]
                self.reg_model.replace(self.register_rows)
                self.reg_page_label.setText(
                    f"{self.register_offset+1 if self.register_rows else 0}-"
                    f"{self.register_offset+len(self.register_rows)} of {self.register_total} "
                    "(unverified source readings)")
            except Exception as exc:
                QMessageBox.warning(self,"Register unavailable",str(exc))

        def search_register(self):
            self.register_offset=0
            self.refresh_register()

        def previous_register_page(self):
            self.register_offset=max(0,self.register_offset-100)
            self.refresh_register()

        def next_register_page(self):
            if self.register_offset+100<self.register_total:
                self.register_offset+=100
                self.refresh_register()

        def select_register_row(self,index):
            if not index.isValid() or not 0<=index.row()<len(self.register_rows):return
            row=self.register_rows[index.row()]
            try:
                origin=self.db.get_object(row["observation_id"])
                review=self.db.effective_review(row["observation_id"])
                self.detail.setPlainText(json.dumps({"source":row,"observation":origin,
                                                    "latest_review":review},indent=2))
                eid=row["extraction_id"]
                source=self.db.get_source_pdf(row["document_sha256"])
                if source is None:
                    self.statusBar().showMessage("Source bytes not embedded; evidence hash and coordinates available.")
                    return
                if eid!=self.current_extraction_id:
                    self.current_extraction_id=eid
                    self.current_result=self.db.export_extraction(eid)
                    self.current_pdf=source
                    self.objects=self.current_result["objects"]
                    self.lst.clear()
                    self.lst.addItems([f"p{o['page']} {o['class']} {o['text'][:55]}" for o in self.objects])
                self.register_bbox=row["bbox"]
                self.register_page_no=row["page"]
                self.render_page(row["page"])
            except Exception as exc:
                QMessageBox.warning(self,"Source selection refused",type(exc).__name__)

        def refresh_graph(self):
            try:
                scope=self.graph_scope.currentText()
                if scope=="Cross-sheet proposals":
                    response=crosssheet_graph_view(self.db,limit=200)
                    rows=[]
                    for r in response["rows"]:
                        rows.append({**r,"from_text":r["from_label"],"to_text":r["to_label"],
                                     "connection_type":"CROSS_SHEET_PROPOSAL", "extraction_id":r["from_extraction_id"]})
                else:
                    eid=self.current_extraction_id if scope=="Current source" else ""
                    if not eid and scope=="Current source":
                        QMessageBox.information(self,"Select a source first","Open a drawing first")
                        return
                    rows=drawing_graph_view(self.db,extraction_id=eid,limit=200)["rows"]
                self.graph_rows=rows
                self.graph_model.replace(rows)
                self.statusBar().showMessage(f"{len(rows)} proposed graph records. No confirmed plant connectivity.")
            except Exception as exc:
                QMessageBox.warning(self,"Graph query refused",str(exc))

        def select_graph_edge(self,index):
            if not index.isValid() or not 0<=index.row()<len(self.graph_rows):return
            row=self.graph_rows[index.row()]
            self.detail.setPlainText(json.dumps({"graph_proposal":row,
                "warning":"Drawing links only; physical connectivity not verified."},indent=2))
            try:
                if row.get("from_observation"):
                    source=self.db.db.execute("SELECT * FROM observation WHERE observation_id=?",
                        (row["from_observation"],)).fetchone()
                    if source:
                        source_hash=self.db.db.execute(
                            "SELECT document_sha256 FROM extraction WHERE extraction_id=?",
                            (source["extraction_id"],)).fetchone()[0]
                        pdf=self.db.get_source_pdf(source_hash)
                        if pdf:
                            self.current_pdf=pdf
                            self.current_extraction_id=source["extraction_id"]
                            self.current_result=self.db.export_extraction(self.current_extraction_id)
                            self.objects=self.current_result["objects"]
                            self.register_bbox=json.loads(source["bbox_json"])
                            self.register_page_no=source["page"]
                            self.render_page(source["page"])
            except Exception:
                self.statusBar().showMessage("Graph source could not be displayed; proposal data remains available.")

        def compare_selected_revisions(self):
            old=self.revision_before.currentData()
            new=self.revision_after.currentData()
            if not old or not new or old==new:
                QMessageBox.information(self,"Select two revisions","Choose two different drawing extractions.")
                return
            try:
                cid,data=self.db.compare_revisions(old,new)
                self.revision_details.setPlainText(json.dumps({"comparison_id":cid,
                    "source_state":data["source_state"],"events":data["events"],
                    "unmatched_before":data["unmatched_before"],
                    "unmatched_after":data["unmatched_after"],
                    "warning":"This compares source readings, not as-built engineering changes."},indent=2))
            except Exception as exc:
                QMessageBox.warning(self,"Revision comparison refused",str(exc))

        def export_project_report(self,kind):
            try:
                ids=([self.current_extraction_id] if self.report_scope.currentIndex()==1 else None)
                if ids is not None and not ids[0]:
                    QMessageBox.information(self,"Select a source first","Open a source drawing.")
                    return
                destination,_=QFileDialog.getSaveFileName(self,"Save unverified drawing-readings report", "",
                    f"{kind.upper()} Files (*.{kind})")
                if not destination:return
                document=make_report(self.db,extraction_ids=ids)
                save_report(document,destination,fmt=kind,overwrite=True)
                self.statusBar().showMessage(
                    f"Report saved ({document['summary']['reading_count']} source observations). No plant verification.")
            except Exception as exc:
                QMessageBox.warning(self,"Report not saved",str(exc))

        def refresh_drawing_catalogue(self):
            try:
                self.project_drawings=self.db.list_drawings(limit=1000)
                self.project_lst.clear()
                self.project_lst.addItems([
                    f"{x['drawing_no']} / Rev {x['revision_label']} | "
                    f"{x['facility']} - {x['area']} | {x['extraction_id'][-8:]}"
                    for x in self.project_drawings])
                for selector in (self.revision_before,self.revision_after):
                    prior=selector.currentData()
                    selector.blockSignals(True)
                    selector.clear()
                    for drawing in self.project_drawings:
                        selector.addItem(f"{drawing['drawing_no']} / Rev {drawing['revision_label']}",
                                         drawing['extraction_id'])
                    if prior:
                        index=selector.findData(prior)
                        if index>=0:selector.setCurrentIndex(index)
                    selector.blockSignals(False)
                self.refresh_register()
                self.project_lst.setToolTip(
                    "Double-click to inspect an explicitly registered drawing revision. "
                    "Registration is not proof that a drawing is current or as-built.")
            except Exception as exc:
                QMessageBox.warning(self,"Catalogue not available",type(exc).__name__)

        def register_current_drawing(self):
            if not self.current_extraction_id:
                QMessageBox.information(self,"Import first","Open a source PDF before registering it.")
                return
            prompts=[('drawing_no','Drawing number'),('revision_label','Drawing revision as printed'),
                     ('facility','Facility'),('area','Area / unit'),('actor','Reviewer display name'),
                     ('reason','Reason for this catalogue entry')]
            values={}
            for key,title in prompts:
                val,ok=QInputDialog.getText(self,"Drawing catalogue",title)
                if not ok:return
                values[key]=val
            try:
                self.db.register_drawing(self.current_extraction_id,**values)
                self.refresh_drawing_catalogue()
                self.statusBar().showMessage(
                    "Drawing reference saved with source hash. Neither current revision nor plant status is verified.")
            except Exception as exc:
                QMessageBox.warning(self,"Registration refused",str(exc))

        def open_registered_drawing(self, selected_item):
            i=self.project_lst.row(selected_item)
            if not 0<=i<len(self.project_drawings):return
            record=self.project_drawings[i]
            try:
                extraction=self.db.export_extraction(record['extraction_id'])
                source=self.db.get_source_pdf(extraction['document']['sha256'])
                if source is None:
                    QMessageBox.warning(self,"Source unavailable",
                        "Original PDF bytes were not embedded; use the extraction record and source hash instead.")
                    return
                self.register_bbox=None;self.register_page_no=None
                self.current_extraction_id=record['extraction_id']
                self.current_pdf=source
                self.current_result=extraction
                self.objects=extraction['objects']
                self.lst.clear()
                self.lst.addItems([f"p{obj['page']} {obj['class']} {obj['text'][:55]}" for obj in self.objects])
                self.topology_analysis_id=None;self.topology_candidates=[];self.highlighted_contact=None
                self.symbol_analysis_id=None;self.symbol_candidates=[];self.highlighted_symbol=None
                self.linework_analysis_id=None;self.linework_candidates=[];self.highlighted_linework=None
                self.text_link_analysis_id=None;self.text_link_proposals=[];self.highlighted_text_link=None
                self.contact_lst.clear();self.symbol_lst.clear();self.linework_lst.clear();self.text_lst.clear()
                self.render_page(1)
                self.detail.setPlainText(json.dumps({
                    'kind':'REGISTERED_SOURCE_DRAWING',
                    'drawing_no':record['drawing_no'],'revision_label':record['revision_label'],
                    'source_sha256':record['document_sha256'],
                    'extraction_id':record['extraction_id'],
                    'warning':'Reading a nominated drawing revision is not verification of the actual plant.'},indent=2))
                self.statusBar().showMessage("Source drawing opened from project. No plant verification.")
            except Exception as exc:
                QMessageBox.warning(self,"Drawing could not be opened",type(exc).__name__)

        def open_pdf(self):
            path,_=QFileDialog.getOpenFileName(self,"Import P&ID PDF", "", "PDF (*.pdf)")
            if not path:
                return
            try:
                data=Path(path).read_bytes()
                result=read_pid(data,ReadParams(),filename=Path(path).name)
                self.current_extraction_id=self.db.add_extraction(result,source_pdf_bytes=data)
                self.topology_candidates=[]
                self.topology_analysis_id=None
                self.highlighted_contact=None
                self.symbol_analysis_id=None
                self.symbol_candidates=[]
                self.highlighted_symbol=None
                self.symbol_lst.clear()
                self.linework_lst.clear()
                self.linework_analysis_id=None
                self.linework_candidates=[]
                self.highlighted_linework=None
                self.contact_lst.clear()
                self.text_link_analysis_id=None
                self.text_link_proposals=[]
                self.highlighted_text_link=None
                self.text_lst.clear()
                self.register_bbox=None;self.register_page_no=None
                self.current_pdf=data
                self.current_result=result
                self.objects=result["objects"]
                self.lst.clear()
                self.lst.addItems([f"p{it['page']}  {it['class']}  {it['text'][:55]}" for it in self.objects])
                self.render_page(1)
                self.refresh_register()
                self.statusBar().showMessage(f"{len(self.objects)} unverified proposals; {len(result['warnings'])} warnings. No plant verification.")
            except Exception as exc:
                QMessageBox.warning(self,"PDF import could not finish",type(exc).__name__)

        def render_page(self,number: int):
            self.scene.clear()
            if not self.current_pdf:
                return
            try:
                import pypdfium2 as pdfium
                pdf=pdfium.PdfDocument(self.current_pdf)
                pg=pdf[number-1]
                scale=min(2.0,2000.0/max(pg.get_size()))
                bmp=pg.render(scale=scale)
                img=bmp.to_pil().convert("RGBA")
                raw=img.tobytes("raw","RGBA")
                qi=QImage(raw,img.width,img.height,QImage.Format_RGBA8888).copy()
                self.scene.addPixmap(QPixmap.fromImage(qi))
                w,h=img.width,img.height
                for it in self.objects:
                    if it["page"] != number:
                        continue
                    bb=it["bbox"]
                    rec=self.scene.addRect(bb["x0"]*w,bb["y0"]*h,(bb["x1"]-bb["x0"])*w,(bb["y1"]-bb["y0"])*h,
                                           QPen(QColor(32,125,215),1),QBrush(Qt.NoBrush))
                    rec.setToolTip(it["class"] + " " + it["text"])
                if self.highlighted_contact and self.highlighted_contact["geometry"]["page"]==number:
                    contact=self.highlighted_contact["geometry"]
                    xy=contact["point"]
                    self.scene.addEllipse(xy[0]*w-7,xy[1]*h-7,14,14,
                                          QPen(QColor(210,65,35),2),QBrush(Qt.NoBrush))
                if self.highlighted_symbol and self.highlighted_symbol["candidate"]["page"]==number:
                    box=self.highlighted_symbol["candidate"]["bbox"]
                    self.scene.addRect(box["x0"]*w,box["y0"]*h,
                                       (box["x1"]-box["x0"])*w,(box["y1"]-box["y0"])*h,
                                       QPen(QColor(168,72,186),3),QBrush(Qt.NoBrush))
                if self.highlighted_linework and self.highlighted_linework["candidate"]["page"]==number:
                    item=self.highlighted_linework["candidate"]
                    if item.get("bbox"):
                        box=item["bbox"]
                        self.scene.addRect(box["x0"]*w,box["y0"]*h,
                            (box["x1"]-box["x0"])*w,(box["y1"]-box["y0"])*h,
                            QPen(QColor(210,128,30),3),QBrush(Qt.NoBrush))
                    # Mixed-style contacts may have no bbox in the standalone
                    # result. Their source contact is selectable in Geometry.
                if self.highlighted_text_link and self.highlighted_text_link['page']==number:
                    box=self.highlighted_text_link['proposal']['bbox']
                    self.scene.addRect(box['x0']*w,box['y0']*h,(box['x1']-box['x0'])*w,(box['y1']-box['y0'])*h,
                        QPen(QColor(54,160,95),3),QBrush(Qt.NoBrush))
                self.view.fitInView(self.scene.sceneRect(),Qt.KeepAspectRatio)
                if self.register_bbox and self.register_page_no==number:
                    box=self.register_bbox
                    rect=QRectF(box["x0"]*w,box["y0"]*h,
                                max(1,(box["x1"]-box["x0"])*w),
                                max(1,(box["y1"]-box["y0"])*h))
                    self.scene.addRect(rect,QPen(QColor(215,60,25),3),QBrush(Qt.NoBrush))
                    pad=max(45,min(w,h)*.08)
                    self.view.fitInView(rect.adjusted(-pad,-pad,pad,pad),Qt.KeepAspectRatio)
            except ImportError:
                self.scene.addText("Optional pypdfium2 rendering package not available.")

        def select_record(self,index: int):
            if index<0 or index>=len(self.objects):
                return
            item=self.objects[index]
            self.detail.setPlainText(json.dumps(item,indent=2))
            self.render_page(item["page"])

        def inspect_geometry(self):
            if not self.current_pdf or not self.current_extraction_id:
                QMessageBox.information(self,"Source needed","Import a PDF first.")
                return
            try:
                pages=tuple(x["page"] for x in self.current_result["pages"])
                result=analyze_pdf_topology(self.current_pdf,pages=pages)
                aid=self.db.add_geometry_analysis(self.current_extraction_id,result)
                self.topology_analysis_id=aid
                self.symbol_analysis_id=None
                self.symbol_candidates=[]
                self.highlighted_symbol=None
                self.symbol_lst.clear()
                self.linework_analysis_id=None
                self.linework_candidates=[]
                self.highlighted_linework=None
                self.linework_lst.clear()
                self.topology_candidates=self.db.list_geometry_candidates(aid,limit=2000)
                self.contact_lst.clear()
                self.contact_lst.addItems([f"p{x['page']}  {x['kind']}  {x['candidate_id'][-8:]}"
                                           for x in self.topology_candidates])
                self.statusBar().showMessage(
                    f"{len(result['contact_candidates'])} unresolved geometric contacts. "
                    "Neither drawing nor physical plant connectivity has been verified.")
            except Exception as exc:
                QMessageBox.warning(self,"Topology analysis could not finish",type(exc).__name__)

        def inspect_symbols(self):
            if not self.current_pdf or not self.current_extraction_id:
                QMessageBox.information(self,"Source needed","Import a PDF first.")
                return
            try:
                if not self.topology_analysis_id:
                    self.inspect_geometry()
                if not self.topology_analysis_id:
                    return
                extraction=self.db.export_extraction(self.current_extraction_id)
                topology=self.db.get_geometry_analysis(self.topology_analysis_id)
                result=build_symbol_proposals(extraction,topology)
                aid=self.db.add_symbol_analysis(self.current_extraction_id,self.topology_analysis_id,result)
                self.symbol_analysis_id=aid
                self.linework_analysis_id=None
                self.linework_candidates=[]
                self.highlighted_linework=None
                self.linework_lst.clear()
                self.symbol_candidates=self.db.list_symbol_candidates(aid,limit=2000)
                self.symbol_lst.clear()
                self.symbol_lst.addItems([f"p{x['page']} {x['candidate_class']} {x['candidate_id'][-8:]}"
                                          for x in self.symbol_candidates])
                self.statusBar().showMessage(f"{len(result['symbol_candidates'])} unverified outline proposals; "
                    f"{len(result['port_candidates'])} possible outline endpoint contacts. No plant verification.")
            except Exception as exc:
                QMessageBox.warning(self,"Symbol proposal analysis refused",type(exc).__name__)

        def inspect_linework(self):
            if not self.current_pdf or not self.current_extraction_id:
                QMessageBox.information(self,"Source needed","Import a PDF first.")
                return
            try:
                if not self.symbol_analysis_id:
                    self.inspect_symbols()
                if not self.symbol_analysis_id:
                    return
                extraction=self.db.export_extraction(self.current_extraction_id)
                topology=self.db.get_geometry_analysis(self.topology_analysis_id)
                symbols=self.db.get_symbol_analysis(self.symbol_analysis_id)
                result=build_linework_proposals(extraction,topology,symbols)
                self.linework_analysis_id=self.db.add_linework_analysis(
                    self.current_extraction_id,self.topology_analysis_id,self.symbol_analysis_id,result)
                self.linework_candidates=self.db.list_linework_candidates(self.linework_analysis_id,limit=2000)
                self.linework_lst.clear()
                self.linework_lst.addItems([f"p{x['page']} {x['kind']} {x['candidate_id'][-8:]}"
                    for x in self.linework_candidates])
                self.statusBar().showMessage(
                    f"{len(result['valve_candidates'])} valve-shaped outlines and "
                    f"{len(result['mixed_style_contacts'])} unresolved mixed-style intersections. "
                    "Graphical proposals only; plant connectivity not verified.")
            except Exception as exc:
                QMessageBox.warning(self,"Linework analysis refused",type(exc).__name__)

        def inspect_text_links(self):
            """Display already computed OCR proposals; never blocks GUI running OCR."""
            if not self.current_extraction_id:
                QMessageBox.information(self,"Source needed","Import a PDF first.")
                return
            try:
                rows=self.db.db.execute(
                    "SELECT analysis_id FROM text_link_analysis WHERE extraction_id=? "
                    "ORDER BY imported_utc DESC,analysis_id DESC LIMIT 1",(self.current_extraction_id,)).fetchall()
                if not rows:
                    QMessageBox.information(self,"No OCR/tag links saved",
                        "Run the offline CLI 'import-ocr' then 'analyze-text-links' against this project, "
                        "and reopen/refresh this view. OCR is intentionally not run synchronously in the GUI.")
                    return
                self.text_link_analysis_id=rows[0][0]
                self.text_link_proposals=self.db.list_text_link_proposals(self.text_link_analysis_id,limit=2000)
                self.text_lst.clear()
                self.text_lst.addItems([
                    f"p{x['page']} {x['proposal']['association_state']} | " +
                    ", ".join(z['text_candidate'] for z in x['proposal']['options'][:3])
                    for x in self.text_link_proposals])
                self.statusBar().showMessage(
                    f"{len(self.text_link_proposals)} source-linked OCR/tag proposals. Readings are not plant verification.")
            except Exception as exc:
                QMessageBox.warning(self,"OCR review not available",type(exc).__name__)

        def select_text_link(self,index: int):
            if index<0 or index>=len(self.text_link_proposals):return
            item=self.text_link_proposals[index]
            self.highlighted_text_link=item
            details=self.db.symbol_evidence(self.text_link_analysis_id,item['symbol_candidate_id'])
            self.detail.setPlainText(json.dumps(details,indent=2))
            self.render_page(item['page'])

        def review_selected_text_link(self):
            index=self.text_lst.currentRow()
            if index<0 or index>=len(self.text_link_proposals):
                QMessageBox.information(self,"Select OCR/tag link","Select a proposed text association first.")
                return
            item=self.text_link_proposals[index]
            actor,ok=QInputDialog.getText(self,"Human review","Reviewer display name")
            if not ok or not actor.strip():return
            decision,ok=QInputDialog.getItem(self,"Text association review",
                "Decision about this source drawing reading:",
                ["ACCEPTED_AS_READING","EDITED_AND_ACCEPTED","REJECTED","UNRESOLVED"],3,False)
            if not ok:return
            text=None
            if decision=='ACCEPTED_AS_READING':
                options=[x['text_candidate'] for x in item['proposal']['options']]
                if not options:
                    QMessageBox.information(self,"No candidate text","Choose edit or unresolved instead.")
                    return
                text,ok=QInputDialog.getItem(self,"Source reading","Select the source-backed text",options,0,False)
                if not ok:return
            elif decision=='EDITED_AND_ACCEPTED':
                text,ok=QInputDialog.getText(self,"Corrected drawing reading","Corrected tag/text (source drawing only)")
                if not ok:return
            reason,ok=QInputDialog.getText(self,"Review reason","Evidence and reason (at least five characters)")
            if not ok:return
            try:
                self.db.review_text_link(item['proposal_id'],actor=actor,decision=decision,
                                         selected_text=text,reason=reason)
                self.select_text_link(index)
                self.statusBar().showMessage('OCR/tag review recorded for this drawing revision; no plant verification.')
            except Exception as exc:
                QMessageBox.warning(self,"Text review not saved",type(exc).__name__)

        def select_linework(self,index: int):
            if index<0 or index>=len(self.linework_candidates):
                return
            item=self.linework_candidates[index]
            self.highlighted_linework=item
            decision=self.db.latest_linework_review(item['candidate_id'])
            self.detail.setPlainText(json.dumps({"proposal":item['candidate'],"latest_review":decision},indent=2))
            self.render_page(item['page'])

        def review_selected_linework(self):
            index=self.linework_lst.currentRow()
            if index<0 or index>=len(self.linework_candidates):
                QMessageBox.information(self,"Select a candidate","Choose an unverified linework proposal first.")
                return
            actor,ok=QInputDialog.getText(self,"Human drawing review","Reviewer display name")
            if not ok or not actor.strip():return
            decision,ok=QInputDialog.getItem(self,"Linework review",
                "What does the source drawing depict (not actual plant status)?",
                ["ACCEPTED_AS_READING","REJECTED","UNRESOLVED"],2,False)
            if not ok:return
            reason,ok=QInputDialog.getText(self,"Review reason","Evidence or reason (minimum five characters)")
            if not ok:return
            try:
                item=self.linework_candidates[index]
                self.db.review_linework(item['candidate_id'],actor=actor,decision=decision,reason=reason)
                self.select_linework(index)
                self.statusBar().showMessage("Linework review recorded as a drawing reading, not verification of the plant.")
            except Exception as exc:
                QMessageBox.warning(self,"Linework review not saved",type(exc).__name__)

        def select_symbol(self,index: int):
            if index<0 or index>=len(self.symbol_candidates):
                return
            item=self.symbol_candidates[index]
            self.highlighted_symbol=item
            decision=self.db.latest_symbol_review(item['candidate_id'])
            self.detail.setPlainText(json.dumps({"proposal":item['candidate'],"latest_review":decision},indent=2))
            self.render_page(item['page'])

        def review_selected_symbol(self):
            index=self.symbol_lst.currentRow()
            if index<0 or index>=len(self.symbol_candidates):
                QMessageBox.information(self,"Select a symbol","Choose a symbol outline proposal first.")
                return
            actor,ok=QInputDialog.getText(self,"Human drawing review","Reviewer display name")
            if not ok or not actor.strip():return
            decision,ok=QInputDialog.getItem(self,"Symbol outline decision",
                "Do you accept this reading of the drawing (not the physical plant)?",
                ["ACCEPTED_AS_READING","REJECTED","UNRESOLVED"],2,False)
            if not ok:return
            reason,ok=QInputDialog.getText(self,"Review reason","Evidence or reason (minimum five characters)")
            if not ok:return
            try:
                item=self.symbol_candidates[index]
                self.db.review_symbol(item['candidate_id'],actor=actor,decision=decision,reason=reason)
                self.select_symbol(index)
                self.statusBar().showMessage("Symbol reading recorded for this drawing revision, not verified in the plant.")
            except Exception as exc:
                QMessageBox.warning(self,"Review could not be saved",type(exc).__name__)

        def select_contact(self,index: int):
            if index<0 or index>=len(self.topology_candidates):
                return
            item=self.topology_candidates[index]
            self.highlighted_contact=item
            review=self.db.latest_geometry_decision(item["candidate_id"])
            self.detail.setPlainText(json.dumps({"proposal":item["geometry"],"latest_review":review},indent=2))
            self.render_page(item["page"])

        def review_selected_contact(self):
            index=self.contact_lst.currentRow()
            if index<0 or index>=len(self.topology_candidates):
                QMessageBox.information(self,"Select a junction","Choose a geometry candidate first.")
                return
            actor,ok=QInputDialog.getText(self,"Human drawing review","Reviewer display name")
            if not ok or not actor.strip():return
            decision,ok=QInputDialog.getItem(self,"Drawing geometry decision",
                "What do the lines depict in this drawing (not the actual plant)?",
                ["CONNECTED_AS_DRAWN","NOT_CONNECTED_AS_DRAWN","UNRESOLVED","REJECTED"],2,False)
            if not ok:return
            reason,ok=QInputDialog.getText(self,"Reason required","Drawing evidence / review reason")
            if not ok:return
            try:
                item=self.topology_candidates[index]
                self.db.review_geometry(item["candidate_id"],actor=actor,decision=decision,reason=reason)
                self.select_contact(index)
                self.statusBar().showMessage("Human decision recorded as a drawing reading, not plant verification.")
            except Exception as exc:
                QMessageBox.warning(self,"Review not saved",type(exc).__name__)

        def accept_selected(self):
            index=self.lst.currentRow()
            if index<0 or not self.current_result:
                return
            actor,ok=QInputDialog.getText(self,"Human review","Reviewer display name")
            if not ok or not actor.strip():
                return
            import hashlib
            from ..api import canonical_json
            eid="ext-"+hashlib.sha256(canonical_json([self.current_result["document"]["sha256"], self.current_result["provenance"]["result_sha256"]]).encode()).hexdigest()[:24]
            item=self.objects[index]
            oid="obs-"+hashlib.sha256(canonical_json([eid,item["id"]]).encode()).hexdigest()[:24]
            try:
                self.db.review(oid,actor=actor,decision="ACCEPTED_AS_READING",reason="Accepted as reading of source revision")
                QMessageBox.information(self,"Reading recorded","Accepted as a reading of the drawing revision; not an assertion about the plant.")
                self.refresh_register()
            except Exception as exc:
                QMessageBox.warning(self,"Review could not be recorded",type(exc).__name__)

        def closeEvent(self,event):
            self.db.close()
            super().closeEvent(event)

    app=QApplication.instance() or QApplication([])
    window=ReaderWindow();window.show()
    return app.exec()
