"""WP05 conservative candidate classification and abstaining tag associations."""
from __future__ import annotations
import math
from .common import (STATE, box, center, collection, digest, evidence_rows, ident,
                     number, overlap, area, page)

VALVE_CODES = {'FV','FCV','LV','LCV','XV','HV','MOV','ESDV','SDV','BDV','PSV'}


def candidates(detector_decisions, bubbles=()):
    """Do not override WP123 withholding or pretend circles are instruments.

    Bubble geometry is a separate candidate route with a distinct eligibility
    label and no detector confidence claim. Text evidence is required.
    """
    evidence_rows(detector_decisions); evidence_rows(list(bubbles))
    out = []
    for d in detector_decisions:
        cls = d.get('coarse_class')
        eligible = (d.get('eligibility')=='REVIEWABLE_CLASS_CANDIDATE' and
                    cls in ('valve','instrumentation') and number(d['raw_score'])>=.65)
        out.append({'id':ident('symbol',d['id']), 'page':d['page'],'bbox':d['bbox'],
                    'kind':'VALVE' if cls=='valve' else 'INSTRUMENT' if cls=='instrumentation' else 'UNKNOWN',
                    'eligibility':'ASSOCIATION_CANDIDATE' if eligible else 'WITHHELD',
                    'reason':None if eligible else d.get('filter_reason') or 'UNCALIBRATED_OR_GENERAL_CLASS',
                    'evidence_ids':[d['id']], 'raw_score':d['raw_score'],'raw_coarse_class':cls,'evidence_record':dict(d),'origin':'DETECTOR', 'review_state':STATE})
    for b in bubbles:
        if b.get('ocr_ids'):
            out.append({'id':ident('symbol-bubble',b['id']), 'page':b['page'],'bbox':b['bbox'],
                        'kind':'INSTRUMENT','eligibility':'BUBBLE_GEOMETRY_CANDIDATE',
                        'reason':'TEXT_AND_RING_GEOMETRY_ONLY', 'evidence_ids':[b['id']]+b['ocr_ids'],
                        'origin':'BUBBLE_GEOMETRY','review_state':STATE})
    return out


def associations(readings, symbols, *, page_sizes, max_gap_points=24., ambiguity_points=5.):
    """Nearest compatible candidate, per-page physical distance, mutual uniqueness.

    All contenders remain listed. Duplicate/overlapping symbol hypotheses are
    treated as ambiguity, not arbitrarily collapsed into one truth.
    """
    evidence_rows(readings); evidence_rows(symbols)
    number(max_gap_points,.1,100); number(ambiguity_points,.01,100)
    opts, contenders = {}, {}
    for r in readings:
        if r.get('kind') not in ('INSTRUMENT_TAG','EQUIPMENT_TAG'):
            continue
        if r['page'] not in page_sizes:
            raise ValueError('Missing page dimensions in PDF points')
        width,height = page_sizes[r['page']]
        number(width,1,20000); number(height,1,20000)
        prefix = r['text_candidate'].split('-')[0]
        options = []
        for s in symbols:
            if s['page'] != r['page'] or s['eligibility'] not in ('ASSOCIATION_CANDIDATE','BUBBLE_GEOMETRY_CANDIDATE'):
                continue
            compatible = ((r['kind']=='INSTRUMENT_TAG' and s['kind']=='INSTRUMENT') or
                          (prefix in VALVE_CODES and s['kind']=='VALVE') or
                          (r['kind']=='EQUIPMENT_TAG' and s['kind']=='EQUIPMENT'))
            if not compatible:
                continue
            a,b = r['bbox'],s['bbox']
            gap = math.hypot(max(0,b['x0']-a['x1'],a['x0']-b['x1'])*width,
                             max(0,b['y0']-a['y1'],a['y0']-b['y1'])*height)
            if gap <= max_gap_points:
                options.append({'symbol_id':s['id'],'gap_points':round(gap,6),'origin':s.get('origin','EXPLICIT_CANDIDATE')})
        options.sort(key=lambda v:(v['gap_points'],v['symbol_id']))
        opts[r['id']] = options
        if options:
            contenders.setdefault(options[0]['symbol_id'],[]).append(r['id'])
    out = []
    for rid, options in sorted(opts.items()):
        state = ('NO_COMPATIBLE_CANDIDATE' if not options else
                 'MULTIPLE_TAGS_COMPETE' if len(contenders[options[0]['symbol_id']])>1 else
                 'AMBIGUOUS_SYMBOLS' if len(options)>1 and options[1]['gap_points']-options[0]['gap_points']<ambiguity_points else
                 'ASSOCIATION_PROPOSED')
        out.append({'id':ident('association',rid,options), 'reading_id':rid,
                    'symbol_id':options[0]['symbol_id'] if state=='ASSOCIATION_PROPOSED' else None,
                    'state':state,'options':options,'review_state':STATE})
    return out


def calibration_report(rows, *, dataset_id, source_sha256s, thresholds=(.65,.75,.85,.95)):
    """Produce a training-only threshold study; never lower the runtime gate.

    Labels refer to actual detector boxes, not a classifier's own predictions.
    Missed symbols require the separate exhaustive reference scorer.
    """
    from .common import source_hash
    collection(rows)
    if not dataset_id or not source_sha256s:
        raise ValueError('Named training dataset and drawing hashes required')
    for sha in source_sha256s:
        source_hash(sha)
    if any(type(r.get('is_correct')) is not bool or r.get('split')!='TRAIN' or
           r.get('source_sha256') not in source_sha256s or r.get('coarse_class') not in ('valve','instrumentation','general') for r in rows):
        raise ValueError('Use explicitly labelled TRAIN boxes from named drawings')
    out = []
    for t in thresholds:
        number(t,.65,1.)
        keep = [r for r in rows if number(r['raw_score'])>=t]
        tp = sum(r['is_correct'] for r in keep)
        out.append({'threshold':t,'retained':len(keep),'correct':tp,'false_positive':len(keep)-tp,
                    'precision':tp/len(keep) if keep else None,
                    'abstention_rate':1-len(keep)/len(rows) if rows else None})
    by_class={}
    for cls in sorted({r['coarse_class'] for r in rows}):
        subset=[r for r in rows if r['coarse_class']==cls]; studies=[]
        for t in thresholds:
            keep=[r for r in subset if r['raw_score']>=t];tp=sum(r['is_correct'] for r in keep)
            studies.append({'threshold':t,'retained':len(keep),'correct':tp,'false_positive':len(keep)-tp,
                            'precision':tp/len(keep) if keep else None,
                            'abstention_rate':1-len(keep)/len(subset)})
        by_class[cls]=studies
    return {'per_class':by_class,'status':'TRAINING_STUDY_ONLY','dataset_id':dataset_id,'dataset_sha256':digest(rows),
            'source_sha256s':source_sha256s,'thresholds':out,'runtime_gate_changed':False,
            'held_out_validation':'NOT_RUN'}


def explicit_candidates(rows, *, source_sha256):
    """Named reviewer proposes a class for a visible source box, independently
    of detector gating. Evidence is retained; this is not model calibration."""
    evidence_rows(rows)
    out=[]
    for r in rows:
        if r.get('source_sha256')!=source_sha256:raise ValueError('Symbol evidence source mismatch')
        if r.get('kind') not in ('EQUIPMENT','VALVE','INSTRUMENT'):
            raise ValueError('Unsupported proposed symbol class')
        if not r.get('actor','').strip() or not r.get('reason','').strip() or not r.get('evidence_ids'):
            raise ValueError('Symbol class proposal requires named reviewer, reason and source evidence')
        out.append({**r,'eligibility':'ASSOCIATION_CANDIDATE','origin':'REVIEWER_DRAWING_PROPOSAL',
                    'review_state':STATE})
    return out
