"""(Integration note: verbatim Grok module; only the EventLog import path changed.)
TR1 model registry (flag PIDLAB_MODEL_REGISTRY_TR1, default OFF): ACTIVE / CANDIDATE / PREVIOUS records, shadow
comparison, explicit gated promotion and rollback. Append-only hash-chained event log; registry has NO access to
accepted engineering data. Promotion is never automatic and is BLOCKED when validation evidence is synthetic-only or
same-author, when old-class regression fails, when licence/provenance is not cleared, or when no named human approver.
"""
from __future__ import annotations
import hashlib, json, os
from .events import EventLog, verify_log

GATES = ("FROZEN_VALIDATION_TARGETS_MET", "OLD_CLASS_REGRESSION_OK", "LICENCE_PROVENANCE_CLEARED", "RESOURCE_BEHAVIOUR_OK", "INDEPENDENT_VALIDATION")


class RegistryError(RuntimeError):
    pass


class ModelRegistry:
    def __init__(self, root):
        self.root = root; os.makedirs(root, exist_ok=True)
        self.path = os.path.join(root, "registry.json"); self.log = EventLog(os.path.join(root, "registry_events.jsonl"))
        self.r = json.load(open(self.path)) if os.path.exists(self.path) else {"schema": "pid-tr1-model-registry/1", "models": {}, "active": None, "previous": None}

    def _save(self):
        tmp = self.path + ".tmp"; json.dump(self.r, open(tmp, "w"), indent=1, sort_keys=True); os.replace(tmp, self.path)

    def register_candidate(self, model_path, training_manifest: dict, *, licence: str, provenance: str) -> str:
        need = ("train_data_sha256", "config_sha256", "checkpoints", "batch_sha256", "status")
        miss = [k for k in need if k not in training_manifest]
        if miss: raise RegistryError("TRAINING_EVIDENCE_MISSING:" + ",".join(miss))
        if training_manifest["status"] != "COMPLETED": raise RegistryError("TRAINING_NOT_COMPLETED")
        sha = hashlib.sha256(open(model_path, "rb").read()).hexdigest()
        mid = "mdl-" + sha[:16]
        if mid in self.r["models"]: return mid
        self.r["models"][mid] = {"sha256": sha, "path": model_path, "status": "CANDIDATE", "licence": licence, "provenance": provenance,
                                 "training_manifest": training_manifest, "shadow": []}
        self._save(); self.log.add("REGISTERED_CANDIDATE", model_id=mid, model_sha256=sha)
        return mid

    def record_shadow(self, mid, report: dict):
        """Shadow comparison results (candidate vs active on identical inputs). Changes nothing else."""
        self.r["models"][mid]["shadow"].append(report); self._save(); self.log.add("SHADOW_RECORDED", model_id=mid, report_sha256=hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest())

    def gate_report(self, mid, gates: dict) -> dict:
        missing = [g for g in GATES if gates.get(g) is not True]
        return {"model_id": mid, "gates": {g: bool(gates.get(g)) for g in GATES}, "blocked_by": missing, "pass": not missing}

    def promote(self, mid, *, approver: str, gates: dict) -> dict:
        m = self.r["models"].get(mid)
        if not m or m["status"] != "CANDIDATE": raise RegistryError("NOT_A_CANDIDATE")
        if not approver or approver.lower() in ("auto", "system", "scheduler", "grok"): raise RegistryError("EXPLICIT_HUMAN_APPROVER_REQUIRED")
        rep = self.gate_report(mid, gates)
        if not rep["pass"]:
            self.log.add("PROMOTION_BLOCKED", model_id=mid, blocked_by=rep["blocked_by"]); raise RegistryError("PROMOTION_BLOCKED:" + ",".join(rep["blocked_by"]))
        if self.r["active"]:
            self.r["models"][self.r["active"]]["status"] = "PREVIOUS"
            if self.r["previous"] and self.r["previous"] != self.r["active"]:
                self.r["models"][self.r["previous"]]["status"] = "RETIRED"
        self.r["previous"], self.r["active"] = self.r["active"], mid; m["status"] = "ACTIVE"
        self._save(); self.log.add("PROMOTED", model_id=mid, approver=approver, gate_report=rep)
        return rep

    def rollback(self, *, approver: str):
        if not self.r["previous"]: raise RegistryError("NO_PREVIOUS_MODEL")
        bad = self.r["active"]; self.r["models"][bad]["status"] = "ROLLED_BACK"
        self.r["active"], self.r["previous"] = self.r["previous"], None
        self.r["models"][self.r["active"]]["status"] = "ACTIVE"
        self._save(); self.log.add("ROLLED_BACK", from_model=bad, to_model=self.r["active"], approver=approver)

    def verify(self) -> bool:
        return verify_log(self.log.path) and all(hashlib.sha256(open(m["path"], "rb").read()).hexdigest() == m["sha256"] for m in self.r["models"].values())
