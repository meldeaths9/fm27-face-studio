"""무거운 일(세이브 읽기, 페이스팩 색인)은 잠깐 뜨는 별도 프로세스에서 한다.

파이썬은 한 번 크게 쓴 메모리를 윈도우에 잘 돌려주지 않아서, 앱 안에서 하면 앱이 계속 수백 MB를 쥐고 있게 된다.
일꾼 프로세스는 결과를 파일(캐시)로 남기고 끝나면서 메모리를 전부 돌려준다.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("worker")


def _cmd(args: list[str]) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--worker", *args]
    main = Path(__file__).resolve().parent.parent / "main.py"
    return [sys.executable, str(main), "--worker", *args]


def run(args: list[str], timeout: int = 600) -> bool:
    env = dict(os.environ)
    env["PYINSTALLER_SUPPRESS_SPLASH_SCREEN"] = "1"       # 일꾼은 시작 그림을 띄우지 않는다
    env.pop("_PYI_SPLASH_IPC", None)
    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    try:
        r = subprocess.run(_cmd(args), env=env, creationflags=flags, timeout=timeout,
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode != 0:
            log.warning("일꾼 실패 (%s): 코드 %s", args[0], r.returncode)
        return r.returncode == 0
    except Exception as e:  # noqa: BLE001
        log.warning("일꾼 실행 실패 (%s): %s", args[0], e)
        return False


def main(args: list[str]) -> int:
    """일꾼 쪽: python main.py --worker <일> ..."""
    from .settings import app_data_dir
    logging.basicConfig(level=logging.INFO, filename=str(app_data_dir() / "worker.log"), filemode="a",
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", encoding="utf-8")
    try:
        job = args[0]
        if job == "save":
            from . import savedata
            savedata.read_save(args[1])
            return 0
        if job == "index":
            from .faceindex import FaceIndex
            fi = FaceIndex()
            fi.ours_name = args[2]
            fi._build_here(Path(args[1]))
            return 0
        return 2
    except Exception:  # noqa: BLE001
        logging.getLogger("worker").exception("일꾼 오류")
        return 1
