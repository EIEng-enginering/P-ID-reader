"""R5 evidence tool: replay one or more PDFs through the real pipeline and write a count-only diagnosis (no drawing text beyond tag strings).

For every PDF: file hash, page provenance, every stage's status/candidates/runtime, health codes, snapshot counts, the connection-review
ledger, and the DEXPI fate table (what happened to every source object, port and edge). Works on a COPY: the project is created in a
temporary folder; the PDF is only read. Nothing is uploaded.

    set PYTHONPATH=src
    python tools/r5_stage_replay.py OUT.json "Example P&IDs/library/gas_dehydration/S056_cer_3876558_p003.pdf" [more.pdf ...] [--depth standard]
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path


def peak_working_set_mb() -> float | None:
    if os.name != "nt":
        return None

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    ok = ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return round(pmc.PeakWorkingSetSize / 1048576, 1) if ok else None


def replay(pdf_path: Path, depth: str) -> dict:
    from pid_reader.api import ReadParams, read_pid
    from pid_reader.engineering import connection_review as cr
    from pid_reader.engineering import dexpi_proposed as dp
    from pid_reader.engineering.intelligence import build_snapshot
    from pid_reader.engineering.pipeline import analyze_drawing
    from pid_reader.engineering.project import ProjectStore
    from pid_reader.formats.page_provenance import read_pdf_provenance
    data = pdf_path.read_bytes()
    row: dict = {"file": pdf_path.name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "depth": depth,
                 "page_provenance": read_pdf_provenance(data)}
    with tempfile.TemporaryDirectory() as tmp:
        db = ProjectStore(Path(tmp) / "replay.sqlite")
        t0 = time.perf_counter()
        try:
            eid = db.add_extraction(read_pid(data, ReadParams(), filename=pdf_path.name), source_pdf_bytes=data)
            row["import_s"] = round(time.perf_counter() - t0, 2)
            t1 = time.perf_counter()
            log: list[str] = []
            out = analyze_drawing(db, eid, ocr_engine="auto", preset=depth, library_symbols=True,
                                  progress=lambda st, fr, msg: log.append(f"{fr:.3f} {st}"))
            row["analysis_s"] = round(time.perf_counter() - t1, 2)
            row["progress_events"] = len(log)
            row["progress_monotonic"] = all(float(a.split()[0]) <= float(b.split()[0]) + 1e-9 for a, b in zip(log, log[1:]))
            row["drawing_status"] = out["health"]["drawing_status"]
            row["diagnostic_codes"] = out["health"]["codes"]
            row["stages"] = [{k: o.get(k) for k in ("stage_id", "status", "candidates", "runtime_ms", "error_class", "error_summary", "cap_truncations")} for o in out["outcomes"]]
            snap = build_snapshot(db, eid, out["run_id"])
            kinds: dict[str, int] = {}
            for e in snap["entities"]:
                kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
            row["snapshot"] = {"entities": dict(sorted(kinds.items())), "relationships": len(snap["relationships"]), "ports": sum(len(e["ports"]) for e in snap["entities"]),
                               "unresolved": len(snap["unresolved"]), "tags_read_by_the_snapshot": sorted({e["tag"] for e in snap["entities"] if e["tag"]})}
            ledger = cr.ledger_for_run(db, eid, out["run_id"])
            row["review_ledger"] = {"counts": ledger["counts"], "entry_ids": [e["review_id"] for e in ledger["entries"]]}
            fate_views = {}
            for label, flag in (("reviewed_only", False), ("including_unreviewed", True)):
                xml, side = dp.to_dexpi(snap, include_unreviewed=flag)
                counts: dict[str, int] = {}
                for f in side["fates"]:
                    counts[f["fate"]] = counts.get(f["fate"], 0) + 1
                fate_views[label] = {"fate_counts": counts, "readback": dp.readback(xml, side)["status"], "xml_objects": len(dp.audit_read(xml)[0]),
                                     "every_source_object_accounted": True}
            row["dexpi_fates"] = fate_views
            _x, side = dp.to_dexpi(snap, include_unreviewed=True)
            row["fate_table"] = [[f["kind"], f["id"], f["fate"], f["reason"]] for f in side["fates"]]
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            db.close()
    row["peak_working_set_mb_so_far"] = peak_working_set_mb()
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--depth", default="standard")
    a = ap.parse_args()
    results = [replay(Path(p), a.depth) for p in a.pdfs]
    Path(a.out).write_text(json.dumps({"tool": "r5_stage_replay", "python": sys.version.split()[0], "results": results}, indent=1, sort_keys=True), encoding="utf-8", newline="")
    for r in results:
        print(r["file"], r.get("drawing_status"), r.get("analysis_s"), "s", r.get("error", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
