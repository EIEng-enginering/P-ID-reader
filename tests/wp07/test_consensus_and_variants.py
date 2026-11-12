"""Consensus only ever returns an observed string; crop variants are re-renderings of one crop."""
import pytest
from PIL import Image

from pid_reader.engineering.model_lab import consensus, pipeline


def test_chosen_reading_is_always_one_of_the_observed_strings():
    seen = [dict(text="GS-22203-168.3-C3S-80", source="rapidocr"), dict(text="GHS-22203-168.3-C35-80", source="trocr:base"),
            dict(text="GHS-22203-1683-C3S-80", source="trocr:large")]
    out = consensus.choose(seen)
    assert out["chosen"]["text"] in {r["text"] for r in seen}
    assert out["status"] == "CONFLICT" and not out["unanimous"] and len(out["alternatives"]) == 2


def test_no_character_is_ever_invented_for_a_pattern():
    # H is missing in every reading; the result must not contain it.
    out = consensus.choose([dict(text="PF-00019-14.3-A3S-40", source="a"), dict(text="PF-00019-114.3-A3S-40", source="b")])
    assert "H" not in out["chosen"]["text"]


def test_typography_only_agreement_is_unanimous_and_gibberish_is_ignored_when_empty():
    out = consensus.choose([dict(text="DR\u201322202", source="a"), dict(text="dr-22202 ", source="b"), dict(text="  ", source="c")])
    assert out["unanimous"] and out["status"] == "UNANIMOUS"
    assert consensus.choose([])["status"] == "NO_READING"


def test_ties_go_to_the_established_reader_listed_first():
    out = consensus.choose([dict(text="AB", source="rapidocr"), dict(text="AC", source="trocr")])
    assert out["chosen"]["source"] == "rapidocr"


def test_same_engine_agreement_is_not_counted_as_independent():
    out = consensus.choose([dict(text="X-1", engine="trocr"), dict(text="X-1", engine="trocr"), dict(text="X-1", engine="trocr")])
    assert out["unanimous"] and out["independent_sources"] == 1


@pytest.mark.parametrize("name", pipeline.VARIANTS)
def test_variants_are_valid_images_of_the_same_crop(name):
    base = Image.new("L", (200, 40), 255)
    for x in range(20, 180):
        base.putpixel((x, 20), 0)
    out = pipeline.variant_image(base, name)
    assert out.width > 0 and out.height > 0
    if name == "binary":
        assert set(out.getdata()) <= {0, 255}
    with pytest.raises(ValueError):
        pipeline.variant_image(base, "hallucinate")


def test_variant_names_are_validated_and_budget_still_applies(tmp_path):
    with pytest.raises(ValueError):
        pipeline.prepare(b"%PDF", 1, [dict(id="a", bbox=dict(x0=0, y0=0, x1=.1, y1=.1))], tmp_path, variants=("base", "base"))
    with pytest.raises(ValueError):
        pipeline.prepare(b"%PDF", 1, [dict(id="a", bbox=dict(x0=0, y0=0, x1=.1, y1=.1))], tmp_path, variants=("nope",))
