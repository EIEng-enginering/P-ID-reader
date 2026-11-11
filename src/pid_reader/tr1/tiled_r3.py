"""R3 tiled inference with cached raw per-tile outputs and selectable merge policies (E6-05). tiled.py (R1) is left unchanged.
Policies:
  r1_drop_inner_edge : exactly the R1 rule (drop any box within 2 px of an inner tile edge, then class-wise NMS).
  edge_safe          : complete-view boxes first; an inner-edge box is dropped only if a same-class complete box covers it
                       (intersection/min-area >= 0.5); surviving edge fragments of the same class from different tiles that overlap
                       are united (seam stitching) and flagged edge_partial=True; final class-wise NMS.  Nothing is declared connected.
  edge_safe+coarse   : edge_safe plus one coarse pass (image downscaled by `coarse_factor`, same 800 px tiles => ~1280 px windows) whose
                       boxes larger than `coarse_min_px` (original px) are added before the final NMS (large-object recovery).
Raw outputs are numpy so they can be cached (npz) and re-merged without re-running the model."""
import numpy as np

def tiles(W, H, tile=800, overlap=200):
    xs = list(range(0, max(1, W - overlap), tile - overlap)); ys = list(range(0, max(1, H - overlap), tile - overlap)); out = []
    for y in ys:
        for x in xs:
            x0, y0 = min(x, max(0, W - tile)), min(y, max(0, H - tile)); out.append((x0, y0, min(W, x0 + tile), min(H, y0 + tile)))
    return sorted(set(out))

def torch_model_fn(model):
    import torch
    def fn(crops):
        with torch.no_grad():
            outs = model([torch.from_numpy(np.ascontiguousarray(c))[None].repeat(3, 1, 1) for c in crops])
        return [(o["boxes"].numpy(), o["scores"].numpy(), o["labels"].numpy()) for o in outs]
    model.eval(); return fn

def raw_tiles(model_fn, img, tile=800, overlap=200, score_min=0.05, batch=4):
    H, W = img.shape; T = tiles(W, H, tile, overlap); rec = []
    for i in range(0, len(T), batch):
        chunk = T[i:i + batch]
        for (x0, y0, x1, y1), (b, s, l) in zip(chunk, model_fn([img[y0:y1, x0:x1] for x0, y0, x1, y1 in chunk])):
            k = s >= score_min; b = b[k].astype(np.float64).copy(); b[:, [0, 2]] += x0; b[:, [1, 3]] += y0
            rec.append({"tile": (x0, y0, x1, y1), "boxes": b, "scores": s[k].astype(np.float64), "labels": l[k].astype(np.int64)})
    return {"W": W, "H": H, "tile": tile, "overlap": overlap, "score_min": score_min, "tiles": rec}

def _edge_mask(b, t, W, H, m=2):
    x0, y0, x1, y1 = t; e = np.zeros(len(b), bool)
    if x0 > 0: e |= b[:, 0] <= x0 + m
    if y0 > 0: e |= b[:, 1] <= y0 + m
    if x1 < W: e |= b[:, 2] >= x1 - m
    if y1 < H: e |= b[:, 3] >= y1 - m
    return e

def nms(b, s, l, iou=0.5):
    import torch, torchvision
    if len(b) == 0: return np.zeros(0, np.int64)
    return torchvision.ops.batched_nms(torch.from_numpy(b).double(), torch.from_numpy(s).double(), torch.from_numpy(l), iou).numpy()

def _iomin(a, b):
    ix = np.clip(np.minimum(a[2], b[:, 2]) - np.maximum(a[0], b[:, 0]), 0, None); iy = np.clip(np.minimum(a[3], b[:, 3]) - np.maximum(a[1], b[:, 1]), 0, None)
    inter = ix * iy; aa = (a[2] - a[0]) * (a[3] - a[1]); bb = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1]); return inter / np.maximum(1e-9, np.minimum(aa, bb))

def merge(raw, policy="r1_drop_inner_edge", iou=0.5, coarse=None, coarse_min_px=250):
    W, H = raw["W"], raw["H"]; B, S, L, E, TI = [], [], [], [], []
    for ti, t in enumerate(raw["tiles"]):
        e = _edge_mask(t["boxes"], t["tile"], W, H); B.append(t["boxes"]); S.append(t["scores"]); L.append(t["labels"]); E.append(e); TI.append(np.full(len(e), ti))
    if not B: return []
    B, S, L, E, TI = (np.concatenate(x) if x else x for x in (B, S, L, E, TI))
    B = B.reshape(-1, 4)
    if policy == "r1_drop_inner_edge":
        k = ~E; b, s, l = B[k], S[k], L[k]; keep = nms(b, s, l, iou)
        return [(*b[j].tolist(), float(s[j]), int(l[j]), False) for j in keep]
    assert policy in ("edge_safe", "edge_safe+coarse")
    kc = ~E; cb, cs, cl = B[kc], S[kc], L[kc]; keep = nms(cb, cs, cl, iou); cb, cs, cl = cb[keep], cs[keep], cl[keep]
    eb, es, el, et = B[E], S[E], L[E], TI[E]; surv = []
    for j in range(len(eb)):
        same = cl == el[j]
        if same.any() and (_iomin(eb[j], cb[same]) >= 0.5).any(): continue
        surv.append(j)
    eb, es, el, et = eb[surv], es[surv], el[surv], et[surv]
    # seam stitching: union overlapping same-class fragments that come from DIFFERENT tiles (greedy by score)
    order = np.argsort(-es, kind="stable"); used = np.zeros(len(eb), bool); fb, fs, fl = [], [], []
    for j in order:
        if used[j]: continue
        used[j] = True; box = eb[j].copy(); grp = [j]; changed = True
        while changed:
            changed = False
            for q in np.where(~used & (el == el[j]))[0]:
                if et[q] in {et[g] for g in grp}: continue
                if _iomin(box, eb[q:q + 1])[0] > 0.0 and _iomin(box, eb[q:q + 1])[0] >= 0.3:
                    box = np.array([min(box[0], eb[q, 0]), min(box[1], eb[q, 1]), max(box[2], eb[q, 2]), max(box[3], eb[q, 3])]); used[q] = True; grp.append(q); changed = True
        fb.append(box); fs.append(es[j]); fl.append(el[j])
    fb = np.array(fb).reshape(-1, 4); fs = np.array(fs, dtype=np.float64); fl = np.array(fl, dtype=np.int64)
    ab = np.concatenate([cb, fb]); as_ = np.concatenate([cs, fs]); al = np.concatenate([cl, fl]); part = np.concatenate([np.zeros(len(cb), bool), np.ones(len(fb), bool)])
    if policy == "edge_safe+coarse" and coarse is not None:
        cm = merge(coarse, "edge_safe", iou); f = coarse["factor"]
        big = [d for d in cm if max(d[2] - d[0], d[3] - d[1]) / f >= coarse_min_px]
        if big:
            gb = np.array([[d[0] / f, d[1] / f, d[2] / f, d[3] / f] for d in big]); ab = np.concatenate([ab, gb]); as_ = np.concatenate([as_, [d[4] for d in big]])
            al = np.concatenate([al, [d[5] for d in big]]); part = np.concatenate([part, [bool(d[6]) for d in big]])
    keep = nms(ab, as_, al, iou)
    return [(*ab[j].tolist(), float(as_[j]), int(al[j]), bool(part[j])) for j in keep]

def save_raw(path, raw):
    d = {"meta": np.array([raw["W"], raw["H"], raw["tile"], raw["overlap"]], dtype=np.float64), "score_min": np.array([raw["score_min"]]), "factor": np.array([raw.get("factor", 1.0)])}
    for i, t in enumerate(raw["tiles"]):
        d[f"t{i}_xy"] = np.array(t["tile"], dtype=np.int64); d[f"t{i}_b"] = t["boxes"]; d[f"t{i}_s"] = t["scores"]; d[f"t{i}_l"] = t["labels"]
    np.savez_compressed(path, **d)

def load_raw(path):
    z = np.load(path); W, H, tile, ov = z["meta"]; n = sum(1 for k in z.files if k.endswith("_xy"))
    return {"W": int(W), "H": int(H), "tile": int(tile), "overlap": int(ov), "score_min": float(z["score_min"][0]), "factor": float(z["factor"][0]),
            "tiles": [{"tile": tuple(int(v) for v in z[f"t{i}_xy"]), "boxes": z[f"t{i}_b"].reshape(-1, 4), "scores": z[f"t{i}_s"], "labels": z[f"t{i}_l"]} for i in range(n)]}
