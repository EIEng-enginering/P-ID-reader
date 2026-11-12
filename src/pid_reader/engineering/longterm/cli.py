import argparse,json
from pathlib import Path
from .store import Store
from .data import sha,freeze_payload
from .runner import run_once
from .handoff import export

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['once','enqueue','status','export','readiness']);p.add_argument('--config',type=Path,required=True)
    p.add_argument('--kind',choices=['TRAIN_OCR','EVALUATE_OCR','EVALUATE_BASELINE_OCR','EXPERIMENT_WP08']);p.add_argument('--payload',type=Path)
    a=p.parse_args();config=json.loads(a.config.read_text(encoding='utf8'))
    if a.command=='once':
        result=run_once(config)
        from .claude_bridge import review
        try:result['claude_review']=review(config)
        except Exception as exc:result['claude_review']={'status':'FAILED','error':str(exc)}
        print(json.dumps(result,indent=2));return
    if a.command=='readiness':
        from .readiness import readiness
        result=readiness(config);print(json.dumps(result,indent=2));raise SystemExit(0 if result['ready'] else 3)
    store=Store(config['state_dir'])
    try:
        if a.command=='enqueue':
            if not a.kind or not a.payload:p.error('enqueue needs --kind and --payload')
            payload=json.loads(a.payload.read_text(encoding='utf8'))
            payload=freeze_payload(payload)
            print(store.enqueue(a.kind,payload))
        elif a.command=='export':print(export(store,force=True))
        else:print(json.dumps({'jobs':[dict(r) for r in store.db.execute('SELECT id,kind,status,attempts FROM jobs')],'audit_problems':store.verify()},indent=2))
    finally:store.close()
if __name__=='__main__':main()
