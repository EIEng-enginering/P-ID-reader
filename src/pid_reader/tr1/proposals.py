"""Tag-to-symbol assignment proposals and conservative join hints for learned-detector detections (Grok R3 modules, switches default OFF).

Both are PROPOSALS shown next to a detection; neither is written to the database or the correction queue, neither is a plant fact and neither is ever
accepted by software.

* ``propose_tags`` (PIDLAB_TAG_ASSIGN_R3): which read tag text most plausibly belongs to which detected symbol. Hungarian assignment with abstention
  (``tag_assign``): a tag may stay UNRESOLVED, a symbol takes at most one tag, and a close call is AMBIGUOUS. Evidence so far is authored fixtures only
  (precision 1.00 against 0.35 for nearest-symbol, 0 reciprocal swaps against 24); the real-drawing gate is BLOCKED.
* ``join_hints`` (PIDLAB_GRAPH_CONSERVATIVE_R3): two detected symbols are hinted as joined only when ONE ink component touches exactly those two symbols;
  a component touching more is an UNRESOLVED junction and nothing is joined. Precision was 0.68 and recall 0.28 on synthetic-source sheets (gate 0.70
  FAILED), so these are hints to look at, never connections, and they must never feed an export as connectivity.
"""
from __future__ import annotations

from . import flags, graph_conservative, tag_assign

TAG_SWITCH = "PIDLAB_TAG_ASSIGN_R3"
HINT_SWITCH = "PIDLAB_GRAPH_CONSERVATIVE_R3"
NOT_TAGS = ("LINE", "NOTE")            # reader classes that are not equipment or instrument tags
MAX_HINT_PIXELS = 150_000_000


class Unavailable(RuntimeError):
    pass


def _components(tags: list[dict], syms: list[dict]) -> list[tuple[list[dict], list[dict]]]:
    """Split the problem into independent groups: tags and symbols that can possibly pair up. The optimum of the whole equals the optimum of each group."""
    parent = {("t", t["id"]): ("t", t["id"]) for t in tags}
    parent.update({("s", s["id"]): ("s", s["id"]) for s in syms})

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for t in tags:
        for s in syms:
            if tag_assign.pair_cost(t, s) is not None:
                parent[find(("t", t["id"]))] = find(("s", s["id"]))
    groups: dict = {}
    for t in tags:
        groups.setdefault(find(("t", t["id"])), ([], []))[0].append(t)
    for s in syms:
        groups.setdefault(find(("s", s["id"])), ([], []))[1].append(s)
    return [g for g in groups.values() if g[0]]


def assign_split(tags: list[dict], syms: list[dict]) -> list[dict]:
    """Same answers as ``tag_assign.assign(tags, syms)`` without leaders or pattern, computed group by group (much faster on a busy sheet)."""
    out = []
    for gt, gs in _components(tags, syms):
        out += tag_assign.assign(gt, gs) if gs else [{"tag": t["id"], "symbol": None, "status": "UNRESOLVED", "cost": None, "margin": None, "alternatives": []} for t in gt]
    return out


def _px(b: dict, w: float, h: float) -> tuple[float, float, float, float]:
    return (b["x0"] * w, b["y0"] * h, b["x1"] * w, b["y1"] * h)


def propose_tags(detections: list[dict], objects: list[dict], page: int, page_px: tuple[float, float], frame=None, explicit_flag=None) -> dict:
    """{detection id: {tag_id, tag_text, status, margin, cost}} plus the tags left UNRESOLVED. ``objects`` are reader objects with media-frame boxes;
    detections are in the rendered-page frame, so tag boxes are mapped into that frame first."""
    if not flags.enabled(TAG_SWITCH, explicit_flag):
        raise Unavailable(f"{TAG_SWITCH} is switched off")
    w, h = page_px
    tags = []
    for o in objects:
        if o.get("page") != page or o.get("class") in NOT_TAGS or not (o.get("text") or "").strip():
            continue
        b = frame.media_bbox_to_render_clipped(o["bbox"]) if frame is not None else o["bbox"]
        if b:
            tags.append({"id": o["id"], "text": o["text"], "box": _px(b, w, h)})
    syms = [{"id": d["id"], "box": _px(d["bbox"], w, h), "cls": d.get("coarse_class")} for d in detections]
    by_tag = {t["id"]: t for t in tags}
    per_symbol, unresolved = {}, []
    for r in assign_split(tags, syms):
        if r["symbol"] is None:
            unresolved.append(r["tag"])
            continue
        per_symbol[r["symbol"]] = {"tag_id": r["tag"], "tag_text": by_tag[r["tag"]]["text"], "status": r["status"], "margin": r["margin"], "cost": r["cost"],
                                   "review_state": "PROPOSED"}
    return {"per_symbol": per_symbol, "unresolved_tags": unresolved, "tags_considered": len(tags), "symbols": len(syms)}


def join_hints(detections: list[dict], gray, explicit_flag=None) -> dict:
    """Conservative join HINTS between detections. ``gray`` is the rendered page as a uint8 array in the same frame as the detections
    (``render scale 2.5``, the detector's frame). Returns {pairs: [(id, id)], unresolved_junction_components, note}. Never connections."""
    if not flags.enabled(HINT_SWITCH, explicit_flag):
        raise Unavailable(f"{HINT_SWITCH} is switched off")
    h, w = gray.shape[:2]
    if w * h > MAX_HINT_PIXELS:
        raise Unavailable(f"The rendered page ({w}x{h}) is larger than {MAX_HINT_PIXELS:,} pixels; join hints are not computed for it.")
    syms = [{"id": d["id"], "box": _px(d["bbox"], w, h)} for d in detections]
    res = graph_conservative.predict(gray, syms)
    return {"pairs": sorted(res["conservative"]), "unresolved_junction_components": res["unresolved_junction_components"],
            "note": "Hints only: one drawn ink component touches exactly these two detected symbols. Proximity is not connectivity; precision was 0.68 on synthetic-source "
                    "sheets (gate 0.70 failed). Not a connection and not for export."}
