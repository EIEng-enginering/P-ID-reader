"""WPU-02: page encoding classes and layout regions (positive, negative, rotated/cropped, determinism)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from revx_fixtures import sheet_pdf  # noqa: E402

pytest.importorskip("pdfplumber")
from pid_reader.engineering.page_regions import analyse_pages, classify_page, ocr_policy, segment_regions, profile_pages  # noqa: E402


def one(pdf: bytes) -> dict:
    return analyse_pages(pdf)[0]


def kinds(page: dict) -> list[str]:
    return [r["kind"] for r in page["regions"]]


# ---- classification: positives
def test_native_text_page():
    p = one(sheet_pdf(body_words=200))
    assert p["classification"] == "NATIVE_TEXT" and p["ocr_policy"]["mode"] == "native"


def test_dense_vector_without_text_is_outlined_text():
    p = one(sheet_pdf(dense=1200, title=False))
    assert p["classification"] == "VECTOR_OUTLINED_TEXT" and p["ocr_policy"]["ocr_required"] is True


def test_title_block_only_on_dense_vector_is_hybrid_with_suspicion():
    p = one(sheet_pdf(dense=1200, title=True))
    assert p["classification"] == "HYBRID"
    assert p["evidence"]["outlined_text_suspected"] is True and p["evidence"]["words"] < 120


def test_raster_page_is_raster_scan():
    p = one(sheet_pdf(raster=True, title=False))
    assert p["classification"] == "RASTER_SCAN" and p["ocr_policy"]["mode"] == "ocr_tiles"


def test_blank_page_is_low_content():
    p = one(sheet_pdf(title=False))
    assert p["classification"] == "LOW_CONTENT" and p["ocr_policy"]["ocr_required"] is False


# ---- classification: negatives / confusers
def test_native_page_is_not_flagged_as_outlined():
    p = one(sheet_pdf(body_words=200, dense=300))
    assert p["classification"] == "NATIVE_TEXT" and "outlined_text_suspected" not in p["evidence"]


def test_raster_is_not_called_vector_and_vector_not_raster():
    assert one(sheet_pdf(dense=1200, title=False))["classification"] != "RASTER_SCAN"
    assert one(sheet_pdf(raster=True, title=False))["classification"] != "VECTOR_OUTLINED_TEXT"


def test_zero_words_is_never_native_text():
    p = one(sheet_pdf(dense=900, title=False))
    assert p["classification"] != "NATIVE_TEXT"


def test_classes_come_from_the_documented_set():
    for kw in (dict(body_words=200), dict(dense=1200), dict(raster=True), dict(title=False)):
        assert one(sheet_pdf(**kw))["classification"] in ("NATIVE_TEXT", "VECTOR_OUTLINED_TEXT", "HYBRID",
                                                           "RASTER_SCAN", "LOW_CONTENT", "UNKNOWN")


def test_ocr_policy_has_every_class():
    for k in ("NATIVE_TEXT", "VECTOR_OUTLINED_TEXT", "RASTER_SCAN", "HYBRID", "LOW_CONTENT", "UNKNOWN"):
        assert ocr_policy({"kind": k})["mode"]


# ---- regions
def test_title_block_found_lower_right():
    p = one(sheet_pdf(title=True))
    tb = [r for r in p["regions"] if r["kind"] == "TITLE_BLOCK"]
    assert len(tb) == 1
    assert tb[0]["bbox"]["x0"] > 0.5 and tb[0]["bbox"]["y0"] > 0.7


def test_notes_table_revision_regions_found_and_separate():
    p = one(sheet_pdf(title=True, notes=True, table=True, revision=True))
    ks = kinds(p)
    for needed in ("TITLE_BLOCK", "NOTES", "TABLE", "REVISION_TABLE", "DRAWING_AREA"):
        assert needed in ks, ks
    table = next(r for r in p["regions"] if r["kind"] == "TABLE")
    assert table["label"].upper().startswith("STATION")
    area = next(r for r in p["regions"] if r["kind"] == "DRAWING_AREA")
    assert len(area["evidence"]["excluded_region_ids"]) >= 4


def test_border_defines_inner_drawing_area():
    p = one(sheet_pdf(border=True, title=False))
    assert "BORDER_GRID" in kinds(p)
    area = next(r for r in p["regions"] if r["kind"] == "DRAWING_AREA")
    assert 0.0 < area["bbox"]["x0"] < 0.1 and 0.9 < area["bbox"]["x1"] < 1.0


def test_no_border_means_full_page_drawing_area_and_no_border_region():
    p = one(sheet_pdf(title=False, body_words=50))
    assert "BORDER_GRID" not in kinds(p)
    assert next(r for r in p["regions"] if r["kind"] == "DRAWING_AREA")["bbox"] == {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}


def test_body_text_is_not_mistaken_for_title_or_notes():
    p = one(sheet_pdf(title=False, body_words=120))
    assert kinds(p) == ["DRAWING_AREA"]


def test_title_like_words_in_upper_left_are_not_a_title_block():
    prof = profile_pages(sheet_pdf(title=True))[0]
    for w in prof["words"]:                               # mirror every word to the top-left
        b = w["bbox"]
        w["bbox"] = {"x0": 1 - b["x1"], "y0": 1 - b["y1"], "x1": 1 - b["x0"], "y1": 1 - b["y0"]}
    assert "TITLE_BLOCK" not in [r["kind"] for r in segment_regions(prof)]


def test_rules_are_not_pipes_regions_keep_raw_rule_evidence():
    p = one(sheet_pdf(table=True))
    table = next(r for r in p["regions"] if r["kind"] == "TABLE")
    assert table["evidence"]["horizontal_rules"] >= 3 and table["evidence"]["vertical_rules"] >= 2


# ---- rotation / CropBox
@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_rotated_pages_still_classified_with_frame_recorded(rotation):
    p = one(sheet_pdf(dense=1200, title=True, rotate=rotation))
    assert p["classification"] == "HYBRID" and p["frame"]["rotation"] == rotation
    for r in p["regions"]:
        b = r["bbox"]
        assert 0 <= b["x0"] < b["x1"] <= 1 and 0 <= b["y0"] < b["y1"] <= 1


def test_cropbox_offset_is_recorded_and_coordinates_round_trip():
    from pid_reader.formats.page_coordinates import PageFrame
    p = one(sheet_pdf(body_words=60, crop=(100, 100, 900, 700)))
    meta = p["frame"]
    assert meta["crop_origin"] != [0, 0] and meta["render_size"][0] < meta["media_size"][0]
    frame = PageFrame(meta["media_size"][0], meta["media_size"][1], meta["crop_origin"][0], meta["crop_origin"][1],
                      meta["render_size"][0], meta["render_size"][1], meta["rotation"])
    for x, y in ((0.1, 0.2), (0.5, 0.5), (0.9, 0.8)):
        mx, my = frame.render_to_media(x, y)
        bx, by = frame.media_to_render(mx, my)
        assert abs(bx - x) < 1e-9 and abs(by - y) < 1e-9


# ---- determinism and ids
def test_analysis_is_deterministic_and_ids_stable():
    pdf = sheet_pdf(title=True, notes=True, table=True, revision=True, border=True)
    a, b = analyse_pages(pdf), analyse_pages(pdf)
    assert a == b
    ids = [r["region_id"] for r in a[0]["regions"]]
    assert len(ids) == len(set(ids))


def test_classify_page_accepts_minimal_profile_and_unknown_is_allowed():
    prof = {"word_count": 15, "graphics_count": 100, "image_count": 0, "image_area_fraction": 0.0}
    assert classify_page(prof)["kind"] in ("UNKNOWN", "NATIVE_TEXT")
