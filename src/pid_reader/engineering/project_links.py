"""Rev M: candidate off-page matches from manually annotated source drawing regions.

Matching labels are alternatives, NOT engineering edges. A separate named
reviewer must link a candidate as depicted on a specific drawing set.
"""
from __future__ import annotations

from itertools import combinations
from collections import defaultdict
from ..api import canonical_json, sha256_hex, stable_id

SCHEMA = 'pid-reader-standalone-crosssheet-v1'
MAX_ANNOTATIONS = 6000
MAX_CANDIDATES = 10000


def build_crosssheet_matches(annotations: list[dict], selected_extractions: list[str],
                             sources: dict[str, str],
                             drawing_snapshot: dict[str, dict] | None = None) -> dict:
    if (not isinstance(selected_extractions, list) or
        not 2 <= len(selected_extractions) <= 500 or
        any(not isinstance(x, str) or not x for x in selected_extractions) or
        len(set(selected_extractions)) != len(selected_extractions)):
        raise ValueError('Select two to 500 unique drawing extraction revisions')
    if set(selected_extractions) != set(sources) or any(not isinstance(v, str) or len(v) != 64 for v in sources.values()):
        raise ValueError('Exact source SHA-256 is required for every selected drawing')
    if drawing_snapshot is None:
        drawing_snapshot = {}
    elif (not isinstance(drawing_snapshot, dict) or set(drawing_snapshot) != set(selected_extractions)
          or any(not isinstance(v,dict) or
                 any(not isinstance(v.get(k),str) or not v[k] for k in
                     ('registration_id','drawing_no','revision_label','facility','area','document_sha256'))
                 for v in drawing_snapshot.values())):
        raise ValueError('Drawing catalogue snapshot does not match selected source revisions')
    if drawing_snapshot and any(drawing_snapshot[k]['document_sha256'] != sources[k] for k in selected_extractions):
        raise ValueError('Drawing snapshot source hash differs from selected revision')
    if not isinstance(annotations, list) or len(annotations) > MAX_ANNOTATIONS:
        raise ValueError('Connector annotation budget exceeded')
    ids = set()
    by_label = defaultdict(list)
    for a in annotations:
        if not isinstance(a, dict):
            raise ValueError('Invalid connector annotation')
        aid, eid, label = a.get('annotation_id'), a.get('extraction_id'), a.get('label')
        if not isinstance(aid, str) or not aid or aid in ids:
            raise ValueError('Duplicate or invalid connector annotation')
        ids.add(aid)
        if eid not in sources or a.get('source_sha256') != sources[eid]:
            raise ValueError('Connector annotation source mismatch')
        if not isinstance(label, str) or not label.strip() or len(label) > 120:
            raise ValueError('Invalid connector label')
        by_label[label.strip().casefold()].append(a)
    result = []
    for key, items in sorted(by_label.items()):
        unique_drawings = {x['extraction_id'] for x in items}
        if len(unique_drawings) < 2:
            continue
        ordered = sorted(items, key=lambda x: x['annotation_id'])
        for a, b in combinations(ordered, 2):
            if a['extraction_id'] == b['extraction_id']:
                continue
            result.append({
                'id': stable_id('crosssheet', key, a['annotation_id'], b['annotation_id']),
                'label': a['label'], 'label_key': key,
                'from_annotation_id': a['annotation_id'],
                'to_annotation_id': b['annotation_id'],
                'from_extraction_id': a['extraction_id'],
                'to_extraction_id': b['extraction_id'],
                'from_source_sha256': sources[a['extraction_id']],
                'to_source_sha256': sources[b['extraction_id']],
                'state': 'PROPOSED_UNVERIFIED',
                'ambiguity': 'MULTIPLE_CANDIDATE_ENDPOINTS' if len(ordered) > 2 else 'ONE_CANDIDATE_PAIR',
                'limitations': 'Matching user-annotated connector labels; does not verify that the two drawings or actual plant are connected.'
            })
            if len(result) > MAX_CANDIDATES:
                raise ValueError('Cross-sheet proposal budget exceeded')
    result.sort(key=lambda x: x['id'])
    body = {'schema': SCHEMA, 'algorithm': 'source-bound-explicit-connector-matching-0.1',
            'selected_extractions': sorted(selected_extractions),
            'source_hashes': {k: sources[k] for k in sorted(sources)},
            'annotation_ids': sorted(ids),
            'drawing_catalogue_snapshot': {k:drawing_snapshot[k] for k in sorted(drawing_snapshot)},
            'candidates': result,
            'limitations': 'These are source-region-matched drawing annotations only; no physical connection, loop or plant identity is established.'}
    body['result_sha256'] = sha256_hex(canonical_json(body).encode('utf-8'))
    return body
