"""Replay explicitly selected regions. Never presents them as automatic coverage."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from pid_reader.engineering.model_lab.pipeline import compare
p=argparse.ArgumentParser()
p.add_argument('--pdf',type=Path,required=True);p.add_argument('--regions',type=Path,required=True)
p.add_argument('--manifest',type=Path,required=True);p.add_argument('--python',type=Path,required=True)
p.add_argument('--output',type=Path,required=True);p.add_argument('--cache',type=Path);p.add_argument('--worker-archive',type=Path)
a=p.parse_args();pdf=a.pdf.read_bytes();regions=json.loads(a.regions.read_text(encoding='utf8'))
if regions['source_sha256']!=sha256(pdf).hexdigest():p.error('Region reference belongs to another source PDF')
manifest=json.loads(a.manifest.read_text(encoding='utf8'))
result=compare(pdf,regions['page'],regions['regions'],manifest,python=a.python,enabled=True,timeout=180,
               max_regions=24,cache_dir=a.cache,worker_archive=a.worker_archive)
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2),encoding='utf8')
print(json.dumps({'status':result['status'],'records':len(result['model_result']['records']),'accuracy':'NOT_MEASURED','output':str(a.output)}))
raise SystemExit(0 if result['status'] in ('COMPLETE_PROPOSALS','PARTIAL') else 1)
