# WP07 on Windows — integration status and measured results (12 Nov 2026)

Branch `claude/wp07-integration` (from `main` c91ebe6; uncommitted, not pushed). Every output below is an **unverified proposal**.
Accuracy figures are **diagnostic and DRAFT**: the only references are analyst readings (not independent), cover a few dozen items, and
must not be quoted as page accuracy. Frozen R1 contract/API/worker/schema v1 and standalone DB v13 are unchanged.

## 1. Software (implemented and verified)
| Item | Result |
|---|---|
| Installer `--check` / `--apply` | CHECKED (25 files, 0 conflicts) / APPLIED; only `main_window.py` (+3 lines) and `pid_reader.spec` (+4) modified |
| WP07 dedicated checks (`tools/wp07/run_checks.py`) | 142 passed on first apply |
| Full repository suite after apply | 1065 passed, 6 skipped, 1208 s (before the package: 1021 / 6) |
| Full suite after the Windows fixes below | see section 6 |
| Reported "symbol matcher timeout" | **did not reproduce** on Windows (slowest test 96 s under load); it was a Linux-environment timeout, not a package regression |
| Windows model runtime | torch 2.8.0+cpu, torchvision 0.23.0+cpu, easyocr 1.7.2, transformers 4.57.1, rfdetr 1.4.3, numpy 2.3.5, Pillow 13.0.0, psutil 7.2.2 (`installed-runtime-WINDOWS.txt` in the results package) |
| Checkpoints (SHA-256 verified before each load) | EasyOCR craft_mlt_25k 4a5efbfb…db17, english_g2 e2272681…29e8; TrOCR small-printed rev 04e994ab… model.safetensors 49350a39…03f3; RF-DETR rev bc41b7c6… checkpoint 063a43b7…4df6 |
| Windows reproduction of the 3-crop diagnostic | identical texts to the Linux evidence for all three engines |

## 2. Defects found only by running the real models on Windows (fixed, with tests)
1. EasyOCR boxes overshooting the crop edge made `core.record` refuse the whole crop: **3 of 20 page tiles were silently lost**. `adapters.clip_xyxy` now clips to the crop and drops boxes with under 1 px visible area; the strict check stays (a test shows the raw box is still refused).
2. **EasyOCR peak memory 9.1 GiB** on a 15.8 GiB machine (7.7 GiB for one 3.3 Mpx tile). The renderer upsizes every crop to about 3.3 Mpx whatever the tile size, so smaller tiles do not help. EasyOCR input is now bounded to 1.3 Mpx (`EASYOCR_MAX_PIXELS`), boxes mapped back to the full crop: peak **3.96 GiB**, page time 842 s to 378 s.
3. Peak memory was `None` on Windows (`resource` is Linux-only). `runtime.metadata` now uses the psutil peak working set.
4. Additions: `model_lab/consensus.py` (choose among OBSERVED strings only; never edits or composes), crop variants in `pipeline.prepare` (`base/small/large/binary`), `tools/wp07/eval_configs.py` (page tiles, targeted re-reads), `tools/wp07/eval_bubbles.py`, `tools/wp07/score_reference.py`. Tests: `tests/wp07/test_windows_fixes.py`, `test_consensus_and_variants.py`.
5. **Pre-existing GUI race (not a WP07 regression).** `tests/test_wp456_gui.py::test_stale_result_does_not_populate_another_page` failed in the final full run, and fails about 1 run in 8 on a clean main c91ebe6 worktree (and 2 of 6 on this branch). Cause: `run_task` cleared `window.task` in one queued slot while the tabs released `_busy` through separate queued connections added afterwards, so a tab could stay busy for a moment after the task was gone. Fix: `run_task(..., on_finish=...)` runs the release inside the same slot that clears the task and returns False when another task is running; the WP04-06 and Model comparison tabs use it. Tests: `tests/test_task_on_finish.py` (3); the formerly flaky test passed 15 of 15 afterwards.

## 3. S418 measured (same drawing, page, budgets; sha256 b6b33833…fd51)
Baseline = c91ebe6 result package (581 RapidOCR words, 353 UNKNOWN centrelines, 65 withheld detector boxes, 0 standard tags).

| Stage | Cost (this CPU, 4 cores) | Result |
|---|---|---|
| EasyOCR on 20 tiles (5x4, 12 % overlap), capped | 378 s, peak 3.96 GiB, 20/20 tiles | 776 raw, 586 merged; 98 do not overlap an existing word; only 21 have score >= 0.3 |
| RF-DETR on the same 20 tiles | 112 s, peak 0.69 GiB, 20/20 | 159 raw, 121 merged boxes; 55 `Instrument_*` |
| TrOCR on 25 auto-selected line crops x 4 renderings | 216 s, peak 0.55 GiB | 104 readings |
| TrOCR on RF-DETR bubble halves (55 bubbles x code/number) | 171 s, peak 0.55 GiB | 110 readings |

Page coverage requested/completed/omitted: tiles 20/20/0; line crops 25/25/0 (budget 80); bubble halves 110/110/0. Not covered: rotated EasyOCR tiles (vertical text), anything outside the listed engines.

### 3.1 Text readings, draft reference (27 items; DRAFT_ANALYST_NOT_INDEPENDENT)
18 line labels, 9 tags/fields. Scope is these items only.
| Reader | exact | incomplete | wrong | missed | mean edit distance (where a reading exists) |
|---|---|---|---|---|---|
| Existing (RapidOCR) | 7 | 3 | 15 | 2 | 2.32 |
| EasyOCR tiles | 2 | 2 | 22 | 1 | 9.04 |
| TrOCR on auto line crops (chosen rendering) | 1 | 0 | 17 | 9 (not selected) | 3.50 |
| Consensus of existing + 4 TrOCR renderings | 7 | 0 | 18 | 2 | 2.48 |

**No improvement in line-label accuracy is demonstrated.** Consensus is closer to the reference than the existing reading on 6 labels and farther on 9. The four renderings of one crop mostly give the same reading, so they are not independent evidence. TrOCR exactness is fragile: with 18 % crop padding it read `GHS-22203-168.3-C3S-80` exactly; with tighter padding that reading was lost and a different one (`PC-22202-33.4-C3S-XXS`) became exact, so a single exact hit says little.
What does work: **disagreement flagging**. 17 of the 18 wrong or incomplete existing readings differ from the TrOCR readings (flag raised); 1 of 7 exact existing readings was flagged. Flags are cheap here because 72 % of the existing line readings are wrong, so treat this as a review queue, not a measure of correctness.

Known S418 cases: drawing number `030` was read exactly by EasyOCR tiles (existing reader: `0.30`) — the one automatic discovery of a previously manual-only item; `012` exact. `V-2201`: existing reader found neither the header nor the vessel label; EasyOCR gave `=2201` and `201`; TrOCR on an EasyOCR-found box gave `Y-2201`; only the manual-region route reads it exactly. `HPF-00019-114.3-A3S-40`, `GHS-22203-168.3-C3S-80` and the FR/720201 bubble remain unread. `S` is read as `5` and `.` is lost or becomes `/` or `,` consistently across renderings.

### 3.2 Symbols: RF-DETR (the clearest gain, still unverified against a reference)
- Existing learned detector: 65 boxes, 1 instrumentation, all withheld. Ring route: 23 circle hypotheses, only where OCR text existed.
- RF-DETR on tiles: 55 `Instrument_*` boxes. 18 of the 23 ring circles are covered; 39 of the 55 boxes have no ring hypothesis.
- Fixed-rule sample (every second `Instrument_*` box in reading order, 28): analyst view: all but about two are real instrument symbols (circles, logic panels, hexagon markers); 2 are partial or debatable (a cloud-bounded pair, a hexagon marker). Classes seen: circles as `Instrument_Field`, square logic panels as `Instrument_Panel`.
- False or wrong classes seen: `Pipe_Insulation_or_Tracing` on off-page connector boxes, `Instrument_Field` on the "O" of ORIGINAL, valves mapped to `Globe_valve_NO` / `Ball_Valve` that the drawing may show as another type (not verified), the V-2201 vessel is not found (no vessel class).
- Visual check on two more real drawings (S035 dirty scan, S333 clean): bubbles found on most circles in both; false hits on the engineer stamp and a revision table (S035). No reference, so no recall/precision.
- RF-DETR boxes are proposals for review; the baseline .65 gate and the withheld detector boxes are unchanged.

### 3.3 Stacked bubble code (draft code reference, 16 of 28 sampled bubbles; legible ones only, so easier than average)
RF-DETR bubble box split into code/number halves: TrOCR 1/16 exact (3/16 once ring-edge marks such as `/PSV\` are stripped); EasyOCR with a letters-only allowlist 4/16; existing ring route 1/16 with a candidate. The engines are right on different bubbles; the errors are F/T and D/O confusions on a low-resolution scan. **Stacked bubble reading is not solved.** Digits were not legible enough to build a number reference; 13 of 55 number crops came back as six digits (descriptive only).

## 4. NOT done (honest limits)
- No independent reference exists; nothing here is page recall or accuracy. The reference files in `examples/wp07/` are DRAFT analyst readings.
- Association (tag to symbol with explicit no-match), port-based connectivity, process/signal separation, junction/crossing tests: **not started**; the 353 geometry edges remain UNKNOWN.
- Vertical text: not covered by tiling (rotated EasyOCR tiles would double the 378 s); one vertical line label was read with both quarter turns.
- Other drawings: RF-DETR only (S035, S333). EasyOCR and TrOCR were not run on them.
- Not run: GUI click-through on Windows (offscreen tests only), DPI/multi-monitor, frozen build with the external worker archive, host gates G4-G7, independent benchmark.

## 5. Where the bottleneck is
Reading small text from a low-resolution raster: glyph confusions (S/5, F/T, D/O) and lost dots are the same across engines and renderings, so a second engine or re-rendering does not fix them. Localisation (RF-DETR bubbles, EasyOCR boxes, existing word boxes) is already ahead of reading. The next lever is better crops (the source raster resolution) and a bubble-aware reference, not another recogniser.

## 6. Final full suite
1103 passed, 7 skipped, 0 failed, 820 s (Windows, Python 3.12.10, PYTHONPATH=src, offscreen Qt). This includes the 44 WP07 tests, the Windows-fix tests, the consensus/variant tests, the 3 task-release tests and the 22 long-term programme tests. Before the race fix the same suite had 1 failure (the pre-existing flaky stale-result test).

## 7. Long-term modelling package (PID_READER_LONGTERM_REV_A) — installed, not scheduled
Installer check/apply: 16 new files, 0 existing files modified (`engineering/longterm/`, `tests/longterm/`, `tools/longterm/`). Its 22 tests pass. With a config outside OneDrive (`C:\PIDWork\PIDLongTerm\programme.json`, empty finite plan) `launch.py status` runs under the Windows ML runtime: no jobs, audit chain clean. **Not done, on purpose:** no job was queued or run, and the hourly Task Scheduler task was **not registered** (it is standing system configuration and would compete for the 4-core laptop). `EXPERIMENT_WP08` jobs need the separate WP08 delta, which was not supplied. `TRAIN_OCR` needs a human-verified source-pixel corpus; none exists. The 27-item and 16-item draft references here are analyst readings from the same low-resolution scan, NOT trainable or validation data under its contract (origin HUMAN_SOURCE_PIXELS, review_status VERIFIED_DEVELOPMENT by a named reviewer). Real-data training is therefore blocked on labels. The S418 evidence argues for exactly this: the errors are consistent glyph confusions (S/5, F/T, D/O, lost dots) that a recogniser tuned on correctly transcribed crops of this scan style could address, whereas more engines and re-renderings did not.
