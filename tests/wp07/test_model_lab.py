import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pid_reader.engineering.model_lab.core import bbox, record, verify_model, benchmark, digest
from pid_reader.engineering.model_lab.__main__ import execute
from pid_reader.engineering.model_lab.host import run, text_evidence

class Models(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'model').write_bytes(b'fixture')
        self.manifest=dict(engine='easyocr',model_dir=str(self.root),files={'model':digest(self.root/'model')},
                           source_url='https://example.org/fixture',revision='test',license_note='fixture only')
        self.req=dict(id='crop-1',page=1,bbox=[.2,.3,.6,.5],source_sha256='a'*64)
    def tearDown(self):self.tmp.cleanup()
    def test_manifest_hash(self):
        verify_model(self.manifest);(self.root/'model').write_bytes(b'changed')
        with self.assertRaises(ValueError):verify_model(self.manifest)
    def test_manifest_inventory(self):
        (self.root/'extra').touch()
        with self.assertRaises(ValueError):verify_model(self.manifest)
    def test_missing_license(self):
        del self.manifest['license_note']
        with self.assertRaises(ValueError):verify_model(self.manifest)
    def test_mapping(self):
        r=record(dict(kind='TEXT',text='FR',xyxy=[25,10,75,30],score=.7),self.req,self.manifest,(100,40),0)
        for actual,expected in zip(r['bbox'].values(),[.3,.35,.5,.45]):self.assertAlmostEqual(actual,expected)
        self.assertEqual(r['review_state'],'PROPOSED_UNVERIFIED');self.assertFalse(r['confidence_calibrated'])
    def test_reject_outside_crop(self):
        with self.assertRaises(ValueError):record(dict(kind='TEXT',xyxy=[-1,0,20,20]),self.req,self.manifest,(100,40),0)
    def test_nonfinite(self):
        with self.assertRaises(ValueError):bbox([0,0,float('nan'),1])
    def test_default_off(self):self.assertEqual(execute({})['status'],'DISABLED')
    def test_host_default_off(self):self.assertEqual(run({},python='DOES_NOT_EXIST')['status'],'DISABLED')
    def test_draft_not_scored(self):self.assertEqual(benchmark({'status':'DRAFT'},[])['status'],'NOT_RUN')
    def test_exact_and_ambiguous(self):
        ref=dict(status='HUMAN_VERIFIED',source_sha256='a'*64,labels=[dict(roi_id='c',text='FR')])
        row=dict(roi_id='c',kind='TEXT',text='FR',source_sha256='a'*64)
        self.assertEqual(benchmark(ref,[row])['exact'],1)
        self.assertEqual(benchmark(ref,[row,row])['exact'],0)
    def test_wrong_source(self):
        with self.assertRaises(ValueError):benchmark(dict(status='HUMAN_VERIFIED',source_sha256='a'*64,labels=[]),[{'source_sha256':'b'*64}])
    def test_timeout(self):
        class Process:
            returncode=None
            def poll(self):return self.returncode
            def terminate(self):self.returncode=-15
            def wait(self,**kwargs):return self.returncode
        with patch('subprocess.Popen',return_value=Process()),patch('pid_reader.engineering.model_lab.host.time.monotonic',side_effect=[0,2]):
            self.assertEqual(run({'enabled':True},python=sys.executable,timeout=1)['status'],'TIMEOUT')
    def test_malformed_worker(self):
        class Process:
            returncode=0
            def poll(self):return 0
        def spawn(*args,**kwargs):
            kwargs['stdout'].write(b'broken');kwargs['stdout'].flush();return Process()
        with patch('subprocess.Popen',side_effect=spawn):
            self.assertEqual(run({'enabled':True},python=sys.executable)['status'],'FAILED')
    def test_bridge_no_symbols(self):
        row=dict(kind='TEXT',text='FR',id='one',raw_score=None)
        r=text_evidence(dict(status='COMPLETE_PROPOSALS',records=[row,dict(kind='SYMBOL')]))
        self.assertTrue(r[0]['score_unavailable']);self.assertEqual(len(r),1)
    def test_real_worker_disabled(self):
        self.assertEqual(run({'enabled':False},python=sys.executable)['status'],'DISABLED')
    def test_fixture_backend_end_to_end(self):
        from PIL import Image
        crop=self.root.parent/(self.root.name+'_crop.png')
        try:
            Image.new('RGB',(100,40),'white').save(crop)
            req=dict(self.req,enabled=True,image_path=str(crop),image_sha256=digest(crop),
                     coordinate_frame='MEDIA_NORMALIZED_TOP_LEFT',model=self.manifest)
            with patch('pid_reader.engineering.model_lab.adapters.infer',return_value=[dict(kind='TEXT',text='FR',score=None,xyxy=[0,0,100,40])]):
                out=execute(req)
            self.assertEqual(out['status'],'COMPLETE_PROPOSALS');self.assertEqual(out['records'][0]['text'],'FR')
        finally:crop.unlink(missing_ok=True)

if __name__=='__main__':unittest.main()
