"""Choose among OBSERVED readings of one printed item. Never edits or composes a string.

The returned reading is always one of the inputs; every input is kept as an alternative. `unanimous` is False whenever any two
readings differ after typography-only normalisation (case, whitespace, dash glyphs). Agreement of correlated readers
(same engine on several renderings of one crop) is reported as `independent_sources`, not as corroboration.
"""
import re

_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2212\uff0d"), "-")


def normalise(text):
    return re.sub(r"\s+", "", (text or "").translate(_DASHES)).upper()


def distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def choose(readings):
    """readings: list of dict(text=..., source=...). Returns the observed reading closest to all the others (medoid).

    Ties go to the earlier entry, so callers list the established reader first. Empty/None texts are ignored.
    """
    rows = [dict(r, _n=normalise(r.get("text"))) for r in readings if normalise(r.get("text"))]
    if not rows:
        return dict(status="NO_READING", chosen=None, unanimous=False, alternatives=[], independent_sources=0)
    totals = [sum(distance(r["_n"], o["_n"]) for o in rows) for r in rows]
    best = min(range(len(rows)), key=lambda i: (totals[i], i))
    unanimous = len({r["_n"] for r in rows}) == 1
    sources = {str(r.get("engine", r.get("source", "?"))) for r in rows}
    return dict(status="UNANIMOUS" if unanimous else "CONFLICT", chosen={k: v for k, v in rows[best].items() if k != "_n"},
                unanimous=unanimous, mean_distance_to_others=(totals[best] / (len(rows) - 1)) if len(rows) > 1 else 0.0,
                alternatives=[{k: v for k, v in r.items() if k != "_n"} for i, r in enumerate(rows) if i != best],
                independent_sources=len(sources))
