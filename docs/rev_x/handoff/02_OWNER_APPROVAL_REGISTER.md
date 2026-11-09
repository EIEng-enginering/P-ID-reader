# OWNER APPROVAL REGISTER - Q1-Q100

Owner approval Q1-Q50 Option A from original Rev X source, and Q51-Q100 Option A explicitly in this conversation on 9 Nov 2026. Every line is a binding development decision; approval is not evidence of implemented code, tested performance, or plant safety.

Precedence: (1) unmodified frozen Worksheet R1 contract, (2) applicable owner approvals and autonomous charter, (3) original baseline source and contracts, (4) this handoff implementation detail and recorded ADRs. Conflicts must be resolved to preserve higher-priority constraints without silent relaxation. If literally irreconcilable, flag BLOCKED and continue safe independent work.

## Q1-Q40: original Rev X master decisions (verbatim)

- **Q1 A:** Standalone Windows application, reusable GUI-free Python core and independent host adapters. Same engine, multiple application surfaces.
- **Q2 A:** Multi-format architecture: vector/scanned/mixed PDF, images, DXF, DEXPI, and planned/licensed DWG/DGN/intelligent CAD, with format-specific delivery/test status. PDF first for R1 host.
- **Q3 A:** Extract and categorise as much DRAWING-SUPPORTED engineering information as possible: title blocks, equipment, valves, piping, instruments, controls, shutdown references, notes, line specs, relief items, connections and attributes. Preserve verbatim source, do not invent missing values.
- **Q4 A:** Typed, port-based engineering connectivity graph: symbols, equipment nozzles, line branches, line crossings, instrument signals, flow arrows and off-page connectors, with explicit ambiguity.
- **Q5 A:** Hybrid native-document and vector extraction, offline OCR, specialist symbol detection, geometry, engineering rules, optional authorised ML. No reliance on general vision AI as sole authority.
- **Q6 A:** Versioned symbol/engineering/tag catalogues, lawful starter content, project-specific overrides and source licences; standards-aware where rights permit.
- **Q7 A:** Source-linked human correction, explicit uncertainty, accepted-as-reading states, revision impact and append-only review decisions.
- **Q8 A:** Public Python SDK, isolated worker/CLI, JSON schemas, DEXPI where conformant, optional controlled local API; never require downstream clients to read internal SQLite schema.
- **Q9 A:** Fully functional offline, bounded hostile-input parsing, pinned dependencies, no telemetry, optional external services only by permission.
- **Q10 A:** Independent benchmark, measured precision/recall/connectivity and silent misses, supported-class declarations, staged validation.
- **Q11 A:** Usable vertical-slice increments R0.1-R0.9: project shell/PDF, vector extraction, scanned OCR, connectivity, review/export, multi-sheet, DEXPI/DXF, licensed CAD adapters, host rehearsal/validation. Never label aspirational formats implemented.
- **Q12 A:** Five separate layers: immutable source, observations, interpretations, relationships, review decisions. Stable plant entity IDs distinct from R1 deterministic observation/result IDs.
- **Q13 A:** Hybrid text/symbol/tag matching, project-specific profile, recognition alternatives and UNKNOWN class; corrections do not automatically become shared training material.
- **Q14 A:** Strict topology rules for ports, junctions, crossings, signal and process edges, off-page links, and unknown directions, with source evidence.
- **Q15 A:** Plant-wide proposed graph across immutable drawings and revisions; source- and model-change comparison; special stricter R1 host same-run cross-sheet limits.
- **Q16 A:** Visual review with inspect/edit/accept/reject/ignored/stale, provenance and optional independent sample check. No automatic acceptance.
- **Q17 A:** R1-safe versioned adapters with no automatic host record writes, complete source evidence and unit-tested handoffs.
- **Q18 A:** R1 fixed host resource limits; separate configurable standalone processing profiles, secure temporary files and no default online access.
- **Q19 A:** Lawfully redistributable/versioned starter engineering catalogues and mappings, company-specific overrides, training models with documented licences.
- **Q20 A:** Gold benchmark >=120 synthetic or cleared drawings, >=30 untouched final test drawings, separate class/format gates, true real-Windows tests and independent sign-off.
- **Q21 A:** Eight-stage evidence-preserving pipeline: validate, classify, native extraction, OCR, symbol/line, engineering interpretation, uncertainty checks, publication.
- **Q22 A:** Preserve verbatim OCR/native text, rotation/polygons, candidate association and advisory tag parsing; do not infer safety functionality from tag alone.
- **Q23 A:** Hierarchical visual/engineering/functional symbol classes, variants, project profiles and versioned model cards; UNKNOWN when unresolved.
- **Q24 A:** Typed connection endpoints/ports, geometric junction rules, unconfirmed alternatives, line arrows only when explicitly depicted; no unreviewed path as established.
- **Q25 A:** Normalized entities for project, document, revision, page, observations, engineering objects, attributes, ports, connections, evidence, alternatives, review, graph and export snapshots.
- **Q26 A:** Cross-sheet reconciliation using multiple compatible evidence factors with ambiguity and source-revision binding; model-change differences distinguished from drawing changes.
- **Q27 A:** Separate raw scores for OCR, symbol, association, geometry, topology, interpretation; calibration only when independently measured; exact R1 decision terminology.
- **Q28 A:** Versioned offline SQLite, graph queries/indexes/full-text and append-only decision/audit; R1 host uses its own additive tables and audit, not direct standalone schema copy.
- **Q29 A:** R1 worker signatures and exact JSON, deterministic hash/IDs, refusal semantics; separate richer standalone SDK and schema; backwards compatibility tests.
- **Q30 A:** Exhaustive unit, geometry, OCR, adversarial, integration, benchmark, Windows, performance and licence evidence; gates not performed remain NOT_RUN.
- **Q31 A:** Configurable dockable multi-document Qt workspace: Project, Drawings, Data, Graph, Review, Exports; saved layouts and keyboard access.
- **Q32 A:** Responsive tiled/vector-quality drawing viewer with zoom, pan, search, mini-map, source/overlay distinction, reliable crop/rotation coordinate transforms, revision compare.
- **Q33 A:** Virtualised spreadsheet-like equipment, piping, valves, instruments, connections and uncertainty registers, with filters, source jump and audited corrections.
- **Q34 A:** Review queue prioritised by uncertainty/dependencies/critical connections; batch preview with R1 restrictions and recorded second checks.
- **Q35 A:** Versioned system/company/project symbol/tag/engineering catalogues with licence records; never silently alter accepted historical readings on library updates.
- **Q36 A:** Source-linked graph workspace, typed paths, selected-neighbourhood expansion, ambiguity visibility and accepted-only vs include-proposals modes.
- **Q37 A:** Bounded batch scheduler, source inventory, safe retries, per-document atomicity, job manifests and recoverable standalone project state; host remains one-revision-per-run.
- **Q38 A:** Full facility/area/drawing explorer, multi-revision/source-vs-model diff, FTS and filters, downstream impact reports without silent source acceptance.
- **Q39 A:** Purpose-specific adapters for HAZOP, LOPA, QRA/PSS, line/equipment indexes, other engineering clients; no automatic engineering acceptance or private DB writes.
- **Q40 A:** Professional report/JSON/graph/DEXPI export where valid, offline Windows delivery, SBOM, all-theme/scale GUI checks and independent software/extraction/engineering/integration gates.

## Q41-Q50: original Rev X approved Stage 5 summary

- **Q41 A:** Single modular repository and reproducible source/releases
- **Q42 A:** Typed, testable hybrid extraction pipeline
- **Q43 A:** PDF first, then individually validated format adapters
- **Q44 A:** SQLite evidence history and dual identity model
- **Q45 A:** Typed port-based graph with ambiguity
- **Q46 A:** Responsive PySide6 UI and bounded workers
- **Q47 A:** Public SDK and strict Worksheet R1 adapter
- **Q48 A:** Synthetic gold fixtures and independent benchmarks
- **Q49 A:** Continuous tested WP-000 to WP-011 releases
- **Q50 A:** End-to-end Claude coding, packaging and final-owner review

## Q51-Q100: owner approved 9 Nov 2026; concise normative restatement of the recommended defaults

- **Q51 A:** Extract every identifiable engineering element, annotation, symbol, specification, connection, label, drawing reference and metadata field, including non-standard items.
- **Q52 A:** Automatically analyse the whole drawing without preselecting equipment or teaching symbols; enable review and correction.
- **Q53 A:** Support native-vector, vector-outlined text, scanned, raster and mixed PDF/image inputs; add individually validated DXF and lawfully available CAD/engineering exchange adapters.
- **Q54 A:** Provide versioned, editable drawing-convention profiles for symbols, tag grammar, title blocks, line numbers, legends and company conventions.
- **Q55 A:** Continue partial extraction, identify missing information and uncertain alternatives, show per-region and category coverage; never silently omit significant information.
- **Q56 A:** Retain and benchmark RapidOCR, and use adaptive, selectively invoked local OCR alternatives where licensed, with native PDF text first.
- **Q57 A:** Recognise text converted to vector outlines using selective rasterization and OCR/vector shape analysis.
- **Q58 A:** Handle rotated, stacked, tiny, touching, partly obscured and low-contrast lettering; re-read uncertain crops and retain alternatives.
- **Q59 A:** Extract titles, numbers, revisions, issue status, dates, firms, approvals, reference tables, holds, notes, legends and sheet metadata.
- **Q60 A:** Reconstruct technical tables and numeric/unit associations with cell coordinates and exact source values.
- **Q61 A:** Recognise manual, actuated, control, isolation, check, relief, shutdown, bypass and specialty valves, actuators, positioners, solenoids and valve annotations.
- **Q62 A:** Recognise vessels, separators, columns, tanks, pumps, compressors, filters, exchangers, heaters, coolers, reactors, mixers, strainers, skids, packages and equipment boundaries; extensible types.
- **Q63 A:** Recognise pressure, temperature, flow, level, analytical, position, control and safety-related instrument symbols, functions and locations; permit user-defined types.
- **Q64 A:** Recognise standard and project-specific symbol styles via original-geometry libraries, authorised legends, and user teach-by-example without end-user model retraining.
- **Q65 A:** Persist raw graphics, position, candidate classes, reasoning/evidence and uncertainty; human corrections should propagate only after consistency review.
- **Q66 A:** Reconstruct supported process, utility, vent, drain, bypass, tie-in and auxiliary piping routes and their connections.
- **Q67 A:** Explicitly distinguish tees, non-connected crossings, junction dots, bridges, gaps, break lines, overlap and uncertain junctions.
- **Q68 A:** Preserve line numbers, dimensions, services, classes, specs, material, insulation, tracing, fittings, reducers, flanges, pressure classes and source locations.
- **Q69 A:** Build a typed port-based graph for equipment, nozzles, line segments, valves, instruments, connections and boundaries based on drawing topology.
- **Q70 A:** Determine flow direction only from drawings or reviewed evidence; combine off-sheet references; retain UNKNOWN directions.
- **Q71 A:** Reconstruct represented instrument loops from transmitters, controllers, final elements, indicators, switches and explicit signal links.
- **Q72 A:** Distinguish electrical, pneumatic, hydraulic, capillary, software, communications and other instrument signals from process piping.
- **Q73 A:** Represent PLC/DCS/SIS/remote-control system boundaries, depicted I/O, alarms and interlocks without inventing control logic.
- **Q74 A:** Recognise relief devices, shutdowns, vents, blowdowns, drains, car seals, locks, spectacle blinds, bypasses, fail positions and depicted protective functions.
- **Q75 A:** Identify safety-relevant objects for review, but never independently award safeguard/IPL/SIL/PFD credit, approve studies or claim plant safety.
- **Q76 A:** Build project-wide cross-drawing engineering model using compatible and evidence-based off-sheet matches.
- **Q77 A:** Keep immutable drawing revisions, detect added/removed/changed objects, distinguish source changes from recognition/model changes.
- **Q78 A:** Store evidence, provenance, review, confidence status, alternatives and conflicts for every entity and relation; separate observed from inferred.
- **Q79 A:** Distinguish drawing occurrences from proposed plant/engineering identities; never merge on tag equality alone.
- **Q80 A:** Extend existing standalone SQLite with additive versioned engineering-entity, attribute, port, relationship, evidence and review structures.
- **Q81 A:** Export source references, text, equipment/line registers, typed graph, design values, symbols, annotations, uncertainty, approvals and coordinates for another AI.
- **Q82 A:** Create evidence-backed engineering narrative per drawing: purpose, equipment, flow, loops, protection, interfaces and unknowns.
- **Q83 A:** Label statements DIRECT_OBSERVATION, STRUCTURALLY_DERIVED, CONTEXTUAL_INFERENCE, CONFLICTING or UNKNOWN and cite evidence; no invented conditions.
- **Q84 A:** Support source-grounded engineering graph queries: connected items, measured variables, routes, isolation proposals, revision changes and unresolved issues.
- **Q85 A:** Deterministic local extraction is usable without any LLM; optional lawfully licensed local AI interpretation, no runtime uploads to cloud AI.
- **Q86 A:** Interactive overlay viewer with selectable equipment, instruments, valves, lines, source evidence, search, zoom and cross-highlighting.
- **Q87 A:** Auditable accept/reject/reclassify/edit/link/unlink with named reviewer and immutable review history.
- **Q88 A:** Cancellable, resumable bounded batch jobs with partial results, caching, progress and project summaries.
- **Q89 A:** Linked equipment, valves, instruments, lines, loops, graph, document, review, discrepancy and AI-export workspaces.
- **Q90 A:** Export user-selected files only after confirmation; import and analysis persist only to project database; no silent overwrites.
- **Q91 A:** Normal Windows 11 CPU-only workstation baseline with optional GPU acceleration, tiled processing, caching, bounded memory and graceful fallback.
- **Q92 A:** Retain compatible components and select permissive licence-cleared code/models/weights; record dependency and redistribution evidence, no unapproved copyleft/commercial.
- **Q93 A:** Local-only no-telemetry security, untrusted-file isolation, secure project data and temp files, bounded processes and explicit export.
- **Q94 A:** Quick, Standard and Deep modes, all evidence-preserving; deep selectively reprocesses uncertain regions and builds richer graph hypotheses.
- **Q95 A:** Report stage status, coverage, failure, timeout, skipped analysis and partial results; zero data must not appear as complete success without proof.
- **Q96 A:** Unit, regression, OCR, symbol, geometry, graph, GUI, integration, security, performance, cancellation, export, installer and compatibility tests, positive/negative/edge cases.
- **Q97 A:** Controlled synthetic fixtures plus independently annotated real sheets, with independent holdout, precision/recall, per-class evidence, omissions and calibrated scoring where justified.
- **Q98 A:** Independent release gates for software, accuracy, integration and engineering; status NOT_RUN/FAIL/BLOCKED surfaced; never claim validation not done.
- **Q99 A:** Deliver integrated source, tests, schemas, rule catalogues, traceability, benchmark tools, Windows build/installer when possible, instructions, rollback and AI-ready examples.
- **Q100 A:** Claude fully implements and tests in-scope WPs autonomously, preserving access/security/legal gates; final product release is owner-approved only.

Full original Q1-Q50 descriptions reside in `baseline/Rev_X_INPUT_ARCHIVE_UNMODIFIED.zip` -> `source_snapshot/docs/CLAUDE_MASTER_PROMPT_AUTONOMOUS_REV_F.md` and approval files; the original `AUTONOMOUS_DEVELOPMENT_CHARTER.md` also governs work. Do not substitute this condensed register for the frozen 104-requirement Worksheet contract.
