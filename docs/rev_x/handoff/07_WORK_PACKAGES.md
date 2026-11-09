# Implementation work packages - Claude execution order

All WPs are approved **scope**, not implemented features in this handoff. Keep development states independent of owner-approved decisions. Prefix `WPU-` avoids collision with original approved `WP-000..WP-011`; map original statuses instead of assuming they are finished.

Complete all slices that do not require external permissions. After each slice: test, integrate into existing `engineering/pipeline.py`, persist source-linked proposals, update GUI/export if relevant, record errors and verify frozen R1.

## 1. WPU-00 - Baseline and frozen contract assurance
**Owner decisions:** Q1,Q8,Q17,Q29,Q41,Q47,Q50,Q98,Q100.
**Likely integration files:** `api.py; worker.py; tests; frozen contracts`.
**Delivery:** No baseline overwrite; compare SHA; run original tests and R1 checker; copy host only.
**Minimum release evidence:** SHA + baseline commands recorded; checker unchanged; source/remote reconciled.
**Test matrix:** at least 5 positive and 5 negative synthetic algorithm cases where meaningful, plus ambiguous/rotated/raster/cancel/size and real-example diagnostic cases; record actual tests and untested gates.

## 2. WPU-01 - Stage telemetry and zero-extraction health
**Owner decisions:** Q5,Q10,Q21,Q27,Q55,Q78,Q95,Q96.
**Likely integration files:** `engineering/pipeline.py; standalone_read.py; findings.py; project.py`.
**Delivery:** Persist stage states/cap/retry/zero-extraction diagnostics in new tables; report to GUI/export.
**Minimum release evidence:** S025-type zero-word nonempty drawing cannot pass as complete; forced OCR failure code tested.
**Test matrix:** at least 5 positive and 5 negative synthetic algorithm cases where meaningful, plus ambiguous/rotated/raster/cancel/size and real-example diagnostic cases; record actual tests and untested gates.

## 3. WPU-02 - Page and region classification
**Owner decisions:** Q2,Q3,Q21,Q53,Q57,Q59,Q60.
**Likely integration files:** `formats/pdf_source.py; engineering/page_regions.py; sheet_fields.py`.
**Delivery:** Separate native-text/vector-outlined/raster/mixed; locate drawing/title/notes/tables/legends.
**Minimum release evidence:** Rotated/CropBox/outlined-text/legends classified, coordinates round trip.
**Test matrix:** at least 5 positive and 5 negative synthetic algorithm cases where meaningful, plus ambiguous/rotated/raster/cancel/size and real-example diagnostic cases; record actual tests and untested gates.

## 4. WPU-03 - Adaptive vector + raster OCR
**Owner decisions:** Q5,Q22,Q53,Q56,Q57,Q58,Q91,Q94.
**Likely integration files:** `formats/ocr_source.py; engineering/standalone_read.py`.
**Delivery:** Selective OCR on text-poor vector and raster; region-based re-read, health trace and alternatives.
**Minimum release evidence:** Synthetic stacked/rotated/tiny outlines recovered under bounded CPU; missing engine fallback.
**Test matrix:** at least 5 positive and 5 negative synthetic algorithm cases where meaningful, plus ambiguous/rotated/raster/cancel/size and real-example diagnostic cases; record actual tests and untested gates.

## 5. WPU-04 - Engineering text, metadata and tables
**Owner decisions:** Q3,Q22,Q54,Q58,Q59,Q60,Q68,Q83.
**Likely integration files:** `engineering/sheet_fields.py; tag_profiles.py; text_links.py; NEW table_parse.py`.
**Delivery:** Parse title/revision/holds/notes/station data, line specs, units with cell evidence.
**Minimum release evidence:** No row crossing, no false design/setpoint substitution, collision/duplicate cases tested.
**Test matrix:** at least 5 positive and 5 negative synthetic algorithm cases where meaningful, plus ambiguous/rotated/raster/cancel/size and real-example diagnostic cases; record actual tests and untested gates.

## 6. WPU-05 - Original-geometry symbols and valve/actuator classification
**Owner decisions:** Q6,Q13,Q19,Q23,Q61,Q62,Q63,Q64,Q65.
**Likely integration files:** `engineering/symbols.py; symbol_catalog.py; examples.py; example_matching.py`.
**Delivery:** Original legal templates filled/curved/small rotated symbols, multi-class alternatives.
**Minimum release evidence:** Synthetic positive/negative per valve/equipment class; class scores reported; no copyright copied.
**Test matrix:** at least 5 positive and 5 negative synthetic algorithm cases where meaningful, plus ambiguous/rotated/raster/cancel/size and real-example diagnostic cases; record actual tests and untested gates.

## 7. WPU-06 - Raster detector and dense tiled symbols
**Owner decisions:** Q5,Q13,Q23,Q57,Q61,Q62,Q63,Q88,Q91.
**Likely integration files:** `engineering/raster_outlines.py; raster_geometry.py; standalone_read.py`.
**Delivery:** Raster and CAD-outline symbol matching sharing same taxonomy and tile coords.
**Minimum release evidence:** Scans yield symbol candidates with source coords; bounded memory; no all-zero false complete.
**Test matrix:** at least 5 positive and 5 negative synthetic algorithm cases where meaningful, plus ambiguous/rotated/raster/cancel/size and real-example diagnostic cases; record actual tests and untested gates.

## 8. WPU-07 - Vector linework and capacity-aware geometry tiling
**Owner decisions:** Q4,Q14,Q24,Q66,Q67,Q69,Q91.
**Likely integration files:** `engineering/linework.py; topology.py; drawing_graph.py`.
**Delivery:** Preserve arcs, dots, hops, polylines; tile above 4000 strokes rather than text-only.
**Minimum release evidence:** Dense synthetic fixture produces PARTIAL only if cap truly hit; no unreported dropped segments.
**Test matrix:** at least 5 positive and 5 negative synthetic algorithm cases where meaningful, plus ambiguous/rotated/raster/cancel/size and real-example diagnostic cases; record actual tests and untested gates.

## 9. WPU-08 - Raster network, junctions and direction
**Owner decisions:** Q4,Q14,Q24,Q66,Q67,Q69,Q70.
**Likely integration files:** `engineering/raster_network.py; raster_centrelines.py; connectivity.py`.
**Delivery:** Endpoint/port tracing, dots vs crossings, arrow recognition, alternatives.
**Minimum release evidence:** T vs crossing test matrix, UNKNOWN direction, no false valve traversal.
**Test matrix:** at least 5 positive and 5 negative synthetic algorithm cases where meaningful, plus ambiguous/rotated/raster/cancel/size and real-example diagnostic cases; record actual tests and untested gates.

## 10. WPU-09 - Engineering port/asset graph v2
**Owner decisions:** Q4,Q12,Q14,Q25,Q45,Q69,Q78,Q79,Q80.
**Likely integration files:** `engineering/connectivity.py; drawing_graph.py; graph_export.py; migrations.py`.
**Delivery:** Typed ports, occurrence vs asset identity, typed edges, source evidence.
**Minimum release evidence:** Connectivity validity schema, no duplicate merge on tag alone; stable hashes across reruns.
**Test matrix:** at least 5 positive and 5 negative synthetic algorithm cases where meaningful, plus ambiguous/rotated/raster/cancel/size and real-example diagnostic cases; record actual tests and untested gates.

## 11. WPU-10 - Instrument loops, controls, protection proposals
**Owner decisions:** Q3,Q22,Q24,Q63,Q71,Q72,Q73,Q74,Q75.
**Likely integration files:** `engineering/checks.py; signal_links.py; signal_paths.py`.
**Delivery:** Drawn signal relations, PLC/DCS/SIS, interlock mentions, relief/ESD devices.
**Minimum release evidence:** Tests block SIL/IPL credit and unshown PLC logic; test loop with disconnected controller.
**Test matrix:** at least 5 positive and 5 negative synthetic algorithm cases where meaningful, plus ambiguous/rotated/raster/cancel/size and real-example diagnostic cases; record actual tests and untested gates.

## 12. WPU-11 - Crosssheet and revision reconciliation
**Owner decisions:** Q15,Q26,Q38,Q70,Q76,Q77,Q79.
**Likely integration files:** `engineering/project_links.py; revisions.py; project.py`.
**Delivery:** Offsheet match alternatives and source/model change diff, revision immutability.
**Minimum release evidence:** Identical tag alone not merged; two-source offsheet evidence; stale review flagged.
**Test matrix:** at least 5 positive and 5 negative synthetic algorithm cases where meaningful, plus ambiguous/rotated/raster/cancel/size and real-example diagnostic cases; record actual tests and untested gates.

## 13. WPU-12 - Additive SQLite v13+ and review workflows
**Owner decisions:** Q7,Q12,Q16,Q25,Q28,Q44,Q78,Q80,Q87.
**Likely integration files:** `engineering/migrations.py; project.py; findings.py`.
**Delivery:** New tables and indices with review audit and backup/restore.
**Minimum release evidence:** v12 unaffected; migration interrupted/restore tested; append-only no tampering.
**Test matrix:** at least 5 positive and 5 negative synthetic algorithm cases where meaningful, plus ambiguous/rotated/raster/cancel/size and real-example diagnostic cases; record actual tests and untested gates.

## 14. WPU-13 - Source-linked PySide6 UI and registers
**Owner decisions:** Q31,Q32,Q33,Q34,Q36,Q46,Q86,Q87,Q89.
**Likely integration files:** `ui/viewer.py; main_window.py; tabs.py; graphview.py`.
**Delivery:** Linked overlay, register, graph, review, warning page, document explorer.
**Minimum release evidence:** Headless/offscreen UI tests, 175% DPI manual gate NOT_RUN until actually tested.
**Test matrix:** at least 5 positive and 5 negative synthetic algorithm cases where meaningful, plus ambiguous/rotated/raster/cancel/size and real-example diagnostic cases; record actual tests and untested gates.

## 15. WPU-14 - AI export schema and public SDK
**Owner decisions:** Q8,Q29,Q40,Q47,Q81,Q82,Q83,Q84,Q85,Q90.
**Likely integration files:** `engineering/reports.py; drawing_export.py; NEW intelligence.py`.
**Delivery:** Schema-valid typed graph/reg, source evidence/narrative, prompt and quality.
**Minimum release evidence:** Synthetic full export schema-valid, no invented fields, all claims source-linked.
**Test matrix:** at least 5 positive and 5 negative synthetic algorithm cases where meaningful, plus ambiguous/rotated/raster/cancel/size and real-example diagnostic cases; record actual tests and untested gates.

## 16. WPU-15 - DEXPI 2.0.1 validated adapter and format status
**Owner decisions:** Q2,Q8,Q11,Q40,Q43,Q53,Q99.
**Likely integration files:** `engineering/dexpi.py; formats/dxf_source.py; NEW dexpi_xml.py`.
**Delivery:** Real XSD-validated DEXPI output or honest refusal; DXF separate tested mode.
**Minimum release evidence:** DEXPI XSD check on supported sample; unsupported mapping signaled, not claimed done.
**Test matrix:** at least 5 positive and 5 negative synthetic algorithm cases where meaningful, plus ambiguous/rotated/raster/cancel/size and real-example diagnostic cases; record actual tests and untested gates.

## 17. WPU-16 - Quality benchmarks, annotation and calibration
**Owner decisions:** Q10,Q20,Q30,Q48,Q55,Q95,Q96,Q97,Q98.
**Likely integration files:** `tools/score_benchmark.py; benchmark_registry.py; NEW gold tools`.
**Delivery:** Independent annotation protocol, stratified metrics and silent-miss reports.
**Minimum release evidence:** 30 untouched final synthetic, real gold only if permission; denominators and CI recorded.
**Test matrix:** at least 5 positive and 5 negative synthetic algorithm cases where meaningful, plus ambiguous/rotated/raster/cancel/size and real-example diagnostic cases; record actual tests and untested gates.

## 18. WPU-17 - Windows security, CPU and batch recovery
**Owner decisions:** Q9,Q18,Q30,Q37,Q88,Q91,Q92,Q93,Q94.
**Likely integration files:** `engineering/isolation.py; batch.py; worker.py; packaging`.
**Delivery:** CPU mode quick/standard/deep, no network; bounded worker/process; safe resume.
**Minimum release evidence:** host limits unchanged; cancel/timeouts tested; hostile PDF fuzz NOT_RUN until run.
**Test matrix:** at least 5 positive and 5 negative synthetic algorithm cases where meaningful, plus ambiguous/rotated/raster/cancel/size and real-example diagnostic cases; record actual tests and untested gates.

## 19. WPU-18 - Systemwide regression, handoff and installer
**Owner decisions:** Q30,Q40,Q49,Q50,Q96,Q98,Q99,Q100.
**Likely integration files:** `packaging; windows; release_assurance.py; docs; tests`.
**Delivery:** Complete source, traceability, license/SBOM, installer candidate, rollback and owner review.
**Minimum release evidence:** R1 + all pytest + release preflight + Windows tests evidence, each gate explicit.
**Test matrix:** at least 5 positive and 5 negative synthetic algorithm cases where meaningful, plus ambiguous/rotated/raster/cancel/size and real-example diagnostic cases; record actual tests and untested gates.

## 20. WPU-19 - Final owner release review and residual blockers
**Owner decisions:** Q16,Q20,Q50,Q75,Q98,Q99,Q100.
**Likely integration files:** `docs; TEST_RESULTS; audit; review pack`.
**Delivery:** Owner receives a finished candidate with honest PASS/FAIL/NOT_RUN/BLOCKED.
**Minimum release evidence:** No claim production approval without owner explicit release and independent engineering gate.
**Test matrix:** at least 5 positive and 5 negative synthetic algorithm cases where meaningful, plus ambiguous/rotated/raster/cancel/size and real-example diagnostic cases; record actual tests and untested gates.

## Dependencies and gates

WPU-00 before any changes. WPU-01 health before WPU-03. WPU-02 precedes table/region OCR. WPU-05/06 and WPU-07/08 precede port graph WPU-09; WPU-04/09 precede loops and cross-sheet; WPU-12 migrations must be versioned before new persistence. WPU-14 exports must not precede source evidence validation. WPU-15 independent DEXPI schema validation. WPU-16 independent annotation before any accuracy claim. WPU-18/19 final acceptance must truthfully declare missing 3rd-party gates.

Separate gates: SOFTWARE FUNCTIONAL; EXTRACTION ACCURACY; R1 WORKSHEET COPY INTEGRATION; INDEPENDENT ENGINEERING AND REAL WINDOWS ACCEPTANCE. Never infer one from another.
