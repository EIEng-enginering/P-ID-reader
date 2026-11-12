# Changelog

## Unreleased - WP-07 model comparison (branch claude/wp07-integration, not committed)
### Added
- `engineering/model_lab/` and tab "Model comparison": isolated, cancellable CPU workers for EasyOCR, TrOCR small printed and RF-DETR P&ID; per-crop cache; audited review sidecar; frozen-build worker archive.
- `model_lab/consensus.py` (chooses among observed strings only), crop variants in `pipeline.prepare`, `tools/wp07/eval_configs.py`, `eval_bubbles.py`, `score_reference.py`, DRAFT references in `examples/wp07/`.
### Fixed (found on Windows)
- EasyOCR/RF-DETR edge-overshooting boxes no longer lose the whole crop (3 of 20 S418 tiles were lost).
- EasyOCR input bounded to 1.3 Mpx: worker peak 9.1 GiB to 3.96 GiB, page time 842 s to 378 s.
- Peak memory is reported on Windows (psutil peak working set).
### Not changed
- Worksheet R1 contract/API/worker, standalone DB v13, detector gate (.65), baseline switches. No accuracy claimed; no line-label improvement demonstrated.

## Unreleased - WP-04..06 (branch claude/wp456-integration, not committed)
### Added
- `engineering/wp456/` and tab "WP-04-06 proposals": evidence-preserving OCR de-duplication, bounded local Tesseract re-read (UTF-8 TSV), line/bubble review states without invented characters, exact-string scorer (NOT_RUN without an approved reference), detector-gate-preserving symbol and association proposals, conservative geometry graph, separate review sidecar.
### Fixed
- `frame_from_pdfplumber`: asymmetric CropBox on 180/270 degree pages shifted boxes (mirrored now).
- WP456 page sizes follow the rotation-aware frame (were swapped on 90/270 degree pages).
### Not changed
- Worksheet R1 contract/API/worker, standalone DB v13, detector gate (.65), all switches.

## Unreleased - WP-01..03 text-to-engineering proposals (branch claude/wp123-integration)
### Added
- `engineering/wp123_*`: OCR-to-tag/line-number/title-block proposals, detector triage (withheld, never deleted), OCR-anchored circle evidence, abstaining tag-to-detector association, isolated append-only review sidecar; schema `contracts/standalone_wp123_result_v1.schema.json`, `tools/check_wp123.py`.
- CLI `recover-wp123` (with `--page`), `wp123-review`, `wp123-audit`.
- Windows tab "WP-01-03 proposals" with evidence-to-sheet navigation, named/reasoned decisions, triage summary, CSV export; viewer layer `wp123`; `engineering/wp123_session.py`.
### Changed (in the supplied code)
- Regions inferred per page; TR1 render-frame boxes mapped to the media frame; clear error when Tesseract is missing.
### Not changed
- Worksheet R1 contract/API/worker, standalone DB v13, all switches. No proposal is accepted automatically.

## Unreleased - R3 components (branch claude/r3-integration; every switch OFF by default)
### Added
- `PIDLAB_TILE_MERGE_R3` (r1_drop_inner_edge default | edge_safe | edge_safe+coarse): Grok `tiled_r3` seam-merge policies; the default still runs the unchanged R1 rule.
- `GuardedQueue`: machine actors can only import proposals; submit, second review and adjudicate need a named human.
- `PIDLAB_TAG_ASSIGN_R3` (tag-to-detection assignment with abstention), `PIDLAB_GRAPH_CONSERVATIVE_R3` (join hints only, never connections), `PIDLAB_FINE_CLASS_R3` (subtype proposal ids, names unverified; card `models/R3_FINE_CLASS_CARD.json`).
- Detections window: subtype, seam-stitched and tag-proposal columns, Join hints button; menu items and merge-policy choice.
- Packaging spec ships the detector script and model cards; `docs/tr1_integration/R3_INTEGRATION_STATUS.md`.
### Not integrated
- Stacked OCR (negative), ONNX path (E6-10 failed), R3 detector arms (all failed against E5), Grok offline trainer (research tool).

## Unreleased - TR1 learned-symbol integration (branch claude/tr1-integration; every switch OFF by default)
### Added
- `src/pid_reader/tr1/`: switches (`flags`), learned detector runner (`detector`; torch-free, runs the detector in a separate process with timeout, cancel and tree kill), stand-alone detector script (`infer_cli.py`, Grok E5 method), coarse-class to catalogue-family mapping (`mapping`), symbol catalogue v1.0.0 (`catalogue`), hash-chained correction queue (`corrections`, plus the CONFIRM kind), review service (`review`), versioned training batches (`batches`, `batch_export`).
- UI: "Learned detector (TR1, proposed)" menu and detections window (overlay layer; confirm, change class, not a symbol, leave unresolved, second review, batch export).
- CLI: `tr1-status`, `tr1-detect`.
- `tools/tr1_train/`: separate offline trainer (Job Object guard, resume to identical weights, seed 20261110, tile preparation, model registry).
- `models/E5_MODEL_CARD.json` and `models/E5_weights_epoch_02.pt` (sha256 6f636fac...; weights are git-ignored), `requirements-tr1-torch.txt` (optional component).
- Tests: `tests/test_tr1_*.py`; `tests/conftest.py` isolates the TR1 switches and data folder for every test.
### Unchanged
- With every switch OFF no TR1 code path runs and nothing is written. The frozen R1 contract, API, worker, schema v13 and pipeline output are untouched.

## Unreleased — baseline-diagnostic fixes 1 to 4 (branch claude/baseline-fixes-1-4)
### Fixed
- OCR: two overlapping tiles could report one drawn token inside two different lines; the proportional split then produced two words with the same id and the whole OCR result was rejected (R5-007). Such words are now merged at word level (higher raw score kept, merge count in the OCR diagnostics). Validators are unchanged.
- Pipeline: when OCR registration fails the unregistered words are no longer used by the raster network, health, graph, loops or document text. This also removes the raster-network mismatch seen on every sheet whose OCR failed.
- Geometry: two identical rectangles or circles no longer share a shape id (and therefore symbol and port ids); the first copy keeps its previous id, repeats get an occurrence number.
- Diagnostics: the drawing status is evaluated after the symbol-library, graph, loops and document-text stages; the symbol-library stage records why a page was partial; stage outcomes record the candidates they produced.
- New tests: tests/test_baseline_fixes.py (9). No schema change, frozen R1 contract unchanged.

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
