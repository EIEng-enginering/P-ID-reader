# R5 program update - status (read this first)

Package: `PID_READER_CLAUDE_PROGRAM_UPDATE_R5_COMPLETE.zip` (outer manifest and the nested R5 research archive verified, 5,260 files, sha256 `0934d71e...ceef04`).
Owner authority used: the package's instruction precedence (implement and test the six specified, compatible updates; nothing else).

| | Before | After |
|---|---|---|
| Version | 0.18.1-dev0 | 0.19.0-dev0 |
| Branch / commit | `main` @ `4cefc35` | `claude/r5-program-update` (commit recorded in `TEST_RESULTS/R5_UPDATE/`) |
| Standalone database | v13 | v13 (no migration, no new table) |
| Dependencies / licences | - | none added |
| Frozen R1 contract ZIP sha256 | `09174700...bd25e2` | unchanged |

## What is implemented, what is enabled

Everything new is **OFF by default**. A switch is read from the environment (`PID_R5_<NAME>=off|shadow|on`), then from the per-user file the **R5 update** menu writes
(`%LOCALAPPDATA%\PIDReader\r5_features.json`), then OFF. Nothing is switched on by this update.

| # | Item | Implemented | Default | Where | Honest limits |
|---|---|---|---|---|---|
| 1 | DEXPI 2.0.1 mapping of BALL_VALVE, GLOBE_VALVE, CENTRIFUGAL_PUMP, PLATE_HEAT_EXCHANGER, TUBULAR_HEAT_EXCHANGER | yes (new writer; the program had none, only a refusing stub) | OFF (`PID_R5_DEXPI`) | `engineering/dexpi_proposed.py`, CLI `export-dexpi`, menu | Only from human-reviewed classes (or an explicit `include_unreviewed`). Not a conformance claim. **XSD layer BLOCKED**: no validator in the locked environment. The live symbol library has no plate/tubular exchanger template, so those two classes can only come from a reviewed class. No flow, fittings, nozzle verification or graphics. |
| 2 | Source/port/edge fate accounting, lossless sidecar, three separate checks, safe ids | yes | with item 1 | same | One fate per entity, port and relationship, asserted after every export; duplicate source ids refuse the export; ids are injective and reversible (`D<revision-namespace>_<escaped id>`), no comma joins; DTD/entities refused; the word "ACCEPTED" in source text changes nothing. |
| 3 | PDF MediaBox/CropBox/Rotate/UserUnit provenance and unverified-scale guard | yes | OFF (`PID_R5_PAGE_FRAME`) | `formats/page_provenance.py`, pipeline, package file `page_provenance.json` | Provenance only. Geometry is never rescaled; lengths are always refused (`physical_measurements_allowed = false`). The existing crop/rotation mapping (`PageFrame`) is untouched and agrees with it on all four rotations (tested). The program has no physical-measurement feature, so the guard has nothing to block in the UI yet. |
| 4 | Review ledger of blocked / ambiguous connection candidates | yes | OFF (`PID_R5_REVIEW_LEDGER`) | `engineering/connection_review.py`, CLI `review-ledger`, menu dialog, package file `review/connection_review_ledger.json` | Entries are never relationships, never in accepted topology, never path/isolation/Worksheet input, and say "blocked is not disconnected". Ids are namespaced by drawing revision and derived from source observations, so they survive re-runs; human decisions use the existing append-only table. Not yet an overlay on the drawing; decisions by CLI/SDK. |
| 5 | OFF / SHADOW / ON adapters, diagnostics, cancellation | yes | OFF | `engineering/r5_features.py` | SHADOW returns the legacy result and writes candidates to a separate folder (`..__r5_shadow`, `_shadow_dexpi`); never to the database, manifest or accepted data. DEXPI export honours a cancel callable. |
| 6 | R4 C12-v4 dashed optimisation | **evaluated, not integrated** | n/a | `docs/r5_update/C12_EVALUATION.md` | The live program has no dash-run reconstruction stage, so there is no incumbent to be equivalent to and nothing to speed up. |

Kept disabled / research only (unchanged by this update): crowded tag matching (R5 gate failed), stacked/rotated optical OCR (never measured), general instrument/port/signal recognition (restricted test only), automatic topology correction, any DEXPI-compliance or engineering-validation label.

## Source crosswalk

| R5 research reference | Live change |
|---|---|
| `src/dexpi_writer.py::EQUIP/VALVES/to_dexpi`, `dexpi/WRITER_R2_TO_R5.diff` | `dexpi_proposed.py::EQUIP, VALVES, to_dexpi` (rewritten against the live `engineering-intelligence-v1` snapshot, not the lab graph) |
| `src/dexpi_audit.py::with_fates, read` | `dexpi_proposed.py::_assert_fates, audit_read, readback` (structured fates, no comma split; no substring check for ACCEPTED) |
| `src/coordinates.py::frame/read_pdf` | `formats/page_provenance.py::frame_provenance, read_pdf_provenance, measurement_guard` (pypdf, already locked) |
| `src/topology.py::build` (R4 guard ON/OFF comparator) | not used: `connection_review.py` reads the live graph's own CONFLICT and `HAS_ALTERNATIVES` items; OFF is the real incumbent |
| `dashes_r4.py::reconstruct_r4/_FragGrid` | not ported (see C12 evaluation) |
| `windows/shadow_contract.py` | replaced by live OFF/SHADOW/ON handling in `r5_features.py` and the callers |

## Evidence (all from this machine; see `TEST_RESULTS/R5_UPDATE/` and `docs/r5_update/evidence/`)

Environment: Windows 11 Pro 10.0.26200, Python 3.12.10, PySide6 6.12.0, RapidOCR 1.4.4 (existing, unchanged), venv `C:\PIDWork\venv312`. No model was downloaded or changed.

| Check | Command / tool | Result |
|---|---|---|
| Incumbent suite (pristine `git archive` of `main` 4cefc35, not the working tree) | `python -m pytest -q tests` | exit 0, 0 failed, 6 skipped (log: `evidence/baseline_main_pytest_log.txt`); 705 passed per the Rev X record for the same commit |
| Update suite (branch) | `tools/record_test_evidence.py --name branch_pytest` | **806 passed, 0 failed, 6 skipped** (`TEST_RESULTS/R5_UPDATE/branch_pytest.json`); 101 new tests in `tests/test_r5_*.py` |
| Frozen Worksheet R1 checker (unchanged ZIP, sha256 09174700...bd25e2) | `record_test_evidence.py --r1-checker` | **16 passed, 0 failed** (`TEST_RESULTS/R5_UPDATE/r1_checker.json`) |
| Release preflight | `tools/release_preflight.py` | all 3 checks PASS (`evidence/release_preflight.json`); its own `not_run` list (Windows host G4-G7, accuracy benchmark, interoperability, installation licensing) still applies |
| All switches OFF = legacy output | `tools/r5_off_identity.py` on the pristine baseline tree and on the branch (run twice each) | 22 of 22 legacy export files identical (drawing JSON/HTML/graph/GraphML and the whole AI package), same 58 tables, schema 13, no new table. Normalised before hashing: version string, ISO timestamps, `elapsed_ms`/`runtime_ms` (two runs of the SAME tree differ there) and the per-file hashes inside `manifest.json` (those files are compared individually). Evidence: `evidence/off_identity_*.json` |
| DEXPI mapping, fates, ids, readback, registry structure, cancel, modes | `tests/test_r5_dexpi.py` (37) | pass; the registry check ran against the official Core.xml/Plant.xml supplied in the R5 archive: **writer output PASS**, unknown class and unknown property detected |
| DEXPI XSD layer | `validate_xsd` | **BLOCKED_NO_XML_SCHEMA_VALIDATOR** (lxml/xmlschema not installed anywhere on this machine). Not run, not passed. |
| Page metadata guard: UserUnit 1/2/5/10, invalid units, quarter turns, crop offsets/negatives, corrupt boxes, empty/corrupt/missing PDF, page cap, agreement with live `PageFrame` on 4 rotations | `tests/test_r5_page_provenance.py` | pass |
| Review ledger: ids, namespacing, re-run stability, decisions, stale, no writes, never topology | `tests/test_r5_review_ledger.py` | pass |
| OFF / SHADOW / ON through the real pipeline and package export, no migration, end-to-end detect -> review -> export | `tests/test_r5_integration.py` | pass: SHADOW leaves the package byte-identical; ON changes only `manifest.json` and adds the two files |
| Window: R5 menu, switches persist, DEXPI export, ledger dialog (offscreen Qt) | `tests/test_r5_gui.py` | pass (not a Windows display/DPI test) |
| In-process "no socket" guard | `tests/test_r5_offline.py` | pass (not an OS-level isolation test) |
| Real library sheets, standard depth (`evidence/S025_S056_replay.json`) | `tools/r5_stage_replay.py` | **S025**: COMPLETE_CANDIDATES, 175 s, OCR 971 words, 550 symbol-library candidates (33 valves classified, 517 unclassified), 0 relationships, 629 source objects each with exactly one fate (all sidecar-only: nothing human-reviewed), read-back PASS. **S056**: **INCOMPLETE, 430 s, OCR stage FAILED** (`ValueError: Invalid OCR evidence: OCR word identity invalid or duplicated`, issue R5-007, pre-existing, not touched by R5), 2 relationships, 3 loops, 1,097 source objects each with exactly one fate (with unreviewed classes allowed, 19 of them are written (as DEXPI objects, nozzles or pipes) and 1,078 stay sidecar-only; reviewed-only: all 1,097 sidecar-only), read-back PASS. Progress was monotonic in both. Both sheets: page provenance OK, `DRAWING_SCALE_UNVERIFIED`, UserUnit 1, lengths refused. The review ledger found no candidates on either sheet. |
| Frozen build | PyInstaller (`packaging/pid_reader.spec`) -> `C:\PIDWork\r5_build\dist\PIDReader` (373 MB) | build succeeded; `pid-reader-cli.exe r5-features` and `export-dexpi --help` run, all switches OFF |
| C12 dashed optimisation | `C12_EVALUATION.md` | not applicable; not integrated |
| Cold + 7 warm timing, working set, antivirus context | - | NOT RUN (nothing was optimised; single-run timings above are descriptive only, peak working set was not captured by the child run) |
| OS-level network isolation, manual DPI review, Windows host G4-G7, independent accuracy (E2), commercial DEXPI importer | - | NOT RUN |

S056 "25 proposal IDs": those were proposals of an earlier (R4-era, ChatGPT-side) pipeline and are not in this repository. They are **not** accounted for and the root cause of the earlier S025/S056 symptoms is **not** claimed. What was done instead: this program's own S056 output is accounted object by object (`fate_table` in the evidence file).

## Rollback

Demonstrated on this machine, not just planned:
1. Feature settings after the change: all three R5 switches OFF (`pid-reader-cli r5-features`; the default, nothing was switched on).
2. With the switches OFF the branch reproduces the baseline exports: 22 of 22 files identical to the pristine `main` 4cefc35 tree (table above), database schema 13 and 58 tables unchanged, so no copied database or review id was touched.
3. Turning a switch ON and OFF again is reversible: the settings file `%LOCALAPPDATA%\PIDReader\r5_features.json` (or the environment variable) is the only state; `tests/test_r5_integration.py` shows ON changes only `manifest.json` plus the added files, and OFF removes them again. Analysis runs recorded while PAGE_FRAME was ON keep their `page_provenance` entry in their own (append-only) run summary; that is additive and harmless.
4. Full revert: `git checkout main` (the branch has not been merged or pushed). `main` was never modified by this work.
No schema migration exists to undo.

## Remaining blockers (not claimed as done)

* XSD validation of the DEXPI output (no XML-schema validator is installed; adding lxml, BSD-licensed, is an owner decision - R5-001).
* OS-level network-isolation test, antivirus-context timing (1 cold + 7 warm) and manual DPI review of the new menu were not run (R5-006). In-process "no socket" tests pass; that is not an OS isolation test.
* No independent accuracy benchmark exists (E2) and the frozen Worksheet R1 host integration (G-HOST) is still not run; hence nothing here is "production-ready", "independently validated" or "engineering-verified".
* S056's original 25 pre-export proposals (a ChatGPT-side artefact) are not in this repository; the live pipeline's own S056 output is accounted object by object instead (see evidence). The root cause of the R4-era S025/S056 problems is NOT claimed.
