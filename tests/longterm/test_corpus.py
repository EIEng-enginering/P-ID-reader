"""Corpus provenance: blind candidates, named human reviewers, adjudication, leakage checks and compatible exports."""
import json

import pytest
from PIL import Image

from pid_reader.engineering.longterm import corpus as C
from pid_reader.engineering.longterm import data as D
from pid_reader.engineering.longterm import scoring as S


def box(x0, y0, x1, y1):
    return dict(x0=x0, y0=y0, x1=x1, y1=y1)


def make(tmp_path, specs):
    """specs: [(id, split, family, source_bytes, bbox, colour)] -> (doc, sources)"""
    items, sources = [], {}
    for i, (cid, split, fam, src, bb, colour) in enumerate(specs):
        sha = C.hashlib.sha256(src).hexdigest()
        (tmp_path / f"{fam}.pdf").write_bytes(src)
        sources[sha] = tmp_path / f"{fam}.pdf"
        im = Image.new("L", (60, 20), 255)
        for x in range(colour, colour + 20):
            for y in range(5, 15):
                im.putpixel((x, y), 0)
        p = tmp_path / f"{cid}.png"
        im.save(p)
        items.append(dict(id=cid, split=split, family_id=fam, source_sha256=sha, page=1, bbox=bb, category="LINE_LABEL", crop_path=p.name,
                          crop_sha256=C.sha256_file(p), dhash=C.dhash(im)))
    return dict(schema=C.CANDIDATES_SCHEMA, items=items), sources


def review(name, role, mapping):
    return dict(schema=C.REVIEW_SCHEMA, reviewer=name, role=role, items={k: (dict(state="READABLE", text=v) if isinstance(v, str) else v) for k, v in mapping.items()})


@pytest.mark.parametrize("name", ["Claude", "GPT-5 reviewer", "RapidOCR", "auto script", "", "ab", "Anthropic Assistant"])
def test_software_like_or_blank_reviewer_names_are_refused(name):
    assert not C.reviewer_name_ok(name)
    with pytest.raises(ValueError):
        C.new_review(name, "FIRST", {})


def test_a_named_person_is_accepted():
    assert C.reviewer_name_ok("Jane Citizen") and C.new_review("Jane Citizen", "FIRST", {})["role"] == "FIRST"


def test_candidates_cannot_carry_a_reading_and_splits_cannot_leak(tmp_path):
    doc, _ = make(tmp_path, [("a", "TRAIN", "F1", b"%PDF-1", box(.1, .1, .2, .15), 5), ("b", "VALIDATION", "F1", b"%PDF-1", box(.5, .5, .6, .55), 30)])
    problems = C.validate_candidates(doc, root=tmp_path)
    assert any("family" in p and "leakage" in p for p in problems) and any("source" in p for p in problems)
    doc["items"][0]["ocr_text"] = "GHS-1"
    assert any("must not carry any reading" in p for p in C.validate_candidates(doc, root=tmp_path))


def test_reserved_final_split_is_refused(tmp_path):
    doc, _ = make(tmp_path, [("a", "TRAIN", "F1", b"%PDF-1", box(.1, .1, .2, .15), 5)])
    doc["items"][0]["split"] = "RESERVED_FINAL"
    assert any("RESERVED_FINAL" in p for p in C.validate_candidates(doc))


def test_overlapping_boxes_must_be_resolved_and_may_not_cross_splits(tmp_path):
    doc, _ = make(tmp_path, [("a", "TRAIN", "F1", b"%PDF-1", box(.1, .1, .3, .15), 5), ("b", "TRAIN", "F1", b"%PDF-1", box(.12, .1, .32, .15), 30)])
    assert any("duplicate_of" in p for p in C.validate_candidates(doc, root=tmp_path))
    doc["items"][1]["duplicate_of"] = "a"
    assert C.validate_candidates(doc, root=tmp_path) == []


def test_near_duplicate_crops_across_splits_are_flagged(tmp_path):
    doc, _ = make(tmp_path, [("a", "TRAIN", "F1", b"%PDF-1a", box(.1, .1, .2, .15), 5), ("b", "VALIDATION", "F2", b"%PDF-2b", box(.6, .6, .7, .65), 5)])
    doc["items"][1]["crop_sha256"] = "0" * 64
    assert any("near-duplicate" in p for p in C.validate_candidates(doc))


def test_crop_bytes_are_checked(tmp_path):
    doc, _ = make(tmp_path, [("a", "TRAIN", "F1", b"%PDF-1", box(.1, .1, .2, .15), 5)])
    (tmp_path / "a.png").write_bytes(b"changed")
    assert any("crop bytes differ" in p for p in C.validate_candidates(doc, root=tmp_path))


def test_adjudication_paths(tmp_path):
    doc, _ = make(tmp_path, [("t", "TRAIN", "F1", b"%PDF-1", box(.1, .1, .2, .15), 5), ("v1", "VALIDATION", "F2", b"%PDF-2", box(.1, .1, .2, .15), 30),
                             ("v2", "VALIDATION", "F2", b"%PDF-2", box(.5, .5, .6, .55), 40), ("v3", "VALIDATION", "F2", b"%PDF-2", box(.7, .1, .8, .15), 10)])
    first = review("Jane Citizen", "FIRST", {"t": "GHS-1", "v1": "AB-1", "v2": "CD-2", "v3": dict(state="UNREADABLE")})
    second = review("Omar Reviewer", "SECOND", {"v1": "AB-1", "v2": "CD-3", "v3": dict(state="READABLE", text="XX")})
    out = C.adjudicate(doc, first, second)
    assert out["t"]["adjudication"] == "SINGLE_REVIEWER" and out["v1"]["adjudication"] == "ADJUDICATED"
    assert out["v2"]["adjudication"] == "NEEDS_ADJUDICATION" and out["v3"]["adjudication"] == "NEEDS_ADJUDICATION"
    final = review("Pat Adjudicator", "ADJUDICATOR", {"v2": "CD-2"})
    out = C.adjudicate(doc, first, second, final)
    assert out["v2"]["adjudication"] == "ADJUDICATED" and out["v2"]["text"] == "CD-2" and "Pat Adjudicator" in out["v2"]["basis"]
    assert C.adjudicate(doc, first)["v1"]["adjudication"] == "AWAITING_SECOND_REVIEWER"


def test_second_reviewer_must_be_a_different_person_and_roles_are_checked(tmp_path):
    doc, _ = make(tmp_path, [("v1", "VALIDATION", "F2", b"%PDF-2", box(.1, .1, .2, .15), 30)])
    a = review("Jane Citizen", "FIRST", {"v1": "AB"})
    with pytest.raises(ValueError):
        C.adjudicate(doc, a, review("jane citizen", "SECOND", {"v1": "AB"}))
    with pytest.raises(ValueError):
        C.adjudicate(doc, a, review("Omar Reviewer", "FIRST", {"v1": "AB"}))


def test_exports_exclude_unresolved_items_and_are_accepted_by_the_trainer_and_scorer(tmp_path):
    doc, sources = make(tmp_path, [("t", "TRAIN", "F1", b"%PDF-1", box(.1, .1, .2, .15), 5), ("t2", "TRAIN", "F1", b"%PDF-1", box(.5, .5, .6, .55), 25),
                                   ("v1", "VALIDATION", "F2", b"%PDF-2", box(.1, .1, .2, .15), 30), ("v2", "VALIDATION", "F2", b"%PDF-2", box(.5, .5, .6, .55), 38)])
    first = review("Jane Citizen", "FIRST", {"t": "GHS-1", "t2": dict(state="UNREADABLE"), "v1": "AB-1", "v2": "CD-2"})
    second = review("Omar Reviewer", "SECOND", {"v1": "AB-1", "v2": "CD-9"})
    dec = C.adjudicate(doc, first, second)
    path, n = C.export_longterm_dataset(doc, dec, tmp_path, tmp_path / "ds", sources=sources)
    assert n == 2                                                  # t (single reviewer) and v1 (agreed); t2 unreadable, v2 unresolved
    train, _ = D.validate(path, purpose="train")
    val, _ = D.validate(path, purpose="validate")
    assert [r["id"] for r in train] == ["t"] and [r["id"] for r in val] == ["v1"]
    ref = C.export_reference_v2(doc, dec, split="VALIDATION")
    assert [i["id"] for i in ref["items"]] == ["v1"] and S.validate_reference(ref)[0] == "ADJUDICATED_DEVELOPMENT"


def test_readiness_counts_the_human_only_blockers(tmp_path):
    doc, _ = make(tmp_path, [("t", "TRAIN", "F1", b"%PDF-1", box(.1, .1, .2, .15), 5), ("v1", "VALIDATION", "F2", b"%PDF-2", box(.1, .1, .2, .15), 30)])
    out = C.readiness(doc, C.adjudicate(doc, review("Jane Citizen", "FIRST", {})))
    assert out["ready"] is False and out["per_split"]["TRAIN"]["reviewed"] == 0


def test_vertical_items_need_a_stated_direction_and_reviewers_must_agree_on_it(tmp_path):
    doc, sources = make(tmp_path, [("v", "VALIDATION", "F2", b"%PDF-2", box(.1, .1, .2, .15), 30)])
    doc["items"][0]["is_vertical"] = True
    no_dir = review("Jane Citizen", "FIRST", {"v": "DR-1"})
    with pytest.raises(ValueError, match="reading direction"):
        C.adjudicate(doc, no_dir)
    cw = review("Jane Citizen", "FIRST", {"v": dict(state="READABLE", text="DR-1", orientation="ROTATE_CW")})
    same = review("Omar Reviewer", "SECOND", {"v": dict(state="READABLE", text="DR-1", orientation="ROTATE_CW")})
    other = review("Omar Reviewer", "SECOND", {"v": dict(state="READABLE", text="DR-1", orientation="ROTATE_CCW")})
    assert C.adjudicate(doc, cw, same)["v"]["adjudication"] == "ADJUDICATED"
    assert C.adjudicate(doc, cw, other)["v"]["adjudication"] == "NEEDS_ADJUDICATION"


def test_export_turns_the_crop_by_the_reviewer_stated_direction(tmp_path):
    doc, sources = make(tmp_path, [("v", "TRAIN", "F1", b"%PDF-1", box(.1, .1, .2, .15), 5)])
    doc["items"][0]["is_vertical"] = True
    rev = review("Jane Citizen", "FIRST", {"v": dict(state="READABLE", text="DR-1", orientation="ROTATE_CW")})
    dec = C.adjudicate(doc, rev)
    path, n = C.export_longterm_dataset(doc, dec, tmp_path, tmp_path / "ds2", sources=sources)
    with Image.open(tmp_path / "ds2" / "v.png") as im, Image.open(tmp_path / "v.png") as src:
        assert im.size == (src.size[1], src.size[0])
