"""Run the PDF reader in a separate, resource-limited child process.

Protects the application (and a batch run) from hostile or pathological PDFs:

* wall-clock timeout and cooperative cancel, enforced by killing the process tree;
* Windows: a Job Object with a per-process memory cap, kill-on-close and a
  kill-on-close so the whole process tree dies with the job (venv launchers spawn a child, so no process-count cap);
* POSIX: ``RLIMIT_AS`` memory cap for the child;
* private scratch directory created and removed by the parent.

The child is the frozen-contract worker (``pid_reader.worker``), so the result is
the same canonical R1 JSON the Worksheet host would receive.
It is a bounded-resource wrapper, not a security sandbox: the child keeps the
user's file permissions, and no malicious-PDF resilience guarantee is made.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

from ..api import (Cancelled, LimitExceeded, ReadParams, RefusedInput, canonical_json,
                   sha256_hex, result_sha256)

DEFAULT_TIMEOUT_S = 180
DEFAULT_MEMORY_MB = 2048
EXIT_OK, EXIT_REFUSED, EXIT_LIMIT, EXIT_INTERNAL, EXIT_CANCELLED = 0, 2, 3, 4, 5


class WorkerTimeout(LimitExceeded):
    pass


# ---------------------------------------------------------------- Windows job
class _Job:
    """Minimal Windows Job Object wrapper (ctypes, no third-party dependency)."""

    def __init__(self, memory_mb: int, single_process: bool = False):
        import ctypes
        from ctypes import wintypes
        self._k = ctypes.WinDLL("kernel32", use_last_error=True)
        k = self._k
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k.CloseHandle.argtypes = [wintypes.HANDLE]

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOps", "WriteOps", "OtherOps",
                                                      "ReadBytes", "WriteBytes", "OtherBytes")]

        class EXT(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        self.handle = k.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x8
        JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x100
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        info = EXT()
        flags = JOB_OBJECT_LIMIT_PROCESS_MEMORY | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if single_process:
            flags |= JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            info.BasicLimitInformation.ActiveProcessLimit = 1
        info.BasicLimitInformation.LimitFlags = flags
        info.ProcessMemoryLimit = memory_mb * 1024 * 1024
        if not k.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            err = ctypes.get_last_error()
            k.CloseHandle(self.handle)
            raise OSError(err, "SetInformationJobObject failed")

    def assign(self, process: subprocess.Popen) -> None:
        import ctypes
        if not self._k.AssignProcessToJobObject(self.handle, int(process._handle)):  # noqa: SLF001
            raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")

    def terminate(self) -> None:
        self._k.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        if self.handle:
            self._k.CloseHandle(self.handle)
            self.handle = None


def _package_parent() -> str:
    return str(Path(__file__).resolve().parents[2])


def _worker_command(input_path: Path, params_path: Path, output_path: Path, workdir: Path,
                    filename: str, expected_sha256: str) -> tuple[list[str], dict]:
    args = ["run", "--input", str(input_path), "--params", str(params_path), "--output", str(output_path),
            "--workdir", str(workdir), "--filename", filename, "--expected-sha256", expected_sha256]
    env = dict(os.environ)
    if getattr(sys, "frozen", False):
        return [sys.executable, "--pid-worker", *args], env
    env["PYTHONPATH"] = _package_parent()
    env["PYTHONIOENCODING"] = "utf-8"
    return [sys.executable, "-X", "utf8", "-m", "pid_reader.worker", *args], env


def run_limited(cmd: list[str], *, env: dict, cwd: str, timeout_s: int, memory_mb: int,
                should_cancel: Callable[[], bool] | None = None) -> tuple[int, str, str]:
    """Run ``cmd`` under the platform memory cap. Returns (exit code, stderr text, reason).

    ``reason`` is ``""`` for a normal exit, ``"timeout"`` or ``"cancel"`` when killed.
    """
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    preexec = None
    if os.name != "nt":  # pragma: no cover - exercised on POSIX only
        def preexec():
            import resource
            limit = memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    proc = subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, creationflags=creationflags,
                            preexec_fn=preexec, cwd=cwd)
    job = None
    if os.name == "nt":
        try:
            job = _Job(memory_mb)
            job.assign(proc)
        except OSError:
            # Already inside a non-nestable job. Fall back to process-kill only; the
            # memory cap is then NOT enforced (memory_cap_enforced() reports this).
            if job:
                job.close()
            job = None
    started = time.monotonic()
    reason = ""
    stderr = ""
    try:
        while True:
            try:
                proc.wait(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                pass
            if should_cancel is not None and should_cancel():
                reason = "cancel"
            elif time.monotonic() - started > timeout_s:
                reason = "timeout"
            if reason:
                if job is not None:
                    job.terminate()
                proc.kill()
                proc.wait()
                break
        stderr = (proc.stderr.read() or b"").decode("utf-8", "replace") if proc.stderr else ""
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if proc.stderr:
            proc.stderr.close()
        if job is not None:
            job.close()
    return proc.returncode, stderr, reason


def read_pid_isolated(pdf_bytes: bytes, params: ReadParams, *, filename: str = "",
                      expected_sha256: str = "", timeout_s: int = DEFAULT_TIMEOUT_S,
                      memory_mb: int = DEFAULT_MEMORY_MB,
                      should_cancel: Callable[[], bool] | None = None,
                      scratch_root: str | Path | None = None) -> dict:
    """Return the validated R1 result produced by a resource-limited child process.

    Raises RefusedInput / LimitExceeded / Cancelled exactly as ``read_pid`` would
    and :class:`WorkerTimeout` (a LimitExceeded, code ``PID_TIMEOUT``).
    """
    params.validate()
    if not isinstance(timeout_s, int) or not 1 <= timeout_s <= 3600:
        raise ValueError("timeout_s must be 1..3600")
    if not isinstance(memory_mb, int) or not 256 <= memory_mb <= 65536:
        raise ValueError("memory_mb must be 256..65536")
    root = tempfile.mkdtemp(prefix="pidreader-", dir=str(scratch_root) if scratch_root else None)
    try:
        base = Path(root)
        workdir = base / "work"
        outdir = base / "out"
        workdir.mkdir()
        outdir.mkdir()
        input_path = base / "input.pdf"
        input_path.write_bytes(pdf_bytes)
        params_path = base / "params.json"
        params_path.write_text(canonical_json(params.as_dict()), encoding="utf-8")
        output_path = outdir / "result.json"
        cmd, env = _worker_command(input_path, params_path, output_path, workdir, filename, expected_sha256)
        code, stderr, reason = run_limited(cmd, env=env, cwd=str(base), timeout_s=timeout_s,
                                           memory_mb=memory_mb, should_cancel=should_cancel)
        if reason == "cancel":
            raise Cancelled()
        if reason == "timeout":
            raise WorkerTimeout("PID_TIMEOUT", f"Reader exceeded the {timeout_s}s time limit.")
        event = {}
        for line in reversed(stderr.strip().splitlines()):
            try:
                event = json.loads(line)
                break
            except ValueError:
                continue
        if code == EXIT_OK:
            data = output_path.read_bytes()
            result = json.loads(data.decode("utf-8"))
            if canonical_json(result).encode("utf-8") != data:
                raise RefusedInput("PID_MALFORMED", "Worker output is not canonical JSON.")
            return result
        if code == EXIT_LIMIT:
            raise LimitExceeded(event.get("code", "PID_LIMIT"), "Reader limit exceeded.")
        if code == EXIT_REFUSED:
            raise RefusedInput(event.get("code", "PID_MALFORMED"), "Reader refused the input.")
        if code == EXIT_CANCELLED:
            raise Cancelled()
        raise LimitExceeded("PID_WORKER_FAILED",
                            f"Reader process ended abnormally (exit {code}); the input may exceed memory limits.")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def memory_cap_enforced() -> bool:
    """True when this platform can apply the per-process memory cap."""
    if os.name != "nt":
        return True
    try:
        job = _Job(DEFAULT_MEMORY_MB)
        job.close()
        return True
    except OSError:
        return False
