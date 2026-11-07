# Claude Code — first integration acceptance checklist (Rev W)

## Authority and baseline

- Preserve the original Worksheet R1 ZIP and its exact SHA-256 (`09174700ff54cdf3bd899d952951d8969041f1a094cbe8cefff9bd714cbd25e2`).
- This package is a staged continuation of the WIN-R01 source. Inspect the *current* local Windows Git checkout before copying any file. Never discard existing modifications, merge blindly or force-push.
- The Windows project location is `C:\Users\Admin\OneDrive - Enhance Integration Engineering\Company\006 Calculation Methods\26 P&ID reader` and the Git remote target is `https://github.com/EIEng-enginering/P-ID-reader.git` (both spellings exact).
- Store working databases and scratch directories outside OneDrive. For the worker, ensure output and scratch are on the same NTFS volume because atomic hard-link publication refuses unsupported/cross-volume filesystems.

## First executable gates (record PASS / FAIL / NOT_RUN / BLOCKED)

1. Under Windows 11 / **Python 3.12**, create a clean environment and install project dependencies, preserving a requirements/lock audit.
2. Confirm Python is importing the new checkout rather than an old editable installation.
3. Run `py -3.12 -m pytest -q` from the extracted project root; expected Linux baseline **282 passed** is a reference, not a Windows result.
4. Run `py -3.12 tools/release_preflight.py` and inspect its JSON, especially `frozen_r1` and `synthetic_worker`.
5. Test worker publication on the actual intended **same-volume NTFS** scratch/output directories, including a concurrent-file collision, permissions and forced cancellation. An unsupported filesystem must produce a clean refusal rather than a partial or replaced result.
6. Verify isolated-worker stdout/stderr under OCR/PDF warnings; confirm no hang on large diagnostic output and 64 KiB tail is sufficient for failure codes.
7. Test Windows Job Object memory-cap enforcement, nested-job failure modes, kill-on-cancel and child-tree cleanup. Treat fallback without memory cap as NOT QUALIFIED for untrusted drawings.
8. Run PySide6 UI smoke tests (high DPI, pan/zoom/source overlays, review, cancellation, database backup/restore) and produce screenshots and results.
9. Run the **actual Worksheet** host G4–G7 integration and rollback tests on a permitted disposable host checkout. Do not claim host integration from local R1 checker results alone.
10. Establish a licenced, independently labelled real P&ID evaluation set and report per-class precision, recall, false confident interpretations, OCR accuracy and missed connections; retain untouched final-test drawings.

## Mandatory output to owner

- Show exact Git commit, branch and provenance of any migrated files.
- Provide actual Windows test logs and screenshots. Mark unrun gates honestly.
- Supply reproducible executable or installer only after its real Windows tests pass.
- Keep all inferred equipment, valves, piping, loops and off-page links as source-linked **review proposals**, not approved asset/HAZOP/LOPA/SIL data.
