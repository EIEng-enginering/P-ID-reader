"""Standalone evidence-linked symbol and port hypotheses, not plant validation.

Input consists ONLY of a verified Worksheet R1 reading and the separately
verified native-vector topology result for the SAME drawing and pages.
No model training, LLM calls or online dependencies are needed. A shape is never
silently equated with an equipment item on geometric proximity alone.
"""
from __future__ import annotations

from math import hypot, isfinite
from .topology import validate_topology_result
from ..api import canonical_json, sha256_hex, result_sha256, stable_id, RefusedInput, LimitExceeded

ALGORITHM = "vector-symbol-proposals-0.1"
SCHEMA = "pid-reader-standalone-symbols-v1"
MAX_SYMBOLS = 12000
MAX_PORTS = 24000


def _middle(box: dict) -> tuple[float, float]:
    return (box["x0"] + box["x1"])/2, (box["y0"] + box["y1"])/2


def _inside(xy: tuple[float, float], box: dict, pad: float = 0.0) -> bool:
    return box["x0"]-pad <= xy[0] <= box["x1"]+pad and box["y0"]-pad <= xy[1] <= box["y1"]+pad


def _at_boundary(xy: list[float], box: dict, shape_kind: str) -> bool:
    """Small normalized geometric proximity check; all coordinates are 0..1.

    Does not establish a real piping port, only a line endpoint near an outline.
    """
    w = box["x1"] - box["x0"]
    h = box["y1"] - box["y0"]
    tolerance = min(.003, max(.0008, min(w,h)*.09))
    x,y=xy
    if not _inside((x,y),box,tolerance):
        return False
    if shape_kind == "CLOSED_NEAR_CIRCULAR_OUTLINE":
        if w <= 0 or h <= 0:
            return False
        cx,cy=_middle(box)
        rho=hypot((x-cx)/(w/2),(y-cy)/(h/2))
        radial_tolerance = min(.28, max(.08, tolerance / max(min(w,h)/2,1e-8)))
        return abs(rho-1.0) <= radial_tolerance
    distance=min(abs(x-box["x0"]),abs(x-box["x1"]),abs(y-box["y0"]),abs(y-box["y1"]))
    return distance <= tolerance


def build_symbol_proposals(extraction: dict, topology: dict) -> dict:
    """Derive conservative candidate shapes, text associations and outline ports.

    These results have a separate schema, are not R1 IPL/SIF/plant claims, and
    deliberately DO NOT infer line continuity, valve state or equipment type
    from graphical context alone.
    """
    if not isinstance(extraction,dict) or extraction.get("schema_version") != 1:
        raise RefusedInput("PID_BAD_PARAMETER", "Versioned R1 extraction required")
    ex_hash = extraction.get("provenance",{}).get("result_sha256")
    if not isinstance(ex_hash,str) or ex_hash != result_sha256(extraction):
        raise RefusedInput("PID_BAD_PARAMETER", "Extraction hash verification failed")
    problems=validate_topology_result(topology)
    if problems:
        raise RefusedInput("PID_BAD_PARAMETER", "Topology result invalid: "+"; ".join(problems[:3]))
    document_sha = extraction.get("document",{}).get("sha256")
    if document_sha != topology.get("source_sha256"):
        raise RefusedInput("PID_SHA_MISMATCH", "Topology and extraction source hashes differ")
    allowed_pages = {p["page"] for p in extraction["pages"]}
    if not set(topology["selected_pages"]).issubset(allowed_pages):
        raise RefusedInput("PID_BAD_PARAMETER", "Topology includes pages outside extraction")

    tags_by_page: dict[int,list[dict]]={}
    for obj in extraction["objects"]:
        if obj.get("page") not in allowed_pages or not isinstance(obj.get("bbox"),dict):
            raise RefusedInput("PID_BAD_PARAMETER", "Extraction object page/geometry invalid")
        # Only real tag readings; NOTE annotations can still be reported separately.
        if obj.get("class") != "NOTE":
            tags_by_page.setdefault(obj["page"],[]).append(obj)
    seg_by_page: dict[int,list[dict]]={}
    for seg in topology["segments"]:
        seg_by_page.setdefault(seg["page"],[]).append(seg)
    proposals=[];ports=[]
    for shape in topology["shape_candidates"]:
        box=shape["bbox"]
        center=_middle(box)
        inside=[]
        for obj in tags_by_page.get(shape["page"],[]):
            if _inside(_middle(obj["bbox"]), box):
                inside.append(obj)
        inside.sort(key=lambda obj:obj["id"])
        text_ids=[obj["id"] for obj in inside]
        if len(inside)==1:
            selected=inside[0]
            if shape["shape"]=="CLOSED_NEAR_CIRCULAR_OUTLINE" and selected["class"]=="INSTRUMENT":
                kind="INSTRUMENT_BUBBLE_CANDIDATE"
            elif shape["shape"]=="RECTANGULAR_OUTLINE" and selected["class"] in {
                    "VESSEL","TANK","COLUMN","PUMP","COMPRESSOR","HEAT_EXCHANGER","FILTER"}:
                kind="EQUIPMENT_OUTLINE_CANDIDATE"
            else:
                kind="UNCLASSIFIED_OUTLINE"
            association="SINGLE_TEXT_CENTRE_OVERLAP"
        elif len(inside)>1:
            kind="AMBIGUOUS_OUTLINE"
            association="MULTIPLE_TEXT_CANDIDATES"
        else:
            kind="UNCLASSIFIED_OUTLINE"
            association="NO_TAG_CENTRE_OVERLAP"
        sid=stable_id("sym",document_sha,shape["page"],shape["id"],kind,text_ids)
        cand={"id":sid,"page":shape["page"],"shape_id":shape["id"],"outline_kind":shape["shape"],
              "candidate_class":kind,"bbox":box,"tag_object_ids":text_ids,
              "text_association":association,"status":"PROPOSED_UNVERIFIED",
              "evidence":{"shape_id":shape["id"],"tag_object_ids":text_ids},
              "limitations":"Drawing outline and tag proximity are not plant identity or verified symbol function."}
        proposals.append(cand)
        if len(proposals)>MAX_SYMBOLS:
            raise LimitExceeded("PID_LIMIT_GEOMETRY", "Too many symbol outline candidates")
        # Preserve only endpoint-near-outline hypotheses. Interior stroke crossings
        # do not create a port, and each candidate must link to observed ink.
        for seg in seg_by_page.get(shape["page"],[]):
            if seg.get("style")!="SOLID_OR_UNKNOWN":
                continue
            for n,point in enumerate(seg["endpoints"]):
                if _at_boundary(point,box,shape["shape"]):
                    pid=stable_id("port",document_sha,shape["id"],seg["id"],n,point)
                    ports.append({"id":pid,"page":shape["page"],"symbol_id":sid,
                        "segment_id":seg["id"],"segment_endpoint_index":n,"point":point,
                        "status":"PROPOSED_UNVERIFIED",
                        "limitations":"Line endpoint touches an outline; signal/process type and equipment port are not established."})
                    if len(ports)>MAX_PORTS:
                        raise LimitExceeded("PID_LIMIT_GEOMETRY", "Too many proposed outline port contacts")
    proposals.sort(key=lambda c:(c["page"],c["id"]))
    ports.sort(key=lambda c:(c["page"],c["id"]))
    body={"schema":SCHEMA,"algorithm":ALGORITHM,"source_sha256":document_sha,
          "extraction_sha256":ex_hash,"topology_sha256":topology["result_sha256"],
          "selected_pages":topology["selected_pages"],"symbol_candidates":proposals,
          "port_candidates":ports,"limitations":(
            "Only standalone vector-outline and text-centre evidence. No inferred physical equipment, "
            "piping connectivity, functional-safety attribution or instrument-loop approval.")}
    body["result_sha256"]=sha256_hex(canonical_json(body).encode("utf-8"))
    return body


def validate_symbol_proposals(result: dict, extraction: dict, topology: dict) -> list[str]:
    """Reject altered, dangling or inconsistent proposal sets before storage."""
    if not isinstance(result,dict):
        return ["Symbol analysis must be an object"]
    errors=[]
    payload={k:v for k,v in result.items() if k!="result_sha256"}
    try:
        digest=sha256_hex(canonical_json(payload).encode("utf-8"))
    except (TypeError,ValueError):
        return ["Symbol analysis cannot be canonically encoded"]
    if digest!=result.get("result_sha256"):
        errors.append("Symbol analysis content hash mismatch")
    if result.get("schema")!=SCHEMA or result.get("algorithm")!=ALGORITHM:
        errors.append("Unsupported symbol analysis version")
    if result.get("source_sha256")!=extraction.get("document",{}).get("sha256"):
        errors.append("Source document mismatch")
    if result.get("extraction_sha256")!=extraction.get("provenance",{}).get("result_sha256"):
        errors.append("Extraction evidence mismatch")
    if result.get("topology_sha256")!=topology.get("result_sha256"):
        errors.append("Topology evidence mismatch")
    if result.get("selected_pages")!=topology.get("selected_pages"):
        errors.append("Selected pages differ from topology")
    if not isinstance(result.get("symbol_candidates"),list) or not isinstance(result.get("port_candidates"),list):
        return errors+["Symbol and port candidate lists required"]
    if len(result["symbol_candidates"])>MAX_SYMBOLS or len(result["port_candidates"])>MAX_PORTS:
        errors.append("Symbol result exceeds budget")
    shape_ids={x["id"] for x in topology.get("shape_candidates",[])}
    tag_ids={x["id"] for x in extraction.get("objects",[])}
    seg_ids={x["id"] for x in topology.get("segments",[])}
    sym_ids={};used=set()
    for x in result["symbol_candidates"]:
        if not isinstance(x,dict):
            errors.append("Invalid symbol record");continue
        ident=x.get("id")
        if not isinstance(ident,str) or ident in used:
            errors.append("Duplicate/invalid symbol ID")
        used.add(ident)
        if x.get("shape_id") not in shape_ids:
            errors.append("Symbol lacks source shape")
        if x.get("candidate_class") not in {"INSTRUMENT_BUBBLE_CANDIDATE","EQUIPMENT_OUTLINE_CANDIDATE", "UNCLASSIFIED_OUTLINE","AMBIGUOUS_OUTLINE"}:
            errors.append("Unsupported proposed symbol class")
        if x.get("status")!="PROPOSED_UNVERIFIED":
            errors.append("Symbol was implicitly accepted")
        if not isinstance(x.get("tag_object_ids"),list) or any(t not in tag_ids for t in x.get("tag_object_ids",[])):
            errors.append("Symbol references missing text evidence")
        sym_ids[ident]=x.get("page")
    port_ids=set()
    for x in result["port_candidates"]:
        if not isinstance(x,dict):
            errors.append("Invalid port record");continue
        if x.get("id") in port_ids or not isinstance(x.get("id"),str):
            errors.append("Duplicate port candidate ID")
        port_ids.add(x.get("id"))
        if x.get("symbol_id") not in sym_ids or x.get("segment_id") not in seg_ids:
            errors.append("Port references missing symbol or segment")
        if x.get("status")!="PROPOSED_UNVERIFIED" or x.get("page")!=sym_ids.get(x.get("symbol_id")):
            errors.append("Port status/page mismatch")
        q=x.get("point")
        if not isinstance(q,list) or len(q)!=2 or any(type(v) not in (int,float) or not isfinite(v) or not 0<=v<=1 for v in q):
            errors.append("Port point is not normalized")
    # Rebuild the entire proposal set from immutable evidence. A caller cannot
    # forge a new symbol or port by changing a JSON field and recomputing SHA.
    if not errors:
        try:
            expected=build_symbol_proposals(extraction,topology)
            if expected != result:
                errors.append("Symbol or port hypotheses differ from source-derived algorithm output")
        except (RefusedInput,LimitExceeded,KeyError,TypeError,ValueError):
            errors.append("Symbol hypotheses cannot be reconstructed from source")
    return errors
