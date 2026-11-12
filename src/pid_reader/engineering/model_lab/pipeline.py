"""Frame-correct crops, independent coverage and optional WP04–06 bridge."""
from hashlib import sha256
from pathlib import Path
import tempfile
from .core import FRAME,digest
from .host import run,text_evidence

def grid_regions(frame,*,columns=4,rows=3,overlap=.12):
    if not 1<=columns<=8 or not 1<=rows<=8 or not 0<=overlap<=.4:raise ValueError('Grid budget')
    out=[]
    for y in range(rows):
        for x in range(columns):
            a=max(0,(x-overlap)/columns);b=max(0,(y-overlap)/rows)
            c=min(1,(x+1+overlap)/columns);d=min(1,(y+1+overlap)/rows)
            out.append(dict(id=f'coverage-{y}-{x}',bbox=frame.bbox_to_media(dict(x0=a,y0=b,x1=c,y1=d)),reason='INDEPENDENT_GRID_COVERAGE'))
    return out

VARIANTS=('base','small','large','binary')

def _otsu(gray):
    hist=gray.histogram();total=sum(hist);sum_all=sum(i*h for i,h in enumerate(hist));w0=0;s0=0;best=(0,128)
    for t in range(256):
        w0+=hist[t];s0+=t*hist[t]
        if w0==0 or w0==total:continue
        m0=s0/w0;m1=(sum_all-s0)/(total-w0);var=w0*(total-w0)*(m0-m1)**2
        if var>best[0]:best=(var,t)
    return best[1]

def variant_image(image,name):
    """Re-renderings of the SAME crop for an independent re-read. They add robustness checks, not new evidence."""
    from PIL import Image,ImageFilter,ImageOps
    if name=='base':return image.copy()
    gray=image.convert('L')
    try:
        if name=='small':return gray.resize((max(1,int(gray.width*.7)),max(1,int(gray.height*.7))),Image.Resampling.LANCZOS)
        if name=='large':return gray.resize((int(gray.width*1.4),int(gray.height*1.4)),Image.Resampling.BICUBIC).filter(ImageFilter.UnsharpMask(radius=2,percent=120,threshold=2))
        if name=='binary':
            t=_otsu(gray);return gray.point(lambda v:255 if v>t else 0)
    finally:gray.close()
    raise ValueError('Unknown crop variant')

def prepare(pdf_bytes,page,regions,directory,*,rotations=(0,),max_regions=8,variants=('base',)):
    from ..wp456.host import pdf_renderer
    if not regions:raise ValueError('No regions selected')
    if len(set(rotations))!=len(rotations) or any(r not in (0,90,180,270) for r in rotations):raise ValueError('Crop rotations')
    if not 1<=max_regions<=24:raise ValueError('Region budget')
    if not variants or len(set(variants))!=len(variants) or any(v not in VARIANTS for v in variants):raise ValueError('Crop variants')
    renderer=pdf_renderer(pdf_bytes);source=sha256(pdf_bytes).hexdigest();requests=[]
    for i,region in enumerate(regions[:max_regions]):
        if region.get('page',page)!=page:raise ValueError('Region page mismatch')
        roi=dict(region,page=page)
        image,mapper=renderer(roi)
        try:
            actual=mapper(dict(x0=0,y0=0,x1=1,y1=1))
            for rotation in rotations:
                rotated=image.rotate(rotation,expand=True)
                try:
                    for variant in variants:
                        if len(requests)>=24:raise ValueError('Crop/rotation count exceeds 24')
                        shaped=variant_image(rotated,variant)
                        path=Path(directory)/f'crop-{i}-{rotation}-{variant}.png'
                        try:shaped.save(path)
                        finally:shaped.close()
                        rid=str(region.get('id',f'roi-{i}'))+f'-rot{rotation}'+('' if variant=='base' else '-'+variant)
                        requests.append(dict(id=rid,page=page,bbox=[actual[k] for k in ('x0','y0','x1','y1')],
                                             rotation=rotation,coordinate_frame=FRAME,source_sha256=source,variant=variant,
                                             image_path=str(path),image_sha256=digest(path)))
                finally:rotated.close()
        finally:image.close()
    return requests,dict(requested_regions=len(regions),scheduled_regions=min(len(regions),max_regions),
                         omitted_regions=max(0,len(regions)-max_regions),crop_count=len(requests))

def compare(pdf_bytes,page,regions,manifest,*,python,enabled=False,timeout=90,cancelled=lambda:False,
            max_regions=8,rotations=(0,),variants=('base',),cache_dir=None,worker_archive=None,words=None,detections=None,segments=None,report=lambda f,m:None):
    if not enabled:return {'status':'DISABLED','records':[]}
    source=sha256(pdf_bytes).hexdigest()
    with tempfile.TemporaryDirectory(prefix='pid-model-crops-') as directory:
        report(.05,'Rendering source regions')
        requests,coverage=prepare(pdf_bytes,page,regions,directory,rotations=rotations,max_regions=max_regions,variants=variants)
        if cancelled():return {'status':'CANCELLED','records':[]}
        report(.15,'Comparing local model proposals')
        if cache_dir:
            for request in requests:request['cache_dir']=str(cache_dir)
        model_result=run(dict(enabled=True,model=manifest,requests=requests),python=python,timeout=timeout,cancelled=cancelled,worker_archive=worker_archive)
    # Source checks at the host boundary are mandatory even for a valid JSON worker response.
    for row in model_result.get('records',[]):
        if row.get('source_sha256')!=source or row.get('page')!=page:raise ValueError('Worker returned a different source/page')
    if coverage['omitted_regions'] and model_result['status']=='COMPLETE_PROPOSALS':model_result['status']='PARTIAL'
    report(.85,'Preparing reviewable alternatives')
    derived=None;derived_error=None
    if words is not None and detections is not None and model_result['status'] in ('COMPLETE_PROPOSALS','PARTIAL'):
        try:derived=derive(pdf_bytes,page,words,detections,model_result,segments=segments)
        except Exception as exc:derived_error=type(exc).__name__+': '+str(exc)
    from ..wp456.common import seal
    return seal(dict(schema='pid-reader-model-lab-v2',status='PARTIAL' if derived_error else model_result['status'],source_sha256=source,page=page,
                     review_state='PROPOSED_UNVERIFIED',model_result=model_result,coverage=coverage,
                     crops=[{k:v for k,v in r.items() if k!='image_path'} for r in requests],
                     model_manifest=manifest,derived_wp456=derived,derived_error=derived_error,accuracy_status='NOT_MEASURED'))

def derive(pdf_bytes,page,words,detections,model_result,*,segments=None,symbol_evidence=None):
    from ..wp123_session import analyse_page
    from ..wp456.host import dimensions
    from ..wp456.pipeline import build
    extra=text_evidence(model_result)
    # Do not silently truncate evidence or create a misleading successful result.
    if len(words)+len(extra)>5000:raise ValueError('Combined OCR evidence exceeds WP04 budget')
    combined=list(words)+extra
    upstream=analyse_page(pdf_bytes,page,combined,detections,scan_bubbles=True,profile='auto')
    return build(upstream,combined,page_sizes=dimensions(pdf_bytes),segments=segments,symbol_evidence=symbol_evidence)
