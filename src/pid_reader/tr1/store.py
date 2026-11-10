"""Where TR1 data lives: outside the standalone database, outside the package manifest and outside OneDrive-synced project folders.

``PIDLAB_TR1_HOME`` or ``%LOCALAPPDATA%/PIDReader/tr1``: ``detections/<source sha256>/page_<n>.json`` (PROPOSED detector output, replaceable),
``corrections/queue.jsonl`` (append-only, hash-chained, never edited), ``batches/<version>/`` (immutable training batches) and ``family_lock.json``.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

_SHA = re.compile(r"^[0-9a-f]{64}$")


def home() -> Path:
    given = os.environ.get("PIDLAB_TR1_HOME")
    if given:
        return Path(given)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "PIDReader" / "tr1"


def detection_path(source_sha256: str, page: int) -> Path:
    if not _SHA.match(source_sha256 or ""):
        raise ValueError("source_sha256 must be 64 lowercase hex characters")
    return home() / "detections" / source_sha256 / f"page_{int(page)}.json"


def queue_path() -> Path:
    return home() / "corrections" / "queue.jsonl"


def batches_dir() -> Path:
    return home() / "batches"


def family_lock_path() -> Path:
    return home() / "family_lock.json"


def write_json_atomic(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True), encoding="utf-8", newline="")
    os.replace(tmp, path)


def read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
