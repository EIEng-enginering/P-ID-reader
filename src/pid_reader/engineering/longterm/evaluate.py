"""Fixed-crop evaluation on reviewed development crops: baseline-only, and paired baseline/candidate.

Scope: fixed supplied crops only. This is not region discovery, symbol classification, association, connectivity or page accuracy.
Scoring is the strict policy in `scoring.py` (no folding, no substitution; formatting-normalised matches reported separately).
Baseline predictions are cached by (model manifest, dataset, preprocessing, runtime) so the pretrained model is evaluated once and is
never passed off as a trained candidate. Repeated checkpoint evaluation is DEVELOPMENT evaluation, not untouched final-test accuracy.
"""
import hashlib
import json
from pathlib import Path

from . import scoring
from .data import sha, validate
from .store import canonical

PREPROCESSING_ID = "trocr-processor-default-v1"
PILOT_TARGET_DEFAULT = dict(min_relative_strict_error_reduction=0.20, max_lost_easy_controls=0, min_baseline_errors=5,
                            note="Development continuation target, declared before any candidate score exists; not a predicted result, "
                                 "production acceptance or full-page accuracy.")


def target_sha(target):
    return hashlib.sha256(canonical(target).encode()).hexdigest()


def report(rows, texts):
    """Strict fixed-crop report for one model. `texts` align with `rows`."""
    if len(rows) != len(texts):
        raise ValueError("Predictions do not cover the declared reference")
    items, by_cat = [], {}
    for r, t in zip(rows, texts):
        outcome = scoring.classify(t, [], r["text"])
        edit = scoring.distance(t or "", r["text"])
        items.append(dict(id=r["id"], category=r.get("category"), control=bool(r.get("control")), reference=r["text"], observed=t, outcome=outcome, edit_distance=edit))
        c = by_cat.setdefault(r.get("category") or "UNSPECIFIED", dict(items=0, strict_exact=0, format_normalised_exact=0))
        c["items"] += 1
        c["strict_exact"] += outcome == "CORRECT_SELECTED"
        c["format_normalised_exact"] += outcome in ("CORRECT_SELECTED", "CORRECT_SELECTED_FORMAT_ONLY")
    chars = sum(len(r["text"]) for r in rows)
    strict = sum(i["outcome"] == "CORRECT_SELECTED" for i in items)
    return dict(policy=scoring.POLICY, status="MEASURED_REVIEWED_DEVELOPMENT_CROPS",
                scope="Fixed supplied crops; not page discovery, symbols, association, connectivity or engineering validation",
                samples=len(rows), strict_exact=strict, strict_errors=len(rows) - strict,
                format_normalised_exact=sum(i["outcome"] in ("CORRECT_SELECTED", "CORRECT_SELECTED_FORMAT_ONLY") for i in items),
                mean_edit_distance=round(sum(i["edit_distance"] for i in items) / max(1, len(items)), 4),
                cer=round(sum(i["edit_distance"] for i in items) / max(1, chars), 4), by_category=by_cat, items=items)


def pilot_verdict(baseline, candidate, target):
    """Compare candidate with baseline against the target that was frozen before any candidate score was seen."""
    b_err, c_err = baseline["strict_errors"], candidate["strict_errors"]
    controls_base_ok = {i["id"] for i in baseline["items"] if i["control"] and i["outcome"] == "CORRECT_SELECTED"}
    lost = sorted(i["id"] for i in candidate["items"] if i["id"] in controls_base_ok and i["outcome"] != "CORRECT_SELECTED")
    newly_right = sorted(i["id"] for b, i in zip(baseline["items"], candidate["items"]) if b["outcome"] != "CORRECT_SELECTED" and i["outcome"] == "CORRECT_SELECTED")
    newly_wrong = sorted(i["id"] for b, i in zip(baseline["items"], candidate["items"]) if b["outcome"] == "CORRECT_SELECTED" and i["outcome"] != "CORRECT_SELECTED")
    reduction = (b_err - c_err) / b_err if b_err else None
    if b_err < target["min_baseline_errors"]:
        verdict = "INCONCLUSIVE_TOO_FEW_BASELINE_ERRORS"
    elif reduction >= target["min_relative_strict_error_reduction"] and len(lost) <= target["max_lost_easy_controls"]:
        verdict = "TARGET_MET_DEVELOPMENT_ONLY"
    else:
        verdict = "TARGET_NOT_MET"
    return dict(verdict=verdict, baseline_strict_errors=b_err, candidate_strict_errors=c_err, relative_strict_error_reduction=None if reduction is None else round(reduction, 4),
                lost_easy_controls=lost, newly_correct=newly_right, newly_wrong=newly_wrong, target=target, target_sha256=target_sha(target),
                note="Development target only. Not production acceptance; the model stays CANDIDATE.")


def _runtime_id():
    import importlib.metadata as m
    import platform
    v = {}
    for n in ("torch", "transformers", "Pillow"):
        try:
            v[n] = m.version(n)
        except m.PackageNotFoundError:
            v[n] = None
    return hashlib.sha256(canonical(dict(python=platform.python_version(), versions=v)).encode()).hexdigest()[:16]


def baseline_cache_key(model_manifest, dataset_sha256):
    files = model_manifest.get("files", {})
    return hashlib.sha256(canonical(dict(model=files, revision=model_manifest.get("revision"), dataset=dataset_sha256, preprocessing=PREPROCESSING_ID, runtime=_runtime_id())).encode()).hexdigest()[:32]


def _decode(root, rows):
    import torch
    from PIL import Image
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel
    torch.set_num_threads(2)
    processor = TrOCRProcessor.from_pretrained(str(root), local_files_only=True, use_fast=False)
    model = VisionEncoderDecoderModel.from_pretrained(str(root), local_files_only=True, use_safetensors=True).to("cpu").eval()
    texts = []
    with torch.inference_mode():
        for row in rows:
            with Image.open(row["image_path"]) as image:
                if image.width * image.height > 4_000_000:
                    raise ValueError("Evaluation crop exceeds pixel budget")
                values = processor(images=image.convert("RGB"), return_tensors="pt").pixel_values
            ids = model.generate(values, max_new_tokens=96)
            texts.append(processor.batch_decode(ids, skip_special_tokens=True)[0])
    del model
    return texts


def _baseline_predictions(payload, out, rows, fingerprint, verify_model):
    manifest = json.loads(Path(payload["model_manifest_path"]).read_text())
    root = verify_model(manifest)
    cache = Path(out).parent.parent / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    key = baseline_cache_key(manifest, fingerprint)
    path = cache / f"baseline_{key}.json"
    if path.is_file():
        saved = json.loads(path.read_text(encoding="utf8"))
        if saved.get("ids") == [r["id"] for r in rows]:
            return saved["texts"], dict(cache="HIT", key=key)
    texts = _decode(root, rows)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(ids=[r["id"] for r in rows], texts=texts, model_revision=manifest.get("revision"), dataset_sha256=fingerprint,
                                   preprocessing=PREPROCESSING_ID)), encoding="utf8")
    tmp.replace(path)
    return texts, dict(cache="MISS", key=key)


def evaluate_baseline(payload, out):
    """Baseline-only evaluation of the pretrained model on the validation split. Produces no candidate and no verdict."""
    from ..model_lab.core import verify_model
    from ..model_lab.offline import deny_network
    rows, fingerprint = validate(payload["dataset_path"], purpose="validate")
    if fingerprint != payload["dataset_sha256"]:
        raise ValueError("Validation manifest changed after enqueue")
    with deny_network():
        texts, cache = _baseline_predictions(payload, out, rows, fingerprint, verify_model)
    return dict(status="SUCCEEDED", mode="BASELINE_ONLY", report=report(rows, texts), baseline_cache=cache, dataset_sha256=fingerprint,
                candidate_only=True, promoted=False, engineering_acceptance="NOT_RUN")


def evaluate(payload, out):
    """Paired baseline/candidate evaluation with leakage checks and the frozen pilot target."""
    from ..model_lab.core import verify_model
    from ..model_lab.offline import deny_network
    rows, fingerprint = validate(payload["dataset_path"], purpose="validate")
    if fingerprint != payload["dataset_sha256"]:
        raise ValueError("Validation manifest changed after enqueue")
    train_rows, training_sha = validate(payload["training_dataset_path"])
    if {r["family_id"] for r in rows} & {r["family_id"] for r in train_rows} or {r["source_sha256"] for r in rows} & {r["source_sha256"] for r in train_rows} \
            or {r["image_sha256"] for r in rows} & {r["image_sha256"] for r in train_rows}:
        raise ValueError("Training/validation document leakage")
    with deny_network():
        base_texts, cache = _baseline_predictions(payload, out, rows, fingerprint, verify_model)
        manifest = json.loads(Path(payload["candidate_manifest_path"]).read_text())
        root = verify_model(manifest)
        provenance = json.loads((root / "checkpoint.json").read_text())
        if provenance["dataset_sha256"] != training_sha:
            raise ValueError("Candidate training provenance differs from declared training data")
        cand_texts = _decode(root, rows)
    baseline, candidate = report(rows, base_texts), report(rows, cand_texts)
    target = payload.get("target") or PILOT_TARGET_DEFAULT
    out_doc = dict(status="SUCCEEDED", mode="PAIRED", reports=dict(baseline=baseline, candidate=candidate), baseline_cache=cache, dataset_sha256=fingerprint,
                   exact_delta=candidate["strict_exact"] - baseline["strict_exact"], verdict=pilot_verdict(baseline, candidate, target),
                   evaluation_kind="DEVELOPMENT_EVALUATION_NOT_FINAL_TEST", candidate_only=True, promoted=False, engineering_acceptance="NOT_RUN")
    return out_doc
