# Windows build, security, confidentiality, licences, dependencies

## Environment and build

Target Windows 11 x64, CPython 3.12, PySide6 6.12.0, offline CPU-only default, same GUI and standalone CLI/public SDK, existing PyInstaller onedir build and per-user installer. Original Rev X `requirements-lock-win312.txt` is authoritative starting pin list; check wheel availability and full transitive licences after any update. Current source includes ONNX Runtime, OpenCV, pypdfium2, pdfplumber/pdfminer, pypdf, NumPy, Shapely and RapidOCR. Do not move working SQLite/temp/model cache into OneDrive; use local configured data/cache directory and include cleanup. Do not deploy unsanctioned model auto-downloads.

For every newly proposed dependency record: package, exact version, URL, upstream owner, code SPDX, bundled model SPDX and copyright, transitive/native DLL licenses, model provenance/SHA/weight file size, Windows x64 Python 3.12 wheel availability, CPU throughput/memory benchmark, source URL, notice obligations, shipping approval (YES/NO/BLOCKED), fallback. A component with no proven redistributable model weights can remain developer-only research, not default production dependency. SBOM and third-party notices accompany installer.

## Research-informed choices

- **Keep existing pypdfium2** for rendering unless evidence dictates otherwise. Its project uses Apache-2.0/BSD-3-Clause with PDFium BSD-style licensing and transitive licence notices; inspect wheel native licence bundle. Sources: https://pypi.org/project/pypdfium2/ and https://pypdfium2.readthedocs.io/en/stable/readme.html (accessed 2026-11-09).
- **Do not adopt PyMuPDF automatically**. It is dual AGPL/commercial, potentially incompatible with current owner permissive-only bundled requirement absent approved commercial licence. Source: https://pymupdf.io/licensing (accessed 2026-11-09).
- **Retain RapidOCR 1.4.4 baseline until benchmarked replacement**. Newer unified `rapidocr` documentation reports gradual retirement of legacy per-runtime packages; new model weights have their own attribution and hashes. See https://rapidai.github.io/RapidOCRDocs/main/en/install_usage/rapidocr/install/ and https://rapidai.github.io/RapidOCRDocs/main/en/model_licenses/ (accessed 2026-11-09). Migration is separately measured and pinned; no silent model change.
- **Optional model detection** must use a licence-cleared ONNX model with verifiable training and redistribution. Never assume training dataset licence applies to weights, or vice versa. SAHI style sliced inference may be implemented with existing code if third-party licences cleared; no need to bundle a heavyweight framework merely for tiling.
- **DEXPI 2.0.1** is the current exchange reference, released 2026-09-30, openly published under CC-BY-4.0; the schema/XSD can be used with compliance and attribution as allowed; do not blindly copy standard content. https://dexpi.org/dexpi-2-0-1-specification-published-the-update-replacing-dexpi-2-0/ and https://dexpi.org/specifications/.
- **ANSI/ISA-5.1-2024** is the latest ISA instrument symbol reference; ISA explicitly prohibits entry of its IP into AI tools without express permission. Do not paste proprietary standard pages/figures into Claude or symbol fixtures. Use original generic engineering geometry and appropriately licensed project conventions. https://www.isa.org/products/ansi-isa-5-1-2024-instrumentation-and-control-symb.
- **ISO 10628-1:2014** remains current after 2026 review, but the copyright of its text/graphics must be respected. https://www.iso.org/cms/%20render/live/en/sites/isoorg/contents/data/standard/05/18/51840.html.

## Security controls

- Local only, no network calls, analytics, update checks, calls to cloud model endpoints or telemetry during drawing processing. Optional local AI must not phone home, and network egress can be disabled for worker.
- PDFs/images/CAD files are untrusted. Parse in limited worker with bounded wall time/memory, capped pages/bytes/pixels/strokes/output; disable embedded active content, external links and unsafe archive extraction. Separate source input from chosen export path, never use drawing metadata as executable path.
- Logs omit raw client content, credentials and full local paths where avoidable; allow explicit diagnostic capture with confidentiality warning. No secret tokens/config in package, Git or sample datasets. Unreviewed source report HTML must escape embedded notes/tags; XLSX exports must neutralize formulas/links.
- Host R1 size, 500-page, 12MP and output caps remain binding. Standalone may have separate settings but may not bypass host constraints through params or model calls.
- `Get-FileHash`, versioned DB backups and safe rollback. No writes to live Worksheet case DB. Disposable host clone must be clearly separated.
- External source/model downloads, new subscriptions, commercial licences, code signing and production release require actual permissions; do not infer authorisation from Q1-Q100.

## Required real Windows checks

1. Build on exact pinned x64 Python 3.12; launch standalone GUI and CLI without Qt import side effects in core.
2. Test OCR model embedded/offline; restart with networking disabled; no auto-download; Tesseract-missing graceful fallback; false OCR success fails health gate.
3. Test PyInstaller onedir, per-user install/uninstall, launcher, models and licence notices, Windows Defender, paths with spaces/Unicode, 125/175% scaling.
4. Open large dense vector + scanned test PDFs; cancel/retry/resume; Task Manager CPU/RAM; Windows Job Object; no output to sync path until user chooses export.
5. Verify checker on frozen R1 contract in disposable host copy, no modifications to live Worksheet, no DB migration or HAZOP row writing.
6. Produce SBOM/hash and release matrix with PASS/FAIL/NOT_RUN/BLOCKED per check. Do not label installer 'ready' until applicable checks are actually run.
