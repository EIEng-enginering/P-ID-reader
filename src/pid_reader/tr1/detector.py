"""App-side runner for the learned symbol detector (switch PIDLAB_SYMBOL_FRCNN_TR1, default OFF).

The detector itself (``infer_cli.py``) needs torch, which is a large OPTIONAL component. This module never imports torch: it starts the detector
as a separate process with the torch component's Python, with a timeout, cancellation and a whole-process-tree kill. If anything is missing
(switch off, no torch component, no model, weights that do not match the model card, a failed run) the result says exactly why and the
normal analysis is not touched; the existing template-matching (NCC) path never depends on this module.

Detections are PROPOSED. They are validated, mapped to catalogue *families* (``mapping``) and written to a sidecar file under the TR1 home
(``store``). Nothing is written to the standalone database, the package manifest or any Worksheet R1 output.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import flags, mapping, store

SWITCH = "PIDLAB_SYMBOL_FRCNN_TR1"
SCHEMA_IN = "tr1-frcnn-candidates-1"
SCHEMA_OUT = "pid-tr1-detections/1"
INFER_SCRIPT = Path(__file__).with_name("infer_cli.py")
REQUIRED_MODULES = ("torch", "torchvision", "pypdfium2", "PIL", "numpy")
DEFAULT_TIMEOUT_S = 900
_STATES = ("FLAG_OFF", "READY", "NO_TORCH_COMPONENT", "NO_MODEL", "WEIGHTS_MISMATCH", "CARD_INVALID")
_hash_cache: dict[tuple, str] = {}


# ----------------------------------------------------------------------------------------------------------------------------- locating
def model_dirs() -> list[Path]:
    dirs = []
    if os.environ.get("PIDLAB_TR1_MODEL_DIR"):
        dirs.append(Path(os.environ["PIDLAB_TR1_MODEL_DIR"]))
    dirs.append(store.home() / "models")
    dirs.append(Path(__file__).resolve().parents[3] / "models")                  # source checkout: <project>/models
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(Path(meipass) / "models")
    return dirs


def locate_model() -> tuple[Path, Path] | None:
    """(card, weights) of the first complete model found, else None. The card names the weights file; ``E5_`` + that name is also accepted."""
    for d in model_dirs():
        for card in sorted(d.glob("*_MODEL_CARD.json")) if d.is_dir() else []:
            data = store.read_json(card)
            wf = data.get("weights_file") if isinstance(data, dict) else None
            if not wf:
                continue
            for name in (wf, card.name.split("_MODEL_CARD")[0] + "_" + wf):
                if (d / name).is_file():
                    return card, d / name
    return None


def _python_ok(python: str) -> bool:
    code = "import importlib.util as u,sys;sys.exit(0 if all(u.find_spec(m) for m in %r) else 1)" % (REQUIRED_MODULES,)
    try:
        return subprocess.run([python, "-I", "-c", code], capture_output=True, timeout=30, creationflags=_nowin()).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def locate_python() -> str | None:
    """Interpreter of the torch component: PIDLAB_TR1_PYTHON, then <TR1 home>/torch_env, then this interpreter if it happens to have torch."""
    cands = []
    if os.environ.get("PIDLAB_TR1_PYTHON"):
        cands.append(os.environ["PIDLAB_TR1_PYTHON"])
    cands.append(str(store.home() / "torch_env" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")))
    if not getattr(sys, "frozen", False):
        cands.append(sys.executable)
    for c in cands:
        if Path(c).is_file() and _python_ok(c):
            return c
    return None


def _nowin() -> int:
    return (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0


def _sha256(path: Path) -> str:
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns)
    if key not in _hash_cache:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _hash_cache[key] = h.hexdigest()
    return _hash_cache[key]


# ------------------------------------------------------------------------------------------------------------------------------- status
def status(explicit_flag=None, *, verify_weights: bool = True) -> dict:
    """Why the detector can or cannot run, in plain words. ``state`` is one of FLAG_OFF, READY, NO_TORCH_COMPONENT, NO_MODEL, WEIGHTS_MISMATCH, CARD_INVALID."""
    on = flags.enabled(SWITCH, explicit_flag)
    out = {"switch": SWITCH, "enabled": on, "state": "FLAG_OFF", "fallback": "template matching (NCC) is used for the normal analysis in every case",
           "message": "The learned detector is switched off. Nothing else is affected.", "python": None, "card": None, "weights": None}
    if not on:
        return out
    model = locate_model()
    if model is None:
        out.update(state="NO_MODEL", message="No model card with its weights file was found (looked in: " + "; ".join(str(d) for d in model_dirs()) + "). "
                   "Analysis continues with template matching only.")
        return out
    card_path, weights_path = model
    card = store.read_json(card_path)
    out.update(card=str(card_path), weights=str(weights_path))
    need = ("model_id", "producer", "classes", "threshold", "weights_file", "weights_sha256", "min_size", "max_size", "tile", "overlap", "pdf_render_scale", "limitations")
    if not isinstance(card, dict) or [k for k in need if k not in card] or not re.fullmatch(r"[0-9a-f]{64}", str(card.get("weights_sha256"))):
        out.update(state="CARD_INVALID", message="The model card is unreadable or incomplete. Analysis continues with template matching only.")
        return out
    out["model"] = {k: card[k] for k in ("model_id", "producer", "classes", "threshold", "weights_sha256")}
    if verify_weights and _sha256(weights_path) != card["weights_sha256"]:
        out.update(state="WEIGHTS_MISMATCH", message="The weights file does not match the model card's sha256, so it will not be loaded. "
                   "Analysis continues with template matching only.")
        return out
    if not INFER_SCRIPT.is_file():
        out.update(state="NO_TORCH_COMPONENT", message="The detector script (tr1/infer_cli.py) is not present in this installation, so the learned detector cannot run. "
                   "Analysis continues with template matching only.")
        return out
    py = locate_python()
    if py is None:
        out.update(state="NO_TORCH_COMPONENT", message="The optional torch component is not installed (needs torch, torchvision, pypdfium2, Pillow and numpy in an "
                   "interpreter named by PIDLAB_TR1_PYTHON or installed under the TR1 home). Analysis continues with template matching only.")
        return out
    out.update(state="READY", python=py, message="Learned detector ready. Detections are proposals that need an engineer's confirmation.")
    return out


# ------------------------------------------------------------------------------------------------------------------------------ running
def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        import signal
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()


def validate_result(result: dict, card: dict, *, source_sha256: str, page: int) -> list[str]:
    """Problems found in a detector result; an empty list means it may be shown. Anything wrong is refused, not repaired."""
    bad = []
    if result.get("schema") != SCHEMA_IN:
        bad.append("SCHEMA")
    if result.get("source_sha256") != source_sha256:
        bad.append("SOURCE_SHA_MISMATCH")
    if result.get("page") != page:
        bad.append("PAGE_MISMATCH")
    if result.get("model") != card.get("model_id"):
        bad.append("MODEL_MISMATCH")
    seen = set()
    for c in result.get("candidates", []):
        b = c.get("bbox") or {}
        try:
            ok = all(0.0 <= b[k] <= 1.0 for k in ("x0", "y0", "x1", "y1")) and b["x0"] < b["x1"] and b["y0"] < b["y1"]
        except (KeyError, TypeError):
            ok = False
        if not ok:
            bad.append("BBOX:" + str(c.get("id")))
        if c.get("catalogue_class") not in card["classes"]:
            bad.append("CLASS:" + str(c.get("id")))
        if c.get("review_state") != "PROPOSED":
            bad.append("NOT_PROPOSED:" + str(c.get("id")))
        if c.get("confidence_status") not in ("LEADING", "WEAK_CLASS_WITHHELD"):
            bad.append("STATUS:" + str(c.get("id")))
        if c.get("id") in seen:
            bad.append("DUPLICATE_ID:" + str(c.get("id")))
        seen.add(c.get("id"))
        if (c.get("evidence") or {}).get("weights_sha256") != card["weights_sha256"]:
            bad.append("WEIGHTS_SHA:" + str(c.get("id")))
    return bad[:50]


def detect(pdf_path: str | os.PathLike, page: int = 1, *, timeout_s: float | None = None, cancel=None, explicit_flag=None, write_sidecar: bool = True,
           threads: int | None = None, poll_s: float = 0.2) -> dict:
    """Run the learned detector on one page and return ``{"status": ..., "state": ..., "message": ..., "detections": [...]}``.

    ``status`` is DONE, UNAVAILABLE (see ``state``/``message``; the caller carries on with the normal analysis), CANCELLED, TIMEOUT or FAILED.
    A failed or refused run never leaves a sidecar behind and never changes anything else.
    """
    st = status(explicit_flag)
    if st["state"] != "READY":
        return {"status": "UNAVAILABLE", "state": st["state"], "message": st["message"], "detections": [], "fallback": st["fallback"]}
    pdf_path = Path(pdf_path)
    card_path, weights_path = Path(st["card"]), Path(st["weights"])
    card = store.read_json(card_path)
    source_sha = _sha256(pdf_path)
    timeout = float(timeout_s if timeout_s is not None else os.environ.get("PIDLAB_TR1_TIMEOUT_S", DEFAULT_TIMEOUT_S))
    tmp_out = store.home() / "tmp" / f"detect_{os.getpid()}_{int(time.time() * 1000)}.json"
    tmp_out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [st["python"], "-B", "-I", str(INFER_SCRIPT), str(card_path), str(weights_path), str(pdf_path), "--page", str(int(page)), "--out", str(tmp_out)]
    if threads:
        cmd += ["--threads", str(int(threads))]
    kw = {"creationflags": _nowin()} if os.name == "nt" else {"start_new_session": True}
    t0 = time.monotonic()
    err_path = tmp_out.with_suffix(".err")
    with open(err_path, "w", encoding="utf-8", errors="replace") as err:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=err, **kw)
        final = None
        while proc.poll() is None:
            if cancel is not None and cancel():
                final = ("CANCELLED", "Cancelled; the detector process was stopped.")
            elif time.monotonic() - t0 > timeout:
                final = ("TIMEOUT", f"The detector did not finish within {timeout:.0f} s and was stopped.")
            if final:
                kill_tree(proc)
                break
            time.sleep(poll_s)
    wall = round(time.monotonic() - t0, 2)
    try:
        if final:
            return {"status": final[0], "state": "READY", "message": final[1], "detections": [], "wall_s": wall}
        if proc.returncode != 0:
            tail = err_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-3:]
            return {"status": "FAILED", "state": "READY", "message": "The detector process failed: " + " | ".join(tail)[:600], "detections": [], "wall_s": wall,
                    "returncode": proc.returncode}
        result = store.read_json(tmp_out)
        if not isinstance(result, dict):
            return {"status": "FAILED", "state": "READY", "message": "The detector produced no readable result.", "detections": [], "wall_s": wall}
        problems = validate_result(result, card, source_sha256=source_sha, page=int(page))
        if problems:
            return {"status": "FAILED", "state": "READY", "message": "The detector result was refused: " + ", ".join(problems[:5]), "detections": [], "wall_s": wall}
        dets = [mapping.enrich(c) for c in result["candidates"]]
        record = {"schema": SCHEMA_OUT, "source_sha256": source_sha, "page": int(page), "source_name": pdf_path.name, "model": card["model_id"],
                  "weights_sha256": card["weights_sha256"], "threshold": card["threshold"], "limitations": card["limitations"], "diagnostics": result.get("diagnostics", {}),
                  "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "detections": dets}
        if write_sidecar:
            store.write_json_atomic(store.detection_path(source_sha, int(page)), record)
        return {"status": "DONE", "state": "READY", "message": f"{len(dets)} proposed detection(s) in {wall:.1f} s (not verified).", "detections": dets, "wall_s": wall,
                "diagnostics": result.get("diagnostics", {}), "source_sha256": source_sha, "record": record}
    finally:
        for p in (tmp_out, err_path):
            try:
                p.unlink()
            except OSError:
                pass


def load_sidecar(source_sha256: str, page: int) -> dict | None:
    """Detections saved by a previous run, or None. Reading never needs torch and works with the switch off (it only reads a file)."""
    rec = store.read_json(store.detection_path(source_sha256, page))
    return rec if isinstance(rec, dict) and rec.get("schema") == SCHEMA_OUT else None
