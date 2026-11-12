"""Pilot machinery: strict fixed-crop report, predeclared verdict, WP08 gate, readiness gates, ledger ordering, handoff content."""
import json
import zipfile

import pytest

from pid_reader.engineering.longterm import evaluate as E
from pid_reader.engineering.longterm import readiness as R
from pid_reader.engineering.longterm import runner, worker
from pid_reader.engineering.longterm.handoff import export
from pid_reader.engineering.longterm.store import Store


def rows(n, controls=()):
    return [dict(id=f"i{k}", text=f"GHS-{k}", category="LINE_LABEL", control=k in controls) for k in range(n)]


def test_report_is_strict_and_keeps_format_matches_separate():
    r = rows(4)
    rep = E.report(r, ["GHS-0", "GHS -1", "ghs-2", "GS-3"])
    assert rep["strict_exact"] == 1 and rep["format_normalised_exact"] == 2 and rep["strict_errors"] == 3
    assert rep["items"][2]["outcome"] == "WRONG"                      # case is never folded


def test_verdict_uses_the_frozen_target_and_protects_controls():
    r = rows(12, controls=(0, 1))
    base = E.report(r, ["GHS-0", "GHS-1"] + ["x"] * 10)                 # 10 errors
    good = E.report(r, ["GHS-0", "GHS-1", "GHS-2", "GHS-3", "x"] + ["x"] * 7)   # 8 errors = 20 % fewer
    out = E.pilot_verdict(base, good, E.PILOT_TARGET_DEFAULT)
    assert out["verdict"] == "TARGET_MET_DEVELOPMENT_ONLY" and out["relative_strict_error_reduction"] == pytest.approx(.2)
    lost = E.report(r, ["x", "GHS-1", "GHS-2", "GHS-3", "GHS-4"] + ["x"] * 7)
    assert E.pilot_verdict(base, lost, E.PILOT_TARGET_DEFAULT)["verdict"] == "TARGET_NOT_MET"
    assert E.pilot_verdict(base, lost, E.PILOT_TARGET_DEFAULT)["lost_easy_controls"] == ["i0"]
    small = E.report(rows(3), ["x", "x", "x"])
    assert E.pilot_verdict(small, small, E.PILOT_TARGET_DEFAULT)["verdict"] == "INCONCLUSIVE_TOO_FEW_BASELINE_ERRORS"


def test_baseline_cache_key_changes_with_model_dataset_and_is_stable():
    m = dict(files={"model.safetensors": "a"}, revision="r1")
    k = E.baseline_cache_key(m, "d1")
    assert k == E.baseline_cache_key(dict(m), "d1") and k != E.baseline_cache_key(m, "d2") and k != E.baseline_cache_key(dict(m, revision="r2", files={"model.safetensors": "b"}), "d1")


def test_wp08_job_is_blocked_explicitly_when_the_delta_is_missing(tmp_path):
    out = tmp_path / "o"
    out.mkdir()
    res = worker.execute(dict(kind="EXPERIMENT_WP08", payload={}), out)
    assert res["status"] == "BLOCKED" and "WP08_UNAVAILABLE" in res["reason"]


def test_targets_are_in_the_ledger_before_jobs_are_enqueued(tmp_path):
    store = Store(tmp_path / "s")
    plan = [dict(kind="EVALUATE_OCR", payload=dict(target=E.PILOT_TARGET_DEFAULT))]
    runner.declare_targets(store, plan)
    runner.declare_targets(store, plan)                                 # idempotent
    kinds = [json.loads(r[0])["kind"] for r in store.db.execute("SELECT payload FROM events")]
    assert kinds == ["PREDECLARED_TARGET"] and store.verify() == []


def config(tmp_path, **kw):
    py = tmp_path / "python.exe"
    py.write_text("")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([dict(kind="EVALUATE_BASELINE_OCR", payload={})]))
    base = dict(repository="C:/repo", state_dir=str(tmp_path / "state"), backend_python=str(py), core_python=str(py), plan_file=str(plan))
    base.update(kw)
    return base


def test_config_gate_enforces_budgets_and_location(tmp_path):
    assert R.check_config(config(tmp_path))["status"] == "PASS"
    assert R.check_config(config(tmp_path, max_tree_memory_mb=8192))["status"] == "FAIL"
    assert R.check_config(config(tmp_path, require_ac=False))["status"] == "FAIL"
    assert R.check_config(config(tmp_path, claude_review_enabled=True))["status"] == "FAIL"
    assert R.check_config(config(tmp_path, state_dir="C:/Users/x/OneDrive - Co/state"))["status"] == "FAIL"


def test_plan_gate_limits_the_pilot_and_rejects_unknown_kinds(tmp_path):
    c = config(tmp_path)
    assert R.check_plan(c)["status"] == "PASS"
    (tmp_path / "plan.json").write_text(json.dumps([dict(kind="TRAIN_OCR", payload=dict(max_steps=500))]))
    assert R.check_plan(c)["status"] == "FAIL"
    (tmp_path / "plan.json").write_text(json.dumps([dict(kind="RUN_SHELL", payload={})]))
    assert R.check_plan(c)["status"] == "FAIL"


def test_not_run_gates_block_readiness_like_a_failure(tmp_path):
    out = R.readiness(config(tmp_path))
    assert out["ready"] is False
    assert out["gates"]["corpus"]["status"] == "NOT_RUN" and out["gates"]["controls"]["status"] == "NOT_RUN"


def test_handoff_pilot_summary_and_no_images_or_weights(tmp_path):
    store = Store(tmp_path / "s")
    with store.db:
        store.event("PREDECLARED_TARGET", target_sha256="x" * 64, target=E.PILOT_TARGET_DEFAULT, job_kind="EVALUATE_OCR")
    path = export(store, force=True)
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
    assert not [n for n in names if n.lower().endswith(R.FORBIDDEN_HANDOFF_SUFFIXES)]
    latest = json.loads((store.root / "handoffs" / "LATEST_RESULTS.json").read_text())
    assert latest["pilot"]["baseline_evaluations"] == 0 and "Human review" in latest["pilot"]["next_finite_experiment"]
    assert latest["pilot"]["predeclared_targets"][0]["target"]["min_relative_strict_error_reduction"] == .2
    assert R.check_handoff(store)["status"] == "PASS"
