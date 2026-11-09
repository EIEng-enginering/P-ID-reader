# ADVANCED P&ID READER - CLAUDE IMPLEMENTATION HANDOFF

**Owner authority:** Q1-Q50 Option A approved 7 Nov 2026; Q51-Q100 Option A explicitly approved 9 Nov 2026.
**Purpose:** implement the full upgrade **IN THE EXISTING SOURCE REPOSITORY**, not to propose a new product.
**Status of this delivery:** IMPLEMENTATION-READY DEVELOPMENT HANDOFF / SPECIFICATION AND SCAFFOLD. **NOT A COMPLETED UPGRADE.** No claim of application integration, Windows test, independent accuracy test, or production release is made.

## Start in this order
1. `01_CLAUDE_MASTER_IMPLEMENTATION_PROMPT.md` - paste the entire text into Claude Code.
2. `02_OWNER_APPROVAL_REGISTER.md` and `requirements/APPROVED_REQUIREMENTS_Q1_Q100.csv` - binding scope, with approved defaults.
3. `03_BASELINE_FORENSIC_INVENTORY.md` - baseline and source module API map.
4. `04_ARCHITECTURE_AND_IMPLEMENTATION.md`, `05_RECOGNITION_ALGORITHMS.md` - detailed implementation requirements.
5. `06_ENGINEERING_DATA_AND_EXPORTS.md` and `schemas/` - AI-readable model; **a standalone new extension**, NOT Worksheet R1.
6. `07_WORK_PACKAGES.md`, `requirements/IMPLEMENTATION_TRACEABILITY.csv` - implementation order and per-slice acceptance.
7. `08_BENCHMARKS_TESTS_GATES.md`, `09_WINDOWS_SECURITY_AND_LICENCES.md` - release and safety gates.
8. `10_TEST_CASES_AND_EXPECTED_FINDINGS.md`, `11_REFERENCE_RESEARCH.md`, `12_OWNER_FINAL_REVIEW.md`.
9. `16_AI_CONSUMER_PROMPT.md` - use with the exported engineering model for downstream AI.

## Baseline is really included
`baseline/Rev_X_INPUT_ARCHIVE_UNMODIFIED.zip` is an **unaltered copy** of the owner's supplied 274-entry Rev X pack. It contains a complete `source_snapshot/` tree, all original tests, historical notes, frozen Worksheet contract, existing schema documents, output evidence and independent baseline context. SHA-256: `61ca7b4acdf8fa24282e4c02de50c027175802b8b197e18cd926885bf1805636`.

**Preserve exactly** `source_snapshot/contracts/PID_READER_MODULE_REQUIREMENTS_R1_UNMODIFIED.zip`, expected SHA-256 `09174700ff54cdf3bd899d952951d8969041f1a094cbe8cefff9bd714cbd25e2`. Never rewrite its contents, tests, IDs, schema or worker protocol.

## Quick start for Claude on Windows PowerShell
```powershell
$package = 'PATH_TO_THIS_UNZIPPED_HANDOFF'
$archive = Join-Path $package 'baseline\Rev_X_INPUT_ARCHIVE_UNMODIFIED.zip'
Get-FileHash $archive -Algorithm SHA256
Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $package 'baseline\expanded') -Force
$root = Join-Path $package 'baseline\expanded\PID_Reader_Update_Pack_For_ChatGPT_Rev_X\source_snapshot'
Get-FileHash (Join-Path $root 'contracts\PID_READER_MODULE_REQUIREMENTS_R1_UNMODIFIED.zip') -Algorithm SHA256
# Compare this baseline with the ACTUAL local Git workspace before making changes.
# Never overwrite uncommitted or newer local work with the snapshot.
```

The user specifies the Windows project directory: `C:\Users\Admin\OneDrive - Enhance Integration Engineering\Company\006 Calculation Methods\26 P&ID reader`. Source may be in sync storage; active SQLite/cache/models/temp should be configured outside OneDrive. Intended Git remote is `https://github.com/EIEng-enginering/P-ID-reader.git` (the owner name spelling is exact). Confirm local/remote state, identity and permissions before any Git operation.

### Handoff preflight
Run `python tools/verify_handoff.py` from the unzipped handoff root (requires only Python 3.12 stdlib; optional `jsonschema` enables schema checks). The frozen R1 archive and root source pack must match expected hashes. Use `python tools/generate_source_map.py --source <path_to_source_snapshot>` to regenerate the module inventory. This verification checks the HANDOFF only, not the application.

### Non-negotiable
Local CPU-first, local-only drawing data, no cloud runtime, reproducible results, preserve unknowns and conflicts, all newly found data proposals only, no automatic HAZOP/LOPA/SIL/IPL/safety credit, no live Worksheet mutations, no unverified standards/model redistribution, no fabricated benchmarks.

### No artificial approval loop
Q1-Q100 are already owner-approved. Complete all reversible, in-scope work and record ADRs; only final product review is planned. Access, spending, secrets, proprietary licensing, production release, real host changes, and other separate permission gates remain separate.
