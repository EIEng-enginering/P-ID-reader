# R3 integration status (Grok return GROK_PID_READER_AUTOMATIC_OFFSHORE_RETURN_R3, sha256 b1428df9...03d0)

Branch `claude/r3-integration` on top of the TR1 integration (main 638ceca). Windows 11 Pro 10.0.26200, Intel i5-8265U 4C/8T, 15.8 GB, Python 3.12.10, PySide6 6.12.0, torch 2.15.0+cpu / torchvision 0.29.2+cpu in the optional component.
ZIP verified first: whole-file sha256 matched and all 219 internal manifest members matched. Everything R3 produced is on synthetic-source sheets, authored fixtures or weak geometry labels; all outputs here stay PROPOSED or UNRESOLVED. Nothing is human-reviewed or engineering-verified, and nothing is production-ready.

## What was integrated (each behind its own switch, default OFF; all in `src/pid_reader/tr1/`)
| Component | Switch | State | What it does |
|---|---|---|---|
| `tiled_r3.py` | `PIDLAB_TILE_MERGE_R3` = `r1_drop_inner_edge` (default) / `edge_safe` / `edge_safe+coarse` | integrated, default = R1 | `edge_safe` keeps and stitches objects larger than the 200 px tile overlap that the R1 rule drops; stitched boxes carry `edge_partial` and stay PROPOSED. The default path still runs the unchanged R1 `predict_gray` |
| `corrections_guard.py` | (always on once the queue is on) | integrated | The review queue is now a `GuardedQueue`: machine actors (`auto:`, `model:`, `pipeline:`, `grok:`) can only import proposals (truth type `MODEL_PSEUDOLABEL`); submit, second review and adjudicate need a named human. The detections window already passes the signed-in reviewer name |
| `tag_assign.py` | `PIDLAB_TAG_ASSIGN_R3` | integrated | Hungarian tag-to-detection assignment with abstention (UNRESOLVED, AMBIGUOUS when the margin is under 0.15), shown in the detections table |
| `graph_conservative.py` | `PIDLAB_GRAPH_CONSERVATIVE_R3` | integrated as hints | "Join hints" button: two detections are hinted only when one drawn ink component touches exactly those two; a component touching more is an unresolved junction. Never connections, never exported |
| fine class stage E6-09 | `PIDLAB_FINE_CLASS_R3` | integrated | MobileNetV3-small, 64x64 crop, decoding restricted to the coarse parent, abstains below tau 0.5; shown as "subtype id N (names unverified)" |
| E5 weights | | unchanged | still the default (sha256 6f636fac...); threshold 0.65; R3 arms A_old, B_expanded, C_balanced and L_exp are NOT shipped (they all failed their gates against E5) |
Not integrated, as instructed: stacked OCR (negative), the ONNX path (E6-10 FAILED: ORT crashes on tiles with no detections, no faster than torch), the Grok offline trainer (research tool; the app already has its own guarded trainer in `tools/tr1_train`).

## Results (PASS / FAIL / NOT_RUN / BLOCKED)
| Item | Result | Evidence |
|---|---|---|
| Full app suite, all switches OFF | **PASS** 869 passed, 6 skipped (849 before + 20 new R3 tests), 880 s; frozen R1 zip sha256 unchanged, its checker 16 passed, `release_preflight` PASS | pytest run |
| Flags-off output identity (working tree vs main 638ceca) | **PASS** hash-identical: analysis counts, stage outcomes, intelligence snapshot, project export, R1 result for 2 fixtures (timestamps and the random R1 run id excluded) | scratch probe |
| Default detector command | **PASS** with every R3 switch off the detector command, candidate fields and sidecar are exactly the TR1 ones (no `--merge-policy`, `--fine-card`, `edge_partial` or `fine`) | `tests/test_tr1_r3.py` |
| Grok R3 tests on Windows with the torch component (`test_r3_*`, `test_tiled_pid2graph`, `test_infer_cli`, `test_queue_batches`) | **PASS** 27 passed (same as Grok on Linux), 2 skipped: `test_r3_exact_resume` needs the R1 tile images, which are not in either ZIP; the app's own resume test (`tests/test_tr1_trainer_tool.py`) passes | |
| New R3 integration tests | **PASS** 20 passed (switch parsing, machine actors refused, split assignment equal to whole assignment, abstention, join hints and junctions, command only gets R3 options when asked, tampered fine weights refused, malformed fine result refused, real detector with all R3 options) | `tests/test_tr1_r3.py` |
| R1 policy equals the frozen R1 rule; seam fixtures | **PASS** authored seam fixtures (3 worlds): R1 rule loses 34 large seam objects, `edge_safe` recovers all 34 with 0 false positives; `r1_drop_inner_edge` equals the frozen `predict_gray` exactly | `tests/tr1_data/merge_checks.py` |
| Each switch ON individually | **PASS** merge policy (each value), tag assign, join hints, fine stage each ran without a crash, outputs PROPOSED/UNRESOLVED/ABSTAINED, no Worksheet R1 or database change | `tests/test_tr1_r3.py`, `tests/test_tr1_ui.py` |
| OPEN100 sentinel on Windows, three policies (descriptive only, nothing selected on it) | **exact agreement with Grok Linux**: valve+instrument TP/FP/FN 517/68/90 (F1 0.8674) r1; 517/94/90 (0.8489) edge_safe; 517/99/90 (0.8455) edge_safe+coarse. All-class counts also equal Linux (661/228/682, 662/265/681, 677/299/666). `edge_safe` does not help on OPEN100: it adds false positives (general 59 to 60 hits, +11 FP; instrumentation +26 FP), so the R1 rule stays the default | `evidence/r3_policy_eval.json` |
| Latency and peak memory on the i5, end to end as the app runs it (3 plans, process wall, median) | r1 61.9 s, 1006 MB peak; edge_safe 61.1 s, 999 MB; edge_safe+coarse 81.6 s, 1090 MB. The coarse pass adds about 20 s and about 85 MB per plan. The fine stage added 0.5 s on the fixture | same file |
| UI smoke (offscreen Qt) with the R3 controls | **PASS** menu items, merge-policy choice persists, subtype and seam columns shown | `tests/test_tr1_ui.py` |
| Process-tree timeout / RAM guard for offline tools on Windows | **PASS** (done in the TR1 round: Job Object guard in `tools/tr1_train/tr1train/guard.py`; Grok's `run_guard.py` is Linux `/proc` only and is not used) | `tests/test_tr1_trainer_tool.py` |
| Frozen package (PyInstaller, `C:\PIDWork\r3_build\dist\PIDReader`), torch component absent and present | **PASS** builds; the GUI exe starts; frozen `pid-reader-cli tr1-detect`: switches off returns FLAG_OFF; on with no weights returns NO_MODEL; weights but no torch component returns NO_TORCH_COMPONENT (the app carries on); with the component it returns 7 proposals on the fixture with the default R1 policy (13 s, 906 MB) and 10 proposals with edge_safe+coarse plus the fine stage. The spec now ships `infer_cli.py`, `tiled_r3.py` and the two cards; the weights are not bundled (place them in `%LOCALAPPDATA%\PIDReader	r1\models` or `models\` beside the program) | `packaging/pid_reader.spec` |
| ONNX parity on Windows | NOT_RUN (ONNX not integrated; E6-10 failed on Linux) | |
| Real-drawing accuracy, real tag-association, real graph and real fine-class gates, Worksheet host G4-G7 | BLOCKED / NOT_RUN (B1 to B5: no real annotated data, as Grok recorded) | |

## Findings
* `edge_safe` and `edge_safe+coarse` fix objects that straddle a tile seam in authored fixtures, but on the only real annotated set they only add false positives, so they are off by default and offered as an option.
* The fine stage was trained on ground-truth crops at the native scale of synthetic-source sheets (macro F1 1.000, saturated); the app crops detector boxes from a rendered page at another scale, so its real behaviour is unknown. Its ids are numeric Dataset-P&ID ids with unverified names and are shown only as "subtype id N".
* Tag assignment evidence is authored fixtures only; join hints failed their own precision gate (0.68 against 0.70) and are labelled hints.
* Not run because the data is not available: Grok's exact-resume test (R1 tile images), real-drawing gates.

## Rollback
Switches: untick the three menu items and choose "R1 rule" in Tile-seam merge policy (or delete `%LOCALAPPDATA%\PIDReader\tr1_features.json`, unset `PIDLAB_*_R3`). Component: delete the torch environment. Code: `git revert` the R3 commits (new files plus small edits to `flags.py`, `detector.py`, `infer_cli.py`, `review.py`, `tr1_dialog.py`, `main_window.py`, `pid_reader.spec`). The E5 weights stay.
