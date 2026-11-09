"""Persistence for engineering-intelligence runs (Rev X, WPU-12). Additive v13 tables only; append-only.

Functions take an open ``ProjectStore``. Nothing here changes a v12 table, so older readers still open the project.
Decisions (human review) are recorded in their own append-only table and are bound to the source hash and model generation;
a later re-analysis does not rewrite them, it marks them ``STALE`` in views (see ``stale_decisions``).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from .stage_telemetry import DRAWING_STATUSES, engine_version, sha256_json

DECISIONS = ("ACCEPTED_AS_READING", "REJECTED", "IGNORED", "NEEDS_REVIEW", "RECLASSIFIED", "EDITED", "LINKED", "UNLINKED",
             "AMBIGUITY_RESOLVED")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _id(prefix: str, *parts) -> str:
    return prefix + "-" + hashlib.sha256(_json(list(parts)).encode("utf-8")).hexdigest()[:24]


def _extraction_source_sha(db, extraction_id: str) -> str:
    row = db.db.execute("SELECT document_sha256 FROM extraction WHERE extraction_id=?", (extraction_id,)).fetchone()
    if row is None:
        raise KeyError("Unknown extraction")
    return row[0]


def record_run(db, extraction_id: str, *, preset: str, status: str, outcomes: list[dict], regions: list[dict] | None = None,
               items: list[dict] | None = None, summary: dict | None = None, config: dict | None = None) -> str:
    """Store one analysis run, its stage outcomes, page regions and engineering items. Idempotent on content."""
    if status not in DRAWING_STATUSES and status != "CANCELLED":
        raise ValueError(f"Unknown run status {status!r}")
    source_sha = _extraction_source_sha(db, extraction_id)
    config_sha = sha256_json(config or {})
    stable = {"outcomes": [{k: v for k, v in o.items() if k not in ("runtime_ms",)} for o in outcomes],
              "regions": [r["region_id"] for r in (regions or [])], "items": [i["item_id"] for i in (items or [])]}
    run_hash = sha256_json({"extraction": extraction_id, "source": source_sha, "config": config_sha, "stable": stable,
                            "engine": engine_version(), "preset": preset})
    run_id = _id("irun", extraction_id, run_hash)
    now = _utc()
    with db.db:
        if db.db.execute("SELECT 1 FROM intelligence_run WHERE run_id=?", (run_id,)).fetchone():
            return run_id
        db.db.execute("INSERT INTO intelligence_run VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (run_id, extraction_id, preset, status, engine_version(), config_sha, source_sha, run_hash,
                       _json(summary or {}), now))
        for o in outcomes:
            db.db.execute("INSERT INTO stage_outcome VALUES(?,?,?,?,?,?,?)",
                          (_id("sout", run_id, o["stage_id"]), run_id, extraction_id, o["stage_id"], o["status"], _json(o), now))
        for r in regions or []:
            db.db.execute("INSERT OR IGNORE INTO page_region VALUES(?,?,?,?,?,?)",
                          (r["region_id"] + ":" + run_id[-8:], run_id, extraction_id, r["page"], r["kind"], _json(r)))
        for it in items or []:
            db.db.execute("INSERT OR IGNORE INTO engineering_item VALUES(?,?,?,?,?,?,?)",
                          (it["item_id"] + ":" + run_id[-8:], run_id, extraction_id, it["item_kind"],
                           it.get("tag_normalized"), it.get("page"), _json(it)))
        db._append_event("INTELLIGENCE_RUN_RECORDED", run_id, {"extraction_id": extraction_id, "status": status,
                                                                 "run_hash": run_hash, "stages": len(outcomes)}, now)
    return run_id


def latest_run(db, extraction_id: str) -> dict | None:
    row = db.db.execute("SELECT * FROM intelligence_run WHERE extraction_id=? ORDER BY created_utc DESC, rowid DESC LIMIT 1",
                        (extraction_id,)).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["summary"] = json.loads(out.pop("summary_json"))
    out["outcomes"] = [json.loads(r[0]) for r in db.db.execute(
        "SELECT outcome_json FROM stage_outcome WHERE run_id=? ORDER BY rowid", (row["run_id"],))]
    return out


def list_items(db, run_id: str, kind: str | None = None) -> list[dict]:
    q = "SELECT item_json FROM engineering_item WHERE run_id=?" + (" AND item_kind=?" if kind else "") + " ORDER BY rowid"
    return [json.loads(r[0]) for r in db.db.execute(q, (run_id, kind) if kind else (run_id,))]


def list_regions(db, run_id: str) -> list[dict]:
    return [json.loads(r[0]) for r in db.db.execute("SELECT region_json FROM page_region WHERE run_id=? ORDER BY rowid", (run_id,))]


def add_snapshot(db, extraction_id: str, run_id: str, schema_id: str, snapshot: dict) -> str:
    """Publish an immutable, hash-addressed snapshot (graph + registers + quality + evidence)."""
    digest = sha256_json(snapshot)
    sid = _id("isnap", extraction_id, digest)
    with db.db:
        if not db.db.execute("SELECT 1 FROM intelligence_snapshot WHERE snapshot_id=?", (sid,)).fetchone():
            db.db.execute("INSERT INTO intelligence_snapshot VALUES(?,?,?,?,?,?,?)",
                          (sid, extraction_id, run_id, schema_id, digest, _json(snapshot), _utc()))
            db._append_event("INTELLIGENCE_SNAPSHOT_PUBLISHED", sid, {"extraction_id": extraction_id, "sha256": digest}, _utc())
    return sid


def get_snapshot(db, snapshot_id: str) -> dict:
    row = db.db.execute("SELECT snapshot_json, snapshot_sha256 FROM intelligence_snapshot WHERE snapshot_id=?", (snapshot_id,)).fetchone()
    if row is None:
        raise KeyError("Unknown snapshot")
    data = json.loads(row[0])
    if sha256_json(data) != row[1]:
        raise ValueError("Stored snapshot failed its integrity check")
    return data


def add_decision(db, extraction_id: str, item_id: str, *, actor: str, decision: str, reason: str,
                 old_value=None, new_value=None, model_generation: str | None = None) -> str:
    """Append a named human decision about a drawing interpretation. Never a plant verification."""
    if decision not in DECISIONS:
        raise ValueError(f"Unknown decision {decision!r}")
    if not actor or not actor.strip():
        raise ValueError("A named reviewer is required")
    if not reason or not reason.strip():
        raise ValueError("A reason is required")
    source_sha = _extraction_source_sha(db, extraction_id)
    now = _utc()
    did = _id("idec", extraction_id, item_id, actor, decision, now, _json(new_value))
    with db.db:
        db.db.execute("INSERT INTO intelligence_decision VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (did, extraction_id, item_id, actor.strip(), decision, _json(old_value), _json(new_value), reason.strip(),
                       source_sha, model_generation or engine_version(), now))
        db._append_event("INTELLIGENCE_DECISION", did, {"item_id": item_id, "decision": decision, "actor": actor.strip()}, now)
    return did


def decisions_for(db, item_id: str) -> list[dict]:
    return [dict(r) for r in db.db.execute("SELECT * FROM intelligence_decision WHERE item_id=? ORDER BY rowid", (item_id,))]


def stale_decisions(db, extraction_id: str, current_model_generation: str | None = None) -> list[dict]:
    """Decisions made under a different source hash or model generation: show them, ask for reaffirmation."""
    source_sha = _extraction_source_sha(db, extraction_id)
    gen = current_model_generation or engine_version()
    return [dict(r) for r in db.db.execute(
        "SELECT * FROM intelligence_decision WHERE extraction_id=? AND (source_sha256<>? OR model_generation<>?) ORDER BY rowid",
        (extraction_id, source_sha, gen))]
