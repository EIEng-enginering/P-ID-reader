# Rev T acceptance gate matrix

| Gate | Evidence | Status |
|---|---|---|
| Rev S cumulative regression | 216 inherited tests + Rev T tests | PASS — Linux synthetic |
| Plain horizontal outlined bow-tie | scan-only fixture and v2 schema | PASS — synthetic |
| Vertical outlined bow-tie | scan-only fixture and orientation test | PASS — synthetic |
| Central ring is observed without assuming valve type | synthetic ring + separate style | PASS — synthetic |
| Rejection of plain X, crossed rectangle, filled-only glyph | positive/negative fixture tests | PASS — synthetic |
| Long sloped strokes retained as UNKNOWN evidence | raster stroke test | PASS — synthetic |
| Existing v1 raster evidence still validates | saved standalone v1 JSON | PASS — local |
| Source hash, canonical candidate IDs and audit | tamper and ProjectStore tests | PASS — local |
| Rotated/cropped PDF bounding boxes | 90/270-degree source tests | PASS — local |
| Full scan-only analysis pipeline | `analyze_drawing` with 3 outlines, no host mutations | PASS — local |
| Original Worksheet R1 archive unchanged | SHA-256 `09174700ff54cdf3bd899d952951d8969041f1a094cbe8cefff9bd714cbd25e2` | PASS |
| Frozen original R1 tests and schema checker | 16 tests and zero R1 violations | PASS — local |
| Windows 11 Python 3.12 / PySide6 GUI | Windows not available | NOT_RUN |
| Original live WIN-R01 checkout reconciliation | No live Windows checkout accessed | NOT_RUN |
| Industrial scans: S023, 46-sheet survey | Original source PDFs unavailable | BLOCKED |
| 120 independently labelled industrial drawings | Not supplied/independently labelled | BLOCKED |
| Industrial recognition precision/recall | No independently labelled corpus | NOT_RUN |
| General pretrained vision model | Not bundled or benchmarked | NOT_IMPLEMENTED |
| Full Worksheet G4–G7 integration | Live host not available | NOT_RUN |
| Independent engineering acceptance and DEXPI | Formal engineering conformance tests absent | NOT_RUN |
