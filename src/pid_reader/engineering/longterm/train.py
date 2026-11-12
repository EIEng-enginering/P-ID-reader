"""CPU TrOCR candidate fine-tuning, checkpointed by step; never activates a model."""
import hashlib,json,os,random,shutil,time,sys,importlib.metadata
from pathlib import Path
from .data import validate,sha
from .store import canonical,digest

def atomic_json(path,value):
    path=Path(path);tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(value,indent=2),encoding='utf8');os.replace(tmp,path)

def verify_checkpoint(path,payload):
    doc=json.loads((path/'checkpoint.json').read_text())
    if doc['job_fingerprint']!=digest(payload):raise ValueError('Checkpoint belongs to another job/config')
    for name,expected in doc['files'].items():
        f=path/name
        if not f.resolve().is_relative_to(path.resolve()) or sha(f)!=expected:raise ValueError('Checkpoint hash mismatch')
    return doc

def train(payload,out):
    import torch
    from PIL import Image
    from transformers import TrOCRProcessor,VisionEncoderDecoderModel
    from ..model_lab.core import verify_model
    from ..model_lab.offline import deny_network
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    runtime=dict(python=sys.version.split()[0],torch=torch.__version__,transformers=importlib.metadata.version('transformers'))
    rows,dataset_sha=validate(payload['dataset_path'])
    if dataset_sha!=payload['dataset_sha256']:raise ValueError('Dataset manifest changed after enqueue')
    manifest_path=Path(payload['model_manifest_path'])
    if sha(manifest_path)!=payload['model_manifest_sha256']:raise ValueError('Base model manifest changed after enqueue')
    manifest=json.loads(manifest_path.read_text());base=verify_model(manifest)
    if manifest['engine']!='trocr':raise ValueError('OCR training requires the staged TrOCR model')
    if (base/'checkpoint.json').exists():raise ValueError('Cross-candidate chaining requires cumulative data provenance; resume the same job or use the provisioned base')
    steps=int(payload.get('max_steps',100));slice_seconds=float(payload.get('slice_seconds',1200));seed=int(payload.get('seed',20261112))
    if not 1<=steps<=100000 or not 1<=slice_seconds<=3000:raise ValueError('Training budget out of range')
    lr=float(payload.get('lr',1e-5));last_layers=int(payload.get('last_layers',1))
    if not 1e-7<=lr<=1e-3 or not 1<=last_layers<=2:raise ValueError('Training hyperparameter outside bounded search')
    torch.set_num_threads(2);torch.manual_seed(seed);torch.use_deterministic_algorithms(True)
    latest=out/'LATEST.json';checkpoint=None;previous=None
    if latest.exists():
        name=json.loads(latest.read_text())['directory'];checkpoint=out/name
        if not checkpoint.resolve().is_relative_to(out.resolve()):raise ValueError('Checkpoint path escape')
        previous=verify_checkpoint(checkpoint,payload)
        if previous.get('runtime') is not None and previous['runtime']!=runtime:raise ValueError('Training runtime changed; create a new explicit job version')
    with deny_network():
        processor=TrOCRProcessor.from_pretrained(str(checkpoint or base),local_files_only=True,use_fast=False)
        model=VisionEncoderDecoderModel.from_pretrained(str(checkpoint or base),local_files_only=True,use_safetensors=True).to('cpu')
        if model.config.decoder_start_token_id is None:
            model.config.decoder_start_token_id=model.generation_config.decoder_start_token_id
        if model.config.decoder_start_token_id is None:model.config.decoder_start_token_id=processor.tokenizer.cls_token_id
        model.config.pad_token_id=processor.tokenizer.pad_token_id
        for parameter in model.parameters():parameter.requires_grad=False
        for layer in model.decoder.model.decoder.layers[-last_layers:]:
            for parameter in layer.parameters():parameter.requires_grad=True
        for parameter in model.decoder.output_projection.parameters():parameter.requires_grad=True
        names=[name for name,parameter in model.named_parameters() if parameter.requires_grad]
        optimizer=torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],lr=lr)
        step=0
        if checkpoint:
            state=torch.load(checkpoint/'optimizer.pt',map_location='cpu',weights_only=True)
            optimizer.load_state_dict(state['optimizer']);step=state['step'];torch.set_rng_state(state['rng'])
        start=time.monotonic();model.train();losses=[];interval=int(payload.get('checkpoint_every',10))
        if not 1<=interval<=100:raise ValueError('Checkpoint interval out of range')
        def save():
            dest=out/f'checkpoint-{step:08d}'
            if not dest.exists():
                stage=out/f'.checkpoint-{step:08d}-{os.getpid()}';stage.mkdir(exist_ok=False)
                try:
                    model.save_pretrained(stage,safe_serialization=True);processor.save_pretrained(stage)
                    torch.save(dict(optimizer=optimizer.state_dict(),step=step,rng=torch.get_rng_state()),stage/'optimizer.pt')
                    info=dict(step=step,job_fingerprint=digest(payload),dataset_sha256=dataset_sha,runtime=runtime,
                              files={p.name:sha(p) for p in stage.iterdir() if p.is_file()})
                    (stage/'checkpoint.json').write_text(json.dumps(info,indent=2));os.replace(stage,dest)
                finally:
                    if stage.exists():shutil.rmtree(stage)
            atomic_json(latest,dict(directory=dest.name,step=step))
            # Retain the latest two full recovery points, not an unbounded weight archive.
            older=sorted([p for p in out.glob('checkpoint-*') if p.is_dir() and p.name[11:].isdigit()])
            for stale in older[:-2]:shutil.rmtree(stale)
            return dest
        start_step=step;steps_per_slice=int(payload.get('max_steps_per_slice',steps))
        if not 1<=steps_per_slice<=100000:raise ValueError('Step slice budget')
        while step<steps and step-start_step<steps_per_slice:
            if time.monotonic()-start>=slice_seconds:break
            order=list(range(len(rows)));random.Random(seed+step//len(rows)).shuffle(order)
            row=rows[order[step%len(rows)]]
            with Image.open(row['image_path']) as image:
                if image.width*image.height>4_000_000:raise ValueError('Training crop exceeds pixel budget')
                pixels=processor(images=image.convert('RGB'),return_tensors='pt').pixel_values
            labels=processor.tokenizer(row['text'],return_tensors='pt',truncation=False).input_ids
            if labels.shape[1]>96:raise ValueError('Label token budget exceeded')
            optimizer.zero_grad(set_to_none=True);loss=model(pixel_values=pixels,labels=labels).loss
            if not torch.isfinite(loss):raise ValueError('Nonfinite training loss')
            loss.backward();torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad],1.)
            optimizer.step();step+=1;value=float(loss.detach());losses.append(value)
            with (out/'losses.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(dict(step=step,loss=value))+'\n')
            if step%interval==0:save()
        saved=save()
    candidate=dict(manifest,model_dir=str(saved),revision='LOCAL_CANDIDATE_'+digest(payload)[:12]+'_'+str(step),
                   files={p.name:sha(p) for p in saved.iterdir() if p.is_file()})
    atomic_json(out/'candidate.manifest.json',candidate)
    immutable_manifest=out/f'candidate-step-{step:08d}.manifest.json'
    atomic_json(immutable_manifest,candidate)
    result=dict(status='SUCCEEDED' if step==steps else 'PARTIAL',steps=step,target_steps=steps,
                candidate_manifest=str(immutable_manifest),candidate_only=True,promoted=False,
                data_origin='SYNTHETIC_ONLY' if all(r['origin']=='SYNTHETIC' for r in rows) else 'REVIEWED_TRAINING',
                trainable_parameters=names,losses_this_slice=losses,elapsed_seconds=time.monotonic()-start,
                recognition_accuracy='NOT_MEASURED',dataset_sha256=dataset_sha,runtime=runtime)
    atomic_json(out/'training_summary.json',result);return result
