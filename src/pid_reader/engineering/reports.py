"""Rev P offline engineering register/report exports, preserving original evidence.

No PDF approval stamp, no 'as-built' inference, no host Worksheet writes.
CSV is protected against spreadsheet-formula execution. HTML escapes source text.
"""
from __future__ import annotations

import csv
from collections import Counter
from hashlib import sha256
from html import escape
from io import StringIO
import json
import os
from pathlib import Path
import tempfile

from ..api import canonical_json
from .workspace import register_page

NOTICE = ("EXTRACTION / REVIEW OF DRAWINGS ONLY. Software proposals and human "
          "acceptance as a reading do not verify the plant, design, risk, or safety systems.")
COLUMNS = ["drawing_no", "revision_label", "source_name", "document_sha256",
           "page", "object_class", "tag_text", "state", "reviewed_by", "observation_id"]


MAX_FINDINGS_PER_LAYER = 500


def _analysis_section(store, eid: str, name: str) -> dict:
    """Stored analysis layers and proposed connectivity for one drawing (all unverified proposals)."""
    from .connectivity import drawing_connectivity
    from .findings import LAYERS, LAYER_TITLES, list_findings
    layers = {}
    for layer in LAYERS:
        items = list_findings(store, eid, layer, limit=2000)
        by_kind = Counter(i["kind"] for i in items)
        layers[layer] = {
            "title": LAYER_TITLES[layer], "count": len(items), "by_kind": dict(sorted(by_kind.items())),
            "reviewed": sum(1 for i in items if i["state"] != "PROPOSED"),
            "listed": [{"id": i["id"], "page": i["page"], "kind": i["kind"], "label": i["label"], "state": i["state"],
                        "bbox": i["bbox"]} for i in items[:MAX_FINDINGS_PER_LAYER]],
            "truncated": max(0, len(items) - MAX_FINDINGS_PER_LAYER)}
    graph = drawing_connectivity(store, eid)
    nodes = graph.get("nodes", [])
    return {
        "extraction_id": eid, "source_name": name, "layers": layers,
        "connectivity": {
            "node_counts": dict(sorted(Counter(n["kind"] for n in nodes).items())),
            "attachments": len(graph.get("edges", [])), "free_line_networks": graph.get("free_networks", 0),
            "tagged_symbols": [{"label": n["label"], "page": n["page"], "bbox": n["bbox"]}
                               for n in nodes if n["kind"] == "SYMBOL" and n.get("tags")],
            "paths": [{"a": p["a_label"], "b": p["b_label"], "valve_glyphs": len(p["via_valve_glyphs"]),
                       "through_tee": p["via_tee"]} for p in graph.get("paths", [])[:MAX_FINDINGS_PER_LAYER]],
            "limitations": graph.get("limitations", "")}}


def make_report(store, *, extraction_ids: list[str] | None = None,
                max_records: int = 20000, include_analysis: bool = True) -> dict:
    """Build a frozen, hash-verified, read-only report from selected extractions.

    Refuse truncation; no summary may pretend to cover records it did not read.
    An empty list means no sources, whereas None selects all imported extractions.
    """
    if type(max_records) is not int or not 1 <= max_records <= 20000:
        raise ValueError("Invalid report limit")
    if not store.verify_audit_chain():
        raise ValueError("Project audit chain failed integrity verification")
    if extraction_ids is None:
        ids = [r[0] for r in store.db.execute("SELECT extraction_id FROM extraction ORDER BY extraction_id")]
    else:
        if not isinstance(extraction_ids, list) or len(extraction_ids) > 1000 or any(
                not isinstance(i, str) or not i or len(i) > 150 for i in extraction_ids):
            raise ValueError("Invalid report source selection")
        ids = sorted(set(extraction_ids))
        if len(ids) != len(extraction_ids):
            raise ValueError("Duplicated extraction ID")
    rows: list[dict] = []
    sources: list[dict] = []
    analysis: list[dict] = []
    state_counts = Counter()
    class_counts = Counter()
    graph_edges = 0
    warnings_count = 0
    for eid in ids:
        original = store.export_extraction(eid)  # raises for non-existent ID
        registered = store.db.execute(
            "SELECT drawing_no,revision_label,facility,area FROM drawing_registration "
            "WHERE extraction_id=? ORDER BY rowid DESC LIMIT 1", (eid,)).fetchone()
        registered = dict(registered) if registered else None
        src = original["document"]
        sources.append({"extraction_id": eid, "source_name": src["filename"],
                        "source_sha256": src["sha256"], "registration": registered,
                        "result_sha256": original["provenance"]["result_sha256"],
                        "selected_pages": [p["page"] for p in original["pages"]]})
        if include_analysis:
            analysis.append(_analysis_section(store, eid, src["filename"]))
        graph_edges += len(original["connections"])
        warnings_count += len(original["warnings"])
        page = register_page(store, extraction_id=eid, limit=250)
        if len(rows) + page["total"] > max_records:
            raise ValueError("Report exceeds record limit; select a smaller source set")
        for offset in range(0, page["total"], 250):
            segment = page if offset == 0 else register_page(store, extraction_id=eid, limit=250, offset=offset)
            for item in segment["rows"]:
                rows.append(item)
                state_counts[item["state"]] += 1
                class_counts[item["object_class"]] += 1
    content = {
        "schema": "pid-reader-standalone-report-v1",
        "notice": NOTICE,
        "selection": {"extraction_ids": ids, "source_count": len(sources)},
        "sources": sources,
        "summary": {"reading_count": len(rows), "source_graph_proposals": graph_edges,
                    "source_warnings": warnings_count,
                    "by_review_state": dict(sorted(state_counts.items())),
                    "by_object_class": dict(sorted(class_counts.items()))},
        "readings": rows,
        "analysis": analysis,
        "limits": {"source": "drawing revisions only", "engineering_validation": "NOT_PERFORMED",
                   "host_integration": "NOT_PERFORMED"},
    }
    content["report_sha256"] = sha256(canonical_json(content).encode("utf-8")).hexdigest()
    return content


def verify_report(report: dict) -> bool:
    if not isinstance(report, dict) or report.get("schema") != "pid-reader-standalone-report-v1":
        return False
    digest = report.get("report_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        return False
    payload = {k: v for k, v in report.items() if k != "report_sha256"}
    try:
        return sha256(canonical_json(payload).encode("utf-8")).hexdigest() == digest
    except (ValueError, TypeError):
        return False


def _spreadsheet_safe(value) -> str:
    text = "" if value is None else str(value)
    # Avoid spreadsheet formula injection from drawings, tags, filenames and comments.
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def _named(report: dict, include_strokes: bool) -> list[dict]:
    """Readings that carry text. Unlabelled line-stroke fragments (class LINE, no text) are
    geometry, not readings an engineer can use; they stay in the JSON audit record."""
    rows = report["readings"]
    return rows if include_strokes else [r for r in rows if (r.get("tag_text") or "").strip()]


def report_csv(report: dict, *, include_strokes: bool = False) -> str:
    if not verify_report(report):
        raise ValueError("Report integrity check failed")
    stream = StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["DRAWING READINGS ONLY - NO PLANT VERIFICATION"])
    writer.writerow(COLUMNS)
    for row in _named(report, include_strokes):
        writer.writerow([_spreadsheet_safe(row.get(c)) for c in COLUMNS])
    return stream.getvalue()


HTML_COLUMNS = [("drawing_no", "Drawing"), ("revision_label", "Rev"), ("page", "Page"), ("object_class", "Class"),
                ("tag_text", "Tag / text"), ("state", "Review"), ("reviewed_by", "Reviewed by")]


def report_html(report: dict, *, include_strokes: bool = False) -> str:
    if not verify_report(report):
        raise ValueError("Report integrity check failed")
    def esc(x):
        return escape("" if x is None else str(x), quote=True)
    rows = _named(report, include_strokes)
    hidden = len(report["readings"]) - len(rows)
    summary = report["summary"]
    # group by source file, then by class, so an engineer can scan equipment / valves / instruments first
    order = {c: i for i, c in enumerate(("VESSEL", "TANK", "COLUMN", "HEAT_EXCHANGER", "PUMP", "COMPRESSOR", "FILTER",
                                         "VALVE_ONOFF", "VALVE_MANUAL", "VALVE_CONTROL", "PSV", "RUPTURE_DISC",
                                         "INSTRUMENT", "LINE", "NOTE"))}
    rows = sorted(rows, key=lambda r: (r.get("source_name") or "", order.get(r["object_class"], 99),
                                       r["page"], r.get("tag_text") or ""))
    lines = ["<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
             "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
             "<title>P&amp;ID Drawing Readings Report</title>",
             "<style>body{font:14px/1.5 system-ui,sans-serif;margin:2rem;color:#233242}"
             "h1{font-size:1.5rem}h2{font-size:1.1rem;margin-top:1.6rem}"
             "aside{border-left:4px solid #be6412;padding:.7rem;background:#f8f6f2}"
             "table{border-collapse:collapse;width:100%;font-size:.85rem}"
             "td,th{border-bottom:1px solid #ccc;padding:.4rem;text-align:left;vertical-align:top;overflow-wrap:anywhere}"
             "th{background:#edf0f2;position:sticky;top:0}.small{width:auto}.mono{font-family:Consolas,monospace;font-size:.75rem}"
             "@media print{th{position:static}body{margin:1cm}}</style></head><body>",
             "<h1>P&amp;ID drawing-reading report</h1>",
             "<aside><strong>Not a plant verification.</strong> " + esc(report["notice"]) + "</aside>",
             "<h2>Summary</h2>",
             "<p>Drawings: " + str(report["selection"]["source_count"]) + " &bull; readings listed: " + str(len(rows)) +
             (" &bull; unlabelled line-stroke fragments not listed: " + str(hidden) + " (kept in the JSON record)" if hidden else "") +
             " &bull; proposed connections in source: " + str(summary["source_graph_proposals"]) + "</p>",
             "<table class=\"small\"><thead><tr><th>Class</th><th>Count</th></tr></thead><tbody>"]
    for cls, n in summary["by_object_class"].items():
        lines.append("<tr><td>" + esc(cls) + "</td><td>" + str(n) + "</td></tr>")
    lines.append("</tbody></table>")
    lines.append("<table class=\"small\"><thead><tr><th>Review state</th><th>Count</th></tr></thead><tbody>")
    for st, n in summary["by_review_state"].items():
        lines.append("<tr><td>" + esc(st) + "</td><td>" + str(n) + "</td></tr>")
    lines.append("</tbody></table>")
    lines.append("<h2>Drawings</h2><table><thead><tr><th>File</th><th>Registered as</th><th>Pages</th><th>Source SHA-256</th></tr></thead><tbody>")
    for src in report["sources"]:
        reg = src.get("registration")
        label = f"{reg['drawing_no']} rev {reg['revision_label']} ({reg['facility']} / {reg['area']})" if reg else "not registered"
        lines.append("<tr><td>" + esc(src["source_name"]) + "</td><td>" + esc(label) + "</td><td>" +
                     esc(len(src["selected_pages"])) + "</td><td class=\"mono\">" + esc(src["source_sha256"]) + "</td></tr>")
    lines.append("</tbody></table>")
    for block in report.get("analysis", []):
        lines.append("<h2>Analysis layers &mdash; " + esc(block["source_name"]) + "</h2>")
        lines.append("<table><thead><tr><th>Layer</th><th>Found</th><th>Of which</th><th>Reviewed</th></tr></thead><tbody>")
        for layer in block["layers"].values():
            kinds = ", ".join(f"{k.replace('_', ' ').lower()}: {n}" for k, n in layer["by_kind"].items()) or "&mdash;"
            lines.append("<tr><td>" + esc(layer["title"]) + "</td><td>" + str(layer["count"]) + "</td><td>" + kinds +
                         "</td><td>" + str(layer["reviewed"]) + "</td></tr>")
        lines.append("</tbody></table>")
        conn = block["connectivity"]
        lines.append("<h2>Proposed connectivity &mdash; " + esc(block["source_name"]) + "</h2>")
        lines.append("<p>Nodes: " + esc(", ".join(f"{k.replace('_', ' ').lower()}: {n}" for k, n in conn["node_counts"].items()) or "none") +
                     " &bull; line-to-outline attachments: " + str(conn["attachments"]) +
                     " &bull; paths: " + str(len(conn["paths"])) + "</p>")
        if conn["tagged_symbols"]:
            lines.append("<p>Tagged symbols: " + esc(", ".join(t["label"] for t in conn["tagged_symbols"])) + "</p>")
        if conn["paths"]:
            lines.append("<table><thead><tr><th>From</th><th>To</th><th>Valve glyphs between</th><th>Through a tee</th></tr></thead><tbody>")
            for pth in conn["paths"]:
                lines.append("<tr><td>" + esc(pth["a"]) + "</td><td>" + esc(pth["b"]) + "</td><td>" + str(pth["valve_glyphs"]) +
                             "</td><td>" + ("yes" if pth["through_tee"] else "no") + "</td></tr>")
            lines.append("</tbody></table>")
        lines.append("<p><em>" + esc(conn["limitations"]) + "</em></p>")
        lines.append("<h2>Findings &mdash; " + esc(block["source_name"]) + "</h2>")
        for layer in block["layers"].values():
            if not layer["listed"]:
                continue
            lines.append("<details><summary>" + esc(layer["title"]) + " (" + str(layer["count"]) + ")</summary>"
                         "<table><thead><tr><th>Finding</th><th>Page</th><th>Review</th><th>Position (x, y)</th></tr></thead><tbody>")
            for f in layer["listed"]:
                pos = f"{f['bbox']['x0']:.3f}, {f['bbox']['y0']:.3f}" if f.get("bbox") else ""
                lines.append("<tr><td>" + esc(f["label"]) + "</td><td>" + str(f["page"]) + "</td><td>" + esc(f["state"]) +
                             "</td><td>" + pos + "</td></tr>")
            lines.append("</tbody></table>" + ("<p>" + str(layer["truncated"]) + " more in the JSON record.</p>" if layer["truncated"] else "") + "</details>")
    lines.append("<h2>Readings</h2>")
    if not rows:
        lines.append("<p><em>No labelled readings were found on these drawings. This usually means the sheet is scanned, "
                     "very dense, or uses tag styles the reader does not yet recognise &mdash; it does not mean the sheet has no "
                     "equipment. Open it in the application, run the analysis and review it by eye.</em></p>")
    else:
        lines.append("<table><thead><tr>" + "".join("<th>" + esc(h) + "</th>" for _c, h in HTML_COLUMNS) + "</tr></thead><tbody>")
        for row in rows:
            lines.append("<tr>" + "".join("<td>" + esc(row.get(c)) + "</td>" for c, _h in HTML_COLUMNS) + "</tr>")
        lines.append("</tbody></table>")
    lines.extend(["<p class=\"mono\">Report SHA-256: " + esc(report["report_sha256"]) + "</p>",
                  "<p>Unregistered sources and unresolved readings remain explicitly unverified.</p>",
                  "</body></html>"])
    return chr(10).join(lines) + chr(10)


def encode_report(report: dict, fmt: str) -> bytes:
    if fmt == "json":
        if not verify_report(report):
            raise ValueError("Report integrity check failed")
        text = canonical_json(report) + "\n"
    elif fmt == "csv":
        text = report_csv(report)
    elif fmt == "html":
        text = report_html(report)
    else:
        raise ValueError("Unsupported report format")
    return text.encode("utf-8")


def save_report(report: dict, destination: str | Path, *, fmt: str, overwrite: bool = False) -> Path:
    """Write a complete report or fail, without a partially written target."""
    out = Path(destination)
    if not out.parent.exists() or not out.parent.is_dir():
        raise FileNotFoundError("Report destination directory does not exist")
    payload = encode_report(report, fmt)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=out.parent, prefix=".pid-report-",
                                         suffix=".tmp", delete=False) as f:
            temp = Path(f.name)
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        if overwrite:
            os.replace(temp, out)
        else:
            os.link(temp, out)  # Atomic create-only: existing reports cannot be overwritten accidentally.
        return out
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
