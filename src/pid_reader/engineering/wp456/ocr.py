"""WP04 bounded, cancellable local Tesseract re-read, UTF-8 TSV and rotations.

No Python OCR wrapper dependency, shell, model download or network call. The
host supplies a renderer that returns (Pillow image, render-box-to-media mapper).
"""
from __future__ import annotations
import csv
import io
import os
from pathlib import Path
import shutil
import subprocess
import time
from .common import STATE, box, evidence_rows, ident, number, source_hash


class TesseractUnavailable(RuntimeError):
    pass


def locate_tesseract():
    candidates = [os.environ.get('TESSERACT_CMD'), shutil.which('tesseract'),
                  'C:/Program Files/Tesseract-OCR/tesseract.exe',
                  'C:/Program Files (x86)/Tesseract-OCR/tesseract.exe',
                  str(Path(os.environ.get('LOCALAPPDATA',''))/'Programs/Tesseract-OCR/tesseract.exe')]
    return next((str(Path(p)) for p in candidates if p and Path(p).is_file()), None)


def unrotate_box(b, angle):
    """Box from an image rotated counterclockwise by angle -> original crop."""
    box(b)
    if angle not in (0,90,180,270): raise ValueError('Unsupported rotation')
    def inv(x,y):
        return ((x,y) if angle==0 else (1-y,x) if angle==90 else
                (1-x,1-y) if angle==180 else (y,1-x))
    points=[inv(x,y) for x in (b['x0'],b['x1']) for y in (b['y0'],b['y1'])]
    return box({'x0':min(x for x,y in points),'y0':min(y for x,y in points),
                'x1':max(x for x,y in points),'y1':max(y for x,y in points)})


def tesseract_tsv(image, *, command, psm, timeout):
    data=io.BytesIO(); image.save(data,format='PNG')
    run=subprocess.run([command,'stdin','stdout','--psm',str(psm),'-l','eng','tsv'],
                       input=data.getvalue(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                       timeout=timeout,check=False,
                       creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0)  # no console flash from the windowed app
    if run.returncode:
        raise RuntimeError('TESSERACT_PROCESS_FAILED: '+run.stderr.decode('utf8',errors='replace')[-400:])
    return list(csv.DictReader(io.StringIO(run.stdout.decode('utf8',errors='strict')),delimiter='\t'))


def reread(regions, *, source_sha256, renderer, command=None, rotations=(0,90,270),
           psms=(6,11), total_seconds=90., call_seconds=8., max_regions=8,
           cancelled=lambda:False, engine=tesseract_tsv, clock=time.monotonic):
    """All partial output includes explicit diagnostics. No silent OCR failure."""
    source_hash(source_sha256); evidence_rows(regions)
    number(total_seconds,.1,300); number(call_seconds,.1,30)
    if type(max_regions) is not int or not 1<=max_regions<=24:
        raise ValueError('Invalid OCR region budget')
    if not rotations or len(rotations)>4 or any(a not in (0,90,180,270) for a in rotations):
        raise ValueError('Unsupported rotations')
    if not psms or len(psms)>2 or any(a not in (6,11) for a in psms):
        raise ValueError('Unsupported segmentation modes')
    command=command or locate_tesseract()
    if not command:
        raise TesseractUnavailable('Tesseract program is not installed. Install it locally or set TESSERACT_CMD.')
    started=clock(); words=[]; diagnostics=[]; calls=0
    for roi in regions[:max_regions]:
        if cancelled() or clock()-started>=total_seconds:
            diagnostics.append({'roi_id':roi['id'],'status':'CANCELLED_OR_TIME_BUDGET'}); break
        image=None
        try:
            image,mapper=renderer(roi)
            if image.width*image.height>3_500_000:
                raise ValueError('Crop exceeds pixel budget')
            for angle in rotations:
                for psm in psms:
                    remaining=total_seconds-(clock()-started)
                    if cancelled() or remaining<=0:
                        diagnostics.append({'roi_id':roi['id'],'status':'CANCELLED_OR_TIME_BUDGET'}); break
                    rotated=image.rotate(angle,expand=True)
                    run_id=ident('ocr-run',source_sha256,roi['id'],angle,psm)
                    try:
                        calls+=1
                        rows=engine(rotated,command=command,psm=psm,timeout=min(call_seconds,remaining))
                        if len(rows)>10000: raise ValueError('TSV row budget exceeded')
                        for index,row in enumerate(rows):
                            text=str(row.get('text','')).strip()
                            if not text or len(text)>200: continue
                            try:
                                score=number(float(row['conf'])/100)
                                l,t,w,h=(float(row[k]) for k in ('left','top','width','height'))
                                if w<=0 or h<=0: continue
                                rb=box({'x0':l/rotated.width,'y0':t/rotated.height,
                                        'x1':(l+w)/rotated.width,'y1':(t+h)/rotated.height})
                            except (ValueError,KeyError,TypeError):
                                continue
                            mb=box(mapper(unrotate_box(rb,angle)))
                            words.append({'id':ident('ocr',run_id,index,text,mb),'page':roi['page'],'bbox':mb,
                                          'text':text,'raw_score':score,'run_id':run_id,'roi_id':roi['id'],
                                          'engine':'TESSERACT_LOCAL_TSV','rotation':angle,'psm':psm,'review_state':STATE})
                            if len(words)>10000: raise ValueError('OCR output word budget exceeded')
                        diagnostics.append({'roi_id':roi['id'],'run_id':run_id,'status':'SUCCESS'})
                    except (subprocess.TimeoutExpired,RuntimeError,UnicodeError) as exc:
                        diagnostics.append({'roi_id':roi['id'],'run_id':run_id,'status':'OCR_FAILED',
                                            'reason':type(exc).__name__+': '+str(exc)[:400]})
                    finally:
                        rotated.close()
                if cancelled() or clock()-started>=total_seconds: break
        finally:
            if image is not None: image.close()
    if len(regions)>max_regions:
        diagnostics.append({'status':'REGION_COUNT_BUDGET','omitted':len(regions)-max_regions})
    partial=any(d['status']!='SUCCESS' for d in diagnostics)
    return {'words':words,'diagnostics':diagnostics,'status':'PARTIAL' if partial else 'SUCCESS',
            'elapsed_seconds':clock()-started,'calls':calls}
