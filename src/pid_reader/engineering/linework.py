"""Standalone valve-glyph and vector line-style observations (not an engineering design).

This module does not modify the Worksheet R1 extraction JSON. It deliberately
cannot conclude a valve's function, fail action, piping service, physical
connectivity, process direction, loop independence, IPL credit or SIL.

The current detector recognises ONLY the six-stroke, symmetric bow-tie glyph
used in the supplied synthetic vector drawings. Other symbols remain unknown.
"""
from __future__ import annotations

from collections import defaultdict
from math import floor, hypot

from ..api import LimitExceeded, RefusedInput, canonical_json, result_sha256, sha256_hex, stable_id
from .topology import validate_topology_result
from .symbols import validate_symbol_proposals

SCHEMA = "pid-reader-standalone-linework-v1"
ALGORITHM = "vector-linework-proposals-0.1"
MAX_VALVES = 1500
MAX_STROKE_ROLES = 4000
MAX_PORTS = 3000
MAX_MIXED_CONTACTS = 12000
TOL = .0025  # normalized drawing coordinates; needs scale-dependent calibration


def _close(a: tuple[float, float], b: tuple[float, float], tol: float = TOL) -> bool:
    return hypot(a[0] - b[0], a[1] - b[1]) <= tol


def _segments(topology: dict) -> dict[int, list[dict]]:
    result: dict[int, list[dict]] = defaultdict(list)
    for seg in topology["segments"]:
        item = {"id": seg["id"], "page": seg["page"], "style": seg["style"],
                "p": tuple(seg["endpoints"][0]), "q": tuple(seg["endpoints"][1])}
        result[item["page"]].append(item)
    return result


def _find_base(segments: list[dict], a: tuple[float, float], b: tuple[float, float], excluded: set[str]) -> dict | None:
    found = [s for s in segments if s["id"] not in excluded and s["style"] == "SOLID_OR_UNKNOWN"
             and ((_close(s["p"], a) and _close(s["q"], b)) or
                  (_close(s["p"], b) and _close(s["q"], a)))]
    return found[0] if len(found) == 1 else None


def _candidate_valves(page: int, segments: list[dict], doc_hash: str) -> list[dict]:
    """Conservative signature: four spokes meeting at a point + two complete side rails.

    Never classify an arbitrary X crossing as a valve. The two complete rails
    are required, and extra/competing spokes at the centre reject the candidate.
    """
    solids = [s for s in segments if s["style"] == "SOLID_OR_UNKNOWN"]
    # Candidate centre = segment endpoint; repeated centres are not counted twice.
    potential_centres: dict[tuple[float, float], tuple[float, float]] = {}
    for s in solids:
        dx, dy = s["q"][0] - s["p"][0], s["q"][1] - s["p"][1]
        if abs(dx) < .005 or abs(dy) < .005 or abs(dx) > .12 or abs(dy) > .12:
            continue
        for point in (s["p"], s["q"]):
            key = (round(point[0], 3), round(point[1], 3))
            potential_centres.setdefault(key, point)
    # Endpoint spatial bins avoid a quadratic all-strokes scan on dense pages.
    def bucket(point: tuple[float,float]) -> tuple[int,int]:
        return (floor(point[0]/TOL),floor(point[1]/TOL))
    nearby: dict[tuple[int,int],list[tuple[dict,tuple[float,float],tuple[float,float]]]] = defaultdict(list)
    for stroke in solids:
        nearby[bucket(stroke["p"])].append((stroke,stroke["p"],stroke["q"]))
        nearby[bucket(stroke["q"])].append((stroke,stroke["q"],stroke["p"]))
    valves = []
    seen_sets: set[tuple[str, ...]] = set()
    for centre in potential_centres.values():
        spokes: dict[str, list[tuple[dict, tuple[float, float]]]] = defaultdict(list)
        bx,by=bucket(centre)
        for x in range(bx-1,bx+2):
            for y in range(by-1,by+2):
                for s,near,other in nearby.get((x,y),()):
                    if not _close(near,centre):
                        continue
                    dx, dy = other[0] - centre[0], other[1] - centre[1]
                    if not (.005 <= abs(dx) <= .12 and .005 <= abs(dy) <= .12):
                        continue
                    quadrant = ("L" if dx < 0 else "R") + ("U" if dy < 0 else "D")
                    spokes[quadrant].append((s, other))
        if any(len(spokes.get(k, [])) != 1 for k in ("LU", "LD", "RU", "RD")):
            continue
        ul, ll, ur, lr = (spokes[k][0] for k in ("LU", "LD", "RU", "RD"))
        outer = [ul[1], ll[1], ur[1], lr[1]]
        left_x = (ul[1][0] + ll[1][0]) / 2
        right_x = (ur[1][0] + lr[1][0]) / 2
        top_y = (ul[1][1] + ur[1][1]) / 2
        bottom_y = (ll[1][1] + lr[1][1]) / 2
        halfwidth = (right_x - left_x) / 2
        halfheight = (bottom_y - top_y) / 2
        if not (.005 <= halfwidth <= .12 and .005 <= halfheight <= .12):
            continue
        if abs((left_x + right_x)/2 - centre[0]) > TOL or abs((top_y + bottom_y)/2 - centre[1]) > TOL:
            continue
        if not (.3 <= halfwidth / halfheight <= 7):
            continue
        core_ids = {ul[0]["id"], ll[0]["id"], ur[0]["id"], lr[0]["id"]}
        # Flow left-right: two vertical side rails. Flow up-down: horizontal rails.
        rails = None
        orientation = None
        for possibility, coords in (
            ("HORIZONTAL_AXIS", ((ul[1],ll[1]),(ur[1],lr[1]))),
            ("VERTICAL_AXIS", ((ul[1],ur[1]),(ll[1],lr[1]))),
        ):
            a = _find_base(solids, coords[0][0], coords[0][1], core_ids)
            b = _find_base(solids, coords[1][0], coords[1][1], core_ids)
            if a and b and a["id"] != b["id"]:
                rails, orientation = (a,b), possibility
                break
        if rails is None:
            continue
        ids = sorted(core_ids | {rails[0]["id"], rails[1]["id"]})
        if len(ids) != 6 or tuple(ids) in seen_sets:
            continue
        seen_sets.add(tuple(ids))
        bbox = {"x0": round(min(p[0] for p in outer),7),
                "y0": round(min(p[1] for p in outer),7),
                "x1": round(max(p[0] for p in outer),7),
                "y1": round(max(p[1] for p in outer),7)}
        vid = stable_id("vshape", doc_hash, page, ids, orientation)
        valve = {"id":vid,"page":page,"kind":"BOWTIE_VALVE_GEOMETRY_CANDIDATE",
                 "orientation":orientation,"centre":[round(v,7) for v in centre],
                 "bbox":bbox,"evidence_segment_ids":ids,
                 "status":"PROPOSED_UNVERIFIED", "limitations":
                 "Six-stroke bow-tie shape only: not a verified valve, valve type, position or process connection."}
        valves.append(valve)
        if len(valves) > MAX_VALVES:
            raise LimitExceeded("PID_LIMIT_GEOMETRY", "Too many valve outline proposals")
    return sorted(valves, key=lambda v:(v["page"],v["id"]))


def _valve_endpoints(valve: dict, segments: list[dict], glyph_segments: set[str], doc_hash: str) -> list[dict]:
    bbox = valve["bbox"]
    cx,cy = valve["centre"]
    if valve["orientation"] == "HORIZONTAL_AXIS":
        locations = (("LEFT",(bbox["x0"],cy)), ("RIGHT",(bbox["x1"],cy)))
    else:
        locations = (("TOP",(cx,bbox["y0"])), ("BOTTOM",(cx,bbox["y1"])))
    ports=[]
    for side, target in locations:
        matches=[]
        for seg in segments:
            if seg["id"] in glyph_segments or seg["style"]!="SOLID_OR_UNKNOWN":
                continue
            for endpoint_num, (point, other) in enumerate(((seg["p"],seg["q"]),(seg["q"],seg["p"]))):
                if not _close(point,target):
                    continue
                # A real outer stub must extend away from this specific side.
                dx,dy=other[0]-point[0],other[1]-point[1]
                if side == "LEFT" and dx >= -.005:continue
                if side == "RIGHT" and dx <= .005:continue
                if side == "TOP" and dy >= -.005:continue
                if side == "BOTTOM" and dy <= .005:continue
                if side in ("LEFT","RIGHT") and abs(dy) > .003:continue
                if side in ("TOP","BOTTOM") and abs(dx) > .003:continue
                matches.append((seg, endpoint_num))
        if len(matches) != 1:
            continue  # Multiple stubs are ambiguous; do not pick arbitrarily.
        seg, endpoint_num=matches[0]
        portid=stable_id("vport",doc_hash,valve["id"],side,seg["id"],endpoint_num)
        ports.append({"id":portid,"page":valve["page"],"valve_id":valve["id"],
                      "side":side,"segment_id":seg["id"],"endpoint_index":endpoint_num,
                      "point":[round(v,7) for v in target],"status":"PROPOSED_UNVERIFIED",
                      "limitations":"Line endpoint appears at a glyph side. Does not establish a connected process line or a functioning valve."})
    return ports


def build_linework_proposals(extraction: dict, topology: dict, symbols: dict) -> dict:
    """Build evidence-linked, separately versioned line/valve hypotheses."""
    if not isinstance(extraction,dict) or extraction.get("schema_version")!=1:
        raise RefusedInput("PID_BAD_PARAMETER", "R1 extraction is required")
    if extraction.get("provenance",{}).get("result_sha256") != result_sha256(extraction):
        raise RefusedInput("PID_BAD_PARAMETER", "Extraction hash does not match its contents")
    if validate_topology_result(topology):
        raise RefusedInput("PID_BAD_PARAMETER", "Topology result cannot be verified")
    if validate_symbol_proposals(symbols,extraction,topology):
        raise RefusedInput("PID_BAD_PARAMETER", "Symbol proposals cannot be verified")
    digest=extraction["document"]["sha256"]
    if digest != topology["source_sha256"] or digest != symbols["source_sha256"]:
        raise RefusedInput("PID_SHA_MISMATCH", "Source evidence differs between analyses")
    groups=_segments(topology)
    valves=[]; ports=[]; roles=[]; mixed_contacts=[]
    for page in sorted(groups):
        strokes=groups[page]
        found=_candidate_valves(page,strokes,digest)
        valves.extend(found)
        used={sid for v in found for sid in v["evidence_segment_ids"]}
        for valve in found:
            ports.extend(_valve_endpoints(valve,strokes,used,digest))
        for stroke in strokes:
            role=("VALVE_GLYPH_STROKE" if stroke["id"] in used else
                  "SIGNAL_STYLE_CANDIDATE" if stroke["style"]=="DASHED_OR_DOTTED" else
                  "SOLID_UNCLASSIFIED_LINEWORK")
            roles.append({"id":stable_id("role",digest,stroke["id"],role),
                          "page":page,"segment_id":stroke["id"],"drawing_style":stroke["style"],
                          "role":role,"status":"PROPOSED_UNVERIFIED",
                          "limitations":"Line styling is graphical evidence, not a verified piping/signal service."})
    role_by_id={x["segment_id"]:x["role"] for x in roles}
    for contact in topology["contact_candidates"]:
        a,b=contact["segment_ids"]
        left,right=role_by_id[a],role_by_id[b]
        if left!=right:
            mixed_contacts.append({"id":stable_id("style-contact",digest,contact["id"],left,right),
                "page":contact["page"],"contact_id":contact["id"],"roles":[left,right],
                "status":"UNRESOLVED","limitations":
                "Cross-style graphical contact is not proof of process/signal connectivity."})
    if len(roles)>MAX_STROKE_ROLES or len(valves)>MAX_VALVES or len(ports)>MAX_PORTS or len(mixed_contacts)>MAX_MIXED_CONTACTS:
        raise LimitExceeded("PID_LIMIT_GEOMETRY", "Linework candidate budget exceeded")
    for collection in (valves,ports,roles,mixed_contacts):
        collection.sort(key=lambda x:(x["page"],x["id"]))
    body={"schema":SCHEMA,"algorithm":ALGORITHM,"source_sha256":digest,
          "extraction_sha256":extraction["provenance"]["result_sha256"],
          "topology_sha256":topology["result_sha256"],
          "symbol_sha256":symbols["result_sha256"],
          "selected_pages":topology["selected_pages"],
          "valve_candidates":valves,"valve_port_candidates":ports,
          "stroke_roles":roles,"mixed_style_contacts":mixed_contacts,
          "limitations":"Valve geometry, line styles and contact hypotheses only. No functional valve class, piping service, instrument loop, plant state, IPL or SIL is verified."}
    body["result_sha256"]=sha256_hex(canonical_json(body).encode("utf-8"))
    return body


def validate_linework_proposals(result: dict, extraction: dict, topology: dict, symbols: dict) -> list[str]:
    """Recompute from original evidence to detect re-hashed forged candidates."""
    if not isinstance(result,dict):
        return ["Linework result must be an object"]
    try:
        body={k:v for k,v in result.items() if k!="result_sha256"}
        digest=sha256_hex(canonical_json(body).encode("utf-8"))
        if digest != result.get("result_sha256"):
            return ["Linework content hash mismatch"]
        if result.get("schema")!=SCHEMA or result.get("algorithm")!=ALGORITHM:
            return ["Unsupported linework analysis version"]
        expected=build_linework_proposals(extraction,topology,symbols)
        return [] if result==expected else ["Linework proposals differ from source-derived algorithm output"]
    except (RefusedInput,LimitExceeded,KeyError,TypeError,ValueError,OverflowError):
        return ["Cannot reconstruct linework from verified evidence"]
