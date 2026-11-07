# P&ID Reader — how to run and evaluate it (Windows, Python 3.12 build "WIN-R01")

> **Read first.** The software reads what is printed on a drawing revision and proposes interpretations. Nothing it
> shows verifies the plant, a drawing's currency or as-built status. It never approves safeguards, assigns SIL,
> establishes IPL independence or accepts HAZOP/LOPA findings. Accuracy on industrial drawings has **not** been
> independently measured (see `docs/WIN_R01_STATUS.md`).

## 1. Install

**Installer:** run `PIDReader-Setup-<version>.exe` (or `Setup.cmd` from the Setup zip). It installs for the current user only
(no administrator rights, no network) to `%LOCALAPPDATA%\Programs\PIDReader`, adds a Start-menu shortcut and an
Apps-and-features entry. Uninstall from Apps & features; your project databases are never deleted.

**From source (developers):**

```powershell
py -3.12 -m venv C:\PIDWork\venv312
C:\PIDWork\venv312\Scripts\python.exe -m pip install -r requirements-lock-win312.txt
$env:PYTHONPATH = "<repo>\src"
C:\PIDWork\venv312\Scripts\python.exe -m pid_reader.cli gui
```

Keep project databases **outside OneDrive** (default: `%LOCALAPPDATA%\PIDReader\projects`); frequent SQLite writes in a
synced folder can conflict with sync.

## 2. First session (about five minutes)

1. *File → New project…* (Ctrl+N). Enter your name when asked — it is recorded on every review decision.
2. *File → Import PDF(s)…* (Ctrl+I) or *Import folder…*. Each PDF is read in its own time- and memory-limited process.
   Scanned (image-only) sheets are read with the bundled offline OCR (RapidOCR); change under *Tools → OCR engine*.
3. The drawing opens in the **Drawing** tab. Mouse wheel zooms, drag pans, `0` fits, `PgUp/PgDn` change page.
   Coloured boxes are layers (tick them at the top): text readings, symbols, valves/lines, template matches, tag links, line contacts.
4. *Drawing → Analyse open drawing* (F5) runs geometry, symbols, valves, template matching, signal-style strokes, OCR and tag↔symbol links.
5. Right panel **Findings**: choose a layer, select a row (the viewer zooms to it), press *Review selected…* (Ctrl+Enter)
   and accept / reject / leave unresolved with a reason. Decisions are append-only and hash-chained (Audit tab → Verify).
6. **Registers** tab: equipment, valves, instruments, piping-line labels, notes across the whole project; filter, page, accept/correct/reject
   readings (the original text is always kept), export the current view to CSV.
7. **Graph** tab: proposed drawn-line connectivity at the real page positions (symbols, valve glyphs, line networks; tee junctions flagged).
8. **Revisions**, **Batch import** (progress, cancel, resume), **Libraries** (site tag profile and symbol template catalogue as editable JSON —
   *configuration, not model training*), **Reports** (HTML/CSV/JSON), **Audit** (event list, chain verification, backup).

## 3. Command line and Python

```powershell
pid-reader-cli init-project p.sqlite
pid-reader-cli import-pdf p.sqlite sheet.pdf --ocr auto          # --ocr off = refuse scanned pages (frozen R1 behaviour)
pid-reader-cli analyze-all p.sqlite <extraction_id>
pid-reader-cli batch-import p.sqlite C:\drawings --actor "Your Name"   # isolated children; --in-process to disable
pid-reader-cli report-export ...  /  backup-project ...
```

Python (Qt-free): `pid_reader.api.read_pid` (frozen Worksheet R1 contract), `pid_reader.engineering.standalone_read.read_pid_standalone`
(adds OCR), `pid_reader.engineering.pipeline.analyze_drawing`, `...findings.list_findings/review_finding`,
`...connectivity.drawing_connectivity`, `...isolation.read_pid_isolated`, `...batch.start_batch/resume_batch`.
Worksheet worker: `python -m pid_reader.worker run --input … --params … --output … --workdir …` (unchanged protocol).

## 4. How to evaluate it honestly

* Use `Example P&IDs\library` (608 public sheets) for *robustness* — does it open, how long, what fails. Do **not** read counts as accuracy.
* `tools\make_benchmark_corpus.py` + `tools\score_benchmark.py` reproduce the synthetic regression benchmark (120 drawings, 30 reserved).
* For real accuracy you need an independent reviewer and labelled drawings; the harness is ready for that, the labels do not exist yet.
* Known gaps are listed in `docs/WIN_R01_STATUS.md` and `docs/OPEN_ISSUES.md` — notably dense vector sheets, scanned-sheet symbols/valves, and everything NOT_RUN.

## 5. Backup and recovery

*File → Back up project…* (or `backup-project`) writes a consistent SQLite copy. Opening a project from an older schema creates a
`.pre-vN-<timestamp>.sqlite` copy beside it first. To recover: close the app, copy a backup over the project file, reopen, then
*Audit → Verify audit chain*. Every import, analysis and decision is an audit event; a broken chain is reported in red.
