"""WP-01..03: offline, evidence-first OCR recovery, detector hygiene and matching.

All output is PROPOSED_UNVERIFIED and source-hashed. Not a Worksheet R1 payload.
This module can consume a Windows S418 evidence export even when its producer
is newer than the bundled Rev W code. No model downloads, network or training.
"""
from __future__ import annotations

from collections import defaultdict
import csv
from dataclasses import dataclass
from hashlib import sha256
from io import StringIO
import json
import math
from pathlib import Path
import re
from typing import Iterable

SCHEMA = 'pid-reader-wp123-recovery-v1'
ALGORITHM = 'wp123-evidence-recovery-0.1'
MAX_WORDS = 50000
MAX_DETECTIONS = 15000
MAX_TAGS = 5000
MAX_BOX_AREA = .075
# Explicit, conservative starter vocabulary, NOT a complete ISA/ISO library.
EQUIPMENT_CODES = {'V','P','K','C','E','T','TK','D','Q','FE'}
INSTRUMENT_CODES = {'FE','FI','FIC','FIT','FT','FQ','FQI','FY','FV','FCV','FSL','FSH',
 'PI','PIT','PIC','PT','PSV','PSH','PSL','PDI','PDT','PDC','LT','LIC','LI','LG','LSH',
 'LSL','LV','LCV','LIT','TT','TIC','TI','TE','TV','TSH','TSL','XV','HV','MOV','ESDV',
 'SDV','BDV','ZSO','ZSC','ESD','PG','TG'}
TAG_CODES = EQUIPMENT_CODES | INSTRUMENT_CODES
TAG_PATTERN = re.compile(r'^([A-Z]{1,5})[-_](\d{3,7}[A-Z]?)$',re.ASCII)
LINE_PATTERN = re.compile(r'^([A-Z]{2,5})-(\d{4,7})-(\d{1,4}(?:\.\d{1,2})?)-([A-Z][A-Z0-9]{1,4})-([A-Z0-9]{2,5})$',re.ASCII)
SHORT_INSTRUMENT = re.compile(r'^[A-Z]{2,4}$',re.ASCII)
LOOP_NUMBER = re.compile(r'^\(?\d{4,7}[A-Z]?\)?$',re.ASCII)
DRAWING_TERMS = ('PIPING','INSTRUMENTATION','DRAWING','REVISIONS','REVISION','ENGINEERING','SCALE','EQUINOX')


def canon(obj: object) -> str:
    return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)


def digest(obj: object) -> str:
    return sha256(canon(obj).encode('utf-8')).hexdigest()


def sid(label: str, *parts: object) -> str:
    return label+'-'+digest(list(parts))[:24]


def _box(d: dict) -> dict:
    b={k:round(float(d[k]),7) for k in ('x0','y0','x1','y1')}
    if not all(math.isfinite(x) for x in b.values()) or not (0 <= b['x0'] < b['x1'] <= 1 and 0 <= b['y0'] < b['y1'] <= 1):
        raise ValueError('Invalid normalized source bbox')
    return b


def _center(b):
    return ((b['x0']+b['x1'])/2,(b['y0']+b['y1'])/2)


def _overlap_area(a,b):
    return max(0,min(a['x1'],b['x1'])-max(a['x0'],b['x0']))*max(0,min(a['y1'],b['y1'])-max(a['y0'],b['y0']))


def _area(b):
    return (b['x1']-b['x0'])*(b['y1']-b['y0'])


def _iou(a,b):
    intr=_overlap_area(a,b)
    return intr/max(1e-10,_area(a)+_area(b)-intr)


def _clean_token(s: str) -> str:
    # Unify typography only. Never silently swap OCR confusables (0/O, 5/S).
    t=s.strip().upper().replace('\u2013','-').replace('\u2014','-').replace('_','-').replace(' ','').replace('\u2212','-')
    return t.strip('"\'[]{}.,;:')


def read_ocr_csv(path: str | Path, *, page: int = 1) -> list[dict]:
    """Read a standalone OCR evidence CSV (not a Worksheet-host extraction)."""
    if type(page) is not int or page < 1:
        raise ValueError('Invalid page')
    p=Path(path)
    if p.stat().st_size > 8*1024*1024:
        raise ValueError('OCR CSV exceeds evidence input budget')
    words=[]
    with p.open('r',encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        required={'text','x0','y0','x1','y1'}
        if not required <= set(reader.fieldnames or []):
            raise ValueError('Missing OCR evidence CSV fields')
        for n,r in enumerate(reader):
            if n>=MAX_WORDS:
                raise ValueError('OCR word count exceeds budget')
            text=str(r.get('text','')).strip()
            if not text or len(text)>200:
                continue
            b=_box(r)
            score=float(r.get('score',r.get('raw_ocr_score',0)) or 0)
            if not math.isfinite(score) or not (0<=score<=1):
                raise ValueError('OCR score is invalid')
            words.append({'id':str(r.get('ocr_id') or sid('ocr',page,b,text)),
                          'text':text,'bbox':b,'raw_score':round(score,4),
                          'page':page,'review_state':'PROPOSED_UNVERIFIED'})
    if len({w['id'] for w in words})!=len(words):
        raise ValueError('Duplicated OCR evidence ID')
    return sorted(words,key=lambda w:(w['page'],w['bbox']['y0'],w['bbox']['x0'],w['id']))


def read_detectors(path: str | Path, *, expected_source_sha256: str | None=None, page_frame=None) -> list[dict]:
    p=Path(path)
    if p.stat().st_size>12*1024*1024:raise ValueError('Detection JSON exceeds budget')
    payload=json.loads(p.read_text(encoding='utf-8'))
    if expected_source_sha256 is not None and isinstance(payload,dict):
        declared=payload.get('source_sha256')
        if declared is not None and declared!=expected_source_sha256:
            raise ValueError('Detector source PDF hash differs from supplied PDF')
    detections=payload.get('detections',payload) if isinstance(payload,dict) else payload
    if not isinstance(detections,list) or len(detections)>MAX_DETECTIONS:
        raise ValueError('Invalid detector list or count')
    return normalise_detections(detections,page_frame=page_frame,
                                render_frame=isinstance(payload,dict) and payload.get('schema')=='pid-tr1-detections/1')


def normalise_detections(detections: list, *, page_frame=None, render_frame: bool=False) -> list[dict]:
    """Validate detector rows and put their boxes in the MediaBox-normalised frame used by WP123.

    TR1 detector records are normalised to the *rendered* (CropBox, rotated) page. When such a record is read together with the page's
    ``PageFrame`` (``render_frame=True``) every box is mapped to the media frame; on an uncropped, unrotated page this is the identity.
    Without a frame the boxes are taken as already media-normalised (the Rev X behaviour)."""
    out=[]
    for d in detections:
        if not isinstance(d,dict):raise ValueError('Malformed detector row')
        raw_box=d['bbox']
        if render_frame and page_frame is not None:raw_box=page_frame.bbox_to_media(_box(raw_box))
        b=_box(raw_box);score=float(d.get('raw_score',0) or 0)
        if not math.isfinite(score) or not 0<=score<=1:raise ValueError('Invalid detection score')
        if type(d.get('page',1)) is not int:raise ValueError('Invalid detector page')
        out.append({'id':str(d.get('id') or sid('det',b,score)), 'bbox':b,'page':d.get('page',1),
                    'coarse_class':str(d.get('coarse_class') or d.get('catalogue_class') or 'general').lower(),
                    'raw_score':round(score,4),'model_confidence_status':str(d.get('confidence_status','UNKNOWN')),
                    'review_state':'PROPOSED_UNVERIFIED'})
    if len({d['id'] for d in out})!=len(out):raise ValueError('Duplicated detector ID')
    return sorted(out,key=lambda d:(d['page'],-d['raw_score'],d['id']))


def infer_regions(words: list[dict], *, profile: str = 'auto') -> list[dict]:
    """Conservative layout routing: preserve metadata, mask only supported regions.

    In AUTO, reserve bottom band only if document/title terms are present in
    that band. The S418 profile adds explicit scan-specific known frame margins;
    it is opt-in and must NOT be applied universally to other drawings.
    Regions are inferred per page present in ``words`` (page 1 when there are no words),
    so a result for page N never borrows another page's layout.
    """
    if profile not in ('auto','none','s418'):
        raise ValueError('Unsupported region profile')
    regions=[]
    if profile=='none':return regions
    for page in (sorted({w['page'] for w in words}) or [1]):
        pw=[w for w in words if w['page']==page]
        has_title=sum(any(term in _clean_token(w['text']) for term in DRAWING_TERMS)
                      for w in pw if w['bbox']['y0']>=.81)
        if has_title>=2 or profile=='s418':
            regions.append({'type':'DOCUMENT_METADATA_REGION','page':page,'bbox':_box({'x0':0,'y0':.822,'x1':1,'y1':1}),
                            'reason':'BOTTOM_TITLE_INDICATORS' if has_title>=2 else 'EXPLICIT_S418_PROFILE'})
        if profile=='s418':
            regions.extend([
             {'type':'DRAWING_FRAME','page':page,'bbox':_box({'x0':0,'y0':0,'x1':.055,'y1':.822}), 'reason':'EXPLICIT_S418_PROFILE'},
             {'type':'DRAWING_FRAME','page':page,'bbox':_box({'x0':.945,'y0':0,'x1':1,'y1':.822}), 'reason':'EXPLICIT_S418_PROFILE'}])
    return regions


def _region_hit(box,regions,page=1) -> str | None:
    for region in regions:
        if region['page']==page and _overlap_area(box,region['bbox'])>=.40*_area(box):
            return region['type']
    return None


def _candidate(parts: list[dict], kind: str, name: str, *, details: dict | None = None) -> dict:
    boxes=[p['bbox'] for p in parts]
    b={k:(min(v[k] for v in boxes) if k in ('x0','y0') else max(v[k] for v in boxes)) for k in ('x0','y0','x1','y1')}
    evidence=sorted({p['id'] for p in parts})
    score=round(min(p['raw_score'] for p in parts),4)
    return {'id':sid('reading',kind,name,parts[0]['page'],evidence), 'kind':kind,'text_candidate':name,
            'page':parts[0]['page'],'bbox':b,'raw_ocr_score':score,'ocr_ids':evidence,
            'components':details or {},'review_state':'PROPOSED_UNVERIFIED','association_state':'UNLINKED'}


def _parse_text(value: str) -> tuple[str,str,dict] | None:
    cleaned=_clean_token(value)
    # Line grammar takes precedence over equipment/instrument code and excludes
    # service/spec/valve-figure fragments from tag interpretation.
    n=LINE_PATTERN.fullmatch(cleaned)
    if n:
        service,seq,size,spec,schedule=n.groups()
        return 'PIPE_LINE_NUMBER',cleaned,dict(service=service,sequence=seq,nominal_size_observed=size,spec=spec,schedule=schedule)
    m=TAG_PATTERN.fullmatch(cleaned)
    if not m:return None
    prefix,number=m.groups()
    if prefix not in TAG_CODES:return None
    kind=('PACKAGE_REFERENCE' if prefix=='Q' else
          'INSTRUMENT_TAG' if prefix in INSTRUMENT_CODES else 'EQUIPMENT_TAG')
    return kind,cleaned,{'prefix':prefix,'number':number}


def line_number_fragment_proposals(words:list[dict], regions:list[dict], readings:list[dict]) -> list[dict]:
    """Preserve near-miss piping strings without inventing line attributes.

    A fragment never passes the complete line-number grammar and is never an
    accepted line. It is queued for visual review and optional regional OCR.
    """
    found=[]
    complete=[r for r in readings if r['kind']=='PIPE_LINE_NUMBER']
    for w in words:
        text=_clean_token(w['text'])
        if _region_hit(w['bbox'],regions,w['page']):continue
        if _parse_text(text) is not None:continue
        if not 13<=len(text)<=70:continue
        dash_count=text.count('-')
        if dash_count<2 or not re.search(r'\d{4,7}',text):continue
        # Require both a digit-rich sequence and a probable CAD specification
        # suffix. Unknown spelling remains unknown; no O/0 or S/5 guessing.
        if not (re.search(r'\d+[.]\d+',text) or re.search(r'[AC][135][SS5]',text)):
            continue
        if any(r['page']==w['page'] and _overlap_area(w['bbox'],r['bbox'])>=.7*_area(w['bbox']) for r in complete):
            continue
        found.append({'id':sid('linefrag',w['id'],text),'text_observed':w['text'],
                      'page':w['page'],'bbox':w['bbox'],'ocr_ids':[w['id']],
                      'reason':'LINE_STYLE_STRING_FAILS_COMPLETE_GRAMMAR',
                      'review_state':'PROPOSED_UNVERIFIED'})
    return sorted(found,key=lambda r:(r['page'],r['bbox']['y0'],r['bbox']['x0'],r['id']))


def recover_readings(words: list[dict],regions: list[dict]) -> tuple[list[dict],list[dict]]:
    readings=[]; rejected=[]
    pages=defaultdict(list)
    for w in words:
        pages[w['page']].append(w)
        parsed=_parse_text(w['text'])
        if parsed:
            if _region_hit(w['bbox'],regions,w['page']):
                rejected.append({'ocr_id':w['id'],'reason':'DOCUMENT_REGION','text':w['text']})
            else:
                readings.append(_candidate([w],*parsed[:2],details=parsed[2]))
    # Only join a SHORTCODE-/number pair, not general text or arbitrary nearby
    # strings. This prevents 'SPECTRAENERGYMIDSTRE' inventions.
    for page, ww in pages.items():
        if len(ww)>MAX_WORDS:raise ValueError('Page evidence too large')
        for a in ww:
            at=_clean_token(a['text'])
            if not re.fullmatch(r'[A-Z]{1,5}-?',at) or at.rstrip('-') not in TAG_CODES:
                continue
            ab=a['bbox'];ay=_center(ab)[1];ah=ab['y1']-ab['y0']
            for b in ww:
                if a is b:continue
                bt=_clean_token(b['text'])
                if not re.fullmatch(r'-?\d{3,7}[A-Z]?',bt):continue
                bb=b['bbox'];bh=bb['y1']-bb['y0']
                same_line=abs(ay-_center(bb)[1])<=.5*max(ah,bh)
                gap=bb['x0']-ab['x1']
                if not same_line or not -.001<=gap<=min(.008,1.1*max(ah,bh)):
                    continue
                if _region_hit(ab,regions,page) or _region_hit(bb,regions,page):continue
                reconstructed=at.rstrip('-')+'-'+bt.lstrip('-')
                parsed=_parse_text(reconstructed)
                if parsed:
                    r=_candidate([a,b],parsed[0],parsed[1],details={**parsed[2],'joined_ocr':True})
                    readings.append(r)
    # Distinct OCR observations preserve duplicate occurrences in different
    # locations, but identical reconstructed candidates collapse deterministically.
    # Remove OCR substrings contained inside a longer independently observed
    # pipe-line number. Example: P-00019 cropped out of PF-00019-14.3-A3S-40.
    lines=[r for r in readings if r['kind']=='PIPE_LINE_NUMBER']
    safe=[]
    for r in readings:
        if r['kind'] in ('INSTRUMENT_TAG','EQUIPMENT_TAG') and any(
                line['page']==r['page'] and line['ocr_ids']!=r['ocr_ids'] and
                _overlap_area(r['bbox'],line['bbox']) >= .77*_area(r['bbox'])
                for line in lines):
            rejected.append({'ocr_id':';'.join(r['ocr_ids']),
                             'reason':'OCR_SUBSTRING_OF_PIPE_LINE','text':r['text_candidate']})
        else:
            safe.append(r)
    unique={r['id']:r for r in safe}
    cleaned=[]
    # Spatial de-duplication of PSM6/PSM11 observations in the same ROI. Other
    # occurrences of FE-2206 in different drawing areas stay separate.
    for r in sorted(unique.values(),key=lambda o:(-o['raw_ocr_score'],o['id'])):
        dup=next((o for o in cleaned if r['kind']==o['kind'] and r['text_candidate']==o['text_candidate']
                  and r['page']==o['page'] and _iou(r['bbox'],o['bbox'])>.72),None)
        if dup is not None:
            dup['ocr_ids']=sorted(set(dup['ocr_ids']+r['ocr_ids']))
            dup['id']=sid('reading',dup['kind'],dup['text_candidate'],dup['page'],dup['ocr_ids'])
        else:
            cleaned.append(r)
    if len(cleaned)>MAX_TAGS:raise ValueError('Reading proposal budget exceeded')
    return sorted(cleaned,key=lambda r:(r['page'],r['bbox']['y0'],r['bbox']['x0'],r['id'])),rejected


def clean_detector_proposals(detections: list[dict],regions: list[dict]) -> list[dict]:
    out=[];retained=[]
    for d in detections:
        item=dict(d)
        reason=_region_hit(d['bbox'],regions,d['page'])
        if reason:
            item['filter_reason']=reason
        elif _area(d['bbox'])>MAX_BOX_AREA:
            item['filter_reason']='OVERSIZED_BOX'
        elif d['raw_score']<.65:
            item['filter_reason']='BELOW_UNCALIBRATED_DETECTOR_GATE'
        elif d['coarse_class'] not in ('valve','instrumentation'):
            item['filter_reason']='UNVERIFIED_GENERAL_CLASS'
        elif any(other['coarse_class']==d['coarse_class'] and other['page']==d['page'] and _iou(other['bbox'],d['bbox'])>=.65 for other in retained):
            item['filter_reason']='DUPLICATE_DETECTION'
        else:
            item['filter_reason']=None
            retained.append(item)
        item['eligibility']='REVIEWABLE_CLASS_CANDIDATE' if item['filter_reason'] is None else 'WITHHELD_NOT_DELETED'
        out.append(item)
    return out


def _separation(a: dict,b:dict):
    """Normalized Euclidean gap between rectangles (zero when overlapping)."""
    dx=max(0,b['x0']-a['x1'],a['x0']-b['x1'])
    dy=max(0,b['y0']-a['y1'],a['y0']-b['y1'])
    return math.hypot(dx,dy)


def title_block_proposals(words: list[dict],regions: list[dict]) -> list[dict]:
    """Document metadata hypotheses, never treated as equipment tags.

    Geography is used only as supporting evidence and ambiguous fields remain
    alternatives. This is intentionally not an automatic drawing register edit.
    """
    if not any(r['type']=='DOCUMENT_METADATA_REGION' for r in regions):return []
    out=[]
    from datetime import datetime
    for w in words:
        b=w['bbox'];t=_clean_token(w['text'])
        field=None; normalized=None
        if b['y0']>.82:
            if re.fullmatch(r'\d{4}/\d{2}/\d{2}',t):
                try:datetime.strptime(t,'%Y/%m/%d')
                except ValueError:continue
                field='DATE_CANDIDATE';normalized=t
            elif re.fullmatch(r'\d{3}',t) and b['x0']>.75 and b['y0']>.91:
                field='DRAWING_NUMBER_CANDIDATE';normalized=t
            elif t in ('NTS','N.T.S'):
                field='SCALE_CANDIDATE';normalized=t
            elif t.startswith('LSD') and len(t)>=12:
                field='LOCATION_REFERENCE_CANDIDATE';normalized=t
        if b['y0']<.055 and b['x0']>.7 and re.fullmatch(r'\d{3}',t):
            field='SHEET_MARK_CANDIDATE';normalized=t
        if field:
            out.append({'id':sid('docfield',field,w['id']),'field':field,'value_candidate':normalized,
                        'page':w['page'],'bbox':b,'ocr_ids':[w['id']],
                        'review_state':'PROPOSED_UNVERIFIED'})
    return sorted(out,key=lambda r:(r['field'],r['page'],r['id']))


def associate_readings(readings: list[dict], detections: list[dict]) -> list[dict]:
    """Mutual nearest, margin-checked association with abstention and no reuse.

    Weak general detector boxes and line/package tags never become instrument
    associations. Connections are NOT inferred from visual proximity.
    """
    options=[]
    for r in readings:
        if r['kind'] not in ('INSTRUMENT_TAG','EQUIPMENT_TAG'):continue
        per=[]
        for d in detections:
            if d['eligibility']!='REVIEWABLE_CLASS_CANDIDATE' or d['page']!=r['page']:continue
            if d['coarse_class']=='instrumentation' and r['kind']!='INSTRUMENT_TAG':continue
            if d['coarse_class']=='valve' and r['components']['prefix'] not in ('FV','FCV','LV','LCV','XV','HV','MOV','ESDV','SDV','BDV','PSV'):
                continue
            gap=_separation(r['bbox'],d['bbox'])
            if gap>.025:continue
            # Containment and intersecting borders can indicate OCR within a
            # symbol, but OCR text *outside* is not forced to attach.
            score=round(gap + .004*(1-d['raw_score']),6)
            per.append((score,d['id']))
        per.sort()
        options.append({'tag_id':r['id'],'options':[{'detector_id':id_,'distance_cost':cost} for cost,id_ in per[:5]]})
    by_tag={a['tag_id']:a for a in options}
    claims=defaultdict(list)
    for a in options:
        if a['options']:
            claims[a['options'][0]['detector_id']].append(a)
    proposals=[]
    for a in options:
        top=a['options'][0] if a['options'] else None
        margin=(a['options'][1]['distance_cost']-top['distance_cost']) if top and len(a['options'])>1 else None
        reason=('NO_ELIGIBLE_NEARBY_SYMBOL' if not top else
                'MULTIPLE_TAGS_COMPETE_FOR_SYMBOL' if len(claims[top['detector_id']])>1 else
                'SYMBOL_AMBIGUITY' if margin is not None and margin<.005 else
                'PROPOSED_UNVERIFIED')
        proposals.append({'tag_id':a['tag_id'],'detector_id':top['detector_id'] if top and reason=='PROPOSED_UNVERIFIED' else None,
                          'candidate_detector_id':top['detector_id'] if top else None,
                          'association_state':reason,'options':a['options'],
                          'review_state':'PROPOSED_UNVERIFIED'})
    return sorted(proposals,key=lambda p:p['tag_id'])


def link_bubble_text(bubbles:list[dict]) -> list[dict]:
    """Attach visible OCR code/number clues to each raster circle.

    No assembled loop number is treated as an accepted instrument tag. These
    are deliberately separate from the verified engineering register.
    """
    out=[]
    for bubble in bubbles:
        code=list(bubble.get('code_candidates',[]))
        numbers=list(bubble.get('number_candidates',[]))
        if not code:continue
        combined=[f'{c}-{n}' for c in code for n in numbers] if code and numbers else []
        row={'id':sid('bubble-text',bubble['id'],code,numbers),
             'bubble_id':bubble['id'],'code_options':code,
             'number_options':numbers,'joined_tag_options':combined,
             'association_state':'OCR_CLUES_WITH_CIRCLE_GEOMETRY',
             'review_state':'PROPOSED_UNVERIFIED',
             'notice':'Circle and OCR proximity only; not a validated instrument identifier.'}
        out.append(row)
    return sorted(out,key=lambda x:x['id'])


def recover_wp123(source_pdf_bytes: bytes, words: list[dict], detections: list[dict], *, profile='auto', bubbles: list[dict] | None=None) -> dict:
    if not isinstance(source_pdf_bytes,bytes) or not source_pdf_bytes.startswith(b'%PDF-') or len(source_pdf_bytes)>16*1024*1024:
        raise ValueError('Expected valid bounded PDF source bytes')
    if len(words)>MAX_WORDS or len(detections)>MAX_DETECTIONS:
        raise ValueError('Evidence collection budget exceeded')
    source=sha256(source_pdf_bytes).hexdigest()
    regions=infer_regions(words,profile=profile)
    bubbles=list(bubbles or [])
    if len(bubbles)>500:raise ValueError('Bubble candidate budget exceeded')
    for b in bubbles:
        if b.get('review_state')!='PROPOSED_UNVERIFIED' or b.get('state') not in ('CODE_ONLY_EVIDENCE','CODE_AND_NUMBER_EVIDENCE','NUMBER_ONLY_EVIDENCE'):
            raise ValueError('Invalid bubble evidence state')
        _box(b['bbox'])
    readings,rejected=recover_readings(words,regions)
    det=clean_detector_proposals(detections,regions)
    links=associate_readings(readings,det)
    bubble_links=link_bubble_text(bubbles)
    document_fields=title_block_proposals(words,regions)
    line_fragments=line_number_fragment_proposals(words,regions,readings)
    res={'schema':SCHEMA,'algorithm':ALGORITHM,'source_sha256':source,'inputs':{
        'ocr_evidence_sha256':digest(words),'detection_evidence_sha256':digest(detections),
        'bubble_evidence_sha256':digest(bubbles),'region_profile':profile},
        'page_regions':regions,'readings':readings,'bubble_candidates':bubbles,
        'document_fields':document_fields,'bubble_text_links':bubble_links,'line_number_fragments':line_fragments,'withheld_ocr':rejected,'detector_decisions':det,
        'associations':links,'summary':{
           'ocr_observations':len(words),'readings_proposed':len(readings),
           'document_fields_proposed':len(document_fields),
           'tags_proposed':sum(r['kind'] in ('INSTRUMENT_TAG','EQUIPMENT_TAG','PACKAGE_REFERENCE') for r in readings),
           'line_numbers_proposed':sum(r['kind']=='PIPE_LINE_NUMBER' for r in readings),
           'line_number_fragments':len(line_fragments),
           'raster_bubble_candidates':len(bubbles),
           'raster_bubbles_with_code_and_number':sum(b['state']=='CODE_AND_NUMBER_EVIDENCE' for b in bubbles),
           'instrument_bubble_ocr_links':len(bubble_links),
           'detectors_total':len(det),'detectors_reviewable':sum(d['eligibility']=='REVIEWABLE_CLASS_CANDIDATE' for d in det),
           'associations_proposed':sum(a['association_state']=='PROPOSED_UNVERIFIED' for a in links),
           'reviewed_engineering_objects':0},
        'notice':'All records are unverified source-linked proposals. No plant, pipe, tag or connection is accepted.'}
    res['result_sha256']=digest(res)
    return res


def validate_wp123(result: dict, source_bytes:bytes, words:list[dict], detections:list[dict], bubbles:list[dict]|None=None) -> list[str]:
    if not isinstance(result,dict):return ['Result must be JSON object']
    if result.get('schema')!=SCHEMA:return ['Schema not supported']
    if result.get('inputs',{}).get('region_profile') not in ('auto','none','s418'):return ['Region profile invalid']
    try:
        expected=recover_wp123(source_bytes,words,detections,profile=result['inputs']['region_profile'],bubbles=bubbles)
    except (ValueError,KeyError,TypeError) as e:
        return ['Invalid supplied evidence: '+str(e)]
    return [] if result==expected else ['Result not reproducible from source-linked evidence']


def save_wp123(result: dict, folder: str | Path) -> dict:
    """Export deterministic, spreadsheet-safe sidecars; no host DB edits."""
    dst=Path(folder);dst.mkdir(parents=True,exist_ok=True)
    (dst/'wp123_result.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    def safe(s):
        text=str(s)
        return "'"+text if text.startswith(('=','+','-','@','\t','\r')) else text
    def csvfile(name,headers,rows):
        with (dst/name).open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=headers);w.writeheader()
            for row in rows:w.writerow({h:safe(row.get(h,'')) for h in headers})
    csvfile('proposed_engineering_register.csv',
            ['id','kind','text_candidate','page','x0','y0','x1','y1','ocr_ids','review_state'],
            [{'id':r['id'],'kind':r['kind'],'text_candidate':r['text_candidate'],'page':r['page'],
              **r['bbox'],'ocr_ids':';'.join(r['ocr_ids']),'review_state':r['review_state']} for r in result['readings']])
    csvfile('partial_line_number_queue.csv',['id','text_observed','page','reason','review_state'],result['line_number_fragments'])
    csvfile('document_metadata_proposals.csv',['id','field','value_candidate','page','review_state'],result['document_fields'])
    csvfile('detector_triage.csv',['id','coarse_class','raw_score','page','filter_reason','eligibility'],result['detector_decisions'])
    csvfile('instrument_bubble_proposals.csv',['id','page','state','raster_ring_support','ocr_ids','review_state'],
            [{**b,'ocr_ids':';'.join(b['ocr_ids'])} for b in result['bubble_candidates']])
    csvfile('instrument_bubble_text_links.csv',['id','bubble_id','code_options','number_options','joined_tag_options','review_state'],
            [{**b,'code_options':';'.join(b['code_options']),
              'number_options':';'.join(b['number_options']),
              'joined_tag_options':';'.join(b['joined_tag_options'])} for b in result['bubble_text_links']])
    csvfile('tag_symbol_associations.csv',['tag_id','detector_id','candidate_detector_id','association_state'],result['associations'])
    (dst/'counts.json').write_text(json.dumps(result['summary'],indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return {'folder':str(dst),'result_sha256':result['result_sha256']}
