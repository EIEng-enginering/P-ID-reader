"""Exercise PAUSE, CANCEL and checkpoint-RESUME on this machine and record the evidence the readiness gate reads.

    python tools/longterm/verify_controls.py --config C:/PIDWork/PIDLongTerm/programme.json

Uses a scratch state directory and SYNTHETIC TRAIN-only crops (machinery check, never accuracy). The real programme state, models,
project databases and datasets are not touched. Needs the ML runtime (backend_python) for the resume check.
"""
import argparse
import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "tr1_train"))
from pid_reader.engineering.longterm import runner  # noqa: E402
from pid_reader.engineering.longterm.data import freeze_payload, sha  # noqa: E402
from tr1train.guard import run_guarded  # noqa: E402


def check_pause(scratch):
    cfg = dict(state_dir=str(scratch / "pause"), require_ac=False, minimum_free_memory_mb=1, maximum_start_cpu_percent=100, minimum_free_disk_mb=1)
    Path(cfg["state_dir"]).mkdir(parents=True)
    (Path(cfg["state_dir"]) / "PAUSE").write_text("")
    return "PASS" if runner.policy(cfg) == "PAUSED" else "FAIL"


def check_cancel(scratch):
    cancel = scratch / "CANCEL"
    cancel.write_text("")
    t0 = time.monotonic()
    res = run_guarded([sys.executable, "-c", "import time; time.sleep(120)"], max_wall_s=60, max_rss_mb=512, cancel_file=str(cancel),
                      stdout_path=str(scratch / "c.out"), stderr_path=str(scratch / "c.err"))
    ok = res["state"] == "CANCELLED" and not res["processes_left_after_kill"] and time.monotonic() - t0 < 30
    return "PASS" if ok else "FAIL", res


def check_resume(config, scratch):
    py, models = config["backend_python"], Path(config.get("models_dir") or Path(config["backend_python"]).parents[2])
    data = scratch / "synthetic"
    subprocess.run([py, str(ROOT / "tools/longterm/synthetic_smoke_data.py"), str(data), "--count", "4"], check=True, cwd=str(ROOT))
    manifest = models / "trocr.manifest.json"
    payload = freeze_payload(dict(dataset_path=str(data / "dataset.json"), model_manifest_path=str(manifest), max_steps=2, max_steps_per_slice=1,
                                  checkpoint_every=1, slice_seconds=600, lr=1e-5, last_layers=1, seed=20261112))
    out = scratch / "resume_job"
    request = scratch / "job.json"
    request.write_text(json.dumps(dict(kind="TRAIN_OCR", payload=payload)), encoding="utf8")
    results = []
    for _ in range(2):
        out.mkdir(exist_ok=True)
        env = dict(__import__("os").environ, PYTHONPATH=str(ROOT / "src"), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", OMP_NUM_THREADS="2")
        guard = run_guarded([py, "-m", "pid_reader.engineering.longterm.worker", str(request), str(out)], cwd=str(ROOT), env=env, max_wall_s=900, max_rss_mb=4096,
                            stdout_path=str(scratch / "w.out"), stderr_path=str(scratch / "w.err"))
        wr = json.loads((out / "worker_result.json").read_text()) if (out / "worker_result.json").is_file() else {}
        results.append(dict(state=guard["state"], status=wr.get("status"), steps=wr.get("steps"), peak_tree_rss_mb=guard["peak_tree_rss_mb"], wall_s=guard["wall_s"]))
    ok = results[0]["status"] == "PARTIAL" and results[0]["steps"] == 1 and results[1]["status"] == "SUCCEEDED" and results[1]["steps"] == 2
    return "PASS" if ok else "FAIL", results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, required=True)
    a = ap.parse_args()
    config = json.loads(a.config.read_text(encoding="utf8"))
    evidence = Path(config["state_dir"]) / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pid-controls-", dir=str(Path(config["state_dir"]))) as tmp:
        scratch = Path(tmp)
        pause = check_pause(scratch)
        cancel, cancel_detail = check_cancel(scratch)
        resume, resume_detail = check_resume(config, scratch)
    doc = dict(utc=datetime.now(timezone.utc).isoformat(), pause=pause, cancel=cancel, resume=resume, cancel_detail=cancel_detail, resume_detail=resume_detail,
               data="SYNTHETIC TRAIN-only machinery check; not recognition accuracy")
    (evidence / "controls_verified.json").write_text(json.dumps(doc, indent=2), encoding="utf8")
    print(json.dumps({k: doc[k] for k in ("pause", "cancel", "resume", "resume_detail")}, indent=2))
    sys.exit(0 if all(doc[k] == "PASS" for k in ("pause", "cancel", "resume")) else 3)


if __name__ == "__main__":
    main()
