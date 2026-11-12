"""Readiness gates for recurring operation. Recurring (scheduled) running is allowed only when every gate is PASS.

Gates: valid configuration; finite plan; reviewed corpus with disjoint validation; successful guarded pilot (baseline evaluation and
a training slice); working pause/cancel/resume evidence; correct runtime/memory reporting; verified handoff export.
A gate that has not been exercised is NOT_RUN, which blocks readiness exactly like FAIL. Nothing here changes any model or project data.
"""
import json
import zipfile
from pathlib import Path

from .data import validate
from .store import Store

KNOWN_KINDS = ("TRAIN_OCR", "EVALUATE_OCR", "EVALUATE_BASELINE_OCR", "EXPERIMENT_WP08")
MIN_TRAIN_READABLE = 40
MIN_VALIDATION_READABLE = 20
FORBIDDEN_HANDOFF_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".pdf", ".safetensors", ".pth", ".bin", ".onnx", ".pt")


def _gate(status, **evidence):
    return dict(status=status, **evidence)


def check_config(config):
    problems = []
    for key in ("repository", "state_dir", "backend_python", "core_python", "plan_file"):
        if not config.get(key):
            problems.append(f"missing {key}")
    state = str(config.get("state_dir", ""))
    if "onedrive" in state.lower():
        problems.append("state_dir must be outside OneDrive")
    for key in ("backend_python", "core_python"):
        if config.get(key) and not Path(config[key]).is_file():
            problems.append(f"{key} does not exist")
    wall, rss, daily = config.get("max_wall_seconds", 1800), config.get("max_tree_memory_mb", 4096), config.get("daily_compute_seconds", 7200)
    if wall > 1800 or rss > 4096 or daily > 7200:
        problems.append("resource limits exceed the agreed budgets (30 min slice, 4 GiB tree, 2 h/day)")
    if config.get("require_ac") is False:
        problems.append("AC-power requirement was disabled")
    if config.get("claude_review_enabled"):
        problems.append("claude review adapter enabled; it must stay disabled unless its executable and budget are verified")
    return _gate("PASS" if not problems else "FAIL", problems=problems)


def check_plan(config):
    path = Path(config.get("plan_file", ""))
    if not path.is_file():
        return _gate("FAIL", problems=["plan file missing"])
    try:
        plan = json.loads(path.read_text(encoding="utf8"))
    except ValueError:
        return _gate("FAIL", problems=["plan is not JSON"])
    if not isinstance(plan, list) or not 1 <= len(plan) <= 50:
        return _gate("FAIL", problems=["plan must be a finite list of 1..50 jobs"])
    bad = [e.get("kind") for e in plan if e.get("kind") not in KNOWN_KINDS]
    pilot_train = [e for e in plan if e.get("kind") == "TRAIN_OCR"]
    problems = [f"unknown job kind {k}" for k in bad]
    for e in pilot_train:
        p = e.get("payload", {})
        if p.get("max_steps", 0) > 100 or p.get("max_steps_per_slice", 25) > 25 or p.get("checkpoint_every", 5) > 5:
            problems.append("pilot training exceeds 100 steps / 25 per slice / checkpoint every 5")
    return _gate("PASS" if not problems else "FAIL", jobs=len(plan), problems=problems)


def check_corpus(config):
    out = {}
    try:
        train, train_sha = validate(config["train_dataset"], purpose="train")
        val, val_sha = validate(config["validation_dataset"], purpose="validate")
    except (KeyError, ValueError, FileNotFoundError, OSError) as exc:
        return _gate("NOT_RUN" if isinstance(exc, KeyError) else "FAIL", problems=[type(exc).__name__ + ": " + str(exc)])
    problems = []
    human_train = [r for r in train if r["origin"] == "HUMAN_SOURCE_PIXELS"]
    if {r["family_id"] for r in train} & {r["family_id"] for r in val}:
        problems.append("training and validation share a drawing family")
    if {r["source_sha256"] for r in train} & {r["source_sha256"] for r in val} or {r["image_sha256"] for r in train} & {r["image_sha256"] for r in val}:
        problems.append("training and validation share a source or crop")
    if any(r.get("adjudication") not in ("ADJUDICATED",) for r in val):
        problems.append("validation contains items that are not adjudicated")
    if len(human_train) < MIN_TRAIN_READABLE or len(val) < MIN_VALIDATION_READABLE:
        problems.append(f"need TRAIN >= {MIN_TRAIN_READABLE} human-reviewed and VALIDATION >= {MIN_VALIDATION_READABLE} adjudicated readable crops; have {len(human_train)} / {len(val)} (text-layer/synthetic proxy items do not count)")
    out.update(train_items=len(train), human_reviewed_train_items=len(human_train), proxy_train_items=len(train) - len(human_train), validation_items=len(val), train_sha256=train_sha, validation_sha256=val_sha, problems=problems)
    return _gate("PASS" if not problems else "FAIL", **out)


def _jobs(store):
    return [dict(r) for r in store.db.execute("SELECT id,kind,status,result FROM jobs")]


def check_pilot(store):
    jobs = _jobs(store)
    base = [j for j in jobs if j["kind"] == "EVALUATE_BASELINE_OCR" and j["status"] == "SUCCEEDED"]
    train = [j for j in jobs if j["kind"] == "TRAIN_OCR" and j["status"] in ("SUCCEEDED", "PARTIAL")]
    if not base or not train:
        return _gate("NOT_RUN", baseline_evaluations=len(base), training_slices_ok=len(train))
    return _gate("PASS", baseline_evaluations=len(base), training_jobs=len(train))


def check_controls(state_dir):
    path = Path(state_dir) / "evidence" / "controls_verified.json"
    if not path.is_file():
        return _gate("NOT_RUN", reason="run `verify_controls` first")
    doc = json.loads(path.read_text(encoding="utf8"))
    ok = all(doc.get(k) == "PASS" for k in ("pause", "cancel", "resume"))
    return _gate("PASS" if ok else "FAIL", **{k: doc.get(k) for k in ("pause", "cancel", "resume")}, verified_utc=doc.get("utc"))


def check_memory_reporting(store):
    seen = []
    for j in _jobs(store):
        if j["result"]:
            guard = json.loads(j["result"]).get("guard") or {}
            if guard.get("peak_tree_rss_mb"):
                seen.append(guard["peak_tree_rss_mb"])
    return _gate("PASS" if seen else "NOT_RUN", jobs_with_process_tree_peak=len(seen), max_peak_tree_rss_mb=max(seen) if seen else None)


def check_handoff(store):
    root = store.root / "handoffs"
    latest = root / "LATEST_RESULTS.json"
    if not latest.is_file():
        return _gate("NOT_RUN", reason="no export yet")
    zips = sorted(root.glob("PID_LONGTERM_RESULTS_*.zip"))
    if not zips:
        return _gate("FAIL", problems=["no result zip"])
    with zipfile.ZipFile(zips[-1]) as z:
        bad = [n for n in z.namelist() if n.lower().endswith(FORBIDDEN_HANDOFF_SUFFIXES)]
    problems = (["handoff zip contains images/weights/drawings: " + ", ".join(bad[:5])] if bad else []) + (["audit chain invalid"] if store.verify() else [])
    return _gate("PASS" if not problems else "FAIL", zip=zips[-1].name, problems=problems)


def readiness(config):
    gates = dict(configuration=check_config(config), plan=check_plan(config), corpus=check_corpus(config))
    state = Path(config["state_dir"])
    if (state / "programme.sqlite").is_file():
        store = Store(state)
        try:
            gates.update(guarded_pilot=check_pilot(store), controls=check_controls(state), memory_reporting=check_memory_reporting(store), handoff_export=check_handoff(store))
        finally:
            store.close()
    else:
        for name in ("guarded_pilot", "controls", "memory_reporting", "handoff_export"):
            gates[name] = _gate("NOT_RUN", reason="no programme state yet")
    ready = all(g["status"] == "PASS" for g in gates.values())
    return dict(ready=ready, gates=gates, rule="recurring operation only when every gate is PASS; NOT_RUN blocks like FAIL")
