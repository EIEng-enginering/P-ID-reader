# Rev R: executable development increment, not only a specification

## Exact source baseline
This package starts from the **WIN-R01 `source_snapshot/` supplied in `PID_Reader_ChatGPT_Research_Pack.zip`**, reconciled into the fully populated Rev Q project layout so the original 175 Rev Q tests can be run. It is **not confirmed to be the user's current live Windows checkout**. No GitHub writes, filesystem changes outside the working container, or live Worksheet changes were performed. Preserve any newer Windows code and perform a three-way comparison before integration.

- Copied the newer WIN-R01 Python package under `src/pid_reader/` and its development tools, Windows packaging scripts and pinned requirements into the Rev Q cumulative source tree.
- Retained the original frozen Worksheet R1 archive untouched (`SHA-256 09174700ff54cdf3bd899d952951d8969041f1a094cbe8cefff9bd714cbd25e2`).
- One inherited Rev Q OCR test assumed a 1,000-pixel *automatic* render must refuse; WIN-R01 correctly scales automatic DPI down when a pixel limit is requested. Updated that test to use explicit 180 DPI, which must refuse the same over-budget render. This reconciles test expectations with newer behavior without changing the OCR implementation.

## Actual code developed this increment
1. **Bounded standalone geometry v0.3.** Raised the native stroke observation limit from **4,000 to 20,000**, while retaining explicit contact and output budgets. A streaming grid index processes source strokes in their original order and never builds a global pair set. Every pair is evaluated once when it overlaps at least one grid cell; contacts remain `UNRESOLVED`, not accepted pipes. If limits prevent complete evaluation, the analysis REFUSES rather than delivering a misleading partial graph.
2. **Backward compatibility.** Existing `vector-topology-0.2` results remain valid under the standalone analysis schema and runtime validator. New results declare `vector-topology-0.3-bounded-index`. R1 host extraction and worker schema were not modified.
3. **Independent benchmark rights registry.** New `src/pid_reader/engineering/benchmark_registry.py` with JSON Schema and deterministic SHA-256 register validation. Enforces documentary rights evidence for cleared sheets, independent annotations by two named reviewers for final-holdout inclusion, and prevents synthetic drawings from masquerading as real final benchmark sheets. The initial registry is empty, because this package contains no licensed or independently annotated industrial drawings.
4. **Tests and fixtures.** A newly rendered and visually inspected synthetic PDF contains **5,500 distinct isolated vector strokes**. Tested source-backed extraction of all 5,500, deterministic hashes, no invented contacts, explicit budget refusals, validation of older results, rights gates, independent verification, and atomic benchmark writes.

## Measured, not predicted
- Local runtime: Linux Python 3.13 (the user requires Windows Python 3.12 testing separately).
- `193 passed` in complete development regression suite (175 original + 18 new).
- Original frozen R1 checker suite: `16 passed`.
- Release preflight: `passed=true`, including current source import, frozen original R1 archive, worker round trip, result hashing and zero R1 schema-rule violations for the synthetic worker sample.
- Synthetic 5,500-stroke fixture: 5,500 segments, zero contact proposals (as designed), standalone validator errors `[]`.

## What these results do NOT mean
This is **not** general OCR, valve or P&ID understanding. The new geometry limit does not guarantee all 12 previously failing public drawings will now pass: the actual drawings were not provided for re-testing, and a drawing exceeding a resource budget still fails explicitly. The 5,500-stroke fixture is a stress case, not a representative industrial P&ID or an independently labelled accuracy result.

## Next work / gates
- Test original documented failed public drawings (with lawful access and labels) and record per-sheet geometry coverage and resource limits.
- Expand filled/curved geometry, tiling, native-vs-raster line separation and project-specific recognition, with independent acceptance tests.
- Source snapshot must be reconciled with actual current Windows/Git repo, which may contain newer changes.
- Windows 11 Python 3.12 and PySide6 GUI **NOT_RUN**; Worksheet host integration **NOT_RUN**; independently labelled 120-drawing benchmark **BLOCKED pending rights/annotations**; DEXPI compliance **NOT_IMPLEMENTED**; independent engineering sign-off **NOT_RUN**.

## Reproduction
```text
py -3.12 -m pip install -e .[test]
py -3.12 -m pytest -q
py -3.12 tools/release_preflight.py
```
On Linux, from this directory, the equivalent Python commands passed. The instructions above are for a fresh Windows clone; these have not been tested on that OS.
