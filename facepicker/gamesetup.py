"""FM27 게임 폴더 찾기, BepInEx·플러그인 설치, 플러그인과 통신.

- BepInEx는 버전이 많아 이 프로그램이 설치하지 않는다. 사용자가 먼저 설치하고, 우리는 플러그인만 넣는다.
- Program Files 아래는 쓰기 권한이 없으니 관리자 권한으로 이 exe를 다시 실행해서 설치한다.
- 플러그인과는 %APPDATA%\\FM27FacePicker\\plugin 의 JSON 파일로 주고받는다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from .pack import fm_running
from .settings import app_data_dir

log = logging.getLogger("gamesetup")
BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
PLUGIN_DLL = BASE / "plugin_dist" / "FM27FaceStudio.dll"
STEAM_APP_ID = "4530370"   # Football Manager 27
PLUGIN_FOLDER = "FM27FaceStudio"
BEPINEX_URL = "https://builds.bepinex.dev/projects/bepinex_be"
BEPINEX_HELP = ("BepInEx가 설치되어 있지 않아요. BepInEx 6 (Unity IL2CPP, win-x64, be.793 이상)를 먼저 "
                "FM27 설치 폴더(fm.exe가 있는 곳)에 설치하고, 게임을 한 번 켰다 끈 뒤 다시 시도해 주세요.")


# ------------------------------------------------------------------ 게임 폴더
def _steam_roots() -> list[Path]:
    roots: list[Path] = []
    if sys.platform == "win32":
        try:
            import winreg
            for hive, key, val in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                                   (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                                   (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        roots.append(Path(winreg.QueryValueEx(k, val)[0]))
                except OSError:
                    pass
        except ImportError:
            pass
    roots.append(Path(r"C:\Program Files (x86)\Steam"))
    libs: list[Path] = []
    for r in roots:
        vdf = r / "steamapps" / "libraryfolders.vdf"
        libs.append(r)
        try:
            for m in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="ignore")):
                libs.append(Path(m.group(1).replace("\\\\", "\\")))
        except OSError:
            pass
    out, seen = [], set()
    for p in libs:
        k = str(p).lower()
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def valid_game(path: str | Path | None) -> bool:
    """FM27 설치 폴더인지: fm.exe, 또는 (게임패스 등 exe 이름이 다를 때) GameAssembly.dll + exe."""
    if not path:
        return False
    p = Path(path)
    if (p / "fm.exe").exists():
        return True
    try:
        return (p / "GameAssembly.dll").exists() and any(x.suffix.lower() == ".exe" for x in p.iterdir())
    except OSError:
        return False


def normalize_game_dir(path: str) -> str:
    """사용자가 고른 폴더가 한 단계 위(게임패스의 'Football Manager 27')여도 Content 를 찾아 준다."""
    p = Path(path)
    for c in (p, p / "Content", p / "content"):
        if valid_game(c):
            return str(c)
    return ""


def _gamepass_dirs() -> list[Path]:
    out = []
    if sys.platform != "win32":
        return out
    import string
    for d in string.ascii_uppercase:
        root = Path(f"{d}:\\")
        for base in (root / "XboxGames", root / "Program Files" / "ModifiableWindowsApps"):
            try:
                if not base.is_dir():
                    continue
                for g in base.iterdir():
                    n = g.name.lower()
                    if "football manager" in n and ("27" in n or "2027" in n):
                        out += [g / "Content", g]
            except OSError:
                continue
    return out


def _epic_dirs() -> list[Path]:
    """에픽 게임즈 런처의 설치 기록(*.item, JSON)에서 FM27 위치."""
    out = []
    pd = os.environ.get("ProgramData") or r"C:\ProgramData"
    man = Path(pd) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    try:
        for f in man.glob("*.item"):
            try:
                d = json.loads(f.read_text(encoding="utf-8", errors="ignore"))
            except (OSError, ValueError):
                continue
            name = str(d.get("DisplayName", "")).lower()
            if "football manager" in name and ("27" in name or "2027" in name) and d.get("InstallLocation"):
                out.append(Path(d["InstallLocation"]))
    except OSError:
        pass
    return out


def find_game(saved: str = "") -> str:
    if valid_game(saved):
        return str(saved)
    for lib in _steam_roots():
        p = lib / "steamapps" / "common" / "Football Manager 27"
        if valid_game(p):
            return str(p)
    for p in _epic_dirs():              # 에픽 게임즈
        if valid_game(p):
            return str(p)
    for p in _gamepass_dirs():          # Xbox 앱 / PC 게임패스
        if valid_game(p):
            return str(p)
    return ""


# ------------------------------------------------------------------ 상태
_MD5: dict = {}


def _md5(path: Path) -> str:
    try:
        st = path.stat()
        key = (str(path), st.st_size, st.st_mtime_ns)
        if key not in _MD5:
            _MD5[key] = hashlib.md5(path.read_bytes()).hexdigest()
        return _MD5[key]
    except OSError:
        return ""


_VER: dict = {}


def dll_version(path: Path) -> str:
    """플러그인 dll의 BepInPlugin 버전 (속성 데이터에서 이름 다음 문자열)."""
    try:
        st = path.stat()
        key = (str(path), st.st_size, st.st_mtime_ns)
        if key not in _VER:
            b = path.read_bytes()
            i = b.find(b"\x0eFM Face Studio")
            v = ""
            if i >= 0:
                n = b[i + 15]
                v = b[i + 16:i + 16 + n].decode("ascii", "ignore") if n < 20 else ""
            _VER[key] = v
        return _VER[key]
    except (OSError, IndexError):
        return ""


_RUN = {"t": 0.0, "v": False}


def _fm_running_cached(alive: bool) -> bool:
    """tasklist를 3초마다 띄우지 않게: 플러그인이 살아 있으면 켜져 있는 것, 아니면 10초 캐시."""
    if alive:
        return True
    now = time.time()
    if now - _RUN["t"] > 10:
        _RUN["v"], _RUN["t"] = fm_running(), now
    return _RUN["v"]


def bridge_dir() -> Path:
    d = app_data_dir() / "plugin"
    d.mkdir(exist_ok=True)
    return d


def heartbeat() -> dict | None:
    """플러그인이 2초마다 쓰는 상태. 6초 안에 갱신됐으면 연결된 것."""
    try:
        data = json.loads((bridge_dir() / "status.json").read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    data["alive"] = (time.time() - float(data.get("time", 0))) < 6.5
    return data


_PROXIES = ("winhttp.dll", "version.dll", "winmm.dll", "dxgi.dll", "dinput8.dll", "d3d11.dll")


def has_bepinex(g: Path) -> bool:
    """BepInEx(IL2CPP)가 깔려 있는지. 게임패스 등은 winhttp.dll 대신 다른 이름의 로더를 쓰기도 해서
    core dll + (로더 dll 하나 또는 doorstop 설정 또는 이미 돈 흔적) 이면 깔린 것으로 본다."""
    core = g / "BepInEx" / "core" / "BepInEx.Unity.IL2CPP.dll"
    if not core.exists():
        return False
    return (any((g / n).exists() for n in _PROXIES) or (g / "doorstop_config.ini").exists()
            or (g / "BepInEx" / "LogOutput.log").exists() or (g / "BepInEx" / "interop").is_dir())


def status(game_dir: str) -> dict:
    g = Path(game_dir) if game_dir else None
    ok_game = valid_game(g)
    has_loader = ok_game and has_bepinex(g)
    initialized = ok_game and (g / "BepInEx" / "interop").is_dir() and any((g / "BepInEx" / "interop").glob("*.dll"))
    installed_dll = (g / "BepInEx" / "plugins" / PLUGIN_FOLDER / "FM27FaceStudio.dll") if ok_game else None
    installed = bool(installed_dll and installed_dll.exists())
    up_to_date = installed and PLUGIN_DLL.exists() and _md5(installed_dll) == _md5(PLUGIN_DLL)
    hb = heartbeat()
    return {
        "game_dir": str(g) if ok_game else "",
        "game_found": ok_game,
        "running": _fm_running_cached(bool(hb and hb.get("alive"))),
        "bepinex": bool(has_loader),
        "bepinex_ready": bool(initialized),
        "plugin_installed": installed,
        "plugin_up_to_date": bool(up_to_date),
        "plugin_file_version": dll_version(installed_dll) if installed else "",
        "plugin_available": PLUGIN_DLL.exists(),
        "connected": bool(hb and hb.get("alive")),
        "heartbeat": hb or {},
    }


# ------------------------------------------------------------------ 설치
def writable(folder: Path) -> bool:
    test = folder / f".fs_write_test_{uuid.uuid4().hex[:6]}"
    try:
        test.write_text("x")
        test.unlink()
        return True
    except OSError:
        return False


def install(game_dir: str) -> list[str]:
    """실제 설치 (이 프로세스에 쓰기 권한이 있어야 함). 한 일을 문장 목록으로 돌려준다."""
    g = Path(game_dir)
    if not valid_game(g):
        raise RuntimeError("FM27 게임 폴더가 아니에요 (fm.exe가 없음).")
    done: list[str] = []
    if not has_bepinex(g):
        raise RuntimeError(BEPINEX_HELP)
    if not PLUGIN_DLL.exists():
        raise RuntimeError("프로그램 안에 플러그인 파일이 없어요.")
    pdir = g / "BepInEx" / "plugins" / PLUGIN_FOLDER
    pdir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PLUGIN_DLL, pdir / "FM27FaceStudio.dll")
    done.append("FM Face Studio 플러그인 설치")
    return done


def run_elevated(args: list[str]) -> int | None:
    """이 exe를 관리자 권한으로 다시 실행하고 끝날 때까지 기다린다. 사용자가 거절하면 None."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class SEI(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    exe = sys.executable
    params = subprocess.list2cmdline(args if getattr(sys, "frozen", False) else [str(BASE / "main.py"), *args])
    sei = SEI()
    sei.cbSize = ctypes.sizeof(SEI)
    sei.fMask = 0x00000040          # SEE_MASK_NOCLOSEPROCESS
    sei.lpVerb = "runas"
    sei.lpFile = exe
    sei.lpParameters = params
    sei.nShow = 0
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
        return None
    ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, 120000)
    code = wintypes.DWORD()
    ctypes.windll.kernel32.GetExitCodeProcess(sei.hProcess, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(sei.hProcess)
    return int(code.value)


def install_any(game_dir: str) -> list[str]:
    if fm_running():
        raise RuntimeError("FM27이 켜져 있어요. 게임을 완전히 끈 다음 설치해 주세요.")
    g = Path(game_dir)
    if writable(g):
        return install(game_dir)
    result = app_data_dir() / "install_result.json"
    result.unlink(missing_ok=True)
    code = run_elevated(["--install-plugin", str(g), str(result)])
    if code is None:
        raise RuntimeError("게임 폴더에 쓸 권한이 없어요. 관리자 권한 창에서 '예'를 눌러야 설치돼요.")
    try:
        data = json.loads(result.read_text(encoding="utf-8-sig"))
    except Exception:
        raise RuntimeError(f"관리자 권한 설치 결과를 확인하지 못했어요 (코드 {code}).") from None
    if not data.get("ok"):
        raise RuntimeError(data.get("error") or "설치 실패")
    return data.get("done", [])


def cli_install(game_dir: str, result_path: str) -> int:
    """관리자 권한으로 다시 실행됐을 때 (main.py --install-plugin)."""
    try:
        done = install(game_dir)
        Path(result_path).write_text(json.dumps({"ok": True, "done": done}, ensure_ascii=False), encoding="utf-8")
        return 0
    except Exception as e:  # noqa: BLE001
        Path(result_path).write_text(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False), encoding="utf-8")
        return 1


def launch_game() -> None:
    if sys.platform == "win32":
        os.startfile(f"steam://rungameid/{STEAM_APP_ID}")  # type: ignore[attr-defined]


# ------------------------------------------------------------------ 플러그인 명령
_CMD_LOCK = threading.Lock()


def command(cmd: str, timeout: float = 20.0, **extra) -> dict:
    """플러그인에 명령을 보내고 답을 기다린다. 명령 파일이 하나라 한 번에 하나씩."""
    with _CMD_LOCK:
        return _command(cmd, timeout, **extra)


def _command(cmd: str, timeout: float = 20.0, **extra) -> dict:
    hb = heartbeat()
    if not hb or not hb.get("alive"):
        return {"ok": False, "message": "게임 속 플러그인과 연결되어 있지 않아요. 게임을 켜고 세이브를 불러와 주세요."}
    d = bridge_dir()
    cid = uuid.uuid4().hex[:12]
    tmp = d / "command.json.tmp"
    tmp.write_text(json.dumps({"id": cid, "cmd": cmd, **extra}), encoding="utf-8")
    os.replace(tmp, d / "command.json")
    end = time.time() + timeout
    while time.time() < end:
        time.sleep(0.25)
        try:
            r = json.loads((d / "result.json").read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if r.get("id") == cid:
            return {"ok": bool(r.get("ok")), "message": r.get("message", "")}
    return {"ok": False, "message": "플러그인이 답하지 않아요. 게임이 멈춰 있거나 로딩 중일 수 있어요."}


# 게임 유니폼 번호가 구단 번호와 다른 구단 (기본 데이터베이스 기준, 확인된 것만). 유니폼 번호 -> 구단 번호
KIT_ALIASES = {
    "1736": "1734",   # 레알 마드리드
    "1733": "1730",   # 레알 베티스
}


def kit_dir() -> Path:
    return bridge_dir() / "kits"


def _kit_png(num: str, kind: str) -> Path | None:
    """유니폼 번호·종류의 png (raw면 여기서 png로 바꾼다)."""
    import struct
    from PIL import Image
    d = kit_dir()
    raw, png = d / f"{num}_{kind}.raw", d / f"{num}_{kind}.png"
    try:
        if raw.exists() and (not png.exists() or raw.stat().st_mtime > png.stat().st_mtime):
            b = raw.read_bytes()
            w, h = struct.unpack("<ii", b[:8])
            Image.frombytes("RGBA", (w, h), b[8:8 + w * h * 4]).transpose(Image.FLIP_TOP_BOTTOM).save(png)
            raw.unlink()
    except Exception as e:  # noqa: BLE001
        log.warning("유니폼 그림 변환 실패 %s: %s", raw.name, e)
    return png if png.exists() else None


def newgen_face(uid: str) -> Path | None:
    """플러그인이 저장한 뉴젠 3D 얼굴 (게임에 얼굴이 한 번 뜬 사람만)."""
    import struct
    from PIL import Image
    uid = str(uid).removeprefix("r-")
    if not uid.isdigit():
        return None
    d = bridge_dir() / "newgen"
    raw, png = d / f"{uid}.raw", d / f"{uid}.png"
    try:
        if raw.exists() and (not png.exists() or raw.stat().st_mtime > png.stat().st_mtime):
            b = raw.read_bytes()
            w, h = struct.unpack("<ii", b[:8])
            Image.frombytes("RGBA", (w, h), b[8:8 + w * h * 4]).transpose(Image.FLIP_TOP_BOTTOM).save(png)
            raw.unlink()
    except Exception as e:  # noqa: BLE001
        log.warning("뉴젠 얼굴 변환 실패 %s: %s", uid, e)
    return png if png.exists() else None


def kit_nums() -> list[str]:
    """모인 유니폼 번호들."""
    nums = set()
    try:
        for f in kit_dir().iterdir():
            if f.suffix in (".png", ".raw") and "_" in f.stem:
                n, k = f.stem.rsplit("_", 1)
                if n.isdigit() and k in ("home", "away", "third"):
                    nums.add(n)
    except OSError:
        pass
    return sorted(nums, key=int)


def kit_owner(num: str, user: dict | None = None) -> str:
    """유니폼 번호의 구단 번호 (사용자 지정 > 기본 목록 > 번호 그대로)."""
    num = str(num)
    return str((user or {}).get(num) or KIT_ALIASES.get(num) or num)


def kit_files(num: str) -> dict:
    return {k: p for k in ("home", "away", "third") if (p := _kit_png(str(num), k))}


def kit_images(club: str | int, user: dict | None = None) -> dict:
    """이 구단의 게임 유니폼 {home|away|third: png}. 구단 번호로 짝지어진 유니폼 번호를 먼저 본다."""
    club = str(club or "").strip()
    if not club.isdigit():
        return {}
    for num in [n for n in kit_nums() if kit_owner(n, user) == club and n != club] + [club]:
        if kit_owner(num, user) != club:
            continue                    # 이 번호는 다른 구단 것으로 짝지어져 있다
        f = kit_files(num)
        if f:
            return f
    return {}


def diag_dir() -> Path:
    d = bridge_dir() / "diag"
    d.mkdir(exist_ok=True)
    return d


# ---------------------------------------------------------------- 내 감독 사진
def manager_photo_path() -> Path:
    return bridge_dir() / "manager.raw"


def write_manager_photo(png: Path) -> None:
    """플러그인이 바로 쓸 수 있게 가로·세로(int32) + RGBA(아래 줄부터)로 저장."""
    import struct
    from PIL import Image
    im = Image.open(png).convert("RGBA").transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    d = bridge_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "manager.raw.tmp"
    tmp.write_bytes(struct.pack("<ii", im.width, im.height) + im.tobytes())
    tmp.replace(manager_photo_path())


def clear_manager_photo() -> None:
    manager_photo_path().unlink(missing_ok=True)


# ---------------------------------------------------------------- 게임 외모 코드 (플러그인이 모음)
_APP_CACHE: dict = {"mtime": 0.0, "map": {}}


def appearance(uid: str) -> str:
    """게임이 뉴젠 얼굴을 그릴 때 쓰는 외모 문자열. 게임에서 한 번이라도 얼굴이 뜬 사람만 있다."""
    p = bridge_dir() / "appearance.json"
    try:
        m = p.stat().st_mtime
        if m != _APP_CACHE["mtime"]:
            _APP_CACHE["map"] = json.loads(p.read_text(encoding="utf-8-sig"))
            _APP_CACHE["mtime"] = m
    except (OSError, ValueError):
        return ""
    return _APP_CACHE["map"].get(str(uid).removeprefix("r-"), "")
