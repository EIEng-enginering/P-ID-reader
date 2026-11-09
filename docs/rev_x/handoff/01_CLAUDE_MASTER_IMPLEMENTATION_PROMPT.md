# CLAUDE CODE MASTER EXECUTION PROMPT - FULL P&ID READER UPGRADE

> Copy the entire content of this file to Claude Code, attaching the COMPLETE ZIP. This is a development execution order, not a request for a further plan or more approvals.

You are the lead Python 3.12 / Windows desktop engineer, technical OCR/computer vision engineer, P&ID process-data modeller, test engineer, and release engineer for the existing **Advanced P&ID Reader**. The owner has explicitly approved **every recommended Option A for Q1-Q100**. Your mission is to implement, integrate, test and package a full upgrade to the ACTUAL existing program using the source in `baseline/Rev_X_INPUT_ARCHIVE_UNMODIFIED.zip`, reconciling against the authoritative local worktree. Build useful working code in sequential integrated slices; do not return a report alone in place of programming.

## 0. First, prove what source you have

- Extract the unmodified baseline archive. Validate its full SHA-256 (`61ca7b4acdf8fa24282e4c02de50c027175802b8b197e18cd926885bf1805636`) and the frozen Worksheet R1 ZIP SHA-256 (`09174700ff54cdf3bd899d952951d8969041f1a094cbe8cefff9bd714cbd25e2`). Check the source tree, `README.md`, `pyproject.toml`, `requirements-lock-win312.txt`, baseline metadata, existing Git history and tests.
- The documented baseline is **0.17.0-dev0**, branch `main` @ `e676ff1`, Python 3.12.10, PySide6 6.12.0, standalone SQLite v12, frozen Worksheet contract R1 and 334 pass/6 skip **as supplied evidence**, not as independently tested by ChatGPT.
- The user's actual local source path is `C:\Users\Admin\OneDrive - Enhance Integration Engineering\Company\006 Calculation Methods\26 P&ID reader`. Remote is `https://github.com/EIEng-enginering/P-ID-reader.git`. Confirm actual repository content, branch, permissions and uncommitted changes; do not overwrite new local work with the snapshot. No force-push, protected-main merge or history rewriting.
- Run existing contract, pytest and preflight checks *before* changes. Record command, environment, wall time, output and SHA of result. If a test cannot run, mark `NOT_RUN` and explain exactly why; do not invent green checks.
- Read baseline `source_snapshot/docs/CLAUDE_MASTER_PROMPT_AUTONOMOUS_REV_F.md` and `docs/AUTONOMOUS_DEVELOPMENT_CHARTER.md`, then `source_snapshot/contracts/PID_READER_MODULE_REQUIREMENTS_R1_UNMODIFIED.zip`, **all 104 PR-* requirements**, the actual `api.py`, `worker.py`, `isolation.py`, and `engineering/pipeline.py`, `project.py`, `migrations.py`. All approved old decisions remain binding. Do not discard or simplify existing modules.

## 1. Immutable constraints and output boundaries

1. Keep Worksheet R1 contract **byte-identical**: `api.read_pid` signature, one schema-v1 result, required top-level keys, canonical hashes, deterministic IDs, worker transport, normalized top-left page fractions after rotation/CropBox, resource limits, one active embedded revision per host run. No v2 additions to R1 JSON; richer outputs are **standalone, separately versioned**.
2. Keep the standalone GUI, CLI, public import-safe Python SDK, `PySide6`, project SQLite and evidence review history. SQLite v12 remains readable. Add new standalone tables via reversible **additive v13+ migrations**, never destructive data replacement. Include backup and migration/restore tests.
3. No cloud calls or telemetry at runtime. CPU Windows 11/Python 3.12 remains complete supported baseline; GPU/local AI optional. No third-party model is silently downloaded at runtime; all models checked for licence, hash, supported hardware and optional deployment rights.
4. Do not copy copyrighted standards or proprietary vendor symbol catalogues into prompts, model training, fixtures or source without explicit permission. ISA/ISO rules may be referenced as *standards to implement in a legally cleared way*, not pasted. New code, models, weights, binaries and transitive dependencies need permissive or separately approved licences. Reject AGPL-only integrations by default.
5. Every item is a **drawing-based proposal**, never a verified plant fact. Distinguish `DIRECT_OBSERVATION`, `STRUCTURALLY_DERIVED`, `CONTEXTUAL_INFERENCE`, `CONFLICTING`, `UNKNOWN` for claims; every accepted-as-reading action is named/human-reviewed and audited. None grants design verification, SIL, safety credit, HAZOP/LOPA approval, QRA approval or plant as-built status.
6. Never infer that a drawing has no equipment because extraction returned zero. Expose `FAILED`, `INCOMPLETE`, `NOT_RUN`, `TIMED_OUT`, `PARTIAL`, `COMPLETE_CANDIDATES` separately from human acceptance and engineering verification. A zero-word result requires trace of OCR execution and completeness evidence.
7. Importing and analysing a P&ID must not write exports to arbitrary folders. Keep existing File -> Export folder picker and collision-safe `NAME (2)` behavior. Recomputations may write approved project SQLite/temp/cache under non-sync storage, with bounded cleanup. Never silently overwrite prior exports.
8. Never alter the live Worksheet host or its databases/case files. Perform any integration on a disposable **hash-verified COPY** and run the frozen R1 checker. No direct accepted HAZOP/LOPA writes. User's final production release remains separately approved.
9. Make each analysis step **deterministic, bounded, cancellable, idempotent, hash/version keyed, observable and locally testable**. Any size/time cap triggers explicit incomplete status; no silent truncation.
10. No additional design approval questions for routine in-scope implementation. If external spend, licence, missing secret, production integration, client confidentiality or external independent reviewer blocks one feature, record `BLOCKED` and continue independent WPs. Never claim background work persists outside the actual coding session.

## 2. Desired finished behavior

User opens one or many P&IDs (native vector, outlined-text vector, scanned/mixed raster PDFs, images, selectively DXF, future separately licensed CAD adapter). The program automatically classifies pages and regions; extracts all supported text and tables (including title/revisions, notes/holds, tag lists, setpoints); finds equipment, valves, instrument bubbles, packages, manifolds, piping sizes/line numbers and instrument signals; reconstructs port-based pipe/signal/loop/cross-sheet connectivity without joining crossings incorrectly; and provides source-linked tables, graph, overlays, AI-readable JSON and a detailed narrative. Each user correction can be recorded and propagated only with explicit consistency and audit. Incomplete areas are listed for review. Full operation remains possible entirely offline without an LLM.

Concrete drawn examples to understand (NOT claim as already validated gold): S023 includes pressure-control instruments (`PIT-100`, `PIT-101`, `PIC-102`, `PCV-102`, `PSHH-201`, `ZT-102`, `ZSC-201`, `ZSO-201`), NPS 20/30/16 piping, heater/pressure-reducing manifolds, station data, flow arrows, PLC/SCADA, and drawing 0209-01-ML-02-001 rev C. The S025 user output has zero OCR words/nodes despite 671 raster contacts and 17 candidate gaps, although the visual drawing contains ethane pipeline pre-filter/booster-pump content. Use these as **diagnostic cases only**, not independently labelled engineering ground truth.

## 3. Implement full typed pipeline, not a monolithic vision model

Follow `04_ARCHITECTURE_AND_IMPLEMENTATION.md` and `05_RECOGNITION_ALGORITHMS.md`. Target these connected features:

A. **Ingest/health**: source immutable SHA, page classification vector/raster/mixed/outlines, rotation/CropBox, native text coverage, render checks, stage events, output budget. Identify logical drawing area vs border/title/legend/table/revision clouds.

B. **OCR completeness**: keep native text, existing RapidOCR 1.4.4 and tiled 1200px/150px overlap/per-bubble crop; diagnose stage skipped or empty; benchmark selective higher-DPI, rotations, grayscale/color, binarization, de-skew, character/word grouping, vocabulary-aware re-scoring that never turns weak evidence into fact, and alternative available local OCR. Preserve 1:1 provenance from all transformations.

C. **Symbols**: operate on vector outlines and raster: filled/curved valve shapes, rotated/scaled, actuators, solenoids, fail flags, gate/globe/ball/check/butterfly/control, equipment and skid symbols, instrument bubbles. Use licensed original-geometry profile library and optional bounded ONNX detector. Retain teach-by-example and catalogue behavior; never force a class.

D. **Piping/relations**: extract vector strokes (segments, arcs, polylines, bezier approximations), raster skeletons, dots, bridges, isolated loops, line breaks, dashed instrument signals, arrows and off-sheet pennants. Resolve junction/crossing hypotheses using visual and semantic evidence, spatial index, typed ports. Every relation is `DRAWN_CONNECTS`, `PROPOSED_OFFSHEET_MATCH`, `SIGNAL_LINK`, `MEASURES`, `CONTROL_RELATION`, or a typed proposal; no proximity-only plant connection.

E. **Engineering parsing**: versioned tag grammar, piping line specs and units, reducers/flanges, nozzle schedules, F-1/P-1/etc class, instrument loops, alarm/setpoint values, positions/open/closed indications, pressure/temperature design conditions. Preserve verbatim source text alongside normalized quantities and uncertainty. Distinguish line tag from signal tag and drawing-number lookalike.

F. **Multi-sheet**: immutable sheet revision snapshots; evidence-based candidate matching across off-page connectors and plant asset identities; name matches alone cannot merge. Keep source changes and extraction-model changes separate.

G. **Storage/review/exports**: new standalone engineering-intelligence schema and additive SQLite tables; audit human edits, revision-aware proposed/accepted statuses. Interactive Qt viewer + registers, typed graph, quality dashboard. Export JSON/GraphML/XLSX/HTML/annotated SVG/PDF where implemented, with formula-injection-safe spreadsheet and HTML escaping. Provide DEXPI 2.0.1 XML only AFTER validating actual schema mapping; otherwise explicit refusal and mapping report.

H. **AI consumer**: export human-readable narrative and **evidence graph** with every claim/source crop/page/id and alternative; separate machine/structured prompt `16_AI_CONSUMER_PROMPT.md`. A narrative cannot substitute for data. Optional local AI model is advisory and disabled by default unless specifically configured and licensed.

I. **Quality gates**: coverage report by page/region/type + missing-object risk, OCR health event, stage completeness, uncertainty review priority; independently measured precision/recall on an untouched annotated corpus, critical silent misses, runtime/size regression and independent engineering review.

## 4. Read/write integration points (do not invent replacements)

- Reader/PDF/OCR: `src/pid_reader/formats/pdf_source.py`, `formats/ocr_source.py`, `engineering/standalone_read.py`.
- Pipeline orchestration: `engineering/pipeline.py::analyze_drawing` with stage telemetry and explicit failure.
- Geometry: `engineering/linework.py`, `topology.py`, `drawing_graph.py`, `raster_geometry.py`, `raster_outlines.py`, `raster_network.py`, `raster_centrelines.py`.
- Symbols/profiles: `engineering/symbols.py`, `symbol_catalog.py`, `examples.py`, `example_matching.py`, `tag_profiles.py`, `text_links.py`.
- Interpretation: `sheet_fields.py`, `checks.py`, `signal_links.py`, `signal_paths.py`, `connectivity.py`, `project_links.py`, `revisions.py`.
- Persistence: `engineering/project.py::ProjectStore`, `migrations.py::upgrade`, findings/reviews in `findings.py`.
- Exports: `graph_export.py::canonical_graph`, `drawing_export.py`, `reports.py`, `xlsx_export.py`, `dexpi.py`.
- Isolation/UI/API: `engineering/isolation.py`, `api.py`, `worker.py`, `ui/viewer.py`, `ui/main_window.py`, `ui/tabs.py`, `ui/graphview.py`.
- See `requirements/SOURCE_MODULE_MAP.csv` for verified top-level symbols and line numbers; reverify against actual worktree before changes.

Do not expose direct SQL as a public SDK. Create a `standalone_intelligence` (or similarly named) versioned Python interface distinct from the original frozen `api.read_pid`. Plan adapters as extensions so other software uses validated JSON and typed public functions, not DB internals.

## 5. Development execution: vertical slices with real tests

Use the sequence in `07_WORK_PACKAGES.md`; implement each WP as working production code and automated tests, not only narrative. For EVERY WP:

1. Identify owner Q IDs, baseline issue IDs and implementation files. Write a tiny test of the CURRENT failure before patching (e.g. S025 `word_count:0` must yield `OCR_NOT_RUN|OCR_FAILED|TEXT_NOT_FOUND` diagnostic and `INCOMPLETE` rather than silent success).
2. Implement deterministic, bounded improvement, preserve original R1 behavior. Verify synthetic positive, negative, rotated, dense, corrupted and hostile cases; test that outputs are stable across reruns and cancel-safe.
3. Integrate result with real `pipeline.py`, `project.py` or additive DB tables, `findings.py`, GUI overlay and export, where meaningful. A helper-only module uncalled by the app does not count as delivered.
4. Rerun targeted + full pytest, original R1 checker and relevant preflight, compare source ZIP/file hashes, and use `pytest -q` terminal output, not invented claims. Never change frozen gold labels for convenience.
5. Record version pin, licence/SPDX, Windows wheels, model SHA and offline placement if dependencies changed. Build a reproducible release candidate when applicable. Record exact run environments.
6. Update `WORKLOG.md`, `REQUIREMENTS_TRACEABILITY.csv`, `CHANGELOG.md`, ADR, `TEST_RESULTS/`, `OPEN_ISSUES.md`. Preserve failures and unfinished work in traceability.
7. Commit incremental local Git changes on a non-protected branch where permitted, with no secrets/uncleared drawing content. Do not push to inaccessible remote or overwrite newer local repo.

**Key early focus:** diagnose S025 OCR zero, document segmentation, adaptive OCR, original-geometry valve recognition, structured lines, dense tiling. But finish all approved WPs; do not stop after only these priorities.

## 6. Explicit acceptance against Q51-Q100

Maintain `requirements/APPROVED_REQUIREMENTS_Q1_Q100.csv`, add per-Q implementation evidence and tests in live repo, and keep the frozen original Q1-Q50 register intact. A user design decision is `APPROVED`; implementation state independently `NOT_STARTED`, `IN_PROGRESS`, `IMPLEMENTED`, `TESTED`, `BLOCKED`, `FAILED`, or `NOT_RUN`. Never report an approved requirement as complete simply because its specification exists.

No generic 'model understands P&IDs' claim. On supported test classes identify: text extraction including vector outlines, valves/equipment/instruments, line sizes/tags, nozzle/port semantics, real topology, loops, revisions, cross-sheet references, metadata/notes/tables, full source evidence and AI package output. Show measured per-class precision/recall and errors for supported style/format; do not hide unsupported classes or scanned failures in averages. Metrics need frozen annotated gold, recorded denominators and an untouched final split. Q20 older target thresholds (e.g. critical symbols precision >=98%, recall >=95%; critical connection precision >=99%, recall >=95%; critical silent misses <=1%) are **targets**, not achieved baseline. Extend/stratify defensibly, never weaken silently.

## 7. External rights and risks

- PyMuPDF is AGPL/commercial: **not a default replacement** for the permissively distributed pypdfium2/pdfplumber stack. Screen alternatives by transitive licence and legally usable wheels/models.
- Current RapidOCR legacy Python package works in the baseline, while upstream RapidOCR now recommends unified `rapidocr`. **Do not change in place without comparative tests, pinned wheel/model hashes, backward-compatible outputs, rollback and licensing audit.** No model weight or CAD library downloads without verifying licence and permitted source.
- DEXPI 2.0.1 (30 Sep 2026) is the current recommended DEXPI specification for an independent export adapter. 'DEXPI-compatible' requires a real, schema-validated artifact and honest attribute mapping.
- ISA5.1-2024 and ISO10628-1:2014 are reference standards, not authorised bundled source material. ISA explicitly restricts AI entry of ISA IP. Do not paste/copy their copyrighted content into Claude prompts or model datasets. Make original/human-authorised drawings and freely usable public descriptions the basis for engineering taxonomy.

## 8. Exact deliverables, not just advice

Deliver a runnable upgraded tree/branch and one owner-review ZIP with:
- full changed/new merge-ready code and tests; original frozen contract unmodified;
- reproducible Windows build/installer or truthful `NOT_RUN` build instructions; source archive / branch reference and SHA manifest;
- additive SQLite migrations with rollback/restore evidence; public standalone API+JSON schema/examples, typed graph and AI consumer prompt;
- actual equipment/line/instrument/valve/loop/metadata/connection/revision exports for synthetic fixtures and cleared source examples;
- quality/stage coverage plus unknowns, alternatives, reviewed and evidence-backed narrative examples;
- independent gold annotation tool/guide and full benchmark scorer with metrics + denominators; untouched held-out results only when independently run;
- old and new release regression tests, R1 checker, Windows resource isolation tests, offscreen GUI, installer and real host COPY results with exact NOT_RUN statuses;
- `SBOM`, THIRD_PARTY_NOTICES, model/source cards, licence review, source/fixture rights, security limits, runtime-memory/performance logs;
- requirements traceability for Q1-Q100 and all frozen PR-*; `WORKLOG`, ADRs, open issues, known limits, rollbacks and final owner acceptance checklist.

Do not claim finished if it is only a prototype, model suggestion or tests of helper functions. A blocked licensed CAD, real host, independent review or Windows build does not justify fabricating success; deliver working independently testable features and a precise blocker.

## 9. Continuation after context limits

If Claude's conversation/session is nearing capacity, write `HANDOFF_STATE.md` with current Git HEAD, exact completed WPs and tests, blockers, current next action, latest diff, files changed, artifact locations, owner approvals and security constraints, then use `17_CONTINUATION_PROMPT.md` in a new session. Do not invent work happening while agent session is closed.

**Start now: inspect the baseline, verify hashes, run baseline tests, create a branch and requirement matrix, then implement WPU-00 onward until all approved scope is complete or honestly blocked.**
