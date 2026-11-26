"""자동 업데이트: GitHub 최신 릴리스 확인 → 설치 파일 받기 → 조용히 설치하고 다시 켜기.

보내는 정보는 없다. api.github.com 에 '최신 릴리스가 뭐냐'고 묻고, 설치 파일을 받을 뿐이다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

log = logging.getLogger("updater")

REPO = "meldeaths9/fm27-face-studio"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
SETUP_NAME = "FMFaceStudio-Setup.exe"
UA = "FMFaceStudio-updater"


def _ctx():
    try:
        import certifi  # type: ignore
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def _ver(s: str) -> tuple:
    nums = re.findall(r"\d+", str(s or ""))[:3]
    return tuple(int(n) for n in nums) + (0,) * (3 - len(nums))


def is_newer(remote: str, local: str) -> bool:
    return _ver(remote) > _ver(local)


def latest(timeout: float = 6) -> dict | None:
    try:
        req = urllib.request.Request(API, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        log.info("업데이트 확인 실패: %s", e)
        return None
    tag = str(data.get("tag_name", "")).lstrip("vV")
    setup = next((a for a in data.get("assets", []) if a.get("name") == SETUP_NAME), None)
    return {"version": ".".join(str(n) for n in _ver(tag)), "tag": tag,
            "setup": setup.get("browser_download_url") if setup else "",
            "size": int(setup.get("size", 0)) if setup else 0,
            "notes": data.get("body", "") or "", "page": data.get("html_url", "")}


def download(url: str, size: int, progress=None) -> Path:
    if not url.startswith(f"https://github.com/{REPO}/releases/download/"):
        raise ValueError("이상한 업데이트 주소예요.")
    out = Path(tempfile.gettempdir()) / "FMFaceStudio-update" / SETUP_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    done = 0
    with urllib.request.urlopen(req, timeout=30, context=_ctx()) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or size or 0)
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if total and done != total:
        raise IOError("설치 파일을 끝까지 받지 못했어요. 다시 시도해 주세요.")
    os.replace(tmp, out)
    return out


def run_installer(path: Path) -> None:
    """설치 프로그램을 조용히 실행한다. 설치가 끝나면 설치 프로그램이 앱을 다시 켠다."""
    if sys.platform != "win32":
        raise RuntimeError("윈도우에서만 돼요.")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     close_fds=True, creationflags=flags)
