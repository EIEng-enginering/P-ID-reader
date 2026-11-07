# Revision W — pre-Claude integration and release hardening

Version: `0.17.0-dev0`; inherited baseline: WIN-R01 / cumulative Rev V.

## Why this increment matters

Rev W fixes failure boundaries that ordinary symbol-recognition fixtures do not exercise. It is a source-code and test increment, not an accuracy or engineering qualification release.

### Implemented changes

1. **Atomic, no-clobber result publication** (`src/pid_reader/worker.py`): after writing and fsyncing the staged canonical JSON, the worker uses same-volume `os.link()` to publish a complete destination entry. It rejects an existing file even if a competing writer creates it *between* the preliminary check and publication. Previously `os.replace()` could overwrite that competing file. Does not copy across volumes or silently fall back to an unsafe overwrite. Tested on local POSIX filesystem. Test this on Windows NTFS before claiming production compatibility.
2. **Output and input bounds**: worker rejects JSON over the frozen 8 MiB limit; the source PDF read is bounded even if the source file grows after preflight. Host R1 schema remains unchanged.
3. **Parameter validation** (`src/pid_reader/api.py`): rejects non-integer, negative, boolean and non-finite field values where unsupported, and malformed page selections with ordinary `PID_BAD_PARAMETER` refusals instead of internal exceptions.
4. **Child stderr pipe drained concurrently** (`src/pid_reader/engineering/isolation.py`): a bounded 64 KiB diagnostic tail prevents large OCR/PDF-library stderr output from deadlocking the parent. No new disk cache of document diagnostics.
5. **Independent isolated-child integrity checks**: before returning a child result, verifies canonical JSON, 8 MiB bound, source PDF SHA-256, provenance input/parameter/result hashes, schema version, collection types and summary counts. Refuses altered or incomplete outputs without accepting their exit code as sufficient evidence.
6. **Fail early**: isolated reader rejects bad PDF bytes, incorrect expected source SHA, oversized PDF and cancellation before writing/spawning a subprocess.
7. **Twenty-five additional adversarial tests** in `tests/test_rev_w_handoff_hardening.py` exercise race/no-overwrite, cross-volume refusal, stderr flood, forged child output and malformed parameters.

## Verified evidence (Linux only)

- `282 passed` — `TEST_RESULTS/HANDOFF_REV_W/development_pytest.txt`.
- `16 passed` — frozen Worksheet R1 reference suite in `TEST_RESULTS/HANDOFF_REV_W/frozen_r1_pytest.txt`.
- All preflight checks PASS; schema/rule violations: 0 — `TEST_RESULTS/HANDOFF_REV_W/release_preflight.json`.
- Original frozen R1 ZIP SHA-256: `09174700ff54cdf3bd899d952951d8969041f1a094cbe8cefff9bd714cbd25e2`.
- Version `0.17.0-dev0`; original schema version and Worksheet integration API unchanged.

## What is not proven

- **NOT_RUN:** Windows 11, Python 3.12, PySide6 6.12, Windows NTFS same-volume hard-link publication and cancellation/Job Object behaviour, full installer tests.
- **NOT_RUN:** real Worksheet host G4–G7 tests, licence review, full DEXPI semantic conformance, industrial precision/recall, and independent engineering QA.
- **NOT IMPLEMENTED/NOT QUALIFIED:** hardened security sandbox. Windows may fall back to process-kill without an enforced memory cap if Job Object assignment fails; this must remain an explicit failure/qualification gate for hazardous/untrusted sources.
- Real source recognition and piping relationships remain **proposals** until a named engineer reviews them.

## Acceptance note

The original R1 requirements archive and schema were not modified. An engineering user should not rely on the program as a validated, complete or as-built plant model.
