"""Run a command and record machine-readable test evidence (Rev X protocol).

    python tools/record_test_evidence.py --name baseline_pytest -- python -m pytest -q tests
    python tools/record_test_evidence.py --name r1_checker --r1-checker

Output: TEST_RESULTS/REV_X/<name>.json with
{command, git_head, env, run_utc, duration_ms, passed, failed, skipped, expected_failures,
 stderr_excerpt_redacted, input_fixture_sha256, result_sha256}.
``--r1-checker`` unpacks the frozen R1 ZIP into a temporary folder and runs its own 16 tests; the ZIP is only read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R1_ZIP = ROOT / "contracts" / "PID_READER_MODULE_REQUIREMENTS_R1_UNMODIFIED.zip"
R1_SHA256 = "09174700ff54cdf3bd899d952951d8969041f1a094cbe8cefff9bd714cbd25e2"
_SECRET = re.compile(r"(?i)(password|token|secret|api[_-]?key)\s*[=:]\s*\S+")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              timeout=20).stdout.strip() or "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def redact(text: str, limit: int = 1500) -> str:
    text = _SECRET.sub(r"\1=<redacted>", text)
    text = text.replace(str(Path.home()), "<home>")
    return text[-limit:]


def count(pattern: str, text: str) -> int:
    m = re.search(pattern, text)
    return int(m.group(1)) if m else 0


def run(name: str, command: list[str], cwd: Path, env_extra: dict[str, str], inputs: list[Path]) -> dict:
    env = dict(os.environ)
    env.update(env_extra)
    start = time.time()
    proc = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=3 * 3600)
    duration = int((time.time() - start) * 1000)
    out = proc.stdout + "\n" + proc.stderr
    record = {
        "name": name,
        "command": " ".join(command),
        "git_head": git_head(),
        "env": {"python": sys.version.split()[0], "platform": platform.platform(), "machine": platform.machine(),
                "cpu_count": os.cpu_count(), "pythonpath": env.get("PYTHONPATH", "")},
        "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_ms": duration,
        "exit_code": proc.returncode,
        "passed": count(r"(\d+) passed", out),
        "failed": count(r"(\d+) failed", out),
        "skipped": count(r"(\d+) skipped", out),
        "expected_failures": count(r"(\d+) xfailed", out),
        "stderr_excerpt_redacted": redact(proc.stderr),
        "stdout_tail_redacted": redact(proc.stdout, 800),
        "input_fixture_sha256": {p.name: sha256_file(p) for p in inputs if p.exists()},
    }
    record["result_sha256"] = hashlib.sha256(json.dumps(record, sort_keys=True).encode("utf-8")).hexdigest()
    return record


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--r1-checker", action="store_true")
    ap.add_argument("--out-dir", default=str(ROOT / "TEST_RESULTS" / "REV_X"))
    ap.add_argument("command", nargs="*")
    args = ap.parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.r1_checker:
        digest = sha256_file(R1_ZIP)
        if digest != R1_SHA256:
            print(f"FROZEN R1 ARCHIVE CHANGED: {digest}", file=sys.stderr)
            return 2
        with tempfile.TemporaryDirectory(prefix="r1chk-") as tmp:
            with zipfile.ZipFile(R1_ZIP) as z:
                z.extractall(tmp)
            base = Path(tmp) / "PID_READER_MODULE_REQUIREMENTS_R1"
            rec = run(args.name, [sys.executable, "-m", "pytest", "-q", "tests"], base, {}, [R1_ZIP])
        rec["frozen_r1_sha256"] = digest
    else:
        if not args.command:
            ap.error("command required")
        cmd = [sys.executable if c == "python" else c for c in args.command]
        rec = run(args.name, cmd, ROOT, {"PYTHONPATH": str(ROOT / "src")}, [R1_ZIP])
    target = out_dir / f"{args.name}.json"
    target.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: rec[k] for k in ("name", "passed", "failed", "skipped", "duration_ms", "exit_code")}))
    return 0 if rec["exit_code"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
