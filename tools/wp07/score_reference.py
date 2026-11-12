"""Diagnostic scoring of text readings against a small explicit reference.

Scope: ONLY the reference items. A DRAFT reference gives a DRAFT score. Nothing here is page recall or accuracy.
The reading taken for each item is fixed by a rule that does not look at the reference text:
  existing   : the single existing OCR word with the largest overlap with the item box;
  easyocr    : engine boxes whose centre lies inside the item box (expanded 25 %), joined in reading order;
  trocr      : readings of the auto-selected crop(s) containing the item, all re-renderings kept; for a vertical crop the quarter
               turn whose readings agree best with each other is used and the other turn is kept as alternatives;
  consensus  : the observed reading closest to all others (existing listed first); status UNANIMOUS or CONFLICT, every other
               reading preserved. It never composes or edits a string.
Outcome: EXACT (case/whitespace/dash-typography only; no O/0 or digit substitution), INCOMPLETE (shorter, all characters appear
in order in the reference), WRONG, MISSED (no reading). Edit distance is reported separately.
"""
import argparse
import json
from pathlib import Path
import sqlite3
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from pid_reader.engineering.model_lab import consensus  # noqa: E402

DASHES = dict.fromkeys(map(ord, "‐‑‒–—−－"), "-")


def norm(text):
    return re.sub(r"\s+", "", (text or "").translate(DASHES)).upper()


def lev(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def subsequence(short, long):
    it = iter(long)
    return all(c in it for c in short)


def outcome(reading, truth):
    if reading is None or not norm(reading):
        return "MISSED", None
    r, t = norm(reading), norm(truth)
    d = lev(r, t)
    if r == t:
        return "EXACT", 0
    if len(r) < len(t) and subsequence(r, t):
        return "INCOMPLETE", d
    return "WRONG", d


def centre(b):
    return (b["x0"] + b["x1"]) / 2, (b["y0"] + b["y1"]) / 2


def expand(b, k=.25):
    w, h = b["x1"] - b["x0"], b["y1"] - b["y0"]
    return dict(x0=b["x0"] - w * k, x1=b["x1"] + w * k, y0=b["y0"] - h * k, y1=b["y1"] + h * k)


def inside(pt, b):
    return b["x0"] <= pt[0] <= b["x1"] and b["y0"] <= pt[1] <= b["y1"]


def join(records, box):
    hit = [r for r in records if inside(centre(r["bbox"]), expand(box))]
    if not hit:
        return None
    vertical = (box["y1"] - box["y0"]) > 1.5 * (box["x1"] - box["x0"])
    hit.sort(key=(lambda r: -centre(r["bbox"])[1]) if vertical else (lambda r: centre(r["bbox"])[0]))
    return " ".join(r["text"] for r in hit)


def best_overlap(records, box):
    def iou(a, b):
        ix = max(0.0, min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]))
        iy = max(0.0, min(a["y1"], b["y1"]) - max(a["y0"], b["y0"]))
        i = ix * iy
        u = (a["x1"] - a["x0"]) * (a["y1"] - a["y0"]) + (b["x1"] - b["x0"]) * (b["y1"] - b["y0"]) - i
        return i / u if u > 0 else 0.0
    scored = sorted(((iou(r["bbox"], box), r) for r in records), key=lambda x: -x[0])
    return scored[0][1]["text"] if scored and scored[0][0] >= .3 else None


def _label(r):
    return "trocr:" + (r["roi_id"].split("-rot", 1)[1])


def trocr_readings(item_box, selection, records):
    """All TrOCR readings of the crop(s) whose region contains the item centre -> (kept readings, other-turn alternatives)."""
    c = centre(item_box)
    ids = {s["id"] for s in selection if inside(c, s["bbox"])}
    mine = [r for r in records if r["roi_id"].rsplit("-rot", 1)[0] in ids and r.get("text")]
    groups = {}
    for r in mine:
        groups.setdefault(r["roi_id"].split("-rot", 1)[1].split("-")[0], []).append(r)
    fmt = lambda rows: [dict(text=r["text"], source=_label(r), engine="trocr") for r in rows]
    if len(groups) <= 1:
        return fmt(mine), []

    def spread(rows):
        t = [consensus.normalise(r["text"]) for r in rows]
        pairs = [(x, y) for i, x in enumerate(t) for y in t[i + 1:]]
        return sum(consensus.distance(x, y) for x, y in pairs) / max(1, len(pairs))
    keep = min(groups, key=lambda k: spread(groups[k]))
    return fmt(groups[keep]), [x for k, v in groups.items() if k != keep for x in fmt(v)]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--eval", type=Path, required=True)
    p.add_argument("--baseline-db", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    ref = json.loads(a.reference.read_text(encoding="utf8"))
    summary = json.loads((a.eval / "summary.json").read_text(encoding="utf8"))
    if summary["source_sha256"] != ref["source_sha256"]:
        raise SystemExit("reference belongs to a different drawing")
    easy = json.loads((a.eval / "easyocr_records.json").read_text(encoding="utf8")) if (a.eval / "easyocr_records.json").exists() else []
    tro = json.loads((a.eval / "trocr_records.json").read_text(encoding="utf8")) if (a.eval / "trocr_records.json").exists() else []
    sel = (summary["engines"].get("trocr") or {}).get("selection", [])
    con = sqlite3.connect(f"file:{a.baseline_db.as_posix()}?mode=ro", uri=True)
    best = con.execute("SELECT analysis_id FROM ocr_word GROUP BY analysis_id ORDER BY COUNT(*) DESC LIMIT 1").fetchone()[0]
    base = [dict(text=t, bbox=json.loads(b)) for t, b in con.execute("SELECT text,bbox_json FROM ocr_word WHERE analysis_id=?", (best,))]
    rows = []
    for it in ref["items"]:
        box = it["bbox"]
        b = best_overlap(base, box)
        e = join([r for r in easy if r["kind"] == "TEXT"], box)
        t_rows, t_alt = trocr_readings(box, sel, tro)
        observed = ([dict(text=b, source="rapidocr", engine="rapidocr")] if b else []) + t_rows
        cons = consensus.choose(observed)
        t = consensus.choose(t_rows)["chosen"]["text"] if t_rows else None
        row = dict(id=it["id"], truth=it["text"], kind=it["kind"], existing=b, easyocr=e, trocr=t,
                   trocr_all=[r["text"] for r in t_rows], trocr_other_turn=[r["text"] for r in t_alt] or None,
                   consensus=cons["chosen"]["text"] if cons["chosen"] else None, consensus_status=cons["status"],
                   consensus_sources=[r["source"] for r in observed])
        for name in ("existing", "easyocr", "trocr", "consensus"):
            row[name + "_outcome"], row[name + "_edit"] = outcome(row[name], it["text"])
        row["combined"] = cons["status"] if observed else "MISSED"
        rows.append(row)

    def tally(name):
        out = {}
        for r in rows:
            out[r[name + "_outcome"]] = out.get(r[name + "_outcome"], 0) + 1
        return out
    comb = {}
    for r in rows:
        comb[r["combined"]] = comb.get(r["combined"], 0) + 1
    flag = dict(
        existing_wrong_or_incomplete=sum(r["existing_outcome"] in ("WRONG", "INCOMPLETE") for r in rows),
        of_those_flagged_by_disagreement=sum(r["existing_outcome"] in ("WRONG", "INCOMPLETE") and r["combined"] == "CONFLICT" for r in rows),
        existing_exact=sum(r["existing_outcome"] == "EXACT" for r in rows),
        of_those_falsely_flagged=sum(r["existing_outcome"] == "EXACT" and r["combined"] == "CONFLICT" for r in rows),
        unanimous_and_exact=sum(r["combined"] == "UNANIMOUS" and r["consensus_outcome"] == "EXACT" for r in rows),
        unanimous_but_wrong=sum(r["combined"] == "UNANIMOUS" and r["consensus_outcome"] != "EXACT" for r in rows),
        consensus_closer_than_existing=sum(r["consensus_edit"] is not None and r["existing_edit"] is not None and r["consensus_edit"] < r["existing_edit"] for r in rows),
        consensus_farther_than_existing=sum(r["consensus_edit"] is not None and r["existing_edit"] is not None and r["consensus_edit"] > r["existing_edit"] for r in rows))
    result = dict(schema="wp07-reference-score-v1", reference_status=ref["status"], reference_items=len(rows),
                  scope=ref["scope"], status="DIAGNOSTIC_DRAFT_REFERENCE_NOT_ACCURACY",
                  outcomes={n: tally(n) for n in ("existing", "easyocr", "trocr", "consensus")},
                  mean_edit_distance_where_a_reading_exists={n: round(sum(r[n + "_edit"] for r in rows if r[n + "_edit"] is not None) / max(1, sum(r[n + "_edit"] is not None for r in rows)), 2) for n in ("existing", "easyocr", "trocr", "consensus")}, combined=comb, error_flagging=flag, rows=rows)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf8")
    print(json.dumps({k: result[k] for k in ("reference_status", "reference_items", "outcomes", "mean_edit_distance_where_a_reading_exists", "combined", "error_flagging")}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
