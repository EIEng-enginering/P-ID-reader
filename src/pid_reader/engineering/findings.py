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

LAYERS = ("symbols", "linework", "catalogue", "text_links", "geometry", "signals")

LAYER_TITLES = {
    "symbols": "Outline symbols", "linework": "Valves / line styles",
    "catalogue": "Template matches", "text_links": "Tag ↔ symbol links",
    "geometry": "Line contacts", "signals": "Signal-style strokes",
}

# Decisions each store method accepts.
DECISIONS = {
    "symbols": ("ACCEPTED_AS_READING", "REJECTED", "UNRESOLVED"),
    "linework": ("ACCEPTED_AS_READING", "REJECTED", "UNRESOLVED"),
    "catalogue": ("ACCEPTED_AS_READING", "REJECTED", "UNRESOLVED"),
    "text_links": ("ACCEPTED_AS_READING", "EDITED_AND_ACCEPTED", "REJECTED", "UNRESOLVED"),
    "geometry": ("CONNECTED_AS_DRAWN", "NOT_CONNECTED_AS_DRAWN", "UNRESOLVED", "REJECTED"),
    "signals": ("SUPPORTED_AS_DRAWN", "NOT_CONNECTED_AS_DRAWN", "UNRESOLVED", "REJECTED"),
}


def latest_analysis_ids(db, extraction_id: str) -> dict[str, str]:
    """Newest stored analysis id of each layer for a drawing (empty if none)."""
    q = {
        "geometry": "geometry_analysis", "symbols": "symbol_analysis", "linework": "linework_analysis",
        "catalogue": "catalog_analysis", "signals": "signal_analysis", "ocr": "ocr_analysis",
        "text_links": "text_link_analysis",
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
