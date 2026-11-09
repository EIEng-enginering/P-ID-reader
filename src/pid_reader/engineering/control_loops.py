"""Instrument loops, control relations and protective-device mentions (Rev X, WPU-10). Pure and deterministic.

Built only from drawn evidence: tagged occurrences and the drawn signal edges of the typed graph. A loop number shared by two tags is a
*candidate*; a loop is ``LINKED_BY_DRAWN_SIGNAL`` only when drawn signal edges join its members. PLC/DCS/SIS logic is never inferred from an
abbreviation: every control loop states ``logic: NOT_SHOWN_ON_DRAWING``. Protective devices (relief valves, ESD/shutdown valves, trip switches)
and interlock wording are listed as *mentions* with ``safety_credit: NOT_ASSESSED``: this module produces no SIL, no IPL, no safeguarding credit,
no HAZOP/LOPA conclusion and no statement that a device is installed, set or effective.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict

VERSION = "control-loops-v1"
FORBIDDEN_KEYS = {"sil", "sil_rating", "ipl", "ipl_credit", "safeguard_credit", "pfd", "risk_reduction", "lopa", "hazop_conclusion"}
_VARIABLES = {"P": "PRESSURE", "T": "TEMPERATURE", "F": "FLOW", "L": "LEVEL", "A": "ANALYSIS", "Z": "POSITION", "S": "SPEED_FREQUENCY",
              "V": "VIBRATION", "W": "WEIGHT_FORCE", "D": "DENSITY", "Q": "QUANTITY", "H": "HAND", "X": "UNCLASSIFIED", "U": "MULTIVARIABLE"}
_TAG = re.compile(r"^([A-Z]{2,4})[- ]?(\d{2,4})([A-Z]?)$")
_NOT_INSTRUMENT_PREFIX = {"NPS", "DN", "PN", "SP", "LINE", "HOLD", "NOTE", "REV", "SIZE", "CLASS", "SHEET", "ANSI"}
_CONTROL_SYSTEMS = re.compile(r"\b(PLC|DCS|SIS|ESD|SCADA|RTU|HMI)\b", re.I)
_INTERLOCK = re.compile(r"\b(INTERLOCK|TRIP|SHUTDOWN|SHUT-DOWN|PERMISSIVE|SIL|IPL|SAFETY INSTRUMENTED)\b", re.I)
_PROTECTIVE = re.compile(r"^(PSV|PRV|PSE|RV|ESDV|SDV|BDV|XV|TSV)[- ]?\d", re.I)


def _id(prefix: str, *parts) -> str:
    return prefix + "-" + hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:20]


def parse_instrument_tag(text: str) -> dict:
    """ISA-style tag parts: measured variable (first letter), function letters, loop number, suffix. Unparsed -> status UNPARSED."""
    t = text.strip().upper()
    m = _TAG.match(t)
    if not m or m.group(1) in _NOT_INSTRUMENT_PREFIX or m.group(1)[0] not in _VARIABLES:
        return {"verbatim": text, "status": "UNPARSED"}
    letters, number, suffix = m.groups()
    funcs = letters[1:]
    return {"verbatim": text, "status": "PARSED", "letters": letters, "measured_variable_letter": letters[0],
            "measured_variable": _VARIABLES.get(letters[0], "UNKNOWN"), "function_letters": funcs, "loop_number": number, "suffix": suffix,
            "roles": _roles(funcs)}


def _roles(funcs: str) -> list[str]:
    if funcs.endswith("V"):                      # PCV, FCV, HV, XV...: the item is the valve; its "C" says it is a control valve
        return ["FINAL_ELEMENT_VALVE"]
    roles = []
    if "C" in funcs:
        roles.append("CONTROLLER")
    if "T" in funcs:
        roles.append("TRANSMITTER")
    if "E" in funcs and "T" not in funcs:
        roles.append("PRIMARY_ELEMENT")
    if "S" in funcs:
        roles.append("SWITCH")
    if "I" in funcs:
        roles.append("INDICATOR")
    if "R" in funcs:
        roles.append("RECORDER")
    if "V" in funcs:
        roles.append("FINAL_ELEMENT_VALVE")
    if "Y" in funcs:
        roles.append("RELAY_OR_COMPUTE")
    if "A" in funcs or ("S" in funcs and ("H" in funcs or "L" in funcs)):
        roles.append("ALARM_OR_TRIP_SWITCH_CANDIDATE")
    return roles


def assert_no_safety_claims(obj) -> None:
    """Raise if any structure carries a SIL/IPL/credit style field. Used as a guard on everything this module emits."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in FORBIDDEN_KEYS:
                raise ValueError(f"Safety claim field {k!r} is not allowed in drawing-based proposals")
            assert_no_safety_claims(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            assert_no_safety_claims(v)


def build_loops(graphs: list[dict], words_by_page: dict[int, list[dict]] | None = None) -> dict:
    """Loops, control relations, protective mentions and control-system mentions from page graphs."""
    words_by_page = words_by_page or {}
    members: dict[str, dict] = {}
    for g in graphs:
        for n in g["nodes"]:
            if n["node_kind"] != "OCCURRENCE" or not n.get("tag"):
                continue
            parsed = parse_instrument_tag(n["tag"]["text"])
            members[n["node_id"]] = {"node_id": n["node_id"], "page": n["page"], "entity_kind": n["entity_kind"], "tag": n["tag"]["text"],
                                     "parsed": parsed, "engineering_class": n["engineering_class"], "actuation": n.get("actuation"),
                                     "bbox": n["bbox"], "tag_word_id": n["tag"]["word_id"]}
    signal_edges, process_edges = [], []
    port_owner: dict[str, dict] = {}
    for g in graphs:
        for n in g["nodes"]:
            if n["node_kind"] == "PORT":
                port_owner[n["node_id"]] = n
        for e in g["edges"]:
            (signal_edges if e["edge_kind"] == "SIGNAL_CONNECTS" else process_edges).append(e)
    # union-find over members linked by drawn signal edges
    parent = {m: m for m in members}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for e in signal_edges:
        a, b = e["from_occurrence"], e["to_occurrence"]
        if a in members and b in members:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
    by_number: dict[str, list[str]] = defaultdict(list)
    for mid, m in members.items():
        if m["parsed"]["status"] == "PARSED":
            by_number[m["parsed"]["loop_number"]].append(mid)
    loops = []
    for number, ids in sorted(by_number.items()):
        comps: dict[str, list[str]] = defaultdict(list)
        for mid in ids:
            comps[find(mid)].append(mid)
        linked = [c for c in comps.values() if len(c) >= 2]
        singles = [c for c in comps.values() if len(c) == 1]
        for comp in sorted(linked, key=lambda c: sorted(c)):
            loops.append(_loop_record(number, comp, members, signal_edges, "LINKED_BY_DRAWN_SIGNAL"))
        if len(ids) >= 2 and singles:
            # tags share a loop number but have no drawn signal path to the others: a candidate only, never a confirmed loop
            leftovers = [mid for c in singles for mid in c]
            if len(leftovers) >= 2 or linked:
                loops.append(_loop_record(number, leftovers, members, signal_edges, "LOOP_NUMBER_ONLY"))
    relations = _relations(signal_edges, process_edges, members, port_owner)
    protective = []
    for mid, m in sorted(members.items()):
        if _PROTECTIVE.match(m["tag"]) or "ALARM_OR_TRIP_SWITCH_CANDIDATE" in m["parsed"].get("roles", []):
            protective.append({"item_id": _id("prot", mid), "occurrence_id": mid, "tag": m["tag"], "page": m["page"],
                               "basis": "TAG_PATTERN" if _PROTECTIVE.match(m["tag"]) else "FUNCTION_LETTERS",
                               "statement": "drawn as a possible protective/alarm device; its set point, action, independence and effectiveness are not shown",
                               "safety_credit": "NOT_ASSESSED", "review_state": "PROPOSED_UNVERIFIED",
                               "evidence": [{"page": m["page"], "bbox": m["bbox"], "word_ids": [m["tag_word_id"]]}]})
    mentions = []
    for page, words in sorted(words_by_page.items()):
        for w in words:
            kind = "CONTROL_SYSTEM_MENTION" if _CONTROL_SYSTEMS.search(w["text"]) else "INTERLOCK_WORDING" if _INTERLOCK.search(w["text"]) else None
            if kind:
                mentions.append({"item_id": _id("men", page, w["id"], kind), "kind": kind, "page": page, "text": w["text"],
                                 "safety_credit": "NOT_ASSESSED", "logic": "NOT_SHOWN_ON_DRAWING", "review_state": "PROPOSED_UNVERIFIED",
                                 "evidence": [{"page": page, "bbox": w["bbox"], "word_ids": [w["id"]]}],
                                 "note": "wording found on the drawing; it is not a connection, a function or a credit"})
    result = {"schema": "pid-reader-standalone-control-loops-v1", "version": VERSION, "loops": loops, "relations": relations,
              "protective_device_mentions": protective, "text_mentions": mentions,
              "limitations": ("Loops come from tags plus drawn signal links. Controller logic, trip set points and interlocks are not on the drawing; "
                              "nothing here is a SIL, IPL, safeguarding credit or HAZOP/LOPA conclusion.")}
    assert_no_safety_claims(result)
    return result


def _loop_record(number: str, ids: list[str], members: dict, signal_edges: list[dict], status: str) -> dict:
    ordered = sorted(ids)
    ms = [members[i] for i in ordered]
    roles = sorted({r for m in ms for r in m["parsed"].get("roles", [])})
    variables = sorted({m["parsed"]["measured_variable"] for m in ms})
    rec = {"loop_id": _id("loop", number, ordered), "loop_number": number, "status": status, "page": min(m["page"] for m in ms),
           "members": [{"occurrence_id": m["node_id"], "tag": m["tag"], "entity_kind": m["entity_kind"], "roles": m["parsed"].get("roles", []),
                        "measured_variable": m["parsed"].get("measured_variable"), "actuation": (m["actuation"] or {}).get("actuation") if m["actuation"] else None}
                       for m in ms],
           "measured_variables": variables, "roles_present": roles,
           "signal_edge_ids": sorted(e["edge_id"] for e in signal_edges if e["from_occurrence"] in ordered and e["to_occurrence"] in ordered),
           "has_controller": "CONTROLLER" in roles, "has_final_element": any(m["entity_kind"] == "VALVE" for m in ms),
           "logic": "NOT_SHOWN_ON_DRAWING" if ("CONTROLLER" in roles or "SWITCH" in roles) else "NOT_APPLICABLE",
           "safety_credit": "NOT_ASSESSED", "review_state": "PROPOSED_UNVERIFIED",
           "truth_class": "STRUCTURALLY_DERIVED" if status == "LINKED_BY_DRAWN_SIGNAL" else "CONTEXTUAL_INFERENCE",
           "evidence": [{"page": m["page"], "bbox": m["bbox"], "word_ids": [m["tag_word_id"]]} for m in ms]}
    if status == "LOOP_NUMBER_ONLY":
        rec["note"] = "tags share a loop number but no drawn signal path joins them; not confirmed as one loop"
    elif rec["has_controller"] and not rec["has_final_element"]:
        rec["note"] = "controller present but no final element joined by a drawn signal in this loop"
    return rec


def _relations(signal_edges, process_edges, members, port_owner) -> list[dict]:
    out = []
    for e in signal_edges:
        a, b = members.get(e["from_occurrence"]), members.get(e["to_occurrence"])
        if not a or not b:
            continue
        pa, pb = port_owner.get(e["from_port"], {}), port_owner.get(e["to_port"], {})
        for src, dst, ps, pd in ((a, b, pa, pb), (b, a, pb, pa)):
            sroles = set(src["parsed"].get("roles", []))
            droles = set(dst["parsed"].get("roles", []))
            kind = None
            if "CONTROLLER" in sroles and dst["entity_kind"] == "VALVE" and (pd.get("port_kind") == "ACTUATOR_SIGNAL" or "FINAL_ELEMENT_VALVE" in droles):
                kind = "CONTROLS"
            elif ("TRANSMITTER" in sroles or "PRIMARY_ELEMENT" in sroles) and ("CONTROLLER" in droles or "INDICATOR" in droles or "RECORDER" in droles):
                kind = "INDICATES" if "CONTROLLER" not in droles else "MEASURED_VALUE_TO_CONTROLLER"
            elif src["parsed"].get("measured_variable_letter") == "Z" and dst["entity_kind"] == "VALVE":
                kind = "POSITION_FEEDBACK"
            elif "ALARM_OR_TRIP_SWITCH_CANDIDATE" in sroles:
                kind = "ALARM_REFERENCE"
            if kind:
                rec = {"relation_id": _id("rel", e["edge_id"], kind, src["node_id"], dst["node_id"]), "relation": kind,
                       "from_occurrence": src["node_id"], "to_occurrence": dst["node_id"], "via_edge_id": e["edge_id"],
                       "direction_basis": "TAG_FUNCTION_LETTERS_AND_PORT_KIND", "page": src["page"], "review_state": "PROPOSED_UNVERIFIED",
                       "truth_class": "CONTEXTUAL_INFERENCE", "safety_credit": "NOT_ASSESSED",
                       "note": "role read from tag letters on a drawn signal path; the drawing shows no logic",
                       "evidence": [{"page": src["page"], "edge_id": e["edge_id"], "word_ids": [src["tag_word_id"], dst["tag_word_id"]]}]}
                out.append(rec)
                if kind == "CONTROLS":
                    out.append({**rec, "relation_id": _id("rel", e["edge_id"], "ACTUATES", src["node_id"], dst["node_id"]), "relation": "ACTUATES"})
    for e in process_edges:
        a, b = members.get(e["from_occurrence"]), members.get(e["to_occurrence"])
        if not a or not b:
            continue
        pa, pb = port_owner.get(e["from_port"], {}), port_owner.get(e["to_port"], {})
        for inst, proc, pi in ((a, b, pa), (b, a, pb)):
            if pi.get("port_kind") == "INSTRUMENT_PORT" and inst["entity_kind"] == "INSTRUMENT" and proc["entity_kind"] != "INSTRUMENT":
                out.append({"relation_id": _id("rel", e["edge_id"], "MEASURES", inst["node_id"], proc["node_id"]), "relation": "MEASURES",
                            "from_occurrence": inst["node_id"], "to_occurrence": proc["node_id"], "via_edge_id": e["edge_id"],
                            "measured_variable": inst["parsed"].get("measured_variable"), "direction_basis": "INSTRUMENT_TO_PROCESS_TAP",
                            "page": inst["page"], "review_state": "PROPOSED_UNVERIFIED", "truth_class": "STRUCTURALLY_DERIVED",
                            "safety_credit": "NOT_ASSESSED", "note": "instrument drawn connected to this item; not a verified tapping point",
                            "evidence": [{"page": inst["page"], "edge_id": e["edge_id"], "word_ids": [inst["tag_word_id"]]}]})
    out.sort(key=lambda r: r["relation_id"])
    seen, uniq = set(), []
    for r in out:
        if r["relation_id"] not in seen:
            seen.add(r["relation_id"])
            uniq.append(r)
    return uniq
