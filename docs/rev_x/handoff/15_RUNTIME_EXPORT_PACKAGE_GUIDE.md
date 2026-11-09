# Packaging the extracted P&ID for a downstream AI

The operator's intention is **one file/folder that a permitted AI can use to understand the drawing**. The program must emit the *structured evidence* rather than a short plain-language summary alone.

After successful analysis and human review as appropriate, user chooses File -> Export open drawing / all drawings -> folder (never automatic). Create `NAME.engineering-intelligence.json` plus `NAME.evidence-manifest.json`, `NAME.graph.v2.json`, optional bounded crops, registers CSV/XLSX and `NAME.readme.md`. Where too large, create chunks with stable manifest references; all file references relative and collision safe. Include the AI runtime prompt from `16_AI_CONSUMER_PROMPT.md` in the export to guide any permitted downstream AI application.

1. **General system overview**: project drawing identification, selected pages, title/issue/revision, purpose with source-backed confidence.
2. **Equipment register**: all detected/unknown equipment occurrences and proposed assets, drawing boxes, ports, nozzles and related lines.
3. **Valve register**: all detected/unknown valves, actuators, fail states if shown, command/status tags, positions and evidence.
4. **Line list and graph**: tags, services, classes, sizes, reducers, connections and typed junction graph with every unknown crossing or tee.
5. **Instrument index and loops**: tag, measured variable, related equipment, instrument and controller nodes, signal types, control path evidence, unresolved path.
6. **Safety-related drawing features**: alarms, reliefs, ESD, blinds, drain/vent/utility boundaries and required manual safeguarding review; no SIL/IPL credit.
7. **Engineering specifications**: source-verbatim and normalized dimensions, ratings, units, equipment/line pressure/temperature values and exact association to tags/rows.
8. **Notes, tables, metadata, revision references and offsheet links**: full text as allowed and row/column positions; any title OCR issue flagged.
9. **Unclassified observations**: raw graphics/crops (on authorised local export), OCR alternatives, unresolved symbols/lines and missing-coverage regions. They must not be dropped because unclassified.
10. **Quality/evidence**: every claim IDs and bboxes, stage statuses, review states, model/config versions and source SHA.

Downstream prompt requires the AI to begin with a quality read; if text, symbols or graph incomplete it must disclose limits before answering engineering queries. Unknown connections are not treated as open pipes. Do not compress drawing into a prose paragraph and throw away structured data. Keep data export separate from external upload permission; shipping a local export is not authorisation to upload client content to an internet AI.
