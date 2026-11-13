"""Resource policy checks with the standard library only (ctypes), so the Reader's core Python needs no extra packages."""
import ctypes
import os
import shutil
import time
from datetime import datetime, timedelta, timezone

PERTH = timezone(timedelta(hours=8))


def perth_date():
    return datetime.now(PERTH).date().isoformat()


class _PowerStatus(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte), ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]


class _MemStatus(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]


def on_battery():
    """True only when Windows reports the machine is running on battery. Unknown or desktop (no battery) is not 'on battery'."""
    if os.name != "nt":
        return False
    s = _PowerStatus()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):
        return False
    return s.ACLineStatus == 0


def free_memory_mb():
    if os.name != "nt":
        return 1 << 20
    m = _MemStatus()
    m.dwLength = ctypes.sizeof(_MemStatus)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullAvailPhys / 2 ** 20


def free_disk_mb(path):
    return shutil.disk_usage(path).free / 2 ** 20


def _kernel32():
    """kernel32 with explicit 64-bit-safe signatures (the default int types truncate process handles)."""
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.SetPriorityClass.restype = wintypes.BOOL
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k.GetExitCodeProcess.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.GetPriorityClass.argtypes = [wintypes.HANDLE]
    k.GetPriorityClass.restype = wintypes.DWORD
    return k


def set_low_priority():
    """BELOW_NORMAL priority class for this process; child processes inherit it, so the user's own work keeps the CPU. Returns True if it took effect."""
    if os.name == "nt":
        k = _kernel32()
        ok = bool(k.SetPriorityClass(k.GetCurrentProcess(), 0x00004000))
        return ok and k.GetPriorityClass(k.GetCurrentProcess()) == 0x00004000
    try:
        os.nice(10)
        return True
    except OSError:
        return False


def boot_time():
    """When this computer last started (epoch seconds), or None if unknown. A runner whose last heartbeat is older than this is from before a restart."""
    try:
        if os.name == "nt":
            k = ctypes.WinDLL("kernel32")
            k.GetTickCount64.restype = ctypes.c_uint64
            return time.time() - k.GetTickCount64() / 1000.0
        with open("/proc/uptime") as f:
            return time.time() - float(f.read().split()[0])
    except (OSError, ValueError, AttributeError):
        return None


def pid_alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        from ctypes import wintypes
        k = _kernel32()
        h = k.OpenProcess(0x1000, False, int(pid))              # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = wintypes.DWORD()
        k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return code.value == 259                                  # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def blocked_reason(cfg, state_dir):
    """None when training may run now, else a short reason. Checked between and during attempts."""
    if cfg.get("require_ac", True) and on_battery():
        return "ON_BATTERY"
    if free_memory_mb() < cfg.get("min_free_memory_mb", 2500):
        return "LOW_FREE_MEMORY"
    if free_disk_mb(state_dir) < cfg.get("min_free_disk_mb", 4000):
        return "LOW_FREE_DISK"
    return None
