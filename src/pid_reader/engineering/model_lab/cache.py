"""Atomic per-crop proposal cache. No review decisions or accepted facts are cached."""
import json
import hashlib
import importlib.resources
import os
from pathlib import Path
import tempfile
from ..wp456.common import digest,seal,verify_seal

def key(request,manifest):
    identity={k:v for k,v in request.items() if k not in ('image_path','cache_dir','enabled','model')}
    model={k:v for k,v in manifest.items() if k!='model_dir'}
    from .runtime import metadata
    runtime=metadata()
    code=importlib.resources.files('pid_reader.engineering.model_lab')
    algorithm=hashlib.sha256(b''.join(code.joinpath(name).read_bytes() for name in ('adapters.py','core.py','__main__.py'))).hexdigest()
    return digest({'algorithm':algorithm,'request':identity,'model':model,'runtime':{k:runtime[k] for k in ('python','platform','versions')}})

def read(directory,cache_key):
    p=Path(directory)/('wp07-cache-'+cache_key+'.json')
    try:
        if p.stat().st_size>4*1024*1024:return None
        doc=json.loads(p.read_text(encoding='utf8'))
        if not verify_seal(doc) or doc['key']!=cache_key or doc['result']['status']!='COMPLETE_PROPOSALS':return None
        return doc['result']
    except (OSError,ValueError,KeyError,TypeError):return None

def write(directory,cache_key,result):
    if result.get('status')!='COMPLETE_PROPOSALS':return
    root=Path(directory);root.mkdir(parents=True,exist_ok=True)
    data=json.dumps(seal({'key':cache_key,'result':result}),ensure_ascii=False)
    if len(data.encode('utf8'))>4*1024*1024:return
    fd,name=tempfile.mkstemp(prefix='wp07-cache-',suffix='.tmp',dir=root)
    try:
        with os.fdopen(fd,'w',encoding='utf8') as f:f.write(data)
        os.replace(name,root/('wp07-cache-'+cache_key+'.json'))
    finally:
        if Path(name).exists():Path(name).unlink()
