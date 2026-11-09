# Independent gold annotation guide (Rev X, WPU-16)

Purpose: produce ground truth that can honestly measure the reader. **This guide describes a process the owner must run; nothing in this repository has been independently annotated or measured.**

## Rules that make the numbers meaningful
1. **Annotate from the PDF at readable zoom, never from the reader's output.** An annotator who has seen predictions is no longer independent.
2. **Two named annotators for every critical fact** (valves, instruments, equipment, connections). Disagreements go to a named adjudicator; the file is `ADJUDICATED` only after that.
3. **Splits.** `TRAIN`/`DEV` may guide development. `REAL_INDEPENDENT` is held out: never used to tune thresholds, grammar, prompts or templates. `FINAL_RESERVED` (the 30 synthetic reserved drawings) is never examined or scored by routine work; each use is logged.
4. **Keep a project together in one split** (sheets of the same project or operator do not straddle splits).
5. **Rights.** Only annotate drawings you are entitled to use for this purpose. A public drawing is not licensed for redistribution. Do not put client content in this repository.

## What to annotate (`benchmark-gold-v1`)
* `objects`: one per drawn thing -- `kind` (VALVE, INSTRUMENT, EQUIPMENT, ...), a tight `bbox` (normalised page fractions, top-left origin, after rotation/CropBox), the printed `tag` verbatim or `null`, and `review_state`: `GOLD_VERIFIED`, `GOLD_AMBIGUOUS` (two readings are defensible), or `NOT_LEGIBLE`.
* `edges`: `GOLD_CONNECTED` / `GOLD_NOT_CONNECTED` / `AMBIGUOUS` between two annotated objects *as drawn*. Mark deliberate crossings that do not join as `GOLD_NOT_CONNECTED`; these test the reader's most dangerous failure.
* `regions`: mark areas you did not annotate (`UNANNOTATED`), cannot read (`UNREADABLE`) or that are `OUT_OF_SCOPE` (title block graphics, legends). Predictions inside such regions are *unscored*, not false positives.

## Tooling
```
python tools/gold_tool.py new SHEET.pdf annotator_a.json --annotator "A. Name" --split DEV
python tools/gold_tool.py validate annotator_a.json
python tools/gold_tool.py agree annotator_a.json annotator_b.json     # lists disagreements for adjudication
python tools/gold_tool.py score adjudicated.json project.sqlite <extraction_id> --stratum vector_native
```
`score` reports TP/FP/FN with denominators and 95 % Wilson intervals per class, tag attachment (a wrong tag on the right symbol is a failure), connectivity recall, critical false connections, and **silent misses** (a missed critical item with no flag at all). A zero denominator is shown as `null`, never 100 %.

## Reading the result
`claims.accuracy_claim_allowed` is `true` only for adjudicated `REAL_INDEPENDENT` gold with at least two annotators. Everything else is `REGRESSION_ONLY`. Targets (critical symbol precision >= 98 %, recall >= 95 %; critical connection precision >= 99 %, recall >= 95 %; silent critical misses <= 1 %) are **targets**, not results.
