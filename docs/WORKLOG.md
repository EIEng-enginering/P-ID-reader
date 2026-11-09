# Worklog — WIN-R01 (2026-11-07)

1. Extracted Rev Q into `C:\PIDWork\staging\RevQ` (outside OneDrive); verified R1 ZIP SHA-256; read handoff docs in the requested order.
2. Python 3.12.10 venv at `C:\PIDWork\venv312`; PySide6 6.12.0, pdfplumber/pypdf/pypdfium2/ezdxf/reportlab/jsonschema installed.
3. Baseline on pristine Rev Q: 168 passed / 3 failed / 4 skipped (175). Failures = environment (Tesseract missing ×2, symlink privilege ×1). Fixed; 16 R1 checker tests pass.
4. Copied source into the project folder (excluding generated `fixtures/*.pre-v*.sqlite` backups), `git init --separate-git-dir C:\PIDWork\git\P-ID-reader.git`, remote `origin` set (read-only `ls-remote` showed an empty repository). **No push performed.**
5. Mistake and correction: `git add -A` swept the newly synced `Example P&IDs/` (1.1 GB, public drawings; redistribution licence unknown) into two *local* commits. They were removed from local history with filter-branch before any push; folder is now git-ignored; repository 846 KB.
6. Added OCR backend, standalone reader, pipeline, isolation, findings, connectivity, GUI, tools, installer, docs (see CHANGELOG).
7. Benchmark loop found and fixed two reader defects (reversed text on /Rotate 180 pages; touching labels) and a generator defect (overlapping valve glyphs).
8. Real-library survey exposed the real limits (docs/WIN_R01_STATUS.md §3).
9. Frozen app built with PyInstaller (`C:\PIDWork\build\dist\PIDReader`, 367 MB): CLI import with OCR OK (11 s for a scanned sheet), isolated batch via frozen worker OK after the shared dispatcher fix, GUI launches.
10. Installer rehearsal (this PC, zip form, temp InstallDir): install → exe + shortcut + Apps&features key present → CLI help OK → GUI launched and stayed alive → uninstall removed exe, shortcut and key and left project data. IExpress self-extractor (`PIDReader-Setup-<ver>.exe`) built by `packaging/build_installer.ps1`; its own run was not executed here to avoid installing into the owner's real profile unprompted.
11. Final suite on Python 3.12.10: 200 passed, 5 skipped (Tesseract-binary and symlink-privilege dependent). Preflight PASS.

# Rev X upgrade (2026-11-09)
1. Package `PID_Reader_Full_Upgrade_Claude_Rev_X_Approved.zip` extracted to its own folder under `C:\PIDWork\revx_pkg`; SHA-256 of the baseline archive (`61ca7b4a…`) and the frozen R1 ZIP (`09174700…25e2`) verified; snapshot compared with local `main` @ e676ff1 (identical apart from CRLF in one planning CSV and the two historical contract ZIPs omitted from the snapshot).
2. Baseline recorded from a pristine export of e676ff1: 334 passed / 6 skipped; R1 checker 16 passed (`TEST_RESULTS/REV_X/`). An early baseline run was killed because I had started editing under it; it was repeated from the export.
3. Branch `claude/rev-x-upgrade`. Work in order: v13 migration + telemetry → regions → adaptive OCR → engineering text/tables → symbol library and tiled detection → vector linework/junctions/arrows → typed graph → loops → cross-sheet → AI export/SDK → DEXPI status → gold tooling → UI, presets, security tests → raster marks → reconciliation action → docs.
4. Mistakes and corrections: Python edit scripts first rewrote LF files as CRLF (text-mode on Windows) — fixed and all later edits use `newline=''`; migration backup file names changed with the schema bump and three tests were updated late; a too-small size ladder first missed valves 10 % off the template size, replaced by coarse-to-fine search; an arrow on a long stroke first directed every edge on that stroke, now only the part it sits on; weak symbols first created graph edges, now excluded.
5. Nothing was pushed. No drawings left the machine. The reserved final split and the real public example library were not used for tuning.

