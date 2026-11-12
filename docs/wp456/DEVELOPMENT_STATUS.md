# Development status and evidence

## What was actually executed here

- The new independent unittest suite, including real local Tesseract on a
  synthetic printed label, and negative/ambiguity/provenance tests.
- Compilation of every new Python module, test and tool.
- S418 replay from all 760 supplied OCR observations, the supplied WP123 result,
  23 circle hypotheses, 65 detector decisions and 353 existing centrelines.
- A separate bounded real Tesseract experiment over automatically proposed
  regions, preserving every observation, pass, rotation and diagnostic.
- Additive installer check/application/idempotence against a temporary Git
  repository containing the exact supplied main-window snapshot. This is NOT
  a run of the user's full program. See recorded smoke results.

Exact local environment and results are in `evidence/validation_summary.json`,
`test_results.txt`, `replay/replay_summary.json` and `installer_smoke.json`.

## Observed S418 behaviour

The source PDF hash is
`b6b338335a3fc728adac8e631e44b43a56ec485a7403a349c2ca5a3f7621fd51`.

| Item | Supplied baseline | New replay |
|---|---|---|
| Tag/line readings | 8 | 8 |
| Document-field rows | 7 | 6: duplicate NTS merged, both OCR sources preserved |
| Instrument circles | 23 proposals | Preserved as unverified ring/text evidence |
| Detector boxes | 65, none reviewable | All retained; gate unchanged |
| Symbol/tag links | 0 | 0 in this actual drawing replay |
| Geometry input | 353 existing centrelines | 353 geometry edges with UNKNOWN line kind |
| Accepted engineering objects / connections | 0 | 0 |
| Accuracy | No exhaustive approved reference | NOT_RUN |

The added real OCR experiment did not recover reliable better line numbers or
bubble identifiers in the tested bounded regions. It added noisy observations
without changing the eight baseline readings. Consult its exact log for counts
and timings; do not treat OCR word volume as extraction quality.

The 353 geometry edges are a new structured *representation of existing*
centrelines, not 353 newly detected pipes or known connections. Unknown strokes
remain isolated for connectivity purposes. Borders, annotations and equipment
outlines may be present. Crossings/tees/overlaps are unresolved.

## Coverage and remaining work

| Area | Implementation | Qualification / remaining work |
|---|---|---|
| Deduplication | Implemented, tested, NTS improvement observed | More drawings with adjacent repeated labels |
| Automatic re-read | Implemented, real engine exercised | Better crop selection/preprocessing for S418; Windows CPU benchmark |
| Line repair alternatives | Observed conflicting strings only; tested | Actual S418 character recovery remains unsolved |
| Bubble code/number joining | Same-pass, interior, aligned, code-above-number; tested | Actual S418 FR/720201 recovery remains unsolved |
| Benchmark scorer | One-to-one exact text/location matching, per class; tested | Named exhaustive reference and unseen drawing set |
| Symbol classification | Existing qualified-for-review detector route, ring route and named manual proposal route | General automated equipment classifier not implemented/trained |
| Association | Compatible classes, physical distances, ambiguity and competition abstention; tested | No correct association gain established on S418 |
| Calibration | Training-only study, gate never lowered; tested | Independent labels and held-out validation |
| Geometry | Conservative graph engine, port/junction input and unresolved conditions; tested | Automatic reliable line-type, port and dot recognition not implemented |
| Export / integration | Separate JSON/CSV sidecar, source digests and review chain | Canonical project graph, R1 host mapping and DEXPI integration not implemented by this pack |
| Windows UI | Additive tab and three-hunk hook; syntax checked | PySide6 runtime, DPI, navigation, tasks, installer not run here |
| Regression | New isolated suite passed | Full actual current-repository suite not available here |
| Engineering qualification | None claimed | Independent benchmark and host gates outstanding |

## Important limits

The runtime here is Linux; see its recorded Python version. Python 3.12 on
Windows and PySide6 6.12.0 are target checks, not assumed passes. The actual live
GitHub repository has not been fetched. No repository, host or project database
was modified. Source code in `src/` is the new additive implementation.

A hash chain can reveal accidental or some deliberate edits. It cannot prove a
reviewer identity or prevent a privileged administrator rewriting the entire
file and its hashes. Preserve filesystem access controls and backups.
