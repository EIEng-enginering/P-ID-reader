"""Compose additive WP04–06 envelopes. Frozen R1 and standalone DB untouched."""
from __future__ import annotations
from copy import deepcopy
import csv
import json
from pathlib import Path
from .common import FRAME, STATE, digest, ident, seal, source_hash, verify_seal
from .readings import deduplicate, line_alternatives, bubble_readings, bubble_tag_proposals, propose_regions
from .symbols import candidates, associations, explicit_candidates
from .topology import build_graph


def build(wp123, words, *, page_sizes, segments=None, ports=None, junctions=None, symbol_evidence=None):
    source_hash(wp123['source_sha256'])
    if wp123.get('schema')!='pid-reader-wp123-recovery-v1' or not verify_seal(wp123):
        raise ValueError('Invalid WP123 result schema or content hash')
    # Changes to evidence must rebuild WP123 first; never attach new OCR to old
    # readings while retaining an obsolete evidence digest.
    if wp123.get('inputs',{}).get('ocr_evidence_sha256')!=digest(words):
        raise ValueError('OCR evidence differs from WP123 inputs')
    bubbles=wp123.get('bubble_candidates',[])
    bubble_results=bubble_readings(bubbles,words)
    readings=deduplicate(wp123['readings']+bubble_tag_proposals(bubble_results,words),text_key='text_candidate')
    fields=deduplicate(wp123['document_fields'],text_key='value_candidate',kind_key='field')
    bubbles=wp123.get('bubble_candidates',[])
    syms=candidates(wp123.get('detector_decisions',[]),bubbles)+explicit_candidates(symbol_evidence or [],source_sha256=wp123['source_sha256'])
    links=associations(readings,syms,page_sizes=page_sizes)
    graph=build_graph(segments or [],ports or [],junctions or [],page_sizes=page_sizes)
    return seal({'schema':'pid-reader-wp456-proposals-v1','algorithm':'wp456-0.1.0',
                 'source_sha256':wp123['source_sha256'],'frame':FRAME,'review_state':STATE,
                 'upstream_wp123_sha256':wp123['result_sha256'],
                 'upstream_wp123_result':deepcopy(wp123),'ocr_evidence':deepcopy(words),
                 'inputs':{'words_sha256':digest(words),'page_sizes':{str(k):v for k,v in page_sizes.items()},
                           'segments_sha256':digest(segments or []),'ports_sha256':digest(ports or []),
                           'junctions_sha256':digest(junctions or []),'symbol_evidence_sha256':digest(symbol_evidence or [])},
                 'wp04':{'readings':readings,'document_fields':fields,
                         'line_number_fragments':deepcopy(wp123.get('line_number_fragments',[])),
                         'line_reviews':line_alternatives(readings,words),
                         'bubble_readings':bubble_results,
                         'automatic_regions':propose_regions(words,bubbles)},
                 'wp05':{'symbols':syms,'explicit_symbol_evidence':symbol_evidence or [],'associations':links,'calibration_status':'NOT_RUN'},
                 'wp06':{'graph':graph,'source_segments':deepcopy(segments or []),'source_ports':deepcopy(ports or []),
                         'source_junctions':deepcopy(junctions or []),'geometry_input_status':'SUPPLIED' if segments else 'NOT_SUPPLIED',
                         'worksheet_r1_status':'UNCHANGED_NOT_EXPORTED'},
                 'metrics':{'status':'NOT_RUN','reason':'APPROVED_EXHAUSTIVE_REFERENCE_REQUIRED'},
                 'notice':'Reviewable drawing hypotheses only. No accepted engineering objects, plant connections or safety credit.'})


def export(result, directory):
    if result.get('schema')!='pid-reader-wp456-proposals-v1' or not verify_seal(result):
        raise ValueError('Invalid result envelope')
    dst=Path(directory); dst.mkdir(parents=True,exist_ok=True)
    (dst/'wp456_result.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n',encoding='utf8')
    def safe(s):
        s=str(s)
        return "'"+s if s.lstrip().startswith(('=','+','-','@')) or s.startswith(('\t','\r','\n')) else s
    with (dst/'wp456_readings.csv').open('w',encoding='utf8',newline='') as f:
        w=csv.writer(f); w.writerow(['id','page','kind','text_candidate','review_state','evidence_ids'])
        for r in result['wp04']['readings']:
            w.writerow([safe(r.get(k,'')) for k in ('id','page','kind','text_candidate','review_state')]+[';'.join(r['ocr_ids'])])
    (dst/'wp456_geometry_proposals.json').write_text(json.dumps(result['wp06'],sort_keys=True,indent=2)+'\n',encoding='utf8')
    return str(dst)
