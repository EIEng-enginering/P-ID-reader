# Contract crosswalk: existing R1 and standalone Rev X v12 -> intelligence v1

This is an **additive** proposal, not a request to edit original R1 schemas.

| Existing source | Preserve existing meaning | New standalone intelligence surface |
|---|---|---|
| R1 schema v1 `provenance` | One completed extraction of one active source revision, canonical SHA, fixed identifiers | `package`, `drawings` and evidence lineage only in standalone extension; R1 untouched |
| R1 `document`, `pages` | Page metadata, source text and geometry bbox top-left fractions | separate `drawings` and page regions with transformation records |
| R1 `objects` | R1 object classes and text/source location, strict `additionalProperties` | `entities`, distinct occurrence + asset hypothesis, typed ports and per-attribute evidence |
| R1 `connections` | Only R1 supported proposal semantics, no added v2 keys | `relationships` typed port links, alternative groups and score provenance |
| R1 `loop_proposals` | Existing conservative proposals | standalone instrument loop records linking typed drawn signal relations |
| R1 `shared_component_evidence` | Original R1 provenance/constraints | separate asset-hypothesis crosssheet groups, only source-supported |
| R1 `unreadable_regions`, `warnings`, `summary` | Original R1 limits/status unchanged | `quality`, `unresolved`, page-stage diagnostics; must not override R1 summary |
| Standalone `project.py` v12 readings/findings | Existing source observations, review decisions and audit history | v13+ additive evidence, occurrence, ports, relations, export snapshot views |
| `drawing_export.py` current JSON/HTML/GraphML | Existing per-drawing filename selection and no-overwrite | optional additional `engineering_intelligence_v1.json` and manifest under same user-confirmed export action |
| `graph_export.py` canonical graph v1 | Existing graph v1 schema and GraphML remain readable | independent typed graph v2; no silent breaking change |
| `dexpi.py` refused export | Preserve truthful refusal until a valid implementation exists | separate DEXPI 2.0.1 adapter/XSD validation; no fake conformance |

## Essential anti-corruption boundary

The frozen R1 worker/API must not import the richer standalone schema by accident or include extra fields. Provide converter `to_r1_v1` only if it reproduces the unchanged legacy schema deterministically; use separately named `to_standalone_intelligence_v1`. Tests compare byte-equivalent canonical result and refuse unknown fields through original R1 checker.
