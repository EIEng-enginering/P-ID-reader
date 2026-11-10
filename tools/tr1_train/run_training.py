"""Guarded launcher for the offline TR1 detector training (switch PIDLAB_LOCAL_TRAINER_TR1, default OFF).

    python run_training.py --tiles-dir DIR --out-dir DIR --python PATH_TO_TORCH_PYTHON [--init COCO.pth|none] [--resume-latest]
                           [--max-wall-s 7200] [--max-cpu-s N] [--max-rss-mb 9000] [--cancel-file FILE] [--register-registry DIR]

Runs ``train_frcnn.py`` as ONE child process under hard limits (wall, CPU, tree memory), inside a Windows Job Object, so a timeout, a cancel or a
crash of this launcher leaves no training process behind. Every state change is appended to ``<out-dir>.events.jsonl`` (hash chained). After a
limit or a cancel the newest checkpoint is reported; ``--resume-latest`` continues from it and ends with the same weights as an uninterrupted run.
It trains nothing unless the switch is on, uploads nothing, and never changes the app's active detector: a finished model is only a CANDIDATE
(optionally recorded in the model registry when PIDLAB_MODEL_REGISTRY_TR1 is on); promotion is a separate human-approved step.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from tr1train import SEED                         # noqa: E402
from tr1train.events import EventLog              # noqa: E402
from tr1train.guard import run_guarded            # noqa: E402

TRAINER_SWITCH = "PIDLAB_LOCAL_TRAINER_TR1"
REGISTRY_SWITCH = "PIDLAB_MODEL_REGISTRY_TR1"


def switch_on(name: str) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        path = Path(os.environ.get("PIDLAB_TR1_SETTINGS") or (Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "PIDReader" / "tr1_features.json"))
        try:
            raw = json.loads(path.read_text(encoding="utf-8")).get(name, "off")
        except (OSError, ValueError, AttributeError):
            raw = "off"
    text = str(raw).strip().lower()
    if text in ("1", "on", "true", "yes"):
        return True
    if text in ("0", "off", "false", "no", ""):
        return False
    raise SystemExit(f"{name} must be on or off (got {raw!r})")


def sha256_file(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def preflight(a) -> list[str]:
    bad = []
    man = Path(a.tiles_dir) / "TILES_MANIFEST.json"
    if not man.is_file():
        bad.append("TILES_MANIFEST_MISSING")
    else:
        try:
            m = json.loads(man.read_text(encoding="utf-8"))
            if not m.get("splits", {}).get("train"):
                bad.append("NO_TRAIN_TILES")
        except ValueError:
            bad.append("TILES_MANIFEST_UNREADABLE")
    if not Path(a.python).is_file():
        bad.append("TORCH_PYTHON_MISSING")
    if a.init != "none" and not Path(a.init).is_file():
        bad.append("INIT_WEIGHTS_MISSING")
    out = Path(a.out_dir)
    if a.resume_latest:
        if not (out / "ckpt_latest.pt").is_file():
            bad.append("NO_CHECKPOINT_TO_RESUME")
    elif out.exists() and any(out.iterdir()):
        bad.append("OUTPUT_EXISTS (use --resume-latest or a new folder)")
    if a.max_wall_s <= 0:
        bad.append("WALL_LIMIT_REQUIRED")
    free_mb = shutil.disk_usage(out.parent if out.parent.exists() else Path(".")).free / 2 ** 20
    if free_mb < 2000:
        bad.append(f"DISK_LOW ({free_mb:.0f} MB free)")
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Guarded offline TR1 detector training (CPU)")
    ap.add_argument("--tiles-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--python", default=sys.executable, help="interpreter of the torch component")
    ap.add_argument("--init", default="none")
    ap.add_argument("--resume-latest", action="store_true")
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--limit-tiles", type=int, default=0)
    ap.add_argument("--ckpt-every-iters", type=int, default=100)
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--max-wall-s", type=float, default=7200.0)
    ap.add_argument("--max-cpu-s", type=float, default=None)
    ap.add_argument("--max-rss-mb", type=float, default=9000.0)
    ap.add_argument("--cancel-file")
    ap.add_argument("--register-registry", help="registry folder; used only when PIDLAB_MODEL_REGISTRY_TR1 is on")
    ap.add_argument("--debug-sleep-per-iter", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args(argv)
    if not switch_on(TRAINER_SWITCH):
        print(f"{TRAINER_SWITCH} is off: nothing was started.", file=sys.stderr)
        return 3
    out = Path(a.out_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    log = EventLog(str(out) + ".events.jsonl")
    log.add("CREATED", seed=a.seed, tiles_dir=str(a.tiles_dir), resume=bool(a.resume_latest))
    bad = preflight(a)
    if bad:
        log.add("PREFLIGHT_BLOCKED", blockers=bad)
        print(json.dumps({"state": "PREFLIGHT_BLOCKED", "blockers": bad}, indent=1))
        return 2
    log.add("READY")
    out.mkdir(parents=True, exist_ok=True)
    cmd = [a.python, "-B", str(HERE / "train_frcnn.py"), "--tiles-dir", a.tiles_dir, "--out-dir", str(out), "--init", a.init, "--epochs", str(a.epochs),
           "--threads", str(a.threads), "--seed", str(a.seed), "--ckpt-every-iters", str(a.ckpt_every_iters)]
    if a.limit_tiles:
        cmd += ["--limit-tiles", str(a.limit_tiles)]
    if a.resume_latest:
        cmd += ["--resume", str(out / "ckpt_latest.pt")]
    if a.debug_sleep_per_iter:
        cmd += ["--debug-sleep-per-iter", str(a.debug_sleep_per_iter)]
    env = dict(os.environ, PYTHONHASHSEED="0", PYTHONUNBUFFERED="1")
    res = run_guarded(cmd, max_wall_s=a.max_wall_s, max_cpu_s=a.max_cpu_s, max_rss_mb=a.max_rss_mb, cancel_file=a.cancel_file, env=env,
                      stdout_path=str(out / "child_stdout.log"), stderr_path=str(out / "child_stderr.log"), events=log)
    res["resumable_from"] = str(out / "ckpt_latest.pt") if (out / "ckpt_latest.pt").is_file() and res["state"] != "COMPLETED" else None
    manifest_path = out / "TRAINING_MANIFEST.json"
    if res["state"] == "COMPLETED" and manifest_path.is_file():
        tm = json.loads(manifest_path.read_text(encoding="utf-8"))
        res["training_manifest"] = tm
        if tm.get("status") == "COMPLETED" and a.register_registry and switch_on(REGISTRY_SWITCH):
            from tr1train.model_registry import ModelRegistry
            reg = ModelRegistry(a.register_registry)
            evidence = {"status": "COMPLETED", "train_data_sha256": tm["tiles_manifest_sha256"], "batch_sha256": tm["tiles_manifest_sha256"],
                        "config_sha256": hashlib.sha256(json.dumps(tm["cfg"], sort_keys=True).encode()).hexdigest(),
                        "checkpoints": {"ckpt_latest.pt": sha256_file(out / "ckpt_latest.pt")}}
            res["registry_model_id"] = reg.register_candidate(str(out / tm["final_weights"]), evidence, licence="see tiles provenance", provenance="local CPU training, tr1_train")
    (out / "RUN_RESULT.json").write_text(json.dumps(res, indent=1, sort_keys=True), encoding="utf-8", newline="")
    print(json.dumps({k: v for k, v in res.items() if k != "training_manifest"}, indent=1, sort_keys=True))
    return 0 if res["state"] == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
