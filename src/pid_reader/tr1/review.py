"""Engineer review of learned-detector proposals, recorded in the TR1 correction queue (switches PIDLAB_CORRECTION_QUEUE_TR1 + PIDLAB_SYMBOL_CATALOGUE_TR1).

Every action is an appended, hash-chained event (``corrections.CorrectionQueue``); nothing edits a proposal, a model or an accepted engineering
reading. Confirm / reject / edit decisions made here are TRAINING DATA for future runs only. They do NOT turn a proposal into a verified plant
fact, and confirming a symbol says nothing about any connection (proximity is not connectivity; edge changes need path evidence and a second reviewer).

States shown to the user, derived from the queue: UNREVIEWED, CONFIRMED, EDITED, REJECTED, UNRESOLVED, AWAITING_SECOND_REVIEW, DISPUTED, WITHDRAWN.
A proposal the detector itself withheld (below its frozen threshold) always needs an independent second reviewer before it counts.
"""
from __future__ import annotations

from pathlib import Path

from . import catalogue as cat_mod
from . import flags, store
from .corrections import CorrectionQueue, QueueError, _sha

NEEDS = ("PIDLAB_CORRECTION_QUEUE_TR1", "PIDLAB_SYMBOL_CATALOGUE_TR1")
PRODUCER_FALLBACK = "tr1-frcnn"


class ReviewUnavailable(RuntimeError):
    pass


def available(explicit: dict | None = None) -> tuple[bool, str]:
    """(usable, reason). Both the queue and the catalogue switches must be on."""
    off = [n for n in NEEDS if not flags.enabled(n, (explicit or {}).get(n))]
    if off:
        return False, "Switched off: " + ", ".join(off)
    return True, ""


def catalogue() -> dict:
    cat = cat_mod.catalogue("1.0.0")
    problems = cat_mod.validate(cat)
    if problems:
        raise ReviewUnavailable("The bundled symbol catalogue failed its own validation: " + ", ".join(problems[:3]))
    return cat


def _queue(path: Path | None = None) -> CorrectionQueue:
    ok, why = available()
    if not ok:
        raise ReviewUnavailable(why)
    target = Path(path or store.queue_path())
    target.parent.mkdir(parents=True, exist_ok=True)
    return CorrectionQueue(str(target), catalogue())


def proposal_id(detection: dict) -> str:
    """The id the queue gives this proposal (content-derived, so importing it twice is harmless)."""
    return "prop-" + _sha(detection)[:20]


def _box(b: dict) -> list[float]:
    return [float(b["x0"]), float(b["y0"]), float(b["x1"]), float(b["y1"])]


def import_record(record: dict, queue: CorrectionQueue | None = None) -> dict[str, str]:
    """Register every detection of a sidecar record as a PROPOSAL in the queue. Returns {detection id: proposal id}."""
    q = queue or _queue()
    out = {}
    for d in record["detections"]:
        out[d["id"]] = q.import_proposal(d, document_sha256=record["source_sha256"], page=record["page"], producer=d.get("evidence", {}).get("producer", PRODUCER_FALLBACK),
                                         actor="tr1-detector")
    return out


def _submit(record: dict, det: dict, kind: str, corrected: dict, reason: str, reviewer: str, note: str, bbox: dict | None = None, queue=None) -> dict:
    q = queue or _queue()
    if not reviewer or not reviewer.strip():
        raise QueueError("REVIEWER_REQUIRED")
    pid = import_record({"detections": [det], "source_sha256": record["source_sha256"], "page": record["page"]}, q)[det["id"]]
    cid = q.submit(pid, kind=kind, corrected=corrected, reason=reason, reviewer=reviewer.strip(), note=note,
                   evidence={"page": record["page"], "bbox": _box(bbox or det["bbox"])})
    c = q.state()["corrections"][cid]
    return {"correction_id": cid, "status": c["status"], "second_review_required": c["second_review_required"]}


def confirm(record: dict, det: dict, reviewer: str, class_id: str | None = None, note: str = "", queue=None) -> dict:
    """The engineer agrees the symbol is where and what it is drawn as. ``class_id`` defaults to the suggested family-level 'type unknown' class."""
    cid = class_id or det.get("suggested_class_id")
    if not cid:
        raise QueueError("CLASS_REQUIRED (the detector class has no catalogue suggestion; choose one)")
    return _submit(record, det, "CONFIRM", {"class_id": cid}, "CONFIRMED_AS_PROPOSED", reviewer, note, queue=queue)


def reject(record: dict, det: dict, reviewer: str, note: str = "", queue=None) -> dict:
    return _submit(record, det, "REJECT_FALSE_POSITIVE", {"rejected": True}, "FALSE_POSITIVE", reviewer, note, queue=queue)


def edit_class(record: dict, det: dict, reviewer: str, class_id: str, *, lookalike: bool = False, note: str = "", queue=None) -> dict:
    return _submit(record, det, "CLASS", {"class_id": class_id}, "LOOKALIKE_CONFUSION" if lookalike else "WRONG_CLASS", reviewer, note, queue=queue)


def edit_box(record: dict, det: dict, reviewer: str, new_bbox: dict, note: str = "", queue=None) -> dict:
    return _submit(record, det, "BBOX", {"bbox": _box(new_bbox)}, "WRONG_EXTENT", reviewer, note, bbox=new_bbox, queue=queue)


def mark_unresolved(record: dict, det: dict, reviewer: str, note: str = "", queue=None) -> dict:
    return _submit(record, det, "MARK_UNRESOLVED", {"unresolved": True}, "INSUFFICIENT_EVIDENCE", reviewer, note, queue=queue)


def second_review(correction_id: str, reviewer: str, agree: bool, note: str = "", queue=None) -> None:
    (queue or _queue()).second_review(correction_id, reviewer=reviewer, agree=agree, note=note)


def awaiting_second_review(queue=None) -> list[dict]:
    st = (queue or _queue()).state()
    return [c for c in st["corrections"].values() if c["status"] == "AWAITING_SECOND_REVIEW"]


_KIND_STATE = {"CONFIRM": "CONFIRMED", "CLASS": "EDITED", "BBOX": "EDITED", "REJECT_FALSE_POSITIVE": "REJECTED", "MARK_UNRESOLVED": "UNRESOLVED"}


def review_states(record: dict, queue=None) -> dict[str, dict]:
    """{detection id: {"state", "correction_id", "kind", "by"}} from the queue; detections nobody has looked at are UNREVIEWED."""
    q = queue or _queue()
    st = q.state()
    out = {}
    for d in record["detections"]:
        item = {"state": "UNREVIEWED", "correction_id": None, "kind": None, "by": None}
        prop = st["proposals"].get(proposal_id(d))
        if prop and prop["corrections"]:
            c = st["corrections"][prop["corrections"][-1]]
            state = {"AWAITING_SECOND_REVIEW": "AWAITING_SECOND_REVIEW", "DISPUTED": "DISPUTED", "WITHDRAWN": "WITHDRAWN",
                     "REJECTED_FINAL": "DISPUTED"}.get(c["status"]) or _KIND_STATE.get(c["kind"], c["status"])
            item = {"state": state, "correction_id": c["id"], "kind": c["kind"], "by": c["submitted_by"]}
        out[d["id"]] = item
    return out
