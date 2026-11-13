"""Scoring logic of the OPEN100 / ASU symbol evaluators (pure functions, no torch)."""
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "tools" / "data"
sys.path.insert(0, str(DATA))
import eval_pid2graph as E  # noqa: E402
import eval_symbol_baseline as B  # noqa: E402


def test_class_must_match_and_matching_is_one_to_one():
    gts = [(0, 0, 10, 10, "valve"), (50, 50, 60, 60, "instrumentation")]
    preds = [(0, 0, 10, 10, .9, "valve"), (1, 1, 10, 10, .8, "valve"),          # second valve box has nothing left to match: a false positive
             (50, 50, 60, 60, .7, "valve")]                                       # right place, wrong class: fp for valve, instrument is missed
    r = E.score_plan(preds, gts, 0.5)
    assert r["valve"] == dict(tp=1, fp=2, fn=0) and r["instrumentation"] == dict(tp=0, fp=0, fn=1)


def test_the_score_threshold_removes_weak_predictions():
    gts = [(0, 0, 10, 10, "arrow")]
    preds = [(0, 0, 10, 10, .4, "arrow")]
    assert E.score_plan(preds, gts, .65)["arrow"] == dict(tp=0, fp=0, fn=1)
    assert E.score_plan(preds, gts, .3)["arrow"] == dict(tp=1, fp=0, fn=0)


def test_precision_recall_f1_and_empty_denominators():
    assert E.prf(8, 2, 2) == dict(tp=8, fp=2, fn=2, precision=.8, recall=.8, f1=.8)
    out = E.prf(0, 0, 0)
    assert out["precision"] is None and out["recall"] is None and out["f1"] is None


def test_symbol_baseline_ap_is_perfect_for_perfect_detections_and_lower_when_boxes_miss():
    gt = [[0, 0, .1, .1], [.5, .5, .6, .6]]
    perfect = [([[0, 0, .1, .1, .9, 0], [.5, .5, .6, .6, .8, 0]], gt)]
    assert B.evaluate(perfect)["ap50"] == 1.0
    miss = [([[0, 0, .1, .1, .9, 0], [.8, .8, .9, .9, .8, 0]], gt)]
    r = B.evaluate(miss)
    assert r["ap50"] < 1.0 and r["max_recall"] == .5


def test_holdout_plans_come_from_the_manifest_and_skip_missing_files(tmp_path):
    import json
    base = tmp_path / "PID2Graph" / "Complete" / "Dataset PID"
    base.mkdir(parents=True)
    for n in (70, 87):
        (base / f"{n}.png").write_bytes(b"x")
        (base / f"{n}.graphml").write_text("<g/>")
    (base / "104.png").write_bytes(b"x")                                         # no graph file: skipped
    man = tmp_path / "TILES_MANIFEST.json"
    man.write_text(json.dumps({"holdout_plans": ["Dataset PID/70.png", "Dataset PID/87.png", "Dataset PID/104.png", "Dataset PID/999.png"]}))
    got = E.holdout_plans(tmp_path, man)
    assert [g.stem for g, _ in got] == ["70", "87"] and all(i.suffix == ".png" for _, i in got)
