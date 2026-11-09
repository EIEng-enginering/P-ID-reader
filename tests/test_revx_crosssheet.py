"""WPU-11: off-sheet evidence, identity proposals, revision reconciliation, stale reviews."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from revx_fixtures import sheet_pdf  # noqa: E402

from pid_reader.api import ReadParams, read_pid  # noqa: E402
from pid_reader.engineering import crosssheet as xs  # noqa: E402
from pid_reader.engineering import intelligence_store as istore  # noqa: E402
from pid_reader.engineering.project import ProjectStore  # noqa: E402

BOX = {"x0": .9, "y0": .4, "x1": .98, "y1": .42}
S1 = {"sheet_id": "s1", "drawing_ref": "0209-01-ML-02-001"}
S2 = {"sheet_id": "s2", "drawing_ref": "0209-01-ML-02-002"}


def line(text, page=1, attributes=None):
    return {"text": text, "bbox": BOX, "page": page, "word_ids": ["w"], **({"attributes": attributes} if attributes else {})}


def conns(l1, l2, **kw):
    a = xs.find_offpage_connectors([l1], "s1", S1["drawing_ref"])
    b = xs.find_offpage_connectors([l2], "s2", S2["drawing_ref"])
    return a + b


# ---------------------------------------------------------------- connectors from text
@pytest.mark.parametrize("text,direction,target,lref", [
    ("TO DWG 0209-01-ML-02-002 LINE 200-2", "TO", "0209-01-ML-02-002", "200-2"),
    ("FROM DRAWING 0209-01-ML-02-001 LINE 200-2", "FROM", "0209-01-ML-02-001", "200-2"),
    ("CONT'D ON SHEET 0209-01-ML-02-003", "CONTINUATION", "0209-01-ML-02-003", None)])
def test_offpage_connectors_are_read_from_text(text, direction, target, lref):
    c = xs.find_offpage_connectors([line(text)], "s1", "X")[0]
    assert c["direction"] == direction and c["target_drawing"] == target and c["line_ref"] == lref and c["review_state"] == "PROPOSED_UNVERIFIED"


@pytest.mark.parametrize("text", ["LINE 200-2", "NPS 20", "TO PUMP", "FROM TANK 5", "NOTE 3 SEE DETAIL"])
def test_plain_text_without_a_drawing_target_is_not_a_connector(text):
    assert xs.find_offpage_connectors([line(text)], "s1", "X") == []


# ---------------------------------------------------------------- matching: positive
def test_two_independent_observations_make_a_candidate():
    c = conns(line("TO DWG 0209-01-ML-02-002 LINE 200-2"), line("FROM DWG 0209-01-ML-02-001 LINE 200-2"))
    r = xs.match_connectors([S1, S2], c)
    assert len(r["candidates"]) == 1 and r["conflicts"] == []
    m = r["candidates"][0]
    assert m["status"] == "OFFPAGE_MATCH_CANDIDATE" and {"RECIPROCAL_DRAWING_REFERENCE", "LINE_REFERENCE_EQUAL", "DIRECTION_COMPLEMENTARY"} <= set(m["evidence_kinds"])
    assert m["review_state"] == "PROPOSED_UNVERIFIED" and not m["ambiguous"] and r["unmatched_connectors"] == []


def test_matching_is_order_independent_and_deterministic():
    c = conns(line("TO DWG 0209-01-ML-02-002 LINE 200-2"), line("FROM DWG 0209-01-ML-02-001 LINE 200-2"))
    assert xs.match_connectors([S1, S2], c) == xs.match_connectors([S2, S1], list(reversed(c)))


# ---------------------------------------------------------------- matching: negatives
def test_identical_line_text_alone_is_not_a_match():
    c = conns(line("TO DWG 0209-01-ML-02-099 LINE 200-2"), line("FROM DWG 0209-01-ML-02-098 LINE 200-2"))
    r = xs.match_connectors([S1, S2], c)
    assert r["candidates"] == [] and r["insufficient"][0]["status"] == "INSUFFICIENT" and "same line reference text only" in r["insufficient"][0]["reason"]


def test_reciprocal_reference_without_a_second_fact_is_insufficient():
    c = conns(line("TO DWG 0209-01-ML-02-002"), line("TO DWG 0209-01-ML-02-001"))        # both say TO: not complementary; no line refs
    r = xs.match_connectors([S1, S2], c)
    assert r["candidates"] == [] and r["insufficient"] and "no second compatible fact" in r["insufficient"][0]["reason"]


def test_incompatible_attributes_conflict_and_are_not_merged():
    c = conns(line("TO DWG 0209-01-ML-02-002 LINE 200-2", attributes={"size_in": 20, "service": "ETHANE"}),
              line("FROM DWG 0209-01-ML-02-001 LINE 200-2", attributes={"size_in": 30, "service": "ETHANE"}))
    r = xs.match_connectors([S1, S2], c)
    assert r["candidates"] == [] and r["conflicts"][0]["status"] == "CONFLICTING" and r["conflicts"][0]["attributes"] == ["size_in"]
    assert r["conflicts"][0]["values"]["size_in"] == [20, 30]


def test_same_sheet_connectors_never_pair():
    both = xs.find_offpage_connectors([line("TO DWG 0209-01-ML-02-002 LINE 200-2"), line("FROM DWG 0209-01-ML-02-002 LINE 200-2")], "s1", S1["drawing_ref"])
    assert xs.match_connectors([S1, S2], both)["candidates"] == []


def test_two_equally_good_candidates_are_flagged_ambiguous_with_alternatives():
    s3 = {"sheet_id": "s3", "drawing_ref": "0209-01-ML-02-002"}              # a duplicate sheet number: two possible partners
    a = xs.find_offpage_connectors([line("TO DWG 0209-01-ML-02-002 LINE 200-2")], "s1", S1["drawing_ref"])
    b = xs.find_offpage_connectors([line("FROM DWG 0209-01-ML-02-001 LINE 200-2")], "s2", S2["drawing_ref"])
    c = xs.find_offpage_connectors([line("FROM DWG 0209-01-ML-02-001 LINE 200-2", page=2)], "s3", s3["drawing_ref"])
    r = xs.match_connectors([S1, S2, s3], a + b + c)
    assert len(r["candidates"]) == 2 and all(m["ambiguous"] and m["alternatives"] for m in r["candidates"])


def test_unmatched_connector_is_listed_not_dropped():
    c = conns(line("TO DWG 0209-01-ML-02-777 LINE 9-9"), line("FROM DWG 0209-01-ML-02-001 LINE 200-2"))
    r = xs.match_connectors([S1, S2], c)
    assert r["candidates"] == [] and len(r["unmatched_connectors"]) == 2


# ---------------------------------------------------------------- asset identity
def occ(oid, sheet, tag, kind="VALVE", corr=()):
    return {"occurrence_id": oid, "sheet_id": sheet, "tag": tag, "entity_kind": kind, "corroboration": list(corr)}


def test_same_tag_on_two_sheets_is_not_merged_without_independent_evidence():
    r = xs.propose_asset_identities([occ("o1", "s1", "HV-101"), occ("o2", "s2", "HV-101")])
    assert r["proposals"] == [] and r["tag_only_not_merged"][0]["status"] == "TAG_ONLY_NOT_MERGED"


def test_same_tag_with_shared_corroboration_gives_a_proposal_not_a_fact():
    r = xs.propose_asset_identities([occ("o1", "s1", "HV-101", corr=["SAME_OFFPAGE_NEIGHBOUR", "SAME_ATTRIBUTE_VALUES"]),
                                     occ("o2", "s2", "HV-101", corr=["SAME_OFFPAGE_NEIGHBOUR"])])
    p = r["proposals"][0]
    assert p["relation"] == "PROPOSED_SAME_AS" and p["evidence_beyond_tag"] == ["SAME_OFFPAGE_NEIGHBOUR"] and p["status"] == "PROPOSED_UNVERIFIED"


def test_same_tag_different_kinds_is_a_conflict():
    r = xs.propose_asset_identities([occ("o1", "s1", "P-101", "EQUIPMENT", ["X"]), occ("o2", "s2", "P-101", "VALVE", ["X"])])
    assert r["proposals"] == [] and r["conflicts"][0]["kind"] == "SAME_TAG_DIFFERENT_KIND"


def test_tag_formatting_differences_do_not_hide_a_match_but_single_sheet_never_matches():
    assert xs.propose_asset_identities([occ("o1", "s1", "HV 101", corr=["A"]), occ("o2", "s2", "hv-101", corr=["A"])])["proposals"]
    assert xs.propose_asset_identities([occ("o1", "s1", "HV-101", corr=["A"]), occ("o2", "s1", "HV-101", corr=["A"])]) == {
        "proposals": [], "tag_only_not_merged": [], "conflicts": []}


# ---------------------------------------------------------------- revision reconciliation
def snap(sha, model, items):
    return {"source_sha256": sha, "model_generation": model, "occurrences": [
        {"id": i, "page": 1, "bbox": {"x0": x, "y0": y, "x1": x + .02, "y1": y + .02}, "graphical_family": "VALVE", "engineering_class": c,
         "tag": {"text": t} if t else None} for i, x, y, c, t in items]}


def test_new_detection_on_an_unchanged_pdf_is_an_interpretation_diff_never_a_drawing_change():
    old = snap("a" * 64, "0.17", [("o1", .1, .1, "GATE_VALVE", "HV-1")])
    new = snap("a" * 64, "0.18", [("o1", .1, .1, "GATE_VALVE", "HV-1"), ("o2", .5, .5, "BALL_VALVE", None)])
    d = xs.diff_interpretations(old, new)
    assert d["label"] == "INTERPRETATION_DIFF" and d["source_diff"] is False and d["drawing_change_asserted"] is False
    assert d["added"] == ["o2"] and d["counts"]["added"] == 1


def test_changed_pdf_with_same_reader_is_a_source_change_candidate():
    old = snap("a" * 64, "0.17", [("o1", .1, .1, "GATE_VALVE", "HV-1"), ("o3", .8, .8, "CHECK_VALVE", None)])
    new = snap("b" * 64, "0.17", [("o1", .1, .1, "GLOBE_VALVE", "HV-1")])
    d = xs.diff_interpretations(old, new)
    assert d["label"] == "SOURCE_REVISION_CHANGE_CANDIDATE" and d["source_diff"] is True and d["drawing_change_asserted"] is False
    assert d["removed"] == ["o3"] and len(d["changed"]) == 1


def test_both_changed_is_mixed_and_says_it_cannot_attribute():
    d = xs.diff_interpretations(snap("a" * 64, "0.17", []), snap("b" * 64, "0.18", [("o", .1, .1, "GATE_VALVE", None)]))
    assert d["label"] == "SOURCE_AND_MODEL_CHANGE_MIXED" and "cannot be attributed" in d["note"]


def test_identical_snapshots_have_no_differences():
    s = snap("a" * 64, "0.17", [("o1", .1, .1, "GATE_VALVE", "HV-1")])
    d = xs.diff_interpretations(s, s)
    assert d["counts"] == {"added": 0, "removed": 0, "changed": 0, "unchanged": 1} and d["interpretation_diff"] is False


# ---------------------------------------------------------------- stale reviews and persistence
def test_reviews_under_another_model_or_source_are_stale_with_reasons(tmp_path):
    pdf = sheet_pdf(body_words=60)
    with ProjectStore(tmp_path / "p.sqlite") as db:
        eid = db.add_extraction(read_pid(pdf, ReadParams(), filename="a.pdf"), source_pdf_bytes=pdf)
        istore.add_decision(db, eid, "it-1", actor="R. Reviewer", decision="ACCEPTED_AS_READING", reason="ok", model_generation="old-gen")
        istore.add_decision(db, eid, "it-2", actor="R. Reviewer", decision="REJECTED", reason="no")
        stale = xs.flag_stale_reviews(db, eid)
        assert [s["item_id"] for s in stale] == ["it-1"] and stale[0]["state"] == "STALE" and stale[0]["reasons"] == ["MODEL_CHANGED"]
        assert xs.flag_stale_reviews(db, eid, "old-gen")[0]["item_id"] == "it-2"


def test_crosssheet_results_are_stored_append_only_and_idempotent(tmp_path):
    pdf = sheet_pdf(body_words=60)
    c = conns(line("TO DWG 0209-01-ML-02-002 LINE 200-2"), line("FROM DWG 0209-01-ML-02-001 LINE 200-2"))
    result = xs.match_connectors([S1, S2], c)
    result["identity"] = xs.propose_asset_identities([occ("o1", "s1", "HV-101", corr=["A"]), occ("o2", "s2", "HV-101", corr=["A"])])
    with ProjectStore(tmp_path / "p.sqlite") as db:
        eid = db.add_extraction(read_pid(pdf, ReadParams(), filename="a.pdf"), source_pdf_bytes=pdf)
        rid = xs.record_crosssheet(db, eid, result)
        assert xs.record_crosssheet(db, eid, result) == rid
        items = istore.list_items(db, rid)
        assert {i["item_kind"] for i in items} == {"RELATION", "ASSET_HYPOTHESIS"} and all(i["review_state"] != "ACCEPTED_AS_READING" for i in items)
        assert db.verify_audit_chain()
