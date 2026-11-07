# Rev Q — release and engineering acceptance matrix

| Gate | Evidence/status as of 7 Nov 2026 | What remains |
|---|---|---|
| Rev Q Linux software regression | PASS when reported by `TEST_RESULTS/LOCAL_DEV_R11/pytest.txt` | Rerun on Python 3.12 and Windows |
| Frozen original R1 archive integrity | PASS: SHA-256 `09174700ff54cdf3bd899d952951d8969041f1a094cbe8cefff9bd714cbd25e2` | None for archival integrity; live contract still to rehearse |
| Original R1 reference checker | PASS only after recorded execution in `TEST_RESULTS/LOCAL_DEV_R11/original_r1_pytest.txt` | Does not constitute host integration |
| Synthetic R1 extraction + canonical result hash | PASS only after recorded preflight and checker outputs | Real drawings / live host untested |
| Complete file SHA-256 manifest + clean ZIP verification | PASS only after running and recording build checker | Does not replace code signing |
| Real Python 3.12 Windows runtime | NOT_RUN | Run `windows/CHECK_WINDOWS.ps1` on Windows 3.12 |
| PySide6 6.12.0 GUI, DPI 100/125/150%, keyboard, cancellation | NOT_RUN | Windows desktop integration/visual and UX verification |
| Windows installer/offline wheel distribution/licence approvals | NOT_IMPLEMENTED / NOT_RUN | Build, licence-audit and sign/distribute permitted dependencies |
| Standalone batch worker CPU/memory isolation and cancellation | NOT_IMPLEMENTED / NOT_RUN | Existing batch import is in-process |
| Independent industrial P&ID symbol/tag/connectivity precision/recall benchmark | NOT_RUN | Obtain lawful gold drawings, independent reviewer; predeclare metrics |
| General pretrained offline vision detector | NOT_IMPLEMENTED | Candidate model/licence selection and qualification |
| Genuine valid DEXPI 2.0.1 interchange / proprietary CAD adapters | NOT_IMPLEMENTED | Build actual adapters and check against interchange validators |
| Live Worksheet R1 host G4–G7 | NOT_RUN | Actual host install, API/migration/audit, rollback and independent host tests |
| Independent functional-safety and process engineering review | NOT_RUN | Named reviewer, separate evidence and independent checks |
| Final user acceptance | NOT_RUN | User reviews completed usable product after Claude work |

Software tests are not independent engineering verification. These are source-document reading proposals only, never proof of physical plant configuration or fitness for safety decisions.
