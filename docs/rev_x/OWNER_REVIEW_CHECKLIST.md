# Owner final-review checklist — Rev X upgrade (0.18.0-dev0, branch `claude/rev-x-upgrade`)

This is a **development candidate for your review**, not a released or engineering-accepted product. Four gates are kept separate; passing one never implies another.

| Gate | Status | Evidence / what is missing |
|---|---|---|
| **G-SW** software (Python 3.12, Windows 11, tests, R1 checker, migrations, GUI) | See `TEST_RESULTS/REV_X/final_*.json` | Full suite, frozen-R1 checker (16), preflight and migration/restore tests recorded. Offscreen GUI tests pass. **Not done:** manual GUI review (175 % DPI, keyboard-only), clean-machine install, code signing. |
| **G-EXT** extraction accuracy | **NOT_RUN** | No independently annotated real drawings and no second annotator exist. Synthetic tests prove behaviour, not accuracy. The 30 reserved synthetic drawings were never touched. |
| **G-HOST** Worksheet R1 copy | **NOT_RUN** | No hash-verified host copy was available. R1 contract, `api.read_pid`, worker and schema v1 are byte-identical (ZIP SHA-256 `09174700…25e2`). |
| **G-ENG** independent engineering review | **NOT_RUN** | Nothing here has been reviewed by a qualified engineer. No safety, SIL, IPL or HAZOP/LOPA conclusion is produced anywhere. |

## What you can try (about 15 minutes)
1. Install/open the app. **Tools ▸ Analysis depth** (Quick / Standard / Deep). Import a drawing, then **Drawing ▸ Analyse**.
2. **Quality tab:** is the status honest? A scanned sheet with OCR off must say `INCOMPLETE` with a blocker, never "0 found, success".
3. **Layers ▸ Library symbols:** boxes for valves/instruments/equipment. Select one, **Review** (named reviewer + reason). Unknown classes show as "class withheld".
4. **File ▸ Export open drawing as AI package…** (folder picker every time) and **Export … as files…** (JSON/HTML/graph, numbered if present). Nothing is written on import.
5. **Tools ▸ Reconcile sheets** on a project with two related sheets (needs printed drawing numbers and "TO/FROM DWG …" text).
6. CLI: `pid-reader-cli analyze-all DB EXTRACTION --depth quick`, `export-intelligence`, `export-ai-package`, `reconcile-sheets`, `tools/gold_tool.py`.

## Things to decide or provide (not assumed)
* Labelled real drawings and two named annotators (guide: `GOLD_ANNOTATION_GUIDE.md`) — without these no accuracy statement is possible.
* A disposable copy of the Worksheet host for G4–G7.
* The official DEXPI 2.0.1 XSD (licence/source checked) and an XML-schema validator, if DEXPI export is wanted.
* Legal review of dependency licences (`THIRD_PARTY_NOTICES.md`: PySide6/Qt LGPL, PyInstaller, OpenCV bundles FFmpeg); code-signing certificate.
* Whether to push `claude/rev-x-upgrade` and to which branch (nothing was pushed).

## Known limits, in one list
Valve/equipment detection uses original shapes at matching scale; real drawings with different glyphs will be missed or marked "class withheld" (teach-by-example still works). Raster pages get symbols, dots and arrows but **no port-to-port graph**. Line numbers are not yet structured records; nozzle schedules and fittings are not extracted; flow is known only where an arrow lies on the drawn line. Cross-sheet matching needs printed drawing numbers on both sheets. DEXPI export is **disabled**; a mapping report replaces it. No local LLM is included or called; the AI package is for you to use as you decide, and it carries a prompt that forbids over-claiming.

See `WPU_STATUS.md` and `REQUIREMENTS_TRACEABILITY_REV_X.csv` (Q1–Q100: approved decision vs implementation state) for the full account.
