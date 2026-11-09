"""Public, import-safe SDK for the standalone engineering-intelligence layer (Rev X, WPU-14).

Typed functions over project *files*; callers never touch SQL tables. This is separate from the frozen Worksheet R1 API
(:func:`pid_reader.api.read_pid`), which is unchanged. Everything returned is a drawing-based proposal, offline, never a plant verification.

    from pid_reader.standalone_intelligence import analyze_pdf, get_snapshot, export_package, validate_snapshot

Importing this module has no side effects (no Qt, no OCR model load, no file access).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["SCHEMA_VERSION", "analyze_pdf", "get_snapshot", "export_package", "validate_snapshot", "list_runs"]
SCHEMA_VERSION = "engineering-intelligence-v1"


def analyze_pdf(project_path: str | Path, pdf_path: str | Path, *, preset: str = "standard", ocr_engine: str | None = "auto",
                library_symbols: bool = True) -> dict[str, Any]:
    """Import ``pdf_path`` into the project (if new) and run the full analysis. Returns ids, status and per-stage outcomes."""
    from .api import ReadParams
    from .engineering.pipeline import analyze_drawing
    from .engineering.project import ProjectStore
    from .engineering.standalone_read import read_pid_standalone
    pdf = Path(pdf_path)
    data = pdf.read_bytes()
    with ProjectStore(project_path) as db:
        result = read_pid_standalone(data, ReadParams(), filename=pdf.name, ocr_engine=ocr_engine)
        eid = db.add_extraction(result, source_pdf_bytes=data)
        out = analyze_drawing(db, eid, ocr_engine=ocr_engine, preset=preset, library_symbols=library_symbols)
    return {"extraction_id": eid, "run_id": out["run_id"], "status": out["health"]["drawing_status"], "diagnostic_codes": out["health"]["codes"],
            "stages": {o["stage_id"]: o["status"] for o in out["outcomes"]}, "proposal_only": True}


def list_runs(project_path: str | Path, extraction_id: str) -> list[dict[str, Any]]:
    from .engineering.project import ProjectStore
    with ProjectStore(project_path) as db:
        return [{"run_id": r["run_id"], "status": r["status"], "preset": r["preset"], "created_utc": r["created_utc"], "engine_version": r["engine_version"]}
                for r in db.db.execute("SELECT run_id,status,preset,created_utc,engine_version FROM intelligence_run WHERE extraction_id=? ORDER BY created_utc, rowid", (extraction_id,))]


def get_snapshot(project_path: str | Path, extraction_id: str, run_id: str | None = None, *, validate: bool = True) -> dict[str, Any]:
    """The ``engineering-intelligence-v1`` document for the latest (or given) run; raises ``ValueError`` if it fails schema validation."""
    from .engineering.intelligence import build_snapshot, validate_snapshot as _validate
    from .engineering.project import ProjectStore
    with ProjectStore(project_path) as db:
        snap = build_snapshot(db, extraction_id, run_id)
    if validate:
        problems = _validate(snap)
        if problems:
            raise ValueError("Snapshot failed validation: " + "; ".join(problems[:5]))
    return snap


def export_package(project_path: str | Path, extraction_id: str, folder: str | Path, *, run_id: str | None = None) -> Path:
    """Write the AI-ready package into a new sub-folder of ``folder`` (never overwrites). The caller chose ``folder``."""
    from .engineering.intelligence import export_package as _export
    from .engineering.project import ProjectStore
    with ProjectStore(project_path) as db:
        return _export(db, extraction_id, folder, run_id=run_id)


def validate_snapshot(snapshot: dict[str, Any]) -> list[str]:
    """Schema and reference problems of a snapshot (empty list means valid)."""
    from .engineering.intelligence import validate_snapshot as _validate
    return _validate(snapshot)
