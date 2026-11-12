"""Reviewed-corpus provenance: candidates, blind review records, adjudication, split/duplicate checks, exports.

Rules enforced here (not left to convention):
* A candidate carries LOCATIONS only (source hash, page, bbox in the media frame, crop hash). It never carries a model reading.
* Transcriptions come only from named human reviewers; reviewer names that look like software are refused, and a second reviewer for
  validation items must be a different person who never receives the first answers.
* Validation items are `ADJUDICATED` only when two independent transcriptions agree strictly, or a named adjudicator recorded the final
  text against the source pixels. Anything else stays `NEEDS_ADJUDICATION` and is excluded from every export.
* Whole drawing families sit in one split; duplicate source/crop hashes, near-duplicate crops (dHash) and overlapping boxes on one
  drawing may not cross splits, and overlapping boxes inside a split must be resolved explicitly (`duplicate_of`).
* No draft/AI-made reference is ever promoted to VERIFIED here; there is no function that does it.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

CANDIDATES_SCHEMA = "pid-corpus-candidates-v1"
REVIEW_SCHEMA = "pid-corpus-review-v1"
CATEGORIES = ("LINE_LABEL", "BUBBLE_CODE", "BUBBLE_NUMBER", "VERTICAL", "TITLE_BLOCK", "EASY_CONTROL", "NON_TEXT_CANDIDATE", "UNREADABLE_CANDIDATE")
SPLITS = ("TRAIN", "VALIDATION")
_SOFTWARE_NAME = re.compile(r"\b(claude|gpt|chatgpt|openai|anthropic|assistant|copilot|gemini|llm|bot|ocr|rapidocr|easyocr|trocr|model|auto|script|ai)\b", re.I)
NEAR_DUPLICATE_HAMMING = 4
OVERLAP_IOU = .30


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def reviewer_name_ok(name):
    """A named person. Refuses blank names and names that identify software (no impersonating a reviewer)."""
    if not isinstance(name, str) or len(name.strip()) < 3:
        return False
    return not _SOFTWARE_NAME.search(name)


def dhash(image, size=8):
    """64-bit difference hash of a PIL image (near-duplicate crop detection)."""
    from PIL import Image
    g = image.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    px = list(g.tobytes())
    bits = 0
    for y in range(size):
        for x in range(size):
            bits = (bits << 1) | (px[y * (size + 1) + x] > px[y * (size + 1) + x + 1])
    return bits


def hamming(a, b):
    return bin(a ^ b).count("1")


def _iou(a, b):
    ix = max(0.0, min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]))
    iy = max(0.0, min(a["y1"], b["y1"]) - max(a["y0"], b["y0"]))
    inter = ix * iy
    union = (a["x1"] - a["x0"]) * (a["y1"] - a["y0"]) + (b["x1"] - b["x0"]) * (b["y1"] - b["y0"]) - inter
    return inter / union if union > 0 else 0.0


def validate_candidates(doc, *, root=None):
    """Return a list of problems (empty = consistent). `root` resolves relative crop paths and enables crop-hash checks."""
    problems = []
    if doc.get("schema") != CANDIDATES_SCHEMA:
        return ["unknown candidates schema"]
    items = doc.get("items", [])
    ids, family_split, source_split, crop_split = set(), {}, {}, {}
    by_page = {}
    for it in items:
        i = it.get("id")
        if i in ids:
            problems.append(f"{i}: duplicate id")
        ids.add(i)
        if it.get("split") not in SPLITS:
            problems.append(f"{i}: split must be TRAIN or VALIDATION (RESERVED_FINAL is never allowed)")
        if it.get("category") not in CATEGORIES:
            problems.append(f"{i}: unknown category")
        if any(k in it for k in ("text", "reading", "draft_text", "ocr_text", "prediction")):
            problems.append(f"{i}: a candidate must not carry any reading")
        for mapping, key, label in ((family_split, it.get("family_id"), "family"), (source_split, it.get("source_sha256"), "source"), (crop_split, it.get("crop_sha256"), "crop")):
            if key in mapping and mapping[key] != it.get("split"):
                problems.append(f"{i}: {label} {str(key)[:12]} appears in two splits (leakage)")
            mapping.setdefault(key, it.get("split"))
        b = it.get("bbox", {})
        if not all(isinstance(b.get(k), (int, float)) for k in ("x0", "y0", "x1", "y1")) or not (0 <= b["x0"] < b["x1"] <= 1 and 0 <= b["y0"] < b["y1"] <= 1):
            problems.append(f"{i}: bbox must be normalised x0<x1,y0<y1")
        by_page.setdefault((it.get("source_sha256"), it.get("page")), []).append(it)
        if root is not None and it.get("crop_path"):
            p = Path(root) / it["crop_path"]
            if not p.is_file():
                problems.append(f"{i}: crop file missing")
            elif sha256_file(p) != it.get("crop_sha256"):
                problems.append(f"{i}: crop bytes differ from crop_sha256")
    for group in by_page.values():
        for n, a in enumerate(group):
            for b in group[n + 1:]:
                if a["bbox"] and b["bbox"] and _iou(a["bbox"], b["bbox"]) >= OVERLAP_IOU:
                    if a["split"] != b["split"]:
                        problems.append(f"{a['id']}/{b['id']}: overlapping boxes on one drawing cross splits")
                    elif not (a.get("duplicate_of") == b["id"] or b.get("duplicate_of") == a["id"]):
                        problems.append(f"{a['id']}/{b['id']}: overlapping boxes on one drawing; mark one duplicate_of the other")
    hashed = [(it["id"], it["split"], it["dhash"]) for it in items if isinstance(it.get("dhash"), int)]
    for n, (ia, sa, ha) in enumerate(hashed):
        for ib, sb, hb in hashed[n + 1:]:
            if sa != sb and hamming(ha, hb) <= NEAR_DUPLICATE_HAMMING:
                problems.append(f"{ia}/{ib}: near-duplicate crops (dHash) cross splits")
    return problems


def new_review(reviewer, role, items):
    """Skeleton the review app fills. `items`: {id: {state, text, note}}."""
    if role not in ("FIRST", "SECOND", "ADJUDICATOR"):
        raise ValueError("role must be FIRST, SECOND or ADJUDICATOR")
    if not reviewer_name_ok(reviewer):
        raise ValueError("a named human reviewer is required")
    return dict(schema=REVIEW_SCHEMA, reviewer=reviewer.strip(), role=role, created_utc=datetime.now(timezone.utc).isoformat(), items=items)


def validate_review(review, candidates_doc):
    problems = []
    if review.get("schema") != REVIEW_SCHEMA:
        problems.append("unknown review schema")
    if not reviewer_name_ok(review.get("reviewer", "")):
        problems.append("reviewer is not a named human")
    ids = {i["id"] for i in candidates_doc["items"]}
    for k, v in review.get("items", {}).items():
        if k not in ids:
            problems.append(f"{k}: not a candidate")
        if v.get("state") not in ("READABLE", "UNREADABLE", "NOT_TEXT"):
            problems.append(f"{k}: invalid state")
        if v.get("state") == "READABLE" and not (isinstance(v.get("text"), str) and v["text"] and len(v["text"]) <= 160):
            problems.append(f"{k}: READABLE needs the exact text")
        if v.get("orientation") not in (None, "UPRIGHT", "ROTATE_CW", "ROTATE_CCW"):
            problems.append(f"{k}: invalid orientation")
        cand = next((i for i in candidates_doc["items"] if i["id"] == k), None)
        if cand and cand.get("is_vertical") and v.get("state") == "READABLE" and v.get("orientation") is None:
            problems.append(f"{k}: a vertical item needs the reading direction (orientation)")
    return problems


def adjudicate(candidates_doc, first, second=None, final=None):
    """Combine reviews into per-item decisions. Returns {id: record}. Never invents or edits a transcription."""
    for review, role in ((first, "FIRST"), (second, "SECOND"), (final, "ADJUDICATOR")):
        if review is not None:
            if review.get("role") != role:
                raise ValueError(f"expected a {role} review")
            bad = validate_review(review, candidates_doc)
            if bad:
                raise ValueError("; ".join(bad[:5]))
    if second is not None and second["reviewer"].strip().lower() == first["reviewer"].strip().lower():
        raise ValueError("the second reviewer must be a different person")
    out = {}
    for it in candidates_doc["items"]:
        i = it["id"]
        a = first["items"].get(i)
        b = second["items"].get(i) if second is not None else None
        f = final["items"].get(i) if final is not None else None
        rec = dict(id=i, split=it["split"], family_id=it["family_id"], category=it["category"], first=a, second=b, final=f)
        agree_o = lambda x, y: x.get("orientation") == y.get("orientation")
        if a is None:
            rec["adjudication"] = "NOT_REVIEWED"
        elif it["split"] == "TRAIN":
            rec["adjudication"] = "SINGLE_REVIEWER"
            rec.update(state=a["state"], text=a.get("text"), orientation=a.get("orientation"))
        else:
            if b is None:
                rec["adjudication"] = "AWAITING_SECOND_REVIEWER"
            elif a["state"] == b["state"] and (a["state"] != "READABLE" or (a["text"] == b["text"] and agree_o(a, b))):
                rec["adjudication"] = "ADJUDICATED"
                rec.update(state=a["state"], text=a.get("text"), orientation=a.get("orientation"), basis="TWO_INDEPENDENT_REVIEWERS_AGREE_STRICTLY")
            elif f is not None:
                rec["adjudication"] = "ADJUDICATED"
                rec.update(state=f["state"], text=f.get("text"), orientation=f.get("orientation"), basis="ADJUDICATOR_AGAINST_SOURCE_PIXELS:" + final["reviewer"])
            else:
                rec["adjudication"] = "NEEDS_ADJUDICATION"
        out[i] = rec
    return out


def export_reference_v2(candidates_doc, decisions, *, split="VALIDATION"):
    """pid-reference-v2 for the strict scorer: only ADJUDICATED validation items (or single-reviewer TRAIN items marked as such)."""
    items = []
    for it in candidates_doc["items"]:
        d = decisions.get(it["id"])
        if not d or it["split"] != split or d["adjudication"] not in ("ADJUDICATED", "SINGLE_REVIEWER") or d.get("state") is None:
            continue
        row = dict(id=it["id"], category=it["category"], state=d["state"], bbox=it["bbox"], adjudication="ADJUDICATED" if d["adjudication"] == "ADJUDICATED" else "SINGLE_REVIEWER",
                   source_sha256=it["source_sha256"], page=it["page"], family_id=it["family_id"])
        if d["state"] == "READABLE":
            row["text"] = d["text"]
        items.append(row)
    status = "ADJUDICATED" if items and all(r["adjudication"] == "ADJUDICATED" for r in items) else "PARTIAL_NOT_ADJUDICATED"
    return dict(schema="pid-reference-v2", status=status, split=split, items=items, coordinate_frame="MEDIA_NORMALIZED_TOP_LEFT")


def export_longterm_dataset(candidates_doc, decisions, root, out_dir, *, sources):
    """pid-longterm-crops-v1 manifest (TRAIN and VALIDATION) from reviewed READABLE items. `sources`: {source_sha256: pdf path}."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=False)
    rows = []
    for it in candidates_doc["items"]:
        d = decisions.get(it["id"])
        if not d or d.get("state") != "READABLE" or d["adjudication"] not in ("ADJUDICATED", "SINGLE_REVIEWER"):
            continue
        if it["split"] == "VALIDATION" and d["adjudication"] != "ADJUDICATED":
            continue
        reviewers = [r for r in (d.get("first"), d.get("second")) if r]
        crop = Path(root) / it["crop_path"]
        target = out_dir / (it["id"] + ".png")
        turn = {"ROTATE_CW": -90, "ROTATE_CCW": 90}.get(d.get("orientation"))
        if turn is not None:                      # the reviewer-stated reading direction decides the rotation; nothing is guessed
            from PIL import Image
            with Image.open(crop) as im:
                im.rotate(turn, expand=True).save(target)
        else:
            target.write_bytes(crop.read_bytes())
        rows.append(dict(id=it["id"], split=it["split"], family_id=it["family_id"], source_sha256=it["source_sha256"], origin="HUMAN_SOURCE_PIXELS",
                         review_status="VERIFIED_DEVELOPMENT", reviewer=d.get("basis") or "single-reviewer", text=d["text"], image_path=target.name,
                         image_sha256=sha256_file(target), source_path=str(sources[it["source_sha256"]]), page=it["page"], bbox=it["bbox"],
                         coordinate_frame="MEDIA_NORMALIZED_TOP_LEFT", category=it["category"], control=bool(it.get("control")), adjudication=d["adjudication"], orientation_applied=d.get("orientation"),
                         reviewers_recorded=len(reviewers)))
    (out_dir / "dataset.json").write_text(json.dumps(dict(schema="pid-longterm-crops-v1", items=rows), indent=1), encoding="utf8")
    return out_dir / "dataset.json", len(rows)


def readiness(candidates_doc, decisions):
    """What is still needed before training can start (the human-only blockers, counted)."""
    split = {s: dict(items=0, reviewed=0, adjudicated=0, needs_adjudication=0, awaiting_second=0, readable=0) for s in SPLITS}
    for it in candidates_doc["items"]:
        d = decisions.get(it["id"]) if decisions else None
        s = split[it["split"]]
        s["items"] += 1
        if d and d["adjudication"] != "NOT_REVIEWED":
            s["reviewed"] += 1
        if d and d["adjudication"] in ("ADJUDICATED", "SINGLE_REVIEWER"):
            s["adjudicated"] += 1
            s["readable"] += d.get("state") == "READABLE"
        if d and d["adjudication"] == "NEEDS_ADJUDICATION":
            s["needs_adjudication"] += 1
        if d and d["adjudication"] == "AWAITING_SECOND_REVIEWER":
            s["awaiting_second"] += 1
    ok = split["TRAIN"]["readable"] >= 40 and split["VALIDATION"]["readable"] >= 20 and not split["VALIDATION"]["needs_adjudication"] and not split["VALIDATION"]["awaiting_second"]
    return dict(ready=ok, per_split=split, minimum="TRAIN >= 40 readable single-reviewed items and VALIDATION >= 20 readable adjudicated items with none pending")
