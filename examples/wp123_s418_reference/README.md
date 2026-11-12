# S418 WP01–03 read-only worked example (unverified)

This example was generated using the owner's S418 evidence from the 12 Nov 2026 Windows analysis. The original full S418 PDF is **not duplicated in this development ZIP**. Re-run against the owner's provided source analysis ZIP. Source PDF SHA-256:
`b6b338335a3fc728adac8e631e44b43a56ec485a7403a349c2ca5a3f7621fd51`.

- 581 original RapidOCR word observations; source CSV is supplied in the separate S418 analysis pack.
- 181 additional local high-resolution Tesseract observations in three explicitly *manually chosen*, drawing-specific regions (`OPTIONAL_MANUALLY_SELECTED_ROIS.json`), for a total of 762 observations. The three regions should NOT be generalised to unrelated drawings.
- 8 unverified reading occurrences: `FE-2202`, two `FE-2206` occurrences, `V-2201` (from focused OCR), `Q-2200` as **package boundary reference**, and three complete-grammar line-number-like strings. Some line text can still be OCR-wrong and must be checked against the drawing.
- 16 additional *incomplete* piping strings, held for review only, not asserted as complete pipe numbers.
- 7 document-field candidates including distinct sheet mark `012` and drawing number `030` and conflicting date readings, all requiring review.
- 65 detector boxes triaged and preserved; none qualified for automatic model tag association. This avoids repeating the prior S418 false matches to logos/title-block text.
- 23 OCR-anchored circular geometries, 4 function-letter/geometry links, one weak code-number joint clue. None proves an instrument tag.
- 0 reviewed assets, 0 independently verified graph edges, 0 validated DEXPI exports and 0 industrial precision/recall estimates.

Deliverables: `wp123_result.json`, `proposed_engineering_register.csv`, `partial_line_number_queue.csv`, `document_metadata_proposals.csv`, `detector_triage.csv`, `instrument_bubble_proposals.csv`, `instrument_bubble_text_links.csv`, `tag_symbol_associations.csv`, `counts.json` and an *independent* `wp123_project.sqlite` containing immutable candidate evidence and no reviewer decisions. All sidecar files were produced by actual code, not manually invented.

**How to run the example on Windows:**

```powershell
py -3.12 -m pid_reader.cli recover-wp123 "C:\your\S418_cer_455653_p003.pdf" --ocr-csv "C:\your\ocr_words.csv" --ocr-source-sha256 b6b338335a3fc728adac8e631e44b43a56ec485a7403a349c2ca5a3f7621fd51 --detections-json "C:\your\detections_record.json" --rois-json "EXAMPLES\WP123_S418\OPTIONAL_MANUALLY_SELECTED_ROIS.json" --scan-bubbles --region-profile s418 --output-dir "C:\work\S418_WP123" --store-database "C:\work\WP123_review.sqlite"
```

No host R1 schema changes, no accepted engineering facts. Compare to the original scan before approving any candidate. Merging the newer Windows program remains Claude's separate integration step.
