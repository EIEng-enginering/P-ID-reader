# Paused — where things stand (7 Nov 2026)

## State of the code
* `main` (pushed to GitHub) = latest tested version: 328 tests passed, 6 skipped. The installed program (`%LOCALAPPDATA%\Programs\PIDReader`, desktop shortcut "P&ID Reader") is built from it.
* Branch `wip/ocr-engine-fix` (LOCAL ONLY, not pushed, **full suite not yet run**) fixes the error the owner hit:
  `S333_cer_2935633_p004.pdf: PID_WORKER_FAILED ... (exit 4)`.

## Cause of that error (confirmed)
The app's saved OCR engine setting was **Tesseract**, which is not installed on this PC. Scanned (image-only) sheets such as S333 need OCR, so the reader process crashed
(exit 4 = unexpected exception) and the message hid the reason. Vector sheets don't need OCR, so they were unaffected. The same sheet imports fine with "Automatic" or "RapidOCR"
(51-61 s; ~500 MB peak memory — it was NOT a memory problem).

**Workaround in the installed program now:** Tools → OCR engine for scanned pages → *Automatic* (or *RapidOCR*), then re-import S333.

## What the WIP branch changes
* `standalone_read.py`: an explicitly chosen engine that is not installed raises `PID_OCR_ENGINE_UNAVAILABLE` instead of crashing.
* `isolation.py`: readable messages for known refusal codes; unexpected errors report the exception type (and `PID_MEMORY` for MemoryError).
* `main_window.py`: a saved-but-missing engine falls back to Automatic with a status message; the Tools menu greys out engines that are not installed.
* Tests added: unavailable-engine refusal (direct and isolated), vector sheet unaffected, GUI fallback. The 3 new tests passed; the full suite and the end-to-end check below were interrupted.

## To finish
1. `git checkout wip/ocr-engine-fix`; run `pytest -q tests` (expect ~331 passed) and `python tools/release_preflight.py`.
2. Re-run the scenario: set OCR engine to Tesseract in a fresh settings file, import S333 in the app → should import (engine falls back to Automatic).
3. Merge into `main` (fast-forward), push, rebuild (`packaging/pid_reader.spec` via PyInstaller into `C:\PIDWork\build\dist`), re-package and reinstall with `packaging/Install-PIDReader.ps1`.

## Other open items
* Installer files in `Release\WIN-R01\` are out of date (rebuild with `packaging/build_installer.ps1`, ~10 min).
* GitHub default branch may still be `claude/win-r01`; switch to `main` in repository settings.
* Not done (see `docs/WIN_R01_STATUS.md`): DEXPI, independent benchmark, legal/licence review, Worksheet host tests, real-sheet valve recognition without teaching.
* Demo project: `%LOCALAPPDATA%\PIDReader\projects\demo-final-180811.sqlite` (File → Open project).
