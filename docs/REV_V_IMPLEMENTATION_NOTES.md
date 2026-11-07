# Rev V — Source-linked raster centreline evidence and reviewed-only navigation

## Implemented in this coding increment

- New `engineering/raster_centrelines.py`: deterministic centreline observations formed from **already grouped, near-duplicate Hough strokes**. Direction is obtained from the longest stroke and cross-track position from source-stroke median. Every source stroke ID is retained; this does **not** establish a pipe, service, flow, loop or physical connection.
- A conservative small-gap detector tests aligned, facing endpoints separated by 2–16 rendered pixels, with lateral offset ≤2.8 pixels and angular-sine error ≤0.085. Disjoint parallel lines, X crossings, T/elbow geometry, overlaps and longer gaps are not **small-collinear-gap** detections.
- OCR/text/symbol context warnings are preserved on gap hypotheses. They do not silently discard source linework. Source positions use the already-supported CropBox/rotation-aware normalized MediaBox reference.
- Bounded spatial endpoint index and strict limits for centreline observations, candidate gaps, pair checks and serialized results; over-budget analysis refuses partial results.
- Source-linked, deterministic JSON output and `contracts/standalone_raster_centrelines_v1.schema.json`. The stored underlying raster analysis and its entire source network are recomputed and verified before a new derived analysis is accepted.
- Standalone **SQLite v12** adds immutable centreline snapshots, source-linked gap proposals, named reviews and hash-chain audit events, with pre-upgrade backup of existing v11 projects. Frozen Worksheet host R1 schema, worker, test contract and existing historical analyses are not changed.
- CLI: `analyze-raster-centrelines`, `raster-gaps`, `review-raster-gap`, `trace-raster-centrelines` and `analyze-all` pipeline integration.
- GUI-source generic finding layer: reviewable gap markers linked to PDF source coordinates; actual Windows/PySide6 runtime operation remains NOT_RUN.
- Read-only traversal may follow `CONTINUOUS_AS_DRAWN` gap reviews or `CONTACT_AS_DRAWN` raster-contact reviews **only**. `--include-unreviewed` permits exploratory navigation, explicitly tagged as provisional. Later REJECTED or SEPARATE decisions immediately remove a link from default traversal.
- A new scan-only PDF fixture and SQLite example exercise import, raster geometry, raster network and centreline pipeline. Original Rev U 244 tests retained.

## Actual verification (Linux, synthetic only)

- 257 local development tests passed, including 13 new centreline-related tests.
- 16 frozen Worksheet R1 checker tests passed.
- `tools/release_preflight.py`: source-checkout, frozen R1 hash and worker smoke validation PASS; schema/rule violations 0.
- Rev V JSON Schema syntax and representative outputs validated, and existing v11 SQLite migration backup exercised.
- A scanned PDF with deliberate disjoint strokes, parallel lines and an X intersection was rendered and visually inspected.
- The scan-only fixture produces roughly 15 raw stroke observations, 8–10 centreline families and 1–2 proposed short gaps under the tested pipeline. This variability reflects Hough fragmentation and software-dependent stroke extraction. **Do not treat this as a false-positive benchmark or proof of reconstruction completeness.**
- Repeated analysis of unchanged source/detector environment yields the same stored content-derived analysis ID in the automated integration test.

## Required qualifications and constraints

- Centreline output groups duplicate *observations*, not physically continuous piping. Even if a named reviewer marks a drawing contact, it proves only the reviewed 2D drawing appearance, not as-built plant connectivity.
- Do not infer valve bypasses, isolation segments, instrument loops, relief paths, HAZOP safeguards, SIL/PFD or IPL from these proposals.
- OCR overlap remains fallible; glyph areas and heavy linework can still generate spurious short gaps.
- No quantitative industrial recognition recall/precision, labelled drawing benchmark, Windows GUI test, Windows Python 3.12 run, actual Worksheet host integration, licence-qualified pretrained detector, installer or DEXPI conformance has been completed here.
- Avoid merging this snapshot over a newer live Windows source without an audited diff. `C:\Users\Admin\OneDrive - Enhance Integration Engineering\Company\006 Calculation Methods\26 P&ID reader` remains the owner-designated project workspace; high-write SQLite/cache should live outside OneDrive.

## Suggested next development sequence

1. Improve sub-pixel raster centreline extraction with skeletonization and multi-resolution morphology, while explicitly distinguishing source ink from derived geometry and quantifying duplicate/fragmentation rates.
2. Add independently reviewed legend/text/annotation region labelling rather than relying only on OCR word masks. Train-free configurable annotation rules; preserve source data.
3. Source-linked valve/equipment nozzle and pipe-segment port proposals, with conservative crossing and symbol-boundary semantics.
4. Evaluate pretrained OCR and symbol recognition components using rights-cleared industrial drawings; prohibit deployment claims without independent labelled accuracy evaluation.
5. Run Windows 11/Python 3.12/PySide6 real GUI, packaging, performance and Worksheet G4-G7 acceptance when host checkout and permissions are available.
