# Rev K implementation and verification notes

## Code added

- `src/pid_reader/engineering/text_links.py`: strict standalone OCR evidence validation and source-linked native/OCR association candidates. Does not modify the host R1 contract. Bounded, deterministic grouping for split tag tokens; raw OCR fragments retained without accepting them as engineering tags.
- `src/pid_reader/engineering/migrations.py`: standalone SQLite schema 5 with append-only OCR analyses/word observations, text link hypotheses and named human review decisions. Existing v1-v4 projects migrate with a pre-upgrade SQLite backup.
- `src/pid_reader/engineering/project.py`: adds audited and idempotent OCR import, text link analysis, review validation, searchable OCR word list and source-linked read-only symbol evidence queries.
- `src/pid_reader/cli.py`: six new commands for importing OCR, listing words, analyzing links, listing/reviewing link candidates and reading source evidence.
- `src/pid_reader/ui/desktop.py`: draft GUI support for **persisted** OCR/link proposals, region highlighting and named text review. No heavy OCR runs on the UI thread; PySide6 UI NOT_RUN on Windows.
- New `contracts/standalone_text_links_v1.schema.json`, synthetic fixture PDF, unreviewed annotation JSON, source linkage JSON and demo SQLite database.

## Results actually obtained

- 74/74 local pytest tests PASS, Linux Python 3.13.5, including 15 Rev K tests.
- 16/16 original Worksheet R1 contract-checker tests PASS.
- New synthetic R1 PDF extraction: zero R1 checker violations.
- Frozen R1 ZIP SHA-256: `09174700ff54cdf3bd899d952951d8969041f1a094cbe8cefff9bd714cbd25e2`, unchanged from uploaded original.
- `src/pid_reader/api.py`, `src/pid_reader/worker.py`, and the frozen R1 JSON schema have identical SHA-256 contents to Rev J.
- Synthetic PDF rendered and visually inspected at 160 dpi. No independent real-P&ID recognition validation performed.

## Safety and provenance rules

Raw OCR word confidence is not an engineering reliability probability. An OCR word or tag near a symbol is a reading proposal. A verified data link does not mean a verified instrument identity, a working instrument loop, a connected physical pipeline, or an independent protection layer. Reviews name individuals who accepted *reading of a drawing revision*, never automatic plant verification. Neither R1 worker payload nor HAZOP/LOPA/QRA records are changed by these modules.

## Uncompleted gates

Windows and Python 3.12 PySide6 execution; actual Worksheet host integration G4–G7; independent 120-drawing benchmark; symbol-specific accuracy and calibrated OCR; rotated/cropped source-coordinate mapping; licence and binary-wheel redistribution; process/resource limits; DEXPI/CAD and reliable plant-level graph are all NOT_RUN/NOT_IMPLEMENTED as applicable.

## Next development opportunity

Use authentic synthetic rotated/cropped drawing fixtures to verify OCR source-to-page coordinates and extend text association to project-specific label formats; then provide reviewed typed instrument-signal relationships without inferring plant state.
