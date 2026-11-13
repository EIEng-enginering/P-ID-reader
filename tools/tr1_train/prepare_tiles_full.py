"""Training tiles from ALL usable PID2Graph plans (the full-data counterpart of prepare_tiles.py, which only sampled a slice).

    python prepare_tiles_full.py <pid2graph_extract_root> <out_dir> [--real-per-plan 40] [--synthetic-per-plan 12]

<extract_root> holds ``PID2Graph/Complete/{Dataset PID, PID2Graph Synthetic, PID2Graph OPEN100}``.

* Train: every Dataset PID plan except the held-out ones, plus every Synthetic plan.
* Held out (never trained on): ``PID2Graph OPEN100`` (the authors' test set) and a second check set of real Dataset PID plans: plans >= 70 spaced every 17th
  (70, 87, 104, ... 495; 26 plans). They are taken from plans >= 70 because the earlier models (E5 and trainer run 1) were trained on plans 0-69, so these plans are unseen by
  every model made so far and a comparison on them is fair. They are listed in the manifest under ``holdout_plans`` and a few validation tiles are cut from them.
* Tiles are centred on objects chosen CLASS-BALANCED (a class is picked first, then an object of that class), so the rare and weak classes (``general``, ``arrow``) are not
  drowned out by valves and instruments; every 4th tile of a plan is at a random place so background is learned too. Deterministic: seed 20261110, same files -> same tiles.
* tank / pump are folded into ``general``; connector / crossing / border nodes are not symbols (same as prepare_tiles.py). A box is kept when at least 60% of it is inside the tile (unchanged).
PID2Graph: Sturmer, Graumann, Koch (DLR), CC BY-SA 4.0, doi 10.5281/zenodo.14803338.
"""
import argparse
import glob
import hashlib
import json
import os
import random
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tr1train import SEED                    # noqa: E402
from tr1train import pid2graph as P          # noqa: E402

Image.MAX_IMAGE_PIXELS = None
CLASSES = ["valve", "instrumentation", "general", "arrow"]
LABEL_MAP = {"tank": "general", "pump": "general"}
TILE = 800
HOLDOUT_FROM, HOLDOUT_EVERY = 70, 17


def plans(src, sub):
    fs = sorted(glob.glob(os.path.join(src, "PID2Graph/Complete", sub, "*.graphml")), key=lambda f: int(os.path.basename(f).split(".")[0]))
    return [(f, next(g for g in (f[:-8] + ".png", f[:-8] + ".jpg") if os.path.exists(g))) for f in fs]


def plan_index(graphml):
    return int(os.path.basename(graphml).split(".")[0])


def is_holdout(idx):
    return idx >= HOLDOUT_FROM and (idx - HOLDOUT_FROM) % HOLDOUT_EVERY == 0


def tiles_for_plan(rnd, im, objs, n_tiles):
    """Yield (x0, y0) crop origins: class-balanced object-centred, with every 4th at a random place."""
    H, W = im.shape
    by_class = {}
    for o in objs:
        by_class.setdefault(o["label"], []).append(o)
    classes = sorted(by_class)
    for k in range(n_tiles):
        if classes and k % 4 != 3:
            o = rnd.choice(by_class[rnd.choice(classes)])
            cx, cy = (o["box"][0] + o["box"][2]) / 2, (o["box"][1] + o["box"][3]) / 2
            x0 = int(min(max(0, cx - rnd.uniform(100, TILE - 100)), max(0, W - TILE)))
            y0 = int(min(max(0, cy - rnd.uniform(100, TILE - 100)), max(0, H - TILE)))
        else:
            x0, y0 = rnd.randint(0, max(0, W - TILE)), rnd.randint(0, max(0, H - TILE))
        yield x0, y0


def main(src, out, real_per_plan=40, synthetic_per_plan=12, validation_per_plan=10):
    os.makedirs(out, exist_ok=False)
    rnd = random.Random(SEED)
    dataset = plans(src, "Dataset PID")
    splits = {"train": [p for p in dataset if not is_holdout(plan_index(p[0]))] + plans(src, "PID2Graph Synthetic"),
              "validation": [p for p in dataset if is_holdout(plan_index(p[0]))]}
    rel = lambda p: os.path.relpath(p, os.path.join(src, "PID2Graph/Complete")).replace(os.sep, "/")
    man = {"classes": CLASSES, "tile": TILE, "seed": SEED, "splits": {}, "source_files": {}, "holdout_plans": [rel(p[1]) for p in splits["validation"]],
           "sampling": "class-balanced object-centred, every 4th tile random"}
    for split, ps in splits.items():
        recs = []
        for g, imgp in ps:
            man["source_files"][rel(imgp)] = hashlib.sha256(open(imgp, "rb").read()).hexdigest()
            im = np.asarray(Image.open(imgp).convert("L"))
            objs = [dict(n, label=LABEL_MAP.get(n["label"], n["label"])) for n in P.read(g)[0] if n["box"]]
            objs = [n for n in objs if n["label"] in CLASSES]
            n_t = validation_per_plan if split == "validation" else (real_per_plan if "Dataset PID" in g else synthetic_per_plan)
            for x0, y0 in tiles_for_plan(rnd, im, objs, n_t):
                crop = im[y0:y0 + TILE, x0:x0 + TILE]
                bx = []
                for o in objs:
                    a = o["box"]
                    c = [max(a[0], x0), max(a[1], y0), min(a[2], x0 + TILE), min(a[3], y0 + TILE)]
                    if c[2] <= c[0] or c[3] <= c[1]:
                        continue
                    frac = (c[2] - c[0]) * (c[3] - c[1]) / max(1e-6, (a[2] - a[0]) * (a[3] - a[1]))
                    if frac >= 0.6:
                        bx.append([c[0] - x0, c[1] - y0, c[2] - x0, c[3] - y0, CLASSES.index(o["label"]) + 1])
                name = f"{split}_{len(recs):05d}.png"
                Image.fromarray(crop).save(os.path.join(out, name))
                recs.append({"tile": name, "source": rel(imgp), "origin": [x0, y0], "boxes": bx})
        man["splits"][split] = recs
        print(split, len(recs), "tiles", flush=True)
    path = os.path.join(out, "TILES_MANIFEST.json")
    with open(path, "w", encoding="utf-8", newline="") as f:
        json.dump(man, f, indent=1)
    sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
    counts = {c: sum(1 for r in man["splits"]["train"] for b in r["boxes"] if b[4] == i + 1) for i, c in enumerate(CLASSES)}
    print({s: len(v) for s, v in man["splits"].items()}, "train boxes per class:", counts, "holdout plans:", len(man["holdout_plans"]), "manifest sha256:", sha)
    return sha


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--real-per-plan", type=int, default=40)
    ap.add_argument("--synthetic-per-plan", type=int, default=12)
    a = ap.parse_args()
    main(a.src, a.out, a.real_per_plan, a.synthetic_per_plan)
