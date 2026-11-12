"""Optional local model comparison integrated with the c91ebe6 task/review APIs."""
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from PySide6.QtWidgets import (QAbstractItemView,QCheckBox,QComboBox,QFileDialog,QHBoxLayout,
 QInputDialog,QLabel,QLineEdit,QMessageBox,QPlainTextEdit,QPushButton,QTableWidget,QTableWidgetItem,QVBoxLayout,QWidget)
from ..engineering.model_lab import pipeline
from ..engineering.model_lab.store import Store
from ..engineering.wp456.common import seal

class ModelLabTab(QWidget):
    def __init__(self,main):
        super().__init__();self.main=main;self.result=None;self.rows=[];self.analysis_id=None;self.busy=False
        self.context=None;self.symbol_evidence=[]
        layout=QVBoxLayout(self)
        controls=QHBoxLayout();self.enabled=QCheckBox('Enable model comparison for this session');controls.addWidget(self.enabled)
        self.reuse=QCheckBox('Reuse identical completed crops');self.reuse.setChecked(True);controls.addWidget(self.reuse)
        self.mode=QComboBox();self.mode.addItems(['Selected proposal','Automatic text regions','Whole-page tiles']);controls.addWidget(self.mode)
        self.rotation=QComboBox();self.rotation.addItem('As drawn',0);self.rotation.addItem('Turn text left',90);self.rotation.addItem('Turn text right',270)
        controls.addWidget(self.rotation);layout.addLayout(controls)
        paths=QHBoxLayout();self.manifest_path=QLineEdit(main.settings.value('model_lab/manifest','',str));self.manifest_path.setPlaceholderText('Local model manifest')
        paths.addWidget(self.manifest_path);choose=QPushButton('Choose model…');choose.clicked.connect(self.choose_manifest);paths.addWidget(choose);layout.addLayout(paths)
        paths=QHBoxLayout();base=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local'/'share')))/'PIDReader'/'models'/'runtime'
        default=base/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        self.python_path=QLineEdit(main.settings.value('model_lab/python',str(default if default.exists() else Path(sys.executable)),str))
        paths.addWidget(QLabel('Model runtime'));paths.addWidget(self.python_path)
        choose=QPushButton('Choose Python…');choose.clicked.connect(self.choose_python);paths.addWidget(choose);layout.addLayout(paths)
        actions=QHBoxLayout();self.run_button=QPushButton('Compare proposals');self.run_button.clicked.connect(self.compare);actions.addWidget(self.run_button)
        export=QPushButton('Export comparison…');export.clicked.connect(self.export_result);actions.addWidget(export)
        review=QPushButton('Review derived readings in WP04–06');review.clicked.connect(self.open_derived);actions.addWidget(review)
        audit=QPushButton('Verify review audit');audit.clicked.connect(self.audit);actions.addWidget(audit);layout.addLayout(actions)
        self.summary=QLabel('Comparison is off. Choose a staged model to test it against the current drawing.');self.summary.setWordWrap(True);layout.addWidget(self.summary)
        self.table=QTableWidget(0,6);self.table.setHorizontalHeaderLabels(['Kind','Observed text / symbol','Raw score','Page','Review','Model'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.itemSelectionChanged.connect(self.selected)
        self.table.itemDoubleClicked.connect(lambda _:self.highlight());layout.addWidget(self.table)
        self.detail=QPlainTextEdit();self.detail.setReadOnly(True);layout.addWidget(self.detail)
        actions=QHBoxLayout()
        for label,action in [('Accept printed text','ACCEPTED_AS_READING'),('Correct text','CORRECTED_READING'),('Support drawing hypothesis','SUPPORTED_AS_DRAWING_HYPOTHESIS'),('Reject','REJECTED'),('Unresolved','UNRESOLVED')]:
            button=QPushButton(label);button.clicked.connect(lambda checked=False,a=action:self.decide(a));actions.addWidget(button)
        layout.addLayout(actions)
        button=QPushButton('Propose class for selected symbol');button.clicked.connect(self.classify);layout.addWidget(button)

    def _store(self):
        root=Path(os.environ.get('PID_MODEL_LAB_STORE') or Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local'/'share')))/'PIDReader'/'model_lab'/'review.sqlite')
        root.parent.mkdir(parents=True,exist_ok=True);return Store(root)

    def choose_manifest(self):
        path,_=QFileDialog.getOpenFileName(self,'Choose local model manifest','','JSON (*.json)')
        if path:self.manifest_path.setText(path);self.main.settings.setValue('model_lab/manifest',path)

    def choose_python(self):
        path,_=QFileDialog.getOpenFileName(self,'Choose model environment Python')
        if path:self.python_path.setText(path);self.main.settings.setValue('model_lab/python',path)

    def reset(self):
        self.result=None;self.rows=[];self.analysis_id=None;self.context=None;self.symbol_evidence=[]
        self.table.setRowCount(0);self.detail.clear();self.summary.setText('No model comparison on this drawing.')

    def _roi(self):
        # The user can select an existing proposal, then switch to this tab.
        for tab in (getattr(self.main,'wp456_tab',None),getattr(self.main,'wp123_tab',None),self):
            if tab is None:continue
            rows=getattr(tab,'rows',[]);i=tab.table.currentRow()
            if 0<=i<len(rows) and rows[i].get('bbox'):
                r=rows[i]
                if r['page']!=self.main.page:raise ValueError('Selected proposal belongs to another page')
                return dict(id='selected-'+r['id'],page=r['page'],bbox=r['bbox'],reason='USER_SELECTED_PROPOSAL')
        raise ValueError('Select a source proposal in WP01–03 or WP04–06 first, then return here')

    def compare(self):
        m=self.main
        if not self.enabled.isChecked():self.summary.setText('Enable model comparison first.');return
        if self.busy or m.task is not None:return
        if not m.current_pdf or not m.current_extraction_id:return
        try:
            path=Path(self.manifest_path.text())
            if path.stat().st_size>1024*1024:raise ValueError('Manifest exceeds size budget')
            manifest=json.loads(path.read_text(encoding='utf8'))
            python=Path(self.python_path.text()).resolve(strict=True)
            mode=self.mode.currentIndex();selected=self._roi() if mode==0 else None
            if manifest['engine']=='trocr' and mode!=0:raise ValueError('TrOCR needs one selected printed text line')
            from ..engineering import wp123_session as S
            from ..engineering.wp456.host import geometry_from_project
            words,_=S.words_from_project(m.db,m.current_extraction_id,m.page,m.current_result)
            detections,_=S.detections_for_page(m.current_pdf,m.page)
            source=sha256(m.current_pdf).hexdigest();pdf=m.current_pdf;page=m.page;extraction=m.current_extraction_id
            segments=geometry_from_project(m.db,extraction,page,source)
        except Exception as exc:QMessageBox.warning(self,'Cannot compare models',str(exc));return
        cache_dir=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local'/'share')))/'PIDReader'/'model_lab'/'cache' if self.reuse.isChecked() else None
        rotation=self.rotation.currentData();self.busy=True;self.run_button.setEnabled(False)
        self.main.settings.setValue('model_lab/manifest',str(path));self.main.settings.setValue('model_lab/python',str(python))
        def job(report,cancelled):
            if mode==0:regions=[selected]
            elif mode==1:
                from ..engineering.wp456.readings import propose_regions
                upstream=S.analyse_page(pdf,page,words,detections,scan_bubbles=True,profile='auto')
                regions=propose_regions(words,upstream['bubble_candidates'])['regions']
            else:
                from io import BytesIO
                import pdfplumber
                from ..formats.page_coordinates import frame_from_pdfplumber
                with pdfplumber.open(BytesIO(pdf)) as doc:frame=frame_from_pdfplumber(doc.pages[page-1])
                regions=pipeline.grid_regions(frame)
            return pipeline.compare(pdf,page,regions,manifest,python=python,enabled=True,timeout=120,
                                    cancelled=cancelled,cache_dir=cache_dir,max_regions=12,rotations=(rotation,),words=words,
                                    detections=detections,segments=segments,report=report)
        def done(result):
            if not m.current_pdf or sha256(m.current_pdf).hexdigest()!=source or m.page!=page or m.current_extraction_id!=extraction:return
            if result.get('schema')!='pid-reader-model-lab-v2':self.summary.setText(result['status']);return
            self.result=result;self.context=(pdf,page,words,detections,segments);self.symbol_evidence=[]
            store=self._store()
            try:self.analysis_id=store.add(result)
            finally:store.close()
            self.populate()
        if not m.run_task('Local model comparison',job,done,on_finish=self.release):self.release()

    def release(self):self.busy=False;self.run_button.setEnabled(True)

    def populate(self):
        self.rows=self.result['model_result']['records'];store=self._store()
        try:latest={d['target_id']:d for d in store.decisions(self.analysis_id)}
        finally:store.close()
        self.table.setRowCount(len(self.rows))
        for i,r in enumerate(self.rows):
            values=[r['kind'],r.get('text') or r.get('class_name'),r.get('raw_score'),r['page'],latest.get(r['id'],{}).get('action','Proposed'),r['engine']]
            for j,v in enumerate(values):self.table.setItem(i,j,QTableWidgetItem('unavailable' if v is None else str(v)))
        c=self.result['coverage'];self.summary.setText(f"{self.result['status']}: {len(self.rows)} model proposals; {c['scheduled_regions']}/{c['requested_regions']} regions scheduled. Accuracy has not been measured.")
        if not self.rows:self.detail.setPlainText(json.dumps(self.result['model_result'],indent=2))

    def current(self):
        return bool(self.result and self.main.current_pdf and sha256(self.main.current_pdf).hexdigest()==self.result['source_sha256'] and self.main.page==self.result['page'])

    def selected(self):
        i=self.table.currentRow();self.detail.setPlainText(json.dumps(self.rows[i],indent=2) if 0<=i<len(self.rows) else '')

    def highlight(self):
        i=self.table.currentRow()
        if self.current() and 0<=i<len(self.rows):self.main.tabs.setCurrentIndex(0);self.main.viewer.highlight(self.rows[i]['bbox'])

    def decide(self,action):
        i=self.table.currentRow()
        if not self.current() or not 0<=i<len(self.rows):return
        actor=self.main.reviewer()
        if not actor:return
        reason,ok=QInputDialog.getText(self,'Source evidence','Reason / evidence checked:')
        if not ok or not reason.strip():return
        corrected=None
        if action=='CORRECTED_READING':
            corrected,ok=QInputDialog.getText(self,'Correct printed text','Text:',text=self.rows[i].get('text') or '')
            if not ok:return
        store=self._store()
        try:store.decide(self.analysis_id,self.rows[i]['id'],action,actor=actor,reason=reason,corrected_text=corrected)
        except Exception as exc:QMessageBox.warning(self,'Review refused',str(exc))
        finally:store.close()
        self.populate()

    def classify(self):
        i=self.table.currentRow()
        if not self.current() or not self.context or not 0<=i<len(self.rows) or self.rows[i]['kind']!='SYMBOL':return
        actor=self.main.reviewer()
        if not actor:return
        kind,ok=QInputDialog.getItem(self,'Visible symbol class','Propose class:',['VALVE','INSTRUMENT','EQUIPMENT'],0,False)
        if not ok:return
        reason,ok=QInputDialog.getText(self,'Source evidence','Reason / visible evidence:')
        if not ok or not reason.strip():return
        row=self.rows[i];evidence=dict(id='review-'+row['id'],page=row['page'],bbox=row['bbox'],kind=kind,actor=actor,reason=reason,
                                      evidence_ids=[row['id']],source_sha256=self.result['source_sha256'])
        symbols=[s for s in self.symbol_evidence if s['id']!=evidence['id']]+[evidence]
        try:
            pdf,page,words,detections,segments=self.context
            derived=pipeline.derive(pdf,page,words,detections,self.result['model_result'],segments=segments,symbol_evidence=symbols)
            updated=dict(self.result,derived_wp456=derived);self.result=seal(updated);self.symbol_evidence=symbols
            store=self._store()
            try:self.analysis_id=store.add(self.result)
            finally:store.close()
            self.summary.setText('Source-linked class hypothesis added; open derived readings in WP04–06 for association review.')
        except Exception as exc:QMessageBox.warning(self,'Cannot propose class',str(exc))

    def open_derived(self):
        if not self.result or not self.result.get('derived_wp456'):return
        m=self.main
        if not m.current_pdf or sha256(m.current_pdf).hexdigest()!=self.result['source_sha256'] or m.page!=self.result['page']:return
        tab=m.wp456_tab;tab.result=self.result['derived_wp456'];store=tab._store()
        try:tab.analysis_id=store.add(tab.result)
        finally:store.close()
        tab.populate();m.tabs.setCurrentWidget(tab)

    def export_result(self):
        if not self.result:return
        folder=QFileDialog.getExistingDirectory(self,'Export model comparison')
        if not folder:return
        from ..engineering.model_lab.export import export
        try:
            export(self.result,folder)
            store=self._store()
            try:
                decisions=store.decisions(self.analysis_id);problems=store.verify()
            finally:store.close()
            Path(folder,'model_review_decisions.json').write_text(json.dumps(decisions,indent=2),encoding='utf8')
            Path(folder,'model_review_audit.json').write_text(json.dumps({'problems':problems,'valid':not problems},indent=2),encoding='utf8')
        except Exception as exc:QMessageBox.warning(self,'Export failed',str(exc))

    def audit(self):
        store=self._store()
        try:problems=store.verify()
        finally:store.close()
        self.summary.setText('Audit chain valid.' if not problems else str(problems))
