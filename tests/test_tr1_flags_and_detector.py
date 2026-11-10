"""TR1 integration: switches default OFF, OFF does nothing, the detector runner degrades cleanly and is contained (timeout / cancel / refusal)."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from pid_reader.tr1 import detector, flags, mapping, store

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures"
TORCH_PY = os.environ.get("PIDLAB_TEST_TORCH_PYTHON", r"C:\PIDWork\venv312_torch\Scripts\python.exe")


def test_every_switch_defaults_to_off_and_unknown_values_are_errors(monkeypatch):
    assert not any(flags.enabled(n) for n in flags.FLAGS)
    monkeypatch.setenv("PIDLAB_SYMBOL_FRCNN_TR1", "on")
    assert flags.enabled("PIDLAB_SYMBOL_FRCNN_TR1") and flags.source("PIDLAB_SYMBOL_FRCNN_TR1") == "environment"
    monkeypatch.setenv("PIDLAB_SYMBOL_FRCNN_TR1", "maybe")
    with pytest.raises(ValueError):
        flags.enabled("PIDLAB_SYMBOL_FRCNN_TR1")
    with pytest.raises(ValueError):
        flags.enabled("PIDLAB_NOT_A_SWITCH")


def test_settings_file_round_trip_and_unreadable_file_means_off():
    assert flags.set_flag("PIDLAB_SYMBOL_CATALOGUE_TR1", True) is True
    assert flags.enabled("PIDLAB_SYMBOL_CATALOGUE_TR1") and flags.source("PIDLAB_SYMBOL_CATALOGUE_TR1") == "settings file"
    flags.settings_path().write_text("{ not json", encoding="utf-8")
    assert not flags.enabled("PIDLAB_SYMBOL_CATALOGUE_TR1")


def test_importing_tr1_never_imports_torch():
    code = ("import sys, pid_reader.tr1.detector, pid_reader.tr1.review, pid_reader.tr1.batch_export, pid_reader.tr1.mapping; "
            "sys.exit(1 if 'torch' in sys.modules or 'torchvision' in sys.modules else 0)")
    r = subprocess.run([sys.executable, "-c", code], env=dict(os.environ, PYTHONPATH=str(ROOT / "src")), capture_output=True)
    assert r.returncode == 0, r.stderr.decode()


def test_off_does_nothing_and_writes_nothing():
    res = detector.detect(FIX / "synthetic_pid_vector.pdf", 1)
    assert res["status"] == "UNAVAILABLE" and res["state"] == "FLAG_OFF" and res["detections"] == []
    assert "template matching" in res["fallback"]
    assert not store.home().exists()


# ----------------------------------------------------------------------------------------------- the runner, with a fake detector script
def _fake_model(tmp_path, monkeypatch):
    d = tmp_path / "models"
    d.mkdir()
    w = d / "T_weights.pt"
    w.write_bytes(b"not real weights")
    card = {"model_id": "fake-1", "producer": "fake", "classes": ["valve", "instrumentation", "general", "arrow"], "threshold": 0.65, "weights_file": "weights.pt",
            "weights_sha256": hashlib.sha256(w.read_bytes()).hexdigest(), "min_size": 800, "max_size": 800, "tile": 800, "overlap": 200, "pdf_render_scale": 2.5,
            "limitations": "fake"}
    (d / "T_MODEL_CARD.json").write_text(json.dumps(card), encoding="utf-8")
    monkeypatch.setenv("PIDLAB_TR1_MODEL_DIR", str(d))
    monkeypatch.setenv("PIDLAB_SYMBOL_FRCNN_TR1", "on")
    monkeypatch.setattr(detector, "locate_python", lambda: sys.executable)
    return card


def _fake_script(tmp_path, monkeypatch, body: str):
    p = tmp_path / "fake_infer.py"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    monkeypatch.setattr(detector, "INFER_SCRIPT", p)


GOOD = """
import hashlib, json, sys
card, weights, pdf = sys.argv[1:4]
out = sys.argv[sys.argv.index("--out") + 1]
card = json.load(open(card))
doc = hashlib.sha256(open(pdf, "rb").read()).hexdigest()
ev = {"producer": "fake", "weights_sha256": card["weights_sha256"], "truth_class": "MODEL_PROPOSAL"}
cands = [{"id": "frc-a", "page": 1, "bbox": {"x0": .1, "y0": .1, "x1": .2, "y1": .2}, "catalogue_class": "valve", "raw_score": .9, "score_kind": "UNCALIBRATED_FRCNN_SOFTMAX",
          "confidence_status": "LEADING", "review_state": "PROPOSED", "evidence": ev},
         {"id": "frc-b", "page": 1, "bbox": {"x0": .5, "y0": .5, "x1": .6, "y1": .55}, "catalogue_class": "general", "raw_score": .3, "score_kind": "UNCALIBRATED_FRCNN_SOFTMAX",
          "confidence_status": "WEAK_CLASS_WITHHELD", "review_state": "PROPOSED", "evidence": ev}]
json.dump({"schema": "tr1-frcnn-candidates-1", "source_sha256": doc, "page": 1, "model": "fake-1", "threshold": .65, "limitations": "fake", "candidates": cands, "diagnostics": {}}, open(out, "w"))
"""


def test_good_run_is_mapped_to_families_and_saved_as_a_sidecar(tmp_path, monkeypatch):
    _fake_model(tmp_path, monkeypatch)
    _fake_script(tmp_path, monkeypatch, GOOD)
    res = detector.detect(FIX / "synthetic_pid_vector.pdf", 1)
    assert res["status"] == "DONE", res
    a, b = res["detections"]
    assert a["suggested_family"] == "VALVE" and a["suggested_class_id"] == "CLS.VALVE.UNKNOWN" and a["review_state"] == "PROPOSED"
    assert b["suggested_family"] == "EQUIPMENT" and b["confidence_status"] == "WEAK_CLASS_WITHHELD"
    side = detector.load_sidecar(res["source_sha256"], 1)
    assert side and len(side["detections"]) == 2
    assert not list((store.home() / "tmp").glob("detect_*"))          # temporary files are removed


@pytest.mark.parametrize("old,new", [
    ('"review_state": "PROPOSED"', '"review_state": "ACCEPTED"'),
    ('"x1": .2', '"x1": 1.7'),
    ('"catalogue_class": "valve"', '"catalogue_class": "pump"'),
    ('"id": "frc-b"', '"id": "frc-a"'),
])
def test_a_result_that_breaks_the_contract_is_refused_not_repaired(tmp_path, monkeypatch, old, new):
    _fake_model(tmp_path, monkeypatch)
    assert old in GOOD
    _fake_script(tmp_path, monkeypatch, GOOD.replace(old, new, 1))
    res = detector.detect(FIX / "synthetic_pid_vector.pdf", 1)
    assert res["status"] == "FAILED" and "refused" in res["message"] and res["detections"] == []
    assert detector.load_sidecar(hashlib.sha256((FIX / "synthetic_pid_vector.pdf").read_bytes()).hexdigest(), 1) is None


def test_a_crashing_detector_is_reported_and_leaves_nothing_behind(tmp_path, monkeypatch):
    _fake_model(tmp_path, monkeypatch)
    _fake_script(tmp_path, monkeypatch, "import sys\nsys.stderr.write('boom: out of memory\\n')\nsys.exit(7)\n")
    res = detector.detect(FIX / "synthetic_pid_vector.pdf", 1)
    assert res["status"] == "FAILED" and "boom" in res["message"] and res["returncode"] == 7
    assert not (store.home() / "detections").exists()


def test_timeout_and_cancel_stop_the_detector(tmp_path, monkeypatch):
    _fake_model(tmp_path, monkeypatch)
    _fake_script(tmp_path, monkeypatch, "import time\ntime.sleep(120)\n")
    t = time.monotonic()
    res = detector.detect(FIX / "synthetic_pid_vector.pdf", 1, timeout_s=2, poll_s=0.1)
    assert res["status"] == "TIMEOUT" and time.monotonic() - t < 30
    res2 = detector.detect(FIX / "synthetic_pid_vector.pdf", 1, cancel=lambda: True, poll_s=0.1)
    assert res2["status"] == "CANCELLED"


def test_missing_model_missing_torch_and_wrong_weights_fall_back_with_a_plain_message(tmp_path, monkeypatch):
    monkeypatch.setenv("PIDLAB_SYMBOL_FRCNN_TR1", "on")
    monkeypatch.setattr(detector, "model_dirs", lambda: [tmp_path / "empty"])
    assert detector.status()["state"] == "NO_MODEL"
    _fake_model(tmp_path, monkeypatch)
    monkeypatch.setattr(detector, "model_dirs", lambda: [tmp_path / "models"])
    monkeypatch.setattr(detector, "locate_python", lambda: None)
    assert detector.status()["state"] == "NO_TORCH_COMPONENT"
    (tmp_path / "models" / "T_weights.pt").write_bytes(b"tampered")
    detector._hash_cache.clear()
    assert detector.status()["state"] == "WEIGHTS_MISMATCH"


def test_mapping_never_invents_an_engineering_class():
    from pid_reader.tr1 import catalogue
    cat = catalogue.catalogue("1.0.0")
    for family, cid in mapping.COARSE_TO_FAMILY.values():
        assert cid is None or cid.endswith(".UNKNOWN")
    assert mapping.enrich({"catalogue_class": "arrow", "id": "x"})["suggested_class_id"] is None
    choices = mapping.class_choices(cat, "valve")
    assert choices[0]["domain"] == "VALVE" and all(c.get("status") != "DEPRECATED" for c in choices)
    assert catalogue.validate(cat) == []


@pytest.mark.skipif(not Path(TORCH_PY).is_file(), reason="optional torch component not installed")
def test_real_detector_runs_on_the_fixture_with_the_shipped_weights(monkeypatch):
    monkeypatch.setenv("PIDLAB_SYMBOL_FRCNN_TR1", "on")
    monkeypatch.setenv("PIDLAB_TR1_PYTHON", TORCH_PY)
    if detector.locate_model() is None:
        pytest.skip("models/ does not hold the E5 card and weights")
    res = detector.detect(FIX / "synthetic_pid_vector.pdf", 1, timeout_s=300)
    assert res["status"] == "DONE", res
    assert res["detections"] and all(d["review_state"] == "PROPOSED" for d in res["detections"])
    assert res["diagnostics"]["torch"].startswith("2.15")
