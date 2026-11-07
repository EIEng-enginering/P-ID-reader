"""Offline development preflight: python tools/release_preflight.py [--json PATH]."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pid_reader.release_assurance import preflight


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--json", help="Optional output location for read-only preflight report")
    args = p.parse_args(argv)
    report = preflight(ROOT)
    display = json.dumps(report, indent=2, ensure_ascii=False)
    print(display)
    if args.json:
        out = Path(args.json)
        if out.exists():
            p.error("Refusing to overwrite an existing preflight report")
        out.write_text(display + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
