"""R5 update, change 3: PDF page provenance and the unverified-scale guard. Geometry is never rescaled."""
from __future__ import annotations

import math
from io import BytesIO

import pytest

from pid_reader.formats import page_provenance as pp

pypdf = pytest.importorskip("pypdf")
from pypdf import PdfWriter  # noqa: E402
from pypdf.generic import ArrayObject, FloatObject, NameObject, NumberObject  # noqa: E402


def pdf_bytes(*, user_unit=None, rotate=None, crop=None, media=(0, 0, 600, 400), pages=1) -> bytes:
    w = PdfWriter()
    for _ in range(pages):
        p = w.add_blank_page(width=media[2] - media[0], height=media[3] - media[1])
        p[NameObject("/MediaBox")] = ArrayObject([FloatObject(v) for v in media])
        if user_unit is not None:
            p[NameObject("/UserUnit")] = FloatObject(user_unit)
        if rotate is not None:
            p[NameObject("/Rotate")] = NumberObject(rotate)
        if crop is not None:
            p[NameObject("/CropBox")] = ArrayObject([FloatObject(v) for v in crop])
    b = BytesIO()
    w.write(b)
    return b.getvalue()


@pytest.mark.parametrize("uu", [1, 2, 5, 10])
def test_userunit_1_2_5_10(uu):
    r = pp.read_pdf_provenance(pdf_bytes(user_unit=uu))
    pg = r["pages"][0]
    assert r["status"] == "OK" and pg["user_unit"] == float(uu)
    assert pg["physical_measurements_allowed"] is False and pg["geometry_rescaled"] is False
    assert (pp.FLAG_USERUNIT in pg["flags"]) is (uu != 1) and (pp.FLAG_SCALE in pg["flags"]) is (uu == 1)
    assert pg["status"] == "PROPOSED_UNVERIFIED" and pg["media_box"] == [0.0, 0.0, 600.0, 400.0]       # the box is NOT multiplied by the unit


def test_absent_userunit_is_recorded_as_the_default_not_substituted_silently():
    pg = pp.read_pdf_provenance(pdf_bytes())["pages"][0]
    assert pg["user_unit"] == 1.0 and "UserUnit" not in pg["raw"] or pg["raw"].get("UserUnit") in (1, 1.0)
    assert pp.FLAG_SCALE in pg["flags"] and pp.FLAG_USERUNIT not in pg["flags"]


@pytest.mark.parametrize("bad", [0, -1, -2.5, math.nan, math.inf, -math.inf, "x", True, None, [1]])
def test_invalid_userunit_is_flagged_and_never_replaced_by_one(bad):
    pg = pp.frame_provenance(1, {"MediaBox": [0, 0, 100, 100], "UserUnit": bad})
    assert "INVALID_USERUNIT" in pg["flags"] and pg["status"] == "UNRESOLVED" and pg["user_unit"] is None
    g = pp.measurement_guard(pg)
    assert g["allowed"] is False and g["code"] == "PAGE_METADATA_INVALID"


@pytest.mark.parametrize("rot,ok", [(0, True), (90, True), (180, True), (270, True), (360, True), (-90, True), (450, True), (45, False), (91, False),
                                    (True, False), ("90", False), (math.nan, False), (None, False)])
def test_rotation_quarter_turns_only(rot, ok):
    pg = pp.frame_provenance(1, {"MediaBox": [0, 0, 100, 100], "Rotate": rot})
    assert ("INVALID_ROTATION" not in pg["flags"]) is ok
    if ok:
        assert pg["rotation"] == int(rot) % 360


def test_crop_offsets_and_negative_coordinates_are_kept_as_given():
    pg = pp.frame_provenance(1, {"MediaBox": [-100, -50, 500, 350], "CropBox": [-20, -10, 480, 340], "Rotate": 90, "UserUnit": 1})
    assert pg["status"] == "PROPOSED_UNVERIFIED" and pg["crop_box"] == [-20, -10, 480, 340] and pg["media_box"] == [-100, -50, 500, 350]
    outside = pp.frame_provenance(1, {"MediaBox": [0, 0, 100, 100], "CropBox": [-5, 0, 100, 100]})
    assert "CROPBOX_OUTSIDE_MEDIABOX" in outside["flags"] and outside["status"] == "UNRESOLVED"


@pytest.mark.parametrize("box", [None, [0, 0, 0, 100], [0, 0, 100], [0, 0, math.nan, 5], [5, 5, 1, 1], ["a", 0, 1, 1], "bad"])
def test_corrupt_boxes_are_flagged(box):
    pg = pp.frame_provenance(1, {"MediaBox": box})
    assert "INVALID_PAGE_BOX" in pg["flags"] and pg["status"] == "UNRESOLVED"


def test_real_pdf_crop_rotation_and_page_count():
    r = pp.read_pdf_provenance(pdf_bytes(rotate=90, crop=(50, 40, 450, 340), user_unit=2, pages=3))
    assert len(r["pages"]) == 3
    pg = r["pages"][1]
    assert pg["rotation"] == 90 and pg["crop_box"] == [50.0, 40.0, 450.0, 340.0] and pp.FLAG_USERUNIT in pg["flags"]


def test_empty_corrupt_and_missing_files_are_reported_not_raised(tmp_path):
    for payload in (b"", b"not a pdf", b"%PDF-1.7\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"):
        r = pp.read_pdf_provenance(payload)
        assert r["status"] in ("UNREADABLE", "OK") and (r["status"] == "UNREADABLE" or r["pages"] == [])
        assert all(p["physical_measurements_allowed"] is False for p in r["pages"])
    r = pp.read_pdf_provenance(tmp_path / "missing.pdf")
    assert r["status"] == "UNREADABLE" and r["error"]


def test_page_limit_is_enforced(monkeypatch):
    monkeypatch.setattr(pp, "MAX_PAGES", 2)
    r = pp.read_pdf_provenance(pdf_bytes(pages=3))
    assert r["status"] == "REFUSED" and "PAGE_COUNT_OVER_LIMIT" in r["error"] and r["pages"] == []


def test_guard_always_refuses_and_says_why():
    g1 = pp.measurement_guard(pp.frame_provenance(1, {"MediaBox": [0, 0, 100, 100], "UserUnit": 1}))
    g2 = pp.measurement_guard(pp.frame_provenance(1, {"MediaBox": [0, 0, 100, 100], "UserUnit": 10}))
    g3 = pp.measurement_guard(None)
    assert [g1["allowed"], g2["allowed"], g3["allowed"]] == [False, False, False]
    assert g1["code"] == pp.FLAG_SCALE and g2["code"] == pp.FLAG_USERUNIT and "10" in g2["message"] and g3["code"] == "NO_PAGE_PROVENANCE"
    assert all(len(g["message"]) < 160 for g in (g1, g2, g3))              # concise, not a wall of implementation detail


def test_the_record_is_json_serialisable_and_carries_the_raw_values():
    import json
    pg = pp.frame_provenance(3, {"MediaBox": [0, 0, 10, 10], "CropBox": [1, 1, 9, 9], "Rotate": 180, "UserUnit": 5})
    assert json.loads(json.dumps(pg))["raw"] == {"MediaBox": [0, 0, 10, 10], "CropBox": [1, 1, 9, 9], "Rotate": 180, "UserUnit": 5}


def test_agrees_with_the_existing_qualified_page_frame_on_crop_and_rotation(tmp_path):
    """The live ``PageFrame`` (CropBox/rotation mapping) is untouched; this only shows both readings agree on real files."""
    pytest.importorskip("pdfplumber")
    for rot in (0, 90, 180, 270):
        f = tmp_path / f"r{rot}.pdf"
        f.write_bytes(pdf_bytes(rotate=rot, crop=(50, 40, 450, 340)))
        row = pp.crosscheck_live_frame(f)[0]
        assert row["rotation_agrees"] is True, row


def test_a_hostile_metadata_value_does_not_crash_the_reader():
    pg = pp.frame_provenance(1, {"MediaBox": [0, 0, 1e308, 1e308], "CropBox": [0, 0, 1e308, 1e308], "Rotate": 10 ** 30, "UserUnit": 1e308})
    assert pg["physical_measurements_allowed"] is False and "geometry_rescaled" in pg
