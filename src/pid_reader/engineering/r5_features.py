"""R5 update feature switches (OFF / SHADOW / ON). Every switch defaults to OFF so legacy behaviour and output bytes are unchanged.

A mode is read, in this order, from an explicit argument, then the environment variable ``PID_R5_<NAME>`` (``off`` | ``shadow`` | ``on``,
case-insensitive), then the per-user settings file (``%LOCALAPPDATA%/PIDReader/r5_features.json``, or the path in ``PID_R5_SETTINGS``; the
R5 menu writes it), then OFF. An unknown value is an error, never silently treated as ON. A missing or unreadable settings file means OFF.

* OFF    -- the legacy code path runs; nothing new is computed, written or reported.
* SHADOW -- the legacy result is returned unchanged and is the only authoritative output. The candidate result is computed and written to a
            SEPARATE diagnostic location (never into accepted data, the database, the package manifest or any host output).
* ON     -- the new behaviour is part of the normal output. Each switch states what it adds; none of them changes an accepted decision.

Switches
--------
``DEXPI``         proposed DEXPI 2.0.1 export (``dexpi_proposed``). OFF keeps the refusing stub of Rev X.
``PAGE_FRAME``    PDF page provenance (MediaBox/CropBox/Rotate/UserUnit) and the unverified-scale measurement guard (``formats.page_provenance``).
``REVIEW_LEDGER`` separate review ledger of ambiguous / blocked connection candidates (``connection_review``).

Not switches (kept disabled, research only): crowded tag matching, stacked/rotated optical OCR, general instrument/port/signal recognition.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

OFF, SHADOW, ON = "OFF", "SHADOW", "ON"
MODES = (OFF, SHADOW, ON)
FEATURES = ("DEXPI", "PAGE_FRAME", "REVIEW_LEDGER")
DISABLED_RESEARCH_ONLY = {
    "CROWDED_MATCHING": "R5 principal gate FAILED (very-crowded precision 94.51 % < 95 %; regression recall below the frozen floors)",
    "OPTICAL_STACKED_OCR": "approved OCR engine/models were unavailable in R5; exact optical accuracy was never measured",
    "GENERAL_PORT_SIGNAL_RECOGNITION": "only a restricted supplied-circle/legend diagnostic was tested",
}


def mode(name: str, explicit: str | None = None) -> str:
    """Resolved mode for ``name`` (one of :data:`FEATURES`)."""
    if name not in FEATURES:
        raise ValueError(f"Unknown R5 feature {name!r}")
    raw = explicit if explicit is not None else os.environ.get("PID_R5_" + name)
    if raw is None:
        raw = _file_modes().get(name, OFF)
    value = str(raw).strip().upper()
    if value == "":
        value = OFF
    if value not in MODES:
        raise ValueError(f"PID_R5_{name} must be off, shadow or on (got {raw!r})")
    return value


def settings_path() -> Path:
    given = os.environ.get("PID_R5_SETTINGS")
    if given:
        return Path(given)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "PIDReader" / "r5_features.json"


def _file_modes() -> dict:
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if k in FEATURES and isinstance(v, str)} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def set_mode(name: str, value: str) -> str:
    """Persist ``value`` for ``name`` in the settings file (an environment variable still wins). Returns the stored mode."""
    if name not in FEATURES:
        raise ValueError(f"Unknown R5 feature {name!r}")
    value = str(value).strip().upper()
    if value not in MODES:
        raise ValueError("mode must be OFF, SHADOW or ON")
    data = _file_modes()
    data[name] = value
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8", newline="")
    os.replace(tmp, path)
    return value


def inventory() -> dict:
    """Current state of every R5 switch, for diagnostics and release notes."""
    return {"features": {n: mode(n) for n in FEATURES}, "settings_file": str(settings_path()), "disabled_research_only": dict(DISABLED_RESEARCH_ONLY)}
