"""WPU-01 stage telemetry / zero-extraction health and WPU-12 v13 persistence."""
from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from revx_fixtures import sheet_pdf  # noqa: E402

pytest.importorskip("pdfplumber")
from pid_reader.api import ReadParams, read_pid  # noqa: E402
from pid_reader.engineering import intelligence_store as istore  # noqa: E402
from pid_reader.engineering.pipeline import analyze_drawing  # noqa: E402
from pid_reader.engineering.project import ProjectStore  # noqa: E402
from pid_reader.engineering.stage_telemetry import (StageRecorder, evaluate_health, export_consistency,  # noqa: E402
                                                    make_outcome, ocr_diagnostics)
from pid_reader.formats import ocr_source  # noqa: E402


def _store(tmp_path, pdf, name="sheet.pdf"):
    db = ProjectStore(tmp_path / "p.sqlite")
    eid = db.add_extraction(read_pid(pdf, ReadParams(), filename=name), source_pdf_bytes=pdf)
    return db, eid


def raster_sheet():
    return sheet_pdf(raster=True, title=False)


# ---------------------------------------------------------------- zero-extraction health (S025-type)
def test_raster_sheet_with_ocr_off_is_incomplete_not_success(tmp_path):
    db, eid = _store(tmp_path, raster_sheet())
    out = analyze_drawing(db, eid, ocr_engine=None)
    h = out["health"]
    assert h["drawing_status"] == "INCOMPLETE" and h["primary_blocker"] == "OCR_DISABLED"
    assert h["pages"][0]["text_status"] == "NOT_ATTEMPTED" and h["pages"][0]["ink_evidence"] is True
    assert out["stages"]["ocr"]["status"] == "SKIPPED"
    db.close()


def test_missing_engine_is_reported_as_missing_not_as_no_text(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_source, "available_engines", lambda: [])
    db, eid = _store(tmp_path, raster_sheet())
    h = analyze_drawing(db, eid, ocr_engine="auto")["health"]
    assert h["drawing_status"] == "INCOMPLETE" and "OCR_ENGINE_MISSING" in h["codes"]
    db.close()


def test_forced_ocr_failure_gets_its_own_code(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_source, "available_engines", lambda: ["rapidocr"])

    def boom(*a, **k):
        raise ValueError("model file corrupt")
    monkeypatch.setattr(ocr_source, "ocr_pdf_preview", boom)
    db, eid = _store(tmp_path, raster_sheet())
    out = analyze_drawing(db, eid, ocr_engine="rapidocr")
    assert out["health"]["drawing_status"] == "INCOMPLETE" and "OCR_FAILED" in out["health"]["codes"]
    o = next(x for x in out["outcomes"] if x["stage_id"] == "ocr")
    assert o["status"] == "FAILED" and o["error_class"] == "ValueError" and "corrupt" in o["error_summary"]
    db.close()


def test_runtime_exception_marker_distinguished_from_generic_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_source, "available_engines", lambda: ["rapidocr"])
    monkeypatch.setattr(ocr_source, "ocr_pdf_preview", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("OCR_RUNTIME_EXCEPTION: every OCR tile failed (X)")))
    db, eid = _store(tmp_path, raster_sheet())
    assert "OCR_RUNTIME_EXCEPTION" in analyze_drawing(db, eid, ocr_engine="rapidocr")["health"]["codes"]
    db.close()


def test_zero_words_with_ink_is_incomplete(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_source, "_tesseract_words", lambda image, timeout: [])
    db, eid = _store(tmp_path, raster_sheet())
    out = analyze_drawing(db, eid, ocr_engine="tesseract")
    assert out["stages"]["ocr"]["status"] == "DONE"                       # it did run ...
    h = out["health"]
    assert h["drawing_status"] == "INCOMPLETE" and "ZERO_WORDS_WITH_INK" in h["codes"]   # ... and that is not a success
    assert h["pages"][0]["text_status"] == "UNREADABLE_OR_FAILED"
    db.close()


def test_ocr_that_finds_words_clears_the_text_blocker(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_source, "_tesseract_words", lambda image, timeout: [("PIT-101", 0.8, 100, 100, 120, 40, False)])
    db, eid = _store(tmp_path, raster_sheet())
    h = analyze_drawing(db, eid, ocr_engine="tesseract")["health"]
    assert h["pages"][0]["text_status"] == "OCR_OK" and h["pages"][0]["words_ocr"] == 1
    assert "ZERO_WORDS_WITH_INK" not in h["codes"]
    db.close()


def test_native_text_page_without_ocr_is_not_flagged_incomplete(tmp_path):
    db, eid = _store(tmp_path, sheet_pdf(body_words=200))
    h = analyze_drawing(db, eid, ocr_engine=None)["health"]
    assert h["pages"][0]["text_status"] == "NATIVE_OK" and h["drawing_status"] != "INCOMPLETE"
    db.close()


def test_outlined_text_sheet_needs_ocr_and_says_so(tmp_path):
    db, eid = _store(tmp_path, sheet_pdf(dense=1200, title=False))
    h = analyze_drawing(db, eid, ocr_engine=None)["health"]
    assert h["pages"][0]["classification"] == "VECTOR_OUTLINED_TEXT" and h["drawing_status"] == "INCOMPLETE"
    db.close()


# ---------------------------------------------------------------- tile failures and consistency
class _Img:
    size = (3000, 2000)

    def crop(self, box):
        return _Img()


def test_single_tile_failure_is_partial_not_fatal(monkeypatch):
    import numpy as np
    calls = {"n": 0}

    def engine(array):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("tile glitch")
        return ([([[0, 0], [10, 0], [10, 5], [0, 5]], f"T{calls['n']}", 0.9)], None)
    monkeypatch.setattr(ocr_source, "_rapid_engine", lambda: engine)
    monkeypatch.setattr(np, "asarray", lambda im: im)
    ocr_source.reset_diagnostics()
    lines = ocr_source._rapid_lines(_Img())
    d = ocr_source.last_diagnostics()
    assert d["tile_failures"] == 1 and d["tiles_successful"] == d["tiles_attempted"] - 1 and lines
    assert d["tile_error_classes"] == ["RuntimeError"]


def test_all_tiles_failing_raises_runtime_exception_marker(monkeypatch):
    import numpy as np

    def engine(array):
        raise RuntimeError("dead")
    monkeypatch.setattr(ocr_source, "_rapid_engine", lambda: engine)
    monkeypatch.setattr(np, "asarray", lambda im: im)
    ocr_source.reset_diagnostics()
    with pytest.raises(RuntimeError, match="OCR_RUNTIME_EXCEPTION"):
        ocr_source._rapid_lines(_Img())


def test_partial_tile_failure_sets_page_ocr_partial():
    page = {"page": 1, "classification": "RASTER_SCAN", "counts": {"word_count": 0, "graphics_count": 0, "image_count": 1},
            "ocr_policy": {"ocr_required": True, "mode": "ocr_tiles"}, "regions": []}
    diag = ocr_diagnostics(requested=True, engine_choice="rapidocr", engines_available=["rapidocr"], stage_status="SUCCESS",
                           pages_selected=[1], counters={"tiles_attempted": 4, "tiles_successful": 3, "tile_failures": 1})
    out = {"ocr": make_outcome("ocr", "SUCCESS")}
    h = evaluate_health(page_analysis=[page], outcomes=out, ocr_diag=diag, ink_pages={1},
                        ocr_words_by_page={1: [{"bbox": {"x0": .1, "y0": .1, "x1": .2, "y1": .2}}]})
    assert h["pages"][0]["text_status"] == "OCR_PARTIAL" and "PARTIAL_TILE_FAILURE" in h["codes"]
    assert h["drawing_status"] == "PARTIAL"


def test_words_dropped_in_export_is_detected_and_makes_incomplete():
    assert export_consistency(40, 0) == "OCR_WORDS_DROPPED_IN_EXPORT"
    assert export_consistency(40, 40) is None and export_consistency(0, 0) is None
    page = {"page": 1, "classification": "RASTER_SCAN", "counts": {"word_count": 0, "graphics_count": 0, "image_count": 1},
            "ocr_policy": {"ocr_required": True}, "regions": []}
    diag = ocr_diagnostics(requested=True, engine_choice="rapidocr", engines_available=["rapidocr"], stage_status="SUCCESS", pages_selected=[1])
    h = evaluate_health(page_analysis=[page], outcomes={"ocr": make_outcome("ocr", "SUCCESS")}, ocr_diag=diag, ink_pages={1},
                        ocr_words_by_page={1: [{"bbox": {"x0": .1, "y0": .1, "x1": .2, "y1": .2}}] * 40}, exported_ocr_words=0)
    assert "OCR_WORDS_DROPPED_IN_EXPORT" in h["codes"] and h["drawing_status"] == "INCOMPLETE"


def test_truncating_stage_can_never_be_success():
    o = make_outcome("geometry", "SUCCESS", cap_truncations=3)
    assert o["status"] == "PARTIAL"
    rec = StageRecorder("a" * 64, {})
    rec.begin("x")
    assert rec.end("x", "DONE", "capped at 4000 strokes")["status"] == "PARTIAL"
    with pytest.raises(ValueError):
        make_outcome("x", "DONE")


def test_no_stage_ran_is_not_run_and_all_failed_is_failed():
    page = {"page": 1, "classification": "NATIVE_TEXT", "counts": {"word_count": 5, "graphics_count": 1, "image_count": 0},
            "ocr_policy": {"ocr_required": False}, "regions": []}
    diag = ocr_diagnostics(requested=False, engine_choice="off", engines_available=[], stage_status="NOT_RUN", pages_selected=[])
    assert evaluate_health(page_analysis=[page], outcomes={}, ocr_diag=diag, ink_pages=set())["drawing_status"] == "NOT_RUN"
    failed = {"geometry": make_outcome("geometry", "FAILED", error_class="X")}
    assert evaluate_health(page_analysis=[page], outcomes=failed, ocr_diag=diag, ink_pages=set())["drawing_status"] == "FAILED"


# ---------------------------------------------------------------- persistence (v13)
def test_run_is_persisted_idempotent_and_readable(tmp_path):
    db, eid = _store(tmp_path, sheet_pdf(body_words=200, notes=True))
    first = analyze_drawing(db, eid, ocr_engine=None)
    second = analyze_drawing(db, eid, ocr_engine=None)
    assert first["run_id"] and first["run_id"] == second["run_id"]                  # deterministic, content-keyed
    run = istore.latest_run(db, eid)
    assert run["status"] == first["health"]["drawing_status"] and {o["stage_id"] for o in run["outcomes"]} >= {"classify", "geometry", "ocr"}
    assert istore.list_regions(db, run["run_id"]) and db.verify_audit_chain()
    db.close()


def test_new_tables_are_append_only(tmp_path):
    db, eid = _store(tmp_path, sheet_pdf(body_words=50))
    run_id = analyze_drawing(db, eid, ocr_engine=None)["run_id"]
    for sql in ("UPDATE stage_outcome SET status='SUCCESS'", "DELETE FROM stage_outcome", "UPDATE intelligence_run SET status='PARTIAL'",
                "DELETE FROM page_region", "DELETE FROM intelligence_run"):
        with pytest.raises(sqlite3.IntegrityError):
            db.db.execute(sql)
    assert run_id
    db.close()


def test_decisions_need_a_named_reviewer_and_go_stale_with_model_generation(tmp_path):
    db, eid = _store(tmp_path, sheet_pdf(body_words=50))
    with pytest.raises(ValueError):
        istore.add_decision(db, eid, "item-1", actor=" ", decision="ACCEPTED_AS_READING", reason="x")
    with pytest.raises(ValueError):
        istore.add_decision(db, eid, "item-1", actor="A. Reviewer", decision="VERIFIED_PLANT", reason="x")
    with pytest.raises(ValueError):
        istore.add_decision(db, eid, "item-1", actor="A. Reviewer", decision="REJECTED", reason="")
    istore.add_decision(db, eid, "item-1", actor="A. Reviewer", decision="ACCEPTED_AS_READING", reason="matches drawing", model_generation="old-model")
    assert len(istore.decisions_for(db, "item-1")) == 1
    assert len(istore.stale_decisions(db, eid)) == 1 and not istore.stale_decisions(db, eid, "old-model")
    assert db.verify_audit_chain()
    db.close()


def test_snapshot_is_hash_addressed_and_tamper_evident(tmp_path):
    db, eid = _store(tmp_path, sheet_pdf(body_words=50))
    run_id = analyze_drawing(db, eid, ocr_engine=None)["run_id"]
    sid = istore.add_snapshot(db, eid, run_id, "engineering_intelligence_v1", {"a": 1})
    assert istore.add_snapshot(db, eid, run_id, "engineering_intelligence_v1", {"a": 1}) == sid
    assert istore.get_snapshot(db, sid) == {"a": 1}
    db.close()


# ---------------------------------------------------------------- migration v12 -> v13 and restore
def _downgrade_to_v12(path: Path) -> None:
    con = sqlite3.connect(path)
    for t in ("intelligence_decision", "intelligence_snapshot", "engineering_item", "page_region", "stage_outcome", "intelligence_run"):
        con.execute(f"DROP TABLE IF EXISTS {t}")
    con.execute("UPDATE project_meta SET value='12' WHERE key='standalone_schema'")
    con.commit()
    con.close()


def test_v12_project_upgrades_additively_with_backup(tmp_path):
    db, eid = _store(tmp_path, sheet_pdf(body_words=60))
    n_ext = db.db.execute("SELECT COUNT(*) FROM extraction").fetchone()[0]
    db.close()
    p = tmp_path / "p.sqlite"
    _downgrade_to_v12(p)
    with ProjectStore(p) as up:
        assert up.db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0] == "13"
        assert up.db.execute("SELECT COUNT(*) FROM extraction").fetchone()[0] == n_ext          # v12 data untouched
        assert up.migration_backup is not None and Path(up.migration_backup).exists()
        assert up.verify_audit_chain()
    old = sqlite3.connect(Path(up.migration_backup))
    assert old.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0] == "12"
    old.close()


def test_interrupted_migration_leaves_v12_intact_and_backup_restores(tmp_path, monkeypatch):
    db, eid = _store(tmp_path, sheet_pdf(body_words=60))
    db.close()
    p = tmp_path / "p.sqlite"
    _downgrade_to_v12(p)
    from pid_reader.engineering import migrations
    monkeypatch.setattr(migrations, "MIGRATION_13", "BEGIN IMMEDIATE; CREATE TABLE intelligence_run(x INTEGER); THIS IS NOT SQL; COMMIT;")
    with pytest.raises(sqlite3.Error):
        ProjectStore(p)
    con = sqlite3.connect(p)
    assert con.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0] == "12"
    assert con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='stage_outcome'").fetchone()[0] == 0
    con.close()
    backups = sorted(tmp_path.glob("p.sqlite.pre-v13-*.sqlite"))
    assert backups, "automatic pre-migration backup is written before the first write"
    restored = tmp_path / "restored.sqlite"
    shutil.copy(backups[-1], restored)
    monkeypatch.undo()
    with ProjectStore(restored) as again:                        # restore + rerun migration is idempotent
        assert again.db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0] == "13"
        assert again.db.execute("SELECT COUNT(*) FROM extraction").fetchone()[0] == 1


def test_database_newer_than_reader_is_refused(tmp_path):
    db, _ = _store(tmp_path, sheet_pdf(body_words=60))
    db.db.execute("UPDATE project_meta SET value='99' WHERE key='standalone_schema'")
    db.db.commit()
    db.close()
    with pytest.raises(ValueError):
        ProjectStore(tmp_path / "p.sqlite")
