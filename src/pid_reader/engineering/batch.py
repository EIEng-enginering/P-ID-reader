"""Standalone local bounded PDF batch importer, not the Worksheet host worker.

A manifest snapshots input file names and hashes before any extraction. Each
per-file import commits atomically and produces an immutable outcome event.
A stopped run can be resumed from its original manifest without silently
accepting changed source bytes; no background service or live folder watcher.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
from ..api import ReadParams, read_pid, RefusedInput, LimitExceeded, Cancelled

MAX_FILES = 250
MAX_CANDIDATES = 500


_REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT (Windows symlinks, junctions, cloud placeholders)


def _is_link(path: Path) -> bool:
    """True for POSIX symlinks and any Windows reparse point (symlink/junction)."""
    if path.is_symlink():
        return True
    try:
        attrs = getattr(path.lstat(), 'st_file_attributes', 0)
    except OSError:
        return False
    return bool(attrs & _REPARSE_POINT)


def _safe_input(path: Path) -> Path:
    if _is_link(path) or not path.is_file() or path.suffix.lower() != '.pdf':
        raise ValueError(f'Not an eligible regular PDF: {path}')
    return path.resolve(strict=True)


def collect_files(inputs: list[str | Path]) -> list[Path]:
    if not isinstance(inputs, list) or not 1 <= len(inputs) <= MAX_CANDIDATES:
        raise ValueError('Select 1 to 500 local input entries')
    out = []
    for input_path in inputs:
        path = Path(input_path)
        if _is_link(path):
            raise ValueError('Symlinked input is not permitted')
        if path.is_dir():
            out.extend(_safe_input(p) for p in sorted(path.iterdir()) if p.suffix.lower() == '.pdf')
        else:
            out.append(_safe_input(path))
    if not out or len(out) > MAX_FILES:
        raise ValueError('Batch must contain 1 to 250 PDFs')
    if len({str(p) for p in out}) != len(out):
        raise ValueError('A source file was selected more than once')
    return out


def _hash_file(path: Path, max_bytes: int) -> tuple[str, int]:
    h = hashlib.sha256()
    total = 0
    with path.open('rb') as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise LimitExceeded('PID_LIMIT_BYTES', 'Input exceeds the configured PDF size limit')
            h.update(chunk)
    return h.hexdigest(), total


def start_batch(db, inputs: list[str | Path], *, actor: str, params: ReadParams | None = None) -> str:
    params = params or ReadParams()
    params.validate()
    files = collect_files(inputs)
    manifest = []
    for path in files:
        # Oversize inputs must be reported as failed items in the run, not silently omitted.
        try:
            digest, size = _hash_file(path, params.max_pdf_bytes)
            preflight = None
        except LimitExceeded:
            digest, size, preflight = None, path.stat().st_size, 'PID_LIMIT_BYTES'
        manifest.append({'path': str(path), 'name': path.name, 'sha256': digest,
                         'size_bytes': size, 'preflight_error': preflight})
    return db.create_batch(manifest, actor=actor, params=params.as_dict())


def resume_batch(db, batch_id: str, *, stop_after: int | None = None, isolated: bool = False,
                 should_cancel=None, progress=None, timeout_s: int = 180, memory_mb: int = 2048) -> dict:
    """Import the not-yet-recorded files of a batch.

    ``isolated=True`` reads every PDF in a resource-limited child process
    (timeout, memory cap, kill-on-cancel). If ``should_cancel()`` becomes true the
    current file is *not* recorded, so a later resume re-reads it; the batch then
    simply stays INCOMPLETE. ``progress(done, total, name)`` is called per file.
    """
    if stop_after is not None and (type(stop_after) is not int or stop_after < 1):
        raise ValueError('stop_after must be a positive integer')
    job = db.get_batch(batch_id)
    params = ReadParams(**job['params'])
    params.validate()
    new_items = 0
    for index, item in enumerate(job['manifest']):
        if item['ordinal'] in job['completed_ordinals']:
            continue
        if stop_after is not None and new_items >= stop_after:
            break
        new_items += 1
        if should_cancel is not None and should_cancel():
            break
        if progress is not None:
            progress(len(job['completed_ordinals']) + new_items - 1, len(job['manifest']), item['name'])
        status = 'FAILED'
        extracted_id = None
        detail = 'Not processed'
        try:
            if item['preflight_error']:
                raise LimitExceeded(item['preflight_error'], f"{item['preflight_error']}: File failed batch preflight limits")
            path = _safe_input(Path(item['path']))
            actual_sha, size = _hash_file(path, params.max_pdf_bytes)
            if actual_sha != item['sha256'] or size != item['size_bytes']:
                raise ValueError('Source file changed after batch manifest was created')
            source = path.read_bytes()
            if hashlib.sha256(source).hexdigest() != item['sha256']:
                raise ValueError('Source file changed while being read')
            if isolated:
                from .isolation import read_pid_isolated
                result = read_pid_isolated(source, params, filename=item['name'], expected_sha256=item['sha256'],
                                           timeout_s=timeout_s, memory_mb=memory_mb, should_cancel=should_cancel)
            else:
                result = read_pid(source, params, filename=item['name'], expected_sha256=item['sha256'])
            extracted_id = db.add_extraction(result, source)
            status, detail = 'IMPORTED', 'Source extraction imported as proposals only'
        except Cancelled:
            break
        except (RefusedInput, LimitExceeded, ValueError, OSError, KeyError) as exc:
            detail = f'{type(exc).__name__}: {exc}'[:500]
        db.record_batch_outcome(batch_id, ordinal=item['ordinal'], status=status,
                                extraction_id=extracted_id, detail=detail)
    return db.get_batch(batch_id)
