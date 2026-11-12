# PROMPT FOR CHATGPT — P&ID Reader, WP07 integration status (written 12 Nov 2026, mid-task)

Paste everything below the line into ChatGPT. It is a status handoff: what was done, what was measured, what is NOT proven, and what to do next. Claude Code (working on the owner's Windows machine) did the work; ChatGPT has no access to the machine, so treat every number here as reported evidence, not something you can re-run.

---

You are continuing development of the owner's **Advanced P&ID Reader** (Python 3.12, PySide6 6.12.0, Windows 11, offline, CPU-only, i5-8265U class laptop). You wrote the WP07 Rev B package (`PID_READER_WP07_COMPLETE_DEVELOPMENT_REV_B_20261112.zip`). Claude Code has now applied it to the real repository and run it on Windows. Below is exactly what happened. Do not restate it back to me; use it to plan the next work package.

## 0. Ground rules that still apply (do not break them)
- Frozen Worksheet R1 contract/API/worker/schema v1; standalone project DB stays v13. No change to `api.py`/`worker.py`.
- Every reading is an **unverified proposal**. No automatic acceptance. No HAZOP/LOPA/SIL/IPL conclusions. No DEXPI conformance claim.
- Baseline detector gate stays 0.65. Never invent characters from grammar (no inserting an H or a digit because a pattern suggests it). Keep conflicting model outputs.
- No push without the owner. No upload of private drawings. Model weights and ML runtime live outside OneDrive.
- The reserved final benchmark split is never used. Accuracy is reported only inside a reviewed reference's coverage; with no approved reference the answer is NOT_RUN. Passing unit tests, word counts, box counts and completed stages are not accuracy.
- Python file edits use `newline=''`; tests run with `PYTHONPATH=src` and `QT_QPA_PLATFORM=offscreen`; stage git paths explicitly, never `git add -A` (the 1.1 GB `Example P&IDs/` library is git-ignored).

## 1. Repository state
- Repo: `C:\Users\Admin\OneDrive - Enhance Integration Engineering\Company\006 Calculation Methods\26 P&ID reader`, remote `https://github.com/EIEng-enginering/P-ID-reader.git`.
- `main` = `c91ebe6` (WP-01..03 + WP-04..06 + Tesseract fixes, pushed). The package was built against exactly this commit, so there was no drift.
- Work is on branch **`claude/wp07-integration`**, created from `c91ebe6`. **Nothing is committed and nothing is pushed.** Working tree has: the installer's additions, the two small hooks, my fixes (below), and new tools/tests.
- Existing untracked items unrelated to this work: `P&ID Hazop test nov 26/`, `PID_Full_Conversion_Research_and_Test_Plan_Rev_A.docx`.

## 2. Integration of your package — DONE
1. `tools/install_wp07.py --check` → `CHECKED`, 25 files to add, 0 conflicts. `--apply` → `APPLIED`.
2. Only two existing files were modified (exactly the two hooks you declared):
   - `src/pid_reader/ui/main_window.py` (+3 lines: import `ModelLabTab`, add tab "Model comparison", `reset()` hook).
   - `packaging/pid_reader.spec` (+4 lines: excludes torch/torchvision/easyocr/transformers/rfdetr from the exe; ships `model_lab_worker.zip` and `tools/wp07` setup files).
3. New: `src/pid_reader/engineering/model_lab/` (core, adapters, host, runtime, offline, cache, store, export, pipeline, provision, `__main__`), `src/pid_reader/ui/model_lab_tab.py`, `tests/wp07/`, `tools/wp07/`, `docs/wp07/`, `packaging/model_lab_worker.zip`.
4. Targeted checks: `tools/wp07/run_checks.py` → **142 passed** (44 new WP07 tests plus the WP456 suites it runs).
5. **Full repository suite on the integrated branch: 1065 passed, 6 skipped, 1208 s (about 20 min)** on Windows, Python 3.12.10. Before the package it was 1021 passed/6 skipped, so the delta is exactly the 44 new tests; no regressions.
6. **Your reported "symbol matcher timeout" did NOT reproduce.** It was a Linux-environment timeout in `symbol_detect._search` (`cv2.matchTemplate`) under `test_gui`. On Windows the slowest test in the whole suite was `test_gui.py::test_incomplete_analysis_is_shown_as_incomplete_not_success` at 96 s (while another heavy job was running). Classification: baseline slowness on a slow machine, not a package regression and not a hang.
7. Tests overwrite tracked screenshots in `TEST_RESULTS/WIN312_R01/screenshots/`; they were restored with `git checkout --` after the run.

## 3. Windows model setup — DONE
- Ran `tools/wp07/SetupModels.ps1 -Engine all -Python C:\PIDWork\venv312\Scripts\python.exe` → exit 0. Separate venv at `%LOCALAPPDATA%\PIDReader\models\runtime`, models at `%LOCALAPPDATA%\PIDReader\models\` (outside OneDrive). Only public weights downloaded; no drawing left the machine.
- Actual Windows runtime (from `installed-runtime-WINDOWS.txt`): torch 2.8.0+cpu, torchvision 0.23.0+cpu, easyocr 1.7.2, transformers 4.57.1, rfdetr 1.4.3, numpy 2.3.5, Pillow 13.0.0, opencv-python-headless 5.0.0.93, psutil 7.2.2, safetensors 0.8.0, sentencepiece 0.2.1. Platform `Windows-11-10.0.26200-SP0`. All pins resolved without changes.
- Checkpoint SHA-256 (from the manifests, verified by `verify_model` before every load):
  - EasyOCR `craft_mlt_25k.pth` 4a5efbfb48b4081100544e75e1e2b57f8de3d84f213004b14b85fd4b3748db17; `english_g2.pth` e2272681d9d67a04e2dff396b6e95077bc19001f8f6d3593c307b9852e1c29e8 (source release v1.3 / pre-v1.1.6, MD5s checked by the provisioner).
  - TrOCR `microsoft/trocr-small-printed` rev 04e994ab854b0089d4929f48c2b4dbe2ce78a340; `model.safetensors` 49350a39968df83e5a1adc90fc0ede02ff247671aed70b842af350fd4a7103f3. Licence note: model card has no explicit licence field; local evaluation only, distribution unresolved.
  - RF-DETR `dimtri009/rfdetr-pid-detector` rev bc41b7c6c2dfe8b05e91842b53a45c4af6e419c6; `checkpoint_best_total.pth` 063a43b7fbc4066fa6a7ab0a999c0964839b3a40a02a17e33473c5f6502d4df6 (Apache-2.0 declared). Note this is a pickle `.pth`; it is pinned and hash-checked, but a safer loading path is worth considering.

## 4. Windows reproduction of your three-crop diagnostic — MATCHES LINUX
Same three selected S418 crops (`examples/S418_model_diagnostic_ROIS.json`; drawing sha256 `b6b338335a3fc728adac8e631e44b43a56ec485a7403a349c2ca5a3f7621fd51`), all three engines, `COMPLETE_PROPOSALS`:
- EasyOCR: `V_2201` (0.91), `#PF` (0.23), `-Ooig_:i4,J-AJS-40` (0.013), `95-27203_168 $-CJS-83` (0.093).
- TrOCR: `V-2201`, `HPF-06019-1163-435-40`, `GSTS-22203-168 3-C35-80`.
- RF-DETR: one box `Rupture_disk` (0.634) in the V-2201 text crop (a text region, so not evidence of a correct symbol).
- Texts are character-for-character identical to the Linux evidence. Wall time about 28–32 s per engine for 3 crops (inflated: the full suite was running at the same time). This is still a selected-crop diagnostic, not automatic discovery.

## 5. DEFECTS FOUND by running the real models on Windows (your Linux tests could not see these) — FIXED
1. **Whole-crop loss from EasyOCR edge boxes.** EasyOCR polygons can overshoot the crop edge by a pixel or more; `core.record()` is strict ("Model box outside crop") and raised, so the *entire crop failed*. On S418 tile coverage, **3 of 20 tiles were lost** (batches 0 and 1 came back PARTIAL), i.e. silent loss of page coverage. Fix: `adapters.clip_xyxy()` clips EasyOCR and RF-DETR boxes to the crop and drops boxes with under 1 px of visible area; the strict check in `core.record` is unchanged (a test proves the raw box is still refused). After the fix all EasyOCR tile batches complete.
2. **Peak memory was `None` on Windows** (it used the Linux-only `resource` module), so "runtime and memory" could not be reported. Fix: `runtime.metadata()` falls back to `psutil` peak working set (`peak_wset`) when `resource` is missing.
3. Added `tests/wp07/test_windows_fixes.py` (4 tests; psutil one skips in the core venv, which lacks psutil). `tests/wp07` now: 47 passed, 1 skipped. `packaging/model_lab_worker.zip` was rebuilt with `tools/wp07/build_worker.py` after the edit.
4. The edit to `adapters.py` changes the crop-cache identity, so previously cached EasyOCR crops are not reused (expected; confirmed — rerun took full time).

## 6. New tool added: `tools/wp07/eval_configs.py` (explicit, no hand-picked coordinates)
Runs on one page and writes raw proposals + coverage/timing bookkeeping, never an accuracy figure:
- Independent page tiles: 5 columns × 4 rows, 12 % overlap (20 tiles) → EasyOCR and RF-DETR, in batches of 6 tiles, 280 s worker limit.
- Automatically selected TrOCR line crops: elongated boxes (aspect ≥ 2.2, ≥ 4 characters) taken from EasyOCR tile output **and** the existing RapidOCR boxes, de-duplicated at IoU 0.5, padded 18 %, capped at 60 crops; vertical boxes get 90°/270° reads.
- Overlap merge of tile duplicates (IoU ≥ 0.4, higher score kept, others stored as `alternatives`); counts EasyOCR texts that do not overlap any baseline RapidOCR word.

## 7. S418 measured so far (run 1, BEFORE the clipping fix) — coverage and cost only
Same drawing; baseline = the c91ebe6 result package (581 RapidOCR words, 437 strokes, 353 UNKNOWN centrelines, 428 symbol candidates, 65 detector boxes, 0 standard tag assignments, overall PARTIAL; WP01–03: 7 readings + 5 fields; manual ROIs add V-2201 and drawing number 030).
- EasyOCR tiles: 2 of 4 batches COMPLETE, 2 PARTIAL (3 tiles lost, bug above). 739 raw records → 577 after overlap merge; **97 EasyOCR texts do not overlap any baseline word** (this is a count of *additional detections*, not of correct readings). 807 s wall for 20 tiles (about 37 s per 1.2-Mpixel tile on this CPU).
- RF-DETR tiles: 4/4 batches COMPLETE; 159 raw → 121 merged boxes; 132 s wall. Not yet inspected for class correctness.
- TrOCR: 60 auto-selected horizontal line crops, 10/10 batches COMPLETE, 235 s wall (about 3.9 s per crop); **no vertical crops were selected** — vertical text is a stated priority and is still not handled by tiling (tiles are not rotated); I have not yet checked whether the 60-crop cap truncated vertical candidates.
- Not yet measured: peak memory on Windows (fix is in, first value will come from the rerun), correctness of any of the new readings.

## 8. IN PROGRESS at the moment of writing
Run 2 (same command, after the clip fix, same switches and budgets) is executing in the background; results go to `C:\PIDWork\wp07_results\s418_eval\` (run 1 outputs preserved in `s418_eval_run1\`). It will give: all 20 tiles complete, a changed TrOCR selection (more EasyOCR boxes), and the first Windows peak-memory numbers. **I have not yet looked at its outputs, so no result in this section is known.**

## 9. NOT done yet — the next work, in priority order
1. **Draft reference + diagnostic scoring (the missing piece).** Build a small explicit S418 reference: the owner's diagnostic observations (V-2201; drawing number 030; HPF-00019-114.3-A3S-40 believed for the baseline's `PF-00019-14.3-A3S-40`; GHS-22203-168.3-C3S-80 believed for `GS-22203-168.3-C3S-80`; bubble FR over 720201 where baseline says FQ / FQ-77701) plus the analyst-verified items (FE-2206 ×2, FE-2202, vertical DR-22202-33.4-C3S-XXS, dates, NTS, 012) plus ~10–15 further line labels read directly from full-resolution crops. Label it `DRAFT_ANALYST_NOT_INDEPENDENT`; the owner's statements are diagnostic checks, not an exhaustive verified reference. Score each configuration (existing / +EasyOCR / +TrOCR auto-crops / RF-DETR / combined) per item as correct / wrong / incomplete / missed, **within the reference's coverage only**.
2. **Do the challengers fix the five known problem cases automatically?** In the 3-crop diagnostic nothing did: TrOCR gives an H but also `0`→`6`, `.` dropped, `114.3`→`1163`; EasyOCR is fragmented. Test whether auto-selected crops reproduce V-2201/030, and whether multi-variant re-reads (several scales/contrast/binarisation of the same suspicious line) produce a *consistent observed* alternative. Use grammar only to **flag** suspicious readings and request a re-read; never to insert unobserved characters. Keep all conflicting outputs.
3. **Vertical and small text:** rotate EasyOCR tiles by 90°/270° (cost doubles, about 15 min per rotation per page on this CPU) or restrict the rotated pass to regions where baseline/line geometry indicates vertical text; verify the 60-crop cap did not hide vertical lines.
4. **RF-DETR evaluation on actual symbols:** inspect the 121 boxes against the page (overlay), class by class; the published taxonomy has 32 classes with duplicates (`Instrument_Field`, `Instrument_Panel`, `Box`, two `Globe_valve_NO` spellings) and does not cover every symbol. Compare with the 65 baseline detector boxes; the baseline gate .65 stays; boxes are shown for review only.
5. **Association and connectivity:** tag-to-symbol association with an explicit "no match" option; port-based connectivity only where evidence exists; process and signal lines distinct; the 353 UNKNOWN centrelines stay UNKNOWN unless there is evidence. This was not started.
6. **More real drawings (development only):** pick a few from `Example P&IDs/library` (608 public sheets; no reserved split is registered in `fixtures/benchmark_registry_empty.json`, but record the hashes used and keep them development-only). Do not tune to S418; do not hard-code its coordinates.
7. **Performance:** EasyOCR about 37 s/tile and each ROI re-renders the whole page at about 4× (`wp456.host.pdf_renderer`) — render once per page and reuse; report peak memory and runtime per configuration.
8. **Not yet verified on Windows:** cancellation, stale-page rejection and rotated/CropBox behaviour *in the real GUI* beyond the package's offscreen tests (those 44+ tests pass); frozen-executable build with the external worker archive; manual DPI/multi-monitor. Host gates G4–G7 and an independent engineering benchmark remain NOT_RUN.
9. Deliverables still owed: baseline-vs-challenger overlays and machine-readable results for the same page and budgets; a demonstrated-improvement vs remaining-error table; versions/hashes (above); runtime and memory; a handoff ZIP; commit on `claude/wp07-integration` only when the owner says.

## 10. Honest status line to carry forward
- **Software implemented:** yes — package applied, 1065/6 full suite on Windows, models staged, two Windows-only defects found and fixed, evaluation tool added.
- **Extraction improvement demonstrated:** **not yet.** The only evidence is a selected-crop diagnostic that reproduces your Linux result: TrOCR reads V-2201 (already found by the manual-ROI method) and both difficult line labels remain wrong; EasyOCR adds many detections of unknown correctness; RF-DETR has not been checked on real symbols.
- **Bottleneck so far:** no reviewed reference, so nothing can be scored; line-label character errors (dropped/mis-read `H`, `1`, `.`) are unchanged by every model; vertical text is not covered; CPU cost is high.

## What I want from you now
1. Propose (do not code yet) the **scoring protocol** for item 9.1, including how to avoid self-confirmation (the reference must not be filled from the program's own output) and how to score partially-correct strings (edit distance reported separately from exact match, no O/0 substitutions).
2. Propose a **multi-variant re-read design** for suspicious line labels that keeps all observed alternatives and never inserts characters; specify the grammar-flagging rules for the prefixes seen in S418 (`HPF`, `GHS`, `DR`, `PC`, `WP`) as flags only.
3. Propose a design for the **rotated/vertical text pass** with a cost cap suited to the CPU above.
4. List the exact code changes you would hand to Claude Code, file by file, as small additive patches against `c91ebe6` + the current `claude/wp07-integration` working tree. Say plainly which of them you expect to give a measurable improvement and which are only infrastructure.
