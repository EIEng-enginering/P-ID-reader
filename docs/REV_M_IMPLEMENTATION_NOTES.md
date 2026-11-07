# Rev M implementation and verification notes

## Scope completed (cumulative development increment)

1. `engineering/signal_paths.py` implements a deterministic, read-only query over dashed native-PDF vector strokes. Default traversal uses **only** `CONNECTED_AS_DRAWN` geometry reviews for stroke-to-stroke joins; instrument-outline endpoints require a **separate** `SUPPORTED_AS_DRAWN` signal decision. The `include_unreviewed` option labels prospective contact edges and endpoints rather than silently turning them into reviewed evidence. Ordinary undetermined crossings cannot be traversed in the default query. This is not instrument-loop, safety function or real plant verification.
2. `engineering/project_links.py` matches only **explicitly and manually annotated** drawing connector regions. Its source hashes, selected extraction IDs, immutable annotation identifiers and versioned drawing catalogue records are retained in the proposal snapshot. Identical connector labels across two different sources create a proposal, never an accepted relationship. Multiple possible partner sheets remain alternatives.
3. `ProjectStore` adds standalone SQLite schema **v7** with append-only drawing metadata registrations, source-region connector annotations, cross-sheet candidates, named decisions and saved signal trace snapshots. Pre-upgrade database backup remains mandatory. The query `trace_drawings()` traverses only named-reviewed `LINKED_AS_DRAWN` connector pairs by default; unreviewed matches are included only upon explicit request and marked `UNREVIEWED_MATCH_PROPOSAL`.
4. The draft PySide6 interface includes a project drawing navigator, source-revision opening and a human-entered drawing registration action. GUI source compiles, but this Linux runtime does not have PySide6 installed and no Windows GUI test was performed.
5. New CLI functions: `trace-signal`, `signal-trace-snapshot`, `register-drawing`, `drawings`, `annotate-offpage`, `offpage-annotations`, `analyze-crosssheet`, `crosssheet-candidates`, `review-crosssheet`, and `trace-drawings`. New independently versioned JSON Schemas cover the signal path and cross-sheet proposals.
6. New synthetic two-instrument dashed-path P&ID; two synthetic manually annotated off-page drawings; two versioned SQLite demonstration projects with only synthetic named reviewer decisions; historic v6 SQLite fixture for actual backward migration tests.

## Verified in current environment

- Linux, Python 3.13.5: **115 pytest tests passed**, including 20 Rev M targeted tests (95 previous tests + 20 new).
- Frozen original Worksheet R1 checker suite: **16/16 tests passed**.
- Fresh native-PDF extraction checked using original R1 checker: **zero schema/contract checker violations**.
- Exact original Worksheet R1 contract ZIP SHA-256: `09174700ff54cdf3bd899d952951d8969041f1a094cbe8cefff9bd714cbd25e2`.
- Original `src/pid_reader/api.py`, `src/pid_reader/worker.py`, and the R1 JSON Schema remain unchanged from Rev L; standalone-only modules and migrations added.
- Geometry fixture PDFs rendered and visually inspected; two example SQLite stores checked for valid audit chain.
- Genuine stored v6 SQLite fixture was upgraded to v7 with backup; earlier stored extraction rows and audit remained intact.

## Limits and exclusions

- Dashed geometry plus reviewer decisions establishes only how **a supplied drawing appears**, not installed instrument wiring, a control loop, a HAZOP/LOPA safeguard or a QRA topology.
- Connector matches are human source-region annotations, **not automatic arrow/text recognition**, and matching labels do not prove physical equivalence. A reviewer must decide `LINKED_AS_DRAWN` before the accepted-only document graph traverses the pair.
- The source catalogue does not designate an automatically current, approved, as-built or superseding drawing. All source revisions remain explicit; older analysis snapshots preserve the catalogue context used at analysis time.
- Only bounded test drawings and graph sizes have been exercised; large-scale throughput, reviewed signal-service typing, multi-document plant-wide graph and DEXPI are not implemented.
- Windows Python 3.12, PySide6 runtime visual QA, exact Worksheet `.hzcase` host integrations G4–G7, independent accuracy benchmark, production CAD interoperability and model licence reviews all remain **NOT_RUN** or **NOT_IMPLEMENTED** as applicable.

## Suggested Rev N continuation

Improve true symbol recognition breadth and confidence reporting with lawful, already-trained offline models and project symbol template packs. Compare output to deterministic vector evidence rather than granting a vision model authority to classify protection functions. Add negative examples for vendor-specific valve and instrument styles and retain R1 adapter compatibility.
