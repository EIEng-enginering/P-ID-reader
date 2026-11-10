"""TR1 correction-capture & review queue (flag PIDLAB_CORRECTION_QUEUE_TR1, default OFF). Stdlib only.

Integration note: this is the Grok TR1 module with one addition, the ``CONFIRM`` kind (reason ``CONFIRMED_AS_PROPOSED``), so that an engineer's
"yes, this is drawn as proposed" is recorded as well as corrections and rejections. Everything else is unchanged.

Append-only, hash-chained JSONL event log. A correction never edits a proposal or any model; it records
original proposal (hash), corrected value, evidence, reviewer, reason and history. Derived state is recomputed from
the chain. Ambiguous, safety-related, class-swap-across-lookalikes and ANY connection/edge change require an
independent second reviewer (different id from the submitter) before ACCEPTED_FINAL. Only ACCEPTED_FINAL items
can be exported to the batch builder, and export carries no rights - rights are checked again by batches.py.
"""
from __future__ import annotations
import hashlib, json, os, time
from contextlib import contextmanager

SCHEMA = "pid-correction-event/1"
KINDS = ("CONFIRM", "CLASS", "BBOX", "TAG", "PORT", "EDGE_ADD", "EDGE_REMOVE", "EDGE_TYPE", "REJECT_FALSE_POSITIVE", "ADD_MISSED", "MARK_UNRESOLVED")
EDGE_KINDS = {"EDGE_ADD", "EDGE_REMOVE", "EDGE_TYPE"}
REASONS = ("CONFIRMED_AS_PROPOSED", "WRONG_CLASS", "LOOKALIKE_CONFUSION", "MISSED_SYMBOL", "FALSE_POSITIVE", "WRONG_EXTENT", "WRONG_TAG", "TAG_SWAP",
           "PORT_POSITION", "FALSE_JOIN", "MISSED_JOIN", "WRONG_LINE_TYPE", "INSUFFICIENT_EVIDENCE", "OTHER")
ACTIONS = ("IMPORT_PROPOSAL", "SUBMIT", "SECOND_REVIEW_AGREE", "SECOND_REVIEW_DISAGREE", "ADJUDICATE", "WITHDRAW")
GENESIS = "0" * 64


def _canon(o) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha(o) -> str:
    return hashlib.sha256(_canon(o).encode()).hexdigest()


class QueueError(ValueError):
    pass


@contextmanager
def _lock(path):
    lp = path + ".lock"
    try:
        fd = os.open(lp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise QueueError("QUEUE_LOCKED (another writer, or stale lock needing a human check)")
    try:
        yield
    finally:
        os.close(fd); os.remove(lp)


class CorrectionQueue:
    def __init__(self, path: str, catalogue: dict):
        self.path = path
        self.classes = {c["class_id"]: c for c in catalogue["classes"]}
        self.catalogue_version = catalogue["catalogue_version"]

    # ---------- log ----------
    def events(self) -> list[dict]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]

    def verify(self) -> list[str]:
        issues, prev = [], GENESIS
        for i, e in enumerate(self.events()):
            body = {k: v for k, v in e.items() if k != "event_sha256"}
            if e.get("schema") != SCHEMA: issues.append(f"{i}:SCHEMA")
            if e.get("seq") != i: issues.append(f"{i}:SEQ")
            if e.get("prev_sha256") != prev: issues.append(f"{i}:CHAIN_BROKEN")
            if _sha(body) != e.get("event_sha256"): issues.append(f"{i}:EVENT_TAMPERED")
            prev = e.get("event_sha256")
        return issues

    def _append(self, action: str, item_id: str, actor: str, payload: dict, now=None) -> dict:
        if action not in ACTIONS:
            raise QueueError("ACTION")
        if not isinstance(actor, str) or not actor.strip():
            raise QueueError("ACTOR_REQUIRED")
        with _lock(self.path):
            evs = self.events()
            bad = self.verify()
            if bad:
                raise QueueError("CHAIN_INVALID:" + ",".join(bad[:3]))
            body = {"schema": SCHEMA, "seq": len(evs), "prev_sha256": evs[-1]["event_sha256"] if evs else GENESIS,
                    "action": action, "item_id": item_id, "actor": actor.strip(), "catalogue_version": self.catalogue_version,
                    "at_utc": now or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "payload": payload}
            ev = dict(body, event_sha256=_sha(body))
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(_canon(ev) + "\n"); f.flush(); os.fsync(f.fileno())
            return ev

    # ---------- operations ----------
    def import_proposal(self, proposal: dict, *, document_sha256: str, page: int, producer: str, actor="importer", now=None) -> str:
        if not (isinstance(document_sha256, str) and len(document_sha256) == 64):
            raise QueueError("DOCUMENT_SHA")
        if proposal.get("review_state", "PROPOSED") != "PROPOSED":
            raise QueueError("ONLY_PROPOSALS_IMPORTED")
        psha = _sha(proposal)
        pid = "prop-" + psha[:20]
        if any(e["action"] == "IMPORT_PROPOSAL" and e["item_id"] == pid for e in self.events()):
            return pid  # idempotent
        self._append("IMPORT_PROPOSAL", pid, actor, {"proposal": proposal, "proposal_sha256": psha, "document_sha256": document_sha256,
                                                      "page": int(page), "producer": producer}, now)
        return pid

    def submit(self, proposal_id: str, *, kind: str, corrected: dict, reason: str, reviewer: str, evidence: dict, note: str = "", now=None) -> str:
        st = self.state()
        if proposal_id not in st["proposals"]:
            raise QueueError("UNKNOWN_PROPOSAL")
        if kind not in KINDS: raise QueueError("KIND")
        if reason not in REASONS: raise QueueError("REASON")
        if (kind == "CONFIRM") != (reason == "CONFIRMED_AS_PROPOSED"): raise QueueError("CONFIRM_NEEDS_REASON_CONFIRMED_AS_PROPOSED")
        if not isinstance(evidence, dict) or not evidence.get("bbox") or "page" not in evidence:
            raise QueueError("EVIDENCE_REQUIRED (page + bbox)")
        b = evidence["bbox"]
        if not (isinstance(b, list) and len(b) == 4 and all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in b) and b[0] < b[2] and b[1] < b[3]):
            raise QueueError("EVIDENCE_BBOX")
        if kind in ("CONFIRM", "CLASS", "ADD_MISSED"):
            cid = corrected.get("class_id")
            c = self.classes.get(cid)
            if not c: raise QueueError("CLASS_NOT_IN_CATALOGUE")
            if c.get("status") == "DEPRECATED": raise QueueError("CLASS_DEPRECATED")
        if kind in EDGE_KINDS:
            if not corrected.get("from") or not corrected.get("to"): raise QueueError("EDGE_ENDPOINTS")
            if not evidence.get("path_evidence"): raise QueueError("EDGE_PATH_EVIDENCE_REQUIRED (proximity is not connectivity)")
        cid = "cor-" + _sha([proposal_id, kind, corrected, reviewer, len(self.events())])[:20]
        self._append("SUBMIT", cid, reviewer, {"proposal_id": proposal_id, "kind": kind, "corrected": corrected, "reason": reason,
                                               "evidence": evidence, "note": note,
                                               "second_review_required": self._needs_second(proposal_id, kind, corrected, reason, st)}, now)
        return cid

    def _needs_second(self, pid, kind, corrected, reason, st) -> list[str]:
        why = []
        prop = st["proposals"][pid]["proposal"]
        if kind in EDGE_KINDS: why.append("CONNECTION_CHANGE")
        if reason in ("LOOKALIKE_CONFUSION", "INSUFFICIENT_EVIDENCE", "TAG_SWAP"): why.append("AMBIGUOUS")
        if prop.get("confidence_status") in ("AMBIGUOUS", "WEAK_CLASS_WITHHELD"): why.append("AMBIGUOUS_PROPOSAL")
        cls = self.classes.get(corrected.get("class_id"), {})
        if "safety" in (cls.get("note") or "").lower() or cls.get("class_id", "").endswith(("SAFETY_RELIEF", "RUPTURE_DISC", "INTERLOCK")):
            why.append("SAFETY_RELATED_CLASS")
        return why

    def second_review(self, correction_id: str, *, reviewer: str, agree: bool, note: str = "", now=None):
        st = self.state()
        c = st["corrections"].get(correction_id)
        if not c: raise QueueError("UNKNOWN_CORRECTION")
        if c["status"] not in ("AWAITING_SECOND_REVIEW",): raise QueueError("NOT_AWAITING_SECOND_REVIEW")
        if reviewer.strip() == c["submitted_by"]: raise QueueError("SECOND_REVIEWER_MUST_BE_INDEPENDENT")
        self._append("SECOND_REVIEW_AGREE" if agree else "SECOND_REVIEW_DISAGREE", correction_id, reviewer, {"note": note}, now)

    def adjudicate(self, correction_id: str, *, adjudicator: str, accept: bool, note: str, now=None):
        st = self.state(); c = st["corrections"].get(correction_id)
        if not c or c["status"] != "DISPUTED": raise QueueError("ONLY_DISPUTED_ADJUDICATED")
        if adjudicator.strip() in (c["submitted_by"], c.get("second_reviewer")): raise QueueError("ADJUDICATOR_MUST_BE_INDEPENDENT")
        if not note: raise QueueError("ADJUDICATION_NOTE_REQUIRED")
        self._append("ADJUDICATE", correction_id, adjudicator, {"accept": bool(accept), "note": note}, now)

    def withdraw(self, correction_id: str, *, actor: str, note: str, now=None):
        st = self.state(); c = st["corrections"].get(correction_id)
        if not c or c["status"] in ("ACCEPTED_FINAL", "REJECTED_FINAL", "WITHDRAWN"): raise QueueError("CANNOT_WITHDRAW")
        self._append("WITHDRAW", correction_id, actor, {"note": note}, now)

    # ---------- derived state ----------
    def state(self) -> dict:
        props, cors = {}, {}
        for e in self.events():
            a, p = e["action"], e["payload"]
            if a == "IMPORT_PROPOSAL":
                props[e["item_id"]] = dict(p, corrections=[])
            elif a == "SUBMIT":
                need = p["second_review_required"]
                cors[e["item_id"]] = {"id": e["item_id"], "proposal_id": p["proposal_id"], "kind": p["kind"], "corrected": p["corrected"],
                                      "reason": p["reason"], "evidence": p["evidence"], "submitted_by": e["actor"],
                                      "second_review_required": need, "status": "AWAITING_SECOND_REVIEW" if need else "ACCEPTED_FINAL",
                                      "history": [e["event_sha256"]]}
                props[p["proposal_id"]]["corrections"].append(e["item_id"])
            else:
                c = cors[e["item_id"]]; c["history"].append(e["event_sha256"])
                if a == "SECOND_REVIEW_AGREE": c.update(status="ACCEPTED_FINAL", second_reviewer=e["actor"])
                elif a == "SECOND_REVIEW_DISAGREE": c.update(status="DISPUTED", second_reviewer=e["actor"])
                elif a == "ADJUDICATE": c.update(status="ACCEPTED_FINAL" if p["accept"] else "REJECTED_FINAL", adjudicator=e["actor"])
                elif a == "WITHDRAW": c.update(status="WITHDRAWN")
        return {"proposals": props, "corrections": cors}

    def export_accepted(self) -> list[dict]:
        """Accepted, final corrections with full provenance; consumed by batches.py (which re-checks rights)."""
        st = self.state(); out = []
        for c in st["corrections"].values():
            if c["status"] != "ACCEPTED_FINAL":
                continue
            pr = st["proposals"][c["proposal_id"]]
            out.append({"correction_id": c["id"], "kind": c["kind"], "corrected": c["corrected"], "reason": c["reason"],
                        "document_sha256": pr["document_sha256"], "page": pr["page"], "proposal_sha256": pr["proposal_sha256"],
                        "original": {k: pr["proposal"].get(k) for k in ("template_id", "engineering_class", "bbox", "confidence_status")},
                        "evidence": c["evidence"], "reviewers": [x for x in (c["submitted_by"], c.get("second_reviewer"), c.get("adjudicator")) if x],
                        "history": c["history"], "truth_class": "HUMAN_CORRECTED_SINGLE" if len(set(filter(None, [c['submitted_by'], c.get('second_reviewer')]))) < 2 else "HUMAN_CORRECTED_DOUBLE"})
        return sorted(out, key=lambda r: r["correction_id"])

    def active_model_changed(self) -> bool:
        return False  # by construction: the queue has no model handle
