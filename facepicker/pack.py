"""graphics 폴더 안 전용 얼굴 팩(이미지 + config.xml) 관리."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path

from .settings import app_data_dir

REC_RX = re.compile(r'<record\b([^>]*?)/?>', re.I)
FROM_RX = re.compile(r'\bfrom\s*=\s*["\']([^"\']+)["\']', re.I)
TO_RX = re.compile(r'\bto\s*=\s*["\']graphics/pictures/person/(r-)?(\d+)/portrait["\']', re.I)

CONFIG_HEAD = (
    "<record>\n"
    "  <!-- FM27 얼굴 교체 프로그램(FacePicker)이 관리하는 파일입니다. 직접 고치지 마세요. -->\n"
    '  <boolean id="preload" value="false"/>\n'
    '  <boolean id="amap" value="false"/>\n'
    '  <list id="maps">\n'
)
CONFIG_TAIL = "  </list>\n</record>\n"
_WRITE_LOCK = threading.RLock()     # config.xml·applied.json은 한 번에 한 쪽만 고친다 (적용·지우기 겹침 방지)


@dataclass
class FaceEntry:
    uid: str
    newgen: bool = False
    name: str = ""
    club: str = ""
    kind: str = "player"   # player / staff

    @property
    def target(self) -> str:
        prefix = "r-" if self.newgen else ""
        return f"graphics/pictures/person/{prefix}{self.uid}/portrait"


def looks_like_newgen(uid: str) -> bool:
    """세이브 중 생성된 인물은 보통 2,000,000,000 이상의 큰 ID를 가짐 (추정)."""
    return uid.isdigit() and len(uid) >= 10 and uid.startswith("20")


def parse_config(text: str) -> dict[str, bool]:
    """config.xml → {uid: newgen}"""
    out: dict[str, bool] = {}
    for m in REC_RX.finditer(text):
        attrs = m.group(1)
        t = TO_RX.search(attrs)
        if t:
            out[t.group(2)] = bool(t.group(1))
    return out


class FacePack:
    def __init__(self, pack_dir: Path) -> None:
        self.dir = Path(pack_dir)
        self.meta_path = app_data_dir() / "applied.json"

    # ---- 읽기 -------------------------------------------------------
    def config_path(self) -> Path:
        return self.dir / "config.xml"

    def _meta(self) -> dict:
        try:
            return json.loads(self.meta_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_meta(self, meta: dict) -> None:
        tmp = self.meta_path.with_name(f"applied.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.meta_path)

    def entries(self) -> list[FaceEntry]:
        try:
            mapping = parse_config(self.config_path().read_text(encoding="utf-8", errors="ignore"))
        except FileNotFoundError:
            mapping = {}
        meta = self._meta()
        res = []
        for uid, newgen in mapping.items():
            m = meta.get(uid, {})
            res.append(FaceEntry(uid, newgen, m.get("name", ""), m.get("club", ""), m.get("kind", "player")))
        return res

    def image_path(self, uid: str) -> Path:
        return self.dir / f"{uid}.png"

    # ---- 쓰기 -------------------------------------------------------
    def _write_config(self, entries: list[FaceEntry]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        cfg = self.config_path()
        if cfg.exists():
            bdir = app_data_dir() / "backups"
            bdir.mkdir(exist_ok=True)
            shutil.copy2(cfg, bdir / time.strftime("config-%Y%m%d-%H%M%S.xml"))
            # 오래된 백업은 30개만 유지
            olds = sorted(bdir.glob("config-*.xml"))
            for p in olds[:-30]:
                p.unlink(missing_ok=True)
        lines = [CONFIG_HEAD]
        for e in sorted(entries, key=lambda x: (0, int(x.uid)) if x.uid.isdigit() else (1, 0)):
            if not e.uid.isdigit():
                continue
            lines.append(f'    <record from="{e.uid}" to="{e.target}"/>\n')
        lines.append(CONFIG_TAIL)
        tmp = cfg.with_suffix(".xml.tmp")
        tmp.write_text("".join(lines), encoding="utf-8")
        os.replace(tmp, cfg)

    def apply(self, items: list[tuple[FaceEntry, Path]]) -> None:
        """(정보, 완성된 png) 목록을 팩에 넣고 config.xml 갱신."""
        with _WRITE_LOCK:
            self._apply(items)

    def _apply(self, items: list[tuple[FaceEntry, Path]]) -> None:
        current = {e.uid: e for e in self.entries()}
        meta = self._meta()
        self.dir.mkdir(parents=True, exist_ok=True)
        for entry, png in items:
            dst = self.image_path(entry.uid)
            tmp = dst.with_suffix(".png.tmp")
            shutil.copyfile(png, tmp)
            os.replace(tmp, dst)
            current[entry.uid] = entry
            meta[entry.uid] = {"name": entry.name, "club": entry.club, "kind": entry.kind}
        self._write_config(list(current.values()))
        self._save_meta(meta)

    def remove(self, uids: list[str]) -> None:
        with _WRITE_LOCK:
            self._remove(uids)

    def _remove(self, uids: list[str]) -> None:
        current = {e.uid: e for e in self.entries()}
        meta = self._meta()
        for uid in uids:
            current.pop(uid, None)
            meta.pop(uid, None)
            self.image_path(uid).unlink(missing_ok=True)
        self._write_config(list(current.values()))
        self._save_meta(meta)


def find_conflicts(graphics_dir: Path, pack_dir: Path, uids: set[str]) -> dict[str, list[str]]:
    """다른 페이스팩 config.xml이 같은 인물을 가리키는지 검사.
    FM은 폴더 이름순으로 읽고 뒤에 읽은 쪽이 이기므로, 우리 폴더보다 뒤에 오는 팩만 문제다."""
    from .settings import pack_sort_key
    found: dict[str, list[str]] = {}
    if not uids:
        return found
    graphics_dir, pack_dir = Path(graphics_dir), pack_dir.resolve()
    ours = pack_sort_key(pack_dir.name)
    for root, dirs, files in os.walk(graphics_dir):
        dirs.sort(key=pack_sort_key)
        if "config.xml" not in files:
            continue
        p = Path(root) / "config.xml"
        try:
            if p.resolve().parent == pack_dir:
                continue
            rel = p.parent.relative_to(graphics_dir).parts
            if rel and pack_sort_key(rel[0]) <= ours:      # 우리보다 앞 → 우리가 덮어쓴다
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
        except (OSError, ValueError):
            continue
        for uid in uids:
            if f"/{uid}/portrait" in text or f"/r-{uid}/portrait" in text:
                found.setdefault(uid, []).append(str(p.parent))
    return found


def fm_running() -> bool:
    if sys.platform != "win32":
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq fm.exe", "/NH"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        return "fm.exe" in out.lower()
    except Exception:
        return False


def entry_to_dict(e: FaceEntry) -> dict:
    return asdict(e)
