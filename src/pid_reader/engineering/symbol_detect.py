"""Symbol detection against the original-geometry library (Rev X, WPU-05/06). Deterministic, tiled, bounded, cancellable.

Works the same on native vector, outlined-text vector and scanned pages: the page is rendered tile by tile (bounded memory, tile
overlap larger than the biggest symbol), ink is correlated (OpenCV normalised cross-correlation) against library templates at the
sheet's own stroke width, a size ladder and the needed quarter turns. Peaks are merged in world coordinates.

Honesty rules enforced here:
* the score is an UNCALIBRATED similarity, never a probability;
* overlapping detections of different classes form one hypothesis group; the alternatives stay on the candidate;
* below ``ACCEPT_SCORE`` the class is reported as ``UNKNOWN`` (family kept) -- a class is never forced;
* valve class and actuation are found separately, each with its own score and evidence box;
* nothing is accepted: every candidate is ``PROPOSED``.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from math import ceil

from . import symbol_library as lib

VERSION = "symbol-detect-v1"
SCORE_KIND = "UNCALIBRATED_NCC"
ACCEPT_SCORE = 0.72            # below this the engineering class is withheld (family only)
AMBIGUITY_MARGIN = 0.05
PRESETS = {
    # coarse_ratio: size step of the cheap first pass; fine_step: relative step of the local refinement around each coarse peak
    "quick": {"families": ("VALVE",), "coarse_ratio": 1.28, "fine_step": 0.05, "threshold": 0.66},
    "standard": {"families": ("VALVE", "ACTUATOR", "INSTRUMENT"), "coarse_ratio": 1.25, "fine_step": 0.04, "threshold": 0.62},
    "deep": {"families": ("VALVE", "ACTUATOR", "INSTRUMENT", "EQUIPMENT"), "coarse_ratio": 1.2, "fine_step": 0.03, "threshold": 0.58},
}
MAX_CANDIDATES_PER_PAGE = 4000
PEAK_CAP = 5000          # coarse-stage local maxima kept per template/size/orientation (more is reported as PEAK_CAP, never dropped silently)
MAX_TILES = 64


def _iou(a: dict, b: dict) -> float:
    ix = max(0.0, min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]))
    iy = max(0.0, min(a["y1"], b["y1"]) - max(a["y0"], b["y0"]))
    inter = ix * iy
    union = (a["x1"] - a["x0"]) * (a["y1"] - a["y0"]) + (b["x1"] - b["x0"]) * (b["y1"] - b["y0"]) - inter
    return inter / union if union > 0 else 0.0


def _contained(a: dict, b: dict) -> float:
    """Share of the smaller box that lies inside the other (1.0 = fully inside)."""
    ix = max(0.0, min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]))
    iy = max(0.0, min(a["y1"], b["y1"]) - max(a["y0"], b["y0"]))
    small = min((a["x1"] - a["x0"]) * (a["y1"] - a["y0"]), (b["x1"] - b["x0"]) * (b["y1"] - b["y0"]))
    return ix * iy / small if small > 0 else 0.0


def _precision(ink_bin, t_raw, x: int, y: int, pad: int = 0) -> float:
    """Share of the ink inside the matched box that the template explains (extra drawn ink lowers it).

    NCC alone rewards a template that fits *part* of a richer symbol (a T-bar inside a diaphragm head, a bare bow-tie on a globe
    valve). Precision is the missing penalty; it re-ranks look-alikes but never replaces the reported NCC score.
    """
    import cv2
    import numpy as np
    th, tw = t_raw.shape
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(ink_bin.shape[1], x + tw + pad), min(ink_bin.shape[0], y + th + pad)
    patch = ink_bin[y0:y1, x0:x1]
    if patch.size == 0 or x < 0 or y < 0 or x + tw > ink_bin.shape[1] or y + th > ink_bin.shape[0]:
        return 0.0
    mask = np.zeros(patch.shape, dtype=bool)
    mask[y - y0:y - y0 + th, x - x0:x - x0 + tw] = cv2.dilate(t_raw, np.ones((3, 3), np.uint8)) > 0
    total = int(patch.sum())
    return float((patch & mask).sum()) / total if total else 0.0


def _rank(score: float, precision: float) -> float:
    return score * (0.7 + 0.3 * precision)


def _stroke_px(binary) -> int:
    """Typical stroke thickness in pixels: low quantile of ink run lengths along rows and columns."""
    import numpy as np
    runs = []
    for arr in (binary, binary.T):
        sample = arr[:: max(1, arr.shape[0] // 160)]
        for row in sample:
            if not row.any():
                continue
            d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
            starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
            runs.extend((ends - starts).tolist())
    if not runs:
        return 2
    runs.sort()
    return int(max(1, min(5, runs[len(runs) // 4])))


def _tile_grid(width: int, height: int, tile: int, overlap: int) -> list[tuple[int, int, int, int]]:
    step = max(1, tile - overlap)
    xs = list(range(0, max(1, width - overlap), step))
    ys = list(range(0, max(1, height - overlap), step))
    return [(x, y, min(width, x + tile), min(height, y + tile)) for y in ys for x in xs]


def _render_tile(page, w_pt: float, h_pt: float, scale: float, box: tuple[int, int, int, int]):
    import numpy as np
    x0, y0, x1, y1 = box
    crop = (x0 / scale, h_pt - y1 / scale, w_pt - x1 / scale, y0 / scale)
    crop = tuple(max(0.0, c) for c in crop)
    img = page.render(scale=scale, crop=crop).to_pil().convert("L")
    return np.asarray(img)


def _match(ink_blur, template_id: str, size_pt: float, scale: float, stroke: int, rot: int, threshold: float):
    import cv2
    import numpy as np
    width = int(round(size_pt * scale))
    t = lib.render(template_id, width, stroke, rot)
    if t.shape[0] < 8 or t.shape[1] < 8 or t.shape[0] >= ink_blur.shape[0] or t.shape[1] >= ink_blur.shape[1]:
        return []
    t = cv2.GaussianBlur(t, (3, 3), 0)
    if float(t.std()) < 1.0:
        return []
    res = np.nan_to_num(cv2.matchTemplate(ink_blur, t, cv2.TM_CCOEFF_NORMED), nan=0.0, posinf=0.0, neginf=0.0)
    ys, xs = np.where(res >= threshold)
    if len(ys) > 150000:                                     # pathological (e.g. a solid block): refuse, never sort forever
        raise ValueError("template matches far too much of the tile; page content is not drawing-like")
    return [(float(res[y, x]), int(x), int(y), t.shape[1], t.shape[0]) for y, x in zip(ys.tolist(), xs.tolist())]


@lru_cache(maxsize=8192)
def _tpl(template_id: str, width_px: int, stroke: int, rot: int):
    """Rendered template plus its 3x3- and 7x7-blurred forms and whether each has any contrast. Read-only; cached because the same few hundred
    templates are re-used for every peak and every tile (rendering and blurring them each time was most of the run time on dense sheets)."""
    import cv2
    t = lib.render(template_id, width_px, stroke, rot)
    tb3, tb7 = cv2.GaussianBlur(t, (3, 3), 0), cv2.GaussianBlur(t, (7, 7), 0)
    return t, tb3, tb7, bool(float(tb3.std()) >= 1.0), bool(float(tb7.std()) >= 1.0)


REFINE_CAP = 400        # coarse peaks refined per template search; more is reported as PEAK_CAP


def _search(ink, ink_coarse, ink_fine, spec: dict, rot: int, cfg: dict, scale: float, stroke: int, ink_bin=None, stats: dict | None = None) -> list[dict]:
    """Two-stage size search for one template and orientation (see module docstring).

    Stage 1 correlates a heavily blurred page with a coarse size ladder at a lowered threshold; stage 2 re-correlates only inside a
    small window around each coarse peak with a fine size ladder, so CPU stays proportional to the number of peaks, not to the page.
    """
    import cv2
    import numpy as np
    coarse_thr = max(0.45, cfg["threshold"] - 0.15)
    peaks = []
    for size in _sizes(spec, cfg["coarse_ratio"]):
        t, _tb3, tb, _ok3, ok7 = _tpl(spec["template_id"], int(round(size * scale)), stroke, rot)
        if t.shape[0] < 8 or t.shape[1] < 8 or t.shape[0] >= ink.shape[0] or t.shape[1] >= ink.shape[1] or not ok7:
            continue
        res = np.nan_to_num(cv2.matchTemplate(ink_coarse, tb, cv2.TM_CCOEFF_NORMED), nan=0.0, posinf=0.0, neginf=0.0)
        # Only local maxima within about a third of the template are peaks. On dense drawings thousands of neighbouring positions pass
        # the threshold; comparing them one by one in Python was minutes of work per template for no extra information.
        k = max(3, min(t.shape) | 1)
        local_max = res >= cv2.dilate(res, np.ones((k, k), np.uint8))
        ys, xs = np.nonzero(local_max & (res >= coarse_thr))
        if len(ys) > PEAK_CAP:
            if stats is not None:
                stats["peak_cap"] = stats.get("peak_cap", 0) + 1
            keep = np.argpartition(-res[ys, xs], PEAK_CAP)[:PEAK_CAP]
            ys, xs = ys[keep], xs[keep]
        for y, x in zip(ys.tolist(), xs.tolist()):
            peaks.append((float(res[y, x]), size, x, y, t.shape[1], t.shape[0]))
    # only peaks that could still reach the threshold after refinement are worth the fine search
    refine_floor = max(coarse_thr, cfg["threshold"] - 0.10)
    peaks = [p for p in peaks if p[0] >= refine_floor]
    peaks.sort(key=lambda p: (-p[0], p[3], p[2], p[1]))
    taken: list[tuple[int, int, int, int, float]] = []
    out = []
    for _s, size, x, y, tw, th in peaks:
        cx, cy = x + tw / 2, y + th / 2
        # a stronger peak suppresses weaker ones at the same place AND similar size; a different size at the same place stays
        if any(abs(cx - (a + c / 2)) < c * 0.45 and abs(cy - (b + d / 2)) < d * 0.45 and 0.8 <= size / sz <= 1.25
               for a, b, c, d, sz in taken):
            continue
        taken.append((x, y, tw, th, size))
        if len(taken) > REFINE_CAP:
            if stats is not None:
                stats["peak_cap"] = stats.get("peak_cap", 0) + 1       # reported as PEAK_CAP: the strongest peaks were refined
            break
        padx, pady = int(tw * 0.35) + 4, int(th * 0.35) + 4
        wx0, wy0 = max(0, x - padx), max(0, y - pady)
        wx1, wy1 = min(ink_fine.shape[1], x + tw + padx), min(ink_fine.shape[0], y + th + pady)
        window = ink_fine[wy0:wy1, wx0:wx1]
        best = None
        for f in np.arange(0.84, 1.17, cfg["fine_step"]):
            fsize = size * float(f)
            t, tb, _tb7, ok3, _ok7 = _tpl(spec["template_id"], int(round(fsize * scale)), stroke, rot)
            if t.shape[0] >= window.shape[0] or t.shape[1] >= window.shape[1] or t.shape[0] < 8 or not ok3:
                continue
            res = np.nan_to_num(cv2.matchTemplate(window, tb, cv2.TM_CCOEFF_NORMED), copy=False, nan=0.0, posinf=0.0, neginf=0.0)
            my, mx = np.unravel_index(int(res.argmax()), res.shape)
            sc = float(res[my, mx])
            prec = _precision(ink_bin, t, wx0 + int(mx), wy0 + int(my)) if ink_bin is not None else 1.0
            if best is None or _rank(sc, prec) > _rank(best[0], best[6]):
                best = (sc, fsize, wx0 + int(mx), wy0 + int(my), t.shape[1], t.shape[0], prec)
        if best and best[0] >= cfg["threshold"]:
            out.append({"score": best[0], "size_pt": round(best[1], 2), "x": best[2], "y": best[3], "w": best[4], "h": best[5],
                        "precision": round(best[6], 4)})
    return out


def _sizes(spec: dict, ratio: float) -> tuple[float, ...]:
    """Geometric size ladder (points) covering the template's plausible range; finer ratio = more CPU, fewer missed sizes."""
    lo, hi = spec["size_range_pt"]
    out, v = [], lo
    while v < hi:
        out.append(round(v, 2))
        v *= ratio
    out.append(round(hi, 2))
    return tuple(out)


def detect_symbols(pdf_bytes: bytes, page_number: int, *, preset: str = "standard", families: tuple[str, ...] | None = None,
                   tile_px: int = 2400, overlap_px: int = 360, max_scale: float = 2.5, max_side_px: int = 10000, cancel=None,
                   progress=None) -> dict:
    """Find library symbols on one page. Returns candidates (proposals), a completeness record, and the parameters used."""
    import cv2
    import numpy as np
    import pypdfium2 as pdfium
    if preset not in PRESETS:
        raise ValueError(f"Unknown symbol preset {preset!r}")
    cfg = PRESETS[preset]
    fams = tuple(families or cfg["families"])
    pdf = pdfium.PdfDocument(pdf_bytes)
    if not 1 <= page_number <= len(pdf):
        raise ValueError("Page out of range")
    page = pdf[page_number - 1]
    w_pt, h_pt = page.get_size()
    scale = min(max_scale, max_side_px / max(w_pt, h_pt))
    width_px, height_px = int(ceil(w_pt * scale)), int(ceil(h_pt * scale))
    tiles = _tile_grid(width_px, height_px, tile_px, overlap_px)
    incomplete: list[dict] = []
    if len(tiles) > MAX_TILES:
        incomplete.append({"reason": "TILE_CAP", "tiles_total": len(tiles), "tiles_processed": MAX_TILES})
        tiles = tiles[:MAX_TILES]
    document_sha = hashlib.sha256(pdf_bytes).hexdigest()
    raw: list[dict] = []
    strokes: list[int] = []
    body_families = [f for f in fams if f != "ACTUATOR"]
    specs = [s for s in lib.LIBRARY.values() if s["graphical_family"] in body_families]
    tiles_done = 0
    peak_stats: dict = {}
    total_steps = max(1, len(tiles) * max(1, len(specs)))
    step = 0

    def tick(message: str) -> None:
        if progress is not None:
            progress(min(1.0, step / total_steps), message)
    for ti, (x0, y0, x1, y1) in enumerate(tiles):
        if cancel is not None:
            cancel.check()
        tick(f"tile {ti + 1} of {len(tiles)}")
        ink = 255 - _render_tile(page, w_pt, h_pt, scale, (x0, y0, x1, y1))
        if int((ink > 128).sum()) < 40:                     # essentially blank tile
            tiles_done += 1
            continue
        stroke = _stroke_px(ink > 128)
        strokes.append(stroke)
        ink_fine = cv2.GaussianBlur(ink, (3, 3), 0)
        ink_coarse = cv2.GaussianBlur(ink, (7, 7), 0)
        ink_bin = ink > 128
        for spec in specs:
            for rot in lib.rotations_for(spec["template_id"]):
                if cancel is not None:
                    cancel.check()
                for hit in _search(ink, ink_coarse, ink_fine, spec, rot, cfg, scale, stroke, ink_bin, peak_stats):
                    raw.append({"score": hit["score"], "precision": hit["precision"], "template_id": spec["template_id"], "rotation": rot, "size_pt": hit["size_pt"],
                                "box_px": (x0 + hit["x"], y0 + hit["y"], x0 + hit["x"] + hit["w"], y0 + hit["y"] + hit["h"]), "tile": (x0, y0)})
            step += 1
            tick(f"tile {ti + 1} of {len(tiles)}: {spec['shape_variant'].replace('_', ' ').lower()}")
        tiles_done += 1
    if peak_stats.get("peak_cap"):
        incomplete.append({"reason": "PEAK_CAP", "template_searches_capped": peak_stats["peak_cap"], "peak_cap": PEAK_CAP, "refine_cap": REFINE_CAP})
    candidates = _merge(raw, document_sha, page_number, width_px, height_px, scale)
    if len(candidates) > MAX_CANDIDATES_PER_PAGE:
        incomplete.append({"reason": "CANDIDATE_CAP", "found": len(candidates), "kept": MAX_CANDIDATES_PER_PAGE})
        candidates = candidates[:MAX_CANDIDATES_PER_PAGE]
    if "ACTUATOR" in fams:
        _add_actuators(pdf_bytes, page, w_pt, h_pt, scale, candidates, cfg, cancel)
    candidates.sort(key=lambda c: (c["bbox"]["y0"], c["bbox"]["x0"], c["id"]))
    status = "COMPLETE_CANDIDATES" if not incomplete else "PARTIAL"
    result = {"schema": "pid-reader-standalone-symbol-detect-v1", "version": VERSION, "page": page_number,
              "source_sha256": document_sha, "preset": preset, "families": list(fams), "render_scale": round(scale, 4),
              "stroke_px_per_tile": strokes, "tiles_total": len(_tile_grid(width_px, height_px, tile_px, overlap_px)), "tiles_processed": tiles_done,
              "status": status, "incomplete": incomplete, "score_kind": SCORE_KIND, "accept_score": ACCEPT_SCORE,
              "candidates": candidates,
              "limitations": ("Shape similarity to original library geometry, not recognition of plant items. A bow-tie drawn as a dimension "
                              "marker or a flange look-alike can still score as a valve; classes below the accept score are withheld.")}
    return result


def _merge(raw: list[dict], document_sha: str, page: int, width_px: int, height_px: int, scale: float) -> list[dict]:
    for r in raw:
        r["rank"] = _rank(r["score"], r.get("precision", 1.0))
    raw.sort(key=lambda r: (-r["rank"], r["box_px"][1], r["box_px"][0], r["template_id"], r["rotation"], r["size_pt"]))
    kept: list[dict] = []
    for r in raw:
        b = {"x0": r["box_px"][0], "y0": r["box_px"][1], "x1": r["box_px"][2], "y1": r["box_px"][3]}
        r["_b"] = b
        fam = lib.LIBRARY[r["template_id"]]["graphical_family"]
        if any(k["_fam"] == fam and k["template_id"] == r["template_id"] and _iou(k["_b"], b) > 0.35 for k in kept):
            continue
        r["_fam"] = fam
        kept.append(r)
    groups: list[list[dict]] = []
    for r in kept:                                   # kept is score-ordered: first member is the group's leader
        for g in groups:
            if g[0]["_fam"] == r["_fam"] and (_iou(g[0]["_b"], r["_b"]) > 0.45 or _contained(g[0]["_b"], r["_b"]) > 0.7):
                g.append(r)
                break
        else:
            groups.append([r])
    out = []
    for g in groups:
        lead = g[0]
        spec = lib.LIBRARY[lead["template_id"]]
        b = lead["_b"]
        nb = {"x0": round(b["x0"] / width_px, 6), "y0": round(b["y0"] / height_px, 6),
              "x1": round(min(1.0, b["x1"] / width_px), 6), "y1": round(min(1.0, b["y1"] / height_px), 6)}
        alts = [{"template_id": a["template_id"], "engineering_class": lib.LIBRARY[a["template_id"]]["engineering_class"],
                 "shape_variant": lib.LIBRARY[a["template_id"]]["shape_variant"], "raw_score": round(a["score"], 4),
                 "precision": round(a.get("precision", 1.0), 4)} for a in g[1:6]]
        runner = g[1]["rank"] if len(g) > 1 and lib.LIBRARY[g[1]["template_id"]]["engineering_class"] != spec["engineering_class"] else None
        if lead["score"] < ACCEPT_SCORE:
            eclass, status = "UNKNOWN", "WEAK_CLASS_WITHHELD"
        elif runner is not None and lead["rank"] - runner < AMBIGUITY_MARGIN:
            eclass, status = spec["engineering_class"], "AMBIGUOUS"
        else:
            eclass, status = spec["engineering_class"], "LEADING"
        ports = []
        bw, bh = nb["x1"] - nb["x0"], nb["y1"] - nb["y0"]
        for p in lib.rotated_ports(lead["template_id"], lead["rotation"]):
            ports.append({"kind": p["kind"], "x": round(nb["x0"] + p["x"] * bw, 6), "y": round(nb["y0"] + p["y"] * bh, 6), "angle": p["angle"]})
        cid = "sym-" + hashlib.sha256(json.dumps([document_sha, page, nb, lead["template_id"], lead["rotation"]], sort_keys=True).encode()).hexdigest()[:24]
        out.append({"id": cid, "page": page, "bbox": nb, "template_id": lead["template_id"],
                    "graphical_family": spec["graphical_family"], "shape_variant": spec["shape_variant"],
                    "engineering_class": eclass, "class_candidates": [spec["engineering_class"]] + list(spec.get("class_alternatives", [])),
                    "actuation": None, "function": spec["function"], "raw_score": round(lead["score"], 4), "precision": round(lead.get("precision", 1.0), 4), "score_kind": SCORE_KIND,
                    "confidence_status": status, "rotation": lead["rotation"], "size_pt": lead["size_pt"], "alternatives": alts,
                    "ports": ports, "review_state": "PROPOSED",
                    "evidence": {"producer": VERSION, "render_scale": round(scale, 4), "tile_origin_px": list(lead["tile"]),
                                 "truth_class": "STRUCTURALLY_DERIVED"}})
    return out


def _add_actuators(pdf_bytes, page, w_pt, h_pt, scale, candidates, cfg, cancel) -> None:
    """Look for actuator heads beside each valve body. Evidence is independent of the body class."""
    import cv2
    import numpy as np
    act_specs = [s for s in lib.LIBRARY.values() if s["graphical_family"] == "ACTUATOR"]
    full_w, full_h = int(ceil(w_pt * scale)), int(ceil(h_pt * scale))
    for cand in candidates:
        if cand["graphical_family"] != "VALVE":
            continue
        if cancel is not None:
            cancel.check()
        b = cand["bbox"]
        bx0, by0, bx1, by1 = b["x0"] * full_w, b["y0"] * full_h, b["x1"] * full_w, b["y1"] * full_h
        bw, bh = bx1 - bx0, by1 - by0
        reach = max(bw, bh) * 1.4
        horizontal = cand["rotation"] in (0, 180)
        sides = ([("above", 0, (bx0 - bw * .3, by0 - reach, bx1 + bw * .3, by0 + bh * .15)),
                  ("below", 180, (bx0 - bw * .3, by1 - bh * .15, bx1 + bw * .3, by1 + reach))] if horizontal else
                 [("right", 90, (bx1 - bw * .15, by0 - bh * .3, bx1 + reach, by1 + bh * .3)),
                  ("left", 270, (bx0 - reach, by0 - bh * .3, bx0 + bw * .15, by1 + bh * .3))])
        best = None
        alts = []
        for side, rot, (wx0, wy0, wx1, wy1) in sides:
            wx0, wy0 = max(0, int(wx0)), max(0, int(wy0))
            wx1, wy1 = min(full_w, int(ceil(wx1))), min(full_h, int(ceil(wy1)))
            if wx1 - wx0 < 12 or wy1 - wy0 < 12:
                continue
            ink = 255 - _render_tile(page, w_pt, h_pt, scale, (wx0, wy0, wx1, wy1))
            if int((ink > 128).sum()) < 20:
                continue
            blur = cv2.GaussianBlur(ink, (3, 3), 0)
            ink_bin_w = ink > 128
            stroke = _stroke_px(ink_bin_w)
            for spec in act_specs:
                for size in _sizes(spec, 1.09):
                    for score, x, y, tw, th in _match(blur, spec["template_id"], size, scale, stroke, rot, cfg["threshold"]):
                        t_raw = lib.render(spec["template_id"], int(round(size * scale)), stroke, rot)
                        prec = _precision(ink_bin_w, t_raw, x, y, pad=int(0.5 * t_raw.shape[1]))
                        hit = {"template_id": spec["template_id"], "actuation": spec["actuation"], "raw_score": round(score, 4), "side": side,
                               "precision": round(prec, 4), "rank": _rank(score, prec),
                               "bbox": {"x0": round((wx0 + x) / full_w, 6), "y0": round((wy0 + y) / full_h, 6),
                                        "x1": round(min(1.0, (wx0 + x + tw) / full_w), 6), "y1": round(min(1.0, (wy0 + y + th) / full_h), 6)}}
                        alts.append(hit)
                        if best is None or hit["rank"] > best["rank"]:
                            best = hit
        if best is None:
            continue
        seen = {}
        for h in sorted(alts, key=lambda a: -a["rank"]):
            seen.setdefault(h["actuation"], h)
        ranked = list(seen.values())
        cand["actuation"] = {"actuation": best["actuation"] if best["raw_score"] >= ACCEPT_SCORE else "UNKNOWN", "raw_score": best["raw_score"], "precision": best["precision"],
                             "score_kind": SCORE_KIND, "side": best["side"], "bbox": best["bbox"],
                             "alternatives": [{"actuation": h["actuation"], "raw_score": h["raw_score"]} for h in ranked[1:4]],
                             "evidence": {"producer": VERSION, "independent_of_body_class": True}}
        cand["ports"].append({"kind": "ACTUATOR_SIGNAL", "x": round((best["bbox"]["x0"] + best["bbox"]["x1"]) / 2, 6),
                              "y": round(best["bbox"]["y0"] if best["side"] == "above" else best["bbox"]["y1"] if best["side"] == "below"
                                         else (best["bbox"]["y0"] + best["bbox"]["y1"]) / 2, 6), "angle": {"above": 270, "below": 90, "right": 0, "left": 180}[best["side"]]})
