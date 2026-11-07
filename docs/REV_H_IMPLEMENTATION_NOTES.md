# Rev H — new development slice (0.2.0-dev0)

**Status:** Early development; no plant or engineering validation. All approved Q1–Q50 Option A decisions remain binding. The original Worksheet R1 ZIP and host result schema/hashing functions are unchanged.

## Implemented since Rev G

- **New standalone `engineering/topology.py`:** reads actual native PDF stroke endpoint coordinates (including diagonals), distinguishes 2D endpoint touch, candidate T-branch, unresolved mid-stroke crossing and collinear overlap. Tags dashed/solid stroke appearance and proposes near-circular closed shapes only as graphics, never as instruments automatically. Produces deterministic evidence locations, explicit unresolved status and a content hash. Limits are bounded, excess complexity is refused rather than truncated.
- **Separate geometry contract:** `pid-reader-standalone-topology-v1` is NOT an R1 host result or a physical pipe network. It contains only drawing-level candidates; reviewed geometric contacts never establish actual plant connectivity.
- **Standalone database v2 migration:** additive tables `geometry_analysis`, `geometry_candidate`, `geometry_decision`; append-only triggers, indexes, audit hash chaining, automatic consistent pre-v2 backup for existing databases. No Worksheet database changes.
- **Human review of contact candidates:** `CONNECTED_AS_DRAWN`, `NOT_CONNECTED_AS_DRAWN`, `UNRESOLVED`, `REJECTED`, all reasoned, named, time-stamped and append-only. The distinction between 'shown as connected on paper' and 'connected in the physical plant' is explicit.
- **CLI:** `analyze-topology`, `topology-candidates`, `review-topology`, `backup-project`.
- **GUI draft:** extra tab for geometry candidate review, page highlighting and reviewer decisions; remains untested on Windows/PySide6.
- **Tests and examples:** synthetic geometry intersection PDF + expected deterministic analysis JSON; local test suite expanded to 34 passing tests, original R1 checker 16 passing tests.

## Example commands (after installation, or set PYTHONPATH=src)

```powershell
python -m pid_reader.cli init-project project.sqlite
python -m pid_reader.cli import-pdf project.sqlite fixtures\synthetic_pid_vector.pdf
# Copy the extraction_id from the printed JSON:
python -m pid_reader.cli analyze-topology project.sqlite <extraction_id> --output-json topology.json
# Copy the analysis_id from the printed JSON:
python -m pid_reader.cli topology-candidates project.sqlite <analysis_id>
python -m pid_reader.cli review-topology project.sqlite <candidate_id> --actor "Engineer A" --decision NOT_CONNECTED_AS_DRAWN --reason "Lines cross without a junction dot"
python -m pid_reader.cli backup-project project.sqlite project_backup.sqlite
python -m pid_reader.cli gui project.sqlite
```

Note: angle brackets in the above commands indicate fields to replace, not literal syntax. For the tested Linux environment, `PYTHONPATH=src python -m ...` is sufficient. The interpreter in the development environment was Python 3.13; Windows Python 3.12 and PySide6 6.12.0 compatibility are untested.

## Known limitations and next engineering work

1. None of the geometric candidate categories proves process-pipe connectivity. The native vector extraction still includes drawing borders and drafting lines; semantic disambiguation and port-to-object matching remain open.
2. No symbol detector, full nozzle/valve/loop interpretation or plant-wide entity matching yet.
3. Raster pages remain refused in the host R1 extraction. Optional Tesseract OCR preview is not yet integrated into the standalone review model.
4. Touch tolerance (1.5 PDF points) and stroke/circle heuristics are development defaults requiring calibration on independent benchmark drawings, not validated industrial parameters.
5. Geometry analysis uses same 16-MiB/500-page safety budget as the initial slice, not a production-ready standalone scaling profile.
6. No full Windows/PySide6 UI acceptance, real host integration rehearsal, model licence review, or independent accuracy benchmark. Worksheet G4–G7 remain NOT_RUN.
7. Host worker scratch/output folder protocol remains an open R1 issue; no claim of drop-in module acceptance.

## Verification performed

- 32 local unit/integration tests PASSED on Linux Python 3.13.
- 16 original independent R1 checker tests PASSED.
- Generated R1 JSON example checker: zero violations.
- R1 contract archive SHA-256 unchanged from original.
- Real synthetic PDF test rendered and visually inspected.
- Standalone CLI smoke: PDF import, geometry analysis, candidate listing, database integrity/audit and backup.

Neither the R1 checker nor the synthetic tests prove accurate engineering interpretation of real-world P&IDs.
