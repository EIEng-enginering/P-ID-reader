# TR1 integration status (Grok return GROK_PID_READER_TRAINING_RND_RETURN_R1, sha256 ed54db9d...d9f2)

Branch `claude/tr1-integration` (cut from `claude/baseline-fixes-1-4`; nothing committed). Windows 11 Pro 10.0.26200, Intel i5-8265U 4C/8T, 15.8 GB, Python 3.12.10, PySide6 6.12.0.
All readings stay unverified proposals. The detector proposes; an engineer decides. No claim is made about the owner's own drawings (none were tested).

## Switches (all default OFF; environment variable, else `%LOCALAPPDATA%\PIDReader\tr1_features.json`, else off; an unknown value is an error)
| Switch | Gates | App menu |
|---|---|---|
| `PIDLAB_SYMBOL_FRCNN_TR1` | learned detector (PROPOSED detections, separate sidecar) | yes |
| `PIDLAB_SYMBOL_CATALOGUE_TR1` | catalogue v1.0.0 for reviews | yes |
| `PIDLAB_CORRECTION_QUEUE_TR1` | confirm / reject / edit capture (hash-chained queue) | yes |
| `PIDLAB_TRAINING_BATCH_TR1` | versioned batch builder (needs approval id and named approver) | yes |
| `PIDLAB_LOCAL_TRAINER_TR1` | `tools/tr1_train/run_training.py` | environment / settings file |
| `PIDLAB_MODEL_REGISTRY_TR1` | registry used by the trainer tool | environment / settings file |

Not integrated: the extended template library and the abstain-only verifier (not requested; Grok's own E1 runtime gate H4 FAILED).

## How it works
* The app never imports torch. `tr1/detector.py` starts `tr1/infer_cli.py` with the torch component's Python (`PIDLAB_TR1_PYTHON`, or `%LOCALAPPDATA%\PIDReader\tr1\torch_env`) with a timeout (default 900 s), cancel and tree kill. The weights sha256 is checked against the model card before every load; the result is validated (schema, source sha, boxes, classes, all PROPOSED, unique ids) and refused, not repaired, if wrong.
* If the switch is off, the torch component or model is missing, the weights do not match, or the run fails or times out, `detect()` returns a plain message and the normal analysis (template matching) is untouched. The detector does NOT replace the NCC path: E5's classes are coarse and cannot feed the engineering graph, so it runs beside it, on request (menu or `tr1-detect`), not inside `analyze_drawing`.
* Output goes to `%LOCALAPPDATA%\PIDReader\tr1\detections\<sha>\page_N.json` (not the database, not the package manifest, not Worksheet output). Coarse class to catalogue family only (`valve` -> `CLS.VALVE.UNKNOWN`, `instrumentation` -> `CLS.INSTRUMENT.UNKNOWN`, `general` -> `CLS.EQUIPMENT.UNKNOWN`, `arrow` -> none); the engineer chooses the real class.
* Review: confirm, change class, not a symbol, leave unresolved, second review, recorded in `corrections/queue.jsonl`. A detector-withheld, ambiguous or safety-class item needs an independent second reviewer. Batches: `batches/<version>/` immutable, hashed, family-split; known development sheets (S023/024/025/056/080/081) go to `development` only; the approval id and approver are typed by the user, never assumed. A `CONFIRM` kind was added to Grok's queue.
* Trainer: `tools/tr1_train/` (README there). Job Object guard, wall/CPU/tree-memory limits, cancel file, hash-chained events, resume, seed 20261110, tile preparation, registry.

## Results (PASS / FAIL / NOT_RUN / BLOCKED)
| Item | Result | Evidence |
|---|---|---|
| App suite, all switches OFF | **PASS** 849 passed, 6 skipped (815 before + 34 new TR1 tests), 965 s | pytest run |
| Flags-OFF output identity | **PASS** hash-identical: analysis counts, stage outcomes, intelligence snapshot, project export and R1 result for 2 fixtures, with vs without the TR1 changes. Timestamps and the random R1 run id are excluded because they differ even between two runs of the same tree | scratch probe, not kept in the repo |
| Frozen R1 contract zip | **PASS** sha256 09174700...25e2 unchanged; its own checker 16 passed; `api.py` and `worker.py` untouched | |
| `tools/release_preflight.py` | **PASS** | |
| Grok candidate tests, app venv | 42 PASS, **1 FAIL** of 43 (the DEXPI-name test ran with the R5 `Plant.xml`) | failure = `test_rss_limit`, see below |
| Grok candidate tests, torch venv (infer CLI, tiling, PID2Graph reader) | **PASS** 5/5 | |
| E5 on Windows, OPEN100 12 plans (24 files, 11.4 MB, fetched from Zenodo 14803338, sha256 matched Grok's manifest) | **PASS, exact agreement**: valve+instrument F1 0.8674496644 (P 0.884, R 0.852), identical to the Linux result; per-plan valve tp/fp/fn identical on 12 of 12 plans | `evidence/e5_windows_open100.json` |
| E5 runtime and memory on Windows | median 62.5 s per plan as a separate process (includes about 10 s torch start and model load), detection 52.5 s; Linux median was 34.2 s. Peak working set about 1.0 GB (max 1014 MB). The zip's own synthetic sheets are small (1080x720 px): 10 to 16 s, 0.6 GB; no Linux E5 output exists for them, so no agreement figure | `evidence/e5_windows_synth.json` |
| Trainer kill-tree on Windows | **PASS** wall limit, cancel, memory limit, and abrupt death of the launcher (Job Object) all leave no process; a grandchild's heartbeat stops | `tests/test_tr1_trainer_tool.py` |
| Real CPU training, stop and resume | **PASS** 4 tiles, 2 epochs, random start, 2 threads: stopped by cancel after a mid-run checkpoint, resumed, final weights sha256 identical to the uninterrupted run; registry registration works (124 s) | same file |
| UI smoke (offscreen Qt) | **PASS** menu toggle persists the switch, background run task, 3 detections in table and overlay layer, confirm / reject / withheld item awaiting second review, queue chain verifies, switch off again | `tests/test_tr1_ui.py` |
| Real detector through the app runner | **PASS** `tr1-detect` on a fixture; with no torch component it returns `NO_TORCH_COMPONENT`, exit code 3 | |
| Tile preparation | **PASS** deterministic on a synthetic mini PID2Graph tree; OPEN100 never used | |
| High-DPI / on-screen GUI check | NOT_RUN (offscreen only) | |
| PyInstaller frozen build with TR1 | NOT_RUN (spec unchanged; `infer_cli.py` is run by path and `models/` would have to be added as data; the frozen app falls back with a message) | |
| Training from reviewed corrections (batch to tiles) | NOT DONE (batches hold boxes and the document sha256; tiles need the original PDFs) | |
| Real-drawing accuracy, blind validation, Worksheet host G4-G7 | BLOCKED / NOT_RUN (no eligible data, as before) | |

## What did not work / findings
* Grok `test_adapter_registry.py::test_rss_limit` FAILS on Windows: the venv `python.exe` is a 5 MB launcher that starts the real interpreter, so Grok's adapter measured the launcher and never saw the memory. The new guard measures the whole Job Object tree and passes its own memory test. Grok's `trainer_adapter` is not used by this integration.
* E5 on OPEN100 at the card threshold, per class (precision / recall / F1): valve 0.81 / 0.77 / 0.79, instrumentation 0.94 / 0.91 / 0.93, general 0.44 / 0.21 / 0.28, arrow 0.50 / 0.19 / 0.27. Scores are uncalibrated.
* Windows is about 1.8x slower per plan than the Linux box.
* A page above 150 Mpixel at scale 2.5 is rendered at a reduced scale (reported in the result notes); symbol sizes then differ from training.
* Item 5 (R1 to R4): **C12-v4 dashed signals** was evaluated in R5 and not integrated, because the app has no dash-run reconstruction stage (`docs/r5_update/C12_EVALUATION.md`); no switch was created. **DEXPI read-back** already exists (`dexpi_proposed.readback`, `PID_R5_DEXPI`). **OCR lab grammar** and **spec-string block list**: BLOCKED, their code and data are in neither this ZIP nor the repo; send the R1/R2 returns that hold them. No switch exists for them.

## Rollback
1. Switch off: untick the four items in the Learned detector menu, or delete `%LOCALAPPDATA%\PIDReader\tr1_features.json` and unset any `PIDLAB_*_TR1` variable. Nothing else is affected; the database and project files never held TR1 data.
2. Remove the optional component: delete `%LOCALAPPDATA%\PIDReader\tr1\torch_env`, or the venv named by `PIDLAB_TR1_PYTHON` (here `C:\PIDWork\venv312_torch`). Without it the app reports `NO_TORCH_COMPONENT` and carries on.
3. Data: `%LOCALAPPDATA%\PIDReader\tr1\` (detections, `corrections\queue.jsonl`, `batches\`) is append-only evidence; keep or archive it, never edit it.
4. Code: nothing is committed. To discard: `git restore .gitignore CHANGELOG.md src/pid_reader/cli.py src/pid_reader/ui/main_window.py src/pid_reader/ui/viewer.py tests/conftest.py`, then delete `src/pid_reader/tr1`, `src/pid_reader/ui/tr1_dialog.py`, `tools/tr1_train`, `models`, `requirements-tr1-torch.txt`, `tests/test_tr1_*.py`, `docs/tr1_integration`. If you commit it, `git revert` that commit. The baseline-fixes 1 to 4 edits are separate and stay.
