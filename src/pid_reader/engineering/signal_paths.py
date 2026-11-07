"""Rev M: signal-style stroke path queries with review-evidence boundaries.

This is NOT an instrument-loop finder or evidence of plant wiring. Only stroke
contacts explicitly reviewed as CONNECTED_AS_DRAWN are traversed by default.
Endpoints to instrument outlines are separately subject to signal reviews.
"""
from __future__ import annotations

from collections import defaultdict, deque

from ..api import canonical_json, sha256_hex, RefusedInput
from .topology import validate_topology_result
from .symbols import validate_symbol_proposals
from .linework import validate_linework_proposals
from .signal_links import validate_signal_links

SCHEMA = 'pid-reader-standalone-signal-path-v1'
MAX_HOPS = 60
MAX_STROKES = 3000
MAX_EDGES = 7000


def trace_signal_path(extraction: dict, topology: dict, symbols: dict,
                      linework: dict, signals: dict, geometry_reviews: dict[str, str],
                      signal_reviews: dict[str, str], start_segment_id: str, *,
                      include_unreviewed: bool = False, max_hops: int = 15) -> dict:
    """Trace dashed vector strokes; never silently assert a control loop.

    All identifiers in the supplied review maps are *native* candidate IDs from
    the validated input analyses, NOT arbitrary GUI/db identifiers.
    """
    if not isinstance(start_segment_id, str) or not start_segment_id:
        raise ValueError('A source signal segment is required')
    if type(max_hops) is not int or not 0 <= max_hops <= MAX_HOPS:
        raise ValueError('Invalid hop count')
    if type(include_unreviewed) is not bool:
        raise ValueError('Invalid proposal mode')
    if validate_topology_result(topology) or validate_symbol_proposals(symbols, extraction, topology):
        raise ValueError('Invalid source or symbol geometry')
    if validate_linework_proposals(linework, extraction, topology, symbols):
        raise ValueError('Linework is not reproducible from source')
    if validate_signal_links(signals, extraction, topology, symbols, linework):
        raise ValueError('Signal proposals are not reproducible from source')
    if not isinstance(geometry_reviews, dict) or not isinstance(signal_reviews, dict):
        raise ValueError('Review evidence must be mapping objects')
    segments = {s['id']: s for s in topology['segments']}
    roles = {r['segment_id']: r['role'] for r in linework['stroke_roles']}
    eligible = {sid: seg for sid, seg in segments.items()
                if roles.get(sid) == 'SIGNAL_STYLE_CANDIDATE' and seg['style'] == 'DASHED_OR_DOTTED'}
    if start_segment_id not in eligible:
        raise ValueError('Starting stroke is not an observed signal-style candidate')
    contacts = {c['id']: c for c in topology['contact_candidates']}
    anchors = {a['id']: a for a in signals['candidates']}
    allowed_geom = {'CONNECTED_AS_DRAWN', 'NOT_CONNECTED_AS_DRAWN', 'REJECTED', 'UNRESOLVED'}
    allowed_sig = {'SUPPORTED_AS_DRAWN', 'NOT_CONNECTED_AS_DRAWN', 'REJECTED', 'UNRESOLVED'}
    if any(cid not in contacts or state not in allowed_geom for cid, state in geometry_reviews.items()):
        raise ValueError('Geometry review does not belong to this analysis')
    if any(cid not in anchors or state not in allowed_sig for cid, state in signal_reviews.items()):
        raise ValueError('Signal review does not belong to this analysis')

    adjacency = defaultdict(list)
    for c in topology['contact_candidates']:
        a, b = c['segment_ids']
        if a not in eligible or b not in eligible:
            continue
        status = geometry_reviews.get(c['id'])
        if status in ('REJECTED', 'NOT_CONNECTED_AS_DRAWN'):
            continue
        if status != 'CONNECTED_AS_DRAWN' and not include_unreviewed:
            continue
        state = ('REVIEWED_CONNECTED_AS_DRAWN' if status == 'CONNECTED_AS_DRAWN'
                 else 'UNREVIEWED_GEOMETRIC_CONTACT')
        edge = {'contact_id': c['id'], 'from_segment_id': a, 'to_segment_id': b,
                'page': c['page'], 'contact_kind': c['kind'], 'point': c['point'],
                'state': state}
        adjacency[a].append((b, edge))
        adjacency[b].append((a, edge))
    for neighbors in adjacency.values():
        neighbors.sort(key=lambda e: (e[0], e[1]['contact_id']))

    reached = {start_segment_id: 0}
    queue = deque([start_segment_id])
    found_edges = {}
    while queue:
        node = queue.popleft()
        if reached[node] >= max_hops:
            continue
        for dest, edge in adjacency[node]:
            found_edges[edge['contact_id']] = edge
            if dest not in reached:
                reached[dest] = reached[node] + 1
                queue.append(dest)
            if len(reached) > MAX_STROKES or len(found_edges) > MAX_EDGES:
                raise RefusedInput('PID_LIMIT_GEOMETRY', 'Signal path is too large')

    endpoint_evidence = []
    for item in signals['candidates']:
        if item['segment_id'] not in reached:
            continue
        status = signal_reviews.get(item['id'])
        if status in ('REJECTED', 'NOT_CONNECTED_AS_DRAWN'):
            continue
        if status != 'SUPPORTED_AS_DRAWN' and not include_unreviewed:
            continue
        endpoint_evidence.append({
            'candidate_id': item['id'], 'symbol_id': item['symbol_id'],
            'segment_id': item['segment_id'], 'page': item['page'],
            'point': item['point'],
            'state': ('REVIEWED_ENDPOINT_AS_DRAWN' if status == 'SUPPORTED_AS_DRAWN'
                      else 'UNREVIEWED_ENDPOINT_PROPOSAL'),
        })
    endpoint_evidence.sort(key=lambda x: (x['page'], x['symbol_id'], x['candidate_id']))
    members = [{'segment_id': sid, 'page': eligible[sid]['page'],
                'endpoints': eligible[sid]['endpoints'], 'hops': hops}
               for sid, hops in sorted(reached.items())]
    base = {
        'schema': SCHEMA,
        'source_sha256': topology['source_sha256'],
        'extraction_sha256': extraction['provenance']['result_sha256'],
        'topology_sha256': topology['result_sha256'],
        'linework_sha256': linework['result_sha256'],
        'signal_sha256': signals['result_sha256'],
        'review_snapshot_sha256': sha256_hex(canonical_json({
            'geometry': geometry_reviews, 'signals': signal_reviews}).encode('utf-8')),
        'start_segment_id': start_segment_id,
        'include_unreviewed': include_unreviewed,
        'max_hops': max_hops,
        'segments': members,
        'contacts': sorted(found_edges.values(), key=lambda x: x['contact_id']),
        'instrument_outline_endpoints': endpoint_evidence,
        'limitations': ('Drawn dashed-stroke path and source-linked instrument-outline endpoints only. '
                        'No process function, instrument loop, control action or physical plant '
                        'connectivity is established.'),
    }
    base['result_sha256'] = sha256_hex(canonical_json(base).encode('utf-8'))
    return base
