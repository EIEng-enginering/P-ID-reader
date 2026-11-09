# HANDOFF_STATE — Rev X upgrade (updated as work proceeds)

**Branch:** `claude/rev-x-upgrade` (from `main` @ e676ff1). Remote not touched. Python: `C:\PIDWork\venv312\Scripts\python.exe`; run tests with `PYTHONPATH=src` (two subprocess tests need it).
**Package:** `C:\PIDWork\revx_pkg\PID_Reader_Full_Upgrade_Claude_Rev_X_Approved` (spec only, unmodified); baseline expanded under `C:\PIDWork\revx_pkg\baseline_expanded`. Pristine baseline run copy: `C:\PIDWork\baseline_src`.
**Editing rule learned:** Python edits must read/write with `newline=''` (files are LF; text mode on Windows converts to CRLF). Long bash heredocs can fail to parse: write patch scripts to the scratchpad and run them.

## Done (committed)
* WPU-00: baseline hashes verified (package 61ca7b4a…, R1 zip 09174700…), snapshot == local main; baseline 334 passed/6 skipped and R1 checker 16 passed recorded in `TEST_RESULTS/REV_X/`. Tools: `tools/record_test_evidence.py`.
* WPU-12 (migration part): schema **v13** additive tables (`intelligence_run`, `stage_outcome`, `page_region`, `engineering_item`, `intelligence_snapshot`, `intelligence_decision`), append-only triggers, backup + interrupted-migration tests. API: `engineering/intelligence_store.py`.
* WPU-01: `stage_telemetry.py` (StageOutcome, health, drawing_status, OCR diagnostics codes), wired into `pipeline.analyze_drawing` (`outcomes`, `health`, `run_id`, `preset`, `record`).
* WPU-02: `page_regions.py` (page encoding classes, regions incl. ruled tables/revision/notes/title/border).
* WPU-03: `ocr_adaptive.py` (orientation/contrast/scale re-read, alternatives, confusion alternatives) + per-tile failure counters in `formats/ocr_source.py`.
* WPU-04: `engineering_text.py`, `table_parse.py`, `doc_text.py` (pipeline stage `doc_text`).

## Next (see 07_WORK_PACKAGES.md in the package)
WPU-05/06 symbol library + detection (raster/tiles), WPU-07 geometry tiling, WPU-08/09 junctions/direction/typed-port graph v2, WPU-10 loops/safety guards, WPU-11 cross-sheet/revisions, WPU-13 UI, WPU-14 intelligence export/SDK/AI package, WPU-15 DEXPI status, WPU-16 gold tools/scorer, WPU-17 CPU presets/security, WPU-18/19 SBOM, notices, traceability, installer, owner pack.

## Boundaries (unchanged)
Frozen R1 untouched; proposals only; no pushes; `Example P&IDs/` is git-ignored (stage explicit paths, never `git add -A`); reserved final benchmark split never used; no standards text/vendor catalogues copied; no real-host changes.
