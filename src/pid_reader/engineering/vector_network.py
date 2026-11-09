"""Vector linework with capacity-aware tiling, junction typing and arrows (Rev X, WPU-07/08). Standalone; never writes the frozen R1.

* Strokes (lines, rectangle edges, flattened curves) keep their ``path_id``; arcs/polylines stay recoverable.
* Pages with more strokes than one tile can hold are split into overlapping spatial tiles (overlap > the largest symbol); contacts are found
  per tile and de-duplicated in page coordinates. ``status`` is ``PARTIAL`` only if a hard cap really truncated work, and every truncated
  tile is listed -- nothing is dropped silently.
* Every contact is typed. A crossing is *not* a connection: a junction dot supports joined, a hop (small bridging arc) supports separated,
  an unmarked crossing favours separated and keeps the alternative; skew crossings stay ``UNKNOWN_CROSSING``.
* Arrow heads (small filled triangles) give a direction only when their axis lines up with a stroke; otherwise direction stays ``UNKNOWN``.
All outputs are proposals with evidence ids; nothing here says what flows or what is connected in the plant.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from io import BytesIO
from math import atan2, cos, degrees, hypot, pi, sin

from .topology import TOUCH_TOLERANCE_PT, _segment_contact

VERSION = "vector-network-v1"
TILE_TARGET = 4000            # segments per tile before the page is split
MAX_PAGE_SEGMENTS = 400000    # hard cap for one page (reported as PARTIAL when reached)
MAX_TILES = 144
MAX_CONTACTS_PER_TILE = 60000
OVERLAP_PT = 48.0
DOT_MAX_PT = 6.0
ARROW_MAX_PT = 20.0
HOP_MAX_PT = 14.0


def _sid(kind: str, *parts) -> str:
    return kind + "-" + hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:20]


def extract_geometry(page, page_number: int, source_sha: str, cancel=None) -> dict:
    """Strokes, junction dots, arrow heads and hop arcs from one pdfplumber page (points, top-left origin)."""
    w, h = float(page.width), float(page.height)
    strokes: list[dict] = []
    dots: list[dict] = []
    arrows: list[dict] = []
    hops: list[dict] = []

    def add_stroke(kind, path_id, p0, p1, lw, dash):
        if hypot(p1[0] - p0[0], p1[1] - p0[1]) < 1e-6:
            return
        strokes.append({"id": _sid("stk", source_sha, page_number, kind, path_id, [round(p0[0], 2), round(p0[1], 2)], [round(p1[0], 2), round(p1[1], 2)]),
                        "kind": kind, "path_id": path_id, "raw_pts": [tuple(p0), tuple(p1)], "linewidth": lw, "dash": bool(dash)})
    for i, ln in enumerate(page.lines):
        pts = ln.get("pts") or []
        for a, b in zip(pts[:-1], pts[1:]):
            add_stroke("LINE", f"l{i}", a, b, float(ln.get("linewidth") or 0), ln.get("dash"))
    for i, rc in enumerate(page.rects):
        x0, x1, top, bottom = float(rc["x0"]), float(rc["x1"]), float(rc["top"]), float(rc["bottom"])
        lw = float(rc.get("linewidth") or 0)
        if rc.get("fill") and not rc.get("stroke") and (x1 - x0 <= 2.0 or bottom - top <= 2.0):
            add_stroke("LINE", f"r{i}", ((x0 + x1) / 2, top), ((x0 + x1) / 2, bottom) if x1 - x0 <= 2.0 else (x1, (top + bottom) / 2), lw, None) \
                if x1 - x0 <= 2.0 else add_stroke("LINE", f"r{i}", (x0, (top + bottom) / 2), (x1, (top + bottom) / 2), lw, None)
            continue
        for k, (a, b) in enumerate((((x0, top), (x1, top)), ((x1, top), (x1, bottom)), ((x1, bottom), (x0, bottom)), ((x0, bottom), (x0, top)))):
            add_stroke("RECT_EDGE", f"r{i}", a, b, lw, rc.get("dash"))
    for i, cv in enumerate(page.curves):
        if cancel is not None and i % 500 == 0:
            cancel.check()
        pts = cv.get("pts") or []
        if len(pts) < 2:
            continue
        x0, x1, top, bottom = float(cv["x0"]), float(cv["x1"]), float(cv["top"]), float(cv["bottom"])
        bw, bh = x1 - x0, bottom - top
        lw = float(cv.get("linewidth") or 0)
        closed = hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 0.5
        filled = bool(cv.get("fill"))
        if filled and closed and max(bw, bh) <= DOT_MAX_PT and 0.6 <= (bw / bh if bh else 0) <= 1.6 and len(pts) >= 4:
            dots.append({"id": _sid("dot", source_sha, page_number, [round(x0, 1), round(top, 1)]), "center": ((x0 + x1) / 2, (top + bottom) / 2),
                         "radius": max(bw, bh) / 2})
            continue
        distinct = _distinct(pts)
        if filled and closed and len(distinct) == 3 and max(bw, bh) <= ARROW_MAX_PT:
            arrows.append({"id": _sid("arw", source_sha, page_number, [round(x0, 1), round(top, 1)]), "vertices": distinct,
                           "bbox": (x0, top, x1, bottom)})
            continue
        # a hop is a short open arc. pdfplumber's bbox ignores Bezier control points, so the extent comes from the path itself
        ex0, etop, ex1, ebot = _path_extent(cv, (x0, top, x1, bottom))
        if not filled and not closed and max(ex1 - ex0, ebot - etop) <= HOP_MAX_PT and min(ex1 - ex0, ebot - etop) >= 2.0                 and any(op[0] == "c" for op in (cv.get("path") or [])):
            hops.append({"id": _sid("hop", source_sha, page_number, [round(ex0, 1), round(etop, 1)]), "bbox": (ex0, etop, ex1, ebot), "pts": pts})
            continue
        for a, b in zip(pts[:-1], pts[1:]):
            add_stroke("CURVE", f"c{i}", a, b, lw, cv.get("dash"))
    return {"width": w, "height": h, "strokes": strokes, "dots": dots, "arrows": arrows, "hops": hops}


def _path_extent(cv: dict, fallback: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    xs, ys = [], []
    for op in cv.get("path") or []:
        for pt in op[1:]:
            xs.append(float(pt[0]))
            ys.append(float(pt[1]))
    if not xs:
        return fallback
    return min(xs), min(ys), max(xs), max(ys)


def _distinct(pts) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for p in pts:
        if not any(hypot(p[0] - q[0], p[1] - q[1]) < 0.3 for q in out):
            out.append((float(p[0]), float(p[1])))
    return out


def tile_plan(strokes: list[dict], width: float, height: float, target: int = TILE_TARGET, overlap: float = OVERLAP_PT,
              max_tiles: int = MAX_TILES) -> list[dict]:
    """Smallest square-ish grid whose busiest tile (with overlap) holds at most ``target`` strokes, up to ``max_tiles`` tiles."""
    if len(strokes) <= target:
        return [{"index": 0, "box": (0.0, 0.0, width, height), "owned": (0.0, 0.0, width, height)}]
    mids = [((s["raw_pts"][0][0] + s["raw_pts"][1][0]) / 2, (s["raw_pts"][0][1] + s["raw_pts"][1][1]) / 2) for s in strokes]
    best = None
    for k in range(2, 13):
        for gx, gy in ((k, k), (k + 1, k), (k, k + 1)):
            if gx * gy > max_tiles:
                continue
            counts = defaultdict(int)
            for mx, my in mids:
                counts[(min(gx - 1, int(mx / width * gx)), min(gy - 1, int(my / height * gy)))] += 1
            peak = max(counts.values())
            if best is None or peak < best[0]:
                best = (peak, gx, gy)
            if peak <= target * 0.6:
                break
        else:
            continue
        break
    peak, gx, gy = best
    tiles = []
    for j in range(gy):
        for i in range(gx):
            ox0, oy0, ox1, oy1 = i * width / gx, j * height / gy, (i + 1) * width / gx, (j + 1) * height / gy
            tiles.append({"index": len(tiles), "box": (max(0.0, ox0 - overlap), max(0.0, oy0 - overlap), min(width, ox1 + overlap), min(height, oy1 + overlap)),
                          "owned": (ox0, oy0, ox1, oy1)})
    return tiles


def _seg_box(s: dict) -> tuple[float, float, float, float]:
    (x0, y0), (x1, y1) = s["raw_pts"]
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def _in_box(box, b) -> bool:
    return not (b[2] < box[0] or b[0] > box[2] or b[3] < box[1] or b[1] > box[3])


def _contacts_in_tile(segs: list[dict], cap: int, cancel=None) -> tuple[list[dict], bool]:
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    cell = 48.0
    boxes = [_seg_box(s) for s in segs]
    for idx, (x0, y0, x1, y1) in enumerate(boxes):
        for gx in range(int(x0 // cell), int(x1 // cell) + 1):
            for gy in range(int(y0 // cell), int(y1 // cell) + 1):
                grid[(gx, gy)].append(idx)
    seen = set()
    out: list[dict] = []
    truncated = False
    for ci, members in enumerate(grid.values()):
        if cancel is not None and ci % 400 == 0:
            cancel.check()
        n = len(members)
        for a in range(n):
            for b in range(a + 1, n):
                i, j = members[a], members[b]
                key = (i, j) if i < j else (j, i)
                if key in seen:
                    continue
                seen.add(key)
                ba, bb = boxes[key[0]], boxes[key[1]]
                if ba[2] < bb[0] - TOUCH_TOLERANCE_PT or bb[2] < ba[0] - TOUCH_TOLERANCE_PT or \
                        ba[3] < bb[1] - TOUCH_TOLERANCE_PT or bb[3] < ba[1] - TOUCH_TOLERANCE_PT:
                    continue
                hit = _segment_contact(segs[key[0]], segs[key[1]])
                if hit is None:
                    continue
                out.append({"a": segs[key[0]]["id"], "b": segs[key[1]]["id"], "type": hit[0], "point": hit[1]})
                if len(out) >= cap:
                    return out, True
    return out, truncated


def _angle(seg: dict) -> float:
    (x0, y0), (x1, y1) = seg["raw_pts"]
    return degrees(atan2(y1 - y0, x1 - x0)) % 180.0


def classify_contact(contact: dict, by_id: dict[str, dict], dots: list[dict], hops: list[dict]) -> dict:
    """Junction status with its supports. Never returns a plant claim."""
    px, py = contact["point"]
    a, b = by_id[contact["a"]], by_id[contact["b"]]
    lw = max(a["linewidth"], b["linewidth"], 0.5)
    dot = next((d["id"] for d in dots if hypot(d["center"][0] - px, d["center"][1] - py) <= max(3.0, 3.0 * lw) + d["radius"]), None)
    hop = next((hp["id"] for hp in hops if hp["bbox"][0] - 2 <= px <= hp["bbox"][2] + 2 and hp["bbox"][1] - 2 <= py <= hp["bbox"][3] + 2), None)
    diff = abs(_angle(a) - _angle(b))
    diff = min(diff, 180 - diff)
    ctype = contact["type"]
    if ctype == "COLLINEAR_OVERLAP_AMBIGUOUS":
        status, relation = "DUPLICATE_OR_OVERLAP", None
    elif ctype == "CROSSING_AMBIGUOUS":
        if dot:
            status, relation = "JOINED_SUPPORTED", "DRAWN_CONNECTS"
        elif hop:
            status, relation = "SEPARATED_SUPPORTED", None
        elif diff < 60:
            status, relation = "UNKNOWN_CROSSING", None                 # skew crossing: neither reading is favoured
        else:
            status, relation = "SEPARATED_FAVOURED", None
    else:                                                               # T branch or end-to-end touch
        status, relation = ("JOINED_SUPPORTED" if dot else "JOINED_FAVOURED"), "DRAWN_CONNECTS"
    return {"id": _sid("jct", contact["a"], contact["b"], [round(px, 1), round(py, 1)]), "stroke_a": contact["a"], "stroke_b": contact["b"],
            "geometry": ctype, "point": [round(px, 3), round(py, 3)], "angle_between_deg": round(diff, 1), "status": status,
            "relation": relation, "supports": {"dot": dot, "hop": hop},
            "alternatives": ([{"status": "JOINED_FAVOURED" if status.startswith("SEPARATED") or status == "UNKNOWN_CROSSING" else "SEPARATED_FAVOURED"}]
                             if status in ("SEPARATED_FAVOURED", "UNKNOWN_CROSSING", "JOINED_FAVOURED") else [])}


def arrow_directions(arrows: list[dict], strokes: list[dict]) -> list[dict]:
    """Direction from small filled triangles. Only when the head's axis lines up with a stroke; else ``UNKNOWN``."""
    out = []
    for ar in arrows:
        v = ar["vertices"]
        sides = [(hypot(v[i][0] - v[(i + 1) % 3][0], v[i][1] - v[(i + 1) % 3][1]), i) for i in range(3)]
        sides.sort()
        base_i = sides[0][1]                                            # shortest side = base of an arrow head
        a0, a1 = v[base_i], v[(base_i + 1) % 3]
        apex = v[(base_i + 2) % 3]
        mid = ((a0[0] + a1[0]) / 2, (a0[1] + a1[1]) / 2)
        axis = (apex[0] - mid[0], apex[1] - mid[1])
        length = hypot(*axis)
        isosceles = abs(sides[1][0] - sides[2][0]) <= 0.25 * max(sides[1][0], sides[2][0])
        rec = {"id": ar["id"], "bbox": [round(c, 3) for c in ar["bbox"]], "apex": [round(apex[0], 3), round(apex[1], 3)],
               "direction": "UNKNOWN", "stroke_id": None, "vector": None, "evidence": "triangle head"}
        if length > 0.5 and isosceles:
            ang = degrees(atan2(axis[1], axis[0])) % 180.0
            reach = max(length * 3.0, 6.0)
            for s in strokes:
                (x0, y0), (x1, y1) = s["raw_pts"]
                d = abs((y1 - y0) * mid[0] - (x1 - x0) * mid[1] + x1 * y0 - y1 * x0) / max(hypot(x1 - x0, y1 - y0), 1e-9)
                sa = degrees(atan2(y1 - y0, x1 - x0)) % 180.0
                da = min(abs(sa - ang), 180 - abs(sa - ang))
                if d <= 1.5 and da <= 6.0 and (min(x0, x1) - reach <= mid[0] <= max(x0, x1) + reach) and (min(y0, y1) - reach <= mid[1] <= max(y0, y1) + reach):
                    rec.update(direction="ALONG_DRAWN_STROKE", stroke_id=s["id"], vector=[round(axis[0] / length, 4), round(axis[1] / length, 4)],
                               evidence="triangle axis aligned with stroke")
                    break
        out.append(rec)
    return out


def analyze_vector_network(pdf_bytes: bytes, page_number: int, *, cancel=None, tile_target: int = TILE_TARGET,
                           max_page_segments: int = MAX_PAGE_SEGMENTS, max_tiles: int = MAX_TILES, progress=None) -> dict:
    """Strokes, typed junctions, dots/hops and arrow directions for one page, tiled when dense."""
    import pdfplumber
    source_sha = hashlib.sha256(pdf_bytes).hexdigest()
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        if not 1 <= page_number <= len(pdf.pages):
            raise ValueError("Page out of range")
        page = pdf.pages[page_number - 1]
        geo = extract_geometry(page, page_number, source_sha, cancel)
    strokes = geo["strokes"]
    incomplete: list[dict] = []
    if len(strokes) > max_page_segments:
        incomplete.append({"reason": "PAGE_SEGMENT_CAP", "found": len(strokes), "kept": max_page_segments})
        strokes = strokes[:max_page_segments]
    by_id = {s["id"]: s for s in strokes}
    tiles = tile_plan(strokes, geo["width"], geo["height"], tile_target, max_tiles=max_tiles)
    contacts: dict[tuple, dict] = {}
    tiles_info = []
    for ti, t in enumerate(tiles):
        if cancel is not None:
            cancel.check()
        if progress is not None:
            progress(0.1 + 0.85 * ti / max(1, len(tiles)), f"line tile {ti + 1} of {len(tiles)}")
        segs = [s for s in strokes if _in_box(t["box"], _seg_box(s))]
        found, truncated = _contacts_in_tile(segs, MAX_CONTACTS_PER_TILE, cancel)
        for c in found:
            key = (tuple(sorted((c["a"], c["b"]))), round(c["point"][0], 1), round(c["point"][1], 1))
            ox0, oy0, ox1, oy1 = t["owned"]
            contacts.setdefault(key, c)
        tiles_info.append({"index": t["index"], "box": [round(v, 1) for v in t["box"]], "strokes": len(segs), "contacts": len(found), "truncated": truncated})
        if truncated:
            incomplete.append({"reason": "TILE_CONTACT_CAP", "tile": t["index"], "cap": MAX_CONTACTS_PER_TILE})
    junctions = [classify_contact(c, by_id, geo["dots"], geo["hops"]) for _, c in sorted(contacts.items(), key=lambda kv: kv[0])]
    arrows = arrow_directions(geo["arrows"], strokes)
    w, h = geo["width"], geo["height"]
    status = "COMPLETE_CANDIDATES" if not incomplete else "PARTIAL"
    result = {"schema": "pid-reader-standalone-vector-network-v1", "version": VERSION, "page": page_number, "source_sha256": source_sha,
              "page_size_pt": [round(w, 3), round(h, 3)], "status": status, "incomplete": incomplete,
              "counts": {"strokes": len(strokes), "tiles": len(tiles), "junctions": len(junctions), "dots": len(geo["dots"]),
                         "hops": len(geo["hops"]), "arrows": len(arrows),
                         "by_status": {k: sum(1 for j in junctions if j["status"] == k) for k in sorted({j["status"] for j in junctions})}},
              "tiles": tiles_info,
              "strokes": [{"id": s["id"], "kind": s["kind"], "path_id": s["path_id"], "p0": [round(s["raw_pts"][0][0] / w, 6), round(s["raw_pts"][0][1] / h, 6)],
                           "p1": [round(s["raw_pts"][1][0] / w, 6), round(s["raw_pts"][1][1] / h, 6)], "linewidth": s["linewidth"], "dash": s["dash"]}
                          for s in strokes],
              "junctions": [{**j, "point_norm": [round(j["point"][0] / w, 6), round(j["point"][1] / h, 6)]} for j in junctions],
              "dots": [{"id": d["id"], "center": [round(d["center"][0] / w, 6), round(d["center"][1] / h, 6)]} for d in geo["dots"]],
              "hops": [{"id": hp["id"], "bbox": [round(hp["bbox"][0] / w, 6), round(hp["bbox"][1] / h, 6), round(hp["bbox"][2] / w, 6), round(hp["bbox"][3] / h, 6)]}
                       for hp in geo["hops"]],
              "arrows": arrows,
              "limitations": ("A drawn junction is not a plant connection. Unmarked crossings favour 'separated' but keep the alternative; direction is "
                              "reported only for arrow heads aligned with a stroke and never assumed left-to-right.")}
    return result
