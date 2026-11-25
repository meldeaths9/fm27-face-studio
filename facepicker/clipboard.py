"""윈도우 클립보드에 '파일(탐색기에서 복사한 것과 같은 형식)'과 '글자'를 함께 넣는다.

웹 AI 입력칸에 Ctrl+V 한 번으로 참고 사진과 프롬프트가 같이 들어가게 하려는 용도.
"""
from __future__ import annotations

import ctypes
import struct
import sys
import time
from pathlib import Path

CF_UNICODETEXT = 13
CF_HDROP = 15
GMEM_MOVEABLE = 0x0002


def _api():
    from ctypes import wintypes
    k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
    k32.GlobalAlloc.restype = wintypes.HGLOBAL
    k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    u32.OpenClipboard.argtypes = [wintypes.HWND]
    u32.SetClipboardData.restype = wintypes.HANDLE
    u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    u32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    u32.RegisterClipboardFormatW.restype = wintypes.UINT
    return k32, u32


def _global(k32, data: bytes):
    h = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not h:
        raise OSError("메모리 할당 실패")
    p = k32.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    k32.GlobalUnlock(h)
    return h


def set_files_and_text(paths: list[str | Path], text: str = "") -> bool:
    """성공하면 True. 윈도우가 아니면 False."""
    if sys.platform != "win32":
        return False
    k32, u32 = _api()
    # DROPFILES { DWORD pFiles; POINT pt; BOOL fNC; BOOL fWide; } + 파일 목록(UTF-16, 이중 NUL로 끝)
    files = "".join(str(Path(p).resolve()) + "\0" for p in paths) + "\0"
    hdrop = struct.pack("<IiiII", 20, 0, 0, 0, 1) + files.encode("utf-16-le")
    for _ in range(10):
        if u32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise OSError("다른 프로그램이 클립보드를 쓰고 있어요. 잠시 뒤 다시 눌러 주세요.")
    try:
        u32.EmptyClipboard()
        if paths:
            u32.SetClipboardData(CF_HDROP, _global(k32, hdrop))
            effect = u32.RegisterClipboardFormatW("Preferred DropEffect")
            u32.SetClipboardData(effect, _global(k32, struct.pack("<I", 1)))   # 복사
        if text:
            u32.SetClipboardData(CF_UNICODETEXT, _global(k32, (text + "\0").encode("utf-16-le")))
    finally:
        u32.CloseClipboard()
    return True
