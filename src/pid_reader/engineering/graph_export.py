"""Canonical graph v1 (nodes, ports, edges, provenance, scores) and GraphML export of one drawing.

Built from stored, source-hash-bound analyses (connectivity proposals, readings, accepted/pending
teach-by-example matches). Everything is ``PROPOSED_UNVERIFIED`` unless a named reviewer has decided on the
underlying finding; nothing is asserted about the constructed plant. The structure follows the research
specification's ``graph.schema.json`` (kept in ``contracts/standalone_canonical_graph_v1.schema.json``).
Ids are deterministic hashes of canonical source keys.
"""
from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET

from ..api import canonical_json
from .connectivity import drawing_connectivity
from .findings import list_findings

SCHEMA_VERSION = "1.0.0"
PRODUCER = "pid_reader.graph_export"
EQUIPMENT_CLASSES = {"VESSEL", "TANK", "COLUMN", "HEAT_EXCHANGER", "PUMP", "COMPRESSOR", "FILTER"}
VALVE_CLASSES = {"VALVE_ONOFF", "VALVE_MANUAL", "VALVE_CONTROL", "PSV", "RUPTURE_DISC"}


def _id(prefix: str, *parts) -> str:
    return prefix + "_" + hashlib.sha256(canonical_json(list(parts)).encode("utf-8")).hexdigest()[:16]


def _prov(sha: str, page: int, object_ids: list[str], bbox: dict) -> dict:
    return {"source_sha256": sha, "page_index": page - 1, "source_object_ids": object_ids or ["none"],
            "producer": PRODUCER, "producer_version": SCHEMA_VERSION, "coordinate_frame_id": "media-top-left-v1",
            "bbox_normalized": {k: round(float(bbox[k]), 7) for k in ("x0", "y0", "x1", "y1")},
            "model_sha256": None, "config_sha256": None}


def canonical_graph(store, extraction_id: str) -> dict:
    extraction = store.export_extraction(extraction_id)
    sha = extraction["document"]["sha256"]
    reg = store.db.execute("SELECT drawing_no,revision_label FROM drawing_registration WHERE extraction_id=? "
                           "ORDER BY rowid DESC LIMIT 1", (extraction_id,)).fetchone()
    conn = drawing_connectivity(store, extraction_id)
    objects = {o["text"]: o for o in extraction["objects"] if o.get("text")}
    nodes, ports, edges = [], [], []
    node_ids: dict[str, str] = {}

    def add_node(key: str, kind: str, label: str, page: int, bbox: dict, ids: list[str], score, attrs: dict, state="PROPOSED_UNVERIFIED"):
        nid = _id("n", sha, key)
        node_ids[key] = nid
        nodes.append({"id": nid, "kind": kind, "label": label, "review_state": state,
                      "provenance": _prov(sha, page, ids, bbox),
                      "score": {"kind": "HEURISTIC" if score is not None else "NONE", "value": score, "calibration_id": None},
                      "attributes": attrs})
        return nid

    for n in conn.get("nodes", []):
        if n["kind"] == "SYMBOL":
            cls = {objects[t]["class"] for t in n.get("tags", []) if t in objects}
            kind = ("EQUIPMENT" if cls & EQUIPMENT_CLASSES else "VALVE" if cls & VALVE_CLASSES else
                    "INSTRUMENT" if "INSTRUMENT" in cls or n.get("symbol_class") == "INSTRUMENT_BUBBLE_CANDIDATE" else "UNKNOWN")
            confs = [objects[t]["confidence"] for t in n.get("tags", []) if t in objects]
            conf = max(confs) if confs else None
            add_node(n["id"], kind, n["label"], n["page"], n["bbox"], [n["id"]], conf,
                     {"tags": ", ".join(n.get("tags", [])), "symbol_class": n.get("symbol_class", "")})
        elif n["kind"] == "VALVE_GLYPH":
            add_node(n["id"], "VALVE", n["label"], n["page"], n["bbox"], [n["id"]], None, {"valve_subtype": "UNKNOWN"})
        else:
            add_node(n["id"], "PIPE_SEGMENT", n["label"], n["page"], n["bbox"], n.get("segment_ids", [])[:50], None,
                     {"stroke_count": n.get("stroke_count", 0), "line_style": n.get("style", ""),
                      "includes_tee": bool(n.get("includes_tee"))})
    # taught look-alikes (rejected ones are left out; accepted ones are marked as reviewed drawing readings)
    for f in list_findings(store, extraction_id, "examples", limit=2000):
        if f["state"] == "REJECTED":
            continue
        d = f["detail"]
        kind = {"VALVE": "VALVE", "INSTRUMENT": "INSTRUMENT", "EQUIPMENT": "EQUIPMENT"}.get(d["class_hint"], "ANNOTATION")
        add_node("example:" + f["id"], kind, d["label"], f["page"], f["bbox"], [f["id"]], round(float(d["score"]), 4),
                 {"taught_symbol": d["label"], "similarity": round(float(d["score"]), 4), "origin": "TEACH_BY_EXAMPLE"},
                 "REVIEWED_DRAWING" if f["state"] == "ACCEPTED_AS_READING" else "PROPOSED_UNVERIFIED")
    for e in conn.get("edges", []):
        a, b = node_ids.get(e["from"]), node_ids.get(e["to"])
        if not a or not b:
            continue
        net = next((n for n in conn["nodes"] if n["id"] == e["to"]), {})
        pkind = "SIGNAL" if net.get("style") == "DASHED" else "PROCESS"
        x, y = e["point"]
        pa, pb = _id("p", a, e["id"], "item"), _id("p", b, e["id"], "line")
        box = {"x0": x, "y0": y, "x1": min(1.0, x + 1e-4), "y1": min(1.0, y + 1e-4)}
        for pid, owner in ((pa, a), (pb, b)):
            ports.append({"id": pid, "owner_node_id": owner, "kind": pkind, "x": round(x, 7), "y": round(y, 7),
                          "review_state": "PROPOSED_UNVERIFIED", "provenance": _prov(sha, e["page"], [e["id"]], box), "label": None})
        edges.append({"id": _id("e", sha, e["id"]), "from_port_id": pa, "to_port_id": pb, "kind": "CONNECTS_ON_DRAWING",
                      "direction": "UNKNOWN", "review_state": "PROPOSED_UNVERIFIED",
                      "provenance": _prov(sha, e["page"], [e["id"]], box),
                      "score": {"kind": "NONE", "value": None, "calibration_id": None}, "hypothesis_group_id": None})
    graph = {"schema_version": SCHEMA_VERSION,
             "drawing_revision": f"{reg['drawing_no']} rev {reg['revision_label']}" if reg else "UNREGISTERED",
             "source_sha256": sha, "nodes": sorted(nodes, key=lambda n: n["id"]), "ports": sorted(ports, key=lambda p: p["id"]),
             "edges": sorted(edges, key=lambda e: e["id"]), "hypotheses": [],
             "generated_from": [extraction["document"]["filename"]], "review_policy": "PROPOSALS_ONLY"}
    return graph


def to_graphml(graph: dict) -> str:
    """GraphML of the canonical graph at node level (an edge joins the owners of its two ports)."""
    owner = {p["id"]: p["owner_node_id"] for p in graph["ports"]}
    root = ET.Element("graphml", xmlns="http://graphml.graphdrawing.org/xmlns")
    for i, (name, typ) in enumerate((("kind", "string"), ("label", "string"), ("review_state", "string"), ("page", "int"),
                                     ("relation", "string"))):
        ET.SubElement(root, "key", id=f"d{i}", **{"for": "edge" if name == "relation" else "node"},
                      **{"attr.name": name, "attr.type": typ})
    g = ET.SubElement(root, "graph", id="G", edgedefault="undirected")
    for n in graph["nodes"]:
        el = ET.SubElement(g, "node", id=n["id"])
        for i, v in enumerate((n["kind"], n["label"], n["review_state"], n["provenance"]["page_index"] + 1)):
            ET.SubElement(el, "data", key=f"d{i}").text = str(v)
    for e in graph["edges"]:
        el = ET.SubElement(g, "edge", id=e["id"], source=owner[e["from_port_id"]], target=owner[e["to_port_id"]])
        ET.SubElement(el, "data", key="d4").text = e["kind"] + " (proposed, unverified)"
    ET.indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=False)
