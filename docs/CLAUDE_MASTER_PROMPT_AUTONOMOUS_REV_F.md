# EXECUTION AUTHORITY - READ BEFORE ANY OTHER SECTION

The project owner authorises **continuous, self-directed development inside this P&ID Reader project**. All 50 default Option A design decisions are approved. You are the lead implementer and may select and execute reasonable, reversible technical details without asking the owner to choose among alternatives. Complete the application before requesting a product review. For any choice not specified, prefer the simplest architecture consistent with the immutable R1 contract, write a short Architecture Decision Record (ADR), add tests, and continue.

This is a **development mandate**, not permission to bypass Claude Code or OS security; obtain valid tool access, use sandboxing and limited allowlists/Auto mode where supported. It does not permit purchases, credential disclosure, uploading confidential drawings, bypassing paid licences, altering the live Worksheet host, changing the frozen R1 contract, destructive Git operations, or falsely claiming engineering validation. When a blocked external action cannot be performed, deliver the completed local code and a precise blocked-action note; do not repeatedly ask for approvals or stop unrelated development.

Authoritative companion files: `AUTONOMOUS_DEVELOPMENT_CHARTER.md`, `CLAUDE.md`, `planning/DECISIONS_APPROVED_STAGE5.md`, `planning/DECISIONS_STATUS.json`, `planning/STAGE5_DECISIONS_Q41_Q50.md`, and the **byte-identical** `contracts/PID_READER_MODULE_REQUIREMENTS_R1_UNMODIFIED.zip`.

---

# CLAUDE MASTER DEVELOPMENT HANDOFF: ADVANCED P&ID READER

Revision: Autonomous Development Rev F, approved implementation contract, 7 November 2026. Supersedes Stage 5 Rev E status wording.

## Decision and delivery status - read this first

- The project owner explicitly APPROVED all forty Option A development decisions from Stages 1 through 4 (Q1-Q40). Treat them as binding.
- The project owner now expressly approves ALL Stage 5 Q41-Q50 Option A defaults as well. All 50 design decisions are APPROVED. The owner also grants standing authority for routine, reversible, in-scope code development and technical design choices; see `AUTONOMOUS_DEVELOPMENT_CHARTER.md` and `CLAUDE.md`. Do not ask for approval at each work package. Finish a tested product and deliver for final owner review. This is not approval to incur new charges, disclose drawings, alter a live Worksheet installation, bypass tool/security permissions, force push, or claim independent engineering validation.
- This is a development HANDOFF, NOT a claim of implemented software. Nothing in this package establishes recognition accuracy, completed UI, Windows acceptance, independent engineering approval, or Worksheet integration.
- This package includes the owner's ORIGINAL `PID_READER_MODULE_REQUIREMENTS_R1.zip` byte-for-byte as the primary, frozen host contract. Treat its 104 requirements, schemas, hash helper, checker, skeleton and hand-in checklist as authoritative for compatibility. This document adds a standalone product architecture; it does not amend R1. Where there is ambiguity, preserve the stricter existing host contract; record the conflict rather than guessing.
- Do not claim the `pid_reader` reader is already implemented. R1's `read_pid()` is `NotImplementedError`. Its supplied checker tests are only contract tests.
- No real client drawing is supplied or authorised for training. Synthetic or explicitly cleared drawings only.

## 0. You are to build software, not merely another plan

You are the lead Python desktop, document-vision, process-engineering-data and software-quality developer. Your task is to implement a separate, installable Windows P&ID Engineering Intelligence Reader and a reusable Python library that other programs can consume. Reuse the same deterministic extraction engine through isolated integration adapters. Implement in small tested vertical slices. At the end of each slice save working source code, runnable tests, screenshots or output evidence where possible, source provenance, an open-issues log and rollback path IN THE REPO; do not interrupt the owner for sign-off, and continue to the next slice. Never mark NOT_RUN as passed.

Do not copy proprietary code, symbol sets, standards text or CAD databases. Choose dependencies only after licences, offline packaging and training-data provenance are checked. Preserve drawing confidentiality. Software output is a proposed reading of a drawing, NOT an assertion about real plant configuration or operational safety. Do not make HAZOP, LOPA, QRA, SIL, IPL or ALARP decisions.

### Exact project locations (do not correct their spelling)

Windows source project root:

`C:\Users\Admin\OneDrive - Enhance Integration Engineering\Company\006 Calculation Methods\26 P&ID reader`

Git remote: `https://github.com/EIEng-enginering/P-ID-reader.git`

The owner `EIEng-enginering` contains the spelling `enginering`. Do not change it. When last checked, the repository existed but was empty; the connected GitHub account had read but not push access. Confirm actual local and remote state on the development machine before initializing or committing; do not assume pushes are permitted. Do not replace an existing project or repository if work has appeared since this specification was written.

Recommended default runtime-data location for caches, project working databases, temporary PDF/OCR files and ML models: a user-configurable non-synchronised local directory, e.g. `%LOCALAPPDATA%\EIE\PIDReader\` (illustrative; implement via Windows known folders). The source tree may reside in OneDrive, but avoid high-write working databases or caches there. Keep portable exports and backups under user selection. Never put absolute machine paths in a portable `.hzcase` file.

## 1. Preserved Stage 1-4 owner-approved design (forty decisions)

The following decisions are binding in addition to the detailed previous discussions and R1. Each line is a requirement, not an aspiration.

### Stage 1 / Q1-Q10: product scope

Q1. Standalone Windows application, reusable GUI-free Python core and independent host adapters. Same engine, multiple application surfaces.
Q2. Multi-format architecture: vector/scanned/mixed PDF, images, DXF, DEXPI, and planned/licensed DWG/DGN/intelligent CAD, with format-specific delivery/test status. PDF first for R1 host.
Q3. Extract and categorise as much DRAWING-SUPPORTED engineering information as possible: title blocks, equipment, valves, piping, instruments, controls, shutdown references, notes, line specs, relief items, connections and attributes. Preserve verbatim source, do not invent missing values.
Q4. Typed, port-based engineering connectivity graph: symbols, equipment nozzles, line branches, line crossings, instrument signals, flow arrows and off-page connectors, with explicit ambiguity.
Q5. Hybrid native-document and vector extraction, offline OCR, specialist symbol detection, geometry, engineering rules, optional authorised ML. No reliance on general vision AI as sole authority.
Q6. Versioned symbol/engineering/tag catalogues, lawful starter content, project-specific overrides and source licences; standards-aware where rights permit.
Q7. Source-linked human correction, explicit uncertainty, accepted-as-reading states, revision impact and append-only review decisions.
Q8. Public Python SDK, isolated worker/CLI, JSON schemas, DEXPI where conformant, optional controlled local API; never require downstream clients to read internal SQLite schema.
Q9. Fully functional offline, bounded hostile-input parsing, pinned dependencies, no telemetry, optional external services only by permission.
Q10. Independent benchmark, measured precision/recall/connectivity and silent misses, supported-class declarations, staged validation.

### Stage 2 / Q11-Q20: release and information design

Q11. Usable vertical-slice increments R0.1-R0.9: project shell/PDF, vector extraction, scanned OCR, connectivity, review/export, multi-sheet, DEXPI/DXF, licensed CAD adapters, host rehearsal/validation. Never label aspirational formats implemented.
Q12. Five separate layers: immutable source, observations, interpretations, relationships, review decisions. Stable plant entity IDs distinct from R1 deterministic observation/result IDs.
Q13. Hybrid text/symbol/tag matching, project-specific profile, recognition alternatives and UNKNOWN class; corrections do not automatically become shared training material.
Q14. Strict topology rules for ports, junctions, crossings, signal and process edges, off-page links, and unknown directions, with source evidence.
Q15. Plant-wide proposed graph across immutable drawings and revisions; source- and model-change comparison; special stricter R1 host same-run cross-sheet limits.
Q16. Visual review with inspect/edit/accept/reject/ignored/stale, provenance and optional independent sample check. No automatic acceptance.
Q17. R1-safe versioned adapters with no automatic host record writes, complete source evidence and unit-tested handoffs.
Q18. R1 fixed host resource limits; separate configurable standalone processing profiles, secure temporary files and no default online access.
Q19. Lawfully redistributable/versioned starter engineering catalogues and mappings, company-specific overrides, training models with documented licences.
Q20. Gold benchmark >=120 synthetic or cleared drawings, >=30 untouched final test drawings, separate class/format gates, true real-Windows tests and independent sign-off.

### Stage 3 / Q21-Q30: recognition, graph, storage and interfaces

Q21. Eight-stage evidence-preserving pipeline: validate, classify, native extraction, OCR, symbol/line, engineering interpretation, uncertainty checks, publication.
Q22. Preserve verbatim OCR/native text, rotation/polygons, candidate association and advisory tag parsing; do not infer safety functionality from tag alone.
Q23. Hierarchical visual/engineering/functional symbol classes, variants, project profiles and versioned model cards; UNKNOWN when unresolved.
Q24. Typed connection endpoints/ports, geometric junction rules, unconfirmed alternatives, line arrows only when explicitly depicted; no unreviewed path as established.
Q25. Normalized entities for project, document, revision, page, observations, engineering objects, attributes, ports, connections, evidence, alternatives, review, graph and export snapshots.
Q26. Cross-sheet reconciliation using multiple compatible evidence factors with ambiguity and source-revision binding; model-change differences distinguished from drawing changes.
Q27. Separate raw scores for OCR, symbol, association, geometry, topology, interpretation; calibration only when independently measured; exact R1 decision terminology.
Q28. Versioned offline SQLite, graph queries/indexes/full-text and append-only decision/audit; R1 host uses its own additive tables and audit, not direct standalone schema copy.
Q29. R1 worker signatures and exact JSON, deterministic hash/IDs, refusal semantics; separate richer standalone SDK and schema; backwards compatibility tests.
Q30. Exhaustive unit, geometry, OCR, adversarial, integration, benchmark, Windows, performance and licence evidence; gates not performed remain NOT_RUN.

### Stage 4 / Q31-Q40: workflows and Windows UI

Q31. Configurable dockable multi-document Qt workspace: Project, Drawings, Data, Graph, Review, Exports; saved layouts and keyboard access.
Q32. Responsive tiled/vector-quality drawing viewer with zoom, pan, search, mini-map, source/overlay distinction, reliable crop/rotation coordinate transforms, revision compare.
Q33. Virtualised spreadsheet-like equipment, piping, valves, instruments, connections and uncertainty registers, with filters, source jump and audited corrections.
Q34. Review queue prioritised by uncertainty/dependencies/critical connections; batch preview with R1 restrictions and recorded second checks.
Q35. Versioned system/company/project symbol/tag/engineering catalogues with licence records; never silently alter accepted historical readings on library updates.
Q36. Source-linked graph workspace, typed paths, selected-neighbourhood expansion, ambiguity visibility and accepted-only vs include-proposals modes.
Q37. Bounded batch scheduler, source inventory, safe retries, per-document atomicity, job manifests and recoverable standalone project state; host remains one-revision-per-run.
Q38. Full facility/area/drawing explorer, multi-revision/source-vs-model diff, FTS and filters, downstream impact reports without silent source acceptance.
Q39. Purpose-specific adapters for HAZOP, LOPA, QRA/PSS, line/equipment indexes, other engineering clients; no automatic engineering acceptance or private DB writes.
Q40. Professional report/JSON/graph/DEXPI export where valid, offline Windows delivery, SBOM, all-theme/scale GUI checks and independent software/extraction/engineering/integration gates.

## 2. R1 precedence: exact frozen host facts and invariants

Read the included original `contracts/PID_READER_MODULE_REQUIREMENTS_R1_UNMODIFIED.zip` and apply all 104 PR-* requirements, not just this summary. Document the file SHA-256 and preserve every R1 file as an immutable input. Do not use this specification to amend its schema, checker or reference hashing.

- R1 was written against Worksheet 0.25.0a1, `.hzcase` schema v23, contract R22, as of 2026-11-07. These are historical starting facts, not assurances about the user's current host checkout. Verify before integration.
- The host is NOT itself Git (per R1). Rehearse a patch against a hashed COPY of the current host. Live host, case files, previously frozen contracts, old migrations and their hashes remain unchanged until explicit accepted integration.
- Host Python 3.12, PySide6 6.12.0. `pid_reader` core imports no Qt and importing has no disk/network/process/thread/logging side effect (PR-B01, B03).
- Host entry point `python -m pid_reader.worker`; host in-process API `read_pid(pdf_bytes, params, cancel=None, *, document_revision_id="", filename="", expected_sha256="")`, as in R1 skeleton. Worker CLI in R1 uses `run --input --params --output --workdir` plus optional source metadata flags.
- One completed extraction contains ONE schema-version-1 top-level JSON result with required keys: `schema_version, provenance, document, pages, objects, connections, loop_proposals, shared_component_evidence, unreadable_regions, warnings, summary`. Respect schema `additionalProperties:false` sections. Do NOT add standalone extension fields to this result.
- Input is bytes of one ACTIVE embedded source revision and optional page range. Recompute SHA-256; refuse mismatch. Host PDF <=16 MiB, maximum 500 pages, render pixels/page <=12,000,000. Parameters can lower but NEVER raise these limits; unknown parameters refused.
- Host placeholder machine/resource budgets from owner decisions: 4 cores, 8 GiB RAM, 30 min per job, 4 GiB worker memory; 20,000 output objects, 8 MiB stored output, 300 MB module delivery target. Must be verified/revised by owner as applicable; hard R1 caps remain binding for host hand-in when adopted.
- Encrypted/password-protected, script-carrying, recursive, invalid and unsupported documents are safely rejected or limited; never execute embedded PDF actions or fetch external links.
- Normalised bounding boxes use top-left origin with `0<=x0<x1<=1`, `0<=y0<y1<=1`; account for PDF crop box and rotation. Preserve source printed units as verbatim strings; no unit conversion or safety calculation in host extraction.
- Status of extracted item is UNVERIFIED; human decision options include ACCEPTED_AS_READING, EDITED_AND_ACCEPTED, REJECTED; distinct ignored-region and stale-source handling per R1. A confidence score is 'reader confidence', not probability of correctness without calibration.
- All outputs indicate limitations and unresolved/unreadable regions, never silent omissions. All proposed loops and shared-component evidence are claims about drawings only, not IPL independence or SIL/LOPA decisions.
- The exact SHA-256 rule: canonical JSON `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)` encoded in UTF-8. For `result_sha256`, exclude from `provenance` only `run_id`, `started_utc`, `finished_utc`, `result_sha256`, then hash entire remaining extraction. Repeat inputs/params/version must reproduce the hash.
- R1 output IDs `obj-`, `con-`, `loop-`, `shr-` use reference helper hashing. Do not replace reference helpers with a new algorithm. Detect deterministic-ID collisions for distinct identical-bbox/class/text observations and fail safely/represent conflict without overwriting. Canonical JSON sorts object keys, not list order: define and test stable sort keys for arrays so repeated runs do not yield different result hashes.
- Worker exit codes: 0 completion, 2 input refused, 3 limit exceeded, 4 internal error, 5 cancelled. stderr contains JSON progress/codes/counts only, no drawing content/tags. Worker writes only under supplied temp workdir, cleans up, and cancellation is effective within 5 seconds.
- `module.json` conforms to original `schemas/module_manifest.schema.json` with pinned dependency licences, model SHA-256, capabilities and blocked bulk classes. `pid_extraction.schema.json` and `tools/check_extraction.py` are final acceptance checkers for R1 results.
- Host `document_revision`, `drawing_region`, `doc_index_run`, `doc_text_span` are existing authoritative source/index tables. Any new host persistence uses the next free migration (24 only if still free), new append-only tables/triggers, host `append_audit`, `reconcile_model`, `VISIBLE_TABLES` and JSON export integration.
- SOURCE-PACK AMBIGUITY TO RESOLVE AT INTEGRATION: R1 PR-C09 says each sheet is a document revision and permits cross-sheet links only when sheets are supplied in the same run; PR-H02 defines one run as one document revision plus page range. Do not invent a way to merge separate document revisions in one host run. In R1 output, limit cross-sheet links to any multiple pages legally covered by the same input; otherwise emit separate off-page connector proposals and no resolved inter-document edge until an owner-approved future contract explicitly defines a multi-revision scope. Log this ambiguity in the host compatibility report.
- Host new tables: `pid_read_run`, `pid_object`, `pid_connection`, `pid_loop_proposal`, `pid_decision`, `pid_asset_link`, `pid_second_check`; new prefix `M17_` only if available at integration. Previous tables/SQL/checks/signatures never altered; contract comparison must classify ADDITIVE.
- R1 requires read-only host extraction. Human decisions can later link drawing evidence to assets, aliases, HAZOP nodes or LOPA layers THROUGH EXISTING host services. No auto HAZOP/LOPA row creation, asset credit, SIL, PFD, process design, QRA or ALARP decisions.
- Always show R1 warning: `Readings are proposals from software. Nothing here verifies the drawing or the plant.`
- R1 source confidentiality: no telemetry, no phone-home, no unconsented external AI, no document text or tags in standard logs, no real client data in tests/training/delivery. Optional providers must use host exact data transfer consent.

### Conflict resolution procedure

If standalone requirements conflict with R1, implement a versioned adapter that narrows the standalone result to the frozen host schema and behaviour. If this still cannot satisfy R1, mark that functionality UNSUPPORTED in the host, log a compatibility issue, and do not weaken R1. In the standalone product, a richer `.pidproj` model and separate output schema are permitted. For example, standalone attributes can be interpreted with typed values but host output attributes remain exact verbatim strings.

## 3. Repository and package structure - reference target

```text
26 P&ID reader/
  README.md
  pyproject.toml                  # Python 3.12 package, explicit extras
  requirements-lock.txt           # pinned versions, hashes
  LICENSES/  SBOM/  model_cards/
  contracts/
    worksheet_r1/                 # original frozen schema and hash checker
    standalone/v1/               # versioned JSON Schema/OpenAPI/DEXPI mappings
  src/pid_reader/
    __init__.py                   # no import-side effects
    api.py                        # R1-compatible API and deterministic helpers
    worker.py                     # R1-compatible process worker
    errors.py                     # typed, safe public errors
    config.py                     # validated config/profiles
    formats/
      pdf_source.py               # native text/vectors/pages/crops/rotation
      image_source.py             # scanned/image sources, standalone
      dxf_source.py               # DXF objects/blocks/layers
      dexpi_source.py             # DEXPI 2.0.1 conformant model import
      dwg_source.py               # optional licensed adapter, safe refusal
    extraction/
      classify.py                 # VECTOR_TEXT/RASTER_ONLY/MIXED/NOT_PID
      text.py                     # native/OCR spans, orientations
      symbols.py                  # library & model detection
      lines.py                    # line segments/crossings/junction candidates
      association.py              # text-to-symbol scoring and alternatives
      limits.py                   # hostile input, memory/time/page caps
      diagnostics.py              # unreadable regions and warnings
      pipeline.py                 # stages, no UI imports
    engineering/
      tags.py                     # project-configured advisory parsers
      types.py                    # typed engineering object taxonomy
      graph.py                    # ports, edges, typed signals/process lines
      topology.py                 # geometric inference & alternatives
      reconcile.py                # cross-sheet and object identity hypotheses
      diff.py                     # source vs extraction vs interpretation revision
      confidence.py               # raw scores, calibration metadata
    model/
      source.py                    # immutable source/revision observations
      entity.py                    # distinct persistent standalone ids
      evidence.py                  # bounded polygons + evidence links
      review.py                    # append-only decisions
      exports.py                   # immutable publication snapshots
    storage/
      migrations/
      sqlite.py                   # local transactions, indexes, schema hash
      audit.py                    # append-only decision history and checks
      queries.py                  # FTS and region / graph projections
      backups.py                  # versioned backup & recovery
    catalogue/
      symbols.py                  # system/company/project libraries
      tags.py                     # parser profiles
      mappings.py                 # DEXPI and source mappings
      licenses.py                 # source rights and model inventory
    jobs/
      scheduler.py                # bounded concurrency & retries
      stages.py                   # per-stage progress and cache keys
      isolation.py                # private workdirs, cleanup and cancellation
    public/
      sdk.py                      # stable project/query/review/export API
      cli.py                      # noninteractive commands
      standalone_schema.py        # richer canonical output, separate R1
      dexpi.py                    # DEXPI 2.0.1 validation/export
      openapi.py                  # optional loopback only, disabled default
    integrations/
      worksheet_r1/
        adapter.py                # strict standalone -> R1 conversion
        schema_check.py           # use ORIGINAL R1 checkers
        host_patch/               # patch against copied host, NEVER silently apply
      hazop.py                     # reviewed evidence handoff only
      qra.py                       # proposed topology only, no inventories guessed
      assets.py                    # reconciliation only
    ui/
      main_window.py              # PySide6 desktop shell
      drawing_view.py             # tiled viewer, layers, source click
      project_tree.py
      engineering_table.py        # virtual QAbstractTableModel
      graph_view.py               # selected-neighbourhood graph
      review_queue.py             # every decision append-only
      revision_compare.py
      job_monitor.py
      catalogues.py
      exports.py
  tests/
    unit/ geometry/ ocr/ graph/ review/ storage/ security/
    integration/ worksheet_r1/ ui/ windows/
  fixtures/
    synthetic_generator/         # drawable deterministic reference PDFs
    truth/                       # independent graph/observation labels
    splits.json                   # never leak held-out to training
  tools/
    evaluate_gold.py             # precision/recall/F1/coverage
    audit_dependencies.py        # licence and SBOM checks
    export_manifest.py           # all output hashes
  docs/
    architecture.md  requirements_traceability.csv  data_dictionary.md
    api_reference.md  licence_review.md  limitations.md
    developer_handoff.md  user_guide.md
  TEST_RESULTS/                  # NEW folder per run; never rewrite earlier evidence
```

Naming is a suggested implementation shape. You may reorganise for better design, but retain clear interfaces, no UI dependency in core, and document any deviation. Do not misrepresent placeholders as implemented modules.

## 4. Core domain model and contracts

### Separation of records

1. `SourceDocument` and immutable `SourceRevision`: exact source hash, type, filename/label, page inventory and non-authoritative printed revision.
2. `PageObservation`: direct source text/vector/raster region with coordinates and pipeline provenance; always immutable.
3. `CandidateClassification`: visual class, engineering class, function candidate, raw scores, alternative hypotheses, detection library/model versions.
4. `EngineeringEntity`: stable standalone identity only after explicit reconciliation, not equal to tag string or R1 observation ID.
5. `EngineeringAttribute`: original string and source span; optional advisory typed parse/units kept separately and never overwritten.
6. `ConnectionPort`, `ConnectionHypothesis`, `InstrumentLoopHypothesis`, `OffPageHypothesis`: typed edges/ports with evidence and uncertainty.
7. `ReviewDecision`: immutable event with actor, reason, before, after, item id and bound source revision/run.
8. `ExportSnapshot`: exact emitted bytes hash, schema version, selection scope, source hashes, model/library versions and unsupported-field report.

### Suggested standalone model fields (contract for design; refine with explicit migration)

| Entity | Minimum fields and constraints |
|---|---|
| source_revision | id UUID, project_id, logical_document_id, `sha256 CHAR(64)` UNIQUE in project+document, storage ref, imported UTC, status, exact printed rev, media type; bytes immutable |
| page | source_revision_id, 1-based page index, media box, crop box, rotation, dimensions, classification, refusal code, image/geometry checksums |
| extraction_run | run UUID, source_revision_id, model/config/library version hashes, worker/engine version, started/finished UTC, per-stage status, limitations and output SHA |
| observation | id UUID, run_id, page, kind enum, bbox/polygon (normalised), verbatim text, geometry or bounded representation, extraction origin, raw score; append only |
| candidate | id UUID, observation_id, class id, confidence type and value, model/source, alternatives, status PROPOSED, explanation reference |
| engineering_entity | UUID, project/area, canonical proposed class, external tag *not unique*, identity_state, created_on, superseded_by optional; no observation overwrite |
| entity_evidence | entity_id, observation_id, relation, source revision, claim provenance and recorded reviewer decision |
| port | id UUID, entity id, kind, geometry, source observation, port label, physical/signal type |
| edge_hypothesis | id UUID, from port, to port, edge type, directional assertion + arrow evidence, path geometry, ambiguity group, review_state, evidence ids |
| review_event | UUID, extraction item, reviewer display name, state, reason, before/after JSON, UTC, source revision hash, previous decision id; insert only |
| revision_match | old revision/run id, new revision/run id, candidate mapping, evidence and conflict reason, decision event if accepted |
| export_snapshot | id, created UTC, selection scope, schema, bytes SHA, source/version inventory, status and licence/droppage warnings |

Do NOT place `NOT_SHOWN` or missing fields as invented numeric zeros. Use explicit `UNKNOWN`, `NOT_SHOWN`, `UNREADABLE`, `NOT_APPLICABLE`, `NOT_PARSED` states as allowed by standalone schema. Do not insert those into R1 fields with closed enums. The adapter must translate to R1 accepted statuses/unknown values without illegal additions.

### Core invariants

- Each observation is traceable to immutable source bytes, page and nonzero-area coordinates; historical observations are never edited.
- Each accepted reading is bound to a particular exact drawing revision, never a fact about the installed plant.
- Acceptance/correction is a human decision, never an automatic confidence threshold transition.
- A `ConnectionHypothesis` cannot refer to nonexistent ports or unrelated source revisions without an explicit cross-sheet reconciliation record.
- Unknown flow direction remains UNKNOWN; no default inferential flow direction from valve/equipment type.
- Text originally printed is never silently modified by tag normalisation, unit conversion, typo correction or AI interpretation.
- Drawings may contain multiple copies of the same tag; do not require a globally unique tag.
- Changing a catalogue/model does not rewrite earlier accepted outputs. Reprocess as new run with source run-to-run diff.
- A graph query may distinguish ACCEPTED_READINGS_ONLY and INCLUDE_PROPOSALS; a questionable edge invalidates any claim of an established path.
- Idempotent import of exact same source/config does not duplicate immutable observations; scoped dataset reuse cannot import decisions from a different project.
- Worker failures/cancellation leave no partial host rows and no temporary document text outside the private working directory.

### Suggested migration constraints

Standalone DB: new numbered, checksummed, reversible-through-backup (not in-place downgrade) migrations; SQLite WAL for active standalone DB, foreign keys ON, read transactions and indexes. `CHECK` constraints on enums, JSON validity as supported, no direct mutation of event tables, audit hashes, tested backups. Compact/cache only disposable derived data, never immutable audit rows.

Host `.hzcase`: ADDITIVE ONLY with all seven required tables, insert-only triggers, event prefix assigned on integration, host `append_audit()` per write and `reconcile_model()` to detect tampering. No host table rebuilding, changing old CHECK lists or bypassing services. Test against frozen manifest; a new migration number is not reserved until integration.

## 5. Executable pipeline design (core; no Qt)

### Source intake (security gate)

```
import_document(bytes, source_metadata, request):
  assert allowed_media_from_bytes, not merely filename extension
  assert supplied_sha256 == sha256(bytes) if supplied
  reject encrypted/password-protected documents and active content
  enforce compressed/decompressed, memory, object, recursion, page, pixel and timeout caps
  inventory pages and record each as READ or REFUSED, with reason
  preserve raw source once as immutable blob + hash (standalone); host holds bytes already
  select adapter by signature and explicit allowlist
  report all refusals through typed safe errors
```

Do not run embedded macros/scripts, access linked URLs, launch external programs from source content, or store document content in generic logs. Bound parsing of XML/ZIP (entity expansion, zip bombs, nested references). DWG/DGN support requires an explicitly licensed compatible adapter; do not pretend DXF conversion preserves native intelligent semantics without verification.

### Vector PDF and OCR

- Use underlying text objects where reliably available; preserve exact character spans, glyph transforms, rotated page/crop coordinates and the difference between text extraction and later tag parsing.
- Produce page-level classification VECTOR_TEXT, RASTER_ONLY, MIXED or NOT_PID with reason. For R1 host, RASTER_ONLY without a bundled OCR component must be REFUSED/NO_TEXT_LAYER rather than processed as an empty page.
- OCR backend must be pluggable, offline and model-licence checked. Preserve candidate word boxes, orientation, alternatives and raw confidence; never treat text detected by OCR as more authoritative than actual source metadata.
- For linework use vector geometry first, then raster segmentation/tracing for image-only layers. Record raster-to-source coordinate transforms and error bounds.
- Break down detection into proposal types: source text, text candidate, symbol candidate, geometric path, junction candidate, off-page label, arrow candidate, title-block candidate, warning/unreadable region.
- Maintain a consistent coordinate frame from source PDF media/crop/rotation to page normalized top-left, and to GUI pixel viewport. Unit-test inverse transforms at 0/90/180/270 degrees, cropped and nonuniform page dimensions.

### Text association and parsing

- Parse project configuration profiles; recognise line tags, equipment tags, instrument loop text and drawing references. Verbatim source always stored. Parse may yield PARSED/PARTIAL/UNPARSED, with per-field evidence.
- Associate tags to items via spatial relationships, drawn leaders, bubble boundaries, crossing/line context, project syntax and competing candidates. Keep ambiguity group rather than selecting nearest automatically.
- A tag alone does NOT establish a safety function, shutdown service, SIL, physical connection, instrument independence, vessel inventory, set pressure or actual operational state.
- Example `XV-201`: offer candidate 'actuated valve' with evidence; do not automatically classify it as an emergency shutdown valve.

### Symbol candidate generation

```
native CAD block/property lookup (if trustworthy)  -> source candidate
vector / geometry template match                  -> candidate(s)
offline neural detector                           -> candidate(s)
legend / project profile                          -> candidate semantic class
text + graph + engineering constraints             -> evidence-ranked alternatives
unclear/missing symbol                             -> UNKNOWN/AMBIGUOUS + region
```

Do not merge contradictory observations into one unqualified classification. Each recognition model records model file hash, license, model card, training-data clearance and per-class benchmark results; calibration scores remain distinct from raw model scores. Unknown symbols must be shown in review queue.

### Geometry -> port graph construction

1. Extract/simplify line segments, polylines and symbol boundaries while keeping the original geometry and tolerance basis.
2. Detect endpoints, candidate junctions, dot/bridge conventions, tiny gaps, crossings and line gaps at placed symbols.
3. Create typed equipment/symbol ports (nozzle, piping, electric, pneumatic, hydraulic, software, capillary etc.) only when supported by appearance or metadata.
4. Segment piping at valve/inline equipment, line-class changes, branch junctions and off-page connector boundaries.
5. Build edge hypotheses with two endpoint IDs and geometric polyline, evidence, ambiguity groups, direction UNKNOWN unless actual arrows show it.
6. Distinguish process lines from signal/utility/control paths. Do not allow an electrical edge to imply process continuity.
7. Flag dangling/isolated endpoints; do not force connections to achieve graph completeness.
8. Recognise off-page connector candidates with printed labels. Standalone may reconcile across drawing sets using multiple evidence types; R1 host cross-sheet links only as allowed by SAME-RUN source evidence and contract.
9. Build advisory instrument loops from actual depicted signal connections and tag consistency; never label independence or credited protection.
10. Provide two query modes: accepted readings only vs include proposals; query result includes complete path provenance and unresolved edges.

### Confidence and uncertainty

Keep separate score dimensions: OCR text, symbol class, tag association, line geometry, junction, edge existence, source quality and interpretation; show score type and calibration version. Never average arbitrary model scores into an 'accuracy percentage'. In review UI use issue-specific labels ('Two tag associations', 'Unresolved junction', 'Source unreadable') along with source snippets/overlays.

### Revision comparison

- Source revision change = different exact immutable source bytes.
- Extraction version change = same source bytes, different engine/config/model results.
- Review revision = new user review event; does not alter source observation.
- Compare candidate correspondence using source geometry, class, verbatim attributes and multiple evidence factors. Persist alternatives and reasons; repeated tags do not prove identity.
- Report ADDED, REMOVED, MODIFIED, POSSIBLE_MATCH, EXTRACTION_CHANGE and UNRESOLVED separately. Mark dependent accepted readings STALE_SOURCE as effective status without deleting historical decisions. Never select 'latest approved drawing' based only on printed revision letters.

## 6. Windows desktop and workflow implementation

Use PySide6 6.12.0 pinned where required by host, but keep standalone GUI behind optional package extra `pid_reader.ui`; pure core imports must run with Qt absent.

### Window contract

- Dockable workspaces: Project, Drawings, Engineering Data, Graph, Review, Exports/Integrations.
- Drawing viewer: original source view with separately switchable overlays (OCR, symbols, line segments, junctions, unresolved/warnings), mini-map, zoom/pan, rectangle selection, evidence jump, rotation/crop correctness. Use incremental tiles. UI does not load every full resolution page into memory.
- Engineering registers: QAbstractTableModel plus SQL-backed fetchMore/canFetchMore; no per-record widgets for large sets. Frozen tag column and saved filters where supported. All editing generates audited interpretation/review commands, never overwrites observations.
- Graph: show selected neighbourhood, expansion, typed edges, source jump. No global giant graph render by default. Accepted-only and include-proposals modes.
- Review: list by uncertainty, drawing, class, consequence for workflow, status, source revision; select -> source region + graph + details; accept/edit/reject/ignore; reason validation; batch previews and constraints. Mandatory banner EXACT R1 text in the host and equivalent in standalone.
- Job queue: intake inventory, staged progress, pause scheduling, cancellation, limits, retry, resource use, output status and per-job limitations. Host worker remains one document revision/page range and atomic single commit.
- Revisions: side-by-side/overlay source comparison, source-vs-model differences, impact on downstream handoffs, stale decisions.
- Exports: choose evidence/review scope; preview records, dropped/unsupported fields and source hashes; save immutable export manifest.
- Themes light/dark/greyscale, font controls, projector view, keyboard navigation, narrow minimum window, 100/125/150 percent Windows scaling; no essential info hover only. Qt item models should be mutated only on GUI thread via queued signals; background extraction never blocks GUI.

### User story: standalone end-to-end

Open project -> import one synthetic drawing -> verify source hash and list pages -> choose profile -> run extraction -> view source and overlays -> inspect proposed V-101/PT-101/line connections -> correct one ambiguous tag and one junction -> record named acceptance of readings -> query accepted-only graph -> export reviewed JSON + source manifest -> restart app -> reopen project and inspect unchanged audit history -> produce diff after importing a revised drawing. Any failure rolls back only the current unit of work and leaves earlier immutable data intact.

### User story: Worksheet host

Host selects ACTIVE `document_revision` and optional pages -> worker receives exact bytes + metadata in private workdir -> enforce R1 limits and source SHA -> parse and produce ONE strict R1 schema JSON result -> original checker passes, matching `result_sha256` -> host atomic additive record_run (new append-only tables + audit) -> reviewer views source through host renderer and makes decisions -> optionally human links evidence to existing HAZOP node/LOPA layer/asset through existing services. Never directly write those targets, never mark a reading HUMAN_VERIFIED by extractor, never claim IPL independence.

## 7. Interoperability and API deliverables

### Python library core API (host - exact)

```python
from pid_reader.api import ReadParams, read_pid
result = read_pid(
    pdf_bytes,
    ReadParams(pages=(1,)),
    document_revision_id="host-document-revision-id",
    filename="P-100-001.pdf",
    expected_sha256="<64-character hex of bytes>"
)
```

The precise function shape, params and hash helpers come from ORIGINAL R1 skeleton. Its `ReadParams.extras` must remain empty; unknown parameters are refused. Return dict conforms exactly to R1 `pid_extraction.schema.json`. Note that `document_revision_id` must not be empty in an actual completed R1 output.

Worker CLI example (match R1):

```text
python -m pid_reader.worker run --input DOC.pdf --params PARAMS.json --output RESULT.json --workdir PRIVATE_DIR --document-revision-id REV-ID --filename DOC.pdf --expected-sha256 HEX
```

The CLI path usage and cleanup are an implementation obligation and are subject to private-temp and hostile-input handling. Exit 0/2/3/4/5 exactly as in R1.

### Standalone richer SDK - proposed public interface

```python
project = pid_reader.public.open_project(path, read_only=False)
source = project.import_document(source_path, profile_id="company-default")
job = project.submit_extraction(source.id, options=ExtractOptions(offline_only=True))
result = project.get_run(job.completed_run_id)   # data + provenance + limitations
candidates = project.query_objects(tag="V-101", include_proposals=True)
connections = project.trace_from(port_id="...", mode="accepted_only")
project.add_review_decision(item_id="...", decision="EDITED_AND_ACCEPTED",
                            actor="Named reviewer", reason="...", correction={...})
snapshot = project.export(selection=..., format="engineering-json-v1")
```

This standalone SDK is a target design, not an implemented existing interface. Define public data classes, error codes, pagination/selection semantics, transactions, schema examples and version policy before implementation. Record all API changes with compatibility tests. Use no implicit remote service. Optional loopback REST service must be authenticated, disabled by default and explicitly opted in. Imported clients cannot write internal SQLite rows directly.

### Format/import-export interfaces

- `engineering-json-v1`: standalone structured values + verbatim text, exact source geometry, observation IDs, entity IDs, review and uncertainty, mappings/limitations, source/model/library hashes.
- `worksheet-r1-json-v1`: strict frozen host extraction schema, may omit richer standalone fields with documented mapping; never insert extra properties.
- DEXPI 2.0.1: implement real schema+semantic validation before advertising 'conformant'; DEXPI alignment in a data class is NOT enough. Handle missing data as a documented loss report and never fabricate attributes.
- DXF: parse source metadata/blocks/layers/attributes; distinguish geometry from intelligent piping data. DWG/DGN and proprietary project formats require explicit licensed SDK or approved converter and separate tests.
- CSV/Excel/JSON/GraphML/report outputs: label proposal vs human accepted-as-reading, include provenance and non-verified-plant disclaimer.

## 8. Host integration instructions: patch, never rewrite

Host integration is a separate gated deliverable and requires the current host tree supplied by the owner. Never guess its latest migration number, event prefix or current services from the R1 historic facts. Steps:

1. Freeze source reader release (module version + tests + hash), then obtain a verified COPY of the current host tree and sample synthetic `.hzcase`.
2. Inventory host schema version, contract manifest, available migration IDs, event prefixes, current `services`, `core.validate_file`, report/export hooks, drawing viewer and AI consent services.
3. Compare host against R1 baseline. If changed, produce a compatibility report before any edits; preserve original R1 requirements or propose explicit owner-reviewed contract v2 if unavoidable.
4. Apply new `00NN_pid_reader.sql` against the COPY only: add seven required tables and insert-only triggers, no rebuild/alteration of older tables or CHECKs, numbered hash recorded. Use existing host services and `append_audit`.
5. Implement `pid_reader_host.py`: `enable_model`, `record_run`, `decide`, `reconcile_model`, `TABLES`, `TRIGGERS`, `MIGRATION`, event names; add service functions exactly as in original `skeleton/host_side_templates.py`. Ensure host saved file remains unchanged until its Save action.
6. Implement off-UI-worker orchestration: exact source bytes/hash, one JSON, independent schema/hash verification, atomic DB commit; cancelled/failed run writes no host records.
7. Add review UI and required status banner using host out-of-process drawing renderer; supported themes/scaling, keyboard controls, second-check queue.
8. Hook `VISIBLE_TABLES`, JSON exports, `core.validate_file`, `reconcile_model`, explicit `upgrade_worksheet_to`, test contract comparison ADDITIVE. Update OI/open issues and hand-in evidence.
9. Rebuild synthetic example case and packs, run all existing host and module tests in a NEW `TEST_RESULTS/LOCAL_BUILD_Rnn` folder, compare frozen old fingerprints, verify HAZOP/LOPA/SIF/asset tables byte-identical after extraction-only run.
10. Record evidence and acceptance delta in the repository; do not interrupt the owner for interim sign-off. Present it in the single final review. Only integrate into the live host after final specific authorisation; do not write to inaccessible GitHub or assume push permission.

## 9. Verification and test contracts

Your test suite must use a mixture of unit/contract tests, deterministic synthetic drawing generator with independent annotations, real drawing tests only if cleared in writing, and real-Windows tests. Never say '100% accurate' or 'validated engineering' based on a demo.

### Three types of truth are different

1. **Machine correctness**: given exact synthetic inputs and rule contracts, does the code return the expected hash, geometry, proposed graph, status and audit?
2. **Extraction performance**: on a held-out labelled drawing set, what are precision, recall, F1, tag exact match, CER, connection precision/recall, loops and silent misses by class/style?
3. **Engineering validity**: has a competent independent reviewer assessed the real engineering significance, supported range, limitations and integration behaviour? Code unit tests do not do this.

### Benchmarks (approved Stage 1-4 baseline)

- >=120 synthetic or cleared drawings across VECTOR_TEXT, dense vector, RASTER_ONLY, MIXED, annotated/multi-sheet, multiple symbol/tag conventions, rotated/cropped pages, markups and separate format adapters.
- >=30 untouched, recorded held-out test drawings; separate development and validation sets inside the rest. Publish exact split SHA before development tuning. No leakage of held-out labels into prompt engineering, library tweaks, model training, threshold selection or error-driven tuning.
- Truth annotation schema: supplied R1 `schemas/gold_annotation.schema.json` for host-compatible cases. Richer standalone truth may use an extension schema, with a deterministic projection back into R1 truth.
- Metrics: per class and per drawing style object precision/recall/F1 at predeclared IoU threshold; exact tag-match and character error rate; endpoint-pair connection precision/recall; loop proposal precision; SILENT-MISS rate (a true object/feature absent from detection AND absent from warnings/unreadable). Confusions and denominator must be reported; zero-ground-truth groups are N/A, never 100%.
- Proposed thresholds predeclared from owner-approved Stage 1-4: critical symbols precision >=98% recall >=95%; tag exact >=98%; critical connection precision >=99% recall >=95%; instrument loop proposal precision >=98%; critical silent misses <=1% for supported clean/vector classes. These are targets, NOT achieved results or requirements applying to all scan styles. For other classes/styles, Claude must predeclare conservative, scientifically defensible performance thresholds and document the basis before any held-out evaluation. If the appropriate independent reviewer is unavailable, mark that acceptance gate NOT_RUN; do not create an additional owner design-approval round. The original R1 owner checklist contains thresholds as decisions; attach the owner's dated Stage approvals.
- Independent assessor other than developer runs benchmark from delivered package. Actual independent G4-G7 host gates remain NOT_RUN until performed. If a class misses its bulk-acceptance threshold, mark it BLOCKED for bulk acceptance in manifest.

### Mandatory synthetic fixtures to implement

The accompanying `fixtures/fixture_contracts.json` defines named rule scenarios. **These are fixture specifications, not completed PDFs or measured truth**. Claude must implement a deterministic fixture generator emitting synthetic vectors/PDF/image inputs and independent truth JSON. Required geometry cases include:

- 0, 90, 180, 270 degree PDF rotation and non-default crop boxes, inverse page-coordinate map.
- Crossing-with-no-junction, intersection-with-junction-dot, bridge/hop, tiny gap, triple branch, valve inline break, nozzle inlet/outlet, reducer/spec break.
- Process line vs pneumatic/electric/software/capillary signals (type mismatch must not bridge).
- Arrow-supported flow vs unspecified direction; do not guess.
- Multiple possible label owners, OCR text overlapping symbol, instrument bubble split, mirrored/rotated labels, line number parsed differently by company profile.
- Same tag different objects, same object across sheets with both matching and conflicting off-page references, two versions of a drawing where only OCR model changes.
- Shared instrument symbol candidate linked to two proposed functions, but NO independent protection claim.
- Unsupported image OCR, corrupt PDF, encrypted/active-content PDF, excessive page count, decompression limit, cancellation midrun, unknown parameters, mismatched SHA.
- Determinism across repeats and order-invariant array sorting where R1 prescribes it; tampered hash and foreign endpoint must be refused.
- Audit before/after correction, duplicate corrections with later superseding event, rollback on transaction failure, stale source, second check, gated batch accept.
- Independent output consumer roundtrip, R1 projection schema validation, target report limitations and source hash manifest.

Every fixture must have documented expected objects, exact geometry/edge type and negative assertions. Invalid/ambiguous examples must not be hidden by passing tests on easy documents.

### Correctness guardrail tests (must include)

- `core_import_without_qt_or_side_effects`
- `read_params_unknown_refused`
- `source_sha_mismatch_rejected`
- `pdf_password_or_active_content_rejected`
- `all_pages_reported_no_silent_skip`
- `rotated_crop_coordinate_roundtrip`
- `r1_object_ids_hash_reference_agrees`
- `r1_result_sha256_reference_agrees`
- `r1_schema_strict_extra_property_rejected`
- `r1_connection_id_endpoints_exist`
- `r1_no_numeric_attribute_conversion`
- `r1_every_proposal_unverified`
- `r1_loop_never_states_independence`
- `r1_absence_shared_evidence_not_proof_of_independence`
- `worker_error_exit_codes_0_2_3_4_5`
- `worker_logs_no_document_text_or_tags`
- `worker_cancel_under_5_seconds_no_partial_write`
- `worker_over_limit_refuse_never_truncate`
- `reproducible_same_input_hash`
- `no_network_socket_attempts`
- `review_writes_new_event_old_unchanged`
- `review_no_automatic_acceptance`
- `revision_change_stale_readings`
- `standalone_graph_port_referential_integrity`
- `standalone_unknown_direction_uninferred`
- `standalone_crossing_without_dot_unconnected`
- `standalone_ambiguous_connection_blocks_accepted_path`
- `project_batch_restart_and_job_retry_safe`
- `original_host_data_unchanged_after_extraction`
- `host_additive_contract_manifest_unchanged_prior_hashes`
- `host_reconcile_catches_tampered_row`
- `host_new_schema_not_readable_in_older_version`
- `host_optional_online_transfer_off_by_default`
- `windows_ui_scaling_100_125_150_real_machine`
- `windows_package_offline_standard_user_installs`

### Existing R1 test status at handoff writing

Original R1 tests under `tests/test_check_extraction.py` were run in this working container on 2026-11-07: 16/16 passed in ~0.02s. This exercises the R1 synthetic checker and reference helpers only. It is NOT a reader benchmark, not a test of the unimplemented reader, not real-Windows acceptance, and not an independent engineering validation. Preserve this distinction in every report.

## 10. Incremental release work packages with stop gates

Each work package must yield a runnable increment. Do not write 'complete' until evidence exists. Dependencies and responsibilities below are design targets, not promises that all work has been performed.

| Package | Scope | Must pass before moving on |
|---|---|---|
| WP-000 | Inspect actual repo/host/R1, freeze source hashes, requirements matrix, Windows tooling, risk & licence register | Exact locations checked; no live modifications; sources catalogued |
| WP-001 | Python 3.12 package, no-side-effect core, R1 API and worker harness, strict schema/hash/errors | Original 16 R1 tests + independent worker error/cancel/hash tests; no claim of extraction |
| WP-002 | Standalone `.pidproj` storage, source intake, project shell, minimal PDF viewer | Safe source import/crop/rotation; backup/recovery; reference PC smoke tests |
| WP-003 | Native vector text/geometry extraction with evidence and limited tag parsing | Synthetic vector gold fixtures, refusal and coordinates, no silent blanks |
| WP-004 | Offline OCR and mixed/scan page handling (after model/licence gate) | Separate scan truth metrics, no model data uploads, CPU offline |
| WP-005 | Equipment/valve/instrument/line symbols, project catalogues and alternatives | Per-class symbol metrics, unknown handling and source-linked review |
| WP-006 | Typed port graph, crossings, junctions, line insertion, signals, loops | Junction/topology edge cases, graph data integrity, no safety claims |
| WP-007 | Full visual review, audit, second check and tabular source-linked register | Reversible-by-event review, batch gates, screenshots, Qt thread checks |
| WP-008 | Multi-document revisions, plant-wide reconciliation, graph explorer and batch queue | Ambiguous cross-sheet/duplicate cases, safe retry and data recovery |
| WP-009 | DEXPI 2.0.1 and DXF import/export, licensed adapter investigations; standalone public SDK/CLI/JSON | Schema+semantic DEXPI checks, DXF fixtures, API consumer compatibility |
| WP-010 | Frozen Worksheet R1 adapter and integration rehearsal on hashed host COPY | ADDITIVE manifest, case audit/reconcile, no side writes, host suite |
| WP-011 | Professional installer/reporting/docs/SBOM/license/benchmark package | Offline clean Windows, 100/125/150% tests, 120-drawing gold, independent gates |

If WP-004 or WP-009 third-party licence/model support is blocked, keep the preceding working program intact; document unsupported feature and add a safe refusal instead of falsifying completeness. If unperformed human checks are necessary to complete WP-011, report NOT_RUN and ship only as experimental development build, not engineering-accepted production release.

### Detailed acceptance protocol per WP

- `CHANGELOG.md`: what actually changed, source tree hash/commit, why, who/what accepted it.
- `TEST_RESULTS/LOCAL_BUILD_Rnn`: new immutable tests, exact commands, logs with no confidential drawing content, version/model/library checksums, machine environment, pass/fail/block/not_run.
- `REQUIREMENTS_TRACEABILITY.csv`: every PR-ID and owner decision links to files/functions/tests and state; no vague 'covered' claims.
- `OPEN_ISSUES.md`: blockers, uncertainties, engineering/standards/licence questions, unimplemented formats/classes.
- Example user workflow proving the increment, failure path and rollback/recovery.
- New screenshot/report export where UI or reporting changed.
- Independent checker results when relevant. A developer self-test never stands in for independent evaluation.

## 11. Dependency/licence/reproducible Windows build

- Pin Python 3.12 and PySide6 6.12.0 host-compatible release. Declare optional OCR/ML/CAD extras and their exact package versions and file SHA-256.
- Evaluate licence compatibility, redistribution rights, model weights, training data and patented/proprietary CAD readers before locking dependencies. Do not assume that a source package being importable means it may be redistributed commercially.
- DEXPI 2.0.1 reference: https://dexpi.org/specifications/ and https://dexpi.org/dexpi-2-0-1-specification-published-the-update-replacing-dexpi-2-0/ . Use this as a model/interchange reference, not proof of achieved conformant exports.
- Qt 6.12 reference: https://doc.qt.io/qt-6/qabstractitemmodel.html and https://doc.qt.io/qt-6/qgraphicsview.html . Qt item models are GUI-thread owned; worker results are marshalled to GUI thread.
- Offline wheelhouse and model resources must be shipped with independent hashes and SBOM, or clearly documented as requiring owner-approved installation step. No network access during product install/import/run without consent. During development, dependency/reference retrieval is permitted only within the developer machine's available trust and network policies, with licence/security checks and without uploading private drawings.
- Windows installer should support non-admin account, clear uninstall, offline launch, access to local user data paths, model load, no registry changes except declared installer registration if approved, no surprise scheduled jobs or telemetry.
- Source repo: produce a clean tree, `.gitignore` for caches/temporary/test outputs/private drawings, deterministic lock and scripts; never commit confidential source P&IDs or runtime databases. Clone/init after verifying actual local and remote state and available repository permissions; the owner pre-approves non-destructive local development. Never overwrite newly appeared history.

## 12. Final Claude execution instructions (mandatory)

1. FIRST inspect and log facts in the development journal (do not ask permission for routine decisions): local files/repo state, R1 checksums, host baseline if supplied, exact Python/Qt versions, dependencies permitted, unsupported licences and unresolved external dependencies.
2. Before implementing a feature, write an explicit acceptance contract: inputs, outputs, failure modes, source evidence, units/coordinates, data models, tests. Do not rely on prose understanding alone.
3. Implement one end-to-end small vertical slice with source, synthetic fixture, GUI if applicable, persisted results, test and handoff. Never make a large speculative rewrite.
4. Do not ask the owner to re-approve Q1-Q50 or routine implementation choices. ALL fifty Option A decisions are binding; stand-alone design/coding/testing/package choices are delegated under `AUTONOMOUS_DEVELOPMENT_CHARTER.md`. Plan internally, implement, test, record assumptions and carry on to the next work package. Do not stop to ask for routine design sign-off or approval of each completed package.
5. When a missing detail blocks implementation, use an explicit conservative assumption, label it, and keep the affected feature disabled/NOT_RUN until resolved. Do not invent standard rules, accuracy thresholds for unrepresented classes, licence grants, drawing revisions or engineering facts.
6. For R1, NEVER silently change frozen schemas, hashes, ID rules, worker API, output status, audit, migration history, case data or host services.
7. Build offline as the runtime default; online documentation/package downloads are permitted only through approved local tooling and compatible licensing/security policies. Do not send private P&IDs or confidential data to cloud services, and do not purchase new services. Reversible commits and non-destructive development-branch pushes to the specified repository are within the owner's development intent ONLY if the relevant tool actually has authenticated write access, the branch is not protected, and the data/licence review passes. Never force push, rewrite main or merge/release production automatically. Document any blocked external action and continue local work.
8. After each package: run actual tests, save commands/results in the project without requesting owner review, inspect new GUI pages in a real Windows environment when available, label skipped tests as NOT_RUN, update decision/issue logs and continue. Give the owner one consolidated final review package rather than requiring interim sign-off.
9. Separately track implementation completeness, measured recognition accuracy, independent engineering review and real-Windows acceptance. None implies the others.
10. Finish with the source package, reproducible setup/run instructions, pinned dependencies/model cards/SBOM, all test reports, gold annotation/split metadata, export samples that pass actual validators, user guide, limitations, rollback and R1 integration patch on a host COPY. No 'full pass' claim if independent checks remain NOT_RUN.

## 13. Outputs Claude must deliver

At minimum, the final handoff must contain:

- A runnable and source-complete standalone Windows reader with Python package SDK and project persistence.
- Demonstrated offline input processing for supported formats with source evidence and explicit unsupported/refusal cases.
- A human review window, registers, selected-neighbourhood graph and project/batch navigation corresponding to supported features.
- R1-compatible module package with strict schema results, `module.json`, worker and host integration rehearsal artifacts (if actual host source has been provided).
- DEXPI/DXF adapters only when their specific tests pass; licensed DWG optional until rights are resolved.
- At least the agreed synthetic/cleared gold set and held-out split, benchmark reports by category and supported format, actual independent benchmark results or NOT_RUN.
- 104-row R1 acceptance matrix with every PR-ID, state, actual evidence references; all staged owner decisions similarly traced.
- Source provenance, dependency and model licence documentation, all file SHA-256, SBOM, exact Windows build commands and reproducible archive.
- Word/Excel/PDF/JSON/graph/DEXPI outputs supported only where implemented and tested; reports always distinguish proposed vs accepted-as-reading.
- Clearly labelled unimplemented work, open issues, safety limitations and external approvals still required.

## 14. Sources and precedence

**Primary input (binding):** Attached original `PID_READER_MODULE_REQUIREMENTS_R1_UNMODIFIED.zip`, containing 01_REQUIREMENTS.md, 02_HOST_INTEGRATION_FACTS.md, 03_ACCEPTANCE_CHECKLIST.csv, 04_HAND_IN_CHECKLIST.md, schemas, original skeleton, checker, SQL template and sample. It is NOT a complete reader.

**Owner decisions:** Stage 1 Q1-Q10, Stage 2 Q11-Q20, Stage 3 Q21-Q30, Stage 4 Q31-Q40 and Stage 5 Q41-Q50 are ALL APPROVED Option A by the owner. Design decision approval is not software acceptance or evidence that tests were run. `AUTONOMOUS_DEVELOPMENT_CHARTER.md` governs in-scope execution autonomy and remaining external safety/permission limits.

**Public documentation reference points:** DEXPI 2.0.1 official release/specification (2026-09-30), Qt 6.12 official model/view and graphics documentation, current Python 3.12 Windows and deployment documentation. References must be checked against actual pinned versions at build time. Any standard or proprietary model used must have verified distribution rights.

---

**END OF CLAUDE MASTER PROMPT**
