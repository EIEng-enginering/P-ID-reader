# HANDOFF_STATE — Rev X upgrade

**Branch:** `claude/rev-x-upgrade` (from `main` @ e676ff1). **Nothing pushed.** Version 0.18.0-dev0, standalone DB schema v13. Python: `C:\PIDWork\venv312\Scripts\python.exe`; run tests with `PYTHONPATH=src` (two subprocess tests need it).
**Package:** `C:\PIDWork\revx_pkg\PID_Reader_Full_Upgrade_Claude_Rev_X_Approved` (specification only, unmodified); baseline expanded under `C:\PIDWork\revx_pkg\baseline_expanded`; pristine baseline copy `C:\PIDWork\baseline_src`.
**Editing rules learned:** Python edits read/write with `newline=''` (files are LF; text mode on Windows converts to CRLF; `Path.read_text(newline=)` does not exist on 3.12). Long bash heredocs can fail to parse: write patch scripts to the scratchpad and run them. Stage Git paths explicitly; never `git add -A`.

## State
All work packages are committed with tests; the per-package state, notes and blockers are in `docs/rev_x/WPU_STATUS.md` (generated from `WPU_STATUS.json`). Q1–Q100 traceability: `docs/rev_x/REQUIREMENTS_TRACEABILITY_REV_X.csv` (regenerate with `tools/build_rev_x_traceability.py`). Owner checklist: `docs/rev_x/OWNER_REVIEW_CHECKLIST.md`.
Final evidence: `TEST_RESULTS/REV_X/` (baseline, final suite, R1 checker, preflight). Owner ZIP: `tools/build_rev_x_owner_pack.py`. Installer: PyInstaller spec unchanged (`packaging/pid_reader.spec`); build into a separate dist folder, then `packaging/Install-PIDReader.ps1` with `-ExecutionPolicy Bypass` and a payload zip that has a top-level `PIDReader` folder.

## Not done (see `docs/OPEN_ISSUES.md` X-001…)
Independent accuracy benchmark and gold (owner), real-host copy test (owner), DEXPI export (BLOCKED: no XSD/validator), ONNX detector, raster port graph, viewer relation overlay, hostile-PDF fuzz, manual DPI/keyboard review, code signing, legal licence review, push.

## Boundaries (unchanged)
Frozen R1 untouched; proposals only; no HAZOP/LOPA/SIL/IPL conclusions; reserved final split never used; `Example P&IDs/` git-ignored; no standards text or vendor catalogues copied; no real-host changes; no uploads.
