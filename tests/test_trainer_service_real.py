"""The background service driving the REAL guarded TR1 trainer (torch component) on synthetic tiles, including a pause/resume in the middle."""
import json
import time
from pathlib import Path

from test_tr1_trainer_tool import TORCH_PY, needs_torch, tiles

from pid_reader.engineering.trainer_service import service


@needs_torch
def test_real_trainer_through_the_service_with_a_pause_and_resume(tmp_path):
    d = tiles(tmp_path, 4)
    state = tmp_path / "state"
    cfg = dict(state_dir=str(state), tiles_dir=str(d), torch_python=TORCH_PY, epochs=2, threads=2, batch=2, lr=0.02, init=None, init_trained=False, ckpt_every_iters=1,
               daily_budget_s=0, require_ac=False, min_free_memory_mb=1, min_free_disk_mb=1, attempt_wall_s=900)
    service.start(cfg)
    s = service.wait_for(state, ("RUNNING",), timeout=30)
    assert s["state"] == "RUNNING"
    t0 = time.time()
    while time.time() - t0 < 240 and not (state / "run" / "ckpt_latest.pt").exists():      # wait for the first checkpoint, then pause
        time.sleep(0.3)
    service.pause(state)
    assert service.wait_for(state, ("PAUSED",), timeout=120)["state"] == "PAUSED"
    service.resume(state)
    final = service.wait_for(state, ("COMPLETED", "FAILED"), timeout=600)
    assert final["state"] == "COMPLETED", final
    manifest = json.loads((state / "run" / "TRAINING_MANIFEST.json").read_text())
    assert manifest["status"] == "COMPLETED" and manifest["iters"] == 4
    assert Path(final["result"]["weights"]).is_file() and final["result"]["candidate_only"] is True
    assert final["progress"]["iter"] == 4
