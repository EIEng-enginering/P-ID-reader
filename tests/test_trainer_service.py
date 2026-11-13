"""Background training service: detached runner, pause/resume/cancel, policy waits, daily budget, low priority. Uses a fake trainer (no torch)."""
import json
import os
import sys
import textwrap
import time
from pathlib import Path

import pytest

from pid_reader.engineering.trainer_service import policy, service

FAKE = textwrap.dedent('''
    import json, sys, time
    from pathlib import Path
    out = Path(sys.argv[1]); steps = int(sys.argv[2]); delay = float(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    start = int((out / "ckpt_latest.pt").read_text()) if (out / "ckpt_latest.pt").exists() else 0
    (out / "train_config.json").write_text(json.dumps({"n_train_tiles": steps * 2}))
    with open(out / "loss_log.jsonl", "a") as log:
        for i in range(start + 1, steps + 1):
            time.sleep(delay)
            log.write(json.dumps({"iter": i, "epoch": 1, "loss": 1.0 / i}) + "\\n"); log.flush()
            (out / "ckpt_latest.pt").write_text(str(i))
    (out / "weights_final.pt").write_bytes(b"w")
    (out / "TRAINING_MANIFEST.json").write_text(json.dumps({"status": "COMPLETED", "iters": steps, "final_weights": "weights_final.pt", "final_weights_sha256": "ab" * 32}))
''')


def cfg_for(tmp_path, steps=60, delay=0.05, **kw):
    script = tmp_path / "fake_trainer.py"
    script.write_text(FAKE)
    tiles = tmp_path / "tiles"
    tiles.mkdir(exist_ok=True)
    (tiles / "TILES_MANIFEST.json").write_text("{}")
    state = tmp_path / "state"
    c = dict(state_dir=str(state), tiles_dir=str(tiles), torch_python=sys.executable, epochs=1, batch=2, daily_budget_s=0, _fast=True,
             _command=[sys.executable, str(script), str(state / "run"), str(steps), str(delay)], min_free_memory_mb=1, min_free_disk_mb=1, require_ac=False, attempt_wall_s=600)
    c.update(kw)
    return c


def stop_all(state):
    service.cancel(state)
    service.wait_for(state, ("CANCELLED", "COMPLETED", "FAILED", "STOPPED_UNEXPECTEDLY"), timeout=20)


def lines(state):
    return (Path(state) / "run" / "loss_log.jsonl").read_text().splitlines()


def test_runs_to_completion_in_a_detached_process_and_reports_progress(tmp_path):
    cfg = cfg_for(tmp_path, steps=40, delay=0.03)
    info = service.start(cfg)
    assert info["pid"] != os.getpid()
    final = service.wait_for(cfg["state_dir"], ("COMPLETED", "FAILED"), timeout=60)
    assert final["state"] == "COMPLETED", final
    assert final["result"]["candidate_only"] is True and Path(final["result"]["weights"]).is_file()
    assert final["progress"]["iter"] == 40 and final["progress"]["iters_total"] is not None


def test_pause_stops_the_trainer_and_resume_continues_from_the_checkpoint(tmp_path):
    cfg = cfg_for(tmp_path, steps=200, delay=0.05)
    state = cfg["state_dir"]
    service.start(cfg)
    service.wait_for(state, ("RUNNING",), timeout=20)
    time.sleep(1.5)
    service.pause(state)
    s = service.wait_for(state, ("PAUSED",), timeout=30)
    assert s["state"] == "PAUSED" and s["controls"]["pause"] is True
    n = len(lines(state))
    paused_at = json.loads(lines(state)[-1])["iter"]
    time.sleep(1.0)
    assert len(lines(state)) == n, "the trainer kept working while paused"
    service.resume(state)
    final = service.wait_for(state, ("COMPLETED", "FAILED"), timeout=90)
    assert final["state"] == "COMPLETED", final
    iters = [json.loads(x)["iter"] for x in lines(state)]
    assert paused_at < 200 and max(iters) == 200
    assert len(set(iters)) == 200                                  # every iteration present: resume continued, it did not restart from zero


def test_cancel_keeps_the_checkpoint_and_ends_the_runner(tmp_path):
    cfg = cfg_for(tmp_path, steps=400, delay=0.05)
    state = cfg["state_dir"]
    info = service.start(cfg)
    service.wait_for(state, ("RUNNING",), timeout=20)
    time.sleep(1.0)
    service.cancel(state)
    s = service.wait_for(state, ("CANCELLED",), timeout=30)
    assert s["state"] == "CANCELLED"
    assert (Path(state) / "run" / "ckpt_latest.pt").is_file()
    t0 = time.time()
    while policy.pid_alive(info["pid"]) and time.time() - t0 < 10:
        time.sleep(0.2)
    assert not policy.pid_alive(info["pid"])


def test_a_blocked_resource_policy_waits_instead_of_training(tmp_path):
    cfg = cfg_for(tmp_path, min_free_disk_mb=10 ** 9)
    state = cfg["state_dir"]
    service.start(cfg)
    s = service.wait_for(state, ("WAITING",), timeout=20)
    assert s["state"] == "WAITING" and s["reason"] == "LOW_FREE_DISK"
    assert not (Path(state) / "run").exists()
    stop_all(state)


def test_the_daily_budget_stops_training_and_the_runner_waits(tmp_path):
    cfg = cfg_for(tmp_path, steps=2000, delay=0.05, daily_budget_s=2)
    state = cfg["state_dir"]
    service.start(cfg)
    s = service.wait_for(state, ("WAITING",), timeout=40)
    assert s["state"] == "WAITING" and s["reason"] == "DAILY_BUDGET_REACHED"
    assert (Path(state) / "run" / "ckpt_latest.pt").is_file()
    assert s["budget"]["used_s"] >= 2
    stop_all(state)


def test_the_runner_runs_at_below_normal_priority(tmp_path):
    if os.name != "nt":
        pytest.skip("Windows priority classes")
    cfg = cfg_for(tmp_path, steps=400, delay=0.05)
    state = cfg["state_dir"]
    service.start(cfg)
    service.wait_for(state, ("RUNNING",), timeout=20)
    time.sleep(0.5)
    runner_pid = service.status(state)["pid"]                     # the runner records its own pid (a venv python.exe is only a launcher)
    k = policy._kernel32()
    h = k.OpenProcess(0x1000, False, runner_pid)
    try:
        assert k.GetPriorityClass(h) == 0x4000
    finally:
        k.CloseHandle(h)
    stop_all(state)


def test_the_default_has_no_daily_compute_limit():
    assert service.DEFAULTS["daily_budget_s"] == 0


def test_a_dead_runner_is_reported_as_stopped_unexpectedly(tmp_path):
    state = tmp_path / "s"
    state.mkdir()
    service.write_json(state / "service.json", dict(state="RUNNING", pid=999999, heartbeat_utc=service.now()))
    s = service.status(state)
    assert s["state"] == "STOPPED_UNEXPECTEDLY" and s["alive"] is False
    assert service.status(tmp_path / "none")["state"] == "NOT_STARTED"


def test_validation_refuses_unsafe_or_incomplete_configs(tmp_path):
    good = cfg_for(tmp_path)
    assert service.validate(good) == []
    assert any("OneDrive" in p for p in service.validate(dict(good, state_dir="C:/Users/x/OneDrive - Co/training")))
    assert any("TILES_MANIFEST" in p for p in service.validate(dict(good, tiles_dir=str(tmp_path / "missing"))))
    assert any("torch_python" in p for p in service.validate(dict(good, torch_python=str(tmp_path / "no.exe"))))
    assert any("threads" in p for p in service.validate(dict(good, threads=16)))
    with pytest.raises(ValueError):
        service.start(dict(good, tiles_dir=str(tmp_path / "missing")))


def test_a_second_start_while_running_is_refused(tmp_path):
    cfg = cfg_for(tmp_path, steps=600, delay=0.05)
    state = cfg["state_dir"]
    service.start(cfg)
    service.wait_for(state, ("RUNNING",), timeout=20)
    with pytest.raises(RuntimeError, match="already"):
        service.start(cfg)
    stop_all(state)


@pytest.fixture(autouse=False)
def keep_test_hooks(monkeypatch):
    """last_config() hides the underscore test hooks (the fake trainer command); these tests need them to survive the round trip."""
    monkeypatch.setattr(service, "last_config", lambda state: service.read_json(Path(state) / "config.json"))


def _cut_off_run(tmp_path, stored="RUNNING", **kw):
    """A run whose runner is gone (as after a reboot): its saved settings and a service.json that still says it was going."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    c = cfg_for(tmp_path, steps=40, delay=0.02, **kw)
    state = Path(c["state_dir"])
    state.mkdir(parents=True, exist_ok=True)
    service.write_json(state / "config.json", dict(service.DEFAULTS, **c))
    service.write_json(state / "service.json", dict(state=stored, pid=999999, heartbeat_utc=service.now()))
    return state


def test_resume_if_interrupted_restarts_a_run_that_was_cut_off_and_it_finishes(tmp_path, keep_test_hooks):
    state = _cut_off_run(tmp_path)
    out = service.resume_if_interrupted(state, tray=False)
    assert out["action"] == "resumed"
    assert service.wait_for(state, ("COMPLETED", "FAILED"), timeout=60)["state"] == "COMPLETED"
    again = service.resume_if_interrupted(state, tray=False)               # finished: nothing to do, and no fresh run is begun
    assert again["action"] == "none" and "COMPLETED" in again["reason"]


def test_resume_if_interrupted_leaves_alone_everything_the_user_or_the_run_ended(tmp_path):
    assert service.resume_if_interrupted(tmp_path / "never", tray=False)["action"] == "none"          # never started
    for stored in ("COMPLETED", "FAILED", "CANCELLED"):
        state = _cut_off_run(tmp_path / stored, stored=stored)
        assert service.resume_if_interrupted(state, tray=False)["action"] == "none"
    paused = _cut_off_run(tmp_path / "paused", stored="PAUSED")                                         # user paused, then the PC restarted
    assert service.resume_if_interrupted(paused, tray=False)["action"] == "none"
    pause_file = _cut_off_run(tmp_path / "pausefile")
    (pause_file / "PAUSE").write_text("x")
    assert service.resume_if_interrupted(pause_file, tray=False)["action"] == "none"
    cancelling = _cut_off_run(tmp_path / "cancelling", stored="CANCELLING")
    assert service.resume_if_interrupted(cancelling, tray=False)["action"] == "none"


def test_resume_if_interrupted_does_not_touch_a_run_that_is_alive(tmp_path):
    c = cfg_for(tmp_path, steps=2000, delay=0.05)
    service.start(c, tray=False)
    state = Path(c["state_dir"])
    try:
        service.wait_for(state, ("RUNNING",), timeout=20)
        out = service.resume_if_interrupted(state, tray=False)
        assert out["action"] == "none" and "already running" in out["reason"]
    finally:
        stop_all(state)


def test_a_pid_from_before_a_reboot_that_is_now_reused_counts_as_gone(tmp_path, keep_test_hooks):
    state = _cut_off_run(tmp_path)
    service.write_json(state / "service.json", dict(state="RUNNING", pid=os.getpid(), heartbeat_utc="2020-01-01T00:00:00+00:00"))        # a live pid, but last heard from long before this computer started
    assert service.resume_if_interrupted(state, tray=False)["action"] == "resumed"
    stop_all(state)
