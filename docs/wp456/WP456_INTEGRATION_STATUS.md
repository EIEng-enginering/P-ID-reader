# WP-04..06 integration status (branch `claude/wp456-integration`, from main c0908b9; nothing committed or pushed)

Source: ChatGPT pack `PID_READER_WP04_WP05_WP06_REV_A`. The pack's snapshot hashes (15 files) matched main c0908b9 exactly, so the three GUI hunks applied cleanly (`install_wp456.py --check` then `--apply`). Worksheet R1 contract/API/worker, standalone DB v13 and every existing module except the two fixes below are untouched. All output is PROPOSED_UNVERIFIED; the reference `reference_wp123_recovery.py` is evidence only and is not in `src/`.

## Added
- `engineering/wp456/` (common, ocr, readings, symbols, topology, metrics, pipeline, store, host), `ui/wp456_tab.py` (tab "WP-04-06 proposals"), `tests/wp456/` (80 pack tests), contracts, examples, `tools/replay_s418.py`, `tools/score_wp456_result.py`, `tools/run_wp456_checks.py`, docs under `docs/wp456/`, replay evidence under `examples/wp456/evidence/` (replay tool paths adapted to it).
- Review sidecar: `%LOCALAPPDATA%\PIDReader\wp456\review.sqlite` or `PID_WP456_STORE`; analyses immutable, decisions append-only and hash-chained; separate from the WP123 sidecar and from the project.
- New repository tests: `tests/test_wp456_gui.py` (5, offscreen Qt: task lifecycle, stale-result guard, cancel, no-Tesseract message, review scope, export, isolation) and `tests/test_wp456_frames.py` (13: rotated 0/90/180/270 x uncropped/asymmetric CropBox, page sizes, outside-crop refusal).

## Changes made to the pack or the repository
1. `host.dimensions` used the unrotated MediaBox, which swaps width/height on 90/270 degree pages (it feeds the physical-distance rules of the symbol associations). It now uses the host PageFrame media frame.
2. `ocr.tesseract_tsv` adds `CREATE_NO_WINDOW` on Windows so the windowed app does not flash a console per OCR call.
3. Tab: the reviewer name comes from the app's saved reviewer (`main.reviewer()`), like the other review tabs, instead of a free-text prompt per decision.
4. **Existing-code fix (`formats/page_coordinates.py`)**: `frame_from_pdfplumber` took pdfplumber's CropBox as is, but for 180/270 degree pages pdfplumber reports the same box as for 0/90, so an asymmetric CropBox shifted every rendered/overlay box by the margin difference (10 pt in the test; checked against PDFium and pdfplumber's own rectangle coordinates). The box is now mirrored for 180/270. Symmetric crops and 0/90 pages are unchanged; related existing tests pass.

## Task lifecycle checks (code review of the tab, then tests)
Words, detections and geometry are gathered on the GUI thread; the worker gets plain data only. Busy state is released on result, error and stopped. A worker result is dropped if the open PDF or page changed. Opening a drawing resets the tab. Re-read without Tesseract shows a message and starts no task. `geometry_from_project` was verified against the real S418 project tables (353 centrelines, all `UNKNOWN`, read-only).

## S418 (see the return ZIP)
Replay reproduces the pack: 8 readings stay 8, document fields 7 -> 6 (duplicate NTS merged), 353 UNKNOWN geometry edges (not pipes), 0 symbol links, 0 reviewable detector boxes. A real automatic Tesseract re-read (48 calls, ~10 s, 788 observations) changed none of the readings: the known line-number and FR/720201 misreads are not improved, and V-2201 is still not found automatically. Accuracy is NOT_RUN: the annotation is a DRAFT and the scorer returns NOT_RUN for it.

## Gates
Not run: Worksheet host G4-G7, real Windows DPI / multi-monitor / installer / frozen build, independent benchmark, held-out accuracy.
