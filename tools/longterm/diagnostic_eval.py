"""Diagnostic comparison of the pretrained model with candidates on NON-authoritative data (run with the ML runtime).

Datasets: (a) a deterministic sample of the held-out text-layer PROXY crops (other operator families, degraded vector renders), and
(b) the S418 DRAFT crops (analyst readings). Neither is human-verified real-scan ground truth, so every output is labelled
DIAGNOSTIC_NOT_AUTHORITATIVE and the predeclared target is applied only as a diagnostic flag. This tool bypasses the programme's
validation-split rules on purpose and therefore can never feed readiness, a pilot verdict or a promotion.
"""
import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from pid_reader.engineering.longterm import evaluate as E  # noqa: E402
from pid_reader.engineering.model_lab.core import verify_model  # noqa: E402
from pid_reader.engineering.model_lab.offline import deny_network  # noqa: E402


def load(path, root, sample=None, seed="diag-v1"):
    doc = json.loads(Path(path).read_text(encoding="utf8"))
    rows = []
    for r in doc["items"]:
        rows.append(dict(id=r["id"], text=r["text"], category=r.get("category"), control=bool(r.get("control")), image_path=str(Path(root) / r["image_path"])))
    if sample and len(rows) > sample:
        rng = random.Random(seed)
        by = {}
        for r in rows:
            by.setdefault(r["category"], []).append(r)
        share = sample / len(rows)
        rows = []
        for cat in sorted(by):
            items = sorted(by[cat], key=lambda r: r["id"])
            rng.shuffle(items)
            rows += items[:max(1, round(len(items) * share))]
        rows.sort(key=lambda r: r["id"])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--candidate", action="append", required=True, help="name=manifest path")
    ap.add_argument("--proxy", type=Path, required=True)
    ap.add_argument("--s418", type=Path, required=True)
    ap.add_argument("--proxy-sample", type=int, default=120)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    sets = dict(heldout_proxy_sample=load(a.proxy, a.proxy.parent, a.proxy_sample), s418_draft=load(a.s418, a.s418.parent))
    models = {"baseline": a.baseline}
    models.update({c.split("=", 1)[0]: Path(c.split("=", 1)[1]) for c in a.candidate})
    preds = {}
    with deny_network():
        for name, manifest_path in models.items():
            manifest = json.loads(manifest_path.read_text())
            root = verify_model(manifest)
            preds[name] = {ds: E._decode(root, rows) for ds, rows in sets.items()}
            print("decoded", name, flush=True)
    target = E.PILOT_TARGET_DEFAULT
    out = dict(label="DIAGNOSTIC_NOT_AUTHORITATIVE", note="Proxy and analyst-draft data. Not human-verified real-scan ground truth, not the pilot verdict, not accuracy.",
               target_applied_as_flag_only=target, target_sha256=E.target_sha(target), datasets={k: len(v) for k, v in sets.items()}, results={})
    for ds, rows in sets.items():
        base = E.report(rows, preds["baseline"][ds])
        out["results"][ds] = dict(baseline=base)
        for name in models:
            if name == "baseline":
                continue
            cand = E.report(rows, preds[name][ds])
            out["results"][ds][name] = dict(report=cand, vs_baseline=E.pilot_verdict(base, cand, target))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, indent=1), encoding="utf8")
    for ds, r in out["results"].items():
        print(ds, "baseline strict", r["baseline"]["strict_exact"], "/", r["baseline"]["samples"], "CER", r["baseline"]["cer"])
        for name, v in r.items():
            if name != "baseline":
                print("  ", name, "strict", v["report"]["strict_exact"], "CER", v["report"]["cer"], v["vs_baseline"]["verdict"], "lost controls", v["vs_baseline"]["lost_easy_controls"])


if __name__ == "__main__":
    main()
