"""Junction dots and arrow heads on rendered/scanned pages (Rev X, WPU-08 raster part). Deterministic, tiled, bounded.

Thin lines are removed by a morphological opening sized from the sheet's stroke width; what survives are filled blobs. A roughly round blob that has
ink running out of it on three or more sides is a ``JUNCTION_DOT_CANDIDATE``; a filled triangle whose axis continues into a line is an
``ARROW_HEAD`` with a direction along that line; anything else is not reported as a mark. Hops are not attempted on raster (a scan cannot separate
a hop arc from a wobble), so raster crossings stay ``UNKNOWN_CROSSING`` at the network layer.

Proposals only. A dot supports "joined as drawn", an aligned arrow supports a direction as drawn; neither is a plant fact, and an arrow that
does not line up with a line gives ``UNKNOWN``.
"""
from __future__ import annotations

import hashlib
import json
from math import atan2, degrees, hypot, pi

from .symbol_detect import _render_tile, _stroke_px, _tile_grid

VERSION = "raster-marks-v1"
MAX_TILES = 64


def _mark_id(kind: str, *parts) -> str:
    return "rmk-" + hashlib.sha256(json.dumps([kind, *parts], sort_keys=True, default=str).encode("utf-8")).hexdigest()[:20]


def _ink_runs_toward(ink_bin, cx: float, cy: float, dx: float, dy: float, start: float, length: int) -> float:
    """Fraction of samples along a ray that are ink."""
    hits = n = 0
    h, w = ink_bin.shape
    for k in range(int(start), int(start) + length):
        x, y = int(round(cx + dx * k)), int(round(cy + dy * k))
        if not (0 <= x < w and 0 <= y < h):
            break
        n += 1
        hits += bool(ink_bin[max(0, y - 2):y + 3, max(0, x - 2):x + 3].any())          # tolerant of a few degrees of axis error
    return hits / n if n else 0.0


def detect_marks(pdf_bytes: bytes, page_number: int, *, tile_px: int = 2400, overlap_px: int = 200, max_scale: float = 2.5, max_side_px: int = 10000,
                 cancel=None) -> dict:
    """Dots and arrow heads on one page (rendered like a scan). Returns marks with page-normalised boxes."""
    import cv2
    import numpy as np
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(pdf_bytes)
    if not 1 <= page_number <= len(pdf):
        raise ValueError("Page out of range")
    page = pdf[page_number - 1]
    w_pt, h_pt = page.get_size()
    scale = min(max_scale, max_side_px / max(w_pt, h_pt))
    width_px, height_px = int(np.ceil(w_pt * scale)), int(np.ceil(h_pt * scale))
    tiles = _tile_grid(width_px, height_px, tile_px, overlap_px)
    incomplete = []
    if len(tiles) > MAX_TILES:
        incomplete.append({"reason": "TILE_CAP", "tiles_total": len(tiles), "tiles_processed": MAX_TILES})
        tiles = tiles[:MAX_TILES]
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    found: dict[tuple, dict] = {}
    for (x0, y0, x1, y1) in tiles:
        if cancel is not None:
            cancel.check()
        ink = 255 - _render_tile(page, w_pt, h_pt, scale, (x0, y0, x1, y1))
        binary = ink > 128
        if int(binary.sum()) < 40:
            continue
        stroke = _stroke_px(binary)
        k = max(3, 2 * stroke + 1)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        blobs = cv2.morphologyEx(binary.astype(np.uint8) * 255, cv2.MORPH_OPEN, kernel)
        n, labels, stats, cents = cv2.connectedComponentsWithStats(blobs, connectivity=8)
        for i in range(1, n):
            bx, by, bw, bh, area = (int(v) for v in stats[i])
            if area < 3 * stroke * stroke or max(bw, bh) > 14 * stroke or max(bw, bh) < 2 * stroke:
                continue
            comp = (labels[by:by + bh, bx:bx + bw] == i).astype(np.uint8)
            contours, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                continue
            cnt = max(contours, key=cv2.contourArea)
            peri = cv2.arcLength(cnt, True)
            carea = cv2.contourArea(cnt)
            if peri <= 0 or carea <= 0:
                continue
            approx = cv2.approxPolyDP(cnt, 0.12 * peri, True)
            circ = 4 * pi * carea / (peri * peri)
            lcx, lcy = float(cents[i][0]), float(cents[i][1])             # centroid in tile coordinates
            nb = {"x0": round(max(0.0, (x0 + bx) / width_px), 6), "y0": round(max(0.0, (y0 + by) / height_px), 6),
                  "x1": round(min(1.0, (x0 + bx + bw) / width_px), 6), "y1": round(min(1.0, (y0 + by + bh) / height_px), 6)}
            radius = max(bw, bh) / 2 + 2 * stroke
            if len(approx) == 3 and circ < 0.72:
                pts = [tuple(p[0]) for p in approx]
                sides = sorted((hypot(pts[a][0] - pts[(a + 1) % 3][0], pts[a][1] - pts[(a + 1) % 3][1]), a) for a in range(3))
                base_i = sides[0][1]
                b0, b1, apex = pts[base_i], pts[(base_i + 1) % 3], pts[(base_i + 2) % 3]
                mid = ((b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2)
                axis = (apex[0] - mid[0], apex[1] - mid[1])
                ln = hypot(*axis)
                if ln < 1 or abs(sides[1][0] - sides[2][0]) > 0.3 * max(sides[1][0], sides[2][0]):
                    continue
                ux, uy = axis[0] / ln, axis[1] / ln
                gmx, gmy = x0 + bx + mid[0], y0 + by + mid[1]
                behind = _ink_runs_toward(binary, mid[0] + bx, mid[1] + by, -ux, -uy, 2, int(4 * ln))
                ahead = _ink_runs_toward(binary, apex[0] + bx, apex[1] + by, ux, uy, 2, int(2 * ln))
                aligned = max(behind, ahead) >= 0.7
                key = ("ARROW", round(gmx / 6), round(gmy / 6))
                found.setdefault(key, {"id": _mark_id("ARROW", sha, page_number, nb), "kind": "ARROW_HEAD", "page": page_number, "bbox": nb,
                                       "direction": "ALONG_DRAWN_LINE" if aligned else "UNKNOWN",
                                       "vector": [round(float(ux), 4), round(float(uy), 4)] if aligned else None,
                                       "evidence": {"ink_behind_base": round(behind, 2), "ink_ahead_of_apex": round(ahead, 2)}, "review_state": "PROPOSED"})
            elif circ >= 0.72 and 0.7 <= bw / bh <= 1.4:
                arms = 0
                for a in range(8):
                    ang = a * pi / 4
                    if _ink_runs_toward(binary, lcx, lcy, float(np.cos(ang)), float(np.sin(ang)), radius, int(4 * stroke + 6)) >= 0.75:
                        arms += 1
                if arms >= 3:
                    key = ("DOT", round((x0 + lcx) / 6), round((y0 + lcy) / 6))
                    found.setdefault(key, {"id": _mark_id("DOT", sha, page_number, nb), "kind": "JUNCTION_DOT_CANDIDATE", "page": page_number, "bbox": nb,
                                           "arms": arms, "status": "SUPPORTS_JOINED_AS_DRAWN", "review_state": "PROPOSED",
                                           "evidence": {"circularity": round(circ, 2), "diameter_px": int(max(bw, bh))}})
    marks = sorted(found.values(), key=lambda m: (m["bbox"]["y0"], m["bbox"]["x0"], m["id"]))
    return {"schema": "pid-reader-standalone-raster-marks-v1", "version": VERSION, "page": page_number, "source_sha256": sha, "render_scale": round(scale, 4),
            "status": "COMPLETE_CANDIDATES" if not incomplete else "PARTIAL", "incomplete": incomplete, "marks": marks,
            "counts": {"dots": sum(m["kind"] == "JUNCTION_DOT_CANDIDATE" for m in marks), "arrows": sum(m["kind"] == "ARROW_HEAD" for m in marks)},
            "limitations": "Raster hops are not detected; a dot or arrow is a drawn mark, never proof of connection or flow."}
