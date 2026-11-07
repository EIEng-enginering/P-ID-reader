"""Excel workbook of everything read from one or more drawings (registers, loops, lines, findings, checks...).

Every sheet carries the source drawing, page and position of each row, the review state and who reviewed it.
All cells are written as plain text/numbers (formula-looking text is neutralised), headers are frozen and
filtered. The "Read me" sheet states that the contents are unverified drawing readings.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .checks import consistency_checks, instrument_loops
from .findings import LAYERS, LAYER_TITLES, list_findings, latest_analysis_ids
from .reports import NOTICE, _spreadsheet_safe
from .sheet_fields import flatten, sheet_fields
from .workspace import register_page

EQUIPMENT = ("VESSEL", "TANK", "COLUMN", "HEAT_EXCHANGER", "PUMP", "COMPRESSOR", "FILTER")
VALVES = ("VALVE_ONOFF", "VALVE_MANUAL", "VALVE_CONTROL", "PSV", "RUPTURE_DISC")


def _readings(store, eid: str, classes: tuple[str, ...]) -> list[dict]:
    rows, offset = [], 0
    while True:
        page = register_page(store, extraction_id=eid, object_classes=classes, named_only=True, limit=250, offset=offset)
        rows.extend(page["rows"])
        offset += 250
        if offset >= page["total"]:
            return rows


def build_tables(store, extraction_id: str) -> dict[str, tuple[list[str], list[list]]]:
    """{sheet name: (header, rows)} for one drawing."""
    ex = store.export_extraction(extraction_id)
    name = ex["document"]["filename"]
    objs = {o["id"]: o for o in ex["objects"]}
    ids = latest_analysis_ids(store, extraction_id)
    ocr_words = store.list_ocr_words(ids["ocr"], limit=2000) if "ocr" in ids else []
    fields = sheet_fields(ex, ocr_words)
    symbols = [f["detail"] for f in list_findings(store, extraction_id, "symbols", limit=2000)]

    def reading_row(r):
        o = objs.get(r["native_object_id"], {})
        edit = (r.get("reviewed_edit") or {}).get("text")
        return [name, r["object_class"], edit or r["tag_text"], r["page"], round(r["bbox"]["x0"], 4), round(r["bbox"]["y0"], 4),
                o.get("attributes", {}).get("source", "PDF text"), o.get("confidence", ""), r["state"], r["reviewed_by"] or ""]
    head = ["Drawing file", "Class", "Tag / text", "Page", "x", "y", "Source", "Confidence", "Review", "Reviewed by"]
    tables: dict[str, tuple[list[str], list[list]]] = {}
    tables["Equipment"] = (head, [reading_row(r) for r in _readings(store, extraction_id, EQUIPMENT)])
    valve_rows = [reading_row(r) for r in _readings(store, extraction_id, VALVES)]
    for f in list_findings(store, extraction_id, "examples", limit=2000):
        if f["detail"]["class_hint"] == "VALVE" and f["state"] != "REJECTED":
            b = f["bbox"]
            valve_rows.append([name, "VALVE (taught look-alike)", f["detail"]["label"], f["page"], round(b["x0"], 4), round(b["y0"], 4),
                               f"TEACH_BY_EXAMPLE similarity {f['detail']['score']:.2f}", "", f["state"], ""])
    tables["Valves"] = (head, valve_rows)
    inst = []
    for r in _readings(store, extraction_id, ("INSTRUMENT",)):
        o = objs.get(r["native_object_id"], {})
        p = o.get("parsed", {})
        base = reading_row(r)
        inst.append(base[:3] + [p.get("measured_variable", ""), p.get("function_letters", ""), p.get("loop_number", "")] + base[3:])
    tables["Instruments"] = (["Drawing file", "Class", "Tag", "Variable", "Functions", "Loop no.", "Page", "x", "y", "Source",
                              "Confidence", "Review", "Reviewed by"], inst)
    tables["Loops"] = (["Drawing file", "Loop no.", "Tags on this drawing", "Count", "Note"],
                       [[name, lp["loop"], ", ".join(m["tag"] for m in lp["members"]), lp["member_count"], lp["note"]]
                        for lp in instrument_loops(ex)])
    line_rows = [[name, "Line number", i["text"], "", i["page"], round(i["bbox"]["x0"], 4), round(i["bbox"]["y0"], 4)]
                 for i in fields["line_numbers"]]
    line_rows += [[name, "Line size", i["text"], i["size"], i["page"], round(i["bbox"]["x0"], 4), round(i["bbox"]["y0"], 4)]
                  for i in fields["line_sizes"]]
    line_rows += [[name, "Line label", i["text"], "", i["page"], round(i["bbox"]["x0"], 4), round(i["bbox"]["y0"], 4)]
                  for i in fields["line_labels"]]
    tables["Lines"] = (["Drawing file", "Kind", "Text read", "Size", "Page", "x", "y"], line_rows)
    tables["Sheet info"] = (["Drawing file", "Group", "Field", "Value", "Page", "x", "y"],
                            [[name, r["group"], r["field"], r["value"], r["page"], r["x"], r["y"]] for r in flatten(fields)])
    find_rows = []
    for layer in LAYERS:
        for f in list_findings(store, extraction_id, layer, limit=2000):
            b = f["bbox"] or {}
            find_rows.append([name, LAYER_TITLES[layer], f["label"], f["kind"], f["page"], round(b.get("x0", 0), 4),
                              round(b.get("y0", 0), 4), f["state"]])
    tables["Findings"] = (["Drawing file", "Layer", "Finding", "Kind", "Page", "x", "y", "Review"], find_rows)
    from .connectivity import drawing_connectivity
    conn = drawing_connectivity(store, extraction_id)
    tables["Connections"] = (["Drawing file", "From", "To", "Valve glyphs between", "Through a tee", "Status"],
                             [[name, p["a_label"], p["b_label"], len(p["via_valve_glyphs"]), "yes" if p["via_tee"] else "no",
                               "proposed, unverified"] for p in conn.get("paths", [])])
    tables["Checks"] = (["Drawing file", "Level", "Check", "Message", "Page"],
                        [[name, c["severity"], c["check"], c["message"], c["page"] or ""]
                         for c in consistency_checks(ex, symbols, fields)])
    tables["Notes"] = (["Drawing file", "Text", "Page"], [[name, n["text"], n["page"]] for n in fields["notes"]])
    tables["OCR words"] = (["Drawing file", "Word", "Page", "x", "y"],
                           [[name, w["text"], w["page"], round(w["bbox"]["x0"], 4), round(w["bbox"]["y0"], 4)] for w in ocr_words])
    return tables


def export_xlsx(store, destination: str | Path, *, extraction_ids: list[str] | None = None) -> Path:
    """Write the workbook atomically (temp file in the same folder, then rename). Returns the path."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    out = Path(destination)
    if not out.parent.is_dir():
        raise FileNotFoundError("Destination folder does not exist")
    if extraction_ids is None:
        extraction_ids = [r[0] for r in store.db.execute("SELECT extraction_id FROM extraction ORDER BY imported_utc, extraction_id")]
    if not extraction_ids:
        raise ValueError("No drawings in the project")
    merged: dict[str, tuple[list[str], list[list]]] = {}
    sources = []
    for eid in extraction_ids:
        ex = store.export_extraction(eid)
        sources.append([ex["document"]["filename"], ex["document"]["sha256"], ex["document"]["page_count"]])
        for sheet, (header, rows) in build_tables(store, eid).items():
            merged.setdefault(sheet, (header, []))[1].extend(rows)
    wb = Workbook()
    ws = wb.active
    ws.title = "Read me"
    ws.append(["P&ID Reader workbook"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([NOTICE])
    ws.append(["Generated (UTC)", datetime.now(timezone.utc).isoformat(timespec="seconds")])
    ws.append(["Contents: readings and proposals read from the drawings. Positions (x, y) are fractions of the page from the top-left. "
               "Confidence values are uncalibrated heuristics. OCR-sourced rows are unverified."])
    ws.append([])
    ws.append(["Drawing file", "Source SHA-256", "Pages"])
    for c in ws[6]:
        c.font = Font(bold=True)
    for row in sources:
        ws.append([_spreadsheet_safe(v) if isinstance(v, str) else v for v in row])
    ws.column_dimensions["A"].width = 48
    ws.column_dimensions["B"].width = 70
    for sheet, (header, rows) in merged.items():
        s = wb.create_sheet(sheet)
        s.append(header)
        for c in s[1]:
            c.font = Font(bold=True)
        for row in rows:
            s.append([_spreadsheet_safe(v) if isinstance(v, str) else v for v in row])
        s.freeze_panes = "A2"
        if rows:
            s.auto_filter.ref = s.dimensions
        for i, col in enumerate(header, start=1):
            width = max([len(str(col))] + [len(str(r[i - 1])) for r in rows[:300] if i - 1 < len(r)])
            s.column_dimensions[s.cell(row=1, column=i).column_letter].width = min(70, max(10, width + 2))
    fd, tmp = tempfile.mkstemp(prefix=".pid-xlsx-", suffix=".tmp", dir=out.parent)
    os.close(fd)
    try:
        wb.save(tmp)
        os.replace(tmp, out)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return out
