"""Table, notes and revision-history parsing with per-cell evidence (Rev X, WPU-04). Pure and deterministic.

Cells come from the ruling-line grid when the region has one, otherwise from text clustering. Every cell keeps its box and
the ids of the words in it. A value is bound to the row label and column label *of its own cell* -- never across rows. When a word
straddles two rows, or row and column labels name different numeric types (design vs operating), the value is reported as
``CONFLICTING`` with both candidates; nothing is guessed and no default is substituted.
"""
from __future__ import annotations

import re
from statistics import median

from .engineering_text import classify_text, parse_quantity

VERSION = "table-parse-v1"


def _center(b: dict) -> tuple[float, float]:
    return (b["x0"] + b["x1"]) / 2, (b["y0"] + b["y1"]) / 2


def _inside(b: dict, region: dict, pad: float = 0.002) -> bool:
    cx, cy = _center(b)
    return region["x0"] - pad <= cx <= region["x1"] + pad and region["y0"] - pad <= cy <= region["y1"] + pad


def _edges(values: list[float], tol: float) -> list[float]:
    out: list[float] = []
    for v in sorted(values):
        if out and abs(v - out[-1]) <= tol:
            out[-1] = (out[-1] + v) / 2
        else:
            out.append(v)
    return out


def grid_from_rules(rules: list[dict], region: dict, tol: float = 0.003) -> tuple[list[float], list[float]]:
    """Row and column edges from short horizontal/vertical rules touching the region."""
    ys, xs = [], []
    for r in rules:
        b = r["bbox"]
        if b["x1"] < region["x0"] - 0.01 or b["x0"] > region["x1"] + 0.01 or b["y1"] < region["y0"] - 0.01 or b["y0"] > region["y1"] + 0.01:
            continue
        if r["orientation"] == "H" and b["x1"] - b["x0"] <= 0.4:
            ys.append((b["y0"] + b["y1"]) / 2)
        elif r["orientation"] == "V" and b["y1"] - b["y0"] <= 0.4:
            xs.append((b["x0"] + b["x1"]) / 2)
    return _edges(ys, tol), _edges(xs, tol)


def _band_overlap(b: dict, lo: float, hi: float) -> float:
    h = b["y1"] - b["y0"]
    if h <= 0:
        return 0.0
    return max(0.0, min(b["y1"], hi) - max(b["y0"], lo)) / h


def _cluster_axis(centres: list[float], gap: float) -> list[list[int]]:
    order = sorted(range(len(centres)), key=lambda i: centres[i])
    groups: list[list[int]] = []
    for i in order:
        if groups and centres[i] - centres[groups[-1][-1]] <= gap:
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups


def parse_table(words: list[dict], region: dict, rules: list[dict] | None = None, *, label: str = "") -> dict:
    """Return ``{"rows", "cols", "cells":[{row,col,text,bbox,word_ids,row_ambiguous}], "grid_source"}``.

    ``words``: ``{"text", "bbox", optional "id"}`` in the page frame; only words whose centre lies in ``region`` are used.
    """
    inside = [w for w in words if _inside(w["bbox"], region)]
    if not inside:
        return {"label": label, "rows": 0, "cols": 0, "cells": [], "grid_source": "NONE", "region": region, "parser": VERSION}
    row_edges, col_edges = grid_from_rules(rules or [], region)
    grid = len(row_edges) >= 3 and len(col_edges) >= 2
    if grid:
        r_bounds = list(zip(row_edges[:-1], row_edges[1:]))
        c_bounds = list(zip(col_edges[:-1], col_edges[1:]))
        source = "RULING_GRID"
        # the heading text above the first rule belongs to no cell
        inside = [w for w in inside if row_edges[0] - 0.002 <= _center(w["bbox"])[1] <= row_edges[-1] + 0.002 and
                  col_edges[0] - 0.002 <= _center(w["bbox"])[0] <= col_edges[-1] + 0.002]
    else:
        hmed = median([w["bbox"]["y1"] - w["bbox"]["y0"] for w in inside]) or 0.01
        rows = _cluster_axis([_center(w["bbox"])[1] for w in inside], hmed * 0.6)
        r_bounds = []
        for grp in rows:
            ys = [inside[i]["bbox"] for i in grp]
            r_bounds.append((min(b["y0"] for b in ys), max(b["y1"] for b in ys)))
        cols = _cluster_axis([w["bbox"]["x0"] for w in inside], hmed * 3.0)
        c_bounds = []
        for grp in cols:
            xs = [inside[i]["bbox"] for i in grp]
            c_bounds.append((min(b["x0"] for b in xs) - 0.001, max(b["x1"] for b in xs) + 0.001))
        # merge touching column bands so a wide cell is not split
        merged: list[tuple[float, float]] = []
        for lo, hi in c_bounds:
            if merged and lo <= merged[-1][1] + hmed:
                merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
            else:
                merged.append((lo, hi))
        c_bounds = merged
        source = "TEXT_CLUSTERS"
    cells: dict[tuple[int, int], dict] = {}
    for w in inside:
        cx, cy = _center(w["bbox"])
        ri = next((i for i, (lo, hi) in enumerate(r_bounds) if lo <= cy <= hi), None)
        ci = next((i for i, (lo, hi) in enumerate(c_bounds) if lo <= cx <= hi), None)
        if ri is None or ci is None:
            continue
        overlaps = [i for i, (lo, hi) in enumerate(r_bounds) if _band_overlap(w["bbox"], lo, hi) >= 0.3]
        cell = cells.setdefault((ri, ci), {"row": ri, "col": ci, "words": [], "row_ambiguous": False})
        cell["words"].append(w)
        if len(overlaps) > 1:
            cell["row_ambiguous"] = True
    out = []
    for (ri, ci), cell in sorted(cells.items()):
        ws = sorted(cell["words"], key=lambda w: (round(_center(w["bbox"])[1], 3), w["bbox"]["x0"]))
        bb = {"x0": min(w["bbox"]["x0"] for w in ws), "y0": min(w["bbox"]["y0"] for w in ws),
              "x1": max(w["bbox"]["x1"] for w in ws), "y1": max(w["bbox"]["y1"] for w in ws)}
        out.append({"row": ri, "col": ci, "text": " ".join(w["text"] for w in ws), "bbox": bb,
                    "word_ids": [w.get("id", "") for w in ws], "row_ambiguous": cell["row_ambiguous"]})
    return {"label": label, "rows": len(r_bounds), "cols": len(c_bounds), "cells": out, "grid_source": source, "region": region,
            "parser": VERSION}


def _is_numeric_cell(text: str) -> bool:
    return bool(re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?(?:\s*[A-Za-z°%()/]+)?", text.strip())) and any(c.isdigit() for c in text)


def bind_values(table: dict) -> list[dict]:
    """Attribute records for numeric cells, bound to their own row label and column header.

    Returns ``{field_name, row_label, column_label, verbatim, quantity, numeric_type, status, evidence, alternatives}`` per value.
    """
    by = {(c["row"], c["col"]): c for c in table["cells"]}
    if not by:
        return []
    header_row = None
    for r in range(table["rows"]):
        row = [by[(r, c)] for c in range(table["cols"]) if (r, c) in by]
        if len(row) >= 2 and sum(1 for c in row if not _is_numeric_cell(c["text"])) >= max(2, len(row) - 1):
            header_row = r
            break
    out = []
    for (r, c), cell in sorted(by.items()):
        if c == 0 or (header_row is not None and r == header_row) or not _is_numeric_cell(cell["text"]):
            continue
        row_label = by.get((r, 0), {}).get("text", "")
        col_label = by.get((header_row, c), {}).get("text", "") if header_row is not None else ""
        row_type, row_alts = _type_of(row_label)
        col_type, col_alts = _type_of(col_label)
        ctx = f"{row_label} {col_label}".strip()
        quantity = parse_quantity(cell["text"], context=ctx)
        status, alts = "BOUND", []
        if cell["row_ambiguous"]:
            status, alts = "CONFLICTING", [{"reason": "ROW_AMBIGUOUS", "text": cell["text"]}]
            ntype = "UNKNOWN"
        elif not row_label.strip():
            status, alts = "UNBOUND", [{"reason": "NO_ROW_LABEL", "text": cell["text"]}]
            ntype = "UNKNOWN"
        elif row_type and col_type and row_type != col_type:
            # a measured quantity label ("PRESSURE") is not a numeric type: only DESIGN/OPERATING/SETPOINT/RATING conflicts count
            status, alts = "CONFLICTING", [{"numeric_type": row_type, "from": "ROW_LABEL"}, {"numeric_type": col_type, "from": "COLUMN_LABEL"}]
            ntype = "CONFLICTING"
        else:
            ntype = row_type or col_type or "UNKNOWN"
        out.append({"field_name": re.sub(r"\s+", " ", row_label).strip() or f"ROW_{r}", "row_label": row_label, "column_label": col_label,
                    "verbatim": cell["text"], "quantity": quantity, "numeric_type": ntype, "status": status,
                    "alternatives": alts or ([{"numeric_type": a} for a in (row_alts or col_alts)] if (row_alts or col_alts) else []),
                    "evidence": {"row": r, "col": c, "bbox": cell["bbox"], "word_ids": cell["word_ids"]}})
    return out


def _type_of(label: str) -> tuple[str, list[str]]:
    from .engineering_text import numeric_type_for
    t, alts = numeric_type_for(label)
    return ("" if t == "UNKNOWN" and not alts else t), alts


def parse_revision_table(table: dict) -> list[dict]:
    """Revision history rows (REV, DATE, DESCRIPTION, BY...) kept apart from issue status."""
    by = {(c["row"], c["col"]): c for c in table["cells"]}
    header = {}
    hdr_row = None
    for r in range(table["rows"]):
        names = {c: by[(r, c)]["text"].upper() for c in range(table["cols"]) if (r, c) in by}
        if sum(1 for v in names.values() if v in ("REV", "REVISION", "DATE", "DESCRIPTION", "BY", "CHK", "APPR", "APP")) >= 3:
            hdr_row, header = r, names
            break
    if hdr_row is None:
        return []
    rows = []
    for r in range(hdr_row + 1, table["rows"]):
        rec = {"row": r, "fields": {}, "evidence": []}
        for c, name in header.items():
            cell = by.get((r, c))
            if cell:
                rec["fields"][name] = cell["text"]
                rec["evidence"].append({"col": c, "bbox": cell["bbox"], "word_ids": cell["word_ids"]})
        if rec["fields"]:
            rows.append(rec)
    return rows


def parse_notes(words: list[dict], region: dict) -> list[dict]:
    """Numbered notes and holds in a NOTES region; each entry keeps its line boxes."""
    inside = [w for w in words if _inside(w["bbox"], region)]
    if not inside:
        return []
    hmed = median([w["bbox"]["y1"] - w["bbox"]["y0"] for w in inside]) or 0.01
    rows = _cluster_axis([_center(w["bbox"])[1] for w in inside], hmed * 0.6)
    lines = []
    for grp in rows:
        ws = sorted((inside[i] for i in grp), key=lambda w: w["bbox"]["x0"])
        lines.append({"text": " ".join(w["text"] for w in ws), "bbox": {"x0": min(w["bbox"]["x0"] for w in ws), "y0": min(w["bbox"]["y0"] for w in ws),
                                                                  "x1": max(w["bbox"]["x1"] for w in ws), "y1": max(w["bbox"]["y1"] for w in ws)},
                      "word_ids": [w.get("id", "") for w in ws]})
    notes: list[dict] = []
    for ln in lines:
        kind = classify_text(ln["text"])["primary"]
        starts = re.match(r"^\s*(?:(\d{1,2})[.)]|(HOLD\s*\d*)|(NOTES?:?))", ln["text"], re.I)
        if starts and not starts.group(3):
            notes.append({"kind": "HOLD" if starts.group(2) else "NOTE", "number": starts.group(1) or "", "text": ln["text"],
                          "evidence": [ln["bbox"]], "word_ids": list(ln["word_ids"]), "classification": kind})
        elif notes and not starts:
            notes[-1]["text"] += " " + ln["text"]                    # wrapped continuation of the previous note
            notes[-1]["evidence"].append(ln["bbox"])
            notes[-1]["word_ids"] += ln["word_ids"]
    return notes
