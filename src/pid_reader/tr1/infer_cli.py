"""Offline learned-symbol detector (TR1 / E5). Runs in the OPTIONAL torch component, never inside the app process.

Stand-alone file on purpose: it is started by path with the torch interpreter, so it must not import ``pid_reader`` (the app environment and
the torch environment are separate). Needs torch + torchvision (CPU), pypdfium2, numpy and Pillow. No network access.

    python infer_cli.py <model_card.json> <weights.pt> <input.pdf|png|jpg> [--page N] [--out result.json] [--threads N] [--max-pixels N]
                        [--merge-policy r1_drop_inner_edge|edge_safe|edge_safe+coarse] [--fine-card CARD.json --fine-weights FINE.pt]

The weights file is checked against the model card's sha256 BEFORE it is loaded; a mismatch refuses to run. Output is PROPOSED detections only
(``review_state`` PROPOSED; a score below the card's frozen threshold is ``WEAK_CLASS_WITHHELD``); this program never writes accepted data.
The detection method (tiling, thresholds, NMS, ids) is the Grok E5 method unchanged; only the page-size guard and the diagnostics block are new.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

import numpy as np

SCHEMA = "tr1-frcnn-candidates-1"
DEFAULT_MAX_PIXELS = 150_000_000        # a float32 page above this would need > 600 MB for the image alone


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def peak_working_set_mb() -> float | None:
    """Peak memory of this process: Windows working set via psapi, otherwise the resource module (Linux, macOS)."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [(n, ctypes.c_size_t) for n in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            return round(pmc.PeakWorkingSetSize / 2 ** 20, 1)
        return None
    try:
        import resource
        kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(kb / (1024 if sys.platform != "darwin" else 1024 * 1024), 1)
    except Exception:
        return None


def tiles(width: int, height: int, tile: int = 800, overlap: int = 200) -> list[tuple[int, int, int, int]]:
    xs = list(range(0, max(1, width - overlap), tile - overlap))
    ys = list(range(0, max(1, height - overlap), tile - overlap))
    out = []
    for y in ys:
        for x in xs:
            x0, y0 = min(x, max(0, width - tile)), min(y, max(0, height - tile))
            out.append((x0, y0, min(width, x0 + tile), min(height, y0 + tile)))
    return sorted(set(out))


def predict_gray(model, img: np.ndarray, tile: int = 800, overlap: int = 200, score_min: float = 0.05, iou: float = 0.5, batch: int = 4):
    """img: HxW float32 in [0, 1] (1 = white). Returns (x0, y0, x1, y1, score, label) in image pixels; a box touching an inner tile edge is
    dropped because the neighbouring tile sees that symbol whole."""
    import torch
    import torchvision
    height, width = img.shape
    grid = tiles(width, height, tile, overlap)
    boxes, scores, labels = [], [], []
    model.eval()
    with torch.no_grad():
        for i in range(0, len(grid), batch):
            chunk = grid[i:i + batch]
            xs = [torch.from_numpy(np.ascontiguousarray(img[y0:y1, x0:x1]))[None].repeat(3, 1, 1) for x0, y0, x1, y1 in chunk]
            for (x0, y0, x1, y1), out in zip(chunk, model(xs)):
                keep = out["scores"] >= score_min
                b = out["boxes"][keep].clone()
                b[:, [0, 2]] += x0
                b[:, [1, 3]] += y0
                inside = torch.ones(len(b), dtype=torch.bool)
                if x0 > 0:
                    inside &= b[:, 0] > x0 + 2
                if y0 > 0:
                    inside &= b[:, 1] > y0 + 2
                if x1 < width:
                    inside &= b[:, 2] < x1 - 2
                if y1 < height:
                    inside &= b[:, 3] < y1 - 2
                boxes.append(b[inside])
                scores.append(out["scores"][keep][inside])
                labels.append(out["labels"][keep][inside])
    if not boxes:
        return [], len(grid)
    b_all, s_all, l_all = torch.cat(boxes), torch.cat(scores), torch.cat(labels)
    kept = torchvision.ops.batched_nms(b_all, s_all, l_all, iou)
    return [(*b_all[j].tolist(), float(s_all[j]), int(l_all[j])) for j in kept], len(grid)


COARSE_FACTOR = 0.625        # R3 edge_safe+coarse: the page is also scanned downscaled by this factor (800 px tiles then cover 1280 px windows)
COARSE_MIN_PX = 250          # only coarse boxes larger than this (original px) are added


def detect_tiles(model, img, card: dict, policy: str):
    """Detections as (x0, y0, x1, y1, score, label, edge_partial) and the number of tiles scanned.
    ``r1_drop_inner_edge`` is the R1 rule through the unchanged ``predict_gray``; the other policies are the Grok R3 ``tiled_r3`` merge."""
    if policy == "r1_drop_inner_edge":
        dets, n = predict_gray(model, img, card["tile"], card["overlap"], 0.05)
        return [(*d, False) for d in dets], n
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import tiled_r3 as T
    from PIL import Image
    fn = T.torch_model_fn(model)
    raw = T.raw_tiles(fn, img, card["tile"], card["overlap"], 0.05)
    n = len(raw["tiles"])
    coarse = None
    if policy == "edge_safe+coarse":
        pil = Image.fromarray(np.clip(np.rint(img * 255.0), 0, 255).astype(np.uint8))
        small = pil.resize((max(1, round(pil.size[0] * COARSE_FACTOR)), max(1, round(pil.size[1] * COARSE_FACTOR))), Image.BILINEAR)
        coarse = T.raw_tiles(fn, np.asarray(small, dtype=np.float32) / 255.0, card["tile"], card["overlap"], 0.05)
        coarse["factor"] = COARSE_FACTOR
        n += len(coarse["tiles"])
    return T.merge(raw, policy, 0.5, coarse, COARSE_MIN_PX), n


def classify_fine(img: np.ndarray, boxes: list, coarse_classes: list, fine_card_path: str, fine_weights_path: str) -> list:
    """Fine subtype PROPOSAL per box (Grok R3 E6-09): MobileNetV3-small on a 64x64 grey crop, decoding restricted to the fine ids whose parent is the
    detector coarse class, abstaining below tau. Ids are the numeric Dataset-P&ID ids; their names are unverified."""
    import torch
    from PIL import Image
    from torch import nn
    from torchvision.models import mobilenet_v3_small
    with open(fine_card_path, encoding="utf-8") as f:
        fc = json.load(f)
    if sha256_file(fine_weights_path) != fc["weights_sha256"]:
        raise SystemExit("FINE_WEIGHTS_SHA256_MISMATCH: the fine-class weights differ from their card; refusing to load them")
    ck = torch.load(fine_weights_path, map_location="cpu", weights_only=True)
    ids = ck["fine_ids"]
    net = mobilenet_v3_small(weights=None)
    net.classifier[3] = nn.Linear(net.classifier[3].in_features, len(ids))
    net.load_state_dict(ck["state_dict"])
    net.eval()
    parent = {int(k): v for k, v in ck["parent"].items()}
    page = Image.fromarray(np.clip(np.rint(img * 255.0), 0, 255).astype(np.uint8))
    size, pad_f, tau = int(fc["size"]), float(fc["pad_fraction"]), float(fc["tau"])
    mean = torch.tensor([0.485, 0.456, 0.406])[None, :, None, None]
    std = torch.tensor([0.229, 0.224, 0.225])[None, :, None, None]
    out = []
    with torch.no_grad():
        for (x0, y0, x1, y1), coarse in zip(boxes, coarse_classes):
            p = pad_f * max(x1 - x0, y1 - y0)
            crop = np.array(page.crop((int(x0 - p), int(y0 - p), int(x1 + p), int(y1 + p))).resize((size, size), Image.BILINEAR), dtype=np.uint8)
            x = (torch.from_numpy(crop).float().div(255)[None, None].repeat(1, 3, 1, 1) - mean) / std
            logits = net(x)[0]
            allowed = torch.tensor([parent[i] == coarse for i in ids])
            if not allowed.any():
                out.append({"subtype_id": None, "confidence": None, "status": "ABSTAINED", "reason": "no fine id under this coarse class", "names": "unverified"})
                continue
            logits = logits.masked_fill(~allowed, -1e9)
            pr = torch.softmax(logits, 0)
            conf, k = pr.max(0)
            ok = float(conf) >= tau
            out.append({"subtype_id": int(ids[int(k)]) if ok else None, "confidence": round(float(conf), 4), "status": "PROPOSED" if ok else "ABSTAINED",
                        "model": fc["model_id"], "names": "unverified"})
    return out


def load(card_path: str, weights_path: str):
    import torch
    from torchvision.models.detection import fasterrcnn_mobilenet_v3_large_fpn
    from torchvision.models.detection.faster_rcnn import FastRCNNPredictor
    with open(card_path, encoding="utf-8") as f:
        card = json.load(f)
    if sha256_file(weights_path) != card["weights_sha256"]:
        raise SystemExit("WEIGHTS_SHA256_MISMATCH: the weights file differs from the model card; refusing to load it")
    model = fasterrcnn_mobilenet_v3_large_fpn(weights=None, weights_backbone=None, min_size=card["min_size"], max_size=card["max_size"],
                                              box_detections_per_img=card.get("detections_per_img", 300))
    model.roi_heads.box_predictor = FastRCNNPredictor(model.roi_heads.box_predictor.cls_score.in_features, len(card["classes"]) + 1)
    model.load_state_dict(torch.load(weights_path, map_location="cpu", weights_only=True))
    model.eval()
    return model, card


def image_of(path: str, card: dict, page: int, max_pixels: int):
    """Grey page as float32 plus the render scale really used (reduced, and reported, if the page would exceed ``max_pixels``)."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    notes = []
    if path.lower().endswith(".pdf"):
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(open(path, "rb").read())
        if not 1 <= page <= len(pdf):
            raise SystemExit(f"PAGE_OUT_OF_RANGE: the file has {len(pdf)} page(s)")
        pg = pdf[page - 1]
        w_pt, h_pt = pg.get_size()
        scale = float(card["pdf_render_scale"])
        if w_pt * h_pt * scale * scale > max_pixels:
            reduced = (max_pixels / (w_pt * h_pt)) ** 0.5
            notes.append(f"RENDER_SCALE_REDUCED {scale:g} -> {reduced:.3f}: the page would exceed {max_pixels:,} pixels; symbol sizes differ from training")
            scale = reduced
        pil = pg.render(scale=scale, grayscale=True).to_pil().convert("L")
    else:
        pil = Image.open(path).convert("L")
        scale = 1.0
        if card.get("raster_norm_width"):
            scale = card["raster_norm_width"] / pil.size[0]
            pil = pil.resize((card["raster_norm_width"], round(pil.size[1] * scale)), Image.BILINEAR)
    return np.asarray(pil, dtype=np.float32) / 255.0, scale, notes


def run(card_path: str, weights_path: str, path: str, page: int = 1, threads: int | None = None, max_pixels: int = DEFAULT_MAX_PIXELS,
        merge_policy: str = "r1_drop_inner_edge", fine_card: str | None = None, fine_weights: str | None = None) -> dict:
    import torch
    t_start = time.perf_counter()
    torch.set_num_threads(threads or max(1, (os.cpu_count() or 2) - 1))
    model, card = load(card_path, weights_path)
    img, scale, notes = image_of(path, card, page, max_pixels)
    height, width = img.shape
    t_loaded = time.perf_counter()
    dets, n_tiles = detect_tiles(model, img, card, merge_policy)
    t_done = time.perf_counter()
    ordered = sorted(dets, key=lambda d: (-d[4], d[0], d[1]))
    fine = None
    if fine_card and fine_weights and ordered:
        fine = classify_fine(img, [d[:4] for d in ordered], [card["classes"][d[5] - 1] for d in ordered], fine_card, fine_weights)
    t_fine = time.perf_counter()
    doc = sha256_file(path)
    out = []
    for n_, (x0, y0, x1, y1, s, label, partial) in enumerate(ordered):
        cls = card["classes"][label - 1]
        nb = {"x0": round(x0 / width, 6), "y0": round(y0 / height, 6), "x1": round(x1 / width, 6), "y1": round(y1 / height, 6)}
        cid = "frc-" + hashlib.sha256(json.dumps([doc, page, nb, cls]).encode()).hexdigest()[:24]
        out.append({"id": cid, "page": page, "bbox": nb, "catalogue_class": cls, "raw_score": round(s, 4), "score_kind": "UNCALIBRATED_FRCNN_SOFTMAX",
                    "confidence_status": "LEADING" if s >= card["threshold"] else "WEAK_CLASS_WITHHELD", "review_state": "PROPOSED",
                    "evidence": {"producer": card["producer"], "weights_sha256": card["weights_sha256"], "truth_class": "MODEL_PROPOSAL"}})
        if merge_policy != "r1_drop_inner_edge":
            out[-1]["edge_partial"] = bool(partial)            # a box stitched across a tile seam: still only a proposal
        if fine is not None:
            out[-1]["fine"] = fine[n_]
    return {"schema": SCHEMA, "source_sha256": doc, "page": page, "model": card["model_id"], "threshold": card["threshold"],
            "limitations": card["limitations"], "candidates": out,
            "diagnostics": {"render_scale": round(scale, 4), "image_px": [width, height], "tiles": n_tiles, "load_s": round(t_loaded - t_start, 3),
                            "detect_s": round(t_done - t_loaded, 3), "fine_s": round(t_fine - t_done, 3) if fine is not None else None,
                            "merge_policy": merge_policy, "fine_class": bool(fine is not None), "wall_s": round(time.perf_counter() - t_start, 3), "peak_working_set_mb": peak_working_set_mb(),
                            "torch": torch.__version__, "threads": torch.get_num_threads(), "notes": notes}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Offline TR1 learned-symbol detector (PROPOSED detections only)")
    ap.add_argument("card")
    ap.add_argument("weights")
    ap.add_argument("input")
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--out")
    ap.add_argument("--threads", type=int)
    ap.add_argument("--max-pixels", type=int, default=DEFAULT_MAX_PIXELS)
    ap.add_argument("--merge-policy", default="r1_drop_inner_edge", choices=("r1_drop_inner_edge", "edge_safe", "edge_safe+coarse"))
    ap.add_argument("--fine-card")
    ap.add_argument("--fine-weights")
    a = ap.parse_args(argv)
    result = run(a.card, a.weights, a.input, a.page, a.threads, a.max_pixels, a.merge_policy, a.fine_card, a.fine_weights)
    text = json.dumps(result, indent=1, sort_keys=True)
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
