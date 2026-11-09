"""Gold annotation validation, annotator agreement and scoring against snapshots (Rev X, WPU-16). Pure functions.

Honesty rules built in:
* every metric carries TP/FP/FN and the denominators; a zero denominator gives ``None``, never 100 %;
* 95 % Wilson intervals accompany proportions;
* predictions in regions the annotators left unannotated (or marked out of scope) are *unscored*, not false positives;
* a gold item that was missed but lies in a flagged region (unprocessed region, withheld-class symbol) is a ``FLAGGED_MISS``; one with no flag at all is
  a ``SILENT_MISS`` and is the number that matters for trust;
* a near miss (right place, wrong tag or class) is a failure, not a partial credit;
* raw scores are UNCALIBRATED: calibration metrics exist only when a calibration id is given;
* ``FINAL_RESERVED`` gold is refused unless ``allow_final`` is set, and each such use is logged;
* an accuracy claim is only marked allowed for adjudicated ``REAL_INDEPENDENT`` gold with at least two annotators.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from math import sqrt
from pathlib import Path

VERSION = "gold-scoring-v1"
SCHEMA_PATH = Path(__file__).resolve().parents[3] / "contracts" / "benchmark_gold_v1.schema.json"
CRITICAL_KINDS = ("VALVE", "INSTRUMENT", "EQUIPMENT")
CONNECT_TYPES = ("DRAWN_CONNECTS", "SIGNAL_CONNECTS")


class ReservedSplitError(PermissionError):
    pass


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n <= 0:
        return None
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def _ratio(k: int, n: int) -> dict:
    return {"value": round(k / n, 4) if n else None, "numerator": k, "denominator": n, "ci95": wilson(k, n)}


def validate_gold(gold: dict) -> list[str]:
    """Schema problems plus cross-checks (empty list = valid)."""
    import jsonschema
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = [f"{'/'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in jsonschema.Draft202012Validator(schema).iter_errors(gold)]
    ids = [o["id"] for o in gold.get("objects", [])] if isinstance(gold.get("objects"), list) else []
    if len(ids) != len(set(ids)):
        errors.append("objects: duplicate ids")
    known = set(ids)
    for e in gold.get("edges", []) if isinstance(gold.get("edges"), list) else []:
        if e.get("from_id") not in known or e.get("to_id") not in known:
            errors.append(f"edges: endpoint not an annotated object ({e.get('from_id')}, {e.get('to_id')})")
    if gold.get("adjudication_status") == "ADJUDICATED" and len(gold.get("annotator_ids", [])) < 2:
        errors.append("an ADJUDICATED record needs at least two named annotators")
    return errors


def _iou(a: dict, b: dict) -> float:
    ix = max(0.0, min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]))
    iy = max(0.0, min(a["y1"], b["y1"]) - max(a["y0"], b["y0"]))
    inter = ix * iy
    union = (a["x1"] - a["x0"]) * (a["y1"] - a["y0"]) + (b["x1"] - b["x0"]) * (b["y1"] - b["y0"]) - inter
    return inter / union if union > 0 else 0.0


def _overlaps(a: dict, b: dict) -> bool:
    return min(a["x1"], b["x1"]) > max(a["x0"], b["x0"]) and min(a["y1"], b["y1"]) > max(a["y0"], b["y0"])


def _norm_tag(t: str | None) -> str | None:
    return None if not t else "".join(ch for ch in t.upper() if ch.isalnum())


def agreement(a: dict, b: dict, *, iou: float = 0.3) -> dict:
    """Object-level agreement between two annotators' gold files for the same drawing."""
    if a["drawing_sha256"] != b["drawing_sha256"]:
        raise ValueError("The two annotation files describe different drawings")
    used, pairs, only_a = set(), [], []
    for oa in a["objects"]:
        best = None
        for ob in b["objects"]:
            if ob["id"] in used or ob["page_index"] != oa["page_index"]:
                continue
            v = _iou(oa["bbox"], ob["bbox"])
            if v >= iou and (best is None or v > best[0]):
                best = (v, ob)
        if best:
            used.add(best[1]["id"])
            pairs.append((oa, best[1]))
        else:
            only_a.append(oa["id"])
    only_b = [o["id"] for o in b["objects"] if o["id"] not in used]
    kind_dis = [(x["id"], y["id"]) for x, y in pairs if x["kind"] != y["kind"]]
    tag_dis = [(x["id"], y["id"]) for x, y in pairs if _norm_tag(x["tag"]) != _norm_tag(y["tag"])]
    total = len(pairs) + len(only_a) + len(only_b)
    return {"objects_matched": len(pairs), "only_in_first": only_a, "only_in_second": only_b, "kind_disagreements": kind_dis, "tag_disagreements": tag_dis,
            "object_agreement": _ratio(len(pairs) - len({p for p in kind_dis} | {p for p in tag_dis}), total),
            "needs_adjudication": bool(only_a or only_b or kind_dis or tag_dis)}


def _pred_objects(snapshot: dict) -> list[dict]:
    ev = {e["id"]: e for e in snapshot["evidence"]}
    out = []
    for e in snapshot["entities"]:
        if not e["source_evidence_ids"] or e["kind"] in ("TABLE", "TABLE_CELL", "ANNOTATION", "INSTRUMENT_LOOP"):
            continue
        x = ev.get(e["source_evidence_ids"][0])
        if x:
            out.append({"id": e["id"], "kind": e["kind"], "tag": e["tag"], "page_index": x["page_index"], "bbox": x["bbox"], "classification": e["classification"]})
    return out


def score(gold: dict, snapshot: dict, *, iou: float = 0.3, allow_final: bool = False, access_log: str | Path | None = None,
          stratum: str = "UNSTRATIFIED", calibration_id: str | None = None, critical_kinds: tuple[str, ...] = CRITICAL_KINDS) -> dict:
    problems = validate_gold(gold)
    if problems:
        raise ValueError("Gold annotation is invalid: " + "; ".join(problems[:5]))
    if gold["split"] == "FINAL_RESERVED":
        if not allow_final:
            raise ReservedSplitError("This gold file belongs to the reserved final split; scoring it requires allow_final=True and is logged")
        if access_log:
            with open(access_log, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "drawing_sha256": gold["drawing_sha256"], "stratum": stratum}) + "\n")
    if snapshot["drawings"][0]["sha256"] != gold["drawing_sha256"]:
        raise ValueError("The snapshot and the gold annotation describe different drawing bytes")
    preds = _pred_objects(snapshot)
    verified = [o for o in gold["objects"] if o["review_state"] == "GOLD_VERIFIED"]
    ambiguous = [o for o in gold["objects"] if o["review_state"] == "GOLD_AMBIGUOUS"]
    skip_regions = [r for r in gold["regions"] if r["reading_status"] in ("UNANNOTATED", "OUT_OF_SCOPE", "UNREADABLE")]
    cand = []
    for g in verified + ambiguous:
        for p in preds:
            if p["page_index"] == g["page_index"]:
                v = _iou(g["bbox"], p["bbox"])
                if v >= iou:
                    cand.append((v, g["id"], p["id"]))
    cand.sort(key=lambda c: (-c[0], c[1], c[2]))
    gmatch, pmatch = {}, {}
    for v, gid, pid in cand:
        if gid not in gmatch and pid not in pmatch:
            gmatch[gid], pmatch[pid] = pid, gid
    gby = {o["id"]: o for o in gold["objects"]}
    pby = {p["id"]: p for p in preds}
    per_class: dict[str, dict] = {}

    def cls(k):
        return per_class.setdefault(k, {"TP": 0, "FP": 0, "FN": 0, "near_miss": 0, "ambiguous_gold": 0, "unscored_predictions": 0})
    wrong_class = []
    for g in verified:
        c = cls(g["kind"].upper())
        pid = gmatch.get(g["id"])
        if pid and pby[pid]["kind"] == g["kind"].upper():
            c["TP"] += 1
        elif pid:
            c["FN"] += 1
            c["near_miss"] += 1
            wrong_class.append({"gold_id": g["id"], "gold_kind": g["kind"], "predicted_kind": pby[pid]["kind"]})
            cls(pby[pid]["kind"])["FP"] += 1
        else:
            c["FN"] += 1
    for g in ambiguous:
        cls(g["kind"].upper())["ambiguous_gold"] += 1
    for p in preds:
        if p["id"] in pmatch:
            continue
        if any(r["page_index"] == p["page_index"] and _overlaps(p["bbox"], r["bbox"]) for r in skip_regions):
            cls(p["kind"])["unscored_predictions"] += 1
        else:
            cls(p["kind"])["FP"] += 1
    classes = {}
    for k, c in sorted(per_class.items()):
        classes[k] = {**c, "precision": _ratio(c["TP"], c["TP"] + c["FP"]), "recall": _ratio(c["TP"], c["TP"] + c["FN"]),
                      "f1": (round(2 * c["TP"] / (2 * c["TP"] + c["FP"] + c["FN"]), 4) if (2 * c["TP"] + c["FP"] + c["FN"]) else None)}
    # tag attachment: exact tag on the right occurrence; a near miss is a failure
    tag_tp = tag_wrong = tag_missing = 0
    for g in verified:
        if not g["tag"]:
            continue
        pid = gmatch.get(g["id"])
        if not pid:
            continue
        pt = pby[pid]["tag"]
        if pt is None:
            tag_missing += 1
        elif _norm_tag(pt) == _norm_tag(g["tag"]):
            tag_tp += 1
        else:
            tag_wrong += 1
    tag_den = tag_tp + tag_wrong + tag_missing
    # connectivity
    pred_edges = set()
    for r in snapshot["relationships"]:
        if r["type"] in CONNECT_TYPES:
            pred_edges.add(frozenset((r["from_entity_id"], r["to_entity_id"])))
    e_tp = e_fn = crit_fp = unjudged = 0
    judged = set()
    for e in gold["edges"]:
        a, b = gmatch.get(e["from_id"]), gmatch.get(e["to_id"])
        pair = frozenset((a, b)) if a and b else None
        if e["edge_status"] == "GOLD_CONNECTED":
            if pair and pair in pred_edges:
                e_tp += 1
                judged.add(pair)
            else:
                e_fn += 1
        elif e["edge_status"] == "GOLD_NOT_CONNECTED" and pair and pair in pred_edges:
            crit_fp += 1
            judged.add(pair)
    unjudged = len([p for p in pred_edges if p not in judged and all(x in pmatch for x in p)])
    # silent misses
    unprocessed = snapshot["quality"]["unprocessed_regions"]
    withheld = [(p["page_index"], p["bbox"]) for p in preds if p["classification"] in (None, "UNKNOWN") or p["kind"] == "UNCLASSIFIED_SYMBOL"]
    silent, flagged = [], []
    for g in verified:
        if gmatch.get(g["id"]) or g["kind"].upper() not in critical_kinds:
            continue
        covered = any(u["page_index"] == g["page_index"] and _overlaps(u["bbox"], g["bbox"]) for u in unprocessed) or \
            any(pi == g["page_index"] and _overlaps(b, g["bbox"]) for pi, b in withheld)
        (flagged if covered else silent).append(g["id"])
    crit_total = sum(1 for g in verified if g["kind"].upper() in critical_kinds)
    claim_ok = gold["split"] == "REAL_INDEPENDENT" and gold["adjudication_status"] == "ADJUDICATED" and len(gold["annotator_ids"]) >= 2
    cal = {"status": "NOT_APPLICABLE_UNCALIBRATED", "note": "raw similarity scores are not probabilities"} if not calibration_id else {"status": "CALIBRATION_ID_GIVEN", "calibration_id": calibration_id}
    return {"schema": "pid-reader-gold-score-v1", "version": VERSION, "drawing_sha256": gold["drawing_sha256"], "split": gold["split"], "stratum": stratum,
            "iou_threshold": iou, "gold_counts": {"verified": len(verified), "ambiguous": len(ambiguous), "not_legible": sum(1 for o in gold["objects"] if o["review_state"] == "NOT_LEGIBLE"),
                                                  "edges": len(gold["edges"]), "regions_skipped": len(skip_regions)},
            "prediction_counts": {"objects": len(preds)}, "classes": classes, "class_confusions": wrong_class,
            "tag_attachment": {"correct": _ratio(tag_tp, tag_den), "wrong_tag": tag_wrong, "missing_tag": tag_missing},
            "connectivity": {"recall": _ratio(e_tp, e_tp + e_fn), "critical_false_connections": crit_fp, "unjudged_predicted_edges": unjudged},
            "silent_misses": {"critical_gold_total": crit_total, "silent": len(silent), "flagged": len(flagged), "silent_ids": silent, "flagged_ids": flagged,
                              "silent_miss_rate": _ratio(len(silent), crit_total)},
            "calibration": cal,
            "claims": {"accuracy_claim_allowed": claim_ok,
                       "basis": "adjudicated REAL_INDEPENDENT gold with >=2 annotators" if claim_ok else
                       ("REGRESSION_ONLY: synthetic/dev gold is not independent evidence" if gold["split"] != "REAL_INDEPENDENT" else "gold not adjudicated by two annotators")}}


def aggregate(reports: list[dict]) -> dict:
    """Pool counts across drawings per (stratum, class); ratios are recomputed from pooled counts (never averaged)."""
    pool: dict[tuple[str, str], dict] = {}
    silent = crit = 0
    for r in reports:
        silent += r["silent_misses"]["silent"]
        crit += r["silent_misses"]["critical_gold_total"]
        for k, c in r["classes"].items():
            p = pool.setdefault((r["stratum"], k), {"TP": 0, "FP": 0, "FN": 0})
            for f in ("TP", "FP", "FN"):
                p[f] += c[f]
    rows = [{"stratum": s, "class": k, **c, "precision": _ratio(c["TP"], c["TP"] + c["FP"]), "recall": _ratio(c["TP"], c["TP"] + c["FN"])} for (s, k), c in sorted(pool.items())]
    return {"drawings": len(reports), "rows": rows, "silent_miss_rate": _ratio(silent, crit),
            "note": "pooled counts; strata are never averaged together and unsupported classes are not hidden in a mean"}
