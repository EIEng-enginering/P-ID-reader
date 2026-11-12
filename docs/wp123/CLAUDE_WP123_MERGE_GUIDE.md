# Claude Code — integration instructions for WP01–WP03 Rev X

## Mandatory source control and safety

**Authoritative owner Windows directory:**
`C:\Users\Admin\OneDrive - Enhance Integration Engineering\Company\006 Calculation Methods\26 P&ID reader`

**Owner repo:** `https://github.com/EIEng-enginering/P-ID-reader.git`

The Windows main source used for S418 was a **newer build** (`c2935a8`) than the Rev W code used as the basis for this patch. Do not replace its directory, reset changes, force-push, or install an older database. Make a feature branch and backup, check `git status`, inspect differences and merge only compatible changes. Respect the 50 approved Option A decisions and the 5 additional approved research decisions. Preserve the frozen Worksheet R1 contract exactly.

## Merge steps

1. Inspect `WP123_MERGE_PATCH/README.md` and the patch vs the current Windows repo. Core new files: `wp123_recovery.py`, `wp123_roi.py`, `wp123_bubbles.py`, `wp123_store.py` under `src/pid_reader/engineering/`. None imports PySide6.
2. Apply/add the `recover-wp123`, `wp123-review` and `wp123-audit` CLI functionality by adapting `wp123_cli_rev_w.patch` to your **current** `cli.py` and checking its imports. The patch applies directly only to the Rev W baseline, not guaranteed to newer main.
3. Place the standalone JSON Schema under `contracts/standalone_wp123_result_v1.schema.json` and the validator under `tools/check_wp123.py`.
4. Run `python -m pytest -q` in a Python 3.12 venv with optional `pytesseract`, `opencv-python`, `pypdfium2` and `pdfplumber` (Tesseract executable and language data installed separately).
5. Use the supplied S418 input PDF and the S418 analysis's `ocr_words.csv`, `detections_record.json`. Run `pid-reader recover-wp123 ... --region-profile s418 --rois-json ... --scan-bubbles --output-dir ... --store-database ...`. Check exact input source hash and review all proposals. The ROI profile is manual and drawing-specific.
6. Integrate the resulting sidecar into the **newer** GUI as a separate unverified engineering-register tab, with evidence-to-source navigation, explicit reviewer actions and a model/region triage panel. Do not write directly to accepted engineering graph tables or host R1.
7. Add controlled S418 ground-truth annotations and report per-class precision/recall, tag string exact-match, associations, false-positive counts, abstention rates, and CPU elapsed time. The demonstration metrics are not accuracy scores.
8. Consider later offline model/SAHI integration only after licence review and a reproducible Windows inference benchmark. No mandatory retraining or remote cloud uploads.
9. Run actual Worksheet host G4–G7 integration checks and Windows PySide6/installer tests on the owner's machine; report `BLOCKED`/`NOT_RUN` if unavailable.

## Commands (adapt paths to local Windows source)

```powershell
py -3.12 -m pytest -q
py -3.12 -m pid_reader.cli recover-wp123 "C:\path\to\S418.pdf" --ocr-csv "C:\path\to\ocr_words.csv" --detections-json "C:\path\to\detections_record.json" --region-profile s418 --rois-json "C:\path\to\OPTIONAL_MANUALLY_SELECTED_ROIS.json" --scan-bubbles --output-dir "C:\work\S418_wp123" --store-database "C:\work\wp123_review.sqlite"
py -3.12 tools/check_wp123.py "C:\work\S418_wp123\wp123_result.json" --source "C:\path\to\S418.pdf"
```

The new database is **independent** of the existing project until a tested additive migration is explicitly approved. Each corrected reading must retain original OCR and source evidence, and an actor/reason entry. The program must not claim auto-approved plant connections, SIL/IPL credit, DEXPI conformance or quantitative industrial accuracy.

## Acceptance evidence and work remaining

See `docs/REV_X_IMPLEMENTATION_NOTES.md` and `TEST_RESULTS/WP123_REV_X`. Do not claim industrial symbol accuracy from the synthetic unit tests. The owner should review S418 tagged entities in the GUI before any engineering use.
