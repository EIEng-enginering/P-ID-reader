"""Teach-by-example: find shapes that look like one example the reviewer boxed on a drawing.

No training and no model files: the page is rendered locally, the boxed region becomes a template, and
normalised cross-correlation (OpenCV ``matchTemplate``) searches the page at a few scales and at the four
quarter-turn orientations. Peaks are de-duplicated by overlap. The result is a list of *proposals* (a
score is a similarity, not a probability); a reviewer accepts or rejects each one.

Limits (stated plainly): works on shapes that look alike at the same drawing scale (+-20 %); symbols with
changed line weight, mirrored forms or heavy overlap with other linework score lower; a very plain example
(a bare circle) matches every circle. It does not know what the symbol *is* - the label is the reviewer's.
"""
from __future__ import annotations

from math import ceil

from ..api import canonical_json, sha256_hex, stable_id

SCHEMA = "pid-reader-standalone-example-matches-v1"
ALGORITHM = "ncc-template-multiscale-rot90-0.1"
DEFAULT_THRESHOLD = 0.72
MAX_MATCHES = 500
MAX_PAGE_SIDE_PX = 4600
SCALES = (0.85, 0.92, 1.0, 1.08, 1.15)
ROTATIONS = (0, 90, 180, 270)


def _iou(a: dict, b: dict) -> float:
    ix = max(0.0, min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]))
    iy = max(0.0, min(a["y1"], b["y1"]) - max(a["y0"], b["y0"]))
    inter = ix * iy
    union = (a["x1"] - a["x0"]) * (a["y1"] - a["y0"]) + (b["x1"] - b["x0"]) * (b["y1"] - b["y0"]) - inter
    return inter / union if union > 0 else 0.0


def find_similar(pdf_bytes: bytes, page: int, example_bbox: dict, *, threshold: float = DEFAULT_THRESHOLD,
                 scales: tuple[float, ...] = SCALES, rotations: tuple[int, ...] = ROTATIONS,
                 max_matches: int = MAX_MATCHES, cancel=None) -> dict:
    """Search ``page`` (1-based) for look-alikes of the region ``example_bbox`` (normalised, top-left origin)."""
    import cv2
    import numpy as np
    import pypdfium2 as pdfium

    if not 0.3 <= threshold <= 0.99:
        raise ValueError("threshold must be between 0.30 and 0.99")
    b = example_bbox
    if not (0 <= b["x0"] < b["x1"] <= 1 and 0 <= b["y0"] < b["y1"] <= 1):
        raise ValueError("Example box must be inside the page")
    pdf = pdfium.PdfDocument(pdf_bytes)
    if not 1 <= page <= len(pdf):
        raise ValueError("Page out of range")
    pg = pdf[page - 1]
    w_pt, h_pt = pg.get_size()
    scale = min(4.0, MAX_PAGE_SIDE_PX / max(w_pt, h_pt))
    image = np.asarray(pg.render(scale=scale).to_pil().convert("L"))
    ih, iw = image.shape
    ink = 255 - image                                     # ink bright, paper dark: ink drives the correlation
    padx, pady = (b["x1"] - b["x0"]) * 0.06, (b["y1"] - b["y0"]) * 0.06
    x0, y0 = max(0, int((b["x0"] - padx) * iw)), max(0, int((b["y0"] - pady) * ih))
    x1, y1 = min(iw, ceil((b["x1"] + padx) * iw)), min(ih, ceil((b["y1"] + pady) * ih))
    template = ink[y0:y1, x0:x1]
    th, tw = template.shape
    if th < 10 or tw < 10:
        raise ValueError("Example box is too small to match (draw it larger)")
    if th > ih // 2 or tw > iw // 2:
        raise ValueError("Example box is too large (it should enclose one symbol)")
    if float(template.std()) < 10.0:
        raise ValueError("Example region is nearly blank; box a symbol with visible linework")

    found = []
    for rot in rotations:
        t_rot = np.rot90(template, k=rot // 90)
        for s in scales:
            if cancel is not None:
                cancel.check()
            t = cv2.resize(t_rot, (max(8, int(t_rot.shape[1] * s)), max(8, int(t_rot.shape[0] * s))),
                           interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
            if t.shape[0] >= ih or t.shape[1] >= iw or float(t.std()) < 1.0:
                continue
            res = cv2.matchTemplate(ink, t, cv2.TM_CCOEFF_NORMED)
            ys, xs = np.where(res >= threshold)
            for y, x in zip(ys.tolist(), xs.tolist()):
                found.append((float(res[y, x]), x, y, t.shape[1], t.shape[0], rot, s))
            if len(found) > 200000:                        # pathological (plain template): refuse rather than sort forever
                raise ValueError("Example matches too much of the page; choose a more distinctive symbol or raise the threshold")
    found.sort(key=lambda f: (-f[0], f[2], f[1], f[5]))
    boxes: list[dict] = []
    out = []
    example_norm = {"x0": x0 / iw, "y0": y0 / ih, "x1": x1 / iw, "y1": y1 / ih}
    for score, x, y, tw2, th2, rot, s in found:
        nb = {"x0": round(x / iw, 6), "y0": round(y / ih, 6), "x1": round(min(1.0, (x + tw2) / iw), 6),
              "y1": round(min(1.0, (y + th2) / ih), 6)}
        if _iou(nb, example_norm) > 0.5:
            continue                                        # the example itself
        if any(_iou(nb, k) > 0.3 for k in boxes):
            continue                                        # a stronger match already covers this place
        boxes.append(nb)
        out.append({"page": page, "bbox": nb, "score": round(score, 4), "rotation": rot, "scale": s})
        if len(out) >= max_matches:
            break
    for item in out:
        item["id"] = stable_id("exm", page, item["bbox"], item["rotation"], item["scale"])
    result = {"schema": SCHEMA, "algorithm": ALGORITHM, "page": page, "example_bbox": example_norm,
              "threshold": threshold, "scales": list(scales), "rotations": list(rotations), "render_scale": round(scale, 4),
              "matches": out,
              "limitations": "Similarity of drawn shapes at this scale, not recognition of what the symbol is. "
                             "Every match is a proposal for the reviewer."}
    result["result_sha256"] = sha256_hex(canonical_json(result).encode("utf-8"))
    return result
