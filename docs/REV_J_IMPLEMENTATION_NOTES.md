# Rev J — Implementation and verification notes

## Actually coded

1. `engineering/linework.py`: conservative deterministic valve-bow-tie six-stroke recognizer, two orientations, explicit negative cases, proposed inline stub endpoints and source-linked IDs.
2. Vector line roles: `VALVE_GLYPH_STROKE`, `SIGNAL_STYLE_CANDIDATE` for native dashed strokes, and `SOLID_UNCLASSIFIED_LINEWORK`; no process or instrument functionality is asserted.
3. Unresolved mixed-style intersections preserve geometry contact evidence but do not create connections.
4. `engineering/drawing_graph.py`: exact provenance, user-reviewed `CONNECTED_AS_DRAWN` contacts only by default; optional uncertain graph mode never includes `NOT_CONNECTED_AS_DRAWN` or `REJECTED`. Valve glyph strokes never become traversable pipes.
5. Standalone SQLite migration v4 (existing v1/v2/v3 projects supported with pre-upgrade backup), immutable linework snapshots, review candidates, append-only review decision and hash-chained audit events.
6. CLI and provisional PySide6 linework panel added. GUI source compiles; no Windows/PySide6 runtime test.
7. Synthetic test vector PDF (`fixtures/synthetic_valves_line_styles.pdf`) visually rendered, inspected, and accompanied by separate author-intent JSON, standalone result JSON, initial database, and R1 output.
8. `contracts/standalone_linework_v1.schema.json` validates new separate linework output; frozen R1 schema/output unchanged.

## Test evidence

- `TEST_RESULTS/LOCAL_DEV_R04/pytest.txt`: 59 local Python tests PASS (Python 3.13 Linux).
- `TEST_RESULTS/LOCAL_DEV_R04/r1_original_checker.txt`: 16 original R1 checker tests PASS.
- `TEST_RESULTS/LOCAL_DEV_R04/r1_fresh_checker.txt`: 0 violations on synthetic extraction using the frozen R1 schema.
- `TEST_RESULTS/LOCAL_DEV_R04/r1_frozen_contract_hash.txt`: exact uploaded original requirements ZIP verified.
- `fixtures/rendered_valves/page-1.png`: visual QA of synthetic drawing; not real industrial P&ID validation.

## Limitations

A six-stroke symbol resemblance is NOT evidence of a valve type or a working valve in a facility. Dashed strokes might represent many drawing conventions; they are not accepted instrumentation. Connected-as-drawn means an engineer judged the source ink, not that the plant is connected. No trained model, full instrument loop, calibrated confidence, real plant data, independent engineering benchmark or Worksheet host G4-G7 integration is included. The original host R1 extraction payload is frozen and does not contain any of the new linework fields.

## Next suggested increment

Persist standalone OCR evidence by source revision with explicit coordinate transforms, project profile handling and tests on rotated/cropped pages; follow with reviewed instrument/line association and graph capability upgrades. Avoid any claims of actual plant connectivity.
