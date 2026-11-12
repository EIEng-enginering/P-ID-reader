"""Crops for the S418 DRAFT diagnostic (core Python). DIAGNOSTIC ONLY: the reference is an analyst draft, not verified ground truth.

Renders each draft item's box from the S418 scan at its native 200 dpi (no enlargement), with the same padding rule as the candidate
builder. The one vertical item reads bottom-to-top (analyst observation) so its crop is turned clockwise. Easy controls are the tags and
title-block fields an analyst read plainly (FE-2202, FE-2206 x2, 012, the issue date).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from build_candidates import pad_box  # noqa: E402
from pid_reader.engineering.longterm.data import sha  # noqa: E402

CONTROLS = {"fe2202-top", "fe2206-top", "fe2206-mid", "sheet-012", "date-issue"}
VERTICAL_CW = {"line-10"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", type=Path, required=True)
    ap.add_argument("--reference", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    ref = json.loads(a.reference.read_text(encoding="utf8"))
    if ref["source_sha256"] != sha(a.pdf):
        sys.exit("reference belongs to another drawing")
    import pypdfium2 as pdfium
    gray = np.array(pdfium.PdfDocument(str(a.pdf))[0].render(scale=200 / 72).to_pil().convert("L"))
    H, W = gray.shape
    a.out.mkdir(parents=True)
    rows = []
    for it in ref["items"]:
        vertical = it["id"] in VERTICAL_CW
        box = pad_box(it["bbox"], vertical, .05, .35)
        crop = Image.fromarray(gray[int(box["y0"] * H):int(box["y1"] * H), int(box["x0"] * W):int(box["x1"] * W)])
        if vertical:
            crop = crop.rotate(-90, expand=True)
        path = a.out / f"{it['id']}.png"
        crop.save(path)
        rows.append(dict(id=it["id"], text=it["text"], category=it.get("category", "LINE_LABEL"), control=it["id"] in CONTROLS, image_path=path.name,
                         image_sha256=sha(path), note="DRAFT_ANALYST_NOT_INDEPENDENT"))
    (a.out / "dataset.json").write_text(json.dumps(dict(schema="pid-diagnostic-crops-v1", status="DIAGNOSTIC_DRAFT_REFERENCE_NOT_AUTHORITATIVE", items=rows), indent=1), encoding="utf8")
    print(len(rows), "crops")


if __name__ == "__main__":
    main()
