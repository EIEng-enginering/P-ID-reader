"""Evidence-only vector geometry inspection for standalone projects.

This is NOT a physical piping graph.  An intersection of ink is not proof of
an engineering connection; analysis cannot determine the actual plant state.
The frozen Worksheet R1 extraction API and JSON are intentionally untouched.
"""
from __future__ import annotations

from collections import defaultdict
from io import BytesIO
from math import floor, hypot, isfinite
from typing import Any

from ..api import CancelToken, LimitExceeded, RefusedInput, canonical_json, sha256_hex, stable_id

ALGORITHM_VERSION = "vector-topology-0.3-bounded-index"
TOUCH_TOLERANCE_PT = 1.5
# Standalone limits. Keep the Worksheet R1 contract entirely unchanged.
# 20k observed strokes are allowed, but all contacts must still be covered;
# analyses that cannot be completed within bounded budgets fail explicitly.
MAX_SEGMENTS = 20000
MAX_CANDIDATES = 12000
MAX_GRID_MEMBERSHIPS = 500000
MAX_PAIRS_EVALUATED = 600000
MAX_TOPOLOGY_BYTES = 8 * 1024 * 1024
GRID_PT = 64.0


def _point(p: Any, width: float, height: float) -> list[float]:
    x, y = float(p[0]), float(p[1])
    if not (isfinite(x) and isfinite(y)):
        raise RefusedInput("PID_MALFORMED", "Invalid vector coordinates")
    return [round(max(0., min(1., x / width)), 7), round(max(0., min(1., y / height)), 7)]


def _cross(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0]*b[1]-a[1]*b[0]


def _difference(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return a[0]-b[0], a[1]-b[1]


def _within_end(value: float, length: float, tolerance: float) -> bool:
    return min(abs(value), abs(1-value))*length <= tolerance


def _segment_contact(a: dict, b: dict, tol: float = TOUCH_TOLERANCE_PT) -> tuple[str, tuple[float, float]] | None:
    """Geometric intersection only; never returns a plant connection.

    Computes point intersection, endpoint/interior conditions and collinear
    overlap.  Near misses are intentionally not bridged automatically.
    """
    p, p2 = a["raw_pts"]
    q, q2 = b["raw_pts"]
    r = _difference(p2, p)
    s = _difference(q2, q)
    lr = hypot(*r)
    ls = hypot(*s)
    if min(lr, ls) <= 0.00001:
        return None
    delta = _difference(q, p)
    denominator = _cross(r, s)
    epsilon = 1e-8 * max(lr*ls, 1.0)
    if abs(denominator) <= epsilon:
        if abs(_cross(delta, r)) > tol*lr:
            return None
        # Overlap of collinear strokes in the parameter of the first stroke.
        denominator_a = lr*lr
        u0 = (delta[0]*r[0] + delta[1]*r[1])/denominator_a
        q2diff = _difference(q2, p)
        u1 = (q2diff[0]*r[0]+q2diff[1]*r[1])/denominator_a
        lo, hi = max(0.0, min(u0, u1)), min(1.0, max(u0, u1))
        if hi < lo:
            return None
        midpoint = (lo+hi)/2
        point = (p[0]+r[0]*midpoint, p[1]+r[1]*midpoint)
        if (hi-lo)*lr <= tol:
            return ("ENDPOINT_TOUCH_CANDIDATE", point)
        return ("COLLINEAR_OVERLAP_AMBIGUOUS", point)
    t = _cross(delta, s)/denominator
    u = _cross(delta, r)/denominator
    if not (0 <= t <= 1 and 0 <= u <= 1):
        # No invented line joins across gaps, even if they look plausible.
        return None
    point = (p[0]+t*r[0], p[1]+t*r[1])
    a_end = _within_end(t, lr, tol)
    b_end = _within_end(u, ls, tol)
    if a_end and b_end:
        return ("ENDPOINT_TOUCH_CANDIDATE", point)
    if a_end or b_end:
        return ("BRANCH_TEE_AMBIGUOUS", point)
    return ("CROSSING_AMBIGUOUS", point)


def _bbox_at(point: list[float], width: float, height: float, radius_pt: float = 4.0) -> dict:
    dx, dy = radius_pt/width, radius_pt/height
    x, y = point
    return {"x0": round(max(0., x-dx), 7), "y0": round(max(0., y-dy), 7),
            "x1": round(min(1., x+dx), 7), "y1": round(min(1., y+dy), 7)}


def analyze_pdf_topology(pdf_bytes: bytes, *, pages: tuple[int, ...] | None = None,
                         cancel: CancelToken | None = None) -> dict:
    """Return reproducible standalone vector observations + ambiguous contacts.

    Scanned pages report no native geometry.  No physical topology or safety
    function is inferred.  This is separate from the frozen R1 host payload.
    """
    try:
        import pdfplumber
        from pypdf import PdfReader
    except ImportError as exc:
        raise RefusedInput("PID_DEPENDENCY_MISSING", "PDF parser dependency unavailable") from exc
    if not isinstance(pdf_bytes, bytes) or not pdf_bytes.startswith(b"%PDF-"):
        raise RefusedInput("PID_MALFORMED", "Expected PDF bytes")
    if len(pdf_bytes) > 16*1024*1024:
        raise LimitExceeded("PID_LIMIT_BYTES", "Standalone topology input exceeds the initial safety limit")
    try:
        probe = PdfReader(BytesIO(pdf_bytes), strict=False)
        if probe.is_encrypted:
            raise RefusedInput("PID_ENCRYPTED", "Encrypted PDF refused")
        count = len(probe.pages)
        if not 1 <= count <= 500:
            raise LimitExceeded("PID_LIMIT_PAGES", "PDF page limit exceeded or no pages")
    except (RefusedInput, LimitExceeded):
        raise
    except Exception as exc:
        raise RefusedInput("PID_MALFORMED", "Unreadable PDF") from exc
    selected = tuple(range(1,count+1)) if pages is None else tuple(pages)
    if not selected or len(selected)!=len(set(selected)) or any(type(i) is not int or not 1 <= i <= count for i in selected):
        raise RefusedInput("PID_BAD_PARAMETER", "Unique valid page numbers required")
    result: dict = {"schema": "pid-reader-standalone-topology-v1", "algorithm": ALGORITHM_VERSION,
                    "source_sha256": sha256_hex(pdf_bytes), "page_count": count,
                    "selected_pages": list(selected), "segments": [], "contact_candidates": [],
                    "shape_candidates": [], "warnings": [],
                    "disclaimer": "Geometric observations only; no physical piping or instrument connectivity confirmed."}
    per_page: dict[int,list[dict]] = defaultdict(list)
    shape_repeats: dict[tuple, int] = defaultdict(int)

    def shape_id(page_number: int, bbox: dict, kind: str) -> str:
        """Id of an outline. The first drawn copy keeps the id it always had; an identical outline drawn again (overprint, duplicated
        object) gets its occurrence number added, so two outlines never share an id."""
        key = (page_number, bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"], kind)
        n = shape_repeats[key]
        shape_repeats[key] += 1
        if n == 0:
            return stable_id("shape", result["source_sha256"], page_number, bbox, kind)
        return stable_id("shape", result["source_sha256"], page_number, bbox, kind, n)
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for page_number in selected:
                if cancel: cancel.check()
                page = pdf.pages[page_number-1]
                width, height = float(page.width),float(page.height)
                if not (0 < width*height < 1e9):
                    raise LimitExceeded("PID_LIMIT_GEOMETRY", "Page dimensions are unsupported")
                for index, raw in enumerate(page.lines):
                    if cancel and index%32==0: cancel.check()
                    pts = raw.get("pts")
                    if not isinstance(pts, list) or len(pts)!=2:
                        continue
                    first, last = tuple(map(float, pts[0])), tuple(map(float,pts[1]))
                    if not all(isfinite(v) for v in (*first,*last)):
                        raise RefusedInput("PID_MALFORMED", "Non-finite stroke coordinates")
                    if hypot(last[0]-first[0],last[1]-first[1]) < 2.:
                        continue
                    norm = [_point(first,width,height),_point(last,width,height)]
                    dash = raw.get("dash") or ([],0)
                    style = "DASHED_OR_DOTTED" if dash[0] else "SOLID_OR_UNKNOWN"
                    rid = stable_id("stroke", result["source_sha256"],page_number,index,sorted(norm),style)
                    seg = {"id":rid,"page":page_number,"endpoints":norm,"style":style,
                           "line_width_pt":round(float(raw.get("linewidth") or 0),3),
                           "status":"PROPOSED_GEOMETRY"}
                    seg["raw_pts"]=[first,last]
                    per_page[page_number].append(seg)
                    result["segments"].append({k:v for k,v in seg.items() if k!="raw_pts"})
                    if len(result["segments"]) > MAX_SEGMENTS:
                        raise LimitExceeded("PID_LIMIT_GEOMETRY", "Too many native vector segments for this analyzer")
                # Preserve geometric evidence of circular outlines, without
                # claiming that they are instrument symbols.
                for index, curve in enumerate(page.curves):
                    if cancel and index%32==0: cancel.check()
                    pts = curve.get("pts") or []
                    if len(pts) < 4 or not isinstance(pts[0],(tuple,list)):
                        continue
                    x0,y0,x1,y1=(float(curve[k]) for k in ("x0","top","x1","bottom"))
                    w,h=x1-x0,y1-y0
                    if min(w,h)<7 or max(w,h)/min(w,h)>1.25:
                        continue
                    if hypot(float(pts[0][0])-float(pts[-1][0]),float(pts[0][1])-float(pts[-1][1]))>2:
                        continue
                    bbox = {"x0":round(x0/width,7),"y0":round(y0/height,7),
                            "x1":round(x1/width,7),"y1":round(y1/height,7)}
                    cid = shape_id(page_number, bbox, "CLOSED_CURVE")
                    result["shape_candidates"].append({"id":cid,"page":page_number,
                        "shape":"CLOSED_NEAR_CIRCULAR_OUTLINE", "bbox":bbox,
                        "status":"PROPOSED_GEOMETRY",
                        "limitation":"May be instrument bubble, symbol, drafting feature or unrelated circle."})
                # Closed rectangular outlines, e.g. vessels, title blocks, frames,
                # boxes and P&ID legend elements. Do not assume an equipment type.
                for index, rect in enumerate(page.rects):
                    if cancel and index % 32 == 0:
                        cancel.check()
                    x0, y0, x1, y1 = (float(rect[k]) for k in ("x0", "top", "x1", "bottom"))
                    rw, rh = x1 - x0, y1 - y0
                    if rw < 9 or rh < 9 or rw * rh > 0.8 * width * height:
                        continue
                    bbox = {"x0":round(max(0.,x0/width),7), "y0":round(max(0.,y0/height),7),
                            "x1":round(min(1.,x1/width),7), "y1":round(min(1.,y1/height),7)}
                    if bbox["x0"]>=bbox["x1"] or bbox["y0"]>=bbox["y1"]:
                        continue
                    sid=shape_id(page_number, bbox, "RECTANGULAR_OUTLINE")
                    result["shape_candidates"].append({"id":sid,"page":page_number,
                        "shape":"RECTANGULAR_OUTLINE","bbox":bbox,"status":"PROPOSED_GEOMETRY",
                        "limitation":"Rectangle may be equipment, drawing border, legend or annotation; unclassified."})
                    if len(result["shape_candidates"]) > MAX_CANDIDATES:
                        raise LimitExceeded("PID_LIMIT_GEOMETRY", "Too many geometric outline candidates")
                if not per_page[page_number]:
                    result["warnings"].append({"page":page_number,"code":"NO_STRAIGHT_VECTOR_STROKES",
                                               "message":"No supported straight line segments extracted; raster or curves may remain unread."})
                # Memory-bounded streaming spatial index, in original stroke order.
                # Each pair is tested once against strokes seen earlier; unlike
                # the original code this does not allocate a giant global pair set.
                # If any work budget is hit we REFUSE the whole analysis rather
                # than discard contacts or claim complete coverage.
                segment_list = per_page[page_number]
                grid: dict[tuple[int, int], list[int]] = defaultdict(list)
                grid_memberships = 0
                pair_count = 0
                for i, seg in enumerate(segment_list):
                    if cancel and i % 32 == 0:
                        cancel.check()
                    p, q = seg["raw_pts"]
                    xlo, xhi = sorted((p[0], q[0]))
                    ylo, yhi = sorted((p[1], q[1]))
                    ixlo = floor((xlo - TOUCH_TOLERANCE_PT) / GRID_PT)
                    ixhi = floor((xhi + TOUCH_TOLERANCE_PT) / GRID_PT)
                    iylo = floor((ylo - TOUCH_TOLERANCE_PT) / GRID_PT)
                    iyhi = floor((yhi + TOUCH_TOLERANCE_PT) / GRID_PT)
                    tile_count = (ixhi - ixlo + 1) * (iyhi - iylo + 1)
                    if tile_count > 2000 or grid_memberships + tile_count > MAX_GRID_MEMBERSHIPS:
                        raise LimitExceeded("PID_LIMIT_GEOMETRY", "Geometry spatial index work budget exceeded; contact coverage is unavailable")
                    cells = [(x, y) for x in range(ixlo, ixhi + 1)
                            for y in range(iylo, iyhi + 1)]
                    prior: set[int] = set()
                    for cell in cells:
                        prior.update(grid[cell])
                    for j in sorted(prior):
                        pair_count += 1
                        if pair_count > MAX_PAIRS_EVALUATED:
                            raise LimitExceeded("PID_LIMIT_GEOMETRY", "Geometry candidate-pair work budget exceeded; contact coverage is unavailable")
                        if cancel and pair_count % 128 == 0:
                            cancel.check()
                        left, right = segment_list[j], seg
                        contact = _segment_contact(left, right)
                        if contact is None:
                            continue
                        kind, raw_pt = contact
                        point = _point(raw_pt, width, height)
                        members = sorted([left["id"], right["id"]])
                        cid = stable_id("contact", result["source_sha256"], page_number,
                                        members, kind, point)
                        result["contact_candidates"].append({
                            "id": cid, "page": page_number, "kind": kind,
                            "point": point, "bbox": _bbox_at(point, width, height),
                            "segment_ids": members, "status": "UNRESOLVED",
                            "limitation": "Graphical contact is not confirmed process or signal connectivity."
                        })
                        if len(result["contact_candidates"]) > MAX_CANDIDATES:
                            raise LimitExceeded("PID_LIMIT_GEOMETRY", "Too many geometric contact candidates; no partial result was returned")
                    for cell in cells:
                        grid[cell].append(i)
                    grid_memberships += tile_count
    except (RefusedInput, LimitExceeded):
        raise
    except Exception as exc:
        raise RefusedInput("PID_MALFORMED", "Standalone geometry inspection failed") from exc
    for key in ("segments","contact_candidates","shape_candidates"):
        result[key].sort(key=lambda x:(x["page"],x["id"]))
    result["warnings"].sort(key=lambda x:(x["page"],x["code"]))
    result["result_sha256"] = sha256_hex(canonical_json(result).encode("utf-8"))
    if len(canonical_json(result).encode("utf-8")) > MAX_TOPOLOGY_BYTES:
        raise LimitExceeded("PID_LIMIT_GEOMETRY", "Geometry result exceeds 8 MiB; no incomplete result was returned")
    return result


def verify_topology_result(result: dict) -> bool:
    if not isinstance(result,dict):return False
    digest=result.get("result_sha256")
    if not isinstance(digest,str) or len(digest)!=64:return False
    body={k:v for k,v in result.items() if k!="result_sha256"}
    return sha256_hex(canonical_json(body).encode("utf-8"))==digest

CONTACT_TYPES = frozenset({"ENDPOINT_TOUCH_CANDIDATE", "BRANCH_TEE_AMBIGUOUS",
                           "CROSSING_AMBIGUOUS", "COLLINEAR_OVERLAP_AMBIGUOUS"})


def validate_topology_result(result: dict) -> list[str]:
    """Validate the separate standalone geometry contract without a new dependency.

    Cryptographic hashing checks accidental alteration; it is not an
    authenticity signature or independent correctness assessment.
    """
    errors=[]
    if not verify_topology_result(result):
        return ["Invalid or missing topology content hash"]
    if result.get("schema")!="pid-reader-standalone-topology-v1":
        errors.append("Unexpected standalone topology schema")
    if result.get("algorithm") not in ("vector-topology-0.2", ALGORITHM_VERSION):
        errors.append("Unsupported topology algorithm version")
    digest=result.get("source_sha256")
    if not isinstance(digest,str) or len(digest)!=64 or any(c not in "0123456789abcdef" for c in digest):
        errors.append("Invalid document SHA-256")
    page_count=result.get("page_count")
    selected=result.get("selected_pages")
    count_valid=type(page_count) is int and 1<=page_count<=500
    if not count_valid:
        errors.append("Invalid document page count")
    if not isinstance(selected,list) or not selected or not count_valid or any(type(p) is not int or p<1 or p>page_count for p in selected) or len(set(selected))!=len(selected):
        errors.append("Selected page list is invalid")
    selected_set=set(selected) if isinstance(selected,list) and all(type(p) is int for p in selected) else set()
    segments=result.get("segments")
    contacts=result.get("contact_candidates")
    shapes=result.get("shape_candidates")
    if not isinstance(segments,list) or not isinstance(contacts,list) or not isinstance(shapes,list):
        return errors+["Segments, contact candidates and shape candidates must be arrays"]
    if len(segments)>MAX_SEGMENTS or len(contacts)>MAX_CANDIDATES:
        errors.append("Geometry result exceeds per-analysis budget")
    def norm_point(pt):
        return isinstance(pt,list) and len(pt)==2 and all(type(v) in (float,int) and isfinite(v) and 0<=v<=1 for v in pt)
    seg_index={}
    for seg in segments:
        if not isinstance(seg,dict) or not isinstance(seg.get("id"),str) or not isinstance(seg.get("page"),int) or seg.get("page") not in selected_set:
            errors.append("Invalid segment ID or source page");continue
        if seg["id"] in seg_index:
            errors.append("Duplicate segment identifier")
        seg_index[seg["id"]]=seg["page"]
        if not isinstance(seg.get("endpoints"),list) or len(seg["endpoints"])!=2 or not all(norm_point(p) for p in seg["endpoints"]):
            errors.append("Segment endpoints not normalized")
        if seg.get("status")!="PROPOSED_GEOMETRY":
            errors.append("Invalid geometry status")
    seen=set()
    for c in contacts:
        if not isinstance(c,dict) or not isinstance(c.get("id"),str):
            errors.append("Invalid contact candidate");continue
        if c["id"] in seen:errors.append("Duplicate contact identifier")
        seen.add(c["id"])
        if c.get("kind") not in CONTACT_TYPES or c.get("status")!="UNRESOLVED":
            errors.append("Contact is not an unresolved supported geometric proposal")
        if not norm_point(c.get("point")):
            errors.append("Contact position outside page")
        members=c.get("segment_ids")
        if not isinstance(members,list) or len(members)!=2 or members[0]==members[1] or any(seg_index.get(v)!=c.get("page") for v in members):
            errors.append("Contact references missing or cross-page segments")
        box=c.get("bbox")
        if not isinstance(box,dict) or any(k not in box or not isinstance(box[k],(int,float)) or not isfinite(box[k]) for k in ("x0","x1","y0","y1")):
            errors.append("Contact bounding box invalid")
        elif not (0<=box["x0"]<box["x1"]<=1 and 0<=box["y0"]<box["y1"]<=1):
            errors.append("Contact bounding box outside page")
    for s in shapes:
        if not isinstance(s,dict) or s.get("page") not in selected_set or s.get("status")!="PROPOSED_GEOMETRY":
            errors.append("Shape source or status invalid")
    if len(canonical_json(result).encode("utf-8")) > MAX_TOPOLOGY_BYTES:
        errors.append("Geometry output exceeds 8 MiB")
    return errors
