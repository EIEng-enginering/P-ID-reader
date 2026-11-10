"""TR1 immutable versioned training batches (flag PIDLAB_TRAINING_BATCH_TR1, default OFF). Stdlib only.

build_batch() admits an item only if ALL hold: catalogued, non-deprecated labels; split allowed by rights (train needs
TRAINING_AUTHORISED + approval_id + approved_by; validation/blind need TRAINING_ or EVALUATION_AUTHORISED); not a
known/surveyed development drawing; not METADATA_ONLY; family obeys the persistent split lock (a family can never move
split or sit in two splits); content not a duplicate (exact sha) and never shared across splits. Old-class replay:
every class present in the parent batch's train split must be present at least `replay_min` times or the build FAILS
(REPLAY_SHORTFALL) - forgetting cannot be introduced silently. Every rejection is logged with a reason; nothing is
deleted. Output directories are immutable (refuse overwrite). Same-author synthetic items are labelled
CONSTRUCTION_TRUTH_SAME_AUTHOR / independent=False and can never be blind_test.
"""
from __future__ import annotations
import hashlib, json, os, re

SCHEMA = "pid-training-batch/1"
SPLITS = ("train", "validation", "test_synthetic", "blind_test", "development")
KNOWN_DEV = re.compile(r"^S(?:023|024|025|056|080|081)(?:[_ .-]|$)", re.I)
TRUTH = ("CONSTRUCTION_TRUTH_SAME_AUTHOR", "HUMAN_CORRECTED_SINGLE", "HUMAN_CORRECTED_DOUBLE", "INDEPENDENT_DOUBLE_ADJUDICATED")


def _canon(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha(o):
    return hashlib.sha256(_canon(o).encode()).hexdigest()


class BatchError(RuntimeError):
    pass


def assign_split(family: str, fractions: dict, seed: str) -> str:
    """Deterministic family-level assignment (never per crop/rotation)."""
    u = int(hashlib.sha256(f"{seed}|{family}".encode()).hexdigest()[:12], 16) / float(16 ** 12)
    acc = 0.0
    for s in ("train", "validation", "test_synthetic", "blind_test"):
        acc += fractions.get(s, 0.0)
        if u < acc:
            return s
    return "development"


def _reject(item, reason):
    return {"item_id": item.get("item_id"), "family": item.get("project_family"), "reason": reason}


def check_item(item: dict, split: str, classes: dict) -> list[str]:
    r = []
    rights = item.get("rights") or {}
    if item.get("source_kind") == "METADATA_ONLY": r.append("METADATA_ONLY_NOT_TRAINABLE")
    if item.get("known_surveyed") is not False or KNOWN_DEV.match(str(item.get("source_id", ""))) or KNOWN_DEV.match(str(item.get("item_id", ""))):
        if split != "development": r.append("KNOWN_DEVELOPMENT_ONLY")
    if split == "train":
        if rights.get("status") != "TRAINING_AUTHORISED" or not rights.get("approval_id") or not rights.get("approved_by"): r.append("USAGE_APPROVAL_MISSING")
    if split not in SPLITS: r.append("SPLIT_INVALID")
    if split == "test_synthetic" and item.get("truth_class") != "CONSTRUCTION_TRUTH_SAME_AUTHOR": r.append("TEST_SYNTHETIC_IS_SYNTHETIC_ONLY")
    elif split in ("validation", "test_synthetic", "blind_test"):
        if rights.get("status") not in ("TRAINING_AUTHORISED", "EVALUATION_AUTHORISED") or not rights.get("approval_id"): r.append("USAGE_APPROVAL_MISSING")
    if item.get("truth_class") not in TRUTH: r.append("TRUTH_CLASS_INVALID")
    if split == "blind_test" and item.get("truth_class") != "INDEPENDENT_DOUBLE_ADJUDICATED": r.append("BLIND_REQUIRES_INDEPENDENT_TRUTH")
    if not re.fullmatch(r"[0-9a-f]{64}", str(item.get("content_sha256", ""))): r.append("CONTENT_SHA_INVALID")
    labels = item.get("labels")
    if not isinstance(labels, list): r.append("LABELS_INVALID")
    else:
        for lab in labels:
            c = classes.get(lab.get("class_id"))
            if not c: r.append("LABEL_CLASS_NOT_IN_CATALOGUE"); break
            if c.get("status") == "DEPRECATED": r.append("LABEL_CLASS_DEPRECATED"); break
    return r


def load_lock(path):
    return json.load(open(path)) if path and os.path.exists(path) else {"schema": "pid-family-split-lock/1", "families": {}}


def build_batch(items: list[dict], *, catalogue: dict, out_dir: str, lock_path: str, version: str, fractions: dict, seed: str,
                parent_manifest: dict | None = None, replay_min: int = 1, notes: str = "") -> dict:
    if os.path.exists(out_dir):
        raise BatchError("BATCH_DIR_EXISTS (batches are immutable; use a new version)")
    classes = {c["class_id"]: c for c in catalogue["classes"]}
    lock = load_lock(lock_path)
    fam_split = dict(lock["families"])
    accepted, rejected, seen = [], [], {}
    for item in sorted(items, key=lambda x: str(x.get("item_id"))):
        fam = item.get("project_family")
        if not fam:
            rejected.append(_reject(item, "FAMILY_REQUIRED")); continue
        want = item.get("requested_split")
        split = fam_split.get(fam) or want or assign_split(fam, fractions, seed)
        if fam in fam_split and want and want != fam_split[fam]:
            rejected.append(_reject(item, f"FAMILY_SPLIT_LOCKED_TO_{fam_split[fam]}")); continue
        reasons = check_item(item, split, classes)
        if reasons:
            rejected.append(_reject(item, ";".join(reasons))); continue
        cs = item["content_sha256"]
        if cs in seen:
            rejected.append(_reject(item, "DUPLICATE_CONTENT" if seen[cs] == split else "CROSS_SPLIT_DUPLICATE_LEAK")); continue
        seen[cs] = split
        fam_split.setdefault(fam, split)
        accepted.append(dict(item, split=split, independent=item["truth_class"] == "INDEPENDENT_DOUBLE_ADJUDICATED"))
    counts = {}
    for it in accepted:
        for lab in it["labels"]:
            counts.setdefault(it["split"], {}).setdefault(lab["class_id"], 0)
            counts[it["split"]][lab["class_id"]] += 1
    replay = {}
    if parent_manifest:
        for cid, n in parent_manifest["class_counts"].get("train", {}).items():
            have = counts.get("train", {}).get(cid, 0)
            replay[cid] = {"parent": n, "child": have, "ok": have >= min(replay_min, n)}
        short = sorted(c for c, v in replay.items() if not v["ok"])
        if short:
            raise BatchError("REPLAY_SHORTFALL:" + ",".join(short))
    by_split = {}
    for it in accepted:
        by_split.setdefault(it["split"], []).append(it["item_id"])
    fams = {}
    for f, s in fam_split.items():
        fams.setdefault(s, []).append(f)
    content = {"items": [_sha(i) for i in accepted]}
    manifest = {"schema": SCHEMA, "batch_version": version, "catalogue_version": catalogue["catalogue_version"],
                "catalogue_sha256": _sha(catalogue), "parent_batch_sha256": parent_manifest.get("batch_sha256") if parent_manifest else None,
                "split_seed": seed, "fractions": fractions, "item_count": len(accepted), "rejected_count": len(rejected),
                "splits": {k: sorted(v) for k, v in by_split.items()}, "class_counts": counts, "replay_check": replay,
                "families_by_split": {k: sorted(v) for k, v in fams.items()}, "independent_items": sum(i["independent"] for i in accepted),
                "notes": notes, "content_sha256": _sha(content)}
    manifest["batch_sha256"] = _sha(manifest)
    os.makedirs(out_dir)
    with open(os.path.join(out_dir, "items.jsonl"), "w") as f:
        for it in accepted: f.write(_canon(it) + "\n")
    with open(os.path.join(out_dir, "rejections.jsonl"), "w") as f:
        for r in rejected: f.write(_canon(r) + "\n")
    json.dump(manifest, open(os.path.join(out_dir, "BATCH_MANIFEST.json"), "w"), indent=1, sort_keys=True)
    lock["families"] = fam_split
    tmp = lock_path + ".tmp"; json.dump(lock, open(tmp, "w"), indent=1, sort_keys=True); os.replace(tmp, lock_path)
    return manifest


def verify_batch(out_dir: str) -> list[str]:
    m = json.load(open(os.path.join(out_dir, "BATCH_MANIFEST.json")))
    issues = []
    body = {k: v for k, v in m.items() if k != "batch_sha256"}
    if _sha(body) != m["batch_sha256"]: issues.append("MANIFEST_TAMPERED")
    items = [json.loads(l) for l in open(os.path.join(out_dir, "items.jsonl")) if l.strip()]
    if _sha({"items": [_sha(i) for i in items]}) != m["content_sha256"]: issues.append("ITEMS_TAMPERED")
    fam = {}
    for i in items:
        if fam.setdefault(i["project_family"], i["split"]) != i["split"]: issues.append("FAMILY_IN_TWO_SPLITS:" + i["project_family"])
    return issues
