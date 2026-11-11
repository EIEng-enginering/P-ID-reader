"""R3 automatic-workflow guard for the TR1 correction queue (owner R3: no reviewer time; software must never self-accept).
GuardedQueue refuses any human-only transition (SUBMIT, SECOND_REVIEW_*, ADJUDICATE) by a machine actor (ids starting with
'auto:', 'model:', 'pipeline:', 'grok:' or listed in MACHINE_ACTORS).  Machine outputs may only be IMPORTED as proposals, carrying a
machine truth_type (MODEL_PSEUDOLABEL / WEAK_GEOMETRY / SYNTHETIC_CONSTRUCTION / PUBLIC_ANNOTATED); export_accepted() is unchanged, so
with no human actor nothing is ever exported as HUMAN_CORRECTED_*.  Human-only transitions stay unexercised in R3 (BLOCKED by design)."""
from . import corrections as cq
MACHINE_PREFIXES = ("auto:", "model:", "pipeline:", "grok:")
MACHINE_TRUTH = {"MODEL_PSEUDOLABEL", "WEAK_GEOMETRY", "SYNTHETIC_CONSTRUCTION", "PUBLIC_ANNOTATED"}
class MachineActorRefused(cq.QueueError): pass
def is_machine(actor, extra=()): return not isinstance(actor, str) or actor.strip().lower().startswith(MACHINE_PREFIXES) or actor in extra
class GuardedQueue(cq.CorrectionQueue):
    def __init__(self, path, catalogue, machine_actors=()):
        super().__init__(path, catalogue); self.machine_actors = set(machine_actors)
    def _deny(self, actor):
        if is_machine(actor, self.machine_actors): raise MachineActorRefused(f"HUMAN_ONLY_TRANSITION_REFUSED_FOR_MACHINE_ACTOR:{actor}")
    def import_machine_proposal(self, proposal, *, truth_type, document_sha256, page, producer, now=None):
        if truth_type not in MACHINE_TRUTH: raise cq.QueueError("TRUTH_TYPE")
        p = dict(proposal, truth_type=truth_type, review_state="PROPOSED")
        return self.import_proposal(p, document_sha256=document_sha256, page=page, producer=producer, actor="pipeline:" + producer, now=now)
    def submit(self, proposal_id, *, reviewer, **kw): self._deny(reviewer); return super().submit(proposal_id, reviewer=reviewer, **kw)
    def second_review(self, correction_id, *, reviewer, **kw): self._deny(reviewer); return super().second_review(correction_id, reviewer=reviewer, **kw)
    def adjudicate(self, correction_id, *, adjudicator, **kw): self._deny(adjudicator); return super().adjudicate(correction_id, adjudicator=adjudicator, **kw)
