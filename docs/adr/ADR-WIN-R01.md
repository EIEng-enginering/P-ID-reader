# Architecture decisions — Claude Windows increment WIN-R01 (2026-11-07)

Each entry: decision, alternatives considered, reason, rollback.

## ADR-1 Source layout, Git and high-write data
* **Decision.** Source lives in the OneDrive project folder as requested; the Git directory is a *separate git dir*
  (`C:\PIDWork\git\P-ID-reader.git`, `.git` file points to it). Venv, caches, temp, benchmark corpora, build output and survey
  results live under `C:\PIDWork\`. Default project databases: `%LOCALAPPDATA%\PIDReader\projects`.
* Alternatives: `.git` inside OneDrive (sync corruption risk); whole repo outside OneDrive (breaks the stated location).
* Rollback: `git init` normally in the folder and fetch from the separate dir.
* Note: `Example P&IDs/` (user-supplied public drawing library, 1.1 GB) is **git-ignored**. An early local commit accidentally
  staged it; that local, never-pushed history was rewritten to remove it before any push (nothing was published).

## ADR-2 OCR backend: add RapidOCR beside Tesseract
* **Decision.** `formats/ocr_source.py` gains `engine = tesseract | rapidocr | auto`. RapidOCR (PP-OCR models via ONNX Runtime,
  Apache-2.0, pip-installable, no system install, no network at run time) is the default on a clean Windows machine.
* Alternatives: require a Tesseract installer (admin rights, extra dependency); EasyOCR/PaddleOCR (PyTorch/Paddle, huge, licensing
  review); cloud OCR (forbidden: confidential drawings).
* Consequences: line-level OCR is split into word boxes proportionally (`split=PROPORTIONAL_FROM_LINE` on each word);
  words carry `engine=local_rapidocr`; text-link validation accepts both engines. Raw scores are *not* calibrated.
* Rollback: use `--ocr tesseract` or `--ocr off`.

## ADR-3 Scanned drawings: a standalone reader beside the frozen R1 reader
* **Decision.** `engineering/standalone_read.read_pid_standalone` = frozen `read_pid` + OCR for pages the native reader refused. Output keeps
  R1 schema 1 (checked in tests), marks OCR objects (`attributes.source=OCR`, confidence capped 0.55) and lists OCR model files with SHA-256 and
  licence in `provenance.models`. `api.read_pid` and the Worksheet worker behaviour are unchanged (R1 still refuses image-only pages).
* Alternative: change `read_pid` — rejected, it would silently alter the frozen contract.

## ADR-4 Process isolation for readers
* **Decision.** `engineering/isolation.py` runs the (R1 or standalone) worker as a child process with wall-clock timeout, cooperative cancel,
  Windows Job Object (per-process memory cap, kill-on-close) / POSIX `RLIMIT_AS`, private scratch removed by the parent.
  No process-count cap (venv launchers spawn a child). Evidence: tests kill a 1.5 GB allocation under a 512 MB cap.
* Limits: a resource wrapper, not a security sandbox (child keeps user permissions); AppContainer/low-integrity not done.

## ADR-5 Desktop UI rewritten as a new package, old viewer kept
* **Decision.** New `pid_reader/ui/{app,main_window,tabs,viewer,graphview,tasks}.py` on the Qt-free engineering API; background `Task` threads with their own
  `ProjectStore` per thread; `ui/desktop.py` kept as `pid-reader gui-legacy` for audit. A shared `findings.py` layer is the single review path.
* Alternative: extend the 800-line monolith — rejected (no threading, no zoom, one-off review calls per layer).

## ADR-6 Connectivity graph = proposals, drawn at page positions
* **Decision.** `engineering/connectivity.py` builds a bipartite graph (symbols/valve glyphs ↔ line networks) from stored analyses. Crossings and collinear
  overlaps never join; tee junctions join but are flagged; valve glyphs pass paths through but state/flow are never asserted.

## ADR-7 DEXPI disabled
* **Decision.** `engineering/dexpi.py` refuses (`NOT_IMPLEMENTED`). A file that only resembles DEXPI would be trusted wrongly; prerequisites are typed, reviewed
  connectivity and a schema/semantic validator run. Rollback: n/a (nothing exported).

## ADR-8 Installer
* **Decision.** PyInstaller one-folder build (GUI + console exes) → per-user PowerShell installer packaged as a Windows IExpress self-extractor, plus zip form.
  No admin rights, no network, uninstall keeps data. Inno Setup/WiX not installed here; no code signing (unsigned binaries trigger SmartScreen).
* Alternative: MSI via WiX (tool not available; would need installing system software).

## ADR-9 Synthetic benchmark programme
* **Decision.** `tools/make_benchmark_corpus.py` (120 generated drawings: vector, rotated 90/180, cropped, scanned; exact truth; 30 `final` reserved with logged access) and
  `tools/score_benchmark.py`. Labelled *developer, not independent*. Real public drawings are used only for robustness/performance surveys (no labels exist).
