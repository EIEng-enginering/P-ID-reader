"""Run the full reader + analysis over every PDF in a library folder (resumable, sharded).

    python tools/run_library_all.py LIBRARY_DIR OUT_DIR --shard 0 --shards 3

Each shard writes ``shard_N.sqlite`` (a normal project the desktop app can open) and
``shard_N.jsonl`` (one detection record per sheet; a sheet already in the JSONL is skipped on rerun).
Records hold counts and the tags the software read - they say what was *detected*, never whether it
is *correct*: no labelled ground truth exists for these sheets.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pid_reader.api import ReadParams, RefusedInput, LimitExceeded  # noqa: E402
from pid_reader.engineering.connectivity import drawing_connectivity  # noqa: E402
from pid_reader.engineering.findings import latest_analysis_ids  # noqa: E402
from pid_reader.engineering.isolation import read_pid_isolated  # noqa: E402
from pid_reader.engineering.pipeline import analyze_drawing  # noqa: E402
from pid_reader.engineering.project import ProjectStore  # noqa: E402

MAX_TAGS_LISTED = 80


def detect_record(db, eid: str, result: dict) -> dict:
    objs = result["objects"]
    tagged = [o for o in objs if o["class"] not in ("LINE", "NOTE") and o["text"]]
    run = analyze_drawing(db, eid, ocr_engine=None)
    ids = latest_analysis_ids(db, eid)
    cat = Counter()
    if "catalogue" in ids:
        for c in db.list_catalogue_candidates(ids["catalogue"], limit=2000):
            cat[c["candidate_class"]] += 1
    graph = drawing_connectivity(db, eid)
    symbols = [n for n in graph["nodes"] if n["kind"] == "SYMBOL"]
    return {
        "tags_by_class": dict(Counter(o["class"] for o in tagged)),
        "tags": [{"class": o["class"], "text": o["text"], "src": o["attributes"].get("source", "TEXT")}
                 for o in tagged][:MAX_TAGS_LISTED],
        "line_numbers": sum(1 for o in objs if o["class"] == "LINE" and o["text"]),
        "notes": sum(1 for o in objs if o["class"] == "NOTE"),
        "strokes": sum(1 for o in objs if o["class"] == "LINE" and not o["text"]),
        "ocr_objects": sum(1 for o in objs if o["attributes"].get("source") == "OCR"),
        "stages": {k: v["status"] for k, v in run["stages"].items()},
        "stage_failures": {k: v["detail"][:140] for k, v in run["stages"].items() if v["status"] == "FAILED"},
        "counts": run["counts"],
        "template_matches": dict(cat),
        "graph": {"symbols": len(symbols), "tagged_symbols": sum(1 for n in symbols if n["tags"]),
                  "valve_glyphs": sum(1 for n in graph["nodes"] if n["kind"] == "VALVE_GLYPH"),
                  "line_networks": sum(1 for n in graph["nodes"] if n["kind"] == "LINE_NETWORK"),
                  "paths": len(graph["paths"])},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("library")
    ap.add_argument("out_dir")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args(argv)
    lib, out = Path(args.library), Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(lib.rglob("*.pdf"))[args.shard::args.shards]
    jsonl = out / f"shard_{args.shard}.jsonl"
    done = set()
    if jsonl.exists():
        done = {json.loads(l)["file"] for l in jsonl.read_text(encoding="utf-8").splitlines() if l.strip()}
    db = ProjectStore(out / f"shard_{args.shard}.sqlite")
    for i, path in enumerate(files, 1):
        rel = str(path.relative_to(lib)).replace("\\", "/")
        if rel in done:
            continue
        data = path.read_bytes()
        rec = {"file": rel, "folder": path.parent.name, "bytes": len(data)}
        t0 = time.monotonic()
        try:
            result = read_pid_isolated(data, ReadParams(), filename=path.name, ocr_engine="auto",
                                       timeout_s=args.timeout, memory_mb=4096)
            rec["read_seconds"] = round(time.monotonic() - t0, 1)
            rec["status"] = "READ"
            rec["pages"] = [p["read_status"] for p in result["pages"]]
            eid = db.add_extraction(result, source_pdf_bytes=data)
            t1 = time.monotonic()
            rec.update(detect_record(db, eid, result))
            rec["analysis_seconds"] = round(time.monotonic() - t1, 1)
        except (RefusedInput, LimitExceeded) as exc:
            rec.update(status="REFUSED", code=getattr(exc, "code", type(exc).__name__),
                       read_seconds=round(time.monotonic() - t0, 1))
        except Exception as exc:
            rec.update(status="ERROR", code=f"{type(exc).__name__}: {str(exc)[:160]}",
                       read_seconds=round(time.monotonic() - t0, 1))
        with jsonl.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        print(f"[shard {args.shard}] {i}/{len(files)} {rec['status']} {rel} {rec.get('read_seconds')}s", flush=True)
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
