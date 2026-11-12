"""Cancellable bounded process worker. No ML packages are imported by the UI."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

MAX_OUTPUT=16*1024*1024

def run(request, *, python, timeout=60, cancelled=lambda:False,worker_archive=None):
    if request.get('enabled') is not True:return {'status':'DISABLED','records':[]}
    if isinstance(timeout,bool) or not 1<=timeout<=300:raise ValueError('Worker timeout must be 1..300 seconds')
    if cancelled():return {'status':'CANCELLED','records':[]}
    env=dict(os.environ)
    if worker_archive is not None:
        worker=Path(worker_archive).resolve()
        if not worker.is_file():return {'status':'FAILED','records':[],'error':'Worker archive not found'}
        src=str(worker)
    elif getattr(sys,'frozen',False):
        worker=Path(sys._MEIPASS)/'model_lab/model_lab_worker.zip'
        if not worker.is_file():return {'status':'FAILED','records':[],'error':'Isolated model worker archive is missing from this installation'}
        src=str(worker)
    else:src=str(Path(__file__).resolve().parents[3])
    env['PYTHONPATH']=src+os.pathsep+env.get('PYTHONPATH','')
    env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='2',TOKENIZERS_PARALLELISM='false')
    with tempfile.TemporaryDirectory(prefix='pid_model_') as tmp:
        path=Path(tmp)/'request.json';path.write_text(json.dumps(request,allow_nan=False),encoding='utf-8')
        # File redirection avoids pipe deadlocks and keeps diagnostics outside the JSON protocol.
        with open(Path(tmp)/'out','w+b') as out,open(Path(tmp)/'err','w+b') as err:
            try:proc=subprocess.Popen([str(python),'-m','pid_reader.engineering.model_lab',str(path)],stdout=out,stderr=err,env=env)
            except OSError as exc:return {'status':'FAILED','records':[],'error':str(exc)}
            start=time.monotonic();interrupted=None
            try:
                while proc.poll() is None:
                    if cancelled():interrupted='CANCELLED';break
                    if time.monotonic()-start>timeout:interrupted='TIMEOUT';break
                    if out.tell()+err.tell()>MAX_OUTPUT:interrupted='OUTPUT_LIMIT';break
                    time.sleep(.05)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=2)
            if interrupted:return {'status':interrupted,'records':[],'accuracy_status':'NOT_MEASURED'}
            out.seek(0);err.seek(0)
            output=out.read(MAX_OUTPUT+1);error=err.read(MAX_OUTPUT+1)
            if len(output)+len(error)>MAX_OUTPUT:return {'status':'OUTPUT_LIMIT','records':[]}
            if proc.returncode:return {'status':'FAILED','records':[],'error':error.decode('utf-8','replace')[-2000:]}
            try:
                result=json.loads(output.decode('utf-8').strip().splitlines()[-1])
                if result['status'] not in {'DISABLED','FAILED','PARTIAL','COMPLETE_PROPOSALS'}:raise ValueError('Unknown status')
                if not isinstance(result['records'],list) or len(result['records'])>24000:raise ValueError('Invalid records')
                result['worker_diagnostics']=error.decode('utf-8','replace')[-2000:]
                return result
            except (ValueError,KeyError,IndexError,TypeError):return {'status':'FAILED','records':[],'error':'Invalid worker response'}

def text_evidence(result):
    if result.get('status') not in {'COMPLETE_PROPOSALS','PARTIAL'}:return []
    rows=[]
    for r in result['records']:
        if r['kind']!='TEXT' or not r.get('text'):continue
        # recover_wp123 consumes raw_ocr_score; retain the uncalibrated original too.
        score=r['raw_score'] if r['raw_score'] is not None else 0.
        rows.append(dict(r,raw_score=score,raw_ocr_score=score,score_unavailable=r['raw_score'] is None,
                         run_id=r.get('run_id',r['id'].split(':')[0]),ocr_ids=[r['id']]))
    return rows
