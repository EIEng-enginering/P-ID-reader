"""TR1 (Grok training programme) feature switches. Every switch defaults to OFF; OFF means no TR1 code path runs and no TR1 file is written.

A switch is read, in this order, from an explicit argument, the environment variable named exactly like the switch (``1``/``on``/``true``/``yes``
or ``0``/``off``/``false``/``no``), the per-user settings file (``%LOCALAPPDATA%/PIDReader/tr1_features.json`` or the path in
``PIDLAB_TR1_SETTINGS``; the Learned detector menu writes it), then OFF. An unknown value is an error, never silently ON.

Switches (each one gates one module; none changes an accepted decision, the standalone database, the package manifest or the Worksheet R1 output):

``PIDLAB_SYMBOL_FRCNN_TR1``       learned symbol detector (PROPOSED detections in a separate sidecar; needs the optional torch component)
``PIDLAB_SYMBOL_CATALOGUE_TR1``   versioned symbol catalogue v1.0.0 (class ids for review and correction)
``PIDLAB_CORRECTION_QUEUE_TR1``   engineer confirm / reject / edit actions recorded in a hash-chained append-only queue
``PIDLAB_TRAINING_BATCH_TR1``     versioned training-batch builder (needs an explicit usage approval id and approver)
``PIDLAB_LOCAL_TRAINER_TR1``      separate offline trainer tool (tools/tr1_train); the app only reports whether it is enabled
``PIDLAB_MODEL_REGISTRY_TR1``     model registry used by the trainer tool (candidate / active / previous, gated promotion, rollback)

Not integrated (not requested or failed their own gates): the extended template library and the abstain-only verifier (E1 runtime gate H4 FAILED).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

FLAGS = {
    "PIDLAB_SYMBOL_FRCNN_TR1": "Learned symbol detector (Faster R-CNN, PROPOSED detections only)",
    "PIDLAB_SYMBOL_CATALOGUE_TR1": "Versioned symbol catalogue v1.0.0",
    "PIDLAB_CORRECTION_QUEUE_TR1": "Correction capture queue (hash-chained, append-only)",
    "PIDLAB_TRAINING_BATCH_TR1": "Versioned training-batch builder",
    "PIDLAB_LOCAL_TRAINER_TR1": "Offline local trainer tool",
    "PIDLAB_MODEL_REGISTRY_TR1": "Model registry for trainer output",
}
_TRUE = {"1", "on", "true", "yes"}
_FALSE = {"0", "off", "false", "no", ""}


def settings_path() -> Path:
    given = os.environ.get("PIDLAB_TR1_SETTINGS")
    if given:
        return Path(given)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "PIDReader" / "tr1_features.json"


def _file_values() -> dict:
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if k in FLAGS and isinstance(v, (str, bool))} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _parse(name: str, raw) -> bool:
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise ValueError(f"{name} must be on or off (got {raw!r})")


def enabled(name: str, explicit: bool | str | None = None) -> bool:
    """True only when the switch was turned on; any unreadable settings file means OFF."""
    if name not in FLAGS:
        raise ValueError(f"Unknown TR1 switch {name!r}")
    if explicit is not None:
        return _parse(name, explicit)
    env = os.environ.get(name)
    if env is not None:
        return _parse(name, env)
    return _parse(name, _file_values().get(name, "off"))


def source(name: str) -> str:
    """Where the effective value of ``name`` comes from: ``environment``, ``settings file`` or ``default``."""
    if name not in FLAGS:
        raise ValueError(f"Unknown TR1 switch {name!r}")
    if os.environ.get(name) is not None:
        return "environment"
    return "settings file" if name in _file_values() else "default"


def set_flag(name: str, on: bool) -> bool:
    """Persist a switch in the settings file (an environment variable still wins). Returns the stored value."""
    if name not in FLAGS:
        raise ValueError(f"Unknown TR1 switch {name!r}")
    data = _file_values()
    data[name] = "on" if on else "off"
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8", newline="")
    os.replace(tmp, path)
    return bool(on)


def inventory() -> dict:
    return {"switches": {n: {"on": enabled(n), "source": source(n), "what": FLAGS[n]} for n in FLAGS}, "settings_file": str(settings_path())}
