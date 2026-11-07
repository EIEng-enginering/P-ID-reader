# Rev R acceptance matrix

| Check | Status | Grounded evidence |
|---|---|---|
| Current checkout under test | PASS | Research-pack WIN-R01 source overlaid onto Rev Q project; `release_preflight` imported expected files |
| Current *live* Windows Git checkout reconciled | NOT_RUN | No authenticated live Windows repository files were edited |
| Original frozen Worksheet R1 ZIP SHA-256 | PASS | `09174700ff54cdf3bd899d952951d8969041f1a094cbe8cefff9bd714cbd25e2` |
| Local cumulative development regression | PASS | `193 passed` in `TEST_RESULTS/LOCAL_DEV_R12/pytest.txt` |
| Original reference checker | PASS | `16 passed` in `TEST_RESULTS/LOCAL_DEV_R12/original_r1_checker_tests.txt` |
| Synthetic worker and hash/schema preflight | PASS | `TEST_RESULTS/LOCAL_DEV_R12/preflight.json` |
| Dense geometry fixture >4k | PASS (synthetic only) | 5,500 observed strokes, 0 contacts, schema validation [] |
| Geometry contact completeness on real P&IDs | NOT_RUN | Real 46-sheet failure sample not available in this runtime |
| Benchmark registry storage and rights gates | PASS | 11 benchmark-focused local unit tests, no real sheets registered |
| Independent labelled 120-drawing benchmark | BLOCKED | Requires rights clearance and independent annotation |
| Windows Python 3.12, PySide6, installer | NOT_RUN | Linux test environment only |
| Actual Worksheet R1 host G4-G7 | NOT_RUN | Host checkout and its approval gates not run |
| DEXPI 2.0.1 conformance | NOT_IMPLEMENTED | No conformance test executed |
| Independent engineering accuracy/acceptance | NOT_RUN | No external gold data or independent reviewer |
