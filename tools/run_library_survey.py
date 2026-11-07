"""Robustness / throughput survey over a folder of real drawings (NO accuracy claims).

    python tools/run_library_survey.py LIBRARY_DIR OUT_JSON [--sample 60] [--seed 1] [--analyze]

For a stratified random sample (by sub-folder) it runs the isolated standalone
reader (time + memory limited child process; offline OCR for scanned sheets) and,
with ``--analyze``, the full analysis pipeline into a throw-away project database.
It records per-file status, timings, object counts and failure reasons. Without
independently labelled ground truth this measures *whether the software runs on
real drawings and how fast*, never whether the readings are right.
Drawing content is not written to the report, only counts and file identifiers.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pid_reader.api import ReadParams, RefusedInput, LimitExceeded  # noqa: E402
from pid_reader.engineering.isolation import read_pid_isolated  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("library")
    ap.add_argument("out_json")
    ap.add_argument("--sample", type=int, default=60)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--timeout", type=int, default=240)
    args = ap.parse_args(argv)
    root = Path(args.library)
    by_folder: dict[str, list[Path]] = {}
    for p in sorted(root.rglob("*.pdf")):
        by_folder.setdefault(p.parent.name, []).append(p)
    rng = random.Random(args.seed)
    per = max(1, args.sample // max(1, len(by_folder)))
    chosen: list[Path] = []
    for folder, files in sorted(by_folder.items()):
        chosen.extend(rng.sample(files, min(per, len(files))))
    chosen = chosen[: args.sample]
    records = []
    tmp = Path(tempfile.mkdtemp(prefix="pid-survey-"))
    db = None
    if args.analyze:
        from pid_reader.engineering.project import ProjectStore
        db = ProjectStore(tmp / "survey.sqlite")
    for i, path in enumerate(chosen, 1):
        data = path.read_bytes()
        rec = {"file": str(path.relative_to(root)).replace("\\", "/"), "bytes": len(data)}
        t0 = time.monotonic()
        try:
            result = read_pid_isolated(data, ReadParams(), filename=path.name, ocr_engine="auto",
                                       timeout_s=args.timeout, memory_mb=3072)
            rec["read_seconds"] = round(time.monotonic() - t0, 2)
            rec["status"] = "READ"
            rec["pages"] = [{"classification": p["classification"], "read_status": p["read_status"]}
                            for p in result["pages"]]
            rec["classes"] = result["summary"]["counts_by_class"]
            rec["object_count"] = result["summary"]["object_count"]
            rec["ocr_used"] = any(o["attributes"].get("source") == "OCR" for o in result["objects"])
            if db is not None:
                from pid_reader.engineering.pipeline import analyze_drawing
                eid = db.add_extraction(result, source_pdf_bytes=data)
                t1 = time.monotonic()
                out = analyze_drawing(db, eid, ocr_engine=None)
                rec["analysis_seconds"] = round(time.monotonic() - t1, 2)
                rec["analysis_stages"] = {k: v["status"] for k, v in out["stages"].items()}
                rec["analysis_counts"] = out["counts"]
                rec["analysis_failures"] = {k: v["detail"][:160] for k, v in out["stages"].items()
                                            if v["status"] == "FAILED"}
        except (RefusedInput, LimitExceeded) as exc:
            rec["status"] = "REFUSED"
            rec["code"] = getattr(exc, "code", type(exc).__name__)
            rec["read_seconds"] = round(time.monotonic() - t0, 2)
        except Exception as exc:  # recorded, survey continues
            rec["status"] = "ERROR"
            rec["code"] = f"{type(exc).__name__}: {str(exc)[:160]}"
            rec["read_seconds"] = round(time.monotonic() - t0, 2)
        records.append(rec)
        print(f"[{i}/{len(chosen)}] {rec['status']} {rec['file']} {rec.get('read_seconds')}s", flush=True)
        Path(args.out_json).write_text(json.dumps({"sample": len(chosen), "records": records}, indent=1), encoding="utf-8")
    if db is not None:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
