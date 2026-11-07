# P&ID Reader — cumulative final ChatGPT development handoff Rev Q

**Authoritative current handoff:** `00_START_HERE_FOR_CLAUDE.md` and `docs/RELEASE_ACCEPTANCE_MATRIX.md`. The codebase version is `0.11.0-dev0`, standalone SQLite schema v9, original Worksheet extraction schema v1. All owner decisions Q1–Q50 Option A are approved. The release is **developer code, not yet a Windows or engineering-qualified application**. Rev Q local tests and contract validation are recorded under `TEST_RESULTS/LOCAL_DEV_R11/`.

**New in Rev Q:** atomic R1 worker result staging/publish, explicit output refusal, strict worker parameter validation, isolated-source release preflight, integrity-checked one-ZIP packaging and Windows check/launch scripts. No real host integration, general pretrained vision model, installer or independent field accuracy study was performed here.

## Historical development details (Rev G–P; some headings below refer to earlier snapshots)

# P&ID Engineering Reader — ChatGPT development codebase (Rev O)

**Development snapshot 0.9.0-dev0 — not an operationally validated P&ID reader.** This is REAL runnable software, not only a specification. It is an initial vertical slice for later continuation and single-ZIP transfer to Claude Code. **Source drawings are treated as unverified evidence.** No plant state, HAZOP, LOPA, SIL, QRA, regulatory compliance or engineering safety conclusion follows from this software.

## User-approved baseline

All 50 Option A decisions Q1–Q50 have standing development approval. The project must ultimately run as (1) a standalone Windows program and (2) a reusable Python module consumed by other software without direct database coupling. The frozen Worksheet R1 integration contract is unmodified under `contracts/PID_READER_MODULE_REQUIREMENTS_R1_UNMODIFIED.zip`.

Exact owner directory (do not rename):
`C:\Users\Admin\OneDrive - Enhance Integration Engineering\Company\006 Calculation Methods\26 P&ID reader`

Exact Git remote (do not rename):
`https://github.com/EIEng-enginering/P-ID-reader.git`

The repository was observed empty with read-only connector access; this snapshot has **not** been pushed or integrated with the live Worksheet application.

## Implemented in this snapshot

- GUI-free `pid_reader` package, Python library `read_pid(pdf_bytes, ReadParams(...))`, R1 reference canonical JSON/SHA-256/IDs, source validation and bounded page selection.
- PDF native text and vector stroke extraction using lazy imports; equipment/instrument-tag hypotheses, notes, geometric stroke observations, tentative stroke-to-stroke endpoint relationships with UNKNOWN type and UNKNOWN flow direction. No unsupported symbol-to-line connections are invented.
- R1 schema-v1 output with original evidence boxes and unreadable/unsupported regions. Scanned PDF pages are **visibly refused** by host `read_pid`; nothing is silently claimed to be read.
- Separate process worker `python -m pid_reader.worker`, defined exit codes and count-only JSON logs.
- Standalone geometry-only intersection analysis and named audited review (endpoint touches, possible T-branches, crossings, overlaps) through a separate contract. These are NOT confirmed process connections.
- Versioned standalone schema v7 migrations with consistent pre-upgrade backup and backup API.
- Standalone SQLite project database: immutable source revision, embedded source PDF bytes (when supplied), extraction snapshots, candidate observations, graph edges, named human decisions, append-only records, audit hash chain and source/evidence retrieval.
- Standalone CLI for creating a project, importing vector PDFs, listing/searching, reviewing, inspecting connections and exporting R1 JSON.
- Optional native DXF **observation preview** adapter (does not infer engineering relationships).
- Optional local Tesseract **OCR preview** adapter (not part of R1 host extraction; depends on separately installed traineddata/software).
- Preliminary PySide6 viewer, separate geometry candidate review and manual decision window. This GUI code is **not tested on Windows** and requires PySide6 and PDFium to run.
- Synthetic vector and raster PDF fixtures, a synthetic SQLite demonstration project, and automated tests.


## New in Rev O (latest increment)

- **Bounded, resumable standalone PDF batches**, source SHA-256 preflight manifest, per-file immutable outcome records, and source-change refusal on resume. Failed documents do not corrupt successful imports or become silent successes. This is not the final hardened Worksheet worker.
- **Conservative engineering drawing comparison**: stable unique class/tag readings, added/removed/moved/changed differences, repeated-tag ambiguity, and explicit unmatched observations. It never asserts latest approved revisions, as-built assets, or installed plant modifications.
- **Project-wide observation search** with exact source metadata, selected drawing registration and latest *reading-level* review status. Source text remains separate from interpretation.
- **SQLite standalone schema v9** with append-only batch/revision snapshots, migration backups and hash-chain audit. Original R1 contract, host schema and worker unchanged.
- **CLI**: `batch-import`, `batch-resume`, `batch-status`, `compare-revisions`, `revision-comparison`, `project-search`.
- Generated synthetic Rev O drawing pair and real CLI demo are in `fixtures/` and `TEST_RESULTS/LOCAL_DEV_R09/`.
- **146 local tests passed**, **16 original R1 checker tests passed**, and fresh extraction **0 violations**. No industrial recognition benchmark or Windows GUI qualification has been performed.

See `docs/REV_O_IMPLEMENTATION_NOTES.md` for the exact test and safety scope. Rev P is the next development package.

## New in Rev N (current coding increment)

- **Training-free vector symbol catalogue** (`engineering/symbol_catalog.py`): a *strictly declarative*, project-versioned library of graphical and tag-grounded templates, 11 synthetic starter patterns, and deterministic source-linked candidate interpretations. Supported classes include tagged instrument circles, pump circles, tagged equipment rectangles, six-stroke valve glyphs, and a **valve with a separately observed stem and untagged circle**. This is not a general trained visual recogniser or certified engineering classification.
- The stemmed-valve test requires a specific coherent combination of two independent graphical features and a solid shaft. An ordinary bow-tie, nearby unrelated instrument bubble, dashed line, or ordinary pipe crossing is insufficient. Unknown/unmatched patterns remain unclassified.
- Standalone SQLite schema **v8**: immutable catalogue registrations, source-specific analysis snapshots, append-only named decisions and pre-upgrade backups. Existing source/geometry/symbol/linework records remain unchanged.
- New CLI commands: `register-symbol-catalogue`, `get-symbol-catalogue`, `analyze-symbol-catalogue`, `catalogue-candidates`, and `review-catalogue`. JSON Schemas define both the catalogue and analysis outputs.
- A new synthetic P&ID fixture demonstrates controlled recognition and negative cases. **132 local tests pass**, original **16 R1 tests pass**, and the new R1 extraction has **zero checker violations**. Results are NOT general industrial accuracy measurements.
- **No new pretrained model is bundled or run.** A lawful, already-trained detector remains a later optional adapter, dependent on licences/model availability and separate benchmarks. No user training is required to use the implemented template recognition.

Quick start (PowerShell or shell, project-relative):

```powershell
python -m pid_reader.cli register-symbol-catalogue project.sqlite
python -m pid_reader.cli get-symbol-catalogue project.sqlite <catalogue_id>
python -m pid_reader.cli analyze-symbol-catalogue project.sqlite <extraction_id> <geometry_analysis_id> <symbol_analysis_id> <linework_analysis_id> <catalogue_id>
python -m pid_reader.cli catalogue-candidates project.sqlite <analysis_id>
python -m pid_reader.cli review-catalogue project.sqlite <candidate_id> --actor Engineer --decision UNRESOLVED --reason "Check project drawing legend"
```

All previous commands and design approvals remain in effect.

## New in Rev M (current coding increment)

- `engineering/signal_paths.py` can trace dashed vector strokes across **named-reviewer-confirmed drawing contacts**, and show source-linked instrument-outline endpoints that have separately received an `SUPPORTED_AS_DRAWN` reading decision. Review-free mode excludes speculative joins; an explicit `--include-unreviewed` mode displays proposed joins with caution. No actual instrument loop is inferred.
- `engineering/project_links.py` matches **manually annotated** off-page labels across *explicitly selected* drawing source revisions. A source hash, immutable selected drawing register snapshot and the underlying annotation region are captured. Label matches remain unreviewed until a named human records `LINKED_AS_DRAWN` or an alternative decision. Revised metadata cannot retroactively rewrite previous analysis snapshots.
- New standalone SQLite schema **v7** stores versioned drawing registrations, source-linked off-page annotations, candidate matches, append-only cross-sheet decisions and saved signal-trace snapshots. Includes pre-migration backups, actual v6 fixture migration testing and audit verification. No host migration is modified.
- The draft PySide6 UI now has a project-drawing navigator and manual drawing registration controls (source code compiles; PySide6 runtime/Windows GUI tests NOT_RUN).
- CLI commands include `trace-signal`, `signal-trace-snapshot`, `register-drawing`, `drawings`, `annotate-offpage`, `offpage-annotations`, `analyze-crosssheet`, `crosssheet-candidates`, `review-crosssheet`, and `trace-drawings`.
- Synthetic instrument signal and cross-sheet source fixtures, JSON Schemas, standalone SQLite demo projects and **115 local passing tests**. Original R1 checker: **16 passing tests**, fresh R1 extraction: **0 violations**. Source R1 contract ZIP is byte-for-byte unchanged.

Example independent *standalone* project queries:

```powershell
python -m pid_reader.cli drawings project.sqlite --search PID-100
python -m pid_reader.cli trace-signal project.sqlite <signal_analysis_id> <dashed_segment_id> --persist
python -m pid_reader.cli register-drawing project.sqlite <extraction_id> --drawing-no PID-100 --revision B --facility Plant --area Unit100 --actor Engineer --reason "Source catalogue entry"
python -m pid_reader.cli annotate-offpage project.sqlite <extraction_id> --page 1 --bbox-json box.json --label "TO LINE 20" --actor Engineer --reason "Manual source annotation"
python -m pid_reader.cli analyze-crosssheet project.sqlite <extraction_id_A> <extraction_id_B>
python -m pid_reader.cli crosssheet-candidates project.sqlite <crosssheet_analysis_id>
python -m pid_reader.cli review-crosssheet project.sqlite <candidate_id> --actor Engineer --decision LINKED_AS_DRAWN --reason "Matching drawn connector labels"
python -m pid_reader.cli trace-drawings project.sqlite <crosssheet_analysis_id> <extraction_id_A>
```

The analysis never automatically designates a latest or approved drawing revision, confirms installed plant routing, establishes an instrument loop or changes Worksheet/HAZOP/LOPA/QRA results. See `docs/REV_M_IMPLEMENTATION_NOTES.md`.

## Previous increment — Rev L (retained)

- Added `engineering/signal_links.py`: independent, deterministic **signal-style endpoint-to-instrument-outline candidates** from a dashed vector stroke ending on a detected instrument circle. A dashed line *crossing through* an instrument is not a connection. All candidates remain unreviewed until a named human records a drawing-level decision. No actual signal function, process line, instrument loop or IPL independence is claimed.
- Added `engineering/tag_profiles.py`: **training-free**, versioned project tag-convention parsing using bounded, declarative prefix/class maps, allowed separators and digit/suffix limits. Interpretations retain all alternative class hypotheses; unknown and conflicting interpretations are not discarded. User-provided regular expressions and code are not executed.
- Added `formats/page_coordinates.py` and updated standalone offline `ocr_pdf_preview()` to the independently versioned **v3** result. Cropped and rotated pages now map rendered PDFium OCR coordinates to pdfplumber's top-left normalized **MediaBox** coordinates. Every page includes its render transformation; standalone storage compares it to the exact embedded source PDF and rejects older OCR-v2 previews on cropped pages. Worksheet R1 `read_pid` and worker are unchanged.
- Added **standalone SQLite schema v6** with immutable signal-analysis proposals, append-only named signal reviews, immutable tag profiles and repeatable profile interpretations, plus pre-upgrade backup/audit rules. Earlier schema v1-v5 databases migrate with a backup.
- Added CLI `analyze-signals`, `signal-candidates`, `review-signal`, `register-tag-profile`, `get-tag-profile`, `evaluate-tag-profile`, plus two separate JSON Schemas, a positive/negative synthetic signal drawing and four cropped/rotated PDF fixtures. All verification remains Linux development qualification, not Windows or independent engineering acceptance.
- **95/95 local software tests passed**, **16/16 original R1 checker tests passed**, **zero R1 schema checker violations** for the new vector fixture. Original R1 archive SHA-256 unchanged. Windows GUI, general instrument recognition and independently measured drawing accuracy remain NOT_RUN.

Example sequence after `import-pdf`, `analyze-topology`, `analyze-symbols`, and `analyze-linework`:

```powershell
python -m pid_reader.cli analyze-signals project.sqlite <extraction_id> <geometry_analysis_id> <symbol_analysis_id> <linework_analysis_id>
python -m pid_reader.cli signal-candidates project.sqlite <signal_analysis_id>
python -m pid_reader.cli review-signal project.sqlite <signal_candidate_id> --actor Engineer --decision UNRESOLVED --reason "Check drawing legend"
python -m pid_reader.cli register-tag-profile project.sqlite path\to\tag_profile.json
python -m pid_reader.cli evaluate-tag-profile project.sqlite <text_link_analysis_id> <tag_profile_id>
```

The sample profile can be produced from Python with `pid_reader.engineering.tag_profiles.example_profile()`. Custom tags are proposed interpretations, never accepted instrument functions.

## Previous increment - Rev K (retained)

- Added `engineering/text_links.py`, a **separate source-hash-bound OCR/native-text association engine**. Every near-outline tag reading is a reviewable hypothesis, with exact PDF/OCR IDs, normalized coordinates, ambiguity and unparsed OCR fragments retained. Matching OCR and native sources are shown together without an invented accuracy score; split words can be combined conservatively without promoting fragments to accepted tags.
- Added **standalone SQLite schema v5** (`ocr_analysis`, `ocr_word`, `text_link_analysis`, `text_link_proposal`, `text_link_decision`) with immutable source observations, reproducible hash validation, named append-only review decisions, pre-upgrade backup and audit-chain verification. Original Worksheet R1 schema and worker remain byte-for-byte unchanged.
- Added CLI `import-ocr`, `ocr-words`, `analyze-text-links`, `text-link-candidates`, `review-text-link` and `symbol-evidence`. The latter returns source-backed symbol/tag alternatives and possible outline port touches without asserting physical plant connectivity.
- Draft PySide6 window displays **saved OCR/tag link proposals** with source-region highlighting, reviewer selection and corrections. It intentionally does not synchronously OCR documents on the GUI thread; no Windows/PySide6 runtime test has been performed.
- Added standalone text-link JSON Schema, synthetic P&ID/annotation/result fixtures, schema-v5 example database and **15 new tests**. The local suite now contains **74 passing tests**, the original R1 checker remains **16 passing tests**, and the R1 extraction checker reports **0 violations**. All testing is on Linux Python 3.13, not a Windows or independent engineering acceptance.

Example standalone usage after `import-pdf`, `analyze-topology`, `analyze-symbols`:

```powershell
python -m pid_reader.cli import-ocr project.sqlite <extraction_id>
python -m pid_reader.cli ocr-words project.sqlite <ocr_analysis_id> --text PT
python -m pid_reader.cli analyze-text-links project.sqlite <extraction_id> <symbol_analysis_id> <ocr_analysis_id>
python -m pid_reader.cli text-link-candidates project.sqlite <text_link_analysis_id>
python -m pid_reader.cli symbol-evidence project.sqlite <text_link_analysis_id> <symbol_candidate_id>
python -m pid_reader.cli review-text-link project.sqlite <proposal_id> --actor Engineer --decision UNRESOLVED --reason "Check source drawing"
```

The optional offline OCR requires a locally installed Tesseract executable and language data; no training is required. For reproducible test data only, `import-ocr ... --ocr-json fixtures\synthetic_ocr_annotations_unreviewed.json` accepts a hashed synthetic proposal matching that fixture PDF. Do not describe those synthetic words as actual model-recognition performance.

## Previous increment — Rev J (retained)

- Added separate `engineering/linework.py`: deterministic six-vector-stroke bow-tie **valve-shaped geometry hypotheses** in horizontal/vertical orientations, supported inline *possible* connection points, and dashed **signal-style candidates** (not confirmed instrument signals). An ordinary X without two complete side rails is never classified as a valve by this template.
- Added explicit `mixed_style_contacts` for unresolved intersections between differently styled/detected linework. Valve glyph outline strokes are excluded from path traversal; no physical plant connection is created.
- Added `engineering/drawing_graph.py`, a **read-only drawing-ink graph**. Default tracing follows only contacts a named human marked `CONNECTED_AS_DRAWN`; optional mode includes unresolved candidate contacts and labels them distinctly. Rejected/not-connected relationships never become traversable. The graph does not automatically cross a drawn valve.
- Added standalone SQLite **schema v4** and migration with pre-upgrade backup. New immutable tables `linework_analysis`, `linework_candidate` and `linework_decision`, with audit-chain review events and source-replay validation. Original Worksheet R1 tables and schema remain unchanged.
- Added CLI `analyze-linework`, `linework-candidates`, `review-linework`, `trace-drawing` and a draft GUI **Valve / line styles** panel. The GUI is not tested on Windows (PySide6 unavailable in this Linux environment).
- Added the independent standalone JSON schema `contracts/standalone_linework_v1.schema.json`, tests and PDF fixture `fixtures/synthetic_valves_line_styles.pdf`, plus a schema-v4 sample SQLite database.
- **59 local software tests passed in Rev J** in Linux Python 3.13.5, **16 original R1 checker tests pass**, and the new synthetic R1 extraction has **zero checker violations**. These are development and contract checks, not real P&ID engineering recognition accuracy. Host G4–G7, real Windows/Python 3.12 and independent 120-drawing benchmark remain NOT_RUN.

To try on a local project after the `analyze-topology` and `analyze-symbols` stages:

```powershell
python -m pid_reader.cli analyze-linework project.sqlite <extraction_id> <geometry_analysis_id> <symbol_analysis_id> --output-json linework.json
python -m pid_reader.cli linework-candidates project.sqlite <linework_analysis_id>
python -m pid_reader.cli review-linework project.sqlite <candidate_id> --actor Engineer --decision UNRESOLVED --reason "Check drawing legend"
python -m pid_reader.cli trace-drawing project.sqlite <linework_analysis_id> <stroke_id> --max-hops 12
python -m pid_reader.cli trace-drawing project.sqlite <linework_analysis_id> <stroke_id> --include-unreviewed
```

**Important:** `trace-drawing` is a graph of *drawn strokes*, not verified piping/instrument connectivity, process service or actual plant construction.

## Previous increment — Rev I (retained)

- Added a separate, deterministic standalone symbol-proposal analysis (`engineering/symbols.py`) for **near-circular instrument-bubble candidates**, **rectangular equipment-outline candidates**, **multiple-tag ambiguity**, and **unclassified/unknown outlines**. Classification is deliberately limited to clear centre-overlap evidence and known tag syntax; it is NOT a general valve/instrument model or a validation of plant function.
- Added conservative **possible outline port contact observations** based on solid vector line endpoints near a detected outline. A contact is not accepted piping, signal connectivity, a verified nozzle, or plant topology.
- Extended the separate standalone topology layer with generic `RECTANGULAR_OUTLINE` observations, under a backward-compatible addition to the standalone topology-v1 schema. The Worksheet R1 schema is unchanged.
- Added **standalone SQLite schema v3** for immutable symbol analysis snapshots, symbol candidates and append-only named review decisions; existing v1/v2 projects migrate with a consistent backup. Original extraction rows and hash chains remain immutable.
- Added CLI commands `analyze-symbols`, `symbol-candidates`, `review-symbol` and a preliminary (not Windows-tested) PySide6 **Symbol outlines** review tab.
- Improved optional Tesseract OCR preview with normalized word boxes, source SHA-256, deterministic candidate IDs, version metadata, hash validation, page/byte/pixel/time/output bounds and explicit unreviewed state. **OCR remains a standalone preview, not integrated into Worksheet R1.**
- Added synthetic drawings, standalone symbol JSON Schema, evidence-linked port/review tests, offline OCR integrity tests and a sample SQLite symbol project.
- **46 local tests passed on Linux**; the **16 original R1 checker tests passed**, and a freshly generated R1 extraction returned **0 schema/checker violations**. `contracts/PID_READER_MODULE_REQUIREMENTS_R1_UNMODIFIED.zip` matches the uploaded original byte-for-byte.

To inspect the new feature from the root folder:

```powershell
python -m pid_reader.cli import-pdf project.sqlite fixtures\synthetic_symbols_ports.pdf
python -m pid_reader.cli analyze-topology project.sqlite <extraction_id>
python -m pid_reader.cli analyze-symbols project.sqlite <extraction_id> <geometry_analysis_id> --output-json proposals.json
python -m pid_reader.cli symbol-candidates project.sqlite <symbol_analysis_id>
python -m pid_reader.cli review-symbol project.sqlite <candidate_id> --actor Engineer --decision UNRESOLVED --reason "Needs a checked drawing legend"
```

The IDs are obtained from the preceding CLI result or from the project database. To try the draft desktop view, install the optional GUI dependencies and use `python -m pid_reader.cli gui project.sqlite` on a supported computer; real-Windows acceptance remains NOT_RUN.

## Verified test evidence

At the Rev I snapshot, 46 local Python tests passed using Python 3.13 on Linux. The independent, original R1 contract-checker suite ran 16 tests successfully. The generated `fixtures/synthetic_extraction_r1.json` passes `tools/check_extraction.py` and the original R1 JSON Schema with **zero violations**. The vector test drawing was rendered and visually inspected.

**Not performed:** Clean Python 3.12 Windows install, real PySide6 GUI tests, independent recognition benchmark, real engineering annotation, model licence/distribution review, Windows GUI DPI tests, and Worksheet host integration G4–G7. They remain NOT_RUN. The code is a candidate development implementation and must not be presented as an accepted R1 delivery.

## Development commands

From this project directory, using **Python 3.12** on Windows:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
python -m pytest -q
python -m pid_reader.cli init-project my_project.sqlite
python -m pid_reader.cli import-pdf my_project.sqlite fixtures\synthetic_pid_vector.pdf --output-json result.json
python tools\check_extraction.py result.json --schema contracts\worksheet_r1_schemas\pid_extraction.schema.json
python -m pid_reader.cli list my_project.sqlite --text V-101
```

Optional features, subject to locally available packages and licence checks:

```powershell
python -m pip install -e ".[dxf,ocr,gui]"
python -m pid_reader.cli inspect-dxf drawing.dxf --output-json dxf_preview.json
python -m pid_reader.cli ocr-preview scanned.pdf --output-json ocr_preview.json
python -m pid_reader.cli gui my_project.sqlite
```

The OCR preview requires the independently installed local Tesseract executable and trained language data; it does not download or train models. The GUI and all binary/library licensing, wheel-hash locking and offline installation remain release tasks. No dependency wheels have been packaged.

## Host worker invocation (development)

```powershell
python -m pid_reader.worker run --input fixtures\synthetic_pid_vector.pdf --params params.json --output extraction.json --workdir temp_workdir
```

`params.json` may be `{}`. The host must supply its exact source revision metadata and SHA-256 as appropriate. The development worker **does not yet claim full PR-B06/B07 compliance**: the R1 skeleton is ambiguous about a persistent `--output` result while deleting all files in its `--workdir`; this implementation leaves the host-nominated output intact and does not delete an arbitrary caller-provided work directory. Resolve and test that protocol against the actual host before integration.

## Still to build

Full advanced valve/instrument visual recognition, verified engineering ports, scanned OCR integration into the formal host pipeline (requires legally packaged models), title-block extraction, graph-based component-to-line attachment, cross-sheet matching, instrument-loop proposals, uncertainty calibration, drawing revisions, DEXPI exchange, full CAD import and engineering catalogue, scalable GUI/batch manager, portable installer/wheels, QA reference benchmark, and independently tested Worksheet R1 integration.

Do not label partially implemented capabilities as finished. The 50 approved decisions authorize development, **not** purchases, licence bypasses, cloud uploads, unreviewed safety conclusions, live-host changes or independent validation claims.

## New Rev H topology commands

See `docs/REV_H_IMPLEMENTATION_NOTES.md` for tested commands, a new PDF fixture, limitations, audit/review rules and the strict distinction between graphical contact and physical plant connectivity.

## Cumulative coding and eventual Claude handoff

Development continues in this ChatGPT conversation with reversible implementation authority. This project is supplied as one cumulative source folder, not a collection of patches. When ready, hand the entire ZIP to Claude Code and direct it to `CLAUDE.md`. The primary approved autonomous build prompt is also readable directly at `docs/CLAUDE_MASTER_PROMPT_AUTONOMOUS_REV_F.md`. No Git push or final engineering acceptance is implied.

## Rev P — engineering workspace and reporting development

Version `0.10.0-dev0`, standalone database schema **v9 (unchanged)**. The new `engineering/workspace.py` exposes paged, source-linked engineering registers and proposal-only drawing/cross-sheet graph views. `engineering/reports.py` creates deterministic, SHA-256-protected **JSON, CSV or HTML** drawing-reading reports, preserving exact source hashes and review status. CSV formula injection and HTML source-text injection are mitigated; reports refuse silent truncation and compromised audit histories.

```powershell
python -m pid_reader.cli register-page my_project.sqlite --text P-101 --limit 100 --offset 0
python -m pid_reader.cli graph-view my_project.sqlite --limit 100
python -m pid_reader.cli crosssheet-view my_project.sqlite
python -m pid_reader.cli report-export my_project.sqlite readings.html --format html
python -m pid_reader.cli report-export my_project.sqlite readings.csv --format csv
python -m pid_reader.cli report-export my_project.sqlite readings.json --format json
```

The optional PySide6 desktop source now contains a paged engineering-register tab, evidence zoom, graph proposal list, two-revision comparison and local report export. **These screens have NOT been run on Windows**; only source compilation and Qt-free core/CLI testing were performed on Linux. For precise evidence see `docs/REV_P_IMPLEMENTATION_NOTES.md` and `TEST_RESULTS/LOCAL_DEV_R10`. Current tests: **157 local pytest cases**, **16 original R1 tests**, **0 R1 violations**. Remaining R1 host, Windows GUI and independent engineering acceptance gates remain NOT_RUN.
