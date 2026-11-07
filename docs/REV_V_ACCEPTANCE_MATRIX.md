# Rev V acceptance and evidence register

| Gate | Status | Evidence / remaining issue |
|---|---|---|
| Local unit/integration software tests | PASS | 257 passing Linux Python 3.13 tests; actual logs in `TEST_RESULTS/LOCAL_DEV_R16/` |
| Original frozen Worksheet R1 reference tests | PASS | 16 tests |
| Worker, schema, reference SHA preflight | PASS | 0 violations; unchanged frozen ZIP SHA256 `09174700ff54cdf3bd899d952951d8969041f1a094cbe8cefff9bd714cbd25e2` |
| JSON Schema | PASS | Draft 2020-12 centreline schema; source-generated example validation |
| v11 -> v12 migration and pre-backup | PASS | Automated synthetic migration check |
| Genuine scan PDF pipeline | PASS (synthetic only) | Rendered scan-only source to source-linked gap proposals; non-acceptance by design |
| Windows 11/Python 3.12/PySide6 GUI | NOT_RUN | Requires target environment and GUI test |
| Industrial P&ID recall/precision, including S023 | NOT_RUN | Rights-cleared independently labelled corpus unavailable |
| Live Worksheet host G4–G7 and database migration | NOT_RUN | Authorised actual host checkout and target runtime required |
| Standalone offline installer and bundled models | NOT_IMPLEMENTED | Windows packaging/licence testing required |
| DEXPI 2.0.1 conformance | NOT_IMPLEMENTED | Separate field mapping and semantics validation required |
| Independent engineering safety approval | NOT_RUN | Not an engineering-accepted plant model |
