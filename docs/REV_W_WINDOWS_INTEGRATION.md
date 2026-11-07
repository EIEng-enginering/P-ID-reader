# Rev W — Windows integration record (Claude, 7 Nov 2026)

Source: `PID_Reader_PreClaude_Integration_Hardening_Rev_W.zip` (ChatGPT, 0.17.0-dev0), extracted to `C:\PIDWork\staging\RevW` and compared file-by-file with this repository (branch `claude/win-r01`).

## Lineage check
Rev W is built on this repository's WIN-R01 source: 89 compared files identical (including `standalone_read.py` with the bubble re-read, `ocr_source.py`, `reports.py`, `batch.py`); 27 differ (Rev W hardening and raster work plus schema v12); 33 only in Rev W (raster_*.py, benchmark_registry.py, new tests/fixtures); 7 only here (`tests/test_gui.py`, `tests/test_win_r01.py`, ...). Nothing of the WIN-R01 behaviour was lost.

## Result on Windows 11, Python 3.12.10 (unmodified Rev W source)
227 passed, 15 failed, 35 errors, 5 skipped (ChatGPT reported 282 passed on Linux). Causes:
1. **OpenCV 5.0 incompatibility (all 50 raster failures):** `cv2.HoughLinesP` returns shape `(N,4)` in OpenCV 5 but `(N,1,4)` in OpenCV 4; Rev W indexed `[:, 0]`. RapidOCR's dependency pulled OpenCV 5.0.0.93 into this environment.
2. Old symlink test (needs Windows Developer Mode) — already fixed in WIN-R01 by a skip plus a reparse-point test.

## Changes made here (branch `claude/rev-w-integration`)
* Imported Rev W `src/`, `tools/`, new tests, fixtures, schemas, docs and the bundled Master Research Spec zip.
* `raster_geometry.py` / `raster_outlines.py`: version-robust Hough result handling (OpenCV 4 and 5).
* Kept WIN-R01 versions of `tests/test_rev_o.py` (symlink skip + reparse test, schema v12 assertions) and `tests/test_rev_q.py`; kept `tests/test_win_r01.py` and `tests/test_gui.py`.

## Result after integration
**312 passed, 6 skipped, 0 failed** (Windows Python 3.12.10, OpenCV 5.0.0). Release preflight PASS. Rev W hardening tests (hard-link no-clobber publication on NTFS, stderr flood, forged child output, parameter validation) all pass on Windows. Real-sheet regression: S023 still yields the 13 instrument tags.

## Not changed by Rev W (measured on S023)
Rev W raster valve detectors (strict synthetic filled/outlined bow-ties) find **0** valve candidates on the real S023 sheet (267 stroke candidates). Real valve recognition remains open (W-004).

## Still NOT_RUN
Live Worksheet host G4-G7; Windows Job-Object nested-job/memory-cap qualification beyond existing tests; independent real-drawing benchmark; installer on a clean machine; licence/legal review.
