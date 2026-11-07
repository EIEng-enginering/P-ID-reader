"""Read-only drawing-ink graph with explicit proposal vs reviewed evidence.

Graph is composed of vector strokes and drawing junction decisions, NOT physical
pipe runs. Default traversal includes ONLY contacts a named reviewer judged
CONNECTED_AS_DRAWN. The optional proposals mode explicitly includes unresolved
contacts but excludes rejected/not-connected ones; neither mode verifies plant.
"""
from __future__ import annotations

from collections import defaultdict, deque

from ..api import RefusedInput
from .topology import validate_topology_result

MAX_HOPS = 80
MAX_NODES = 4000
MAX_EDGES = 12000


def trace_drawing_segments(topology: dict, linework: dict, geometry_reviews: dict[str,str],
                           start_segment_id: str, *, include_unreviewed: bool = False,
                           max_hops: int = 15) -> dict:
    """Return reachable source strokes and eligible evidence-linked contact edges.

    The caller must supply review state from the *same* geometry analysis. No
    valve is automatically traversed. A crossing remains unresolved until a
    human reviews that contact as connected on the drawing.
    """
    if validate_topology_result(topology):
        raise RefusedInput("PID_BAD_PARAMETER", "Cannot use invalid geometry evidence")
    if not isinstance(linework,dict) or linework.get("topology_sha256")!=topology.get("result_sha256"):
        raise RefusedInput("PID_BAD_PARAMETER", "Linework does not match geometry evidence")
    if linework.get("source_sha256")!=topology.get("source_sha256"):
        raise RefusedInput("PID_SHA_MISMATCH", "Linework source is different")
    if not isinstance(geometry_reviews,dict):
        raise RefusedInput("PID_BAD_PARAMETER", "Drawing review state must be a mapping")
    if type(max_hops) is not int or not 0<=max_hops<=MAX_HOPS:
        raise RefusedInput("PID_BAD_PARAMETER", "max_hops must be from 0 to 80")
    strokes={s["id"]:s for s in topology["segments"]}
    if start_segment_id not in strokes:
        raise RefusedInput("PID_BAD_PARAMETER", "Unknown starting stroke ID")
    roles={x["segment_id"]:x["role"] for x in linework.get("stroke_roles",[])}
    adjacency=defaultdict(list)
    permitted={"CONNECTED_AS_DRAWN","NOT_CONNECTED_AS_DRAWN","UNRESOLVED","REJECTED"}
    for contact in topology["contact_candidates"]:
        cid=contact["id"]
        review=geometry_reviews.get(cid,"UNREVIEWED")
        if review not in permitted | {"UNREVIEWED"}:
            raise RefusedInput("PID_BAD_PARAMETER", "Unexpected drawing review state")
        a,b=contact["segment_ids"]
        # Glyph contours are never treated as traversable pipes/signals.
        if roles.get(a)=="VALVE_GLYPH_STROKE" or roles.get(b)=="VALVE_GLYPH_STROKE":
            continue
        if review in {"NOT_CONNECTED_AS_DRAWN","REJECTED"}:
            continue
        if review!="CONNECTED_AS_DRAWN" and not include_unreviewed:
            continue
        state=("REVIEWED_CONNECTED_AS_DRAWN" if review=="CONNECTED_AS_DRAWN" else
               "UNREVIEWED_CONTACT_PROPOSAL")
        edge={"id":cid,"from_segment_id":a,"to_segment_id":b,
              "kind":contact["kind"],"page":contact["page"],
              "point":contact["point"],"state":state,
              "evidence_contact_id":cid,
              "limitations":"Drawing connectivity review only; no physical plant or process service verification."}
        adjacency[a].append((b,edge));adjacency[b].append((a,edge))
    for neighbors in adjacency.values():
        neighbors.sort(key=lambda item:(item[0],item[1]["id"]))
    visited={start_segment_id:0};edges={};queue=deque([start_segment_id])
    while queue:
        current=queue.popleft()
        if visited[current]>=max_hops:
            continue
        for target,edge in adjacency[current]:
            edges[edge["id"]]=edge
            if target not in visited:
                visited[target]=visited[current]+1
                queue.append(target)
            if len(edges)>MAX_EDGES or len(visited)>MAX_NODES:
                raise RefusedInput("PID_LIMIT_GEOMETRY", "Drawing graph result budget exceeded")
    nodes=[{"segment_id":sid,"page":strokes[sid]["page"],"endpoints":strokes[sid]["endpoints"],
            "drawing_style":strokes[sid]["style"],"role":roles.get(sid,"UNKNOWN"),
            "hops_from_start":visited[sid]} for sid in sorted(visited)]
    return {"kind":"SOURCE_DRAWING_STROKE_GRAPH","source_sha256":topology["source_sha256"],
            "topology_sha256":topology["result_sha256"],
            "linework_sha256":linework["result_sha256"],
            "start_segment_id":start_segment_id,"include_unreviewed":bool(include_unreviewed),
            "max_hops":max_hops,"nodes":nodes,"edges":sorted(edges.values(),key=lambda e:e["id"]),
            "limitations":("Graph of drawn vector strokes only. Reviewed means connected AS DRAWN, "
                           "not a confirmed physical piping/signal network; valve glyphs cannot be traversed.")}
