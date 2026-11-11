"""R3 components behind their own switches (default OFF): tile-merge policy choice, guarded correction queue, tag assignment, join hints, fine subtype stage."""
from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from pid_reader.tr1 import detector, flags, mapping, proposals, review, store, tag_assign
from pid_reader.tr1.corrections import QueueError
from pid_reader.tr1.corrections_guard import MachineActorRefused

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures"
TORCH_PY = os.environ.get("PIDLAB_TEST_TORCH_PYTHON", r"C:\PIDWork\venv312_torch\Scripts\python.exe")
needs_torch = pytest.mark.skipif(not Path(TORCH_PY).is_file(), reason="optional torch component not installed")


# ------------------------------------------------------------------------------------------------------------------------------ switches
def test_r3_switches_default_off_and_the_merge_choice_defaults_to_r1():
    for n in ("PIDLAB_TAG_ASSIGN_R3", "PIDLAB_GRAPH_CONSERVATIVE_R3", "PIDLAB_FINE_CLASS_R3"):
        assert n in flags.FLAGS and not flags.enabled(n)
    assert flags.choice("PIDLAB_TILE_MERGE_R3") == "r1_drop_inner_edge"
    inv = flags.inventory()
    assert inv["choices"]["PIDLAB_TILE_MERGE_R3"]["value"] == "r1_drop_inner_edge"


def test_merge_choice_round_trip_environment_wins_and_unknown_is_an_error(monkeypatch):
    assert flags.set_choice("PIDLAB_TILE_MERGE_R3", "edge_safe") == "edge_safe"
    assert flags.choice("PIDLAB_TILE_MERGE_R3") == "edge_safe"
    flags.set_flag("PIDLAB_FINE_CLASS_R3", True)                                # a boolean write must not lose the choice
    assert flags.choice("PIDLAB_TILE_MERGE_R3") == "edge_safe" and flags.enabled("PIDLAB_FINE_CLASS_R3")
    monkeypatch.setenv("PIDLAB_TILE_MERGE_R3", "edge_safe+coarse")
    assert flags.choice("PIDLAB_TILE_MERGE_R3") == "edge_safe+coarse"
    monkeypatch.setenv("PIDLAB_TILE_MERGE_R3", "everything")
    with pytest.raises(ValueError):
        flags.choice("PIDLAB_TILE_MERGE_R3")
    with pytest.raises(ValueError):
        flags.set_choice("PIDLAB_TILE_MERGE_R3", "nope")


# ------------------------------------------------------------------------------------------------------------- guarded correction queue
DOC = "a" * 64


def _det(i="frc-1"):
    return mapping.enrich({"id": i, "page": 1, "bbox": {"x0": 0.1, "y0": 0.1, "x1": 0.2, "y1": 0.2}, "catalogue_class": "valve", "raw_score": 0.9,
                           "score_kind": "UNCALIBRATED_FRCNN_SOFTMAX", "confidence_status": "LEADING", "review_state": "PROPOSED",
                           "evidence": {"producer": "tr1-frcnn-e5", "weights_sha256": "b" * 64, "truth_class": "MODEL_PROPOSAL"}})


@pytest.mark.parametrize("actor", ["auto:e5", "model:x", "pipeline:e5", "grok:r3", "Auto:Mixed"])
def test_a_machine_actor_can_import_but_never_review(monkeypatch, actor):
    monkeypatch.setenv("PIDLAB_CORRECTION_QUEUE_TR1", "on")
    monkeypatch.setenv("PIDLAB_SYMBOL_CATALOGUE_TR1", "on")
    d = _det()
    rec = {"source_sha256": DOC, "page": 1, "detections": [d]}
    with pytest.raises(MachineActorRefused):
        review.confirm(rec, d, actor)
    with pytest.raises(MachineActorRefused):
        review.reject(rec, d, actor)
    q = review._queue()
    assert [e["action"] for e in q.events()] == ["IMPORT_PROPOSAL"]             # the proposal was imported, nothing was submitted
    assert q.export_accepted() == [] and q.verify() == []
    prop = next(iter(q.state()["proposals"].values()))["proposal"]
    assert prop["truth_type"] == "MODEL_PSEUDOLABEL" and prop["review_state"] == "PROPOSED"
    assert review.confirm(rec, d, "Alice Example")["status"] == "ACCEPTED_FINAL"   # a named human can


def test_a_machine_second_reviewer_is_refused(monkeypatch):
    monkeypatch.setenv("PIDLAB_CORRECTION_QUEUE_TR1", "on")
    monkeypatch.setenv("PIDLAB_SYMBOL_CATALOGUE_TR1", "on")
    d = mapping.enrich(dict(_det("frc-w"), confidence_status="WEAK_CLASS_WITHHELD", raw_score=0.3))
    rec = {"source_sha256": DOC, "page": 1, "detections": [d]}
    res = review.confirm(rec, d, "Alice", class_id="CLS.VALVE.BALL")
    assert res["status"] == "AWAITING_SECOND_REVIEW"
    with pytest.raises(MachineActorRefused):
        review.second_review(res["correction_id"], "model:checker", True)
    with pytest.raises(QueueError, match="INDEPENDENT"):
        review.second_review(res["correction_id"], "Alice", True)


# --------------------------------------------------------------------------------------------------------------------- tag assignment
def _tag(i, x, y, w=60, h=20, text=None):
    return {"id": i, "box": (x, y, x + w, y + h), "text": text or i}


def _sym(i, x, y, s=50):
    return {"id": i, "box": (x, y, x + s, y + s), "cls": "instrumentation"}


def test_split_assignment_gives_the_same_answers_as_the_whole_problem():
    r = random.Random(5)
    tags = [_tag(f"T{i}", r.uniform(0, 1500), r.uniform(0, 900)) for i in range(40)]
    syms = [_sym(f"S{i}", r.uniform(0, 1500), r.uniform(0, 900)) for i in range(40)]
    whole = {x["tag"]: x for x in tag_assign.assign(tags, syms)}
    split = {x["tag"]: x for x in proposals.assign_split(tags, syms)}
    assert whole.keys() == split.keys()
    for k in whole:
        assert (whole[k]["symbol"], whole[k]["status"], whole[k]["cost"]) == (split[k]["symbol"], split[k]["status"], split[k]["cost"]), k


def test_tag_proposals_abstain_when_far_and_flag_off_refuses(monkeypatch):
    dets = [dict(_det("frc-a"), bbox={"x0": 0.10, "y0": 0.10, "x1": 0.15, "y1": 0.20}, coarse_class="instrumentation"),
            dict(_det("frc-b"), bbox={"x0": 0.50, "y0": 0.50, "x1": 0.55, "y1": 0.60}, coarse_class="instrumentation")]
    objs = [{"id": "o1", "page": 1, "class": "INSTRUMENT", "text": "PIT-101", "bbox": {"x0": 0.10, "y0": 0.205, "x1": 0.15, "y1": 0.225}},
            {"id": "o2", "page": 1, "class": "INSTRUMENT", "text": "FAR-9", "bbox": {"x0": 0.90, "y0": 0.05, "x1": 0.94, "y1": 0.07}},
            {"id": "o3", "page": 1, "class": "LINE", "text": "6-P-100", "bbox": {"x0": 0.1, "y0": 0.1, "x1": 0.2, "y1": 0.11}},
            {"id": "o4", "page": 2, "class": "INSTRUMENT", "text": "OTHER-PAGE", "bbox": {"x0": 0.5, "y0": 0.61, "x1": 0.55, "y1": 0.63}}]
    with pytest.raises(proposals.Unavailable):
        proposals.propose_tags(dets, objs, 1, (1000, 700))
    monkeypatch.setenv("PIDLAB_TAG_ASSIGN_R3", "on")
    res = proposals.propose_tags(dets, objs, 1, (1000, 700))
    assert res["tags_considered"] == 2                                               # the line number and the other page are not tags
    assert res["per_symbol"]["frc-a"]["tag_text"] == "PIT-101" and res["per_symbol"]["frc-a"]["review_state"] == "PROPOSED"
    assert "frc-b" not in res["per_symbol"] and res["unresolved_tags"] == ["o2"]       # the far tag abstains; nothing is forced


# ----------------------------------------------------------------------------------------------------------------------- join hints
def _page(draw):
    import numpy as np
    img = np.full((400, 900), 255, dtype=np.uint8)
    draw(img)
    return img


def test_join_hints_pair_only_a_line_that_touches_exactly_two_symbols(monkeypatch):
    def draw(img):
        for x0 in (50, 300, 600):                                   # three symbol outlines
            img[100:150, x0:x0 + 50] = 0
            img[104:146, x0 + 4:x0 + 46] = 255
        img[124:127, 100:300] = 0                                   # a line from symbol 1 to symbol 2 only
    dets = [dict(_det(f"frc-{i}"), bbox={"x0": x / 900, "y0": 100 / 400, "x1": (x + 50) / 900, "y1": 150 / 400}) for i, x in enumerate((50, 300, 600))]
    with pytest.raises(proposals.Unavailable):
        proposals.join_hints(dets, _page(draw))
    monkeypatch.setenv("PIDLAB_GRAPH_CONSERVATIVE_R3", "on")
    res = proposals.join_hints(dets, _page(draw))
    assert res["pairs"] == [("frc-0", "frc-1")] and res["unresolved_junction_components"] == 0 and "not" in res["note"].lower()

    def draw3(img):
        draw(img)
        img[124:127, 350:600] = 0                                   # the same line now also reaches symbol 3: a junction, nothing is joined
    res3 = proposals.join_hints(dets, _page(draw3))
    assert res3["pairs"] == [] and res3["unresolved_junction_components"] == 1


# --------------------------------------------------------------------------------------- detector runner passes the R3 options only when asked
def _fake(tmp_path, monkeypatch, with_fine=True):
    d = tmp_path / "models"
    d.mkdir()
    w = d / "T_weights.pt"
    w.write_bytes(b"weights")
    card = {"model_id": "fake-1", "producer": "fake", "classes": ["valve", "instrumentation", "general", "arrow"], "threshold": 0.65, "weights_file": "weights.pt",
            "weights_sha256": hashlib.sha256(w.read_bytes()).hexdigest(), "min_size": 800, "max_size": 800, "tile": 800, "overlap": 200, "pdf_render_scale": 2.5,
            "limitations": "fake"}
    (d / "T_MODEL_CARD.json").write_text(json.dumps(card), encoding="utf-8")
    if with_fine:
        fw = d / "fine.pt"
        fw.write_bytes(b"fine weights")
        (d / detector.FINE_CARD_NAME).write_text(json.dumps({"weights_file": "fine.pt", "weights_sha256": hashlib.sha256(fw.read_bytes()).hexdigest(), "model_id": "fine-1"}), encoding="utf-8")
    monkeypatch.setenv("PIDLAB_TR1_MODEL_DIR", str(d))
    monkeypatch.setenv("PIDLAB_SYMBOL_FRCNN_TR1", "on")
    monkeypatch.setattr(detector, "locate_python", lambda: sys.executable)
    monkeypatch.setattr(detector, "model_dirs", lambda: [d])          # only the fake models, never the real ones in the project
    script = tmp_path / "fake_infer.py"
    script.write_text(textwrap.dedent("""
        import hashlib, json, sys
        argv = sys.argv[1:]
        card = json.load(open(argv[0])); doc = hashlib.sha256(open(argv[2], "rb").read()).hexdigest()
        out = argv[argv.index("--out") + 1]
        ev = {"producer": "fake", "weights_sha256": card["weights_sha256"], "truth_class": "MODEL_PROPOSAL"}
        c = {"id": "frc-a", "page": 1, "bbox": {"x0": .1, "y0": .1, "x1": .2, "y1": .2}, "catalogue_class": "valve", "raw_score": .9, "score_kind": "X",
             "confidence_status": "LEADING", "review_state": "PROPOSED", "evidence": ev}
        if "--merge-policy" in argv: c["edge_partial"] = True
        if "--fine-card" in argv: c["fine"] = {"subtype_id": 3, "confidence": .9, "status": "PROPOSED", "names": "unverified"}
        json.dump({"schema": "tr1-frcnn-candidates-1", "source_sha256": doc, "page": 1, "model": "fake-1", "threshold": .65, "limitations": "x", "candidates": [c],
                   "diagnostics": {"argv": argv}}, open(out, "w"))
    """), encoding="utf-8")
    monkeypatch.setattr(detector, "INFER_SCRIPT", script)


def test_with_every_r3_switch_off_the_detector_command_is_exactly_the_r1_command(tmp_path, monkeypatch):
    _fake(tmp_path, monkeypatch)
    res = detector.detect(FIX / "synthetic_pid_vector.pdf", 1)
    assert res["status"] == "DONE", res
    argv = res["diagnostics"]["argv"]
    assert "--merge-policy" not in argv and "--fine-card" not in argv and "edge_partial" not in res["detections"][0] and "fine" not in res["detections"][0]


def test_merge_policy_and_fine_stage_are_passed_only_when_switched_on(tmp_path, monkeypatch):
    _fake(tmp_path, monkeypatch)
    monkeypatch.setenv("PIDLAB_TILE_MERGE_R3", "edge_safe")
    monkeypatch.setenv("PIDLAB_FINE_CLASS_R3", "on")
    res = detector.detect(FIX / "synthetic_pid_vector.pdf", 1)
    assert res["status"] == "DONE", res
    argv = res["diagnostics"]["argv"]
    assert argv[argv.index("--merge-policy") + 1] == "edge_safe" and "--fine-card" in argv and "--fine-weights" in argv
    d = res["detections"][0]
    assert d["edge_partial"] is True and d["fine"]["status"] == "PROPOSED" and d["fine"]["names"] == "unverified" and d["review_state"] == "PROPOSED"
    assert res["record"]["merge_policy"] == "edge_safe"


def test_fine_stage_missing_or_tampered_is_reported_and_detection_still_works(tmp_path, monkeypatch):
    _fake(tmp_path, monkeypatch)
    monkeypatch.setenv("PIDLAB_FINE_CLASS_R3", "on")
    (tmp_path / "models" / "fine.pt").write_bytes(b"tampered")
    detector._hash_cache.clear()
    res = detector.detect(FIX / "synthetic_pid_vector.pdf", 1)
    assert res["status"] == "DONE" and "--fine-card" not in res["diagnostics"]["argv"] and any("Fine subtype" in n for n in res["notices"])


@pytest.mark.parametrize("bad", [{"status": "PROPOSED", "subtype_id": None, "names": "unverified"}, {"status": "ACCEPTED", "subtype_id": 1, "names": "unverified"},
                                 {"status": "PROPOSED", "subtype_id": 1, "names": "Gate valve"}, "text"])
def test_a_malformed_fine_result_is_refused(tmp_path, monkeypatch, bad):
    _fake(tmp_path, monkeypatch)
    card = store.read_json(next((tmp_path / "models").glob("*_MODEL_CARD.json")))
    c = {"id": "x", "page": 1, "bbox": {"x0": .1, "y0": .1, "x1": .2, "y1": .2}, "catalogue_class": "valve", "review_state": "PROPOSED", "confidence_status": "LEADING",
         "evidence": {"weights_sha256": card["weights_sha256"]}, "fine": bad}
    res = {"schema": detector.SCHEMA_IN, "source_sha256": "s", "page": 1, "model": "fake-1", "candidates": [c]}
    assert any(p.startswith("FINE:") for p in detector.validate_result(res, card, source_sha256="s", page=1))


# ----------------------------------------------------------------------------------------------------------------- with the torch component
@needs_torch
def test_merge_policies_on_authored_seam_fixtures_and_r1_equals_the_frozen_rule():
    r = subprocess.run([TORCH_PY, "-B", "-I", str(ROOT / "tests" / "tr1_data" / "merge_checks.py")], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "OK" in r.stdout, r.stdout + r.stderr


@needs_torch
def test_real_detector_with_edge_safe_coarse_and_fine_stage_proposes_only(monkeypatch):
    monkeypatch.setenv("PIDLAB_SYMBOL_FRCNN_TR1", "on")
    monkeypatch.setenv("PIDLAB_TR1_PYTHON", TORCH_PY)
    if detector.locate_model() is None or detector.locate_fine() is None:
        pytest.skip("models/ does not hold the E5 and fine-class cards with their weights")
    base = detector.detect(FIX / "synthetic_pid_vector.pdf", 1, timeout_s=300)
    assert base["status"] == "DONE"
    assert all("edge_partial" not in d and "fine" not in d for d in base["detections"])
    monkeypatch.setenv("PIDLAB_TILE_MERGE_R3", "edge_safe+coarse")
    monkeypatch.setenv("PIDLAB_FINE_CLASS_R3", "on")
    res = detector.detect(FIX / "synthetic_pid_vector.pdf", 1, timeout_s=300)
    assert res["status"] == "DONE", res
    assert res["detections"] and all(d["review_state"] == "PROPOSED" and isinstance(d["edge_partial"], bool) for d in res["detections"])
    assert all(d["fine"]["names"] == "unverified" and d["fine"]["status"] in ("PROPOSED", "ABSTAINED") for d in res["detections"])
    assert res["diagnostics"]["merge_policy"] == "edge_safe+coarse" and res["diagnostics"]["fine_class"] is True
    base_ids = {d["id"] for d in base["detections"]}
    assert base_ids <= {d["id"] for d in res["detections"]} or len(base_ids - {d["id"] for d in res["detections"]}) <= 1   # edge-safe only adds or stitches
