"""Geometry-supported bubble processing: ring, interior, divider and the actual code/number text bands.

Input: a grey crop of ONE detector box (RF-DETR Instrument_* proposal). Output: boxes in the crop's pixel frame plus quality flags.
Nothing here reads text and nothing repairs a string. When the geometry does not support a convincing code or number band the band is
withheld (abstention) and the reason is recorded, so the recogniser is not asked to read ring strokes or blank paper.

Preserved for review: the original crop, the interior crop (outside the ring masked white), the code band, the number band, and the
transform (all boxes are pixel boxes of the original crop; `scale_note` records the render the crop came from).
"""

import numpy as np

MIN_INK_FRACTION = .012      # a band with less ink than this holds no convincing text
MIN_BAND_ROWS = 5            # pixels
DIVIDER_MIN_SPAN = .85       # of the interior width
DIVIDER_MIN_DENSITY = .28    # a dashed 1-bit divider still inks about a third of its row


def _binary(gray):
    import cv2
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, ink = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return ink > 0


def find_ring(gray):
    """Best circle (cx, cy, r) from a Hough search limited to the crop size, else None."""
    import cv2
    h, w = gray.shape
    side = min(h, w)
    if side < 16:
        return None
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    found = cv2.HoughCircles(blur, cv2.HOUGH_GRADIENT, dp=1, minDist=side, param1=100, param2=14,
                             minRadius=int(.34 * side), maxRadius=int(.58 * side))
    if found is None:
        return None
    cx, cy, r = (float(v) for v in found[0][0])
    return cx, cy, r


def _row_span(ink_row):
    """(span fraction, ink fraction) of one row: a divider stretches across the interior even when dashed or dotted."""
    cols = np.flatnonzero(ink_row)
    if cols.size < 3:
        return 0.0, 0.0
    return (cols[-1] - cols[0] + 1) / ink_row.size, cols.size / ink_row.size


def analyse(gray, *, shape="circle"):
    """Geometry of one bubble crop. `shape` is 'circle' (Instrument_Field) or 'box' (Instrument_Panel and other square symbols)."""
    gray = np.asarray(gray, dtype=np.uint8)
    h, w = gray.shape
    flags = []
    ink = _binary(gray)
    ring = find_ring(gray) if shape == "circle" else None
    if shape == "circle" and ring is None:
        flags.append("NO_RING_FOUND")
    if ring is not None:
        cx, cy, r = ring
        yy, xx = np.mgrid[0:h, 0:w]
        inside = (xx - cx) ** 2 + (yy - cy) ** 2 <= (.80 * r) ** 2          # excludes the ring stroke and its anti-aliasing
        x0, x1 = max(0, int(cx - .80 * r)), min(w, int(cx + .80 * r) + 1)
        y0, y1 = max(0, int(cy - .80 * r)), min(h, int(cy + .80 * r) + 1)
    else:
        inset_x, inset_y = int(.12 * w), int(.12 * h)
        inside = np.zeros((h, w), bool)
        inside[inset_y:h - inset_y, inset_x:w - inset_x] = True
        x0, x1, y0, y1 = inset_x, w - inset_x, inset_y, h - inset_y
        cx, cy, r = w / 2, h / 2, min(w, h) / 2
    interior = ink & inside
    if x1 - x0 < 8 or y1 - y0 < 8:
        return dict(status="ABSTAIN", reason="INTERIOR_TOO_SMALL", flags=flags + ["INTERIOR_TOO_SMALL"], ring=None, interior_box=None,
                    divider_y=None, code_band=None, number_band=None)
    width = x1 - x0
    # Divider: a long horizontal run in the middle third of the interior (a text stroke is much shorter).
    mid_lo, mid_hi = y0 + int(.30 * (y1 - y0)), y0 + int(.70 * (y1 - y0))
    divider = None
    candidates = []
    for y in range(mid_lo, mid_hi + 1):
        span, density = _row_span(interior[y, x0:x1])
        # Letters and digits stay well under the full interior width; a (possibly dashed) divider does not.
        if span >= DIVIDER_MIN_SPAN and density >= DIVIDER_MIN_DENSITY:
            candidates.append(y)
    if candidates:
        # a divider is 1-4 px thick; take the centre of the first contiguous group
        group = [candidates[0]]
        for y in candidates[1:]:
            if y - group[-1] <= 2:
                group.append(y)
            else:
                break
        thin = len(group) <= max(4, int(.10 * (y1 - y0)))
        above = int((interior[y0:group[0], x0:x1].sum(axis=1) > 0).sum())
        below = int((interior[group[-1] + 1:y1, x0:x1].sum(axis=1) > 0).sum())
        # A real divider separates two text areas. A lone text line's baseline strokes look wide too, but nothing sits below them.
        if thin and above >= MIN_BAND_ROWS and below >= MIN_BAND_ROWS:
            divider = float(sum(group)) / len(group)
            d_lo, d_hi = group[0], group[-1]
    if divider is None:
        flags.append("NO_DIVIDER")

    def band(top, bottom):
        if bottom - top < MIN_BAND_ROWS:
            return None, "BAND_TOO_THIN"
        sub = interior[top:bottom, x0:x1]
        rows = np.where(sub.sum(axis=1) > 0)[0]
        cols = np.where(sub.sum(axis=0) > 0)[0]
        if rows.size == 0 or cols.size == 0:
            return None, "NO_TEXT_INK"
        r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
        if r1 - r0 < MIN_BAND_ROWS or sub[r0:r1, c0:c1].mean() < MIN_INK_FRACTION:
            return None, "NO_CONVINCING_INK"
        pad = 2
        return [max(0, x0 + c0 - pad), max(0, top + r0 - pad), min(w, x0 + c1 + pad), min(h, top + r1 + pad)], None

    code = number = None
    code_reason = number_reason = None
    if divider is not None:
        code, code_reason = band(y0, d_lo)
        number, number_reason = band(d_hi + 1, y1)
    else:
        # No divider line: use the ACTUAL row structure of the ink. Two text row-groups separated by a blank gap are two bands
        # (stacked code over number); one group is a single band; anything else is ambiguous and abstains. Never a fixed split.
        rows = np.flatnonzero(interior[y0:y1, x0:x1].sum(axis=1) > 0) + y0
        groups = []
        for y in rows:
            if groups and y - groups[-1][-1] <= 1:
                groups[-1].append(int(y))
            else:
                groups.append([int(y)])
        groups = [g for g in groups if len(g) >= 3]                      # specks and ring remnants are not text rows
        if len(groups) == 2 and groups[1][0] - groups[0][-1] >= 2 and min(len(g) for g in groups) >= MIN_BAND_ROWS:
            code, code_reason = band(groups[0][0], groups[0][-1] + 1)
            number, number_reason = band(groups[1][0], groups[1][-1] + 1)
            flags.append("BANDS_FROM_ROW_GAP")
        elif len(groups) == 1:
            code, code_reason = band(y0, y1)
            number_reason = "ONE_TEXT_ROW_GROUP_NO_NUMBER_BAND"
        elif not groups:
            code_reason = number_reason = "NO_TEXT_INK"
        else:
            code_reason = number_reason = "AMBIGUOUS_ROW_GROUPS_" + str(len(groups))
    for reason in (code_reason, number_reason):
        if reason and reason not in flags:
            flags.append(reason)
    status = "OK" if code is not None and number is not None else ("PARTIAL" if code is not None or number is not None else "ABSTAIN")
    return dict(status=status, flags=flags, ring=dict(cx=cx, cy=cy, r=r) if ring is not None else None,
                interior_box=[x0, y0, x1, y1], divider_y=divider, code_band=code, number_band=number,
                crop_size=[w, h], scale_note="pixel boxes of the supplied crop")


def interior_crop(gray, result):
    """The crop with everything outside the ring interior painted white (original crop is kept by the caller)."""
    gray = np.asarray(gray, dtype=np.uint8).copy()
    h, w = gray.shape
    if result.get("ring"):
        cx, cy, r = result["ring"]["cx"], result["ring"]["cy"], result["ring"]["r"]
        yy, xx = np.mgrid[0:h, 0:w]
        gray[(xx - cx) ** 2 + (yy - cy) ** 2 > (.80 * r) ** 2] = 255
    elif result.get("interior_box"):
        x0, y0, x1, y1 = result["interior_box"]
        mask = np.ones((h, w), bool)
        mask[y0:y1, x0:x1] = False
        gray[mask] = 255
    return gray


def to_media_box(box_px, crop_box_media, crop_size):
    """Map a pixel box of the crop into the media-normalised frame (axis-aligned; the crop is not rotated)."""
    w, h = crop_size
    a, b, c, d = box_px
    bw, bh = crop_box_media["x1"] - crop_box_media["x0"], crop_box_media["y1"] - crop_box_media["y0"]
    return dict(x0=crop_box_media["x0"] + a / w * bw, y0=crop_box_media["y0"] + b / h * bh,
                x1=crop_box_media["x0"] + c / w * bw, y1=crop_box_media["y0"] + d / h * bh)
