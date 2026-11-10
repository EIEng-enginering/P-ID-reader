"""Versioned engineering symbol catalogue (TRAINING_Q1). Stable class/variant IDs, hierarchy, aliases, lookalikes, evidence
requirements, ports, phase, provenance and mappings to (a) the frozen Worksheet R1 class enum, (b) the existing app
`symbol_library` template ids, (c) DEXPI 2.0.1 class names (metadata only, checked against the official Plant.xml when available).

Rules enforced by `validate()`:
* IDs are immutable: a published ID is never removed or re-meaned; it may only be DEPRECATED with `replaced_by`.
* visual depiction (variant) is separate from engineering meaning (class); one variant may carry class alternatives;
  every family has an UNKNOWN class and the catalogue has UNRESOLVED/UNKNOWN states - a class is never forced.
* artwork provenance must be ORIGINAL_* or a rights-ELIGIBLE source id from the source register; PENDING/REJECTED sources refused.
This catalogue is NOT exhaustive standards coverage (ISO 10628 / ISA-5.1 are not copied; names only)."""
from __future__ import annotations
import hashlib, json, re

SCHEMA = "pid-symbol-catalogue/1"
CLASS_ID = re.compile(r"^CLS\.[A-Z]+(\.[A-Z0-9_]+){1,3}$")
VAR_ID = re.compile(r"^VAR\.[A-Z]+(\.[A-Z0-9_]+){2,4}$")
DOMAINS = ("EQUIPMENT", "VALVE", "ACTUATOR", "INSTRUMENT", "FITTING", "CONNECTOR", "ANNOTATION", "PORT", "LINE", "STATE")
R1_CLASSES = {"VESSEL", "TANK", "COLUMN", "HEAT_EXCHANGER", "PUMP", "COMPRESSOR", "FILTER", "VALVE_MANUAL", "VALVE_CONTROL",
              "VALVE_ONOFF", "VALVE_CHECK", "PSV", "RUPTURE_DISC", "INSTRUMENT", "OTHER", "UNKNOWN"}   # frozen Worksheet R1 enum (app symbol_catalog.R1_CLASSES)
STATUSES = ("ACTIVE", "DRAFT", "DEPRECATED")
PROVENANCE_OK = ("ORIGINAL_APP_LIBRARY", "ORIGINAL_TR1_AUTHORED")
LINE_TYPES = ("PROCESS", "DUCT", "GLYCOL", "UTILITY", "ELECTRICAL", "PNEUMATIC", "HYDRAULIC", "CONTROL_SIGNAL", "SOFTWARE_LINK",
              "CAPILLARY", "UNKNOWN")          # superset of the Stage1 annotation handbook types; UNKNOWN is a type, UNRESOLVED abstains
PORT_KINDS = ("PROCESS_UNKNOWN", "NOZZLE", "INSTRUMENT_PORT", "ACTUATOR_SIGNAL", "SIGNAL_IN", "SIGNAL_OUT", "OFF_PAGE")


def _c(cid, domain, name, *, r1, phase, aliases=(), dexpi=None, lookalikes=(), evidence=(), ports=(), status="ACTIVE", note=None, replaced_by=None):
    return {"class_id": cid, "domain": domain, "name": name, "r1_class": r1, "training_phase": phase, "aliases": list(aliases),
            "dexpi_class": dexpi, "lookalike_class_ids": list(lookalikes), "evidence_required": list(evidence), "port_kinds": list(ports),
            "status": status, "note": note, "replaced_by": replaced_by}


def _v(vid, cid, *, template, provenance, alternatives=(), directional=False, lookalike_risk=(), status="ACTIVE"):
    return {"variant_id": vid, "class_id": cid, "template_id": template, "artwork_provenance": provenance,
            "class_alternatives": list(alternatives), "directional": directional, "lookalike_risk": list(lookalike_risk), "status": status}


EV_SHAPE = "symbol geometry match with source evidence box"
EV_TAG = "associated tag text (separate association evidence)"
EV_LEGEND = "project legend/notes confirming convention"
EV_PORT = "drawn line terminating at the port location"

CLASSES = [
    # ---- states (never forced classes)
    _c("CLS.STATE.UNKNOWN", "STATE", "Unknown symbol", r1="UNKNOWN", phase=1, note="emitted when evidence is insufficient"),
    _c("CLS.STATE.UNRESOLVED", "STATE", "Unresolved (alternatives retained)", r1="UNKNOWN", phase=1, note="abstention with alternatives"),
    # ---- valves (phase 1)
    _c("CLS.VALVE.UNKNOWN", "VALVE", "Valve, type unknown", r1="UNKNOWN", phase=1, dexpi="Valve", evidence=[EV_SHAPE]),
    _c("CLS.VALVE.GATE", "VALVE", "Gate valve", r1="VALVE_MANUAL", phase=1, aliases=["GV", "gate"], dexpi="GateValve",
       lookalikes=["CLS.VALVE.ISOLATION_UNSPECIFIED", "CLS.ANNOTATION.DIMENSION_ARROWS"], evidence=[EV_SHAPE], ports=["PROCESS_UNKNOWN"]),
    _c("CLS.VALVE.ISOLATION_UNSPECIFIED", "VALVE", "Isolation valve, type by project convention", r1="VALVE_MANUAL", phase=1,
       dexpi="Valve", lookalikes=["CLS.VALVE.GATE", "CLS.VALVE.BALL"], evidence=[EV_SHAPE, EV_LEGEND], ports=["PROCESS_UNKNOWN"]),
    _c("CLS.VALVE.GLOBE", "VALVE", "Globe valve", r1="VALVE_MANUAL", phase=1, aliases=["globe"], dexpi="GlobeValve",
       lookalikes=["CLS.VALVE.BALL", "CLS.VALVE.NEEDLE"], evidence=[EV_SHAPE], ports=["PROCESS_UNKNOWN"]),
    _c("CLS.VALVE.BALL", "VALVE", "Ball valve", r1="VALVE_MANUAL", phase=1, aliases=["BV", "ball"], dexpi="BallValve",
       lookalikes=["CLS.VALVE.GLOBE", "CLS.VALVE.PLUG"], evidence=[EV_SHAPE], ports=["PROCESS_UNKNOWN"]),
    _c("CLS.VALVE.BUTTERFLY", "VALVE", "Butterfly valve", r1="VALVE_MANUAL", phase=1, aliases=["BFV", "butterfly"], dexpi="ButterflyValve",
       lookalikes=["CLS.VALVE.GATE"], evidence=[EV_SHAPE], ports=["PROCESS_UNKNOWN"]),
    _c("CLS.VALVE.CHECK", "VALVE", "Check (non-return) valve", r1="VALVE_CHECK", phase=1, aliases=["NRV", "check", "non-return"],
       dexpi="CheckValve", lookalikes=["CLS.ANNOTATION.FLOW_ARROW"], evidence=[EV_SHAPE], ports=["PROCESS_UNKNOWN"],
       note="direction is a drawn attribute, never inferred"),
    _c("CLS.VALVE.NEEDLE", "VALVE", "Needle valve", r1="VALVE_MANUAL", phase=1, aliases=["needle"], dexpi="NeedleValve",
       lookalikes=["CLS.VALVE.GLOBE"], evidence=[EV_SHAPE], ports=["PROCESS_UNKNOWN"]),
    _c("CLS.VALVE.PLUG", "VALVE", "Plug valve", r1="VALVE_MANUAL", phase=1, aliases=["plug", "cock"], dexpi="PlugValve",
       lookalikes=["CLS.VALVE.BALL"], evidence=[EV_SHAPE], ports=["PROCESS_UNKNOWN"]),
    _c("CLS.VALVE.ANGLE", "VALVE", "Angle valve", r1="VALVE_MANUAL", phase=2, aliases=["angle"], dexpi="AngleValve",
       evidence=[EV_SHAPE], ports=["PROCESS_UNKNOWN"]),
    _c("CLS.VALVE.THREE_WAY", "VALVE", "Three-way valve", r1="VALVE_MANUAL", phase=2, aliases=["3-way", "three way"], dexpi="ThreePortValve",
       lookalikes=["CLS.VALVE.GATE"], evidence=[EV_SHAPE, EV_PORT], ports=["PROCESS_UNKNOWN"]),
    _c("CLS.VALVE.SAFETY_RELIEF", "VALVE", "Safety / relief valve", r1="PSV", phase=1, aliases=["PSV", "PRV", "relief", "safety valve"],
       dexpi="SpringLoadedAngleGlobeSafetyValve", lookalikes=["CLS.VALVE.ANGLE"], evidence=[EV_SHAPE, EV_TAG], ports=["PROCESS_UNKNOWN"],
       note="drawing class only - NEVER safety/IPL/SIL credit"),
    _c("CLS.FITTING.RUPTURE_DISC", "FITTING", "Rupture / bursting disc", r1="RUPTURE_DISC", phase=2, aliases=["PSE", "bursting disc"],
       dexpi="RuptureDisc", evidence=[EV_SHAPE, EV_TAG], ports=["PROCESS_UNKNOWN"], note="drawing class only - no safety credit"),
    _c("CLS.VALVE.CONTROL_BODY", "VALVE", "Control valve (body + actuator evidence)", r1="VALVE_CONTROL", phase=2,
       aliases=["CV", "control valve"], dexpi="OperatedValve", evidence=[EV_SHAPE, "actuator evidence (separate)", EV_TAG],
       ports=["PROCESS_UNKNOWN", "ACTUATOR_SIGNAL"], note="composite: body class and actuation are separate evidence"),
    # ---- actuators (phase 1-2)
    _c("CLS.ACTUATOR.UNKNOWN", "ACTUATOR", "Actuator, type unknown", r1="UNKNOWN", phase=2),
    _c("CLS.ACTUATOR.MANUAL", "ACTUATOR", "Handwheel / manual operator", r1="VALVE_MANUAL", phase=1, evidence=[EV_SHAPE], ports=["ACTUATOR_SIGNAL"]),
    _c("CLS.ACTUATOR.DIAPHRAGM", "ACTUATOR", "Pneumatic diaphragm actuator", r1="VALVE_CONTROL", phase=1, evidence=[EV_SHAPE], ports=["ACTUATOR_SIGNAL"]),
    _c("CLS.ACTUATOR.SOLENOID", "ACTUATOR", "Solenoid actuator", r1="VALVE_ONOFF", phase=1, evidence=[EV_SHAPE], ports=["ACTUATOR_SIGNAL"]),
    _c("CLS.ACTUATOR.MOTOR", "ACTUATOR", "Motor actuator", r1="VALVE_ONOFF", phase=1, evidence=[EV_SHAPE], ports=["ACTUATOR_SIGNAL"]),
    _c("CLS.ACTUATOR.PISTON", "ACTUATOR", "Piston / cylinder actuator", r1="VALVE_ONOFF", phase=2, evidence=[EV_SHAPE], ports=["ACTUATOR_SIGNAL"]),
    # ---- instruments (phase 1/3)
    _c("CLS.INSTRUMENT.UNKNOWN", "INSTRUMENT", "Instrument, type unknown", r1="INSTRUMENT", phase=1, dexpi="ProcessInstrumentationFunction"),
    _c("CLS.INSTRUMENT.FIELD", "INSTRUMENT", "Field-mounted discrete instrument", r1="INSTRUMENT", phase=1, aliases=["bubble"],
       dexpi="ProcessInstrumentationFunction", lookalikes=["CLS.EQUIPMENT.PUMP_CENTRIFUGAL", "CLS.ANNOTATION.NOTE_CIRCLE"],
       evidence=[EV_SHAPE, EV_TAG], ports=["INSTRUMENT_PORT"]),
    _c("CLS.INSTRUMENT.PANEL", "INSTRUMENT", "Panel / control-room instrument", r1="INSTRUMENT", phase=1,
       dexpi="ProcessInstrumentationFunction", lookalikes=["CLS.INSTRUMENT.FIELD"], evidence=[EV_SHAPE, EV_TAG], ports=["INSTRUMENT_PORT"]),
    _c("CLS.INSTRUMENT.SHARED_DISPLAY", "INSTRUMENT", "Shared display / DCS function", r1="INSTRUMENT", phase=1,
       dexpi="ProcessInstrumentationFunction", evidence=[EV_SHAPE, EV_TAG], ports=["INSTRUMENT_PORT"]),
    _c("CLS.INSTRUMENT.PLC", "INSTRUMENT", "PLC / logic function (diamond in square)", r1="INSTRUMENT", phase=2,
       dexpi="ProcessInstrumentationFunction", lookalikes=["CLS.INSTRUMENT.INTERLOCK"], evidence=[EV_SHAPE, EV_TAG], ports=["INSTRUMENT_PORT"]),
    _c("CLS.INSTRUMENT.INTERLOCK", "INSTRUMENT", "Interlock / logic (diamond)", r1="INSTRUMENT", phase=2,
       dexpi="ProcessInstrumentationFunction", lookalikes=["CLS.INSTRUMENT.PLC"], evidence=[EV_SHAPE, EV_TAG], ports=["INSTRUMENT_PORT"],
       note="drawing class only - no SIF/SIL interpretation"),
    _c("CLS.INSTRUMENT.COMPUTER", "INSTRUMENT", "Computer function (hexagon)", r1="INSTRUMENT", phase=2,
       dexpi="ProcessInstrumentationFunction", evidence=[EV_SHAPE, EV_TAG], ports=["INSTRUMENT_PORT"]),
    _c("CLS.INSTRUMENT.STACKED_BUBBLE", "INSTRUMENT", "Stacked instrument bubble text (letters over number)", r1="INSTRUMENT", phase=3,
       evidence=[EV_SHAPE, "OCR text within outline"], note="text reading is OCR's job; recognition only locates the outline"),
    # ---- equipment (phase 1)
    _c("CLS.EQUIPMENT.UNKNOWN", "EQUIPMENT", "Equipment, type unknown", r1="OTHER", phase=1),
    _c("CLS.EQUIPMENT.VESSEL", "EQUIPMENT", "Pressure vessel / drum", r1="VESSEL", phase=1, aliases=["V-", "drum", "separator"],
       dexpi="PressureVessel", lookalikes=["CLS.EQUIPMENT.COLUMN", "CLS.EQUIPMENT.TANK"], evidence=[EV_SHAPE, EV_TAG], ports=["NOZZLE"]),
    _c("CLS.EQUIPMENT.TANK", "EQUIPMENT", "Atmospheric tank", r1="TANK", phase=1, aliases=["T-", "TK-"], dexpi="Tank",
       lookalikes=["CLS.EQUIPMENT.VESSEL"], evidence=[EV_SHAPE, EV_TAG], ports=["NOZZLE"]),
    _c("CLS.EQUIPMENT.COLUMN", "EQUIPMENT", "Column / tower", r1="COLUMN", phase=1, aliases=["C-", "tower"], dexpi="ProcessColumn",
       lookalikes=["CLS.EQUIPMENT.VESSEL"], evidence=[EV_SHAPE, EV_TAG], ports=["NOZZLE"]),
    _c("CLS.EQUIPMENT.PUMP_CENTRIFUGAL", "EQUIPMENT", "Centrifugal pump", r1="PUMP", phase=1, aliases=["P-", "pump"], dexpi="CentrifugalPump",
       lookalikes=["CLS.INSTRUMENT.FIELD", "CLS.EQUIPMENT.COMPRESSOR"], evidence=[EV_SHAPE, EV_TAG], ports=["NOZZLE"]),
    _c("CLS.EQUIPMENT.PUMP_POSITIVE_DISPLACEMENT", "EQUIPMENT", "Positive displacement pump", r1="PUMP", phase=2, dexpi="ReciprocatingPump",
       evidence=[EV_SHAPE, EV_TAG], ports=["NOZZLE"]),
    _c("CLS.EQUIPMENT.COMPRESSOR", "EQUIPMENT", "Compressor", r1="COMPRESSOR", phase=1, aliases=["K-", "C-"], dexpi="Compressor",
       lookalikes=["CLS.EQUIPMENT.PUMP_CENTRIFUGAL", "CLS.EQUIPMENT.FAN_BLOWER"], evidence=[EV_SHAPE, EV_TAG], ports=["NOZZLE"]),
    _c("CLS.EQUIPMENT.FAN_BLOWER", "EQUIPMENT", "Fan / blower", r1="OTHER", phase=2, aliases=["fan", "blower"], dexpi="Fan",
       lookalikes=["CLS.EQUIPMENT.COMPRESSOR"], evidence=[EV_SHAPE, EV_TAG], ports=["NOZZLE"]),
    _c("CLS.EQUIPMENT.HEAT_EXCHANGER", "EQUIPMENT", "Heat exchanger (generic)", r1="HEAT_EXCHANGER", phase=1, aliases=["E-", "HX"],
       dexpi="HeatExchanger", lookalikes=["CLS.INSTRUMENT.FIELD"], evidence=[EV_SHAPE, EV_TAG], ports=["NOZZLE"]),
    _c("CLS.EQUIPMENT.HEAT_EXCHANGER_SHELL_TUBE", "EQUIPMENT", "Shell-and-tube exchanger", r1="HEAT_EXCHANGER", phase=2,
       dexpi="TubularHeatExchanger", lookalikes=["CLS.EQUIPMENT.VESSEL"], evidence=[EV_SHAPE, EV_TAG], ports=["NOZZLE"]),
    _c("CLS.EQUIPMENT.FILTER_STRAINER", "EQUIPMENT", "Filter / strainer", r1="FILTER", phase=1, aliases=["F-", "strainer"], dexpi="Filter",
       evidence=[EV_SHAPE, EV_TAG], ports=["NOZZLE"]),
    _c("CLS.EQUIPMENT.AGITATOR", "EQUIPMENT", "Agitator / mixer", r1="OTHER", phase=2, dexpi="Agitator", evidence=[EV_SHAPE, EV_TAG]),
    # ---- fittings / connectors / negatives (lookalikes that must NOT become equipment)
    _c("CLS.FITTING.REDUCER", "FITTING", "Reducer", r1="OTHER", phase=2, dexpi="PipeReducer", lookalikes=["CLS.VALVE.CHECK"],
       evidence=[EV_SHAPE], ports=["PROCESS_UNKNOWN"]),
    _c("CLS.FITTING.FLANGE_PAIR", "FITTING", "Flange pair", r1="OTHER", phase=2, dexpi="Flange", lookalikes=["CLS.VALVE.BUTTERFLY"],
       evidence=[EV_SHAPE], ports=["PROCESS_UNKNOWN"]),
    _c("CLS.FITTING.LINE_BLIND", "FITTING", "Spectacle / line blind", r1="OTHER", phase=2, dexpi="LineBlind", evidence=[EV_SHAPE],
       ports=["PROCESS_UNKNOWN"]),
    _c("CLS.CONNECTOR.OFF_PAGE", "CONNECTOR", "Off-page connector", r1="OTHER", phase=2, dexpi="PipeOffPageConnector",
       evidence=[EV_SHAPE, "sheet reference text"], ports=["OFF_PAGE"]),
    _c("CLS.ANNOTATION.DIMENSION_ARROWS", "ANNOTATION", "Dimension arrows (NOT a valve)", r1="OTHER", phase=2,
       lookalikes=["CLS.VALVE.GATE"], note="negative class: confusable with bow-tie valves"),
    _c("CLS.ANNOTATION.FLOW_ARROW", "ANNOTATION", "Flow arrow (NOT a check valve)", r1="OTHER", phase=2, lookalikes=["CLS.VALVE.CHECK"]),
    _c("CLS.ANNOTATION.NOTE_CIRCLE", "ANNOTATION", "Note / revision circle (NOT an instrument)", r1="OTHER", phase=2,
       lookalikes=["CLS.INSTRUMENT.FIELD"]),
    _c("CLS.ANNOTATION.REVISION_TRIANGLE", "ANNOTATION", "Revision triangle (NOT a check valve)", r1="OTHER", phase=2,
       lookalikes=["CLS.VALVE.CHECK"]),
    # ---- ports and lines (phase 3/4: recognised by separate components)
    *[_c(f"CLS.PORT.{k}", "PORT", f"Port: {k}", r1="OTHER", phase=3) for k in PORT_KINDS],
    *[_c(f"CLS.LINE.{t}", "LINE", f"Line type: {t}", r1="OTHER", phase=4, note="typed line recognition is separate; proximity is not connectivity")
      for t in LINE_TYPES],
]

O, N = "ORIGINAL_APP_LIBRARY", "ORIGINAL_TR1_AUTHORED"
VARIANTS = [
    _v("VAR.VALVE.GATE.BOWTIE_HOLLOW", "CLS.VALVE.GATE", template="VALVE_BOWTIE_HOLLOW", provenance=O, lookalike_risk=["CLS.ANNOTATION.DIMENSION_ARROWS"]),
    _v("VAR.VALVE.ISO.BOWTIE_FILLED", "CLS.VALVE.ISOLATION_UNSPECIFIED", template="VALVE_BOWTIE_FILLED", provenance=O,
       alternatives=["CLS.VALVE.GATE", "CLS.VALVE.BALL", "CLS.VALVE.UNKNOWN"]),
    _v("VAR.VALVE.GLOBE.CENTRE_DOT", "CLS.VALVE.GLOBE", template="VALVE_GLOBE", provenance=O),
    _v("VAR.VALVE.BALL.CENTRE_RING", "CLS.VALVE.BALL", template="VALVE_BALL", provenance=O),
    _v("VAR.VALVE.BUTTERFLY.CENTRE_BAR", "CLS.VALVE.BUTTERFLY", template="VALVE_BUTTERFLY", provenance=O),
    _v("VAR.VALVE.CHECK.TRIANGLE_BAR", "CLS.VALVE.CHECK", template="VALVE_CHECK", provenance=O, directional=True,
       lookalike_risk=["CLS.ANNOTATION.FLOW_ARROW", "CLS.ANNOTATION.REVISION_TRIANGLE"]),
    _v("VAR.VALVE.NEEDLE.BOWTIE_STEM_TRIANGLE", "CLS.VALVE.NEEDLE", template="TR1_VALVE_NEEDLE", provenance=N),
    _v("VAR.VALVE.PLUG.BOWTIE_CENTRE_SQUARE", "CLS.VALVE.PLUG", template="TR1_VALVE_PLUG", provenance=N),
    _v("VAR.VALVE.ANGLE.TRIANGLE_PAIR_RIGHT", "CLS.VALVE.ANGLE", template="TR1_VALVE_ANGLE", provenance=N),
    _v("VAR.VALVE.THREE_WAY.TRIPLE_TRIANGLE", "CLS.VALVE.THREE_WAY", template="TR1_VALVE_3WAY", provenance=N),
    _v("VAR.VALVE.SAFETY.ANGLE_SPRING", "CLS.VALVE.SAFETY_RELIEF", template="TR1_VALVE_PSV", provenance=N, alternatives=["CLS.VALVE.ANGLE"]),
    _v("VAR.ACTUATOR.MANUAL.STEM_TBAR", "CLS.ACTUATOR.MANUAL", template="ACT_MANUAL", provenance=O),
    _v("VAR.ACTUATOR.DIAPHRAGM.STEM_DOME", "CLS.ACTUATOR.DIAPHRAGM", template="ACT_DIAPHRAGM", provenance=O),
    _v("VAR.ACTUATOR.SOLENOID.STEM_BOX", "CLS.ACTUATOR.SOLENOID", template="ACT_SOLENOID", provenance=O),
    _v("VAR.ACTUATOR.MOTOR.STEM_RING", "CLS.ACTUATOR.MOTOR", template="ACT_MOTOR", provenance=O),
    _v("VAR.INSTRUMENT.FIELD.BUBBLE_PLAIN", "CLS.INSTRUMENT.FIELD", template="INST_FIELD", provenance=O, lookalike_risk=["CLS.ANNOTATION.NOTE_CIRCLE"]),
    _v("VAR.INSTRUMENT.PANEL.BUBBLE_BAR", "CLS.INSTRUMENT.PANEL", template="INST_PANEL", provenance=O),
    _v("VAR.INSTRUMENT.SHARED.BUBBLE_IN_SQUARE", "CLS.INSTRUMENT.SHARED_DISPLAY", template="INST_SHARED", provenance=O),
    _v("VAR.INSTRUMENT.PLC.DIAMOND_IN_SQUARE", "CLS.INSTRUMENT.PLC", template="TR1_INST_PLC", provenance=N),
    _v("VAR.INSTRUMENT.INTERLOCK.DIAMOND", "CLS.INSTRUMENT.INTERLOCK", template="TR1_INST_INTERLOCK", provenance=N),
    _v("VAR.INSTRUMENT.COMPUTER.HEXAGON", "CLS.INSTRUMENT.COMPUTER", template="TR1_INST_COMPUTER", provenance=N),
    _v("VAR.EQUIPMENT.VESSEL.CAPSULE_VERTICAL", "CLS.EQUIPMENT.VESSEL", template="EQ_VESSEL_V", provenance=O,
       alternatives=["CLS.EQUIPMENT.COLUMN", "CLS.EQUIPMENT.UNKNOWN"]),
    _v("VAR.EQUIPMENT.VESSEL.CAPSULE_HORIZONTAL", "CLS.EQUIPMENT.VESSEL", template="EQ_VESSEL_H", provenance=O),
    _v("VAR.EQUIPMENT.TANK.OPEN_TOP_BOX", "CLS.EQUIPMENT.TANK", template="TR1_EQ_TANK", provenance=N),
    _v("VAR.EQUIPMENT.COLUMN.TALL_CAPSULE_TRAYS", "CLS.EQUIPMENT.COLUMN", template="TR1_EQ_COLUMN", provenance=N),
    _v("VAR.EQUIPMENT.PUMP.CIRCLE_TANGENT", "CLS.EQUIPMENT.PUMP_CENTRIFUGAL", template="EQ_PUMP", provenance=O),
    _v("VAR.EQUIPMENT.COMPRESSOR.CIRCLE_TRAPEZOID", "CLS.EQUIPMENT.COMPRESSOR", template="TR1_EQ_COMPRESSOR", provenance=N),
    _v("VAR.EQUIPMENT.FAN.CIRCLE_BLADES", "CLS.EQUIPMENT.FAN_BLOWER", template="TR1_EQ_FAN", provenance=N),
    _v("VAR.EQUIPMENT.HX.CIRCLE_ZIGZAG", "CLS.EQUIPMENT.HEAT_EXCHANGER", template="EQ_EXCHANGER", provenance=O),
    _v("VAR.EQUIPMENT.HX_ST.SHELL_TUBES", "CLS.EQUIPMENT.HEAT_EXCHANGER_SHELL_TUBE", template="TR1_EQ_SHELL_TUBE", provenance=N),
    _v("VAR.EQUIPMENT.FILTER.BOX_DIAGONAL", "CLS.EQUIPMENT.FILTER_STRAINER", template="EQ_FILTER", provenance=O),
    _v("VAR.FITTING.REDUCER.TRAPEZOID", "CLS.FITTING.REDUCER", template="TR1_FIT_REDUCER", provenance=N),
    _v("VAR.FITTING.FLANGE.DOUBLE_BAR", "CLS.FITTING.FLANGE_PAIR", template="TR1_FIT_FLANGE", provenance=N),
    _v("VAR.CONNECTOR.OFF_PAGE.PENTAGON", "CLS.CONNECTOR.OFF_PAGE", template="TR1_CONN_OFFPAGE", provenance=N),
    _v("VAR.ANNOTATION.DIMENSION.ARROW_PAIR", "CLS.ANNOTATION.DIMENSION_ARROWS", template="TR1_NEG_DIMENSION", provenance=N),
    _v("VAR.ANNOTATION.REVISION.TRIANGLE", "CLS.ANNOTATION.REVISION_TRIANGLE", template="TR1_NEG_REV_TRIANGLE", provenance=N),
    _v("VAR.ANNOTATION.NOTE.CIRCLE_NUMBER", "CLS.ANNOTATION.NOTE_CIRCLE", template="TR1_NEG_NOTE_CIRCLE", provenance=N),
]


def catalogue(version="1.0.0") -> dict:
    return {"schema": SCHEMA, "catalogue_version": version, "licence": "Original authored metadata; names of standard classes only",
            "not_exhaustive": True, "classes": CLASSES, "variants": VARIANTS, "line_types": list(LINE_TYPES), "port_kinds": list(PORT_KINDS)}


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def catalogue_sha256(cat: dict) -> str:
    return hashlib.sha256(canonical(cat)).hexdigest()


def validate(cat: dict, *, template_ids=None, dexpi_names=None, eligible_source_ids=()) -> list[str]:
    errs = []
    if cat.get("schema") != SCHEMA:
        errs.append("SCHEMA")
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(cat.get("catalogue_version", ""))):
        errs.append("VERSION_FORMAT")
    cls = {}
    for c in cat.get("classes", []):
        cid = c.get("class_id")
        if not isinstance(cid, str) or not CLASS_ID.fullmatch(cid):
            errs.append(f"CLASS_ID_FORMAT:{cid}"); continue
        if cid in cls:
            errs.append(f"DUPLICATE_CLASS:{cid}")
        cls[cid] = c
        if c.get("domain") not in DOMAINS or cid.split(".")[1] != c.get("domain"):
            errs.append(f"DOMAIN:{cid}")
        if c.get("r1_class") not in R1_CLASSES:
            errs.append(f"R1_MAPPING:{cid}")
        if c.get("status") not in STATUSES:
            errs.append(f"STATUS:{cid}")
        if c.get("status") == "DEPRECATED" and not c.get("replaced_by"):
            errs.append(f"DEPRECATED_WITHOUT_REPLACEMENT:{cid}")
        if c.get("training_phase") not in (1, 2, 3, 4):
            errs.append(f"PHASE:{cid}")
        for p in c.get("port_kinds", []):
            if p not in PORT_KINDS:
                errs.append(f"PORT_KIND:{cid}:{p}")
        if dexpi_names is not None and c.get("dexpi_class") and c["dexpi_class"] not in dexpi_names:
            errs.append(f"DEXPI_NAME_NOT_IN_OFFICIAL_PLANT_XML:{cid}:{c['dexpi_class']}")
    for cid, c in cls.items():
        for l in c.get("lookalike_class_ids", []):
            if l not in cls:
                errs.append(f"LOOKALIKE_DANGLING:{cid}:{l}")
            if l == cid:
                errs.append(f"LOOKALIKE_SELF:{cid}")
        if c.get("replaced_by") and c["replaced_by"] not in cls:
            errs.append(f"REPLACED_BY_DANGLING:{cid}")
    for d in [x for x in DOMAINS if x in ("EQUIPMENT", "VALVE", "ACTUATOR", "INSTRUMENT")]:
        if f"CLS.{d}.UNKNOWN" not in cls:
            errs.append(f"MISSING_UNKNOWN:{d}")
    for s in ("CLS.STATE.UNKNOWN", "CLS.STATE.UNRESOLVED"):
        if s not in cls:
            errs.append(f"MISSING_STATE:{s}")
    vids, tids = set(), {}
    for v in cat.get("variants", []):
        vid = v.get("variant_id")
        if not isinstance(vid, str) or not VAR_ID.fullmatch(vid) or vid in vids:
            errs.append(f"VARIANT_ID:{vid}"); continue
        vids.add(vid)
        if v.get("class_id") not in cls:
            errs.append(f"VARIANT_CLASS_DANGLING:{vid}")
        elif cls[v["class_id"]]["domain"] != vid.split(".")[1]:
            errs.append(f"VARIANT_DOMAIN:{vid}")
        for a in v.get("class_alternatives", []) + v.get("lookalike_risk", []):
            if a not in cls:
                errs.append(f"VARIANT_ALT_DANGLING:{vid}:{a}")
        prov = v.get("artwork_provenance")
        if prov not in PROVENANCE_OK and prov not in set(eligible_source_ids):
            errs.append(f"ARTWORK_PROVENANCE_NOT_ELIGIBLE:{vid}:{prov}")
        t = v.get("template_id")
        if t in tids:
            errs.append(f"TEMPLATE_REUSED:{t}")
        tids[t] = vid
        if template_ids is not None and t not in template_ids:
            errs.append(f"TEMPLATE_MISSING:{vid}:{t}")
    return errs


def diff(old: dict, new: dict) -> dict:
    """Version diff with the immutability rule: removed IDs or changed meaning (domain/name/r1) are violations."""
    o = {c["class_id"]: c for c in old["classes"]}; n = {c["class_id"]: c for c in new["classes"]}
    ov = {v["variant_id"]: v for v in old["variants"]}; nv = {v["variant_id"]: v for v in new["variants"]}
    viol = [f"CLASS_REMOVED:{k}" for k in o if k not in n] + [f"VARIANT_REMOVED:{k}" for k in ov if k not in nv]
    viol += [f"CLASS_MEANING_CHANGED:{k}" for k in o if k in n and any(o[k][f] != n[k][f] for f in ("domain", "name", "r1_class"))]
    viol += [f"VARIANT_RETARGETED:{k}" for k in ov if k in nv and ov[k]["class_id"] != nv[k]["class_id"]]
    return {"added_classes": sorted(set(n) - set(o)), "added_variants": sorted(set(nv) - set(ov)),
            "deprecated": sorted(k for k in n if n[k]["status"] == "DEPRECATED" and o.get(k, {}).get("status") != "DEPRECATED"),
            "violations": viol}


def legend_proposals(cat: dict, legend_rows: list[dict]) -> list[dict]:
    """Drawing-legend workflow: map each legend row's label text to catalogue class candidates by alias/name tokens.
    Output is a LOCAL, per-document PROPOSED mapping needing human review; it never changes the global catalogue."""
    out = []
    for row in legend_rows:
        text = str(row.get("label", "")).lower()
        toks = set(re.findall(r"[a-z0-9\-]+", text))
        cands = []
        for c in cat["classes"]:
            if c["domain"] in ("STATE", "PORT", "LINE"):
                continue
            keys = {a.lower() for a in c["aliases"]} | {c["name"].lower().split(" (")[0]}
            hit = [k for k in keys if (k in text if " " in k or len(k) > 3 else k in toks)]
            if hit:
                cands.append({"class_id": c["class_id"], "matched": sorted(hit)})
        out.append({"document_sha256": row.get("document_sha256"), "page": row.get("page"), "legend_row_id": row.get("row_id"),
                    "label": row.get("label"), "evidence_bbox": row.get("bbox"), "candidates": cands,
                    "state": "PROPOSED_LOCAL_MAPPING" if len(cands) == 1 else ("UNRESOLVED" if cands else "UNKNOWN"),
                    "scope": "THIS_DOCUMENT_ONLY", "requires_review": True})
    return out
