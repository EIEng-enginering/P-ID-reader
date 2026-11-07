# Rev L coding and verification notes

## Completed code

1. Separate standalone `signal_links.py`: conservatively links dashed vector-line **endpoints** to known instrument-outline candidates, with source/revision/geometry/hash lineage. A line passing through a symbol is not accepted as connected, and no signal path or loop is inferred.
2. Versioned `tag_profiles.py`: bounded configuration (no regex execution), source-linked tag alternatives, persistent profile snapshots, stable content hashes, and deterministic interpretation output.
3. PDF/OCR coordinate fix: PDFium renders visible CropBox, but pdfplumber extracts coordinates against its rotated MediaBox. `PageFrame` records both and converts OCR boxes to the common media-normalized top-left coordinate system. Source-import validation rejects altered CropBox metadata and legacy v2 observations on cropped PDFs. Checked four /Rotate values (0,90,180,270) and inspected the actual rendered 90-degree cropped drawing.
4. Standalone SQLite schema v6 with audited signal review, separate tag-profile registers and profile evaluation; backward migration and backup tests from versions 1-5. Does not touch host migration SQL.
5. CLI commands, independent JSON Schemas, synthetic tests and project fixtures.

## Verification conducted

- Linux local Python development test suite: 95 tests passed (original 74 plus 21 Rev L tests).
- Original Worksheet R1 reference test suite: 16 passed.
- Fresh synthetic PDF R1 extraction passed original checker: 0 violations.
- Exact original Worksheet R1 ZIP SHA-256: 09174700ff54cdf3bd899d952951d8969041f1a094cbe8cefff9bd714cbd25e2.
- `api.py`, worker, and the R1 JSON Schema were not changed by Rev L.

## Important limitations

- Signal candidate == graphical dashed stroke endpoint near bubble; not verified pneumatic/electric/software signalling, function, control loop or real plant connectivity.
- Symbol recognition remains conservative synthetic vector-template/outline heuristics; may miss most proprietary P&ID symbols and complex signal styles.
- Tag-profile interpretation depends entirely on supplied project conventions; it is not a calibrated confidence score.
- PDF media/crop mapping currently covers standard rotation and CropBox-in-MediaBox examples; unusual box origins, skew, malformed PDFs, non-orthogonal transforms and OCR accuracy need independent qualification.
- Older standalone OCR v2 evidence from an uncropped source is still supported; deliberately refused on cropped source to prevent silent misalignment.
- Real Windows/PySide6 UX, independent benchmark, actual Worksheet host G4-G7, offline model licensing, optional CAD and DEXPI remain NOT_RUN or NOT_IMPLEMENTED as applicable.

## Recommended next development step (Rev M)

Build persisted, explicit instrument *signal-path candidate tracing* (without auto-assuming crossings or loop functions), multi-document provenance/revision indexing and drawing-to-project navigation. Run Windows execution and broad symbol benchmarks separately when the user moves this code to their Windows machine.
