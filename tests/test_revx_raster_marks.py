"""WPU-08 (raster): junction dots and arrow heads found on scan-style pages; no marks where there are none."""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

import pytest
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).parent))
pytest.importorskip("cv2")
from pid_reader.api import Cancelled  # noqa: E402
from pid_reader.engineering import raster_marks as rm  # noqa: E402
from test_revx_vector_network import network_pdf  # noqa: E402

PW, PH = 600.0, 400.0


def scan_of(ops) -> bytes:
    """Render a vector drawing to an image and wrap it as an image-only PDF (a scan)."""
    import pypdfium2 as pdfium
    vec = network_pdf(ops)
    img = pdfium.PdfDocument(vec)[0].render(scale=2.5).to_pil().convert("L")
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(PW, PH), pageCompression=0, invariant=1)
    c.drawImage(ImageReader(img), 0, 0, width=PW, height=PH)
    c.showPage()
    c.save()
    return buf.getvalue()


def at(res, x, y, kind, tol=0.02):
    nx, ny = x / PW, 1 - y / PH
    return [m for m in res["marks"] if m["kind"] == kind and abs((m["bbox"]["x0"] + m["bbox"]["x1"]) / 2 - nx) < tol and abs((m["bbox"]["y0"] + m["bbox"]["y1"]) / 2 - ny) < tol]


@pytest.mark.parametrize("raster", [False, True])
def test_dot_on_a_crossing_is_found_with_arms(raster):
    ops = [("line", 50, 200, 350, 200), ("line", 200, 120, 200, 330), ("dot", 200, 200)]
    pdf = scan_of(ops) if raster else network_pdf(ops)
    res = rm.detect_marks(pdf, 1)
    hits = at(res, 200, 200, "JUNCTION_DOT_CANDIDATE")
    assert len(hits) == 1 and hits[0]["arms"] >= 3 and hits[0]["status"] == "SUPPORTS_JOINED_AS_DRAWN" and hits[0]["review_state"] == "PROPOSED"


def test_dot_on_a_t_junction_is_found():
    res = rm.detect_marks(scan_of([("line", 50, 200, 350, 200), ("line", 200, 200, 200, 330), ("dot", 200, 200)]), 1)
    assert len(at(res, 200, 200, "JUNCTION_DOT_CANDIDATE")) == 1


def test_plain_crossing_has_no_dot():
    res = rm.detect_marks(scan_of([("line", 50, 200, 350, 200), ("line", 200, 120, 200, 330)]), 1)
    assert res["counts"]["dots"] == 0


def test_isolated_blob_is_not_a_junction_dot():
    res = rm.detect_marks(scan_of([("line", 50, 100, 350, 100), ("dot", 300, 300)]), 1)
    assert res["counts"]["dots"] == 0


def test_dot_at_a_line_end_with_one_arm_is_not_a_junction():
    res = rm.detect_marks(scan_of([("line", 50, 200, 200, 200), ("dot", 200, 200)]), 1)
    assert res["counts"]["dots"] == 0


@pytest.mark.parametrize("ang,vec", [(0, (1, 0)), (180, (-1, 0))])
def test_arrow_on_a_line_gives_direction_along_it(ang, vec):
    res = rm.detect_marks(scan_of([("line", 50, 200, 350, 200), ("arrow", 200, 200, ang)]), 1)
    a = at(res, 200, 200, "ARROW_HEAD", tol=0.03)
    assert len(a) == 1 and a[0]["direction"] == "ALONG_DRAWN_LINE"
    assert abs(a[0]["vector"][0] - vec[0]) < 0.35 and abs(a[0]["vector"][1]) < 0.35


def test_vertical_arrow_uses_top_left_axes():
    res = rm.detect_marks(scan_of([("line", 200, 80, 200, 330), ("arrow", 200, 200, 90)]), 1)
    a = at(res, 200, 200, "ARROW_HEAD", tol=0.03)
    assert a and a[0]["direction"] == "ALONG_DRAWN_LINE" and a[0]["vector"][1] < -0.6


def test_arrow_not_on_a_line_is_unknown():
    res = rm.detect_marks(scan_of([("line", 50, 100, 350, 100), ("arrow", 200, 300, 0)]), 1)
    a = at(res, 200, 300, "ARROW_HEAD", tol=0.03)
    assert a and a[0]["direction"] == "UNKNOWN" and a[0]["vector"] is None


def test_blank_page_has_no_marks_and_is_complete():
    res = rm.detect_marks(scan_of([]), 1)
    assert res["marks"] == [] and res["status"] == "COMPLETE_CANDIDATES"


def test_tile_cap_makes_the_result_partial(monkeypatch):
    monkeypatch.setattr(rm, "MAX_TILES", 1)
    res = rm.detect_marks(scan_of([("line", 50, 200, 350, 200)]), 1, tile_px=300, overlap_px=50)
    assert res["status"] == "PARTIAL" and res["incomplete"][0]["reason"] == "TILE_CAP"


def test_deterministic_cancelable_and_bad_page():
    pdf = scan_of([("line", 50, 200, 350, 200), ("line", 200, 120, 200, 330), ("dot", 200, 200)])
    assert rm.detect_marks(pdf, 1) == rm.detect_marks(pdf, 1)

    class Cancel:
        def check(self):
            raise Cancelled()
    with pytest.raises(Cancelled):
        rm.detect_marks(pdf, 1, cancel=Cancel())
    with pytest.raises(ValueError):
        rm.detect_marks(pdf, 4)
