# Revision X — Implemented WP-01, WP-02 and WP-03 integration slice

**Source baseline:** Rev W 0.17.0-dev0, cumulative; Rev X 0.18.0-dev0.
**Intended merge target:** owner's newer Windows 11 / Python 3.12 repository at c2935a8 or later. Actual target repository was not writable/available in this Linux session. **Do not replace target files wholesale.**

## What has actually been coded

**WP-01 text-to-engineering proposals** (`wp123_recovery.py`, `wp123_roi.py`):
- Import the standalone OCR word CSV used on S418, or run the existing offline OCR preview. Source PDF SHA is recorded. Import can also require an explicitly supplied expected source SHA.
- Parse strict, configurable-starter engineering prefixes (`V`, `FE`, `P`, `PT`, `PIC`, etc.) and full service-sequence-size-spec-schedule line numbers as **proposals**. Reject lone letters, valve figures, company names, and standalone specification codes.
- Join *only* geometrically adjacent short code/number fragments; suppress embedded substring `P-00019` when a complete line observation `PF-00019-14.3-A3S-40` occupies the same source area.
- Preserve uncertain line-number-like strings as **fragments** for review rather than inventing completed line numbers.
- Extract candidate sheet-mark, drawing number, date, scale and location fields; preserve conflicting dates. Keep title blocks separately from process objects.
- Optional local, explicit-region high-resolution Tesseract re-reading with CropBox-aware coordinates. No cloud calls or model training. The S418 manual ROI manifest is **drawing-specific** and must not become a universal crop definition.

**WP-02 model/geometry hygiene** (`wp123_recovery.py`, `wp123_bubbles.py`):
- Distinguish document metadata and drawing-frame regions (AUTO bottom region only with OCR cues; explicit S418 frame profile opt-in).
- Retain all detector proposals while marking `BELOW_UNCALIBRATED_DETECTOR_GATE`, `DOCUMENT_METADATA_REGION`, `DRAWING_FRAME`, `OVERSIZED_BOX`, `UNVERIFIED_GENERAL_CLASS` and duplicate-box withhold reasons.
- Optional, offline OpenCV circular-outline observations anchored to OCR instrumentation clues. These are **circle hypotheses**, not ISA symbol classification. Source boxes are mapped to original PDF page geometry; cropped/rotated PDF work needs testing against actual Windows renderer.
- Existing learned detector weights are **not** included in this ZIP. The existing 65 S418 detections are consumed as source evidence; no trained model is claimed.

**WP-03 evidence association and review** (`wp123_recovery.py`, `wp123_store.py`):
- Deterministic, geometry-bounded, mutually restricted tag/detector matching. Competitions, low-confidence detections and ambiguous pairs abstain, rather than creating a false association.
- Link OCR function/loop clues with OCR-anchored bubble contours as **reviewable evidence**, with no automatic instrument loop approval.
- Export JSON + equipment/instrument/piping proposal CSV + detector triage + document fields + incomplete-line queue + bubble/association tables.
- Separate, additive SQLite sidecar supports immutable analyses and append-only, named, reasoned, SHA-chained decisions. No changes to frozen Worksheet R1, accepted host assets or Worksheet database.
- A strict standalone JSON Schema and standalone verifier are included.

## S418 evidence — what changed and what did NOT

S418 is a one-page raster scan, Windows c2935a8 analysis, with 581 OCR words, 65 learned detections, 428 old symbol candidates and zero official structured graph objects. **No independent gold annotations exist.**

Using the stored 581 OCR words and 65 detections, the new bridge produces a **nonempty proposed register**. With three *manually selected* Tesseract rereading ROIs and OCR-anchored circle observations, the demonstration produces:

- **762 OCR observations** (581 original plus 181 supplemental observations; duplicate text can remain as distinct source observations).
- **8 proposed reading occurrences** (five tag occurrences; three complete-line-form strings), including visible `FE-2202`, `FE-2206`, `V-2201`, `Q-2200` when the manual ROI is enabled.
- **16 incomplete line-number-like strings** preserved as review tasks, not accepted line readings.
- **7 candidate document-metadata field observations** (including `030` drawing number vs `012` top sheet mark, with conflicting date alternatives preserved).
- **23 OCR-anchored circle proposals** and **4 circle-to-OCR-code evidence links**. One circle has both code-like and number-like words but no accepted instrument loop.
- **65 existing detector boxes triaged; 0 passed the eligibility gate**. This is deliberate: the existing model's uncalibrated S418 classes/scores are not reliable enough to attach tags automatically.
- **0 reviewed objects and 0 accepted engineering connections.** Engineering accuracy, recall and precision remain `NOT_RUN`.

The existing R1 result is **not changed**, and no valid DEXPI or HAZOP/LOPA content is claimed. The new sidecars demonstrate recovery of some useful unverified information, **not** an accurate digital twin.

## Boundaries, blockers and next actions

- The owner's actual Windows repository is newer than this Rev W-derived checkpoint. Claude should selectively merge the modules and CLI functions, not overwrite `project.py`, `migrations.py`, worker, packaging or the newer detection pipeline.
- `PaddleOCR` was researched but **not installed**, bundled or executed here. The optional PP-OCRv5/PP-OCRv6 comparison and correct model licensing remain open. Existing Tesseract and optional RapidOCR paths remain supported.
- Raster circle proposals, tag grammars and document region boundaries require independent labelled accuracy testing and site-configuration profiles; the manually selected S418 ROI is not an automatic universal solution.
- Source OCR CSV from the Windows analysis lacks a per-row authenticated source signature. Source PDF and detector JSON SHA are checked; the CSV origin must be reconciled with the original analysis manifest during the Windows merge.
- This module does **not** reconstruct the complete process network or automatically create accepted graph entities. The next meaningful stage is checked source-data reconciliation into the newer Windows review/graph view, followed by owner-supplied labels on S418 and other held-out drawings.
- All host integration and Windows UI/system testing remain `NOT_RUN`. No licence review or independent engineering approval is claimed.
