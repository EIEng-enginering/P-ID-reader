"""Review ledger for ambiguous or blocked connection candidates (R5 update, change 4).

The typed drawing graph proposes a connection only when a drawn path joins two compatible ports. Two kinds of candidate are left over:

* ``BLOCKED_PORT_KIND_MISMATCH`` -- a drawn line reaches ports that may not be joined (for example a dashed signal line meeting a process
  port). The graph keeps this as a CONFLICT item and proposes no edge.
* ``AMBIGUOUS_CROSSING`` -- a proposed edge whose path passes crossings that could be read either way (``HAS_ALTERNATIVES``).

This module lists them in a **separate ledger** with their source evidence and reasons. The ledger is not topology: its entries are never
edges of the graph, never enter a path, isolation or loop query, never reach a Worksheet decision, and carry
``blocked_is_not_disconnected = true`` -- a candidate that the reader could not join is *not* a statement that the plant is disconnected,
and a candidate that is listed is *not* a statement that it is connected.

Review ids are namespaced by the immutable drawing revision (source SHA-256) and derived from the *source observations* (ports, strokes,
junction ids), not from the run, so a re-run of the same drawing gives the same ids and a human decision recorded against an id survives. A
decision is stored in the existing append-only ``intelligence_decision`` table (no schema change); a decision made against a different
source hash is shown as ``STALE``. Deciding never moves a candidate into accepted topology.
"""
from __future__ import annotations

import hashlib
import json

from . import intelligence_store as istore

VERSION = "connection-review-ledger-v1"
STATE_MAP = {"ACCEPTED_AS_READING": "REVIEWER_ACCEPTED_AS_DRAWN", "REJECTED": "REVIEWER_REJECTED", "IGNORED": "REVIEWER_IGNORED", "NEEDS_REVIEW": "UNRESOLVED"}
LEDGER_NOTE = ("Candidates for human review only. Not topology, not path or isolation input, not a Worksheet decision. A blocked candidate is not "
               "evidence of disconnection and a listed candidate is not evidence of connection.")


def review_id(source_sha256: str, kind: str, ports=(), strokes=(), junctions=()) -> str:
    basis = json.dumps([VERSION, source_sha256, kind, sorted(map(str, ports)), sorted(map(str, strokes)), sorted(map(str, junctions))], separators=(",", ":"))
    return "rvw-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


def build_ledger(items: list[dict], source_sha256: str) -> dict:
    """Ledger from stored engineering items (``RELATION`` and ``CONFLICT``). Pure; the items are not changed."""
    entries: dict[str, dict] = {}
    for it in items:
        kind = it.get("item_kind")
        if kind == "CONFLICT":
            c = it["conflict"]
            rid = review_id(source_sha256, "BLOCKED_PORT_KIND_MISMATCH", c.get("ports", []), c.get("stroke_ids", []))
            entries.setdefault(rid, {"review_id": rid, "candidate_kind": "BLOCKED_PORT_KIND_MISMATCH", "page": it.get("page"),
                                     "ports": sorted(c.get("ports", [])), "port_kinds": c.get("port_kinds", []), "stroke_ids": c.get("stroke_ids", []),
                                     "junction_ids": [], "source_item_ids": [], "reasons": [c.get("kind"), c.get("note")]})["source_item_ids"].append(it["item_id"])
        elif kind == "RELATION":
            r = it["relation"]
            ev = r.get("evidence") if isinstance(r.get("evidence"), dict) else {}
            alt = ev.get("junction_ids_with_alternatives") or []
            if alt:
                ports = [p for p in (r.get("from_port"), r.get("to_port")) if p]
                rid = review_id(source_sha256, "AMBIGUOUS_CROSSING", ports, ev.get("stroke_ids", []), alt)
                entries.setdefault(rid, {"review_id": rid, "candidate_kind": "AMBIGUOUS_CROSSING", "page": it.get("page") or r.get("page"), "ports": sorted(ports),
                                         "port_kinds": [], "stroke_ids": ev.get("stroke_ids", []), "junction_ids": sorted(alt), "source_item_ids": [],
                                         "reasons": ["the drawn path passes crossings that may be read as joined or separate", ev.get("path_status")]})["source_item_ids"].append(it["item_id"])
    rows = []
    for rid in sorted(entries):
        e = entries[rid]
        e.update({"namespace": source_sha256[:16], "source_sha256": source_sha256, "state": "UNRESOLVED", "decided_by": None,
                  "usable_for_path_queries": False, "in_accepted_topology": False, "blocked_is_not_disconnected": True,
                  "source_item_ids": sorted(set(e["source_item_ids"])), "reasons": [x for x in e["reasons"] if x]})
        rows.append(e)
    return {"schema": "pid-reader-connection-review-ledger-v1", "version": VERSION, "source_sha256": source_sha256, "entries": rows,
            "counts": {"entries": len(rows), "by_kind": _by(rows, "candidate_kind")}, "note": LEDGER_NOTE}


def _by(rows, key):
    out: dict[str, int] = {}
    for r in rows:
        out[r[key]] = out.get(r[key], 0) + 1
    return dict(sorted(out.items()))


def apply_decisions(db, ledger: dict) -> dict:
    """Set each entry's ``state`` from the latest recorded decision (``STALE`` if made for a different source hash). Read-only."""
    for e in ledger["entries"]:
        last = None
        for d in istore.decisions_for(db, e["review_id"]):
            last = d
        if last is None:
            continue
        e["decided_by"] = last["actor"]
        e["decision_reason"] = last["reason"]
        e["state"] = "STALE" if last["source_sha256"] != e["source_sha256"] else STATE_MAP.get(last["decision"], "UNRESOLVED")
    ledger["counts"]["by_state"] = _by(ledger["entries"], "state")
    return ledger


def ledger_for_run(db, extraction_id: str, run_id: str | None = None) -> dict:
    """Ledger of a stored run with human decisions applied. Reads only."""
    run = istore.latest_run(db, extraction_id) if run_id is None else {"run_id": run_id}
    if run is None:
        raise ValueError("No analysis run is stored for this drawing")
    sha = db.export_extraction(extraction_id)["document"]["sha256"]
    return apply_decisions(db, build_ledger(istore.list_items(db, run["run_id"]), sha))


def record_review(db, extraction_id: str, entry_review_id: str, *, actor: str, decision: str, reason: str) -> str:
    """Append a named human decision about one ledger entry. The id must belong to this drawing's current ledger; nothing becomes topology."""
    ledger = ledger_for_run(db, extraction_id)
    if entry_review_id not in {e["review_id"] for e in ledger["entries"]}:
        raise KeyError("Unknown review id for this drawing revision")
    if decision not in STATE_MAP:
        raise ValueError("Decision must be ACCEPTED_AS_READING, REJECTED, IGNORED or NEEDS_REVIEW")
    return istore.add_decision(db, extraction_id, entry_review_id, actor=actor, decision=decision, reason=reason,
                               new_value={"ledger": VERSION, "candidate_only": True})


def held_relationship_ids(snapshot: dict) -> set[str]:
    """Relationships of a snapshot that carry an unresolved alternative reading: callers that need *only* clean proposals exclude these."""
    return {u["id"][4:] for u in snapshot.get("unresolved", []) if u["id"].startswith("unr-") and any(r["id"] == u["id"][4:] for r in snapshot.get("relationships", []))}


def clean_relationships(snapshot: dict) -> list[dict]:
    """Snapshot relationships without the held (ambiguous) ones. The ledger candidates themselves are never relationships."""
    held = held_relationship_ids(snapshot)
    return [r for r in snapshot.get("relationships", []) if r["id"] not in held]
