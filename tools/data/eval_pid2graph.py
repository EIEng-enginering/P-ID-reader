"""Per-class precision/recall/F1 of a TR1 detector on the held-out real PID2Graph OPEN100 plans (never used for training).

    python eval_pid2graph.py --root "D:/Data P&ID/PID2Graph_zenodo_14803338" --weights W.pt [--card CARD.json] [--plans 12] --out OUTDIR [--tag NAME]

Ground truth = the dataset authors' graphml boxes, mapped exactly as the training tiles are (tank and pump are folded into `general`; connector/crossing/border nodes are not
symbols). A prediction counts when its class matches, its score is at least the card threshold (default 0.65, the detector gate) and IoU >= 0.5; matching is greedy by score,
one-to-one. Per-plan raw detector output is cached in OUTDIR/<tag>/ so reruns are free. This is a development measurement on public data: not an accuracy claim about the owner's drawings.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "tr1_train"))
from tr1train import pid2graph as P  # noqa: E402

TORCH_PY = os.environ.get("PIDLAB_TR1_PYTHON", "C:/PIDWork/venv312_torch/Scripts/python.exe")
CLASSES = ["valve", "instrumentation", "general", "arrow"]
LABEL_MAP = {"tank": "general", "pump": "general"}


def plans(root):
    base = Path(root) / "PID2Graph" / "Complete" / "PID2Graph OPEN100"
    if not base.exists():
        found = glob.glob(str(Path(root) / "**" / "PID2Graph OPEN100"), recursive=True)
        base = Path(found[0]) if found else base
    out = []
    for g in sorted(base.glob("*.graphml"), key=lambda f: int(f.stem) if f.stem.isdigit() else f.stem):
        img = next((g.with_suffix(e) for e in (".png", ".jpg") if g.with_suffix(e).exists()), None)
        if img:
            out.append((g, img))
    return out


def holdout_plans(root, manifest):
    """The extra held-out REAL plans listed by prepare_tiles_full.py under ``holdout_plans`` (never trained on), as (graphml, image) pairs."""
    base = Path(root) / "PID2Graph" / "Complete"
    out = []
    for rel in json.loads(Path(manifest).read_text(encoding="utf8"))["holdout_plans"]:
        img = base / rel
        g = img.with_suffix(".graphml")
        if g.is_file() and img.is_file():
            out.append((g, img))
    return out


def iou(a, b):
    ix, iy = max(0, min(a[2], b[2]) - max(a[0], b[0])), max(0, min(a[3], b[3]) - max(a[1], b[1]))
    i = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u > 0 else 0


def score_plan(preds, gts, thr_score, thr_iou=.5):
    """per-class tp/fp/fn for one plan. preds: [(x0,y0,x1,y1,score,cls)], gts: [(x0,y0,x1,y1,cls)] (same pixel frame)."""
    res = {c: dict(tp=0, fp=0, fn=0) for c in CLASSES}
    used = set()
    for p in sorted([p for p in preds if p[4] >= thr_score], key=lambda p: -p[4]):
        best, bi = 0.0, -1
        for j, g in enumerate(gts):
            if j in used or g[4] != p[5]:
                continue
            v = iou(p[:4], g[:4])
            if v > best:
                best, bi = v, j
        if bi >= 0 and best >= thr_iou:
            used.add(bi)
            res[p[5]]["tp"] += 1
        else:
            res[p[5]]["fp"] += 1
    for j, g in enumerate(gts):
        if j not in used:
            res[g[4]]["fn"] += 1
    return res


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return dict(tp=tp, fp=fp, fn=fn, precision=None if p is None else round(p, 3), recall=None if r is None else round(r, 3), f1=None if f is None else round(f, 3))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--weights", required=True)
    ap.add_argument("--card", default=str(ROOT / "models" / "E5_MODEL_CARD.json"))
    ap.add_argument("--plans", type=int, default=12)
    ap.add_argument("--threshold", type=float, default=0.65)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--out", required=True)
    ap.add_argument("--holdout-manifest", default=None, help="score the extra held-out real plans listed in this TILES_MANIFEST.json instead of OPEN100 (use --plans 100 for all of them)")
    a = ap.parse_args()
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    tag = a.tag or Path(a.weights).stem
    work = Path(a.out) / tag
    work.mkdir(parents=True, exist_ok=True)
    which = "holdout" if a.holdout_manifest else "open100"
    chosen = (holdout_plans(a.root, a.holdout_manifest) if a.holdout_manifest else plans(a.root))[:a.plans]
    if not chosen:
        sys.exit(f"no {which} plans found under --root")
    total = {c: dict(tp=0, fp=0, fn=0) for c in CLASSES}
    per_plan = []
    for g, img in chosen:
        cache = work / (g.stem + ".json")
        if not cache.exists():
            t0 = time.time()
            subprocess.run([TORCH_PY, str(ROOT / "src/pid_reader/tr1/infer_cli.py"), a.card, a.weights, str(img), "--out", str(cache), "--threads", str(a.threads)], check=True, capture_output=True)
            print(g.stem, round(time.time() - t0), "s", flush=True)
        det = json.loads(cache.read_text(encoding="utf8"))
        W, H = Image.open(img).size
        preds = [(c["bbox"]["x0"] * W, c["bbox"]["y0"] * H, c["bbox"]["x1"] * W, c["bbox"]["y1"] * H, c["raw_score"], c["catalogue_class"]) for c in det["candidates"] if c["catalogue_class"] in CLASSES]
        nodes = [dict(n, label=LABEL_MAP.get(n["label"], n["label"])) for n in P.read(str(g))[0] if n["box"]]
        gts = [(n["box"][0], n["box"][1], n["box"][2], n["box"][3], n["label"]) for n in nodes if n["label"] in CLASSES]
        r = score_plan(preds, gts, a.threshold)
        per_plan.append(dict(plan=g.stem, **{c: r[c] for c in CLASSES}))
        for c in CLASSES:
            for k in ("tp", "fp", "fn"):
                total[c][k] += r[c][k]
    both = {k: total["valve"][k] + total["instrumentation"][k] for k in ("tp", "fp", "fn")}
    what = "the extra held-out real Dataset PID plans" if a.holdout_manifest else "OPEN100"
    out = dict(label=f"DEVELOPMENT MEASUREMENT on public PID2Graph {what} (held out from training); not an accuracy claim about the owner's drawings", weights=a.weights, plans=len(chosen),
               score_threshold=a.threshold, iou=0.5, per_class={c: prf(**total[c]) for c in CLASSES}, valve_plus_instrumentation=prf(**both), per_plan=per_plan)
    (Path(a.out) / f"{tag}_{which}_results.json").write_text(json.dumps(out, indent=1), encoding="utf8")
    print(json.dumps({k: out[k] for k in ("plans", "score_threshold", "per_class", "valve_plus_instrumentation")}, indent=1))


if __name__ == "__main__":
    main()
