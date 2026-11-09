"""Engineering text parsing (Rev X, WPU-04): quantities, line sizes, text classification. Pure functions, deterministic.

Every parsed value keeps the verbatim source text next to any normalised number and the *exact* original unit. Pressure basis
(gauge / absolute) is never defaulted: a unit without a basis stays ``UNKNOWN``. Missing values stay ``None``, never 0.
Classification returns every rule that matched, in precedence order, so ambiguity stays visible (``NPS 20`` is a size, not a tag;
``LINE 200-2`` is a line reference, not a drawing number; ``DP`` can be design or differential pressure).
"""
from __future__ import annotations

import re
from fractions import Fraction

VERSION = "engineering-text-v1"
_NUM = r"[-+]?\d+(?:[.,]\d+)?"
_MIXED = r"\d+\s+\d+/\d+|\d+/\d+"

_PRESSURE = re.compile(rf"(?P<val>{_NUM})\s*(?P<unit>kPa|MPa|Pa|bar|psi|kg/cm2|mbar)\s*(?:\(\s*(?P<b1>g|a|abs|gauge)\s*\)|(?P<b2>g|a)(?![A-Za-z]))?", re.I)
_TEMP = re.compile(rf"(?P<val>{_NUM})\s*(?:°|º|deg\.?\s*|degrees?\s*)\s*(?P<unit>[CF])\b", re.I)
_LENGTH = re.compile(rf"(?P<val>{_NUM})\s*(?P<unit>mm|cm|in(?:ch(?:es)?)?|m)\b|(?P<val2>{_NUM})\s*(?P<unit2>\")", re.I)
_POWER = re.compile(rf"(?P<val>{_NUM})\s*(?P<unit>BTU\s*/\s*h(?:r)?|BTU|MW|kW|W)\b", re.I)
_RANGE = re.compile(rf"(?P<lo>{_NUM})\s*(?:-|to|–)\s*(?P<hi>{_NUM})\s*(?P<rest>kPa|MPa|Pa|bar|psi|mm|in|°\s*[CF])", re.I)
_TYPE_WORDS = (
    ("SETPOINT", re.compile(r"\b(?:SP|SET\s*POINT|SETPOINT|SET)\b\s*[=:]?", re.I)),
    ("DESIGN", re.compile(r"\b(?:DESIGN|MAWP|MDP)\b", re.I)),
    ("OPERATING", re.compile(r"\b(?:OPERATING|NORMAL|NOP|MOP|MAOP)\b", re.I)),
    ("RATING", re.compile(r"\b(?:RATING|CLASS|ANSI|PN)\b", re.I)),
    ("SIZE", re.compile(r"\b(?:NPS|DN|SIZE)\b", re.I)),
)
_STATES = {"TBD": "TBD", "HOLD": "HOLD", "N/A": "NOT_APPLICABLE", "NA": "NOT_APPLICABLE", "-": "UNKNOWN", "--": "UNKNOWN"}
_PRESSURE_KPA = {"kpa": 1.0, "mpa": 1000.0, "pa": 0.001, "bar": 100.0, "psi": 6.894757293, "kg/cm2": 98.0665, "mbar": 0.1}
_POWER_W = {"w": 1.0, "kw": 1000.0, "mw": 1e6, "btu": None, "btu/h": 0.29307107, "btu/hr": 0.29307107}


def _num(text: str) -> float:
    return float(text.replace(",", "."))


def _basis(m) -> str:
    b = (m.group("b1") or m.group("b2") or "").lower()
    if b in ("g", "gauge"):
        return "GAUGE"
    if b in ("a", "abs"):
        return "ABSOLUTE"
    unit = m.group("unit").lower()
    return "UNKNOWN"


def numeric_type_for(context: str) -> tuple[str, list[str]]:
    """Numeric type from nearby label text. Ambiguity is returned as alternatives, never guessed away."""
    found = [name for name, rx in _TYPE_WORDS if rx.search(context)]
    if re.search(r"\bDP\b", context) and "DESIGN" not in found:
        return "UNKNOWN", ["DESIGN", "DIFFERENTIAL"]          # DP is genuinely ambiguous on drawings
    if not found:
        return "UNKNOWN", []
    if len(found) > 1:
        return "CONFLICTING", found
    return found[0], []


def parse_quantity(text: str, *, context: str = "") -> dict:
    """Parse one quantity. ``context`` (row/column label) only informs numeric type and missing units."""
    verbatim = text.strip()
    base = {"verbatim": verbatim, "value": None, "normalized_value": None, "original_unit": None, "normalized_unit": None,
            "pressure_basis": None, "numeric_type": "UNKNOWN", "qualifier": "", "status": "UNPARSED", "alternatives": [],
            "parser": VERSION}
    nt, alts = numeric_type_for(verbatim + " " + context)
    base["numeric_type"], base["alternatives"] = nt, alts
    if verbatim.upper() in _STATES:
        base["status"] = _STATES[verbatim.upper()]
        return base
    sp = re.search(r"\b(SP|SET\s*POINT|SETPOINT)\s*[=:]\s*", verbatim, re.I)
    if sp:
        base["qualifier"] = "SETPOINT_ASSIGNMENT"
    rng = _RANGE.search(verbatim)
    if rng:
        base.update(status="PARSED", numeric_type="RANGE" if nt in ("UNKNOWN",) else nt, value=[_num(rng["lo"]), _num(rng["hi"])],
                    original_unit=rng["rest"].replace(" ", ""), qualifier=base["qualifier"] or "RANGE")
        return base
    m = _PRESSURE.search(verbatim)
    if m:
        unit = m.group("unit")
        val = _num(m.group("val"))
        base.update(status="PARSED", value=val, original_unit=unit + (f"({m.group('b1') or m.group('b2')})" if (m.group("b1") or m.group("b2")) else ""),
                    pressure_basis=_basis(m))
        factor = _PRESSURE_KPA[unit.lower()]
        base.update(normalized_value=round(val * factor, 6), normalized_unit="kPa")
        return base
    m = _TEMP.search(verbatim)
    if m:
        val, unit = _num(m.group("val")), m.group("unit").upper()
        base.update(status="PARSED", value=val, original_unit="°" + unit,
                    normalized_value=round(val if unit == "C" else (val - 32) * 5 / 9, 6), normalized_unit="°C")
        if nt == "UNKNOWN":
            base["numeric_type"] = "UNKNOWN"
        return base
    m = _POWER.search(verbatim)
    if m:
        val, unit = _num(m.group("val")), re.sub(r"\s+", "", m.group("unit")).lower()
        factor = _POWER_W.get(unit)
        base.update(status="PARSED", value=val, original_unit=re.sub(r"\s+", "", m.group("unit")))
        if factor is not None:
            base.update(normalized_value=round(val * factor, 6), normalized_unit="W")
        else:
            base["qualifier"] = base["qualifier"] or "ENERGY_UNIT_NO_RATE"      # BTU without /h is not a power; keep unnormalised
        return base
    m = _LENGTH.search(verbatim)
    if m:
        raw = m.group("val") or m.group("val2")
        unit = (m.group("unit") or m.group("unit2")).lower()
        unit = "in" if unit.startswith("in") or unit == '"' else unit
        val = _num(raw)
        mm = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}[unit]
        base.update(status="PARSED", value=val, original_unit=unit, normalized_value=round(val * mm, 6), normalized_unit="mm")
        return base
    # unit-less number: only meaningful when the label supplies a unit; the value stays verbatim, the unit stays unknown
    m = re.fullmatch(rf"\s*({_NUM})\s*", verbatim)
    if m:
        base.update(status="PARSED_NO_UNIT", value=_num(m.group(1)))
        ctx = _PRESSURE.search(context) or None
        lab = re.search(rf"(kPa|MPa|Pa|bar|psi)\s*(?:\(\s*(g|a)\s*\))?", context, re.I)
        if lab:
            unit = lab.group(1)
            basis = {"g": "GAUGE", "a": "ABSOLUTE"}.get((lab.group(2) or "").lower(), "UNKNOWN")
            base.update(original_unit=unit + (f"({lab.group(2)})" if lab.group(2) else ""), pressure_basis=basis,
                        normalized_value=round(base["value"] * _PRESSURE_KPA[unit.lower()], 6), normalized_unit="kPa",
                        qualifier="UNIT_FROM_LABEL")
        elif re.search(r"\b(?:TEMP|TEMPERATURE|°\s*[CF])", context, re.I):
            tm = re.search(r"°\s*([CF])", context)
            if tm:
                u = tm.group(1).upper()
                base.update(original_unit="°" + u, normalized_value=round(base["value"] if u == "C" else (base["value"] - 32) * 5 / 9, 6),
                            normalized_unit="°C", qualifier="UNIT_FROM_LABEL")
        return base
    return base


def parse_line_size(text: str) -> dict:
    """Pipe sizes: ``NPS 20``, ``NPS 1 1/2``, ``NPS 30 x NPS 20`` (reducer), ``20"``, ``DN 500``."""
    t = text.strip()
    out = {"verbatim": t, "kind": "UNKNOWN", "sizes": [], "status": "UNPARSED", "parser": VERSION}
    token = rf"(?:(?P<sys>NPS|DN)\s*(?P<v>{_MIXED}|\d+(?:\.\d+)?)|(?P<inch>{_MIXED}|\d+(?:\.\d+)?)\s*(?:\"|IN\b|INCH))"

    def one(m) -> dict | None:
        raw = m.group("v") or m.group("inch")
        if raw is None:
            return None
        parts = raw.split()
        try:
            val = float(sum(Fraction(p) for p in parts))
        except (ValueError, ZeroDivisionError):
            return None
        system = (m.group("sys") or "NPS_INCH").upper()
        return {"system": "NPS" if system in ("NPS", "NPS_INCH") else "DN", "value": val, "verbatim": m.group(0).strip(),
                "unit": "in" if system in ("NPS", "NPS_INCH") else "mm"}
    def parse_one(chunk: str) -> dict | None:
        m = re.fullmatch(rf"\s*{token}\s*", chunk)
        return one(m) if m else None

    whole = parse_one(t)
    if whole:
        out.update(kind="SIZE", sizes=[whole], status="PARSED")
        return out
    parts = re.split(r"\s+[xX]\s+|\s*×\s*", t)
    if len(parts) == 2:
        first, second = parse_one(parts[0]), parse_one(parts[1])
        if first and second:
            out.update(kind="REDUCER", sizes=[first, second], status="PARSED")
    return out


_DWG = re.compile(r"\b\d{3,5}-\d{2}-[A-Z]{2}-\d{2}-\d{3}\b")
_DATE = re.compile(r"\b(?:\d{4}[-/.]\d{2}[-/.]\d{2}|\d{1,2}[-/ ](?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*[-/ ]\d{2,4})\b", re.I)
_LINE_REF = re.compile(r"\bLINE\s+[A-Z0-9][A-Z0-9-]*\b", re.I)
_SPEC = re.compile(r"\b\d{1,2}(?:\"|IN)?-[A-Z]{1,4}-\d{2,5}(?:-[A-Z0-9]{2,5})?\b")
_ISA = re.compile(r"\b(?!NPS|DN|PN|LINE|HOLD|REV|SP\b)[A-Z]{2,4}-?\d{2,4}[A-Z]?\b")
_CLASS = re.compile(r"\b(?:CLASS|ANSI|CL)\s*\.?\s*\d{2,4}\b|\b\d{3,4}\s*#|\bPN\s*\d{1,3}\b", re.I)
_HOLD = re.compile(r"^\s*HOLD\s*\d*\b", re.I)
_NOTE = re.compile(r"^\s*(?:NOTES?\b|\d{1,2}[.)]\s)", re.I)
_PRECEDENCE = ("DRAWING_REFERENCE", "DATE", "PIPING_SPEC", "REDUCER_SIZE", "SIZE", "LINE_REFERENCE", "PRESSURE_CLASS", "SETPOINT",
               "QUANTITY", "HOLD", "NOTE", "INSTRUMENT_TAG")


def classify_text(text: str) -> dict:
    """All rule matches for a text, in precedence order. ``primary`` is the first; ``UNKNOWN`` is a valid answer."""
    t = text.strip()
    kinds: list[dict] = []

    def hit(kind: str, rule: str, extra: dict | None = None) -> None:
        kinds.append({"kind": kind, "rule": rule, **(extra or {})})
    if _DWG.search(t):
        hit("DRAWING_REFERENCE", "drawing-number-pattern")
    if _DATE.search(t):
        hit("DATE", "date-pattern")
    if _SPEC.search(t) and not _DWG.search(t):
        hit("PIPING_SPEC", "size-service-number-pattern")
    sz = parse_line_size(t)
    if sz["status"] == "PARSED":
        hit("REDUCER_SIZE" if sz["kind"] == "REDUCER" else "SIZE", "nps-dn-inch", {"sizes": sz["sizes"]})
    if _LINE_REF.search(t):
        hit("LINE_REFERENCE", "line-reference")
    if _CLASS.search(t):
        hit("PRESSURE_CLASS", "ansi-pn-class")
    if re.search(r"\b(SP|SET\s*POINT|SETPOINT)\s*[=:]", t, re.I):
        hit("SETPOINT", "setpoint-assignment")
    if parse_quantity(t)["status"].startswith("PARSED") and not any(k["kind"] == "PIPING_SPEC" for k in kinds):
        hit("QUANTITY", "numeric-with-unit")
    if _HOLD.search(t):
        hit("HOLD", "hold-marker")
    if _NOTE.search(t):
        hit("NOTE", "note-marker")
    if _ISA.search(t) and not any(k["kind"] in ("SIZE", "REDUCER_SIZE", "LINE_REFERENCE", "HOLD", "DRAWING_REFERENCE", "PIPING_SPEC") for k in kinds):
        hit("INSTRUMENT_TAG", "isa-like-pattern")
    kinds.sort(key=lambda k: _PRECEDENCE.index(k["kind"]))
    return {"verbatim": t, "primary": kinds[0]["kind"] if kinds else "UNKNOWN", "matches": kinds,
            "ambiguous": len({k["kind"] for k in kinds}) > 1, "parser": VERSION}
