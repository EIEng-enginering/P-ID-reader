"""TR1: engineer decisions on learned-detector proposals are recorded in a hash-chained queue and can become an immutable, hashed training batch."""
from __future__ import annotations

import hashlib
import json

import pytest

from pid_reader.tr1 import batch_export, batches, flags, mapping, review, store
from pid_reader.tr1.corrections import CorrectionQueue, QueueError

DOC = "a" * 64


def det(i: str, coarse="valve", score=0.9, status="LEADING", box=(0.1, 0.1, 0.2, 0.2)):
    d = {"id": i, "page": 1, "bbox": dict(zip(("x0", "y0", "x1", "y1"), box)), "catalogue_class": coarse, "raw_score": score,
         "score_kind": "UNCALIBRATED_FRCNN_SOFTMAX", "confidence_status": status, "review_state": "PROPOSED",
         "evidence": {"producer": "tr1-frcnn-e5", "weights_sha256": "b" * 64, "truth_class": "MODEL_PROPOSAL"}}
    return mapping.enrich(d)


def record(*dets, name="S100_test.pdf"):
    return {"source_sha256": DOC, "page": 1, "source_name": name, "detections": list(dets)}


@pytest.fixture()
def on(monkeypatch):
    for n in ("PIDLAB_CORRECTION_QUEUE_TR1", "PIDLAB_SYMBOL_CATALOGUE_TR1", "PIDLAB_TRAINING_BATCH_TR1"):
        monkeypatch.setenv(n, "on")


def test_review_is_unavailable_while_switched_off():
    ok, why = review.available()
    assert not ok and "PIDLAB_CORRECTION_QUEUE_TR1" in why
    with pytest.raises(review.ReviewUnavailable):
        review.confirm(record(det("frc-1")), det("frc-1"), "Alice")
    assert not store.home().exists()


def test_confirm_reject_edit_unresolved_are_recorded_and_the_chain_verifies(on):
    a, b, c, d = det("frc-1"), det("frc-2", "instrumentation"), det("frc-3", "general"), det("frc-4", "valve")
    rec = record(a, b, c, d)
    r1 = review.confirm(rec, a, "Alice")
    assert r1["status"] == "ACCEPTED_FINAL"
    assert review.reject(rec, b, "Alice", "title block")["status"] == "ACCEPTED_FINAL"
    assert review.edit_class(rec, c, "Alice", "CLS.EQUIPMENT.TANK")["status"] == "ACCEPTED_FINAL"
    assert review.mark_unresolved(rec, d, "Alice")["status"] == "AWAITING_SECOND_REVIEW"       # insufficient evidence always needs a second person
    states = review.review_states(rec)
    assert [states[x]["state"] for x in ("frc-1", "frc-2", "frc-3", "frc-4")] == ["CONFIRMED", "REJECTED", "EDITED", "AWAITING_SECOND_REVIEW"]
    q = review._queue()
    assert q.verify() == []
    kinds = [e["action"] for e in q.events()]
    assert kinds.count("IMPORT_PROPOSAL") == 4 and kinds.count("SUBMIT") == 4
    assert not q.active_model_changed()


def test_a_withheld_proposal_needs_an_independent_second_reviewer(on):
    w = det("frc-9", "general", score=0.4, status="WEAK_CLASS_WITHHELD")
    rec = record(w)
    res = review.confirm(rec, w, "Alice", class_id="CLS.EQUIPMENT.VESSEL")
    assert res["status"] == "AWAITING_SECOND_REVIEW" and "AMBIGUOUS_PROPOSAL" in res["second_review_required"]
    with pytest.raises(QueueError, match="INDEPENDENT"):
        review.second_review(res["correction_id"], "Alice", True)
    review.second_review(res["correction_id"], "Bob", True)
    assert review.review_states(rec)["frc-9"]["state"] == "CONFIRMED"


def test_bad_input_is_refused(on):
    a = det("frc-1")
    rec = record(a)
    with pytest.raises(QueueError, match="REVIEWER_REQUIRED"):
        review.confirm(rec, a, "  ")
    with pytest.raises(QueueError, match="CLASS_NOT_IN_CATALOGUE"):
        review.edit_class(rec, a, "Alice", "CLS.VALVE.MADE_UP")
    arrow = det("frc-5", "arrow")
    with pytest.raises(QueueError, match="CLASS_REQUIRED"):
        review.confirm(record(arrow), arrow, "Alice")                    # no suggested class: the engineer must choose
    assert review.confirm(record(arrow), arrow, "Alice", class_id="CLS.ANNOTATION.FLOW_ARROW")["status"] == "ACCEPTED_FINAL"


def test_editing_the_queue_file_is_detected_and_blocks_further_writes(on):
    a = det("frc-1")
    rec = record(a)
    review.confirm(rec, a, "Alice")
    p = store.queue_path()
    p.write_text(p.read_text(encoding="utf-8").replace("Alice", "Mallory"), encoding="utf-8")
    assert review._queue().verify()
    with pytest.raises(QueueError, match="CHAIN_INVALID"):
        review.reject(rec, det("frc-2"), "Alice")


# ---------------------------------------------------------------------------------------------------------------- training batches
def _seed_reviews():
    a, b, c = det("frc-1"), det("frc-2", "instrumentation"), det("frc-3", "valve")
    rec = record(a, b, c)
    review.confirm(rec, a, "Alice")
    review.reject(rec, b, "Alice")
    review.edit_box(rec, c, "Alice", {"x0": 0.3, "y0": 0.3, "x1": 0.35, "y1": 0.34})
    return rec


def test_batch_needs_an_explicit_approval_and_never_invents_one(on):
    _seed_reviews()
    with pytest.raises(batch_export.BatchUnavailable, match="approval"):
        batch_export.build("B1", project_family="plantA", approval_id="", approved_by="Owner")
    with pytest.raises(batch_export.BatchUnavailable, match="approval"):
        batch_export.build("B1", project_family="plantA", approval_id="AP-1", approved_by=" ")
    assert not (store.batches_dir() / "B1").exists()


def test_batch_is_off_unless_switched_on(monkeypatch):
    monkeypatch.setenv("PIDLAB_CORRECTION_QUEUE_TR1", "on")
    monkeypatch.setenv("PIDLAB_SYMBOL_CATALOGUE_TR1", "on")
    with pytest.raises(batch_export.BatchUnavailable, match="switched off"):
        batch_export.build("B1", project_family="plantA", approval_id="AP-1", approved_by="Owner")


def test_final_reviews_become_an_immutable_verified_batch(on):
    _seed_reviews()
    names = {DOC: "PlantA_unit1.pdf"}
    m = batch_export.build("B1", project_family="plantA", approval_id="AP-1", approved_by="Owner", source_names=names, fractions={"train": 1.0})
    assert m["item_count"] == 1 and m["rejected_count"] == 0 and m["splits"]["train"]
    out = store.batches_dir() / "B1"
    assert batches.verify_batch(str(out)) == []
    item = json.loads((out / "items.jsonl").read_text(encoding="utf-8").splitlines()[0])
    classes = sorted(lab["class_id"] for lab in item["labels"])
    assert classes == ["CLS.VALVE.UNKNOWN", "CLS.VALVE.UNKNOWN"]                    # confirmed + moved box (suggested family-level class)
    assert len(item["negatives"]) == 1 and item["rights"]["approved_by"] == "Owner" and item["truth_class"] == "HUMAN_CORRECTED_SINGLE"
    assert (out / "BATCH_MANIFEST.json").read_text(encoding="utf-8") and m["batch_sha256"]
    with pytest.raises(batches.BatchError, match="BATCH_DIR_EXISTS"):
        batch_export.build("B1", project_family="plantA", approval_id="AP-1", approved_by="Owner", source_names=names)
    # tampering is detected
    items = out / "items.jsonl"
    items.write_text(items.read_text(encoding="utf-8").replace("CLS.VALVE.UNKNOWN", "CLS.VALVE.GATE", 1), encoding="utf-8")
    assert "ITEMS_TAMPERED" in batches.verify_batch(str(out))


def test_known_development_sheets_never_enter_the_training_split(on):
    _seed_reviews()
    m = batch_export.build("B2", project_family="plantA", approval_id="AP-1", approved_by="Owner", source_names={DOC: "S025_pump_area.pdf"}, fractions={"train": 1.0})
    assert not m["splits"].get("train") and m["splits"].get("development")


def test_waiting_reviews_are_not_training_data(on):
    w = det("frc-9", "general", score=0.4, status="WEAK_CLASS_WITHHELD")
    review.confirm(record(w), w, "Alice", class_id="CLS.EQUIPMENT.VESSEL")
    with pytest.raises(batch_export.BatchUnavailable, match="no final reviews"):
        batch_export.build("B3", project_family="plantA", approval_id="AP-1", approved_by="Owner")
