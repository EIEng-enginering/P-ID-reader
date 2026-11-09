# Benchmark, validation and release acceptance protocol

## Historical baseline is not an accuracy claim

The owner's Rev X source says Python test suite 334 PASS/6 SKIPPED on Windows, synthetic 90 DEV/30 reserved FINAL, initial synthetic tags 1582/1582 but valve and topology misses concentrated in scanned sheets. Earlier public survey 46 completed/47 attempted (unlabelled), 12/46 hit geometry stroke cap and only 12/46 had named assets. None is a measured independent engineering-accuracy benchmark. Another source includes later improvement on S023 to 13 instrument tags but no robust valves. Keep all historic evidence labelled by exact version and date; don't conflate.

## Gold and split governance

1. Preserve the source's 90 synthetic development / 30 reserved final drawings; **DO NOT examine the reserved final drawings to tune, choose thresholds, amend taxonomy or write examples**. No arbitrary reallocation after model development. If original split cannot be verified, pause use of the final data and create a new unexposed holdout using a documented process.
2. Create new synthetic variations with original-generated geometry for vector, vector-outline fonts, pure raster, low resolution, rotation, crop, table, bubbles, actuation, nozzles, signal styles, multiple line specs, overlaps, bridged crossings, offsheet, revision clouds. Each fixture includes unambiguous and intentionally ambiguous cases. Do not include paid standard tables/vendor examples without rights.
3. Establish independently annotated real development corpus only from legitimately accessible/licence-cleared drawings. Annotation must be separated from algorithm predictions, include two named reviewers for critical graph facts and adjudicated conflict notes. Public sheet != licensed redistribution, nor does unlabelled public sheet imply evaluation gold.
4. Hold a separate independent real evaluation set blind to detector tuning and prompt engineering. Record acquisition source, drawing hashes, sampling strata and project/operator leakage prevention; connected sheets of same project stay in one split.
5. Allow an annotation UI that draws bounding boxes/port locations and classifies evidence/unknown; gold format includes class, bbox tolerance, directed typed graph edges, OCR tokens verbatim, metadata fields, offpage links and annotator disagreements.

## Metrics with denominator and scope

For every input stratum and class, record TP, FP, FN, precision TP/(TP+FP), recall TP/(TP+FN), F1, per-class support, unlabelled/unreadable/unsupported counts and 95% uncertainty interval where justified; no metric with zero denominator reported as 100%.

- OCR: token exact, character error, end-to-end field value exact/near-match, reading-order/table-cell assignment; include outlined vs native vs scan.
- Detection: per-class AP/mAP at IoU threshold, precision/recall for instrument, valve, equipment, actuator, symbol and annotation. Big vs tiny objects separately.
- Tag attachment: exact tag to correct occurrence; false merge and unassigned rate; near-miss matched by text but wrong component is a **failure**.
- Piping graph: junction type (T/crossing/dot/bridge), correct port attachments, typed-edge exact precision/recall, false connected components, topological path connectivity; wrong crossing join is a critical FP.
- Loops/control: correct loop grouping with explicit source edges, no invented logic, class-specific supported set, abstention.
- Specs/metadata: setpoint vs design vs operating, exact raw and normalized units, nozzle schedules/table row associations.
- Coverage: proportion of annotated applicable items retrieved, unprocessed raster-region fraction, silent miss rate. **Never call an unlabelled apparent sheet complete merely because no candidates remain.**
- Calibration: ECE/Brier/ reliability only for outputs with true calibrated probabilities and held-out calibration set id; ordinary raw symbol likelihood labelled `UNCALIBRATED`.
- Runtime: p50/p90/p99 wall time, peak RSS, tile count, OCR model load, worst-case per-page latency, Windows normal CPU + 175% DPI UI; record machine exact hardware and input hash.

Historical owner target gates from baseline master: critical symbols P>=98% R>=95%; tag exact >=98%; critical connectivity P>=99% R>=95%; proposed loop P>=98%; silent critical misses <=1% for supported clean/vector classes. **These are predeclared targets, NOT observed results.** Stratify and declare defensible thresholds for scans and unsupported symbols before independent test. Report upper/lower confidence as appropriate; do not loosen critical thresholds without new owner authorisation if binding.

## Four independent gates

| Gate | What must be demonstrated | Failure / unknown condition |
|---|---|---|
| G-SW software | Python 3.12/Windows 11, full pytest, frozen R1 checker, schema, migrations, security, worker limits, GUI, package signing/install as applicable | Mark NOT_RUN if real Windows not used, and no PASS if suite timed out |
| G-EXT extraction | Independent annotated real validation with measured per-class accuracy and silent-miss controls; operator-vetted supported class/style list | No real gold/reviewer => NOT_RUN; synthetic PASS does not grant this gate |
| G-HOST Worksheet R1 | Byte-identical original contract and checker; disposable copy of current Worksheet host tested against specific host version and current schema | No host copy or G4-G7 rehearsal => NOT_RUN; live host never modified |
| G-ENG independent | Qualified human engineering review of sample interpretations and exception handling, no plant-as-built claim | AI self-review does not count; owner still approves final production release |

## Required automated tests per work package

- Baseline regression tests and R1 schema/version checksum.
- Positives, negative confusers and unknowns for each new symbol/tag/graph class.
- Different page rotations and CropBoxes, disappearing text fonts and SVG-to-PDF conversion.
- Dense geometry >4000 vector strokes; render images with 1-pixel gaps/bridges and atypical crossed lines.
- Case `OCR_DISABLED`, `OCR_ENGINE_UNAVAILABLE`, `OCR_RUNTIME_EXCEPTION`, `ZERO_WORDS_WITH_INK`, `PARTIAL_TILE_FAILURE`, `OCR_WORDS_DROPPED_IN_EXPORT` with different diagnostics.
- Worker subprocess cancellation at each stage, memory/time caps, page count, PDF size, malformed PDF, zip bombs if import archive supported, Windows path traversal, formula injection into Excel and HTML escaping.
- Additive migration from DB v12, interruption, rollback via backup, review hash chain tamper detection, source-revision binding, stable IDs across reruns.
- Native/scan tests on actual selected non-secret drawings only where permitted and independently annotated; never train on reserved final.

## Test evidence artifact

For each command output `{command, git_head, env, run_utc, duration_ms, passed, failed, skipped, expected_failures, stderr_excerpt_redacted, input_fixture_sha256, result_sha256}`. For hardware-dependent checks record CPU/RAM, model versions/hashes. Keep `TEST_RESULTS/` and machine-readable gate statuses. `NOT_RUN` and `BLOCKED` are distinct from `FAIL`.
