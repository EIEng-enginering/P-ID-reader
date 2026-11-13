"""Class-agnostic symbol-localisation baseline on real labelled sheets (ASU test split, YOLO 'Symbol' boxes) for the detectors we already have.

    python eval_symbol_baseline.py --sheets DIR --labels DIR --out OUTDIR [--models tr1,rfdetr]

Detectors: TR1 E5 Faster R-CNN (repo models/, torch env) and the adopted RF-DETR P&ID checkpoint (ML runtime). Both are run on the same sheets; per-sheet raw
outputs are cached in OUTDIR so an interrupted run resumes. Scoring: greedy one-to-one matching by score at IoU >= 0.5; precision/recall at fixed score
thresholds plus average precision (AP@0.5). It measures finding symbol boxes only (not classes, not text, not connectivity), on a public dataset whose labels were
made by its authors; it is a development baseline, not an accuracy claim about the owner's drawings.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TORCH_PY = "C:/PIDWork/venv312_torch/Scripts/python.exe"
ML_PY = Path(os.environ.get("LOCALAPPDATA", "")) / "PIDReader/models/runtime/Scripts/python.exe"
RFDETR_WEIGHTS = Path(os.environ.get("LOCALAPPDATA", "")) / "PIDReader/models/rfdetr/checkpoint_best_total.pth"

RFDETR_SCRIPT = r'''
import json, sys, time
from pathlib import Path
import numpy as np
from PIL import Image
Image.MAX_IMAGE_PIXELS = None
from rfdetr import RFDETRBase
weights, out_dir = sys.argv[1], Path(sys.argv[2]); sheets = sys.argv[3:]
model = RFDETRBase(pretrain_weights=weights, device="cpu")
TILE, STRIDE = 960, 800
def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1])); i = ix * iy
    u = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - i
    return i / u if u > 0 else 0
for s in sheets:
    target = out_dir / (Path(s).stem + ".json")
    if target.exists():
        continue
    t0 = time.time(); im = Image.open(s).convert("RGB"); W, H = im.size
    xs = list(range(0, max(1, W - TILE) + 1, STRIDE)); ys = list(range(0, max(1, H - TILE) + 1, STRIDE))
    if xs[-1] + TILE < W: xs.append(W - TILE)
    if ys[-1] + TILE < H: ys.append(H - TILE)
    boxes = []
    for y in ys:
        for x in xs:
            crop = im.crop((x, y, min(W, x + TILE), min(H, y + TILE)))
            d = model.predict(crop, threshold=0.2)
            for b, c, sc in zip(d.xyxy, d.class_id, d.confidence):
                boxes.append([float(b[0]) + x, float(b[1]) + y, float(b[2]) + x, float(b[3]) + y, float(sc), int(c)])
    boxes.sort(key=lambda b: -b[4]); keep = []
    for b in boxes:
        if all(iou(b[:4], k[:4]) < 0.5 for k in keep):
            keep.append(b)
    target.write_text(json.dumps(dict(size=[W, H], seconds=round(time.time() - t0, 1), boxes=[[b[0]/W, b[1]/H, b[2]/W, b[3]/H, b[4], b[5]] for b in keep])))
    print(Path(s).name, len(keep), "boxes", round(time.time() - t0, 1), "s", flush=True)
'''


def iou(a, b):
    ix, iy = max(0, min(a[2], b[2]) - max(a[0], b[0])), max(0, min(a[3], b[3]) - max(a[1], b[1]))
    i = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u > 0 else 0


def gt_boxes(label_file):
    out = []
    for line in open(label_file):
        p = line.split()
        if len(p) >= 5:
            cx, cy, w, h = map(float, p[1:5])
            out.append([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])
    return out


def match(preds, gts, thr):
    """Greedy one-to-one by score at IoU >= thr. Returns list of (score, is_tp)."""
    used, res = set(), []
    for p in sorted(preds, key=lambda b: -b[4]):
        best, bi = 0.0, -1
        for j, g in enumerate(gts):
            if j in used:
                continue
            v = iou(p[:4], g)
            if v > best:
                best, bi = v, j
        if bi >= 0 and best >= thr:
            used.add(bi)
            res.append((p[4], True))
        else:
            res.append((p[4], False))
    return res


def evaluate(per_sheet, thr=0.5):
    allm, n_gt = [], 0
    for preds, gts in per_sheet:
        allm += match(preds, gts, thr)
        n_gt += len(gts)
    allm.sort(key=lambda x: -x[0])
    tp = fp = 0
    prec, rec = [], []
    for sc, ok in allm:
        tp += ok
        fp += (not ok)
        prec.append(tp / (tp + fp))
        rec.append(tp / n_gt)
    ap, prev = 0.0, 0.0                          # area under the precision envelope
    env = [max(prec[i:]) for i in range(len(prec))] if prec else []
    for p, r in zip(env, rec):
        ap += p * (r - prev)
        prev = r
    table = {}
    for t in (0.3, 0.5, 0.65, 0.8):
        sel = [(s, ok) for s, ok in allm if s >= t]
        k = sum(ok for _, ok in sel)
        table[str(t)] = dict(predictions=len(sel), tp=k, precision=round(k / len(sel), 3) if sel else None, recall=round(k / n_gt, 3))
    return dict(gt_boxes=n_gt, ap50=round(ap, 3), max_recall=round(rec[-1], 3) if rec else 0.0, by_score_threshold=table)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheets", type=Path, required=True)
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--models", default="tr1,rfdetr")
    a = ap.parse_args()
    sheets = sorted(a.sheets.glob("*.jpg"), key=lambda p: int(p.stem) if p.stem.isdigit() else p.stem)
    models = a.models.split(",")
    for m in models:
        (a.out / m).mkdir(parents=True, exist_ok=True)
    if "tr1" in models:
        for s in sheets:
            t = a.out / "tr1" / (s.stem + ".json")
            if t.exists():
                continue
            t0 = time.time()
            subprocess.run([TORCH_PY, str(ROOT / "src/pid_reader/tr1/infer_cli.py"), str(ROOT / "models/E5_MODEL_CARD.json"), str(ROOT / "models/E5_weights_epoch_02.pt"), str(s),
                            "--out", str(t), "--threads", "2"], check=True, capture_output=True)
            print("tr1", s.name, round(time.time() - t0), "s", flush=True)
    if "rfdetr" in models:
        script = a.out / "_rfdetr_run.py"
        script.write_text(RFDETR_SCRIPT, encoding="utf8")
        env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", OMP_NUM_THREADS="2")
        subprocess.run([str(ML_PY), str(script), str(RFDETR_WEIGHTS), str(a.out / "rfdetr")] + [str(s) for s in sheets], check=True, env=env)
    result = dict(label="DEVELOPMENT BASELINE, class-agnostic symbol localisation, public ASU test split", sheets=len(sheets), models={})
    for m in models:
        per = []
        for s in sheets:
            d = json.loads((a.out / m / (s.stem + ".json")).read_text())
            if m == "tr1":
                boxes = [[c["bbox"]["x0"], c["bbox"]["y0"], c["bbox"]["x1"], c["bbox"]["y1"], c["raw_score"], c["catalogue_class"]] for c in d["candidates"]]
            else:
                boxes = d["boxes"]
            per.append((boxes, gt_boxes(str(a.labels / (s.stem + ".txt")))))
        result["models"][m] = evaluate(per)
        if m == "rfdetr":
            result["models"][m]["note"] = "all 32 RF-DETR classes merged; threshold column applies to its confidence"
    (a.out / "baseline_results.json").write_text(json.dumps(result, indent=1), encoding="utf8")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
