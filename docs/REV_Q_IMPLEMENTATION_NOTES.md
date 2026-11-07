# Rev Q — final ChatGPT development increment and Claude handoff

Rev Q builds on cumulative Rev P **without removing earlier source code**. It is the final *planned ChatGPT increment* and the **start of continued Claude development**, not a claim that the engineering reader is production-complete.

## Changes implemented in Rev Q

- Core version `0.11.0-dev0`; standalone database **schema v9** unchanged. Original Worksheet R1 output `schema_version=1` unchanged.
- `pid_reader.worker` now uses `atomic_publish`: write complete canonical JSON to a new temporary file inside host-provided scratch; flush/fsync; publish by single `os.replace` to the only nominated result. Clean up own staging files on ordinary failures. Refuse existing output or output inside scratch. No extra persistent caches and no document text in worker stderr. Parent host must clean its private scratch after force-kill. Same-volume requirement for atomic rename is explicit.
- Worker validates JSON parameter object and integer page array, refuses oversize input before reading entire input into memory, and returns R1-defined status codes for common refused/limit errors.
- `pid_reader.release_assurance` and `tools/release_preflight.py` confirm frozen R1 archive SHA, isolated import from current checkout rather than stale editable installs, and complete worker→JSON→R1 schema/hash smoke test. These **do not** invoke or modify the live Worksheet host.
- `tools/build_handoff.py` builds a deterministic-entry, content-hashed, single-ZIP cumulative archive. Every entry is checked against `FILE_SHA256.txt`; caches, symlinks and bytecode are excluded. ZIP content hashes are verified after creation. This is not cryptographic code signing.
- `windows/CHECK_WINDOWS.ps1` and `windows/RUN_READER_WINDOWS.ps1` prepare real target environment checking and local GUI preview without network downloads. Untested on Windows here.
- 18 new tests for worker/result integrity, no clobber, invalid parameters, source checkout, frozen R1, preflight and archive tampering. All older tests preserved.
- `docs/RELEASE_ACCEPTANCE_MATRIX.md` is the authoritative evidence/gates boundary. Do not mark Windows/host/industrial accuracy PASS without executing those tests.

## Implementation limits not to disguise

1. Worker output atomicity protects the single nominated JSON handoff. It cannot guarantee zero scratch residue after OS force-kill; host must own and clean its temporary directory. The R1 B06 text and skeleton's explicit output path require actual Worksheet integration reconciliation. The new worker **has not been run in the real host**.
2. No multi-process sandbox/seccomp/AppContainer protection is supplied for the standalone batch pipeline; that is still in-process. No independent malicious PDF resilience guarantee is made.
3. No genuine PySide6-on-Windows runtime screenshots, scale checks, installer, vendored/pinned offline dependency wheels, or permission/credential verification are delivered.
4. The original R1 packaging requires a `module.json` manifest, dependency wheel register/licence evidence and host migration/entrypoint testing. The existing standalone development source is not a certified drop-in Worksheet plugin or complete R1 release artifact.
5. Source tag/shape geometry and graph are bounded hypotheses tested on synthetic examples. The whole industrial recognition benchmark and pretrained vision model are absent. Standard PDFs with raster-only content are refused visibly in the R1 host reader.
6. Python tests in this environment were executed on Linux 3.13, while the destination is Windows Python 3.12. Version differences need actual verification.

## Destination, ownership and permissions

Windows project directory (exact): `C:\Users\Admin\OneDrive - Enhance Integration Engineering\Company\006 Calculation Methods\26 P&ID reader`.
GitHub (exact): `https://github.com/EIEng-enginering/P-ID-reader.git`.
Owner approved Q1–Q50 Option A and normal autonomous coding. No live host writes or protected remote push have been made by this ChatGPT package.

See `00_START_HERE_FOR_CLAUDE.md` for the one-shot instructions to Claude Code.
