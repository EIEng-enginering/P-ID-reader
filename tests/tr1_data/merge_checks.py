"""Run with the torch component's Python (not collected by pytest): tile-merge policies on authored seam fixtures with a stub detector.
Prints OK and exits 0 when every check passes."""
import json
import os
import random
import sys

import numpy as np
import torch

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "pid_reader", "tr1")
sys.path.insert(0, SRC)
import infer_cli          # noqa: E402
import tiled_r3 as T      # noqa: E402


def world(seed, n=40, W=4000, H=2600, lo=40, hi=700):
    r = random.Random(seed)
    objs = []
    while len(objs) < n:
        w, h = r.randint(lo, hi), r.randint(lo, min(hi, 400))
        x, y = r.randint(0, W - w - 1), r.randint(0, H - h - 1)
        b = (x, y, x + w, y + h)
        if all(min(b[2], o[2]) <= max(b[0], o[0]) or min(b[3], o[3]) <= max(b[1], o[1]) for o in objs):
            objs.append(b)
    return W, H, objs


class StubModel:
    """A perfect detector (score 0.9, label 1) that sees whatever part of an object lies inside the crop it is given; same call shape as torchvision."""

    def __init__(self, objs, W, H, tile=800, overlap=200):
        self.objs, self.order = objs, iter(T.tiles(W, H, tile, overlap))

    def eval(self):
        return self

    def __call__(self, xs):
        out = []
        for _ in xs:
            x0, y0, x1, y1 = next(self.order)
            bs = []
            for o in self.objs:
                c = (max(o[0], x0), max(o[1], y0), min(o[2], x1), min(o[3], y1))
                if c[2] - c[0] >= 1 and c[3] - c[1] >= 1:
                    bs.append([c[0] - x0, c[1] - y0, c[2] - x0, c[3] - y0])
            b = torch.tensor(bs, dtype=torch.float32).reshape(-1, 4)
            out.append({"boxes": b, "scores": torch.full((len(b),), 0.9), "labels": torch.ones(len(b), dtype=torch.int64)})
        return out


def hits(objs, dets, thr=0.5):
    used, tp = set(), 0
    for d in dets:
        for i, o in enumerate(objs):
            if i in used:
                continue
            ix, iy = max(0, min(d[2], o[2]) - max(d[0], o[0])), max(0, min(d[3], o[3]) - max(d[1], o[1]))
            inter = ix * iy
            u = (d[2] - d[0]) * (d[3] - d[1]) + (o[2] - o[0]) * (o[3] - o[1]) - inter
            if u > 0 and inter / u >= thr:
                used.add(i)
                tp += 1
                break
    return tp, len(dets) - tp, len(objs) - tp


card = {"tile": 800, "overlap": 200}
lost_by_r1 = recovered = 0
for seed in (1, 2, 3):
    W, H, objs = world(seed)
    img = np.ones((H, W), np.float32)
    r1, _ = infer_cli.detect_tiles(StubModel(objs, W, H), img, card, "r1_drop_inner_edge")
    frozen, _ = infer_cli.predict_gray(StubModel(objs, W, H), img, 800, 200, 0.05)
    # the R1 policy must be exactly the frozen R1 rule
    assert [d[:6] for d in r1] == [tuple(d) for d in frozen], "r1 policy differs from the frozen R1 predict_gray"
    assert all(d[6] is False for d in r1)
    es, _ = infer_cli.detect_tiles(StubModel(objs, W, H), img, card, "edge_safe")
    tp1, fp1, fn1 = hits(objs, [d[:4] for d in r1])
    tp2, fp2, fn2 = hits(objs, [d[:4] for d in es])
    assert fn2 <= fn1 and fp2 == 0, (seed, fn1, fn2, fp2)
    lost_by_r1 += fn1
    recovered += fn1 - fn2
    assert any(d[6] for d in es) or fn1 == 0
    assert all(abs(d[4] - 0.9) < 1e-6 for d in es)
assert lost_by_r1 > 0 and recovered > 0, "the authored fixtures must contain seam objects the R1 rule loses"

print(json.dumps({"lost_by_r1": lost_by_r1, "recovered_by_edge_safe": recovered}))
print("OK")
