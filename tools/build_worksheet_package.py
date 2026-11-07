"""Assemble the Worksheet R1 *integration candidate* package (not an installed host module).

    python tools/build_worksheet_package.py WHEELHOUSE_DIR OUT_DIR

OUT_DIR must not exist. Produces: module.json (validated against the frozen R1
manifest schema), DEPENDENCY_REGISTER.csv, SBOM.json, wheels/ (copied), the
pid_reader source, a sample extraction that passes the R1 checker, and
PACKAGE_MANIFEST.sha256. Items the frozen checklist needs but that cannot exist
without the real host (migration SQL, host adapter, independent runs) are
written into STATUS.json as NOT_IMPLEMENTED / NOT_RUN - never as done.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import check_extraction  # noqa: E402
from pid_reader import __version__  # noqa: E402
from pid_reader.api import ReadParams, read_pid  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wheel_meta(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.endswith(".dist-info/METADATA"))
        text = z.read(name).decode("utf-8", "replace")
    meta = {}
    for line in text.splitlines():
        if not line.strip():
            break
        key, _, value = line.partition(":")
        meta.setdefault(key.strip(), value.strip())
    licence = meta.get("License-Expression") or meta.get("License") or ""
    if not licence or len(licence) > 80:
        classifiers = [l.split("::")[-1].strip() for l in text.splitlines() if l.startswith("Classifier: License")]
        licence = "; ".join(classifiers) or "UNKNOWN - record manually"
    return {"package": meta.get("Name", path.name), "version": meta.get("Version", "?"), "licence": licence,
            "source": f"https://pypi.org/project/{meta.get('Name', '')}/{meta.get('Version', '')}/"}


def main(argv=None) -> int:
    wheelhouse, out = Path(argv[0] if argv else sys.argv[1]), Path(argv[1] if argv else sys.argv[2])
    if out.exists():
        raise SystemExit("OUT_DIR already exists; refusing to overwrite")
    wheels = sorted(wheelhouse.glob("*.whl"))
    if not wheels:
        raise SystemExit("No wheels found in WHEELHOUSE_DIR")
    (out / "wheels").mkdir(parents=True)
    deps = []
    for w in wheels:
        shutil.copy2(w, out / "wheels" / w.name)
        m = wheel_meta(w)
        deps.append({**m, "wheel_sha256": sha256(w), "used_for": "PDF parsing / geometry / rendering (core reader)"})
    shutil.copytree(ROOT / "src" / "pid_reader", out / "pid_reader", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "ui"))
    manifest = {
        "name": "pid_reader", "version": __version__,
        "summary": "Reads vector P&ID PDFs and proposes objects, tags and connections for human review (development build).",
        "python": "3.12", "platform": "win_amd64",
        "host": {"contract_min": "R22", "contract_max": None, "schema_min": 23, "qt": "PySide6==6.12.0"},
        "entry_points": {"library": "pid_reader.api:read_pid", "worker": "pid_reader.worker",
                         "migration": "contracts/migrations/00NN_pid_reader.sql (NOT PROVIDED - needs the real host)",
                         "ui": "pid_reader.ui.main_window:MainWindow (standalone window; no host ReviewDialog exists)"},
        "capabilities": ["READ_PDF_VECTOR"],
        "object_classes": ["VESSEL", "TANK", "COLUMN", "HEAT_EXCHANGER", "PUMP", "COMPRESSOR", "FILTER", "VALVE_ONOFF",
                           "VALVE_MANUAL", "VALVE_CONTROL", "PSV", "RUPTURE_DISC", "INSTRUMENT", "LINE", "NOTE"],
        "bulk_accept_blocked_classes": ["VESSEL", "TANK", "COLUMN", "HEAT_EXCHANGER", "PUMP", "COMPRESSOR", "FILTER",
                                        "VALVE_ONOFF", "VALVE_MANUAL", "VALVE_CONTROL", "PSV", "RUPTURE_DISC",
                                        "INSTRUMENT", "LINE", "NOTE"],
        "dependencies": deps, "models": [],
        "limits": {"max_pdf_bytes": 16777216, "max_pages": 500, "max_render_pixels": 12000000, "max_objects_per_run": 20000,
                   "max_stored_result_bytes": 8388608, "peak_memory_mb": 2048, "seconds_per_page_reference": 3.0,
                   "reference_pc": "NOT MEASURED on a reference PC (development laptop, Windows 11 x64, Python 3.12.10)"},
        "error_codes": ["PID_SHA_MISMATCH", "PID_ENCRYPTED", "PID_NO_TEXT_LAYER", "PID_LIMIT_BYTES", "PID_LIMIT_PAGES",
                        "PID_LIMIT_OBJECTS", "PID_LIMIT_GEOMETRY", "PID_LIMIT_RESULT", "PID_UNKNOWN_PARAMETER",
                        "PID_LIMIT_RAISED", "PID_BAD_PARAMETER", "PID_MALFORMED", "PID_CANCELLED",
                        "PID_DEPENDENCY_MISSING"],
        "schema_versions": {"reads": [1], "writes": 1},
        "evidence": {"benchmark_report_id": None, "independent_run": "NOT_RUN", "thresholds_record": None},
    }
    schema = json.loads((ROOT / "contracts" / "worksheet_r1_schemas" / "module_manifest.schema.json").read_text("utf-8"))
    try:
        import jsonschema
        errors = [e.message for e in jsonschema.Draft202012Validator(schema).iter_errors(manifest)]
    except ImportError:
        errors = ["jsonschema missing - manifest not validated"]
    (out / "module.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    with (out / "DEPENDENCY_REGISTER.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["package", "version", "licence_as_declared", "source", "wheel_sha256", "review_status"])
        for d in deps:
            w.writerow([d["package"], d["version"], d["licence"], d["source"], d["wheel_sha256"], "NOT_REVIEWED_BY_OWNER_OR_LEGAL"])
    (out / "SBOM.json").write_text(json.dumps({"bomFormat": "pid-reader-simple-sbom", "component": "pid_reader " + __version__,
                                               "dependencies": deps}, indent=2), encoding="utf-8")
    pdf = (ROOT / "fixtures" / "synthetic_pid_vector.pdf").read_bytes()
    sample = read_pid(pdf, ReadParams(), filename="synthetic_pid_vector.pdf")
    sample_path = out / "sample_extraction.json"
    sample_path.write_text(json.dumps(sample), encoding="utf-8")
    schema_path = ROOT / "contracts" / "worksheet_r1_schemas" / "pid_extraction.schema.json"
    checker = check_extraction.check(sample) + check_extraction.schema_check(sample, schema_path)
    status = {
        "package_kind": "R1_INTEGRATION_CANDIDATE_NOT_INSTALLED_IN_HOST",
        "manifest_schema_errors": errors, "sample_extraction_checker_violations": checker,
        "gates": {
            "module_manifest_valid_against_frozen_schema": "PASS" if not errors else "FAIL",
            "sample_extraction_passes_R1_checker": "PASS" if not checker else "FAIL",
            "vendored_wheels_with_sha256": "PASS (hashes recorded; licence review NOT_RUN)",
            "host_migration_sql": "NOT_IMPLEMENTED (needs the real Worksheet host)",
            "pid_reader_host.py_adapter": "NOT_IMPLEMENTED",
            "host_review_dialog": "NOT_IMPLEMENTED",
            "host_G4_G7_rehearsal_on_host_copy": "NOT_RUN",
            "independent_benchmark_run": "NOT_RUN",
            "owner_threshold_record": "NOT_RUN",
            "reference_pc_performance": "NOT_RUN",
        },
    }
    (out / "STATUS.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    shutil.copy2(ROOT / "contracts" / "PID_READER_MODULE_REQUIREMENTS_R1_UNMODIFIED.zip", out / "R1_REQUIREMENTS_UNMODIFIED.zip")
    lines = []
    for p in sorted(out.rglob("*")):
        if p.is_file():
            lines.append(f"{sha256(p)}  {p.relative_to(out).as_posix()}")
    (out / "PACKAGE_MANIFEST.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(status["gates"], indent=2))
    return 0 if not errors and not checker else 1


if __name__ == "__main__":
    raise SystemExit(main())
