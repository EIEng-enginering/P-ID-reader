"""Automatic scoring of a finished training run, so a new model is never left unchecked.

When a run finishes the runner calls :func:`evaluate_guarded`: it scores the new weights on the held-out plans (PID2Graph OPEN100, plus the extra held-out real plans listed in the
tiles manifest when present), scores the PARENT run (or the repo's E5 weights for the first run) the same way, compares them, records everything in ``lineage.json`` and, if the new
run is clearly worse, marks it ``rejected`` so the next run builds on the better one (``auto_reject``, on by default). Weights are never deleted. Scoring uses the dataset authors'
labels on public data: it is a development measurement, not an accuracy claim about the owner's drawings. It runs at low priority, honours the CANCEL file, and a failure here
never changes the finished run (the status shows why, and ``python -m pid_reader.cli trainer evaluate`` repeats it).
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import policy
from .service import E5_WEIGHTS, LINEAGE_FILE, ROOT, mark_lineage, now, read_json, read_lineage, write_json

CLASSES = ["valve", "instrumentation", "general", "arrow"]
MACRO_DROP = 0.01          # reject when the four-class macro F1 falls by more than this ...
MAIN_DROP = 0.03           # ... or valve+instrumentation F1 falls by more than this, versus the parent
EVAL_TOOL = ROOT / "tools" / "data" / "eval_pid2graph.py"
E5_CARD = ROOT / "models" / "E5_MODEL_CARD.json"
DEFAULT_ROOT = r"D:\Data P&ID\PID2Graph_zenodo_14803338"
TOOL_TIMEOUT_S = 6 * 3600


def f1_of(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    return 0.0 if not p or not r else 2 * p * r / (p + r)


def pool(sets):
    """Sum tp/fp/fn per class over the scored sets and derive F1 from the pooled counts. ``sets`` = {name: summary}."""
    per = {c: dict(tp=0, fp=0, fn=0) for c in CLASSES}
    for s in sets.values():
        for c in CLASSES:
            for k in ("tp", "fp", "fn"):
                per[c][k] += int(s["per_class"][c][k])
    for c in CLASSES:
        per[c]["f1"] = round(f1_of(**{k: per[c][k] for k in ("tp", "fp", "fn")}), 3)
        tp, fp, fn = per[c]["tp"], per[c]["fp"], per[c]["fn"]
        per[c]["precision"] = round(tp / (tp + fp), 3) if tp + fp else None
        per[c]["recall"] = round(tp / (tp + fn), 3) if tp + fn else None
    main = {k: per["valve"][k] + per["instrumentation"][k] for k in ("tp", "fp", "fn")}
    return dict(per_class=per, macro_f1=round(sum(per[c]["f1"] for c in CLASSES) / len(CLASSES), 3), main_f1=round(f1_of(**main), 3), plans=sum(int(s.get("plans", 0)) for s in sets.values()))


def verdict(new, base, auto_reject=True):
    """Compare pooled scores. 'reject' only when clearly worse on the macro F1 or on the main classes; otherwise 'keep' (the run stays usable)."""
    d_macro = round(new["macro_f1"] - base["macro_f1"], 3)
    d_main = round(new["main_f1"] - base["main_f1"], 3)
    reasons = []
    if d_macro < -MACRO_DROP:
        reasons.append(f"macro F1 fell by {-d_macro:.3f} (limit {MACRO_DROP})")
    if d_main < -MAIN_DROP:
        reasons.append(f"valve+instrumentation F1 fell by {-d_main:.3f} (limit {MAIN_DROP})")
    gains = {c: round(new["per_class"][c]["f1"] - base["per_class"][c]["f1"], 3) for c in CLASSES}
    return dict(decision="reject" if reasons else "keep", reasons=reasons, auto_reject=bool(auto_reject), macro_f1_change=d_macro, main_f1_change=d_main, f1_change_by_class=gains)


def describe(entry_name, base_name, new, base, v):
    gains = ", ".join(f"{c} {v['f1_change_by_class'][c]:+.2f}" for c in CLASSES)
    text = (f"{entry_name} vs {base_name}: macro F1 {new['macro_f1']:.3f} vs {base['macro_f1']:.3f} ({v['macro_f1_change']:+.3f}); valve+instrumentation F1 {new['main_f1']:.3f} vs "
            f"{base['main_f1']:.3f} ({v['main_f1_change']:+.3f}); by class {gains}. ")
    if v["decision"] == "reject":
        text += ("REJECTED (" + "; ".join(v["reasons"]) + ")" if v["auto_reject"] else "WORSE, not rejected (auto_reject is off): " + "; ".join(v["reasons"]))
    else:
        text += "KEPT (usable)."
    return text


def candidate_card(state_dir, entry):
    """A model card for a lineage run, copied from the E5 card with its own weights checksum and a CANDIDATE label (the E5 card pins E5's checksum and refuses other weights)."""
    card = json.loads(E5_CARD.read_text(encoding="utf8"))
    name = f"run{entry['id']:03d}"
    card.update(model_id=f"tr1-frcnn-pid2graph-{name}-CANDIDATE", producer="tr1-trainer-service", weights_file=Path(entry["weights"]).name, weights_sha256=entry["sha256"],
                training=f"CANDIDATE from the background trainer service, lineage run {entry['id']} (parent {entry.get('parent')}); epochs {entry.get('epochs')}, lr {entry.get('lr')}, "
                         f"{entry.get('iters')} iterations", measured="see lineage.json 'eval'")
    card["limitations"] = "CANDIDATE ONLY - not promoted, not validated on owner drawings. " + str(card.get("limitations", ""))
    path = Path(entry["weights"]).with_name(f"{name}_card.json")
    path.write_text(json.dumps(card, indent=1), encoding="utf8")
    return str(path)


def _kill_tree(proc):
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.kill()


def run_eval_tool(cfg, weights, card, which, out_dir, tag, manifest=None, cancel=None):
    """Run tools/data/eval_pid2graph.py for one held-out set; returns its summary dict (per-plan detail dropped), or None if cancelled."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(EVAL_TOOL), "--root", cfg.get("eval_root") or DEFAULT_ROOT, "--weights", str(weights), "--card", str(card), "--out", str(out_dir), "--tag", tag,
           "--threads", str(cfg.get("threads", 2))]
    if which == "holdout":
        cmd += ["--holdout-manifest", str(manifest), "--plans", "100"]
    env = dict(os.environ, PIDLAB_TR1_PYTHON=str(cfg.get("torch_python") or ""), PYTHONPATH=str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""))
    flags = 0x00004000 if os.name == "nt" else 0                       # BELOW_NORMAL_PRIORITY_CLASS: keep the machine usable
    log = open(out_dir / f"{tag}_{which}.log", "ab")
    proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=flags)
    started = time.time()
    while proc.poll() is None:
        if cancel and cancel():
            _kill_tree(proc)
            return None
        if time.time() - started > TOOL_TIMEOUT_S:
            _kill_tree(proc)
            raise TimeoutError(f"scoring {which} took longer than {TOOL_TIMEOUT_S // 3600} hours")
        time.sleep(2)
    if proc.returncode != 0:
        raise RuntimeError(f"the scoring tool failed on {which} (exit {proc.returncode}); see {out_dir / f'{tag}_{which}.log'}")
    res = json.loads((out_dir / f"{tag}_{which}_results.json").read_text(encoding="utf8"))
    return dict(plans=res["plans"], per_class=res["per_class"], valve_plus_instrumentation=res["valve_plus_instrumentation"], weights=str(weights), scored_utc=now())


def score_weights(state, name, weights, card, cfg, run_eval=None, cancel=None):
    """Summaries per held-out set for one model, cached under <state>/eval/<name>/ so a repeat costs nothing. None when cancelled."""
    state = Path(state)
    manifest = Path(cfg["tiles_dir"]) / "TILES_MANIFEST.json" if cfg.get("tiles_dir") else None
    holdout = bool(manifest and manifest.is_file() and (read_json(manifest, {}) or {}).get("holdout_plans"))
    run_eval = run_eval or (lambda which, tag, out: run_eval_tool(cfg, weights, card, which, out, tag, manifest=manifest, cancel=cancel))
    sets = {}
    for which in (["open100", "holdout"] if holdout else ["open100"]):
        cache = state / "eval" / name / f"{which}.json"
        got = read_json(cache)
        if got is None or got.get("weights") != str(weights):
            got = run_eval(which, f"{name}_{which}", state / "eval" / name / "work")
            if got is None:
                return None
            got = dict(got, weights=str(weights))                       # the cache is valid only for exactly these weights
            write_json(cache, got)
        sets[which] = got
    return sets


def evaluate_entry(state, entry_id, cfg, run_eval=None, cancel=None, progress=None):
    """Score lineage run ``entry_id`` and its parent (or E5), store the comparison in lineage.json, and reject it if clearly worse. Returns the eval dict, or None if cancelled."""
    state = Path(state)
    entries = read_lineage(state)
    entry = next((e for e in entries if e["id"] == entry_id), None)
    if entry is None:
        raise ValueError(f"no finished run {entry_id} in the lineage")
    parent = next((e for e in entries if e["id"] == entry.get("parent")), None)
    say = progress or (lambda msg: None)
    if parent:
        base_name, base_weights, base_card = f"run{parent['id']:03d}", parent["weights"], candidate_card(state, parent)
    else:
        base_name, base_weights, base_card = "E5", str(E5_WEIGHTS), str(E5_CARD)
    name = f"run{entry['id']:03d}"
    say(f"scoring {name} on the held-out plans")
    new_sets = score_weights(state, name, entry["weights"], candidate_card(state, entry), cfg, run_eval, cancel)
    if new_sets is None:
        return None
    say(f"scoring {base_name} (the parent) the same way")
    base_sets = score_weights(state, base_name, base_weights, base_card, cfg, run_eval, cancel)
    if base_sets is None:
        return None
    new, base = pool(new_sets), pool(base_sets)
    v = verdict(new, base, cfg.get("auto_reject", True))
    text = describe(name, base_name, new, base, v)
    result = dict(scored_utc=now(), compared_to=base_name, sets={k: dict(plans=s["plans"], per_class=s["per_class"]) for k, s in new_sets.items()}, pooled=new, baseline_pooled=base,
                  verdict=v, summary=text, label="DEVELOPMENT MEASUREMENT on public PID2Graph held-out plans; not an accuracy claim about the owner's drawings")
    entries = read_lineage(state)
    for e in entries:
        if e["id"] == entry_id:
            e["eval"] = result
    write_json(state / LINEAGE_FILE, entries)
    if v["decision"] == "reject" and v["auto_reject"]:
        mark_lineage(state, entry_id, "rejected", notes="auto: " + "; ".join(v["reasons"]))
    return result


def _set_status(state_dir, **fields):
    path = Path(state_dir) / "evaluation.json"
    cur = read_json(path, {}) or {}
    cur.update(fields, updated_utc=now())
    write_json(path, cur, strict=False)


def evaluate_guarded(state, cfg, entry_id=None, run_eval=None, cancel=None):
    """The runner's / CLI's entry point: never raises, records progress in <state>/evaluation.json, returns that status dict."""
    state = Path(state)
    entries = read_lineage(state)
    if not entries:
        _set_status(state, state="SKIPPED", message="no finished run to score", pid=None)
        return read_json(state / "evaluation.json")
    entry_id = entry_id or entries[-1]["id"]
    root = Path(cfg.get("eval_root") or DEFAULT_ROOT)
    if run_eval is None and os.environ.get("PID_TRAINER_NO_EVAL"):                   # the env switch is for tests: they must never start a real scoring run
        _set_status(state, state="SKIPPED", entry=entry_id, pid=None, message="scoring disabled by PID_TRAINER_NO_EVAL")
        return read_json(state / "evaluation.json")
    if run_eval is None and not (root / "PID2Graph" / "Complete").exists():
        _set_status(state, state="SKIPPED", entry=entry_id, pid=None, message=f"the data folder {root} was not found (is the D: drive connected?). Connect it and run: python -m pid_reader.cli trainer evaluate")
        return read_json(state / "evaluation.json")
    if run_eval is None and not Path(cfg.get("torch_python") or "").is_file():
        _set_status(state, state="SKIPPED", entry=entry_id, pid=None, message="the torch environment was not found")
        return read_json(state / "evaluation.json")
    _set_status(state, state="RUNNING", entry=entry_id, pid=os.getpid(), started_utc=now(), message="scoring started")
    try:
        res = evaluate_entry(state, entry_id, cfg, run_eval=run_eval, cancel=cancel, progress=lambda m: _set_status(state, message=m))
        if res is None:
            _set_status(state, state="CANCELLED", pid=None, message="scoring was cancelled; run: python -m pid_reader.cli trainer evaluate")
        else:
            _set_status(state, state="DONE", pid=None, message=res["summary"], decision=res["verdict"]["decision"])
    except Exception as exc:                                          # noqa: BLE001  scoring must never harm a finished run
        _set_status(state, state="FAILED", pid=None, message=f"{type(exc).__name__}: {exc}")
    return read_json(state / "evaluation.json")


def evaluation_pending(state):
    """True when the last run finished, nothing else is going, and its weights have not been scored (used by the logon task to finish scoring after a restart)."""
    from .service import status
    state = Path(state)
    entries = read_lineage(state)
    st = read_json(state / "service.json", {}) or {}
    if not entries or st.get("state") != "COMPLETED" or entries[-1].get("eval"):
        return False
    cfg = read_json(state / "config.json", {}) or {}
    if cfg.get("auto_evaluate", True) is False:
        return False
    ev = read_json(state / "evaluation.json", {}) or {}
    if ev.get("state") == "RUNNING" and policy.pid_alive(ev.get("pid")):
        boot = policy.boot_time()
        try:
            from datetime import datetime
            fresh = boot is None or datetime.fromisoformat(ev["updated_utc"]).timestamp() >= boot - 5
        except (KeyError, ValueError):
            fresh = False
        if fresh:
            return False
    return status(state).get("state") == "COMPLETED"


def spawn_evaluation(state, python=None):
    """Start the scoring as its own detached low-priority process (python -m pid_reader.cli trainer evaluate)."""
    exe = Path(python or sys.executable)
    if os.name == "nt" and exe.with_name("pythonw.exe").is_file():
        exe = exe.with_name("pythonw.exe")
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""))
    cmd = [str(exe), "-m", "pid_reader.cli", "trainer", "evaluate", "--state-dir", str(state)]
    kw = dict(cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    if os.name == "nt":
        base = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW | 0x00004000
        try:
            subprocess.Popen(cmd, creationflags=base | 0x01000000, **kw)
        except OSError:
            subprocess.Popen(cmd, creationflags=base, **kw)
    else:
        subprocess.Popen(cmd, start_new_session=True, **kw)
    return True
