# Rev S implementation notes - executable raster geometry increment

## Baseline and integration status
This code is a **cumulative copy of Rev R**. Rev R was based on the WIN-R01 source snapshot attached to the user's research pack, merged with the earlier Rev Q cumulative source. **It is not verified against the latest live Windows checkout.** Perform a three-way reconciliation before any push, overwrite, installer release or Worksheet host integration. The full Master Research/Build Specification Rev A is unchanged under `contracts/`.

## Implemented in source, this increment
1. `engineering/raster_geometry.py` provides a new optional OFFLINE raster evidence layer for PDF pages with no native straight vector strokes. PDFium renders locally, OpenCV produces bounded line observations, and a constrained paired-filled-triangle detector proposes horizontal or vertical **filled bow-tie valve-like glyphs**. Neither a line stroke nor a proposed glyph is a verified process connection, valve function, physical configuration or safe operation.
2. **Source coordinates:** every observation uses the PDFPLUMBER_MEDIA_NORMALIZED_V1 normalized top-left frame, including CropBox and page rotation. Rendering-downscale warnings are explicit. Original images and source hashes remain the authority.
3. **Resource limits:** 16 MiB input, up to 12 selected raster pages per analysis, up to 8 million rendered pixels/page, 7,000 observed strokes, 750 glyph candidates, 8 MiB JSON. At excessive size, auto-resolution can reduce DPI down to 72 with an explicit warning; beyond budgets the analysis refuses rather than returning partial false completeness.
4. `engineering/migrations.py` adds **standalone SQLite schema v10** with immutable raster analyses and proposed valve records; migration creates a pre-v10 backup for existing projects. `ProjectStore` provides source/hash checks, idempotent storage, candidate queries, named append-only reviews and hash-chain audit.
5. `engineering/pipeline.py` integrates raster processing *separately* on selected pages with no native line strokes; manual `analyze-raster` can also target specific pages. The frozen R1 `read_pid` and its worker output have NOT been expanded.
6. `engineering/findings.py` and the draft PySide6 desktop source expose the raster-filled-glyph review layer. CropBox-aware page overlays are implemented in the viewer source. PySide6 Windows display has NOT been run here.
7. CLI: `raster-preview`, `analyze-raster`, `raster-valves`, `review-raster-valve` plus the existing `analyze-all` pipeline.
8. `contracts/standalone_raster_geometry_v1.schema.json` defines the new immutable standalone output, distinct from Worksheet R1.
9. Synthetic one-page **scan-only** fixture: horizontal and vertical filled bow-ties; negatives: a single arrowhead, non-valve X-crossing, box/text and independent line. It was rendered to PNG and visually inspected. Do not count as a real P&ID accuracy case.

## Suggested local reproduction
```powershell
py -3.12 -m pip install -e '.[test,raster]'
py -3.12 -m pytest -q
py -3.12 tools/release_preflight.py
py -3.12 -m pid_reader.cli raster-preview fixtures/synthetic_raster_filled_valves.pdf --output-json raster.json
py -3.12 -m pid_reader.cli import-pdf project.sqlite fixtures/synthetic_raster_filled_valves.pdf --ocr off
py -3.12 -m pid_reader.cli analyze-raster project.sqlite <extraction_id>
```

OpenCV's `opencv-python` distribution is used by the existing WIN-R01 Windows dependency lock; do **not** install `opencv-python` and `opencv-python-headless` simultaneously. `numpy`, `opencv-python`, `pypdfium2`, `Pillow` are optional raster dependencies under `[raster]`. No network, cloud OCR, or user model training is used by the raster layer.

## Important recognition limitations
- The detector is tuned to two **filled** isosceles triangles whose tips meet; it does not recognise most industrial valve drawings, outlines, rotated/skewed or degraded scans, pressure safety valves, control actuator types or service. It must not be treated as proof of a valve.
- Hough stroke candidates can include borders, letter strokes and symbol edges. Stroke gaps and crossings are **not** converted to pipe connections.
- Overlapping tiles are deduplicated approximately; incomplete stroke merging or duplicate thick-line observations may remain. No independent accuracy metrics are available.
- A low-resolution auto-downscaled render may miss small symbols. The warning is preserved.
- 12-page and 8-Mpx budgets are explicit; pages beyond a selected scope are never silently counted as analysed.
- JSON SHA-256 hashes protect accidental changes; they are not an origin-authentication signature.

## Verification status
The local automated tests, frozen R1 checker, release preflight and manifest results are under `TEST_RESULTS/LOCAL_DEV_R13/`. These tests ran under Linux Python 3.13, not Windows Python 3.12. No original 46-sheet public failure survey, 64 scanned-valve cases, S023 real sheet or 120-labelled benchmark was available in this container; none were retested and no industrial precision/recall was inferred.

## Next implementation work
- More robust morphology and symbol-template calibration against lawful independently labelled industrial scans; tolerate skew, blur and different filled/outlined conventions.
- Calibration of line pixels, text masks, adaptive binarisation, connected components and tile stitching without inventing process connectivity.
- Verified all-page raster processing for large multipage P&ID sets using per-page audit/resume rather than silently scanning only a subset.
- Windows GUI/PySide6 interaction, CPU runtime memory benchmarks, packaging/licensing review and real Worksheet G4-G7 host integration.
