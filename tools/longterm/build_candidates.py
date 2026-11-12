"""Build blind review candidates (locations + native-resolution crops) for the pilot corpus. Core Python; RF-DETR runs in the ML runtime.

Output (outside OneDrive):  <out>/candidates.json  <out>/crops/*.png  <out>/context/*.png  <out>/selection_log_INTERNAL.json
Candidate records carry LOCATIONS only. Draft OCR text is used internally to choose WHERE to look (e.g. long label-like strings, mixes
of S/5, F/T, D/O and decimal points) and is written ONLY to selection_log_INTERNAL.json, which must never be shown to a reviewer.
Crops are rendered at the page's native raster resolution (capped at 400 dpi): re-rendering larger adds no information.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "wp07"))
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from pid_reader.engineering.longterm import bubbles as B  # noqa: E402
from pid_reader.engineering.longterm import corpus as C  # noqa: E402

CONFUSABLE = re.compile(r"[S5FTDO0\.]")
LINE_LIKE = re.compile(r"(?=.*\d{4})(?=.*[-~.].*[-~.])")


def native_dpi(path):
    """Native raster dpi for a scanned page (one image covering most of the page), else 200 for vector pages.

    A vector drawing with a few small raster pieces (logos, stamps) must not be rendered at the dpi of those pieces.
    """
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw
    page = pdfium.PdfDocument(str(path))[0]
    w, h = page.get_size()
    best = 0.0
    for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE]):
        left, bottom, right, top = obj.get_bounds()
        placed_w, placed_h = max(right - left, 1e-6), max(top - bottom, 1e-6)
        if placed_w * placed_h / (w * h) >= .5:                       # the image covers most of the page: a scan
            best = max(best, obj.get_metadata().width / (placed_w / 72))
    return int(round(best)) if best else 200


def iou(a, b):
    return C._iou(a, b)


def hash_rank(*parts):
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


def pad_box(b, vertical, px=.05, py=.35):
    w, h = b["x1"] - b["x0"], b["y1"] - b["y0"]
    dx, dy = (py * w, px * h) if vertical else (px * w, py * h)
    return dict(x0=max(0, b["x0"] - dx), y0=max(0, b["y0"] - dy), x1=min(1, b["x1"] + dx), y1=min(1, b["y1"] + dy))


def render_gray(pdf_path, dpi):
    import pypdfium2 as pdfium
    page = pdfium.PdfDocument(str(pdf_path))[0]
    return np.array(page.render(scale=dpi / 72).to_pil().convert("L"))


def ocr_words(pdf_bytes):
    from pid_reader.formats.ocr_source import ocr_pdf_preview
    res = ocr_pdf_preview(pdf_bytes, pages=(1,), engine="rapidocr", timeout_seconds=240)
    return res["pages"][0]["words"]


def rfdetr_records(pdf_path, out_dir, models, ml_python, cache_from=None):
    target = Path(out_dir) / "rfdetr_records.json"
    if cache_from and Path(cache_from).is_file():
        return json.loads(Path(cache_from).read_text(encoding="utf8"))
    if not target.is_file():
        subprocess.run([sys.executable, str(ROOT / "tools/wp07/eval_configs.py"), "--pdf", str(pdf_path), "--out", str(out_dir), "--engines", "rfdetr",
                        "--models", str(models), "--python", str(ml_python)], check=True, cwd=str(ROOT), env=dict(__import__("os").environ, PYTHONPATH=str(ROOT / "src")))
    return json.loads(target.read_text(encoding="utf8"))


def pools(words, rf, gray, frame_to_render):
    """Candidate pools: list of dict(bbox(media), category, origin, draft(text or None), strata)."""
    out = []
    xs = sorted((w["bbox"]["y1"] - w["bbox"]["y0"]) for w in words) or [0]
    median_h = xs[len(xs) // 2]
    for w in words:
        b, t = w["bbox"], w["text"].strip()
        bw, bh = b["x1"] - b["x0"], b["y1"] - b["y0"]
        if bw <= 0 or bh <= 0:
            continue
        compact = t.replace(" ", "")
        strata = dict(confusable=bool(CONFUSABLE.search(compact)), has_dot="." in compact, has_s5=bool(re.search(r"[S5]", compact)),
                      has_ft=bool(re.search(r"[FT]", compact)), has_do=bool(re.search(r"[DO0]", compact)))
        if LINE_LIKE.search(compact) and len(compact) >= 10 and bw > bh:
            out.append(dict(bbox=b, category="LINE_LABEL", origin="RAPIDOCR_BOX", draft=t, strata=strata))
        elif bh / max(bw, 1e-9) >= 2.2 and len(compact) >= 5:
            out.append(dict(bbox=b, category="VERTICAL", origin="RAPIDOCR_BOX", draft=t, strata=strata))
        elif b["x0"] > .55 and b["y0"] > .84 and len(compact) >= 3:
            out.append(dict(bbox=b, category="TITLE_BLOCK", origin="RAPIDOCR_BOX", draft=t, strata=strata))
        elif 4 <= len(compact) <= 9 and compact.isalpha() and compact.isupper() and w.get("raw_ocr_score", 0) >= .97 and bh >= median_h:
            out.append(dict(bbox=b, category="EASY_CONTROL", origin="RAPIDOCR_BOX", draft=t, strata=strata))
        if w.get("raw_ocr_score", 1) < .90 and bw > 0.006 and bh > 0.004:
            # lowest-confidence boxes first: the likeliest places a human will call "unreadable" (abstention evaluation)
            out.append(dict(bbox=b, category="UNREADABLE_CANDIDATE", origin="RAPIDOCR_LOW_SCORE_BOX", draft=None, strata={}, score=w.get("raw_ocr_score", 1)))
    H, W = gray.shape
    for r in rf:
        b = r["bbox"]
        if r["class_name"].startswith("Instrument"):
            x0, y0, x1, y1 = int(b["x0"] * W), int(b["y0"] * H), int(b["x1"] * W), int(b["y1"] * H)
            m = 2
            crop = gray[max(0, y0 - m):y1 + m, max(0, x0 - m):x1 + m]
            if crop.shape[0] < 16 or crop.shape[1] < 16:
                continue
            g = B.analyse(crop, shape="circle" if r["class_name"] == "Instrument_Field" else "box")
            ox, oy = max(0, x0 - m), max(0, y0 - m)
            if g["status"] == "OK":
                for part, cat in (("code_band", "BUBBLE_CODE"), ("number_band", "BUBBLE_NUMBER")):
                    bb = g[part]
                    px = [bb[0] + ox, bb[1] + oy, bb[2] + ox, bb[3] + oy]
                    out.append(dict(bbox=dict(x0=px[0] / W, y0=px[1] / H, x1=px[2] / W, y1=px[3] / H), category=cat, origin="RFDETR_BUBBLE_GEOMETRY_BAND", draft=None,
                                    strata={}, detector_class=r["class_name"], detector_score=r["raw_score"]))
        elif r["class_name"] in ("Gate_Valve", "Ball_Valve", "Globe_valve_NO", "Check_valve", "Pipe_Insulation_or_Tracing", "Flange_or_Nozzle", "Reducer", "Box", "Flow_Arrow"):
            out.append(dict(bbox=b, category="NON_TEXT_CANDIDATE", origin="RFDETR_NON_INSTRUMENT_BOX", draft=None, strata={}, detector_class=r["class_name"]))
    return out


def choose(pool, category, n, taken, seed):
    """Deterministic, spread-out selection. Line labels alternate confusable-glyph strata with plain ones; no overlapping picks."""
    cands = [p for p in pool if p["category"] == category]
    cands.sort(key=lambda p: hash_rank(seed, p["bbox"]["x0"], p["bbox"]["y0"]))
    if category == "UNREADABLE_CANDIDATE":
        cands.sort(key=lambda p: p.get("score", 1))
    if category == "LINE_LABEL":
        hard = [p for p in cands if p["strata"].get("confusable") and p["strata"].get("has_dot")]
        rest = [p for p in cands if p not in hard]
        ordered = [x for pair in zip(hard + [None] * len(rest), rest + [None] * len(hard)) for x in pair if x is not None]
    else:
        ordered = cands
    picked = []
    for p in ordered:
        if len(picked) >= n:
            break
        if any(iou(p["bbox"], t["bbox"]) > .05 or (abs(p["bbox"]["x0"] - t["bbox"]["x0"]) < .004 and abs(p["bbox"]["y0"] - t["bbox"]["y0"]) < .004) for t in taken + picked):
            continue
        picked.append(p)
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--models", type=Path, required=True)
    ap.add_argument("--ml-python", type=Path, required=True)
    ap.add_argument("--seed", default="pilot-v1")
    a = ap.parse_args()
    if a.out.exists() and any(p for p in a.out.iterdir() if p.name != "work"):
        ap.error("choose a new output directory (an existing work/ cache of OCR words and RF-DETR boxes is reused)")
    plan = json.loads(a.plan.read_text(encoding="utf8"))
    from pid_reader.formats.page_coordinates import frame_from_pdfplumber
    import pdfplumber
    (a.out / "crops").mkdir(parents=True, exist_ok=True)
    (a.out / "context").mkdir(exist_ok=True)
    items, log, excluded = [], [], []
    for sheet in plan["sheets"]:
        pdf = Path(sheet["pdf"])
        pdf_bytes = pdf.read_bytes()
        sha = hashlib.sha256(pdf_bytes).hexdigest()
        dpi_native = native_dpi(pdf)
        dpi = min(dpi_native, 400)
        print(f"[{sheet['sheet_id']}] native {dpi_native} dpi, rendering at {dpi}", flush=True)
        try:
            with pdfplumber.open(str(pdf)) as doc:
                frame = frame_from_pdfplumber(doc.pages[0])
        except ValueError as exc:
            # The reader refuses inconsistent page frames; a coordinate frame is never guessed to keep a sheet.
            excluded.append(dict(sheet_id=sheet["sheet_id"], family_id=sheet["family_id"], reason="PAGE_FRAME_REFUSED: " + str(exc)))
            print(f"  EXCLUDED {sheet['sheet_id']}: {exc}", flush=True)
            continue
        gray = render_gray(pdf, dpi)
        H, W = gray.shape
        if frame.media_width != frame.crop_width or frame.media_height != frame.crop_height:
            print(f"  note: CropBox differs from MediaBox on {sheet['sheet_id']}; boxes are mapped through PageFrame", flush=True)
        sheet_dir = a.out / "work" / sheet["sheet_id"]
        sheet_dir.mkdir(parents=True, exist_ok=True)
        words_cache = sheet_dir / "ocr_words.json"
        if words_cache.is_file():
            words = json.loads(words_cache.read_text(encoding="utf8"))
        else:
            words = ocr_words(pdf_bytes)
            words_cache.write_text(json.dumps(words), encoding="utf8")
        rf = rfdetr_records(pdf, sheet_dir, a.models, a.ml_python, sheet.get("rfdetr_cache"))
        pool = pools(words, rf, gray, None)
        print(f"  words {len(words)}, rfdetr {len(rf)}, pool {len(pool)}", flush=True)
        taken = []
        for category, n in sheet["quota"].items():
            for p in choose(pool, category, n, taken, a.seed + sheet["sheet_id"]):
                taken.append(p)
                idx = len(items)
                cid = "c" + hashlib.sha256(f"{sha}|{p['category']}|{p['bbox']['x0']:.5f}|{p['bbox']['y0']:.5f}".encode()).hexdigest()[:10]
                vertical = (p["bbox"]["y1"] - p["bbox"]["y0"]) > 2.0 * (p["bbox"]["x1"] - p["bbox"]["x0"]) and p["category"] in ("VERTICAL", "LINE_LABEL")
                box = pad_box(p["bbox"], vertical, *( (.12, .2) if p["category"] in ("BUBBLE_CODE", "BUBBLE_NUMBER") else (.05, .35)))
                rb = frame.media_bbox_to_render_clipped(box) or box
                x0, y0, x1, y1 = int(rb["x0"] * W), int(rb["y0"] * H), int(rb["x1"] * W), int(rb["y1"] * H)
                crop = Image.fromarray(gray[y0:y1, x0:x1])
                rotation = 0          # vertical crops stay AS DRAWN; the reviewer states the reading direction and the export rotates
                cpath = a.out / "crops" / f"{cid}.png"
                crop.save(cpath)
                ctx = Image.fromarray(gray).convert("RGB")
                cw, ch = int(max(.22 * W, 6 * (x1 - x0))), int(max(.18 * H, 6 * (y1 - y0)))
                cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
                window = ctx.crop((max(0, cx - cw // 2), max(0, cy - ch // 2), min(W, cx + cw // 2), min(H, cy + ch // 2)))
                d = ImageDraw.Draw(window)
                ox, oy = max(0, cx - cw // 2), max(0, cy - ch // 2)
                d.rectangle([x0 - ox - 2, y0 - oy - 2, x1 - ox + 2, y1 - oy + 2], outline=(220, 0, 0), width=max(2, dpi // 100))
                scale = min(1.0, 760 / window.width)
                window.resize((max(1, int(window.width * scale)), max(1, int(window.height * scale)))).save(a.out / "context" / f"{cid}.png")
                items.append(dict(id=cid, split=sheet["split"], family_id=sheet["family_id"], sheet_id=sheet["sheet_id"], source_sha256=sha, source_path=str(pdf), page=1,
                                  bbox=box, coordinate_frame="MEDIA_NORMALIZED_TOP_LEFT", category=p["category"], location_origin=p["origin"],
                                  crop_path=f"crops/{cid}.png", crop_sha256=C.sha256_file(cpath), dhash=C.dhash(crop), crop_rotation=rotation, is_vertical=bool(vertical),
                                  native_dpi=dpi_native, render_dpi=dpi, control=p["category"] == "EASY_CONTROL"))
                log.append(dict(id=cid, draft_text_INTERNAL_NOT_FOR_REVIEWERS=p.get("draft"), strata=p.get("strata"), detector_class=p.get("detector_class"),
                                detector_score=p.get("detector_score")))
    doc = dict(schema=C.CANDIDATES_SCHEMA, seed=a.seed, note="locations only; no readings", excluded_sheets=excluded, items=items)
    problems = C.validate_candidates(doc, root=a.out)
    (a.out / "candidates.json").write_text(json.dumps(doc, indent=1), encoding="utf8")
    (a.out / "selection_log_INTERNAL.json").write_text(json.dumps(log, indent=1), encoding="utf8")
    counts = {}
    for it in items:
        counts[(it["split"], it["category"])] = counts.get((it["split"], it["category"]), 0) + 1
    print(json.dumps(dict(items=len(items), problems=problems, counts={f"{k[0]}/{k[1]}": v for k, v in sorted(counts.items())}), indent=1))


if __name__ == "__main__":
    main()
