# Detailed algorithms, default processing policies and failure recovery

All thresholds below are **engineering development defaults/proposals**, not empirically validated universal truth. Tune on synthetic development + labelled training/development splits, freeze prior to held-out testing, store as versioned configuration. Existing baseline limits and constants take precedence unless an explicitly measured improvement justifies an additive change. Keep an option for `UNKNOWN` at every stage.

## A. Document classification / coordinate identity

For each PDF page, collect native text chars and glyph matrices, vector paths/curves/rectangles, embedded images, page CropBox/MediaBox, rotation, rendering resolution and pixel budget. Sample raster region density and estimate whether important content uses outlined vector lettering. Classify per PAGE and per REGION: `NATIVE_TEXT`, `VECTOR_OUTLINED_TEXT`, `RASTER_SCAN`, `HYBRID`, `LOW_CONTENT`, `UNKNOWN`. A 40-word title block on a dense vector engineering body means **HYBRID with outlined-text suspicion**, not text-complete. Rotation and crop transform must preserve normalized bbox on the rotated display page; verify round-trip errors on 0/90/180/270 and CropBox offsets. Record scale, skew, page size, DPI and clipping.

Separate graph area, title block, revision schedule, list of notes/holds, legend, material/equipment tables, border/grid and graphical details. Apply spatial layout segmentation using vector density, text blocks, rules and Hough-like horizontal/vertical structure, then allow human region overrides. Region classifier must avoid interpreting line-table rules or revision clouds as pipes; retain raw polygons even when filtered from engineering graph.

## B. OCR health and adaptive re-read

Current `standalone_read.py` already has sparse vector fallback, 1200px tiles / 150px overlap, DPI <=240 within 12MP budget, stacked bubble reconciliation and per-bubble crop reread. Preserve these, first add **stage diagnostics** with `ocr_requested`, `engine_available`, `ocr_attempted`, `cropping`, `tiles_attempted`, `tiles_successful`, `exception`, `word_count_native`, `word_count_ocr`, `recognized_tags`, `coverage`, `retry_count`, `truncated`. Investigate S025 explicitly: distinguish OCR untriggered, model not available, raster image too big, orientation, invalid input, worker killed, content discarded at export, and true unreadable. Compare internal OCR words with exported `ocr.words` and `readings`.

A CPU-efficient iterative OCR policy:
1. Extract native PDF text first with font, orientation and bboxes; preserve char-level evidence. If body text density is sufficient, avoid redundant full-page OCR while still scrutinizing unreliable regions.
2. Rasterize only chosen regions or tiled slices at sensible DPI, preserving page transforms. Start with 150-240 dpi depending on text size; raise effective DPI only for text-poor/low-confidence small symbol areas subject to 12MP/page host budget (standalone configurable independently). Do NOT render whole A0 sheets into unbounded images.
3. Run current RapidOCR as default; optional local Tesseract fallback if installed and user-configured. Benchmark future unified RapidOCR model upgrades in isolated environment, not as a mandatory migration; record ONNX/model hashes and licences.
4. Use orientation candidates 0/90/180/270 on text-region crops if orientation is uncertain; deskew modestly only with reliable page/rule orientation. Keep transform lineage.
5. For tiny glyphs compare grayscale, local contrast enhancement and light thresholding; retain original as another candidate. Do not rely on aggressive denoise that erases `1`, `I`, dots, minus signs or decimal points.
6. For outlined text use vector-to-raster crops around short repeated curve groups; OCR at multiple scales with words merged along common baselines; if one engine fails return competing candidates and targeted human inspection.
7. For instrument bubbles crop within circular/rectangular region, recognize multi-line letters and numeric loop, retain letter/number split evidence; e.g. `PIT`+`100` may form PIT-100, but a leading `0` or adjacent overlap must not be silently discarded without visual evidence.
8. Deduplicate tile overlaps by source geometry and normalized text, not by text string alone (two physical tags may have same letters); retain all raw candidate observations with parent tile ids.
9. Score tag parse against project grammar and known locale; low OCR confidence must not be upgraded into certainty by plausible tag syntax. Preserve raw `0/O`, `1/I/l`, `5/S`, `8/B`, slashes, degree symbols and decimal signs.
10. If OCR returns zero while page has ink/geometry, `INCOMPLETE` + retry alternative engine/orientation/crops where budget permits, otherwise explicit diagnostic. If no licensed OCR engine is installed, report `OCR_ENGINE_MISSING` and keep native/geometry results.

Default policy presets (not promised performance): `Quick` native and targeted crops, no whole-page repeated rotation; `Standard` existing tiling + per-symbol crop + selective local alternatives; `Deep` additional outlined glyph candidates, multi-pass rotation/contrast/size, stronger postprocessing and uncertain graph re-analysis. All preserve raw evidence and bounded resources. Report page/region recall unknown until gold comparison.

## C. Symbol detector and symbol library

Represent a symbol as original drawn/vector/raster geometry and a typed set of port templates and optional tag/actuator context. Build original-geometry symbol exemplars using geometric primitive composition (do not copy proprietary vendor tables), category families including:
- valves: ball, gate, globe, butterfly, check, needle, plug, diaphragm, control, isolation, emergency shutdown, relief, rupture disc; actuation by manual handwheel, motor, pneumatic, hydraulic, spring, solenoid and relevant feedback; valve class and actuation must have independent evidence;
- equipment: pressure vessel, separator, tank, filter, strainer, exchanger, heater, compressor, pump, blower, mixer, column, reactor, cooler, skid/package, building envelope;
- instruments: pressure, temperature, level, flow, analytical, vibration, position, indicator, switch, transmitter, recorder/controller, system boundary, I/O, PLC/DCS/SIS, local/remote panel; tag letters and bubble position separated;
- piping: reducer, flange, blind, spectacle blind, check/relief, process break, line arrow, drainage/vent/utility/tie-in and reference pennants;
- non-process: table, revision cloud, leader, dimension, drawing grid, border, header, legend.

Use a hierarchy: `graphical_family`, `shape_variant`, `engineering_class`, `actuation`, `function`, `confidence_status`. Match candidate regions via contours, primitive descriptors, aspect ratio, topology, flood fill and model-catalogue templates, across rotations and bounded scale variations. Sample symbol pattern widths from recognized line stroke size. Use a spatial index to avoid pairwise matching of every object with every other. A detector may propose a bounding box and class, but engineering meaning is cross-checked against adjacent line ports and text. Keep special distinction of instrument circles vs pipe circles; distinguish skid rectangle vs drawn vessel.

For dense or raster sheets use overlapping tiles (defaults align with OCR 1200px tiles/150px overlap where appropriate); dedupe by shape IoU + coordinates but keep conflicting class alternatives. Context-specific crops around line interruptions may recover valves that do not appear in raw vector shape due to filled polygons. Deterministic template matching remains valid baseline. An optional ONNX classifier is permitted only with a licensed model, documented data origin, exact hashes, CPU performance and independent benchmark. Never require end-user model retraining; teach-by-example remains declarative project-local classification.

## D. Vector/raster line tracing

1. Normalize vector segments and curves; preserve path IDs and shapes before polyline approximation. Adaptive flatten Beziers/arcs to segments where approximation error < min(0.2 * median stroke width, 0.25% of local symbol size); not a global fixed-pixel threshold; store original geometry. Compare proposed arc transformations to rendered sample.
2. Identify piping-vs-text/style and large geometry. Classify based on line width, pattern, right-angle topology, nearby annotation, port contact, title region and context. Text glyph curves/legend table grid must not be assimilated into process pipes.
3. For raster: select grayscale/colour channels with minimal information loss; line enhancement and skeletonization with morphological operations sized from local stroke width; detect junction points and candidate gaps. Keep alternate paths if anti-aliasing/scan defects obscure junction.
4. Segment into edges at endpoints, dots, symbols, suspected T intersections and bridge boundaries. Use a spatial index and tolerance scaled by page stroke width. Start with a conservative endpoint snap tolerance ~0.25-0.5 local median stroke width (subject to testing), and do not snap if it would merge visually separated lines or bridge a valve graphic.
5. Determine crossings: explicit dot/contact supports a possible join; right-angle crossing without dot and explicit bridge/hop favours separated network; vector collinear overlaps may be duplicate path renderings; ambiguous raster/poor quality remain `UNKNOWN_CROSSING`. Publish candidate alternatives, not a single false plant connection.
6. Allocate typed ports to symbol boundaries, rather than connect lines to symbol centroids. Valve main ports vs actuator ports and instrument signal ports are separate. Determine nearest edge-to-port matches using angle, distance, styles, port multiplicity and tag associations; hard constraints prohibit process pipe linking into instrument signal ports unless symbol definitions permit it.
7. Arrowheads/triangle glyphs may indicate process flow, valve position or instrumentation direction; classify using shaft alignment and context. Record direction only when arrow semantics and linked line are supported, else `UNKNOWN`. Never assume flow left-to-right.
8. Assemble same-sheet `DRAWN_CONNECTS` path hypotheses with traceability and graph type. Offsheet connectors are unresolved boundaries until a second sheet provides compatible reference and human review.
9. For an isolation query, distinguish explicit valve occurrence on path and valve-open/closed status (if known), don't infer closure capability from graphic geometry alone. `potential_isolation_boundaries` is advisory; no automatic accepted isolation claim.
10. For large drawings, tile geometry with overlap greater than maximum expected symbol width and dedupe/stitch at world coordinates. Record cap hit and unprocessed regions. If original 4000-stroke limit is reached, tile rather than 'text-only SUCCESS'.

## E. Engineering syntax, tables and units

Classify raw text into tag/line no/size/spec/service/unit/rating/setpoint/notes/drawing reference/date/hold with per-project JSON grammar profiles and bounded regex. Never greedily convert `NPS 20` as a valve tag or `LINE 200-2` as a drawing number. Support `NPS 30 x NPS 20`, fraction sizes, inches/millimetres, ANSI class/PN, kPa(g) vs kPa(a), bara/barg, psi(g), Fahrenheit/Celsius, DPs, W/BTU, comments such as `TBD`, `HOLD`, `N/O`, `N/C`, `CSO`, `CSC` (only after project legend). Normalized numeric value is secondary to verbatim evidence and exact unit; do not conflate pressure design rating with operating setpoint.

For tables, detect region and rule grid, recover cell polygons, multiline cell text and row/column labels. Bind `STATION DATA` values to their correct row/column, including `design pressure`, `MOP`, `temperature`, `line description`; if row alignment uncertain return `CONFLICTING` field candidates, not a guessed number. Parse revision history separately from issue status.

Tag association: cost function over spatial proximity, direction from label leader, symbol class compatibility, angle, enclosure, overlaps, grammar, and competing nearby candidates; solve constrained 1-to-1 or 1-to-many associations where appropriate. Never attach a tag merely because it has the lowest Euclidean distance on a dense sheet. Keep reviewer correction and resulting dependency update trace.

## F. Control loops, systems and functions

One loop identity may connect several occurrences only by matching appropriate instrument tags AND drawn signal links plus compatible variables and boundaries. Distinguish `MEASURES`, `CONTROLS`, `ACTUATES`, `POSITION_FEEDBACK`, `INDICATES`, `COMMANDS` and `ALARM_REFERENCE`. Never infer PLC logic or SIL performance from abbreviation alone; extract 'shown' evidence. Crosssheet signals/off-page references require both sides, compatible types and retained alternative routes.

## G. Cross-sheet and revision reconciliation

Two occurrences merge into a `proposed_asset_identity` only with evidence beyond shared tag (source revision, site area, document references, port connections, equipment context). For conflicting tags document `CONFLICTING`; no silent merge. Different revisions are separate immutable evidence sources. Compare `source_diff` and `interpretation_diff`: newly detected object in unchanged PDF is not a physical design change. When model/template updates cause broader findings, keep old interpretations reproducible by versioned model/config hashes.

## H. Efficient evaluation and failure containment

Each module gets synthetic positives, negatives, near misses, ambiguous/unknowns, rotated/cropped/dense/raster/vector, malicious/very large, and concurrency/cancel tests. Measure CPU wall time and peak RSS on real Windows. Preserve existing per-worker Job Object caps for R1. Work units keyed by page/region and cached across retries. Every stage emits heartbeat/progress/cancel. Never let one failed OCR tile cancel whole drawing silently; preserve a `PARTIAL` snapshot with detailed unresolved items. Test deterministic output excluding approved event-time fields.

## I. Software release requirements

No new library without an SPDX+model weight+transitive licence audit, version pin, SHA and offline packaging test. Replace obsolete dependencies in isolated branch only after benchmark/evidence, never speculate a speed improvement. DEXPI output must validate against 2.0.1 XSD. Separate a usable extraction product (functional gates) from engineering accuracy, actual Worksheet COPY and independent sign-off gates, marked PASS/FAIL/NOT_RUN/BLOCKED individually.
