# Rev N — Symbol Catalogue Implementation and Test Notes

## Scope implemented

The standalone, Qt-free `engineering/symbol_catalog.py` provides bounded and deterministic symbol template matching. It operates ONLY on source-verified existing R1 extraction, topology, outline proposals, and six-stroke linework proposals. It neither modifies nor extends the Worksheet R1 worker/schema.

New library features: `TAGGED_OUTLINE`, `BOWTIE_VALVE` and `BOWTIE_STEM_CIRCLE`. The original starter catalogue defines 11 conservative patterns. New project definitions are declarative JSON; arbitrary Python, expressions, regular expressions, network lookups and unsafe identifier strings are rejected. The catalogue hash and exact source-layer hashes appear in every analysis result.

The optional stemmed-valve recognition requires a linked observed solid shaft to an untagged circular outline. It does NOT assert the actual type of valve/actuator or any plant condition. In real drawings, a circular shape could be an annotation: the item remains PROPOSED_UNVERIFIED and requires human review. Negative controls include an unstemed six-stroke glyph and a dashed shaft.

SQLite schema v8 adds immutable `symbol_catalogue`, `catalog_analysis`, `catalog_candidate`, `catalog_decision`, with named audited reviewer decisions. Upgrade backs up a v7 database before migration. The CLI can register a template catalogue, create a separate analysis snapshot, list candidates, inspect catalogues and record review decisions.

## Verification in the development environment

- Linux Python 3.13.5: 132 local pytest cases pass, including the previous 115 regression tests and 17 new tests.
- Original, unmodified Worksheet R1 checker suite: 16 tests pass.
- Fresh `fixtures/synthetic_catalog_r1_extraction.json` checker: 0 violations.
- Original contract ZIP SHA-256: `09174700ff54cdf3bd899d952951d8969041f1a094cbe8cefff9bd714cbd25e2`.
- Synthetic `fixtures/synthetic_catalog_symbols.pdf` was rendered and visually inspected. This is one controlled page, not a measurement of recognition accuracy.
- Both standalone JSON Schemas validate the synthetic catalogue and result.
- A clean ZIP-extraction regression test is run when packaging; test evidence is recorded under `TEST_RESULTS/LOCAL_DEV_R08`.

## Explicit limitations / future Claude work

- NO pretrained symbol model was used, trained or packaged. The catalogue provides a practical training-free first layer; this does not meet a claim of broad industrial recognition.
- Visual-symbol definitions are only a small synthetic subset. Project drawing legends, raster-model inference, alternate vendor symbols, scaling tolerance, dense CAD line segmentation and confidence calibration remain future development.
- No independently tested accuracy claim, Windows PySide6 runtime pass, DEXPI exchange, QRA integration or real Worksheet host integration. All must retain NOT_RUN until executed.
- Do not treat classification as a confirmed physical component, valid P&ID symbol function, equipment mapping, SIL, SIF, IPL, or approved plant topology.
