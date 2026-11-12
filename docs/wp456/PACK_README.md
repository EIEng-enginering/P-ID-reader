# P&ID Reader WP04–06 development and Claude merge pack, Revision A

Prepared 12 November 2026. Additive source, tests, three-hunk GUI hook, replay
fixtures and measured development evidence. This is executable development
work, not an engineering-qualified release or a claim of completed accuracy.

## Start

1. Give this ZIP to Claude Code in the actual P&ID Reader repository.
2. Ask Claude to read `CLAUDE_START_HERE.txt` completely and execute its merge
   and acceptance instructions. The owner has authorised local development.
3. Claude must merge into the current repository, run the full suite and
   perform Windows acceptance. It must not replace whole older source files.

## What is implemented

| Pack | Executable development implementation |
|---|---|
| WP04 | Evidence-preserving OCR deduplication; automatic bounded re-read regions; local Tesseract UTF-8 TSV, rotations, time/call/cancellation budgets; evidence-only line alternatives; same-run instrument code/number reading; exact-string/location benchmark scorer; standalone review/audit sidecar. |
| WP05 | Detector withholding preserved; instrument-circle geometry route; named reviewer symbol-class proposals; compatible, physical-distance associations with competition/ambiguity abstention; training-only threshold calibration study. |
| WP06 | Straight-segment geometry graph; known line-type separation; explicit junction splitting; unresolved crossings, tees, overlaps, gaps and ambiguous ports; existing centreline/stroke read adapter; source-hashed proposal exports. |
| Windows | Separate tab, background tasks, Tesseract availability message, selected-proposal or automatic re-read, opt-in circle scan, layout control, review/correction, class proposals, geometry envelope import, CSV/JSON export and audit check. |

Tesseract is the optional local OCR executable. The new region module invokes
it directly with PNG bytes and UTF-8 TSV output; it does not require
`pytesseract`, change the system PATH, download a model or use a network.
English language data must already be installed with the executable.

## What is not demonstrated or delivered as a completed capability

- No newly trained/calibrated universal equipment or valve detector.
- No automatic trustworthy classification of scanned strokes as process/signal.
- No automatic extraction of reliable equipment ports or junction dots.
- No accepted plant connectivity, inferred flow direction, off-page continuity,
  engineering verification, HAZOP/LOPA/SIL/IPL writes or safety credit.
- No change to frozen Worksheet R1/schema v1/API/worker or standalone DB v13.
  WP456 export is a separate proposal envelope; R1 output integration remains
  a future host change requiring its actual contracts and acceptance tests.
- No approved exhaustive S418 or held-out accuracy reference. The annotation
  seed remains DRAFT, and the scorer refuses to turn it into an accuracy score.
- No full current-repository, real Windows GUI/DPI/installer or host G4–G7 test
  in this work area. The GUI source is syntax-checked, not runtime-certified.

## Run checks in this extracted pack

```text
python tools/run_wp456_checks.py
python tools/replay_s418.py --output replay_output
python tools/replay_s418.py --output replay_output --with-ocr
```

Core algorithms use Python standard library only. OCR/image checks need Pillow;
PDF replay needs Pillow and pypdfium2. Host adapter reuses pdfplumber, PDFium and
the existing PageFrame implementation. GUI requires the target PySide6 6.12.0.
No dependency lockfile or installed program is changed by this pack.

Test logs, replay summaries and result envelopes are under `evidence/`.
The real Tesseract test is skipped only if its executable or a suitable test
font is absent; skips must be disclosed in the target machine report.

## Merge helper

```text
python tools/install_wp456.py PATH_TO_REAL_REPOSITORY --check
python tools/install_wp456.py PATH_TO_REAL_REPOSITORY --apply
```

The helper copies new `src/` and `tests/` Python files only and applies the
three small GUI hook hunks. It refuses differing destination files. It does
not commit, push, migrate a database or alter the frozen host contract.
Use a feature branch. If the actual repository has moved, merge the three
hunks manually and run its full checks. Tools/contracts/docs may be copied
under a new documentation directory, preserving existing files.

## Provenance

The supplied handoff describes repository main `c0908b9`. That live revision
has NOT been fetched or independently verified here. The GUI patch is against
the attached `source_new_files/main_window.py` snapshot; baseline file hashes
are recorded in `evidence/source_snapshot_sha256.json`.

The standalone reference `evidence/reference_wp123_recovery.py` is an unchanged
copy of the supplied handoff's recovery module, for replay only; NEVER copy it
over the live module. Only the new package and the small GUI hook are changes.
