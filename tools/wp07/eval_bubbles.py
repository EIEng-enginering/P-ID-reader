"""Read the stacked code / number halves of instrument bubbles found by RF-DETR, with TrOCR.

Chain under test: RF-DETR Instrument_* box -> two half-bubble crops (code above the divider, number below) -> TrOCR.
Regions come from detector boxes, never from hand-picked coordinates. Output is a list of proposals; nothing is joined into a tag
here (joining is the review step: a wrong code or digit must not be repaired from a grammar).
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pid_reader.engineering.model_lab import pipeline  # noqa: E402
from eval_configs import run_batches  # noqa: E402

# Fractions of the detector box: the code sits above the divider, the number below, both inside the ring.
HALVES = dict(code=(.14, .16, .86, .50), number=(.14, .50, .86, .86))


def bubble_regions(records, classes=("Instrument_Field", "Instrument_Panel", "Instrument_Aux_Panel")):
    regions = []
    for r in records:
        if r.get("class_name") not in classes:
            continue
        b = r["bbox"]
        w, h = b["x1"] - b["x0"], b["y1"] - b["y0"]
        for part, (a0, b0, a1, b1) in HALVES.items():
            regions.append(dict(id=f"bubble-{r['id'][:8]}-{part}", bbox=dict(x0=b["x0"] + a0 * w, y0=b["y0"] + b0 * h, x1=b["x0"] + a1 * w, y1=b["y0"] + b1 * h),
                                reason="RFDETR_BUBBLE_" + part.upper(), part=part, detector_id=r["id"], detector_class=r["class_name"],
                                detector_score=r["raw_score"]))
    return regions


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pdf", type=Path, required=True)
    p.add_argument("--rfdetr-records", type=Path, required=True)
    p.add_argument("--models", type=Path, required=True)
    p.add_argument("--python", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--variants", default="base")
    p.add_argument("--min-score", type=float, default=0.0)
    a = p.parse_args()
    pdf = a.pdf.read_bytes()
    records = [r for r in json.loads(a.rfdetr_records.read_text(encoding="utf8")) if r["raw_score"] >= a.min_score]
    regions = bubble_regions(records)
    manifest = json.loads((a.models / "trocr.manifest.json").read_text(encoding="utf8"))
    variants = tuple(v for v in a.variants.split(",") if v)
    res = run_batches(pdf, a.page, regions, manifest, a.python, batch=max(1, 24 // len(variants)), rotations=(0,),
                      cache=str(a.out / "crop_cache"), timeout=280, label="trocr-bubbles", variants=variants)
    by_id = {r["id"]: r for r in regions}
    rows = []
    for rec in res["records"]:
        rid = rec["roi_id"].split("-rot", 1)[0]
        reg = by_id[rid]
        rows.append(dict(detector_id=reg["detector_id"], part=reg["part"], detector_class=reg["detector_class"], detector_score=reg["detector_score"],
                         variant=rec["roi_id"].split("-rot0", 1)[1].lstrip("-") or "base", text=rec["text"], bbox=rec["bbox"]))
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "bubble_readings.json").write_text(json.dumps(dict(
        schema="wp07-bubble-readings-v1", source_sha256=sha256(pdf).hexdigest(), page=a.page, review_state="PROPOSED_UNVERIFIED",
        accuracy_status="NOT_MEASURED", detector_boxes=len({r["detector_id"] for r in rows}), requested_regions=len(regions),
        completed_batches=res["completed_batches"], total_batches=res["total_batches"], wall_seconds=res["wall_seconds"],
        peak_worker_rss_mib=res["peak_worker_rss_mib"], rows=rows), indent=1), encoding="utf8")
    print(json.dumps(dict(boxes=len({r["detector_id"] for r in rows}), readings=len(rows), batches=f"{res['completed_batches']}/{res['total_batches']}",
                          wall_seconds=res["wall_seconds"], peak_mib=round(res["peak_worker_rss_mib"]))))


if __name__ == "__main__":
    main()
