"""Proposed DEXPI 2.0.1 export of an ``engineering-intelligence-v1`` snapshot (R5 update, changes 1 and 2).

Status: OFF by default (``PID_R5_DEXPI``). This is NOT a DEXPI-conformance claim, NOT an interoperability certification and NOT an
engineering verification. What it is: a narrow, explicit mapping of reviewed source classes to DEXPI 2.0.1 class names, a complete
accounting of what happened to every source object, and three *separate* checks that must not be mixed up:

1. **XSD validation** (``validate_xsd``) against the official, hash-checked schema. Needs an XML-schema validator (lxml) that is not part of
   the locked environment, so it reports ``BLOCKED_NO_XML_SCHEMA_VALIDATOR`` instead of passing.
2. **Registry / structural check** (``registry_check``): every exported class exists and is concrete in the official Plant/Core model files and
   every property used is declared on the class or an ancestor. Needs the official ``Plant.xml`` and ``Core.xml`` (supplied, never downloaded).
3. **Source read-back** (``readback``): a separately written Expat reader (DTD/entities refused) that re-reads the produced XML and compares it
   with the source snapshot and the fate table: duplicate or dangling IDs, a source object that is claimed written but is not in the XML, an
   object in the XML with no source, class or tag differences.

Mapping (explicit classes only; nothing is inferred from drawing appearance):

====================== ================================================
source class           DEXPI 2.0.1 class
====================== ================================================
BALL_VALVE             Plant/Piping.BallValve
GLOBE_VALVE            Plant/Piping.GlobeValve
CENTRIFUGAL_PUMP       Plant/ProcessEquipment.CentrifugalPump
PLATE_HEAT_EXCHANGER   Plant/ProcessEquipment.PlateHeatExchanger
TUBULAR_HEAT_EXCHANGER Plant/ProcessEquipment.TubularHeatExchanger
====================== ================================================

plus the classes the research writer already carried (VESSEL, TANK, FILTER and the generic VALVE/CONTROL_VALVE -> OperatedValve with a
"sub-type unresolved" note that is never removed) and PRESSURE_VESSEL -> Vessel (the parent class, not a subtype). Every other class
(gate valve, check valve, generic HEAT_EXCHANGER, ...) is kept in the sidecar with a reason. A class is exported only from a human-reviewed
reading (``ACCEPTED_AS_READING``) unless the caller explicitly passes ``include_unreviewed=True``; the export is then still marked proposed.

Never done here: no flow direction (Source/Target order is arbitrary and noted as such), no fittings, no nozzle verification, no graphics, no
safety conclusion, no automatic acceptance. Source/Target of a drawn connection never means flow.
"""
from __future__ import annotations

import copy
import hashlib
import json
import xml.etree.ElementTree as ET
import xml.parsers.expat as expat
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import r5_features

VERSION = "dexpi-proposed-v1"
TARGET_VERSION = "2.0.1"
MAX_XML_BYTES = 64 * 1024 * 1024
MAX_SOURCE_OBJECTS = 400_000

EQUIP = {"VESSEL": "Plant/ProcessEquipment.Vessel", "PRESSURE_VESSEL": "Plant/ProcessEquipment.Vessel", "TANK": "Plant/ProcessEquipment.Tank",
         "FILTER": "Plant/ProcessEquipment.Filter", "CENTRIFUGAL_PUMP": "Plant/ProcessEquipment.CentrifugalPump",
         "PLATE_HEAT_EXCHANGER": "Plant/ProcessEquipment.PlateHeatExchanger", "TUBULAR_HEAT_EXCHANGER": "Plant/ProcessEquipment.TubularHeatExchanger"}
VALVES = {"VALVE": "Plant/Piping.OperatedValve", "CONTROL_VALVE": "Plant/Piping.OperatedValve", "BALL_VALVE": "Plant/Piping.BallValve",
          "GLOBE_VALVE": "Plant/Piping.GlobeValve"}
SUBTYPE_UNRESOLVED = ("VALVE", "CONTROL_VALVE")
NEW_IN_R5 = ("BALL_VALVE", "GLOBE_VALVE", "CENTRIFUGAL_PUMP", "PLATE_HEAT_EXCHANGER", "TUBULAR_HEAT_EXCHANGER")
INSTRUMENT_CLASS = "Plant/Instrumentation.ProcessInstrumentationFunction"
SIGNAL_CLASS = "Plant/Instrumentation.SignalConveyingFunction"
# fates
REPRESENTED, REPRESENTED_UNSUPPORTED, SIDECAR_ONLY, REJECTED = "REPRESENTED", "REPRESENTED_WITH_UNSUPPORTED_FIELDS", "SIDECAR_ONLY", "REJECTED_WITH_REASON"
FATES = (REPRESENTED, REPRESENTED_UNSUPPORTED, SIDECAR_ONLY, REJECTED)
_NOT_EXPORTABLE_STATES = {"REJECTED": "HUMAN_REJECTED", "IGNORED": "HUMAN_IGNORED", "STALE": "REVIEW_STALE_REAFFIRMATION_NEEDED", "NEEDS_REVIEW": "HUMAN_NEEDS_REVIEW"}


class DexpiExportError(ValueError):
    """Refused: the message starts with a stable machine code."""


# --------------------------------------------------------------------------------------------- identifiers
def encode_id(namespace: str, source_id: str) -> str:
    """Injective, reversible XML id: ``D<namespace>_<source id with every non [A-Za-z0-9] byte written as _XX>``. Two different
    (namespace, source id) pairs can never collide, whatever commas, spaces, dots or unicode the source id contains."""
    if not isinstance(source_id, str) or source_id == "":
        raise DexpiExportError("EMPTY_SOURCE_ID")
    out = []
    for b in source_id.encode("utf-8"):
        c = chr(b)
        out.append(c if c.isascii() and c.isalnum() else "_%02X" % b)
    return f"D{namespace}_" + "".join(out)


def decode_id(xml_id: str) -> tuple[str, str]:
    head, _, rest = xml_id.partition("_")
    if not head.startswith("D") or not _:
        raise DexpiExportError("NOT_AN_ENCODED_ID")
    raw = bytearray()
    i = 0
    while i < len(rest):
        if rest[i] == "_":
            raw.append(int(rest[i + 1:i + 3], 16))
            i += 3
        else:
            raw.append(ord(rest[i]))
            i += 1
    return head[1:], raw.decode("utf-8")


def _namespace(snapshot: dict) -> str:
    d = snapshot["drawings"][0]
    basis = json.dumps([d["sha256"], d.get("drawing_no"), d.get("revision")], sort_keys=True)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]


# --------------------------------------------------------------------------------------------- writer
class _W:
    def __init__(self, ns: str):
        self.ns, self.ids = ns, set()

    def obj(self, parent, prop, type_, source_id=None, suffix=""):
        c = parent.find(f"Components[@property='{prop}']")
        if c is None:
            c = ET.SubElement(parent, "Components", property=prop)
        e = ET.SubElement(c, "Object", type=type_)
        if source_id is not None:
            i = encode_id(self.ns, source_id + suffix)
            if i in self.ids:
                raise DexpiExportError("XML_ID_COLLISION")        # cannot happen for distinct inputs; fail closed if it ever does
            e.set("id", i)
            self.ids.add(i)
        return e

    @staticmethod
    def data(e, prop, value, kind="String"):
        d = ET.SubElement(e, "Data", property=prop)
        ET.SubElement(d, kind).text = str(value)

    @staticmethod
    def ref(e, prop, *ids):
        ET.SubElement(e, "References", property=prop, objects=" ".join("#" + i for i in ids))


def _exportable(entity: dict, include_unreviewed: bool) -> tuple[bool, str]:
    state = entity.get("review_state") or "PROPOSED_UNVERIFIED"
    if state in _NOT_EXPORTABLE_STATES:
        return False, _NOT_EXPORTABLE_STATES[state]
    if state != "ACCEPTED_AS_READING" and not include_unreviewed:
        return False, "CLASS_NOT_HUMAN_REVIEWED"
    if entity.get("semantic_level") in ("UNKNOWN", "CONFLICTING"):
        return False, "SEMANTIC_LEVEL_" + str(entity.get("semantic_level"))
    return True, ""


def _check_unique(snapshot: dict) -> None:
    seen: dict[str, str] = {}
    n = 0
    for e in snapshot["entities"]:
        n += 1
        for key, label in ((e["id"], "entity"),):
            if key in seen:
                raise DexpiExportError(f"DUPLICATE_SOURCE_ID: {label} id {key!r} appears more than once; the export is refused rather than merging observations")
            seen[key] = label
        for p in e.get("ports", []):
            n += 1
            if p["id"] in seen:
                raise DexpiExportError(f"DUPLICATE_SOURCE_ID: port id {p['id']!r} appears more than once")
            seen[p["id"]] = "port"
    for r in snapshot["relationships"]:
        n += 1
        if r["id"] in seen:
            raise DexpiExportError(f"DUPLICATE_SOURCE_ID: relationship id {r['id']!r} appears more than once")
        seen[r["id"]] = "relationship"
    if n > MAX_SOURCE_OBJECTS:
        raise DexpiExportError("SOURCE_OVER_LIMIT")


def to_dexpi(snapshot: dict, *, include_unreviewed: bool = False, cancel=None) -> tuple[str, dict]:
    """(xml text, sidecar). Pure: no file is written. ``cancel`` is an optional callable returning True to stop (raises ``InterruptedError``)."""
    _check_unique(snapshot)
    ns = _namespace(snapshot)
    w = _W(ns)
    fates: list[dict] = []
    objects: dict[str, dict] = {}
    unresolved_rel = {u["id"][4:] for u in snapshot.get("unresolved", []) if u["id"].startswith("unr-")}

    def tick(i):
        if cancel is not None and i % 256 == 0 and cancel():
            raise InterruptedError("DEXPI export cancelled")

    entities = {e["id"]: e for e in snapshot["entities"]}
    stamp = snapshot["package"].get("created_utc") or datetime.now(timezone.utc).isoformat(timespec="seconds")
    root = ET.Element("Model", name="pid_reader_proposed_export", uri="urn:pidreader:proposed-unverified:" + ns)
    ET.SubElement(root, "Import", prefix="Core", source="https://data.dexpi.org/models/2.0.1/Core.xml")
    ET.SubElement(root, "Import", prefix="Plant", source="https://data.dexpi.org/models/2.0.1/Plant.xml")
    eng = ET.SubElement(root, "Object", type="Core/EngineeringModel")
    pm = w.obj(eng, "ConceptualModel", "Plant/PlantModel", "PlantModel1")
    w.data(eng, "ExportDateTime", stamp[:19], "DateTime")
    w.data(eng, "OriginatingSystemName", "Advanced P&ID Reader (proposed export)")
    w.data(eng, "OriginatingSystemVendorName", "owner build - unvalidated")
    w.data(eng, "OriginatingSystemVersion", snapshot["package"].get("engine_version") or VERSION)
    notes: dict[str, str] = {}

    def note(code):
        if code not in notes:
            n = w.obj(pm, "Notes", "Core/Note", "Note_" + code)
            w.data(n, "NoteClassification", code)
            notes[code] = n.get("id")
        return notes[code]

    def prov(e, src, codes=("PROPOSED_UNVERIFIED",), **extra):
        p = w.obj(e, "PersistentIdentifiers", "Core/PersistentIdentifier")
        w.data(p, "Context", "pidreader:source_id")
        w.data(p, "Value", src)
        w.ref(e, "ReferencedNotes", *[note(c) for c in codes])
        objects[e.get("id")] = {"source_id": src, "namespace": ns, "notes": list(codes), **extra}

    def fate(kind, sid, value, reason, state, unsupported=None, xml_ids=None):
        fates.append({"kind": kind, "id": sid, "fate": value, "reason": reason, "source_review_state": state or "PROPOSED_UNVERIFIED",
                      "export_state": "PROPOSED_UNVERIFIED", "unsupported_fields": sorted(unsupported or []), "xml_ids": sorted(xml_ids or [])})

    # ---- decide which entities can be exported at all
    eligible_equipment, eligible_valves, eligible_instruments = {}, {}, {}
    for i, e in enumerate(snapshot["entities"]):
        tick(i)
        cls = e.get("classification")
        if e["kind"] == "EQUIPMENT" and cls in EQUIP:
            ok, why = _exportable(e, include_unreviewed)
            (eligible_equipment.__setitem__(e["id"], e) if ok else fate("entity", e["id"], SIDECAR_ONLY, why, e.get("review_state")))
        elif e["kind"] == "VALVE" and cls in VALVES:
            ok, why = _exportable(e, include_unreviewed)
            (eligible_valves.__setitem__(e["id"], e) if ok else fate("entity", e["id"], SIDECAR_ONLY, why, e.get("review_state")))
        elif e["kind"] == "INSTRUMENT":
            ok, why = _exportable(e, include_unreviewed)
            (eligible_instruments.__setitem__(e["id"], e) if ok else fate("entity", e["id"], SIDECAR_ONLY, why, e.get("review_state")))
        elif e["kind"] in ("EQUIPMENT", "VALVE"):
            fate("entity", e["id"], SIDECAR_ONLY, "NO_VALIDATED_MAPPING_FOR_CLASS:" + str(cls), e.get("review_state"))
        else:
            fate("entity", e["id"], SIDECAR_ONLY, "UNMAPPED_KIND:" + e["kind"], e.get("review_state"))

    # ---- classify relationships
    process_edges, signal_edges = [], []
    port_owner = {p["id"]: e["id"] for e in snapshot["entities"] for p in e.get("ports", [])}
    for i, r in enumerate(snapshot["relationships"]):
        tick(i)
        st = r.get("review_state") or "PROPOSED_UNVERIFIED"
        a, b = r["from_entity_id"], r["to_entity_id"]
        if st in _NOT_EXPORTABLE_STATES:
            fate("relationship", r["id"], SIDECAR_ONLY, _NOT_EXPORTABLE_STATES[st], st)
        elif r["id"] in unresolved_rel:
            fate("relationship", r["id"], SIDECAR_ONLY, "UNRESOLVED_ALTERNATIVE_READING_SEE_REVIEW_LEDGER", st)
        elif st != "ACCEPTED_AS_READING" and not include_unreviewed:
            fate("relationship", r["id"], SIDECAR_ONLY, "CONNECTION_NOT_HUMAN_REVIEWED", st)
        elif r.get("from_port_id") and port_owner.get(r["from_port_id"]) != a or r.get("to_port_id") and port_owner.get(r["to_port_id"]) != b:
            fate("relationship", r["id"], REJECTED, "PORT_NOT_OWNED_BY_ENDPOINT_ENTITY", st)
        elif r["type"] == "DRAWN_CONNECTS" and a in {**eligible_equipment, **eligible_valves} and b in {**eligible_equipment, **eligible_valves} and a != b:
            process_edges.append(r)
        elif r["type"] == "SIGNAL_CONNECTS" and a in eligible_instruments and b in eligible_instruments and a != b:
            signal_edges.append(r)
        else:
            fate("relationship", r["id"], SIDECAR_ONLY, f"NO_FAITHFUL_MAPPING_FOR:{r['type']}:{entities.get(a, {}).get('kind')}->{entities.get(b, {}).get('kind')}", st)

    used_valves = {x for r in process_edges for x in (r["from_entity_id"], r["to_entity_id"]) if x in eligible_valves}
    for vid, v in eligible_valves.items():
        if vid not in used_valves:
            fate("entity", vid, SIDECAR_ONLY, "NOT_ON_ANY_EXPORTED_CONNECTION", v.get("review_state"))

    # ---- equipment + nozzles
    port_obj: dict[str, tuple[str, str]] = {}
    equip_xml: dict[str, str] = {}
    exported_ports: set[str] = set()
    for eid in sorted(eligible_equipment):
        e = eligible_equipment[eid]
        x = w.obj(pm, "TaggedPlantItems", EQUIP[e["classification"]], eid)
        if e.get("tag"):
            w.data(x, "TagName", e["tag"])
        prov(x, eid, source_class=e["classification"])
        xml_ids = [x.get("id")]
        equip_xml[eid] = x.get("id")
        for p in sorted(e.get("ports", []), key=lambda p: p["id"]):
            if p["kind"] != "NOZZLE":
                continue
            nz = w.obj(x, "Nozzles", "Plant/ProcessEquipment.ProcessNozzle", p["id"])
            pn = w.obj(nz, "Nodes", "Plant/Piping.PipingNode", p["id"], "#node")
            prov(nz, p["id"], codes=("PROPOSED_UNVERIFIED", "NOZZLE_NOT_VERIFIED_PORT_FROM_SYMBOL"))
            objects[pn.get("id")] = {"source_endpoint": p["id"], "namespace": ns}
            port_obj[p["id"]] = (nz.get("id"), pn.get("id"))
            exported_ports.add(p["id"])
            xml_ids += [nz.get("id"), pn.get("id")]
            fate("port", p["id"], REPRESENTED_UNSUPPORTED, "NOZZLE_FROM_SYMBOL_PORT", e.get("review_state"), ["angle_degrees", "source_evidence_ids", "label"], [nz.get("id"), pn.get("id")])
        fate("entity", eid, REPRESENTED_UNSUPPORTED, "MAPPED:" + e["classification"] + "->" + EQUIP[e["classification"]], e.get("review_state"),
             ["source_evidence_ids", "score", "attributes", "bbox_in_evidence"], [x.get("id")])
        objects[x.get("id")]["xml_ids"] = xml_ids

    # ---- instruments
    pif: dict[str, ET.Element] = {}
    inst_edge_ids = {x for r in signal_edges for x in (r["from_entity_id"], r["to_entity_id"])}
    for iid in sorted(eligible_instruments):
        e = eligible_instruments[iid]
        x = w.obj(pm, "ProcessInstrumentationFunctions", INSTRUMENT_CLASS, iid)
        p = w.obj(x, "PersistentIdentifiers", "Core/PersistentIdentifier")
        w.data(p, "Context", "pidreader:raw_tag_text")
        w.data(p, "Value", e.get("tag") or "")
        prov(x, iid, codes=("PROPOSED_UNVERIFIED", "INSTRUMENT_TAG_NOT_DECOMPOSED"))
        pif[iid] = x
        fate("entity", iid, REPRESENTED_UNSUPPORTED, "INSTRUMENT_AS_PROCESS_INSTRUMENTATION_FUNCTION", e.get("review_state"),
             ["source_evidence_ids", "score", "attributes", "ports", "bbox_in_evidence"], [x.get("id")])
        for pt in e.get("ports", []):
            fate("port", pt["id"], SIDECAR_ONLY, "INSTRUMENT_PORT_HAS_NO_FAITHFUL_DEXPI_MAPPING", e.get("review_state"))
    for e in list(eligible_equipment.values()):
        for p in e.get("ports", []):
            if p["id"] not in exported_ports:
                fate("port", p["id"], SIDECAR_ONLY, "PORT_KIND_NOT_NOZZLE:" + str(p["kind"]), e.get("review_state"))
    for r in sorted(signal_edges, key=lambda r: r["id"]):
        a, b = r["from_entity_id"], r["to_entity_id"]
        s = w.obj(pif[a], "SignalConveyingFunctions", SIGNAL_CLASS, r["id"])
        w.ref(s, "Source", pif[a].get("id"))
        w.ref(s, "Target", pif[b].get("id"))
        prov(s, r["id"], codes=("PROPOSED_UNVERIFIED", "SIGNAL_DIRECTION_NOT_ESTABLISHED"))
        fate("relationship", r["id"], REPRESENTED_UNSUPPORTED, "SIGNAL_BETWEEN_TWO_INSTRUMENTS", r.get("review_state"), ["source_evidence_ids", "direction", "from_port_id", "to_port_id"], [s.get("id")])

    # ---- piping: components joined through valves (equipment terminates a segment)
    par = {r["id"]: r["id"] for r in process_edges}

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    by_valve: dict[str, list[str]] = defaultdict(list)
    for r in process_edges:
        for x in (r["from_entity_id"], r["to_entity_id"]):
            if x in eligible_valves:
                by_valve[x].append(r["id"])
    for lst in by_valve.values():
        for other in lst[1:]:
            par[find(other)] = find(lst[0])
    comps: dict[str, list[dict]] = defaultdict(list)
    for r in process_edges:
        comps[find(r["id"])].append(r)
    valve_xml: dict[str, tuple[ET.Element, dict]] = {}
    for k, key in enumerate(sorted(comps, key=lambda c: min(r["id"] for r in comps[c])), 1):
        edges = sorted(comps[key], key=lambda r: r["id"])
        sysx = w.obj(pm, "PipingNetworkSystems", "Plant/Piping.PipingNetworkSystem", f"PNS{k}")
        prov(sysx, f"component{k}", codes=("PROPOSED_UNVERIFIED", "COMPONENT_GROUPING_IS_AN_EXPORT_CHOICE"))
        seg = w.obj(sysx, "Segments", "Plant/Piping.PipingNetworkSegment", f"PNSeg{k}")
        prov(seg, f"component{k}", codes=("PROPOSED_UNVERIFIED", "COMPONENT_GROUPING_IS_AN_EXPORT_CHOICE"))

        def resolve(entity_id, port_id):
            if port_id in port_obj:
                return port_obj[port_id]
            if entity_id in eligible_equipment:                       # equipment with no exported nozzle for this port: attach to the item itself
                return equip_xml[entity_id], None
            if entity_id not in valve_xml:
                v = eligible_valves[entity_id]
                cls = v["classification"]
                x = w.obj(seg, "Items", VALVES[cls], entity_id)
                if v.get("tag"):
                    w.data(x, "PipingComponentName", v["tag"])
                codes = ["PROPOSED_UNVERIFIED"] + (["VALVE_SUBTYPE_UNRESOLVED"] if cls in SUBTYPE_UNRESOLVED else []) + (["ACTUATOR_NOT_MODELLED"] if cls == "CONTROL_VALVE" else [])
                prov(x, entity_id, codes=tuple(codes), source_class=cls)
                valve_xml[entity_id] = (x, {})
                fate("entity", entity_id, REPRESENTED_UNSUPPORTED, "MAPPED:" + cls + "->" + VALVES[cls], v.get("review_state"),
                     ["source_evidence_ids", "score", "attributes", "bbox_in_evidence"], [x.get("id")])
            x, nodes = valve_xml[entity_id]
            if port_id not in nodes:
                pn = w.obj(x, "Nodes", "Plant/Piping.PipingNode", port_id or entity_id, "#node")
                nodes[port_id] = pn.get("id")
                objects[pn.get("id")] = {"source_endpoint": port_id, "namespace": ns}
                if port_id:
                    exported_ports.add(port_id)
                    fate("port", port_id, REPRESENTED_UNSUPPORTED, "VALVE_END_AS_PIPING_NODE", eligible_valves[entity_id].get("review_state"), ["angle_degrees", "source_evidence_ids"], [pn.get("id")])
            return x.get("id"), nodes[port_id]
        for r in edges:
            (ia, na), (ib, nb) = resolve(r["from_entity_id"], r.get("from_port_id")), resolve(r["to_entity_id"], r.get("to_port_id"))
            pe = w.obj(seg, "Connections", "Plant/Piping.Pipe", r["id"])
            w.ref(pe, "SourceItem", ia)
            w.ref(pe, "TargetItem", ib)
            if na:
                w.ref(pe, "SourceNode", na)
            if nb:
                w.ref(pe, "TargetNode", nb)
            prov(pe, r["id"], codes=("PROPOSED_UNVERIFIED", "FLOW_DIRECTION_UNKNOWN_SOURCE_TARGET_ARBITRARY"))
            fate("relationship", r["id"], REPRESENTED_UNSUPPORTED, "DRAWN_CONNECTION_AS_PIPE", r.get("review_state"),
                 ["source_evidence_ids", "direction", "path_geometry"], [pe.get("id")])

    # ---- every source port that has no fate yet (ports of entities that did not export)
    have = {(f["kind"], f["id"]) for f in fates}
    for e in snapshot["entities"]:
        if ("entity", e["id"]) not in have:
            fate("entity", e["id"], SIDECAR_ONLY, "NOT_EXPORTED", e.get("review_state"))
            have.add(("entity", e["id"]))
        for p in e.get("ports", []):
            if ("port", p["id"]) not in have:
                fate("port", p["id"], SIDECAR_ONLY, "OWNER_NOT_EXPORTED_OR_PORT_NOT_ON_AN_EXPORTED_CONNECTION", e.get("review_state"))
                have.add(("port", p["id"]))
    for r in snapshot["relationships"]:
        if ("relationship", r["id"]) not in have:
            fate("relationship", r["id"], SIDECAR_ONLY, "NOT_EXPORTED", r.get("review_state"))

    for xid, o in objects.items():
        o["xml_key"] = decode_id(xid)[1]
    xml = ET.tostring(root, encoding="unicode")
    sidecar = {"schema": "pid-reader-dexpi-sidecar-v1", "version": VERSION, "target": "DEXPI " + TARGET_VERSION, "dexpi_conformant": False,
               "engineering_validation": "NOT_PERFORMED", "namespace": ns, "include_unreviewed": bool(include_unreviewed),
               "document": {"sha256": snapshot["drawings"][0]["sha256"], "drawing_no": snapshot["drawings"][0].get("drawing_no"),
                            "revision": snapshot["drawings"][0].get("revision"), "source_name": snapshot["drawings"][0]["source_name"]},
               "id_mapping": {xid: {"source_id": o.get("source_id", o.get("source_endpoint")), "namespace": o["namespace"]} for xid, o in sorted(objects.items())},
               "objects": objects, "notes": notes,
               "fates": sorted(fates, key=lambda f: (f["kind"], f["id"])),
               "unsupported_information": {"geometry_and_units": "native DEXPI graphics are not emitted; boxes, scores and evidence stay in source_snapshot",
                                           "flow_direction": "never asserted; Source/Target order is arbitrary", "fittings": "not detected",
                                           "nozzle_verification": "ports come from symbol templates and are not verified nozzles"},
               "source_snapshot": copy.deepcopy(snapshot)}
    _assert_fates(snapshot, sidecar)
    return xml, sidecar


def _assert_fates(snapshot: dict, sidecar: dict) -> None:
    want = ([("entity", e["id"]) for e in snapshot["entities"]] + [("port", p["id"]) for e in snapshot["entities"] for p in e.get("ports", [])]
            + [("relationship", r["id"]) for r in snapshot["relationships"]])
    got = [(f["kind"], f["id"]) for f in sidecar["fates"]]
    if sorted(want) != sorted(got):
        missing = sorted(set(want) - set(got))
        extra = sorted(set(got) - set(want))
        dup = sorted({x for x in got if got.count(x) > 1})
        raise DexpiExportError(f"FATE_ACCOUNTING_FAILED missing={missing[:5]} extra={extra[:5]} duplicated={dup[:5]}")
    bad = [f for f in sidecar["fates"] if f["fate"] not in FATES]
    if bad:
        raise DexpiExportError("FATE_VALUE_INVALID")


# --------------------------------------------------------------------------------------------- check 3: source read-back
def audit_read(xml: str | bytes) -> tuple[list[dict], list[str]]:
    """Separately written Expat reader: objects with ordered typed leaf values and ID references. DTDs and entities are refused
    (no external-entity resolution), input is size-limited. Returns (objects, issues)."""
    raw = xml.encode("utf-8") if isinstance(xml, str) else xml
    if len(raw) > MAX_XML_BYTES:
        return [], ["INPUT_OVER_LIMIT"]
    parser = expat.ParserCreate()
    stack: list[tuple[str, dict]] = []
    objects: list[dict] = []
    issues: list[str] = []
    cur: list[dict] = []

    def start(name, attrs):
        stack.append((name, attrs))
        if name == "Object":
            objects.append({"id": attrs.get("id"), "type": attrs.get("type"), "data": [], "references": [], "depth": len(stack)})
        elif name == "References":
            o = next((o for o in reversed(objects) if o["depth"] < len(stack)), None)
            if o is not None:
                o["references"].append((attrs.get("property"), attrs.get("objects", "").split()))
        elif name == "Data":
            cur.append({"depth": len(stack), "prop": attrs.get("property"), "owner": next((o for o in reversed(objects) if o["depth"] < len(stack)), None), "kind": None, "text": ""})
        elif cur and len(stack) == cur[-1]["depth"] + 1:
            cur[-1]["kind"] = name

    def chars(s):
        if cur and len(stack) == cur[-1]["depth"] + 1:
            cur[-1]["text"] += s

    def end(name):
        if name == "Data":
            d = cur.pop()
            if d["owner"] is not None:
                d["owner"]["data"].append((d["prop"], d["kind"], d["text"]))
        stack.pop()

    def refuse(*_a):
        raise ValueError("DTD_ENTITIES_FORBIDDEN")
    parser.StartElementHandler, parser.EndElementHandler, parser.CharacterDataHandler = start, end, chars
    parser.StartDoctypeDeclHandler = parser.EntityDeclHandler = parser.ExternalEntityRefHandler = refuse
    try:
        parser.Parse(raw, True)
    except (expat.ExpatError, ValueError) as ex:
        return objects, ["MALFORMED_XML" if isinstance(ex, expat.ExpatError) else str(ex)]
    ids = [o["id"] for o in objects if o["id"]]
    idset = set(ids)
    if len(ids) != len(idset):
        issues.append("DUPLICATE_ID")
    for o in objects:
        for _prop, targets in o["references"]:
            if any(t.lstrip("#") not in idset for t in targets):
                issues.append("DANGLING_REFERENCE")
    return objects, sorted(set(issues))


def readback(xml: str, sidecar: dict) -> dict:
    """Compare the XML with the fate table and the embedded source snapshot. Separate from schema and registry checks."""
    objects, issues = audit_read(xml)
    problems = list(issues)
    by_id = {o["id"]: o for o in objects if o["id"]}
    snap = sidecar["source_snapshot"]
    ents = {e["id"]: e for e in snap["entities"]}
    rels = {r["id"]: r for r in snap["relationships"]}
    ns = sidecar["namespace"]
    for f in sidecar["fates"]:
        if f["fate"] in (REPRESENTED, REPRESENTED_UNSUPPORTED):
            if not f["xml_ids"]:
                problems.append(f"FATE_WITHOUT_XML_OBJECT:{f['id']}")
            for xid in f["xml_ids"]:
                if xid not in by_id:
                    problems.append(f"WRITTEN_BUT_MISSING_IN_XML:{f['id']}")
        elif f["xml_ids"]:
            problems.append(f"SIDECAR_ONLY_BUT_HAS_XML:{f['id']}")
    for xid, o in by_id.items():
        if xid in sidecar["id_mapping"]:
            m = sidecar["id_mapping"][xid]
            try:
                dns, dsrc = decode_id(xid)
            except DexpiExportError:
                problems.append(f"ID_NOT_DECODABLE:{xid}")
                continue
            if dns != ns:
                problems.append(f"WRONG_NAMESPACE:{xid}")
            if dsrc != sidecar["objects"].get(xid, {}).get("xml_key"):
                problems.append(f"ID_MAPPING_MISMATCH:{xid}")
            src = ents.get(m["source_id"])
            tag = next((v for p, _k, v in o["data"] if p in ("TagName", "PipingComponentName")), None)
            if src is not None and (o["type"].startswith("Plant/ProcessEquipment.") or o["type"].startswith("Plant/Piping.")) and src.get("tag") and tag != src["tag"]:
                problems.append(f"TAG_DIFFERS_FROM_SOURCE:{m['source_id']}")
            if src is not None and src.get("classification") in (EQUIP | VALVES):
                expected = (EQUIP | VALVES)[src["classification"]]
                if o["type"] != expected:
                    problems.append(f"CLASS_DIFFERS_FROM_SOURCE:{m['source_id']}")
        elif o["type"] not in ("Core/EngineeringModel", "Plant/PlantModel", "Core/Note", "Core/PersistentIdentifier"):
            problems.append(f"XML_OBJECT_WITHOUT_SOURCE:{xid}")
    return {"layer": "SOURCE_READBACK", "status": "PASS" if not problems else "FAIL", "problems": sorted(set(problems))[:100], "objects_read": len(objects),
            "scope": "compares the XML with this program's own snapshot and fate table; it is not an independent importer"}


# --------------------------------------------------------------------------------------------- check 2: registry
def load_registry(*paths: str | Path) -> dict:
    """Official DEXPI model files (Core.xml, Plant.xml ...) -> {class path: {abstract, supers, props}}. Files are parsed with DTDs refused."""
    reg: dict[str, dict] = {}
    for p in paths:
        data = Path(p).read_bytes()
        if b"<!DOCTYPE" in data[:4096] or b"<!ENTITY" in data[:4096]:
            raise DexpiExportError("REGISTRY_FILE_HAS_DTD")
        root = ET.fromstring(data)
        model = root.get("name")

        def walk(node, pkg):
            for ch in node:
                if ch.tag == "Package":
                    walk(ch, (pkg + "." if pkg else "") + ch.get("name"))
                elif ch.tag in ("ConcreteClass", "AbstractClass"):
                    path = f"{model}/{pkg + '.' if pkg else ''}{ch.get('name')}"
                    supers = []
                    for s in (ch.get("superTypes") or "").split():
                        supers.append(model + s if s.startswith("/") else s)
                    props = {c.get("name") for c in ch if c.tag in ("DataProperty", "CompositionProperty", "ReferenceProperty")}
                    reg[path] = {"abstract": ch.tag == "AbstractClass", "supers": supers, "props": props}
        walk(root, "")
    return reg


def _all_props(reg: dict, cls: str, seen=None) -> set[str]:
    seen = seen or set()
    if cls in seen or cls not in reg:
        return set()
    seen.add(cls)
    out = set(reg[cls]["props"])
    for s in reg[cls]["supers"]:
        out |= _all_props(reg, s, seen)
    return out


def registry_check(xml: str, registry: dict) -> dict:
    """Structural check against the official model files: class exists, is concrete, and every property used is declared (own or inherited)."""
    _objs, issues = audit_read(xml)
    if "MALFORMED_XML" in issues or any("DTD" in i for i in issues):
        return {"layer": "REGISTRY_STRUCTURE", "status": "FAIL", "errors": [{"code": i} for i in issues]}
    root = ET.fromstring(xml)
    errors = []

    def visit(obj):
        t = obj.get("type")
        if t not in registry:
            errors.append({"code": "UNKNOWN_CLASS", "class": t, "id": obj.get("id")})
            props = None
        else:
            if registry[t]["abstract"]:
                errors.append({"code": "ABSTRACT_CLASS_INSTANTIATED", "class": t, "id": obj.get("id")})
            props = _all_props(registry, t)
        for ch in obj:
            if ch.tag in ("Components", "Data", "References"):
                name = ch.get("property")
                if props is not None and name not in props and name.rsplit("/", 1)[-1] not in props:
                    errors.append({"code": "UNKNOWN_PROPERTY", "class": t, "property": name, "id": obj.get("id")})
                if ch.tag == "Components":
                    for sub in ch:
                        if sub.tag == "Object":
                            visit(sub)
    for o in root:
        if o.tag == "Object":
            visit(o)
    by_code: dict[str, int] = {}
    for e in errors:
        by_code[e["code"]] = by_code.get(e["code"], 0) + 1
    return {"layer": "REGISTRY_STRUCTURE", "status": "PASS" if not errors else "FAIL", "errors": errors[:100], "by_code": by_code,
            "scope": "class and property names against the official model files; datatypes, units and engineering meaning are NOT assessed"}


# --------------------------------------------------------------------------------------------- check 1: XSD
def validate_xsd(xml: str, xsd_path: str | Path | None, expected_sha256: str | None = None) -> dict:
    """Schema validation against the official XSD. Reports BLOCKED (never PASS) when the XSD or a validator is missing."""
    if xsd_path is None or not Path(xsd_path).is_file():
        return {"layer": "XSD", "status": "BLOCKED_XSD_NOT_SUPPLIED", "reason": "the official DEXPI 2.0.1 XSD was not supplied"}
    digest = hashlib.sha256(Path(xsd_path).read_bytes()).hexdigest()
    if expected_sha256 and digest != expected_sha256:
        return {"layer": "XSD", "status": "BLOCKED_XSD_HASH_MISMATCH", "sha256": digest}
    try:
        from lxml import etree
    except ImportError:
        return {"layer": "XSD", "status": "BLOCKED_NO_XML_SCHEMA_VALIDATOR", "reason": "lxml is not installed in the locked environment", "xsd_sha256": digest}
    parser = etree.XMLParser(no_network=True, resolve_entities=True, load_dtd=False)
    schema = etree.XMLSchema(etree.parse(str(xsd_path), parser))
    doc = etree.fromstring(xml.encode("utf-8"), etree.XMLParser(no_network=True, resolve_entities=False))
    ok = schema.validate(doc)
    return {"layer": "XSD", "status": "VALID" if ok else "INVALID", "errors": [f"{e.type_name}: {e.message}" for e in schema.error_log][:50], "xsd_sha256": digest}


# --------------------------------------------------------------------------------------------- orchestration
def _unique_base(folder: Path, stem: str) -> str:
    """``stem`` or ``stem (2)``, ... such that none of the three output files exists yet (never overwrites)."""
    k = 1
    while True:
        base = stem if k == 1 else f"{stem} ({k})"
        if not any((folder / (base + ext)).exists() for ext in (".dexpi.xml", ".dexpi.sidecar.json", ".dexpi.checks.json")):
            return base
        k += 1


def export_dexpi_proposed(snapshot: dict, folder: str | Path, *, mode: str | None = None, include_unreviewed: bool = False,
                          registry_files: tuple | list = (), xsd_path: str | Path | None = None, xsd_sha256: str | None = None, cancel=None) -> dict:
    """Write ``<stem>.dexpi.xml`` + ``<stem>.dexpi.sidecar.json`` + ``<stem>.dexpi.checks.json`` into ``folder`` (never overwriting).

    OFF refuses (the legacy behaviour). SHADOW writes the same three files into a sub-folder ``_shadow_dexpi`` and reports that nothing
    authoritative changed. ON writes next to the other exports. The result states the three check layers separately."""
    m = r5_features.mode("DEXPI", mode)
    if m == r5_features.OFF:
        from .dexpi import DexpiNotAvailable
        raise DexpiNotAvailable("DEXPI_EXPORT_OFF: the proposed DEXPI export is switched off (PID_R5_DEXPI=off). Use the JSON/CSV/HTML reports.")
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError("The chosen folder does not exist")
    target = folder / "_shadow_dexpi" if m == r5_features.SHADOW else folder
    xml, sidecar = to_dexpi(snapshot, include_unreviewed=include_unreviewed, cancel=cancel)
    checks = {"xsd": validate_xsd(xml, xsd_path, xsd_sha256), "registry": None, "readback": readback(xml, sidecar)}
    checks["registry"] = registry_check(xml, load_registry(*registry_files)) if registry_files else {"layer": "REGISTRY_STRUCTURE", "status": "BLOCKED_REGISTRY_FILES_NOT_SUPPLIED"}
    checks["conformance"] = ("NOT_CLAIMED: schema, structure and read-back are separate partial checks; no external importer was run and no engineering review was done")
    stem = Path(snapshot["drawings"][0]["source_name"]).stem or "drawing"
    target.mkdir(exist_ok=True)
    base = _unique_base(target, stem) + ".dexpi"
    xml_path = target / (base + ".xml")
    xml_path.write_text(xml, encoding="utf-8", newline="")
    (target / (base + ".sidecar.json")).write_text(json.dumps(sidecar, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8", newline="")
    (target / (base + ".checks.json")).write_text(json.dumps(checks, indent=1, sort_keys=True), encoding="utf-8", newline="")
    counts: dict[str, int] = {}
    for f in sidecar["fates"]:
        counts[f["fate"]] = counts.get(f["fate"], 0) + 1
    return {"mode": m, "xml": str(xml_path), "sidecar": str(target / (base + ".sidecar.json")), "checks_file": str(target / (base + ".checks.json")),
            "fate_counts": counts, "checks": {k: (v["status"] if isinstance(v, dict) else v) for k, v in checks.items()}, "authoritative_output_changed": m == r5_features.ON}
