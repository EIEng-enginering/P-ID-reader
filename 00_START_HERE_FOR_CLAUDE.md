# P&ID Reader — final ChatGPT-to-Claude Code source handoff (Rev Q)

**This is the single cumulative source-code handoff.** Earlier ChatGPT ZIPs Rev G–P must NOT be separately imported or stacked on top of this package. This ZIP includes their current cumulative implementation plus Rev Q release-assurance changes, the original unmodified Worksheet R1 contract, all approved design decisions, examples, tests, recorded results and open issues.

The owner authorised routine development decisions, coding and local tests under Q1–Q50 Option A. The owner wants to inspect the finished Windows application rather than approve each work package. This does **not** authorise new charges, cloud upload of confidential drawings, bypassing permissions, unlicensed software, destructive Git actions, or modifications to a live Worksheet installation without appropriate authorisation. Independent engineering acceptance is a separate actual test/reviewer gate.

## Target identity — preserve exactly

- Windows project directory: `C:\Users\Admin\OneDrive - Enhance Integration Engineering\Company\006 Calculation Methods\26 P&ID reader`
- GitHub repository: `https://github.com/EIEng-enginering/P-ID-reader.git`
- Target Python: 3.12; optional GUI: PySide6 6.12.0. This ChatGPT package was locally tested on **Linux Python 3.13**, not Windows 3.12.
- Two deliverables: a standalone Windows engineering application **and** reusable Qt-free `pid_reader` core with R1-compatible adapter.
- Frozen Worksheet R1 contract ZIP: `contracts/PID_READER_MODULE_REQUIREMENTS_R1_UNMODIFIED.zip`, SHA-256 `09174700ff54cdf3bd899d952951d8969041f1a094cbe8cefff9bd714cbd25e2`.

## Claude: begin doing actual development, not writing only plans

1. Extract this ZIP into a **new staging directory**. Do not overwrite existing local work. Check actual Git repository status and inspect changes before integrating into the chosen source directory. Do not assume GitHub push permission.
2. Read `CLAUDE.md`, `docs/REV_Q_IMPLEMENTATION_NOTES.md`, `docs/DEVELOPMENT_STATUS.json`, `docs/OPEN_ISSUES.md`, `planning/DECISIONS_STATUS.json` and the full frozen R1 archive. Read older revision notes as history.
3. Create and use Python **3.12** isolated environment. Confirm `pid_reader.__file__` points to THIS checkout, not an old editable installation. Use `windows/CHECK_WINDOWS.ps1` for checks once dependencies are lawfully available.
4. Run `python tools/release_preflight.py` and `python -m pytest -q tests`; rerun the 16 original R1 checker tests and validate a fresh generated result. Preserve actual failure logs and fix failures.
5. Implement outstanding capabilities **as code**, not just specifications: complete Windows/PySide6 workflow and installer, hardened batch subprocess/resource caps, general model-assisted symbols where legally and technically practical, richer but reviewable graph, safe engineering exports, real host adapter integration rehearsal, independent industrial benchmark. Prioritise real usable vertical slices and keep all tests green.
6. Preserve all source-bound reading/review distinctions. No automatic HAZOP, LOPA, IPL, SIL, QRA conclusions, no assertion that a drawing describes the constructed plant, no guessed equipment attributes.
7. Do not change R1 schema v1 or the original R1 archive. Any richer data remains in standalone project interfaces; propose a separately versioned change if real host needs new capabilities.
8. Maintain append-only audit, backups, local reversible Git commits/branches, exact change/test/release evidence and reproducible package hashes. Record unresolved blockers without stopping all other work.
9. Before claiming release readiness, independently check Windows runtime/GUI/DPI, dependency and model licences/offline wheels, actual host G4–G7, field drawing gold-set accuracy, malicious PDF/cancellation, backup and recovery. Mark NOT_RUN or BLOCKED where appropriate.
10. Present **one finished-product package** to the owner for review, including installer/app, tested reusable module, sample outputs, limits and remaining risks. The current ZIP is a **development handoff**, not that final engineering-accepted product.

## Local smoke commands

```powershell
py -3.12 -m pytest -q tests
py -3.12 tools/release_preflight.py
py -3.12 -m pid_reader.cli --help
# With GUI dependencies present:
.\windows\RUN_READER_WINDOWS.ps1
```

On Linux here, local tests were run using `PYTHONPATH=src` and Python 3.13. An old editable installation is known to confuse Python subprocess imports; always isolate the target source and check it.

See `docs/RELEASE_ACCEPTANCE_MATRIX.md` for confirmed versus NOT_RUN gates. `FILE_SHA256.txt` lists SHA-256 hashes of every delivered file except itself. It establishes accidental/tamper detection for this archive, **not a trusted third-party signature**.
