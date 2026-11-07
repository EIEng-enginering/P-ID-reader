"""Rev L standalone signal-style to outline hypotheses. Never a control-loop or IPL claim.

Only a dashed native stroke ending at a detected outline generates a candidate.
The outline and stroke must be on the same source page.  A crossing or a line
passing through the outline never produces a connection.  Review is explicit.
"""
from __future__ import annotations

from collections import defaultdict
from math import isfinite

from ..api import canonical_json, result_sha256, sha256_hex, stable_id
from .topology import validate_topology_result
from .symbols import validate_symbol_proposals, _at_boundary
from .linework import validate_linework_proposals

ALGORITHM = "signal-outline-hypotheses-0.1"
SCHEMA = "pid-reader-standalone-signal-links-v1"
MAX_CANDIDATES = 8000


def build_signal_links(extraction: dict, topology: dict, symbols: dict, linework: dict) -> dict:
    if extraction.get("schema_version") != 1 or result_sha256(extraction) != extraction.get("provenance",{}).get("result_sha256"):
        raise ValueError("Invalid source extraction hash")
    if validate_topology_result(topology) or validate_symbol_proposals(symbols, extraction, topology) or validate_linework_proposals(linework, extraction, topology, symbols):
        raise ValueError("Signal analysis requires complete, reproducible source evidence")
    digest = extraction["document"]["sha256"]
    if not digest == topology["source_sha256"] == symbols["source_sha256"] == linework["source_sha256"]:
        raise ValueError("Signal analysis contains inconsistent source revisions")
    outlines_by_page: dict[int,list[dict]] = defaultdict(list)
    for s in symbols["symbol_candidates"]:
        if s["candidate_class"] == "INSTRUMENT_BUBBLE_CANDIDATE":
            outlines_by_page[s["page"]].append(s)
    segments = {s["id"]:s for s in topology["segments"]}
    signal_roles = sorted((r for r in linework["stroke_roles"] if r["role"] == "SIGNAL_STYLE_CANDIDATE"),key=lambda r:r["id"])
    results=[]
    for role in signal_roles:
        segment=segments.get(role["segment_id"])
        if segment is None or segment["page"]!=role["page"] or segment["style"]!="DASHED_OR_DOTTED":
            raise ValueError("Signal line style has no matching geometric evidence")
        for endpoint_index,point in enumerate(segment["endpoints"]):
            matched=[]
            for outline in outlines_by_page[role["page"]]:
                if _at_boundary(point,outline["bbox"],outline["outline_kind"]):
                    matched.append(outline)
            # Distinct outlines touching the same point are kept as alternatives,
            # not silently resolved to the nearest one.
            for outline in matched:
                body={"id":stable_id("siglink",digest,role["id"],endpoint_index,outline["id"]),
                      "page":role["page"],"segment_id":segment["id"],
                      "segment_style":segment["style"],"endpoint_index":endpoint_index,
                      "point":point,"symbol_id":outline["id"],"symbol_bbox":outline["bbox"],
                      "candidate_kind":"SIGNAL_STYLE_ENDPOINT_TO_INSTRUMENT_OUTLINE",
                      "association_state":"ALTERNATIVE_OUTLINES" if len(matched)>1 else "ONE_OUTLINE",
                      "review_state":"PROPOSED_UNVERIFIED",
                      "limitations":"Dashed ink ends near an instrument-bubble outline as drawn. Signal service, loop, instrument function and actual plant connection remain unverified."}
                results.append(body)
                if len(results)>MAX_CANDIDATES:
                    raise ValueError("Signal candidate budget exceeded")
    results.sort(key=lambda x:(x["page"],x["id"]))
    body={"schema":SCHEMA,"algorithm":ALGORITHM,"source_sha256":digest,
          "extraction_sha256":extraction["provenance"]["result_sha256"],
          "topology_sha256":topology["result_sha256"],
          "symbol_sha256":symbols["result_sha256"],
          "linework_sha256":linework["result_sha256"],
          "candidates":results,
          "limitations":"Vector signal-style candidates only; not accepted instrument loops or proof of connected plant equipment."}
    body["result_sha256"]=sha256_hex(canonical_json(body).encode("utf-8"))
    return body


def validate_signal_links(result: dict, extraction: dict, topology: dict, symbols: dict, linework: dict) -> list[str]:
    """Validation cannot be bypassed by recomputing the content hash."""
    try:
        if not isinstance(result,dict) or result.get("schema") != SCHEMA:
            return ["Unrecognised signal analysis schema"]
        expected=build_signal_links(extraction,topology,symbols,linework)
        return [] if expected==result else ["Signal result differs from source-derived analysis"]
    except (ValueError,TypeError,KeyError,OverflowError):
        return ["Signal analysis cannot be reconstructed from verified evidence"]
