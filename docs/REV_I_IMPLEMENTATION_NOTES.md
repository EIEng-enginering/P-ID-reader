# Rev I — implementation and verification notes

## Actually coded

1. Independent deterministic `build_symbol_proposals(extraction, topology)` stage, with stable shape-linked candidate IDs and strict replay validation.
2. Class hypotheses: closed near-circle with a single centred instrument tag; rectangle with a single centred known equipment tag; multiple-centred-tag ambiguity; unclassified outline.
3. Proposed outline port contact only when a **solid/unknown** native vector segment endpoint lies near a shape boundary. Dashed or dotted strokes do not create these port proposals.
4. A separate standalone symbol-v1 JSON Schema. Worksheet R1 remains unmodified.
5. Standalone schema v3: immutable proposals, separate named human review decisions, audit event entries and backup-before-migration from v1/v2.
6. CLI analysis/list/review commands and draft PySide6 symbol overlay/review tab.
7. Offline Tesseract preview v2: source hash, normalized word coordinates, unique IDs, engine metadata, content hashing and bounded rendering. This is still a standalone OCR preview, NOT host extraction or calibrated AI recognition.

## Local evidence

- `TEST_RESULTS/LOCAL_DEV_R03/pytest.txt`: 46 passed.
- `TEST_RESULTS/LOCAL_DEV_R03/r1_original_checker.txt`: 16 original checker tests passed.
- `TEST_RESULTS/LOCAL_DEV_R03/r1_fresh_checker.txt`: 0 violations for freshly extracted synthetic PDF with v0.3.0-dev0 metadata.
- `TEST_RESULTS/LOCAL_DEV_R03/r1_frozen_contract_hash.txt`: exact uploaded R1 ZIP digest verified.
- `TEST_RESULTS/LOCAL_DEV_R03/ocr_preview.json`: local Tesseract produced four unverified word observations from a raster synthetic drawing.
- `fixtures/synthetic_symbols_ports.pdf`: visually rendered and inspected. Candidate test annotations in `fixtures/synthetic_symbol_gold_intent.json` are synthetic author intent, not an independent benchmark.
- `fixtures/symbol_demo.sqlite`: standalone schema v3 sample project, not plant data.

## Important limitations

No training of any P&ID-specific model is required for these tests. No verified valve symbols, physical connectivity, SIL, HAZOP/LOPA conclusions or facility semantics are computed. The Worksheet host worker remains a development adapter; G4-G7 integration gates are NOT_RUN. No Windows GUI or Python 3.12 environment acceptance has been performed. No dependency/model licence distribution evidence or independent 120-drawing benchmark has been delivered. See `docs/OPEN_ISSUES.md`.

## Next coding increment recommendation

Improve source-linked line-vs-signal recognition and P&ID valve glyph proposals, convert selected geometric contacts into typed but still unverified graph propositions, and preserve standalone OCR evidence in the project database. First add difficult synthetic negative cases and independently defined class-specific test fixtures.
