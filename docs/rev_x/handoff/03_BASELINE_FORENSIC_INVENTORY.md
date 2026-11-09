# Rev X forensic baseline - use before changing code

**Verified by inspection of supplied ZIP, not by a new clean Windows installation.** The input pack `02_CURRENT_STATE_REV_X_BASELINE.md` describes `0.17.0-dev0`, branch `main` at commit `e676ff1`, Windows 11 + Python 3.12.10, PySide6 6.12.0, SQLite standalone schema v12, RapidOCR 1.4.4 ONNX optional Tesseract, and `334 passed / 6 skipped` on its recorded baseline run. Historical files such as `docs/DEVELOPMENT_STATUS.json` contain **older** snapshot results and are superseded by the explicit Rev X baseline where they disagree.

The supplied ZIP has **274 entries**, including `source_snapshot/src/pid_reader`, `source_snapshot/tests`, `source_snapshot/contracts`, tools, packaging, planning, evidence, and prior prompt documents. This pack embeds the source ZIP without alteration and includes an automated inventory below.

## Known factual defects in current exports
- Supplied S025 (scanned-looking P&ID) JSON: `ocr.word_count=0`, no readings, no semantic graph; raster contacts 671 (357 T candidates, 186 endpoint touch, 128 crossings) and 17 gaps are all unresolved. This is NOT proof of an empty engineering drawing.
- Supplied S023: output in the owner's standalone conversation shows notes, unlabelled lines and ~35 symbol outlines; original Rev X forensic notes record that at a later processing stage S023 yielded 13 OCR tags, still zero standard valve classes without manual teaching. These reports reflect **different builds/analysis stages**. Do not present them as one contemporaneous benchmark result.
- Zero OCR can reflect an untriggered stage, unavailable model, model failure, preprocess loss, job timeout, or OCR results discarded during pipeline/report conversion. A diagnostic event trace is required before concluding the cause.
- The pack says initial synthetic dev benchmark was saturated and real gold acceptance remains NOT_RUN.

## Hard freezes
- `api.read_pid` signature and schema v1, worker CLI/protocol, canonical JSON/SHA256, deterministic IDs, CropBox/rotation mapped top-left normalized bboxes and source-revision binding.
- Worksheet R1 requirement archive exact checksum `09174700ff54cdf3bd899d952951d8969041f1a094cbe8cefff9bd714cbd25e2`; inspect every PR-* requirement and run its **original** checker.
- No direct Worksheet project/case/HAZOP/LOPA writes; no modification of live host. Standalone richer schema must have separate version, endpoint/adapter.
- DB v12 cannot be retroactively rewritten. Use additive v13+ migrations, backups and downgrade/rollback tests.

## Code modules and integration anchors
See `requirements/SOURCE_MODULE_MAP.csv` automatically extracted from source AST. Do not assume every module implements its intended feature: e.g. `engineering/dexpi.py` deliberately refuses, and existing raster network generation is detection-only. Exact `pipeline.py` stages and DB migrations must be reread before implementation.

## Baseline test status in this handoff environment
A Linux baseline `PYTHONPATH=src python -m pytest -q tests` run was attempted in this container. It reached visible progress through about 87% but **the process exceeded the allotted execution timeout** before a summary, so its final status is `NOT_COMPLETED/TIMED_OUT`, not PASS. The owner's *supplied* 334/6 is cited only as baseline evidence. Claude must rerun actual baseline tests in the authoritative Windows 11/Python 3.12 environment before touching code.

## Git and storage
Local project: `C:\Users\Admin\OneDrive - Enhance Integration Engineering\Company\006 Calculation Methods\26 P&ID reader`; intended remote: `https://github.com/EIEng-enginering/P-ID-reader.git`. Check actual local Git branch, commits, uncommitted work and remote permissions; never overwrite newer edits with the snapshot. Use local nonsync AppData for active DB/caches/temp and explicitly user-selected export directories. No cloud runtime.
