# Development status — Claude increment WIN-R01 (7 Nov 2026), version 0.11.0-dev0 + changes

Baseline: ChatGPT Rev Q (imported unmodified as commit `b147c4f`). Everything below is *development* software, **not**
engineering-validated. Gate vocabulary: `PASS` (executed, evidence kept), `FAIL`, `BLOCKED`, `NOT_RUN`, `NOT_IMPLEMENTED`.

## 1. Gates (evidence in `TEST_RESULTS/WIN312_R01/`)

| Gate | Status | Evidence / note |
|---|---|---|
| Frozen R1 archive unchanged (SHA-256 `09174700…25e2`) | PASS | `tools/release_preflight.py`; `contracts/*_UNMODIFIED.zip` untouched |
| Original R1 checker tests (16) on Python 3.12 / Windows | PASS | `r1_original_checker_tests.txt` |
| Rev Q regression on Windows Python 3.12.10 | PASS | 175 baseline: 168 pass, 3 environment failures (no Tesseract binary ×2, no symlink privilege ×1) → fixed, see CHANGELOG |
| Current full suite (`pytest tests`) | PASS (see `pytest.txt` for final count) | includes 40+ new tests (OCR, isolation, pipeline, findings, GUI, reader fixes) |
| Release preflight (source isolation, worker→R1 schema/hash) | PASS | `preflight.json` |
| Real-Windows GUI starts, imports, analyses, reviews, exports (native Qt platform, scripted) | PASS | `tests/test_gui.py` (offscreen), `tools/gui_screenshots.py` real-platform screenshots at 100/125/150 % in `screenshots/` |
| GUI manual usability review by a person, keyboard-only walk-through, 175 % DPI, multi-monitor | NOT_RUN | needs the owner |
| Frozen app (`PIDReader.exe`, `pid-reader-cli.exe`) builds, CLI import with OCR, isolated batch, GUI launch | PASS | `build_installer.txt`; smoke runs recorded in WORKLOG |
| Offline installer + uninstall | see `docs/WORKLOG.md` (install/uninstall rehearsal result) | unsigned binaries (SmartScreen warning expected) |
| Code signing | NOT_IMPLEMENTED | no certificate |
| Memory/time-limited reader process, cancellation, resume | PASS | `tests/test_win_r01.py` (1.5 GB allocation killed under 512 MB cap; cancel; resume) |
| Hostile / malicious-PDF resilience | NOT_RUN | wrapper limits resources only; no fuzz corpus run |
| Synthetic developer benchmark (90 dev drawings) | PASS (regression only) | tags 1582/1582, lines 425/425, valves 402/466, paths 463/548, **scanned: valves 0/64, paths 0/85** (no raster geometry) after generator fix: all non-scanned variants 100 % — *self-generated, saturated, not independent* |
| Final reserved split (30 drawings) | NOT_RUN | intentionally untouched; scorer logs any use |
| Real-drawing robustness survey (47 public sheets) | PASS as *robustness only* | 46 read, 1 `PID_WORKER_FAILED`; reader median 6 s/sheet (max 78 s with OCR); geometry analysis fails on 12/46 dense sheets (stroke cap); **only 12/46 sheets yielded any named equipment/instrument/valve tag** — real-sheet recognition is weak |
| Independent industrial precision/recall benchmark | NOT_RUN | no labelled real drawings, no independent reviewer |
| Pretrained general symbol detector | NOT_IMPLEMENTED | none qualified; template catalogue + geometry only |
| DEXPI | NOT_IMPLEMENTED (adapter refuses on purpose) | `engineering/dexpi.py` |
| Worksheet host G4–G7 on a host copy | NOT_RUN | no host checkout; candidate package built (`tools/build_worksheet_package.py`) |
| R1 package manifest valid vs frozen schema; sample passes checker | PASS | `STATUS.json` of the package |
| Dependency licences/legal review | NOT_RUN | wheel hashes + declared licences recorded in `DEPENDENCY_REGISTER.csv`; owner/legal decision pending |
| Independent functional-safety / process review | NOT_RUN | |
| Final user acceptance | NOT_RUN | |

## 2. What was added in WIN-R01 (all keep R1 schema 1 and the original R1 API/worker behaviour)

* Windows 3.12 environment, lock file, reparse-point-safe batch input, OCR optional-binary handling.
* **Offline OCR without a system install** (RapidOCR/ONNX) + engine selection; **standalone reader** that reads scanned pages (R1-schema-valid, OCR objects marked).
* **Reader fixes found by the benchmark:** text on upside-down pages was reversed (0 % recall on /Rotate 180 sheets) → corrected per page; touching labels (`HV-383HV-303`) are split.
* **Analysis pipeline** (`analyze_drawing`) chaining geometry → symbols → valves/line styles → template catalogue → signal strokes → OCR → tag/symbol links; idempotent, cancellable.
* **Unified findings/review layer**, **proposed connectivity graph**, **process-isolated reader** (Job Object), isolated/cancellable/resumable batch.
* **New desktop application** (viewer with layered overlays, registers, review, graph, revisions, batch, libraries, reports, audit).
* **Benchmark generator + scorer**, real-library survey tool, Worksheet package builder, PyInstaller + installer scripts, DEXPI refusal adapter.

## 3. Honest limits (do not read around these)

1. **Real P&IDs are mostly not read well yet.** Public sheets are dense (thousands of strokes/curves), often scanned or with partial text layers; tag grammar is conservative; 12/46 sampled sheets produced any named tag.
2. **Scanned sheets: text only.** Valves, symbols and connectivity need vector geometry; no raster line/symbol detection exists.
3. **Dense vector sheets** exceed the geometry analyser's stroke cap (4 000) → text readings only; no tiling yet (H-001).
4. Template catalogue = 11 synthetic declarative templates; **no trained or pretrained symbol detector**.
5. OCR scores are raw engine scores; OCR on line-level text is split into words by character proportion.
6. Connectivity paths mean "ink joins two outlines in this drawing", never verified piping, flow, valve state or loops. No instrument-loop, off-page or flow-direction inference.
7. Resource limits are not a security sandbox. Binaries are unsigned. Installer untested on a clean second machine.
8. Synthetic benchmark numbers are saturated regression checks on drawings produced by this repository's generator.

## 4. Update after real-sheet testing (7 Nov 2026, later session)
* Sheet S023 (public TransCanada P&ID, outlined lettering): named instrument tags 0 → **13** (tiled high-resolution OCR, OCR on text-poor vector sheets, stacked bubble-text assembly, per-bubble magnified re-read). All 13 checked by eye against the render; **not** an independent measurement and **one sheet only**.
* Still failing on S023: **no valves** (filled/curved glyphs), no line-number records (`NPS 20`…), equipment blocks (heater, manifolds) not read as equipment, no flow direction, no loops, title block/tables not parsed.
* Reports now include analysis layers, findings, proposed connectivity, all OCR words and an annotated drawing image (HTML); JSON has the same data without images.
* Full-library run (608 sheets) was started and **stopped after 15 sheets** by the owner; throughput lesson: OCR processes must be thread-limited (`PID_OCR_THREADS`) — three unrestricted OCR engines on four cores ran ~7× slower than one.
