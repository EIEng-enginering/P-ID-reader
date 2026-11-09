# Changelog

## Unreleased — save each drawing as its own files
### Added
- File ▸ "Export open drawing as files…" (Ctrl+E), "Export all drawings as files…" (Ctrl+Shift+E) and a button on the Report tab. A folder picker opens on every export; nothing is written on import.
- Per drawing, named after the original PDF: `NAME.json` (full readings report), `NAME.html` (annotated report), `NAME.graph.json` and `NAME.graphml`. A multi-page PDF is one set. Existing files are never overwritten: a clash saves the whole set as `NAME (2)`, `NAME (3)`…
- CLI `export-drawings DATABASE FOLDER [--extraction-id ID]`; module `engineering/drawing_export.py`.
- Output is unverified proposals, as for all other exports; frozen R1 contract unchanged.

## WIN-R01 — 2026-11-07 (Claude Code on top of ChatGPT Rev Q 0.11.0-dev0)
### Fixed
- Batch input rejects any Windows reparse point (symlink/junction), not just POSIX symlinks; symlink test skips without privilege and a simulated-reparse test was added.
- OCR preview no longer fails when the Tesseract binary is absent but a word engine is injected.
- Upside-down pages (`/Rotate 180`) returned reversed tags (0 % recall in benchmark) — now re-ordered per page with a warning.
- Touching labels such as `HV-383HV-303` are split into two readings (marked `split_from_touching_labels`).
### Added
- RapidOCR offline backend and `--engine/--ocr` options; `read_pid_standalone` (OCR for scanned pages, R1-schema-valid); standalone worker.
- `analyze_drawing` pipeline, `findings` review layer, `connectivity` graph, `isolation` (Job Object) + batch isolation/cancel/progress, disabled `dexpi` adapter.
- New PySide6 application (`pid-reader gui`), `gui-legacy` retains the old viewer.
- Tools: benchmark generator/scorer, library survey, GUI screenshots, Worksheet package builder; PyInstaller spec and installer scripts.
- Docs: USER_GUIDE, WIN_R01_STATUS, ADRs, issues W-001…W-012; `requirements-lock-win312.txt`.
### Unchanged by design
- R1 contract ZIP, `api.read_pid` behaviour, worker protocol and exit codes, R1 schema v1, standalone DB schema v9.

## Rev W integration + teach-by-example (7 Nov 2026, later)
- Integrated ChatGPT Rev W (0.17.0-dev0: raster geometry, hardened publication/isolated-reader checks, benchmark registry); OpenCV 4/5 compatible; 312 tests green on Windows.
- Added: teach-by-example symbol finder (additive tables, audited review, Findings layer, viewer teach mode), sheet-information extractor, reading checks and loop groups, Excel export, canonical graph JSON (validated against the spec schema) and GraphML, Sheet info tab, report sections, CLI commands.
- Fixed: raster-layer row-limit crash in report/workbook/GUI; console encoding crash on OCR characters.
- Tests: 327 passing, 6 skipped (Tesseract binary absent, symlink privilege).

## Fix: scanned sheet failed with "PID_WORKER_FAILED (exit 4)" (9 Nov 2026)
- Cause: the saved OCR engine was Tesseract, which is not installed; scanned sheets need OCR so the reader process crashed, and the message hid the reason.
- Now: an uninstalled engine is refused with a clear message (`PID_OCR_ENGINE_UNAVAILABLE`); the app falls back to Automatic when the saved engine is missing and greys out missing engines in Tools → OCR engine; unexpected reader errors report the exception type (`PID_MEMORY` for out-of-memory).
- Verified: full suite 331 passed / 6 skipped; S333 imports in the app with the Tesseract setting saved (18 readings).
