"""Offline CPU worker, supporting one crop or a bounded batch with model reuse."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from .core import record,validate_request,verify_model
from .offline import deny_network

_VERIFIED={}

def execute(request):
    start=time.monotonic()
    result={'status':'FAILED','records':[],'review_state':'PROPOSED_UNVERIFIED',
            'accuracy_status':'NOT_MEASURED','source_sha256':request.get('source_sha256')}
    try:
        if request.get('enabled') is not True:result['status']='DISABLED';return result
        validate_request(request)
        manifest=request['model'];key=json.dumps(manifest,sort_keys=True)
        if key not in _VERIFIED:_VERIFIED[key]=verify_model(manifest)
        root=_VERIFIED[key]
        from . import cache
        cache_key=cache.key(request,manifest)
        if request.get('cache_dir'):
            saved=cache.read(request['cache_dir'],cache_key)
            if saved is not None:
                result.update(saved,cache_hit=True)
                return result
        os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='2',TOKENIZERS_PARALLELISM='false')
        from PIL import Image
        from .adapters import infer
        with Image.open(request['image_path']) as source:
            if source.width*source.height>4_000_000:raise ValueError('Crop pixel budget exceeded')
            image=source.convert('RGB')
            try:
                with deny_network():raw=infer(manifest['engine'],image,root,manifest,request.get('options'))
                if len(raw)>1000:raise ValueError('Output record budget exceeded')
                result['records']=[record(row,request,manifest,image.size,i) for i,row in enumerate(raw)]
            finally:image.close()
        result['status']='COMPLETE_PROPOSALS'
        result['cache_hit']=False
        if request.get('cache_dir'):
            try:cache.write(request['cache_dir'],cache_key,result)
            except OSError:result['cache_warning']='Cannot write proposal cache'
    except Exception as exc:result.update(status='FAILED',records=[],error=type(exc).__name__+': '+str(exc))
    finally:result['elapsed_seconds']=round(time.monotonic()-start,4)
    return result

def batch(payload):
    if payload.get('enabled') is not True:return {'status':'DISABLED','records':[]}
    requests=payload['requests']
    if not isinstance(requests,list) or not 1<=len(requests)<=24:raise ValueError('Batch requires 1..24 crops')
    if len({r['id'] for r in requests})!=len(requests):raise ValueError('Duplicate crop IDs')
    if len({r['source_sha256'] for r in requests})!=1:raise ValueError('Mixed drawings in batch')
    started=time.monotonic();runs=[]
    for req in requests:
        req=dict(req,enabled=True,model=payload['model']);runs.append(execute(req))
    records=[r for run in runs for r in run['records']]
    count=sum(run['status']=='COMPLETE_PROPOSALS' for run in runs)
    return dict(status='COMPLETE_PROPOSALS' if count==len(runs) else 'PARTIAL' if count else 'FAILED',
                records=records,runs=runs,source_sha256=requests[0]['source_sha256'],
                elapsed_seconds=round(time.monotonic()-started,4),accuracy_status='NOT_MEASURED',
                coverage={'requested':len(requests),'completed':count},review_state='PROPOSED_UNVERIFIED')

if __name__=='__main__':
    try:
        req=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
        result=batch(req) if 'requests' in req else execute(req)
    except Exception as exc:result={'status':'FAILED','records':[],'error':type(exc).__name__+': '+str(exc)}
    from .runtime import metadata
    result['runtime']=metadata()
    print(json.dumps(result,allow_nan=False))
