"""Structured sheet information read from a drawing's text (native and OCR): title block, line sizes,
line numbers, set-points, line labels and notes.

Pure, deterministic, read-only: it never writes to the project and never decides which candidate is right.
Every item is a ``PROPOSED_UNVERIFIED`` candidate carrying its page position as evidence; where several
candidates exist (two drawing-number-like strings, two revision letters) all are returned.
"""
from __future__ import annotations

import re
from collections import defaultdict

SCHEMA = "pid-reader-standalone-sheet-fields-v1"
STATUS = "PROPOSED_UNVERIFIED"

_DWG_NO = re.compile(r"^[A-Z0-9]{2,8}(?:[-–—][A-Z0-9]{1,8}){3,6}$", re.I)
_NPS = re.compile(r"^(?:NPS|DN)[\s_]?(\d{1,3}(?:[\s-]?\d/\d)?)$", re.I)
_NPS_PAIR = re.compile(r"\b(?:NPS|(?-i:DN))[\s_]?(\d{1,3}(?:[\s-]?\d/\d)?)(?:\s*[x×]\s*(?:NPS|(?-i:DN))?[\s_]?(\d{1,3}(?:[\s-]?\d/\d)?))?", re.I)
_LINE_LABEL = re.compile(r"\bLINE\s+(\d{1,4}\s*[-–]\s*\d{1,3})\b", re.I)
_LINE_NUMBER = re.compile(r'^\d+(?:\.\d+)?["″]?[-/][A-Za-z]{1,4}[-/]\d+[A-Za-z0-9-]*$')
_SET_POINT = re.compile(r"\bSP\s*=\s*([\dXx.]+)\s*(kPa|MPa|bar|psi|Pa|mbar)\s*(?:[\(（]\s*([ga])\s*[\)）])?", re.I)
_SHEET = re.compile(r"\b(?:PAGE|SHEET)\s*(\d+)\s*OF\s*(\d+)\b", re.I)
_MONTH = (r"(?:January|February|March|April|May|June|July|August|September|October|November|December|"
          r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)")
_DATE = re.compile(rf"\b(?:{_MONTH}\.?\s+\d{{4}}|\d{{1,2}}[-/.]\d{{1,2}}[-/.]\d{{2,4}}|\d{{4}}[-/.]\d{{1,2}}[-/.]\d{{1,2}})\b", re.I)


def _item(text, page, bbox, **extra):
    return {"text": text, "page": page, "bbox": bbox, "status": STATUS, **extra}


def _union(boxes):
    return {"x0": min(b["x0"] for b in boxes), "y0": min(b["y0"] for b in boxes),
            "x1": max(b["x1"] for b in boxes), "y1": max(b["y1"] for b in boxes)}


def _text_lines(words: list[dict]) -> list[dict]:
    """Group word boxes into reading-order lines (same page, similar vertical centre, left to right)."""
    by_page = defaultdict(list)
    for w in words:
        by_page[w["page"]].append(w)
    lines = []
    for page, ws in by_page.items():
        ws = sorted(ws, key=lambda w: ((w["bbox"]["y0"] + w["bbox"]["y1"]) / 2, w["bbox"]["x0"]))
        current: list[dict] = []
        for w in ws:
            cy = (w["bbox"]["y0"] + w["bbox"]["y1"]) / 2
            h = max(w["bbox"]["y1"] - w["bbox"]["y0"], 1e-4)
            if current:
                ref = current[-1]
                ry = (ref["bbox"]["y0"] + ref["bbox"]["y1"]) / 2
                if abs(cy - ry) <= 0.6 * max(h, ref["bbox"]["y1"] - ref["bbox"]["y0"]):
                    current.append(w)
                    continue
                lines.append(current)
            current = [w]
        if current:
            lines.append(current)
    out = []
    for group in lines:
        group = sorted(group, key=lambda w: w["bbox"]["x0"])
        out.append({"page": group[0]["page"], "text": " ".join(w["text"] for w in group),
                    "bbox": _union([w["bbox"] for w in group]), "words": group})
    return out


def sheet_fields(extraction: dict, ocr_words: list[dict] | None = None) -> dict:
    """Candidate sheet information from ``extraction['objects']`` (native/OCR readings) and optional OCR words."""
    words = [{"text": o["text"], "page": o["page"], "bbox": o["bbox"]} for o in extraction["objects"] if o.get("text")]
    native_boxes = [(w["page"], w["bbox"]) for w in words]

    def covered(page, b):
        cx, cy = (b["x0"] + b["x1"]) / 2, (b["y0"] + b["y1"]) / 2
        return any(p == page and nb["x0"] <= cx <= nb["x1"] and nb["y0"] <= cy <= nb["y1"] for p, nb in native_boxes)
    for w in ocr_words or []:
        if not covered(w["page"], w["bbox"]):     # native text wins where both read the same place
            words.append({"text": w["text"], "page": w["page"], "bbox": w["bbox"]})
    lines = _text_lines(words)

    title = defaultdict(list)
    line_sizes, line_labels, line_numbers, set_points, notes = [], [], [], [], []
    for ln in lines:
        text, page, bbox = ln["text"], ln["page"], ln["bbox"]
        in_title_zone = bbox["x0"] >= 0.45 and bbox["y0"] >= 0.78
        for part in re.split(r"\s+", text):
            if _DWG_NO.match(part) and len(part) >= 10:
                title["drawing_number"].append(_item(part.replace("–", "-").replace("—", "-"), page, bbox,
                                                     in_title_block_zone=in_title_zone))
        for m in _SHEET.finditer(text):
            title["sheet"].append(_item(f"{m.group(1)} of {m.group(2)}", page, bbox))
        for m in _DATE.finditer(text):
            title["date"].append(_item(m.group(0), page, bbox))
        if in_title_zone:
            ws = ln["words"]
            for i, w in enumerate(ws[:-1]):
                if re.fullmatch(r"REV\.?:?", w["text"], re.I) and re.fullmatch(r"[A-Z0-9]{1,3}", ws[i + 1]["text"]):
                    title["revision"].append(_item(ws[i + 1]["text"], page, _union([w["bbox"], ws[i + 1]["bbox"]])))
        if re.search(r"piping\s+and\s+instrumentation|P\s*&\s*ID", text, re.I) and len(text) > 20:
            title["title"].append(_item(text, page, bbox))
        for m in _NPS_PAIR.finditer(text):
            size = m.group(1).replace(" ", "") + (f" x {m.group(2).replace(' ', '')}" if m.group(2) else "")
            line_sizes.append(_item(m.group(0).strip(), page, bbox, size=size,
                                    unit="NPS" if m.group(0).upper().startswith("NPS") else "DN"))
        for m in _LINE_LABEL.finditer(text):
            line_labels.append(_item("LINE " + re.sub(r"\s+", "", m.group(1)), page, bbox))
        for m in _SET_POINT.finditer(text):
            set_points.append(_item(m.group(0).strip(), page, bbox, value=m.group(1), unit=m.group(2),
                                    gauge_or_abs={"g": "gauge", "a": "absolute"}.get((m.group(3) or "").lower(), "unspecified")))
        for part in re.split(r"\s+", text):
            if _LINE_NUMBER.match(part):
                line_numbers.append(_item(part, page, bbox))
        if len(text) > 12 and not re.fullmatch(r"[\d\W]+", text):
            notes.append(_item(text, page, bbox))

    def dedupe(items):
        seen_keys, out = set(), []
        for it in sorted(items, key=lambda i: (i["page"], i["bbox"]["y0"], i["bbox"]["x0"], i["text"])):
            key = (it["text"], it["page"], round(it["bbox"]["x0"], 2), round(it["bbox"]["y0"], 2))
            if key not in seen_keys:
                seen_keys.add(key)
                out.append(it)
        return out

    tb = {k: dedupe(v) for k, v in title.items()}
    # a drawing number inside the title-block zone is the most plausible candidate, but all are kept
    if "drawing_number" in tb:
        tb["drawing_number"].sort(key=lambda i: (not i.get("in_title_block_zone", False), i["page"], i["text"]))
    return {"schema": SCHEMA, "status": STATUS,
            "title_block": tb, "line_sizes": dedupe(line_sizes), "line_labels": dedupe(line_labels),
            "line_numbers": dedupe(line_numbers), "set_points": dedupe(set_points), "notes": dedupe(notes),
            "limitations": "Candidates read from drawing text; not verified. Several candidates may exist for one field; "
                           "a reviewer chooses. Title-block position rules assume a bottom-right block."}


def flatten(fields: dict) -> list[dict]:
    """Rows ``{group, field, value, page, x, y}`` for tables and spreadsheets."""
    rows = []
    for field, items in fields["title_block"].items():
        for it in items:
            rows.append({"group": "Title block", "field": field.replace("_", " "), "value": it["text"], "page": it["page"],
                         "x": round(it["bbox"]["x0"], 4), "y": round(it["bbox"]["y0"], 4)})
    for group, key in (("Line size", "line_sizes"), ("Line label", "line_labels"), ("Line number", "line_numbers"),
                       ("Set-point", "set_points"), ("Note / text", "notes")):
        for it in fields[key]:
            rows.append({"group": group, "field": group.lower(), "value": it["text"], "page": it["page"],
                         "x": round(it["bbox"]["x0"], 4), "y": round(it["bbox"]["y0"], 4)})
    return rows
