"""WPU-03 adaptive OCR re-read: orientation mapping, alternatives, bounded retries, provenance."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from revx_fixtures import sheet_pdf  # noqa: E402

pytest.importorskip("pdfplumber")
from pid_reader.api import Cancelled, ReadParams, read_pid  # noqa: E402
from pid_reader.engineering import ocr_adaptive as oa  # noqa: E402
from pid_reader.engineering.page_regions import analyse_pages  # noqa: E402
from pid_reader.engineering.pipeline import analyze_drawing  # noqa: E402
from pid_reader.engineering.project import ProjectStore  # noqa: E402
from pid_reader.formats import ocr_source  # noqa: E402


def fwd(u, v, rot):
    """Forward map used by PIL ``rotate(rot, expand=True)`` in normalised coordinates (counter-clockwise)."""
    return {0: (u, v), 90: (v, 1 - u), 180: (1 - u, 1 - v), 270: (1 - v, u)}[rot]


@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_rotated_box_maps_back_exactly(rot):
    box = {"x0": 0.10, "y0": 0.20, "x1": 0.30, "y1": 0.25}
    a, b = fwd(box["x0"], box["y0"], rot), fwd(box["x1"], box["y1"], rot)
    rotated = {"x0": min(a[0], b[0]), "y0": min(a[1], b[1]), "x1": max(a[0], b[0]), "y1": max(a[1], b[1])}
    back = oa.map_rotated_box(rotated, rot)
    for k in box:
        assert abs(back[k] - box[k]) < 1e-6


def test_bad_rotation_refused():
    with pytest.raises(ValueError):
        oa.map_rotated_box({"x0": 0, "y0": 0, "x1": .1, "y1": .1}, 45)


# ---- character-confusion alternatives (provenance only)
@pytest.mark.parametrize("text,alt", [("PIT-1O0", "PIT-100"), ("P1T", "PIT"), ("5ET", "SET"), ("1OO", "100"), ("PT-I01", "PT-101")])
def test_confusion_alternatives_positive(text, alt):
    assert alt in oa.confusion_alternatives(text)


@pytest.mark.parametrize("text", ["PIT-101", "HV", "100", "", "ABC-DEF", "0"])
def test_confusion_alternatives_negative(text):
    assert oa.confusion_alternatives(text) == []


def test_alternatives_never_change_the_raw_text():
    text = "PIT-1O0"
    oa.confusion_alternatives(text)
    assert text == "PIT-1O0"


# ---- augment through the real pipeline with an injected word engine
def _store(tmp_path, pdf):
    db = ProjectStore(tmp_path / "p.sqlite")
    return db, db.add_extraction(read_pid(pdf, ReadParams(), filename="scan.pdf"), source_pdf_bytes=pdf)


def sideways_engine(calls):
    """Reads nothing on the landscape page; finds one word once the image has been turned portrait."""
    def fake(image, timeout):
        calls.append(image.size)
        if image.height > image.width:
            return [("PIT-101", 0.7, int(image.width * 0.40), int(image.height * 0.30), int(image.width * 0.10), int(image.height * 0.02), False)]
        return []
    return fake


def test_zero_word_page_is_recovered_by_orientation_retry(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(ocr_source, "_tesseract_words", sideways_engine(calls))
    db, eid = _store(tmp_path, sheet_pdf(raster=True, title=False))
    out = analyze_drawing(db, eid, ocr_engine="tesseract", preset="standard")
    ocr_outcome = next(o for o in out["outcomes"] if o["stage_id"] == "ocr")
    trace = ocr_outcome["diagnostics"]["adaptive_trace"]
    assert {t["variant"] for t in trace} == {"contrast", "rot90", "rot270"}
    assert all(t["trigger"] == "ZERO_WORDS_WITH_INK" for t in trace)
    h = out["health"]
    assert h["pages"][0]["text_status"] == "OCR_OK" and "ZERO_WORDS_WITH_INK" not in h["codes"]
    words = db.get_ocr_analysis(out["analyses"]["ocr"])["pages"][0]["words"]
    assert words and all(w["variant"] in ("rot90", "rot270") and w["raw_ocr_score"] == 0.7 for w in words)   # raw score untouched
    for w in words:
        assert 0 <= w["bbox"]["x0"] < w["bbox"]["x1"] <= 1 and 0 <= w["bbox"]["y0"] < w["bbox"]["y1"] <= 1
    assert out["health"]["drawing_status"] != "FAILED" and out["outcomes"]
    db.close()


def test_rot90_word_lands_where_the_inverse_map_says(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_source, "_tesseract_words", sideways_engine([]))
    pdf = sheet_pdf(raster=True, title=False)
    got = oa.read_variant(pdf, 1, "tesseract", "rot90")
    assert len(got) == 1
    expect = oa.map_rotated_box({"x0": 0.40, "y0": 0.30, "x1": 0.50, "y1": 0.32}, 90)
    for k in ("x0", "x1", "y0", "y1"):
        assert abs(got[0]["bbox"][k] - expect[k]) < 0.002


def test_quick_preset_never_retries(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(ocr_source, "_tesseract_words", sideways_engine(calls))
    db, eid = _store(tmp_path, sheet_pdf(raster=True, title=False))
    out = analyze_drawing(db, eid, ocr_engine="tesseract", preset="quick")
    assert next(o for o in out["outcomes"] if o["stage_id"] == "ocr")["diagnostics"]["adaptive_trace"] == []
    assert "ZERO_WORDS_WITH_INK" in out["health"]["codes"] and len(calls) == 1
    db.close()


def test_page_that_needs_no_ocr_is_never_reread(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(ocr_source, "_tesseract_words", sideways_engine(calls))
    pdf = sheet_pdf(body_words=200)
    pages = analyse_pages(pdf)
    base = {"adapter": "standalone_ocr_preview_v3", "algorithm": "tesseract-word-ocr-v3", "pages": [{"page": 1, "words": []}], "result_sha256": "x"}
    res, trace = oa.augment_ocr(pdf, base, pages, preset="deep")
    assert trace == [] and res is base and calls == []


def test_a_failing_variant_is_recorded_and_the_rest_still_run(monkeypatch):
    pdf = sheet_pdf(raster=True, title=False)
    seen = []

    def flaky(image, timeout):
        seen.append(image.size)
        if len(seen) == 2:
            raise RuntimeError("engine hiccup")
        return [("T-1", 0.6, 10, 10, 50, 20, False)] if len(seen) == 3 else []
    monkeypatch.setattr(ocr_source, "_tesseract_words", flaky)
    pages = analyse_pages(pdf)
    base = {"adapter": "standalone_ocr_preview_v3", "algorithm": "tesseract-word-ocr-v3", "pages": [{"page": 1, "words": []}]}
    res, trace = oa.augment_ocr(pdf, base, pages, preset="standard")
    assert [bool(t["error"]) for t in trace] == [False, True, False] and trace[1]["error"].startswith("RuntimeError")
    assert res["adaptive"]["words_added"] == 1 and res["pages"][0]["words"][0]["variant"] == "rot270"


def test_overlapping_different_reading_is_kept_as_alternative_not_replacement(monkeypatch):
    pdf = sheet_pdf(raster=True, title=False)
    n = {"i": 0}

    def eng(image, timeout):
        n["i"] += 1
        return [("PIT-100" if n["i"] > 1 else "PIT-1O0", 0.5, int(image.width * .1), int(image.height * .1),
                 int(image.width * .2), int(image.height * .04), False)]
    monkeypatch.setattr(ocr_source, "_tesseract_words", eng)
    base = ocr_source.ocr_pdf_preview(pdf, engine="tesseract")
    pages = analyse_pages(pdf)
    res, trace = oa.augment_ocr(pdf, base, pages, preset="deep")
    words = res["pages"][0]["words"]
    old = next(w for w in words if "variant" not in w)
    alts = [w for w in words if w.get("alternative_of") == old["id"]]
    assert old["text"] == "PIT-1O0" and alts and alts[0]["text"] == "PIT-100"
    assert "PIT-100" in old.get("confusion_alternatives", oa.confusion_alternatives(old["text"]))


def test_cancel_is_honoured_between_variants(monkeypatch):
    class Cancel:
        def check(self):
            raise Cancelled()
    monkeypatch.setattr(ocr_source, "_tesseract_words", lambda image, timeout: [])
    pdf = sheet_pdf(raster=True, title=False)
    base = {"adapter": "standalone_ocr_preview_v3", "algorithm": "tesseract-word-ocr-v3", "pages": [{"page": 1, "words": []}]}
    with pytest.raises(Cancelled):
        oa.augment_ocr(pdf, base, analyse_pages(pdf), preset="standard", cancel=Cancel())


def test_unknown_preset_refused():
    with pytest.raises(ValueError):
        oa.augment_ocr(b"%PDF-", {"algorithm": "x", "pages": []}, [], preset="turbo")


def test_retries_are_bounded_by_the_preset():
    assert len(oa.PRESETS["quick"]["zero_variants"]) == 0
    assert len(oa.PRESETS["standard"]["zero_variants"]) <= 3
    assert len(oa.PRESETS["deep"]["zero_variants"]) <= 5
