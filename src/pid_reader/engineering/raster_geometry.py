"""Offline, evidence-only raster line, filled and outlined glyph observations.

This is a standalone inference layer. Rendering a PDF does not establish
physical piping topology, valve function or correct engineering interpretation.
No changes are made to the frozen Worksheet R1 extraction/worker contract.

OpenCV and numpy are OPTIONAL dependencies under the `raster` extra. The input
is rendered locally by PDFium, never sent to an external recognition service.
"""
from __future__ import annotations

from io import BytesIO
from importlib import metadata
from math import atan2, ceil, degrees, hypot, isfinite
from typing import Any

from ..api import CancelToken, LimitExceeded, RefusedInput, canonical_json, sha256_hex, stable_id


def _hough_rows(lines) -> list[list[int]]:
    """Rows [x1, y1, x2, y2] from cv2.HoughLinesP: OpenCV 4 returns shape (N,1,4), OpenCV 5 returns (N,4)."""
    if lines is None:
        return []
    import numpy as np
    return np.asarray(lines).reshape(-1, 4).tolist()

SCHEMA_V1 = "pid-reader-standalone-raster-geometry-v1"
ALGORITHM_V1 = "offline-raster-lines-filled-bowtie-0.1"
SCHEMA = "pid-reader-standalone-raster-geometry-v2"
ALGORITHM = "offline-raster-lines-filled-and-outlined-bowtie-0.2"
MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_PAGES = 12
MAX_PIXELS = 8_000_000
MAX_STROKES = 7000
MAX_FILLED_VALVES = 750
MAX_OUTLINED_VALVES = 750
MAX_JSON_BYTES = 8 * 1024 * 1024
TILE = 1200
OVERLAP = 100


def _dependencies():
    try:
        import cv2
        import numpy as np
        import pypdfium2 as pdfium
        import pdfplumber
        return cv2, np, pdfium, pdfplumber
    except ImportError as exc:
        raise RuntimeError("Raster analysis needs optional raster dependencies: pip install -e '.[raster]'") from exc


def raster_available() -> bool:
    try:
        _dependencies()
        return True
    except RuntimeError:
        return False


def _normalised_point(point: tuple[int, int], width: int, height: int, frame) -> list[float]:
    x, y = frame.render_to_media(min(1., max(0., point[0] / width)),
                                 min(1., max(0., point[1] / height)))
    return [round(x, 7), round(y, 7)]


def _normalised_box(box: tuple[int, int, int, int], width: int, height: int, frame) -> dict:
    """Correct media normalized bounding box after CropBox and 90-degree rotation."""
    x0,y0,x1,y1=box
    corners=[_normalised_point((x,y),width,height,frame) for x in (x0,x1) for y in (y0,y1)]
    return {"x0":min(x for x,_ in corners),"y0":min(y for _,y in corners),
            "x1":max(x for x,_ in corners),"y1":max(y for _,y in corners)}


def _raster_strokes(ink, cv2, *, cancel: CancelToken | None = None):
    """Return bounded pixel strokes from overlapping tiles, no pipe inference.

    The minimum length rejects most font stems; shapes shorter than this are
    NOT covered by this line detector. Overlapping Hough observations are
    deterministically deduplicated but may remain parallel on thick ink.
    """
    height, width = ink.shape
    step = TILE - OVERLAP
    raw = []
    for top in range(0, height, step):
        if cancel: cancel.check()
        if top >= height: break
        for left in range(0, width, step):
            tile = ink[top:min(height, top + TILE), left:min(width, left + TILE)]
            if tile.shape[0] < 3 or tile.shape[1] < 3:
                continue
            # Extract line-like structures while suppressing most character ink.
            horizontal = cv2.morphologyEx(tile, cv2.MORPH_OPEN,
                        cv2.getStructuringElement(cv2.MORPH_RECT, (23, 1)))
            vertical = cv2.morphologyEx(tile, cv2.MORPH_OPEN,
                        cv2.getStructuringElement(cv2.MORPH_RECT, (1, 23)))
            signal = cv2.bitwise_or(horizontal, vertical)
            detected = cv2.HoughLinesP(signal, 1, 3.141592653589793 / 180,
                                       threshold=22, minLineLength=34, maxLineGap=3)
            # Sparse long diagonal strokes are also useful engineering
            # observations; they are NOT classified as pipes or connections.
            # The 60 px limit intentionally suppresses typical CAD glyph
            # edges and small text stems.
            sloping = cv2.HoughLinesP(tile, 1, 3.141592653589793 / 180,
                                      threshold=35, minLineLength=60, maxLineGap=3)
            if sloping is not None:
                for x1, y1, x2, y2 in _hough_rows(sloping):
                    dx, dy = abs(x2-x1), abs(y2-y1)
                    if min(dx,dy) >= .23 * max(dx,dy) and hypot(dx,dy) >= 60:
                        raw.append((min((x1+left,y1+top),(x2+left,y2+top)),
                                    max((x1+left,y1+top),(x2+left,y2+top))))
                        if len(raw) > MAX_STROKES * 6:
                            raise LimitExceeded("PID_LIMIT_RASTER", "Raster tile observations exceed safe processing budget")
            if detected is not None:
                for line in _hough_rows(detected):
                    x1, y1, x2, y2 = map(int, line)
                    a = (x1 + left, y1 + top)
                    b = (x2 + left, y2 + top)
                    if hypot(b[0] - a[0], b[1] - a[1]) >= 34:
                        raw.append((min(a, b), max(a, b)))
                    if len(raw) > MAX_STROKES * 6:
                        raise LimitExceeded("PID_LIMIT_RASTER", "Raster tile observations exceed safe processing budget")
            if left + TILE >= width: break
        if top + TILE >= height: break
    # Deduplicate tile overlaps and near-identical Hough segments. Never join
    # separate strokes across a physical gap; that requires engineering review.
    result = []
    seen = set()
    for a, b in sorted(raw):
        # Quantized endpoints only dedupe near-identical observations (<=2 px).
        key = (round(a[0] / 3), round(a[1] / 3), round(b[0] / 3), round(b[1] / 3))
        if key in seen:
            continue
        seen.add(key)
        result.append((a, b))
        if len(result) > MAX_STROKES:
            raise LimitExceeded("PID_LIMIT_RASTER", "Too many raster stroke observations; no partial result returned")
    return result


def _triangles(ink, cv2):
    """Return isolated, dense filled triangles with a well-defined base and tip.

    A morphological opening drops thin lines and separates triangles touching
    only at a narrow tip; an isolated arrowhead is NOT a valve.
    """
    cleaned = cv2.morphologyEx(ink, cv2.MORPH_OPEN,
                               cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    triangles = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 65 or area > 18000:
            continue
        x, y, width, height = cv2.boundingRect(contour)
        if min(width, height) < 11 or max(width, height) > 220:
            continue
        if area / (width * height) < .30 or area / (width * height) > .72:
            continue
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, .055 * perimeter, True)
        if len(approx) != 3:
            continue
        points = [tuple(int(v) for v in p[0]) for p in approx]
        for axis in ("HORIZONTAL_AXIS", "VERTICAL_AXIS"):
            for direction in (-1, 1):
                # Positive direction: apex at increasing coordinate.
                ai = 0 if axis == "HORIZONTAL_AXIS" else 1
                sorted_pts = sorted(points, key=lambda p: p[ai])
                tip = sorted_pts[-1] if direction == 1 else sorted_pts[0]
                base = sorted_pts[:2] if direction == 1 else sorted_pts[1:]
                orth = 1 - ai
                if abs(base[0][ai] - base[1][ai]) > 4:
                    continue
                tip_span = abs(tip[ai] - (base[0][ai] + base[1][ai]) / 2)
                base_span = abs(base[0][orth] - base[1][orth])
                mid_orth = (base[0][orth] + base[1][orth]) / 2
                if not (8 <= tip_span <= 180 and 12 <= base_span <= 220):
                    continue
                if not (.35 <= tip_span / base_span <= 2.2):
                    continue
                if abs(tip[orth] - mid_orth) > max(4., .16 * base_span):
                    continue
                triangles.append({"axis": axis, "direction": direction, "tip": tip,
                                  "base_mid": ((base[0][0] + base[1][0]) / 2,
                                               (base[0][1] + base[1][1]) / 2),
                                  "base_span": base_span, "bbox": (x, y, x + width, y + height)})
                break
    return triangles


def _filled_bowties(ink, cv2):
    triangles = _triangles(ink, cv2)
    candidates = []
    triangle_pair_count = [0] * len(triangles)
    for i, first in enumerate(triangles):
        for j in range(i + 1, len(triangles)):
            second = triangles[j]
            if first["axis"] != second["axis"] or first["direction"] == second["direction"]:
                continue
            distance = hypot(first["tip"][0] - second["tip"][0],
                             first["tip"][1] - second["tip"][1])
            scale = max(first["base_span"], second["base_span"])
            if distance > max(5, .12 * scale):
                continue
            if abs(first["base_span"] - second["base_span"]) > .25 * scale:
                continue
            a = first["base_mid"]; b = second["base_mid"]
            axis = first["axis"]
            ai = 0 if axis == "HORIZONTAL_AXIS" else 1
            if abs(a[1-ai] - b[1-ai]) > max(4, .15 * scale):
                continue
            # Base centres must lie on OPPOSITE sides of their shared tip.
            mid = (first["tip"][ai] + second["tip"][ai]) / 2
            if (a[ai] - mid) * (b[ai] - mid) >= 0:
                continue
            x0 = min(first["bbox"][0], second["bbox"][0])
            y0 = min(first["bbox"][1], second["bbox"][1])
            x1 = max(first["bbox"][2], second["bbox"][2])
            y1 = max(first["bbox"][3], second["bbox"][3])
            candidates.append({"bbox_px": (x0, y0, x1, y1),
                               "centre_px": (round((first["tip"][0] + second["tip"][0]) / 2),
                                             round((first["tip"][1] + second["tip"][1]) / 2)),
                               "orientation": axis,
                               "evidence": "TWO_FILLED_TRIANGLES_WITH_OPPOSING_APICES"})
            triangle_pair_count[i] += 1
            triangle_pair_count[j] += 1
            candidates[-1]["triangle_indices"] = (i,j)
    # Multiple possible pairings for the same triangle are ambiguous.
    boxes = {}
    for c in candidates:
        i,j = c.pop("triangle_indices")
        if triangle_pair_count[i] != 1 or triangle_pair_count[j] != 1:
            continue  # ambiguous multi-pair matches must not become proposals
        key = c["bbox_px"]
        boxes[key] = c
    if len(boxes) > MAX_FILLED_VALVES:
        raise LimitExceeded("PID_LIMIT_RASTER", "Filled glyph proposal budget exceeded")
    return [boxes[k] for k in sorted(boxes)]


def analyze_raster_geometry(pdf_bytes: bytes, *, pages: tuple[int, ...] | None = None,
                            dpi: int = 144, max_pixels: int = MAX_PIXELS,
                            cancel: CancelToken | None = None) -> dict:
    """Produce deterministic, source-backed raster hypotheses on selected PDF pages.

    All coordinates use the SAME normalized MediaBox frame as native PDF/OCR.
    No connection between any strokes is asserted by this function.
    """
    cv2, np, pdfium, pdfplumber = _dependencies()
    from ..formats.page_coordinates import frame_from_pdfplumber
    if not isinstance(pdf_bytes, bytes) or not pdf_bytes.startswith(b"%PDF-"):
        raise RefusedInput("PID_MALFORMED", "Raster analysis expects PDF bytes")
    if len(pdf_bytes) > MAX_INPUT_BYTES:
        raise LimitExceeded("PID_LIMIT_BYTES", "Raster PDF exceeds 16 MiB")
    if type(dpi) is not int or not 72 <= dpi <= 240:
        raise RefusedInput("PID_BAD_PARAMETER", "Raster DPI must be an integer between 72 and 240")
    if type(max_pixels) is not int or not 1 <= max_pixels <= MAX_PIXELS:
        raise RefusedInput("PID_BAD_PARAMETER", "Invalid raster pixel budget")
    try:
        pdf = pdfium.PdfDocument(pdf_bytes)
        count = len(pdf)
        if not 1 <= count <= 500:
            raise LimitExceeded("PID_LIMIT_PAGES", "Invalid or excessive PDF page count")
        chosen = tuple(range(1, count + 1)) if pages is None else tuple(pages)
        if (not chosen or len(chosen) > MAX_PAGES or len(set(chosen)) != len(chosen)
                or any(type(n) is not int or not 1 <= n <= count for n in chosen)):
            raise RefusedInput("PID_BAD_PARAMETER", "Select 1-12 unique valid raster pages")
        source_sha = sha256_hex(pdf_bytes)
        result = {"schema": SCHEMA, "algorithm": ALGORITHM, "source_sha256": source_sha,
                  "page_count": count, "selected_pages": list(chosen), "dpi": dpi,
                  "engine_versions": {"opencv": cv2.__version__, "numpy": np.__version__,
                                      "pypdfium2": metadata.version("pypdfium2")},
                  "coordinate_frame": "PDFPLUMBER_MEDIA_NORMALIZED_V1", "page_frames": [],
                  "stroke_candidates": [], "filled_valve_candidates": [],
                  "outline_valve_candidates": [], "warnings": [],
                  "disclaimer": "Raster observations only; no valve type, service, process or physical connectivity is confirmed."}
        with pdfplumber.open(BytesIO(pdf_bytes)) as inspected:
            frames = {n: frame_from_pdfplumber(inspected.pages[n-1]) for n in chosen}
        for n in chosen:
            if cancel: cancel.check()
            page = pdf[n - 1]
            width_pt, height_pt = page.get_size()
            frame = frames[n]
            if abs(width_pt - frame.crop_width) > .5 or abs(height_pt - frame.crop_height) > .5:
                raise RefusedInput("PID_BAD_PARAMETER", "PDFium/pdfplumber page frames disagree")
            scale = dpi / 72
            px_w = ceil(width_pt * scale); px_h = ceil(height_pt * scale)
            if px_w * px_h > max_pixels:
                # Reduce locally to stay within a fixed memory budget. Do not
                # silently assume unchanged recognition coverage after scaling.
                scale = min(scale, (max_pixels / (width_pt * height_pt)) ** .5 * .97)
                if scale < 1.0:
                    raise LimitExceeded("PID_LIMIT_RASTER", "Page cannot fit raster budget even at 72 DPI")
                result["warnings"].append({"page": n,"code":"DOWNSCALED_RENDER",
                    "message":"Rendering resolution reduced; small glyphs may be missed."})
            image = page.render(scale=scale).to_pil().convert("L")
            pixels = np.asarray(image)
            # Otsu is stable on mixed-raster PDF pages; reject background inversions
            # to avoid treating the whole page as dark foreground.
            _, ink = cv2.threshold(pixels, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            dark = cv2.countNonZero(ink) / ink.size
            if dark > .38:
                raise RefusedInput("PID_UNSUPPORTED_RASTER", "Dark-background or excessively noisy page refused")
            result["page_frames"].append({"page": n, "transform": frame.as_metadata(),
                                          "width_px": int(image.width), "height_px": int(image.height),
                                          "dark_fraction": round(float(dark), 6),
                                          "render_dpi": round(scale * 72, 3)})
            if dark < .0001:
                result["warnings"].append({"page": n, "code": "NO_RASTER_INK"})
                continue
            lines = _raster_strokes(ink, cv2, cancel=cancel)
            for start, end in lines:
                a = _normalised_point(start, image.width, image.height, frame)
                b = _normalised_point(end, image.width, image.height, frame)
                sid = stable_id("raster-stroke", source_sha, n, a, b, ALGORITHM)
                result["stroke_candidates"].append({"id": sid, "page": n, "endpoints": [a, b],
                    "status": "PROPOSED_UNVERIFIED", "role": "RASTER_LINEWORK_UNKNOWN",
                    "limitations": "Pixel stroke may be piping, annotation, border or equipment outline; not a confirmed process connection."})
                if len(result["stroke_candidates"]) > MAX_STROKES:
                    raise LimitExceeded("PID_LIMIT_RASTER", "Raster segment result budget exceeded")
            for shape in _filled_bowties(ink, cv2):
                x0, y0, x1, y1 = shape["bbox_px"]
                center = _normalised_point(shape["centre_px"], image.width, image.height, frame)
                bbox = _normalised_box((x0,y0,x1,y1),image.width,image.height,frame)
                cid = stable_id("raster-filled-valve", source_sha, n, bbox, shape["orientation"], ALGORITHM)
                result["filled_valve_candidates"].append({"id": cid, "page": n, "bbox": bbox,
                    "centre": center, "orientation": shape["orientation"],
                    "kind": "FILLED_BOWTIE_VALVE_GLYPH_CANDIDATE",
                    "evidence": shape["evidence"], "status": "PROPOSED_UNVERIFIED",
                    "limitations": "Paired filled triangles only; not a confirmed valve, valve type or process connection."})
                if len(result["filled_valve_candidates"]) > MAX_FILLED_VALVES:
                    raise LimitExceeded("PID_LIMIT_RASTER", "Raster filled-valve result budget exceeded")
            # Outlined bowties use separate end-base and diagonal evidence.
            # They do not become connected pipes or engineering valve types.
            from .raster_outlines import find_outline_valves
            outlines, outline_warnings = find_outline_valves(ink, cv2, np, cancel=cancel)
            for warning in outline_warnings:
                result["warnings"].append({"page": n, "code": warning.split("_HORIZONTAL_AXIS")[0].split("_VERTICAL_AXIS")[0],
                                            "message": warning})
            for shape in outlines:
                x0, y0, x1, y1 = shape["bbox_px"]
                center = _normalised_point(shape["centre_px"],image.width,image.height,frame)
                bbox = _normalised_box((x0,y0,x1,y1),image.width,image.height,frame)
                oid = stable_id("raster-outline-valve",source_sha,n,bbox,shape["orientation"],shape["style"],ALGORITHM)
                result["outline_valve_candidates"].append({"id":oid,"page":n,"bbox":bbox,
                    "centre":center,"orientation":shape["orientation"],
                    "kind":"OUTLINED_BOWTIE_VALVE_GLYPH_CANDIDATE",
                    "style":shape["style"],"evidence":shape["evidence"],
                    "status":"PROPOSED_UNVERIFIED",
                    "limitations":"Outlined geometric pattern only; not a confirmed valve, globe type, piping connection or complete drawing survey."})
                if len(result["outline_valve_candidates"])>MAX_OUTLINED_VALVES:
                    raise LimitExceeded("PID_LIMIT_RASTER", "Raster outlined-valve result budget exceeded")
        for key in ("stroke_candidates", "filled_valve_candidates", "outline_valve_candidates"):
            result[key].sort(key=lambda c: (c["page"], c["id"]))
        result["result_sha256"] = sha256_hex(canonical_json(result).encode("utf-8"))
        if len(canonical_json(result).encode("utf-8")) > MAX_JSON_BYTES:
            raise LimitExceeded("PID_LIMIT_RASTER", "Raster analysis result exceeds 8 MiB")
        return result
    except (RefusedInput, LimitExceeded):
        raise
    except Exception as exc:
        raise RefusedInput("PID_MALFORMED", "Raster PDF rendering or geometry analysis failed") from exc


def validate_raster_result(result: dict, pdf_bytes: bytes | None = None) -> list[str]:
    """Structural and source/frame validation, not a digital authenticity signature."""
    errors = []
    if not isinstance(result, dict):
        return ["Raster result must be an object"]
    try:
        body = {k: v for k, v in result.items() if k != "result_sha256"}
        if sha256_hex(canonical_json(body).encode("utf-8")) != result.get("result_sha256"):
            errors.append("Raster result content hash mismatch")
    except (TypeError, ValueError):
        return ["Malformed raster JSON"]
    version = result.get("schema")
    if (version == SCHEMA and result.get("algorithm") == ALGORITHM):
        algorithm = ALGORITHM
    elif (version == SCHEMA_V1 and result.get("algorithm") == ALGORITHM_V1):
        algorithm = ALGORITHM_V1
    else:
        errors.append("Unsupported raster version")
        algorithm = str(result.get("algorithm"))
    if pdf_bytes is not None and result.get("source_sha256") != sha256_hex(pdf_bytes):
        errors.append("Raster PDF source hash mismatch")
    frame_by_page = {}
    try:
        if pdf_bytes is not None:
            from ..formats.page_coordinates import frame_from_pdfplumber
            import pdfplumber
            with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
                if result.get("page_count") != len(pdf.pages):
                    errors.append("Raster page count mismatch")
                frame_by_page = {p: frame_from_pdfplumber(pdf.pages[p - 1]).as_metadata()
                                 for p in result.get("selected_pages", [])}
        selected = result["selected_pages"]
        if (not isinstance(selected, list) or len(selected) > MAX_PAGES or not selected
                or len(set(selected)) != len(selected)
                or any(type(p) is not int or p < 1 or p > result["page_count"] for p in selected)):
            errors.append("Invalid selected raster pages")
        frames = result["page_frames"]
        if len(frames) != len(selected) or {x["page"] for x in frames} != set(selected):
            errors.append("Incomplete raster source transforms")
        for frame in frames:
            if frame_by_page and frame["transform"] != frame_by_page[frame["page"]]:
                errors.append("Raster-to-PDF coordinate transform changed")
        ids = set()
        for key, limit in (("stroke_candidates", MAX_STROKES),
                           ("filled_valve_candidates", MAX_FILLED_VALVES)) + (
                           (("outline_valve_candidates", MAX_OUTLINED_VALVES),) if version == SCHEMA else ()):
            if len(result[key]) > limit:
                errors.append("Raster candidate count over limit")
            for row in result[key]:
                if row["id"] in ids:
                    errors.append("Duplicate raster candidate ID")
                ids.add(row["id"])
                if row["page"] not in selected or row.get("status") != "PROPOSED_UNVERIFIED":
                    errors.append("Invalid raster candidate source or status")
                coords = row.get("endpoints") if key == "stroke_candidates" else [
                    [row["bbox"]["x0"], row["bbox"]["y0"]], [row["bbox"]["x1"], row["bbox"]["y1"]]]
                if key != "stroke_candidates" and version == SCHEMA:
                    bb=row["bbox"]
                    if bb["x0"] >= bb["x1"] or bb["y0"] >= bb["y1"]:
                        errors.append("Invalid raster glyph bounding box order")
                for point in coords:
                    if (len(point) != 2 or any(type(c) not in (int, float) or not isfinite(c)
                                             or c < 0 or c > 1 for c in point)):
                        errors.append("Invalid raster candidate coordinates")
        if type(result.get("dpi")) is not int or not 72 <= result["dpi"] <= 240:
            errors.append("Invalid raster DPI")
        for row in result["stroke_candidates"]:
            a,b = row["endpoints"]
            expected = stable_id("raster-stroke", result["source_sha256"], row["page"], a, b, algorithm)
            if row["id"] != expected or row.get("role") != "RASTER_LINEWORK_UNKNOWN":
                errors.append("Raster stroke identity or role differs from source claim")
        for row in result["filled_valve_candidates"]:
            expected = stable_id("raster-filled-valve", result["source_sha256"], row["page"],
                                 row["bbox"], row["orientation"], algorithm)
            if row["id"] != expected or row.get("kind") != "FILLED_BOWTIE_VALVE_GLYPH_CANDIDATE":
                errors.append("Raster glyph identity or kind differs from source claim")
        if version == SCHEMA:
            for row in result["outline_valve_candidates"]:
                expected = stable_id("raster-outline-valve", result["source_sha256"], row["page"],
                                     row["bbox"], row["orientation"], row["style"], algorithm)
                if (row["id"] != expected or row.get("kind") != "OUTLINED_BOWTIE_VALVE_GLYPH_CANDIDATE"
                    or row.get("evidence") != "FOUR_DIAGONALS_TWO_END_BASES_NO_TOP_BOTTOM_EDGE"
                    or row.get("style") not in {"PLAIN_OUTLINE", "CENTRAL_RING_OBSERVED"}):
                    errors.append("Raster outlined glyph identity or source evidence differs from claim")
        if result.get("coordinate_frame") != "PDFPLUMBER_MEDIA_NORMALIZED_V1":
            errors.append("Unexpected raster coordinate frame")
    except (TypeError, KeyError, ValueError, IndexError) as exc:
        errors.append("Malformed raster result structure: " + type(exc).__name__)
    return errors
