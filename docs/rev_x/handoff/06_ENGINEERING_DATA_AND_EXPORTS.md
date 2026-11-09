# Engineering information model / AI consumer data contract

The output is a **drawing interpretation package**, not a digital twin or verified plant model. `schemas/engineering_intelligence_v1.schema.json` is an initial separate standalone schema proposal and does NOT modify the frozen Worksheet R1 schema or worker JSON. Claude must implement validators, versioning, stable ordering, forward compatibility, tests and a public standalone SDK.

## Required model fields

`package`: schema id/version, extraction engine version, run hash, generated UTC, status, source links, model/config hashes, confidentiality label, no-plant-validation disclaimer.
`drawings[]`: immutable document SHA, registered/unknown drawing and revision, exact pages and source coordinate transforms, title blocks, page status and stage diagnostics.
`evidence[]`: stable id, source drawing hash, 0-based page, normalized top-left bbox or polygon, raw observed text/geometry, producer/version/config/model hashes, output crop refs if exported, and provenance type. No fabricated source references.
`observations[]`: native text, OCR words, vector primitives, raster contours, junction glyph, symbol geometry, annotation/text groups, including raw scores and alternatives.
`entities[]`: separate graphical occurrence from identity hypothesis; kind, raw/normalized tag, class, attributes, ports, evidence refs, hypothesis groups, machine interpretation level, review status and source drawings.
`relations[]`: typed directed/undirected from/to entity/port IDs, evidence refs and source classification, type-specific semantics and alternatives; `direction UNKNOWN` allowed.
`registers`: equipment, line, valve, instrument, loop, setpoint, title block, notes, off-page reference, package and revision views; all rows cross-reference canonical entity/obs/attribute ids. Missing field is `null`/`UNKNOWN`, not invented zero.
`quality`: per-page/region/text/symbol/line/graph coverage, stages, warnings, errors, missed-risk, caps, unresolved conflicts, human-reviewed fraction. Coverage does not equal accuracy.
`narrative`: paragraphs with `claim_id`, confidence classification and evidence IDs; narrative generative interpretation must never override observed data.
`review`: append-only decisions indexed by source version and named reviewer; not human plant verification.

## Entity hierarchy

Entities: `DOCUMENT_OCCURRENCE`, `EQUIPMENT`, `EQUIPMENT_NOZZLE`, `PIPING_LINE`, `PIPING_SEGMENT`, `FITTING`, `VALVE`, `VALVE_ACTUATOR`, `INSTRUMENT`, `INSTRUMENT_LOOP`, `CONTROL_SYSTEM`, `SIGNAL`, `SAFETY_DEVICE`, `PACKAGE`, `BUILDING`, `UTILITY`, `OFFPAGE_CONNECTOR`, `ANNOTATION`, `TABLE`, `TABLE_CELL`, `UNCLASSIFIED_SYMBOL`. Graph occurrence `o_*` is immutable to a source page; asset hypothesis `a_*` may link occurrences across sheets/revisions with independent evidence. A tag string is an attribute, NOT identity.

`typed_port`: declared kind `PROCESS_IN`, `PROCESS_OUT`, `PROCESS_BIDIRECTIONAL`, `PROCESS_UNKNOWN`, `SIGNAL_IN`, `SIGNAL_OUT`, `INSTRUMENT_TAP`, `ACTUATOR_SIGNAL`, `NOZZLE`, `DRAIN`, `VENT`, `UTILITY`, `OTHER`. Ports have bboxes/angles/source ids; they cannot be aliased to symbol centre.

`relation`: type `DRAWN_CONNECTS`, `SIGNAL_CONNECTS`, `HAS_PORT`, `HAS_NOZZLE`, `MEASURES`, `INDICATES`, `CONTROLS`, `ACTUATES`, `POSITION_FEEDBACK`, `ALARM_REFERENCE`, `PART_OF_PACKAGE`, `PROPOSED_SAME_AS`, `OFFPAGE_MATCH_CANDIDATE`, `REFERENCES`, `LOCATED_IN`, `OTHER`. Do not use a universal CONNECTED edge for all relationships. Relationship evidence includes junction type/line style and whether crossing ambiguity exists.

## Evidence and truth vocabulary

- `DIRECT_OBSERVATION`: literal text/glyph/geometry unambiguously present in source, subject to extraction quality.
- `STRUCTURALLY_DERIVED`: geometry-based line-to-port path or parsed table cell with explicit trace.
- `CONTEXTUAL_INFERENCE`: engineering-convention interpretation; tentative and never asserted as design fact.
- `CONFLICTING`: source alternatives/claims disagree.
- `UNKNOWN`: not recoverable from available evidence.

Review states independent: `PROPOSED_UNVERIFIED`, `ACCEPTED_AS_READING`, `REJECTED`, `IGNORED`, `NEEDS_REVIEW`, `STALE`. Quality status independent: `NOT_RUN`, `FAILED`, `INCOMPLETE`, `PARTIAL`, `COMPLETE_CANDIDATES`. Calibration: only include `calibrated_probability` if benchmark-calibration ID is defined; otherwise use raw model score with `score_kind: UNCALIBRATED`.

## Engineering attributes / numeric values

Each value stores `{field_name, verbatim, normalized_value (optional), original_unit, normalized_unit, numeric_type: SETPOINT|DESIGN|OPERATING|RATING|SIZE|RANGE|UNKNOWN, qualifier, source_refs, confidence, status, alternatives}`. Always preserve original instrument setpoint vs design pressure vs normal operating pressure. Preserve gauge/absolute pressure distinction, Fahrenheit/ Celsius, nominal size vs outside diameter, dimension tolerance and 'TBD/HOLD' states. An absent value remains UNKNOWN, not default 0.

## Hierarchical AI payload for context-efficient query

1. `manifest.json`: versions, pages, run/engine, hashes, available registers and file IDs, quality warnings, drawing status.
2. `overview.json`: drawing metadata, topology summary, main equipment and system narrative with evidence references, explicit unknowns; suitable for low-context AI first pass.
3. `registers/*`: sorted typed registers with evidence refs; optional compressed external local payload.
4. `graph/*.json`: typed subgraphs partitioned by connected process/area/line, stable node/edge ids and boundary references.
5. `evidence/*.json`: source refs, page regions, OCR/symbol candidates, conflicting hypotheses and reviewer actions; optional user-confirmed crop images.
6. `quality.json`: detailed run statuses and the list of unsupported/unprocessed regions; no silent claims that model is complete.
7. `AI_INTERPRETATION_PROMPT.md`: instructions for downstream AI; no automatic external upload. Confidential user drawings must remain in local privacy-controlled environment unless separately permitted.

If exports exceed file limits, partition and create an index; never truncate a graph without warning and manifest. On selective export, clearly identify omitted sheets/regions and what query answers cannot be trusted.

## What an AI must be able to do (without hallucinations)

- Describe a system's **shown** equipment and process-line arrangement.
- Trace a path through **proposed graphical topology** with line/port ids, unresolved crossings listed. Avoid asserting actual fluid flow where arrows are missing.
- Describe one instrument loop using measured variables, devices and drawn signals; say which logic is not shown.
- List isolation valves on a drawn path as candidates; never certify safe isolation or safeguarding credit.
- Compare revisions by two source hashes and distinguish model extraction changes from drawing changes.
- List all unrecognised symbols/text/tables and record missing/ambiguous data to drive human review.

## DEXPI mapping

Implement separate versioned output `dexpi_2_0_1.xml` only if validation passes official DEXPI XML XSD and mandatory entity/nozzle relation semantics. The JSON schema in this handoff is **NOT a DEXPI schema**. Include a mapping matrix per entity/relation and preservation of unknown/unmapped attributes via parallel manifest, not dishonest lossless claims. Do not bundle standards content lacking copyright permission.
