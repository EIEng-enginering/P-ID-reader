"""Offline, review-only raster stroke context and *possible* contact graph.

Pixel strokes are often typography, title borders, duplicate Hough detections,
equipment outlines or pipes. Nothing here is an accepted pipe or process edge.
No writes to the frozen Worksheet R1 module/worker contract.

All contact operations are in PDFium rendered pixels, mapped from the existing
normalised PDFplumber MediaBox frame. This matters for cropped and rotated PDFs.
"""
from __future__ import annotations

from collections import defaultdict
from math import hypot, isfinite
from typing import Any

from ..api import LimitExceeded, canonical_json, sha256_hex, stable_id
from ..formats.page_coordinates import PageFrame
from .raster_geometry import validate_raster_result

SCHEMA = 'pid-reader-standalone-raster-network-v1'
ALGORITHM = 'raster-context-spatial-contacts-0.1'
MAX_OBSERVATIONS = 7000
MAX_CONTACTS = 6000
MAX_PAIR_CHECKS = 85000
MAX_GRID_INSERTS = 150000
MAX_TEXT_BOXES = 12000
MAX_REGION_GRID_INSERTS = 120000
GRID = 96.0
CONTACT_TOL = 4.0


def _frame(row: dict) -> PageFrame:
    transform = row['transform']
    return PageFrame(float(transform['media_size'][0]),float(transform['media_size'][1]),
                     float(transform['crop_origin'][0]),float(transform['crop_origin'][1]),
                     float(transform['render_size'][0]),float(transform['render_size'][1]),
                     int(transform['rotation']))


def _pixel(frame: PageFrame, page: dict, point: list[float]) -> tuple[float, float]:
    x,y = frame.media_to_render(point[0],point[1])
    return (x * page['width_px'],y * page['height_px'])


def _source(frame: PageFrame, page: dict, point: tuple[float,float]) -> list[float]:
    x=max(0.,min(1.,point[0]/page['width_px']))
    y=max(0.,min(1.,point[1]/page['height_px']))
    return [round(c,7) for c in frame.render_to_media(x,y)]


def _expanded_box(a,b,pad=CONTACT_TOL):
    return (min(a[0],b[0])-pad,min(a[1],b[1])-pad,
            max(a[0],b[0])+pad,max(a[1],b[1])+pad)


def _bucket_keys(rect):
    x0,y0,x1,y1=rect
    for gx in range(int(x0//GRID),int(x1//GRID)+1):
        for gy in range(int(y0//GRID),int(y1//GRID)+1):
            yield gx,gy


def _index_regions(boxes):
    """Bounded tile lookup for OCR/symbol boxes, avoiding strokes x words."""
    grid=defaultdict(list);inserts=0
    for box in boxes:
        for key in _bucket_keys((box[0]-2,box[1]-2,box[2]+2,box[3]+2)):
            inserts+=1
            if inserts>MAX_REGION_GRID_INSERTS:
                raise LimitExceeded('PID_LIMIT_RASTER','OCR/symbol region spatial-index budget exceeded')
            grid[key].append(box)
    return grid


def _sample_coverage(a,b,boxes):
    # Seven samples are an intentionally weak contextual clue, never proof of
    # handwriting or piping. A long line crossing one tag remains uncertain.
    inside=0
    for i in range(9):
        t=i/8
        x=a[0]+t*(b[0]-a[0]);y=a[1]+t*(b[1]-a[1])
        if any(x0-2<=x<=x1+2 and y0-2<=y<=y1+2
               for x0,y0,x1,y1 in boxes.get((int(x//GRID),int(y//GRID)),())):
            inside+=1
    return inside/9


def _projection(p,a,b):
    dx=b[0]-a[0];dy=b[1]-a[1];length2=dx*dx+dy*dy
    if length2<1e-12:return (0.,hypot(p[0]-a[0],p[1]-a[1]))
    t=((p[0]-a[0])*dx+(p[1]-a[1])*dy)/length2
    px=a[0]+max(0.,min(1.,t))*dx;py=a[1]+max(0.,min(1.,t))*dy
    return t,hypot(p[0]-px,p[1]-py)


def _contact(a,b,c,d):
    len1=hypot(b[0]-a[0],b[1]-a[1]);len2=hypot(d[0]-c[0],d[1]-c[1])
    if min(len1,len2)<12:return None
    v=(b[0]-a[0],b[1]-a[1]);w=(d[0]-c[0],d[1]-c[1])
    cross=v[0]*w[1]-v[1]*w[0]
    sine=abs(cross)/(len1*len2)
    if sine < .06:
        # Two Hough observations of the same thick ink are not two pipes.
        _,sep1=_projection(c,a,b);_,sep2=_projection(d,a,b)
        if max(sep1,sep2) <= 2.8:
            t0,_=_projection(c,a,b);t1,_=_projection(d,a,b)
            overlap=max(0.,min(1.,max(t0,t1))-max(0.,min(t0,t1)))
            if overlap*len1 >= .78*min(len1,len2):
                return 'DUPLICATE_OVERLAP', ((a[0]+b[0]+c[0]+d[0])/4,(a[1]+b[1]+c[1]+d[1])/4)
    # Endpoint pairs first. The two line drawings can represent coincident
    # pipes, overlapping annotation strokes or just touching ink.
    nearest=min(((hypot(p[0]-q[0],p[1]-q[1]),p,q) for p in (a,b) for q in (c,d)),
                key=lambda row:row[0])
    if nearest[0] <= CONTACT_TOL:
        return 'ENDPOINT_TOUCH_UNRESOLVED', ((nearest[1][0]+nearest[2][0])/2,
                                             (nearest[1][1]+nearest[2][1])/2)
    for p in (a,b):
        t,dist=_projection(p,c,d)
        if .08<t<.92 and dist<=3:
            return 'T_JUNCTION_UNRESOLVED',p
    for p in (c,d):
        t,dist=_projection(p,a,b)
        if .08<t<.92 and dist<=3:
            return 'T_JUNCTION_UNRESOLVED',p
    # Proper crossing: not a connection unless confirmed from the drawing.
    if sine>=.28:
        dx=c[0]-a[0];dy=c[1]-a[1]
        ta=(dx*w[1]-dy*w[0])/cross
        tb=(dx*v[1]-dy*v[0])/cross
        if .06<ta<.94 and .06<tb<.94:
            return 'CROSSING_UNRESOLVED',(a[0]+ta*v[0],a[1]+ta*v[1])
    return None


def _check_ocr(raster:dict,ocr:dict|None):
    if ocr is None:return
    from ..formats.ocr_source import verify_ocr_preview
    if not verify_ocr_preview(ocr):
        raise ValueError('Invalid OCR result evidence')
    if ocr['source_sha256'] != raster['source_sha256']:
        raise ValueError('Raster/OCR source hashes differ')
    if ocr.get('coordinate_frame')!='PDFPLUMBER_MEDIA_NORMALIZED_V1':
        raise ValueError('OCR lacks a source-coordinate frame')
    frames={r['page']:r['transform'] for r in raster['page_frames']}
    for p in ocr['pages']:
        if p['page'] in frames and p.get('render_transform')!=frames[p['page']]:
            raise ValueError('OCR/raster page transforms disagree')
    if sum(len(p['words']) for p in ocr['pages'])>MAX_TEXT_BOXES:
        raise LimitExceeded('PID_LIMIT_RASTER','Too many OCR words for raster context')


def build_raster_network(raster:dict,ocr:dict|None=None) ->dict:
    """Infer *unreviewed* per-stroke roles and bounded possible raster contacts.

    No claim is made that OCR is complete. Missing OCR is flagged explicitly.
    All input evidence is immutable, source-linked and content-hashed.
    """
    if validate_raster_result(raster):
        raise ValueError('Invalid raster source analysis')
    _check_ocr(raster,ocr)
    strokes=raster['stroke_candidates']
    if len(strokes)>MAX_OBSERVATIONS:
        raise LimitExceeded('PID_LIMIT_RASTER','Too many strokes for raster network')
    pages={r['page']:r for r in raster['page_frames']}
    positions={};groups=defaultdict(list)
    for s in strokes:
        pg=pages[s['page']];fr=_frame(pg)
        a,b=(_pixel(fr,pg,p) for p in s['endpoints'])
        if hypot(b[0]-a[0],b[1]-a[1])<1.0:
            raise ValueError('Degenerate raster stroke')
        positions[s['id']]=(a,b);groups[s['page']].append(s)
    text=defaultdict(list)
    if ocr is not None:
        for pg in ocr['pages']:
            if pg['page'] not in pages:continue
            row=pages[pg['page']];fr=_frame(row)
            for word in pg['words']:
                box=word['bbox']
                p=_pixel(fr,row,[box['x0'],box['y0']]);q=_pixel(fr,row,[box['x1'],box['y1']])
                text[pg['page']].append((min(p[0],q[0]),min(p[1],q[1]),max(p[0],q[0]),max(p[1],q[1])))
    shapes=defaultdict(list)
    for s in raster['filled_valve_candidates']+raster.get('outline_valve_candidates',[]):
        row=pages[s['page']];fr=_frame(row);box=s['bbox']
        p=_pixel(fr,row,[box['x0'],box['y0']]);q=_pixel(fr,row,[box['x1'],box['y1']])
        shapes[s['page']].append((min(p[0],q[0]),min(p[1],q[1]),max(p[0],q[0]),max(p[1],q[1])))
    text_index={pg:_index_regions(regions) for pg,regions in text.items()}
    glyph_index={pg:_index_regions(regions) for pg,regions in shapes.items()}
    result={'schema':SCHEMA,'algorithm':ALGORITHM,'source_sha256':raster['source_sha256'],
            'raster_result_sha256':raster['result_sha256'],
            'ocr_result_sha256':ocr['result_sha256'] if ocr is not None else None,
            'coordinate_frame':'PDFPLUMBER_MEDIA_NORMALIZED_V1',
            'stroke_evidence':[],'contact_candidates':[], 'duplicate_observation_groups':[], 'warnings':[],
            'disclaimer':'Contextual raster observations only; no process pipe, valve or plant connection is confirmed.'}
    if ocr is None:
        result['warnings'].append('TEXT_MASK_NOT_AVAILABLE: possible text strokes may remain')
    else:
        result['warnings'].append('OCR_WORD_BOXES_PROVISIONAL: no stroke excluded on OCR evidence alone')
    excluded=set()
    for page in sorted(groups):
        pg=pages[page]
        for s in sorted(groups[page],key=lambda item:item['id']):
            a,b=positions[s['id']]
            text_fraction=_sample_coverage(a,b,text_index.get(page,{}))
            glyph_fraction=_sample_coverage(a,b,glyph_index.get(page,{}))
            width,height=pg['width_px'],pg['height_px']
            horizontal_edge=(max(abs(a[1]-b[1]),1)<5 and min(a[1],b[1])<10 or
                             max(abs(a[1]-b[1]),1)<5 and max(a[1],b[1])>height-10)
            vertical_edge=(max(abs(a[0]-b[0]),1)<5 and min(a[0],b[0])<10 or
                           max(abs(a[0]-b[0]),1)<5 and max(a[0],b[0])>width-10)
            border=(horizontal_edge or vertical_edge) and hypot(b[0]-a[0],b[1]-a[1])>min(width,height)*.18
            if text_fraction>=.50:role='OCR_TEXT_OVERLAP_UNRESOLVED'
            elif glyph_fraction>=.30:role='SYMBOL_REGION_STROKE_CANDIDATE'
            elif border:role='PAGE_FRAME_STROKE_CANDIDATE'
            elif text_fraction>0:role='TEXT_INTERSECTING_STROKE_UNRESOLVED'
            else:role='UNCLASSIFIED_LINEWORK'
            # OCR is a fallible detector and MUST NOT remove potential contacts.
            # Only sufficiently long, edge-aligned page-border candidates are omitted.
            if role=='PAGE_FRAME_STROKE_CANDIDATE':
                excluded.add(s['id'])
            result['stroke_evidence'].append({'stroke_id':s['id'],'page':page,'role':role,
                         'text_sample_fraction':round(text_fraction,4),
                         'glyph_sample_fraction':round(glyph_fraction,4),
                         'status':'PROPOSED_UNVERIFIED'})
    # Group highly overlapping Hough observations. This reduces review noise
    # without deleting any original stroke, joining gaps or asserting a pipe.
    # Each source stroke remains available in stroke_evidence.
    parent={r['id']:r['id'] for r in strokes}
    def root(k):
        while parent[k]!=k:
            parent[k]=parent[parent[k]]
            k=parent[k]
        return k
    def union(a,b):
        x=root(a);y=root(b)
        if x!=y:parent[max(x,y)]=min(x,y)
    raw_contacts=[]
    total_pairs=0;grid_inserts=0
    for page in sorted(groups):
        pg=pages[page];fr=_frame(pg)
        grid=defaultdict(list);found=set();page_strokes=sorted(groups[page],key=lambda x:x['id'])
        for s in page_strokes:
            if s['id'] in excluded:continue
            a,b=positions[s['id']]
            keys=list(_bucket_keys(_expanded_box(a,b)))
            grid_inserts+=len(keys)
            if grid_inserts>MAX_GRID_INSERTS:
                raise LimitExceeded('PID_LIMIT_RASTER','Raster spatial-index budget exceeded')
            near=set()
            for key in keys:near.update(grid.get(key,()))
            for prev in sorted(near):
                pair=(prev,s['id'])
                if pair in found:continue
                found.add(pair)
                total_pairs+=1
                if total_pairs>MAX_PAIR_CHECKS:
                    raise LimitExceeded('PID_LIMIT_RASTER','Raster contact comparison budget exceeded')
                c,d=positions[prev]
                contact=_contact(a,b,c,d)
                if contact is None:continue
                kind,at=contact
                if kind=='DUPLICATE_OVERLAP':
                    union(*pair)
                else:
                    raw_contacts.append((page,pair,kind,_source(fr,pg,at)))
            
            for key in keys:grid[key].append(s['id'])
    aliases=defaultdict(list)
    for sid in sorted(parent):aliases[root(sid)].append(sid)
    for representative,items in sorted(aliases.items()):
        if len(items)>1:
            result['duplicate_observation_groups'].append({
                'representative_stroke_id':representative,
                'stroke_ids':items,
                'explanation':'Overlapping Hough observations of ink; not evidence of a connected pipe.'})
    # Per pair of evidence groups, retain one candidate of each kind. This
    # avoids hundreds of redundant reviews for a few thick drawing strokes.
    grouped={}
    for page,pair,kind,point in raw_contacts:
        reps=tuple(sorted((root(pair[0]),root(pair[1]))))
        if reps[0]==reps[1]:continue
        key=(page,reps,kind)
        if key not in grouped:
            grouped[key]=[point,1]
        else:
            grouped[key][1]+=1
            if point<grouped[key][0]:grouped[key][0]=point
    if len(grouped)>MAX_CONTACTS:
        raise LimitExceeded('PID_LIMIT_RASTER','Too many unresolved raster contacts; no partial result')
    for (page,reps,kind),(point,hits) in sorted(grouped.items()):
        cid=stable_id('raster-contact',raster['source_sha256'],page,list(reps),kind,point,ALGORITHM)
        result['contact_candidates'].append({'id':cid,'page':page,'stroke_ids':list(reps),
            'kind':kind,'point':point,'supporting_observation_pairs':hits,
            'status':'UNRESOLVED',
            'limitations':'Ink geometry only: not verified as a piping, electrical, signal, or physical plant connection.'})
    result['stroke_evidence'].sort(key=lambda r:(r['page'],r['stroke_id']))
    result['contact_candidates'].sort(key=lambda r:(r['page'],r['id']))
    result['statistics']={'strokes':len(strokes),'contact_proposals':len(result['contact_candidates']),
                          'pair_checks':total_pairs,'context_excluded_strokes':len(excluded),
                          'duplicate_observation_groups':len(result['duplicate_observation_groups'])}
    result['result_sha256']=sha256_hex(canonical_json(result).encode('utf-8'))
    if len(canonical_json(result).encode('utf-8'))>8*1024*1024:
        raise LimitExceeded('PID_LIMIT_RASTER','Raster network JSON exceeds 8 MiB')
    return result


def validate_raster_network(result:dict,raster:dict,ocr:dict|None=None)->list[str]:
    """Recompute the deterministic derived evidence, preventing rehashed forgery."""
    try:
        expected=build_raster_network(raster,ocr)
        return [] if canonical_json(result)==canonical_json(expected) else ['Raster network does not match source evidence']
    except (TypeError,KeyError,ValueError,IndexError,LimitExceeded) as exc:
        return [f'Invalid raster network input: {type(exc).__name__}: {exc}']
