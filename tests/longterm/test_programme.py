import hashlib,json
from pathlib import Path
from unittest.mock import patch
import pytest
from pid_reader.engineering.longterm.store import Store
from pid_reader.engineering.longterm.data import validate,score,sha
from pid_reader.engineering.longterm.handoff import export

def dataset(tmp_path,**extra):
    image=tmp_path/'crop.png';image.write_bytes(b'fixture')
    row=dict(id='one',split='TRAIN',family_id='family',source_sha256='a'*64,origin='SYNTHETIC',text='FR-720201',image_path=image.name,image_sha256=sha(image))
    row.update(extra);path=tmp_path/'dataset.json';path.write_text(json.dumps({'schema':'pid-longterm-crops-v1','items':[row]}));return path,row

def test_synthetic_train_allowed_validation_forbidden(tmp_path):
    path,row=dataset(tmp_path);assert len(validate(path)[0])==1
    row['split']='VALIDATION';path.write_text(json.dumps({'schema':'pid-longterm-crops-v1','items':[row]}))
    with pytest.raises(ValueError):validate(path,purpose='validate')

def test_pseudo_labels_are_not_ground_truth(tmp_path):
    path,_=dataset(tmp_path,origin='OCR_PREDICTION')
    with pytest.raises(ValueError):validate(path)

def test_reserved_final_is_never_consumed(tmp_path):
    path,_=dataset(tmp_path,split='RESERVED_FINAL')
    with pytest.raises(ValueError):validate(path)

def test_source_revision_family_leak_rejected(tmp_path):
    path,row=dataset(tmp_path);second=dict(row,id='two',split='VALIDATION',source_sha256='b'*64)
    path.write_text(json.dumps({'schema':'pid-longterm-crops-v1','items':[row,second]}))
    with pytest.raises(ValueError):validate(path)

def test_crop_hash_change_rejected(tmp_path):
    path,_=dataset(tmp_path);(tmp_path/'crop.png').write_bytes(b'changed')
    with pytest.raises(ValueError):validate(path)

def test_exact_scoring_does_not_fix_o_zero_or_dot():
    rows=[{'id':'a','text':'HPF-00019-114.3'},{'id':'b','text':'V-2201'}]
    result=score(rows,['HPF-OOO19-1143','V-2201'])
    assert result['exact']==1 and result['items'][0]['edit_distance']==4

def test_missing_prediction_not_success():
    with pytest.raises(ValueError):score([{'id':'a','text':'FR'}],[])

def test_queue_idempotence_and_recovery(tmp_path):
    s=Store(tmp_path);jid=s.enqueue('TRAIN_OCR',{'x':1});assert s.enqueue('TRAIN_OCR',{'x':1})==jid
    assert s.acquire('first',1);assert not s.acquire('second',1);job=s.next();assert job['id']==jid
    s.release('first');assert s.acquire('second');assert s.next()['id']==jid
    s.finish(jid,'PARTIAL',{'steps':1});assert s.verify()==[];s.release('second');s.close()

def test_audit_append_only(tmp_path):
    s=Store(tmp_path);s.enqueue('TRAIN_OCR',{})
    with pytest.raises(Exception):s.db.execute('DELETE FROM events')
    assert s.verify()==[];s.close()

def test_bundle_excludes_weights_and_drawings(tmp_path):
    import zipfile
    s=Store(tmp_path);jid=s.enqueue('TRAIN_OCR',{});s.finish(jid,'SUCCEEDED',{'candidate_only':True,'steps':2})
    (tmp_path/'secret.pdf').write_bytes(b'private');(tmp_path/'model.safetensors').write_bytes(b'large weights')
    path=export(s);assert Path(path).exists() and export(s) is None
    with zipfile.ZipFile(path) as z:assert not any(n.endswith(('.pdf','.safetensors','.pt')) for n in z.namelist())
    s.close()

def test_resource_policy_on_battery(tmp_path):
    from pid_reader.engineering.longterm.runner import policy
    import types,sys
    fake=types.SimpleNamespace(sensors_battery=lambda:types.SimpleNamespace(power_plugged=False))
    with patch.dict(sys.modules,{'psutil':fake}):assert policy({'state_dir':str(tmp_path)})=='ON_BATTERY'

def test_state_inside_repo_refused(tmp_path):
    from pid_reader.engineering.longterm.runner import run_once
    with pytest.raises(ValueError):run_once({'repository':str(tmp_path),'state_dir':str(tmp_path/'state')})

def test_changed_results_refresh_same_day_bundle(tmp_path):
    s=Store(tmp_path);first=s.enqueue('TRAIN_OCR',{'seed':1});a=export(s)
    s.finish(first,'SUCCEEDED',{'steps':1});b=export(s)
    assert a==b and b is not None and export(s) is None;s.close()

def test_unknown_job_kind_is_not_an_arbitrary_command(tmp_path):
    s=Store(tmp_path)
    with pytest.raises(ValueError):s.enqueue('SHELL',{'command':'anything'})
    s.close()

def test_job_inputs_are_frozen_to_bytes(tmp_path):
    from pid_reader.engineering.longterm.data import freeze_payload
    path,_=dataset(tmp_path);payload=freeze_payload({'dataset_path':str(path)})
    assert payload['dataset_sha256']==sha(path)

def test_dataset_without_validation_cannot_report_accuracy(tmp_path):
    path,_=dataset(tmp_path)
    with pytest.raises(ValueError):validate(path,purpose='validate')

def test_claude_bridge_disabled_does_not_start_cli():
    from pid_reader.engineering.longterm.claude_bridge import review
    with patch('subprocess.run',side_effect=AssertionError('must not run')):assert review({})['status']=='DISABLED'

def test_claude_bridge_needs_explicit_usage_budget():
    from pid_reader.engineering.longterm.claude_bridge import review
    with pytest.raises(ValueError):review({'claude_review_enabled':True})

def test_claude_bridge_sends_only_metrics_and_disables_tools(tmp_path):
    from pid_reader.engineering.longterm.claude_bridge import review
    import subprocess,sys
    s=Store(tmp_path);job=s.enqueue('TRAIN_OCR',{});s.finish(job,'SUCCEEDED',{'steps':2,'raw_transcription':'PRIVATE-DO-NOT-SEND','candidate_only':True});export(s);s.close()
    config=dict(state_dir=str(tmp_path),claude_review_enabled=True,claude_cli=sys.executable,claude_max_budget_usd=.1)
    def respond(args,**kwargs):
        assert '--tools' in args and args[args.index('--tools')+1]=='' and '--safe-mode' in args
        assert 'PRIVATE-DO-NOT-SEND' not in kwargs['input']
        return subprocess.CompletedProcess(args,0,stdout='{"is_error": false, "result": "Synthetic smoke only"}',stderr='')
    with patch('subprocess.run',side_effect=respond):assert review(config)['status']=='REVIEWED_BY_LOCAL_CLAUDE_CLI'
    assert review(config)['status']=='ALREADY_ATTEMPTED_TODAY'

def test_new_frozen_jobs_pin_programme_code(tmp_path):
    from pid_reader.engineering.longterm.data import freeze_payload,code_sha
    path,_=dataset(tmp_path);p=freeze_payload({'dataset_path':str(path)})
    assert p['_programme_code_sha256']==code_sha()

def test_missing_plan_is_blocked_with_a_handoff(tmp_path):
    from pid_reader.engineering.longterm.runner import run_once
    repo=tmp_path/'repo';repo.mkdir();state=tmp_path/'state'
    with patch('pid_reader.engineering.longterm.runner.policy',return_value=None):
        result=run_once(dict(repository=str(repo),state_dir=str(state),plan_file=str(tmp_path/'missing.json')))
    assert result['status']=='BLOCKED' and result['reason']=='PLAN_FILE_MISSING' and Path(result['handoff']).exists()

def test_checkpointed_partial_training_queues_paired_validation(tmp_path,monkeypatch):
    import types,sys
    from pid_reader.engineering.longterm.runner import run_once
    repo=tmp_path/'repo';tool=repo/'tools/tr1_train/tr1train';tool.mkdir(parents=True);(tool/'guard.py').touch()
    state=tmp_path/'state';crop=tmp_path/'crop';crop.write_bytes(b'crop')
    source=tmp_path/'source';source.write_bytes(b'real drawing')
    row=dict(id='v',split='VALIDATION',family_id='held-out-family',source_sha256=sha(source),origin='HUMAN_SOURCE_PIXELS',
             source_path=str(source),page=1,bbox=dict(x0=.1,y0=.1,x1=.3,y1=.2),coordinate_frame='MEDIA_NORMALIZED_TOP_LEFT',review_status='VERIFIED_DEVELOPMENT',reviewer='Analyst',text='FR-720201',image_path=str(crop),image_sha256=sha(crop))
    val=tmp_path/'val.json';val.write_text(json.dumps({'schema':'pid-longterm-crops-v1','items':[row]}))
    train=tmp_path/'train.json';train.write_text('{}');base=tmp_path/'base.json';base.write_text('{}');candidate=tmp_path/'candidate.json';candidate.write_text('{}')
    s=Store(state);s.enqueue('TRAIN_OCR',{'dataset_path':str(train),'model_manifest_path':str(base)});s.close()
    def guarded(*args,**kwargs):
        out=Path(kwargs['stdout_path']).parent
        (out/'worker_result.json').write_text(json.dumps({'status':'PARTIAL','steps':25,'candidate_manifest':str(candidate)}))
        return dict(state='COMPLETED',wall_s=1,peak_tree_rss_mb=20,processes_left_after_kill=[])
    module=types.ModuleType('tr1train.guard');module.run_guarded=guarded
    monkeypatch.setitem(sys.modules,'tr1train',types.ModuleType('tr1train'));monkeypatch.setitem(sys.modules,'tr1train.guard',module)
    monkeypatch.setattr('pid_reader.engineering.longterm.runner.policy',lambda config:None)
    result=run_once(dict(repository=str(repo),state_dir=str(state),backend_python=sys.executable,validation_dataset=str(val)))
    assert result['status']=='PARTIAL' and result['result']['evaluation_job']
    s=Store(state);assert s.next()['kind']=='EVALUATE_OCR';s.close()
