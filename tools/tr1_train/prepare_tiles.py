"""Deterministic 800x800 training tiles from the PID2Graph 'Complete' folders (the Grok E5 data preparation, unchanged in method).

    python prepare_tiles.py <pid2graph_extract_root> <out_dir>

<extract_root> holds ``PID2Graph/Complete/{Dataset PID, PID2Graph Synthetic, PID2Graph OPEN100}``. Train = Dataset PID plans 0-69 + all Synthetic plans;
validation = Dataset PID plans 70-79; OPEN100 is never touched here (it is the held-out source). tank / pump are folded into ``general`` as in
Dataset PID. Seed 20261110. Running it twice on the same files gives byte-identical tiles and manifest. The manifest records source files by RELATIVE path, so its
sha256 differs from Grok's E5 manifest (02361e7f..., which recorded absolute Linux paths); compare the ``splits`` section and the tile PNGs instead.
PID2Graph: Sturmer, Graumann, Koch (DLR), CC BY-SA 4.0, doi 10.5281/zenodo.14803338.
"""
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


def plans(src: str, sub: str):
    fs = sorted(glob.glob(os.path.join(src, "PID2Graph/Complete", sub, "*.graphml")), key=lambda f: int(os.path.basename(f).split(".")[0]))
    return [(f, next(g for g in (f[:-8] + ".png", f[:-8] + ".jpg") if os.path.exists(g))) for f in fs]


def main(src: str, out: str, n_dataset: int = 20, n_synthetic: int = 3) -> str:
    os.makedirs(out, exist_ok=False)
    rnd = random.Random(SEED)
    dataset = plans(src, "Dataset PID")
    splits = {"train": [p for p in dataset if int(os.path.basename(p[0]).split(".")[0]) < 70] + plans(src, "PID2Graph Synthetic"),
              "validation": [p for p in dataset if int(os.path.basename(p[0]).split(".")[0]) >= 70]}
    man = {"classes": CLASSES, "tile": TILE, "seed": SEED, "splits": {}, "source_files": {}}
    for split, ps in splits.items():
        recs = []
        for g, imgp in ps:
            man["source_files"][os.path.relpath(imgp, os.path.join(src, "PID2Graph/Complete")).replace(os.sep, "/")] = hashlib.sha256(open(imgp, "rb").read()).hexdigest()
            im = np.asarray(Image.open(imgp).convert("L"))
            H, W = im.shape
            objs = [dict(n, label=LABEL_MAP.get(n["label"], n["label"])) for n in P.read(g)[0] if n["box"]]
            objs = [n for n in objs if n["label"] in CLASSES]
            n_t = n_dataset if "Dataset PID" in g else n_synthetic
            for k in range(n_t):
                if objs and k < n_t - 1:
                    o = rnd.choice(objs)
                    cx, cy = (o["box"][0] + o["box"][2]) / 2, (o["box"][1] + o["box"][3]) / 2
                    x0 = int(min(max(0, cx - rnd.uniform(100, TILE - 100)), max(0, W - TILE)))
                    y0 = int(min(max(0, cy - rnd.uniform(100, TILE - 100)), max(0, H - TILE)))
                else:
                    x0, y0 = rnd.randint(0, max(0, W - TILE)), rnd.randint(0, max(0, H - TILE))
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
                recs.append({"tile": name, "source": os.path.relpath(imgp, os.path.join(src, "PID2Graph/Complete")).replace(os.sep, "/"), "origin": [x0, y0], "boxes": bx})
        man["splits"][split] = recs
    path = os.path.join(out, "TILES_MANIFEST.json")
    with open(path, "w", encoding="utf-8", newline="") as f:
        json.dump(man, f, indent=1)
    sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
    print({s: len(v) for s, v in man["splits"].items()}, "train boxes:", sum(len(r["boxes"]) for r in man["splits"]["train"]), "manifest sha256:", sha)
    return sha


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
