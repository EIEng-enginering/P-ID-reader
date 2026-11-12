"""Bubble geometry on synthetic bubbles: divider located, bands exclude ring/divider, abstention when there is no text evidence."""
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from pid_reader.engineering.longterm import bubbles as B

FONT = "C:/Windows/Fonts/arial.ttf"


def font(size):
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        pytest.skip("no TrueType font available")


def make(shape="circle", code="PSV", number="220101", divider=True, size=72, r=30):
    im = Image.new("L", (size, size), 255)
    d = ImageDraw.Draw(im)
    c = size // 2
    if shape == "circle":
        d.ellipse([c - r, c - r, c + r, c + r], outline=0, width=3)
    else:
        d.rectangle([c - r, c - r, c + r, c + r], outline=0, width=3)
    f = font(13)
    if divider:
        d.line([c - r + 3, c, c + r - 3, c], fill=0, width=2)
    if code:
        d.text((c, c - 9 if divider else c - 7), code, fill=0, font=f, anchor="mm")
    if number:
        d.text((c, c + 11), number, fill=0, font=f, anchor="mm")
    return np.array(im)


def test_circle_with_divider_gives_two_bands_that_avoid_ring_and_divider():
    g = make()
    out = B.analyse(g)
    assert out["status"] == "OK" and out["ring"] is not None
    assert abs(out["divider_y"] - 36) <= 2.5
    cb, nb = out["code_band"], out["number_band"]
    assert cb[3] <= out["divider_y"] + 1 and nb[1] >= out["divider_y"] - 1
    cx, cy, r = out["ring"]["cx"], out["ring"]["cy"], out["ring"]["r"]
    for box in (cb, nb):
        assert (box[0] - cx) ** 2 + (box[1] - cy) ** 2 < r ** 2 * 1.3   # corners stay near the interior, not on the ring stroke
        assert box[2] - box[0] > 10


def test_no_divider_gives_a_single_band_and_withholds_the_number():
    out = B.analyse(make(divider=False, number=None))
    assert "NO_DIVIDER" in out["flags"] and out["number_band"] is None and out["code_band"] is not None
    assert out["status"] == "PARTIAL"


def test_blank_bubble_abstains_instead_of_offering_empty_crops():
    out = B.analyse(make(code=None, number=None))
    assert out["status"] == "ABSTAIN" and out["code_band"] is None and out["number_band"] is None
    assert "NO_TEXT_INK" in out["flags"]


def test_square_panel_uses_the_box_interior():
    out = B.analyse(make(shape="box", code="ESD", number="000007"), shape="box")
    assert out["ring"] is None and out["divider_y"] is not None and out["status"] == "OK"


def test_tiny_crop_abstains():
    out = B.analyse(np.full((10, 10), 255, np.uint8))
    assert out["status"] == "ABSTAIN"


def test_interior_crop_masks_the_ring_and_keeps_text():
    g = make()
    out = B.analyse(g)
    inner = B.interior_crop(g, out)
    assert inner[0, 0] == 255 and (inner < 128).sum() > 20 and (inner < 128).sum() < (g < 128).sum()


def test_media_mapping_is_linear():
    box = B.to_media_box([10, 20, 30, 40], dict(x0=.2, y0=.4, x1=.3, y1=.5), (100, 100))
    assert box == pytest.approx(dict(x0=.21, y0=.42, x1=.23, y1=.44))


def test_dashed_divider_is_still_found():
    g = make()
    c = 36
    for x in range(0, 72, 3):                       # knock every third pixel out of the divider rows, as a 1-bit scan can
        g[c - 1:c + 1, x] = 255
    out = B.analyse(g)
    assert out["divider_y"] is not None and abs(out["divider_y"] - 36) <= 2.5 and out["status"] == "OK"


def test_a_long_text_line_alone_is_not_mistaken_for_a_divider():
    out = B.analyse(make(divider=False, code="PSVXYZ12", number=None))
    assert "NO_DIVIDER" in out["flags"]


def test_stacked_text_without_a_divider_line_is_split_by_its_real_row_gap():
    out = B.analyse(make(divider=False))
    assert out["status"] == "OK" and "BANDS_FROM_ROW_GAP" in out["flags"] and "NO_DIVIDER" in out["flags"]
    assert out["code_band"][3] <= out["number_band"][1]


def test_three_text_row_groups_abstain_instead_of_guessing():
    g = np.full((72, 72), 255, np.uint8)
    for y0 in (20, 32, 44):
        g[y0:y0 + 6, 22:50] = 0
    out = B.analyse(g, shape="box")
    assert out["status"] == "ABSTAIN" and any(f.startswith("AMBIGUOUS_ROW_GROUPS") for f in out["flags"])
