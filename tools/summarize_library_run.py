"""Summarise run_library_all.py output into a Markdown report and a CSV (one row per sheet).

    python tools/summarize_library_run.py SURVEY_DIR REPORT.md SHEETS.csv

States what was *detected* (counts, stage failures, timing). It cannot say what was *correct*.
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


def main(argv=None) -> int:
    d, report, sheets = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    recs = [json.loads(l) for f in sorted(d.glob("shard_*.jsonl")) for l in f.read_text("utf-8").splitlines() if l.strip()]
    ok = [r for r in recs if r["status"] == "READ"]
    bad = [r for r in recs if r["status"] != "READ"]

    def named(r):
        return sum(r.get("tags_by_class", {}).values())

    with sheets.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["folder", "file", "status", "read_s", "analysis_s", "ocr_objects", "named_tags", "equipment", "valves",
                    "instruments", "line_numbers", "notes", "outline_symbols", "tagged_symbols", "valve_glyphs",
                    "template_matches", "line_networks", "paths", "geometry_status", "failure"])
        for r in sorted(recs, key=lambda r: r["file"]):
            t = r.get("tags_by_class", {})
            eq = sum(t.get(c, 0) for c in ("VESSEL", "TANK", "COLUMN", "HEAT_EXCHANGER", "PUMP", "COMPRESSOR", "FILTER"))
            vl = sum(t.get(c, 0) for c in ("VALVE_ONOFF", "VALVE_MANUAL", "VALVE_CONTROL", "PSV", "RUPTURE_DISC"))
            g = r.get("graph", {})
            w.writerow([r["folder"], r["file"].split("/")[-1], r["status"], r.get("read_seconds"), r.get("analysis_seconds"),
                        r.get("ocr_objects", ""), named(r) if ok else "", eq, vl, t.get("INSTRUMENT", 0), r.get("line_numbers", ""),
                        r.get("notes", ""), g.get("symbols", ""), g.get("tagged_symbols", ""), g.get("valve_glyphs", ""),
                        sum(r.get("template_matches", {}).values()), g.get("line_networks", ""), g.get("paths", ""),
                        r.get("stages", {}).get("geometry", ""), r.get("code") or "; ".join(r.get("stage_failures", {}).values())[:120]])

    cls = Counter()
    for r in ok:
        cls.update(r.get("tags_by_class", {}))
    by_folder = defaultdict(list)
    for r in ok:
        by_folder[r["folder"]].append(r)
    geom = Counter(r["stages"].get("geometry") for r in ok if "stages" in r)
    fail_reasons = Counter()
    for r in ok:
        for k, v in r.get("stage_failures", {}).items():
            fail_reasons[(k, v[:90])] += 1
    secs = [r["read_seconds"] for r in ok]
    lines = ["# Library run: what the software detected (NOT a measure of correctness)", "",
             f"Sheets processed: **{len(recs)}** (read: {len(ok)}, refused/failed: {len(bad)}). No labelled ground truth exists for these sheets, "
             "so every number below counts *detections*, not correct detections.", "",
             "## Headline", "",
             f"- Sheets with **at least one named equipment/instrument/valve tag**: {sum(1 for r in ok if named(r))} of {len(ok)}",
             f"- Sheets with a **line number** read: {sum(1 for r in ok if r.get('line_numbers'))}",
             f"- Sheets with **tagged symbols** in the proposed graph: {sum(1 for r in ok if r.get('graph', {}).get('tagged_symbols'))}",
             f"- Sheets with **valve glyphs** detected: {sum(1 for r in ok if r.get('graph', {}).get('valve_glyphs'))}",
             f"- Sheets where OCR contributed readings: {sum(1 for r in ok if r.get('ocr_objects'))}",
             f"- Geometry analysis: {dict(geom)}",
             f"- Time per sheet (reader, incl. OCR): median {statistics.median(secs):.0f} s, max {max(secs):.0f} s" if secs else "",
             "", "## Detections by class (named readings only)", "", "| Class | Count |", "|---|---|"]
    lines += [f"| {c} | {n} |" for c, n in cls.most_common()]
    lines += ["", "## By folder", "", "| Folder | Sheets | With any tag | Equipment+valves+instruments | Line numbers | Valve glyphs | Geometry failed |", "|---|---|---|---|---|---|---|"]
    for f, rs in sorted(by_folder.items()):
        lines.append(f"| {f} | {len(rs)} | {sum(1 for r in rs if named(r))} | {sum(named(r) for r in rs)} | "
                     f"{sum(r.get('line_numbers', 0) for r in rs)} | {sum(r.get('graph', {}).get('valve_glyphs', 0) for r in rs)} | "
                     f"{sum(1 for r in rs if r['stages'].get('geometry') == 'FAILED')} |")
    lines += ["", "## Stage failures", ""]
    lines += [f"- {k[0]}: {k[1]} — {n} sheet(s)" for k, n in fail_reasons.most_common()] or ["- none"]
    if bad:
        lines += ["", "## Sheets not read", ""] + [f"- {r['file']}: {r.get('code')}" for r in bad]
    lines += ["", "Per-sheet details: the CSV next to this report. Open the `shard_*.sqlite` projects in the desktop app to inspect any sheet visually."]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:22]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
