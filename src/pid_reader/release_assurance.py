"""Read-only, offline release preflight for the P&ID Reader development handoff.

This does not grant engineering approval, validate the plant or alter Worksheet.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from zipfile import ZipFile

EXPECTED_R1_SHA256 = "09174700ff54cdf3bd899d952951d8969041f1a094cbe8cefff9bd714cbd25e2"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def local_runtime_env(root: Path) -> dict[str, str]:
    """Force subprocesses to use this checkout rather than an old editable install."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def check_import(root: Path) -> dict:
    code = ("import json,pid_reader,pid_reader.api;"
            "print(json.dumps({'module':pid_reader.__file__,'api':pid_reader.api.__file__,'version':pid_reader.__version__}))")
    run = subprocess.run([sys.executable, "-c", code], cwd=root,
                         env=local_runtime_env(root), capture_output=True, text=True, timeout=20)
    if run.returncode != 0:
        return {"status": "FAIL", "reason": "Local core package failed isolated import."}
    try:
        info = json.loads(run.stdout.strip())
        expected = (root / "src" / "pid_reader" / "__init__.py").resolve()
        actual = Path(info["module"]).resolve()
        ok = actual == expected
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        ok, info = False, {}
    return {"status": "PASS" if ok else "FAIL", "imported": str(info.get("module", "")),
            "expected": str(expected)}


def check_r1(root: Path) -> dict:
    path = root / "contracts" / "PID_READER_MODULE_REQUIREMENTS_R1_UNMODIFIED.zip"
    if not path.is_file():
        return {"status": "FAIL", "reason": "Original R1 ZIP missing."}
    actual = digest(path.read_bytes())
    if actual != EXPECTED_R1_SHA256:
        return {"status": "FAIL", "sha256": actual, "expected": EXPECTED_R1_SHA256}
    try:
        with ZipFile(path) as z:
            valid = z.testzip() is None
            names = set(z.namelist())
            valid &= "PID_READER_MODULE_REQUIREMENTS_R1/schemas/pid_extraction.schema.json" in names
            valid &= "PID_READER_MODULE_REQUIREMENTS_R1/01_REQUIREMENTS.md" in names
    except Exception:
        valid = False
    return {"status": "PASS" if valid else "FAIL", "sha256": actual,
            "archive_integrity": valid}


def smoke_worker(root: Path) -> dict:
    """Run the standalone host-shaped worker without touching an actual host."""
    src = root / "fixtures" / "synthetic_pid_vector.pdf"
    if not src.is_file():
        return {"status": "FAIL", "reason": "Synthetic source fixture absent."}
    with tempfile.TemporaryDirectory(prefix="pid-preflight-") as tmp:
        work = Path(tmp)
        scratch = work / "scratch"
        scratch.mkdir()
        params = work / "params.json"
        params.write_text("{}", encoding="utf-8")
        dst = work / "result.json"
        cmd = [sys.executable, "-m", "pid_reader.worker", "run", "--input", str(src),
               "--params", str(params), "--output", str(dst), "--workdir", str(scratch)]
        try:
            run = subprocess.run(cmd, cwd=root, env=local_runtime_env(root),
                                 capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            return {"status": "FAIL", "reason": "Worker smoke test exceeded 120 seconds."}
        if run.returncode != 0 or not dst.exists() or list(scratch.iterdir()):
            return {"status": "FAIL", "exit_code": run.returncode,
                    "result_exists": dst.exists(), "scratch_empty": not any(scratch.iterdir())}
        try:
            from .api import result_sha256
            result = json.loads(dst.read_text(encoding="utf-8"))
            hash_ok = result_sha256(result) == result["provenance"]["result_sha256"]
            import importlib.util
            checker_path = root / "tools" / "check_extraction.py"
            spec = importlib.util.spec_from_file_location("pid_r1_checker_release", checker_path)
            assert spec and spec.loader
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            schema = root / "contracts" / "worksheet_r1_schemas" / "pid_extraction.schema.json"
            issues = mod.check(result) + mod.schema_check(result, schema)
        except Exception as e:
            return {"status": "FAIL", "reason": f"Worker result invalid: {type(e).__name__}"}
        return {"status": "PASS" if hash_ok and not issues else "FAIL",
                "exit_code": run.returncode, "result_hash_valid": hash_ok,
                "schema_and_rule_violations": len(issues), "objects": len(result["objects"])}


def preflight(root: Path) -> dict:
    root = Path(root).resolve()
    check = {"source_checkout": check_import(root), "frozen_r1": check_r1(root),
             "synthetic_worker": smoke_worker(root)}
    return {"scope": "Local development and contract smoke checks only; not engineering acceptance.",
            "runtime_python": sys.version.split()[0],
            "checks": check,
            "passed": all(v.get("status") == "PASS" for v in check.values()),
            "not_run": ["Windows Python 3.12 / PySide6 6.12 UI", "Real Worksheet host G4-G7",
                        "Independent industrial P&ID accuracy benchmark", "Commercial CAD/DEXPI interoperability",
                        "Windows installation and offline dependency licensing"]}
