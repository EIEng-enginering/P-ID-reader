# Merge and acceptance checklist for the developer

## Baseline and file placement

Work in a feature branch. Check current working changes first. The only patch
to an existing program file adds an import, a tab and its drawing-reset hook to
`src/pid_reader/ui/main_window.py`. All other source files are new:
`src/pid_reader/engineering/wp456/` and `src/pid_reader/ui/wp456_tab.py`.
New tests live in the distinct `tests/wp456/` package, avoiding collisions with
existing test module names. Do not copy replay reference code over live code.

Keep baseline, new modules and replay evidence separate. The pack includes an
installer that refuses differing destination files. Review the patch even if
`git apply --check` succeeds. Adapt only where current host APIs differ.

## Checks after merging

1. Run the isolated new suite with Python 3.12. Run the entire repository test
   suite using the repository's own documented commands and environment.
2. Load a raster drawing with stored OCR. Build proposals with and without
   circles. Confirm words/detections/geometry are read on the GUI thread and
   no host SQLite connection enters the worker.
3. With Tesseract absent, click Re-read: show the availability message, leave
   existing analysis intact. With Tesseract installed, test PATH, TESSERACT_CMD
   and the normal Windows installation location without changing system PATH.
   Verify English language data. Test missing language/error diagnostics.
4. Select a reading/field/circle row and re-read its source region. With no
   selection, check the automatic region list. Region scheduling must balance
   bubbles, lines, tags and title clues so circles do not exhaust every call.
   Region count/pixel/total-time limits and omissions must remain visible.
5. Cancel during OCR. No accepted objects or host writes may appear; busy state
   releases on result/error/stopped. Partial diagnostic output may be retained
   only as proposals. Change page/drawing during a task: stale worker results
   must not populate the new page/drawing.
6. Double-click a row with a source bbox: navigate to and highlight the correct
   page. Test 100/125/150/200% DPI and multi-monitor scenarios in Windows.
7. Test uncropped, offset MediaBox, CropBox and 0/90/180/270-degree PDFs. Compare
   displayed evidence boxes to the printed source. Test crop partially/fully
   outside visible page and an oversized selected region. Compare PDFium and
   PageFrame dimensions; never silently mix render and media coordinates.
8. Confirm metadata duplicates merge only at the same printed occurrence.
   Separate FE-2206 occurrences and conflicting FR/FQ readings must stay apart.
   Original OCR members/IDs/pass/rotation remain inspectable.
9. Correct a printed reading with named reviewer/reason. Reject a false one,
   leave another unresolved. Geometry cannot be accepted with the printed-text
   action. Verify append-only chain, reopen/export it, and test invalid input.
10. Select an actual symbol candidate box and propose a class with named reason.
    Rebuild. Check manual class evidence remains distinct from detector output.
    Two competing labels/symbols must abstain. General/low-score detector boxes
    are never silently promoted by a lower runtime threshold.
11. Import a source-hashed geometry proposal envelope. Check same-page known
    line types, junction/port evidence, unknown strokes, signal/process separation,
    dot-free crossings, T contacts, duplicate overlapping strokes and gaps.
    No gap repair, process-flow direction or off-page continuity may be assumed.
12. Export JSON/CSV and review records. Test spreadsheet formula-leading values,
    including leading whitespace before a formula sign. Confirm there is no
    standalone DB migration, R1 host write or accepted engineering record.

## Benchmark workflow

The scorer measures per-class text/localisation outcomes only in explicitly
exhaustive class/page scope. Tags outside that scope are excluded, not false
positives. Matching is one-to-one, with geometry overlap plus typography-normalised
text equality (case/whitespace/dash typography; no O/0 or digit substitutions).
Duplicate predictions count as false positives. Empty denominators are null.
`score_associations` requires mappings from independently measured endpoints.

- Complete and independently check the DRAFT S418 annotation. Find missing
  items on the full page; do not just mark the eight proposals as exhaustive.
- Record annotator/reviewer, date, source hash, class/page scope and version.
- Keep independent held-out drawings separate from threshold training. The
  supplied calibration report does not assess missed symbols and cannot change
  the runtime gate. Use the exhaustive scorer to assess detection recall.
- Report normalised exact-string precision/recall, false positives, misses,
  unresolved/withheld counts and CPU time. Association scoring needs object
  mappings; graph validation needs independently annotated ports/junctions/edges.
- No reference = NOT_RUN. Passing synthetic tests is not drawing accuracy.

## Open release gates

Full repository suite, real Windows GUI/DPI and installer, frozen-build checks,
Worksheet host G4–G7, held-out accuracy, independent engineering benchmark and
any DEXPI validation remain separate gates. Provide PASS / FAIL / NOT_RUN /
BLOCKED plus evidence and reason. The owner reviews engineering acceptance;
routine local coding and tests do not require repeated sign-off.
