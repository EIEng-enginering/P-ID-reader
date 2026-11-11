"""E6-08 conservative symbol-connectivity baseline (geometry only; no neural training). PROPOSALS only - never process connectivity facts.
Predicted: binarise (ink < 128), whiten symbol box interiors (boxes shrunk by `shrink` px so the line can still touch the border band),
connected components (8-conn) of the remaining ink; a component 'touches' a symbol if it has ink inside the symbol box band
(box expanded by `band` px minus the shrunk interior).  naive: emit every pair of symbols touching one component (ink-proximity joins).
conservative: emit a pair only when a component touches exactly 2 symbols; components touching >2 symbols -> UNRESOLVED junction (no join).
GT (PID2Graph graphml): symbols = nodes with symbol labels; connectors pass through freely; at a 'crossing' node a path continues only to
the most collinear opposite neighbour (crossing lines do not join).  A GT pair = two symbols linked by such a path with no symbol between."""
import math, collections
import numpy as np
SYMBOL = {"valve", "instrumentation", "general", "arrow", "tank", "pump", "inlet/outlet"}

def gt_pairs(nodes, edges):
    nd = {n["id"]: n for n in nodes}; adj = collections.defaultdict(set)
    for u, v, _ in edges:
        if u in nd and v in nd: adj[u].add(v); adj[v].add(u)
    def c(n): b = nd[n]["box"]; return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) if b else (0, 0)
    def straight(prev, cur):
        px, py = c(prev); cx, cy = c(cur); a = math.atan2(cy - py, cx - px); best, bn = -2, None
        for w in adj[cur]:
            if w == prev: continue
            wx, wy = c(w); b = math.atan2(wy - cy, wx - cx); d = math.cos(b - a)
            if d > best: best, bn = d, w
        return [bn] if bn is not None and best > 0.7 else []
    pairs = set()
    for s in nd:
        if nd[s]["label"] not in SYMBOL: continue
        seen = set(); st = [(w, s) for w in adj[s]]
        while st:
            cur, prev = st.pop()
            if (cur, prev) in seen: continue
            seen.add((cur, prev)); lab = nd[cur]["label"]
            if lab in SYMBOL:
                if cur != s: pairs.add(tuple(sorted((s, cur))))
                continue
            nxt = straight(prev, cur) if lab == "crossing" else [w for w in adj[cur] if w != prev]
            st += [(w, cur) for w in nxt]
    return pairs

def predict(gray, syms, shrink=3, band=4):
    import cv2
    ink = (gray < 128).astype(np.uint8); H, W = ink.shape
    for s in syms:
        x0, y0, x1, y1 = [int(round(v)) for v in s["box"]]; ink[max(0, y0 + shrink):max(0, y1 - shrink), max(0, x0 + shrink):max(0, x1 - shrink)] = 0
    n, lab = cv2.connectedComponents(ink, connectivity=8); touch = collections.defaultdict(set)
    for s in syms:
        x0, y0, x1, y1 = [int(round(v)) for v in s["box"]]; X0, Y0, X1, Y1 = max(0, x0 - band), max(0, y0 - band), min(W, x1 + band), min(H, y1 + band)
        ids = np.unique(lab[Y0:Y1, X0:X1]); 
        for i in ids:
            if i: touch[int(i)].add(s["id"])
    naive, cons, unresolved = set(), set(), 0
    for comp, ss in touch.items():
        ss = sorted(ss)
        if len(ss) < 2: continue
        for a in range(len(ss)):
            for b in range(a + 1, len(ss)): naive.add((ss[a], ss[b]))
        if len(ss) == 2: cons.add((ss[0], ss[1]))
        else: unresolved += 1
    return {"naive": naive, "conservative": cons, "unresolved_junction_components": unresolved}

def score(pred, gt):
    tp = len(pred & gt); fp = len(pred - gt); fn = len(gt - pred); p = tp / (tp + fp) if tp + fp else None; r = tp / (tp + fn) if tp + fn else None
    return {"tp": tp, "false_joins": fp, "fn": fn, "precision": p, "recall": r, "f1": 2 * p * r / (p + r) if p and r else 0.0}
