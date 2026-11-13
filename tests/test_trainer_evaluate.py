"""Automatic scoring of finished runs: pooling, the keep/reject rule, lineage bookkeeping, caching and failure handling (scoring itself is injected; no torch)."""
import json
from pathlib import Path

import pytest

from pid_reader.engineering.trainer_service import evaluate as ev
from pid_reader.engineering.trainer_service import service


def summ(plans=12, **per):
    """A scored-set summary from per-class (tp, fp, fn) triples; classes not given are zero."""
    pc = {c: dict(tp=0, fp=0, fn=0) for c in ev.CLASSES}
    for c, (tp, fp, fn) in per.items():
        pc[c] = dict(tp=tp, fp=fp, fn=fn)
    return dict(plans=plans, per_class=pc, valve_plus_instrumentation={}, weights="w", scored_utc="t")


GOOD = dict(valve=(80, 20, 20), instrumentation=(90, 10, 10), general=(50, 50, 50), arrow=(30, 70, 70))
WEAKER_GENERAL = dict(valve=(80, 20, 20), instrumentation=(90, 10, 10), general=(30, 70, 70), arrow=(30, 70, 70))
BETTER = dict(valve=(85, 15, 15), instrumentation=(92, 8, 8), general=(60, 40, 40), arrow=(40, 60, 60))
WORSE_MAIN = dict(valve=(60, 40, 40), instrumentation=(80, 20, 20), general=(50, 50, 50), arrow=(30, 70, 70))


def lineage_with(state, n=2):
    state = Path(state)
    (state / "lineage").mkdir(parents=True, exist_ok=True)
    entries = []
    for i in range(1, n + 1):
        w = state / "lineage" / f"run{i:03d}_weights.pt"
        w.write_bytes(b"w%d" % i)
        entries.append(dict(id=i, weights=str(w), sha256=f"{i:064x}", iters=10, epochs=1, lr=0.005, parent=i - 1 or None, status="usable", notes=""))
    service.write_json(state / "lineage.json", entries)
    return entries


def fake_eval(table, calls=None):
    """run_eval(which, tag, out) -> summary; ``table`` maps a run name ('run001', 'run002', 'E5') to {'open100': per, 'holdout': per}."""
    def run(which, tag, out):
        name = tag.rsplit("_", 1)[0]
        if calls is not None:
            calls.append(tag)
        return summ(plans=12 if which == "open100" else 26, **table[name][which])
    return run


def test_pooling_sums_counts_before_computing_f1():
    p = ev.pool({"a": summ(valve=(8, 2, 2)), "b": summ(valve=(2, 8, 8))})
    assert p["per_class"]["valve"]["tp"] == 10 and p["per_class"]["valve"]["fp"] == 10 and p["plans"] == 24
    assert p["per_class"]["valve"]["f1"] == 0.5 and p["per_class"]["general"]["f1"] == 0.0
    assert p["main_f1"] == 0.5 and p["macro_f1"] == round(0.5 / 4, 3)


def test_the_rule_keeps_equal_or_better_runs_and_rejects_clearly_worse_ones():
    base = ev.pool({"o": summ(**GOOD)})
    assert ev.verdict(ev.pool({"o": summ(**BETTER)}), base)["decision"] == "keep"
    assert ev.verdict(base, base)["decision"] == "keep"
    worse_macro = ev.verdict(ev.pool({"o": summ(**WEAKER_GENERAL)}), base)
    assert worse_macro["decision"] == "reject" and any("macro" in r for r in worse_macro["reasons"])
    worse_main = ev.verdict(ev.pool({"o": summ(**WORSE_MAIN)}), base)
    assert worse_main["decision"] == "reject" and any("valve+instrumentation" in r for r in worse_main["reasons"])
    assert ev.verdict(ev.pool({"o": summ(**WEAKER_GENERAL)}), base, auto_reject=False)["auto_reject"] is False


def test_a_candidate_card_pins_its_own_weights_and_is_labelled_candidate(tmp_path):
    e = lineage_with(tmp_path, 1)[0]
    card = json.loads(Path(ev.candidate_card(tmp_path, e)).read_text())
    assert card["weights_sha256"] == e["sha256"] and card["weights_file"] == "run001_weights.pt" and "CANDIDATE" in card["model_id"] and card["limitations"].startswith("CANDIDATE ONLY")
    assert card["classes"] == ev.CLASSES and card["threshold"] == 0.65


def test_scoring_a_run_compares_it_with_its_parent_records_it_and_caches(tmp_path):
    lineage_with(tmp_path, 2)
    table = {"run001": dict(open100=GOOD), "run002": dict(open100=BETTER)}
    calls = []
    res = ev.evaluate_entry(tmp_path, 2, dict(auto_reject=True), run_eval=fake_eval(table, calls))
    assert res["compared_to"] == "run001" and res["verdict"]["decision"] == "keep" and res["pooled"]["macro_f1"] > res["baseline_pooled"]["macro_f1"]
    assert sorted(calls) == ["run001_open100", "run002_open100"] and "KEPT" in res["summary"]
    entry = service.read_lineage(tmp_path)[1]
    assert entry["eval"]["verdict"]["decision"] == "keep" and entry["status"] == "usable"
    calls.clear()
    ev.evaluate_entry(tmp_path, 2, dict(auto_reject=True), run_eval=fake_eval(table, calls))
    assert calls == []                                              # both models are cached: a repeat costs nothing


def test_the_first_run_is_compared_with_e5_and_a_clearly_worse_run_is_rejected_but_kept_on_disk(tmp_path):
    lineage_with(tmp_path, 1)
    table = {"E5": dict(open100=GOOD), "run001": dict(open100=WORSE_MAIN)}
    res = ev.evaluate_entry(tmp_path, 1, dict(auto_reject=True), run_eval=fake_eval(table))
    assert res["compared_to"] == "E5" and res["verdict"]["decision"] == "reject"
    e = service.read_lineage(tmp_path)[0]
    assert e["status"] == "rejected" and e["notes"].startswith("auto:") and Path(e["weights"]).is_file()          # never deleted
    assert service.resolve_init(tmp_path, "auto")[1] is None         # the next 'auto' run skips it and falls back to E5


def test_with_auto_reject_off_a_worse_run_stays_usable(tmp_path):
    lineage_with(tmp_path, 1)
    table = {"E5": dict(open100=GOOD), "run001": dict(open100=WORSE_MAIN)}
    res = ev.evaluate_entry(tmp_path, 1, dict(auto_reject=False), run_eval=fake_eval(table))
    assert res["verdict"]["decision"] == "reject" and service.read_lineage(tmp_path)[0]["status"] == "usable" and "not rejected" in res["summary"]


def test_the_extra_held_out_plans_are_pooled_with_open100_when_the_manifest_lists_them(tmp_path):
    lineage_with(tmp_path, 1)
    tiles = tmp_path / "tiles"
    tiles.mkdir()
    (tiles / "TILES_MANIFEST.json").write_text(json.dumps({"holdout_plans": ["Dataset PID/70.png"]}))
    table = {"E5": dict(open100=GOOD, holdout=GOOD), "run001": dict(open100=BETTER, holdout=BETTER)}
    res = ev.evaluate_entry(tmp_path, 1, dict(tiles_dir=str(tiles)), run_eval=fake_eval(table))
    assert set(res["sets"]) == {"open100", "holdout"} and res["pooled"]["plans"] == 12 + 26
    assert res["pooled"]["per_class"]["valve"]["tp"] == 170


def test_guarded_scoring_reports_skips_failures_and_cancels_without_raising(tmp_path, monkeypatch):
    assert ev.evaluate_guarded(tmp_path, {})["state"] == "SKIPPED"                                   # nothing finished yet
    lineage_with(tmp_path, 1)
    st = ev.evaluate_guarded(tmp_path, dict(eval_root=str(tmp_path / "nope")))
    assert st["state"] == "SKIPPED"                                                                   # NO_EVAL switch from conftest (and a missing folder) both skip
    monkeypatch.delenv("PID_TRAINER_NO_EVAL")
    st = ev.evaluate_guarded(tmp_path, dict(eval_root=str(tmp_path / "nope")))
    assert st["state"] == "SKIPPED" and "D: drive" in st["message"]

    def boom(which, tag, out):
        raise RuntimeError("inference crashed")
    st = ev.evaluate_guarded(tmp_path, {}, run_eval=boom)
    assert st["state"] == "FAILED" and "inference crashed" in st["message"]
    st = ev.evaluate_guarded(tmp_path, {}, run_eval=lambda *a: None)                                   # a cancelled scoring returns None
    assert st["state"] == "CANCELLED"
    ok = ev.evaluate_guarded(tmp_path, {}, run_eval=fake_eval({"E5": dict(open100=GOOD), "run001": dict(open100=BETTER)}))
    assert ok["state"] == "DONE" and ok["decision"] == "keep" and "run001 vs E5" in ok["message"]
    service.write_json(tmp_path / "service.json", dict(state="COMPLETED", pid=999999, heartbeat_utc=service.now()))
    assert service.status(tmp_path)["evaluation"]["state"] == "DONE"                                  # the status shows the scoring result


def test_scoring_is_pending_only_for_a_finished_unscored_run_with_nothing_else_going(tmp_path):
    lineage_with(tmp_path, 1)
    assert not ev.evaluation_pending(tmp_path)                                                         # no service.json: no finished run
    service.write_json(tmp_path / "service.json", dict(state="RUNNING", pid=999999, heartbeat_utc=service.now()))
    assert not ev.evaluation_pending(tmp_path)                                                         # a run that is going/was cut off is not a finished one
    service.write_json(tmp_path / "service.json", dict(state="COMPLETED", pid=999999, heartbeat_utc=service.now()))
    assert ev.evaluation_pending(tmp_path)
    service.write_json(tmp_path / "config.json", dict(auto_evaluate=False))
    assert not ev.evaluation_pending(tmp_path)                                                         # the user switched it off
    service.write_json(tmp_path / "config.json", dict(auto_evaluate=True))
    entries = service.read_lineage(tmp_path)
    entries[0]["eval"] = {"done": True}
    service.write_json(tmp_path / "lineage.json", entries)
    assert not ev.evaluation_pending(tmp_path)                                                         # already scored
