"""Uniform, Qt-free view over every analysis layer for review and display.

A *finding* is one proposal from one layer (symbol outline, valve shape,
catalogue template match, tag/symbol link, geometry contact, signal-style
stroke) with its source page/box and latest human review. This module only
reads and dispatches review calls to the existing audited store methods; it
never creates acceptance by itself.
"""
from __future__ import annotations

import json
from typing import Any

LAYERS = ("symbols", "linework", "catalogue", "text_links", "geometry", "signals", "raster", "raster_network", "raster_centrelines", "examples")

LAYER_TITLES = {
    "symbols": "Outline symbols", "linework": "Valves / line styles",
    "catalogue": "Template matches", "text_links": "Tag ↔ symbol links",
    "geometry": "Line contacts", "signals": "Signal-style strokes",
    "raster": "Filled and outlined raster valve proposals",
    "raster_network": "Raster contacts (unresolved until drawing review)",
    "raster_centrelines": "Raster centreline gap proposals",
    "examples": "Taught-symbol matches (look-alikes)",
}

# Decisions each store method accepts.
DECISIONS = {
    "symbols": ("ACCEPTED_AS_READING", "REJECTED", "UNRESOLVED"),
    "linework": ("ACCEPTED_AS_READING", "REJECTED", "UNRESOLVED"),
    "catalogue": ("ACCEPTED_AS_READING", "REJECTED", "UNRESOLVED"),
    "text_links": ("ACCEPTED_AS_READING", "EDITED_AND_ACCEPTED", "REJECTED", "UNRESOLVED"),
    "geometry": ("CONNECTED_AS_DRAWN", "NOT_CONNECTED_AS_DRAWN", "UNRESOLVED", "REJECTED"),
    "signals": ("SUPPORTED_AS_DRAWN", "NOT_CONNECTED_AS_DRAWN", "UNRESOLVED", "REJECTED"),
    "raster": ("ACCEPTED_AS_READING", "REJECTED", "UNRESOLVED"),
    "raster_network": ("CONTACT_AS_DRAWN", "NOT_CONTACT_AS_DRAWN", "UNRESOLVED", "REJECTED"),
    "raster_centrelines": ("CONTINUOUS_AS_DRAWN", "SEPARATE_AS_DRAWN", "UNRESOLVED", "REJECTED"),
    "examples": ("ACCEPTED_AS_READING", "REJECTED", "UNRESOLVED"),
}


# The store caps how many rows each layer will return per call; ask for no more than that.
MAX_ROWS = {"raster": 1000, "raster_network": 1000, "raster_centrelines": 3500}


def latest_analysis_ids(db, extraction_id: str) -> dict[str, str]:
    """Newest stored analysis id of each layer for a drawing (empty if none)."""
    q = {
        "geometry": "geometry_analysis", "symbols": "symbol_analysis", "linework": "linework_analysis",
        "catalogue": "catalog_analysis", "signals": "signal_analysis", "ocr": "ocr_analysis",
        "text_links": "text_link_analysis", "raster": "raster_analysis",
        "raster_network": "raster_network_analysis",
        "raster_centrelines": "raster_centreline_analysis",
    }
    out = {}
    for layer, table in q.items():
        row = db.db.execute(f"SELECT analysis_id FROM {table} WHERE extraction_id=? ORDER BY rowid DESC LIMIT 1",
                            (extraction_id,)).fetchone()
        if row:
            out[layer] = row[0]
    return out


def _decision(row: dict | None) -> str:
    return row["decision"] if row else "PROPOSED"


def _box(candidate: dict) -> dict | None:
    for key in ("bbox",):
        if isinstance(candidate.get(key), dict):
            return candidate[key]
    geom = candidate.get("geometry")
    if isinstance(geom, dict) and isinstance(geom.get("bbox"), dict):
        return geom["bbox"]
    return None


def list_findings(db, extraction_id: str, layer: str, *, limit: int = 500) -> list[dict]:
    """Findings of one layer: ``{layer, id, page, bbox, kind, label, state, detail}``."""
    if layer not in LAYERS:
        raise ValueError("Unknown analysis layer")
    limit = min(limit, MAX_ROWS.get(layer, 2000))
    if layer == "examples":
        from .examples import latest_example_review, list_example_candidates
        return [{"layer": layer, "id": c["candidate_id"], "page": c["page"], "bbox": c["bbox"], "kind": c["class_hint"],
                 "label": f"{c['label']} (similarity {c['score']:.2f})",
                 "state": _decision(latest_example_review(db, c["candidate_id"])), "detail": c}
                for c in list_example_candidates(db, extraction_id, limit=limit)]
    ids = latest_analysis_ids(db, extraction_id)
    if layer not in ids:
        return []
    aid = ids[layer]
    out: list[dict[str, Any]] = []
    if layer == "symbols":
        for c in db.list_symbol_candidates(aid, limit=limit):
            cand = c.get("candidate") or json.loads(c["candidate_json"])
            out.append({"layer": layer, "id": c["candidate_id"], "page": c["page"], "bbox": _box(cand),
                        "kind": c["candidate_class"], "label": c["candidate_class"].replace("_", " ").title(),
                        "state": _decision(db.latest_symbol_review(c["candidate_id"])), "detail": cand})
    elif layer == "linework":
        for c in db.list_linework_candidates(aid, limit=limit):
            cand = c["candidate"]
            out.append({"layer": layer, "id": c["candidate_id"], "page": c["page"], "bbox": _box(cand),
                        "kind": c["kind"], "label": c["kind"].replace("_", " ").title(),
                        "state": _decision(db.latest_linework_review(c["candidate_id"])), "detail": cand})
    elif layer == "catalogue":
        for c in db.list_catalogue_candidates(aid, limit=limit):
            cand = c.get("candidate") or json.loads(c["candidate_json"])
            out.append({"layer": layer, "id": c["candidate_id"], "page": c["page"], "bbox": _box(cand),
                        "kind": c["candidate_class"], "label": c["candidate_class"].replace("_", " ").title(),
                        "state": _decision(db.latest_catalogue_review(c["candidate_id"])), "detail": cand})
    elif layer == "text_links":
        for c in db.list_text_link_proposals(aid, limit=limit):
            p = c["proposal"]
            texts = [o["text_candidate"] for o in p["options"]]
            out.append({"layer": layer, "id": c["proposal_id"], "page": c["page"], "bbox": _box(p),
                        "kind": p["association_state"],
                        "label": ", ".join(texts) if texts else "(no text found)",
                        "state": _decision(db.latest_text_link_review(c["proposal_id"])), "detail": p})
    elif layer == "geometry":
        for c in db.list_geometry_candidates(aid, limit=limit):
            g = c["geometry"]
            out.append({"layer": layer, "id": c["candidate_id"], "page": c["page"], "bbox": _box(c),
                        "kind": c["kind"], "label": c["kind"].replace("_", " ").title(),
                        "state": _decision(db.latest_geometry_decision(c["candidate_id"])), "detail": g})
    elif layer == "raster":
        for c in db.list_raster_valves(aid, limit=limit):
            cand = c["candidate"]
            out.append({"layer": layer, "id": c["candidate_id"], "page": c["page"],
                        "bbox": _box(cand), "kind": cand["kind"],
                        "label": ("Unverified raster outlined-bowtie glyph" if cand["kind"].startswith("OUTLINED")
                                  else "Unverified raster filled-bowtie glyph"),
                        "state": _decision(db.latest_raster_review(c["candidate_id"])),
                        "detail": cand})
    elif layer == 'raster_network':
        for c in db.list_raster_network_contacts(aid,limit=limit):
            cand=c['candidate'];at=cand['point']
            out.append({'layer':layer,'id':c['candidate_id'],'page':c['page'],
                        'bbox':{'x0':max(0.,at[0]-.004),'y0':max(0.,at[1]-.004),
                                'x1':min(1.,at[0]+.004),'y1':min(1.,at[1]+.004)},
                        'kind':cand['kind'],'label':cand['kind'].replace('_',' ').title(),
                        'state':_decision(db.latest_raster_network_review(c['candidate_id'])),
                        'detail':cand})
    elif layer == 'raster_centrelines':
        for c in db.list_raster_centreline_gaps(aid,limit=min(limit,3500)):
            cand=c['candidate'];at=cand['point']
            out.append({'layer':layer,'id':c['candidate_id'],'page':c['page'],
                        'bbox':{'x0':max(0.,at[0]-.004),'y0':max(0.,at[1]-.004),
                                'x1':min(1.,at[0]+.004),'y1':min(1.,at[1]+.004)},
                        'kind':'COLLINEAR_GAP_UNRESOLVED',
                        'label':f"Possible {cand['gap_px']} px raster gap",
                        'state':_decision(db.latest_raster_centreline_review(c['candidate_id'])),
                        'detail':cand})
    elif layer == "signals":
        for c in db.list_signal_candidates(aid, limit=limit):
            cand = c.get("candidate") or json.loads(c["candidate_json"])
            out.append({"layer": layer, "id": c["candidate_id"], "page": c.get("page", 1), "bbox": _box(cand),
                        "kind": cand.get("kind", "SIGNAL_STYLE"), "label": "Signal-style stroke → outline",
                        "state": _decision(db.latest_signal_review(c["candidate_id"])), "detail": cand})
    return out


def review_finding(db, layer: str, finding_id: str, *, actor: str, decision: str, reason: str,
                   selected_text: str | None = None) -> str:
    """Dispatch to the audited review method for the layer (named reviewer, reason)."""
    if layer not in LAYERS:
        raise ValueError("Unknown analysis layer")
    if decision not in DECISIONS[layer]:
        raise ValueError(f"Decision {decision} is not valid for {layer}")
    if layer == "symbols":
        return db.review_symbol(finding_id, actor=actor, decision=decision, reason=reason)
    if layer == "linework":
        return db.review_linework(finding_id, actor=actor, decision=decision, reason=reason)
    if layer == "catalogue":
        return db.review_catalogue_candidate(finding_id, actor=actor, decision=decision, reason=reason)
    if layer == "text_links":
        return db.review_text_link(finding_id, actor=actor, decision=decision, reason=reason,
                                   selected_text=selected_text)
    if layer == "examples":
        from .examples import review_example_match
        return review_example_match(db, finding_id, actor=actor, decision=decision, reason=reason)
    if layer == "raster":
        return db.review_raster_valve(finding_id, actor=actor, decision=decision, reason=reason)
    if layer == 'raster_centrelines':
        return db.review_raster_centreline_gap(finding_id,actor=actor,decision=decision,reason=reason)
    if layer == 'raster_network':
        return db.review_raster_network_contact(finding_id,actor=actor,decision=decision,reason=reason)
    if layer == "geometry":
        return db.review_geometry(finding_id, actor=actor, decision=decision, reason=reason)
    return db.review_signal(finding_id, actor=actor, decision=decision, reason=reason)


def finding_counts(db, extraction_id: str) -> dict[str, dict[str, int]]:
    """{layer: {total, reviewed}} for a dashboard summary."""
    out = {}
    for layer in LAYERS:
        items = list_findings(db, extraction_id, layer, limit=2000)
        out[layer] = {"total": len(items), "reviewed": sum(i["state"] != "PROPOSED" for i in items)}
    return out
