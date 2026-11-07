"""Storage, audit and review of teach-by-example symbol searches.

Additive tables created idempotently when a project is opened (no schema-version bump, so existing
projects and the migration tests are unaffected; older program versions simply ignore the tables).
Records are append-only and every teach/review action is written to the hash-chained audit log.
"""
from __future__ import annotations

import json

from ..api import canonical_json

DDL = """
CREATE TABLE IF NOT EXISTS example_match_analysis (
  analysis_id TEXT PRIMARY KEY,
  extraction_id TEXT NOT NULL REFERENCES extraction(extraction_id),
  label TEXT NOT NULL, class_hint TEXT NOT NULL, page INTEGER NOT NULL,
  example_bbox_json TEXT NOT NULL, params_json TEXT NOT NULL,
  result_hash TEXT NOT NULL, result_json TEXT NOT NULL,
  actor TEXT NOT NULL, created_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS example_match_candidate (
  candidate_id TEXT PRIMARY KEY,
  analysis_id TEXT NOT NULL REFERENCES example_match_analysis(analysis_id),
  native_id TEXT NOT NULL, page INTEGER NOT NULL, candidate_json TEXT NOT NULL,
  UNIQUE(analysis_id, native_id)
);
CREATE TABLE IF NOT EXISTS example_match_decision (
  decision_id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES example_match_candidate(candidate_id),
  actor TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL, created_utc TEXT NOT NULL,
  CHECK(decision IN ('ACCEPTED_AS_READING','REJECTED','UNRESOLVED'))
);
CREATE INDEX IF NOT EXISTS ix_example_analysis_extraction ON example_match_analysis(extraction_id);
CREATE INDEX IF NOT EXISTS ix_example_candidate_analysis ON example_match_candidate(analysis_id);
CREATE INDEX IF NOT EXISTS ix_example_decision_candidate ON example_match_decision(candidate_id);
CREATE TRIGGER IF NOT EXISTS block_update_example_analysis BEFORE UPDATE ON example_match_analysis BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_example_analysis BEFORE DELETE ON example_match_analysis BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_example_candidate BEFORE UPDATE ON example_match_candidate BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_example_candidate BEFORE DELETE ON example_match_candidate BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_update_example_decision BEFORE UPDATE ON example_match_decision BEGIN SELECT RAISE(ABORT,'append-only record'); END;
CREATE TRIGGER IF NOT EXISTS block_delete_example_decision BEFORE DELETE ON example_match_decision BEGIN SELECT RAISE(ABORT,'append-only record'); END;
"""

CLASS_HINTS = ("VALVE", "INSTRUMENT", "EQUIPMENT", "FITTING", "ANNOTATION", "OTHER")
DECISIONS = ("ACCEPTED_AS_READING", "REJECTED", "UNRESOLVED")


def ensure_schema(db) -> None:
    db.executescript(DDL)


def _check(text: str, name: str, lo: int = 1, hi: int = 150) -> str:
    if not isinstance(text, str) or not lo <= len(text.strip()) <= hi:
        raise ValueError(f"Invalid {name}")
    return text.strip()


def teach_symbol(store, extraction_id: str, *, page: int, bbox: dict, label: str, class_hint: str = "OTHER",
                 actor: str, threshold: float | None = None, cancel=None) -> tuple[str, dict]:
    """Run the example search for one boxed symbol and store the proposals. Returns (analysis_id, result)."""
    from .example_matching import DEFAULT_THRESHOLD, find_similar
    from .project import _global_id, _utc
    label, actor = _check(label, "symbol label", 1, 80), _check(actor, "reviewer name")
    if class_hint not in CLASS_HINTS:
        raise ValueError("Unknown class hint")
    row = store.db.execute("SELECT document_sha256 FROM extraction WHERE extraction_id=?", (extraction_id,)).fetchone()
    if row is None:
        raise KeyError("Unknown drawing")
    pdf = store.get_source_pdf(row[0])
    if pdf is None:
        raise ValueError("The source PDF bytes are not stored in this project; matching needs the page image")
    result = find_similar(pdf, page, bbox, threshold=DEFAULT_THRESHOLD if threshold is None else threshold, cancel=cancel)
    aid = _global_id("example-analysis", extraction_id, label, str(page), result["result_sha256"])
    now = _utc()
    with store.db:
        if store.db.execute("SELECT 1 FROM example_match_analysis WHERE analysis_id=?", (aid,)).fetchone():
            return aid, result
        store.db.execute("INSERT INTO example_match_analysis VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                         (aid, extraction_id, label, class_hint, page, canonical_json(result["example_bbox"]),
                          canonical_json({"threshold": result["threshold"], "scales": result["scales"],
                                          "rotations": result["rotations"]}),
                          result["result_sha256"], canonical_json(result), actor, now))
        for m in result["matches"]:
            store.db.execute("INSERT INTO example_match_candidate VALUES(?,?,?,?,?)",
                             (_global_id("example-candidate", aid, m["id"]), aid, m["id"], m["page"], canonical_json(m)))
        store._append_event("SYMBOL_EXAMPLE_TAUGHT", aid,
                            {"extraction_id": extraction_id, "label": label, "class_hint": class_hint, "page": page,
                             "actor": actor, "matches": len(result["matches"]), "result_sha256": result["result_sha256"]}, now)
    return aid, result


def list_example_candidates(store, extraction_id: str, *, limit: int = 2000) -> list[dict]:
    """Candidates of the newest analysis for each (label, page) taught on this drawing."""
    rows = store.db.execute(
        """SELECT c.candidate_id, c.page, c.candidate_json, a.analysis_id, a.label, a.class_hint
           FROM example_match_candidate c JOIN example_match_analysis a ON a.analysis_id=c.analysis_id
           WHERE a.extraction_id=? AND a.rowid=(SELECT MAX(a2.rowid) FROM example_match_analysis a2
                  WHERE a2.extraction_id=a.extraction_id AND a2.label=a.label AND a2.page=a.page)
           ORDER BY a.label, c.page, c.candidate_id LIMIT ?""", (extraction_id, limit)).fetchall()
    out = []
    for r in rows:
        c = json.loads(r["candidate_json"])
        c.update({"candidate_id": r["candidate_id"], "analysis_id": r["analysis_id"], "label": r["label"],
                  "class_hint": r["class_hint"]})
        out.append(c)
    return out


def latest_example_review(store, candidate_id: str) -> dict | None:
    row = store.db.execute("SELECT * FROM example_match_decision WHERE candidate_id=? ORDER BY rowid DESC LIMIT 1",
                           (candidate_id,)).fetchone()
    return dict(row) if row else None


def review_example_match(store, candidate_id: str, *, actor: str, decision: str, reason: str) -> str:
    from uuid import uuid4
    from .project import _utc
    if decision not in DECISIONS:
        raise ValueError("Unsupported example-match decision")
    actor = _check(actor, "reviewer name")
    reason = _check(reason, "reason", 5, 500)
    if not store.db.execute("SELECT 1 FROM example_match_candidate WHERE candidate_id=?", (candidate_id,)).fetchone():
        raise KeyError("Unknown example match")
    did, now = "exdec-" + uuid4().hex, _utc()
    with store.db:
        store.db.execute("INSERT INTO example_match_decision VALUES(?,?,?,?,?,?)", (did, candidate_id, actor, decision, reason, now))
        store._append_event("SYMBOL_EXAMPLE_REVIEW", candidate_id,
                            {"decision_id": did, "actor": actor, "decision": decision, "reason": reason}, now)
    return did
