"""R1-shaped worker with atomic result handoff and no document-text diagnostics.

The only published output is the host-nominated JSON path. A candidate is staged
inside the private --workdir, fsynced, then atomically hard-linked into its final
name without permitting replacement of another writer's result.
The host is responsible for supplying an isolated scratch directory and stopping
this process for cancellation. We never recursively delete a caller-owned folder.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
from pathlib import Path
import sys
import tempfile

from .api import (Cancelled, CancelToken, LimitExceeded, ReadParams,
                  RefusedInput, canonical_json, read_pid, sha256_hex)

EXIT_OK, EXIT_REFUSED, EXIT_LIMIT, EXIT_INTERNAL, EXIT_CANCELLED = 0, 2, 3, 4, 5


def progress(**fields):
    sys.stderr.write(json.dumps(fields, sort_keys=True) + "\n")
    sys.stderr.flush()


def atomic_publish(result: dict, destination: Path, scratch: Path) -> None:
    """Publish a complete JSON file or leave no new destination.

    Scratch and destination must support same-volume hard links. Publication is
    atomic and cannot replace an existing result, even if a result appears during
    staging.
    Does not permit overwriting an existing result or storing it in scratch.
    """
    if not scratch.is_dir() or scratch.is_symlink():
        raise RefusedInput("PID_BAD_PARAMETER", "Scratch must be an existing private directory.")
    dst = destination.resolve(strict=False)
    wrk = scratch.resolve(strict=True)
    if dst.is_relative_to(wrk):
        raise RefusedInput("PID_BAD_PARAMETER", "Result path must be outside scratch.")
    if destination.exists() or destination.is_symlink():
        raise RefusedInput("PID_BAD_PARAMETER", "Result path must not already exist.")
    if not destination.parent.is_dir():
        raise RefusedInput("PID_BAD_PARAMETER", "Result directory does not exist.")
    data = canonical_json(result).encode("utf-8")
    if len(data) > 8 * 1024 * 1024:
        raise LimitExceeded("PID_LIMIT_RESULT", "Worker output exceeds the 8 MiB R1 result limit.")
    staged: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix="pid-stage-", suffix=".json", dir=wrk, delete=False) as f:
            staged = Path(f.name)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        # Atomic no-clobber creation, including if another process creates the
        # result AFTER the earlier existence check. os.replace would overwrite
        # that concurrent result; os.link fails with EEXIST instead. The staged
        # file is complete and fsynced before the destination becomes visible.
        # NTFS and POSIX filesystems support hard links to ordinary files.
        try:
            os.link(staged, destination)
        except FileExistsError as exc:
            raise RefusedInput("PID_BAD_PARAMETER", "Result path appeared during staging; refusing to overwrite it.") from exc
        except OSError as exc:
            if exc.errno in (errno.EXDEV, errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP):
                raise RefusedInput("PID_BAD_PARAMETER", "Destination must support atomic no-clobber hard links on the scratch volume.") from exc
            raise
        # The complete output is now visible. Delete the private stage, never
        # the destination. If cancellation occurs here, output stays complete.
        staged.unlink()
        staged = None
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def main(argv: list[str] | None = None, _reader=None) -> int:
    """``_reader`` lets the standalone worker substitute a reader; the R1 entry point leaves it unset."""
    parser = argparse.ArgumentParser(prog="pid_reader.worker")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    for name in ("--input", "--params", "--output", "--workdir"):
        run.add_argument(name, required=True)
    run.add_argument("--document-revision-id", default="")
    run.add_argument("--filename", default="")
    run.add_argument("--expected-sha256", default="")
    args = parser.parse_args(argv)
    try:
        workdir = Path(args.workdir)
        if not workdir.is_dir() or workdir.is_symlink():
            raise RefusedInput("PID_BAD_PARAMETER", "Scratch must be an existing private directory.")
        output = Path(args.output)
        # Check the destination before processing a potentially long document.
        if output.resolve(strict=False).is_relative_to(workdir.resolve(strict=True)):
            raise RefusedInput("PID_BAD_PARAMETER", "Result path must be outside scratch.")
        if output.exists() or output.is_symlink():
            raise RefusedInput("PID_BAD_PARAMETER", "Refusing to overwrite an existing output.")
        raw = json.loads(Path(args.params).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise RefusedInput("PID_BAD_PARAMETER", "Parameters must be an object.")
        pages = raw.pop("pages", None)
        if pages is not None and (not isinstance(pages, list) or not all(type(n) is int for n in pages)):
            raise RefusedInput("PID_BAD_PARAMETER", "pages must be an array of integers or null.")
        known = {k: raw.pop(k) for k in list(raw) if k in ReadParams.__dataclass_fields__ and k != "extras"}
        params = ReadParams(pages=tuple(pages) if pages is not None else None, extras=raw, **known)
        # Read a bounded number of bytes, even if another process grows the
        # source after the size preflight. Never read an unbounded hostile file.
        src = Path(args.input)
        if src.stat().st_size > params.max_pdf_bytes:
            raise LimitExceeded("PID_LIMIT_BYTES", "Input exceeds the configured byte limit.")
        with src.open("rb") as handle:
            input_data = handle.read(params.max_pdf_bytes + 1)
        if len(input_data) > params.max_pdf_bytes:
            raise LimitExceeded("PID_LIMIT_BYTES", "Input grew beyond the configured byte limit while reading.")
        progress(event="start", bytes=len(input_data), sha256=sha256_hex(input_data))
        result = (_reader or read_pid)(input_data, params, CancelToken(),
                          document_revision_id=args.document_revision_id,
                          filename=args.filename, expected_sha256=args.expected_sha256)
        atomic_publish(result, output, workdir)
        progress(event="done", objects=len(result["objects"]), connections=len(result["connections"]))
        return EXIT_OK
    except LimitExceeded as exc:
        progress(event="refused", code=exc.code)
        return EXIT_LIMIT
    except RefusedInput as exc:
        progress(event="refused", code=exc.code)
        return EXIT_REFUSED
    except Cancelled:
        progress(event="cancelled")
        return EXIT_CANCELLED
    except Exception as exc:
        progress(event="error", kind=type(exc).__name__)
        return EXIT_INTERNAL


if __name__ == "__main__":
    raise SystemExit(main())
