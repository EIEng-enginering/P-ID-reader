# Rev S acceptance / qualification matrix

| Gate | Evidence | Status |
|---|---|---|
| Rev R cumulative baseline preserved | Rev R source copied, original tests retained | PASS (local) |
| Offline raster line observations on scanned PDF | Synthetic scan-only fixture, deterministic analysis | PASS (synthetic only) |
| Horizontal and vertical filled-bowtie proposals | Two fixture positives detected | PASS (synthetic only) |
| Isolated arrow and X crossing negative cases | Fixture negatives not classified as filled valves | PASS (synthetic only) |
| Cropped/rotated source coordinates | Source transform validation and round-trip tests | PASS (local synthetic) |
| Standalone DB v9 to v10 migration and backup | Legacy fixture and audit tests | PASS (Linux only) |
| Named reviewer and audit immutability | SQLite triggers, hash-chain tests | PASS (Linux only) |
| Graph/source inference integrity | Raster strokes remain unclassified; no accepted R1 changes | PASS (local) |
| Frozen original R1 ZIP | Original SHA-256 invariant | PASS (verified) |
| Original R1 schema and reference tests | `TEST_RESULTS/LOCAL_DEV_R13` | PASS (local) |
| Windows 11 Python 3.12 PySide6 GUI operation | Not available here | NOT_RUN |
| Actual live Windows checkout reconciliation | No live checkout edited | NOT_RUN |
| Actual Worksheet host integration G4-G7 | Host not provided for tests | NOT_RUN |
| S023 / 46-sheet survey re-run | Original real-world examples not available here | BLOCKED |
| 120 independently annotated, legally cleared real drawings | No approved labelled corpus available | BLOCKED |
| Industrial-valve precision and recall | No independent labels or review | NOT_RUN |
| General pretrained industrial object detector | Not bundled or evaluated | NOT_IMPLEMENTED |
| Engineering acceptance and DEXPI 2.0.1 conformance | No independent conformance tests | NOT_RUN |
