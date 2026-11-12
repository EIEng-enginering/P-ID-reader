"""Paired exact-string evaluation on reviewed development crops only."""
import json
from pathlib import Path
from .data import validate,sha,score

def evaluate(payload,out):
    import torch
    from PIL import Image
    from transformers import TrOCRProcessor,VisionEncoderDecoderModel
    from ..model_lab.core import verify_model
    from ..model_lab.offline import deny_network
    rows,fingerprint=validate(payload['dataset_path'],purpose='validate')
    if fingerprint!=payload['dataset_sha256']:raise ValueError('Validation manifest changed after enqueue')
    train_rows,training_sha=validate(payload['training_dataset_path'])
    if {r['family_id'] for r in rows}&{r['family_id'] for r in train_rows} or {r['source_sha256'] for r in rows}&{r['source_sha256'] for r in train_rows} or {r['image_sha256'] for r in rows}&{r['image_sha256'] for r in train_rows}:raise ValueError('Training/validation document leakage')
    torch.set_num_threads(2);reports={}
    with deny_network():
        for label,key in [('baseline','model_manifest_path'),('candidate','candidate_manifest_path')]:
            manifest=json.loads(Path(payload[key]).read_text());root=verify_model(manifest)
            if label=='candidate':
                provenance=json.loads((root/'checkpoint.json').read_text())
                if provenance['dataset_sha256']!=training_sha:raise ValueError('Candidate training provenance differs from declared training data')
            processor=TrOCRProcessor.from_pretrained(str(root),local_files_only=True,use_fast=False)
            model=VisionEncoderDecoderModel.from_pretrained(str(root),local_files_only=True,use_safetensors=True).to('cpu').eval();texts=[]
            with torch.inference_mode():
                for row in rows:
                    with Image.open(row['image_path']) as image:
                        if image.width*image.height>4_000_000:raise ValueError('Evaluation crop exceeds pixel budget')
                        values=processor(images=image.convert('RGB'),return_tensors='pt').pixel_values
                    ids=model.generate(values,max_new_tokens=96);texts.append(processor.batch_decode(ids,skip_special_tokens=True)[0])
            reports[label]=score(rows,texts);del model
    return dict(status='SUCCEEDED',reports=reports,dataset_sha256=fingerprint,
                exact_delta=reports['candidate']['exact']-reports['baseline']['exact'],
                candidate_only=True,promoted=False,engineering_acceptance='NOT_RUN')
