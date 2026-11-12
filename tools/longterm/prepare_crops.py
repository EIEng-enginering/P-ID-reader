"""Freeze annotated source regions as native-resolution crops in a pid-longterm-crops-v1 dataset (replaces the WP08-dependent original).

Annotations that are not VERIFIED_DEVELOPMENT stay DRAFT and are refused by the trainer. For a real corpus use build_candidates.py,
make_review_package.py and adjudicate.py; this tool exists for small, already-reviewed annotation files.
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
from pid_reader.engineering.longterm.data import sha  # noqa: E402
from build_candidates import native_dpi  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pdf", type=Path, required=True)
    p.add_argument("--annotations", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        p.error("Choose a new versioned dataset directory")
    annotations = json.loads(a.annotations.read_text(encoding="utf8"))
    fingerprint = sha(a.pdf)
    if annotations["source_sha256"] != fingerprint:
        p.error("Source hash mismatch")
    items = annotations["items"]
    if not 1 <= len(items) <= 1000:
        p.error("Crop count budget is 1..1000")
    import pdfplumber
    import pypdfium2 as pdfium
    from pid_reader.formats.page_coordinates import frame_from_pdfplumber
    dpi = min(native_dpi(a.pdf), 400)
    document = pdfium.PdfDocument(str(a.pdf))
    a.output.mkdir(parents=True)
    rows, cache = [], {}
    with pdfplumber.open(str(a.pdf)) as plumber:
        for i, item in enumerate(items):
            page = int(item["page"])
            if page not in cache:
                cache[page] = (np.array(document[page - 1].render(scale=dpi / 72).to_pil().convert("L")), frame_from_pdfplumber(plumber.pages[page - 1]))
            gray, frame = cache[page]
            h, w = gray.shape
            box = item["bbox"]
            rb = frame.media_bbox_to_render_clipped(box)
            if rb is None:
                p.error(f"item {i}: region lies outside the visible page")
            crop = gray[int(rb["y0"] * h):int(rb["y1"] * h), int(rb["x0"] * w):int(rb["x1"] * w)]
            path = a.output / f"crop-{i:04d}.png"
            Image.fromarray(crop).save(path)
            rows.append(dict(item, image_path=path.name, image_sha256=sha(path), source_path=str(a.pdf.resolve()), source_sha256=fingerprint,
                             origin="HUMAN_SOURCE_PIXELS", bbox=box, coordinate_frame="MEDIA_NORMALIZED_TOP_LEFT",
                             review_status=item.get("review_status", "DRAFT_ANALYST_NOT_INDEPENDENT"), render=dict(dpi=dpi, native_dpi=native_dpi(a.pdf))))
    (a.output / "dataset.json").write_text(json.dumps(dict(schema="pid-longterm-crops-v1", items=rows), indent=2))
    print(a.output / "dataset.json")


if __name__ == "__main__":
    main()
