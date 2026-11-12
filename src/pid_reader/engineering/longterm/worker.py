"""Fixed worker entry points only; no arbitrary shell commands in job records."""
import json,sys
from pathlib import Path
from .data import sha,code_sha
from .train import atomic_json

def execute(job,out):
    payload=json.loads(job['payload']) if isinstance(job['payload'],str) else job['payload']
    if payload.get('_programme_code_sha256') not in (None,code_sha()):raise ValueError('Programme code changed after enqueue; create an explicit new job version')
    for field in ('dataset_path','training_dataset_path','model_manifest_path','candidate_manifest_path','pdf_path'):
        if field in payload:
            expected=payload.get(field+'_sha256')
            if expected and sha(payload[field])!=expected:raise ValueError('Enqueued input changed: '+field)
    if job['kind']=='TRAIN_OCR':
        from .train import train
        return train(payload,out)
    if job['kind']=='EVALUATE_OCR':
        from .evaluate import evaluate
        return evaluate(payload,out)
    if job['kind']=='EXPERIMENT_WP08':
        from ..wp08.pipeline import analyse
        manifests=[json.loads(Path(payload[name]).read_text()) for name in ('discovery_manifest','line_manifest')]
        if sha(payload['pdf_path'])!=payload['source_sha256']:raise ValueError('Drawing bytes changed')
        result=analyse(Path(payload['pdf_path']).read_bytes(),int(payload.get('page',1)),*manifests,
                       python=payload['backend_python'],enabled=True,total_seconds=int(payload.get('total_seconds',1200)),
                       discovery_scale=float(payload.get('discovery_scale',4)),line_scale=float(payload.get('line_scale',6)),
                       max_lines=int(payload.get('max_lines',48)),cache_dir=Path(out)/'crop_cache')
        target=Path(out)/'automatic_result.json';atomic_json(target,result)
        return dict(status='SUCCEEDED' if result['status']=='COMPLETE_PROPOSALS' else 'PARTIAL',coverage=result['coverage'],
                    source_sha256=result['source_sha256'],full_result_path=str(target),full_result_sha256=sha(target),
                    elapsed_seconds=result['model_result']['elapsed_seconds'],accuracy_status='NOT_RUN_NO_APPROVED_REFERENCE')
    raise ValueError('Unknown job kind')

if __name__=='__main__':
    path=Path(sys.argv[1]);job=json.loads(path.read_text());out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
    try:result=execute(job,out)
    except (ValueError,FileNotFoundError,KeyError) as exc:result=dict(status='BLOCKED',reason=type(exc).__name__+': '+str(exc))
    except Exception as exc:result=dict(status='FAILED',reason=type(exc).__name__+': '+str(exc))
    atomic_json(out/'worker_result.json',result);print(json.dumps(result))
