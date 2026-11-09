# CURRENT INSTRUCTIONS — R5 UPDATE (adds to Rev X; supersedes nothing)

R5 update is on branch `claude/r5-program-update` (0.19.0-dev0, standalone DB still v13). Read `docs/r5_update/R5_UPDATE_STATUS.md`. Three new switches (`PID_R5_DEXPI`, `PID_R5_PAGE_FRAME`, `PID_R5_REVIEW_LEDGER`) are OFF by default; failed R5 research items (crowded matching, optical stacked OCR, general port/signal recognition) stay disabled; the DEXPI export is a proposal and never a conformance claim. All Rev X rules still hold.

---

# CURRENT INSTRUCTIONS — REV X (supersedes WIN-R01 where they conflict)

Rev X is implemented on branch `claude/rev-x-upgrade` (0.18.0-dev0, standalone DB v13). Read `docs/rev_x/HANDOFF_STATE.md`, `docs/rev_x/WPU_STATUS.md`, `docs/rev_x/OWNER_REVIEW_CHECKLIST.md`. Rules that still hold: frozen R1 contract/API/worker/schema v1; all readings are unverified proposals; no HAZOP/LOPA/SIL/IPL conclusions; stage Git paths explicitly (never `git add -A`); no pushes without the owner; never use the reserved final split; Python edits use `newline=''`; run tests with `PYTHONPATH=src`.

---

# CURRENT INSTRUCTIONS — WIN-R01 (supersedes Rev Q notes below where they conflict)

Rev Q was imported unmodified (commit b147c4f) and extended on Windows Python 3.12. Read `docs/WIN_R01_STATUS.md` (gates, limits), `docs/OPEN_ISSUES.md` (W-001…W-012), `docs/adr/ADR-WIN-R01.md`, `docs/USER_GUIDE.md`.
Rules that still hold: frozen R1 contract/API/worker/schema v1 and standalone DB v9 stay unchanged; all readings are unverified proposals; no HAZOP/LOPA/SIL/IPL conclusions; stage Git paths explicitly (never `git add -A`: `Example P&IDs/` is a 1.1 GB user library and is git-ignored); no pushes without the owner; high-write data stays outside OneDrive (`C:\PIDWork`, `%LOCALAPPDATA%\PIDReader`).
Environment: `C:\PIDWorkenv312` (Python 3.12.10, PySide6 6.12.0, RapidOCR). Commands: `pytest -q tests`, `python tools/release_preflight.py`, `python -m pid_reader.cli gui`.

---

# CURRENT INSTRUCTIONS — REV Q (overrides earlier snapshot labels below)

Read `00_START_HERE_FOR_CLAUDE.md` FIRST, then `docs/REV_Q_IMPLEMENTATION_NOTES.md`, `docs/RELEASE_ACCEPTANCE_MATRIX.md`, `docs/DEVELOPMENT_STATUS.json`, and the unmodified R1 contract. Rev Q is cumulative and complete as a **ChatGPT-to-Claude code handoff**, not a finished engineering-accepted product. Existing `CLAUDE.md` historical sections below remain for audit only. All Q1–Q50 Option A are owner-approved, normal coding and tests need no repeated signoff; never assume rights to spend, upload private drawings, rewrite the live host, break the R1 contract or push protected Git branches. Use Python 3.12 on Windows and run source-isolation preflight. Current local Linux tests and historical records under `TEST_RESULTS` do not certify Windows/industrial operation.

# Current code snapshot Rev O — important

Implement from the actual cumulative source rather than recreating it from prompts. The standalone database is v9; `engineering/symbol_catalog.py` and the template catalogue are synthetic, evidence-based and never engineering verification. 132 local tests; original R1 contract remains unchanged. No ONNX/pretrained model packaged or qualified yet. See `docs/REV_N_IMPLEMENTATION_NOTES.md`.

# P&ID Reader — Cumulative AI Coding Instructions (Rev K)

Owner-approved: ALL Q1–Q50 Option A. Build working software in tested increments without further routine design approvals. **Do not confuse successful software tests with independent P&ID engineering accuracy validation.**

Read these local files in order:
1. `README.md` and `docs/DEVELOPMENT_STATUS.json` — exactly what works and what is NOT_RUN.
2. `docs/REV_K_IMPLEMENTATION_NOTES.md`, `docs/REV_J_IMPLEMENTATION_NOTES.md`, `docs/REV_I_IMPLEMENTATION_NOTES.md`, `docs/REV_H_IMPLEMENTATION_NOTES.md` and `docs/OPEN_ISSUES.md` — latest code and outstanding problems.
3. `docs/AUTONOMOUS_DEVELOPMENT_CHARTER.md` and `docs/CLAUDE_MASTER_PROMPT_AUTONOMOUS_REV_F.md` — standing authority, complete design and limits.
4. `planning/DECISIONS_STATUS.json`, `docs/DECISIONS_APPROVED_Q1_Q50.md`, and `planning/REQUIREMENTS_TRACEABILITY_STARTER.csv` — approved decision baseline and traceability.
5. `contracts/PID_READER_MODULE_REQUIREMENTS_R1_UNMODIFIED.zip` — frozen host contract and exact output schema/hash checker.

This is REAL code in `src/pid_reader`, with tests in `tests`, synthetic drawing fixtures in `fixtures`, and a standalone SQLite project. Do not overwrite or recreate these blindly. Start by running the tests on the target Python 3.12 environment, inspect actual code, then address `docs/OPEN_ISSUES.md` in safe, recoverable work packages. Do not alter the R1 contract or claim host integration tests G4–G7 passed.

Exact user-selected project source directory:
`C:\Users\Admin\OneDrive - Enhance Integration Engineering\Company\006 Calculation Methods\26 P&ID reader`

Exact Git remote: `https://github.com/EIEng-enginering/P-ID-reader.git`. GitHub write access was not confirmed; do not assume permission to push. High-write project databases/caches should live outside synced storage.

**Core rules:** Python 3.12 pure core without Qt dependency, PySide6 6.12.0 optional GUI, offline-first, no user model training required, source/evidence-linked proposals, no automatic engineering safety approval, append-only review and audit. No silent cloud uploads, external purchases or destructive host/repository changes. User reviews the final product, not each routine coding step.

### Rev K continuation focus

Run 74 local tests (see `TEST_RESULTS/LOCAL_DEV_R05`), verify the frozen R1 ZIP and host worker are unchanged. The OCR/native text link module is standalone-only, does not change R1 extraction, and requires selected human review. Next priorities: tested rotated/cropped coordinate transforms; multi-sheet/revision identity matching; more robust symbology and line-to-instrument links; Windows GUI and independent engineering benchmark. Never traverse possible outline ports as installed plant connections.


## ChatGPT development Rev L (new)

Cumulative dev source is now `0.6.0-dev0` and standalone DB schema v6. Offline OCR standalone preview v3 has explicit CropBox/MediaBox/rotation mapping; do not assume its coordinates equal legacy v2 on cropped documents. Separate `signal_links.py` only proposes dashed stroke endpoint-to-outline contacts and needs a named human to decide whether an association is supported AS DRAWN. `tag_profiles.py` is bounded, deterministic and editable without AI training. Do not modify the Worksheet R1 host API/result/worker to accommodate these standalone features. Tests: 95 local, 16 original R1 checker, 0 fresh violations. Actual Windows/host tests not completed. See `docs/REV_L_IMPLEMENTATION_NOTES.md`.


## ChatGPT development Rev M (new)

Version 0.7.0-dev0, standalone DB schema v7. Added `engineering/signal_paths.py` (explicitly reviewed drawn-stroke traversal), `engineering/project_links.py` (manual off-page source-region annotation and source-bound match proposals), immutable drawing catalogue snapshots and v7 migration. Review mode is separate from uncertain proposal mode; do not assume a drawn label means physical plant connectivity. Added project browser source in `ui/desktop.py`, but PySide6 is NOT installed in the Linux QA environment. Linux: 115 pytest tests passed, original R1 checker 16 passed, fresh schema checker 0 violations. Exact Worker/API unchanged. See `docs/REV_M_IMPLEMENTATION_NOTES.md`.

## Rev O added modules

Standalone `engineering/batch.py` and `engineering/revisions.py` provide offline PDF batch intake and revision-reading diffs. Schema v9 is additive; the original Worksheet R1 host is unmodified. See `docs/REV_O_IMPLEMENTATION_NOTES.md` and `TEST_RESULTS/LOCAL_DEV_R09`. Complete the Windows, independent benchmark and host integration gates before claiming release readiness.

## Rev P addition — source-linked engineer workspace

Keep `engineering/workspace.py`, `engineering/reports.py` and new `ui/desktop.py` Qt tabs. They preserve immutable source evidence and read-only graph proposals. Do not turn an accepted tag observation or linked off-page drawing annotation into a verified plant connection. Report HTML/CSV/JSON are not issued engineering approvals. Run `pytest -q` (157 synthetic/Linux cases), original frozen R1 checker (16 cases), inspect `TEST_RESULTS/LOCAL_DEV_R10`, and perform the missing Windows PySide6 runtime/DPI tests before release. The next major handoff is Rev Q; existing project source must not be overwritten.
