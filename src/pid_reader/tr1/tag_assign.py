"""E6-07 crowded tag -> symbol association with abstention (proposal-only; never accepted automatically).
Cost per (tag, symbol) pair, all terms evidence-based:
  d   = centre distance / symbol size (max side); pairs with d > radius are not candidates
  containment: tag box inside symbol box (e.g. text inside an instrument bubble) -> distance term 0
  leader: a supplied leader/line segment with one end within `leader_tol`*size of the tag box and the other within it of the symbol box -> x0.3
  pattern: optional callable(tag_text, symbol_class) -> True/False/None (None = no evidence); False adds +1.0, True subtracts 0.2
Global min-cost assignment (Hungarian, own implementation, stdlib) over tags x (symbols + one dummy 'UNRESOLVED' column per tag with
cost = abstain_cost).  Tags may share a symbol only if allow_shared (default False: one tag per symbol, as in stacked/duplicated tags
the caller must group fragments first).  Each output carries: symbol id or None, cost, margin to the best alternative, status
PROPOSED / AMBIGUOUS (margin < min_margin) / UNRESOLVED, and the top-3 alternatives.  The tag text is NOT used to match to gold."""
import math

def _hungarian(C):
    n, m = len(C), len(C[0]); assert n <= m
    INF = float("inf"); u = [0.0] * (n + 1); v = [0.0] * (m + 1); p = [0] * (m + 1); way = [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i; j0 = 0; minv = [INF] * (m + 1); used = [False] * (m + 1)
        while True:
            used[j0] = True; i0 = p[j0]; delta = INF; j1 = 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = C[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]: minv[j] = cur; way[j] = j0
                    if minv[j] < delta: delta = minv[j]; j1 = j
            for j in range(m + 1):
                if used[j]: u[p[j]] += delta; v[j] -= delta
                else: minv[j] -= delta
            j0 = j1
            if p[j0] == 0: break
        while True:
            j1 = way[j0]; p[j0] = p[j1]; j0 = j1
            if j0 == 0: break
    a = [None] * n
    for j in range(1, m + 1):
        if p[j]: a[p[j] - 1] = j - 1
    return a

def _c(b): return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
def _near(pt, b, tol): return b[0] - tol <= pt[0] <= b[2] + tol and b[1] - tol <= pt[1] <= b[3] + tol

def pair_cost(tag, sym, leaders=(), pattern=None, radius=3.0, leader_tol=0.25):
    sb, tb = sym["box"], tag["box"]; size = max(sb[2] - sb[0], sb[3] - sb[1], 1e-6); (tx, ty), (sx, sy) = _c(tb), _c(sb)
    d = math.hypot(tx - sx, ty - sy) / size
    inside = tb[0] >= sb[0] and tb[1] >= sb[1] and tb[2] <= sb[2] and tb[3] <= sb[3]
    if d > radius and not inside: return None
    c = 0.0 if inside else d
    for (x0, y0, x1, y1) in leaders:
        t = leader_tol * size
        if (_near((x0, y0), tb, t) and _near((x1, y1), sb, t)) or (_near((x1, y1), tb, t) and _near((x0, y0), sb, t)): c *= 0.3; break
    if pattern is not None:
        ok = pattern(tag.get("text", ""), sym.get("cls"))
        if ok is False: c += 1.0
        elif ok is True: c = max(0.0, c - 0.2)
    return c

def _bdist(pt, b): return math.hypot(max(b[0] - pt[0], 0, pt[0] - b[2]), max(b[1] - pt[1], 0, pt[1] - b[3]))

def leader_owners(tags, syms, leaders, tol_px=12.0):
    """each leader belongs to at most ONE tag (the tag box nearest one endpoint) and ONE symbol (nearest the other endpoint); else unused"""
    own = {}
    for L in leaders:
        best = None
        for a, b in (((L[0], L[1]), (L[2], L[3])), ((L[2], L[3]), (L[0], L[1]))):
            if not tags or not syms: break
            ti = min(range(len(tags)), key=lambda i: _bdist(a, tags[i]["box"])); si = min(range(len(syms)), key=lambda j: _bdist(b, syms[j]["box"]))
            dd = _bdist(a, tags[ti]["box"]) + _bdist(b, syms[si]["box"])
            if _bdist(a, tags[ti]["box"]) <= tol_px and _bdist(b, syms[si]["box"]) <= tol_px and (best is None or dd < best[0]): best = (dd, ti, si)
        if best: own.setdefault(best[1], []).append((best[2], L))
    return own

def assign(tags, syms, leaders=(), pattern=None, radius=3.0, abstain_cost=2.5, min_margin=0.15):
    n, m = len(tags), len(syms); BIG = 1e6; own = leader_owners(tags, syms, leaders)
    def pc(i, j):
        L = [l for sj, l in own.get(i, []) if sj == j]; return pair_cost(tags[i], syms[j], L, pattern, radius)
    C = [[(pc(i, j) if pc(i, j) is not None else BIG) for j in range(m)] + [abstain_cost if k == i else BIG for k in range(n)] for i in range(n)]
    a = _hungarian(C) if n else []; out = []
    for i, t in enumerate(tags):
        row = sorted(((C[i][j], syms[j]["id"]) for j in range(m) if C[i][j] < BIG), key=lambda x: x[0])
        j = a[i]
        if j is None or j >= m or C[i][j] >= BIG:
            out.append({"tag": t["id"], "symbol": None, "status": "UNRESOLVED", "cost": None, "margin": None, "alternatives": row[:3]}); continue
        alt = [c for c, sid in row if sid != syms[j]["id"]]; margin = (alt[0] - C[i][j]) if alt else (abstain_cost - C[i][j])
        out.append({"tag": t["id"], "symbol": syms[j]["id"], "status": "AMBIGUOUS" if margin < min_margin else "PROPOSED", "cost": round(C[i][j], 4), "margin": round(margin, 4),
                    "alternatives": row[:3], "review_state": "PROPOSED"})
    return out

def nearest(tags, syms):
    """baseline: each tag to the nearest symbol centre (no abstention, shared allowed)"""
    out = []
    for t in tags:
        tx, ty = _c(t["box"]); b = min(syms, key=lambda s: math.hypot(tx - _c(s["box"])[0], ty - _c(s["box"])[1])) if syms else None
        out.append({"tag": t["id"], "symbol": b["id"] if b else None, "status": "PROPOSED" if b else "UNRESOLVED"})
    return out

def score(pred, truth):
    """truth: tag id -> symbol id (or None). Returns precision over committed (PROPOSED+AMBIGUOUS) answers, recall, unresolved, reciprocal swaps, cycles>2."""
    com = [p for p in pred if p["symbol"] is not None]; tp = sum(1 for p in com if truth.get(p["tag"]) == p["symbol"]); pos = sum(1 for v in truth.values() if v is not None)
    wrong = {p["tag"]: p["symbol"] for p in com if truth.get(p["tag"]) != p["symbol"]}
    inv = {v: k for k, v in truth.items() if v is not None}; swaps = 0; seen = set()
    for t, s in wrong.items():
        o = inv.get(s)
        if o and o not in seen and wrong.get(o) == truth.get(t): swaps += 1; seen |= {t, o}
    return {"committed": len(com), "tp": tp, "precision": tp / len(com) if com else None, "recall": tp / pos if pos else None,
            "unresolved": sum(1 for p in pred if p["symbol"] is None), "ambiguous": sum(1 for p in pred if p.get("status") == "AMBIGUOUS"), "reciprocal_swaps": swaps}
