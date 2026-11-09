"""WPU-07/08 (vector): tiling for dense sheets, typed junctions, dots, hops, arrows and direction."""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).parent))
pytest.importorskip("pdfplumber")
from pid_reader.api import Cancelled  # noqa: E402
from pid_reader.engineering import vector_network as vn  # noqa: E402

PW, PH = 600.0, 400.0


def network_pdf(ops: list[tuple], size=(PW, PH)) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=size, pageCompression=0, invariant=1)
    c.setLineWidth(0.8)
    for op in ops:
        kind = op[0]
        if kind == "line":
            c.line(*op[1:5])
        elif kind == "dot":
            c.circle(op[1], op[2], 2.2, stroke=0, fill=1)
        elif kind == "hop":                                   # small bridging arc over a horizontal line
            x, y = op[1], op[2]
            p = c.beginPath()
            p.moveTo(x - 5, y)
            p.curveTo(x - 5, y + 7, x + 5, y + 7, x + 5, y)
            c.drawPath(p, stroke=1, fill=0)
        elif kind == "arrow":                                 # filled triangle, apex pointing along `ang` degrees (ccw, PDF axes)
            import math
            x, y, ang = op[1], op[2], math.radians(op[3])
            ux, uy = math.cos(ang), math.sin(ang)
            nx, ny = -uy, ux
            pts = [(x + ux * 6, y + uy * 6), (x - ux * 3 + nx * 3.2, y - uy * 3 + ny * 3.2), (x - ux * 3 - nx * 3.2, y - uy * 3 - ny * 3.2)]
            p = c.beginPath()
            p.moveTo(*pts[0])
            p.lineTo(*pts[1])
            p.lineTo(*pts[2])
            p.close()
            c.drawPath(p, stroke=0, fill=1)
        elif kind == "dense":
            n = op[1]
            for i in range(n):
                x = 15 + (i % 120) * 4.7
                y = 12 + (i // 120) * 1.9
                c.line(x, y, x + 2.2, y + 0.6)
    c.showPage()
    c.save()
    return buf.getvalue()


def top(y: float, ph: float = PH) -> float:
    return ph - y


def junction_near(res: dict, x: float, y: float, ph: float = PH, tol: float = 6.0):
    px, py = x / res["page_size_pt"][0], top(y, ph) / res["page_size_pt"][1]
    best = [j for j in res["junctions"] if abs(j["point_norm"][0] - px) * res["page_size_pt"][0] < tol and
            abs(j["point_norm"][1] - py) * res["page_size_pt"][1] < tol]
    return best


def analyse(ops, **kw):
    return vn.analyze_vector_network(network_pdf(ops, kw.pop("size", (PW, PH))), 1, **kw)


# ---------------------------------------------------------------- junction typing: positives
def test_t_junction_is_joined_favoured_and_a_drawn_connection_hypothesis():
    r = analyse([("line", 50, 200, 350, 200), ("line", 200, 200, 200, 330)])
    j = junction_near(r, 200, 200)
    assert len(j) == 1 and j[0]["geometry"] == "BRANCH_TEE_AMBIGUOUS" and j[0]["status"] == "JOINED_FAVOURED" and j[0]["relation"] == "DRAWN_CONNECTS"


def test_dot_at_a_crossing_supports_joined():
    r = analyse([("line", 50, 200, 350, 200), ("line", 200, 120, 200, 330), ("dot", 200, 200)])
    j = junction_near(r, 200, 200)
    assert j and j[0]["status"] == "JOINED_SUPPORTED" and j[0]["supports"]["dot"] and j[0]["relation"] == "DRAWN_CONNECTS"
    assert r["counts"]["dots"] == 1


def test_hop_at_a_crossing_supports_separated():
    r = analyse([("line", 50, 200, 350, 200), ("line", 200, 120, 200, 330), ("hop", 200, 200)])
    j = junction_near(r, 200, 200)
    assert j and all(x["status"] in ("SEPARATED_SUPPORTED",) for x in j if x["geometry"] == "CROSSING_AMBIGUOUS")
    assert any(x["supports"]["hop"] for x in j) and r["counts"]["hops"] == 1
    assert all(x["relation"] is None for x in j if x["geometry"] == "CROSSING_AMBIGUOUS")


def test_unmarked_right_angle_crossing_favours_separated_and_keeps_the_alternative():
    r = analyse([("line", 50, 200, 350, 200), ("line", 200, 120, 200, 330)])
    j = junction_near(r, 200, 200)[0]
    assert j["status"] == "SEPARATED_FAVOURED" and j["relation"] is None and j["alternatives"][0]["status"] == "JOINED_FAVOURED"


def test_skew_crossing_stays_unknown():
    r = analyse([("line", 50, 200, 350, 200), ("line", 150, 170, 250, 230)])
    j = junction_near(r, 200, 200)[0]
    assert j["status"] == "UNKNOWN_CROSSING" and j["angle_between_deg"] < 60


def test_corner_end_to_end_touch_is_joined_favoured():
    r = analyse([("line", 50, 200, 200, 200), ("line", 200, 200, 200, 330)])
    j = junction_near(r, 200, 200)[0]
    assert j["geometry"] == "ENDPOINT_TOUCH_CANDIDATE" and j["status"] == "JOINED_FAVOURED"


# ---------------------------------------------------------------- negatives
def test_near_miss_is_not_bridged():
    r = analyse([("line", 50, 200, 198, 200), ("line", 204, 200, 350, 200)])
    assert junction_near(r, 200, 200) == [] and r["counts"]["junctions"] == 0


def test_duplicate_overlapping_strokes_are_not_a_connection():
    r = analyse([("line", 50, 200, 300, 200), ("line", 100, 200, 250, 200)])
    j = junction_near(r, 175, 200, tol=80)
    assert j and all(x["status"] == "DUPLICATE_OR_OVERLAP" and x["relation"] is None for x in j)


def test_dot_far_from_a_crossing_does_not_join_it():
    r = analyse([("line", 50, 200, 350, 200), ("line", 200, 120, 200, 330), ("dot", 320, 320)])
    assert junction_near(r, 200, 200)[0]["status"] == "SEPARATED_FAVOURED"


def test_empty_page_has_no_junctions_and_is_complete():
    r = analyse([])
    assert r["status"] == "COMPLETE_CANDIDATES" and r["counts"]["strokes"] == 0 and r["junctions"] == []


# ---------------------------------------------------------------- arrows and direction
@pytest.mark.parametrize("ang,vec", [(0, (1, 0)), (180, (-1, 0))])
def test_arrow_aligned_with_a_stroke_gives_direction_along_it(ang, vec):
    r = analyse([("line", 50, 200, 350, 200), ("arrow", 200, 200, ang)])
    a = r["arrows"][0]
    assert a["direction"] == "ALONG_DRAWN_STROKE" and a["stroke_id"]
    assert abs(a["vector"][0] - vec[0]) < 0.05 and abs(a["vector"][1]) < 0.05


def test_vertical_arrow_direction_uses_top_left_axes():
    r = analyse([("line", 200, 80, 200, 330), ("arrow", 200, 200, 90)])             # PDF 90 deg = up on the page
    a = r["arrows"][0]
    assert a["direction"] == "ALONG_DRAWN_STROKE" and a["vector"][1] < -0.9          # up = negative y in the top-left frame


def test_arrow_not_on_any_line_is_unknown_never_assumed():
    r = analyse([("line", 50, 100, 350, 100), ("arrow", 200, 300, 0)])
    assert r["arrows"][0]["direction"] == "UNKNOWN" and r["arrows"][0]["stroke_id"] is None


def test_arrow_across_a_line_is_unknown():
    r = analyse([("line", 50, 200, 350, 200), ("arrow", 200, 200, 90)])
    assert r["arrows"][0]["direction"] == "UNKNOWN"


def test_no_arrow_means_no_direction_claim():
    r = analyse([("line", 50, 200, 350, 200)])
    assert r["arrows"] == []


# ---------------------------------------------------------------- tiling (dense sheets)
def test_dense_sheet_is_tiled_and_loses_no_junction():
    structure = [("line", 40, 40, 560, 40), ("line", 300, 40, 300, 380)]            # T-ish at (300, 40)
    r = analyse(structure + [("dense", 9000)], size=(PW, PH))
    assert r["counts"]["strokes"] > 9000 and r["counts"]["tiles"] > 1 and r["status"] == "COMPLETE_CANDIDATES"
    assert max(t["strokes"] for t in r["tiles"]) < vn.TILE_TARGET * 2.2
    assert any(j["status"].startswith("JOINED") for j in junction_near(r, 300, 40))


def test_junction_straddling_a_tile_seam_is_found_exactly_once():
    big = (1200.0, 800.0)
    ops = [("line", 100, 300, 1100, 300), ("line", 600, 300, 600, 700), ("dense", 8000)]
    r = analyse(ops, size=big, tile_target=1500)
    assert r["counts"]["tiles"] > 1
    hits = [j for j in junction_near(r, 600, 300, ph=800.0, tol=3.0) if j["geometry"] == "BRANCH_TEE_AMBIGUOUS"]
    assert len(hits) == 1


def test_hard_cap_makes_the_page_partial_and_says_so():
    r = analyse([("dense", 3000)], max_page_segments=1000)
    assert r["status"] == "PARTIAL" and r["incomplete"][0]["reason"] == "PAGE_SEGMENT_CAP" and r["counts"]["strokes"] == 1000


def test_small_page_is_one_tile_and_untruncated():
    r = analyse([("line", 50, 200, 350, 200), ("line", 200, 200, 200, 330)])
    assert r["counts"]["tiles"] == 1 and r["incomplete"] == [] and r["status"] == "COMPLETE_CANDIDATES"


def test_result_is_deterministic_and_normalised():
    ops = [("line", 50, 200, 350, 200), ("line", 200, 120, 200, 330), ("dot", 200, 200)]
    a, b = analyse(ops), analyse(ops)
    assert a == b
    for s in a["strokes"]:
        assert all(0 <= v <= 1 for v in s["p0"] + s["p1"])


def test_cancel_and_bad_page():
    class Cancel:
        def check(self):
            raise Cancelled()
    pdf = network_pdf([("line", 50, 200, 350, 200), ("dense", 500)])
    with pytest.raises(Cancelled):
        vn.analyze_vector_network(pdf, 1, cancel=Cancel())
    with pytest.raises(ValueError):
        vn.analyze_vector_network(pdf, 9)


def test_curves_are_kept_as_flattened_polylines_with_a_shared_path_id():
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(PW, PH), pageCompression=0, invariant=1)
    p = c.beginPath()
    p.moveTo(100, 100)
    p.curveTo(150, 250, 250, 250, 300, 100)
    p.curveTo(320, 60, 360, 60, 380, 100)
    c.drawPath(p, stroke=1, fill=0)
    c.showPage()
    c.save()
    r = vn.analyze_vector_network(buf.getvalue(), 1)
    curve = [s for s in r["strokes"] if s["kind"] == "CURVE"]
    assert curve and len({s["path_id"] for s in curve}) == 1
