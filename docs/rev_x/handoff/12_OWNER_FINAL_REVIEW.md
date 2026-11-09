# Final owner acceptance checklist - to be completed by Claude, not pre-approved

**All Q1-Q100 Option A decisions are owner APPROVED development scope, not software implementation acceptance.** Fill all rows in final release candidate, with actual evidence links and no invented PASS. The owner alone decides whether to release into production after seeing the complete review package.

## Required status matrix

| Gate | Minimum items | Current handoff status |
|---|---|---|
| Baseline source and R1 freeze | Snapshot SHA, actual local Git reconciliation, contract SHA, original checker | INPUT CHECKSUM VERIFIED in handoff; real Windows checker NOT_RUN here |
| Functional code | Integrated WPU-00..19, targeted + full tests, no regressions, additive DB, GUI and exports | NOT_IMPLEMENTED in this handoff |
| Independent extraction accuracy | Labelled real source, per-class P/R, topology errors and silent miss, untouched holdout | NOT_RUN / data and independent review required |
| Host compatibility | Exact R1 schema/hash/worker, disposable current Worksheet COPY, no host mutations | NOT_RUN in this handoff |
| Real Windows installer | Offline clean-machine install/start, CPU/raster, 175% scaling, cancel, memory, antivirus | NOT_RUN in this handoff |
| Independent engineering | Qualified review of interpretation/critical misses and limitations | NOT_RUN in this handoff |
| Legal/data | Licence/source/model/weights/SBOM/drawing rights, no ISA IP copied to AI | External counsel/permission as applicable NOT_RUN |
| Owner release | Reviewed full package and explicitly accepted | NOT_APPROVED for release by development approval alone |

## Final review bundle content

1. Source branch/repo hash and full source archive, exact differences from Rev X snapshot, frozen PR contract hash, no live Worksheet changes.
2. `requirements/APPROVED_REQUIREMENTS_Q1_Q100.csv` with each Q's actual implementation/test outcome, original PR-* traceability and open blockers.
3. Release build + installer or precise NOT_RUN evidence; Windows Python3.12 source launch steps, rollback and backup/restore checks.
4. Per-class supported/unsupported detection catalogues, false positive/false negative examples, calibration IDs, independent real-gold confidence intervals, untouched holdout with leakage control.
5. Original-geometry, licence-clean synthetic drawing inputs and outputs with actual production pipeline, typed engineering graph, AI export and narrative.
6. Document S023/S025 diagnostic outcomes including PDF/OCR stage, source tags, reviewable candidates; describe unresolved field ambiguities without plant-truth claims.
7. Test command transcripts, date/env/versions, model weight hashes, peak RSS and stage-level timing, Job Object and fail-injection cases, `NOT_RUN` independent tests explicit.
8. Threat model, confidentiality and offline egress evidence, third-party licences/models, SBOM, signed/checksummed package if approved, no cloud AI transfer at runtime.
9. All code migration ADRs, hashes, generated version numbers, migration rollback, reviewer-audit preservation, UI screenshots (synthetic or approved drawings only).
10. One page of accepted improvements and precise remaining limitations, owner-final-action checklist and system-level release recommendation tied to evidence.

## Owner's final decision options

`ACCEPT DEVELOPMENT CANDIDATE FOR FURTHER VALIDATION`, `ACCEPT FOR LIMITED INTERNAL PILOT SUBJECT TO LISTED LIMITS`, `APPROVE PRODUCTION RELEASE`, or `REJECT/REQUEST REWORK`. None is selected by this Q51-Q100 approval; do not print `APPROVE PRODUCTION RELEASE` as a default.
