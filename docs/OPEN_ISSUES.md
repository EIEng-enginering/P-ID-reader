# Open issues — cumulative development slice 0.4.0-dev0 (Rev J)

| ID | Severity | Issue / current status | Next action |
|---|---|---|---|
| G-001 | P0 | Host `--output` versus R1 scratch cleanup semantics unresolved; worker is not a final R1 drop-in. | Test actual Worksheet worker invocation and clean staging/cleanup. |
| G-002 | P0 | Basic outline and constrained six-stroke bow-tie valve-geometry proposals exist in Rev J, but verified ports, instrument loops and engineering connectivity remain unimplemented. | Add native shape recognition, port matching and independent annotated fixtures. |
| G-003 | P0 | Raster host extraction refused; OCR preview is standalone and not integrated into R1. | Offline model packaging/permissions and separate host acceptance. |
| G-004 | P0 | No independent real P&ID accuracy benchmark. | >=120 synthetic/cleared drawings; held-out final sample and independent review. |
| G-005 | P0 | PySide6 viewer including new geometry-review UI not tested on Windows. | Clean Windows Python 3.12 tests at multiple DPI scales. |
| G-006 | P0 | Worker lacks enforced operating-system memory/process limits. | Windows job object/watchdog and hostile-input testing. |
| G-007 | P0 | No pinned dependency wheel hashes or redistribution assessment. | Reproducible wheel/model packaging and legal review. |
| G-008 | P1 | Standalone additive schema v2 upgrade and pre-upgrade backup implemented; Linux tests pass. | Windows migration and recovery qualification. |
| G-009 | P1 | Rev H geometry distinguishes crossing/T/touch/overlap but cannot determine if strokes are pipe, drawing borders or instrument signals. | Context and symbol/legend association. |
| G-010 | P1 | Tag parsing is rule-based and may have project false positives. | Versioned tag profiles and ambiguity fixtures. |
| G-011 | P1 | No releasable wheel hashes/models/manifest. | Produce actual release evidence, licences and model cards. |
| G-012 | P1 | No validated DEXPI interchange. | Implement separate DEXPI adapter and schema/semantic tests. |
| G-013 | P1 | Standalone OCR preview now provides normalized bounding boxes, source hash, model version and reproducible IDs; calibrated accuracy, packaged model and formal host integration remain unimplemented. | Add source-linked OCR observations with held-out tests. |
| G-014 | P1 | Physical entity matching across drawing revisions not implemented; geometry is source-backed only. | Persistent reviewed entity association model. |
| H-001 | P1 | Vector geometry spatial index currently refuses pathological density rather than providing large-project segmentation. | Benchmark safe tiling and chunking with explicit completeness guarantees. |
| H-002 | P1 | Proposed endpoint tolerance and near-circle classifications not independently calibrated. | Gold-standard per-class measurement; no automatic acceptance. |
| H-003 | P2 | GUI geometry-review workflow remains untested and currently requires a separate import run rather than project navigation. | Test on Windows, then implement persisted project navigation and zoom-to-evidence. |

Gates G4–G7 in Worksheet R1 remain NOT_RUN.

| I-001 | P1 | Rev I recognises only unverified circular/rectangular outline candidates with centred native-text tags; no P&ID-specific valve bowtie recognition or packaged symbol ML model. | Add safe symbol-template matching and isolated class-specific benchmark fixtures. |
| I-002 | P1 | Port proposals are endpoint-near-outline geometry, not confirmed nozzles, instrument taps or line connections. | Add typed connection ports and explicit route/line-style classification with independent annotation. |
| I-003 | P1 | Standalone SQLite schema v3 upgrade verified on Linux only; original host migrations unchanged. | Test upgrades/backups and crash consistency on real Windows. |
| I-004 | P1 | OCR word boxes are normalized to PDFium rendered pages, but orientation and source transform fidelity across cropped/rotated PDFs need specific benchmarks. | Add rotated/cropped image coordinate fixtures and model/version package lock. |
| I-005 | P1 | The new GUI symbol panel is not run/tested under Windows; selection/zoom performance and desktop packaging remain unverified. | Perform real PySide6 + DPI screenshot and keyboard tests on Windows. |
| I-006 | P1 | Neither trained specialized symbol model nor complete automatic OCR pipeline is implemented. No training needed for current preview. | Continue pretrained-offline model comparison and fit controlled symbol/port rules before optional fine-tuning. |

## Rev J issues and scope of new code

| ID | Severity | Issue / current status | Next action |
|---|---|---|---|
| J-001 | P1 | Bow-tie detector requires six specific vector strokes, complete rails and synthetic calibration. Real P&IDs use filled symbols, broken polylines and varying legends. | Benchmark against independently annotated vendor/project styles; implement more templates cautiously. |
| J-002 | P1 | Dashed strokes are only signal-style candidates; solid strokes remain unclassified. Neither is proven process piping. | Add project legend profiles and source-linked verified instrument/line evidence. |
| J-003 | P1 | Read-only graph follows human decisions about geometry AS DRAWN; it cannot traverse a valve or assert equipment/plant connectivity. | Introduce separately reviewed port-to-line and equipment identity relationships. |
| J-004 | P1 | New GUI linework panel is source code only, not visually QA-tested on Windows; PySide6 is unavailable in this Linux test runtime. | Test on Windows Python 3.12 at multiple DPI scales. |
| J-005 | P1 | Valve geometry tolerance is normalized and not independently calibrated on cropped/rotated/large-format PDFs. | Create gold fixtures with pages of different sizes and orientations; measure precision/recall. |
| J-006 | P1 | Current trace limit is 80 hops; hard limits may decline large graph queries rather than segmenting them. | Add scalable indexed graph expansion and project-level pagination. |

Original Worksheet R1 worker and host G4-G7 remain unchanged and NOT_RUN.

## Rev K issues and scope of new code

| ID | Severity | Issue / current status | Next action |
|---|---|---|---|
| K-001 | P1 | Offline OCR words now persist in standalone schema v5; unchanged R1 worker continues refusing raster-only pages. | Perform separate host contract amendment only if user authorises; do not modify frozen R1. |
| K-002 | P1 | OCR/native tag associations use centre-in-outline geometry and a constrained tag pattern. Leader-line labels, rotated/cropped PDF annotations and vendor tag conventions are not qualified. | Add verified rotation/crop fixtures and project-specific tag profiles, benchmark false associations. |
| K-003 | P1 | OCR confidence is raw Tesseract output, not calibrated reliability; split word grouping uses a bounded, conservative distance rule. | Measure actual recognition on independent cleared drawings before any auto-suggestion thresholds. |
| K-004 | P1 | Standalone source-linked evidence includes proposed outline port touches but DOES NOT create physical line, signal or instrument loops. | Add typed, individually reviewed port-to-line and signal relations with negative crossing cases. |
| K-005 | P1 | New GUI OCR/tag review code compiles but was not run under PySide6/Windows and does not start heavy OCR synchronously. | Test Windows Python 3.12, DPI scaling, responsiveness, keyboard and review state. |
| K-006 | P1 | Existing host worker output/workdir and operating-system memory limits remain unresolved. | Test exact Worksheet invocation and cancellation before any live integration. |

**G4–G7 host integration, Windows GUI, and independent engineering benchmarking remain NOT_RUN.**

## Rev L additions and open issues

| ID | Severity | Status / issue | Next step |
|---|---|---|---|
| L-001 | P1 | Signal-to-bubble proposals depend on dashed native strokes ending at a simple vector instrument circle. They are not control-loop verification. | Add typed signal-route candidates and independently labelled crossing/line-style fixtures. |
| L-002 | P1 | Site tag profile is deterministic and avoids regex injection but cannot infer the client's real naming rules automatically. | Add editable project profile manager and versioned legend evidence. |
| L-003 | P1 | OCR v3 maps standard CropBox/MediaBox offsets and 0/90/180/270 rotation; exotic PDF coordinate/transformation cases not independently benchmarked. | Expand renderer parity corpus, OCR ground truth and display alignment tests. |
| L-004 | P1 | Standalone SQLite v6 migrations tested on Linux only; sample projects migrated, pre-upgrade backups preserved by user workflow. | Test Windows SQLite crash recovery and backup/restore. |
| L-005 | P0 | Windows GUI and real Worksheet host R1 integration G4-G7 still NOT_RUN; the host worker is not a released module. | Run exact host installation and user-visible DPI tests when available. |
| L-006 | P0 | No independent P&ID recognition benchmarks, real drawing gold set, or validated DEXPI model. | Establish predeclared metrics, independent reviewer and lawful source corpus. |

## Rev M additions and remaining limitations

| ID | Priority | Issue | Next action |
|---|---|---|---|
| M-001 | P1 | Signal-path graph is a limited dashed *stroke* graph; reviewer decisions are about source ink, not instrument function, loop correctness or operating plant. | Add typed reviewed signal services and geometry-independent evidence in a future stage; never auto-credit safety function. |
| M-002 | P1 | Cross-sheet matching uses explicitly *manual* connector region annotations; equivalent text might be incorrect, duplicated, ambiguous or refer to another document revision. | Develop optional arrow/text extraction to propose annotation coordinates and independent verified labels; retain human review gates. |
| M-003 | P1 | Current Qt project catalogue tab has not run on Windows (PySide6 unavailable in Linux test environment). | Run real Windows Python 3.12, PySide6 6.12, DPI, keyboard, provenance and multi-PDF test. |
| M-004 | P1 | Standalone SQLite v7, hash-chain auditing and real v6 upgrade pass Linux tests, but large collection performance and crash recovery are not independently measured. | Stress-test 500+ source revisions, duplicate annotations and backup/recovery on Windows. |
| M-005 | P0 | Actual Worksheet host integration G4–G7, real engineering recognition accuracy and full plant-wide graph remain NOT_RUN / NOT_IMPLEMENTED. | Keep no-claim safety boundaries; conduct controlled host integration and independent benchmark before any production assertion. |

## Rev N remaining items

- Acquire and licence-check appropriate pretrained offline symbol detection model(s). Implement a separate bounded adapter and independently benchmark per object class and drawing style; no model is bundled in Rev N.
- Expand project-specific symbol template coverage and support additional geometric primitives; current templates are conservative and tested on synthetic drawings only.
- Validate on Windows/Python 3.12/PySide6 6.12.0 and actual client-cleared P&IDs.
- Complete real Worksheet R1 host tests G4-G7 without mutating host records automatically.

## Rev O batch / drawing-change limitations

| ID | Priority | Issue | Next action |
|---|---|---|---|
| O-001 | P0 | Standalone batch import currently processes PDF bytes in-process, not through a hardened memory/time-limited worker; hostile input safety is unqualified. | Implement isolated batch worker, per-job memory/CPU limits, termination/cleanup tests. |
| O-002 | P1 | Source-file manifest uses preflight hashing and read-back hashing; filesystem races and hostile directory contents have not been OS-verified. | Test on Windows, protect file descriptor identity and Windows ACL/symlink corner cases. |
| O-003 | P1 | Revision comparisons match only unique (object class, parsed tag). Tag renames, untagged objects, OCR ambiguity and changes of object class remain unresolved, never auto-merged. | Develop human-reviewed persistent asset equivalence with independent benchmark fixtures. |
| O-004 | P1 | Project search is backed by indexed observations and project metadata; large multi-project search speed and FTS remain unbenchmarked. | Benchmark 500+ drawings; add paged/FTS filters if justified. |
| O-005 | P1 | No automated designation of current revision or approved drawing. No automatic transfer of review acceptance. | Keep human-defined drawing set baselines; add explicit review workflow if required. |
| O-006 | P0 | Windows GUI, full field P&ID accuracy, real Worksheet R1 integration, model distribution and independent engineering gates remain NOT_RUN. | Continue Rev P/Q then execute tests on the target Windows system. |

## Rev P engineering workspace and reports

| ID | Priority | Limitation / next action |
|---|---|---|
| P-001 | P0 | Expanded PySide6 screens are source-compiled only; PySide6 unavailable in Linux QA. Exercise actual Windows Python 3.12/PySide6 6.12.0 GUI, keyboard, multiple DPI, source zoom, large table and failure handling. |
| P-002 | P1 | Current graph tab lists original source-proposed edges and reviewable cross-sheet links, not a full validated plant graph, routed drawing overlay or automatically confirmed instrument loops. Further graph topology qualification is required. |
| P-003 | P1 | Engineering reports are offline source-reading JSON/CSV/HTML. PDF/DOCX/XLSX/DEXPI report adapters, printable page-break QA, external archive/signature and independent assessment remain unfinished. |
| P-004 | P1 | Paged register retrieves 100 observations at a time but has not been stress-tested with hundreds of industrial drawing revisions. Benchmark SQL indexes, Qt responsiveness, file handles and memory before release. |
| P-005 | P0 | No qualified pretrained symbol recognition model, no independent real P&ID gold standard, no Windows installer and no live Worksheet host G4–G7. All remain NOT_RUN / NOT_IMPLEMENTED. |

## Rev Q — handoff and remaining release blockers

- **Q-001 P0:** Real Windows Python 3.12 / PySide6 6.12.0 GUI, DPI, installer, offline wheels and licence checks are NOT_RUN/NOT_IMPLEMENTED. Run the included Windows scripts and perform proper manual/screenshots QA.
- **Q-002 P0:** Genuine Worksheet host G4–G7, module.json/wheel/dependency licence register, R1 migrations and live audit/rollback integration NOT_RUN/NOT_IMPLEMENTED. The local R1-shaped worker is a development adapter only.
- **Q-003 P0:** Independent industrial drawing precision/recall/silent-miss benchmark and general pretrained symbol detector NOT_RUN/NOT_IMPLEMENTED. Synthetic passing tests are not engineering evidence of accuracy.
- **Q-004 P1:** Standalone batch PDF import remains in-process; real memory/CPU sandbox and cancellation/resume under hostile workloads are not qualified. Add external workers and OS-level bounds.
- **Q-005 P1:** Worker stages complete result in provided scratch and atomically publishes only output path, but host scratch must be cleaned by the host on forced kill; same-volume host output requirement must be rehearsed.
- **Q-006 P1:** Python editable install contamination can cause subprocess to import an earlier Rev I package. The new source-isolation preflight protects QA; continue strict environment verification on Windows.
- **Q-007 P1:** Handoff file SHA manifest is integrity checking, not trusted code signing. Git remote write access, protected branches and credentials are not confirmed.
