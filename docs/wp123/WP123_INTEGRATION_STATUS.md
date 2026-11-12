# WP-01..03 integration status (branch `claude/wp123-integration`, from main c2935a8)

Source: ChatGPT package `PID_Reader_WP01_WP02_WP03_*_Rev_X` (its own "Rev X"/0.18.0 label is unrelated to this repository's Rev X; the code was merged selectively, nothing was replaced). Only the nine WP123 files (4 modules, 3 test files, `tools/check_wp123.py`, schema) were added; the older cumulative snapshot in the Full ZIP was NOT used. Worksheet R1 contract, API, worker, standalone DB v13 and every newer module are untouched. All WP123 output is PROPOSED_UNVERIFIED.

## What was integrated
- `engineering/wp123_recovery.py`, `wp123_roi.py`, `wp123_bubbles.py`, `wp123_store.py` (Qt-free), `contracts/standalone_wp123_result_v1.schema.json`, `tools/check_wp123.py`.
- CLI (patch re-applied to the current `cli.py`): `recover-wp123`, `wp123-review`, `wp123-audit`; added `--page`.
- Windows review: tab "WP-01-03 proposals" (`ui/wp123_tab.py`) + `engineering/wp123_session.py`; overlay layer `wp123` on the sheet.

## Changes made to the supplied code (and why)
1. `infer_regions` is per page (the original hard-coded page 1, so page N would have borrowed page 1's layout). Page 1 results are byte-identical (S418 result hash reproduced).
2. Detector boxes from TR1 records are normalised to the *rendered* (CropBox/rotated) page; WP123 assumes the media frame. `read_detectors(..., page_frame=)` / `normalise_detections` map them (identity on uncropped pages such as S418). CLI and GUI pass the frame.
3. `supplemental_ocr` raises `TesseractUnavailable` (CLI exit 3, clear message) instead of a raw pytesseract error; its test skips when the program is absent.

## Review interface rules
- Proposals and decisions live only in the WP123 sidecar (`%LOCALAPPDATA%\PIDReader\wp123\wp123_review.sqlite`, or `PID_WP123_STORE`): immutable analyses, append-only SHA-chained decisions with a named actor and a required reason. Nothing is written to extraction, project tables, the R1 payload, or the TR1 correction queue.
- Accept / Correct only for readings, incomplete line strings and document fields. Detector boxes and circles can only be rejected or left unresolved (accepting a symbol class stays in the guarded TR1 window).
- "Accept as printed" means the printed text reads like this. It is not a verified tag, connection, DEXPI claim, or HAZOP/LOPA/SIL/IPL input.
- Words come from the stored OCR analysis of the open page, else the native text layer; detections only from a saved TR1 run (the tab never runs the detector).

## Open / NOT_RUN
- Tesseract ROI re-read: program not installed on the development laptop (NOT_RUN here).
- No gold labels: precision/recall/exact-match/abstention remain NOT_RUN. S418 comparison is counts plus an analyst visual check of 16 items (`examples/` and the S418 comparison ZIP), not an accuracy score.
- Not touched: host G4-G7, installer/frozen build, DPI testing, licence review, optional PaddleOCR/SAHI.
