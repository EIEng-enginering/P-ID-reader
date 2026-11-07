"""Reading-consistency checks and instrument loop grouping for one drawing.

These catch *probable reading errors* (a tag read twice, an instrument tag outside any bubble, a bubble
without a tag, a loop with a single member on this sheet). They never assert anything about the plant: a
loop group is just tags that share a loop number printed on this drawing, and the absence of a member may
simply mean it is drawn on another sheet. No safety function or credit is implied.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

EQUIPMENT_CLASSES = {"VESSEL", "TANK", "COLUMN", "HEAT_EXCHANGER", "PUMP", "COMPRESSOR", "FILTER"}
_LOOP = re.compile(r"^([A-Z]{2,5})-?(\d{2,4})([A-Z]{0,2})$")


def instrument_loops(extraction: dict) -> list[dict]:
    """Group INSTRUMENT readings by printed loop number: ``{loop, members[{tag, variable, functions, page, bbox}]}``."""
    groups: dict[str, list[dict]] = defaultdict(list)
    seen = set()
    for o in extraction["objects"]:
        if o["class"] != "INSTRUMENT" or not o.get("text"):
            continue
        m = _LOOP.match(o["text"].strip().upper().replace(" ", ""))
        if not m or (o["text"], o["page"]) in seen:
            continue
        seen.add((o["text"], o["page"]))
        letters, number = m.group(1), m.group(2)
        groups[number].append({"tag": f"{letters}-{number}{m.group(3)}", "variable": letters[0], "functions": letters[1:],
                               "page": o["page"], "bbox": o["bbox"], "source": o["attributes"].get("source", "TEXT")})
    return [{"loop": loop, "members": sorted(ms, key=lambda x: (x["page"], x["tag"])), "member_count": len(ms),
             "note": "Tags sharing a printed loop number on this drawing; other members may be on other sheets."}
            for loop, ms in sorted(groups.items())]


def _inside(inner: dict, outer: dict) -> bool:
    cx, cy = (inner["x0"] + inner["x1"]) / 2, (inner["y0"] + inner["y1"]) / 2
    return outer["x0"] <= cx <= outer["x1"] and outer["y0"] <= cy <= outer["y1"]


def consistency_checks(extraction: dict, symbols: list[dict] | None = None, fields: dict | None = None) -> list[dict]:
    """List of ``{check, severity, message, page, bbox}``; severity is INFO or REVIEW (look at it by eye)."""
    out: list[dict] = []

    def add(check, severity, message, page=None, bbox=None):
        out.append({"check": check, "severity": severity, "message": message, "page": page, "bbox": bbox})

    named = [o for o in extraction["objects"] if o["class"] not in ("LINE", "NOTE") and o.get("text")]
    counts = Counter((o["class"], o["text"].upper().replace(" ", "")) for o in named)
    for (cls, text), n in sorted(counts.items()):
        if n > 1:
            first = next(o for o in named if (o["class"], o["text"].upper().replace(" ", "")) == (cls, text))
            add("DUPLICATE_TAG", "REVIEW", f"{text} ({cls}) is read {n} times on this drawing; one may be a misread or a repeated bubble.",
                first["page"], first["bbox"])
    if symbols is not None:
        tagged_boxes = []
        for s in symbols:
            texts = [o for o in named if o["page"] == s["page"] and _inside(o["bbox"], s["bbox"])]
            tagged_boxes.append((s, texts))
            cls = {o["class"] for o in texts}
            if s.get("candidate_class") == "INSTRUMENT_BUBBLE_CANDIDATE" and cls & EQUIPMENT_CLASSES:
                add("TAG_VS_SYMBOL", "REVIEW", f"Equipment-style tag {texts[0]['text']} sits inside an instrument-bubble outline.",
                    s["page"], s["bbox"])
            if s.get("candidate_class") == "EQUIPMENT_OUTLINE_CANDIDATE" and "INSTRUMENT" in cls:
                add("TAG_VS_SYMBOL", "REVIEW", f"Instrument-style tag {texts[0]['text']} sits inside an equipment outline.",
                    s["page"], s["bbox"])
        for o in named:
            if o["class"] == "INSTRUMENT" and not any(s["page"] == o["page"] and _inside(o["bbox"], s["bbox"]) for s in symbols):
                add("INSTRUMENT_OUTSIDE_BUBBLE", "INFO", f"Instrument tag {o['text']} was read but no circular outline surrounds it "
                    "(it may be a note, a table entry, or the bubble was not detected).", o["page"], o["bbox"])
        untagged = [s for s, t in tagged_boxes if not t and s.get("outline_kind") == "CLOSED_NEAR_CIRCULAR_OUTLINE"
                    and 1.2e-4 <= (s["bbox"]["x1"] - s["bbox"]["x0"]) * (s["bbox"]["y1"] - s["bbox"]["y0"]) <= 3e-3]
        if untagged:
            add("BUBBLE_WITHOUT_TAG", "INFO", f"{len(untagged)} instrument-sized circular outline(s) have no readable tag "
                "(gauges and indicators such as PG/IF are often drawn without a number).", untagged[0]["page"], untagged[0]["bbox"])
    for loop in instrument_loops(extraction):
        if loop["member_count"] == 1:
            m = loop["members"][0]
            add("SINGLE_MEMBER_LOOP", "INFO", f"Loop {loop['loop']} has only {m['tag']} on this drawing (other members may be on another sheet).",
                m["page"], m["bbox"])
    if fields is not None:
        tb = fields["title_block"]
        for name in ("drawing_number", "revision", "sheet"):
            if not tb.get(name):
                add("TITLE_BLOCK_FIELD_MISSING", "INFO", f"No {name.replace('_', ' ')} candidate was read from the title block.")
        if len(tb.get("drawing_number", [])) > 1:
            add("SEVERAL_DRAWING_NUMBERS", "INFO", "Several drawing-number-like strings were read; the first (title-block zone) is "
                "listed first. A reviewer should confirm the real one.")
    return out
