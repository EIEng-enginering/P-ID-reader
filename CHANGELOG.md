# Changelog

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
