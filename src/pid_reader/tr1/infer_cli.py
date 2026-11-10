"""Offline learned-symbol detector (TR1 / E5). Runs in the OPTIONAL torch component, never inside the app process.

Stand-alone file on purpose: it is started by path with the torch interpreter, so it must not import ``pid_reader`` (the app environment and
the torch environment are separate). Needs torch + torchvision (CPU), pypdfium2, numpy and Pillow. No network access.

    python infer_cli.py <model_card.json> <weights.pt> <input.pdf|png|jpg> [--page N] [--out result.json] [--threads N] [--max-pixels N]

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


def run(card_path: str, weights_path: str, path: str, page: int = 1, threads: int | None = None, max_pixels: int = DEFAULT_MAX_PIXELS) -> dict:
    import torch
    t_start = time.perf_counter()
    torch.set_num_threads(threads or max(1, (os.cpu_count() or 2) - 1))
    model, card = load(card_path, weights_path)
    img, scale, notes = image_of(path, card, page, max_pixels)
    height, width = img.shape
    t_loaded = time.perf_counter()
    dets, n_tiles = predict_gray(model, img, card["tile"], card["overlap"], 0.05)
    t_done = time.perf_counter()
    doc = sha256_file(path)
    out = []
    for x0, y0, x1, y1, s, label in sorted(dets, key=lambda d: (-d[4], d[0], d[1])):
        cls = card["classes"][label - 1]
        nb = {"x0": round(x0 / width, 6), "y0": round(y0 / height, 6), "x1": round(x1 / width, 6), "y1": round(y1 / height, 6)}
        cid = "frc-" + hashlib.sha256(json.dumps([doc, page, nb, cls]).encode()).hexdigest()[:24]
        out.append({"id": cid, "page": page, "bbox": nb, "catalogue_class": cls, "raw_score": round(s, 4), "score_kind": "UNCALIBRATED_FRCNN_SOFTMAX",
                    "confidence_status": "LEADING" if s >= card["threshold"] else "WEAK_CLASS_WITHHELD", "review_state": "PROPOSED",
                    "evidence": {"producer": card["producer"], "weights_sha256": card["weights_sha256"], "truth_class": "MODEL_PROPOSAL"}})
    return {"schema": SCHEMA, "source_sha256": doc, "page": page, "model": card["model_id"], "threshold": card["threshold"],
            "limitations": card["limitations"], "candidates": out,
            "diagnostics": {"render_scale": round(scale, 4), "image_px": [width, height], "tiles": n_tiles, "load_s": round(t_loaded - t_start, 3),
                            "detect_s": round(t_done - t_loaded, 3), "wall_s": round(time.perf_counter() - t_start, 3), "peak_working_set_mb": peak_working_set_mb(),
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
    a = ap.parse_args(argv)
    result = run(a.card, a.weights, a.input, a.page, a.threads, a.max_pixels)
    text = json.dumps(result, indent=1, sort_keys=True)
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
