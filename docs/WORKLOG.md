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
