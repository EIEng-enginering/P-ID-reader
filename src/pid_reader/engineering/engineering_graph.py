"""Typed port/asset graph v2 for one drawing (Rev X, WPU-09). Pure and deterministic; standalone, not the frozen R1.

Inputs are earlier *proposals*: library symbol occurrences with typed ports (``symbol_detect``), the vector network (``vector_network``:
strokes, typed junctions, arrows) and tag-like text. Output nodes are **occurrences** (a drawn thing on this page, immutable to the page);
**asset hypotheses** are separate and only link occurrences when independent evidence exists (never from a tag string alone).

Rules enforced:
* ports are typed and never aliased to the symbol centre;
* an edge ``DRAWN_CONNECTS`` / ``SIGNAL_CONNECTS`` needs a drawn stroke path between two ports of *different* occurrences; the search stops at the
  first foreign port and never passes through another occurrence, so a valve is not traversed as if it were pipe;
* separated or unknown crossings create no connection; paths that touch a crossing with an alternative reading say so;
* port kinds must be compatible (a process line is never joined to a signal port); incompatible pairs become ``CONFLICT`` items;
* direction comes only from an arrow aligned with a stroke on the path; otherwise ``UNKNOWN`` -- never left-to-right by default;
* proximity alone never makes a plant connection, and tags are attached by a bounded cost (distance, grammar fit, 1-to-1) with alternatives kept.
"""
from __future__ import annotations

import hashlib
import heapq
import json
from collections import defaultdict
from math import hypot

from .engineering_text import classify_text

VERSION = "engineering-graph-v2"
SNAP_PT = 0.8
PORT_ATTACH_PT = 4.5
TAG_RADIUS_FACTOR = 2.4
PROCESS_KINDS = {"PROCESS_UNKNOWN", "PROCESS_IN", "PROCESS_OUT", "PROCESS_BIDIRECTIONAL", "NOZZLE", "DRAIN", "VENT"}
SIGNAL_KINDS = {"SIGNAL_IN", "SIGNAL_OUT", "ACTUATOR_SIGNAL"}
# INSTRUMENT_PORT: a bubble's connection point. Drawings attach lines on any side, so the port has no built-in direction or role:
# the drawn line style and the other end decide whether it is an impulse/process line or a signal line.
_FAMILY_KIND = {"VALVE": "VALVE", "ACTUATOR": "VALVE_ACTUATOR", "INSTRUMENT": "INSTRUMENT", "EQUIPMENT": "EQUIPMENT"}


def _id(prefix: str, *parts) -> str:
    return prefix + "-" + hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:20]


def port_compatible(a: str, b: str, dashed: bool | None = None) -> tuple[bool, str]:
    """May a drawn line join these two port kinds? Returns (allowed, edge_type). ``dashed``: the drawn path is all dashed (None = unknown)."""
    if a == "INSTRUMENT_PORT" or b == "INSTRUMENT_PORT":
        other = b if a == "INSTRUMENT_PORT" else a
        if other in PROCESS_KINDS or other == "INSTRUMENT_TAP":
            return (False, "") if dashed else (True, "DRAWN_CONNECTS")        # a dashed signal line is not an impulse line to a process port
        if other in SIGNAL_KINDS or other == "INSTRUMENT_PORT":
            return True, "SIGNAL_CONNECTS" if dashed or other in SIGNAL_KINDS else "DRAWN_CONNECTS"
        return False, ""
    if a in PROCESS_KINDS and b in PROCESS_KINDS:
        return True, "DRAWN_CONNECTS"
    if (a == "INSTRUMENT_TAP" and b in PROCESS_KINDS) or (b == "INSTRUMENT_TAP" and a in PROCESS_KINDS):
        return True, "DRAWN_CONNECTS"
    if {a, b} <= (SIGNAL_KINDS | {"INSTRUMENT_TAP"}) and (a in SIGNAL_KINDS or b in SIGNAL_KINDS):
        if (a == "SIGNAL_OUT" and b in ("SIGNAL_IN", "ACTUATOR_SIGNAL")) or (b == "SIGNAL_OUT" and a in ("SIGNAL_IN", "ACTUATOR_SIGNAL")):
            return True, "SIGNAL_CONNECTS"
        if a == "SIGNAL_OUT" and b == "SIGNAL_OUT":
            return False, ""
    return False, ""


def _tag_candidates(words: list[dict]) -> list[dict]:
    out = []
    for w in words:
        cls = classify_text(w["text"])
        if cls["primary"] in ("INSTRUMENT_TAG", "UNKNOWN") and any(ch.isdigit() for ch in w["text"]) and 2 <= len(w["text"]) <= 14:
            out.append({**w, "grammar": cls["primary"]})
    return out


def associate_tags(occurrences: list[dict], words: list[dict], w_pt: float, h_pt: float) -> list[dict]:
    """1-to-1 tag association by cost = normalised distance, minus a grammar bonus; alternatives within 25 % are kept."""
    cands = _tag_candidates(words)
    scored = []
    for occ in occurrences:
        occ = {**occ, "family": occ.get("family") or occ.get("graphical_family")}
        b = occ["bbox"]
        cx, cy = (b["x0"] + b["x1"]) / 2 * w_pt, (b["y0"] + b["y1"]) / 2 * h_pt
        size = max((b["x1"] - b["x0"]) * w_pt, (b["y1"] - b["y0"]) * h_pt, 4.0)
        for t in cands:
            tb = t["bbox"]
            tx, ty = (tb["x0"] + tb["x1"]) / 2 * w_pt, (tb["y0"] + tb["y1"]) / 2 * h_pt
            inside = b["x0"] <= (tb["x0"] + tb["x1"]) / 2 <= b["x1"] and b["y0"] <= (tb["y0"] + tb["y1"]) / 2 <= b["y1"]
            dist = hypot(tx - cx, ty - cy)
            if dist > size * TAG_RADIUS_FACTOR + 0.5 * hypot((tb["x1"] - tb["x0"]) * w_pt, (tb["y1"] - tb["y0"]) * h_pt):
                continue
            cost = dist / size
            if occ["family"] == "INSTRUMENT" and t["grammar"] == "INSTRUMENT_TAG":
                cost -= 0.3
            if inside:
                cost -= 0.2
            scored.append((cost, occ["id"], t["id"], t))
    scored.sort(key=lambda s: (s[0], s[1], s[2]))
    taken_occ, taken_tag, assign = set(), set(), {}
    alts: dict[str, list] = defaultdict(list)
    for cost, oid, tid, t in scored:
        if oid in taken_occ or tid in taken_tag:
            if oid not in taken_occ or oid in assign:
                alts[oid].append({"text": t["text"], "word_id": tid, "cost": round(cost, 3), "note": "competing nearby text"})
            continue
        taken_occ.add(oid)
        taken_tag.add(tid)
        assign[oid] = {"text": t["text"], "word_id": tid, "source": t.get("source", ""), "cost": round(cost, 3), "bbox": t["bbox"],
                       "assignment": "ASSOCIATED_PROPOSAL"}
    for oid, a in assign.items():
        a["alternatives"] = [x for x in alts.get(oid, []) if x["cost"] <= a["cost"] * 1.25 + 0.05][:3]
    return [{"occurrence_id": oid, **a} for oid, a in sorted(assign.items())]


def _project(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return 0.0, hypot(p[0] - ax, p[1] - ay), a
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    q = (ax + t * dx, ay + t * dy)
    return t, hypot(p[0] - q[0], p[1] - q[1]), q


def build_graph(*, page: int, page_size_pt: tuple[float, float], occurrences: list[dict], vector: dict | None, words: list[dict],
                source_sha256: str = "") -> dict:
    """Return the page graph. ``occurrences`` are symbol-detect candidates (``id``, ``bbox``, ``ports``, family fields)."""
    w_pt, h_pt = page_size_pt
    occs = []
    for c in sorted(occurrences, key=lambda c: (c["bbox"]["y0"], c["bbox"]["x0"], c["id"])):
        fam = c.get("graphical_family") or c.get("family")
        occs.append({"id": c["id"], "family": fam, "bbox": c["bbox"], "ports": c.get("ports", []), "source": c})
    tags = associate_tags(occs, words, w_pt, h_pt)
    tag_by = {t["occurrence_id"]: t for t in tags}
    nodes, edges, conflicts, quality = [], [], [], {"unattached_ports": 0, "ports": 0, "vector_status": (vector or {}).get("status", "NOT_AVAILABLE")}
    port_nodes = []
    for o in occs:
        src = o["source"]
        nodes.append({"node_id": o["id"], "node_kind": "OCCURRENCE", "entity_kind": _FAMILY_KIND.get(o["family"], "UNCLASSIFIED_SYMBOL"), "page": page,
                      "bbox": o["bbox"], "engineering_class": src.get("engineering_class", "UNKNOWN"), "class_candidates": src.get("class_candidates", []),
                      "tag": tag_by.get(o["id"]), "actuation": src.get("actuation"), "confidence_status": src.get("confidence_status"),
                      "evidence_class": "STRUCTURALLY_DERIVED", "review_state": "PROPOSED_UNVERIFIED"})
        for k, p in enumerate(o["ports"]):
            pid = _id("port", o["id"], k, p["kind"], round(p["x"], 5), round(p["y"], 5))
            node = {"node_id": pid, "node_kind": "PORT", "occurrence_id": o["id"], "port_kind": p["kind"], "page": page,
                    "x": p["x"], "y": p["y"], "angle": p.get("angle"), "attached": False}
            port_nodes.append(node)
            nodes.append(node)
    quality["ports"] = len(port_nodes)
    strokes = {s["id"]: s for s in (vector or {}).get("strokes", [])}
    if not strokes:
        return _finish(page, nodes, edges, conflicts, tags, quality, source_sha256)
    pts = {sid: ((s["p0"][0] * w_pt, s["p0"][1] * h_pt), (s["p1"][0] * w_pt, s["p1"][1] * h_pt)) for sid, s in strokes.items()}
    splits: dict[str, list[tuple[float, tuple[float, float], str]]] = defaultdict(list)       # stroke -> [(t, point, node_key)]
    node_keys: dict[tuple[int, int], str] = {}

    def key_for(p) -> str:
        k = (int(round(p[0] / SNAP_PT)), int(round(p[1] / SNAP_PT)))
        return node_keys.setdefault(k, f"n{len(node_keys)}")

    for sid, (a, b) in pts.items():
        splits[sid].append((0.0, a, key_for(a)))
        splits[sid].append((1.0, b, key_for(b)))
    joined = [j for j in vector["junctions"] if j.get("relation") == "DRAWN_CONNECTS"]
    for j in joined:
        jp = (j["point_norm"][0] * w_pt, j["point_norm"][1] * h_pt)
        for sid in (j["stroke_a"], j["stroke_b"]):
            if sid in pts:
                t, _d, q = _project(jp, *pts[sid])
                splits[sid].append((t, q, key_for(jp)))
    attach: dict[str, str] = {}
    for pn in port_nodes:
        pp = (pn["x"] * w_pt, pn["y"] * h_pt)
        best = None
        for sid, (a, b) in pts.items():
            t, d, q = _project(pp, a, b)
            if d <= PORT_ATTACH_PT and (best is None or d < best[0]):
                best = (d, sid, t, q)
        if best:
            nk = key_for(pp)
            splits[best[1]].append((best[2], best[3], nk))
            attach[pn["node_id"]] = nk
            pn["attached"] = True
            pn["attached_stroke"] = best[1]
        else:
            quality["unattached_ports"] += 1
    adj: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
    for sid, plist in splits.items():
        ordered = sorted(plist, key=lambda x: x[0])
        for (t0, p0, k0), (t1, p1, k1) in zip(ordered[:-1], ordered[1:]):
            if k0 == k1:
                continue
            d = hypot(p1[0] - p0[0], p1[1] - p0[1])
            adj[k0].append((k1, d, sid))
            adj[k1].append((k0, d, sid))
    port_by_key: dict[str, list[dict]] = defaultdict(list)
    for pn in port_nodes:
        if pn["node_id"] in attach:
            port_by_key[attach[pn["node_id"]]].append(pn)
    def inside_symbol(j: dict) -> bool:
        """Contacts inside a symbol's own box are the symbol's drawing, not an open question about the pipe."""
        px, py = j["point_norm"]
        padx, pady = 1.5 / w_pt, 1.5 / h_pt
        return any(o["bbox"]["x0"] - padx <= px <= o["bbox"]["x1"] + padx and o["bbox"]["y0"] - pady <= py <= o["bbox"]["y1"] + pady for o in occs)
    risky = {j["id"]: j for j in vector["junctions"]
             if j["status"] in ("UNKNOWN_CROSSING", "SEPARATED_FAVOURED", "JOINED_FAVOURED") and not inside_symbol(j)}
    risky_by_stroke: dict[str, list[str]] = defaultdict(list)
    for jid, j in risky.items():
        risky_by_stroke[j["stroke_a"]].append(jid)
        risky_by_stroke[j["stroke_b"]].append(jid)
    arrows = [a for a in vector.get("arrows", []) if a["direction"] == "ALONG_DRAWN_STROKE"]
    seen_pairs: set[tuple[str, str]] = set()
    for pn in port_nodes:
        start = attach.get(pn["node_id"])
        if start is None:
            continue
        dist = {start: 0.0}
        prev: dict[str, tuple[str, str]] = {}
        heap = [(0.0, start)]
        while heap:
            d, k = heapq.heappop(heap)
            if d > dist.get(k, 1e18):
                continue
            foreign = [q for q in port_by_key.get(k, []) if q["occurrence_id"] != pn["occurrence_id"]]
            own_other = [q for q in port_by_key.get(k, []) if q["occurrence_id"] == pn["occurrence_id"] and q["node_id"] != pn["node_id"]]
            if k != start and (foreign or own_other):
                for q in foreign:
                    pair = tuple(sorted((pn["node_id"], q["node_id"])))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    path_strokes, cur = [], k
                    while cur != start:
                        pk, sid = prev[cur]
                        path_strokes.append(sid)
                        cur = pk
                    path_strokes = path_strokes[::-1]
                    all_dashed = bool(path_strokes) and all(strokes[s]["dash"] for s in path_strokes if s in strokes)
                    ok, etype = port_compatible(pn["port_kind"], q["port_kind"], all_dashed)
                    if not ok:
                        conflicts.append({"conflict_id": _id("cfl", pair), "kind": "PORT_KIND_MISMATCH", "ports": list(pair),
                                          "port_kinds": [pn["port_kind"], q["port_kind"]], "stroke_ids": path_strokes,
                                          "note": "a drawn line reaches incompatible port kinds; no connection is proposed"})
                        continue
                    if etype == "SIGNAL_CONNECTS" or all(strokes[s]["dash"] for s in path_strokes if s in strokes) and path_strokes:
                        etype_final = "SIGNAL_CONNECTS" if etype == "SIGNAL_CONNECTS" else etype
                    else:
                        etype_final = etype
                    alt_j = sorted({jid for s in path_strokes for jid in risky_by_stroke.get(s, [])})
                    direction = _direction(path_strokes, arrows, strokes, pn, q, pts, w_pt, h_pt)
                    edges.append({"edge_id": _id("edge", pair, path_strokes), "edge_kind": etype_final, "from_port": pair[0], "to_port": pair[1],
                                  "from_occurrence": pn["occurrence_id"] if pair[0] == pn["node_id"] else q["occurrence_id"],
                                  "to_occurrence": q["occurrence_id"] if pair[0] == pn["node_id"] else pn["occurrence_id"], "page": page,
                                  "direction": direction, "path_length_pt": round(d, 2),
                                  "evidence": {"stroke_ids": path_strokes, "junction_ids_with_alternatives": alt_j,
                                               "path_status": "HAS_ALTERNATIVES" if alt_j else "CLEAN"},
                                  "evidence_class": "STRUCTURALLY_DERIVED", "review_state": "PROPOSED_UNVERIFIED",
                                  "note": "ink path between two ports as drawn; not a verified plant connection"})
                continue
            for nk, w, sid in adj.get(k, []):
                nd = d + w
                if nd < dist.get(nk, 1e18):
                    dist[nk] = nd
                    prev[nk] = (k, sid)
                    heapq.heappush(heap, (nd, nk))
    edges.sort(key=lambda e: e["edge_id"])
    return _finish(page, nodes, edges, conflicts, tags, quality, source_sha256)


def _direction(path_strokes: list[str], arrows: list[dict], strokes: dict, p_from: dict, p_to: dict, pts: dict, w_pt: float, h_pt: float) -> dict:
    """Direction only from arrows aligned with a stroke of the path; opposing arrows -> CONFLICTING."""
    votes = []
    fx, fy = p_from["x"] * w_pt, p_from["y"] * h_pt
    tx, ty = p_to["x"] * w_pt, p_to["y"] * h_pt
    ux, uy = tx - fx, ty - fy
    for a in arrows:
        if a["stroke_id"] in path_strokes and a["vector"]:
            norm = hypot(ux, uy)
            dot = a["vector"][0] * ux + a["vector"][1] * uy
            if norm > 0 and abs(dot) / norm >= 0.85:        # the chord must run along the arrow's stroke; bends -> no vote
                votes.append((a["id"], "FROM_TO" if dot > 0 else "TO_FROM"))
    if not votes:
        return {"value": "UNKNOWN", "arrows": []}
    kinds = {v for _, v in votes}
    return {"value": next(iter(kinds)) if len(kinds) == 1 else "CONFLICTING", "arrows": [a for a, _ in votes]}


def _finish(page, nodes, edges, conflicts, tags, quality, source_sha) -> dict:
    graph = {"schema": "pid-reader-standalone-drawing-graph-v2", "version": VERSION, "page": page, "source_sha256": source_sha,
             "nodes": nodes, "edges": edges, "conflicts": conflicts, "tag_associations": tags,
             "asset_hypotheses": [{"asset_id": _id("asset", n["node_id"]), "occurrences": [n["node_id"]], "basis": "SINGLE_OCCURRENCE",
                                   "tag_text": (n["tag"] or {}).get("text"), "status": "PROPOSED_UNVERIFIED"}
                                  for n in nodes if n["node_kind"] == "OCCURRENCE"],
             "quality": quality,
             "limitations": ("Edges are ink paths between typed ports as drawn. They are not verified connections, not flow, and not safe isolation. "
                             "Asset hypotheses on one sheet never merge occurrences; a tag string is an attribute, not identity.")}
    graph["graph_sha256"] = hashlib.sha256(json.dumps({k: v for k, v in graph.items()}, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return graph
