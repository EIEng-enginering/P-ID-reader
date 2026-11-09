"""Cross-sheet and revision reconciliation (Rev X, WPU-11). Pure, deterministic, proposals only.

* Off-page connectors are read from text (``TO / FROM / CONT'D ON ... <drawing>``, optional line reference).
* A connector pair is a **match candidate** only with independent observations on *both* sheets: each sheet names the other drawing
  (reciprocal reference) plus a second compatible fact (same line reference, or complementary TO/FROM). A shared line/tag string alone is
  ``INSUFFICIENT``; equal strings with incompatible size or service are ``CONFLICTING`` and never merged.
* Occurrences on different sheets may be linked as ``PROPOSED_SAME_AS`` only with evidence beyond the tag; a bare tag match is reported
  as ``TAG_ONLY_NOT_MERGED``.
* Revision comparison keeps two questions apart: ``source_diff`` (the PDF bytes differ) and ``interpretation_diff`` (the reader/config differ).
  A change in an unchanged PDF is an interpretation change, never a drawing change.
* Review decisions made under another source or model generation are ``STALE`` and need reaffirmation.
"""
from __future__ import annotations

import hashlib
import json
import re

from .engineering_text import classify_text

VERSION = "crosssheet-v1"
_OFFPAGE = re.compile(r"\b(TO|FROM|CONT'?D\.?|CONTINUED|CONTINUATION)\b[^A-Z0-9]*(?:ON\s+)?(?:DWG\.?|DRAWING|P&ID|PID|SHEET)?\s*([A-Z0-9][A-Z0-9-]{3,})", re.I)
_LINE_REF = re.compile(r"\bLINE\s+([A-Z0-9][A-Z0-9-]*)\b", re.I)


def _id(prefix: str, *parts) -> str:
    return prefix + "-" + hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:20]


def _norm_drawing(ref: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (ref or "").upper())


def find_offpage_connectors(lines: list[dict], sheet_id: str, own_drawing_ref: str | None) -> list[dict]:
    """Connectors from text lines ``{text, bbox, page, word_ids}``. Needs a TO/FROM/CONT'D cue and a drawing-like target."""
    out = []
    for ln in lines:
        text = ln["text"].strip()
        m = _OFFPAGE.search(text)
        if not m:
            continue
        direction = "TO" if m.group(1).upper() == "TO" else "FROM" if m.group(1).upper() == "FROM" else "CONTINUATION"
        target = m.group(2).upper()
        looks_like_drawing = classify_text(target)["primary"] == "DRAWING_REFERENCE" or (re.search(r"\d", target) and len(target) >= 5)
        if not looks_like_drawing:
            continue
        lr = _LINE_REF.search(text)
        out.append({"connector_id": _id("ocn", sheet_id, ln["page"], ln["bbox"], text), "sheet_id": sheet_id, "page": ln["page"],
                    "text": text, "direction": direction, "target_drawing": target, "line_ref": lr.group(1).upper() if lr else None,
                    "own_drawing": own_drawing_ref, "bbox": ln["bbox"], "word_ids": ln.get("word_ids", []),
                    "attributes": ln.get("attributes", {}), "truth_class": "DIRECT_OBSERVATION", "review_state": "PROPOSED_UNVERIFIED"})
    return out


def _complementary(a: str, b: str) -> bool:
    return {a, b} == {"TO", "FROM"}


def match_connectors(sheets: list[dict], connectors: list[dict]) -> dict:
    """Candidate matches between connectors of different sheets. ``sheets``: ``{sheet_id, drawing_ref}``."""
    connectors = sorted(connectors, key=lambda c: (c["sheet_id"], c["connector_id"]))            # canonical pair order: input order never matters
    ref_of = {s["sheet_id"]: _norm_drawing(s.get("drawing_ref")) for s in sheets}
    candidates, conflicts, insufficient = [], [], []
    for i, a in enumerate(connectors):
        for b in connectors[i + 1:]:
            if a["sheet_id"] == b["sheet_id"]:
                continue
            evidence = []
            if _norm_drawing(a["target_drawing"]) == ref_of.get(b["sheet_id"]) and _norm_drawing(b["target_drawing"]) == ref_of.get(a["sheet_id"]) and ref_of.get(a["sheet_id"]):
                evidence.append({"kind": "RECIPROCAL_DRAWING_REFERENCE", "sources": [a["connector_id"], b["connector_id"]]})
            line_equal = bool(a["line_ref"] and a["line_ref"] == b["line_ref"])
            if line_equal:
                evidence.append({"kind": "LINE_REFERENCE_EQUAL", "value": a["line_ref"], "sources": [a["connector_id"], b["connector_id"]]})
            if _complementary(a["direction"], b["direction"]):
                evidence.append({"kind": "DIRECTION_COMPLEMENTARY", "sources": [a["connector_id"], b["connector_id"]]})
            mism = [k for k in sorted(set(a["attributes"]) & set(b["attributes"])) if a["attributes"][k] != b["attributes"][k]]
            kinds = {e["kind"] for e in evidence}
            if "RECIPROCAL_DRAWING_REFERENCE" not in kinds:
                if line_equal:
                    insufficient.append({"connectors": [a["connector_id"], b["connector_id"]], "status": "INSUFFICIENT",
                                         "reason": "same line reference text only; the sheets do not name each other", "evidence": evidence})
                continue
            if mism:
                conflicts.append({"conflict_id": _id("xcf", a["connector_id"], b["connector_id"]), "kind": "OFFSHEET_ATTRIBUTE_CONFLICT",
                                  "connectors": [a["connector_id"], b["connector_id"]], "attributes": mism,
                                  "values": {k: [a["attributes"][k], b["attributes"][k]] for k in mism}, "status": "CONFLICTING",
                                  "note": "references agree but the drawn attributes disagree; not merged"})
                continue
            if len(kinds) >= 2:
                candidates.append({"match_id": _id("xmt", a["connector_id"], b["connector_id"]), "relation": "OFFPAGE_MATCH_CANDIDATE", "connectors": [a["connector_id"], b["connector_id"]],
                                   "sheets": [a["sheet_id"], b["sheet_id"]], "evidence": evidence, "evidence_kinds": sorted(kinds),
                                   "score": len(kinds), "status": "OFFPAGE_MATCH_CANDIDATE", "review_state": "PROPOSED_UNVERIFIED",
                                   "truth_class": "STRUCTURALLY_DERIVED", "note": "two independent observations; a reviewer must still confirm"})
            else:
                insufficient.append({"connectors": [a["connector_id"], b["connector_id"]], "status": "INSUFFICIENT",
                                     "reason": "only the reciprocal drawing reference; no second compatible fact", "evidence": evidence})
    by_conn: dict[str, list[dict]] = {}
    for c in candidates:
        for cid in c["connectors"]:
            by_conn.setdefault(cid, []).append(c)
    for c in candidates:
        rivals = {x["match_id"] for cid in c["connectors"] for x in by_conn[cid] if x["match_id"] != c["match_id"] and x["score"] >= c["score"]}
        c["ambiguous"] = bool(rivals)
        c["alternatives"] = sorted(rivals)
    candidates.sort(key=lambda c: c["match_id"])
    connected = {cid for c in candidates for cid in c["connectors"]}
    return {"candidates": candidates, "conflicts": sorted(conflicts, key=lambda c: c["conflict_id"]), "insufficient": insufficient,
            "unmatched_connectors": sorted(c["connector_id"] for c in connectors if c["connector_id"] not in connected)}


def propose_asset_identities(occurrences: list[dict]) -> dict:
    """Occurrences ``{occurrence_id, sheet_id, tag, entity_kind, engineering_class, corroboration:[...]}`` -> same-as proposals.

    ``corroboration`` is a list of independent fact names supplied by the caller (for example ``SAME_OFFPAGE_NEIGHBOUR``, ``SAME_ATTRIBUTE_VALUES``,
    ``DOCUMENT_REFERENCE``); the tag text itself never counts.
    """
    by_tag: dict[str, list[dict]] = {}
    for o in occurrences:
        if o.get("tag"):
            by_tag.setdefault(re.sub(r"[^A-Z0-9]", "", o["tag"].upper()), []).append(o)
    proposals, tag_only, conflicts = [], [], []
    for tag, group in sorted(by_tag.items()):
        sheets = {o["sheet_id"] for o in group}
        if len(sheets) < 2:
            continue
        kinds = {o["entity_kind"] for o in group}
        if len(kinds) > 1:
            conflicts.append({"conflict_id": _id("acf", tag, sorted(o["occurrence_id"] for o in group)), "kind": "SAME_TAG_DIFFERENT_KIND", "tag": tag,
                              "occurrences": sorted(o["occurrence_id"] for o in group), "kinds": sorted(kinds), "status": "CONFLICTING"})
            continue
        shared = set.intersection(*[set(o.get("corroboration", [])) for o in group]) if group else set()
        ids = sorted(o["occurrence_id"] for o in group)
        if shared:
            proposals.append({"proposal_id": _id("same", tag, ids), "relation": "PROPOSED_SAME_AS", "occurrences": ids, "tag": tag,
                              "evidence_beyond_tag": sorted(shared), "status": "PROPOSED_UNVERIFIED", "truth_class": "CONTEXTUAL_INFERENCE"})
        else:
            tag_only.append({"tag": tag, "occurrences": ids, "status": "TAG_ONLY_NOT_MERGED",
                             "note": "a tag string is an attribute, not identity; no independent evidence was supplied"})
    return {"proposals": proposals, "tag_only_not_merged": tag_only, "conflicts": conflicts}


def _key(o: dict) -> tuple:
    b = o["bbox"]
    return (o["page"], round((b["x0"] + b["x1"]) / 2 / 0.01), round((b["y0"] + b["y1"]) / 2 / 0.01), o.get("graphical_family") or o.get("entity_kind"))


def diff_interpretations(old: dict, new: dict) -> dict:
    """Compare two interpretation snapshots ``{source_sha256, model_generation, occurrences:[...]}``.

    Every difference is labelled by *why* it can exist; a PDF-identical pair never yields a drawing change.
    """
    same_source = old["source_sha256"] == new["source_sha256"]
    same_model = old.get("model_generation") == new.get("model_generation")
    a = {_key(o): o for o in old["occurrences"]}
    b = {_key(o): o for o in new["occurrences"]}
    added = [b[k] for k in sorted(b.keys() - a.keys(), key=str)]
    removed = [a[k] for k in sorted(a.keys() - b.keys(), key=str)]
    changed = [{"before": a[k], "after": b[k]} for k in sorted(a.keys() & b.keys(), key=str)
               if (a[k].get("engineering_class"), (a[k].get("tag") or {}).get("text") if isinstance(a[k].get("tag"), dict) else a[k].get("tag")) !=
               (b[k].get("engineering_class"), (b[k].get("tag") or {}).get("text") if isinstance(b[k].get("tag"), dict) else b[k].get("tag"))]
    if same_source:
        label = "INTERPRETATION_DIFF"
        note = "the PDF bytes are identical: every difference comes from the reader, its configuration or earlier review; none is a drawing change"
    elif same_model:
        label = "SOURCE_REVISION_CHANGE_CANDIDATE"
        note = "the PDF differs and the reader generation is the same; differences may reflect drawing changes (still unverified)"
    else:
        label = "SOURCE_AND_MODEL_CHANGE_MIXED"
        note = "both the PDF and the reader generation differ; differences cannot be attributed to the drawing alone"
    return {"source_diff": not same_source, "interpretation_diff": not same_model or (same_source and bool(added or removed or changed)),
            "label": label, "note": note, "drawing_change_asserted": False,
            "added": [o.get("id") or o.get("node_id") or o.get("occurrence_id") for o in added],
            "removed": [o.get("id") or o.get("node_id") or o.get("occurrence_id") for o in removed],
            "changed": [{"before": c["before"].get("id") or c["before"].get("node_id"), "after": c["after"].get("id") or c["after"].get("node_id")} for c in changed],
            "counts": {"added": len(added), "removed": len(removed), "changed": len(changed), "unchanged": len(a.keys() & b.keys()) - len(changed)}}


def flag_stale_reviews(db, extraction_id: str, current_model_generation: str | None = None) -> list[dict]:
    """Decisions made under another source hash or model generation, with the reason; shown, never silently reused."""
    from .intelligence_store import stale_decisions, _extraction_source_sha
    from .stage_telemetry import engine_version
    source_sha = _extraction_source_sha(db, extraction_id)
    gen = current_model_generation or engine_version()
    out = []
    for d in stale_decisions(db, extraction_id, gen):
        reasons = []
        if d["source_sha256"] != source_sha:
            reasons.append("SOURCE_CHANGED")
        if d["model_generation"] != gen:
            reasons.append("MODEL_CHANGED")
        out.append({**d, "state": "STALE", "reasons": reasons, "action": "reaffirm or revise against the current evidence"})
    return out


def reconcile_project(db, extraction_ids: list[str] | None = None, *, record: bool = True) -> dict:
    """Project-level pass over the stored drawings: off-page connectors, matches, identity proposals. Proposals only.

    Reads each drawing's source text again (no stage needed), uses its registered or printed drawing number, and the tagged occurrences of its latest
    analysis run. Two sheets joined by an off-page match candidate give their same-tag occurrences one weak corroboration
    (``SHARED_OFFPAGE_CONTEXT``); a tag alone never merges anything.
    """
    from .doc_text import _lines
    from .page_regions import profile_pages
    ids = extraction_ids if extraction_ids is not None else [r[0] for r in db.db.execute("SELECT extraction_id FROM extraction ORDER BY imported_utc, extraction_id")]
    if len(ids) < 1:
        raise ValueError("No drawings in the project")
    sheets, connectors, occ = [], [], []
    for eid in ids:
        ex = db.export_extraction(eid)
        src = db.get_source_pdf(ex["document"]["sha256"])
        if src is None:
            continue
        reg = db.db.execute("SELECT drawing_no FROM drawing_registration WHERE extraction_id=? ORDER BY rowid DESC LIMIT 1", (eid,)).fetchone()
        lines = []
        ref = reg["drawing_no"] if reg and reg["drawing_no"] else None
        for prof in profile_pages(src):
            words = [{"id": f"nat-{prof['page']}-{i}", "text": w["text"], "bbox": w["bbox"]} for i, w in enumerate(prof["words"])]
            for ln in _lines(words):
                lines.append({"text": ln["text"], "bbox": ln["bbox"], "page": prof["page"], "word_ids": ln["word_ids"]})
                if ref is None and re.search(r"DRAWING\s*NO", ln["text"], re.I):
                    cls = classify_text(ln["text"])
                    if any(m["kind"] == "DRAWING_REFERENCE" for m in cls["matches"]):
                        ref = re.search(r"\d{3,5}-\d{2}-[A-Z]{2}-\d{2}-\d{3}", ln["text"]).group(0)
        sheets.append({"sheet_id": eid, "drawing_ref": ref, "source_name": ex["document"]["filename"]})
        connectors += find_offpage_connectors(lines, eid, ref)
        from . import intelligence_store as istore
        run = istore.latest_run(db, eid)
        if run:
            kinds = {i["item_id"]: i for i in istore.list_items(db, run["run_id"], "OCCURRENCE")}
            for it in istore.list_items(db, run["run_id"], "ATTRIBUTE"):
                a = it.get("attribute", {})
                if a.get("field_name") == "TAG_ASSOCIATION" and a.get("occurrence_id") in kinds:
                    oc = kinds[a["occurrence_id"]]["occurrence"]
                    occ.append({"occurrence_id": a["occurrence_id"], "sheet_id": eid, "tag": a["verbatim"],
                                "entity_kind": {"VALVE": "VALVE", "INSTRUMENT": "INSTRUMENT", "EQUIPMENT": "EQUIPMENT"}.get(oc["graphical_family"], "OTHER"), "corroboration": []})
    result = match_connectors(sheets, connectors)
    joined = {frozenset(c["sheets"]) for c in result["candidates"]}
    for o in occ:
        if any(o["sheet_id"] in pair for pair in joined):
            o["corroboration"].append("SHARED_OFFPAGE_CONTEXT")
    by_pair_ok = {}
    for o in occ:                                                    # corroboration only counts when every copy of the tag sits on a joined sheet pair
        by_pair_ok.setdefault(re.sub(r"[^A-Z0-9]", "", o["tag"].upper()), []).append(o)
    for group in by_pair_ok.values():
        sheets_of = {o["sheet_id"] for o in group}
        if len(sheets_of) > 1 and not any(frozenset(p) <= sheets_of or (len(sheets_of) == 2 and frozenset(p) == frozenset(sheets_of)) for p in joined):
            for o in group:
                o["corroboration"] = []
    result["identity"] = propose_asset_identities(occ)
    result["sheets"] = sheets
    result["connectors"] = connectors
    result["run_id"] = record_crosssheet(db, ids[0], result) if record and (connectors or result["identity"]["proposals"] or result["identity"]["tag_only_not_merged"]) else None
    return result


def record_crosssheet(db, extraction_id: str, result: dict, *, config: dict | None = None) -> str:
    """Store cross-sheet proposals as a ``crosssheet`` run attached to one extraction (append-only; idempotent)."""
    from .intelligence_store import record_run
    from .stage_telemetry import make_outcome
    items = []
    for c in result.get("candidates", []):
        items.append({"item_id": c["match_id"], "item_kind": "RELATION", "tag_normalized": None, "page": None, "relation": c,
                      "truth_class": c["truth_class"], "review_state": c["review_state"], "evidence": c["evidence"]})
    for c in result.get("conflicts", []):
        items.append({"item_id": c["conflict_id"], "item_kind": "CONFLICT", "tag_normalized": None, "page": None, "conflict": c,
                      "truth_class": "CONFLICTING", "review_state": "NEEDS_REVIEW", "evidence": [c]})
    for p in result.get("identity", {}).get("proposals", []):
        items.append({"item_id": p["proposal_id"], "item_kind": "ASSET_HYPOTHESIS", "tag_normalized": p["tag"], "page": None, "asset": p,
                      "truth_class": p["truth_class"], "review_state": p["status"], "evidence": [{"evidence_beyond_tag": p["evidence_beyond_tag"]}]})
    outcome = make_outcome("crosssheet", "SUCCESS", candidates=len(items), config_sha256="", diagnostics={"version": VERSION})
    return record_run(db, extraction_id, preset="crosssheet", status="COMPLETE_CANDIDATES", outcomes=[outcome], items=items,
                      summary={"candidates": len(result.get("candidates", [])), "conflicts": len(result.get("conflicts", []))}, config=config or {"v": VERSION})
