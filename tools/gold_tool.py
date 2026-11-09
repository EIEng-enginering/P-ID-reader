"""Gold annotation helper (independent annotation protocol, Rev X WPU-16).

    python tools/gold_tool.py new DRAWING.pdf OUT.json --annotator "Name" [--split DEV|TRAIN|REAL_INDEPENDENT]
    python tools/gold_tool.py validate GOLD.json
    python tools/gold_tool.py agree GOLD_A.json GOLD_B.json
    python tools/gold_tool.py score GOLD.json PROJECT.sqlite EXTRACTION_ID [--stratum NAME] [--out REPORT.json]

``new`` writes an EMPTY annotation for the drawing's exact bytes (its SHA-256). Annotate with your own eyes on the PDF, not from the reader's output;
see docs/rev_x/GOLD_ANNOTATION_GUIDE.md. ``FINAL_RESERVED`` cannot be created or scored from this tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pid_reader.engineering import gold_scoring as gs  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    n.add_argument("pdf")
    n.add_argument("out")
    n.add_argument("--annotator", required=True)
    n.add_argument("--split", choices=("TRAIN", "DEV", "REAL_INDEPENDENT"), default="DEV")
    v = sub.add_parser("validate")
    v.add_argument("gold")
    a = sub.add_parser("agree")
    a.add_argument("a")
    a.add_argument("b")
    s = sub.add_parser("score")
    s.add_argument("gold")
    s.add_argument("project")
    s.add_argument("extraction_id")
    s.add_argument("--stratum", default="UNSTRATIFIED")
    s.add_argument("--out")
    args = ap.parse_args(argv)
    if args.cmd == "new":
        out = Path(args.out)
        if out.exists():
            print("Refusing to overwrite an existing annotation file", file=sys.stderr)
            return 2
        sha = hashlib.sha256(Path(args.pdf).read_bytes()).hexdigest()
        out.write_text(json.dumps({"schema_version": "benchmark-gold-v1", "drawing_sha256": sha, "split": args.split, "annotator_ids": [args.annotator],
                                   "adjudication_status": "UNREVIEWED", "objects": [], "edges": [], "regions": []}, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"written": str(out), "drawing_sha256": sha}))
        return 0
    if args.cmd == "validate":
        problems = gs.validate_gold(json.loads(Path(args.gold).read_text(encoding="utf-8")))
        print(json.dumps({"valid": not problems, "problems": problems}, indent=1))
        return 0 if not problems else 1
    if args.cmd == "agree":
        res = gs.agreement(json.loads(Path(args.a).read_text(encoding="utf-8")), json.loads(Path(args.b).read_text(encoding="utf-8")))
        print(json.dumps(res, indent=1))
        return 0
    from pid_reader.engineering.intelligence import build_snapshot
    from pid_reader.engineering.project import ProjectStore
    gold = json.loads(Path(args.gold).read_text(encoding="utf-8"))
    with ProjectStore(args.project) as db:
        snap = build_snapshot(db, args.extraction_id)
    report = gs.score(gold, snap, stratum=args.stratum)
    text = json.dumps(report, indent=1)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
