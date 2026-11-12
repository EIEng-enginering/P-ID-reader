import json
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch
import pytest
from pid_reader.engineering.model_lab.core import record
from pid_reader.engineering.model_lab.offline import deny_network
from pid_reader.engineering.model_lab.pipeline import grid_regions,prepare,derive
from pid_reader.engineering.model_lab.__main__ import batch
from pid_reader.engineering.model_lab.host import run
from pid_reader.engineering.model_lab.store import Store
from pid_reader.engineering.model_lab.export import export
from pid_reader.engineering.wp456.common import seal
from pid_reader.formats.page_coordinates import PageFrame


def envelope():
    row=dict(id='text-1',page=1,bbox=dict(x0=.1,y0=.1,x1=.2,y1=.2),kind='TEXT',text='=BAD',raw_score=.5,
             engine='fixture',model_revision='test',review_state='PROPOSED_UNVERIFIED')
    return seal(dict(schema='pid-reader-model-lab-v2',source_sha256='a'*64,model_result={'records':[row]},derived_wp456=None))

def test_no_network_and_restore():
    original=socket.create_connection
    with deny_network():
        with pytest.raises(RuntimeError):socket.create_connection(('example.com',443))
        with socket.socket() as sock:
            with pytest.raises(RuntimeError):sock.connect(('127.0.0.1',1))
    assert socket.create_connection is original

@pytest.mark.parametrize('rotation,expected',[(0,[.1,.2,.3,.4]),(90,[.6,.1,.8,.3]),(180,[.7,.6,.9,.8]),(270,[.2,.7,.4,.9])])
def test_inverse_crop_rotation(rotation,expected):
    req=dict(id='c',page=1,bbox=[0,0,1,1],source_sha256='a'*64,rotation=rotation)
    out=record(dict(kind='TEXT',text='FR',score=None,xyxy=[10,20,30,40]),req,{'engine':'trocr','revision':'fixture'},(100,100),0)
    assert list(out['bbox'].values())==pytest.approx(expected)

def test_grid_independent_of_existing_ocr():
    frame=PageFrame(600,400,100,70,400,250,0)
    regions=grid_regions(frame)
    assert len(regions)==12 and all(r['reason']=='INDEPENDENT_GRID_COVERAGE' for r in regions)
    assert regions[0]['bbox']['x0']==pytest.approx(100/600)

def test_store_audit_and_review_scope(tmp_path):
    store=Store(tmp_path/'review.sqlite');doc=envelope();aid=store.add(doc)
    store.decide(aid,'text-1','CORRECTED_READING',actor='Reviewer',reason='Compared source',corrected_text='FR-720201')
    assert store.verify()==[] and store.decisions(aid)[0]['corrected_text']=='FR-720201'
    with pytest.raises(ValueError):store.decide(aid,'text-1','ACCEPTED_AS_PLANT',actor='Reviewer',reason='No')
    with pytest.raises(Exception):store.con.execute("DELETE FROM wp07_decisions")
    store.close()

def test_export_preserves_raw_and_escapes_formula(tmp_path):
    doc=envelope();export(doc,tmp_path)
    assert "'=BAD" in (tmp_path/'model_proposals.csv').read_text(encoding='utf-8-sig')
    assert json.loads((tmp_path/'model_comparison.json').read_text())['model_result']['records'][0]['text']=='=BAD'

def test_batch_partial_preserves_success():
    payload=dict(enabled=True,model={},requests=[dict(id='a',source_sha256='a'*64),dict(id='b',source_sha256='a'*64)])
    with patch('pid_reader.engineering.model_lab.__main__.execute',side_effect=[{'status':'COMPLETE_PROPOSALS','records':[{'id':'ok'}]},{'status':'FAILED','records':[]}]):
        out=batch(payload)
    assert out['status']=='PARTIAL' and out['coverage']=={'requested':2,'completed':1} and out['records']==[{'id':'ok'}]

def test_real_subprocess_missing_assets_fails_cleanly():
    result=run(dict(enabled=True,id='invalid'),python=sys.executable,timeout=5)
    assert result['status']=='FAILED' and result['records']==[]

def test_cancel_before_launch():
    assert run({'enabled':True},python='missing',cancelled=lambda:True)['status']=='CANCELLED'

@pytest.mark.parametrize('rotation',[0,90,180,270])
@pytest.mark.parametrize('crop',[None,(100.,80.,500.,330.)])
def test_source_crop_mapping(rotation,crop,tmp_path):
    from test_wp456_frames import make,media_box
    from PIL import Image
    pdf=make(rotation,crop);want=media_box(pdf)
    region=dict(id='rect',page=1,bbox=dict(x0=want['x0']-.03,y0=want['y0']-.03,x1=want['x1']+.03,y1=want['y1']+.03))
    requests,coverage=prepare(pdf,1,[region],tmp_path)
    req=requests[0]
    with Image.open(req['image_path']) as image:
        bounds=image.point(lambda v:255 if v<128 else 0).getbbox()
        assert bounds
        got=record(dict(kind='SYMBOL',xyxy=list(bounds),score=.9),req,{'engine':'rfdetr','revision':'fixture'},image.size,0)
    assert got['bbox']==pytest.approx(want,abs=.012)


def test_bridge_preserves_original_alternative():
    from test_wp123_integration import pdf_two_pages
    pdf=pdf_two_pages()
    word=dict(id='word-1',page=1,text='FE-2202',bbox=dict(x0=.1,y0=.1,x1=.2,y1=.15),raw_score=.8)
    challenger=dict(word,id='word-2',text='FE-2203',kind='TEXT',raw_score=.9,roi_id='r',engine='fixture')
    doc=derive(pdf,1,[word],[],{'status':'COMPLETE_PROPOSALS','records':[challenger]})
    texts={r['text_candidate'] for r in doc['wp04']['readings']}
    assert 'FE-2202' in texts and 'FE-2203' in texts


def test_cache_atomic_integrity_and_corruption(tmp_path):
    from pid_reader.engineering.model_lab import cache
    request=dict(id='c',source_sha256='a'*64,image_sha256='b'*64)
    manifest=dict(engine='fixture',revision='test',model_dir='/unused',files={'weights':'c'*64})
    key=cache.key(request,manifest)
    result=dict(status='COMPLETE_PROPOSALS',records=[{'id':'one'}])
    cache.write(tmp_path,key,result);assert cache.read(tmp_path,key)==result
    path=next(tmp_path.glob('*.json'));path.write_text('{}');assert cache.read(tmp_path,key) is None
    assert cache.key(dict(request,image_sha256='d'*64),manifest)!=key


def test_cancel_running_process_terminates():
    from unittest.mock import patch
    class Process:
        returncode=None
        terminated=False
        def poll(self):return self.returncode
        def terminate(self):self.terminated=True;self.returncode=-15
        def wait(self,**kwargs):return self.returncode
    process=Process();calls=iter([False,True])
    with patch('subprocess.Popen',return_value=process):
        out=run({'enabled':True},python=sys.executable,cancelled=lambda:next(calls))
    assert out['status']=='CANCELLED' and process.terminated


def test_frozen_install_refuses_missing_worker(tmp_path,monkeypatch):
    monkeypatch.setattr(sys,'frozen',True,raising=False);monkeypatch.setattr(sys,'_MEIPASS',str(tmp_path),raising=False)
    out=run({'enabled':True},python=sys.executable)
    assert out['status']=='FAILED' and 'archive' in out['error']


def test_frozen_worker_archive_imports_without_source_tree(tmp_path,monkeypatch):
    import importlib.util,shutil
    tool=Path(__file__).resolve().parents[2]/'tools/wp07/build_worker.py'
    spec=importlib.util.spec_from_file_location('worker_builder',tool);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    archive=module.build(Path(__file__).resolve().parents[2])
    target=tmp_path/'model_lab/model_lab_worker.zip';target.parent.mkdir();shutil.copy2(archive,target)
    monkeypatch.setattr(sys,'frozen',True,raising=False);monkeypatch.setattr(sys,'_MEIPASS',str(tmp_path),raising=False)
    out=run({'enabled':True,'id':'missing-assets'},python=sys.executable,timeout=5)
    assert out['status']=='FAILED' and '.zip' in out['runtime']['worker_module_file']
