# Rev U acceptance gates

| Gate | Evidence | Status |
|---|---|---|
| Rev T baseline and Rev U cumulative local regression | `TEST_RESULTS/LOCAL_DEV_R15/pytest.txt` | PASS — Linux synthetic |
| New raster-network pure geometry cases (endpoints, T, crossings) | `tests/test_rev_u_raster_network.py` | PASS — synthetic |
| Hough duplicate grouping and preserved source IDs | test + scan-only synthetic fixture | PASS — synthetic |
| OCR false-positive does not erase possible connections | local Tesseract fixture test | PASS — synthetic |
| Pixel/source frames, CropBox and rotation | simulated and rendered-page tests | PASS — development |
| SQL v10 to v11 backup and append-only review | migration and audit tests | PASS — Linux |
| CLI/pipeline/source-linked generic GUI findings | automated core and CLI tests | PASS — GUI not executed |
| JSON Schema and content-hash derived result verification | schema and re-computation tests | PASS — local |
| Original Worksheet R1 contract and generated extraction | frozen checker and release preflight | PASS — local |
| Windows 11 / Python 3.12 / PySide6 live usage | Windows unavailable | NOT_RUN |
| Real industrial scan precision, recall, completeness | No independently labelled authorised dataset | BLOCKED |
| S023 and 46 public sheets re-run | Original source sheets unavailable here | BLOCKED |
| Actual Worksheet host G4-G7 and installer | Host/Windows unavailable | NOT_RUN |
| Independent engineering acceptance and DEXPI | No independent evidence | NOT_RUN |
