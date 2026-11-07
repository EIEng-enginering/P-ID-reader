"""Small, bounded native-text/vector PDF extraction adapter.

Only text and vector geometry are extracted. No graphical symbol recognition or
scanned-page OCR is claimed. Returned readings are unverified proposals.
"""
from __future__ import annotations

from collections import Counter
from io import BytesIO
from math import hypot, isfinite, floor
import re
from typing import Any

from ..api import CancelToken, LimitExceeded, RefusedInput, connection_id, object_id, stable_id

TAG_RE = re.compile(r"^(?P<letters>[A-Za-z]{1,6})[- ]?(?P<number>\d{2,6})(?P<suffix>[A-Za-z]{0,3})$")
LINE_RE = re.compile(r'^\d+(?:\.\d+)?["\u2033]?[-/][A-Za-z]{1,4}[-/]\d+[A-Za-z0-9-]*$', re.I)
INSTRUMENT_CODES = ("PT", "PIT", "PI", "PDT", "FT", "FIT", "FI", "LT", "LIT", "LIC", "TT", "TIT", "TI", "PSH", "PSHH", "PSL", "LSHH", "LSH", "LSL", "TSHH", "FIC", "PIC", "TIC")
EQUIPMENT_CODES = {
    "V": "VESSEL", "TK": "TANK", "T": "TANK", "C": "COLUMN", "E": "HEAT_EXCHANGER",
    "P": "PUMP", "K": "COMPRESSOR", "F": "FILTER", "XV": "VALVE_ONOFF",
    "HV": "VALVE_MANUAL", "CV": "VALVE_CONTROL", "PSV": "PSV", "PRV": "PSV", "RD": "RUPTURE_DISC",
}


def _bbox(page_width: float, page_height: float, x0: float, top: float, x1: float, bottom: float) -> dict:
    """Normalised top-left coordinates; pad degenerate dimensions without leaving page."""
    if not all(isfinite(float(v)) for v in (page_width, page_height, x0, top, x1, bottom)) or page_width <= 0 or page_height <= 0:
        raise RefusedInput("PID_MALFORMED", "Invalid page coordinate geometry.")
    left, right = sorted((float(x0) / page_width, float(x1) / page_width))
    upper, lower = sorted((float(top) / page_height, float(bottom) / page_height))
    left, right = max(0.0, left), min(1.0, right)
    upper, lower = max(0.0, upper), min(1.0, lower)
    if right <= left:
        right = min(1.0, left + .0002)
        left = max(0.0, right - .0002)
    if lower <= upper:
        lower = min(1.0, upper + .0002)
        upper = max(0.0, lower - .0002)
    return {"x0": round(left, 7), "y0": round(upper, 7), "x1": round(right, 7), "y1": round(lower, 7)}


def _parse_tag(text: str) -> tuple[str, dict, float]:
    text = text.strip()
    if LINE_RE.fullmatch(text):
        return "LINE", {"parse_status": "PARTIAL", "normalised_tag": text.upper()}, 0.6
    m = TAG_RE.fullmatch(text)
    if not m:
        return "NOTE", {"parse_status": "UNPARSED"}, 0.40
    code = m["letters"].upper()
    suffix = m["suffix"].upper()
    number = m["number"]
    if code in EQUIPMENT_CODES:
        return EQUIPMENT_CODES[code], {"parse_status": "PARSED", "normalised_tag": f"{code}-{number}{suffix}", "suffix": suffix}, .76
    if code in INSTRUMENT_CODES or (len(code) >= 2 and code[0] in "PFTLAZ" and code[-1] in "TICSHL"):
        return "INSTRUMENT", {
            "parse_status": "PARTIAL", "normalised_tag": f"{code}-{number}{suffix}",
            "measured_variable": code[0], "function_letters": code[1:], "loop_number": number, "suffix": suffix,
        }, .70
    return "NOTE", {"parse_status": "UNPARSED"}, .35


_MERGE_SPLIT_RE = re.compile(r"(?<=\d)(?=[A-Za-z]{1,6}-?\d{2,6})")


def _is_tag_like(text: str) -> bool:
    return _parse_tag(text)[0] != "NOTE"


def _split_merged(text: str) -> list[str]:
    """Split touching labels such as ``HV-383HV-303`` when every part is a valid tag."""
    if _is_tag_like(text):
        return [text]
    parts = [p for p in _MERGE_SPLIT_RE.split(text) if p]
    if len(parts) > 1 and all(_is_tag_like(p) for p in parts):
        return parts
    return [text]


def _page_text_reversed(words: list[dict]) -> bool:
    """True when text on a page reads backwards (page drawn upside down, /Rotate 180).

    Decided per page by comparing how many words are valid tags forwards versus
    backwards, so ordinary pages are never altered.
    """
    forward = sum(1 for w in words if _is_tag_like(str(w.get("text", ""))))
    backward = sum(1 for w in words if _is_tag_like(str(w.get("text", ""))[::-1]))
    return backward >= 2 and backward > forward


def _make_obj(cls: str, page_num: int, b: dict, text: str, parsed: dict, confidence: float, attributes: dict | None = None) -> dict:
    return {
        "id": object_id(cls, page_num, b, text), "class": cls, "page": page_num,
        "bbox": b, "text": text, "parsed": parsed,
        "confidence": confidence, "status": "UNVERIFIED",
        "evidence": [{"page": page_num, "bbox": b, "text": text[:500]}], "attributes": attributes or {},
    }


def _segment_endpoints(page: Any, line: dict) -> list[list[float]]:
    """Endpoint candidates from pdfplumber; no flow direction is asserted."""
    x0, x1 = float(line["x0"]), float(line["x1"])
    t, b = float(line["top"]), float(line["bottom"])
    if x0 == x1:
        a, z = (x0, t), (x1, b)
    elif abs(t - b) < 1e-4:
        a, z = (x0, t), (x1, b)
    else:
        a, z = (x0, t), (x1, b)
    return [[round(min(1, max(0, x / page.width)), 7), round(min(1, max(0, y / page.height)), 7)] for x, y in (a, z)]


def extract_pdf(pdf_bytes: bytes, *, pages: tuple[int, ...] | None, max_pages: int, cancel: CancelToken | None = None, max_objects: int = 20000) -> dict:
    """Return deterministic raw host-schema items plus page classifications.

    Limits and SHA verification are performed by api.read_pid. No network, OCR,
    model loading or image rasterisation occurs here.
    """
    try:
        import pdfplumber
        from pypdf import PdfReader
    except ImportError as exc:
        raise RefusedInput("PID_DEPENDENCY_MISSING", "Native PDF parsing dependency is unavailable.") from exc
    try:
        probe = PdfReader(BytesIO(pdf_bytes), strict=False)
        if probe.is_encrypted:
            raise RefusedInput("PID_ENCRYPTED", "Password-protected PDF refused.")
        count = len(probe.pages)
        if count == 0:
            raise RefusedInput("PID_MALFORMED", "PDF has no pages.")
        if count > max_pages:
            raise LimitExceeded("PID_LIMIT_PAGES", "PDF page count exceeds permitted limit.")
    except (RefusedInput, LimitExceeded):
        raise
    except Exception as exc:
        raise RefusedInput("PID_MALFORMED", "PDF document could not be parsed.") from exc
    selected = tuple(range(1, count + 1)) if pages is None else tuple(pages)
    if not selected or len(set(selected)) != len(selected) or any(type(p) is not int or not 1 <= p <= count for p in selected):
        raise RefusedInput("PID_BAD_PARAMETER", "Selected page numbers must be unique and in range.")
    result = {"page_count": count, "pages": [], "objects": [], "connections": [], "loop_proposals": [],
              "shared_component_evidence": [], "unreadable_regions": [], "warnings": []}
    seen: set[str] = set()
    line_endpoints: list[tuple[int, str, list[list[float]]]] = []
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for number in selected:
                if cancel:
                    cancel.check()
                page = pdf.pages[number - 1]
                if not (page.width > 0 and page.height > 0):
                    raise RefusedInput("PID_MALFORMED", "Invalid PDF page dimensions.")
                if page.width * page.height > 10**9:
                    raise LimitExceeded("PID_LIMIT_GEOMETRY", "Page geometry exceeds parser budget.")
                words = page.extract_words(x_tolerance=2, y_tolerance=3, keep_blank_chars=False)
                reversed_page = _page_text_reversed(words)
                if reversed_page:
                    words = [{**w, "text": str(w["text"])[::-1]} for w in words]
                    result["warnings"].append({"code": "OTHER", "page": number,
                        "message": "Text on this page is upside down; characters were re-ordered to read it. Positions are unchanged."})
                has_text = bool(words)
                graphics = list(page.lines)
                image_count = len(page.images)
                if has_text and image_count:
                    kind, reason = "MIXED", "Native text and image regions found; the image regions need separate interpretation."
                elif has_text or graphics:
                    kind, reason = "VECTOR_TEXT", "Native text or vector strokes found on the PDF page."
                elif image_count:
                    kind, reason = "RASTER_ONLY", "Image-only page; this build has no packaged OCR model."
                else:
                    kind, reason = "NOT_PID", "No supported native text or raster image content found."
                rotation = int(getattr(page, "rotation", 0) or 0) % 360
                if rotation not in (0, 90, 180, 270):
                    rotation = 0
                status = "REFUSED" if kind == "RASTER_ONLY" else "READ"
                rec = {"page": number, "classification": kind, "reason": reason, "rotation": rotation, "read_status": status}
                if status == "REFUSED":
                    rec["refusal_code"] = "PID_NO_TEXT_LAYER"
                result["pages"].append(rec)
                if status == "REFUSED" or kind == "NOT_PID":
                    result["unreadable_regions"].append({
                        "id": stable_id("reg", number, "source_page_unread"), "page": number,
                        "bbox": {"x0": 0, "y0": 0, "x1": 1, "y1": 1},
                        "code": "PAGE_NOT_READ", "message": "Source page is not interpreted by the available native-text processing method.",
                    })
                    result["warnings"].append({"code": "NO_TEXT_LAYER" if status == "REFUSED" else "PAGE_NOT_PID", "page": number,
                                               "message": "Page lacks the supported native drawing data needed for this processing method."})
                    continue
                # Tag recognition from native words. Other significant lines become NOTE observations.
                token_rectangles: list[tuple[float, float, float, float]] = []
                expanded: list[tuple[str, float, float, dict, bool]] = []
                for word in words:
                    whole = str(word.get("text", ""))
                    pieces = _split_merged(whole)
                    total = max(1, sum(len(x) for x in pieces))
                    cursor = 0
                    for piece in pieces:
                        wx0, wx1 = float(word["x0"]), float(word["x1"])
                        a0 = wx0 + (wx1 - wx0) * cursor / total
                        a1 = wx0 + (wx1 - wx0) * (cursor + len(piece)) / total
                        cursor += len(piece)
                        expanded.append((piece, a0, a1, word, len(pieces) > 1))
                for text, wx0, wx1, word, was_split in expanded:
                    if cancel:
                        cancel.check()
                    cls, parsed, conf = _parse_tag(text)
                    if cls == "NOTE":
                        continue
                    b = _bbox(page.width, page.height, wx0, word["top"], wx1, word["bottom"])
                    attrs = {"split_from_touching_labels": "true"} if was_split else None
                    obj = _make_obj(cls, number, b, text, parsed, conf * (0.85 if was_split else 1.0), attrs)
                    if obj["id"] in seen:
                        result["warnings"].append({"code": "OTHER", "page": number,
                                                    "message": "Two extraction candidates share the same stable identifier; duplicate omitted."})
                        continue
                    seen.add(obj["id"])
                    result["objects"].append(obj)
                    token_rectangles.append((wx0, float(word["top"]), wx1, float(word["bottom"])))
                for textline in page.extract_text_lines(layout=False, strip=True):
                    if cancel:
                        cancel.check()
                    text = str(textline.get("text", "")).strip()
                    if reversed_page:
                        text = text[::-1]
                    if len(text) < 3:
                        continue
                    # Exact tag-only lines already have a tag object.
                    if _parse_tag(text)[0] != "NOTE":
                        continue
                    b = _bbox(page.width, page.height, textline["x0"], textline["top"], textline["x1"], textline["bottom"])
                    obj = _make_obj("NOTE", number, b, text, {"parse_status": "UNPARSED"}, .50)
                    if obj["id"] not in seen:
                        result["objects"].append(obj)
                        seen.add(obj["id"])
                # Vector stroke segments are proposed LINE objects, not automatically assigned to process lines.
                for line in graphics:
                    if cancel:
                        cancel.check()
                    length = hypot(float(line["x1"]) - float(line["x0"]), float(line["bottom"]) - float(line["top"]))
                    if length < 14.0:
                        continue
                    b = _bbox(page.width, page.height, line["x0"], line["top"], line["x1"], line["bottom"])
                    obj = _make_obj("LINE", number, b, "", {"parse_status": "UNPARSED"}, .38)
                    if obj["id"] not in seen:
                        result["objects"].append(obj)
                        seen.add(obj["id"])
                        line_endpoints.append((number, obj["id"], _segment_endpoints(page, line)))
                result["warnings"].append({"code": "OTHER", "page": number,
                                           "message": "This build detects native text and straight vector strokes only; symbols and many line relationships remain unread."})
                result["unreadable_regions"].append({
                    "id": stable_id("reg", number, "unsupported_symbols"), "page": number,
                    "bbox": {"x0": 0, "y0": 0, "x1": 1, "y1": 1},
                    "code": "SYMBOLS_NOT_INTERPRETED", "message": "Graphic symbols and curved paths on this source page may be outside current recognition scope.",
                })
                if len(result["objects"]) > max_objects:
                    raise LimitExceeded("PID_LIMIT_OBJECTS", "Object count exceeds the permitted result limit.")
    except (RefusedInput, LimitExceeded):
        raise
    except Exception as exc:
        raise RefusedInput("PID_MALFORMED", "Native PDF extraction failed.") from exc

    # Spatial buckets avoid O(n^2) comparisons in dense drawings. One stroke
    # endpoint may touch other strokes; crossings in the middle of a stroke are
    # NOT considered connection proof. Even endpoint matches remain tentative.
    if len(line_endpoints) > 4000:
        raise LimitExceeded("PID_LIMIT_GEOMETRY", "Too many strokes for bounded endpoint interpretation.")
    tolerance=.0015
    point_index: dict[tuple[int,int,int],list[tuple[int,int]]] = {}
    for index,(page_number,oid,poly) in enumerate(line_endpoints):
        for endpoint_number,(x,y) in enumerate(poly):
            key=(page_number,floor(x/tolerance),floor(y/tolerance))
            point_index.setdefault(key,[]).append((index,endpoint_number))
    formed: set[tuple[int,int]] = set()
    for index,(pa,aid,apoly) in enumerate(line_endpoints):
        if cancel:
            cancel.check()
        for a_number,(x,y) in enumerate(apoly):
            gx,gy=floor(x/tolerance),floor(y/tolerance)
            for dx in (-1,0,1):
                for dy in (-1,0,1):
                    for other,b_number in point_index.get((pa,gx+dx,gy+dy),[]):
                        if other<=index or (index,other) in formed:
                            continue
                        pb,bid,bpoly=line_endpoints[other]
                        b_point=bpoly[b_number]
                        if hypot(x-b_point[0],y-b_point[1])>=tolerance:
                            continue
                        poly=[apoly[1-a_number],bpoly[1-b_number]]
                        if poly[0]==poly[1]:
                            continue
                        formed.add((index,other))
                        cid=connection_id("UNKNOWN",aid,bid,poly)
                        b=_bbox(1,1,min(poly[0][0],poly[1][0]),min(poly[0][1],poly[1][1]),
                                  max(poly[0][0],poly[1][0]),max(poly[0][1],poly[1][1]))
                        result["connections"].append({
                            "id":cid,"type":"UNKNOWN","from":{"object_id":aid},"to":{"object_id":bid},
                            "direction":"UNKNOWN","polyline":poly,"confidence":.32,"status":"UNVERIFIED",
                            "evidence":[{"page":pa,"bbox":b,"text":""}],
                        })
                        if len(result["connections"])>=max_objects:
                            raise LimitExceeded("PID_LIMIT_OBJECTS", "Connection count exceeds the permitted result limit.")
    result["objects"].sort(key=lambda x: (x["page"],x["bbox"]["y0"],x["bbox"]["x0"],x["class"],x["id"]))
    result["connections"].sort(key=lambda x:x["id"])
    result["warnings"].sort(key=lambda x:(x.get("page",0),x["code"],x["message"]))
    result["unreadable_regions"].sort(key=lambda x:(x["page"],x["id"]))
    return result
