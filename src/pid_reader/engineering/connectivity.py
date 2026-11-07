"""Proposed drawn-line connectivity graph (bipartite: items <-> line networks).

Nodes are tagged/untagged outline symbols and valve glyphs. Between them sit
*line networks*: groups of pipe-like strokes that touch end-to-end or in a tee.
An item attaches to a network where a stroke endpoint meets its outline or
glyph side. Everything here is derived deterministically from already stored,
source-hash-bound analyses and stays ``PROPOSED_UNVERIFIED``:

* crossings and collinear overlaps never join networks;
* tee junctions do join, but every path through one is flagged ``via_tee``;
* an attachment is "a drawn line ends at this outline", not a verified nozzle;
* valves are pass-through elements in the *drawing*; no flow or position
  (open/closed) is asserted.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque

from ..api import canonical_json

SCHEMA = "pid-reader-standalone-connectivity-v1"
MAX_PAIRS = 5000
_JOINING = {"ENDPOINT_TOUCH_CANDIDATE": False, "BRANCH_TEE_AMBIGUOUS": True}


class _DSU:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def build_connectivity(extraction: dict, geometry: dict, symbols: dict, linework: dict | None) -> dict:
    text_by_id = {o["id"]: o["text"] for o in extraction["objects"] if o.get("text")}
    segments = {s["id"]: s for s in geometry["segments"]}
    roles = {r["segment_id"]: r["role"] for r in (linework or {}).get("stroke_roles", [])}
    outline_strokes: set[str] = set()
    for shape in geometry.get("shape_candidates", []):
        outline_strokes.update(shape.get("segment_ids", []) or shape.get("stroke_ids", []) or [])
    glyph_strokes = {sid for sid, role in roles.items() if role == "VALVE_GLYPH_STROKE"}
    pipe_like = {sid for sid in segments if sid not in outline_strokes and sid not in glyph_strokes}

    dsu = _DSU()
    for sid in pipe_like:
        dsu.find(sid)
    tee_strokes: set[str] = set()
    uncertain_contacts = []
    for c in geometry["contact_candidates"]:
        a, b = (c.get("segment_ids") or [None, None])[:2]
        kind = c["kind"]
        if a in pipe_like and b in pipe_like:
            if kind in _JOINING:
                dsu.union(a, b)
                if _JOINING[kind]:
                    tee_strokes.update((a, b))
            else:
                uncertain_contacts.append({"contact_id": c["id"], "kind": kind, "page": c["page"]})

    members: dict[str, list[str]] = defaultdict(list)
    for sid in sorted(pipe_like):
        members[dsu.find(sid)].append(sid)

    def net_id(root: str) -> str:
        return "net-" + hashlib.sha256(canonical_json(sorted(members[root])).encode()).hexdigest()[:16]

    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def add_net(root: str) -> str:
        nid = net_id(root)
        if nid not in nodes:
            styles = {segments[s]["style"] for s in members[root]}
            nodes[nid] = {"id": nid, "kind": "LINE_NETWORK", "label": f"Line network ({len(members[root])} strokes)",
                          "page": segments[members[root][0]]["page"], "bbox": _union_box(
                              [segments[s]["endpoints"] for s in members[root]]),
                          "stroke_count": len(members[root]),
                          "style": ("DASHED" if styles == {"DASHED_OR_DOTTED"} else
                                    "SOLID_OR_UNKNOWN" if "DASHED_OR_DOTTED" not in styles else "MIXED"),
                          "includes_tee": any(s in tee_strokes for s in members[root]),
                          "segment_ids": sorted(members[root]), "status": "PROPOSED_UNVERIFIED"}
        return nid

    for sym in symbols["symbol_candidates"]:
        texts = [text_by_id[t] for t in sym.get("tag_object_ids", []) if t in text_by_id]
        label = " / ".join(texts) if texts else sym["candidate_class"].replace("_", " ").title() + " (no tag)"
        nodes[sym["id"]] = {"id": sym["id"], "kind": "SYMBOL", "label": label, "page": sym["page"],
                            "bbox": sym["bbox"], "symbol_class": sym["candidate_class"],
                            "tags": texts, "status": "PROPOSED_UNVERIFIED"}
    for valve in (linework or {}).get("valve_candidates", []):
        nodes[valve["id"]] = {"id": valve["id"], "kind": "VALVE_GLYPH", "label": "Valve-style glyph (no tag)",
                              "page": valve["page"], "bbox": valve["bbox"], "tags": [],
                              "status": "PROPOSED_UNVERIFIED"}

    def attach(item_id: str, segment_id: str, relation: str, point: list[float], page: int) -> None:
        if item_id not in nodes or segment_id not in pipe_like:
            return
        nid = add_net(dsu.find(segment_id))
        edges.append({"id": "edge-" + hashlib.sha256(canonical_json([item_id, nid, segment_id, point]).encode()).hexdigest()[:16],
                      "from": item_id, "to": nid, "relation": relation, "page": page, "point": point,
                      "via_tee": segment_id in tee_strokes, "status": "PROPOSED_UNVERIFIED"})

    for port in symbols.get("port_candidates", []):
        attach(port["symbol_id"], port["segment_id"], "LINE_ENDS_AT_OUTLINE", port["point"], port["page"])
    for port in (linework or {}).get("valve_port_candidates", []):
        attach(port["valve_id"], port["segment_id"], "LINE_ENDS_AT_VALVE_SIDE", port["point"], port["page"])

    edges.sort(key=lambda e: e["id"])
    # Item-to-item reachability across line networks, passing through valve glyphs only.
    adj: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for e in edges:
        adj[e["from"]].append((e["to"], e))
        adj[e["to"]].append((e["from"], e))
    pairs = []
    terminals = sorted(n for n, v in nodes.items() if v["kind"] == "SYMBOL")
    for start in terminals:
        seen = {start}
        queue = deque([(start, [], False)])
        while queue:
            cur, valves, tee = queue.popleft()
            for nxt, edge in adj[cur]:
                if nxt in seen:
                    continue
                seen.add(nxt)
                t = tee or edge["via_tee"] or (nodes[nxt]["kind"] == "LINE_NETWORK" and nodes[nxt]["includes_tee"])
                kind = nodes[nxt]["kind"]
                if kind == "SYMBOL":
                    if start < nxt:
                        pairs.append({"a": start, "b": nxt, "a_label": nodes[start]["label"], "b_label": nodes[nxt]["label"],
                                      "via_valve_glyphs": list(valves), "via_tee": t,
                                      "relation": "DRAWN_LINE_PATH", "status": "PROPOSED_UNVERIFIED"})
                    continue  # equipment/instruments terminate a path
                queue.append((nxt, valves + [nxt] if kind == "VALVE_GLYPH" else valves, t))
    pairs.sort(key=lambda p: (p["a"], p["b"]))
    attached = {e["to"] for e in edges}
    result = {
        "schema": SCHEMA,
        "source_sha256": geometry["source_sha256"],
        "nodes": sorted(nodes.values(), key=lambda n: n["id"]),
        "edges": edges,
        "paths": pairs[:MAX_PAIRS],
        "free_networks": sum(1 for r in members if net_id(r) not in attached),
        "uncertain_contacts": sorted(uncertain_contacts, key=lambda c: c["contact_id"]),
        "limitations": ("Proposed graph of drawn lines and outlines. A path means ink connects two outlines in this "
                        "drawing revision; it does not verify piping, flow direction, valve state, instrument loops "
                        "or the constructed plant. Crossings never join; tee junctions are flagged."),
    }
    result["result_sha256"] = hashlib.sha256(canonical_json(
        {k: v for k, v in result.items()}).encode()).hexdigest()
    return result


def _union_box(polylines: list[list[list[float]]]) -> dict:
    xs = [p[0] for line in polylines for p in line]
    ys = [p[1] for line in polylines for p in line]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    return {"x0": round(x0, 7), "y0": round(y0, 7), "x1": round(max(x1, x0 + 0.0005), 7), "y1": round(max(y1, y0 + 0.0005), 7)}


def drawing_connectivity(db, extraction_id: str) -> dict:
    """Connectivity for the newest stored symbol/geometry/linework analyses of a drawing."""
    from .findings import latest_analysis_ids
    ids = latest_analysis_ids(db, extraction_id)
    if "geometry" not in ids or "symbols" not in ids:
        return {"schema": SCHEMA, "nodes": [], "edges": [], "paths": [], "free_networks": 0,
                "uncertain_contacts": [], "limitations": "Run the analysis first (geometry and symbols are required)."}
    extraction = db.export_extraction(extraction_id)
    geometry = db.get_geometry_analysis(ids["geometry"])
    symbols = db.get_symbol_analysis(ids["symbols"])
    linework = db.get_linework_analysis(ids["linework"]) if "linework" in ids else None
    return build_connectivity(extraction, geometry, symbols, linework)
