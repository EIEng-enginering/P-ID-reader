"""Real Qt/task/window tests, synthetic recognition fixture; no accuracy claims."""
import json
from pathlib import Path
import sys
import time
from hashlib import sha256
import pytest
pytest.importorskip('PySide6.QtWidgets')
from test_wp456_gui import win,qapp,wait_idle
from pid_reader.engineering.wp456.common import seal


def configure(win,tmp_path,monkeypatch):
    tab=win.model_lab_tab
    monkeypatch.setenv('PID_MODEL_LAB_STORE',str(tmp_path/'model.sqlite'))
    p=tmp_path/'fixture.manifest.json';p.write_text(json.dumps({'engine':'easyocr'}))
    tab.manifest_path.setText(str(p));tab.python_path.setText(sys.executable)
    tab.enabled.setChecked(True);tab.mode.setCurrentIndex(1)
    return tab


def fixture_compare(pdf,page,regions,manifest,**kwargs):
    from pid_reader.engineering.model_lab.pipeline import derive
    source=sha256(pdf).hexdigest()
    row=dict(id='model-word',text='FE-2203',kind='TEXT',page=page,bbox=dict(x0=.1,y0=.1,x1=.2,y1=.15),raw_score=.8,
             engine='fixture',model_revision='test',source_sha256=source,roi_id='fixture-roi',review_state='PROPOSED_UNVERIFIED')
    raw=dict(status='COMPLETE_PROPOSALS',records=[row],source_sha256=source)
    derived=derive(pdf,page,kwargs['words'],kwargs['detections'],raw,segments=kwargs['segments'])
    return seal(dict(schema='pid-reader-model-lab-v2',status='COMPLETE_PROPOSALS',source_sha256=source,page=page,
                     model_result=raw,coverage=dict(requested_regions=len(regions),scheduled_regions=len(regions)),derived_wp456=derived))


def test_real_window_adds_tab_default_off_and_reset(win):
    tab=win.model_lab_tab
    assert not tab.enabled.isChecked() and tab.result is None
    assert 'Model comparison' in [win.tabs.tabText(i) for i in range(win.tabs.count())]
    tab.compare();assert win.task is None
    tab.rows=[{}];win.open_drawing(win.current_extraction_id);assert tab.rows==[]


def test_compare_review_export_and_host_isolation(win,qapp,tmp_path,monkeypatch):
    from pid_reader.ui import model_lab_tab as ui
    tab=configure(win,tmp_path,monkeypatch)
    monkeypatch.setattr(ui.pipeline,'compare',fixture_compare)
    before=win.db.db.execute('SELECT COUNT(*) FROM audit_event').fetchone()[0]
    tab.compare();wait_idle(win,qapp)
    assert tab.result and tab.rows[0]['text']=='FE-2203' and not tab.busy
    assert tab.run_button.isEnabled()
    tab.table.selectRow(0)
    answers=iter([('Checked source',True),('FE-2204',True)])
    monkeypatch.setattr(ui.QInputDialog,'getText',lambda *a,**k:next(answers))
    tab.decide('CORRECTED_READING')
    st=tab._store()
    try:assert st.decisions(tab.analysis_id)[0]['corrected_text']=='FE-2204' and st.verify()==[]
    finally:st.close()
    out=tmp_path/'export';out.mkdir()
    monkeypatch.setattr(ui.QFileDialog,'getExistingDirectory',lambda *a,**k:str(out))
    tab.export_result();assert (out/'model_comparison.json').is_file()
    tab.open_derived();assert win.wp456_tab.result and win.tabs.currentWidget() is win.wp456_tab
    assert win.db.db.execute('SELECT COUNT(*) FROM audit_event').fetchone()[0]==before


def test_stale_model_worker_is_discarded(win,qapp,tmp_path,monkeypatch):
    from pid_reader.ui import model_lab_tab as ui
    tab=configure(win,tmp_path,monkeypatch)
    def slow(*a,**k):time.sleep(.2);return fixture_compare(*a,**k)
    monkeypatch.setattr(ui.pipeline,'compare',slow)
    tab.compare();win.goto_page(2);wait_idle(win,qapp)
    assert tab.result is None and not tab.busy


def test_cancel_model_worker_releases_ui(win,qapp,tmp_path,monkeypatch):
    from pid_reader.ui import model_lab_tab as ui
    tab=configure(win,tmp_path,monkeypatch)
    def spin(*a,cancelled,**k):
        started=time.monotonic()
        while not cancelled() and time.monotonic()-started<3:time.sleep(.01)
        return {'status':'CANCELLED'}
    monkeypatch.setattr(ui.pipeline,'compare',spin)
    tab.compare();assert win.task is not None;win.task.cancel();wait_idle(win,qapp)
    assert tab.result is None and not tab.busy and tab.run_button.isEnabled()
