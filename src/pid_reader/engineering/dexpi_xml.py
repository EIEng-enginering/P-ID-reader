"""DEXPI 2.0.1 export status and mapping report (Rev X, WPU-15). Honest by construction.

A file may be called DEXPI-conformant only if it validates against the official DEXPI XSD *and* its entity/nozzle/piping semantics are mapped.
Neither condition can be met inside this offline build:

* the official DEXPI 2.0.1 XSD is not bundled (no permission to redistribute it was established, and nothing is downloaded at run time);
* no XML-schema validator library is part of the locked environment;
* the typed graph is built from unverified drawing readings: no verified nozzles, line classes or flow.

So :func:`export_dexpi_xml` **refuses**, with a specific, machine-readable status, unless the owner supplies the official XSD and a validator is
installed *and* the produced file validates. :func:`mapping_report` is what is delivered instead: for each entity and relationship kind in a
snapshot, what a DEXPI export would need, what would be lost, and the preserved-unknown policy. Target class names in the report are descriptive
concepts, explicitly ``UNVERIFIED_AGAINST_SPEC``; they are not claims about the standard's identifiers.
"""
from __future__ import annotations

from pathlib import Path

from .dexpi import DexpiNotAvailable

VERSION = "dexpi-status-v1"
TARGET_VERSION = "2.0.1"
STATUS_DISABLED = "DISABLED_NO_VALIDATED_MAPPING"
STATUS_BLOCKED_XSD = "BLOCKED_OFFICIAL_XSD_NOT_SUPPLIED"
STATUS_BLOCKED_VALIDATOR = "BLOCKED_NO_XML_SCHEMA_VALIDATOR"

# descriptive concepts only (not identifiers from the DEXPI specification)
ENTITY_MAPPING = {
    "EQUIPMENT": ("equipment item (type from class, e.g. vessel / pump / exchanger)", "PARTIAL", "needs verified nozzles and equipment attributes"),
    "EQUIPMENT_NOZZLE": ("nozzle of an equipment item", "NOT_AVAILABLE", "the reader proposes ports, not verified nozzles"),
    "VALVE": ("piping valve component on a piping segment", "PARTIAL", "valve class is a proposal; position/fail state unknown"),
    "VALVE_ACTUATOR": ("actuating system of a valve", "PARTIAL", "actuation class is an independent proposal"),
    "INSTRUMENT": ("instrumentation function / process instrumentation item", "PARTIAL", "needs verified signal topology"),
    "INSTRUMENT_LOOP": ("instrumentation loop", "PARTIAL", "loops here require a drawn signal path; logic is not shown"),
    "CONTROL_SYSTEM": ("process control function / system reference", "NOT_AVAILABLE", "only a wording mention is read"),
    "SAFETY_DEVICE": ("protective device (as drawn)", "NOT_AVAILABLE", "mention only; effectiveness and credit not assessed"),
    "OFFPAGE_CONNECTOR": ("piping off-page connector", "PARTIAL", "needs two-sheet evidence and review"),
    "PIPING_LINE": ("piping network system / segment", "NOT_AVAILABLE", "line numbers, class and specification are not yet structured records"),
    "PIPING_SEGMENT": ("piping network segment", "NOT_AVAILABLE", "ink paths are not verified pipes"),
    "FITTING": ("piping fitting (reducer, flange ...)", "NOT_AVAILABLE", "not detected"),
    "ANNOTATION": ("text annotation", "UNMAPPED", "kept in a side manifest"),
    "TABLE": ("table (no standard counterpart)", "UNMAPPED", "kept in a side manifest"),
    "TABLE_CELL": ("table cell value (no standard counterpart)", "UNMAPPED", "kept in a side manifest"),
    "UNCLASSIFIED_SYMBOL": ("unclassified graphical symbol", "UNMAPPED", "class withheld; never forced into a DEXPI class"),
}
RELATION_MAPPING = {
    "DRAWN_CONNECTS": ("piping connection between nozzles / segment ends", "PARTIAL", "ink path between ports; not a verified connection or flow"),
    "SIGNAL_CONNECTS": ("information flow / signal line", "PARTIAL", "drawn signal line; logic not shown"),
    "MEASURES": ("measuring point relation", "PARTIAL", "not a verified tapping point"),
    "CONTROLS": ("control relation", "PARTIAL", "role from tag letters on a drawn signal path"),
    "ACTUATES": ("actuation relation", "PARTIAL", "as above"),
    "POSITION_FEEDBACK": ("position feedback relation", "PARTIAL", "as above"),
    "INDICATES": ("indication relation", "PARTIAL", "as above"),
    "ALARM_REFERENCE": ("alarm/trip reference", "NOT_AVAILABLE", "mention only"),
    "PROPOSED_SAME_AS": ("identity of occurrences across sheets", "UNMAPPED", "not part of an interchange file; stays a proposal"),
    "OFFPAGE_MATCH_CANDIDATE": ("off-page connector pairing", "UNMAPPED", "proposal"),
    "OTHER": ("unmapped relation", "UNMAPPED", "kept in a side manifest"),
}


def mapping_report(snapshot: dict) -> dict:
    """Per-kind mapping status for ``snapshot`` (an ``engineering-intelligence-v1`` document). Never produces XML."""
    kinds: dict[str, int] = {}
    for e in snapshot.get("entities", []):
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    rels: dict[str, int] = {}
    for r in snapshot.get("relationships", []):
        rels[r["type"]] = rels.get(r["type"], 0) + 1
    ent_rows = [{"kind": k, "count": n, "concept": ENTITY_MAPPING.get(k, ("unmapped", "UNMAPPED", "no mapping defined"))[0],
                 "status": ENTITY_MAPPING.get(k, ("", "UNMAPPED", ""))[1], "gap": ENTITY_MAPPING.get(k, ("", "", "no mapping defined"))[2],
                 "target_class_verified": False} for k, n in sorted(kinds.items())]
    rel_rows = [{"type": k, "count": n, "concept": RELATION_MAPPING.get(k, ("unmapped", "UNMAPPED", ""))[0], "status": RELATION_MAPPING.get(k, ("", "UNMAPPED", ""))[1],
                 "gap": RELATION_MAPPING.get(k, ("", "", "no mapping defined"))[2], "target_class_verified": False} for k, n in sorted(rels.items())]
    return {"schema": "pid-reader-dexpi-mapping-report-v1", "version": VERSION, "target": f"DEXPI {TARGET_VERSION}", "export_status": STATUS_DISABLED,
            "xsd_validation": "NOT_RUN", "dexpi_conformant": False, "entities": ent_rows, "relationships": rel_rows,
            "preserved_unknown_policy": ("Unknown, withheld-class and unmapped items are kept in a side manifest next to any future export, never dropped "
                                         "and never forced into a DEXPI class; a lossless round trip is NOT claimed."),
            "prerequisites": ["official DEXPI 2.0.1 XSD supplied by the owner (licence and source checked)", "an XML-schema validator in the locked environment",
                              "reviewed, typed connectivity with verified nozzles", "mapping of every exported class against the specification",
                              "inverse-import round trip on a supported sample"],
            "note": "Class names above are descriptive concepts marked UNVERIFIED_AGAINST_SPEC; they are not DEXPI identifiers."}


def status(xsd_path: str | Path | None = None) -> dict:
    """What would block an export right now."""
    validator = _validator_name()
    if xsd_path is None or not Path(xsd_path).is_file():
        code, why = STATUS_BLOCKED_XSD, "the official DEXPI 2.0.1 XSD has not been supplied (not bundled, never downloaded)"
    elif validator is None:
        code, why = STATUS_BLOCKED_VALIDATOR, "no XML-schema validator (xmlschema or lxml) is installed in this environment"
    else:
        code, why = STATUS_DISABLED, "mapping is not validated against the specification; export stays disabled"
    return {"status": code, "reason": why, "validator": validator, "dexpi_conformant": False, "version": VERSION}


def _validator_name() -> str | None:
    for name in ("xmlschema", "lxml"):
        try:
            __import__(name)
            return name
        except ImportError:
            continue
    return None


def export_dexpi_xml(snapshot: dict, destination: str | Path, *, xsd_path: str | Path | None = None) -> Path:
    """Always refuses today. The exception carries the specific status; no file is written."""
    st = status(xsd_path)
    raise DexpiNotAvailable(f"{st['status']}: {st['reason']}. Use mapping_report() for what a validated export would need.")
