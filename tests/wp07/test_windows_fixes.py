"""Defects found by running the real models on Windows (S418 tile coverage), not by the Linux package tests."""
import pytest

from pid_reader.engineering.model_lab import core
from pid_reader.engineering.model_lab.adapters import clip_xyxy


def test_edge_overshoot_is_clipped_to_the_crop_so_the_crop_is_not_lost():
    assert clip_xyxy([-3.2, 10, 50, 20.5], (100, 40)) == [0.0, 10.0, 50.0, 20.5]
    assert clip_xyxy([90, 5, 104.7, 41], (100, 40)) == [90.0, 5.0, 100.0, 40.0]


def test_box_with_no_visible_area_is_dropped_not_invented():
    assert clip_xyxy([-8, 3, -1, 9], (100, 40)) is None
    assert clip_xyxy([100.0, 3, 120, 9], (100, 40)) is None
    assert clip_xyxy([10, 10, 10.4, 30], (100, 40)) is None


def test_clipped_box_passes_the_strict_record_check_while_the_raw_one_is_refused():
    manifest = dict(engine="easyocr", revision="r", model_dir=".")
    request = dict(id="t", page=1, bbox=[.1, .1, .3, .2], rotation=0, source_sha256="0" * 64, image_sha256="1" * 64)
    raw = dict(kind="TEXT", text="X", score=.5, xyxy=[-4.0, 2.0, 60.0, 30.0])
    with pytest.raises(ValueError):
        core.record(raw, request, manifest, (100, 40), 0)
    raw["xyxy"] = clip_xyxy(raw["xyxy"], (100, 40))
    assert core.record(raw, request, manifest, (100, 40), 0)["bbox"]["x0"] >= .1


def test_peak_memory_is_reported_where_psutil_or_resource_exists():
    from pid_reader.engineering.model_lab.runtime import metadata
    try:
        import psutil  # noqa: F401
    except ImportError:
        pytest.skip("psutil not installed here; the model runtime lists it")
    meta = metadata()
    assert isinstance(meta["peak_worker_rss_mib"], float) and meta["peak_worker_rss_mib"] > 10
