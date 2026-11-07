# Rev U — raster context, duplicate-observation grouping, possible contact graph

## Baseline and binding limits

This is a **real source-code increment** over Rev T, which incorporates the supplied WIN-R01 research-pack snapshot over the earlier Rev Q foundation. It does **not** replace a more recent Windows project checkout without a staged diff. The Master Research/Claude Build Specification Rev A and the frozen Worksheet R1 archive remain unmodified. Approved Q1–Q50 Option A and the five later approved Option A decisions are retained.

## Implemented source

1. **New `engineering/raster_network.py`** builds a bounded pixel-space contextual graph from source-bound raster stroke observations, optionally annotated by separately stored OCR words. It distinguishes *possible* endpoint touches, T-junctions and unresolved X crossings, but never assumes an actual connection, flow direction, pipe service or valve function.
2. **Pixel-to-source transform** uses the existing CropBox/rotation-aware MediaBox normalized frame. Raster and OCR evidence must share source SHA-256 and page transforms. Native source/host output is not altered.
3. **OCR-annotation safety**: local OCR word boxes can be wrong, as demonstrated by an extra `ss` reading on the synthetic fixture. OCR-overlapping strokes are explicitly `OCR_TEXT_OVERLAP_UNRESOLVED` and **remain available for contact proposals**. No OCR-only suppression of process-looking strokes is permitted.
4. **Title-frame evidence**: long edge-aligned border-like strokes are marked `PAGE_FRAME_STROKE_CANDIDATE` and omitted from this contact *proposal* stage only, without removal from source observations or proof of non-piping.
5. **Hough duplicate reduction**: collinear near-identical pixel observations are grouped as `duplicate_observation_groups` rather than represented as distinct engineering contacts. All original source IDs remain. Grouped contacts identify representative source strokes and the number of supporting pixel-pair observations. This grouping is a raster-evidence de-noising method, **not a pipe merge**.
6. **Bounded index/outputs**: separate spatial tiles for contact candidate pairs and OCR/symbol regions; explicit pair, cell, word, contact and JSON budgets refuse over-limit complete analyses rather than silently truncating.
7. **Standalone SQLite schema v11**: append-only raster-network analyses, source-linked candidate records, named review decisions, audit-chain events and pre-upgrade SQLite backups. Source/extraction IDs and R1 host schema are untouched. Previous standalone v10 projects migrate additively.
8. **GUI/CLI/pipeline integration**: `analyze-raster-network`, `raster-contacts`, `review-raster-contact`, automatic `analyze-all` stage, and the generic draft PySide6 finding/overlay layer now expose the new candidates. GUI actual operation remains **NOT_RUN** on Windows.
9. **JSON Schema** `contracts/standalone_raster_network_v1.schema.json`; synthetic scan-only fixture and generator; 16 new synthetic tests plus full inherited regression.

## Reproducible test example

```powershell
py -3.12 -m pip install -e '.[test,raster,ocr]'
py -3.12 -m pytest -q
py -3.12 tools/release_preflight.py
py -3.12 -m pid_reader.cli import-pdf example.sqlite fixtures/synthetic_raster_network_context.pdf --ocr off
py -3.12 -m pid_reader.cli analyze-raster example.sqlite <extraction_id>
py -3.12 -m pid_reader.cli analyze-raster-network example.sqlite <extraction_id> <raster_analysis_id>
py -3.12 -m pid_reader.cli raster-contacts example.sqlite <network_analysis_id>
# Named, reasoned review only: CONTACT_AS_DRAWN means observed contact on paper, NOT real physical plant connectivity.
```

## Technical caveats and unfinished product gates

- Hough strokes are not clean centreline vectors; thick ink can generate multiple near-overlapping observations. Grouping reduces, but does not eliminate, duplicated junction proposals.
- Source SHA-256 and canonical hashes prevent accidental content changes but **are not an authenticating signature**; recomputation of derived contexts catches rehashed proposal forgery within this bounded algorithm, but the initial raster geometry itself still requires source/detector verification and independent review.
- Long page-edge lines could be real drawing objects; border classification is a proposed explanation only, not a deleted source record.
- `OCR_TEXT_OVERLAP_UNRESOLVED` is not reliable proof of typography. Incorrect OCR can overlap real pipework. Do not equate word boxes with accepted text masks.
- Results are tested on generated **synthetic** drawings and programmatically constructed source-backed stroke test records, not an independently labelled industrial corpus.
- Dense industrial scan speed, false-positive rates, missing junctions, precision/recall, S023 and the 46-sheet re-run, Windows/PySide6 runtime, actual Worksheet G4–G7 integration, independent safety review, DEXPI compliance, pretrained vision recognition and installer remain `NOT_RUN`/`BLOCKED`/`NOT_IMPLEMENTED` as appropriate.

## Recommended next code increment

Improve raster centreline reconstruction and short-stroke continuity *as hypotheses only*; add explicit user-reviewed text/legend exclusion regions and source-linked loop traces. Independently test against rights-cleared industrial scans rather than optimising only for synthetic geometry.
