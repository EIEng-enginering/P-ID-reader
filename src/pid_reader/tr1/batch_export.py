"""Turn the engineer's FINAL reviews into a versioned, immutable, hashed training batch (switch PIDLAB_TRAINING_BATCH_TR1).

Only corrections that reached ACCEPTED_FINAL in the queue are used. A batch needs an explicit usage approval (approval id + the named person who
approved training on these drawings); this code never invents one. Items from the known development sheets (S023, S024, S025, S056, S080, S081)
are kept in the ``development`` split and never trained on. Families are split as a whole (a drawing family can never sit in two splits).
The batch builder is the Grok ``batches.build_batch``; this module only converts reviews into its item format.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import batches, flags, review, store
from .corrections import _sha

SWITCH = "PIDLAB_TRAINING_BATCH_TR1"
DEFAULT_FRACTIONS = {"train": 0.8, "validation": 0.2}
DEFAULT_SEED = "tr1-20261110"
_POSITIVE = ("CONFIRM", "CLASS", "ADD_MISSED")


class BatchUnavailable(RuntimeError):
    pass


def _label_for(corr: dict, prop: dict) -> dict | None:
    kind = corr["kind"]
    if kind in _POSITIVE:
        cid = corr["corrected"]["class_id"]
    elif kind == "BBOX":
        cid = prop["proposal"].get("suggested_class_id")
        if not cid:
            return None
    else:
        return None
    b = corr["evidence"]["bbox"]
    return {"class_id": cid, "bbox": b, "correction_id": corr["id"], "detector_class": prop["proposal"].get("coarse_class")}


def items_from_queue(queue, *, project_family: str, approval_id: str, approved_by: str, source_names: dict[str, str] | None = None) -> tuple[list[dict], dict]:
    """(items, skipped counts). One item per (document, page); labels = confirmed / corrected boxes, negatives = rejected false positives."""
    st = queue.state()
    groups: dict[tuple, dict] = {}
    skipped = {"not_final": 0, "unresolved": 0, "no_class": 0}
    for corr in st["corrections"].values():
        if corr["status"] != "ACCEPTED_FINAL":
            skipped["not_final"] += 1
            continue
        prop = st["proposals"][corr["proposal_id"]]
        key = (prop["document_sha256"], prop["page"])
        g = groups.setdefault(key, {"labels": [], "negatives": [], "reviewers": set(), "double": True})
        g["reviewers"].update(x for x in (corr["submitted_by"], corr.get("second_reviewer"), corr.get("adjudicator")) if x)
        g["double"] &= bool(corr.get("second_reviewer"))
        if corr["kind"] == "REJECT_FALSE_POSITIVE":
            g["negatives"].append({"bbox": corr["evidence"]["bbox"], "correction_id": corr["id"], "detector_class": prop["proposal"].get("coarse_class")})
            continue
        if corr["kind"] == "MARK_UNRESOLVED":
            skipped["unresolved"] += 1
            continue
        lab = _label_for(corr, prop)
        if lab is None:
            skipped["no_class"] += 1
            continue
        g["labels"].append(lab)
    items = []
    for (doc, page), g in sorted(groups.items()):
        if not g["labels"] and not g["negatives"]:
            continue
        name = (source_names or {}).get(doc, "")
        stem = Path(name).stem if name else doc[:12]
        dev = bool(batches.KNOWN_DEV.match(stem))
        items.append({"item_id": f"{doc[:16]}_p{page}", "source_id": stem, "source_kind": "PDF", "known_surveyed": False,
                      "project_family": project_family + ("-development" if dev else ""), "requested_split": "development" if dev else None,
                      "rights": {"status": "TRAINING_AUTHORISED", "approval_id": approval_id, "approved_by": approved_by},
                      "truth_class": "HUMAN_CORRECTED_DOUBLE" if g["double"] else "HUMAN_CORRECTED_SINGLE",
                      "content_sha256": _sha([doc, page]), "document_sha256": doc, "page": page,
                      "labels": sorted(g["labels"], key=lambda x: x["correction_id"]), "negatives": sorted(g["negatives"], key=lambda x: x["correction_id"]),
                      "reviewers": sorted(g["reviewers"])})
    return items, skipped


def build(version: str, *, project_family: str, approval_id: str, approved_by: str, source_names: dict[str, str] | None = None,
          fractions: dict | None = None, seed: str = DEFAULT_SEED, parent_manifest: dict | None = None, notes: str = "") -> dict:
    """Build batch ``version`` from the queue. Raises ``BatchUnavailable`` (switch off / no approval) or ``batches.BatchError`` (a batch rule failed)."""
    if not flags.enabled(SWITCH):
        raise BatchUnavailable(f"{SWITCH} is switched off")
    ok, why = review.available()
    if not ok:
        raise BatchUnavailable(why)
    if not (approval_id or "").strip() or not (approved_by or "").strip():
        raise BatchUnavailable("A usage approval id and the name of the person who approved training on these drawings are required; none is assumed.")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", version or ""):
        raise BatchUnavailable("The batch version may use letters, digits, '.', '_' and '-' only.")
    if not (project_family or "").strip():
        raise BatchUnavailable("A project family is required: it keeps every revision of a project in one split.")
    q = review._queue()
    bad = q.verify()
    if bad:
        raise BatchUnavailable("The correction queue failed its integrity check: " + ", ".join(bad[:3]))
    items, skipped = items_from_queue(q, project_family=project_family.strip(), approval_id=approval_id.strip(), approved_by=approved_by.strip(), source_names=source_names)
    if not items:
        raise BatchUnavailable("There are no final reviews to build a batch from yet (second reviews may still be outstanding).")
    out = store.batches_dir() / version
    manifest = batches.build_batch(items, catalogue=review.catalogue(), out_dir=str(out), lock_path=str(store.family_lock_path()), version=version,
                                   fractions=fractions or DEFAULT_FRACTIONS, seed=seed, parent_manifest=parent_manifest, notes=notes)
    manifest = dict(manifest)
    manifest["skipped_reviews"] = skipped
    manifest["path"] = str(out)
    return manifest
