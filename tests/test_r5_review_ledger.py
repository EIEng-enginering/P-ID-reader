"""R5 update, change 4: review ledger of ambiguous / blocked connection candidates. Never topology."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from revx_fixtures import sheet_pdf  # noqa: E402

from pid_reader.api import ReadParams, read_pid  # noqa: E402
from pid_reader.engineering import connection_review as cr  # noqa: E402
from pid_reader.engineering import intelligence_store as istore  # noqa: E402
from pid_reader.engineering.project import ProjectStore  # noqa: E402

SHA = "c" * 64


def conflict(item_id="cfl-1", ports=("pn-a", "pn-b"), strokes=("s1", "s2")):
    return {"item_id": item_id, "item_kind": "CONFLICT", "page": 1, "conflict": {"conflict_id": item_id, "kind": "PORT_KIND_MISMATCH", "ports": list(ports),
            "port_kinds": ["INSTRUMENT_PORT", "NOZZLE"], "stroke_ids": list(strokes), "note": "a drawn line reaches incompatible port kinds; no connection is proposed"}}


def relation(item_id="edge-1", alt=("j1", "j2"), ports=("pn-c", "pn-d"), strokes=("s3",)):
    return {"item_id": item_id, "item_kind": "RELATION", "page": 1, "relation": {"edge_id": item_id, "edge_kind": "DRAWN_CONNECTS", "from_port": ports[0], "to_port": ports[1],
            "from_occurrence": "o1", "to_occurrence": "o2", "page": 1, "evidence": {"stroke_ids": list(strokes), "junction_ids_with_alternatives": list(alt),
            "path_status": "HAS_ALTERNATIVES" if alt else "CLEAN"}}}


def test_blocked_and_ambiguous_candidates_are_listed_with_reasons_and_evidence():
    led = cr.build_ledger([conflict(), relation(), relation("edge-clean", alt=())], SHA)
    kinds = {e["candidate_kind"] for e in led["entries"]}
    assert kinds == {"BLOCKED_PORT_KIND_MISMATCH", "AMBIGUOUS_CROSSING"} and len(led["entries"]) == 2     # a clean edge is not a review candidate
    b = next(e for e in led["entries"] if e["candidate_kind"] == "BLOCKED_PORT_KIND_MISMATCH")
    assert b["ports"] == ["pn-a", "pn-b"] and b["stroke_ids"] == ["s1", "s2"] and "PORT_KIND_MISMATCH" in b["reasons"]
    a = next(e for e in led["entries"] if e["candidate_kind"] == "AMBIGUOUS_CROSSING")
    assert a["junction_ids"] == ["j1", "j2"] and a["source_item_ids"] == ["edge-1"]


def test_entries_are_never_topology_and_say_blocked_is_not_disconnected():
    led = cr.build_ledger([conflict(), relation()], SHA)
    assert all(e["state"] == "UNRESOLVED" and e["usable_for_path_queries"] is False and e["in_accepted_topology"] is False
               and e["blocked_is_not_disconnected"] is True for e in led["entries"])
    assert "not evidence of disconnection" in led["note"] and "not evidence of connection" in led["note"]


def test_ids_are_namespaced_by_revision_and_stable_across_item_order_and_reruns():
    items = [conflict(), relation()]
    a = cr.build_ledger(items, SHA)
    b = cr.build_ledger(list(reversed(copy.deepcopy(items))), SHA)
    assert [e["review_id"] for e in a["entries"]] == [e["review_id"] for e in b["entries"]]
    other_rev = cr.build_ledger(items, "d" * 64)
    assert not ({e["review_id"] for e in a["entries"]} & {e["review_id"] for e in other_rev["entries"]})
    assert all(e["namespace"] == SHA[:16] for e in a["entries"])
    renamed = cr.build_ledger([conflict(item_id="cfl-other-run-id"), relation("edge-other-run-id")], SHA)       # item ids differ per run; observations do not
    assert [e["review_id"] for e in renamed["entries"]] == [e["review_id"] for e in a["entries"]]


def test_different_observations_get_different_ids_and_nothing_merges():
    led = cr.build_ledger([conflict(), conflict("cfl-2", ports=("pn-a", "pn-z")), conflict("cfl-3", strokes=("s1", "s9"))], SHA)
    assert len({e["review_id"] for e in led["entries"]}) == 3
    dup = cr.build_ledger([conflict(), conflict("cfl-1-again")], SHA)                 # the same observation seen twice is one candidate with both sources
    assert len(dup["entries"]) == 1 and dup["entries"][0]["source_item_ids"] == ["cfl-1", "cfl-1-again"]


@pytest.fixture()
def project(tmp_path):
    pdf = sheet_pdf(title=True)
    db = ProjectStore(tmp_path / "p.sqlite")
    eid = db.add_extraction(read_pid(pdf, ReadParams(), filename="a.pdf"), source_pdf_bytes=pdf)
    sha = db.export_extraction(eid)["document"]["sha256"]
    yield db, eid, sha
    db.close()


def record(db, eid, preset, items):
    return istore.record_run(db, eid, preset=preset, status="PARTIAL", outcomes=[], items=items, summary={}, config={"preset": preset})


def test_ledger_reads_a_stored_run_and_writes_nothing(project):
    db, eid, sha = project
    run = record(db, eid, "standard", [conflict(), relation()])
    before = db.db.execute("SELECT (SELECT count(*) FROM intelligence_decision),(SELECT count(*) FROM engineering_item),(SELECT count(*) FROM intelligence_run)").fetchone()
    led = cr.ledger_for_run(db, eid, run)
    after = db.db.execute("SELECT (SELECT count(*) FROM intelligence_decision),(SELECT count(*) FROM engineering_item),(SELECT count(*) FROM intelligence_run)").fetchone()
    assert tuple(before) == tuple(after) and len(led["entries"]) == 2 and led["source_sha256"] == sha


def test_a_human_decision_is_stored_append_only_survives_a_rerun_and_never_becomes_topology(project):
    db, eid, sha = project
    run1 = record(db, eid, "quick", [conflict(), relation()])
    rid = cr.ledger_for_run(db, eid, run1)["entries"][0]["review_id"]
    cr.record_review(db, eid, rid, actor="A. Reviewer", decision="REJECTED", reason="the line only passes behind the nozzle")
    run2 = record(db, eid, "standard", [conflict("cfl-rerun"), relation("edge-rerun")])      # a re-run produces new item ids
    assert run1 != run2
    led = cr.ledger_for_run(db, eid, run2)
    e = next(x for x in led["entries"] if x["review_id"] == rid)
    assert e["state"] == "REVIEWER_REJECTED" and e["decided_by"] == "A. Reviewer"
    assert e["usable_for_path_queries"] is False and e["in_accepted_topology"] is False
    cr.record_review(db, eid, rid, actor="B. Lead", decision="ACCEPTED_AS_READING", reason="seen on the markup")
    e2 = next(x for x in cr.ledger_for_run(db, eid, run2)["entries"] if x["review_id"] == rid)
    assert e2["state"] == "REVIEWER_ACCEPTED_AS_DRAWN" and e2["in_accepted_topology"] is False and e2["decided_by"] == "B. Lead"
    assert len(istore.decisions_for(db, rid)) == 2                                              # both decisions are kept
    with pytest.raises(Exception):
        db.db.execute("UPDATE intelligence_decision SET decision='IGNORED' WHERE item_id=?", (rid,))


def test_a_decision_for_another_source_hash_is_shown_as_stale(project):
    db, eid, sha = project
    run = record(db, eid, "standard", [conflict()])
    rid = cr.ledger_for_run(db, eid, run)["entries"][0]["review_id"]
    cr.record_review(db, eid, rid, actor="A", decision="REJECTED", reason="r")
    db.db.execute("DROP TRIGGER block_update_intelligence_decision")                           # simulate an old decision made under another source hash
    db.db.execute("UPDATE intelligence_decision SET source_sha256=? WHERE item_id=?", ("f" * 64, rid))
    assert cr.ledger_for_run(db, eid, run)["entries"][0]["state"] == "STALE"


def test_unknown_ids_and_bad_decisions_are_refused(project):
    db, eid, sha = project
    record(db, eid, "standard", [conflict()])
    with pytest.raises(KeyError):
        cr.record_review(db, eid, "rvw-" + "0" * 24, actor="A", decision="REJECTED", reason="r")
    rid = cr.ledger_for_run(db, eid)["entries"][0]["review_id"]
    with pytest.raises(ValueError):
        cr.record_review(db, eid, rid, actor="A", decision="RECLASSIFIED", reason="r")
    with pytest.raises(ValueError):
        cr.record_review(db, eid, rid, actor="  ", decision="REJECTED", reason="r")
    with pytest.raises(ValueError):
        cr.record_review(db, eid, rid, actor="A", decision="REJECTED", reason="")


def test_snapshot_helpers_keep_ambiguous_edges_out_of_clean_proposals():
    snap = {"relationships": [{"id": "e1"}, {"id": "e2"}, {"id": "e3"}], "unresolved": [{"id": "unr-e2"}, {"id": "unr-cfl-9"}, {"id": "unr-class-x"}]}
    assert cr.held_relationship_ids(snap) == {"e2"}
    assert [r["id"] for r in cr.clean_relationships(snap)] == ["e1", "e3"]
    assert "rvw-" not in json.dumps(snap)                                                      # ledger entries are never relationships
