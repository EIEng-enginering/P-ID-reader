"""Strict scoring policy: no folding, no substitution, omissions counted, draft references labelled as drafts."""
import pytest

from pid_reader.engineering.longterm import scoring as S


def box(x0, y0, x1, y1):
    return dict(x0=x0, y0=y0, x1=x1, y1=y1)


def ref(items, status="DRAFT", **extra):
    return dict(schema="pid-reference-v2", status=status, items=items, **extra)


def item(i, text, b, state="READABLE", **kw):
    return dict(id=i, text=text, bbox=b, state=state, adjudication="ADJUDICATED", category=kw.pop("category", "LINE"), **kw)


@pytest.mark.parametrize("sel,truth", [("DR-22202-33.4-C3S-xxS", "DR-22202-33.4-C3S-XXS"), ("GHS-C35", "GHS-C3S"), ("O0", "00"), ("33,4", "33.4"),
                                      ("FT", "FY"), ("1I", "II"), ("DR", "OR")])
def test_no_folding_or_substitution_is_ever_applied(sel, truth):
    assert S.classify(sel, [], truth) == "WRONG"


def test_formatting_only_difference_is_labelled_separately_from_strict():
    assert S.classify("GHS -22203\u201316 8.3", [], "GHS-22203-168.3") == "CORRECT_SELECTED_FORMAT_ONLY"
    assert S.classify("GHS-22203-168.3", [], "GHS-22203-168.3") == "CORRECT_SELECTED"


def test_correct_alternative_with_a_wrong_selection_is_a_conflict_not_a_hit():
    assert S.classify("GS-1", ["HPF-1", "GHS-1"], "GHS-1") == "CORRECT_ALTERNATIVE_CONFLICTING"
    assert S.classify("PF-1", [], "HPF-1") == "INCOMPLETE"


def test_omissions_budget_and_extras_are_reported_not_hidden():
    r = ref([item("a", "AB-1", box(.1, .1, .2, .15)), item("b", "CD-2", box(.3, .1, .4, .15)), item("c", "EF-3", box(.5, .1, .6, .15))],
            exhaustive_regions=[dict(bbox=box(0, 0, 1, .3))])
    preds = [dict(bbox=box(.1, .1, .2, .15), text="AB-1", selected=True), dict(bbox=box(.7, .2, .8, .25), text="ZZ")]
    out = S.score(r, preds, omitted_by_budget={"b"})
    assert out["strict_exact"] == 1 and out["outcomes"]["NOT_ATTEMPTED_BUDGET"] == 1 and out["outcomes"]["MISSED"] == 1
    assert out["wrong_extra_detections_in_exhaustive_regions"] == 1
    assert out["cer_with_omissions"] > out["cer_attempted"] == 0
    assert out["reference_authority"] == "DRAFT_DIAGNOSTIC" and "DIAGNOSTIC" in out["claim"]


def test_extras_are_not_counted_without_a_declared_exhaustive_region():
    r = ref([item("a", "AB-1", box(.1, .1, .2, .15))])
    out = S.score(r, [dict(bbox=box(.1, .1, .2, .15), text="AB-1"), dict(bbox=box(.7, .7, .8, .8), text="junk")])
    assert out["wrong_extra_detections_in_exhaustive_regions"] is None


def test_selection_never_uses_the_reference_text():
    r = ref([item("a", "GHS-1", box(.1, .1, .2, .15))])
    wrong_high = dict(bbox=box(.1, .1, .2, .15), text="GS-1", raw_score=.9)
    right_low = dict(bbox=box(.1, .1, .2, .15), text="GHS-1", raw_score=.1)
    out = S.score(r, [right_low, wrong_high])
    assert out["rows"][0]["selected"] == "GS-1" and out["rows"][0]["outcome"] == "CORRECT_ALTERNATIVE_CONFLICTING"
    flagged = S.score(r, [dict(right_low, selected=True), wrong_high])
    assert flagged["rows"][0]["outcome"] == "CORRECT_SELECTED"


def test_abstention_on_unreadable_and_non_text_regions():
    r = ref([item("u", None, box(.1, .1, .2, .15), state="UNREADABLE"), dict(id="n", state="NOT_TEXT", bbox=box(.5, .5, .6, .6), category="STAMP")])
    out = S.score(r, [dict(bbox=box(.1, .1, .2, .15), text="FAKE1"), dict(bbox=box(.5, .5, .6, .6), text="")])
    assert out["abstention"]["false_readings"] == 1 and out["abstention"]["correct"] == 1


def test_a_prediction_is_matched_to_at_most_one_item():
    r = ref([item("a", "AB-1", box(.1, .1, .2, .15)), item("b", "AB-1", box(.12, .1, .22, .15))])
    owner = S.match(r["items"], [dict(bbox=box(.1, .1, .2, .15), text="AB-1")])
    assert len(owner) == 1


def test_reference_validation_marks_non_adjudicated_as_draft():
    good = ref([item("a", "AB-1", box(.1, .1, .2, .15))], status="ADJUDICATED")
    assert S.validate_reference(good)[0] == "ADJUDICATED_DEVELOPMENT"
    assert S.validate_reference(ref([item("a", "AB-1", box(.1, .1, .2, .15))]))[0] == "DRAFT_DIAGNOSTIC"
    bad = ref([dict(id="x", state="READABLE", bbox=box(0, 0, 1, 1))], status="ADJUDICATED")
    assert S.validate_reference(bad)[0] == "DRAFT_DIAGNOSTIC" and S.validate_reference(bad)[1]
    with pytest.raises(ValueError):
        S.score(bad, [])
