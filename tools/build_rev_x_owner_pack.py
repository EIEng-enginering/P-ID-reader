"""Assemble the owner-review ZIP for the Rev X upgrade.

    python tools/build_rev_x_owner_pack.py OUTPUT.zip [--installer PATH]

Contents: a ``git archive`` of HEAD (source, tests, tools, docs; the git-ignored 1.1 GB drawing library is never included), the evidence under
TEST_RESULTS/REV_X, SBOM / notices / traceability / status / owner checklist at the top level, and a MANIFEST_SHA256.txt of everything. An installer
zip, if given, is NOT embedded (it is large); its path, size and SHA-256 are recorded in the manifest so it can be matched to this source.
The frozen R1 ZIP is included unmodified and its hash is checked first.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R1_SHA = "09174700ff54cdf3bd899d952951d8969041f1a094cbe8cefff9bd714cbd25e2"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("output")
    ap.add_argument("--installer")
    args = ap.parse_args(argv)
    r1 = (ROOT / "contracts" / "PID_READER_MODULE_REQUIREMENTS_R1_UNMODIFIED.zip").read_bytes()
    if sha(r1) != R1_SHA:
        print("FROZEN R1 ARCHIVE CHANGED; refusing to package", file=sys.stderr)
        return 2
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    tar = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=ROOT, capture_output=True).stdout
    entries: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(tar)) as tf:
        for m in tf.getmembers():
            if m.isfile():
                entries["source/" + m.name] = tf.extractfile(m).read()
    for rel in ("SBOM.json", "THIRD_PARTY_NOTICES.md", "REQUIREMENTS_TRACEABILITY_REV_X.csv", "WPU_STATUS.md", "OWNER_REVIEW_CHECKLIST.md", "HANDOFF_STATE.md", "GOLD_ANNOTATION_GUIDE.md"):
        p = ROOT / "docs" / "rev_x" / rel
        if p.exists():
            entries["OWNER_REVIEW/" + rel] = p.read_bytes()
    for p in sorted((ROOT / "TEST_RESULTS" / "REV_X").glob("*")):
        if p.is_file():
            entries["OWNER_REVIEW/evidence/" + p.name] = p.read_bytes()
    manifest = {"application": "P&ID Reader (Advanced)", "branch": branch, "git_head": head, "working_tree_dirty_tracked_files": bool(dirty),
                "frozen_r1_sha256": R1_SHA, "files": {k: {"sha256": sha(v), "bytes": len(v)} for k, v in sorted(entries.items())},
                "gates": {"G-SW": "see evidence/final_*.json", "G-EXT": "NOT_RUN", "G-HOST": "NOT_RUN", "G-ENG": "NOT_RUN"},
                "not_included": ["Example P&IDs/ (git-ignored public drawings, redistribution licence unknown)", "the official DEXPI XSD", "any client drawing"]}
    if args.installer and Path(args.installer).is_file():
        data = Path(args.installer).read_bytes()
        manifest["installer"] = {"path": str(args.installer), "bytes": len(data), "sha256": sha(data), "signed": False,
                                 "note": "unsigned; built from this git_head; clean-machine install NOT_RUN"}
    entries["MANIFEST_SHA256.json"] = json.dumps(manifest, indent=1).encode("utf-8")
    out = Path(args.output)
    if out.exists():
        print("Refusing to overwrite an existing file", file=sys.stderr)
        return 2
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in sorted(entries.items()):
            z.writestr(name, data)
    print(json.dumps({"written": str(out), "files": len(entries), "bytes": out.stat().st_size, "git_head": head}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
