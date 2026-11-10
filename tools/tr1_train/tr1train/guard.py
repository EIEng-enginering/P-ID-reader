"""Run one child process under hard limits and make sure its WHOLE process tree is gone afterwards.

Windows: the child is put in a Job Object created with KILL_ON_JOB_CLOSE, so closing the job (or this program dying) ends every process the
child ever started, including grandchildren that were re-parented. ``taskkill /T /F`` is used as a second line. Limits are polled: wall
time, CPU time (job accounting) and the tree's working set. Cancellation is a file whose appearance stops the job.
Other platforms: a new session + ``killpg`` and /proc probes (only so the tool's tests can run elsewhere; the supported platform is Windows 11).

``run_guarded`` never raises for a limit; it returns the state: COMPLETED, FAILED, LIMIT_EXCEEDED or CANCELLED, with the reason, the peak tree
memory, the CPU seconds and the list of processes still alive after the kill (it must be empty).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

from .events import EventLog

STATES = ("COMPLETED", "FAILED", "LIMIT_EXCEEDED", "CANCELLED")


class _Job:
    """Windows Job Object wrapper (ctypes). KILL_ON_JOB_CLOSE makes 'the tree is gone' a property of the operating system, not of our polling."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ct, self.wt = ctypes, wintypes
        k32 = self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        k32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = k32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class IOC(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class EXT(ctypes.Structure):
            _fields_ = [("Basic", BASIC), ("Io", IOC), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        class ACCT(ctypes.Structure):
            _fields_ = [("TotalUserTime", ctypes.c_int64), ("TotalKernelTime", ctypes.c_int64), ("ThisPeriodTotalUserTime", ctypes.c_int64),
                        ("ThisPeriodTotalKernelTime", ctypes.c_int64), ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
                        ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD)]

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [(n, ctypes.c_size_t) for n in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]

        self.EXT, self.ACCT, self.PMC = EXT, ACCT, PMC
        info = EXT()
        info.Basic.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
        self.psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]

    def assign(self, proc: subprocess.Popen) -> None:
        if not self.k32.AssignProcessToJobObject(self.handle, int(proc._handle)):
            raise OSError(self.ct.get_last_error(), "AssignProcessToJobObject failed")

    def pids(self) -> list[int]:
        ct, wt = self.ct, self.wt
        n = 64

        class LIST(ct.Structure):
            _fields_ = [("NumberOfAssignedProcesses", wt.DWORD), ("NumberOfProcessIdsInList", wt.DWORD), ("ProcessIdList", ct.c_size_t * n)]
        buf = LIST()
        if not self.k32.QueryInformationJobObject(self.handle, 3, ct.byref(buf), ct.sizeof(buf), None):
            return []
        return [int(buf.ProcessIdList[i]) for i in range(min(buf.NumberOfProcessIdsInList, n))]

    def cpu_s(self) -> float:
        a = self.ACCT()
        if not self.k32.QueryInformationJobObject(self.handle, 1, self.ct.byref(a), self.ct.sizeof(a), None):
            return 0.0
        return (a.TotalUserTime + a.TotalKernelTime) / 1e7

    def tree_rss_mb(self) -> float:
        total = 0
        for pid in self.pids():
            h = self.k32.OpenProcess(0x1000 | 0x0010, False, pid)      # QUERY_LIMITED_INFORMATION | VM_READ
            if not h:
                continue
            try:
                pmc = self.PMC()
                pmc.cb = self.ct.sizeof(pmc)
                if self.psapi.GetProcessMemoryInfo(h, self.ct.byref(pmc), pmc.cb):
                    total += pmc.WorkingSetSize
            finally:
                self.k32.CloseHandle(h)
        return total / 2 ** 20

    def peak_job_mb(self) -> float:
        info = self.EXT()
        if self.k32.QueryInformationJobObject(self.handle, 9, self.ct.byref(info), self.ct.sizeof(info), None):
            return info.PeakJobMemoryUsed / 2 ** 20
        return 0.0

    def close(self) -> None:
        if self.handle:
            self.k32.CloseHandle(self.handle)         # KILL_ON_JOB_CLOSE ends everything still in the job
            self.handle = None


def _posix_tree(pid: int) -> list[int]:
    kids: dict[int, list[int]] = {}
    if not os.path.isdir("/proc"):
        return [pid]
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                kids.setdefault(int(open(f"/proc/{d}/stat").read().rsplit(")", 1)[1].split()[1]), []).append(int(d))
            except OSError:
                pass
    out, todo = [], [pid]
    while todo:
        p = todo.pop()
        if os.path.exists(f"/proc/{p}"):
            out.append(p)
        todo += kids.get(p, [])
    return out


def _posix_rss_mb(pid: int) -> float:
    tot = 0.0
    for p in _posix_tree(pid):
        try:
            for line in open(f"/proc/{p}/status"):
                if line.startswith("VmRSS:"):
                    tot += int(line.split()[1]) / 1024
        except OSError:
            pass
    return tot


def run_guarded(cmd: list[str], *, max_wall_s: float, max_cpu_s: float | None = None, max_rss_mb: float | None = None, cwd: str | None = None,
                env: dict | None = None, cancel_file: str | None = None, stdout_path: str | None = None, stderr_path: str | None = None,
                events: EventLog | None = None, poll_s: float = 0.25) -> dict:
    out = open(stdout_path, "ab") if stdout_path else subprocess.DEVNULL
    err = open(stderr_path, "ab") if stderr_path else subprocess.DEVNULL
    nt = os.name == "nt"
    job = _Job() if nt else None
    kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW} if nt else {"start_new_session": True}
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=out, stderr=err, **kw)
    state, why, peak = None, None, 0.0
    try:
        if job:
            job.assign(proc)
        if events:
            events.add("RUNNING", pid=proc.pid)
        while proc.poll() is None:
            el = time.monotonic() - t0
            rss = job.tree_rss_mb() if job else _posix_rss_mb(proc.pid)
            peak = max(peak, rss)
            cpu = job.cpu_s() if job else None
            if cancel_file and os.path.exists(cancel_file):
                state, why = "CANCELLED", "cancel requested"
            elif el > max_wall_s:
                state, why = "LIMIT_EXCEEDED", f"wall {el:.1f}s > {max_wall_s}"
            elif max_cpu_s and cpu is not None and cpu > max_cpu_s:
                state, why = "LIMIT_EXCEEDED", f"cpu {cpu:.1f}s > {max_cpu_s}"
            elif max_rss_mb and rss > max_rss_mb:
                state, why = "LIMIT_EXCEEDED", f"rss {rss:.0f}MB > {max_rss_mb}"
            if state:
                break
            time.sleep(poll_s)
        leftover: list[int] = []
        if state:
            if nt:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                deadline = time.monotonic() + 15
                while job.pids() and time.monotonic() < deadline:
                    time.sleep(0.1)
                if job.pids():                       # taskkill missed something (re-parented grandchild): closing the job kills it
                    job.close()
                    time.sleep(0.5)
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
        if job and job.handle:
            peak = max(peak, job.peak_job_mb())
            cpu_final = job.cpu_s()
            leftover = job.pids()
        else:
            cpu_final = None
            leftover = [] if nt else [p for p in _posix_tree(proc.pid) if p != proc.pid]
        if state is None:
            state = "COMPLETED" if proc.returncode == 0 else "FAILED"
        res = {"state": state, "reason": why, "returncode": proc.returncode, "wall_s": round(time.monotonic() - t0, 2),
               "peak_tree_rss_mb": round(peak, 1), "cpu_s": None if cpu_final is None else round(cpu_final, 2), "processes_left_after_kill": leftover}
        if events:
            events.add(state, **{k: v for k, v in res.items() if k != "state"})
        return res
    finally:
        if job:
            job.close()
        for f in (out, err):
            if f is not subprocess.DEVNULL:
                f.close()
