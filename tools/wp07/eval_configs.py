"""WP07 challenger runs on ONE page: independent page tiles and automatically selected text-line crops.

Writes raw model proposals plus coverage/timing/memory bookkeeping. It never produces an accuracy figure:
scoring is a separate step against an explicitly reviewed reference (tools/wp07/score_reference.py).
Every region comes from the page geometry or from OCR boxes, never from hand-chosen coordinates.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from pid_reader.engineering.model_lab import pipeline  # noqa: E402
from pid_reader.engineering.longterm import vertical as vertical_budget  # noqa: E402


def iou(a, b):
    ix = max(0.0, min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]))
    iy = max(0.0, min(a["y1"], b["y1"]) - max(a["y0"], b["y0"]))
    inter = ix * iy
    union = (a["x1"] - a["x0"]) * (a["y1"] - a["y0"]) + (b["x1"] - b["x0"]) * (b["y1"] - b["y0"]) - inter
    return inter / union if union > 0 else 0.0


def covered_fraction(box, others):
    """Share of `box` area covered by the union of the stored `others` boxes (axis-aligned, sampled on a grid)."""
    n = 12
    hit = 0
    for i in range(n):
        for j in range(n):
            x = box["x0"] + (i + .5) / n * (box["x1"] - box["x0"])
            y = box["y0"] + (j + .5) / n * (box["y1"] - box["y0"])
            if any(o["x0"] <= x <= o["x1"] and o["y0"] <= y <= o["y1"] for o in others):
                hit += 1
    return hit / (n * n)


def page_frame(pdf, page):
    import io
    import pdfplumber
    from pid_reader.formats.page_coordinates import frame_from_pdfplumber
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return frame_from_pdfplumber(doc.pages[page - 1])


def baseline_words(db_path, page):
    if not db_path:
        return []
    con = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    try:
        best = con.execute("SELECT analysis_id FROM ocr_word GROUP BY analysis_id ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
        if not best:
            return []
        return [dict(id=r[0], text=r[1], bbox=json.loads(r[2]), page=page, engine="rapidocr")
                for r in con.execute("SELECT native_word_id,text,bbox_json FROM ocr_word WHERE analysis_id=? AND page=?", (best[0], page))]
    finally:
        con.close()


def run_batches(pdf, page, regions, manifest, python, *, batch, rotations, cache, timeout, label, variants=("base",)):
    records, runs, t0 = [], [], time.monotonic()
    omitted = 0
    for start in range(0, len(regions), batch):
        chunk = regions[start:start + batch]
        res = pipeline.compare(pdf, page, chunk, manifest, python=python, enabled=True, timeout=timeout,
                               max_regions=batch, rotations=rotations, variants=variants, cache_dir=cache, worker_archive=None)
        mr = res.get("model_result") or {}
        omitted += res.get("coverage", {}).get("omitted_regions", 0)
        records += mr.get("records", [])
        runs.append(dict(batch=start // batch, status=res.get("status"), worker_status=mr.get("status"),
                         seconds=mr.get("elapsed_seconds"), crops=len(res.get("crops", [])),
                         cached=sum(1 for r in mr.get("runs", []) if r.get("cache_hit")),
                         failures=[r.get("error") for r in mr.get("runs", []) if r.get("status") != "COMPLETE_PROPOSALS"],
                         peak_worker_rss_mib=(mr.get("runtime") or {}).get("peak_worker_rss_mib"),
                         versions=(mr.get("runtime") or {}).get("versions"), error=mr.get("error")))
        print(f"[{label}] batch {start // batch}: {res.get('status')} worker={mr.get('status')} records={len(mr.get('records', []))} "
              f"{mr.get('elapsed_seconds')}s", flush=True)
    return dict(label=label, requested_regions=len(regions), omitted_regions=omitted, batches=runs, records=records,
                wall_seconds=round(time.monotonic() - t0, 2),
                peak_worker_rss_mib=max([b["peak_worker_rss_mib"] or 0 for b in runs] or [0]),
                completed_batches=sum(b["worker_status"] == "COMPLETE_PROPOSALS" for b in runs), total_batches=len(runs))


def dedupe(records, threshold=.4):
    """Merge repeats of the same printed item seen in overlapping tiles. Differing readings are kept as alternatives."""
    out = []
    for r in sorted(records, key=lambda x: -(x["raw_score"] or 0)):
        for kept in out:
            if kept["kind"] == r["kind"] and iou(kept["bbox"], r["bbox"]) >= threshold:
                kept.setdefault("alternatives", []).append({k: r.get(k) for k in ("id", "text", "class_name", "raw_score", "roi_id")})
                break
        else:
            out.append(dict(r))
    return out


LINE_LIKE = re.compile(r"(?=.*\d{4})(?=.*[-~.].*[-~.])")


def looks_like_line_label(text):
    """Selection heuristic only (never a verdict): long string, 4+ digits, at least two separators.

    Complete-grammar strings are included on purpose: PF-00019-14.3-A3S-40 satisfies a line grammar and is still misread.
    """
    t = text.replace(" ", "")
    return len(t) >= 10 and bool(LINE_LIKE.search(t))


def text_line_regions(records, existing, *, frame, min_new_chars=8, pad_x=.05, pad_y=.35, budget=80):
    """Auto-select TrOCR crops.

    Priority 1: every line-label-like string already read by the existing OCR (re-read request, original kept).
    Priority 2: elongated EasyOCR boxes with enough characters that overlap no existing word (possible missed text).
    Boxes taller than wide are vertical labels and are read with both quarter turns.
    """
    fw, fh = frame.media_width, frame.media_height
    regions, seen = [], []

    def add(b, text, reason):
        w, h = (b["x1"] - b["x0"]) * fw, (b["y1"] - b["y0"]) * fh
        if min(w, h) <= 0 or any(iou(b, s) >= .5 for s in seen):
            return
        seen.append(b)
        # Pad lightly along the text (neighbouring labels abut) and generously across it (ascenders, rules).
        vertical = h > w
        px = (b["x1"] - b["x0"]) * (pad_y if vertical else pad_x)
        py = (b["y1"] - b["y0"]) * (pad_x if vertical else pad_y)
        box = dict(x0=max(0.0, b["x0"] - px), y0=max(0.0, b["y0"] - py), x1=min(1.0, b["x1"] + px), y1=min(1.0, b["y1"] + py))
        regions.append(dict(id=f"line-{len(regions)}", bbox=box, reason=reason, vertical=vertical, source_text=text))

    for w in sorted(existing, key=lambda x: -len(x["text"])):
        if looks_like_line_label(w["text"]):
            add(w["bbox"], w["text"], "TARGETED_REREAD_OF_EXISTING_LINE_LABEL")
    others = [w["bbox"] for w in existing]
    for r in records:
        if r["kind"] != "TEXT" or len((r.get("text") or "").replace(" ", "")) < min_new_chars:
            continue
        b = r["bbox"]
        w, h = (b["x1"] - b["x0"]) * fw, (b["y1"] - b["y0"]) * fh
        if (w / max(h, 1e-9) >= 2.2 or h / max(w, 1e-9) >= 2.2) and covered_fraction(b, others) < .3:
            add(b, r["text"], "AUTO_NEW_TEXT_LINE_FROM_EASYOCR")
    return regions[:budget]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pdf", type=Path, required=True)
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--models", type=Path, required=True, help="folder with <engine>.manifest.json")
    p.add_argument("--python", type=Path, required=True)
    p.add_argument("--engines", default="easyocr,trocr,rfdetr")
    p.add_argument("--cols", type=int, default=5)
    p.add_argument("--rows", type=int, default=4)
    p.add_argument("--overlap", type=float, default=.12)
    p.add_argument("--batch", type=int, default=6)
    p.add_argument("--timeout", type=int, default=280)
    p.add_argument("--baseline-db", type=Path)
    p.add_argument("--max-line-crops", type=int, default=80)
    p.add_argument("--max-vertical", type=int, default=6, help="vertical-text regions (each read at 90 and 270 degrees), at most 6")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--variants", default="base,small,large,binary", help="TrOCR re-renderings of each line crop")
    a = p.parse_args()
    pdf = a.pdf.read_bytes()
    a.out.mkdir(parents=True, exist_ok=True)
    cache = None if a.no_cache else str(a.out / "crop_cache")
    frame = page_frame(pdf, a.page)
    tiles = pipeline.grid_regions(frame, columns=a.cols, rows=a.rows, overlap=a.overlap)
    manifests = {e: json.loads((a.models / f"{e}.manifest.json").read_text(encoding="utf8")) for e in a.engines.split(",")}
    base = baseline_words(a.baseline_db, a.page)
    summary = dict(schema="wp07-eval-configs-v1", source_sha256=sha256(pdf).hexdigest(), page=a.page,
                   tiles=dict(columns=a.cols, rows=a.rows, overlap=a.overlap, count=len(tiles)),
                   baseline_words=len(base), accuracy_status="NOT_MEASURED", engines={})
    results = {}
    prior = a.out / "summary.json"
    if prior.exists():
        summary["engines"] = json.loads(prior.read_text(encoding="utf8")).get("engines", {})
    reused_easy = None
    if "easyocr" not in manifests and (a.out / "easyocr_records.json").exists():
        reused_easy = json.loads((a.out / "easyocr_records.json").read_text(encoding="utf8"))
    if "easyocr" in manifests:
        results["easyocr"] = run_batches(pdf, a.page, tiles, manifests["easyocr"], a.python, batch=a.batch, rotations=(0,),
                                         cache=cache, timeout=a.timeout, label="easyocr-tiles")
    if "rfdetr" in manifests:
        results["rfdetr"] = run_batches(pdf, a.page, tiles, manifests["rfdetr"], a.python, batch=a.batch, rotations=(0,),
                                        cache=cache, timeout=a.timeout, label="rfdetr-tiles")
    if "trocr" in manifests:
        easy = dedupe(results["easyocr"]["records"]) if "easyocr" in results else (reused_easy or [])
        variants = tuple(v for v in a.variants.split(",") if v)
        per_call = max(1, 24 // len(variants))
        lines = text_line_regions(easy, base, frame=frame, budget=a.max_line_crops)
        horizontal = [r for r in lines if not r["vertical"]]
        vertical, vertical_omitted = vertical_budget.select([r for r in lines if r["vertical"]], a.max_vertical)
        tr_h = run_batches(pdf, a.page, horizontal, manifests["trocr"], a.python, batch=per_call, rotations=(0,),
                           cache=cache, timeout=a.timeout, label="trocr-horizontal", variants=variants) if horizontal else None
        tr_v = run_batches(pdf, a.page, vertical, manifests["trocr"], a.python, batch=max(1, per_call // 2), rotations=(90, 270),
                           cache=cache, timeout=a.timeout, label="trocr-vertical", variants=variants) if vertical else None
        merged = dict(label="trocr-lines", requested_regions=len(lines), omitted_regions=sum(x["omitted_regions"] for x in (tr_h, tr_v) if x),
                      records=sum([x["records"] for x in (tr_h, tr_v) if x], []),
                      batches=sum([x["batches"] for x in (tr_h, tr_v) if x], []),
                      wall_seconds=round(sum(x["wall_seconds"] for x in (tr_h, tr_v) if x), 2),
                      peak_worker_rss_mib=max([x["peak_worker_rss_mib"] for x in (tr_h, tr_v) if x] or [0]),
                      completed_batches=sum(x["completed_batches"] for x in (tr_h, tr_v) if x),
                      total_batches=sum(x["total_batches"] for x in (tr_h, tr_v) if x),
                      selection=[{k: v for k, v in r.items()} for r in lines if not r["vertical"]] + [{k: v for k, v in r.items()} for r in vertical],
                      vertical=vertical_budget.report(vertical, vertical_omitted, {x["roi_id"].rsplit("-rot", 1)[0] for x in (tr_v["records"] if tr_v else [])}))
        results["trocr"] = merged
    for engine, res in results.items():
        summary["engines"].pop(engine, None)
        records = dedupe(res["records"]) if engine != "trocr" else res["records"]
        entry = {k: v for k, v in res.items() if k not in ("records",)}
        entry["raw_records"] = len(res["records"])
        entry["merged_records"] = len(records)
        if engine in ("easyocr",):
            others = [w["bbox"] for w in base]
            new = [r for r in records if covered_fraction(r["bbox"], others) < .3]
            entry["texts_not_overlapping_baseline_words"] = len(new)
        summary["engines"][engine] = entry
        (a.out / f"{engine}_records.json").write_text(json.dumps(records, indent=1), encoding="utf8")
    (a.out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf8")
    print(json.dumps({e: {k: v[k] for k in ("requested_regions", "omitted_regions", "completed_batches", "total_batches", "wall_seconds", "raw_records", "merged_records")}
                      for e, v in summary["engines"].items()}, indent=1))


if __name__ == "__main__":
    main()
