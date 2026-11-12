"""Frame mapping of the WP04 region renderer on offset, cropped and rotated PDF pages (real PDFium + PageFrame; synthetic black rectangle)."""
from __future__ import annotations

from io import BytesIO

import pytest

pytest.importorskip("pypdfium2")
pytest.importorskip("pdfplumber")
from reportlab.pdfgen.canvas import Canvas  # noqa: E402

from pid_reader.engineering.wp456 import host  # noqa: E402

W, H = 600.0, 400.0
RECT = (200.0, 150.0, 260.0, 190.0)            # x0,y0,x1,y1 in PDF user space (origin bottom-left, MediaBox units)


def make(rotate: int, crop: tuple | None) -> bytes:
    s = BytesIO()
    c = Canvas(s, pagesize=(W, H))
    c.setFillColorRGB(0, 0, 0)
    c.rect(RECT[0], RECT[1], RECT[2] - RECT[0], RECT[3] - RECT[1], stroke=0, fill=1)
    c.showPage()
    c.save()
    data = s.getvalue()
    if rotate or crop:                         # same helper approach as tests/revx_fixtures.py
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import RectangleObject
        page = PdfReader(BytesIO(data)).pages[0]
        if crop:
            page.cropbox = RectangleObject(list(crop))
        if rotate:
            page.rotate(rotate)
        w = PdfWriter()
        w.add_page(page)
        out = BytesIO()
        w.write(out)
        data = out.getvalue()
    return data


def media_box(pdf: bytes) -> dict:
    """Ground truth independent of PageFrame: pdfplumber's own rotation-aware coordinates of the drawn rectangle."""
    import pdfplumber
    with pdfplumber.open(BytesIO(pdf)) as doc:
        p = doc.pages[0]
        r = p.rects[0]
        return {"x0": r["x0"] / p.width, "x1": r["x1"] / p.width, "y0": r["top"] / p.height, "y1": r["bottom"] / p.height}


@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
@pytest.mark.parametrize("crop", [None, (100.0, 80.0, 500.0, 330.0)])
def test_dark_region_maps_back_to_the_media_frame(rotate, crop):
    pdf = make(rotate, crop)
    want = media_box(pdf)
    pad_x, pad_y = 30 / W, 25 / H
    roi = {"id": "roi-test", "page": 1, "bbox": {"x0": want["x0"] - pad_x, "x1": want["x1"] + pad_x, "y0": want["y0"] - pad_y, "y1": want["y1"] + pad_y}}
    image, mapper = host.pdf_renderer(pdf)(roi)
    px = image.point(lambda v: 255 if v < 128 else 0)
    bb = px.getbbox()
    assert bb, "the rectangle must be visible in the crop"
    n = {"x0": bb[0] / image.width, "y0": bb[1] / image.height, "x1": bb[2] / image.width, "y1": bb[3] / image.height}
    got = mapper(n)
    tol = 0.012
    assert all(abs(got[k] - want[k]) < tol for k in ("x0", "y0", "x1", "y1")), (rotate, crop, got, want)


def test_region_outside_the_visible_crop_is_refused():
    pdf = make(0, (100.0, 80.0, 500.0, 330.0))
    with pytest.raises(ValueError):
        host.pdf_renderer(pdf)({"id": "r", "page": 1, "bbox": {"x0": 0.0, "x1": 0.05, "y0": 0.0, "y1": 0.05}})


@pytest.mark.parametrize("rotate,expected", [(0, (600.0, 400.0)), (90, (400.0, 600.0)), (180, (600.0, 400.0)), (270, (400.0, 600.0))])
def test_page_sizes_follow_the_rotation_aware_frame(rotate, expected):
    assert host.dimensions(make(rotate, None))[1] == expected
