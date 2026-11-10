"""Regression tests for the baseline-diagnostic findings F01, F02, F04, F05, F07, F09 and F12 (docs: PID_READER_CLAUDE_BASELINE_DIAGNOSTIC_R1).

Each test reproduces a failure observed on real drawings with a small synthetic input. No drawing content is used.
"""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from revx_fixtures import sheet_pdf  # noqa: E402

pytest.importorskip("pdfplumber")
pytest.importorskip("reportlab")
from reportlab.pdfgen import canvas  # noqa: E402

from pid_reader.api import ReadParams, read_pid  # noqa: E402
from pid_reader.engineering.pipeline import analyze_drawing  # noqa: E402
from pid_reader.engineering.project import ProjectStore  # noqa: E402
from pid_reader.engineering.symbols import build_symbol_proposals, validate_symbol_proposals  # noqa: E402
from pid_reader.engineering.text_links import validate_ocr_source  # noqa: E402
from pid_reader.engineering.topology import analyze_pdf_topology  # noqa: E402
from pid_reader.formats import ocr_source  # noqa: E402


def _store(tmp_path, pdf):
    db = ProjectStore(tmp_path / "p.sqlite")
    return db, db.add_extraction(read_pid(pdf, ReadParams(), filename="scan.pdf"), source_pdf_bytes=pdf)


def _outcome(out, stage):
    return next(o for o in out["outcomes"] if o["stage_id"] == stage)


# ---- F01: overlapping OCR detections that split into identical word boxes must not reject the whole OCR result
def test_identical_split_tokens_are_merged_so_the_ocr_result_validates(monkeypatch):
    pdf = sheet_pdf(raster=True, title=False)

    def engine(image, timeout):                       # two detections of the same drawn token, different raw scores
        w, h = image.size
        box = (int(w * .40), int(h * .30), int(w * .06), int(h * .02))
        return [("IS9", 0.9007, *box, True), ("IS9", 0.9196, *box, True), ("PT-101", 0.8, int(w * .6), int(h * .5), int(w * .08), int(h * .02), False)]
    monkeypatch.setattr(ocr_source, "_tesseract_words", engine)
    ocr = ocr_source.ocr_pdf_preview(pdf, engine="tesseract")
    words = [w for p in ocr["pages"] for w in p["words"]]
    assert len({w["id"] for w in words}) == len(words) == 2
    kept = next(w for w in words if w["text"] == "IS9")
    assert kept["raw_ocr_score"] == 0.9196                                 # the higher raw score is kept, nothing is rescored
    assert validate_ocr_source(ocr, read_pid(pdf, ReadParams(), filename="scan.pdf")) == []
    assert ocr_source.last_diagnostics().get("duplicate_words_merged") == 1


def test_distinct_words_with_the_same_text_are_not_merged(monkeypatch):
    pdf = sheet_pdf(raster=True, title=False)

    def engine(image, timeout):
        w, h = image.size
        return [("V", 0.7, int(w * .2), int(h * .3), int(w * .02), int(h * .02), False), ("V", 0.7, int(w * .5), int(h * .3), int(w * .02), int(h * .02), False)]
    monkeypatch.setattr(ocr_source, "_tesseract_words", engine)
    ocr = ocr_source.ocr_pdf_preview(pdf, engine="tesseract")
    assert len(ocr["pages"][0]["words"]) == 2


# ---- F04 / F05: a failed OCR registration must not leave unstored words feeding later stages
def _fail_ocr_registration(monkeypatch):
    def boom(self, extraction_id, result):
        raise ValueError("Invalid OCR evidence: simulated")
    monkeypatch.setattr(ProjectStore, "add_ocr_analysis", boom)


def _one_word_engine(image, timeout):
    return [("PIT-101", 0.7, int(image.width * 0.40), int(image.height * 0.30), int(image.width * 0.10), int(image.height * 0.02), False)]


def test_failed_ocr_registration_leaves_no_words_for_later_stages(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_source, "_tesseract_words", _one_word_engine)
    _fail_ocr_registration(monkeypatch)
    db, eid = _store(tmp_path, sheet_pdf(raster=True, title=False))
    out = analyze_drawing(db, eid, ocr_engine="tesseract", preset="quick")
    assert _outcome(out, "ocr")["status"] == "FAILED"
    assert out["health"]["pages"][0]["words_ocr"] == 0                     # health must not count words that were never stored
    assert "ocr" not in out["analyses"]
    db.close()


def test_failed_ocr_registration_does_not_break_the_raster_network(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_source, "_tesseract_words", _one_word_engine)
    _fail_ocr_registration(monkeypatch)
    db, eid = _store(tmp_path, sheet_pdf(raster=True, title=False))
    out = analyze_drawing(db, eid, ocr_engine="tesseract", preset="quick")
    assert _outcome(out, "raster")["status"] == "SUCCESS"
    assert _outcome(out, "raster_network")["status"] == "SUCCESS", _outcome(out, "raster_network").get("error_summary")
    db.close()


# ---- F02: identical outlines must not collide
def _rect_pdf(copies: int) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(842, 595))
    for _ in range(copies):
        c.rect(100, 100, 60, 40)
        c.circle(300, 300, 20)
    c.line(160, 120, 300, 120)
    c.drawString(110, 115, "V-101")
    c.save()
    return buf.getvalue()


def test_identical_outlines_get_unique_shape_symbol_and_port_ids():
    pdf = _rect_pdf(2)
    ext = read_pid(pdf, ReadParams(), filename="dup.pdf")
    topo = analyze_pdf_topology(pdf)
    ids = [s["id"] for s in topo["shape_candidates"]]
    assert len(ids) == 4 and len(set(ids)) == 4
    sym = build_symbol_proposals(ext, topo)
    assert validate_symbol_proposals(sym, ext, topo) == []
    assert len({x["id"] for x in sym["symbol_candidates"]}) == len(sym["symbol_candidates"])
    assert len({x["id"] for x in sym["port_candidates"]}) == len(sym["port_candidates"])


def test_the_first_copy_of_an_outline_keeps_the_id_it_always_had():
    from pid_reader.api import stable_id
    topo = analyze_pdf_topology(_rect_pdf(2))
    kind_name = {"CLOSED_NEAR_CIRCULAR_OUTLINE": "CLOSED_CURVE", "RECTANGULAR_OUTLINE": "RECTANGULAR_OUTLINE"}
    legacy = {stable_id("shape", topo["source_sha256"], s["page"], s["bbox"], kind_name[s["shape"]]) for s in topo["shape_candidates"]}
    actual = {s["id"] for s in topo["shape_candidates"]}
    assert len(legacy) == 2 and legacy <= actual and len(actual) == 4        # legacy ids survive; only the repeats are new


# ---- F09 / F07 / F12: honest status, cap reasons and candidate counts
def _partial_detector(monkeypatch):
    from pid_reader.engineering import symbol_detect

    def fake(pdf_bytes, page_number, **kw):
        return {"candidates": [], "tiles_processed": 3, "status": "PARTIAL", "page": page_number,
                "incomplete": [{"reason": "PEAK_CAP", "template_searches_capped": 10, "peak_cap": 5000, "refine_cap": 400}]}
    monkeypatch.setattr(symbol_detect, "detect_symbols", fake)


def test_status_is_computed_after_the_library_stage_and_never_overstates(tmp_path, monkeypatch):
    _partial_detector(monkeypatch)
    db, eid = _store(tmp_path, sheet_pdf(dense=200, title=True, body_words=140))   # native text layer: no OCR needed
    out = analyze_drawing(db, eid, ocr_engine=None, preset="quick", library_symbols=True)
    assert _outcome(out, "symbol_library")["status"] == "PARTIAL"
    assert out["health"]["drawing_status"] == "PARTIAL"
    assert "STAGE_TRUNCATED" in out["health"]["codes"]
    db.close()


def test_library_stage_records_why_a_page_was_partial(tmp_path, monkeypatch):
    _partial_detector(monkeypatch)
    db, eid = _store(tmp_path, sheet_pdf(dense=200, title=True, body_words=140))   # native text layer: no OCR needed
    out = analyze_drawing(db, eid, ocr_engine=None, preset="quick", library_symbols=True)
    stats = _outcome(out, "symbol_library")["diagnostics"]["stats"]
    assert stats["incomplete"] == [{"page": 1, "reasons": [{"reason": "PEAK_CAP", "template_searches_capped": 10, "peak_cap": 5000, "refine_cap": 400}]}]
    db.close()


def _crossing_pdf() -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(842, 595))
    c.line(100, 300, 400, 300)
    c.line(250, 200, 250, 400)           # crosses the first line: a contact candidate
    c.rect(500, 200, 60, 40)
    c.drawString(510, 215, "V-101")
    c.save()
    return buf.getvalue()


def test_stage_outcomes_record_the_candidates_they_produced(tmp_path):
    db, eid = _store(tmp_path, _crossing_pdf())
    out = analyze_drawing(db, eid, ocr_engine=None, preset="quick")
    expected = {"geometry": "contacts", "symbols": "symbols", "linework": "valves", "catalogue": "catalogue_matches", "signals": "signal_candidates"}
    seen = 0
    for stage, key in expected.items():
        o = _outcome(out, stage)
        if o["status"] in ("SUCCESS", "PARTIAL") and key in out["counts"]:
            assert o["candidates"] == out["counts"][key], stage
            seen += 1
    assert seen >= 3 and out["counts"]["contacts"] > 0 and _outcome(out, "geometry")["candidates"] == out["counts"]["contacts"]
    assert _outcome(out, "symbols")["candidates"] == out["counts"]["symbols"] > 0
    db.close()
