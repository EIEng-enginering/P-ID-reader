"""WPU-16: gold validation, agreement, scoring with denominators, silent misses, reserved-split guard."""
from __future__ import annotations

import copy
import json

import pytest

pytest.importorskip("jsonschema")
from pid_reader.engineering import gold_scoring as gs

SHA = "a" * 64


def box(x, y, w=0.04, h=0.03):
    return {"x0": x, "y0": y, "x1": x + w, "y1": y + h}


def gold(objects, edges=(), regions=(), split="DEV", annotators=("ann1",), status="UNREVIEWED"):
    return {"schema_version": "benchmark-gold-v1", "drawing_sha256": SHA, "split": split, "annotator_ids": list(annotators), "adjudication_status": status,
            "objects": [{"id": i, "page_index": 0, "kind": k, "bbox": b, "tag": t, "review_state": s} for i, k, b, t, s in objects],
            "edges": [{"from_id": a, "to_id": b, "kind": "PIPE", "edge_status": s} for a, b, s in edges],
            "regions": [{"page_index": 0, "bbox": b, "reading_status": s} for b, s in regions]}


def snapshot(preds, rels=(), unprocessed=(), sha=SHA):
    evidence, entities = [], []
    for i, (eid, kind, b, tag, cls) in enumerate(preds):
        evidence.append({"id": f"ev{eid}", "page_index": 0, "bbox": b})
        entities.append({"id": eid, "kind": kind, "tag": tag, "classification": cls, "source_evidence_ids": [f"ev{eid}"]})
    return {"drawings": [{"sha256": sha}], "evidence": evidence, "entities": entities,
            "relationships": [{"type": "DRAWN_CONNECTS", "from_entity_id": a, "to_entity_id": b} for a, b in rels],
            "quality": {"unprocessed_regions": [{"drawing_id": "d", "page_index": 0, "bbox": b, "reason": "x"} for b in unprocessed]}}


V = "GOLD_VERIFIED"
BASE_OBJECTS = [("g1", "VALVE", box(.1, .1), "HV-1", V), ("g2", "VALVE", box(.3, .1), "HV-2", V), ("g3", "INSTRUMENT", box(.5, .5), "PIT-1", V), ("g4", "EQUIPMENT", box(.7, .7, .1, .1), "V-1", V)]


# ---------------------------------------------------------------- validation
def test_valid_gold_passes_and_extras_fail():
    assert gs.validate_gold(gold(BASE_OBJECTS)) == []
    bad = gold(BASE_OBJECTS)
    bad["objects"][0]["confidence"] = 0.9
    assert gs.validate_gold(bad)


def test_cross_checks():
    g = gold(BASE_OBJECTS, edges=[("g1", "nope", "GOLD_CONNECTED")])
    assert any("endpoint" in e for e in gs.validate_gold(g))
    g = gold(BASE_OBJECTS + [("g1", "VALVE", box(.9, .9), None, V)])
    assert any("duplicate" in e for e in gs.validate_gold(g))
    g = gold(BASE_OBJECTS, status="ADJUDICATED", annotators=("solo",))
    assert any("two named annotators" in e for e in gs.validate_gold(g))


# ---------------------------------------------------------------- metrics and denominators
def test_perfect_prediction_gives_full_counts_with_intervals():
    preds = [("p1", "VALVE", box(.1, .1), "HV-1", "GATE_VALVE"), ("p2", "VALVE", box(.3, .1), "HV-2", "GATE_VALVE"), ("p3", "INSTRUMENT", box(.5, .5), "PIT-1", "X"),
             ("p4", "EQUIPMENT", box(.7, .7, .1, .1), "V-1", "PRESSURE_VESSEL")]
    r = gs.score(gold(BASE_OBJECTS), snapshot(preds))
    v = r["classes"]["VALVE"]
    assert v["TP"] == 2 and v["FP"] == 0 and v["FN"] == 0 and v["recall"]["denominator"] == 2 and v["recall"]["value"] == 1.0
    assert v["recall"]["ci95"][0] < 1.0                                   # two samples never certify 100 %
    assert r["tag_attachment"]["correct"]["value"] == 1.0 and r["silent_misses"]["silent"] == 0


def test_missing_and_spurious_objects_count_as_fn_and_fp():
    preds = [("p1", "VALVE", box(.1, .1), "HV-1", "G"), ("px", "VALVE", box(.9, .1), None, "G")]
    r = gs.score(gold(BASE_OBJECTS), snapshot(preds))
    v = r["classes"]["VALVE"]
    assert (v["TP"], v["FP"], v["FN"]) == (1, 1, 1) and v["precision"]["value"] == 0.5 and v["recall"]["value"] == 0.5
    assert r["classes"]["INSTRUMENT"]["FN"] == 1 and r["classes"]["INSTRUMENT"]["recall"]["value"] == 0.0


def test_zero_denominators_are_none_never_one_hundred_percent():
    r = gs.score(gold([]), snapshot([]))
    assert r["classes"] == {} and r["tag_attachment"]["correct"]["value"] is None and r["silent_misses"]["silent_miss_rate"]["value"] is None
    assert gs.wilson(0, 0) is None and gs._ratio(0, 0)["value"] is None


def test_near_miss_wrong_class_is_a_failure_on_both_sides():
    preds = [("p1", "INSTRUMENT", box(.1, .1), "HV-1", "X")]                   # right place, wrong kind
    r = gs.score(gold([BASE_OBJECTS[0]]), snapshot(preds))
    assert r["classes"]["VALVE"]["FN"] == 1 and r["classes"]["VALVE"]["near_miss"] == 1 and r["classes"]["INSTRUMENT"]["FP"] == 1
    assert r["class_confusions"][0]["predicted_kind"] == "INSTRUMENT"


def test_wrong_tag_on_the_right_symbol_is_not_credited():
    preds = [("p1", "VALVE", box(.1, .1), "HV-9", "G"), ("p2", "VALVE", box(.3, .1), None, "G")]
    r = gs.score(gold(BASE_OBJECTS[:2]), snapshot(preds))
    t = r["tag_attachment"]
    assert t["wrong_tag"] == 1 and t["missing_tag"] == 1 and t["correct"]["numerator"] == 0 and t["correct"]["denominator"] == 2


def test_tag_comparison_ignores_formatting_only():
    r = gs.score(gold([BASE_OBJECTS[0]]), snapshot([("p1", "VALVE", box(.1, .1), "hv 1", "G")]))
    assert r["tag_attachment"]["correct"]["numerator"] == 1


def test_predictions_in_unannotated_regions_are_unscored_not_false_positives():
    preds = [("p1", "VALVE", box(.1, .1), "HV-1", "G"), ("p2", "VALVE", box(.85, .85), None, "G")]
    r = gs.score(gold([BASE_OBJECTS[0]], regions=[(box(.8, .8, .2, .2), "UNANNOTATED")]), snapshot(preds))
    assert r["classes"]["VALVE"]["FP"] == 0 and r["classes"]["VALVE"]["unscored_predictions"] == 1


def test_ambiguous_gold_is_excluded_from_recall_but_counted():
    g = gold([BASE_OBJECTS[0], ("g9", "VALVE", box(.6, .1), None, "GOLD_AMBIGUOUS"), ("g8", "VALVE", box(.6, .3), None, "NOT_LEGIBLE")])
    r = gs.score(g, snapshot([("p1", "VALVE", box(.1, .1), "HV-1", "G")]))
    assert r["classes"]["VALVE"]["recall"]["denominator"] == 1 and r["classes"]["VALVE"]["ambiguous_gold"] == 1
    assert r["gold_counts"]["ambiguous"] == 1 and r["gold_counts"]["not_legible"] == 1


# ---------------------------------------------------------------- silent vs flagged misses
def test_unflagged_miss_is_silent_and_flagged_miss_is_not():
    g = gold(BASE_OBJECTS[:2])
    r = gs.score(g, snapshot([("p1", "VALVE", box(.1, .1), "HV-1", "G")]))
    assert r["silent_misses"]["silent_ids"] == ["g2"] and r["silent_misses"]["silent_miss_rate"]["denominator"] == 2
    r2 = gs.score(g, snapshot([("p1", "VALVE", box(.1, .1), "HV-1", "G")], unprocessed=[box(.25, .05, .2, .2)]))
    assert r2["silent_misses"]["silent"] == 0 and r2["silent_misses"]["flagged_ids"] == ["g2"]


def test_withheld_class_symbol_over_a_miss_counts_as_flagged():
    r = gs.score(gold([BASE_OBJECTS[0]]), snapshot([("p1", "UNCLASSIFIED_SYMBOL", box(.1, .1), None, "UNKNOWN")]))
    assert r["silent_misses"]["silent"] == 0 and r["classes"]["VALVE"]["FN"] == 1


def test_non_critical_kinds_are_not_silent_miss_material():
    g = gold([("g1", "ANNOTATION", box(.1, .1), None, V)])
    assert gs.score(g, snapshot([]))["silent_misses"]["critical_gold_total"] == 0


# ---------------------------------------------------------------- connectivity
def conn_gold(status="GOLD_CONNECTED"):
    return gold(BASE_OBJECTS[:2], edges=[("g1", "g2", status)])


PREDS2 = [("p1", "VALVE", box(.1, .1), "HV-1", "G"), ("p2", "VALVE", box(.3, .1), "HV-2", "G")]


def test_gold_connection_found_is_recall_and_missed_is_fn():
    assert gs.score(conn_gold(), snapshot(PREDS2, rels=[("p1", "p2")]))["connectivity"]["recall"]["numerator"] == 1
    assert gs.score(conn_gold(), snapshot(PREDS2))["connectivity"]["recall"]["value"] == 0.0


def test_wrong_join_of_gold_not_connected_is_a_critical_false_connection():
    r = gs.score(conn_gold("GOLD_NOT_CONNECTED"), snapshot(PREDS2, rels=[("p1", "p2")]))
    assert r["connectivity"]["critical_false_connections"] == 1
    assert gs.score(conn_gold("GOLD_NOT_CONNECTED"), snapshot(PREDS2))["connectivity"]["critical_false_connections"] == 0


def test_predicted_edge_with_no_gold_judgement_is_unjudged_not_false():
    r = gs.score(gold(BASE_OBJECTS[:2]), snapshot(PREDS2, rels=[("p1", "p2")]))
    assert r["connectivity"]["unjudged_predicted_edges"] == 1 and r["connectivity"]["critical_false_connections"] == 0


# ---------------------------------------------------------------- governance
def test_final_reserved_gold_is_refused_unless_explicitly_allowed_and_is_logged(tmp_path):
    g = gold(BASE_OBJECTS, split="FINAL_RESERVED")
    with pytest.raises(gs.ReservedSplitError):
        gs.score(g, snapshot([]))
    log = tmp_path / "final_access.log"
    gs.score(g, snapshot([]), allow_final=True, access_log=log, stratum="vector")
    assert json.loads(log.read_text(encoding="utf-8").splitlines()[0])["stratum"] == "vector"


def test_scoring_refuses_a_snapshot_of_different_bytes():
    with pytest.raises(ValueError, match="different drawing bytes"):
        gs.score(gold(BASE_OBJECTS), snapshot([], sha="b" * 64))


def test_accuracy_claim_needs_adjudicated_independent_gold_with_two_annotators():
    syn = gs.score(gold(BASE_OBJECTS), snapshot([]))
    assert syn["claims"]["accuracy_claim_allowed"] is False and "REGRESSION_ONLY" in syn["claims"]["basis"]
    one = gs.score(gold(BASE_OBJECTS, split="REAL_INDEPENDENT"), snapshot([]))
    assert one["claims"]["accuracy_claim_allowed"] is False
    ok = gs.score(gold(BASE_OBJECTS, split="REAL_INDEPENDENT", annotators=("a", "b"), status="ADJUDICATED"), snapshot([]))
    assert ok["claims"]["accuracy_claim_allowed"] is True


def test_calibration_is_not_reported_without_an_id():
    assert gs.score(gold(BASE_OBJECTS), snapshot([]))["calibration"]["status"] == "NOT_APPLICABLE_UNCALIBRATED"
    assert gs.score(gold(BASE_OBJECTS), snapshot([]), calibration_id="cal-1")["calibration"]["calibration_id"] == "cal-1"


# ---------------------------------------------------------------- agreement and pooling
def test_agreement_flags_disagreements_for_adjudication():
    a = gold(BASE_OBJECTS[:3], annotators=("a",))
    b = gold([BASE_OBJECTS[0], ("h2", "VALVE", box(.3, .1), "HV-3", V), ("h5", "INSTRUMENT", box(.2, .8), None, V)], annotators=("b",))
    r = gs.agreement(a, b)
    assert r["objects_matched"] == 2 and r["tag_disagreements"] and r["only_in_first"] == ["g3"] and r["only_in_second"] == ["h5"] and r["needs_adjudication"] is True
    assert gs.agreement(a, copy.deepcopy(a))["needs_adjudication"] is False
    with pytest.raises(ValueError):
        gs.agreement(a, {**b, "drawing_sha256": "c" * 64})


def test_pooling_recomputes_ratios_from_counts_and_keeps_strata_apart():
    r1 = gs.score(gold(BASE_OBJECTS[:2]), snapshot([PREDS2[0]]), stratum="vector")
    r2 = gs.score(gold(BASE_OBJECTS[:2]), snapshot(PREDS2), stratum="scan")
    agg = gs.aggregate([r1, r2])
    rows = {(x["stratum"], x["class"]): x for x in agg["rows"]}
    assert rows[("vector", "VALVE")]["recall"]["value"] == 0.5 and rows[("scan", "VALVE")]["recall"]["value"] == 1.0
    assert agg["silent_miss_rate"]["denominator"] == 4 and agg["silent_miss_rate"]["numerator"] == 1
