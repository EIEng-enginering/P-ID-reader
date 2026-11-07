"""Rev V: conservative centreline *hypotheses* from already-source-verified raster strokes.

A centreline here describes one ink observation family, NOT a pipe, electrical
conductor, instrument signal, process line, valve port or plant connection.
Neither collinear gaps nor intersections are automatically connected.  The
only path edges are explicit drawing-review decisions, or clearly labelled
unreviewed candidate edges when requested for investigation.

This layer does not alter the Worksheet R1 API, schema or worker.
"""
from __future__ import annotations

from collections import defaultdict, deque
from math import hypot, isfinite
from typing import Any

from ..api import canonical_json, sha256_hex, stable_id, LimitExceeded
from .raster_geometry import validate_raster_result
from .raster_network import validate_raster_network, _frame, _pixel, _source

SCHEMA = 'pid-reader-standalone-raster-centrelines-v1'
ALGORITHM = 'duplicate-supported-centrelines-gaps-0.1'
MAX_LINES = 7000
MAX_GAPS = 3500
MAX_PAIR_TESTS = 60000
MAX_GRID_INSERTS = 120000
GRID = 36
MAX_GAP_PX = 16.0
MAX_OFFSET_PX = 2.8
MAX_ANGLE_SINE = .085
MIN_LINE_PX = 22.


def _median(values):
    values=sorted(values)
    n=len(values)
    return (values[(n-1)//2]+values[n//2])/2


def _group_centreline(strokes, positions):
    # Recover a centreline using the longest source stroke as the direction.
    # Cross-track medians suppress parallel Hough lines arising from thick ink.
    ref=max(strokes,key=lambda x:(hypot(positions[x][1][0]-positions[x][0][0],
                                      positions[x][1][1]-positions[x][0][1]),x))
    a,b=positions[ref]
    length=hypot(b[0]-a[0],b[1]-a[1]);ux=(b[0]-a[0])/length;uy=(b[1]-a[1])/length
    # Fixed direction makes output deterministic irrespective of Hough endpoint order.
    if ux<0 or (abs(ux)<1e-9 and uy<0):ux=-ux;uy=-uy
    tx=[];ty=[]
    for sid in strokes:
        p,q=positions[sid]
        for point in (p,q):
            tx.append(point[0]*ux+point[1]*uy)
            ty.append(-point[0]*uy+point[1]*ux)
    offset=_median(ty)
    lo=min(tx);hi=max(tx)
    return (lo*ux-offset*uy,lo*uy+offset*ux), (hi*ux-offset*uy,hi*uy+offset*ux)


def _gap_candidate(a,b,c,d):
    """Return (pixel midpoint, size, lateral offset) for facing axis-aligned ends.

    Collinear but overlapping segments, parallel neighbouring pipes, skewed
    strokes, T-junctions, and perpendicular crossings cannot satisfy this.
    """
    l1=hypot(b[0]-a[0],b[1]-a[1]);l2=hypot(d[0]-c[0],d[1]-c[1])
    if min(l1,l2)<MIN_LINE_PX:return None
    vx=((b[0]-a[0])/l1,(b[1]-a[1])/l1)
    wx=((d[0]-c[0])/l2,(d[1]-c[1])/l2)
    if abs(vx[0]*wx[1]-vx[1]*wx[0])>MAX_ANGLE_SINE:return None
    # Ordered from left/top -> right/bottom; look only for b -> c or d -> a.
    for left_end,right_start,unit in ((b,c,vx),(d,a,wx)):
        dx=right_start[0]-left_end[0];dy=right_start[1]-left_end[1]
        along=dx*unit[0]+dy*unit[1]
        lateral=abs(dx*unit[1]-dy*unit[0])
        if 2.0 <= along <= MAX_GAP_PX and lateral <= MAX_OFFSET_PX:
            return ((left_end[0]+right_start[0])/2,(left_end[1]+right_start[1])/2),round(along,2),round(lateral,2)
    return None


def build_raster_centrelines(raster:dict,network:dict)->dict:
    """Deterministically derive centreline evidence and *unresolved* small gaps."""
    if validate_raster_result(raster):
        raise ValueError('Invalid source raster geometry')
    if network.get('source_sha256')!=raster.get('source_sha256') or network.get('raster_result_sha256')!=raster.get('result_sha256'):
        raise ValueError('Raster network/source hash mismatch')
    # An OCR-derived network may require its actual OCR source to recompute.
    # Verify its own content hash and all referential inputs; database persistence
    # separately validates the network against its original stored OCR evidence.
    nh={k:v for k,v in network.items() if k!='result_sha256'}
    if sha256_hex(canonical_json(nh).encode())!=network.get('result_sha256'):
        raise ValueError('Invalid raster network content hash')
    if network.get('schema')!='pid-reader-standalone-raster-network-v1':
        raise ValueError('Unexpected raster network schema')
    positions={};pages={r['page']:r for r in raster['page_frames']}
    source_strokes=raster['stroke_candidates']
    if len(source_strokes)>MAX_LINES:raise LimitExceeded('PID_LIMIT_RASTER','Centreline observation budget exceeded')
    for stroke in source_strokes:
        page=pages[stroke['page']];frame=_frame(page)
        pair=tuple(_pixel(frame,page,p) for p in stroke['endpoints'])
        if not all(isfinite(v) for pt in pair for v in pt):raise ValueError('Non-finite source stroke')
        positions[stroke['id']]=pair
    context={s['stroke_id']:s['role'] for s in network['stroke_evidence']}
    if set(context)!=set(positions):raise ValueError('Raster network stroke set differs from source')
    parent={sid:sid for sid in positions}
    def find(x):
        while parent[x]!=x:
            parent[x]=parent[parent[x]];x=parent[x]
        return x
    for group in network['duplicate_observation_groups']:
        members=group['stroke_ids'];rep=group['representative_stroke_id']
        if rep not in members or any(x not in parent for x in members):
            raise ValueError('Unknown stroke in duplicate evidence')
        for x in members:parent[find(x)]=find(rep)
    grouped=defaultdict(list);source_pages={s['id']:s['page'] for s in source_strokes}
    for sid in sorted(parent):grouped[find(sid)].append(sid)
    centrelines=[];pixel_lines={};by_page=defaultdict(list)
    for rep,ids in sorted(grouped.items()):
        page=source_pages[ids[0]]
        if any(source_pages[sid]!=page for sid in ids):raise ValueError('Cross-page duplicate grouping')
        a,b=_group_centreline(ids,positions)
        if hypot(b[0]-a[0],b[1]-a[1])<MIN_LINE_PX:continue
        row=pages[page];frame=_frame(row)
        roles=sorted({context[sid] for sid in ids})
        line_id=stable_id('raster-centreline',raster['source_sha256'],page,ids,ALGORITHM)
        role=('PAGE_FRAME_STROKE_CANDIDATE' if roles==['PAGE_FRAME_STROKE_CANDIDATE']
              else 'CONTEXT_REVIEW_REQUIRED' if any('OCR' in r or 'TEXT' in r or 'SYMBOL' in r or 'PAGE_FRAME' in r for r in roles)
              else 'LINEWORK_UNCLASSIFIED')
        centrelines.append({'id':line_id,'page':page,'source_stroke_ids':ids,
                            'endpoints':[_source(frame,row,a),_source(frame,row,b)],
                            'length_px':round(hypot(b[0]-a[0],b[1]-a[1]),2),
                            'context':role,'source_roles':roles,'status':'PROPOSED_UNVERIFIED'})
        pixel_lines[line_id]=(a,b);by_page[page].append(line_id)
    if len(centrelines)>MAX_LINES:raise LimitExceeded('PID_LIMIT_RASTER','Centreline output budget exceeded')
    # Small endpoint search, not an all-pairs geometric graph.
    proposals=[];pairs=0;inserts=0;seen=set()
    contexts={cl['id']:cl['context'] for cl in centrelines}
    for page,ids in sorted(by_page.items()):
        grid=defaultdict(set);row=pages[page];frame=_frame(row)
        for lid in sorted(ids):
            a,b=pixel_lines[lid]
            for p in (a,b):
                key=(int(p[0]//GRID),int(p[1]//GRID))
                near=set()
                for gx in range(key[0]-1,key[0]+2):
                    for gy in range(key[1]-1,key[1]+2):near.update(grid.get((gx,gy),()))
                for other in sorted(near):
                    pair=tuple(sorted((lid,other)))
                    if pair in seen:continue
                    seen.add(pair);pairs+=1
                    if pairs>MAX_PAIR_TESTS:raise LimitExceeded('PID_LIMIT_RASTER','Centreline pair budget exceeded')
                    if lid==other:continue
                    match=_gap_candidate(*pixel_lines[pair[0]],*pixel_lines[pair[1]])
                    if match is None:continue
                    middle,gap,offset=match
                    if 'PAGE_FRAME_STROKE_CANDIDATE' in (contexts[pair[0]],contexts[pair[1]]):continue
                    warning=('TEXT_OR_SYMBOL_CONTEXT_REVIEW' if any(contexts[x]=='CONTEXT_REVIEW_REQUIRED' for x in pair)
                             else 'UNKNOWN_PROCESS_OR_INSTRUMENT_STROKE')
                    candidates={'id':stable_id('raster-gap',raster['source_sha256'],page,pair,ALGORITHM),
                                'page':page,'centreline_ids':list(pair),'point':_source(frame,row,middle),
                                'gap_px':gap,'lateral_offset_px':offset,'context_warning':warning,
                                'status':'UNRESOLVED',
                                'limitations':'Two line observations face across a small gap on paper. No pipe continuity or plant connection is established.'}
                    proposals.append(candidates)
                    if len(proposals)>MAX_GAPS:raise LimitExceeded('PID_LIMIT_RASTER','Centreline gap output budget exceeded')
                grid[key].add(lid);inserts+=1
                if inserts>MAX_GRID_INSERTS:raise LimitExceeded('PID_LIMIT_RASTER','Centreline index budget exceeded')
    result={'schema':SCHEMA,'algorithm':ALGORITHM,'source_sha256':raster['source_sha256'],
            'raster_result_sha256':raster['result_sha256'],'network_result_sha256':network['result_sha256'],
            'coordinate_frame':'PDFPLUMBER_MEDIA_NORMALIZED_V1',
            'centrelines':sorted(centrelines,key=lambda x:(x['page'],x['id'])),
            'gap_candidates':sorted(proposals,key=lambda x:(x['page'],x['id'])),
            'statistics':{'source_strokes':len(source_strokes),'centrelines':len(centrelines),
                          'duplicate_strokes':len(source_strokes)-len(grouped),
                          'gap_proposals':len(proposals),'gap_pair_checks':pairs},
            'disclaimer':'Ink centrelines only. No signal, piping, equipment port, drawing continuity, or physical plant connection is verified.'}
    result['result_sha256']=sha256_hex(canonical_json(result).encode())
    if len(canonical_json(result).encode())>8*1024*1024:raise LimitExceeded('PID_LIMIT_RASTER','Centreline JSON exceeds 8 MiB')
    return result


def validate_raster_centrelines(result:dict,raster:dict,network:dict)->list[str]:
    try:
        expected=build_raster_centrelines(raster,network)
        return [] if canonical_json(result)==canonical_json(expected) else ['Centreline evidence does not match source']
    except (TypeError,ValueError,KeyError,IndexError,LimitExceeded,ZeroDivisionError) as exc:
        return [f'Invalid centreline evidence: {type(exc).__name__}: {exc}']


def trace_reviewed_centrelines(db:Any,analysis_id:str,start_line_id:str,
                               *,include_unreviewed:bool=False,max_hops:int=20)->dict:
    """Read-only traversal of human-reviewed *drawing* contacts and gaps.

    Unreviewed optional traversals are exploratory and explicitly annotated.
    It is impossible to infer a process flow or a real plant connection here.
    """
    if type(max_hops) is not int or not 1<=max_hops<=60:raise ValueError('max_hops must be 1-60')
    result=db.get_raster_centreline_analysis(analysis_id)
    lines={r['id']:r for r in result['centrelines']}
    if start_line_id not in lines:raise KeyError('Centreline does not belong to analysis')
    row=db.db.execute('SELECT raster_network_analysis_id FROM raster_centreline_analysis WHERE analysis_id=?',(analysis_id,)).fetchone()
    network_id=row[0]
    # Resolve each original stroke to its centreline group.
    aliases={sid:line['id'] for line in lines.values() for sid in line['source_stroke_ids']}
    links=defaultdict(list)
    # Read the complete persisted candidate set; no silent 1,000-row truncation.
    import json
    contact_rows=db.db.execute('SELECT candidate_id,candidate_json FROM raster_network_candidate '
                               'WHERE analysis_id=? ORDER BY page,candidate_id',(network_id,))
    for contact_id,candidate_json in contact_rows:
        native=json.loads(candidate_json);left,right=(aliases.get(x) for x in native['stroke_ids'])
        if left is None or right is None or left==right:continue
        decision=db.latest_raster_network_review(contact_id)
        state=decision['decision'] if decision else 'UNRESOLVED'
        if state!='CONTACT_AS_DRAWN' and not (include_unreviewed and state=='UNRESOLVED'):continue
        obj={'kind':'RASTER_CONTACT','candidate_id':contact_id,
             'review_state':state,'provisional':state!='CONTACT_AS_DRAWN'}
        links[left].append((right,obj));links[right].append((left,obj))
    for gap in db.list_raster_centreline_gaps(analysis_id,limit=MAX_GAPS):
        left,right=gap['candidate']['centreline_ids']
        decision=db.latest_raster_centreline_review(gap['candidate_id'])
        state=decision['decision'] if decision else 'UNRESOLVED'
        if state!='CONTINUOUS_AS_DRAWN' and not (include_unreviewed and state=='UNRESOLVED'):continue
        obj={'kind':'COLLINEAR_GAP','candidate_id':gap['candidate_id'],
             'review_state':state,'provisional':state!='CONTINUOUS_AS_DRAWN'}
        links[left].append((right,obj));links[right].append((left,obj))
    visited={start_line_id};q=deque([(start_line_id,0)]);edges={}
    while q:
        point,hops=q.popleft()
        if hops>=max_hops:continue
        for to,info in sorted(links[point],key=lambda p:(p[0],p[1]['candidate_id'])):
            key=info['candidate_id'];edges[key]={'from_id':min(point,to),'to_id':max(point,to),**info}
            if to not in visited:
                visited.add(to);q.append((to,hops+1))
    return {'analysis_id':analysis_id,'start_centreline_id':start_line_id,
            'include_unreviewed':include_unreviewed,'max_hops':max_hops,
            'centreline_ids':sorted(visited),'traversed_edges':sorted(edges.values(),key=lambda x:x['candidate_id']),
            'notice':'Drawing-only review states; not proof of physical plant connectivity, service, or flow direction.'}
