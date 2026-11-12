"""WP04: provenance-preserving dedup, bounded re-read regions and alternatives."""
from __future__ import annotations
from copy import deepcopy
import re
from .common import (STATE, area, box, center, clean, collection, evidence_rows,
                     ident, iou, number, overlap)

# Explicit starter vocabulary; not an ISA library or a complete plant taxonomy.
CODES = {'FR','FE','FI','FT','FIC','FIT','FQ','FQI','FQI','PIC','PI','PT','PSV',
         'LT','LI','LIC','LIT','TT','TI','TIC','XV','HV','SDV','ESDV','BDV','PG','TG'}
LINE = re.compile(r'^[A-Z]{2,5}-\d{4,7}-\d{1,4}(?:\.\d{1,2})?-[A-Z][A-Z0-9]{1,4}-[A-Z0-9]{2,5}$')


def deduplicate(rows, *, text_key='text', kind_key='kind', overlap_gate=.65):
    """Same class/text/page and overlapping boxes only; keep all source members.

    Complete-link spatial clusters prevent a chain of overlapping words merging
    separate printed occurrences. Conflicting text always remains separate.
    """
    evidence_rows(rows); number(overlap_gate, .1, 1.)
    groups = []
    for row in sorted(rows, key=lambda r: r['id']):
        for cluster in groups:
            if all(row['page'] == q['page'] and row.get(kind_key) == q.get(kind_key)
                   and clean(row[text_key]) == clean(q[text_key])
                   and overlap(row['bbox'], q['bbox']) / min(area(row['bbox']), area(q['bbox'])) >= overlap_gate
                   for q in cluster):
                cluster.append(row)
                break
        else:
            groups.append([row])
    out = []
    for cluster in groups:
        chosen = max(cluster, key=lambda r: (r.get('raw_score', r.get('raw_ocr_score', 0)), r['id']))
        merged = deepcopy(chosen)
        merged['member_ids'] = sorted(q['id'] for q in cluster)
        merged['evidence_members'] = deepcopy(cluster)
        merged['ocr_ids'] = sorted({s for q in cluster for s in q.get('ocr_ids', [q['id']])})
        merged['id'] = ident('merged', text_key, kind_key, merged['member_ids'])
        merged['review_state'] = STATE
        out.append(merged)
    return sorted(out, key=lambda r: (r['page'], r['bbox']['y0'], r['bbox']['x0'], r['id']))


def propose_regions(words, bubbles=(), *, selected=None, max_regions=24, max_area=.02):
    """Prioritise selected region, circles, suspect lines, weak tags, title clues.

    Input frame is explicitly MediaBox normalized, top-left. A capped list is
    returned with truncation diagnostics; no hidden S418 coordinates.
    """
    evidence_rows(words); evidence_rows(list(bubbles))
    if type(max_regions) is not int or not 1 <= max_regions <= 48:
        raise ValueError('Region count budget')
    number(max_area, .001, .1)
    candidates = []
    if selected:
        from .common import page
        page(selected['page']); box(selected['bbox'])
        candidates.append((0, selected['page'], selected['bbox'], 'USER_SELECTION', []))
    for b in bubbles:
        candidates.append((1, b['page'], b['bbox'], 'BUBBLE_INTERIOR', [b['id']]))
    for w in words:
        text = clean(w['text'])
        if text.count('-') >= 2 and any(c.isdigit() for c in text):
            priority, why = 2, 'LINE_NUMBER_REREAD'
        elif re.fullmatch(r'[A-Z]{1,5}-?\d{3,7}[A-Z]?', text):
            priority, why = 3, 'TAG_REREAD'
        elif any(t in text for t in ('DRAWING', 'SCALE', 'REVISION')):
            priority, why = 4, 'TITLE_FIELD_REREAD'
        else:
            continue
        candidates.append((priority, w['page'], w['bbox'], why, [w['id']]))
    # Round-robin evidence types so a page full of circles cannot starve
    # line-number re-reading within the OCR call budget.
    ordered = sorted(candidates, key=lambda r: (r[0], r[1], r[2]['y0'], r[2]['x0']))
    selected_items = [r for r in ordered if r[0] == 0]
    buckets = {p:[r for r in ordered if r[0]==p] for p in (1,2,3,4)}
    balanced = list(selected_items)
    while any(buckets.values()):
        for bucket in buckets.values():
            if bucket: balanced.append(bucket.pop(0))
    out, rejected = [], []
    for priority, pg, b, why, ids in balanced:
        # Selected crops are exact. Automatic crops add nearby context.
        dx = 0 if why == 'USER_SELECTION' else max(.003, .2*(b['x1']-b['x0']))
        dy = 0 if why == 'USER_SELECTION' else max(.003, .35*(b['y1']-b['y0']))
        bb = box({'x0':max(0,b['x0']-dx),'y0':max(0,b['y0']-dy),
                  'x1':min(1,b['x1']+dx),'y1':min(1,b['y1']+dy)})
        if area(bb) > max_area:
            rejected.append({'reason':'REGION_AREA_BUDGET', 'evidence_ids':ids})
            continue
        if any(q['page'] == pg and iou(q['bbox'], bb) > .65 for q in out):
            continue
        if len(out) == max_regions:
            rejected.append({'reason':'REGION_COUNT_BUDGET', 'evidence_ids':ids})
            continue
        out.append({'id':ident('roi', pg, bb, why, ids), 'page':pg, 'bbox':bb,
                    'reason':why, 'evidence_ids':ids, 'priority':priority})
    return {'regions':out, 'withheld':rejected, 'truncated':bool(rejected)}


def line_alternatives(readings, words):
    """Offer only complete strings independently observed over the same label.

    Grammar can trigger re-reading but cannot invent a leading H or a digit.
    Conflicting originals remain visible, including when both pass grammar.
    """
    evidence_rows(readings); evidence_rows(words)
    out = []
    for r in readings:
        if r.get('kind') != 'PIPE_LINE_NUMBER':
            continue
        options = []
        for w in words:
            if w['page'] != r['page'] or clean(w['text']) == clean(r['text_candidate']):
                continue
            if not LINE.fullmatch(clean(w['text'])):
                continue
            if overlap(w['bbox'],r['bbox']) / min(area(w['bbox']),area(r['bbox'])) < .6:
                continue
            options.append({'text_candidate':clean(w['text']), 'ocr_ids':[w['id']],
                            'reason':'INDEPENDENT_OVERLAPPING_OCR_READING', 'review_state':STATE})
        out.append({'id':ident('line-review',r['id'],options), 'reading_id':r['id'],
                    'page':r['page'], 'bbox':r['bbox'], 'original':r['text_candidate'],
                    'alternatives':options, 'state':'CONFLICT_REQUIRES_REVIEW' if options else 'REREAD_OR_VISUAL_REVIEW_REQUIRED',
                    'review_state':STATE})
    return out


def bubble_readings(bubbles, words):
    """Code above number within one bubble, one OCR run, one region.

    A number from another pass/rotation is never combined with a code. Codes
    with competing readings produce warnings, not automatic substitutions.
    """
    evidence_rows(list(bubbles)); evidence_rows(words)
    out = []
    for b in bubbles:
        inside = [w for w in words if w['page'] == b['page'] and
                  overlap(w['bbox'], b['bbox']) >= .85*area(w['bbox'])]
        codes = [w for w in inside if clean(w['text']) in CODES]
        nums = [w for w in inside if re.fullmatch(r'\(?\d{3,7}[A-Z]?\)?',clean(w['text']))]
        options, warnings = [], []
        for c in codes:
            for n in nums:
                if center(c['bbox'])[1] >= center(n['bbox'])[1]:
                    continue
                if abs(center(c['bbox'])[0]-center(n['bbox'])[0]) > .35*(b['bbox']['x1']-b['bbox']['x0']):
                    continue
                same_run = bool(c.get('run_id')) and c.get('run_id') == n.get('run_id') and c.get('roi_id') == n.get('roi_id')
                if not same_run:
                    warnings.append('CROSS_RUN_FRAGMENTS_NOT_JOINED')
                    continue
                options.append({'text_candidate':clean(c['text'])+'-'+clean(n['text']).strip('()'),
                                'ocr_ids':[c['id'],n['id']], 'run_id':c['run_id'], 'review_state':STATE})
        distinct = {o['text_candidate'] for o in options}
        if len(distinct) > 1:
            warnings.append('CONFLICTING_BUBBLE_READINGS')
        if any(clean(c['text']) in ('FR','FQ') for c in codes):
            warnings.append('FR_FQ_CONFUSION_CHECK')
        if not options:
            warnings.append('INCOMPLETE_INSTRUMENT_READING')
        out.append({'id':ident('bubble-reading',b['id'],options), 'bubble_id':b['id'], 'page':b['page'],
                    'bbox':b['bbox'], 'options':options, 'warnings':sorted(set(warnings)),
                    'review_state':STATE, 'evidence_ids':sorted(w['id'] for w in inside)})
    return out


def bubble_tag_proposals(bubble_results, words):
    """Promote a unique same-run printed reading to the proposal register only.

    Conflicting strings remain in the bubble review queue. This never assigns
    a functional instrument type or marks a tag as accepted.
    """
    by_id={w['id']:w for w in words};out=[]
    for b in bubble_results:
        distinct={o['text_candidate'] for o in b['options']}
        if len(distinct)!=1:continue
        text=next(iter(distinct));ids=sorted({x for o in b['options'] for x in o['ocr_ids']})
        parts=[by_id[x] for x in ids]
        bb={k:(min(p['bbox'][k] for p in parts) if k in ('x0','y0') else max(p['bbox'][k] for p in parts))
            for k in ('x0','y0','x1','y1')}
        out.append({'id':ident('bubble-tag',b['bubble_id'],text,ids),'page':b['page'],'bbox':bb,
                    'kind':'INSTRUMENT_TAG','text_candidate':text,'ocr_ids':ids,
                    'raw_ocr_score':min(p['raw_score'] for p in parts),
                    'warnings':b['warnings'],'origin':'SAME_RUN_BUBBLE_PRINTED_READING',
                    'review_state':STATE,'association_state':'UNLINKED'})
    return out
