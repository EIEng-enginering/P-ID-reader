"""WP06 straight-segment geometry hypotheses. Never confirms plant connectivity.

Crossings and T contacts remain unresolved without explicit junction evidence.
Only same-page, same known stroke types may share a proposed geometry node.
No off-page inference, raster gap repair, process-flow direction or loop credit.
"""
from __future__ import annotations
from collections import defaultdict
import math
from .common import STATE, collection, ident, number, page

KNOWN = {'PROCESS','SIGNAL'}


def point(p):
    if not isinstance(p,(list,tuple)) or len(p)!=2:
        raise ValueError('Expected normalized xy point')
    return (number(p[0]),number(p[1]))


def _project(p,a,b,size):
    px,py = p[0]*size[0],p[1]*size[1]
    ax,ay = a[0]*size[0],a[1]*size[1]
    dx,dy = (b[0]-a[0])*size[0],(b[1]-a[1])*size[1]
    t = ((px-ax)*dx+(py-ay)*dy)/(dx*dx+dy*dy)
    q = (a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1]))
    return t, math.hypot((q[0]-p[0])*size[0],(q[1]-p[1])*size[1])


def _intersection(a,b,c,d):
    dx,dy = b[0]-a[0],b[1]-a[1]
    ex,ey = d[0]-c[0],d[1]-c[1]
    den = dx*ey-dy*ex
    if abs(den)<1e-15:
        return None
    t = ((c[0]-a[0])*ey-(c[1]-a[1])*ex)/den
    u = ((c[0]-a[0])*dy-(c[1]-a[1])*dx)/den
    if -1e-10 <= t <= 1+1e-10 and -1e-10 <= u <= 1+1e-10:
        return (a[0]+t*dx,a[1]+t*dy)
    return None


def build_graph(segments, ports, junctions, *, page_sizes, tolerance_points=.25, gap_points=3.):
    collection(segments,limit=1000); collection(ports,limit=2000); collection(junctions,limit=500)
    number(tolerance_points,.001,1.); number(gap_points,tolerance_points,12.)
    segs = []
    for s in segments:
        pg = page(s['page']); a,b = point(s['a']),point(s['b'])
        if a==b:
            raise ValueError('Zero-length segment')
        if pg not in page_sizes:
            raise ValueError('Missing page dimensions')
        size = page_sizes[pg]
        number(size[0],1,20000); number(size[1],1,20000)
        if s.get('line_kind') not in ('PROCESS','SIGNAL','UNKNOWN'):
            raise ValueError('Unrecognised line kind')
        segs.append({**s,'a':a,'b':b})
    for r in ports+junctions:
        page(r['page']); point(r['point'])
        if r['page'] not in page_sizes or not r.get('evidence_ids'):
            raise ValueError('Port/junction needs page frame and source evidence')
    # Explicit junction evidence must identify a line kind. Unknown evidence
    # cannot connect process and signal strokes.
    for j in junctions:
        if j.get('line_kind') not in KNOWN:
            raise ValueError('Junction needs a known stroke kind')
    cuts = {s['id']:[(0.,s['a'],None),(1.,s['b'],None)] for s in segs}
    for j in junctions:
        for s in segs:
            if s['page']!=j['page'] or s['line_kind']!=j['line_kind']:
                continue
            t,dist = _project(point(j['point']),s['a'],s['b'],page_sizes[s['page']])
            if 0<=t<=1 and dist<=tolerance_points:
                # Shared point is the actual explicit junction coordinate.
                cuts[s['id']].append((t,point(j['point']),j['id']))
    if sum(len(v) for v in cuts.values())>20000:
        raise ValueError('Junction split budget exceeded; divide the page into smaller inputs')
    contacts = []; overlapping=set(); contact_truncated=False
    for i,s in enumerate(segs):
        for q in segs[i+1:]:
            if s['page']!=q['page']:
                continue
            p = _intersection(s['a'],s['b'],q['a'],q['b'])
            if p is None:
                # Positive-length collinear overlaps are duplicate/ambiguous
                # line evidence, never two confidently independent pipes.
                ta,da=_project(q['a'],s['a'],s['b'],page_sizes[s['page']])
                tb,db=_project(q['b'],s['a'],s['b'],page_sizes[s['page']])
                if da<=1e-7 and db<=1e-7 and min(1.,max(ta,tb))-max(0.,min(ta,tb))>1e-9:
                    overlapping.update((s['id'],q['id']))
                    if len(contacts)<5000:
                        contacts.append({'id':ident('overlap',s['id'],q['id']),'page':s['page'],
                                         'segment_ids':[s['id'],q['id']],'state':'COLLINEAR_OVERLAP_UNRESOLVED',
                                         'review_state':STATE})
                    else:contact_truncated=True
                continue
            if len(contacts)>=5000:
                contact_truncated=True;continue
            matching = [j for j in junctions if j['page']==s['page'] and
                        j['line_kind']==s['line_kind']==q['line_kind'] and
                        math.hypot((p[0]-j['point'][0])*page_sizes[s['page']][0],
                                   (p[1]-j['point'][1])*page_sizes[s['page']][1])<=tolerance_points]
            endpoints = all(any(math.dist(p,x)<1e-9 for x in (z['a'],z['b'])) for z in (s,q))
            contacts.append({'id':ident('contact',s['id'],q['id'],p), 'page':s['page'],'point':p,
                             'segment_ids':[s['id'],q['id']],
                             'state':'EXPLICIT_JUNCTION_PROPOSED' if matching else 'ENDPOINT_CONTACT_PROPOSED' if endpoints else 'CROSSING_OR_T_UNRESOLVED',
                             'junction_ids':[j['id'] for j in matching], 'review_state':STATE})
    # Cluster only exact endpoint coordinates. Near misses are listed below.
    endpoints = defaultdict(set)
    for s in segs:
        for t,p,jid in cuts[s['id']]:
            endpoints[(s['page'],s['line_kind'],round(p[0],9),round(p[1],9))].add(s['id'])
    nodes, edges, node_data = {}, [], {}
    for s in sorted(segs,key=lambda x:x['id']):
        ordered = sorted(cuts[s['id']],key=lambda c:(c[0],c[2] or ''))
        # If a junction lies on an endpoint, prefer its explicit identity.
        unique = []
        for item in ordered:
            if unique and abs(item[0]-unique[-1][0])<1e-9:
                if item[2]: unique[-1]=item
            else:
                unique.append(item)
        chain = []
        for t,p,jid in unique:
            key = (s['page'],s['line_kind'],round(p[0],9),round(p[1],9))
            degree = len(endpoints[key])
            # Three or more incident segments need explicit junction evidence.
            discriminator = jid or (s['id'] if s['line_kind']=='UNKNOWN' or degree>2 or s['id'] in overlapping else 'endpoint')
            nid = ident('node',key,discriminator)
            nodes[nid] = {'id':nid,'page':s['page'],'point':p,'line_kind':s['line_kind'],
                          'junction_id':jid,'state':'GEOMETRY_NODE_PROPOSED','review_state':STATE}
            chain.append(nid)
            node_data[nid] = (p,s['page'],s['line_kind'])
        for a,b in zip(chain,chain[1:]):
            if a!=b:
                edges.append({'id':ident('edge',s['id'],a,b),'a':a,'b':b,'segment_id':s['id'],
                              'page':s['page'],'line_kind':s['line_kind'],'review_state':STATE})
    by_id={s['id']:s for s in segs}
    for contact in contacts:
        if contact['state']!='ENDPOINT_CONTACT_PROPOSED':continue
        incident=[by_id[x] for x in contact['segment_ids']]
        kinds={s['line_kind'] for s in incident}
        p=contact['point']
        if len(kinds)!=1 or 'UNKNOWN' in kinds:
            contact['state']='LINE_KIND_UNRESOLVED'
        elif any(len(endpoints[(s['page'],s['line_kind'],round(p[0],9),round(p[1],9))])>2 for s in incident):
            contact['state']='JUNCTION_EVIDENCE_REQUIRED'
    # Physical gap candidates only; no speculative joining across broken scans.
    gaps = []
    nitems = sorted(node_data.items())
    for i,(aid,(a,pg,kind)) in enumerate(nitems):
        if len(gaps)>=2000: break
        for bid,(b,bpg,bkind) in nitems[i+1:]:
            if pg!=bpg or kind!=bkind or kind=='UNKNOWN': continue
            size = page_sizes[pg]
            dist = math.hypot((a[0]-b[0])*size[0],(a[1]-b[1])*size[1])
            if 1e-7 < dist <= gap_points:
                gaps.append({'id':ident('gap',aid,bid),'a':aid,'b':bid,'gap_points':dist,
                             'state':'GAP_UNRESOLVED','review_state':STATE})
                if len(gaps)>=2000: break
    attachments = []
    for port in ports:
        compatible = []
        for nid,(p,pg,kind) in node_data.items():
            if pg!=port['page'] or kind!=port.get('line_kind') or kind=='UNKNOWN': continue
            size=page_sizes[pg]
            dist=math.hypot((p[0]-port['point'][0])*size[0],(p[1]-port['point'][1])*size[1])
            if dist<=tolerance_points: compatible.append(nid)
        attachments.append({'id':ident('port-contact',port['id'],sorted(compatible)),
                            'port_id':port['id'], 'symbol_id':port['symbol_id'], 'node_options':sorted(compatible),
                            'node_id':compatible[0] if len(compatible)==1 else None,
                            'state':'PORT_CONTACT_PROPOSED' if len(compatible)==1 else 'PORT_UNRESOLVED',
                            'review_state':STATE})
    return {'nodes':sorted(nodes.values(),key=lambda n:n['id']),'edges':edges,'contacts':contacts,
            'gaps':gaps,'port_attachments':attachments,'gap_budget_reached':len(gaps)>=2000,
            'contact_budget_reached':contact_truncated,
            'notice':'Geometry proposals only; no accepted plant connectivity or inferred flow direction.'}
