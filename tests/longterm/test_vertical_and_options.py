"""Vertical budget and recogniser decoding constraints."""
import pytest

from pid_reader.engineering.longterm import vertical as V
from pid_reader.engineering.model_lab import core


def reg(i, y, text):
    return dict(id=i, bbox=dict(x0=.1, y0=y, x1=.12, y1=y + .1), vertical=True, source_text=text)


def test_budget_caps_at_six_reports_omissions_and_both_turns():
    cands = [reg(f"v{k}", k / 20, "A" * (k + 3)) for k in range(9)] + [dict(id="h", bbox=dict(x0=0, y0=0, x1=.1, y1=.01), vertical=False)]
    sel, omitted = V.select(cands)
    assert len(sel) == 6 and len(omitted) == 3 and all(c["vertical"] for c in sel + omitted)
    rep = V.report(sel, omitted, {c["id"] for c in sel[:4]})
    assert rep["requested"] == 9 and rep["scheduled"] == 6 and rep["completed"] == 4 and len(rep["not_completed"]) == 2
    assert rep["turns_each"] == [90, 270] and len(rep["omitted_by_budget"]) == 3


def test_selection_is_deterministic_and_never_exceeds_the_budget_setting():
    cands = [reg(f"v{k}", k / 20, "AB-123") for k in range(8)]
    assert V.select(cands)[0] == V.select(list(reversed(cands)))[0]
    with pytest.raises(ValueError):
        V.select(cands, 7)


def request(**options):
    return dict(coordinate_frame=core.FRAME, bbox=[.1, .1, .2, .2], page=1, id="a", source_sha256="0" * 64, rotation=0, image_path=__file__, image_sha256="x", **options)


def test_only_letters_or_digits_allowlists_are_accepted(tmp_path):
    p = tmp_path / "c.png"
    p.write_bytes(b"png")
    good = request(options=dict(allowlist="letters"))
    good.update(image_path=str(p), image_sha256=core.digest(p))
    core.validate_request(good)
    for bad in (dict(allowlist="alnum"), dict(allowlist="letters", repair=True), "letters"):
        r = dict(good, options=bad)
        with pytest.raises(ValueError):
            core.validate_request(r)
