"""Model evidence contract. Scores retain their engine-specific meaning."""
import hashlib
import json
import math
from pathlib import Path

FRAME = 'MEDIA_NORMALIZED_TOP_LEFT'
ENGINES = {'easyocr', 'trocr', 'rfdetr'}

def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def bbox(value):
    if len(value)!=4 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in value):
        raise ValueError('Four finite coordinates required')
    a,b,c,d=map(float,value)
    if not 0<=a<c<=1 or not 0<=b<d<=1: raise ValueError('Box outside normalized page')
    return [a,b,c,d]

def verify_model(manifest):
    if manifest['engine'] not in ENGINES: raise ValueError('Unsupported engine')
    root=Path(manifest['model_dir']).resolve(strict=True)
    if not root.is_dir(): raise ValueError('Model directory required')
    for field in ('source_url','revision','license_note'):
        if not isinstance(manifest.get(field),str) or not manifest[field].strip(): raise ValueError('Missing '+field)
    expected=manifest.get('files',{})
    if not expected: raise ValueError('No verified model artifacts')
    # Reject omitted extra files, symlinks and path escapes before model loading.
    actual={str(p.relative_to(root)).replace('\\','/') for p in root.rglob('*') if p.is_file()}
    if actual!=set(expected): raise ValueError('Model inventory differs from manifest')
    for name,sha in expected.items():
        p=root/name
        if not p.resolve().is_relative_to(root) or p.is_symlink(): raise ValueError('Model path escape')
        if digest(p)!=sha: raise ValueError('Model hash mismatch: '+name)
    if manifest['engine']=='rfdetr':
        if manifest.get('checkpoint') not in expected: raise ValueError('Checkpoint must be inventoried')
        if not manifest.get('classes'): raise ValueError('Explicit checkpoint class mapping required')
    return root

def record(raw, request, manifest, image_size, index):
    w,h=image_size
    x0,y0,x1,y1=raw['xyxy']
    if any(not math.isfinite(float(v)) for v in raw['xyxy']): raise ValueError('Nonfinite model box')
    if not 0<=x0<x1<=w or not 0<=y0<y1<=h: raise ValueError('Model box outside crop')
    a,b,c,d=bbox(request['bbox'])
    u0,v0,u1,v1=x0/w,y0/h,x1/w,y1/h
    rotation=request.get('rotation',0)
    if rotation==90:u0,v0,u1,v1=1-v1,u0,1-v0,u1
    elif rotation==180:u0,v0,u1,v1=1-u1,1-v1,1-u0,1-v0
    elif rotation==270:u0,v0,u1,v1=v0,1-u1,v1,1-u0
    mapped=bbox([a+u0*(c-a),b+v0*(d-b),a+u1*(c-a),b+v1*(d-b)])
    score=raw.get('score')
    if score is not None and (isinstance(score,bool) or not math.isfinite(float(score)) or not 0<=float(score)<=1): raise ValueError('Invalid raw score')
    return dict(id=hashlib.sha256(json.dumps([request['source_sha256'],request['id'],manifest['engine'],manifest['revision'],request.get('image_sha256'),index],separators=(',',':')).encode()).hexdigest()[:32], page=request['page'],
                bbox=dict(zip(('x0','y0','x1','y1'),mapped)), text=raw.get('text'),
                class_id=raw.get('class_id'), class_name=raw.get('class_name'),
                kind=raw['kind'], raw_score=score, confidence_calibrated=False,
                review_state='PROPOSED_UNVERIFIED', engine=manifest['engine'],
                model_revision=manifest['revision'], run_id=request['id']+':'+manifest['engine'],
                model_manifest_sha256=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                crop_sha256=request.get('image_sha256'), roi_id=request['id'],
                source_sha256=request['source_sha256'], coordinate_frame=FRAME)

def validate_request(request):
    if request.get('coordinate_frame')!=FRAME: raise ValueError('Explicit MediaBox frame required')
    bbox(request['bbox'])
    if type(request.get('page')) is not int or request['page']<1: raise ValueError('Invalid page')
    if not isinstance(request.get('id'),str) or not request['id']: raise ValueError('ROI id required')
    sha=request.get('source_sha256','')
    if len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha): raise ValueError('Source SHA256 required')
    if digest(request['image_path'])!=request['image_sha256']: raise ValueError('Crop bytes changed')
    if request.get('rotation',0) not in (0,90,180,270): raise ValueError('Unsupported crop rotation')

def benchmark(reference, predictions):
    """Fixed-crop OCR comparison. Not page detection accuracy or graph accuracy."""
    if reference.get('status')!='HUMAN_VERIFIED': return {'status':'NOT_RUN','reason':'Reference needs human verification'}
    labels=reference['labels']
    ids=[r['roi_id'] for r in labels]
    if len(ids)!=len(set(ids)): raise ValueError('Duplicate reference ROI')
    if any(r.get('source_sha256')!=reference['source_sha256'] for r in predictions): raise ValueError('Source mismatch')
    exact=0; extra=0
    for label in labels:
        values=[r.get('text') for r in predictions if r['roi_id']==label['roi_id'] and r['kind']=='TEXT']
        exact+=values==[label['text']]
        extra+=max(0,len(values)-1)
    return {'status':'MEASURED_FIXED_CROPS','total':len(labels),'exact':exact,'extra_readings':extra,
            'exact_fraction':exact/len(labels) if labels else None,
            'scope':'Exact single reading per fixed ROI; no normalization, no page recall claim'}
