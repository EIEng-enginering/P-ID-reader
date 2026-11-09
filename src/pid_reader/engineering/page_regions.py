"""Page and region classification (Rev X, WPU-02). Standalone; never changes the R1 reader.

Per page this separates how the content is encoded, because that decides how it must be read:

``NATIVE_TEXT``           the text layer carries the drawing's lettering
``VECTOR_OUTLINED_TEXT``  dense vector graphics but (almost) no text layer: lettering is probably drawn as outlines
``RASTER_SCAN``           the page is essentially an image
``HYBRID``                mixed evidence, for example a 40-word title block on a dense vector body (outlined-text suspicion)
``LOW_CONTENT``           nothing substantial to read
``UNKNOWN``               evidence does not fit any class

and finds layout regions (``DRAWING_AREA``, ``TITLE_BLOCK``, ``REVISION_TABLE``, ``NOTES``, ``TABLE``, ``LEGEND``,
``BORDER_GRID``). All boxes use the frozen R1 frame: MediaBox top-left, normalised 0..1, after CropBox/rotation mapping.
Regions are layout *proposals* from rule and text-block heuristics; heuristics are development defaults, not validated
thresholds. Raw polygons are kept even when a region is later excluded from the engineering graph.
"""
from __future__ import annotations

import hashlib
import json
from io import BytesIO
from statistics import median

PAGE_KINDS = ("NATIVE_TEXT", "VECTOR_OUTLINED_TEXT", "RASTER_SCAN", "HYBRID", "LOW_CONTENT", "UNKNOWN")
REGION_KINDS = ("DRAWING_AREA", "TITLE_BLOCK", "REVISION_TABLE", "NOTES", "TABLE", "LEGEND", "BORDER_GRID")
VERSION = "page-regions-v1"

# development defaults (versioned with VERSION; tune only on development data)
NATIVE_WORDS = 120            # enough text layer to treat the page as text-bearing
DENSE_GRAPHICS = 800          # strokes + curves + rects that make a sheet "dense vector"
RASTER_IMAGE_FRACTION = 0.5   # share of the page covered by images
LOW_CONTENT_GRAPHICS = 20
MAX_WORDS = 30000
TITLE_WORDS = {"DRAWING", "DWG", "TITLE", "SCALE", "SHEET", "DATE", "APPROVED", "DRAWN", "CHECKED", "REV", "REVISION",
               "PROJECT", "CLIENT", "SIZE", "NO.", "NUMBER", "STATUS", "ISSUED", "DESIGNED"}
REVISION_WORDS = {"REV", "REVISION", "REVISIONS", "DATE", "DESCRIPTION", "BY", "CHK", "APPR", "APP"}
NOTE_WORDS = {"NOTES", "NOTE:", "NOTES:", "HOLD", "HOLDS", "HOLDS:", "GENERAL"}
LEGEND_WORDS = {"LEGEND", "LEGEND:", "SYMBOLS", "ABBREVIATIONS", "SYMBOL"}


def _rid(source_sha: str, page: int, kind: str, bbox: dict) -> str:
    raw = json.dumps([source_sha, page, kind, bbox], sort_keys=True)
    return "reg-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _norm_box(x0, y0, x1, y1, w, h) -> dict:
    return {"x0": round(max(0.0, min(1.0, x0 / w)), 6), "y0": round(max(0.0, min(1.0, y0 / h)), 6),
            "x1": round(max(0.0, min(1.0, x1 / w)), 6), "y1": round(max(0.0, min(1.0, y1 / h)), 6)}


def profile_pages(pdf_bytes: bytes, pages: tuple[int, ...] | None = None) -> list[dict]:
    """Cheap per-page facts: counts, image coverage, words and long rules (all normalised)."""
    import pdfplumber
    from ..formats.page_coordinates import frame_from_pdfplumber
    out = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        chosen = tuple(range(1, len(pdf.pages) + 1)) if pages is None else tuple(pages)
        for number in chosen:
            page = pdf.pages[number - 1]
            w, h = float(page.width), float(page.height)
            frame = frame_from_pdfplumber(page)
            words = page.extract_words(x_tolerance=2, y_tolerance=3)[:MAX_WORDS]
            graphics = len(page.lines) + len(page.curves) + len(page.rects)
            image_area = 0.0
            for im in page.images:
                try:
                    image_area += max(0.0, float(im["x1"]) - float(im["x0"])) * max(0.0, float(im["bottom"]) - float(im["top"]))
                except (KeyError, TypeError, ValueError):
                    continue
            rules = []
            for seg in list(page.lines) + list(page.rects):
                x0, x1 = float(seg["x0"]), float(seg["x1"])
                top, bottom = float(seg["top"]), float(seg["bottom"])
                if abs(bottom - top) <= 1.5 and (x1 - x0) >= 0.03 * w:
                    rules.append(("H", _norm_box(x0, top, x1, bottom, w, h)))
                elif abs(x1 - x0) <= 1.5 and (bottom - top) >= 0.03 * h:
                    rules.append(("V", _norm_box(x0, top, x1, bottom, w, h)))
                if len(rules) >= 6000:
                    break
            out.append({
                "page": number, "frame": frame.as_metadata(), "width_pt": round(w, 3), "height_pt": round(h, 3),
                "word_count": len(words), "char_count": len(page.chars), "graphics_count": graphics,
                "line_count": len(page.lines), "curve_count": len(page.curves), "rect_count": len(page.rects),
                "image_count": len(page.images), "image_area_fraction": round(min(1.0, image_area / (w * h)), 4),
                "words": [{"text": str(t["text"]), "bbox": _norm_box(t["x0"], t["top"], t["x1"], t["bottom"], w, h)}
                          for t in words],
                "rules": [{"orientation": o, "bbox": b} for o, b in rules]})
    return out


def classify_page(profile: dict) -> dict:
    """Page encoding class with the evidence that led to it (never a quality claim)."""
    words, graphics = profile["word_count"], profile["graphics_count"]
    image_frac, images = profile["image_area_fraction"], profile["image_count"]
    evidence = {"words": words, "graphics": graphics, "images": images, "image_area_fraction": image_frac}
    if images and image_frac >= RASTER_IMAGE_FRACTION and words < 30 and graphics < DENSE_GRAPHICS:
        kind, reason = "RASTER_SCAN", "Page is mostly an image and has almost no text layer or vector drawing."
    elif words >= 30 and images and image_frac >= 0.15:
        kind, reason = "HYBRID", "Native text and substantial image area; image regions need separate reading."
    elif graphics >= DENSE_GRAPHICS and words < NATIVE_WORDS:
        if words == 0:
            kind, reason = "VECTOR_OUTLINED_TEXT", "Dense vector drawing with no text layer: lettering is probably outlined."
        else:
            kind, reason = "HYBRID", (f"Only {words} text-layer words on a dense vector body ({graphics} shapes): "
                                      "title block is native text, body lettering is probably outlined.")
            evidence["outlined_text_suspected"] = True
    elif words >= NATIVE_WORDS:
        kind, reason = "NATIVE_TEXT", "Text layer carries the page's lettering."
    elif words < 10 and graphics < LOW_CONTENT_GRAPHICS and not images:
        kind, reason = "LOW_CONTENT", "Almost nothing to read on this page."
    elif words or graphics:
        kind, reason = "NATIVE_TEXT" if words >= 30 else "UNKNOWN", "Small amount of content; encoding class is uncertain."
    else:
        kind, reason = "UNKNOWN", "No recognisable content."
    return {"kind": kind, "reason": reason, "evidence": evidence}


def _blocks(words: list[dict]) -> list[dict]:
    """Group words into text blocks (union-find over a spatial hash)."""
    if not words:
        return []
    heights = [w["bbox"]["y1"] - w["bbox"]["y0"] for w in words if w["bbox"]["y1"] > w["bbox"]["y0"]]
    hmed = median(heights) if heights else 0.01
    gap_x, gap_y = max(hmed * 2.5, 0.004), max(hmed * 1.6, 0.003)
    cell = max(gap_x, gap_y)
    parent = list(range(len(words)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    grid: dict[tuple[int, int], list[int]] = {}
    for i, wd in enumerate(words):
        b = wd["bbox"]
        for gx in range(int((b["x0"] - gap_x) / cell), int((b["x1"] + gap_x) / cell) + 1):
            for gy in range(int((b["y0"] - gap_y) / cell), int((b["y1"] + gap_y) / cell) + 1):
                for j in grid.get((gx, gy), ()):
                    c = words[j]["bbox"]
                    if b["x0"] - gap_x <= c["x1"] and c["x0"] - gap_x <= b["x1"] and \
                            b["y0"] - gap_y <= c["y1"] and c["y0"] - gap_y <= b["y1"]:
                        ri, rj = find(i), find(j)
                        if ri != rj:
                            parent[ri] = rj
        for gx in range(int(b["x0"] / cell), int(b["x1"] / cell) + 1):
            for gy in range(int(b["y0"] / cell), int(b["y1"] / cell) + 1):
                grid.setdefault((gx, gy), []).append(i)
    groups: dict[int, list[int]] = {}
    for i in range(len(words)):
        groups.setdefault(find(i), []).append(i)
    blocks = []
    for members in groups.values():
        ws = [words[i] for i in members]
        bb = {"x0": min(w["bbox"]["x0"] for w in ws), "y0": min(w["bbox"]["y0"] for w in ws),
              "x1": max(w["bbox"]["x1"] for w in ws), "y1": max(w["bbox"]["y1"] for w in ws)}
        ordered = sorted(ws, key=lambda w: (round(w["bbox"]["y0"], 3), w["bbox"]["x0"]))
        blocks.append({"bbox": bb, "words": [w["text"].upper() for w in ordered], "count": len(ws)})
    blocks.sort(key=lambda b: (b["bbox"]["y0"], b["bbox"]["x0"]))
    return blocks


def _rules_in(rules: list[dict], bb: dict, pad: float = 0.012) -> tuple[int, int, dict]:
    """Short ruling lines touching a text block (page-length border rules are ignored).

    Returns (horizontal count, vertical count, box covering the block and its ruling lines).
    """
    h = v = 0
    ext = dict(bb)
    for r in rules:
        b = r["bbox"]
        length = (b["x1"] - b["x0"]) if r["orientation"] == "H" else (b["y1"] - b["y0"])
        if length > 0.4:
            continue
        if b["x1"] >= bb["x0"] - pad and b["x0"] <= bb["x1"] + pad and b["y1"] >= bb["y0"] - pad and b["y0"] <= bb["y1"] + pad:
            if r["orientation"] == "H":
                h += 1
            else:
                v += 1
            ext = {"x0": min(ext["x0"], b["x0"]), "y0": min(ext["y0"], b["y0"]),
                   "x1": max(ext["x1"], b["x1"]), "y1": max(ext["y1"], b["y1"])}
    return h, v, ext


def _union(a: dict, b: dict) -> dict:
    return {"x0": min(a["x0"], b["x0"]), "y0": min(a["y0"], b["y0"]), "x1": max(a["x1"], b["x1"]), "y1": max(a["y1"], b["y1"])}


def _rule_grids(rules: list[dict], pad: float = 0.004) -> list[dict]:
    """Connected groups of short ruling lines that form a grid (at least 3 horizontal and 2 vertical)."""
    short = [r for r in rules if ((r["bbox"]["x1"] - r["bbox"]["x0"]) if r["orientation"] == "H"
                                  else (r["bbox"]["y1"] - r["bbox"]["y0"])) <= 0.4]
    parent = list(range(len(short)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i, a in enumerate(short):
        for j in range(i + 1, len(short)):
            b = short[j]["bbox"]
            ab = a["bbox"]
            if ab["x0"] - pad <= b["x1"] and b["x0"] - pad <= ab["x1"] and ab["y0"] - pad <= b["y1"] and b["y0"] - pad <= ab["y1"]:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj
    groups: dict[int, list[dict]] = {}
    for i, r in enumerate(short):
        groups.setdefault(find(i), []).append(r)
    grids = []
    for members in groups.values():
        h = sum(1 for r in members if r["orientation"] == "H")
        v = len(members) - h
        if h >= 3 and v >= 2:
            bb = members[0]["bbox"]
            for r in members[1:]:
                bb = _union(bb, r["bbox"])
            grids.append({"bbox": bb, "h": h, "v": v})
    grids.sort(key=lambda g: (g["bbox"]["y0"], g["bbox"]["x0"]))
    return grids


def segment_regions(profile: dict, source_sha: str = "") -> list[dict]:
    """Layout regions for one page. Every region keeps its raw bbox and the evidence that produced it."""
    page = profile["page"]
    words, rules = profile["words"], profile["rules"]
    regions: list[dict] = []

    def add(kind: str, bbox: dict, evidence: dict, label: str = "") -> dict:
        reg = {"region_id": _rid(source_sha, page, kind, bbox), "page": page, "kind": kind, "bbox": bbox,
               "label": label, "evidence": evidence, "producer": VERSION, "state": "PROPOSED"}
        regions.append(reg)
        return reg

    # border / grid: long rules hugging the page edge
    edge_h = [r for r in rules if r["orientation"] == "H" and (r["bbox"]["y0"] < 0.06 or r["bbox"]["y1"] > 0.94)
              and r["bbox"]["x1"] - r["bbox"]["x0"] > 0.5]
    edge_v = [r for r in rules if r["orientation"] == "V" and (r["bbox"]["x0"] < 0.06 or r["bbox"]["x1"] > 0.94)
              and r["bbox"]["y1"] - r["bbox"]["y0"] > 0.5]
    inner = {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
    if len(edge_h) >= 2 and len(edge_v) >= 2:
        inner = {"x0": min(r["bbox"]["x1"] for r in edge_v if r["bbox"]["x0"] < 0.06) if any(r["bbox"]["x0"] < 0.06 for r in edge_v) else 0.0,
                 "y0": max(r["bbox"]["y1"] for r in edge_h if r["bbox"]["y0"] < 0.06) if any(r["bbox"]["y0"] < 0.06 for r in edge_h) else 0.0,
                 "x1": min(r["bbox"]["x0"] for r in edge_v if r["bbox"]["x1"] > 0.94) if any(r["bbox"]["x1"] > 0.94 for r in edge_v) else 1.0,
                 "y1": min(r["bbox"]["y0"] for r in edge_h if r["bbox"]["y1"] > 0.94) if any(r["bbox"]["y1"] > 0.94 for r in edge_h) else 1.0}
        if inner["x0"] < inner["x1"] and inner["y0"] < inner["y1"]:
            add("BORDER_GRID", {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0},
                {"edge_rules_h": len(edge_h), "edge_rules_v": len(edge_v), "inner_box": inner,
                 "note": "polygon is the page; the drawing area is the inner box"})
        else:
            inner = {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}

    claimed: list[dict] = []
    blocks = [b for b in _blocks(words) if b["count"] >= 3]
    # title block: text blocks in the lower-right with title keywords
    title_parts = []
    for b in blocks:
        cx, cy = (b["bbox"]["x0"] + b["bbox"]["x1"]) / 2, (b["bbox"]["y0"] + b["bbox"]["y1"]) / 2
        hits = len(TITLE_WORDS & set(b["words"]))
        if cx > 0.5 and cy > 0.65 and hits >= 2:
            title_parts.append((b, hits))
    if title_parts:
        bb = title_parts[0][0]["bbox"]
        for b, _ in title_parts[1:]:
            bb = _union(bb, b["bbox"])
        add("TITLE_BLOCK", bb, {"keyword_hits": sum(h for _, h in title_parts), "blocks": len(title_parts)}, "title block")
        claimed.append(bb)
    for b in blocks:
        bb = b["bbox"]
        if any(bb["x0"] >= c["x0"] - 1e-6 and bb["x1"] <= c["x1"] + 1e-6 and bb["y0"] >= c["y0"] - 1e-6 and bb["y1"] <= c["y1"] + 1e-6 for c in claimed):
            continue
        ws = set(b["words"])
        head = set(b["words"][:6])
        hrules, vrules, ext = _rules_in(rules, bb)
        label = " ".join(b["words"][:4]).title()
        if LEGEND_WORDS & head:
            add("LEGEND", bb, {"keywords": sorted(LEGEND_WORDS & head)}, label)
        elif len(REVISION_WORDS & ws) >= 3 and {"REV", "REVISION", "REVISIONS"} & ws:
            bb = ext if (hrules >= 3 and vrules >= 2) else bb          # a ruled table is as big as its rules, not its words
            add("REVISION_TABLE", bb, {"keywords": sorted(REVISION_WORDS & ws), "rules": [hrules, vrules]}, "revision table")
        elif NOTE_WORDS & head:
            add("NOTES", bb, {"keywords": sorted(NOTE_WORDS & head)}, label)
        else:
            continue
        claimed.append(bb)

    for g in _rule_grids(rules):
        gb = g["bbox"]
        cx, cy = (gb["x0"] + gb["x1"]) / 2, (gb["y0"] + gb["y1"]) / 2
        if any(c["x0"] <= cx <= c["x1"] and c["y0"] <= cy <= c["y1"] for c in claimed):
            continue
        inside = [w for w in words if gb["x0"] <= (w["bbox"]["x0"] + w["bbox"]["x1"]) / 2 <= gb["x1"]
                  and gb["y0"] <= (w["bbox"]["y0"] + w["bbox"]["y1"]) / 2 <= gb["y1"]]
        above = [w for w in words if gb["x0"] - 0.01 <= w["bbox"]["x0"] <= gb["x1"] and gb["y0"] - 0.035 <= w["bbox"]["y1"] <= gb["y0"] + 0.002]
        label_words = sorted(above or inside[:3], key=lambda w: (round(w["bbox"]["y0"], 3), w["bbox"]["x0"]))
        box = _union(gb, {"x0": min([w["bbox"]["x0"] for w in above] + [gb["x0"]]), "y0": min([w["bbox"]["y0"] for w in above] + [gb["y0"]]),
                          "x1": gb["x1"], "y1": gb["y1"]})
        upper = {w["text"].upper() for w in inside}
        if len(REVISION_WORDS & upper) >= 3 and {"REV", "REVISION"} & upper:
            add("REVISION_TABLE", box, {"horizontal_rules": g["h"], "vertical_rules": g["v"], "keywords": sorted(REVISION_WORDS & upper),
                                        "grid_box": gb}, "revision table")
        else:
            add("TABLE", box, {"horizontal_rules": g["h"], "vertical_rules": g["v"], "words": len(inside) + len(above),
                               "grid_box": gb}, " ".join(w["text"] for w in label_words[:4]).title())
        claimed.append(box)

    add("DRAWING_AREA", inner,
        {"excluded_region_ids": [r["region_id"] for r in regions if r["kind"] in ("TITLE_BLOCK", "REVISION_TABLE", "NOTES", "TABLE", "LEGEND")],
         "note": "polygon is a rectangle; listed regions inside it are not drawing content"}, "drawing area")
    regions.sort(key=lambda r: (r["kind"] != "DRAWING_AREA", r["bbox"]["y0"], r["bbox"]["x0"], r["kind"]))
    return regions


def ocr_policy(classification: dict) -> dict:
    """What reading is required for this page encoding (a plan, not a result)."""
    kind = classification["kind"]
    table = {
        "NATIVE_TEXT": ("native", False, "Use the text layer; OCR only to re-read suspicious regions."),
        "VECTOR_OUTLINED_TEXT": ("ocr_tiles", True, "Lettering is outlined: tiled OCR of the drawing area is required."),
        "HYBRID": ("native_plus_ocr", True, "Title block is native; read the drawing area with tiled OCR."),
        "RASTER_SCAN": ("ocr_tiles", True, "Image page: tiled OCR is the only text source."),
        "LOW_CONTENT": ("none", False, "No reading needed unless the reviewer disagrees."),
        "UNKNOWN": ("ocr_tiles", True, "Encoding unclear: attempt OCR and report the outcome."),
    }
    mode, needs, note = table[kind]
    return {"mode": mode, "ocr_required": needs, "note": note}


def analyse_pages(pdf_bytes: bytes, pages: tuple[int, ...] | None = None, *, source_sha256: str = "",
                  profiles_out: dict | None = None) -> list[dict]:
    """Profile, classify and segment pages. Result is deterministic for identical bytes.

    ``profiles_out``: optional dict that receives ``{page: profile}`` (words and rules) for downstream stages.
    """
    source_sha256 = source_sha256 or hashlib.sha256(pdf_bytes).hexdigest()
    out = []
    for prof in profile_pages(pdf_bytes, pages):
        if profiles_out is not None:
            profiles_out[prof["page"]] = prof
        cls = classify_page(prof)
        out.append({"page": prof["page"], "frame": prof["frame"], "classification": cls["kind"], "reason": cls["reason"],
                    "evidence": cls["evidence"], "ocr_policy": ocr_policy(cls),
                    "counts": {k: prof[k] for k in ("word_count", "char_count", "graphics_count", "line_count",
                                                    "curve_count", "rect_count", "image_count")},
                    "regions": segment_regions(prof, source_sha256), "producer": VERSION})
    return out
