"""Proxy TRAIN data: exact label strings from native CAD text layers, rendered to pixels and degraded to look like a low-resolution scan.

Origin `VECTOR_TEXT_LAYER`: the string is the document's own embedded text (no OCR, no model, no human). It is real P&ID vocabulary in real
fonts, but the rendering is synthetic. It is therefore TRAIN-only proxy data: never validation, never counted as human-reviewed, never
reported as real-scan accuracy. Operators in the human-validation families (and their corporate relatives) are excluded outright.

Per sheet we keep: page is a native vector drawing (no page-covering image, a real text layer), glyphs are visible (non-white, 4-40 pt, ink
present in the rendered crop), printable ASCII only. Held-out operators go to a separate PROXY file that the training/evaluation jobs
cannot load (its split value is not TRAIN/VALIDATION); the diagnostic tool reads it directly.
"""
import argparse
import csv
import hashlib
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import numpy as np  # noqa: E402
from PIL import Image, ImageFilter  # noqa: E402
from pid_reader.engineering.longterm import corpus as C  # noqa: E402

EXCLUDE_OPERATORS = re.compile(r"spectra|westcoast|talisman", re.I)   # human-validation families and their corporate relatives
LINE_LIKE = re.compile(r"^(?=.*\d{3})(?=.*[-~.].*[-~.])[A-Z0-9][A-Z0-9.\-~/]{7,31}$")   # label-shaped only: no spaces, no sentences, no file paths
TAG_LIKE = re.compile(r"^[A-Z]{1,4}-?\d{3,5}[A-Z]?$")
NUMBER_DOT = re.compile(r"^\d{1,3}\.\d{1,2}$")
EASY = re.compile(r"^[A-Z]{4,9}$")
PRINTABLE = re.compile(r"^[\x20-\x7e]+$")
DEGRADE_DPIS = (200, 200, 300, 150)                  # shared out deterministically; the 1-bit 200 dpi scan is the weak spot


def family_of(operator):
    return re.sub(r"[^A-Z0-9]+", "_", operator.upper()).strip("_")[:40] or "UNKNOWN"


def is_native_vector(page):
    import pypdfium2.raw as raw
    w, h = page.get_size()
    for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE]):
        l, b, r, t = obj.get_bounds()
        if (r - l) * (t - b) / (w * h) >= .5:
            return False
    return True


def visible(word):
    colour = word.get("non_stroking_color")
    if colour in ((1,), (1, 1, 1), [1], [1, 1, 1], (1.0,), (1.0, 1.0, 1.0)):
        return False
    size = word.get("size", 0)
    return 4 <= size <= 40


def category_of(text):
    if LINE_LIKE.match(text):
        return "LINE_LABEL"
    if TAG_LIKE.match(text):
        return "TAG"
    if NUMBER_DOT.match(text):
        return "DECIMAL_NUMBER"
    if EASY.match(text):
        return "EASY_CONTROL"
    return None


def degrade(gray, dpi, rng, source_dpi):
    """Scan-like degradation of a crop rendered at source_dpi: resample to dpi, blur a little, add noise, binarise at a random threshold."""
    img = Image.fromarray(gray)
    f = dpi / source_dpi
    img = img.resize((max(1, int(img.width * f)), max(1, int(img.height * f))), Image.Resampling.LANCZOS)
    img = img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(.4, .8)))
    arr = np.asarray(img, dtype=np.float32)
    arr = arr + np.random.default_rng(rng.randrange(1 << 30)).normal(0, 7, arr.shape)
    threshold = rng.uniform(135, 185)
    out = np.where(arr > threshold, 255, 0).astype(np.uint8)
    return Image.fromarray(out), dict(dpi=dpi, blur="gaussian", noise_sigma=7, threshold=round(threshold, 1), mode="1-bit")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=Path, required=True)
    ap.add_argument("--library", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--sheets", type=int, default=40)
    ap.add_argument("--per-sheet", type=int, default=12)
    ap.add_argument("--heldout-fraction", type=float, default=.2)
    ap.add_argument("--seed", default="textlayer-v1")
    a = ap.parse_args()
    if a.out.exists():
        ap.error("choose a new output directory")
    import pdfplumber
    import pypdfium2 as pdfium
    from pid_reader.formats.page_coordinates import frame_from_pdfplumber
    rows = [r for r in csv.DictReader(open(a.index, encoding="utf8")) if r["text_source"] == "text" and r["doc_type"] != "legend_sheet"
            and not EXCLUDE_OPERATORS.search(r["operator"] + " " + r["filing_or_project"])]
    by_family = {}
    for r in rows:
        by_family.setdefault(family_of(r["operator"]), []).append(r)
    families = sorted(by_family)
    rng = random.Random(a.seed)
    held = {f for f in families if int(hashlib.sha256((a.seed + f).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF < a.heldout_fraction}
    chosen = []
    for f in families:                                           # spread the sheet budget across families, round robin
        r = list(by_family[f])
        rng.shuffle(r)
        by_family[f] = r
    while len(chosen) < a.sheets and any(by_family.values()):
        for f in families:
            if by_family[f] and len(chosen) < a.sheets:
                chosen.append(by_family[f].pop())
    (a.out / "crops").mkdir(parents=True)
    train, proxy, skipped = [], [], []
    seen_ids = set()                                            # the same word drawn twice at one position is ONE item
    for r in chosen:
        path = a.library / r["library_file"]
        family = family_of(r["operator"])
        try:
            pdf = pdfium.PdfDocument(str(path))
            page = pdf[0]
            if not is_native_vector(page):
                skipped.append(dict(sheet=r["sheet_id"], reason="page is dominated by a raster image (text layer may be OCR output)"))
                continue
            with pdfplumber.open(str(path)) as plumber:
                p = plumber.pages[0]
                frame = frame_from_pdfplumber(p)
                words = p.extract_words(extra_attrs=["size", "non_stroking_color", "upright"], use_text_flow=False, keep_blank_chars=False, x_tolerance=1, x_tolerance_ratio=0.18)
            if len(words) < 20:
                skipped.append(dict(sheet=r["sheet_id"], reason="fewer than 20 text-layer words"))
                continue
            render_dpi = 400
            gray = np.array(page.render(scale=render_dpi / 72).to_pil().convert("L"))
            H, W = gray.shape
        except Exception as exc:                                  # a broken sheet is skipped, never patched
            skipped.append(dict(sheet=r["sheet_id"], reason=f"{type(exc).__name__}: {exc}"[:120]))
            continue
        sha = C.sha256_file(path)
        picks = {"LINE_LABEL": [], "TAG": [], "DECIMAL_NUMBER": [], "EASY_CONTROL": []}
        for w in words:
            t = w["text"]
            cat = category_of(t) if PRINTABLE.match(t) and visible(w) else None
            if cat:
                picks[cat].append(w)
        quota = dict(LINE_LABEL=int(a.per_sheet * .5), TAG=int(a.per_sheet * .2), DECIMAL_NUMBER=int(a.per_sheet * .15), EASY_CONTROL=max(1, int(a.per_sheet * .15)))
        for cat, n in quota.items():
            cand = picks[cat]
            rng.shuffle(cand)
            taken = 0
            for w in cand:
                if taken >= n:
                    break
                label = w["text"]                                  # the label of THIS word (never a loop leftover)
                box_pt = (w["x0"], w["top"], w["x1"], w["bottom"])
                norm = dict(x0=box_pt[0] / p.width, y0=box_pt[1] / p.height, x1=box_pt[2] / p.width, y1=box_pt[3] / p.height)
                if not (0 <= norm["x0"] < norm["x1"] <= 1 and 0 <= norm["y0"] < norm["y1"] <= 1):
                    continue
                rb = frame.media_bbox_to_render_clipped(norm)
                if rb is None:
                    continue
                pad_x, pad_y = .02 * (rb["x1"] - rb["x0"]), .25 * (rb["y1"] - rb["y0"])
                x0, x1 = int((rb["x0"] - pad_x) * W), int((rb["x1"] + pad_x) * W)
                y0, y1 = int((rb["y0"] - pad_y) * H), int((rb["y1"] + pad_y) * H)
                crop = gray[max(0, y0):min(H, y1), max(0, x0):min(W, x1)]
                if crop.size == 0 or min(crop.shape) < 8:
                    continue
                rotate = 0
                if not w.get("upright", True):
                    continue                 # rotated text is not part of this proxy set (direction would have to be guessed)
                ink = float((crop < 128).mean())
                if not .02 <= ink <= .6:
                    continue
                item_id = "t" + hashlib.sha256(f"{sha}|{label}|{box_pt}".encode()).hexdigest()[:11]
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                dpi = DEGRADE_DPIS[len(train) % len(DEGRADE_DPIS)]
                img, params = degrade(crop, dpi, rng, render_dpi)
                degraded_ink = float((np.asarray(img) < 128).mean())
                if not .06 <= degraded_ink <= .38:                 # blank or blobbed after degradation: not a usable training crop
                    seen_ids.discard(item_id)
                    skipped.append(dict(item=item_id, reason=f"degraded ink fraction {degraded_ink:.3f} outside 0.06..0.38"))
                    continue
                cpath = a.out / "crops" / f"{item_id}.png"
                img.save(cpath)
                item = dict(id=item_id, split="TRAIN", family_id=family, source_sha256=sha, origin="VECTOR_TEXT_LAYER",
                            review_status="EXACT_FROM_DOCUMENT_TEXT_LAYER", reviewer="document text layer (no human, no OCR, no model)", text=label,
                            image_path=f"crops/{item_id}.png", image_sha256=C.sha256_file(cpath), source_path=str(path.resolve()), page=1, bbox=norm,
                            coordinate_frame="MEDIA_NORMALIZED_TOP_LEFT", category=cat, control=cat == "EASY_CONTROL", degradation=params,
                            crop_rotation_applied=0, sheet_id=r["sheet_id"])
                (proxy if family in held else train).append(item)
                taken += 1
    for name, items in (("train_proxy", train), ("heldout_proxy", proxy)):
        rows_out = items if name == "train_proxy" else [dict(i, split="PROXY_HELDOUT") for i in items]
        (a.out / f"{name}.json").write_text(json.dumps(dict(schema="pid-longterm-crops-v1", proxy=True, items=rows_out), indent=1), encoding="utf8")
    cats = {}
    for i in train:
        cats[i["category"]] = cats.get(i["category"], 0) + 1
    summary = dict(train_items=len(train), heldout_items=len(proxy), train_families=sorted({i["family_id"] for i in train}), heldout_families=sorted({i["family_id"] for i in proxy}),
                   sheets_used=len({i["sheet_id"] for i in train + proxy}), skipped=skipped, categories_train=cats,
                   excluded_operator_pattern=EXCLUDE_OPERATORS.pattern, note="TRAIN-only proxy data; synthetic degradation of vector renders; not human reviewed")
    (a.out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
