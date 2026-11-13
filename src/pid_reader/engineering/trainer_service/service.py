"""API of the background training service: start, status, pause, resume, cancel.

State lives in one folder per run (default %LOCALAPPDATA%\\PIDReader\\training\\tr1, never OneDrive):
  config.json      frozen settings of the run            service.json   current state (written by the runner, atomically)
  progress.json    epoch/iteration/loss/ETA              budget.json    compute seconds used per Perth date
  PAUSE / CANCEL   control files (the GUI and CLI only create/remove these)
  run/             the guarded trainer's folder: checkpoints, loss_log.jsonl, weights_final.pt, TRAINING_MANIFEST.json
  runner.log, service_events.jsonl (hash-chained)
The runner is a separate detached process: closing the Reader does not stop training, and a restart resumes from the last checkpoint.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import policy

ROOT = Path(__file__).resolve().parents[4]
TOOL = ROOT / "tools" / "tr1_train"
REQUIRED = ("state_dir", "tiles_dir", "torch_python")
DEFAULTS = dict(epochs=6, lr=0.005, init=None, init_trained=True, threads=2, batch=2, ckpt_every_iters=50, attempt_wall_s=6 * 3600, max_rss_mb=4096,
                require_ac=True, min_free_memory_mb=2500, min_free_disk_mb=4000, daily_budget_s=0, max_attempts=12)
STALE_AFTER_S = 45


def default_state_dir():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share"))) / "PIDReader" / "training" / "tr1"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf8"))
    except (OSError, ValueError):
        return default


def write_json(path, value, strict=True):
    """Atomic write. On Windows os.replace is denied while another process (the status reader) has the target open, so it retries briefly; the runner
    passes strict=False so a status file that cannot be replaced right now never stops training (the next heartbeat rewrites it)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    for attempt in range(40):
        try:
            tmp.write_text(json.dumps(value, indent=1), encoding="utf8")
            os.replace(tmp, path)
            return True
        except PermissionError:
            time.sleep(0.05)
        except OSError:
            if strict:
                raise
            return False
    if strict:
        raise PermissionError(f"could not replace {path}")
    return False


def validate(cfg):
    """List of problems that stop a start (empty = ok)."""
    problems = [f"missing {k}" for k in REQUIRED if not cfg.get(k)]
    if problems:
        return problems
    if "onedrive" in str(cfg["state_dir"]).lower():
        problems.append("state_dir must be outside OneDrive (checkpoints are large and written often)")
    if not Path(cfg["torch_python"]).is_file():
        problems.append("torch_python does not exist (the optional torch environment is not installed)")
    if not (Path(cfg["tiles_dir"]) / "TILES_MANIFEST.json").is_file():
        problems.append("tiles_dir has no TILES_MANIFEST.json (prepare tiles first)")
    if cfg.get("init") and not Path(cfg["init"]).is_file():
        problems.append("init weights file does not exist")
    if not (TOOL / "run_training.py").is_file():
        problems.append("tools/tr1_train is missing (training runs from a source checkout only)")
    c = dict(DEFAULTS, **cfg)
    if not 1 <= c["threads"] <= 4:
        problems.append("threads must be 1..4")
    if not 1 <= c["epochs"] <= 200:
        problems.append("epochs must be 1..200")
    if not 0 <= c["daily_budget_s"] <= 24 * 3600:
        problems.append("daily_budget_s must be 0 (no cap) .. 86400")
    if not 512 <= c["max_rss_mb"] <= 12000:
        problems.append("max_rss_mb out of range")
    return problems


def status(state_dir):
    """One dict the GUI/CLI can show. Reads files only; never blocks."""
    state_dir = Path(state_dir)
    s = read_json(state_dir / "service.json")
    if s is None:
        return dict(state="NOT_STARTED", alive=False, message="No training run has been started.")
    alive = policy.pid_alive(s.get("pid"))
    age = None
    try:
        beat = datetime.fromisoformat(s["heartbeat_utc"])
        age = (datetime.now(timezone.utc) - beat).total_seconds()
        boot = policy.boot_time()
        if alive and boot is not None and beat.timestamp() < boot - 5:          # last heard from before the computer started: the pid now belongs to something else
            alive = False
    except (KeyError, ValueError):
        pass
    out = dict(s, alive=alive, heartbeat_age_s=age, controls=dict(pause=(state_dir / "PAUSE").exists(), cancel=(state_dir / "CANCEL").exists()),
               progress=read_json(state_dir / "progress.json", {}), budget=read_json(state_dir / "budget.json", {}))
    if s.get("state") in ("STARTING", "RUNNING", "PAUSING", "PAUSED", "WAITING", "STOPPING", "CANCELLING") and not alive:
        out["state"] = "STOPPED_UNEXPECTEDLY"
        out["message"] = "The runner is no longer running (computer restarted or the process ended). Start again to resume from the last checkpoint."
    return out


def default_config(state_dir=None):
    """The settings a one-click Start uses when there is no previous run: continue from the repo's E5 weights on the newest prepared tiles."""
    tiles = sorted((p for p in Path("C:/PIDWork/tr1").glob("tiles*") if (p / "TILES_MANIFEST.json").is_file()), key=lambda p: p.stat().st_mtime) if Path("C:/PIDWork/tr1").exists() else []
    return dict(state_dir=str(state_dir or default_state_dir()), tiles_dir=str(tiles[-1]) if tiles else r"C:\PIDWork\tr1\tiles",
                torch_python=os.environ.get("PIDLAB_TR1_PYTHON", r"C:\PIDWork\venv312_torch\Scripts\python.exe"), init=str(ROOT / "models" / "E5_weights_epoch_02.pt"), init_trained=True)


def last_config(state_dir):
    """The frozen settings of the previous run in this folder (what 'Start' repeats), or None."""
    c = read_json(Path(state_dir) / "config.json")
    return {k: v for k, v in c.items() if not k.startswith("_")} if c else None


TRAY_INFO = default_state_dir().parent / "tray.json"


def tray_running():
    return policy.pid_alive((read_json(TRAY_INFO, {}) or {}).get("pid"))


def ensure_tray(state_dir=None, python=None):
    """Start the notification-area icon (a separate detached process) unless it is already running. Returns True if it was launched."""
    if os.environ.get("PID_TRAINER_NO_TRAY") or tray_running():            # the env switch is for tests: they must never open a real icon
        return False
    exe = Path(python or sys.executable)
    if os.name == "nt" and exe.with_name("pythonw.exe").is_file():
        exe = exe.with_name("pythonw.exe")
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""))
    cmd = [str(exe), "-m", "pid_reader.ui.training_tray", "--state-dir", str(state_dir or default_state_dir())]
    kw = dict(cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    if os.name == "nt":
        base = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        try:
            subprocess.Popen(cmd, creationflags=base | 0x01000000, **kw)
        except OSError:
            subprocess.Popen(cmd, creationflags=base, **kw)
    else:
        subprocess.Popen(cmd, start_new_session=True, **kw)
    return True


def archive_finished_run(state):
    """A COMPLETED run is kept (never deleted) and a new Start begins a fresh one."""
    state = Path(state)
    n = 1
    while (state / f"run.completed.{n}").exists():
        n += 1
    for name, target in (("run", f"run.completed.{n}"), ("run.events.jsonl", f"run.completed.{n}.events.jsonl"), ("progress.json", f"run.completed.{n}.progress.json")):
        if (state / name).exists():
            os.replace(state / name, state / target)


def start(cfg, python=None, tray=True):
    """Spawn the detached runner. Raises ValueError for an invalid config and RuntimeError if a run is already active."""
    problems = validate(cfg)
    if problems:
        raise ValueError("; ".join(problems))
    state = Path(cfg["state_dir"])
    state.mkdir(parents=True, exist_ok=True)
    cur = status(state)
    if cur.get("alive") and cur.get("state") in ("STARTING", "RUNNING", "PAUSING", "PAUSED", "WAITING", "STOPPING", "CANCELLING"):
        raise RuntimeError(f"a training run is already {cur['state']}")
    if cur.get("state") == "COMPLETED":
        archive_finished_run(state)
    frozen = dict(DEFAULTS, **cfg)
    write_json(state / "config.json", frozen)
    for name in ("CANCEL", "PAUSE", "ATTEMPT_CANCEL"):
        try:
            (state / name).unlink()
        except FileNotFoundError:
            pass
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""), PYTHONUNBUFFERED="1")
    cmd = [python or sys.executable, "-m", "pid_reader.engineering.trainer_service.runner", str(state / "config.json")]
    log = open(state / "runner.log", "ab")
    kw = {}
    if os.name == "nt":
        base = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        kw["creationflags"] = base | 0x01000000                                  # CREATE_BREAKAWAY_FROM_JOB: survive the parent's job object
        try:
            proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True, **kw)
        except OSError:
            proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True, creationflags=base)
    else:
        proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True, start_new_session=True)
    write_json(state / "service.json", dict(state="STARTING", pid=proc.pid, started_utc=now(), heartbeat_utc=now(), attempts=0))
    launched = False
    if tray:
        try:
            launched = ensure_tray(state)
        except OSError:
            launched = False                                            # the icon is a convenience; training must start regardless
    return dict(pid=proc.pid, state_dir=str(state), tray_launched=launched)


ACTIVE_STATES = ("STARTING", "RUNNING", "PAUSING", "PAUSED", "WAITING", "STOPPING", "CANCELLING")


def resume_if_interrupted(state_dir, python=None, tray=True):
    """For the 'resume after reboot' scheduled task. Restarts a run ONLY if it was cut off (restart, crash, logoff) while it was meant to be going.
    It never starts a new run, and never overrides the user: a paused, cancelled, completed, failed or never-started run is left alone."""
    state = Path(state_dir)
    cur = status(state)
    if cur.get("state") == "NOT_STARTED":
        return dict(action="none", reason="no run has been started")
    stored = (read_json(state / "service.json") or {}).get("state")
    gone = not cur.get("alive")
    if stored not in ACTIVE_STATES:
        return dict(action="none", reason=f"the last run ended as {stored}; nothing to resume")
    if not gone:
        return dict(action="none", reason="the runner is already running")
    if (state / "PAUSE").exists() or stored in ("PAUSING", "PAUSED"):
        return dict(action="none", reason="you paused this run; it stays paused until you resume it")
    if (state / "CANCEL").exists() or stored in ("STOPPING", "CANCELLING"):
        return dict(action="none", reason="you stopped this run; it stays stopped")
    cfg = last_config(state)
    if not cfg:
        return dict(action="none", reason="no saved settings to resume from")
    try:
        out = start(cfg, python=python, tray=tray)
    except (ValueError, RuntimeError) as exc:
        return dict(action="none", reason=f"could not resume: {exc}")
    return dict(action="resumed", **out)


def pause(state_dir):
    (Path(state_dir) / "PAUSE").write_text(now(), encoding="utf8")


def resume(state_dir):
    try:
        (Path(state_dir) / "PAUSE").unlink()
    except FileNotFoundError:
        pass


def cancel(state_dir):
    """Stop for good: the runner finishes the current checkpoint-safe stop and exits with state CANCELLED (the checkpoints are kept)."""
    (Path(state_dir) / "CANCEL").write_text(now(), encoding="utf8")


def wait_for(state_dir, states, timeout=30.0, poll=0.2):
    """Test/CLI helper: wait until status()['state'] is one of `states`."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = status(state_dir)
        if s.get("state") in states:
            return s
        time.sleep(poll)
    return status(state_dir)
