"""graphics 폴더 전체의 기존 얼굴 사진 색인: UID → 이미지 파일.

모든 페이스팩의 config.xml을 읽어서 `graphics/pictures/person/(r-)?UID/portrait` 연결을 모은다.
사진 파일 자체는 열지 않으므로 큰 메가팩도 빠르다. 결과는 config 파일 목록·크기·수정 시각이
같으면 저장해 둔 걸 다시 쓴다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path

from .settings import PACK_FOLDER_NAME, OLD_PACK_FOLDER_NAMES, app_data_dir, pack_sort_key

log = logging.getLogger("faceindex")
REC_RX = re.compile(r'<record\b[^>]*?\bfrom\s*=\s*"([^"]+)"[^>]*?\bto\s*=\s*"graphics/pictures/person/(r-)?(-?\d+)/portrait"', re.I)
REC_RX2 = re.compile(r'<record\b[^>]*?\bto\s*=\s*"graphics/pictures/person/(r-)?(-?\d+)/portrait"[^>]*?\bfrom\s*=\s*"([^"]+)"', re.I)
EXTS = (".png", ".jpg", ".jpeg", ".tga", ".bmp", ".dds")
VERSION = 3



def _parse(text: str):
    pairs = [(m.group(1), m.group(3), bool(m.group(2))) for m in REC_RX.finditer(text)]
    pairs += [(m.group(3), m.group(2), bool(m.group(1))) for m in REC_RX2.finditer(text)]
    return pairs


def iter_records(root: Path, cfgs: list[Path]):
    """config.xml 순서대로 (config, uid, {path, pack, regen}) — 사진 파일이 실제로 있는 것만."""
    for cfg in cfgs:
        folder = cfg.parent
        try:
            text = cfg.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        files = None
        for frm, uid, regen in _parse(text):
            if files is None:
                try:
                    files = {f.lower(): f for f in os.listdir(folder)}
                except OSError:
                    files = {}
            stem = frm.replace("\\", "/").split("/")[-1]
            name = files.get(stem.lower())
            if not name:
                for ext in EXTS:
                    if (stem + ext).lower() in files:
                        name = files[(stem + ext).lower()]
                        break
            if name:
                yield cfg, uid, {"path": str(folder / name), "pack": folder.name, "regen": regen}


def top_folder(root: Path, path) -> str:
    try:
        return Path(path).relative_to(root).parts[0]
    except (ValueError, IndexError):
        return ""


class FaceIndex:
    def __init__(self) -> None:
        self.map: dict[str, dict] = {}      # uid -> {"path", "pack", "ours"}
        self.root = ""
        self.building = False
        self.built_at = 0.0
        self.configs = 0
        self._lock = threading.Lock()

    def _cache_path(self) -> Path:
        return app_data_dir() / "face_index.json"

    @staticmethod
    def _configs(root: Path) -> list[Path]:
        out = []
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                if f.lower() == "config.xml":
                    out.append(Path(dirpath) / f)
        # FM이 읽는 순서(이름순) — 뒤에 읽은 config가 이긴다
        out.sort(key=lambda c: [pack_sort_key(x) for x in c.relative_to(root).parts])
        return out

    @staticmethod
    def _stamp(cfgs: list[Path]) -> list:
        st = []
        for c in cfgs:
            try:
                s = c.stat()
                st.append([str(c), s.st_size, int(s.st_mtime)])
            except OSError:
                pass
        return sorted(st)

    def build(self, graphics_dir: str, force: bool = False) -> None:
        with self._lock:
            if self.building:
                return
            self.building = True
        try:
            root = Path(graphics_dir)
            if not root.is_dir():
                self.map, self.root = {}, str(root)
                return
            t0 = time.time()
            cfgs = self._configs(root)
            stamp = self._stamp(cfgs)
            if not force:
                try:
                    cached = json.loads(self._cache_path().read_text(encoding="utf-8"))
                    if cached.get("version") == VERSION and cached.get("root") == str(root) and cached.get("stamp") == stamp:
                        self.map, self.root, self.configs = cached["map"], str(root), len(cfgs)
                        self.built_at = time.time()
                        return
                except Exception:
                    pass
            ours_dirs = {(root / n).resolve() for n in (PACK_FOLDER_NAME, *OLD_PACK_FOLDER_NAMES)}
            result: dict[str, dict] = {}
            ours_entries: dict[str, dict] = {}
            for cfg, uid, entry in iter_records(root, cfgs):
                is_ours = cfg.parent.resolve() in ours_dirs
                entry["ours"] = is_ours
                if is_ours:
                    ours_entries[uid] = entry
                else:
                    result[uid] = entry          # 뒤에 읽은 팩이 이긴다 (게임과 같게)
            # 우리 폴더는 이름이 맨 뒤라 보통 이긴다. 그래도 우리보다 뒤 폴더가 같은 사람을 지정하면 그쪽이 보인다
            ours_key = pack_sort_key(PACK_FOLDER_NAME)
            for uid, e in ours_entries.items():
                cur = result.get(uid)
                top = Path(cur["path"]).relative_to(root).parts[0] if cur else ""
                if not cur or pack_sort_key(top) <= ours_key:
                    result[uid] = e
            self.map, self.root, self.configs = result, str(root), len(cfgs)
            self.built_at = time.time()
            try:
                self._cache_path().write_text(json.dumps({"version": VERSION, "root": str(root), "stamp": stamp,
                                                          "map": result}, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
            log.info("얼굴 색인: config %d개, 사진 %d개, %.1f초", len(cfgs), len(result), time.time() - t0)
        finally:
            self.building = False

    def get(self, uid: str) -> dict | None:
        return self.map.get(str(uid))
