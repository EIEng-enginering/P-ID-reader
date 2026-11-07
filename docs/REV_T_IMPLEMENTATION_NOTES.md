# Rev T — executable outlined raster-glyph and diagonal stroke increment

## Actual source baseline

Rev T extends the cumulative Rev S reader, itself based on the supplied WIN-R01 source and prior Rev Q development. **It has not been reconciled to a newer live Windows checkout**; do not overwrite such a checkout without a staged source diff and tests. This package includes executable code, not only a proposed design. All owner-approved decisions remain in effect. The complete frozen Master Research/Claude Build Specification remains under `contracts/` unchanged.

## Changes implemented and tested

1. **Outlined raster bow-tie geometry:** `engineering/raster_outlines.py` proposes horizontal and vertical glyphs only if there are two separate near-axis-aligned end bases with four supported diagonal edges converging at the centre. A plain X crossing fails; a crossed rectangle fails due to its horizontal top/bottom edges. A nearby filled glyph is not duplicated as an outline.
2. **Central ring observation:** a small outlined central ring is separately noted as `CENTRAL_RING_OBSERVED`, **not** a globe/control valve functional interpretation. The glyph remains `PROPOSED_UNVERIFIED`. The detector does not claim that absence of recognition implies absence of a valve.
3. **Long diagonal raster strokes:** the OpenCV tiled Hough stage now records sparse long diagonal ink in addition to orthogonal strokes. Every candidate remains `RASTER_LINEWORK_UNKNOWN`: no pipe service, connection, piping trace or flow direction is inferred.
4. **Standalone schema v2:** `contracts/standalone_raster_geometry_v2.schema.json` adds `outline_valve_candidates` and explicit incomplete-coverage warnings when the outline detector exceeds its base/outcome budget. The original standalone raster schema v1 remains untouched, and the validator accepts historic v1 records. The **frozen Worksheet R1 schema and worker remain untouched**.
5. **Source-coordinate improvement:** candidate bounding boxes are normalized correctly after CropBox and PDF rotation; both orientations are covered by tests. Record IDs include the source hash, page, shape/box and algorithm version.
6. **Database and review:** schema v10 already supported source-bound raster candidates, so the existing append-only candidate/review tables store outlined candidates as an additive kind **without a destructive migration**. Named human decisions, audit history and the host extraction remain separate.
7. **CLI, pipeline and GUI source:** `raster-preview`, `analyze-raster`, `raster-valves`, review functions, engineering findings and draft PySide6 overlays now expose both outlined and filled glyphs. The automatic pipeline records separate counts. Actual Windows GUI interaction was not tested here.
8. **New fixture:** `fixtures/synthetic_raster_outline_valves.pdf` contains a horizontal outline, a vertical outline, a central-ring outline and explicit negatives: X crossings, crossed rectangle, text and long diagonal strokes. Generated entirely for regression; this is not an independently annotated industrial drawing.

## Limitations and safety constraints

- Only two-axis near-horizontal or near-vertical outlined bow-tie patterns are covered. Angled, skewed, partially occluded, line-weight-varying and degraded industrial glyphs need further research and independent benchmarking.
- The central ring is only a graphical observation. Do NOT classify PSV, globe, ESDV, control or manual valve function without source legend/tag evidence and human review.
- Neither outlined glyphs nor detected diagonal strokes are accepted piping connections; the program cannot infer as-built plant state, safety credit, HAZOP or LOPA outcomes.
- On dense pages the outline stage may mark `OUTLINE_DETECTION_SKIPPED_*` rather than imply completeness. Excessive whole-result budgets refuse the analysis. No silent truncation is allowed.
- Normalised result SHA-256 verifies content consistency, not trusted author identity or cryptographic provenance. Independent source re-computation and external review remain appropriate.
- Pretrained industrial vision detector, S023/46-sheet re-run, 120 independently labelled drawings, industrial precision/recall, Windows installer, and actual Worksheet host G4-G7 remain NOT_RUN/BLOCKED/NOT_IMPLEMENTED as appropriate.

## Commands (development checkout, optional raster dependencies installed)

```powershell
py -3.12 -m pip install -e '.[test,raster]'
py -3.12 -m pytest -q
py -3.12 tools/release_preflight.py
py -3.12 -m pid_reader.cli raster-preview fixtures/synthetic_raster_outline_valves.pdf --output-json raster_outlines_v2.json
py -3.12 -m pid_reader.cli import-pdf project.sqlite fixtures/synthetic_raster_outline_valves.pdf --ocr off
# Use the returned extraction ID:
py -3.12 -m pid_reader.cli analyze-raster project.sqlite <extraction_id>
```

Source provenance, standalone schema and acceptance evidence are in `TEST_RESULTS/LOCAL_DEV_R14/`, `docs/REV_T_ACCEPTANCE_MATRIX.md` and `FILE_SHA256.txt`.
