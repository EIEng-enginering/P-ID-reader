"""Document-text stage (Rev X, WPU-04 integration): tables, revision history, notes/holds, title-block text, as engineering items.

Consumes the regions from ``page_regions`` plus native and OCR words, runs ``table_parse`` / ``engineering_text`` and returns
``engineering_item`` rows (kinds ``TABLE``, ``ATTRIBUTE``, ``EVIDENCE``). Every item names its evidence (page, normalised box,
word ids), its truth class (``DIRECT_OBSERVATION`` for verbatim text, ``STRUCTURALLY_DERIVED`` for a table-cell binding) and
starts as ``PROPOSED_UNVERIFIED``. Nothing here asserts a design value of the plant.
"""
from __future__ import annotations

import hashlib
import json

from .engineering_text import classify_text, parse_quantity
from .table_parse import bind_values, parse_notes, parse_revision_table, parse_table

VERSION = "doc-text-v1"
MAX_ITEMS_PER_PAGE = 2000


def _iid(*parts) -> str:
    return "itm-" + hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:24]


def _words_for(page: int, profile: dict | None, ocr_words: list[dict]) -> list[dict]:
    words: list[dict] = []
    if profile:
        for i, w in enumerate(profile["words"]):
            words.append({"id": f"nat-{page}-{i}", "text": w["text"], "bbox": w["bbox"], "source": "NATIVE"})
    for w in ocr_words:
        words.append({"id": w["id"], "text": w["text"], "bbox": w["bbox"], "source": "OCR"})
    return words


def extract_document_text(page_analysis: list[dict], profiles: dict[int, dict], ocr_words_by_page: dict[int, list[dict]],
                          source_sha256: str) -> tuple[list[dict], dict]:
    """Return ``(items, stats)``. Deterministic for identical inputs."""
    items: list[dict] = []
    stats = {"tables": 0, "table_values": 0, "conflicting_values": 0, "unbound_values": 0, "notes": 0, "revision_rows": 0,
             "title_lines": 0, "pages": 0, "capped_pages": 0}
    for pg in page_analysis:
        number = pg["page"]
        profile = profiles.get(number)
        words = _words_for(number, profile, ocr_words_by_page.get(number, []))
        rules = profile["rules"] if profile else []
        stats["pages"] += 1
        page_items: list[dict] = []
        for reg in pg["regions"]:
            kind, bbox = reg["kind"], reg["bbox"]
            base = {"page": number, "region_id": reg["region_id"], "producer": VERSION, "review_state": "PROPOSED_UNVERIFIED",
                    "source_sha256": source_sha256}
            if kind == "TABLE":
                table = parse_table(words, bbox, rules, label=reg.get("label", ""))
                if not table["cells"]:
                    continue
                stats["tables"] += 1
                page_items.append({**base, "item_id": _iid(source_sha256, number, "TABLE", bbox), "item_kind": "TABLE", "tag_normalized": None,
                                   "truth_class": "STRUCTURALLY_DERIVED", "label": table["label"], "table": {k: table[k] for k in ("rows", "cols", "grid_source", "cells")},
                                   "evidence": [{"page": number, "bbox": bbox, "word_ids": sorted({i for c in table["cells"] for i in c["word_ids"]})[:400]}]})
                for v in bind_values(table):
                    stats["table_values"] += 1
                    stats["conflicting_values"] += v["status"] == "CONFLICTING"
                    stats["unbound_values"] += v["status"] == "UNBOUND"
                    page_items.append({**base, "item_id": _iid(source_sha256, number, "ATTR", v["evidence"]["bbox"], v["verbatim"], v["field_name"]),
                                       "item_kind": "ATTRIBUTE", "tag_normalized": None, "truth_class": "STRUCTURALLY_DERIVED",
                                       "attribute": {k: v[k] for k in ("field_name", "row_label", "column_label", "verbatim", "quantity",
                                                                       "numeric_type", "status", "alternatives")},
                                       "evidence": [{"page": number, "bbox": v["evidence"]["bbox"], "word_ids": v["evidence"]["word_ids"]}]})
            elif kind == "REVISION_TABLE":
                table = parse_table(words, bbox, rules, label="revision table")
                for row in parse_revision_table(table):
                    stats["revision_rows"] += 1
                    page_items.append({**base, "item_id": _iid(source_sha256, number, "REV", row["row"], bbox), "item_kind": "ATTRIBUTE",
                                       "tag_normalized": None, "truth_class": "STRUCTURALLY_DERIVED",
                                       "attribute": {"field_name": "REVISION_HISTORY_ROW", "fields": row["fields"], "status": "BOUND",
                                                     "verbatim": " | ".join(row["fields"].values())},
                                       "evidence": [{"page": number, "bbox": e["bbox"], "word_ids": e["word_ids"]} for e in row["evidence"]]})
            elif kind == "NOTES":
                for note in parse_notes(words, bbox):
                    stats["notes"] += 1
                    page_items.append({**base, "item_id": _iid(source_sha256, number, "NOTE", note["text"], note["evidence"][0]),
                                       "item_kind": "ATTRIBUTE", "tag_normalized": None, "truth_class": "DIRECT_OBSERVATION",
                                       "attribute": {"field_name": note["kind"], "number": note["number"], "verbatim": note["text"],
                                                     "classification": note["classification"], "status": "BOUND"},
                                       "evidence": [{"page": number, "bbox": b, "word_ids": note["word_ids"]} for b in note["evidence"]]})
            elif kind == "TITLE_BLOCK":
                inside = [w for w in words if bbox["x0"] <= (w["bbox"]["x0"] + w["bbox"]["x1"]) / 2 <= bbox["x1"]
                          and bbox["y0"] <= (w["bbox"]["y0"] + w["bbox"]["y1"]) / 2 <= bbox["y1"]]
                for line in _lines(inside):
                    cls = classify_text(line["text"])
                    if cls["primary"] == "UNKNOWN" and ":" not in line["text"]:
                        continue
                    stats["title_lines"] += 1
                    page_items.append({**base, "item_id": _iid(source_sha256, number, "TITLE", line["bbox"], line["text"]), "item_kind": "ATTRIBUTE",
                                       "tag_normalized": None, "truth_class": "DIRECT_OBSERVATION",
                                       "attribute": {"field_name": "TITLE_BLOCK_TEXT", "verbatim": line["text"], "classification": cls["primary"],
                                                     "matches": [m["kind"] for m in cls["matches"]], "status": "BOUND"},
                                       "evidence": [{"page": number, "bbox": line["bbox"], "word_ids": line["word_ids"]}]})
        if len(page_items) > MAX_ITEMS_PER_PAGE:
            stats["capped_pages"] += 1
            page_items = page_items[:MAX_ITEMS_PER_PAGE]
        items += page_items
    return items, stats


def _lines(words: list[dict]) -> list[dict]:
    if not words:
        return []
    ordered = sorted(words, key=lambda w: ((w["bbox"]["y0"] + w["bbox"]["y1"]) / 2, w["bbox"]["x0"]))
    lines: list[list[dict]] = []
    for w in ordered:
        cy = (w["bbox"]["y0"] + w["bbox"]["y1"]) / 2
        h = w["bbox"]["y1"] - w["bbox"]["y0"]
        if lines:
            last = lines[-1]
            lcy = sum((x["bbox"]["y0"] + x["bbox"]["y1"]) / 2 for x in last) / len(last)
            if abs(cy - lcy) <= max(h, 0.003) * 0.6:
                last.append(w)
                continue
        lines.append([w])
    out = []
    for ln in lines:
        ln.sort(key=lambda w: w["bbox"]["x0"])
        out.append({"text": " ".join(w["text"] for w in ln), "word_ids": [w["id"] for w in ln],
                    "bbox": {"x0": min(w["bbox"]["x0"] for w in ln), "y0": min(w["bbox"]["y0"] for w in ln),
                             "x1": max(w["bbox"]["x1"] for w in ln), "y1": max(w["bbox"]["y1"] for w in ln)}})
    return out
