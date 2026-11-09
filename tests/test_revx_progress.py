"""Progress honesty and responsiveness: the bar follows every stage, reaches 100 % only at the end, and Cancel works inside slow stages."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from revx_fixtures import symbol_sheet_pdf  # noqa: E402

from pid_reader.api import Cancelled, ReadParams, read_pid  # noqa: E402
from pid_reader.engineering import intelligence_store as istore  # noqa: E402
from pid_reader.engineering import pipeline as pl  # noqa: E402
from pid_reader.engineering import symbol_detect as sd  # noqa: E402
from pid_reader.engineering.project import ProjectStore  # noqa: E402
from pid_reader.formats import ocr_source  # noqa: E402


def run_with_progress(tmp_path, pdf, **kw):
    events = []
    with ProjectStore(tmp_path / "p.sqlite") as db:
        eid = db.add_extraction(read_pid(pdf, ReadParams(), filename="p.pdf"), source_pdf_bytes=pdf)
        out = pl.analyze_drawing(db, eid, ocr_engine=None, library_symbols=True, progress=lambda s, f, m: events.append((s, f, m)), **kw)
    return events, out


PDF = symbol_sheet_pdf([{"kind": "gate", "x": 150, "y": 200, "s": 22, "tag": "HV-1"}, {"kind": "globe", "x": 400, "y": 200, "s": 22}])


def test_progress_never_goes_backwards_and_hits_100_only_at_the_very_end(tmp_path):
    events, out = run_with_progress(tmp_path, PDF, preset="quick")
    fractions = [f for _, f, _ in events]
    assert fractions == sorted(fractions)
    assert events[-1][0] == "done" and events[-1][1] == 1.0
    assert all(f < 1.0 for _, f, _ in events[:-1])
    assert [s for s, _, _ in events].count("done") == 1


def test_every_slow_stage_reports_inside_itself(tmp_path):
    events, _ = run_with_progress(tmp_path, PDF, preset="quick")
    stages = [s for s, _, _ in events]
    for needed in ("classify", "geometry", "symbol_library", "engineering_graph", "control_loops", "doc_text", "record"):
        assert needed in stages, needed
    assert sum(1 for s in stages if s == "symbol_library") >= 3          # start plus per-template ticks
    sym = [(f, m) for s, f, m in events if s == "symbol_library"]
    assert any("tile 1 of" in m for _, m in sym) and all(pl._W_START["symbol_library"] <= f <= pl._W_START["engineering_graph"] for f, _ in sym)


def test_progress_plan_covers_all_stages_and_sums_to_one():
    assert set(pl.STAGES) <= set(pl.PROGRESS_WEIGHTS)
    assert pl._W_START["classify"] == 0.0 and list(pl.PROGRESS_WEIGHTS)[-1] == "record"
    assert pl._W_START["record"] + pl.PROGRESS_WEIGHTS["record"] / pl._W_TOTAL == pytest.approx(1.0)


def test_a_skipped_library_stage_does_not_stall_the_bar(tmp_path):
    events = []
    with ProjectStore(tmp_path / "p.sqlite") as db:
        eid = db.add_extraction(read_pid(PDF, ReadParams(), filename="p.pdf"), source_pdf_bytes=PDF)
        pl.analyze_drawing(db, eid, ocr_engine=None, library_symbols=False, progress=lambda s, f, m: events.append((s, f, m)))
    assert events[-1][1] == 1.0 and [f for _, f, _ in events] == sorted(f for _, f, _ in events)


# ---------------------------------------------------------------- cancel works inside the slow stages
class Cancel:
    def __init__(self, after):
        self.after, self.n = after, 0

    def check(self):
        self.n += 1
        if self.n > self.after:
            raise Cancelled()


def test_cancel_stops_the_symbol_search_between_templates():
    c = Cancel(3)
    with pytest.raises(Cancelled):
        sd.detect_symbols(PDF, 1, preset="quick", cancel=c)
    assert c.n <= 6                                                       # stopped within a few templates, not after the whole page


def test_ocr_tile_hook_reports_and_cancels_between_tiles(monkeypatch):
    import numpy as np

    class Img:
        size = (3000, 2000)

        def crop(self, box):
            return Img()
    calls = []
    monkeypatch.setattr(ocr_source, "_rapid_engine", lambda: (lambda arr: (calls.append(1) or [], None)))
    monkeypatch.setattr(np, "asarray", lambda im: im)
    seen = []

    def hook(done, total):
        seen.append((done, total))
        if done >= 2:
            raise Cancelled()
    ocr_source.reset_diagnostics()
    ocr_source._HOOK["tile"] = hook
    try:
        with pytest.raises(Cancelled):
            ocr_source._rapid_lines(Img())
    finally:
        ocr_source._HOOK.clear()
    assert seen[:3] == [(0, seen[0][1]), (1, seen[0][1]), (2, seen[0][1])] and seen[0][1] > 2 and len(calls) == 2


def test_ocr_progress_and_cancel_reach_ocr_pdf_preview(monkeypatch):
    monkeypatch.setattr(ocr_source, "_tesseract_words", lambda image, timeout: [])
    pages = []
    ocr_source.ocr_pdf_preview(PDF, engine="tesseract", progress=lambda f, m: pages.append((f, m)))
    assert pages and pages[0][0] == 0.0 and "OCR page 1" in pages[0][1] and not ocr_source._HOOK

    class C:
        def check(self):
            raise Cancelled()
    with pytest.raises(Cancelled):
        ocr_source.ocr_pdf_preview(PDF, engine="tesseract", cancel=C())


def test_a_stale_ocr_hook_is_cleared_after_a_failure(monkeypatch):
    def boom(image, timeout):
        raise RuntimeError("engine died")
    monkeypatch.setattr(ocr_source, "_tesseract_words", boom)
    with pytest.raises(Exception):
        ocr_source.ocr_pdf_preview(PDF, engine="tesseract", progress=lambda f, m: None)
    ocr_source._HOOK.clear()


# ---------------------------------------------------------------- dense pages: capped and reported, never a crash or a silent cut
def test_peak_cap_is_reported_as_partial_not_raised(monkeypatch):
    monkeypatch.setattr(sd, "PEAK_CAP", 1)
    pdf = symbol_sheet_pdf([{"kind": "ball", "x": 120 + 80 * i, "y": 200, "s": 22} for i in range(5)], noise=300)
    res = sd.detect_symbols(pdf, 1, preset="quick")
    assert res["status"] == "PARTIAL" and any(i["reason"] == "PEAK_CAP" for i in res["incomplete"])


def test_plain_joined_contacts_are_not_stored_as_thousands_of_evidence_items(tmp_path):
    events, out = run_with_progress(tmp_path, PDF, preset="quick")
    items = [i for i in out["items"] if i["item_kind"] == "EVIDENCE"]
    assert all(i["junction"]["status"] in ("UNKNOWN_CROSSING", "SEPARATED_FAVOURED", "JOINED_SUPPORTED", "SEPARATED_SUPPORTED") for i in items)
