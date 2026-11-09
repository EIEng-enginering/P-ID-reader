"""R5 evidence tool: hash every legacy export of one fixed drawing, so two source trees can be compared byte for byte.

Run it once from the baseline tree and once from the update tree with all PID_R5_* switches unset, then compare the two JSON files.
The version string is pinned (a version bump legitimately changes it), ISO timestamps are replaced by ``TS`` and ``elapsed_ms``/``runtime_ms`` values by 0 before hashing (two runs of the same tree differ there); everything
else is hashed as written. Uses the original-geometry synthetic fixture of the test-suite; no private drawing.

    set PYTHONPATH=<tree>/src
    python <tree>/tools/r5_off_identity.py OUT.json <tree>/tests
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

TS = re.compile(rb"\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:\.\d+)?(?:\+00:00|Z)?")
TIMING = re.compile(rb'("(?:elapsed_ms|runtime_ms)":\s*)\d+')       # wall-clock timings differ on every run of the SAME tree


def main() -> int:
    out_path, tests_dir = Path(sys.argv[1]), Path(sys.argv[2])
    sys.path.insert(0, str(tests_dir))
    import pid_reader
    pid_reader.__version__ = "0.0.0-identity"
    from revx_fixtures import symbol_sheet_pdf
    from pid_reader.api import ReadParams, read_pid
    from pid_reader.engineering.drawing_export import export_drawing
    from pid_reader.engineering.intelligence import export_package
    from pid_reader.engineering.pipeline import analyze_drawing
    from pid_reader.engineering.project import ProjectStore
    pdf = symbol_sheet_pdf([{"kind": "gate", "x": 120, "y": 200, "s": 20, "tag": "HV-101"}, {"kind": "globe", "x": 300, "y": 200, "s": 20, "tag": "FCV-102", "actuator": "diaphragm"},
                            {"kind": "ball", "x": 480, "y": 200, "s": 20, "tag": "XV-103"}], arrows=[(210, 200, 0)])
    hashes: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        db = ProjectStore(t / "p.sqlite")
        eid = db.add_extraction(read_pid(pdf, ReadParams(), filename="Identity Sheet.pdf"), source_pdf_bytes=pdf)
        analyze_drawing(db, eid, ocr_engine=None, preset="standard", library_symbols=True)
        (t / "files").mkdir()
        (t / "pkg").mkdir()
        export_drawing(db, eid, t / "files")
        export_package(db, eid, t / "pkg")
        for folder in (t / "files", t / "pkg"):
            for p in sorted(folder.rglob("*")):
                if p.is_file():
                    raw = p.read_bytes()
                    if p.name == "manifest.json":                 # it lists the hash/size of timing-bearing files; those files are compared one by one anyway
                        man = json.loads(raw)
                        man["files"] = {k: sorted(v) for k, v in man.get("files", {}).items()}
                        raw = json.dumps(man, sort_keys=True).encode("utf-8")
                    hashes[str(p.relative_to(t)).replace("\\", "/")] = hashlib.sha256(TIMING.sub(rb"\g<1>0", TS.sub(b"TS", raw))).hexdigest()
        names = sorted(r[0] for r in db.db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"))
        schema = db.db.execute("SELECT value FROM project_meta WHERE key='standalone_schema'").fetchone()[0]
        db.close()
    out_path.write_text(json.dumps({"files": hashes, "tables": names, "schema": schema, "count": len(hashes)}, indent=1, sort_keys=True), encoding="utf-8", newline="")
    print(len(hashes), "files hashed; schema", schema, "; tables", len(names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
