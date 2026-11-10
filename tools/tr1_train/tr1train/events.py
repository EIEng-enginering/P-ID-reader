"""Hash-chained append-only event log (verbatim from the Grok TR1 trainer_adapter.py): each event stores the sha256 of the previous one."""
from __future__ import annotations
import hashlib, json, os, time


class EventLog:
    def __init__(self, path):
        self.path = path; self.prev = "0" * 64; self.seq = 0
        if os.path.exists(path):
            for l in open(path):
                e = json.loads(l); self.prev = e["sha256"]; self.seq = e["seq"] + 1

    def add(self, state, **info):
        if set(info) & {"seq", "prev", "state", "t", "sha256"}: raise ValueError("RESERVED_EVENT_KEY")
        body = {"seq": self.seq, "prev": self.prev, "state": state, "t": round(time.time(), 3), **info}
        body["sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        with open(self.path, "a") as f: f.write(json.dumps(body, sort_keys=True) + "\n")
        self.prev = body["sha256"]; self.seq += 1
        return body


def verify_log(path) -> bool:
    prev = "0" * 64
    for i, l in enumerate(open(path)):
        e = json.loads(l); s = e.pop("sha256")
        if e["seq"] != i or e["prev"] != prev or hashlib.sha256(json.dumps(e, sort_keys=True).encode()).hexdigest() != s: return False
        prev = s
    return True
