"""TR1 offline trainer tool (tools/tr1_train): the process-tree guard, the switch, tile preparation and (with the optional torch component) a real
resumable CPU training run. The guard tests use plain Python children and need no torch."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "tr1_train"
sys.path.insert(0, str(TOOL))

from tr1train import SEED                      # noqa: E402
from tr1train.events import EventLog, verify_log   # noqa: E402
from tr1train.guard import run_guarded         # noqa: E402

TORCH_PY = os.environ.get("PIDLAB_TEST_TORCH_PYTHON", r"C:\PIDWork\venv312_torch\Scripts\python.exe")
needs_torch = pytest.mark.skipif(not Path(TORCH_PY).is_file(), reason="optional torch component not installed")


def heartbeat_child(tmp_path: Path, with_grandchild: bool = True) -> tuple[list[str], Path]:
    hb = tmp_path / "heartbeat.txt"
    grand = tmp_path / "grand.py"
    grand.write_text(textwrap.dedent(f"""
        import pathlib, time
        while True:
            pathlib.Path(r"{hb}").write_text(str(time.time()))
            time.sleep(0.1)
    """), encoding="utf-8")
    child = tmp_path / "child.py"
    child.write_text(textwrap.dedent(f"""
        import subprocess, sys, time
        {'subprocess.Popen([sys.executable, r"' + str(grand) + '"])' if with_grandchild else 'pass'}
        time.sleep(120)
    """), encoding="utf-8")
    return [sys.executable, str(child)], hb


def assert_heartbeat_stopped(hb: Path):
    time.sleep(0.6)
    first = hb.read_text()
    time.sleep(1.2)
    assert hb.read_text() == first, "a grandchild process survived the kill"


def test_wall_limit_kills_the_whole_tree_including_grandchildren(tmp_path):
    cmd, hb = heartbeat_child(tmp_path)
    t = time.monotonic()
    res = run_guarded(cmd, max_wall_s=3, poll_s=0.1)
    assert res["state"] == "LIMIT_EXCEEDED" and "wall" in res["reason"] and time.monotonic() - t < 30
    assert res["processes_left_after_kill"] == []
    assert hb.exists()
    assert_heartbeat_stopped(hb)


def test_cancel_file_stops_the_job_and_is_logged_in_a_chained_event_log(tmp_path):
    cmd, hb = heartbeat_child(tmp_path)
    cancel = tmp_path / "CANCEL"
    log = EventLog(str(tmp_path / "job.events.jsonl"))
    threading.Timer(2.0, lambda: cancel.write_text("x")).start()
    res = run_guarded(cmd, max_wall_s=60, cancel_file=str(cancel), events=log, poll_s=0.1)
    assert res["state"] == "CANCELLED" and res["processes_left_after_kill"] == []
    assert_heartbeat_stopped(hb)
    assert verify_log(log.path) and [json.loads(l)["state"] for l in open(log.path)] == ["RUNNING", "CANCELLED"]


def test_memory_limit_kills_the_tree(tmp_path):
    child = tmp_path / "hog.py"
    child.write_text("import time\nx = bytearray(400 * 1024 * 1024)\nfor i in range(0, len(x), 4096):\n    x[i] = 1\ntime.sleep(60)\n", encoding="utf-8")
    res = run_guarded([sys.executable, str(child)], max_wall_s=60, max_rss_mb=200, poll_s=0.1)
    assert res["state"] == "LIMIT_EXCEEDED" and "rss" in res["reason"] and res["peak_tree_rss_mb"] >= 200
    assert res["processes_left_after_kill"] == []


def test_normal_exit_and_failure_are_reported_with_their_return_codes(tmp_path):
    ok = run_guarded([sys.executable, "-c", "print('fine')"], max_wall_s=30, stdout_path=str(tmp_path / "o.log"))
    assert ok["state"] == "COMPLETED" and ok["returncode"] == 0 and "fine" in (tmp_path / "o.log").read_text()
    bad = run_guarded([sys.executable, "-c", "import sys; sys.exit(5)"], max_wall_s=30)
    assert bad["state"] == "FAILED" and bad["returncode"] == 5


@pytest.mark.skipif(os.name != "nt", reason="Job Objects are Windows-only")
def test_if_the_launcher_itself_dies_the_job_object_still_ends_the_child(tmp_path):
    cmd, hb = heartbeat_child(tmp_path)
    launcher = tmp_path / "launcher.py"
    launcher.write_text(textwrap.dedent(f"""
        import os, subprocess, sys, time
        sys.path.insert(0, r"{TOOL}")
        from tr1train.guard import _Job
        job = _Job()
        p = subprocess.Popen({cmd!r}, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        job.assign(p)
        time.sleep(2.5)
        os._exit(0)          # abrupt death of the launcher: no cleanup code runs
    """), encoding="utf-8")
    subprocess.run([sys.executable, str(launcher)], check=True, timeout=60)
    assert hb.exists()
    assert_heartbeat_stopped(hb)


# ------------------------------------------------------------------------------------------------------------------- the launcher
def tiles(tmp_path: Path, n: int = 4) -> Path:
    import numpy as np
    from PIL import Image
    d = tmp_path / "tiles"
    d.mkdir()
    rng = np.random.default_rng(1)
    recs = []
    for i in range(n):
        im = np.full((800, 800), 255, dtype=np.uint8)
        boxes = []
        for _ in range(3):
            x0, y0 = (int(v) for v in rng.integers(40, 650, 2))
            w, h = (int(v) for v in rng.integers(40, 90, 2))
            im[y0:y0 + 3, x0:x0 + w] = 0
            im[y0 + h - 3:y0 + h, x0:x0 + w] = 0
            im[y0:y0 + h, x0:x0 + 3] = 0
            im[y0:y0 + h, x0 + w - 3:x0 + w] = 0
            boxes.append([x0, y0, x0 + w, y0 + h, int(rng.integers(1, 5))])
        Image.fromarray(im).save(d / f"train_{i:05d}.png")
        recs.append({"tile": f"train_{i:05d}.png", "source": "synthetic", "origin": [0, 0], "boxes": boxes})
    (d / "TILES_MANIFEST.json").write_text(json.dumps({"classes": ["valve", "instrumentation", "general", "arrow"], "tile": 800, "seed": SEED,
                                                       "splits": {"train": recs, "validation": []}, "source_files": {}}), encoding="utf-8")
    return d


def run_tool(args: list[str], env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ, **(env_extra or {}))
    return subprocess.run([sys.executable, str(TOOL / "run_training.py"), *args], capture_output=True, text=True, env=env, timeout=900)


def test_launcher_does_nothing_while_the_switch_is_off(tmp_path):
    d = tiles(tmp_path)
    r = run_tool(["--tiles-dir", str(d), "--out-dir", str(tmp_path / "out"), "--python", sys.executable],
                 {"PIDLAB_LOCAL_TRAINER_TR1": "", "PIDLAB_TR1_SETTINGS": str(tmp_path / "none.json")})
    assert r.returncode == 3 and "is off" in r.stderr and not (tmp_path / "out").exists()


def test_launcher_preflight_blocks_unsafe_requests(tmp_path):
    d = tiles(tmp_path)
    env = {"PIDLAB_LOCAL_TRAINER_TR1": "on"}
    r = run_tool(["--tiles-dir", str(tmp_path / "nope"), "--out-dir", str(tmp_path / "o1"), "--python", sys.executable], env)
    assert r.returncode == 2 and "TILES_MANIFEST_MISSING" in r.stdout
    (tmp_path / "o2").mkdir()
    (tmp_path / "o2" / "something").write_text("x")
    r = run_tool(["--tiles-dir", str(d), "--out-dir", str(tmp_path / "o2"), "--python", sys.executable], env)
    assert "OUTPUT_EXISTS" in r.stdout
    r = run_tool(["--tiles-dir", str(d), "--out-dir", str(tmp_path / "o3"), "--python", sys.executable, "--max-wall-s", "0"], env)
    assert "WALL_LIMIT_REQUIRED" in r.stdout
    r = run_tool(["--tiles-dir", str(d), "--out-dir", str(tmp_path / "o4"), "--python", sys.executable, "--resume-latest"], env)
    assert "NO_CHECKPOINT_TO_RESUME" in r.stdout
    assert verify_log(str(tmp_path / "o1") + ".events.jsonl")


@needs_torch
def test_real_training_run_is_resumable_and_ends_with_identical_weights(tmp_path):
    d = tiles(tmp_path, 4)
    env = {"PIDLAB_LOCAL_TRAINER_TR1": "on", "PIDLAB_MODEL_REGISTRY_TR1": "on"}
    common = ["--tiles-dir", str(d), "--python", TORCH_PY, "--epochs", "2", "--threads", "2", "--ckpt-every-iters", "1", "--max-wall-s", "600"]
    a = run_tool([*common, "--out-dir", str(tmp_path / "A"), "--register-registry", str(tmp_path / "reg")], env)
    assert a.returncode == 0, a.stdout + a.stderr
    man_a = json.loads((tmp_path / "A" / "TRAINING_MANIFEST.json").read_text())
    assert man_a["status"] == "COMPLETED" and man_a["iters"] == 4 and man_a["cfg"]["seed"] == SEED == 20261110
    res_a = json.loads((tmp_path / "A" / "RUN_RESULT.json").read_text())
    assert res_a["state"] == "COMPLETED" and res_a["registry_model_id"].startswith("mdl-") and res_a["processes_left_after_kill"] == []
    # run B: stopped part-way by a cancel file once the first mid-run checkpoint exists, then resumed
    out_b = tmp_path / "B"
    cancel = tmp_path / "CANCEL"

    def cancel_when_checkpointed():
        t0 = time.time()
        while time.time() - t0 < 300 and not (out_b / "ckpt_latest.pt").exists():
            time.sleep(0.2)
        time.sleep(0.5)
        cancel.write_text("x")
    threading.Thread(target=cancel_when_checkpointed, daemon=True).start()
    b1 = run_tool([*common, "--out-dir", str(out_b), "--cancel-file", str(cancel), "--debug-sleep-per-iter", "20"], env)
    assert b1.returncode == 1, b1.stdout + b1.stderr
    res_b1 = json.loads((out_b / "RUN_RESULT.json").read_text())
    assert res_b1["state"] == "CANCELLED" and res_b1["resumable_from"] and res_b1["processes_left_after_kill"] == []
    assert not (out_b / "TRAINING_MANIFEST.json").exists()
    b2 = run_tool([*common, "--out-dir", str(out_b), "--resume-latest"], env)
    assert b2.returncode == 0, b2.stdout + b2.stderr
    man_b = json.loads((out_b / "TRAINING_MANIFEST.json").read_text())
    assert man_b["status"] == "COMPLETED" and man_b["iters"] == 4
    assert man_b["final_weights_sha256"] == man_a["final_weights_sha256"], "a resumed run must end with the same weights as an uninterrupted one"


# ---------------------------------------------------------------------------------------------------------- tile preparation
def test_tile_preparation_is_deterministic_and_never_touches_the_held_out_source(tmp_path):
    import numpy as np
    from PIL import Image
    sys.path.insert(0, str(TOOL))
    import prepare_tiles

    def plan(sub, n, w=1200, h=900):
        d = tmp_path / "src" / "PID2Graph" / "Complete" / sub
        d.mkdir(parents=True, exist_ok=True)
        Image.fromarray(np.full((h, w), 255, dtype=np.uint8)).save(d / f"{n}.png")
        (d / f"{n}.graphml").write_text(
            '<?xml version="1.0"?><graphml xmlns="http://graphml.graphdrawing.org/xmlns">'
            '<key id="d0" for="node" attr.name="label" attr.type="string"/><key id="d1" for="node" attr.name="xmin" attr.type="int"/>'
            '<key id="d2" for="node" attr.name="ymin" attr.type="int"/><key id="d3" for="node" attr.name="xmax" attr.type="int"/>'
            '<key id="d4" for="node" attr.name="ymax" attr.type="int"/><graph edgedefault="undirected">'
            '<node id="a"><data key="d0">valve</data><data key="d1">300</data><data key="d2">300</data><data key="d3">360</data><data key="d4">350</data></node>'
            '<node id="b"><data key="d0">tank</data><data key="d1">700</data><data key="d2">400</data><data key="d3">800</data><data key="d4">500</data></node>'
            '</graph></graphml>', encoding="utf-8")
    plan("Dataset PID", 0)
    plan("Dataset PID", 71)
    plan("PID2Graph Synthetic", 5)
    plan("PID2Graph OPEN100", 1)
    m1 = prepare_tiles.main(str(tmp_path / "src"), str(tmp_path / "t1"), n_dataset=3, n_synthetic=2)
    m2 = prepare_tiles.main(str(tmp_path / "src"), str(tmp_path / "t2"), n_dataset=3, n_synthetic=2)
    assert m1 == m2
    man = json.loads((tmp_path / "t1" / "TILES_MANIFEST.json").read_text())
    assert len(man["splits"]["train"]) == 3 + 2 and len(man["splits"]["validation"]) == 3
    assert not any("OPEN100" in r["source"] for s in man["splits"].values() for r in s)
    assert all("OPEN100" not in k for k in man["source_files"])
    h = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    assert [h(p) for p in sorted((tmp_path / "t1").glob("*.png"))] == [h(p) for p in sorted((tmp_path / "t2").glob("*.png"))]
    labels = {b[4] for r in man["splits"]["train"] for b in r["boxes"]}
    assert labels <= {1, 2, 3, 4} and 3 in labels                                        # tank folded into 'general' (3)


@needs_torch
def test_training_can_continue_from_trained_weights_with_a_lower_learning_rate(tmp_path):
    """--init-trained loads a checkpoint of THIS model (5-class head) instead of a COCO one; --lr overrides the default 0.02."""
    d = tiles(tmp_path, 2)
    env = {"PIDLAB_LOCAL_TRAINER_TR1": "on"}
    common = ["--tiles-dir", str(d), "--python", TORCH_PY, "--epochs", "1", "--threads", "2", "--ckpt-every-iters", "1", "--max-wall-s", "600"]
    first = run_tool([*common, "--out-dir", str(tmp_path / "first")], env)
    assert first.returncode == 0, first.stdout + first.stderr
    weights = tmp_path / "first" / "weights_final.pt"
    assert weights.is_file()
    second = run_tool([*common, "--out-dir", str(tmp_path / "second"), "--init", str(weights), "--init-trained", "--lr", "0.002"], env)
    assert second.returncode == 0, second.stdout + second.stderr
    man = json.loads((tmp_path / "second" / "TRAINING_MANIFEST.json").read_text())
    assert man["status"] == "COMPLETED" and man["cfg"]["lr"] == 0.002 and man["cfg"]["init_trained"] is True
    assert man["final_weights_sha256"] != json.loads((tmp_path / "first" / "TRAINING_MANIFEST.json").read_text())["final_weights_sha256"]
    # without --init-trained the same weights are refused (a COCO-shaped model cannot take a 5-class head)
    wrong = run_tool([*common, "--out-dir", str(tmp_path / "third"), "--init", str(weights)], env)
    assert wrong.returncode != 0
