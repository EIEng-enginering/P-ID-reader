# Architecture, integration and behavior specification

## Authoritative system layers

Implement a new **standalone-intelligence** namespace instead of replacing the v1 host module.

1. `SourceDocument` immutable content-addressed PDF/image/format payload, file SHA, project/drawing/revision key, page-to-source transforms, scan policy, licence and any authorisation constraints. Never identify physical equipment from document filename.
2. `Observations` native glyphs/text/curves, OCR words/polygons, raster strokes, connected components, symbol crops, arrows, dots, areas, page tables. Every observation has source revision, page, polygon, coordinate frame, producer/version, model/config digest, score provenance. Do not erase original evidence.
3. `InterpretationCandidates` tag grammar parse, symbol classes, line spec parse, equipment identity hypothesis, table-cell role and proposed relation types with uncertainty. Alternatives belong to a named hypothesis group; unknown is a valid result.
4. `EngineeringGraph` typed occurrence nodes, asset identity hypotheses, ports, edges and edge evidence. `DRAWN_CONNECTS` and `PROPOSED_MATCH` must be distinguishable. Processes/signal/control/annotation edges belong to separate edge-type namespaces; no implicit 'touching means pipe' rule.
5. `ReviewDecisions` independent human decisions with named reviewer, timestamp, source hash, model generation, old/new value, append-only audit. Review of a drawing interpretation is never confirmation of constructed plant.
6. `PublicationSnapshots` consistent, versioned graph+registers+metadata+quality+evidence with SHA for downstream AI/export. No mutation of approved past exports; new versioned snapshot after edits.

## Pure engine modules and adapters

`formats/*` source adapters -> `read/` page class/region -> `recognition/` text + symbols + line geometry -> `interpret/` tags + attributes + graph candidates -> `engineering/` persistence/review -> `export/` graph/registers/AI narrative; use actual existing code modules and cross-wiring, not a new unrelated namespace unless it reduces risk. Keep core Qt-free and import side-effect free. UI directly invokes public standalone SDK with only typed/JSON interfaces. R1 adapter remains a separate projection obeying schema 1 caps and immutability.

## Stage result contract

Each pipeline stage returns structured `StageOutcome {stage_id, status: SUCCESS|PARTIAL|SKIPPED|FAILED|TIMEOUT|CANCELLED|NOT_RUN, input_source_sha256, input_model_sha256, config_sha256, stage_version, runtime_ms, tile_count, candidates, cap_truncations, error_class, error_summary, pages_processed, regions_processed, observed_content_evidence_count, output_sha256, diagnostics}`. Status records go to standalone DB and local logs with redaction. Failure to execute OCR differs from successfully executed OCR finding no words. No StageOutcome can say SUCCESS if it truncated silently; caller must propagate `PARTIAL` to page and export.

Stage report must include `coverage` vectors with domain unknown/attempted/reviewable versus verified. Example: `{page:1, region:'MAIN_PROCESS', texts_attempted:true, words:0, text_status:'UNREADABLE_OR_FAILED', symbol_classes_attempted:['VALVE'], graph_join_status:'UNRESOLVED', primary_blocker:'OCR_NO_WORDS'}`. Never convert a coverage percentage into accuracy without labelled gold.

## Caching and versioning

Key immutable cache records on `(source_sha256, page, crop_transform, extraction_stage_version, config_sha256, model_weight_sha256, relevant_prior_model_output_sha256)`. If user corrections change source interpretation, do not re-run raw OCR unless needed; recalculate only affected semantic graph neighborhoods. Invalidate downstream dependencies on model profile/legend revision, not raw raster. Keep per-revision source identities immutable and create a new engineering interpretation snapshot. Deterministic sorting, stable IDs, canonical numeric representation and explicit no-float-in-source units. Use bounded spatial indexing and per-region tiling; do not load all pages rasterized at once.

## SQLite migration plan

- Existing DB version 12 is immutable; add v13+ incremental tables such as `intelligence_run`, `page_region`, `evidence_item`, `text_candidate`, `symbol_candidate`, `engineering_occurrence`, `engineering_asset_hypothesis`, `occurrence_port`, `engineering_relationship`, `relationship_evidence`, `conflict_group`, `reading_decision`, `publication_snapshot`, `stage_diagnostic`.
- Required indices: `(source_revision,page)`, `(drawing_id,revision)`, `(entity_type,tag_normalized)`, `(relationship_from,relationship_to,type)`, `(status,review_state)`, FTS for verbatim labels. Foreign-key constraints, row caps and atomic transactions on stage completion.
- Migrations need backup-before-write, interrupted-transaction recovery, idempotent rerun, original v12 reader still able to read legacy tables; downgrade is by verified backup restore, not dropping additive tables unsafely.
- Keep underlying evidence and user review append-only; derived materialized views may be recreated with versioned provenance.

## Design for source-to-export traceability

Every nontrivial exported assertion links to >=1 evidence id with drawing SHA, drawing-revision identifier, page index (0-based internally; UI display 1-based), normalized top-left bbox or polygon, original raw text (if available), observation type, extraction engine/model version, config digest and classification state. Cross-sheet links require independent matching observations on both documents. The exact per-page transform and source fingerprint travel with each image crop; never leave coordinates ambiguous after rotation.

## Quality and uncertainty

Separate: algorithm raw score (un-calibrated); independently calibrated confidence (only with calibration dataset id); human review state; engineering verification state; coverage; and quality gate. Do not convert a heuristic into a % probability. Critical missing information and incompatible hypotheses must be prominently visible and exported, never dropped because of a `MAX_ROWS` UI pagination cap.

## Review and interactions

All exported entities can be clicked to zoom to exact source evidence. User corrections propose dependent updates for review with a diff; no silent rebinding of other objects. Review actions: accept-as-reading/reject/ignore/reclassify/edit/link/unlink/resolve ambiguity; on reanalysis show stale-review decisions and ask for reaffirmation where source/model changed. Support keyboard and 175% DPI, large sheets, light/dark themes, pagination, virtualized tables and graph neighborhood expansion.

## Export and downstream AI package

`engineering_intelligence_v1.json`, `drawing_graph_v2.json`, `registers/` CSV+XLSX, `source_regions.json`, `evidence_manifest.json`, `quality_report.json`, `drawing_summary.md`, optional rendered bounded crops and prompt `16_AI_CONSUMER_PROMPT.md`. Export allowed only after user picks folder and confirms; protect against CSV/XLSX formulas, HTML/XSS, path traversal, external URLs and oversized content. Chunk by drawing/system for AI context while keeping a stable manifest and crossrefs; use no automatic external uploads. `schemas/engineering_intelligence_v1.schema.json` is an initial handoff design to be hardened by Claude and versioned; does not replace Worksheet R1.

## DEXPI 2.0.1

Map only supported reviewed graph types to a conformant DEXPI XML `Model` document, following authoritative DEXPI 2.0.1 XSD and example. Test valid required IDs, classes, nozzles/ports, piping connections and preservation of unknowns in an extension or accompanying manifest. If mapping is incomplete or XSD validation fails, refuse to label the output DEXPI conformant. Do not simply rename graph JSON properties to DEXPI terms. Include inverse import round-trip test where supported. Keep exporter disabled with specific status until true validation passes.

## Concurrency/security/resource invariants

No network at runtime; child process/job object (Windows); cancellation injected into every tile/page stage; worker memory and output caps. No undocumented shell execution, no arbitrary embedded PDF links/scripts, reject or sandbox malformed input, per-page budgets, no confidential data in exception traces. Host R1 caps cannot be increased by standalone defaults. Use configured local non-sync model caches; user-controlled export is the sole path for sharing an AI-ready package.
