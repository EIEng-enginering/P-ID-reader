"""Faster R-CNN (torchvision MobileNetV3-Large FPN) fine-tuning on tiles, CPU only, deterministic and resumable.

This is the Grok E5 training method (``experiments/e5_train.py``, seed 20261110) made portable and restartable:
  * no Linux-only modules (peak memory is read with psapi on Windows);
  * paths and the starting weights are arguments (``--init`` a torchvision COCO checkpoint, or ``none`` for a random start, used by the tests);
  * full-state checkpoints every ``--ckpt-every-iters`` iterations (model, optimiser, scheduler, both random generators, the position inside the
    epoch), written atomically, so a run killed at any moment resumes from the last checkpoint and ends with the SAME weights as an uninterrupted run;
  * an optional soft wall budget (``--max-wall-s``) that checkpoints and stops cleanly. The hard limits live in ``run_training.py`` (guard).

Usage (normally started by run_training.py):
    python train_frcnn.py --tiles-dir DIR --out-dir DIR [--init PATH|none] [--resume CKPT] [--epochs 2] [--limit-tiles N]
Tiles: ``TILES_MANIFEST.json`` {classes, splits: {train: [{tile, boxes: [[x0,y0,x1,y1,label_index_from_1]]}]}} plus the PNG tiles (see prepare_tiles.py).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
import time

import numpy as np
import torch
from PIL import Image

SEED = 20261110
DEFAULTS = {"seed": SEED, "epochs": 2, "batch": 2, "lr": 0.02, "momentum": 0.9, "wd": 1e-4, "warmup_iters": 100, "threads": 6, "size": 800,
            "hflip_p": 0.5, "scale_jitter": [0.7, 1.4]}


def sha256_file(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def peak_mb() -> float | None:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [(n, ctypes.c_size_t) for n in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi")
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        return round(pmc.PeakWorkingSetSize / 2 ** 20, 1) if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb) else None
    import resource
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def atomic_save(obj, path: str) -> None:
    tmp = path + ".tmp"
    torch.save(obj, tmp)
    os.replace(tmp, path)


def sample(tiles_dir: str, rec: dict, rng: random.Random, cfg: dict):
    """One augmented training sample (Grok E5 augmentation, unchanged): optional horizontal flip, log-uniform scale jitter by crop or white pad."""
    im = np.asarray(Image.open(os.path.join(tiles_dir, rec["tile"])).convert("L"), dtype=np.float32) / 255.0
    b = torch.tensor([x[:4] for x in rec["boxes"]], dtype=torch.float32).reshape(-1, 4)
    lab = torch.tensor([x[4] for x in rec["boxes"]], dtype=torch.int64)
    if rng.random() < cfg["hflip_p"]:
        im = im[:, ::-1].copy()
        w = im.shape[1]
        if len(b):
            b = torch.stack([w - b[:, 2], b[:, 1], w - b[:, 0], b[:, 3]], 1)
    s = math.exp(rng.uniform(math.log(cfg["scale_jitter"][0]), math.log(cfg["scale_jitter"][1])))
    win = int(round(cfg["size"] / s))
    h, w = im.shape
    if win <= min(h, w):
        x0, y0 = rng.randint(0, w - win), rng.randint(0, h - win)
        im = im[y0:y0 + win, x0:x0 + win]
        if len(b):
            o = b.clone()
            b[:, [0, 2]] = (b[:, [0, 2]] - x0).clamp(0, win)
            b[:, [1, 3]] = (b[:, [1, 3]] - y0).clamp(0, win)
            keep = ((b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])) >= 0.6 * ((o[:, 2] - o[:, 0]) * (o[:, 3] - o[:, 1]))
            b, lab = b[keep], lab[keep]
    else:
        pad = np.ones((max(win, h), max(win, w)), dtype=np.float32)
        pad[:h, :w] = im
        im = pad
    return torch.from_numpy(np.ascontiguousarray(im))[None].repeat(3, 1, 1), {"boxes": b.reshape(-1, 4), "labels": lab}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiles-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--lr", type=float, default=DEFAULTS["lr"], help="peak learning rate (default unchanged: 0.02; use ~0.005 or lower when continuing from trained weights)")
    ap.add_argument("--init-trained", action="store_true", help="--init is a checkpoint of THIS model (5-class head), e.g. the E5 weights: swap the head first, then load it, so training continues instead of restarting from COCO")
    ap.add_argument("--init", default="none", help="torchvision COCO checkpoint (fasterrcnn_mobilenet_v3_large_fpn-fb6a3cc7.pth) or 'none'")
    ap.add_argument("--resume")
    ap.add_argument("--epochs", type=int, default=DEFAULTS["epochs"])
    ap.add_argument("--batch", type=int, default=DEFAULTS["batch"])
    ap.add_argument("--threads", type=int, default=DEFAULTS["threads"])
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--size", type=int, default=DEFAULTS["size"])
    ap.add_argument("--limit-tiles", type=int, default=0, help="use only the first N training tiles (tests)")
    ap.add_argument("--ckpt-every-iters", type=int, default=100)
    ap.add_argument("--max-wall-s", type=float, default=0.0, help="soft budget: checkpoint and stop cleanly (0 = none)")
    ap.add_argument("--debug-sleep-per-iter", type=float, default=0.0, help="test hook: sleep after each iteration")
    a = ap.parse_args(argv)
    cfg = dict(DEFAULTS, seed=a.seed, epochs=a.epochs, batch=a.batch, threads=a.threads, size=a.size, lr=a.lr, init_trained=bool(a.init_trained))
    t0 = time.monotonic()
    torch.manual_seed(cfg["seed"])
    random.seed(cfg["seed"])
    torch.set_num_threads(cfg["threads"])
    torch.use_deterministic_algorithms(True, warn_only=True)
    man_path = os.path.join(a.tiles_dir, "TILES_MANIFEST.json")
    man = json.load(open(man_path, encoding="utf-8"))
    classes, recs = man["classes"], man["splits"]["train"]
    if a.limit_tiles:
        recs = recs[:a.limit_tiles]
    data_sha = sha256_file(man_path)
    cfg_run = dict(cfg, limit_tiles=a.limit_tiles, init=a.init if a.init == "none" else sha256_file(a.init)[:16])
    from torchvision.models.detection import fasterrcnn_mobilenet_v3_large_fpn
    from torchvision.models.detection.faster_rcnn import FastRCNNPredictor
    model = fasterrcnn_mobilenet_v3_large_fpn(weights=None, weights_backbone=None, min_size=cfg["size"], max_size=cfg["size"], box_detections_per_img=300)
    if a.init != "none" and not a.init_trained:
        model.load_state_dict(torch.load(a.init, map_location="cpu", weights_only=True))
    model.roi_heads.box_predictor = FastRCNNPredictor(model.roi_heads.box_predictor.cls_score.in_features, len(classes) + 1)
    if a.init != "none" and a.init_trained:
        model.load_state_dict(torch.load(a.init, map_location="cpu", weights_only=True))
    opt = torch.optim.SGD([p for p in model.parameters() if p.requires_grad], lr=cfg["lr"], momentum=cfg["momentum"], weight_decay=cfg["wd"])
    steps_per_epoch = math.ceil(len(recs) / cfg["batch"])
    n_it = steps_per_epoch * cfg["epochs"]
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda i: min(1.0, (i + 1) / cfg["warmup_iters"]) * 0.5 * (1 + math.cos(math.pi * i / n_it)))
    start_ep, start_step, it, rng_state, torch_state = 0, 0, 0, None, None
    if a.resume:
        ck = torch.load(a.resume, map_location="cpu", weights_only=False)
        if ck["data_sha256"] != data_sha or ck["cfg"] != cfg_run:
            print("RESUME_REFUSED: checkpoint was made with different data or settings", file=sys.stderr)
            return 3
        model.load_state_dict(ck["model"])
        opt.load_state_dict(ck["opt"])
        sched.load_state_dict(ck["sched"])
        start_ep, start_step, it, rng_state, torch_state = ck["epoch"], ck["step"], ck["iter"], ck["rng_state"], ck["torch_state"]
        torch.set_rng_state(torch_state)
    os.makedirs(a.out_dir, exist_ok=True)
    log = open(os.path.join(a.out_dir, "loss_log.jsonl"), "a", encoding="utf-8")
    json.dump({"cfg": cfg_run, "tiles_manifest_sha256": data_sha, "classes": classes, "n_train_tiles": len(recs), "torch": torch.__version__,
               "platform": sys.platform}, open(os.path.join(a.out_dir, "train_config.json"), "w"), indent=1, sort_keys=True)

    def checkpoint(name: str, ep: int, step: int, rng: random.Random) -> str:
        path = os.path.join(a.out_dir, name)
        atomic_save({"model": model.state_dict(), "opt": opt.state_dict(), "sched": sched.state_dict(), "epoch": ep, "step": step, "iter": it,
                     "cfg": cfg_run, "data_sha256": data_sha, "rng_state": rng.getstate() if step else None, "torch_state": torch.get_rng_state()}, path)
        return path

    status, last_ckpt = "COMPLETED", None
    model.train()
    for ep in range(start_ep, cfg["epochs"]):
        rng = random.Random(cfg["seed"] * 1000 + ep)
        order = list(range(len(recs)))
        rng.shuffle(order)
        first = start_step if ep == start_ep else 0
        if ep == start_ep and rng_state is not None:
            rng.setstate(rng_state)                      # same augmentation draws as the uninterrupted run
        tl = []
        for s in range(first, len(order), cfg["batch"]):
            xs, ts = zip(*[sample(a.tiles_dir, recs[k], rng, cfg) for k in order[s:s + cfg["batch"]]])
            ld = model(list(xs), list(ts))
            loss = sum(ld.values())
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()
            it += 1
            rec = {"iter": it, "epoch": ep + 1, "lr": opt.param_groups[0]["lr"], "loss": float(loss.detach())} | {k: float(v.detach()) for k, v in ld.items()}
            log.write(json.dumps(rec) + "\n")
            log.flush()
            tl.append(rec["loss"])
            nxt = s + cfg["batch"]
            if a.debug_sleep_per_iter:
                time.sleep(a.debug_sleep_per_iter)
            if a.ckpt_every_iters and it % a.ckpt_every_iters == 0 and nxt < len(order):
                last_ckpt = checkpoint("ckpt_latest.pt", ep, nxt, rng)
            if a.max_wall_s and time.monotonic() - t0 > a.max_wall_s:
                last_ckpt = checkpoint("ckpt_latest.pt", ep, nxt, rng) if nxt < len(order) else checkpoint("ckpt_latest.pt", ep + 1, 0, rng)
                status = "STOPPED_WALL_BUDGET"
                break
        if status != "COMPLETED":
            break
        last_ckpt = checkpoint("ckpt_latest.pt", ep + 1, 0, rng)
        atomic_save(model.state_dict(), os.path.join(a.out_dir, f"weights_epoch_{ep + 1:02d}.pt"))
        print(json.dumps({"epoch": ep + 1, "iters": it, "mean_loss": sum(tl) / max(1, len(tl)), "wall_s": round(time.monotonic() - t0, 1), "peak_mb": peak_mb()}), flush=True)
    final = None
    if status == "COMPLETED":
        final = os.path.join(a.out_dir, "weights_final.pt")
        atomic_save(model.state_dict(), final)
    log.close()
    json.dump({"status": status, "iters": it, "final_weights": os.path.basename(final) if final else None, "final_weights_sha256": sha256_file(final) if final else None,
               "latest_checkpoint": os.path.basename(last_ckpt) if last_ckpt else None, "tiles_manifest_sha256": data_sha, "cfg": cfg_run,
               "wall_s": round(time.monotonic() - t0, 1), "peak_working_set_mb": peak_mb(), "torch": torch.__version__, "platform": sys.platform,
               "label": "LOCAL_CPU_TRAINING (research candidate; not validated on owner drawings)"},
              open(os.path.join(a.out_dir, "TRAINING_MANIFEST.json"), "w"), indent=1, sort_keys=True)
    print("DONE", status, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
