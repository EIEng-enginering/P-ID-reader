# Rev P — Engineering Workspace, Drawing Graph Explorer and Reports

**Software development evidence only, not engineering validation.** Build `0.10.0-dev0`, standalone SQLite schema **v9 unchanged**. All owner Q1–Q50 defaults are approved; original Worksheet R1 contract, importable API and worker are unchanged. This increment adds no approved plant/asset/LOPA/QRA records.

## Delivered code

- `engineering/workspace.py`: Qt-free, parameterised and paginated `register_page()` with latest *drawing-reading* review state and exact source/revision hash; `drawing_graph_view()` exposing original proposed graph edges without converting reviewed endpoints into a proven connection; `crosssheet_graph_view()` with explicit source-linked proposed links and named as-drawn review state. Filters escape literal `%`, `_`, `\\` and reject unbounded offsets/limits.
- `engineering/reports.py`: deterministic, SHA-256-protected `make_report()` from a selected set of immutable extraction records and current review/catalogue entries; refuses silent record truncation and compromised audit history. `report_csv()` neutralises spreadsheet formula prefixes in source-controlled strings; `report_html()` escapes untrusted drawing metadata and text and uses only inline/offline CSS; `save_report()` uses same-directory temporary output, atomic create-only link by default and explicit `overwrite=True` for replacement. There are no safety sign-off fields or unearned plant-verification claims.
- `cli.py`: `register-page`, `graph-view`, `crosssheet-view`, `report-export`, with `--extraction-ids` scope, explicit format and explicit overwrite. Cleanly refuses existing output files.
- `ui/desktop.py`: adds a Qt `QAbstractTableModel` register page with search/review-state filters, page navigation, drawing-source selection and zoom-to-evidence; a read-only drawing-edge/cross-sheet link browser; a revision-comparison selection panel backed by existing frozen snapshots; offline HTML/CSV/JSON project report export. Existing extraction and review screens remain intact.
- **No host R1 API/worker/JSON/schema changes.** No model training or cloud operation. No DEXPI implementation or finished installer.

## Development validation performed

- Linux Python 3.13.5: **157/157 pytest tests pass** (146 Rev O baseline + 11 new Rev P tests).
- Original unchanged Worksheet R1 package: **16/16** reference checker tests pass.
- Fresh `synthetic_pid_vector.pdf` extraction: **0 R1 checker/schema violations**.
- `contracts/PID_READER_MODULE_REQUIREMENTS_R1_UNMODIFIED.zip` SHA-256: `09174700ff54cdf3bd899d952951d8969041f1a094cbe8cefff9bd714cbd25e2` (unchanged).
- `TEST_RESULTS/LOCAL_DEV_R10/` includes logs, generated R1 JSON, synthetic project HTML/CSV/JSON reports and contract hash.
- The new tests check source and review provenance, output determinism/hash tampering, spreadsheet formula escaping, HTML escaping, no silent truncation, atomic create-only outputs, graph-review separation, cross-sheet review decisions, CLI return codes and Qt-free core imports.
- `ui/desktop.py` Python syntax compilation passed. **PySide6 is not installed in this Linux runtime, so the expanded GUI has not been executed or visually QA-tested.** Real Windows/Python 3.12/PySide6 6.12.0 and multiple-DPI testing remain NOT_RUN.

## Example CLI

```powershell
python -m pid_reader.cli register-page project.sqlite --text PT-101 --state PROPOSED --limit 100
python -m pid_reader.cli graph-view project.sqlite --extraction-id ext-...
python -m pid_reader.cli crosssheet-view project.sqlite
python -m pid_reader.cli report-export project.sqlite drawing_report.html --format html
python -m pid_reader.cli report-export project.sqlite drawing_report.csv --format csv
python -m pid_reader.cli report-export project.sqlite drawing_report.json --format json --extraction-ids ext-...
python -m pid_reader.cli gui project.sqlite
```

## Outstanding limitations / Rev Q handoff

1. Running Qt/PySide6 GUI on Windows, UI responsiveness, table scrolling with 500+ drawings, source zoom and error pathways are **NOT_RUN**. Syntax compilation is not a GUI test.
2. `graph-view` exposes original **unverified** extraction edges; it does not establish process/electrical/signal path correctness. Cross-sheet matches remain as-drawn proposals, not physical-asset links.
3. CSV, HTML and JSON are implemented. PDF, DOCX, XLSX and DEXPI exports are not implemented in this increment. Do not claim they are completed.
4. Report is a deterministic view of chosen source extractions plus *latest* catalogue/review values at invocation; its SHA identifies that view. It is **not** a certified issued engineering report, and no signed export archive is implemented.
5. Standalone batch ingestion still occurs in-process; no hostile-document sandbox/resource-isolation qualification. Original host R1 G4–G7, independent accuracy benchmarking, final installer, model licence reviews and Windows integration are **NOT_RUN**.
6. Rev Q should focus on an honest Claude handoff, independent build/test reproducibility, host contract audits, broader test fixtures, and a properly separated checklist of tasks that require the target Windows environment and actual qualified drawings. Do not silently claim advanced unimplemented algorithms are finished.
