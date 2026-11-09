"""Engineering-intelligence snapshot and AI package export (Rev X, WPU-14). Standalone; not the frozen Worksheet R1.

``build_snapshot`` turns one stored analysis run into a document that validates against
``contracts/engineering_intelligence_v1.schema.json`` (no field is invented: what the reader did not find stays absent or ``UNKNOWN``).
``export_package`` writes the context-efficient package -- manifest, overview, registers, per-page graphs, evidence, quality, summary and
the AI prompt -- only into a folder the user chose, never overwriting (``NAME (2)`` folders), chunked with an index, formula-safe CSV.

Everything is a drawing-based proposal. The narrative is generated from the data and links each claim to evidence ids; it cannot say more
than the data does, and it never asserts verification, flow, safe isolation, or any safety credit.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from . import intelligence_store as istore
from .ai_prompt import PROMPT
from .drawing_export import safe_stem
from .stage_telemetry import engine_version

VERSION = "intelligence-export-v1"
SCHEMA_ID = "engineering-intelligence-v1"
def _contract_path(name: str) -> Path:
    """Schema file in the source tree, or in the bundle of a frozen (PyInstaller) build."""
    import sys
    for base in (Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "_MEIPASS", None) else None, Path(__file__).resolve().parents[3]):
        if base is not None and (base / "contracts" / name).is_file():
            return base / "contracts" / name
    return Path(__file__).resolve().parents[3] / "contracts" / name


SCHEMA_PATH = _contract_path("engineering_intelligence_v1.schema.json")
MAX_EVIDENCE_PER_FILE = 4000
FULL = {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
_ENTITY_BY_FAMILY = {"VALVE": "VALVE", "ACTUATOR": "VALVE_ACTUATOR", "INSTRUMENT": "INSTRUMENT", "EQUIPMENT": "EQUIPMENT"}
_PORT_KIND = {"INSTRUMENT_PORT": "OTHER"}
_REL_TYPE = {"MEASURED_VALUE_TO_CONTROLLER": "OTHER"}
_NUMERIC = {"SETPOINT", "DESIGN", "OPERATING", "RATING", "SIZE", "RANGE", "UNKNOWN", "NOT_NUMERIC"}
_DIRECTION = {"FROM_TO": "UNIDIRECTIONAL", "TO_FROM": "UNIDIRECTIONAL", "UNKNOWN": "UNKNOWN", "CONFLICTING": "UNKNOWN"}


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _box(b) -> dict:
    if isinstance(b, dict) and all(k in b for k in ("x0", "y0", "x1", "y1")):
        return {k: round(min(1.0, max(0.0, float(b[k]))), 6) for k in ("x0", "y0", "x1", "y1")}
    return dict(FULL)


def _union(boxes: list[dict]) -> dict:
    boxes = [b for b in boxes if b]
    if not boxes:
        return dict(FULL)
    return {"x0": min(b["x0"] for b in boxes), "y0": min(b["y0"] for b in boxes), "x1": max(b["x1"] for b in boxes), "y1": max(b["y1"] for b in boxes)}


def _level(item: dict) -> str:
    return item.get("truth_class") if item.get("truth_class") in ("DIRECT_OBSERVATION", "STRUCTURALLY_DERIVED", "CONTEXTUAL_INFERENCE", "CONFLICTING", "UNKNOWN") else "UNKNOWN"


def _review_state(db, item: dict, extraction_id: str, source_sha: str, generation: str) -> str:
    state = item.get("review_state") or "PROPOSED_UNVERIFIED"
    if state not in ("PROPOSED_UNVERIFIED", "ACCEPTED_AS_READING", "REJECTED", "IGNORED", "NEEDS_REVIEW", "STALE"):
        state = "PROPOSED_UNVERIFIED"
    last = None
    for d in istore.decisions_for(db, item["item_id"]):
        last = d
    if last and last["decision"] in ("ACCEPTED_AS_READING", "REJECTED", "IGNORED", "NEEDS_REVIEW"):
        state = last["decision"]
        if last["source_sha256"] != source_sha or last["model_generation"] != generation:
            state = "STALE"
    return state


def build_snapshot(db, extraction_id: str, run_id: str | None = None) -> dict:
    """Snapshot of one run as ``engineering-intelligence-v1`` (validated by :func:`validate_snapshot`)."""
    run = None
    if run_id:
        row = db.db.execute("SELECT * FROM intelligence_run WHERE run_id=? AND extraction_id=?", (run_id, extraction_id)).fetchone()
        if row:
            run = dict(row)
            run["summary"] = json.loads(run.pop("summary_json"))
            run["outcomes"] = [json.loads(r[0]) for r in db.db.execute("SELECT outcome_json FROM stage_outcome WHERE run_id=? ORDER BY rowid", (run_id,))]
    else:
        run = istore.latest_run(db, extraction_id)
    if run is None:
        raise ValueError("No analysis run is stored for this drawing; run the analysis first")
    ex = db.export_extraction(extraction_id)
    doc = ex["document"]
    source_sha = doc["sha256"]
    generation = engine_version()
    items = istore.list_items(db, run["run_id"])
    regions = istore.list_regions(db, run["run_id"])
    reg = db.db.execute("SELECT drawing_no,revision_label FROM drawing_registration WHERE extraction_id=? ORDER BY rowid DESC LIMIT 1", (extraction_id,)).fetchone()
    drawing_id = extraction_id
    drawing = {"id": drawing_id, "source_name": doc["filename"], "sha256": source_sha, "page_count": int(doc["page_count"]),
               "drawing_no": reg["drawing_no"] if reg else None, "revision": reg["revision_label"] if reg else None,
               "registration_status": "REGISTERED" if reg else "UNREGISTERED", "title": None, "page_coordinate_frame": "media-top-left-v1",
               "page_regions": [{"page_index": r["page"] - 1, "region_type": r["kind"], "bbox": _box(r["bbox"])} for r in regions]}
    evidence: list[dict] = []
    ev_ids: set[str] = set()
    cfg_sha = run["config_sha256"] if len(run.get("config_sha256", "")) == 64 else None

    def add_ev(eid, page, bbox, raw, etype, producer, level, score=None, objects=None) -> str:
        if eid in ev_ids:
            return eid
        ev_ids.add(eid)
        e = {"id": eid, "drawing_id": drawing_id, "page_index": max(0, int(page or 1) - 1), "bbox": _box(bbox), "raw": str(raw)[:500], "type": etype,
             "producer": producer, "producer_version": generation, "semantic_level": level, "model_sha256": None, "config_sha256": cfg_sha}
        if score is not None:
            e["score"] = {"kind": "UNCALIBRATED", "raw_score": float(score), "calibrated_probability": None, "calibration_id": None}
        else:
            e["score"] = {"kind": "NONE", "raw_score": None, "calibrated_probability": None, "calibration_id": None}
        if objects:
            e["source_object_ids"] = sorted(set(objects))
        evidence.append(e)
        return eid

    page_ev = {}
    for p in run["summary"].get("pages", []):
        page_ev[p["page"]] = add_ev(f"ev-page-{p['page']}", p["page"], FULL, f"page {p['page']} classified {p['classification']}: {p['reason']}", "OTHER",
                                    "page-regions-v1", "DIRECT_OBSERVATION")
    occ_box = {i["item_id"]: _box(i.get("bbox")) for i in items if i["item_kind"] == "OCCURRENCE"}
    tag_of: dict[str, dict] = {}
    for i in items:
        if i["item_kind"] == "ATTRIBUTE" and i.get("attribute", {}).get("field_name") == "TAG_ASSOCIATION":
            tag_of[i["attribute"]["occurrence_id"]] = i
    asset_group = {}
    for i in items:
        if i["item_kind"] == "ASSET_HYPOTHESIS":
            for o in i["asset"]["occurrences"]:
                asset_group[o] = i["item_id"]
    entities: list[dict] = []
    ports_by_occ: dict[str, list[dict]] = {}
    for i in items:
        if i["item_kind"] != "PORT":
            continue
        p = i["port"]
        eid = add_ev("ev-" + i["item_id"], i["page"], {"x0": p["x"], "y0": p["y"], "x1": min(1.0, p["x"] + 0.0005), "y1": min(1.0, p["y"] + 0.0005)},
                     f"port {p['port_kind']}", "RASTER_SHAPE", "symbol-detect-v1", "STRUCTURALLY_DERIVED")
        ports_by_occ.setdefault(p["occurrence_id"], []).append({"id": i["item_id"], "kind": _PORT_KIND.get(p["port_kind"], p["port_kind"]),
                                                                  "label": p["port_kind"] if p["port_kind"] in _PORT_KIND else None,
                                                                  "angle_degrees": p.get("angle"), "source_evidence_ids": [eid]})
    entity_ids: set[str] = set()
    for i in items:
        if i["item_kind"] != "OCCURRENCE":
            continue
        oc = i["occurrence"]
        kind = _ENTITY_KIND(oc)
        ev = add_ev("ev-" + i["item_id"], i["page"], i["bbox"], f"{oc['graphical_family']} {oc['shape_variant']} ({oc['template_id']})", "RASTER_SHAPE",
                    "symbol-detect-v1", _level(i), oc["raw_score"], [i["item_id"]])
        tag = tag_of.get(i["item_id"])
        attrs = [{"name": "engineering_class", "verbatim": oc["engineering_class"], "semantic_level": "STRUCTURALLY_DERIVED" if oc["engineering_class"] != "UNKNOWN" else "UNKNOWN",
                  "evidence_ids": [ev], "numeric_type": "NOT_NUMERIC"},
                 {"name": "confidence_status", "verbatim": str(oc["confidence_status"]), "semantic_level": "STRUCTURALLY_DERIVED", "evidence_ids": [ev], "numeric_type": "NOT_NUMERIC"}]
        if oc.get("actuation"):
            attrs.append({"name": "actuation", "verbatim": str(oc["actuation"]["actuation"]), "semantic_level": "STRUCTURALLY_DERIVED", "evidence_ids": [ev], "numeric_type": "NOT_NUMERIC"})
        entities.append({"id": i["item_id"], "kind": kind, "tag": tag["attribute"]["verbatim"] if tag else None, "display_name": None,
                         "classification": oc["engineering_class"], "semantic_level": _level(i), "review_state": _review_state(db, i, extraction_id, source_sha, generation),
                         "source_evidence_ids": [ev] + ([ev_for_tag(tag, add_ev, drawing_id)] if tag else []), "source_occurrence_ids": [i["item_id"]],
                         "asset_hypothesis_group_id": asset_group.get(i["item_id"]) and "grp-" + asset_group[i["item_id"]], "attributes": attrs,
                         "ports": ports_by_occ.get(i["item_id"], []), "score": {"kind": "UNCALIBRATED", "raw_score": float(oc["raw_score"]), "calibrated_probability": None, "calibration_id": None}})
        entity_ids.add(i["item_id"])
    for i in items:
        if i["item_kind"] == "ATTRIBUTE":
            at = i["attribute"]
            name = at.get("field_name")
            if name == "TAG_ASSOCIATION":
                continue
            ev = add_ev("ev-" + i["item_id"], i["page"], _union([_box(e.get("bbox")) for e in i["evidence"] if isinstance(e, dict) and "bbox" in e]),
                        at.get("verbatim", name), "DRAWING_NOTE" if name in ("NOTE", "HOLD") else "NATIVE_TEXT", "doc-text-v1", _level(i), None,
                        [w for e in i["evidence"] if isinstance(e, dict) for w in e.get("word_ids", []) if w])
            if at.get("occurrence_id") and "tag" in at and at.get("statement"):          # protective-device mention
                kind = "SAFETY_DEVICE"
            elif "quantity" in at:
                kind = "TABLE_CELL"
            elif at.get("kind") in ("CONTROL_SYSTEM_MENTION", "INTERLOCK_WORDING"):
                kind = "CONTROL_SYSTEM" if at["kind"] == "CONTROL_SYSTEM_MENTION" else "ANNOTATION"
            else:
                kind = "ANNOTATION"
            attrs = []
            q = at.get("quantity")
            if q:
                nt = (at.get("numeric_type") or q.get("numeric_type") or "UNKNOWN")
                attrs.append({"name": str(at.get("field_name") or "VALUE"), "verbatim": at["verbatim"], "normalized_value": q.get("normalized_value"),
                              "original_unit": q.get("original_unit"), "normalized_unit": q.get("normalized_unit"), "numeric_type": nt if nt in _NUMERIC else "UNKNOWN",
                              "qualifier": at.get("column_label") or None, "semantic_level": _level(i), "evidence_ids": [ev]})
            else:
                attrs.append({"name": str(name or "TEXT"), "verbatim": str(at.get("verbatim") or at.get("text") or at.get("statement") or ""), "numeric_type": "NOT_NUMERIC",
                              "semantic_level": _level(i), "evidence_ids": [ev]})
            entities.append({"id": i["item_id"], "kind": kind, "tag": (at.get("tag") or None), "display_name": None, "classification": at.get("classification"),
                             "semantic_level": _level(i), "review_state": _review_state(db, i, extraction_id, source_sha, generation), "source_evidence_ids": [ev],
                             "source_occurrence_ids": [at["occurrence_id"]] if at.get("occurrence_id") in entity_ids else [], "asset_hypothesis_group_id": None,
                             "attributes": attrs, "ports": []})
            entity_ids.add(i["item_id"])
        elif i["item_kind"] == "TABLE":
            ev = add_ev("ev-" + i["item_id"], i["page"], i["evidence"][0]["bbox"], i.get("label") or "table", "NATIVE_TEXT", "table-parse-v1", _level(i),
                        None, i["evidence"][0].get("word_ids", []))
            entities.append({"id": i["item_id"], "kind": "TABLE", "tag": None, "display_name": i.get("label") or None, "classification": None,
                             "semantic_level": _level(i), "review_state": _review_state(db, i, extraction_id, source_sha, generation), "source_evidence_ids": [ev],
                             "source_occurrence_ids": [], "asset_hypothesis_group_id": None, "attributes": [], "ports": []})
            entity_ids.add(i["item_id"])
        elif i["item_kind"] == "LOOP":
            lp = i["loop"]
            ev = add_ev("ev-" + i["item_id"], i["page"], _union([_box(e.get("bbox")) for e in i["evidence"] if isinstance(e, dict)]),
                        f"loop {lp['loop_number']} ({lp['status']})", "OTHER", "control-loops-v1", _level(i))
            entities.append({"id": i["item_id"], "kind": "INSTRUMENT_LOOP", "tag": lp["loop_number"], "display_name": None, "classification": lp["status"],
                             "semantic_level": _level(i), "review_state": _review_state(db, i, extraction_id, source_sha, generation), "source_evidence_ids": [ev],
                             "source_occurrence_ids": [m["occurrence_id"] for m in lp["members"] if m["occurrence_id"] in entity_ids], "asset_hypothesis_group_id": None,
                             "attributes": [{"name": "logic", "verbatim": lp["logic"], "numeric_type": "NOT_NUMERIC", "semantic_level": "CONTEXTUAL_INFERENCE", "evidence_ids": [ev]},
                                            {"name": "safety_credit", "verbatim": lp["safety_credit"], "numeric_type": "NOT_NUMERIC", "semantic_level": "CONTEXTUAL_INFERENCE", "evidence_ids": [ev]}],
                             "ports": []})
            entity_ids.add(i["item_id"])
    relationships: list[dict] = []
    unresolved: list[dict] = []
    for i in items:
        if i["item_kind"] == "RELATION":
            r = i["relation"]
            if "from_occurrence" not in r or "to_occurrence" not in r:
                continue
            a, b = r["from_occurrence"], r["to_occurrence"]
            if a not in entity_ids or b not in entity_ids:
                continue
            rtype = r.get("edge_kind") or r.get("relation") or "OTHER"
            rtype = _REL_TYPE.get(rtype, rtype)
            direction = (r.get("direction") or {}).get("value", "UNKNOWN") if isinstance(r.get("direction"), dict) else "UNKNOWN"
            fe, te = (a, b)
            fp, tp = r.get("from_port"), r.get("to_port")
            if direction == "TO_FROM":
                fe, te, fp, tp = b, a, tp, fp
            ev = add_ev("ev-" + i["item_id"], r.get("page", 1), _union([occ_box.get(a), occ_box.get(b)]), f"{rtype} path " + ",".join(r.get("evidence", {}).get("stroke_ids", [])[:6]) if "evidence" in r and isinstance(r["evidence"], dict) else rtype,
                        "LINE_PATH", "engineering-graph-v2", _level(i))
            relationships.append({"id": i["item_id"], "type": rtype if rtype in _REL_TYPES else "OTHER", "from_entity_id": fe, "to_entity_id": te,
                                  "from_port_id": fp, "to_port_id": tp, "direction": _DIRECTION.get(direction, "UNKNOWN"), "semantic_level": "CONFLICTING" if direction == "CONFLICTING" else _level(i),
                                  "review_state": _review_state(db, i, extraction_id, source_sha, generation), "source_evidence_ids": [ev], "hypothesis_group_id": None})
            alt = (r.get("evidence") or {}).get("junction_ids_with_alternatives") if isinstance(r.get("evidence"), dict) else None
            if alt:
                unresolved.append({"id": "unr-" + i["item_id"], "severity": "WARNING", "description": f"drawn path passes {len(alt)} crossing(s) with an alternative reading; the connection may not hold",
                                   "evidence_ids": [ev], "affected_entity_ids": [a, b], "hypothesis_group_id": None})
        elif i["item_kind"] == "CONFLICT":
            c = i["conflict"]
            ev = add_ev("ev-" + i["item_id"], i["page"] or 1, FULL, f"{c.get('kind')}", "OTHER", "engineering-graph-v2", "CONFLICTING")
            unresolved.append({"id": "unr-" + i["item_id"], "severity": "CRITICAL", "description": f"{c.get('kind')}: {c.get('note', 'conflicting evidence')}",
                               "evidence_ids": [ev], "affected_entity_ids": [], "hypothesis_group_id": None})
    for e in entities:
        if e["kind"] in ("VALVE", "INSTRUMENT", "EQUIPMENT", "UNCLASSIFIED_SYMBOL") and e["classification"] in ("UNKNOWN",):
            unresolved.append({"id": "unr-class-" + e["id"], "severity": "INFO", "description": "symbol found but its class is withheld (score below the accept threshold)",
                               "evidence_ids": e["source_evidence_ids"][:1], "affected_entity_ids": [e["id"]], "hypothesis_group_id": None})
    health = run["summary"].get("health", {})
    for p in health.get("pages", []):
        if p.get("text_status") in ("UNREADABLE_OR_FAILED", "NOT_ATTEMPTED") and p.get("ink_evidence"):
            unresolved.append({"id": f"unr-text-{p['page']}", "severity": "CRITICAL",
                               "description": f"page {p['page']} has drawn content but its text is not readable ({p.get('primary_blocker') or p['text_status']}); an empty result is NOT an empty drawing",
                               "evidence_ids": [page_ev.get(p["page"])] if page_ev.get(p["page"]) else [], "affected_entity_ids": [], "hypothesis_group_id": None})
    outcomes = []
    for o in run["outcomes"]:
        outcomes.append({"stage": o["stage_id"], "status": o["status"], "input_sha256": source_sha, "observed_count": int(o.get("candidates", 0)),
                         "error_code": o.get("error_class") or None, "pages_processed": [], "truncated": bool(o.get("cap_truncations")), "elapsed_ms": int(o.get("runtime_ms", 0))})
    warnings = [f"{o['stage_id']}: {o['status']}" + (f" ({o.get('error_summary')})" if o.get("error_summary") else "") for o in run["outcomes"]
                if o["status"] in ("FAILED", "TIMEOUT", "PARTIAL", "CANCELLED")]
    warnings += [f"diagnostic {c}" for c in health.get("codes", [])]
    unprocessed = [{"drawing_id": drawing_id, "page_index": p["page"] - 1, "bbox": dict(FULL), "reason": p.get("primary_blocker") or p["text_status"]}
                   for p in health.get("pages", []) if p.get("text_status") in ("UNREADABLE_OR_FAILED", "NOT_ATTEMPTED")]
    narrative = _narrative(run["status"], entities, relationships, unresolved, page_ev, ev_ids, health)
    snap = {"schema_version": SCHEMA_ID,
            "package": {"run_id": run["run_id"], "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "offline": True, "proposal_only": True,
                        "source_scope": "DRAWING_REVISION_ONLY", "engineering_validation": "NOT_PERFORMED", "status": run["status"] if run["status"] != "CANCELLED" else "INCOMPLETE",
                        "engine_version": generation, "model_config_sha256": run["config_sha256"], "warnings": warnings},
            "drawings": [drawing], "evidence": sorted(evidence, key=lambda e: e["id"]),
            "entities": sorted(entities, key=lambda e: e["id"]), "relationships": sorted(relationships, key=lambda r: r["id"]),
            "quality": {"status": run["status"] if run["status"] != "CANCELLED" else "INCOMPLETE", "stage_outcomes": outcomes, "warnings": warnings, "unprocessed_regions": unprocessed,
                        "coverage_note": "Coverage describes which stages ran and produced candidates. It is not accuracy; no labelled gold has measured it."},
            "narrative": narrative, "unresolved": sorted(unresolved, key=lambda u: u["id"])}
    return snap


_REL_TYPES = {"DRAWN_CONNECTS", "SIGNAL_CONNECTS", "HAS_PORT", "HAS_NOZZLE", "MEASURES", "INDICATES", "CONTROLS", "ACTUATES", "POSITION_FEEDBACK",
              "ALARM_REFERENCE", "PART_OF_PACKAGE", "PROPOSED_SAME_AS", "OFFPAGE_MATCH_CANDIDATE", "REFERENCES", "LOCATED_IN", "OTHER"}


def _ENTITY_KIND(oc: dict) -> str:
    if oc["engineering_class"] == "UNKNOWN":
        return "UNCLASSIFIED_SYMBOL"
    return _ENTITY_BY_FAMILY.get(oc["graphical_family"], "UNCLASSIFIED_SYMBOL")


def ev_for_tag(tag_item: dict, add_ev, drawing_id: str) -> str:
    e = next((x for x in tag_item["evidence"] if isinstance(x, dict) and "word_ids" in x), tag_item["evidence"][0])
    return add_ev("ev-" + tag_item["item_id"], tag_item["page"], e.get("bbox"), tag_item["attribute"]["verbatim"], "NATIVE_TEXT", "engineering-graph-v2",
                  "CONTEXTUAL_INFERENCE", None, e.get("word_ids", []))


def _narrative(status: str, entities, relationships, unresolved, page_ev, ev_ids, health) -> list[dict]:
    claims = []

    def claim(cid, text, level, evidence_ids, unresolved_ids=None):
        c = {"claim_id": cid, "text": text, "semantic_level": level, "evidence_ids": sorted({e for e in evidence_ids if e in ev_ids})}
        if unresolved_ids:
            c["unresolved_issue_ids"] = sorted(unresolved_ids)
        claims.append(c)
    codes = ", ".join(health.get("codes", [])) or "none"
    claim("N1", f"Analysis status is {status} (diagnostic codes: {codes}). This describes which stages ran and produced candidates; it is not accuracy and not plant verification.",
          "DIRECT_OBSERVATION", list(page_ev.values()))
    by_kind: dict[str, list[dict]] = {}
    for e in entities:
        by_kind.setdefault(e["kind"], []).append(e)
    for k in ("EQUIPMENT", "VALVE", "INSTRUMENT", "UNCLASSIFIED_SYMBOL", "SAFETY_DEVICE", "INSTRUMENT_LOOP", "TABLE"):
        if k in by_kind:
            tags = sorted({e["tag"] for e in by_kind[k] if e["tag"]})
            claim(f"N-{k}", f"{len(by_kind[k])} {k.lower().replace('_', ' ')} item(s) are drawn as proposals" + (f"; tags read: {', '.join(tags[:12])}" if tags else "; none carries a tag") + ".",
                  "STRUCTURALLY_DERIVED", [ev for e in by_kind[k][:40] for ev in e["source_evidence_ids"][:1]])
    if relationships:
        drawn = [r for r in relationships if r["type"] in ("DRAWN_CONNECTS", "SIGNAL_CONNECTS")]
        claim("N-REL", f"{len(drawn)} drawn connection proposal(s) join ports of different items as ink paths on this sheet; direction is known only for "
                       f"{sum(1 for r in drawn if r['direction'] == 'UNIDIRECTIONAL')} of them (arrow evidence). These are not verified connections.",
              "STRUCTURALLY_DERIVED", [ev for r in drawn[:40] for ev in r["source_evidence_ids"]])
    if unresolved:
        crit = [u["id"] for u in unresolved if u["severity"] == "CRITICAL"]
        claim("N-UNRESOLVED", f"{len(unresolved)} unresolved issue(s) are listed ({len(crit)} critical). They must be read before relying on any part of this package.",
              "CONFLICTING" if crit else "UNKNOWN", [ev for u in unresolved[:40] for ev in u["evidence_ids"][:1]], [u["id"] for u in unresolved[:60]])
    if status in ("FAILED", "INCOMPLETE", "NOT_RUN"):
        claim("N-RELIABILITY", "A reliable, comprehensive description of this drawing cannot be produced from this run; do not read a short list of items as an empty drawing.",
              "DIRECT_OBSERVATION", list(page_ev.values()))
    claim("N-LIMITS", "This is an interpretation of a drawing revision, not a verification of the constructed plant or its safety systems. No safety credit, flow, or isolation is asserted.",
          "DIRECT_OBSERVATION", list(page_ev.values()))
    return claims


def validate_snapshot(snapshot: dict) -> list[str]:
    """Schema problems (empty list = valid). Also checks that every referenced evidence id exists."""
    import jsonschema
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = [f"{'/'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in jsonschema.Draft202012Validator(schema).iter_errors(snapshot)]
    ids = {e["id"] for e in snapshot.get("evidence", [])}
    for group in ("entities", "relationships"):
        for obj in snapshot.get(group, []):
            for ev in obj.get("source_evidence_ids", []):
                if ev not in ids:
                    errors.append(f"{group}/{obj.get('id')}: unknown evidence id {ev}")
    for n in snapshot.get("narrative", []):
        for ev in n["evidence_ids"]:
            if ev not in ids:
                errors.append(f"narrative/{n['claim_id']}: unknown evidence id {ev}")
    ent = {e["id"] for e in snapshot.get("entities", [])}
    for r in snapshot.get("relationships", []):
        if r["from_entity_id"] not in ent or r["to_entity_id"] not in ent:
            errors.append(f"relationships/{r['id']}: endpoint entity missing")
    return errors


# ---------------------------------------------------------------------------------------------------- package export
def _safe_cell(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def _csv(header: list[str], rows: list[list]) -> str:
    buf = StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for r in rows:
        w.writerow([_safe_cell(c) for c in r])
    return buf.getvalue()


def registers(snapshot: dict) -> dict[str, str]:
    ev = {e["id"]: e for e in snapshot["evidence"]}
    out = {}

    def rows(kinds, extra):
        res = []
        for e in snapshot["entities"]:
            if e["kind"] in kinds:
                b = ev[e["source_evidence_ids"][0]]["bbox"] if e["source_evidence_ids"] else FULL
                res.append([e["id"], e["tag"], e["kind"], e["classification"], e["review_state"], e["semantic_level"],
                            ev[e["source_evidence_ids"][0]]["page_index"] + 1 if e["source_evidence_ids"] else "", round(b["x0"], 4), round(b["y0"], 4),
                            ";".join(e["source_evidence_ids"]), *extra(e)])
        return res
    head = ["entity_id", "tag", "kind", "classification", "review_state", "semantic_level", "page", "x0", "y0", "evidence_ids"]
    out["equipment.csv"] = _csv(head, rows({"EQUIPMENT"}, lambda e: []))
    out["valves.csv"] = _csv(head + ["actuation"], rows({"VALVE", "VALVE_ACTUATOR"}, lambda e: [next((a["verbatim"] for a in e["attributes"] if a["name"] == "actuation"), "")]))
    out["instruments.csv"] = _csv(head, rows({"INSTRUMENT"}, lambda e: []))
    out["loops.csv"] = _csv(head, rows({"INSTRUMENT_LOOP"}, lambda e: []))
    out["unclassified_symbols.csv"] = _csv(head, rows({"UNCLASSIFIED_SYMBOL"}, lambda e: []))
    out["safety_related_mentions.csv"] = _csv(head, rows({"SAFETY_DEVICE", "CONTROL_SYSTEM"}, lambda e: []))
    vals = []
    for e in snapshot["entities"]:
        if e["kind"] == "TABLE_CELL":
            for a in e["attributes"]:
                vals.append([e["id"], a["name"], a["qualifier"], a["numeric_type"], a["verbatim"], a.get("original_unit"), a.get("normalized_value"), a.get("normalized_unit"),
                             e["review_state"], ";".join(a["evidence_ids"])])
    out["values_and_setpoints.csv"] = _csv(["entity_id", "field", "column", "numeric_type", "verbatim", "original_unit", "normalized_value", "normalized_unit", "review_state", "evidence_ids"], vals)
    notes = [[e["id"], a["name"], a["verbatim"], e["review_state"], ";".join(a["evidence_ids"])] for e in snapshot["entities"] if e["kind"] == "ANNOTATION" for a in e["attributes"]]
    out["notes_and_title_text.csv"] = _csv(["entity_id", "field", "verbatim", "review_state", "evidence_ids"], notes)
    rels = [[r["id"], r["type"], r["from_entity_id"], r["to_entity_id"], r["direction"], r["review_state"], r["semantic_level"], ";".join(r["source_evidence_ids"])]
            for r in snapshot["relationships"]]
    out["relationships.csv"] = _csv(["relationship_id", "type", "from", "to", "direction", "review_state", "semantic_level", "evidence_ids"], rels)
    return out


def _unique_dir(parent: Path, name: str) -> Path:
    n = 1
    while True:
        cand = parent / (name if n == 1 else f"{name} ({n})")
        if not cand.exists():
            return cand
        n += 1


def export_package(db, extraction_id: str, folder: str | Path, *, run_id: str | None = None) -> Path:
    """Write the AI-ready package into a NEW sub-folder of ``folder`` (never overwrites). Returns the package folder."""
    parent = Path(folder)
    if not parent.is_dir():
        raise FileNotFoundError("The chosen folder does not exist")
    snap = build_snapshot(db, extraction_id, run_id)
    problems = validate_snapshot(snap)
    if problems:
        raise ValueError("Snapshot failed schema validation: " + "; ".join(problems[:5]))
    stem = safe_stem(snap["drawings"][0]["source_name"])
    out = _unique_dir(parent, stem + "_intelligence")
    out.mkdir()
    files: dict[str, bytes] = {}

    def put(rel: str, text: str) -> None:
        files[rel] = text.encode("utf-8")
    put("engineering_intelligence_v1.json", json.dumps(snap, indent=1, sort_keys=True, ensure_ascii=False))
    for name, text in registers(snap).items():
        put("registers/" + name, text)
    pages = sorted({e["page_index"] for e in snap["evidence"]})
    for pg in pages:
        ids = {e["id"] for e in snap["evidence"] if e["page_index"] == pg}
        ents = [e for e in snap["entities"] if set(e["source_evidence_ids"]) & ids]
        eids = {e["id"] for e in ents}
        rels = [r for r in snap["relationships"] if r["from_entity_id"] in eids or r["to_entity_id"] in eids]
        put(f"graph/graph_page_{pg + 1}.json", json.dumps({"page": pg + 1, "entities": ents, "relationships": rels, "boundary_note":
                                                         "relationships may reference entities on other pages; see the main file"}, indent=1, sort_keys=True))
    parts = [snap["evidence"][i:i + MAX_EVIDENCE_PER_FILE] for i in range(0, max(1, len(snap["evidence"])), MAX_EVIDENCE_PER_FILE)]
    for k, part in enumerate(parts, 1):
        put(f"evidence/evidence_part_{k:03d}.json", json.dumps(part, indent=1, sort_keys=True))
    put("evidence/evidence_index.json", json.dumps({"parts": len(parts), "evidence_count": len(snap["evidence"]), "max_per_file": MAX_EVIDENCE_PER_FILE}, indent=1))
    put("quality.json", json.dumps(snap["quality"] | {"unresolved": snap["unresolved"]}, indent=1, sort_keys=True))
    put("overview.json", json.dumps({"drawing": snap["drawings"][0], "status": snap["package"]["status"], "counts": _counts(snap),
                                     "narrative": snap["narrative"], "unresolved_count": len(snap["unresolved"]),
                                     "note": "low-context first pass; every claim lists evidence ids"}, indent=1, sort_keys=True))
    put("drawing_summary.md", _summary_md(snap))
    put("AI_INTERPRETATION_PROMPT.md", PROMPT)
    manifest = {"schema_version": SCHEMA_ID, "package_version": VERSION, "engine_version": engine_version(), "run_id": snap["package"]["run_id"],
                "status": snap["package"]["status"], "drawing_sha256": snap["drawings"][0]["sha256"], "pages": [p + 1 for p in pages],
                "registers": sorted(k for k in files if k.startswith("registers/")), "graph_files": sorted(k for k in files if k.startswith("graph/")),
                "evidence_parts": len(parts), "unresolved": len(snap["unresolved"]), "quality_warnings": snap["quality"]["warnings"],
                "partitioning": "evidence is split at %d records per file; nothing is truncated" % MAX_EVIDENCE_PER_FILE,
                "files": {k: {"sha256": hashlib.sha256(v).hexdigest(), "bytes": len(v)} for k, v in sorted(files.items())},
                "disclaimer": "Interpretation of a drawing revision, not verification of the constructed plant or safety systems. Keep this package local.",
                "upload": "NONE: the program never uploads this package; any sharing is the user's own action."}
    put("manifest.json", json.dumps(manifest, indent=1, sort_keys=True))
    for rel, data in files.items():
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return out


def _counts(snap: dict) -> dict:
    kinds: dict[str, int] = {}
    for e in snap["entities"]:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    return {"entities": dict(sorted(kinds.items())), "relationships": len(snap["relationships"]), "evidence": len(snap["evidence"])}


def _summary_md(snap: dict) -> str:
    d = snap["drawings"][0]
    lines = [f"# {d['source_name']}", "", f"- SHA-256: `{d['sha256']}`", f"- Pages: {d['page_count']}", f"- Status: **{snap['package']['status']}**", "",
             "> Interpretation of a drawing revision, not a verification of the constructed plant or its safety systems.", "", "## What the reader says", ""]
    for n in snap["narrative"]:
        lines.append(f"- ({n['claim_id']}, {n['semantic_level']}) {n['text']}")
    lines += ["", "## Unresolved", ""]
    lines += [f"- [{u['severity']}] {u['description']}" for u in snap["unresolved"][:40]] or ["- none listed (this is not a statement of completeness)"]
    return "\n".join(lines) + "\n"
