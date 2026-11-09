# Worked cases and expected extraction behavior

**Important:** S023/S025 are owner-uploaded *regulator drawing derived outputs*. These descriptions are useful for regression diagnosis, **NOT independently annotated acceptance gold**. The supplied Rev X pack contains an S023 output and a detailed human inspection. The user also supplied S025 report in the current conversation but not a complete independently validated engineering annotation or original source PDF inside this upgrade pack. Do not call the hand-observed tags definitive unless verified against the actual PDF at appropriate zoom by an independent reviewer.

## Case S023: Ancaster Station 209

- PDF `S023_cer_2693621_p002.pdf`, vector-outlined diagram body, some native title block text, rotated page; drawing `0209-01-ML-02-001`, rev C, preliminary-only, date February 2015 (according to Rev X forensic notes).
- Historical run: native title note extraction worked but equipment, valves and detailed tags missing. Later improved Rev X notes reported OCR 13 specific instrument tags including `ZSC-201`, `ZSO-201`, `TSL-315`, `TSL-100`, `FMV-201`, `PIC-102`, `PY-102`, `PSHH-201`, `PIT-101`, `PIT-100`, `ZT-102`, `FBV-200`, `PCV-102`. Keep source badge for each and verify against original PDF prior to gold assertion.
- Expected proposed stage improvements: `VECTOR_OUTLINED_TEXT` classification; OCR on body; instrument stacked-letter association; 2 pressure gauges + other unnumbered bubble classes remain correctly untagged; valves including actuators proposed with project symbol alternatives; heater/control-valve/manifold skid blocks; distinct note vs process-line words; reducer NPS 30 x 20; line labels LINE 200-1/200-2; station design and operating pressure table cells bound to correct line; drawn signal paths and PLC/SCADA proposals; flow arrow as drawn and not assumed; title revision/issue-status fields with cited boxes.
- Acceptance: no new false certainty, no source/model revision collapse, no plant verification claim. All findings carry page bbox/source ids.

## Case S025: Minton pump prefilter ethane station

- Upload report `S025_cer_2935633_p006.pdf` has `ocr.word_count:0`, zero source readings, zero connectivity graph nodes/edges; `671` raster contacts (`357` tee candidates, `186` endpoint touches, `128` crossings) and `17` raster gap candidates. All are unreviewed, unverified. This is evidence of **reader output failure/insufficiency**, not a claim of no plant components.
- Previous visual interpretation in this conversation described ethane pipeline to a pre-filter skid, MOVs, two booster pumps, pressure/DP instrumentation, thermal relief, fills/vents/drains and title block. Treat individual tags and design values as **candidates to re-verify**, not supplied gold. Be especially careful that drawing number, rev and status were originally misread in a previous response and later corrected.
- Must test differentiated diagnostic causes: (1) no OCR engine; (2) OCR not triggered on raster; (3) OCR ran and failed; (4) OCR words seen in internal pipeline but dropped in persisted report; (5) worker cancel/memory; (6) scan too small; (7) OCR retrieved title only. Each produces a distinct stage record, not silent success. Return partial geometry evidence and `INCOMPLETE`, offer targeted crop re-read.
- Post-upgrade acceptance: manually annotated tags/objects and connections (created independently and legally) used to calculate recall; no claim of full coverage from synthetic tests alone.

## Synthetic control fixtures to generate

- Filter F-1 + upstream/downstream isolation + pressure taps + DPIT-100 with one T-junction and one nonconnected crossing; explicit 10in Class 600 and design pressure note. Model has valid flow only when arrow shown.
- Closed vessel with two nozzle ports and line break indicating off-page connector; no false merge into neighboring line with same tag.
- Rotated 90/270 and CropBox offset variants with exact bbox mapping, and text converted to outlines.
- A P&ID-style title block whose line text looks like instrument tag; out-of-process labels must not create equipment.
- Engineering table with one setpoint and one design pressure in adjacent columns; normalize units independently.
- Symbol legend with visually similar gate/check/control valves and actuators, plus 5 negatives (bow tie dimension, flange, instrument bubble, title graphic, flow arrow).
- Scan with faint 1-pixel junction dot, raster crossing and explicit bridge; must retain unresolved candidate where ambiguity remains.
- Multi-page offsheet connection with identical tag but incompatible service vs compatible dual evidence; false merge is forbidden.
- Revision unchanged source but new detector version must be `INTERPRETATION_DIFF`, not `DRAWING_CHANGE`.

## Expected report examples

`DRAWING_STATUS=INCOMPLETE`, `OCR_STAGE=NOT_RUN/FAILED/NO_WORDS`, `KNOWN_RASTER_CONTACTS=671`, `SEMANTIC_GRAPH=NOT_AVAILABLE` is valid for an S025-like failed run; `0 EQUIPMENT` with status `SUCCESSFULLY_COMPLETE` is not. Future successful extraction would instead provide entities with evidence, unresolved junctions, and independent test metrics, not merely many rectangular overlays.
