"""Combine exported human reviews into decisions, readiness counts and (only for resolved items) the dataset and reference exports.

    python tools/longterm/adjudicate.py --candidates C/candidates.json --first first.json [--second second.json] [--final adjudicator.json] --out OUTDIR

Nothing is exported for an item unless a named human transcription (and, for validation, a second independent one or a named
adjudicator) exists. The command never writes a transcription of its own.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from pid_reader.engineering.longterm import corpus as C  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", type=Path, required=True)
    ap.add_argument("--first", type=Path)
    ap.add_argument("--second", type=Path)
    ap.add_argument("--final", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    root = a.candidates.parent
    doc = json.loads(a.candidates.read_text(encoding="utf8"))
    problems = C.validate_candidates(doc, root=root)
    if problems:
        sys.exit("inconsistent candidates:\n" + "\n".join(problems[:20]))
    load = lambda p: json.loads(p.read_text(encoding="utf8")) if p else None
    first, second, final = load(a.first), load(a.second), load(a.final)
    if first is None:
        sys.exit("a FIRST review is required (nothing can be exported without a named human transcription)")
    decisions = C.adjudicate(doc, first, second, final)
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / "decisions.json").write_text(json.dumps(decisions, indent=1), encoding="utf8")
    ready = C.readiness(doc, decisions)
    (a.out / "readiness.json").write_text(json.dumps(ready, indent=1), encoding="utf8")
    sources = {i["source_sha256"]: i["source_path"] for i in doc["items"]}
    summary = dict(readiness=ready)
    if any(d["adjudication"] in ("ADJUDICATED", "SINGLE_REVIEWER") and d.get("state") == "READABLE" for d in decisions.values()):
        path, n = C.export_longterm_dataset(doc, decisions, root, a.out / "dataset", sources=sources)
        summary["dataset"] = dict(path=str(path), items=n)
        for split in ("VALIDATION", "TRAIN"):
            ref = C.export_reference_v2(doc, decisions, split=split)
            (a.out / f"reference_{split.lower()}.json").write_text(json.dumps(ref, indent=1), encoding="utf8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
