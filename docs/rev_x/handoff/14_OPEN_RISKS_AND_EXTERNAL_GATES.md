# Risks and genuinely external blockers (not additional owner design questions)

| ID | Risk | Mitigation / owner dependency | Current status |
|---|---|---|---|
| X-01 | Copyleft/proprietary OCR/CAD/model dependency | Prefer baseline permissive, audit weights and transitive notices, licensed alternatives only if separately approved | LEGAL_REVIEW_NOT_RUN |
| X-02 | User drawings may be client confidential or copyright restricted | Local only; no client fixtures or uploads; seek explicit permission if external sharing | REQUIRE SOURCE RIGHTS |
| X-03 | Public examples unlabelled, synthetic dev saturated | Commission independent gold and reviewers; preserve held-out set | EXTRACTION ACCURACY GATE NOT_RUN |
| X-04 | Clean Windows 11 builder/175% DPI and unsigned installer | Build and run on Windows, signature only with actual authorised certificate | WINDOWS TESTS NOT_RUN IN HANDOFF |
| X-05 | Worksheet host live not present | Run frozen checker + cloned host integration; leave live host untouched | REAL HOST COPY GATE NOT_RUN |
| X-06 | Auto-recognition cannot guarantee all symbols and connections | Explicit supported taxonomy, unknowns, alternative paths, coverage and critical-miss metrics | PERMANENT ENGINEERING LIMITATION |
| X-07 | Legacy output file/DB backward compatibility | Preserve v12 and graph v1 formats; additive versioned tables; snapshot backward tests | REQUIRED TEST |
| X-08 | OCR zero may be orchestration or export failure rather than model | Instrument stage outcomes and compare internal word counts with report; S025 failure matrix | WPU-01 BLOCKER |
| X-09 | Dense/large page CPU memory/timeout | Adaptive tiled processing, capped progress, subjob cache, no silent truncation | REQUIRES WINDOWS BENCHMARK |
| X-10 | ISA copyrighted standard IP not allowed in AI tools without permission | Do not paste, train, embed figures; use original generic symbolic grammar and permitted docs | MUST RESPECT RIGHTS |
| X-11 | CAD native DWG/DGN/SmartPlant licences not provided | Ship validated DXF and declared disabled adapters for unavailable inputs | LICENCE OR SDK BLOCKED |
| X-12 | DEXPI nonconformant outputs risk silent data loss | Validate actual 2.0.1 XSD, mapping matrix and refused export until proven | NOT_IMPLEMENTED BASELINE |
| X-13 | Model/regex changes create spurious 'revision' differences | Separate extraction-model-change diff and actual source revision diff | REQUIRED TEST |
| X-14 | Misread safety devices/isolations might affect HAZOP | No automatic safeguard credit or host accepted writes; qualified human acceptance | INDEPENDENT ENGINEERING GATE |
| X-15 | Loss of development progress/context | Incremental commits and HANDOFF_STATE per continuation instructions | REQUIRED CONTINUITY |

Blocked permissions do not stop other technical work. No spending, external data disclosure or live host write is implied by approval of development scope.
