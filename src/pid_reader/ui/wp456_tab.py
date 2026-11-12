"""Additive WP04–06 Windows tab; worker tasks, page guards, separate review DB."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QCheckBox,
                               QTableWidget,QTableWidgetItem,QPlainTextEdit,QFileDialog,QMessageBox,
                               QInputDialog,QComboBox,QAbstractItemView)
from ..engineering.wp456 import host
from ..engineering.wp456.common import canonical,verify_seal
from ..engineering.wp456.pipeline import export
from ..engineering.wp456.store import Store,targets
from ..engineering import wp123_session as S


class Wp456Tab(QWidget):
    def __init__(self,main):
        super().__init__(); self.main=main; self.result=None; self.analysis_id=None; self.rows=[]; self.geometry=None; self.symbol_evidence=[]
        layout=QVBoxLayout(self)
        note=QLabel('WP04–06 development proposals. Text acceptance records printed readings only. '
                    'Symbol links and geometry remain drawing hypotheses. No Worksheet or project database writes.')
        note.setWordWrap(True); layout.addWidget(note)
        top=QHBoxLayout()
        self.build_button=QPushButton('Build WP04–06 proposals'); self.build_button.clicked.connect(lambda:self.build(False))
        top.addWidget(self.build_button)
        self.reread_button=QPushButton('Re-read selected region / automatic regions')
        self.reread_button.clicked.connect(lambda:self.build(True)); top.addWidget(self.reread_button)
        self.circles=QCheckBox('Scan instrument circles'); top.addWidget(self.circles)
        self.layout_profile=QComboBox(); self.layout_profile.addItem('Layout: automatic','auto'); self.layout_profile.addItem('Layout: none','none')
        top.addWidget(self.layout_profile); layout.addLayout(top)
        second=QHBoxLayout()
        self.geometry_button=QPushButton('Load classified geometry proposals…'); self.geometry_button.clicked.connect(self.load_geometry)
        second.addWidget(self.geometry_button)
        classify=QPushButton("Propose class for selected symbol box…"); classify.clicked.connect(self.propose_symbol_class); second.addWidget(classify)
        self.export_button=QPushButton('Export WP04–06 package…'); self.export_button.clicked.connect(self.export_result); second.addWidget(self.export_button)
        self.audit_button=QPushButton('Verify review chain'); self.audit_button.clicked.connect(self.audit); second.addWidget(self.audit_button)
        layout.addLayout(second)
        self.summary=QLabel('No WP04–06 proposals built.'); self.summary.setWordWrap(True); layout.addWidget(self.summary)
        self.table=QTableWidget(0,5); self.table.setHorizontalHeaderLabels(['Group','Proposal / state','Page','Review','ID'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.on_select)
        self.table.itemDoubleClicked.connect(lambda _item:self.show_on_drawing()); layout.addWidget(self.table)
        self.detail=QPlainTextEdit(); self.detail.setReadOnly(True); layout.addWidget(self.detail)
        actions=QHBoxLayout()
        for label,action in [('Accept printed reading','ACCEPTED_AS_READING'),('Correct printed reading','CORRECTED_READING'),
                             ('Support drawing hypothesis','SUPPORTED_AS_DRAWING_HYPOTHESIS'),('Reject','REJECTED'),('Unresolved','UNRESOLVED')]:
            button=QPushButton(label); button.clicked.connect(lambda checked=False,a=action:self.decide(a)); actions.addWidget(button)
        layout.addLayout(actions)
        self._busy=False

    def _store(self):
        path=host.store_path(); path.parent.mkdir(parents=True,exist_ok=True); return Store(path)

    def reset(self):
        self.result=None; self.analysis_id=None; self.rows=[]; self.geometry=None; self.symbol_evidence=[]
        self.table.setRowCount(0); self.detail.clear(); self.summary.setText('No WP04–06 proposals built.')

    def load_geometry(self):
        path,_=QFileDialog.getOpenFileName(self,'Geometry proposal envelope','','JSON (*.json)')
        if not path:return
        try:
            p=Path(path)
            if p.stat().st_size>8*1024*1024: raise ValueError('Geometry file too large')
            doc=json.loads(p.read_text(encoding='utf8'))
            if not self.main.current_pdf or doc.get('source_sha256')!=sha256(self.main.current_pdf).hexdigest():
                raise ValueError('Geometry source PDF does not match')
            if doc.get('frame')!='MEDIA_NORMALIZED_TOP_LEFT': raise ValueError('Geometry frame does not match')
            self.geometry=doc; self.summary.setText('Geometry proposals loaded; build to validate them.')
        except Exception as exc: QMessageBox.warning(self,'Cannot load geometry',str(exc))

    def propose_symbol_class(self):
        i=self.table.currentRow()
        if not self.result or not 0<=i<len(self.rows):return
        row=self.rows[i]
        if row['display_group']!='Symbol':
            QMessageBox.information(self,'Select symbol box','Select a source-linked symbol candidate box first.'); return
        kind,ok=QInputDialog.getItem(self,'Printed symbol class','Propose visible class:', ['EQUIPMENT','VALVE','INSTRUMENT'],0,False)
        if not ok:return
        actor=self.main.reviewer()
        if not actor:return
        reason,ok=QInputDialog.getText(self,'Evidence','Reason / visible symbol evidence:')
        if not ok or not reason.strip():return
        from ..engineering.wp456.common import ident
        evidence={'id':ident('reviewer-symbol',row['id'],kind,actor,reason),'page':row['page'],'bbox':row['bbox'],
                  'kind':kind,'actor':actor,'reason':reason,'evidence_ids':row['evidence_ids'],
                  'source_sha256':self.result['source_sha256']}
        self.symbol_evidence.append(evidence)
        self.summary.setText('Reviewer symbol class proposal queued. Build again to assess associations; no engineering object accepted.')

    def build(self,reread):
        m=self.main
        if self._busy:return
        if not m.current_pdf or not m.current_extraction_id:
            QMessageBox.information(self,'No drawing','Open and analyse a drawing first.'); return
        if reread:
            from ..engineering.wp456.ocr import locate_tesseract
            if not locate_tesseract():
                QMessageBox.information(self,'Tesseract unavailable','Install the local Tesseract OCR program or set TESSERACT_CMD.'); return
        if m.task is not None:
            QMessageBox.information(self,"Busy","Wait for the current task or cancel it first."); return
        pdf,page=m.current_pdf,m.page; source=sha256(pdf).hexdigest(); selected=None
        index=self.table.currentRow()
        if reread and 0<=index<len(self.rows) and self.rows[index].get('bbox'):
            row=self.rows[index]
            if row['page']!=page:
                QMessageBox.information(self,'Different page','Select a proposal on the open page.'); return
            selected={'page':page,'bbox':row['bbox']}
        try:
            words,_=S.words_from_project(m.db,m.current_extraction_id,page,m.current_result)
            detections,_=S.detections_for_page(pdf,page)
            geometry=self.geometry or {'segments':host.geometry_from_project(m.db,m.current_extraction_id,page,source)}
        except Exception as exc:
            QMessageBox.warning(self,'Cannot gather evidence',str(exc)); return
        circles=self.circles.isChecked(); profile=self.layout_profile.currentData()
        symbol_evidence=list(self.symbol_evidence)
        self._busy=True; self.build_button.setEnabled(False); self.reread_button.setEnabled(False)
        def job(report,is_cancelled):
            report(.1,'Building source-linked drawing proposals')
            return host.analyse(pdf,page,words,detections,scan_bubbles=circles,profile=profile,
                                reread_enabled=reread,selected=selected,cancelled=is_cancelled,
                                segments=geometry.get('segments'),ports=geometry.get('ports'),junctions=geometry.get('junctions'),symbol_evidence=symbol_evidence)
        def done(result):
            # A completed worker must never populate a newly opened drawing/page.
            if not m.current_pdf or sha256(m.current_pdf).hexdigest()!=source or m.page!=page: return
            self.result=result; st=self._store()
            try:self.analysis_id=st.add(result)
            finally:st.close()
            self.populate()
        if not m.run_task('WP04–06 proposals',job,done,on_finish=self._release):
            self._release()

    def _release(self):
        self._busy=False; self.build_button.setEnabled(True); self.reread_button.setEnabled(True)

    def populate(self):
        if not self.result:return
        r=self.result; self.rows=[]
        for group,items in [('Reading',r['wp04']['readings']),('Document field',r['wp04']['document_fields']),
                            ('Incomplete line',r['wp04']['line_number_fragments']),('Line review',r['wp04']['line_reviews']),('Bubble reading',r['wp04']['bubble_readings']),
                            ('Symbol',r['wp05']['symbols']),('Association',r['wp05']['associations'])]:
            self.rows += [dict(q,display_group=group) for q in items]
        for group in ('contacts','gaps','port_attachments'):
            self.rows += [dict(q,display_group=group) for q in r['wp06']['graph'][group]]
        st=self._store()
        try:latest={d['target_id']:d for d in st.decisions(self.analysis_id)}
        finally:st.close()
        self.table.setRowCount(len(self.rows))
        for i,q in enumerate(self.rows):
            text=q.get('text_candidate',q.get('value_candidate',q.get('text_observed',q.get('state',q.get('kind','')))))
            for col,value in enumerate([q['display_group'],text,q.get('page',''),latest.get(q['id'],{}).get('action','Proposed'),q['id']]):
                self.table.setItem(i,col,QTableWidgetItem(str(value)))
        graph=r['wp06']['graph']
        self.summary.setText(f"{len(r['wp04']['readings'])} readings; {len(r['wp04']['document_fields'])} fields; "
                             f"{sum(a['state']=='ASSOCIATION_PROPOSED' for a in r['wp05']['associations'])} symbol links proposed; "
                             f"{len(graph['edges'])} geometry edges. OCR: {r.get('ocr_run',{}).get('status','not run')}. "
                             'Geometry is unverified; unknown strokes remain unclassified. Accuracy: NOT_RUN until reference approved.')

    def on_select(self):
        i=self.table.currentRow()
        self.detail.setPlainText(json.dumps(self.rows[i],indent=2) if 0<=i<len(self.rows) else '')

    def show_on_drawing(self):
        i=self.table.currentRow()
        if not 0<=i<len(self.rows):return
        row=self.rows[i]
        if not row.get('bbox'):return
        self.main.tabs.setCurrentIndex(0)
        if row['page']!=self.main.page:self.main.goto_page(row['page'])
        self.main.viewer.highlight(row['bbox'])

    def decide(self,action):
        i=self.table.currentRow()
        if not self.result or not 0<=i<len(self.rows):return
        target=self.rows[i]['id']; kinds=targets(self.result)
        if target not in kinds:
            QMessageBox.information(self,'Evidence only','Review the associated printed reading; this row is diagnostic evidence.'); return
        if action in ('ACCEPTED_AS_READING','CORRECTED_READING') and kinds[target]!='READING':
            QMessageBox.information(self,'Hypothesis scope','This is a drawing hypothesis, not a printed reading.'); return
        actor=self.main.reviewer()      # the named reviewer saved for the app (asked once), same as the other review tabs
        if not actor:return
        reason,ok=QInputDialog.getText(self,'Review reason','Reason / visual evidence:')
        if not ok:return
        corrected=None
        if action=='CORRECTED_READING':
            corrected,ok=QInputDialog.getText(self,'Correct reading','Printed text:')
            if not ok:return
        st=self._store()
        try:
            st.decide(self.analysis_id,target,action,actor=actor,reason=reason,corrected_text=corrected)
        except Exception as exc:QMessageBox.warning(self,'Review not saved',str(exc))
        finally:st.close()
        self.populate()

    def audit(self):
        st=self._store()
        try:errors=st.verify()
        finally:st.close()
        QMessageBox.information(self,'Review chain','\n'.join(errors) if errors else 'Stored hashes and chain agree. This is not an independent engineering validation.')

    def export_result(self):
        if not self.result:return
        path=QFileDialog.getExistingDirectory(self,'Export WP04–06 proposals')
        if not path:return
        try:
            export(self.result,path)
            st=self._store()
            try:decisions=st.decisions(self.analysis_id)
            finally:st.close()
            (Path(path)/'wp456_review_decisions.json').write_text(json.dumps(decisions,indent=2)+'\n',encoding='utf8')
        except Exception as exc:QMessageBox.warning(self,'Export failed',str(exc))
