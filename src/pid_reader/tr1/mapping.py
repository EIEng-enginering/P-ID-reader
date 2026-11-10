"""Coarse detector class -> catalogue family (a PROPOSAL, never an engineering class).

The E5 detector knows four coarse PID2Graph classes. None of them is an engineering class: ``valve`` does not say gate, ball or control;
``instrumentation`` does not say field, panel or shared display; ``general`` folds tanks, pumps and every other equipment symbol together.
So the mapping only suggests the *family* and the catalogue's own "type unknown" class for it. The engineer picks the real class when
confirming or editing; nothing is ever assigned automatically.
"""
from __future__ import annotations

COARSE_TO_FAMILY = {
    "valve": ("VALVE", "CLS.VALVE.UNKNOWN"),
    "instrumentation": ("INSTRUMENT", "CLS.INSTRUMENT.UNKNOWN"),
    "general": ("EQUIPMENT", "CLS.EQUIPMENT.UNKNOWN"),
    "arrow": ("ANNOTATION", None),      # flow / dimension arrows: the catalogue has no 'unknown arrow' class, so none is suggested
}
NOTE = ("Coarse detector class only (PID2Graph valve / instrumentation / general / arrow). The catalogue family is a suggestion; the engineering "
        "class must be chosen by an engineer. Uncalibrated score. Not verified.")


def family_of(coarse: str) -> tuple[str, str | None] | None:
    return COARSE_TO_FAMILY.get(coarse)


def enrich(detection: dict) -> dict:
    """Add the suggested family and class to one detector record, keeping every original field and the PROPOSED state."""
    out = dict(detection)
    fam = family_of(detection.get("catalogue_class"))
    out["coarse_class"] = detection.get("catalogue_class")
    out["suggested_family"] = fam[0] if fam else None
    out["suggested_class_id"] = fam[1] if fam else None
    out["mapping_note"] = NOTE
    out["review_state"] = "PROPOSED"
    return out


def class_choices(catalogue: dict, coarse: str | None) -> list[dict]:
    """Catalogue classes an engineer may choose, the suggested family first. Deprecated classes are never offered."""
    fam = family_of(coarse or "")
    domain = fam[0] if fam else None
    live = [c for c in catalogue["classes"] if c.get("status") != "DEPRECATED"]
    return sorted(live, key=lambda c: (c["domain"] != domain, c["domain"] == "STATE", c["domain"], c["class_id"]))
