"""The detached runner: supervises the guarded TR1 trainer, pausing/resuming around the user's controls and the resource policy.

    python -m pid_reader.engineering.trainer_service.runner CONFIG.json

Runs at BELOW_NORMAL priority (children inherit it) so the user's own work keeps the CPU. The trainer itself runs under tools/tr1_train's Job Object
guard (wall/memory limits, whole-tree kill), and this runner wraps that in an outer Job Object, so if the runner dies the whole tree dies with it.
Pause, resume, policy waits (battery, memory, disk, daily budget) and cancel all work by stopping the trainer at a checkpoint and starting it again with
--resume-latest: the trainer's resume restores the optimiser, schedule and random state, so the finished weights equal an uninterrupted run.
Nothing here changes the active detector or any project data; a finished model is a CANDIDATE only.
"""
import json
import math
import os
import shutil
import sys
import threading
import time
from pathlib import Path

from . import policy
from .service import TOOL, now, read_json, write_json

sys.path.insert(0, str(TOOL))
from tr1train.events import EventLog  # noqa: E402
from tr1train.guard import run_guarded  # noqa: E402

HEARTBEAT_S = 3.0
WAIT_POLL_S = 5.0


class State:
    def __init__(self, state_dir):
        self.dir = Path(state_dir)
        self.path = self.dir / "service.json"
        self.value = read_json(self.path, {}) or {}

    def update(self, **fields):
        self.value.update(fields)
        self.value["heartbeat_utc"] = now()
        write_json(self.path, self.value, strict=False)


def tail_progress(out, cfg, samples):
    """progress dict from the trainer's loss_log.jsonl (last iterations) and a short window of (time, iter) samples for the ETA."""
    log = out / "loss_log.jsonl"
    last = None
    try:
        with open(log, "rb") as f:
            f.seek(max(0, log.stat().st_size - 4096))
            lines = f.read().decode("utf8", "replace").splitlines()
        recs = []
        for line in lines[-40:]:
            try:
                recs.append(json.loads(line))
            except ValueError:
                pass
        last = recs[-1] if recs else None
    except OSError:
        return {}
    if not last:
        return {}
    conf = read_json(out / "train_config.json", {}) or {}
    tiles = conf.get("n_train_tiles") or 0
    per_epoch = math.ceil(tiles / cfg["batch"]) if tiles else 0
    total = per_epoch * cfg["epochs"] if per_epoch else None
    losses = [r["loss"] for r in recs[-20:] if "loss" in r]
    now_t = time.time()
    samples.append((now_t, last["iter"]))
    while samples and now_t - samples[0][0] > 600:
        samples.pop(0)
    rate = None
    if len(samples) >= 2 and samples[-1][0] > samples[0][0] and samples[-1][1] >= samples[0][1]:
        rate = (samples[-1][1] - samples[0][1]) / (samples[-1][0] - samples[0][0])
    eta = (total - last["iter"]) / rate if total and rate and rate > 0 else None
    return dict(epoch=last.get("epoch"), epochs=cfg["epochs"], iter=last["iter"], iters_total=total, loss_recent_mean=round(sum(losses) / len(losses), 4) if losses else None,
                iters_per_min=round(rate * 60, 2) if rate else None, eta_s=int(eta) if eta else None, updated_utc=now())


def build_command(cfg, state, resume):
    if cfg.get("_command"):                                             # tests
        return list(cfg["_command"])
    cmd = [sys.executable, "-B", str(TOOL / "run_training.py"), "--tiles-dir", cfg["tiles_dir"], "--out-dir", str(state / "run"), "--python", cfg["torch_python"],
           "--epochs", str(cfg["epochs"]), "--threads", str(cfg["threads"]), "--ckpt-every-iters", str(cfg["ckpt_every_iters"]),
           "--max-wall-s", str(cfg["attempt_wall_s"]), "--max-rss-mb", str(cfg["max_rss_mb"]), "--cancel-file", str(state / "ATTEMPT_CANCEL"), "--lr", str(cfg["lr"])]
    if cfg.get("init"):
        cmd += ["--init", cfg["init"]]
        if cfg.get("init_trained"):
            cmd += ["--init-trained"]
    if resume:
        cmd += ["--resume-latest"]
    return cmd


def prepare_out(state):
    """A fresh start needs an empty run folder; a folder with no usable checkpoint (killed very early) is set aside, never deleted."""
    out = state / "run"
    resume = (out / "ckpt_latest.pt").is_file()
    if not resume and out.exists() and any(out.iterdir()):
        n = 1
        while (state / f"run.aborted.{n}").exists():
            n += 1
        shutil.move(str(out), str(state / f"run.aborted.{n}"))
        events = Path(str(out) + ".events.jsonl")
        if events.exists():
            shutil.move(str(events), str(state / f"run.aborted.{n}.events.jsonl"))
    return resume


def run(cfg):
    state = Path(cfg["state_dir"])
    S = State(state)
    policy.set_low_priority()
    log = EventLog(str(state / "service_events.jsonl"))
    log.add("RUNNER_STARTED", pid=os.getpid(), threads=cfg["threads"], daily_budget_s=cfg["daily_budget_s"])
    S.update(state="RUNNING", pid=os.getpid(), reason=None, started_utc=S.value.get("started_utc") or now())
    budget = read_json(state / "budget.json", {}) or {}
    env_child = dict(os.environ, PIDLAB_LOCAL_TRAINER_TR1="on", OMP_NUM_THREADS=str(cfg["threads"]), MKL_NUM_THREADS=str(cfg["threads"]))
    attempts = S.value.get("attempts", 0)
    samples = []

    def used_today():
        if budget.get("date") != policy.perth_date():
            budget.update(date=policy.perth_date(), used_s=0.0)
        return budget["used_s"]

    def sleep_with_heartbeat(seconds, **fields):
        t0 = time.time()
        while time.time() - t0 < seconds:
            S.update(**fields)
            if (state / "CANCEL").exists():
                return
            time.sleep(min(HEARTBEAT_S, seconds))

    while True:
        if (state / "CANCEL").exists():
            log.add("CANCELLED")
            S.update(state="CANCELLED", reason="cancelled by the user; checkpoints are kept")
            return "CANCELLED"
        if (state / "PAUSE").exists():
            S.update(state="PAUSED", reason="paused by the user")
            time.sleep(WAIT_POLL_S if not cfg.get("_fast") else .2)
            continue
        reason = policy.blocked_reason(cfg, state)
        if not reason and cfg["daily_budget_s"] and used_today() >= cfg["daily_budget_s"]:
            reason = "DAILY_BUDGET_REACHED"
        if reason:
            S.update(state="WAITING", reason=reason)
            time.sleep(WAIT_POLL_S if not cfg.get("_fast") else .2)
            continue
        if attempts >= cfg["max_attempts"]:
            S.update(state="FAILED", reason="too many restarts; see run/child_stderr.log")
            return "FAILED"
        resume = prepare_out(state)
        out = state / "run"
        attempts += 1
        S.update(state="RUNNING", reason=None, attempts=attempts, resuming=resume)
        log.add("ATTEMPT_START", attempt=attempts, resume=resume)
        result = {}
        done = threading.Event()

        def work():
            cmd = build_command(cfg, state, resume)
            stdout, stderr = str(state / "launcher_stdout.log"), str(state / "launcher_stderr.log")
            result.update(run_guarded(cmd, max_wall_s=cfg["attempt_wall_s"] + 600, cwd=str(TOOL.parents[1]), env=env_child, cancel_file=str(state / "ATTEMPT_CANCEL"),
                                      stdout_path=stdout, stderr_path=stderr))
            done.set()

        t = threading.Thread(target=work, daemon=True)
        started = time.time()
        t.start()
        interrupted = None
        last_budget_save = time.time()
        last_tick = time.time()
        while not done.wait(HEARTBEAT_S if not cfg.get("_fast") else .1):
            tick = time.time()
            budget["used_s"] = used_today() + (tick - last_tick)
            last_tick = tick
            if tick - last_budget_save > 30:
                write_json(state / "budget.json", budget, strict=False)
                last_budget_save = tick
            S.update(state={"CANCEL": "CANCELLING", "PAUSE": "PAUSING"}.get(interrupted, "STOPPING") if interrupted else "RUNNING", reason=interrupted)
            prog = tail_progress(out, cfg, samples)
            if prog:
                write_json(state / "progress.json", prog, strict=False)
            if interrupted is None:
                if (state / "CANCEL").exists():
                    interrupted = "CANCEL"
                elif (state / "PAUSE").exists():
                    interrupted = "PAUSE"
                else:
                    r = policy.blocked_reason(cfg, state)
                    if r:
                        interrupted = r
                    elif cfg["daily_budget_s"] and used_today() >= cfg["daily_budget_s"]:
                        interrupted = "DAILY_BUDGET_REACHED"
                if interrupted:
                    (state / "ATTEMPT_CANCEL").write_text(interrupted, encoding="utf8")
                    log.add("ATTEMPT_STOP_REQUESTED", reason=interrupted)
        t.join()
        write_json(state / "budget.json", budget, strict=False)
        final_progress = tail_progress(out, cfg, [])                    # the last iterations may have landed after the final periodic reading
        if final_progress:
            write_json(state / "progress.json", final_progress, strict=False)
        try:
            (state / "ATTEMPT_CANCEL").unlink()
        except FileNotFoundError:
            pass
        samples.clear()
        log.add("ATTEMPT_END", outcome=result.get("state"), reason=result.get("reason"), wall_s=round(time.time() - started, 1), peak_tree_rss_mb=result.get("peak_tree_rss_mb"))
        if result.get("state") == "COMPLETED":
            manifest = read_json(out / "TRAINING_MANIFEST.json", {}) or {}
            final = out / (manifest.get("final_weights") or "weights_final.pt")
            S.update(state="COMPLETED", reason=None, result=dict(weights=str(final) if final.exists() else None, weights_sha256=manifest.get("final_weights_sha256"),
                                                                    iters=manifest.get("iters"), candidate_only=True,
                                                                    note="CANDIDATE only: not validated on the owner's drawings; the active detector is unchanged"))
            log.add("COMPLETED")
            return "COMPLETED"
        if interrupted:
            continue                                                    # pause/cancel/policy: loop decides what happens next
        if result.get("state") == "LIMIT_EXCEEDED" and "wall" in str(result.get("reason")):
            continue                                                    # the per-attempt wall slice ended; resume
        S.update(state="FAILED", reason=f"{result.get('state')}: {result.get('reason')}", result=dict(candidate_only=True))
        log.add("FAILED", reason=result.get("reason"))
        return "FAILED"


def main(argv=None):
    argv = argv or sys.argv[1:]
    cfg = json.loads(Path(argv[0]).read_text(encoding="utf8"))
    return 0 if run(cfg) in ("COMPLETED", "CANCELLED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
