"""One guarded slice per invocation; Windows Task Scheduler repeats the invocation."""
import json,os,shutil,sys,uuid
from datetime import datetime,timezone,timedelta
from pathlib import Path
from .store import Store,canonical,digest
from .data import sha,freeze_payload,validate,code_sha
from .handoff import export

def policy(config):
    import psutil
    if config.get('require_ac',True):
        battery=psutil.sensors_battery()
        if battery is not None and not battery.power_plugged:return 'ON_BATTERY'
    if psutil.virtual_memory().available/2**20<config.get('minimum_free_memory_mb',3000):return 'LOW_FREE_MEMORY'
    if psutil.cpu_percent(interval=.25)>config.get('maximum_start_cpu_percent',35):return 'COMPUTER_BUSY'
    root=Path(config['state_dir']);root.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(root).free/2**20<config.get('minimum_free_disk_mb',8000):return 'LOW_FREE_DISK'
    if (root/'PAUSE').exists():return 'PAUSED'
    return None

def run_once(config):
    root=Path(config['state_dir']).resolve();repo=Path(config['repository']).resolve()
    if root.is_relative_to(repo):raise ValueError('High-write state must be outside the source/OneDrive repository')
    wall=int(config.get('max_wall_seconds',1800));rss=int(config.get('max_tree_memory_mb',4096))
    if not 30<=wall<=3300 or not 512<=rss<=8192:raise ValueError('Runner resource limits outside permitted range')
    store=Store(root);owner=str(uuid.uuid4())
    try:
        if store.verify():return dict(status='BLOCKED',reason='AUDIT_CHAIN_INVALID',handoff=export(store))
        if not store.acquire(owner,seconds=wall+120):return {'status':'ANOTHER_RUNNER_ACTIVE'}
        job=None
        try:
            reason=policy(config)
            if reason:
                with store.db:store.event('RESOURCE_WAIT',reason=reason)
                bundle=export(store);return dict(status='WAITING',reason=reason,handoff=bundle)
            today=datetime.now(timezone(timedelta(hours=8))).date();used=0.
            for event in store.db.execute('SELECT payload FROM events'):
                entry=json.loads(event[0])
                if entry.get('kind')=='FINISHED' and datetime.fromisoformat(entry['utc']).astimezone(timezone(timedelta(hours=8))).date()==today:used+=entry.get('wall_seconds',0)
            remaining=float(config.get('daily_compute_seconds',7200))-used
            if remaining<30:return dict(status='WAITING',reason='DAILY_COMPUTE_BUDGET',handoff=export(store))
            wall=min(wall,int(remaining))
            if config.get('plan_file'):
                plan_path=Path(config['plan_file'])
                if not plan_path.is_file():
                    with store.db:store.event('CONFIGURATION_BLOCKED',reason='PLAN_FILE_MISSING')
                    return dict(status='BLOCKED',reason='PLAN_FILE_MISSING',handoff=export(store))
                plan=json.loads(plan_path.read_text(encoding='utf8'))
                if not isinstance(plan,list) or len(plan)>10000:raise ValueError('Invalid finite experiment plan')
                for entry in plan:
                    try:store.enqueue(entry['kind'],freeze_payload(entry['payload']))
                    except (FileNotFoundError,ValueError) as exc:
                        payload=dict(entry['payload'],_programme_code_sha256=code_sha(),preflight_blocker=str(exc))
                        blocked=store.enqueue(entry['kind'],payload)
                        if store.db.execute('SELECT status FROM jobs WHERE id=?',(blocked,)).fetchone()[0]!='BLOCKED':
                            store.finish(blocked,'BLOCKED',{'reason':str(exc),'candidate_only':True})
            job=store.next()
            if job is None:return dict(status='IDLE',handoff=export(store))
            if digest([job['kind'],json.loads(job['payload'])])[:24]!=job['id']:raise ValueError('Job payload integrity mismatch')
            out=root/'jobs'/job['id'];out.mkdir(parents=True,exist_ok=True)
            request=out/'job.json';request.write_text(json.dumps(job),encoding='utf8')
            tool=repo/'tools/tr1_train'
            if not (tool/'tr1train/guard.py').is_file():
                result=dict(status='BLOCKED',reason='Existing guarded trainer is missing');store.finish(job['id'],'BLOCKED',result);return result
            sys.path.insert(0,str(tool))
            from tr1train.guard import run_guarded
            env=dict(os.environ);env['PYTHONPATH']=str(repo/'src');env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
            worker_python=config['core_python'] if job['kind']=='EXPERIMENT_WP08' else config['backend_python']
            cmd=[worker_python,'-m','pid_reader.engineering.longterm.worker',str(request),str(out)]
            guarded=run_guarded(cmd,cwd=str(repo),env=env,max_wall_s=wall,max_rss_mb=rss,cancel_file=str(root/'CANCEL'),
                                stdout_path=str(out/'stdout.log'),stderr_path=str(out/'stderr.log'))
            result_path=out/'worker_result.json'
            if guarded['state']=='COMPLETED' and result_path.is_file():
                result=json.loads(result_path.read_text());status=result['status']
            else:
                status='PARTIAL' if job['kind']=='TRAIN_OCR' and (out/'LATEST.json').exists() else 'CANCELLED' if guarded['state']=='CANCELLED' else 'FAILED'
                result=dict(status=status,guard=guarded,reason='Inspect guarded worker diagnostics; no success inferred')
            if job['kind']=='EXPERIMENT_WP08' and status=='PARTIAL':
                # Keep partial evidence but do not spend every hour repeating the same capped selection.
                status='BLOCKED';result['next_action']='Adjust the recorded coverage budget or enqueue another explicit configuration'
            if job['kind']=='TRAIN_OCR' and status in ('PARTIAL','SUCCEEDED') and result.get('candidate_manifest') and config.get('validation_dataset'):
                payload=json.loads(job['payload'])
                try:
                    validate(config['validation_dataset'],purpose='validate')
                    evaluation=freeze_payload(dict(dataset_path=config['validation_dataset'],training_dataset_path=payload['dataset_path'],
                        model_manifest_path=payload['model_manifest_path'],candidate_manifest_path=result['candidate_manifest']))
                    result['evaluation_job']=store.enqueue('EVALUATE_OCR',evaluation)
                except (ValueError,OSError,KeyError) as exc:result['evaluation_blocked_by']=str(exc)
            result['guard']=guarded;store.finish(job['id'],status,result)
            return dict(status=status,job=job['id'],result=result,handoff=export(store))
        except Exception as exc:
            result=dict(status='FAILED' if job else 'BLOCKED',reason=type(exc).__name__+': '+str(exc))
            if job:store.finish(job['id'],'FAILED',result)
            else:
                with store.db:store.event('CONFIGURATION_BLOCKED',reason=result['reason'])
            return dict(result,handoff=export(store))
        finally:store.release(owner)
    finally:store.close()
