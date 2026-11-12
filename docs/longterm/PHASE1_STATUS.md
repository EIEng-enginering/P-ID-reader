# Long-term programme, phase 1 — status (12 Nov 2026)

Branch `claude/longterm-phase1` from main `2d33f05`; merged into main and pushed on 13 Nov 2026 at the owner's instruction. Software implementation, actual execution and recognition
change are three separate statuses and are reported separately below. Every model is CANDIDATE-only. Frozen R1 contract, DB v13, the .65 detector
gate and the Windows fixes (clipping, EasyOCR size cap, peak-memory reporting, `run_task(..., on_finish=...)`) are untouched.

## 1. Software implemented (infrastructure unless stated)
| File | What |
|---|---|
| `engineering/longterm/scoring.py` | Strict scorer (policy `wp07-strict-scoring-v1`): no case folding, no O/0, I/1, S/5, F/T, D/O or decimal substitution; formatting-normalised matches reported separately; MISSED vs NOT_ATTEMPTED_BUDGET; correct-alternative-with-conflict; abstention; extras only inside exhaustively reviewed regions; draft references labelled DIAGNOSTIC |
| `engineering/longterm/corpus.py` | Candidate/review/adjudication schema, named-human reviewers (software-like names refused), two-reviewer rule for validation, family/source/crop/near-duplicate (dHash)/overlap leakage checks, vertical reading direction stated by the reviewer, exports to the trainer and scorer |
| `engineering/longterm/objective.py`, `train.py` | **Bug fix with a measured effect** — see section 5: the training loss was wrong |
| `engineering/longterm/evaluate.py` | Baseline-only evaluation with a prediction cache keyed by model, dataset, preprocessing, runtime; paired evaluation; frozen pilot target and verdict; easy-control regression |
| `engineering/longterm/readiness.py`, `runner.py`, `handoff.py`, `cli.py` | Readiness gates (every gate PASS or no scheduler); target recorded in the hash-chained ledger before jobs are enqueued; pilot summary and next finite experiment in the handoff; `readiness` command |
| `engineering/longterm/bubbles.py` | Ring/interior/divider/text-band geometry with abstention (infrastructure; **no measured recognition gain**, section 4) |
| `engineering/longterm/vertical.py`, `tools/wp07/eval_configs.py` | Vertical-text budget: at most 6 regions at 90 and 270 degrees, completion and omissions reported |
| `engineering/model_lab/{adapters,core,__main__}.py` | EasyOCR letters/digits allowlist option (a decoding constraint; strings are never repaired afterwards) |
| `engineering/longterm/worker.py` | `EVALUATE_BASELINE_OCR` job; `EXPERIMENT_WP08` is blocked explicitly (`WP08_UNAVAILABLE`), never aliased |
| `engineering/longterm/data.py` | New origin `VECTOR_TEXT_LAYER` (TRAIN-only proxy data) |
| `tools/longterm/` | `build_candidates.py`, `make_review_package.py`, `adjudicate.py`, `build_textlayer_crops.py`, `make_diag_crops.py`, `diagnostic_eval.py`, `verify_controls.py`, `prepare_crops.py` (rewritten: the original imported the missing WP08 module), `Install-ScheduledRunner.ps1` (readiness-gated, duplicate-safe, refuses while a job runs) |
| Tests | 65 new long-term tests (87 in `tests/longterm`; one torch-dependent objective test is skipped in the core env and was checked against the real model instead). **Full suite on the completed integration: 1168 passed, 8 skipped, 0 failed (780 s)** |

## 2. Corpus and review readiness
- Families: TRAIN = Pembina Prairie, Pouce Coupé, NOVA/NGTL, Trans Mountain; VALIDATION = Spectra West Doe (holds S418, kept validation/diagnostic only) and Talisman. Westcoast Sikanni and Spectra Dawson were left out of TRAIN because they share a corporate parent with the S418 family. S456 was tried and excluded (its CropBox extends outside its MediaBox; the reader refuses that frame); S471 replaced it.
- 163 candidates (locations and native-resolution crops only, no readings): TRAIN 71 readable-type + 24 abstention candidates; VALIDATION 52 + 16. Consistency problems: 0 (duplicates, overlaps, near-duplicates, family leakage).
- **Native resolution:** S418 is a 1-bit 200 dpi scan (3396x2197); S035 300 dpi; S333 400 dpi. The library copies are cut unaltered from the originals, so no better scan exists locally. Enlarging adds no information.
- Blind review package: first reviewer 163 items, second reviewer 68 validation items; no readings, splits, families, drawing names or category hints (abstention items are labelled just "region"). Checked in a browser: items load, progress counts, vertical items ask for the reading direction.
- **Human-only blocker:** no named human has transcribed anything. Real-data training and the authoritative pilot verdict are blocked on that; the draft references are analyst readings and stay diagnostic. S418 line-7/line-8 in the old draft were the same printed label (IoU 0.90) — corrected in `examples/wp07/S418_reference_DRAFT_v2.json` (26 items, still DRAFT).

## 3. Jobs actually executed
- Candidate build (10 sheets, RapidOCR + RF-DETR), twice (S471 first rendered at 56 dpi because of a dpi-detection bug, fixed).
- Text-layer proxy extraction (128 sheets, 11 operator families).
- Proxy pilot through the programme runner (guarded jobs, checkpoints, ledger): candidates A (lr 1e-5) and B (lr 3e-6), 100 steps each, 25 per slice, checkpoint every 5, last decoder layer + language head, same data and seed. Peak process tree 1.50 GiB (limit 4), about 50 s per slice. Run twice: the first run is REJECTED (wrong objective, section 5); the second is the valid one.
- Control checks on Windows: pause PASS, cancel PASS, checkpoint resume PASS (synthetic machinery check; tree peak 1.19 GiB).
- No baseline-only evaluation on a reviewed corpus (none exists) and no scheduled task.

## 4. Measured recognition changes (all DIAGNOSTIC; none authoritative)
Target frozen in the ledger (event 2) before the first training slice (event 5): at least 20 % relative reduction in strict crop errors, no lost easy controls.

| Data | Baseline | Candidate A | Candidate B |
|---|---|---|---|
| Held-out proxy sample (120 degraded text-layer crops from other families) | 103 strict (17 errors), CER 0.0167 | 106 (14 errors, 17.6 % fewer), CER 0.0134 | 104 (16 errors, 5.9 % fewer), CER 0.0159 |
| S418 DRAFT crops (26 analyst items) | 7 strict, CER 0.1537 | 7, CER 0.1468 | 7, CER 0.1491 |
No easy control was lost. **Neither candidate reaches the 20 % target**, and 3 items on a proxy sample is not a significant difference. On S418 the same errors remain for every model: `S` read as `5` in `C3S`/`A3S`, `.` read as `,` or `/`, `DR` read as `OR`, a dropped `1`.
Why: the proxy data is too clean. The pretrained model already reads 86 % of it exactly, and it contains no `C3S`-style class codes or 1-bit scan breakage, so it cannot teach the S418 confusions. Per the brief, the finite plan is finished: no automatic increase in steps or search.
Other measured items: bubble geometry bands did not beat the earlier fixed crops (TrOCR 3/16 codes, EasyOCR letters-only 1/16, 1 of 13 number bands as six digits, draft reference, optimistic because the geometry was tuned while looking at those bubbles); the strict re-score of the old S418 history (26 items) gives existing 6 exact vs consensus 7, mean edit 2.67 vs 2.58 — still no demonstrated gain.

## 5. Defects found and fixed
1. **Training objective (high impact).** In transformers 4.57.1 `model(..., labels=...)` applies the generic causal-LM loss that shifts labels a second time; the trainer also prepended `<s>`, which this checkpoint never emits. On 8 strings the pretrained model reads exactly: plain cross-entropy 0.016, built-in loss 21.4, the old trainer's format 13.2 (manual) or 4.9 (built-in). Training losses near 6 for a model that reads 86 % of the crops were the symptom. Fixed in `objective.py`; checked on the real model (loss 0.041 on exactly-read strings, 0.589 on misread ones). The earlier Linux "loss decreased" evidence therefore meant nothing, and the first A/B run is rejected.
2. Text-layer extractor: stale loop variable labelled every crop with the page's last word; words merged across spaces; the same word drawn twice made one crop id overwrite another. All fixed with a position/label regression test.
3. `prepare_crops.py` imported the missing WP08 module; native-dpi detection treated small raster pieces on vector pages as the page dpi; vertical crops were rotated by a guess (now the reviewer states the direction).

## 6. Scheduler and resources
Readiness on the real state: configuration PASS, plan PASS, controls PASS, corpus FAIL (no reviewed datasets), guarded pilot / memory reporting / handoff NOT_RUN there. `Install-ScheduledRunner.ps1 -CheckOnly` refuses; **no `PIDReaderLongTerm` task is registered**. Budgets kept: 2 torch threads, 2 h/day, 30 min slice, 4 GiB tree, AC and idle start, one heavy job at a time. Measured: training slice peak 1.50 GiB, about 50 s; EasyOCR page tiles 3.96 GiB (unchanged cap).

## 7. Next finite plan
1. A named person transcribes `review_FIRST.html`; a different person transcribes `review_SECOND.html` (validation only); adjudicate with `tools/longterm/adjudicate.py`.
2. Run `EVALUATE_BASELINE_OCR` on the validation dataset, then candidates A and B (plan template in `examples/longterm/`).
3. Only then register the scheduler (`Install-ScheduledRunner.ps1`), which re-checks every gate.
If no reviewers are available: more realistic proxy data (scan-style degradation of S418-like class-code strings) is the only unreviewed lever, and it still cannot be measured on real scans.
