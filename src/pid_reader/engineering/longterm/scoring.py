"""Strict, omission-aware text scoring. Policy wp07-strict-scoring-v1.

What this module will NOT do: fold case, substitute O/0, I/1, S/5, F/T, D/O or decimal points, strip characters, or repair a string.
What it separates:
  strict   raw string equality                                  (the headline figure)
  format   equality after whitespace removal and Unicode dash glyph unification only (reported separately, never merged into strict)
  edit distance / CER (attempted items, and with omissions counted as fully wrong)
  omissions: MISSED (nothing read there) vs NOT_ATTEMPTED_BUDGET (candidate existed but the budget did not schedule it)
  conflict: the reference string appears among OBSERVED alternatives but the selected reading is wrong (CORRECT_ALTERNATIVE_CONFLICTING)
Spatial policy: a prediction belongs to the reference item with the largest IoU if IoU >= 0.30 or its centre lies inside the item box;
each prediction is matched to at most one item. The reading used for an item is the one the configuration itself marked `selected`
(else the highest raw_score, ties by x then id) - never chosen by looking at the reference text.
Extra detections are counted only inside regions the reference declares exhaustively reviewed.
Fixed-crop recognition, region discovery, symbols, association and connectivity are separate questions and are not mixed here.
A reference that is not ADJUDICATED is DRAFT/diagnostic: its numbers carry that label and are not an accuracy claim.
"""
import re

POLICY = "wp07-strict-scoring-v1"
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—−－"), "-")
IOU_MATCH = .30


def format_normalise(text):
    """Whitespace removal and dash-glyph unification ONLY (no case folding, no character substitution)."""
    return re.sub(r"\s+", "", (text or "").translate(_DASHES))


def distance(a, b):
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def _subsequence(short, long):
    it = iter(long)
    return all(c in it for c in short)


def classify(selected, alternatives, truth):
    """Outcome of one attempted reading. `selected` may be None (nothing selected)."""
    if selected is None or selected == "":
        return "MISSED"
    if selected == truth:
        return "CORRECT_SELECTED"
    if format_normalise(selected) == format_normalise(truth):
        return "CORRECT_SELECTED_FORMAT_ONLY"
    if any(a == truth for a in alternatives or []):
        return "CORRECT_ALTERNATIVE_CONFLICTING"
    if len(selected) < len(truth) and _subsequence(selected, truth):
        return "INCOMPLETE"
    return "WRONG"


def iou(a, b):
    ix = max(0.0, min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]))
    iy = max(0.0, min(a["y1"], b["y1"]) - max(a["y0"], b["y0"]))
    inter = ix * iy
    union = (a["x1"] - a["x0"]) * (a["y1"] - a["y0"]) + (b["x1"] - b["x0"]) * (b["y1"] - b["y0"]) - inter
    return inter / union if union > 0 else 0.0


def _centre_in(inner, outer):
    cx, cy = (inner["x0"] + inner["x1"]) / 2, (inner["y0"] + inner["y1"]) / 2
    return outer["x0"] <= cx <= outer["x1"] and outer["y0"] <= cy <= outer["y1"]


def validate_reference(reference):
    """Return (authority, problems). ADJUDICATED needs a named adjudicated transcription on every readable item."""
    problems = []
    items = reference.get("items", [])
    if reference.get("schema") != "pid-reference-v2":
        problems.append("schema must be pid-reference-v2")
    ids = [i.get("id") for i in items]
    if len(ids) != len(set(ids)):
        problems.append("duplicate item ids")
    adjudicated = reference.get("status") == "ADJUDICATED"
    for it in items:
        if it.get("state") not in ("READABLE", "UNREADABLE", "NOT_TEXT"):
            problems.append(f"{it.get('id')}: state must be READABLE, UNREADABLE or NOT_TEXT")
            continue
        if it["state"] == "READABLE":
            if not isinstance(it.get("text"), str) or not it["text"]:
                problems.append(f"{it['id']}: READABLE needs exact text")
            if adjudicated and it.get("adjudication") != "ADJUDICATED":
                problems.append(f"{it['id']}: not adjudicated")
        for k in ("x0", "y0", "x1", "y1"):
            if not isinstance(it.get("bbox", {}).get(k), (int, float)):
                problems.append(f"{it['id']}: bbox needs x0,y0,x1,y1")
                break
    authority = "ADJUDICATED_DEVELOPMENT" if adjudicated and not problems else "DRAFT_DIAGNOSTIC"
    return authority, problems


def match(items, predictions):
    """Greedy one-to-one-per-prediction assignment of predictions to reference items (see module policy)."""
    owner = {}
    for p_index, p in enumerate(predictions):
        best, best_iou = None, 0.0
        for it in items:
            v = iou(p["bbox"], it["bbox"])
            if v > best_iou:
                best, best_iou = it, v
        if best is not None and best_iou >= IOU_MATCH:
            owner[p_index] = best["id"]
        else:
            for it in items:
                if _centre_in(p["bbox"], it["bbox"]):
                    owner[p_index] = it["id"]
                    break
    return owner


def _select(group):
    flagged = [p for p in group if p.get("selected")]
    if flagged:
        return flagged[0]
    return sorted(group, key=lambda p: (-(p.get("raw_score") or 0), p["bbox"]["x0"], str(p.get("id", ""))))[0]


def score(reference, predictions, *, omitted_by_budget=(), config="unnamed"):
    """Score one configuration. `predictions`: [{bbox, text, selected?, raw_score?, id?}] (media-normalised frame)."""
    authority, problems = validate_reference(reference)
    if problems:
        raise ValueError("invalid reference: " + "; ".join(problems[:5]))
    items = reference["items"]
    owner = match(items, predictions)
    groups = {}
    for i, p in enumerate(predictions):
        if i in owner:
            groups.setdefault(owner[i], []).append(p)
    omitted = set(omitted_by_budget)
    rows = []
    for it in items:
        group = groups.get(it["id"], [])
        if it["state"] == "NOT_TEXT":
            sel = _select(group) if group else None
            rows.append(dict(id=it["id"], category=it.get("category"), state="NOT_TEXT", outcome="FALSE_READING_ON_NON_TEXT" if sel and sel.get("text") else "ABSTAIN_CORRECT"))
            continue
        if it["state"] == "UNREADABLE":
            sel = _select(group) if group else None
            rows.append(dict(id=it["id"], category=it.get("category"), state="UNREADABLE", outcome="FALSE_READING_ON_UNREADABLE" if sel and sel.get("text") else "ABSTAIN_CORRECT"))
            continue
        truth = it["text"]
        if not group:
            rows.append(dict(id=it["id"], category=it.get("category"), state="READABLE", truth=truth, selected=None,
                             outcome="NOT_ATTEMPTED_BUDGET" if it["id"] in omitted else "MISSED", edit=len(truth)))
            continue
        sel = _select(group)
        alternatives = [p["text"] for p in group if p is not sel and p.get("text")]
        out = classify(sel.get("text"), alternatives, truth)
        rows.append(dict(id=it["id"], category=it.get("category"), state="READABLE", truth=truth, selected=sel.get("text"), alternatives=alternatives,
                         outcome=out, edit=distance(sel.get("text") or "", truth) if sel.get("text") else len(truth)))
    readable = [r for r in rows if r["state"] == "READABLE"]
    attempted = [r for r in readable if r["outcome"] not in ("MISSED", "NOT_ATTEMPTED_BUDGET")]
    chars = sum(len(r["truth"]) for r in readable)
    extras = 0
    for region in reference.get("exhaustive_regions", []):
        for i, p in enumerate(predictions):
            if i not in owner and p.get("text") and _centre_in(p["bbox"], region["bbox"]):
                extras += 1
    count = {}
    for r in rows:
        count[r["outcome"]] = count.get(r["outcome"], 0) + 1
    by_cat = {}
    for r in readable:
        c = by_cat.setdefault(r.get("category") or "UNSPECIFIED", dict(items=0, strict_exact=0, format_exact=0))
        c["items"] += 1
        c["strict_exact"] += r["outcome"] == "CORRECT_SELECTED"
        c["format_exact"] += r["outcome"] in ("CORRECT_SELECTED", "CORRECT_SELECTED_FORMAT_ONLY")
    return dict(policy=POLICY, config=config, reference_authority=authority,
                claim="DIAGNOSTIC ONLY - the reference is a draft" if authority == "DRAFT_DIAGNOSTIC" else "Development evaluation on adjudicated crops; not final-test accuracy",
                readable_items=len(readable), strict_exact=count.get("CORRECT_SELECTED", 0),
                format_normalised_exact=count.get("CORRECT_SELECTED", 0) + count.get("CORRECT_SELECTED_FORMAT_ONLY", 0),
                outcomes=count, mean_edit_attempted=round(sum(r["edit"] for r in attempted) / max(1, len(attempted)), 3),
                cer_attempted=round(sum(r["edit"] for r in attempted) / max(1, sum(len(r["truth"]) for r in attempted)), 4),
                cer_with_omissions=round(sum(r["edit"] for r in readable) / max(1, chars), 4),
                abstention=dict(unreadable_or_non_text=sum(r["state"] != "READABLE" for r in rows),
                                correct=sum(r["outcome"] == "ABSTAIN_CORRECT" for r in rows),
                                false_readings=sum(r["outcome"].startswith("FALSE_READING") for r in rows)),
                wrong_extra_detections_in_exhaustive_regions=extras if reference.get("exhaustive_regions") else None,
                by_category=by_cat, rows=rows)
