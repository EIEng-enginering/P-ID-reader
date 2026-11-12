"""Dataset boundaries and honest fixed-crop scoring."""
import hashlib,json,importlib.resources
from pathlib import Path

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def validate(path,*,purpose='train'):
    path=Path(path);doc=json.loads(path.read_text(encoding='utf8'))
    if doc.get('schema')!='pid-longterm-crops-v1':raise ValueError('Unknown dataset schema')
    rows=doc.get('items',[])
    if not 1<=len(rows)<=100000:raise ValueError('Dataset size must be 1..100000')
    ids=set();families={};sources={};images={};selected=[]
    for r in rows:
        if r['id'] in ids:raise ValueError('Duplicate item id')
        ids.add(r['id']);split=r['split']
        if split=='RESERVED_FINAL':raise ValueError('Reserved final data is forbidden in long-term programme manifests')
        if split not in ('TRAIN','VALIDATION'):raise ValueError('Explicit TRAIN/VALIDATION split required')
        for mapping,key in ((families,r['family_id']),(sources,r['source_sha256']),(images,r['image_sha256'])):
            if key in mapping and mapping[key]!=split:raise ValueError('Source/revision family split leakage')
            mapping[key]=split
        if r['origin']=='SYNTHETIC':
            if split!='TRAIN':raise ValueError('Synthetic samples cannot be validation evidence')
        elif r['origin']=='VECTOR_TEXT_LAYER':
            # Exact string from the document's own CAD text layer rendered and degraded to look like a scan: PROXY training data only.
            if split!='TRAIN':raise ValueError('Text-layer proxy samples can only be TRAIN (never validation evidence)')
            if r.get('review_status')!='EXACT_FROM_DOCUMENT_TEXT_LAYER':raise ValueError('Text-layer samples must declare their provenance')
            if type(r.get('page')) is not int or r['page']<1 or r.get('coordinate_frame')!='MEDIA_NORMALIZED_TOP_LEFT':raise ValueError('Text-layer crops need source page and explicit coordinate frame')
            if sha(Path(r['source_path']))!=r['source_sha256']:raise ValueError('Source drawing bytes changed')
        elif r['origin']=='HUMAN_SOURCE_PIXELS':
            if r.get('review_status')!='VERIFIED_DEVELOPMENT' or not r.get('reviewer','').strip():raise ValueError('Real labels need source-pixel review; OCR output is not a training label')
            if type(r.get('page')) is not int or r['page']<1 or r.get('coordinate_frame')!='MEDIA_NORMALIZED_TOP_LEFT':raise ValueError('Real crops need source page and explicit coordinate frame')
            from ..model_lab.core import bbox
            bbox([r['bbox'][k] for k in ('x0','y0','x1','y1')])
            source=Path(r['source_path'])
            if sha(source)!=r['source_sha256']:raise ValueError('Source drawing bytes changed')
        else:raise ValueError('Unreviewed/pseudo labels are not supervised ground truth')
        if not isinstance(r.get('text'),str) or not r['text'] or len(r['text'])>160:raise ValueError('Invalid exact text label')
        image=Path(r['image_path']);image=image if image.is_absolute() else path.parent/image
        if sha(image)!=r['image_sha256']:raise ValueError('Crop bytes changed')
        row=dict(r,image_path=str(image.resolve()))
        if (purpose=='train' and split=='TRAIN') or (purpose=='validate' and split=='VALIDATION'):selected.append(row)
    if not selected:raise ValueError('No eligible '+purpose+' samples')
    return selected,sha(path)

def distance(a,b):
    previous=list(range(len(b)+1))
    for i,ca in enumerate(a,1):
        current=[i]
        for j,cb in enumerate(b,1):current.append(min(current[-1]+1,previous[j]+1,previous[j-1]+(ca!=cb)))
        previous=current
    return previous[-1]

def score(rows,predictions):
    if len(rows)!=len(predictions):raise ValueError('Predictions do not cover the declared reference')
    items=[dict(id=r['id'],reference=r['text'],observed=p,exact=r['text']==p,edit_distance=distance(r['text'],p)) for r,p in zip(rows,predictions)]
    chars=sum(len(r['text']) for r in rows)
    return dict(status='MEASURED_REVIEWED_DEVELOPMENT_CROPS',scope='Fixed supplied crops; not page discovery, symbols, topology or engineering validation',
                samples=len(rows),exact=sum(r['exact'] for r in items),cer=sum(r['edit_distance'] for r in items)/chars,items=items)


def code_sha():
    root=importlib.resources.files('pid_reader.engineering.longterm')
    return hashlib.sha256(b''.join(root.joinpath(name).read_bytes() for name in ('train.py','data.py','evaluate.py','worker.py'))).hexdigest()

def freeze_payload(payload):
    payload=dict(payload)
    payload['_programme_code_sha256']=code_sha()
    for name in ('dataset_path','training_dataset_path','model_manifest_path','candidate_manifest_path','pdf_path','discovery_manifest','line_manifest'):
        if name in payload:payload[name+'_sha256']=sha(payload[name])
    if 'dataset_path' in payload:payload['dataset_sha256']=payload['dataset_path_sha256']
    if 'model_manifest_path' in payload:payload['model_manifest_sha256']=payload['model_manifest_path_sha256']
    return payload
