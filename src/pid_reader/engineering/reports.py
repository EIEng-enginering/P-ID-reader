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


def make_report(store, *, extraction_ids: list[str] | None = None,
                max_records: int = 20000) -> dict:
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


def report_csv(report: dict) -> str:
    if not verify_report(report):
        raise ValueError("Report integrity check failed")
    stream = StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["DRAWING READINGS ONLY - NO PLANT VERIFICATION"])
    writer.writerow(COLUMNS)
    for row in report["readings"]:
        writer.writerow([_spreadsheet_safe(row.get(c)) for c in COLUMNS])
    return stream.getvalue()


def report_html(report: dict) -> str:
    if not verify_report(report):
        raise ValueError("Report integrity check failed")
    def esc(x):
        return escape("" if x is None else str(x), quote=True)
    lines = ["<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
             "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
             "<title>P&amp;ID Drawing Readings Report</title>",
             "<style>body{font:14px/1.5 system-ui,sans-serif;margin:2rem;color:#233242}" 
             "h1{font-size:1.5rem}aside{border-left:4px solid #be6412;padding:.7rem;background:#f8f6f2}" 
             "table{border-collapse:collapse;width:100%;font-size:.83rem}" 
             "td,th{border-bottom:1px solid #ccc;padding:.45rem;text-align:left;vertical-align:top;overflow-wrap:anywhere}" 
             "th{background:#edf0f2;position:sticky;top:0}" 
             "@media print{th{position:static}body{margin:1cm}}</style></head><body>",
             "<h1>P&amp;ID drawing-reading report</h1>",
             "<aside><strong>Not a plant verification.</strong> " + esc(report["notice"]) + "</aside>",
             "<p>Source revisions: " + str(report["selection"]["source_count"]) +
             "; source observations: " + str(report["summary"]["reading_count"]) +
             "; source graph proposals: " + str(report["summary"]["source_graph_proposals"]) + "</p>",
             "<p>SHA-256 of structured report: <code>" + esc(report["report_sha256"]) + "</code></p>",
             "<table><thead><tr>" + "".join("<th>" + esc(c.replace("_", " ").title()) + "</th>" for c in COLUMNS) +
             "</tr></thead><tbody>"]
    for row in report["readings"]:
        lines.append("<tr>" + "".join("<td>" + esc(row.get(c)) + "</td>" for c in COLUMNS) + "</tr>")
    lines.extend(["</tbody></table><p>Unregistered sources and unresolved readings remain explicitly unverified.</p>",
                  "</body></html>"])
    return "\n".join(lines) + "\n"


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
