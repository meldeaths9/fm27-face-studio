"""메모리 사용량 기록 (최적화용). 작업 관리자의 '메모리' 칸과 같은 값(전용 작업 집합)에 가깝게."""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time

log = logging.getLogger("mem")


def rss_mb() -> float:
    if sys.platform == "win32":
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                        ("PrivateUsage", ctypes.c_size_t)]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        k32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            return pmc.PrivateUsage / 1048576
        return 0.0
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


def ws_mb() -> float:
    """작업 집합(작업 관리자 숫자에 가까움)."""
    if sys.platform != "win32":
        return rss_mb()
    try:
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t)] + \
                       [(n, ctypes.c_size_t) for n in ("a", "b", "c", "d", "e", "f", "g")]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        k32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            return pmc.WorkingSetSize / 1048576
    except Exception:  # noqa: BLE001
        pass
    return 0.0


def mark(tag: str) -> float:
    v = rss_mb()
    log.info("메모리 %s: 전용 %.0fMB · 작업 집합 %.0fMB", tag, v, ws_mb())
    return v


def trim() -> None:
    """파이썬이 쥐고 있는 빈 메모리를 윈도우에 돌려준다."""
    import gc
    gc.collect()
    if sys.platform == "win32":
        try:
            from ctypes import wintypes
            k32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
            psapi.EmptyWorkingSet(k32.GetCurrentProcess())
            # 파이썬 C 메모리 더미에 남은 빈 공간도 돌려준다
            ctypes.CDLL("msvcrt")._heapmin()
        except Exception:  # noqa: BLE001
            pass


def start_watch(every: int = 300) -> None:
    def run():
        while True:
            time.sleep(every)
            mark("주기")
    threading.Thread(target=run, daemon=True, name="memwatch").start()
