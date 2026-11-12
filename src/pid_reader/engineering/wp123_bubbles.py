"""WP-02 raster circle observations near OCR instrumentation clues.

This is NOT a symbol classifier. A drawn circular contour is a geometric
hypothesis, and an OCR word in its interior is not an accepted instrument.
Optional local OpenCV/PDFium; deterministic output and per-page budgets.
"""
from __future__ import annotations
from hashlib import sha256
from io import BytesIO
import math

from ..formats.page_coordinates import frame_from_pdfplumber
from .wp123_recovery import sid,digest,_box,_center,_region_hit,INSTRUMENT_CODES,LOOP_NUMBER,_clean_token


def _ring_support(gray, x:int,y:int,r:int)->float:
    h,w=gray.shape
    marks=0
    for k in range(24):
        angle=2*math.pi*k/24
        xx=int(round(x+r*math.cos(angle))); yy=int(round(y+r*math.sin(angle)))
        if 2<=xx<w-2 and 2<=yy<h-2 and gray[yy-1:yy+2,xx-1:xx+2].min()<155:
            marks+=1
    return marks/24


def circle_candidates_from_image(gray, words:list[dict], *, profile_regions:list[dict] | None=None,
                                 page:int=1,score_threshold:float=.62,max_proposals:int=400) -> list[dict]:
    import cv2
    import numpy as np
    if not isinstance(gray,np.ndarray) or gray.ndim!=2 or gray.dtype!=np.uint8:
        raise ValueError('Expected uint8 grayscale raster')
    h,w=gray.shape
    if h*w>10_000_000:raise ValueError('Circle raster exceeds pixel budget')
    circles=cv2.HoughCircles(cv2.medianBlur(gray,3),cv2.HOUGH_GRADIENT,dp=1.35,
                            minDist=11,param1=125,param2=23,minRadius=7,maxRadius=40)
    if circles is None:return []
    candidates=[]
    regions=profile_regions or []
    for x,y,r in circles[0]:
        x,y,r=float(x),float(y),float(r)
        box={'x0':max(0.,(x-r)/w),'y0':max(0.,(y-r)/h),'x1':min(1.,(x+r)/w),'y1':min(1.,(y+r)/h)}
        try:box=_box(box)
        except ValueError:continue
        if _region_hit(box,regions,page):continue
        support=_ring_support(gray,int(round(x)),int(round(y)),int(round(r)))
        if support<score_threshold:continue
        near=[];codes=[];numbers=[]
        for wd in words:
            if wd.get('page',page)!=page:continue
            b=wd['bbox'];wx,wy=_center(b)
            # Interior/near-center only. Nearby piping numbers must not be
            # treated as text inside the instrument bubble.
            if abs(wx-x/w)>.7*r/w or abs(wy-y/h)>.7*r/h:continue
            near.append(wd['id']);txt=_clean_token(wd['text']).strip('()')
            if txt in INSTRUMENT_CODES and len(txt)>1:codes.append(wd)
            if LOOP_NUMBER.fullmatch(txt):numbers.append(wd)
        if not codes and not numbers:continue
        status='CODE_AND_NUMBER_EVIDENCE' if codes and numbers else ('CODE_ONLY_EVIDENCE' if codes else 'NUMBER_ONLY_EVIDENCE')
        proposals={'bbox':box,'page':page,'raster_ring_support':round(support,3),
                    'state':status,'ocr_ids':sorted(set(near)),
                    'code_candidates':sorted({_clean_token(c['text']) for c in codes}),
                    'number_candidates':sorted({_clean_token(c['text']).strip('()') for c in numbers}),
                    'review_state':'PROPOSED_UNVERIFIED'}
        proposals['id']=sid('circle',page,box,proposals['ocr_ids'])
        candidates.append(proposals)
        if len(candidates)>max_proposals:raise ValueError('OCR-anchored bubble count exceeded')
    # Hough can return near-duplicate circles. Retain best score; no averaging
    # distinct instrument observations that touch or overlap.
    kept=[]
    for c in sorted(candidates,key=lambda a:(-a['raster_ring_support'],a['id'])):
        if any(math.hypot(_center(c['bbox'])[0]-_center(k['bbox'])[0],
                          _center(c['bbox'])[1]-_center(k['bbox'])[1]) < .5*min(
                c['bbox']['x1']-c['bbox']['x0'],k['bbox']['x1']-k['bbox']['x0']) for k in kept):
            continue
        kept.append(c)
    return sorted(kept,key=lambda b:(b['page'],b['bbox']['y0'],b['bbox']['x0'],b['id']))


def scan_pdf_bubbles(pdf_bytes:bytes,words:list[dict],regions:list[dict],*,dpi:int=160,page:int=1)->list[dict]:
    import pypdfium2
    import pdfplumber
    import numpy as np
    if not pdf_bytes.startswith(b'%PDF-') or len(pdf_bytes)>16*1024*1024:raise ValueError('Invalid source PDF')
    if type(dpi) is not int or not 100<=dpi<=250:raise ValueError('Unsupported bubble raster resolution')
    with pdfplumber.open(BytesIO(pdf_bytes)) as doc:
        if not 1<=page<=len(doc.pages):raise ValueError('Invalid page')
        frame=frame_from_pdfplumber(doc.pages[page-1])
    pdf=pypdfium2.PdfDocument(pdf_bytes)
    try:
        pg=pdf[page-1];width,height=pg.get_size()
        if abs(frame.crop_width-width)>.5 or abs(frame.crop_height-height)>.5:
            raise ValueError('PDFium/PDFPlumber frame mismatch')
        scale=dpi/72
        if math.ceil(width*scale)*math.ceil(height*scale)>10_000_000:
            scale*=math.sqrt(10_000_000/(math.ceil(width*scale)*math.ceil(height*scale)))*.95
        img=pg.render(scale=scale).to_pil().convert('L')
        a=np.array(img,dtype=np.uint8)
        # Scan geometry is in PDFium's visible CropBox. Convert OCR source
        # evidence to render coords, and candidates back to source coords.
        render_words=[]
        for wd in words:
            if wd['page']!=page:continue
            clipped=frame.media_bbox_to_render_clipped(wd['bbox'])
            if clipped is not None:render_words.append({**wd,'bbox':clipped})
        render_regions=[]
        for reg in regions:
            if reg['page']!=page:continue
            clipped=frame.media_bbox_to_render_clipped(reg['bbox'])
            if clipped is not None:render_regions.append({**reg,'bbox':clipped})
        found=circle_candidates_from_image(a,render_words,profile_regions=render_regions,page=page)
        for row in found:row['bbox']=frame.bbox_to_media(row['bbox'])
        return found
    finally:pdf.close()
