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
VERSION = 4



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


class CompactMap:
    """UID → {path, pack, ours, regen}. 메가팩은 수십만 명이라 파이썬 dict로 들고 있으면 수백 MB라
    numpy 배열(정렬된 UID + 짧은 번호들)로 들고, 꺼낼 때만 dict를 만든다."""

    def __init__(self) -> None:
        import numpy as np
        self.np = np
        self.folders: list[str] = []      # 사진 폴더 (전체 경로)
        self.ours: list[bool] = []        # 그 폴더가 내 폴더인지
        self.prefixes: list[str] = [""]   # 파일 이름 앞부분 (예: "face_")
        self.uids = np.zeros(0, np.int64)
        self.folder = np.zeros(0, np.int32)
        self.pfx = np.zeros(0, np.int32)
        self.ext = np.zeros(0, np.int8)   # EXTS 번호 / -1 = 이름이 규칙에 안 맞음 → odd
        self.regen = np.zeros(0, np.bool_)
        self.odd: dict[str, dict] = {}    # 규칙에 안 맞는 소수 + 숫자가 아닌 UID
        self.over: dict[str, dict | None] = {}   # 켜 있는 동안 바뀐 것 (적용·지우기)

    # ---- dict처럼
    def __len__(self) -> int:
        return int(len(self.uids)) + len(self.odd) + sum(1 for v in self.over.values() if v)

    def get(self, uid, default=None):
        k = str(uid)
        if k in self.over:
            v = self.over[k]
            return dict(v) if v else default
        if k in self.odd:
            return dict(self.odd[k])
        try:
            n = int(k)
        except ValueError:
            return default
        i = int(self.np.searchsorted(self.uids, n))
        if i >= len(self.uids) or int(self.uids[i]) != n:
            return default
        f = int(self.folder[i])
        name = f"{self.prefixes[int(self.pfx[i])]}{k}{EXTS[int(self.ext[i])]}"
        return {"path": self.folders[f] + os.sep + name, "pack": os.path.basename(self.folders[f]),
                "ours": self.ours[f], "regen": bool(self.regen[i])}

    def __setitem__(self, uid, entry: dict) -> None:
        self.over[str(uid)] = dict(entry)

    def pop(self, uid, default=None):
        v = self.get(uid, None)
        self.over[str(uid)] = None
        return v if v is not None else default

    # ---- 만들기
    @classmethod
    def build(cls, rows, folders, ours, prefixes, odd):
        """rows: (uid:int, folder, pfx, ext, regen) 를 읽은 순서대로 — 같은 UID면 뒤가 이긴다."""
        import numpy as np
        m = cls()
        m.folders, m.ours, m.prefixes, m.odd = folders, ours, prefixes, odd
        if rows:
            a = np.array(rows, dtype=np.int64)
            uid = a[:, 0]
            order = np.argsort(uid, kind="stable")
            uid_s = uid[order]
            last = np.ones(len(uid_s), dtype=bool)
            last[:-1] = uid_s[1:] != uid_s[:-1]        # 같은 UID 중 마지막(=뒤에 읽은 것)만
            keep = order[last]
            m.uids = uid[keep]
            m.folder = a[keep, 1].astype(np.int32)
            m.pfx = a[keep, 2].astype(np.int32)
            m.ext = a[keep, 3].astype(np.int8)
            m.regen = a[keep, 4].astype(np.bool_)
        return m

    def save(self, path: Path, meta: dict) -> None:
        np = self.np
        tmp = path.with_suffix(".tmp.npz")
        np.savez(tmp, uids=self.uids, folder=self.folder, pfx=self.pfx, ext=self.ext, regen=self.regen,
                 meta=np.array(json.dumps({**meta, "folders": self.folders, "ours": self.ours,
                                           "prefixes": self.prefixes, "odd": self.odd}, ensure_ascii=False)))
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: Path):
        import numpy as np
        with np.load(path, allow_pickle=False) as z:
            meta = json.loads(str(z["meta"]))
            m = cls()
            m.uids, m.folder, m.pfx, m.ext, m.regen = z["uids"], z["folder"], z["pfx"], z["ext"], z["regen"]
        m.folders, m.ours, m.prefixes, m.odd = meta["folders"], meta["ours"], meta["prefixes"], meta["odd"]
        return m, meta


def top_folder(root: Path, path) -> str:
    try:
        return Path(path).relative_to(root).parts[0]
    except (ValueError, IndexError):
        return ""


class FaceIndex:
    def __init__(self) -> None:
        self.map = CompactMap()      # uid -> {"path", "pack", "ours", "regen"}
        self.root = ""
        self.ours_name = ""          # 내 폴더 이름 (설정에서 바꿀 수 있음)
        self.building = False
        self.built_at = 0.0
        self.configs = 0
        self._lock = threading.Lock()

    def _cache_path(self) -> Path:
        return app_data_dir() / "face_index.npz"

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

    def load_cached(self, graphics_dir: str) -> None:
        """지난번 색인을 바로 쓴다 (확인은 나중에 build가 한다) → 켤 때 카드 사진이 바로 보이게."""
        try:
            (app_data_dir() / "face_index.json").unlink(missing_ok=True)      # 예전 큰 색인 파일
            m, meta = CompactMap.load(self._cache_path())
            if meta.get("version") == VERSION and meta.get("root") == str(Path(graphics_dir)):
                self.map, self.root = m, str(Path(graphics_dir))
        except Exception:  # noqa: BLE001
            pass

    def _mem(self, tag: str) -> None:
        try:
            from . import memlog
            memlog.trim()
            memlog.mark(f"{tag} (사진 {len(self.map)}장)")
        except Exception:  # noqa: BLE001
            pass

    def build(self, graphics_dir: str, force: bool = False) -> None:
        with self._lock:
            if self.building:          # 도는 중이면 끝나고 한 번 더 (지우기·적용 직후 옛 사진이 남지 않게)
                self._again = (graphics_dir, force or getattr(self, "_again", (None, False))[1])
                return
            self.building = True
            self._again = None
        try:
            self._build(graphics_dir, force)
            self._mem("얼굴 색인")
        finally:
            with self._lock:
                self.building = False
                again, self._again = self._again, None
            if again:
                self.build(*again)

    def _build(self, graphics_dir: str, force: bool = False) -> None:
        try:
            root = Path(graphics_dir)
            if not root.is_dir():
                self.map, self.root = CompactMap(), str(root)
                return
            t0 = time.time()
            cfgs = self._configs(root)
            stamp = self._stamp(cfgs)
            if not force:
                try:
                    m, meta = CompactMap.load(self._cache_path())
                    if meta.get("version") == VERSION and meta.get("root") == str(root) and meta.get("stamp") == stamp:
                        self.map, self.root, self.configs = m, str(root), len(cfgs)
                        self.built_at = time.time()
                        return
                except Exception:
                    pass
            ours_name = self.ours_name or PACK_FOLDER_NAME
            ours_dirs = {(root / n).resolve() for n in (ours_name, *OLD_PACK_FOLDER_NAMES)}
            folders: list[str] = []
            fidx: dict[str, int] = {}
            ours_f: list[bool] = []
            prefixes: list[str] = [""]
            pidx: dict[str, int] = {"": 0}
            rows: list[tuple] = []
            odd: dict[str, dict] = {}
            ours_entries: dict[str, dict] = {}
            ext_i = {e: i for i, e in enumerate(EXTS)}
            for cfg, uid, entry in iter_records(root, cfgs):
                is_ours = cfg.parent.resolve() in ours_dirs
                entry["ours"] = is_ours
                if is_ours:
                    ours_entries[uid] = entry
                    continue
                folder, name = os.path.split(entry["path"])
                fi = fidx.get(folder)
                if fi is None:
                    fi = fidx[folder] = len(folders)
                    folders.append(folder)
                    ours_f.append(False)
                stem, ext = os.path.splitext(name)
                ei = ext_i.get(ext.lower()) if ext.lower() == ext or ext.lower() in ext_i else None
                ok = ei is not None and EXTS[ei] == ext and stem.endswith(uid) and uid.lstrip("-").isdigit()
                if ok:
                    pre = stem[: len(stem) - len(uid)]
                    pi = pidx.get(pre)
                    if pi is None:
                        pi = pidx[pre] = len(prefixes)
                        prefixes.append(pre)
                    odd.pop(uid, None)
                    rows.append((int(uid), fi, pi, ei, 1 if entry["regen"] else 0))
                else:
                    odd[uid] = entry          # 드문 경우는 그대로 (odd가 배열보다 먼저 찾아진다)
            m = CompactMap.build(rows, folders, ours_f, prefixes, odd)
            # 우리 폴더는 이름이 맨 뒤라 보통 이긴다. 그래도 우리보다 뒤 폴더가 같은 사람을 지정하면 그쪽이 보인다
            ours_key = pack_sort_key(ours_name)
            for uid, e in ours_entries.items():
                cur = m.get(uid)
                top = Path(cur["path"]).relative_to(root).parts[0] if cur else ""
                if not cur or pack_sort_key(top) <= ours_key:
                    m.odd[uid] = e
            result = m
            self.map, self.root, self.configs = result, str(root), len(cfgs)
            self.built_at = time.time()
            try:
                m.save(self._cache_path(), {"version": VERSION, "root": str(root), "stamp": stamp})
            except OSError:
                pass
            log.info("얼굴 색인: config %d개, 사진 %d개, %.1f초", len(cfgs), len(result), time.time() - t0)
        finally:
            pass

    def get(self, uid: str) -> dict | None:
        return self.map.get(str(uid))
