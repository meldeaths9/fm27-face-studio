"""화면(HTML)에서 부르는 기능 모음. pywebview가 window.pywebview.api 로 노출한다.

주의: pywebview는 공개 속성을 모두 화면에 노출하려고 훑기 때문에, 내부 상태는 전부 _로 시작.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import sys
import threading
import traceback
import uuid
import webbrowser
from pathlib import Path

from PIL import Image, ImageOps

from . import updater, ai_models, appearance, clipboard, faceindex, gamesetup, imaging, prompts, providers, savedata
from .pack import FaceEntry, FacePack, find_conflicts, fm_running, looks_like_newgen
from .people import People
from .settings import Settings, app_data_dir
from .style import STYLE_LABELS, Deco, decorate

VERSION = "1.2.1"
DISPLAY_MAX = 1600   # 화면에 보낼 편집용 사진 최대 크기
log = logging.getLogger("api")


def _data_url(im: Image.Image, fmt: str = "PNG", quality: int = 90) -> str:
    buf = io.BytesIO()
    if fmt == "JPEG":
        im.convert("RGB").save(buf, "JPEG", quality=quality)
        mime = "image/jpeg"
    else:
        im.save(buf, "PNG")
        mime = "image/png"
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode()


def _from_data_url(data: str) -> Image.Image:
    if "," in data[:100]:
        data = data.split(",", 1)[1]
    im = Image.open(io.BytesIO(base64.b64decode(data)))
    return ImageOps.exif_transpose(im).convert("RGBA")


def _thumb_url(path: Path, size: int = 96) -> str:
    try:
        return _data_url(imaging.thumbnail(Image.open(path), size))
    except Exception:
        return ""



def _build_no() -> int:
    try:
        from . import buildinfo
        return int(buildinfo.BUILD)
    except Exception:  # noqa: BLE001
        return 0


def _desktop_dir() -> Path:
    """진짜 바탕화면 (OneDrive로 옮긴 PC 포함)."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf) == 0 and buf.value:   # CSIDL_DESKTOPDIRECTORY
                return Path(buf.value)
        except Exception:  # noqa: BLE001
            pass
    return Path(os.path.expanduser("~")) / "Desktop"

def _clean_uid(raw) -> tuple[str, bool]:
    """'r-2002042946' 같은 입력 → ('2002042946', True)."""
    s = str(raw or "").strip().lower().replace(" ", "")
    prefixed = s.startswith("r-")
    if prefixed:
        s = s[2:]
    return "".join(c for c in s if c.isdigit()), prefixed


def _safe(fn):
    """예외를 {'error': ...}로 바꿔 화면에 전달."""
    def wrap(self, *a, **k):
        try:
            return fn(self, *a, **k)
        except providers.ProviderError as e:
            return {"error": str(e)}
        except Exception as e:  # noqa: BLE001
            log.error("%s 실패\n%s", fn.__name__, traceback.format_exc())
            return {"error": f"{type(e).__name__}: {e}"}
    wrap.__name__ = fn.__name__
    return wrap


BROWSE_MAX = 50       # 첫 화면에 한 번에 보여 줄 최대 인원



import re as _re_name
import unicodedata as _ud_name


def name_key(s) -> str:
    """파일 이름/목록 이름 공통 정리: 확장자·뒤 번호 떼고 공백 하나로."""
    s = _ud_name.normalize("NFC", str(s or "")).strip()
    s = _re_name.sub(r"\.(png|jpe?g|webp|bmp|gif)$", "", s, flags=_re_name.I)
    s = _re_name.sub(r"[\s_]*(\(\d{1,3}\)|\d{1,3})$", "", s)       # 김민재1, 김민재 2, 김민재(2), 김민재 (2)
    return " ".join(s.replace("_", " ").split())


def loose_key(s) -> str:
    s = _ud_name.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not _ud_name.combining(c))
    s = _re_name.sub(r"[-‐'’`.·]", "", s)
    return " ".join(s.split())


def order_key(s) -> str:
    return " ".join(sorted(loose_key(s).split()))


class Api:
    def __init__(self) -> None:
        self._cfg = Settings()
        if self._cfg.ai_provider not in providers.BY_ID:      # 목록에 없는 AI를 골라 뒀으면 제미나이로
            self._cfg.ai_provider = "web_gemini"
        self._people = People()
        self._people.set(savedata.load_cache(self._cfg.last_save) if self._cfg.last_save else None)
        self._lock = threading.Lock()
        self._qlock = threading.RLock()      # 대기열은 한 번에 한 요청만 고친다
        self._orig: Image.Image | None = None
        self._work: Image.Image | None = None
        self._nobg: Image.Image | None = None
        self._kit: Image.Image | None = None      # 유니폼 참고 사진
        self._progress = {"task": "", "done": 0, "total": 0}
        self._window = None
        self._qdir = app_data_dir() / "queue"
        self._qdir.mkdir(exist_ok=True)
        self._queue: list[dict] = self._load_queue()
        self._reading = {"active": False, "path": "", "started": 0.0, "error": ""}
        self._last_check = 0.0
        self._started = __import__("time").time()     # 이 시각 이후에 저장된 세이브만 자동으로 읽는다
        self._index = faceindex.FaceIndex()
        self._thumbs: dict[str, str] = {}
        try:
            self._pack_moved = self._cfg.migrate_pack_dir()
            if self._pack_moved:
                log.info("우리 폴더 옮기기(맨 뒤 이름으로): %s", self._pack_moved)
        except Exception as e:  # noqa: BLE001
            self._pack_moved = ""
            log.warning("우리 폴더 옮기기 실패: %s", e)
        self._index.ours_name = self._cfg.pack_name
        self._index.load_cached(self._cfg.graphics_dir)

        def _later_index():          # 화면이 먼저 뜨고 업데이트 확인이 끝난 뒤에 색인 (켤 때 렉 줄이기)
            import time as _t
            _t.sleep(2.5)
            self._index.build(self._cfg.graphics_dir)
        threading.Thread(target=_later_index, daemon=True).start()
        threading.Thread(target=self._maybe_reload, daemon=True).start()

    def _set_window(self, w) -> None:
        self._window = w
        self._maxed = False
        try:
            w.events.maximized += lambda *a: setattr(self, "_maxed", True)
            w.events.restored += lambda *a: setattr(self, "_maxed", False)
            w.events.shown += lambda *a: self._fit_work_area()
            w.events.moved += lambda *a: self._fit_work_area()
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------------- 창 (제목줄을 직접 그린다)
    def win_state(self) -> dict:
        w = self._window
        if not w:
            return {"maximized": False, "width": 1440, "height": 900}
        return {"maximized": bool(getattr(self, "_maxed", False)), "width": int(w.width), "height": int(w.height)}

    def win_min(self) -> bool:
        if self._window:
            self._window.minimize()
        return True

    def win_toggle_max(self) -> bool:
        w = self._window
        if not w:
            return False
        if getattr(self, "_maxed", False):
            w.restore()
            self._maxed = False
        else:
            self._fit_work_area()
            w.maximize()
            self._maxed = True
        return self._maxed

    def _fit_work_area(self) -> None:
        """제목줄 없는 창은 최대화하면 작업표시줄까지 덮는다 → 최대화 크기를 작업 영역(작업표시줄 뺀 곳)으로 묶는다."""
        try:
            form = self._window.native
            from System import Func, Type  # type: ignore
            from System.Windows.Forms import Screen  # type: ignore
            from System.Drawing import Rectangle  # type: ignore

            def _set():
                scr = Screen.FromHandle(form.Handle)
                wa, b = scr.WorkingArea, scr.Bounds
                form.MaximizedBounds = Rectangle(wa.X - b.X, wa.Y - b.Y, wa.Width, wa.Height)

            if form.InvokeRequired:
                form.Invoke(Func[Type](_set))
            else:
                _set()
        except Exception as e:  # noqa: BLE001
            log.debug("작업 영역 맞추기 실패: %s", e)

    def win_resize(self, width: int, height: int, edge: str = "rb") -> bool:
        """edge: 잡은 가장자리(l/r/t/b 조합). 반대쪽 모서리를 고정하고 크기를 바꾼다."""
        if self._window and not getattr(self, "_maxed", False):
            from webview.window import FixPoint
            fix = (FixPoint.EAST if "l" in edge else FixPoint.WEST) | (FixPoint.SOUTH if "t" in edge else FixPoint.NORTH)
            self._window.resize(max(1240, int(width)), max(760, int(height)), fix)
        return True

    def win_close(self) -> bool:
        if self._window:
            self._window.destroy()
        return True

    @_safe
    def pack_folder_info(self) -> dict:
        """graphics 안 폴더들을 FM이 읽는 순서대로 (내 폴더가 몇 번째인지)."""
        from .settings import pack_sort_key
        g = Path(self._cfg.graphics_dir)
        try:
            names = sorted((d.name for d in g.iterdir() if d.is_dir()), key=pack_sort_key)
        except OSError:
            names = []
        return {"name": self._cfg.pack_name, "folders": names}

    @_safe
    def rename_pack_folder(self, new: str) -> dict:
        """내 폴더 이름 바꾸기 (안의 사진·config.xml도 함께 옮겨짐)."""
        from .settings import valid_pack_name, PACK_FOLDER_NAME
        new = str(new or "").strip() or PACK_FOLDER_NAME
        if not valid_pack_name(new):
            return {"error": '폴더 이름에 \\ / : * ? " < > | 는 쓸 수 없고, 60자 이하여야 해요.'}
        old_dir = self._cfg.pack_dir
        new_dir = Path(self._cfg.graphics_dir) / new
        if new_dir.resolve() == old_dir.resolve():
            return {"ok": True, "name": new}
        if new_dir.exists():
            return {"error": f"graphics 안에 '{new}' 폴더가 이미 있어요. 다른 이름을 써 주세요."}
        if old_dir.exists():
            try:
                old_dir.rename(new_dir)
            except OSError as e:
                return {"error": f"폴더 이름을 바꾸지 못했어요. FM27을 끄고 다시 해 주세요.\n({e})"}
        self._cfg.pack_folder = new
        self._cfg.save()
        self._index.ours_name = new
        threading.Thread(target=lambda: self._index.build(self._cfg.graphics_dir, force=True), daemon=True).start()
        return {"ok": True, "name": new}

    # ---------------------------------------------------------------- 자동 업데이트 (GitHub 릴리스)
    @_safe
    def check_update(self, manual: bool = False) -> dict:
        """최신 릴리스 버전만 묻는다. 보내는 정보 없음 (GitHub에 일반 접속만)."""
        if not manual and not self._cfg.check_updates:
            return {"available": False, "off": True}
        if not getattr(sys, "frozen", False) and not manual:
            return {"available": False}
        rel = updater.latest(beta=bool(getattr(self._cfg, "beta_updates", False)))
        if not rel:
            return {"available": False, "error": "업데이트 정보를 못 받았어요." if manual else ""}
        local = f"{VERSION}.{_build_no()}"
        newer = updater.is_newer(rel["version"], local)
        skipped = not manual and rel["version"] == self._cfg.skip_version
        self._update = rel if newer else None
        return {"available": newer and not skipped, "version": rel["version"], "label": rel.get("label", rel["version"]),
                "current": local, "notes": rel.get("notes", "")[:1500], "url": rel.get("page", "")}

    @_safe
    def do_update(self) -> dict:
        rel = getattr(self, "_update", None)
        if not rel or not rel.get("setup"):
            return {"error": "받을 설치 파일이 없어요."}
        def prog(done, total):
            self._progress = {"task": f"새 버전 {rel['version']} 받는 중", "done": done, "total": total}
        try:
            path = updater.download(rel["setup"], rel.get("size", 0), prog)
        finally:
            self._progress = {"task": "", "done": 0, "total": 0}
        updater.run_installer(path)
        threading.Timer(2.5, lambda: self._window and self._window.destroy()).start()
        return {"ok": True}

    # ---------------------------------------------------------------- 상태
    def _pack(self) -> FacePack:
        return FacePack(self._cfg.pack_dir)

    def _people_info(self) -> dict:
        return {"loaded": bool(self._people.items), "count": len(self._people.items),
                "save": self._people.save, "save_name": Path(self._people.save).stem if self._people.save else "",
                "my_clubs": [c["name"] for c in self._people.my_clubs]}

    def _ai_view(self) -> list[dict]:
        out = []
        for p in providers.PROVIDERS:
            cfg = self._cfg.ai_cfg.get(p["id"], {})
            out.append({**p, "status": providers.status(p["id"], cfg),
                        "key": cfg.get("key", ""), "account": cfg.get("account", ""),
                        "model": cfg.get("model", ""), "default_model": providers.DEFAULT_MODELS.get(p["id"], "")})
        return out

    @_safe
    def get_state(self) -> dict:
        c = self._cfg
        return {
            "version": VERSION, "pack_moved": getattr(self, "_pack_moved", ""),
            "settings": {
                "graphics_dir": c.graphics_dir, "output_size": c.output_size, "check_updates": c.check_updates, "beta_updates": bool(getattr(c, "beta_updates", False)), "pack_folder": c.pack_name, "bulk_crop": c.bulk_crop, "bulk_deco": c.bulk_deco,
                "prompt_template": c.prompt_template, "send_photo": c.send_photo,
                "ai_provider": c.ai_provider, "deco": c.deco, "prompt_lang": c.prompt_lang,
                "expression": c.expression, "manager_outfit": c.manager_outfit, "ref_mode": c.ref_mode, "club_hints": c.club_hints,
            },
            "ai": self._ai_view(),
            "styles": STYLE_LABELS,
            "default_prompt": prompts.FACE["ko"],
            "default_prompt_en": prompts.FACE["en"],
            "expressions": prompts.EXPRESSION_LABELS,
            "squads": list(savedata.SQUADS),
            "people": self._people_info(),
            "queue": self._queue_view(),
            "face_ai": ai_models.face_available(),
            "bg_ready": ai_models.bg_ready(),
            "pack_dir": str(c.pack_dir),
        }

    @_safe
    def save_settings(self, s: dict) -> dict:
        c = self._cfg
        if "graphics_dir" in s:
            c.graphics_dir = str(s["graphics_dir"]).strip() or c.graphics_dir
        if "output_size" in s:
            try:
                c.output_size = max(128, min(1024, int(s["output_size"])))
            except (TypeError, ValueError):
                c.output_size = 512
        if "prompt_template" in s:
            t = str(s["prompt_template"]).strip()
            c.prompt_template = "" if t in (prompts.FACE["ko"].strip(), prompts.FACE["en"].strip()) else t
        if s.get("prompt_lang") in ("ko", "en"):
            c.prompt_lang = s["prompt_lang"]
        if s.get("expression") in prompts.EXPRESSION_LABELS:
            c.expression = s["expression"]
        if s.get("ref_mode") in ("game", "photo"):
            c.ref_mode = s["ref_mode"]
        if s.get("manager_outfit") in ("suit", "training"):
            c.manager_outfit = s["manager_outfit"]
        if "send_photo" in s:
            c.send_photo = bool(s["send_photo"])
        if s.get("ai_provider") in providers.BY_ID:
            c.ai_provider = s["ai_provider"]
        if isinstance(s.get("ai_cfg"), dict):
            for pid, v in s["ai_cfg"].items():
                if pid in providers.BY_ID and isinstance(v, dict):
                    c.ai_cfg[pid] = {k: str(v.get(k, "")).strip() for k in ("key", "model", "account")}
        if isinstance(s.get("deco"), dict):
            d = Deco.from_dict(s["deco"]).to_dict()
            d.pop("text", None)          # 글자는 인물마다 다르므로 저장하지 않음
            c.deco = d
        c.save()
        return self.get_state()

    @_safe
    def pick_folder(self, initial: str = "") -> str | None:
        if not self._window:
            return None
        import webview
        r = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=initial or "")
        return r[0] if r else None

    @_safe
    def open_pack_dir(self) -> bool:
        d = self._cfg.pack_dir
        d.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(d)  # type: ignore[attr-defined]
        return True

    @_safe
    def open_url(self, url: str) -> bool:
        if str(url).startswith("https://"):
            webbrowser.open(url)
        return True

    @_safe
    def progress(self) -> dict:
        return dict(self._progress)

    # ---------------------------------------------------------------- 세이브 자동 연결
    def _target_save(self) -> str:
        if self._cfg.follow_save:
            return savedata.last_saved_game() or self._cfg.last_save
        return self._cfg.last_save

    def _maybe_reload(self, force: bool = False, path: str = "", reread: bool = False) -> None:
        """현재 세이브(게임이 마지막으로 저장/불러온 것)에 연결하고, 바뀌었으면 백그라운드로 다시 읽는다."""
        import time as _t
        if self._reading["active"]:
            return
        self._last_check = _t.time()
        try:
            target = path or self._target_save()
        except Exception:  # noqa: BLE001
            return
        if not target or not Path(target).exists():
            return
        p = Path(target)
        try:
            if not force and _t.time() - p.stat().st_mtime < 4:      # 게임이 아직 저장 중일 수 있음
                return
        except OSError:
            return
        cache = None if reread else savedata.load_cache(p)
        if cache is not None:
            if self._people.save != str(p) or not self._people.items:
                self._people.set(cache)
                self._cfg.last_save = str(p)
                self._cfg.save()
            return
        if not force:
            if not self._cfg.follow_save:
                return      # 자동 읽기는 끔: 사용자가 버튼을 누를 때만 읽는다
            try:
                if p.stat().st_mtime < self._started:
                    return  # 켜져 있어도 프로그램을 켠 뒤 게임에서 새로 저장한 것만 읽는다
            except OSError:
                return
        self._reading = {"active": True, "path": str(p), "started": _t.time(), "error": ""}
        try:
            data = savedata.read_save(p)
            self._people.set(data)
            self._cfg.last_save = str(p)
            self._cfg.save()
            self._reading["error"] = ""
        except Exception as e:  # noqa: BLE001
            log.error("세이브 자동 읽기 실패: %s\n%s", p, traceback.format_exc())
            self._reading["error"] = f"{type(e).__name__}: {e}"
        finally:
            self._reading["active"] = False

    @_safe
    def read_save_now(self, which: str = "current") -> dict:
        """버튼으로만 세이브를 읽는다. current: 게임이 마지막으로 쓴 세이브, reload: 지금 세이브 다시 읽기."""
        if self._reading["active"]:
            return {"started": True, "path": self._reading["path"]}
        if which == "reload":
            path = self._cfg.last_save
        else:
            path = savedata.last_saved_game() or self._cfg.last_save
        if not path or not Path(path).exists():
            return {"error": "읽을 세이브를 찾지 못했어요. FM27에서 세이브를 한 번 저장하거나 '세이브 직접 고르기'를 눌러 주세요."}
        self._reading = {"active": True, "path": str(path), "started": __import__("time").time(), "error": ""}
        def run():
            self._reading["active"] = False
            self._maybe_reload(force=True, path=str(path), reread=(which == "reload"))
        threading.Thread(target=run, daemon=True).start()
        return {"started": True, "path": str(path)}

    # ---------------------------------------------------------------- 첫 화면 (선수 카드)
    def _face_thumb(self, path: str, size: int = 200) -> str:
        try:
            st = os.stat(path)
        except OSError:
            return ""
        key = f"{path}|{st.st_mtime}|{size}"
        if key in self._thumbs:
            return self._thumbs[key]
        try:
            im = Image.open(path)
            im.draft("RGB", (size * 2, size * 2))
            url = _data_url(imaging.thumbnail(im.convert("RGBA"), size))
        except Exception:
            url = ""
        if len(self._thumbs) > 800:
            self._thumbs.clear()
        self._thumbs[key] = url
        return url

    @_safe
    def clubs(self, team: str) -> list[dict]:
        return self._people.clubs(team)

    @_safe
    def browse(self, name: str, team: str, kind: str, filt: str = "all", offset: int = 0, limit: int = 50,
               squad: str = "", club: str = "") -> dict:
        idx = self._index
        limit = min(int(limit), BROWSE_MAX)
        offset = 0
        items = self._people.search(name, team, kind, limit=100000, mine_if_empty=True, squad=squad, club=club)
        def face_of(p):
            return idx.get(p["uid"])
        if filt == "none":
            items = [p for p in items if not face_of(p)]
        elif filt == "has":
            items = [p for p in items if face_of(p)]
        elif filt == "ours":
            items = [p for p in items if (face_of(p) or {}).get("ours")]
        page = []
        queued = {it["uid"]: it for it in self._queue}
        for p in items[int(offset):int(offset) + int(limit)]:
            f = face_of(p)
            d = dict(p)
            d["face"] = self._face_thumb(f["path"]) if f else ""
            d["face_state"] = "ours" if f and f.get("ours") else "has" if f else "none"
            d["pack"] = f["pack"] if f else ""
            q = queued.get(str(p.get("uid", "")).removeprefix("r-"))
            if q:
                d["queued"] = True
                d["face"] = _thumb_url(Path(q["png"]), 160)
            page.append(d)
        return {"total": len(items), "items": page, "offset": 0, "max": BROWSE_MAX,
                "index": {"building": idx.building, "count": len(idx.map), "configs": idx.configs},
                "empty_query": not (name.strip() or team.strip())}

    @_safe
    def current_face(self, uid: str) -> dict:
        clean, _ = _clean_uid(uid)
        f = self._index.get(clean)
        look = appearance.summary(gamesetup.appearance(clean))
        if not f:
            return {"face": "", "pack": "", "ours": False, "look": look}
        return {"face": self._face_thumb(f["path"], 300), "pack": f["pack"], "ours": f.get("ours", False), "look": look}

    @_safe
    def load_existing(self, uid: str) -> dict:
        clean, _ = _clean_uid(uid)
        f = self._index.get(clean)
        if not f:
            return {"error": "지금 쓰이는 사진이 없어요."}
        return self.load_image_path(f["path"])

    @_safe
    def rebuild_index(self) -> dict:
        threading.Thread(target=lambda: self._index.build(self._cfg.graphics_dir, force=True), daemon=True).start()
        return {"ok": True}

    # ---------------------------------------------------------------- 상태 배지
    @_safe
    def status_all(self) -> dict:
        c = self._cfg
        game = gamesetup.find_game(c.game_dir)
        if game and game != c.game_dir:
            c.game_dir = game
            c.save()
        g = gamesetup.status(game)
        save = {"loaded": bool(self._people.items), "path": self._people.save,
                "name": Path(self._people.save).stem if self._people.save else "",
                "count": len(self._people.items), "changed": False, "exists": False,
                "counts": {}, "read_at": 0}
        if self._people.save:
            sp = Path(self._people.save)
            save["exists"] = sp.exists()
            cache = savedata.load_cache()
            if cache and save["exists"]:
                try:
                    save["changed"] = abs(sp.stat().st_mtime - float(cache.get("mtime", 0))) > 1
                except OSError:
                    pass
                save["read_at"] = cache.get("read_at", 0)
                save["game"] = cache.get("game", "")
            kinds = {}
            for p in self._people.items:
                kinds[p.get("kind", "")] = kinds.get(p.get("kind", ""), 0) + 1
            save["counts"] = kinds
        import time as _t
        if not self._reading["active"] and _t.time() - self._last_check > 5:
            self._sync_manager()
            threading.Thread(target=self._maybe_reload, daemon=True).start()
        save["reading"] = dict(self._reading)
        save["index"] = {"building": self._index.building, "count": len(self._index.map)}
        save["follow"] = c.follow_save
        save["version"] = getattr(self._people, "version", 0)
        return {"save": save, "game": g, "graphics_dir": c.graphics_dir, "auto_refresh": c.auto_refresh,
                "bepinex_url": gamesetup.BEPINEX_URL}

    @_safe
    def install_plugin(self) -> dict:
        game = gamesetup.find_game(self._cfg.game_dir)
        if not game:
            return {"error": "FM27 설치 폴더를 찾지 못했어요. 설정에서 게임 폴더를 지정해 주세요."}
        done = gamesetup.install_any(game)
        return {"done": done, "status": gamesetup.status(game)}

    @_safe
    def launch_game(self) -> bool:
        gamesetup.launch_game()
        return True

    @_safe
    def open_game_folder(self) -> bool:
        game = gamesetup.find_game(self._cfg.game_dir)
        if game and sys.platform == "win32":
            os.startfile(game)  # type: ignore[attr-defined]
        return True

    @_safe
    def plugin_refresh(self) -> dict:
        return gamesetup.command("refresh", timeout=30)

    @_safe
    def plugin_diag(self, seconds: int = 120) -> dict:
        return gamesetup.command("diag", timeout=10, seconds=int(seconds))

    @_safe
    def plugin_diag_stop(self) -> dict:
        return gamesetup.command("diag_stop", timeout=10)

    @_safe
    def make_report(self) -> dict:
        """사용자가 개발자에게 보낼 '오류 보고 파일'. 바탕화면에 txt로 만든다. API 키는 넣지 않는다."""
        import datetime
        import platform

        def tail(path: Path, n: int = 300) -> str:
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                return "\n".join(lines[-n:]) or "(비어 있음)"
            except OSError:
                return "(없음)"

        out = []
        now = datetime.datetime.now()
        out.append(f"FM Face Studio 오류 보고  {now:%Y-%m-%d %H:%M:%S}")
        out.append(f"버전 {VERSION} · {platform.platform()} · Python {platform.python_version()}")
        c = self._cfg
        safe = {k: v for k, v in c.__dict__.items() if k not in ("ai_cfg", "club_hints")}
        safe["ai_cfg"] = {pid: {"model": (v or {}).get("model", ""), "has_key": bool((v or {}).get("key"))}
                          for pid, v in (c.ai_cfg or {}).items()}
        out.append("\n== 설정 (API 키 제외) ==\n" + json.dumps(safe, ensure_ascii=False, indent=1, default=str))
        try:
            st = gamesetup.status(c.game_dir)
            out.append("\n== 게임·플러그인 상태 ==\n" + json.dumps(st, ensure_ascii=False, indent=1, default=str))
        except Exception as e:  # noqa: BLE001
            out.append(f"\n== 게임·플러그인 상태 ==\n(읽기 실패: {e})")
        out.append(f"\n== 세이브 ==\n{self._people.save or '(없음)'} · 인물 {len(self._people.items)}명 · 읽는 중 {self._reading.get('active')}")
        ad = app_data_dir()
        out.append("\n== app.log (끝 300줄) ==\n" + tail(ad / "app.log"))
        out.append("\n== crash.log ==\n" + tail(ad / "crash.log", 200))
        out.append("\n== 플러그인 status.json ==\n" + tail(gamesetup.bridge_dir() / "status.json", 50))
        if c.game_dir:
            try:      # 설치 폴더 구성 (게임패스 등 BepInEx 인식 문제 확인용, 파일 이름만)
                gd = Path(c.game_dir)
                top = sorted(x.name + ("/" if x.is_dir() else "") for x in gd.iterdir())
                bep = sorted(str(x.relative_to(gd)) for x in (gd / "BepInEx").glob("*/*"))[:60] if (gd / "BepInEx").is_dir() else []
                out.append("\n== 게임 폴더 ==\n" + "\n".join(top[:80]) + "\n-- BepInEx --\n" + "\n".join(bep))
            except OSError as e:
                out.append(f"\n== 게임 폴더 == 못 읽음: {e}")
            out.append("\n== BepInEx LogOutput.log (끝 200줄) ==\n" + tail(Path(c.game_dir) / "BepInEx" / "LogOutput.log", 200))
        desk = _desktop_dir()
        if not desk.exists():
            desk = ad
        f = desk / f"FMFaceStudio_오류보고_{now:%Y%m%d-%H%M}.txt"
        f.write_text("\n".join(out), encoding="utf-8")
        if sys.platform == "win32":
            providers.reveal(f)
        return {"ok": True, "path": str(f)}

    @_safe
    def plugin_collect(self, seconds: int = 120) -> dict:
        return gamesetup.command("collect", timeout=10, seconds=int(seconds))

    @_safe
    def plugin_collect_stop(self) -> dict:
        r = gamesetup.command("collect_stop", timeout=10)
        self._convert_collected()
        return r

    def _convert_collected(self) -> Path | None:
        """플러그인이 모은 raw 그림을 png로 (가장 최근 폴더)."""
        import struct
        dirs = sorted(gamesetup.diag_dir().glob("images-*"))
        if not dirs:
            return None
        d = dirs[-1]
        for f in sorted(d.glob("*.raw")):
            out = f.with_suffix(".png")
            if out.exists():
                continue
            try:
                b = f.read_bytes()
                w, h = struct.unpack("<ii", b[:8])
                im = Image.frombytes("RGBA", (w, h), b[8:8 + w * h * 4]).transpose(Image.FLIP_TOP_BOTTOM)
                im.save(out)
                f.unlink()
            except Exception as e:  # noqa: BLE001
                log.warning("수집 그림 변환 실패 %s: %s", f.name, e)
        return d

    @_safe
    def open_diag_folder(self) -> bool:
        d = gamesetup.diag_dir()
        img = self._convert_collected()
        if img and sys.platform == "win32" and (not list(d.glob("diag-*.txt")) or img.stat().st_mtime > max(x.stat().st_mtime for x in d.glob("diag-*.txt"))):
            os.startfile(img)  # type: ignore[attr-defined]
            return True
        if sys.platform == "win32":
            files = sorted(d.glob("diag-*.txt"))
            if files:
                providers.reveal(files[-1])
            else:
                os.startfile(d)  # type: ignore[attr-defined]
        return True

    @_safe
    def set_club_hint(self, club: str, hint: str) -> bool:
        club = str(club or "").strip()
        if not club:
            return False
        hint = str(hint or "").strip()
        if hint:
            self._cfg.club_hints[club] = hint
        else:
            self._cfg.club_hints.pop(club, None)
        self._cfg.save()
        return True

    @_safe
    def set_option(self, key: str, value) -> bool:
        if key == "auto_refresh":
            self._cfg.auto_refresh = bool(value)
        elif key == "bulk_crop" and value in ("face", "keep"):
            self._cfg.bulk_crop = value
        elif key == "bulk_deco" and value in ("follow", "none"):
            self._cfg.bulk_deco = value
        elif key == "check_updates":
            self._cfg.check_updates = bool(value)
        elif key == "beta_updates":
            self._cfg.beta_updates = bool(value)
        elif key == "skip_version":
            self._cfg.skip_version = str(value or "")
        elif key == "follow_save":
            self._cfg.follow_save = bool(value)
            if value:
                threading.Thread(target=self._maybe_reload, daemon=True).start()
        elif key == "game_dir":
            g = gamesetup.normalize_game_dir(str(value or ""))
            if not g:
                return {"error": "FM27 설치 폴더가 아니에요. fm.exe(게임패스는 GameAssembly.dll)가 들어 있는 폴더를 골라 주세요.\n게임패스는 보통 C:\\XboxGames\\Football Manager 27\\Content 예요."}
            self._cfg.game_dir = g
        else:
            return False
        self._cfg.save()
        return True

    # ---------------------------------------------------------------- 세이브
    @_safe
    def pick_save(self) -> dict | None:
        if not self._window:
            return {"error": "창이 준비되지 않았어요."}
        import webview
        start = Path(self._cfg.last_save).parent if self._cfg.last_save else savedata.default_games_dir()
        r = self._window.create_file_dialog(webview.FileDialog.OPEN, directory=str(start) if start.exists() else "",
                                            file_types=("FM 세이브 (*.fm)", "모든 파일 (*.*)"))
        if not r:
            return None
        return self.load_save(r[0])

    @_safe
    def load_save(self, path: str) -> dict:
        p = Path(path)
        if not p.exists():
            return {"error": f"세이브 파일이 없어요: {p}"}
        data = savedata.load_cache(p)
        cached = data is not None
        if data is None:
            data = savedata.read_save(p)
        self._people.set(data)
        self._cfg.last_save = str(p)
        current = savedata.last_saved_game()
        if current and Path(current) != p:
            self._cfg.follow_save = False     # 게임의 현재 세이브와 다른 걸 직접 골랐음
        self._cfg.save()
        info = self._people_info()
        info["cached"] = cached
        info["seconds"] = data.get("read_seconds")
        return info

    @_safe
    def reload_save(self) -> dict:
        if not self._cfg.last_save:
            return {"error": "먼저 세이브를 불러와 주세요."}
        p = Path(self._cfg.last_save)
        if not p.exists():
            return {"error": f"세이브 파일이 없어요: {p}"}
        self._people.set(savedata.read_save(p))
        return self._people_info()

    @_safe
    def search(self, name: str, team: str, kind: str) -> list[dict]:
        pack = self._pack()
        applied = {e.uid for e in pack.entries()}
        res = []
        for p in self._people.search(name, team, kind):
            d = dict(p)
            d["face"] = _thumb_url(pack.image_path(p["uid"]), 72) if p["uid"] in applied else ""
            res.append(d)
        return res

    @_safe
    def guess_newgen(self, uid: str) -> bool:
        clean, prefixed = _clean_uid(uid)
        return prefixed or looks_like_newgen(clean)

    # ---------------------------------------------------------------- 사진
    def _src(self) -> Image.Image | None:
        return self._nobg if self._nobg is not None else self._work

    def _photo_payload(self, with_box: bool = True) -> dict:
        src = self._src()
        disp = src.copy()
        disp.thumbnail((DISPLAY_MAX, DISPLAY_MAX), Image.LANCZOS)
        transparent = self._nobg is not None
        out = {
            "url": _data_url(disp) if transparent else _data_url(disp, "JPEG", 90),
            "w": src.width, "h": src.height, "nobg": transparent,
            "is_original": self._work is self._orig,
        }
        if with_box:
            out["box"] = list(imaging.auto_box(self._work))
        return out

    def _set_photo(self, im: Image.Image, original: bool) -> dict:
        with self._lock:
            if original or self._orig is None:
                self._orig = im
            self._work = im
            self._nobg = None
        return self._photo_payload()

    @_safe
    def load_image(self, data_url: str) -> dict:
        return self._set_photo(_from_data_url(data_url), original=True)

    @_safe
    def load_image_path(self, path: str) -> dict:
        return self._set_photo(imaging.load_image(path), original=True)

    @_safe
    def paste_clipboard(self) -> dict:
        from PIL import ImageGrab
        data = ImageGrab.grabclipboard()
        if isinstance(data, Image.Image):
            return self._set_photo(data.convert("RGBA"), original=True)
        if isinstance(data, list) and data:
            return self.load_image_path(data[0])
        return {"error": "클립보드에 사진이 없어요."}

    @_safe
    def revert_original(self) -> dict:
        if self._orig is None:
            return {"error": "원본 사진이 없어요."}
        return self._set_photo(self._orig, original=True)

    @_safe
    def auto_box(self) -> list:
        if self._work is None:
            return {"error": "사진이 없어요."}
        return list(imaging.auto_box(self._work))

    @_safe
    def set_nobg(self, on: bool) -> dict:
        if self._work is None:
            return {"error": "사진이 없어요."}
        if on and self._nobg is None:
            if not ai_models.bg_ready():
                self._progress = {"task": "배경 제거 모델 내려받는 중", "done": 0, "total": 0}

                def prog(done, total):
                    self._progress = {"task": "배경 제거 모델 내려받는 중", "done": done, "total": total}
                try:
                    ai_models.download_bg_model(prog)
                finally:
                    self._progress = {"task": "", "done": 0, "total": 0}
            work = self._work
            out = ai_models.remove_background(work)
            if work is self._work:
                self._nobg = out
        elif not on:
            self._nobg = None
        return self._photo_payload(with_box=False)

    @_safe
    def preview(self, box: list, deco: dict, size: int = 300) -> str:
        src = self._src()
        if src is None:
            return ""
        im = imaging.render(src, tuple(float(v) for v in box), int(size))
        return _data_url(decorate(im, Deco.from_dict(deco)))

    # ---------------------------------------------------------------- AI
    @_safe
    def set_kit(self, data_url: str) -> dict:
        self._kit = _from_data_url(data_url)
        t = self._kit.copy()
        t.thumbnail((160, 160))
        return {"thumb": _data_url(t)}

    @_safe
    def set_kit_path(self, path: str) -> dict:
        self._kit = imaging.load_image(path)
        t = self._kit.copy()
        t.thumbnail((160, 160))
        return {"thumb": _data_url(t)}

    @_safe
    def clear_kit(self) -> bool:
        self._kit = None
        return True

    @_safe
    def game_kits(self, club: str) -> dict:
        """이 클럽의 게임 유니폼 (플러그인이 클럽 화면에서 모아 둔 것)."""
        kits = gamesetup.kit_images(club)
        out = {}
        for k, pth in kits.items():
            try:
                out[k] = _thumb_url(pth, 96)
            except Exception:  # noqa: BLE001
                pass
        return {"kits": out}

    @_safe
    def use_game_kit(self, club: str, kind: str) -> dict:
        pth = gamesetup.kit_images(club).get(kind)
        if not pth:
            return {"error": "이 클럽의 게임 유니폼이 아직 없어요."}
        im = imaging.load_image(str(pth))
        bg = Image.new("RGB", im.size, (235, 235, 235))      # 투명 배경 → 밝은 회색 (AI가 보기 쉽게)
        bg.paste(im, mask=im.getchannel("A") if im.mode == "RGBA" else None)
        self._kit = bg
        t = bg.copy()
        t.thumbnail((160, 160))
        return {"thumb": _data_url(t)}

    def _lang(self) -> str:
        return "en" if self._cfg.prompt_lang == "en" or self._cfg.ai_provider == "cloudflare" else "ko"

    def _hint(self, person: dict) -> str:
        return self._cfg.club_hints.get(str(person.get("club", "")).strip(), "")

    @_safe
    def build_prompt(self, person: dict, send_photo: bool, mode: str = "face", expression: str = "") -> str:
        if mode == "uniform":
            return prompts.uniform_prompt(person, lang=self._lang(), has_kit=self._kit is not None, club_hint=self._hint(person))
        clean, _ = _clean_uid(str(person.get("uid", "")))
        if clean and not person.get("look"):
            person = {**person, "look": gamesetup.appearance(clean)}
        text, _ = prompts.face_prompt(
            person, lang=self._lang(), template=self._cfg.prompt_template,
            has_ref=bool(send_photo) and self._work is not None, has_kit=self._kit is not None,
            expression=expression or self._cfg.expression, club_hint=self._hint(person),
            manager_outfit=self._cfg.manager_outfit, ref_mode=self._cfg.ref_mode)
        return text

    def _face_photos(self, send_photo: bool) -> list:
        photos = []
        if send_photo and self._work is not None:
            photos.append(self._work)
        if self._kit is not None:
            photos.append(self._kit)
        return photos

    @_safe
    def ai_web(self, pid: str, prompt: str, send_photo: bool, mode: str = "face") -> dict:
        """무료 웹 연동: 참고 사진+프롬프트를 클립보드에 함께 넣고 사이트 열기 (입력칸에 Ctrl+V 한 번)."""
        p = providers.BY_ID.get(pid)
        if not p or p["group"] != "free_web":
            return {"error": "웹 연동 방식이 아니에요."}
        ref = None
        files = []
        if mode == "uniform":
            if self._work is None:
                return {"error": "유니폼을 바꿀 선수 사진을 먼저 넣어 주세요."}
            ref = providers.save_reference(self._work, "선수사진")
            files = [ref]
            if self._kit is not None:
                files.append(providers.save_reference(self._kit, "유니폼"))
        else:
            if send_photo and self._work is not None:
                ref = providers.save_reference(self._work)
                files.append(ref)
            else:
                prompt = prompts.strip_ref(prompt)
            if self._kit is not None:
                files.append(providers.save_reference(self._kit, "유니폼"))
                ref = ref or files[-1]
        # 사이트는 붙여넣기 한 번에 파일과 글 중 하나만 받는다 → 사진 먼저, 프롬프트는 2단계
        clip = False
        try:
            clip = clipboard.set_files_and_text(files, "" if files else prompt)
        except Exception as e:  # noqa: BLE001
            log.warning("클립보드 실패: %s", e)
        if ref and not clip:
            providers.reveal(ref)
        webbrowser.open(p["url"])
        return {"ok": True, "clip": clip, "with_photo": bool(files), "files": len(files),
                "step2": bool(files), "prompt": prompt}

    @_safe
    def ai_generate(self, pid: str, prompt: str, send_photo: bool, mode: str = "face") -> dict:
        cfg = self._cfg.ai_cfg.get(pid, {})
        if mode == "uniform":
            if self._work is None:
                return {"error": "유니폼을 바꿀 선수 사진을 먼저 넣어 주세요."}
            if not providers.BY_ID.get(pid, {}).get("ref"):
                return {"error": "이 방식은 사진을 보낼 수 없어서 유니폼 바꾸기를 못 해요. 제미나이·챗GPT 등 다른 방식을 골라 주세요."}
            photos = [self._work] + ([self._kit] if self._kit is not None else [])
            try:
                im = providers.generate(pid, cfg, prompt, photos)
            except providers.ProviderError as e:
                if str(e) == "need_key":
                    return {"error": "need_key"}
                raise
            return self._set_photo(im, original=False)
        photos = self._face_photos(send_photo)
        if not providers.BY_ID.get(pid, {}).get("ref"):
            photos = []
        if not (send_photo and self._work is not None and photos):
            prompt = prompts.strip_ref(prompt)
        try:
            im = providers.generate(pid, cfg, prompt, photos or None)
        except providers.ProviderError as e:
            if str(e) == "need_key":
                return {"error": "need_key"}
            raise
        return self._set_photo(im, original=False)

    # ---------------------------------------------------------------- 대기열
    def _qfile(self) -> Path:
        return self._qdir / "queue.json"

    def _load_queue(self) -> list[dict]:
        try:
            items = json.loads(self._qfile().read_text(encoding="utf-8"))
        except Exception:
            return []
        return [it for it in items if Path(it.get("png", "")).exists()]

    def _save_queue(self) -> None:
        self._qfile().write_text(json.dumps(self._queue, ensure_ascii=False, indent=1), encoding="utf-8")

    def _queue_view(self) -> list[dict]:
        out = []
        for it in self._queue:
            d = {k: it.get(k) for k in ("id", "uid", "name", "club", "kind", "newgen")}
            d["thumb"] = _thumb_url(Path(it["png"]), 72)
            out.append(d)
        return out

    @_safe
    def add_to_queue(self, person: dict, box: list, deco: dict, replace: bool = False) -> dict:
        uid, prefixed = _clean_uid(person.get("uid"))
        if not uid:
            return {"error": "UID(숫자)를 입력하거나 검색 결과에서 인물을 선택해 주세요."}
        src = self._src()
        if src is None:
            return {"error": "먼저 사진을 불러오거나 AI로 만들어 주세요."}
        dup = [it for it in self._queue if it["uid"] == uid]
        if dup and not replace:
            return {"confirm": "duplicate"}
        b = imaging.clamp_box(src, *(float(v) for v in box))
        self._queue_put(person, uid, prefixed, src, b, deco)
        return {"queue": self._queue_view()}

    def _queue_put(self, person: dict, uid: str, prefixed: bool, src, box, deco: dict) -> dict:
        """사진 하나를 잘라 꾸며서 대기열에 넣는다 (같은 사람이 있으면 바꾼다)."""
        with self._qlock:
            return self._queue_put_locked(person, uid, prefixed, src, box, deco)

    def _queue_put_locked(self, person: dict, uid: str, prefixed: bool, src, box, deco: dict) -> dict:
        for it in [i for i in self._queue if i["uid"] == uid]:
            self._drop_files(it)
            self._queue.remove(it)
        out = decorate(imaging.render(src, box, int(self._cfg.output_size or 512)), Deco.from_dict(deco))
        iid = uuid.uuid4().hex
        png = self._qdir / f"{iid}.png"
        out.save(png, "PNG", optimize=True)
        srcf = self._qdir / f"{iid}_src.png"
        try:      # 대기 중인 사람을 다시 열면 자르기 전 사진부터 이어서 고칠 수 있게
            src.save(srcf, "PNG", compress_level=1)
        except Exception:  # noqa: BLE001
            srcf = None
        self._queue.append({
            "id": iid, "uid": uid, "name": str(person.get("name", "")).strip(),
            "club": str(person.get("club", "")).strip(), "kind": person.get("kind", "player"),
            "newgen": bool(person.get("newgen")) or prefixed, "png": str(png),
            "src": str(srcf) if srcf else "", "box": [float(v) for v in box],
        })
        if person.get("me") and uid != self._cfg.manager_uid:
            self._cfg.manager_uid = uid
            self._cfg.save()
        self._save_queue()
        return self._queue[-1]

    @staticmethod
    def _drop_files(it: dict) -> None:
        for k in ("png", "src"):
            if it.get(k):
                Path(it[k]).unlink(missing_ok=True)

    @_safe
    def load_queued(self, uid: str) -> dict:
        """대기열에 있는 사람: 대기열에 넣었던 사진(자르기 전)과 자른 틀을 편집기로."""
        clean, _ = _clean_uid(uid)
        it = next((i for i in reversed(self._queue) if i["uid"] == clean), None)
        if not it:
            return {"error": "대기열에 없어요."}
        if it.get("src") and Path(it["src"]).exists():
            im = imaging.load_image(it["src"])
            out = self._set_photo(im, original=True)
            if im.mode == "RGBA" and im.getchannel("A").getextrema()[0] < 255:   # 배경 지운 사진이었다
                with self._lock:
                    self._nobg = im
                out = self._photo_payload()
            if it.get("box") and isinstance(out, dict):
                out["box"] = list(it["box"])
        else:      # 예전 대기열(원본을 안 남김) → 완성 사진이라도
            out = self._set_photo(imaging.load_image(it["png"]), original=True)
        if isinstance(out, dict):
            out["queued"] = True
        return out

    def _quick_args(self, src, person: dict):
        """대량 바꾸기·카드에 끌어다 놓기: 자르기와 꾸미기 설정대로."""
        if self._cfg.bulk_crop == "keep":
            w, h = src.size
            side = float(min(w, h))
            box = (w / 2, side / 2 if h > w else h / 2, side)       # 세로 사진은 위쪽(머리)에 맞춘다
        else:
            box = imaging.auto_box(src)
        deco = dict(self._cfg.deco or {}) if self._cfg.bulk_deco == "follow" else {}
        deco["text"] = str(person.get("name", "")).strip()
        return box, deco

    @_safe
    def quick_add(self, person: dict, data_url: str) -> dict:
        """카드에 사진을 끌어다 놓았을 때: 얼굴 맞춤으로 자르고 지금 꾸미기 설정으로 바로 대기열에."""
        uid, prefixed = _clean_uid(person.get("uid"))
        if not uid:
            return {"error": "이 사람의 UID를 알 수 없어요."}
        src = _from_data_url(data_url)
        box, deco = self._quick_args(src, person)
        it = self._queue_put(person, uid, prefixed, src, box, deco)
        return {"queue": self._queue_view(), "thumb": _thumb_url(Path(it["png"]), 160), "uid": uid}

    # ---------------------------------------------------------------- 대량 사진 바꾸기
    _IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}

    def _match_name(self, stem: str) -> dict:
        """파일 이름 → 사람. 규칙은 하나: 목록에 보이는 이름 그대로.
        뒤 번호(1, (2))는 떼고, ① 똑같은 이름 → ② 악센트·대소문자·하이픈 무시 → ③ 순서 무시 순으로
        앞 단계에서 못 찾았을 때만 다음 단계로 넘어간다 (순서만 다른 다른 사람이 섞이지 않게)."""
        name = name_key(stem)
        if not name or not self._people.items:
            return {"status": "none", "how": "", "candidates": [], "key": ""}
        k1, k2, k3 = name, loose_key(name), order_key(name)
        idx = self._name_index()
        hit, how = list(idx[0].get(k1, [])), "exact"
        if not hit:
            hit, how = list(idx[1].get(k2, [])), "loose"
        if not hit:
            hit, how = list(idx[2].get(k3, [])), "order"
        if not hit:
            return {"status": "none", "how": "", "candidates": [], "key": k3}
        hit.sort(key=lambda p: (not p.get("me"), not p.get("mine"), bool(p.get("alt")), p.get("kind") != "player"))
        cands = [self._cand(p) for p in hit[:12]]
        status = "ok" if len(hit) == 1 and how != "order" else "multi"
        return {"status": status, "how": how, "candidates": cands, "key": k3}

    def _name_index(self):
        """이름 → 사람 목록 (세 단계용). 세이브를 새로 읽으면 다시 만든다."""
        items = self._people.items
        key = (id(items), len(items))
        if getattr(self, "_nidx_key", None) != key:
            a, b, c = {}, {}, {}
            for p in items:
                n = name_key(p.get("name"))
                if not n:
                    continue
                a.setdefault(n, []).append(p)
                b.setdefault(loose_key(n), []).append(p)
                c.setdefault(order_key(n), []).append(p)
            self._nidx, self._nidx_key = (a, b, c), key
        return self._nidx

    @staticmethod
    def _cand(p: dict) -> dict:
        return {k: p.get(k, "") for k in ("uid", "name", "club", "age", "kind", "newgen", "me", "alt", "squad")}

    @_safe
    def bulk_match(self, names: list) -> dict:
        """파일 이름 목록을 사람과 짝짓는다 (끌어다 놓은 파일용)."""
        return {"rows": [{"file": n, **self._match_name(Path(str(n)).stem)} for n in names],
                "loaded": bool(self._people.items)}

    @_safe
    def bulk_pick_folder(self) -> dict:
        """폴더를 고르면 안의 사진 파일을 모두 짝지어 돌려준다."""
        if not self._window:
            return {"error": "창이 없어요."}
        import webview
        r = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if not r:
            return {"cancel": True}
        return self.bulk_scan(str(r[0] if isinstance(r, (list, tuple)) else r))

    @_safe
    def bulk_scan(self, folder: str) -> dict:
        """폴더 안 사진을 (다시) 읽어 짝짓는다. 파일 이름을 고친 뒤 '다시 읽기'에도 쓴다."""
        folder = Path(folder)
        if not folder.is_dir():
            return {"error": f"폴더를 찾을 수 없어요: {folder}"}
        files = sorted((p for p in folder.iterdir() if p.suffix.lower() in self._IMG_EXT), key=lambda p: p.name.lower())[:1000]
        rows = []
        for f in files:
            row = {"file": f.name, "path": str(f), **self._match_name(f.stem)}
            try:
                row["thumb"] = _thumb_url(f, 72)
            except Exception:  # noqa: BLE001
                row["thumb"] = ""
            rows.append(row)
        return {"rows": rows, "folder": str(folder), "loaded": bool(self._people.items)}

    @_safe
    def bulk_add_one(self, person: dict, path: str = "", data_url: str = "") -> dict:
        """대량 바꾸기의 한 줄: 얼굴 맞춤으로 자르고 지금 꾸미기로 대기열에."""
        uid, prefixed = _clean_uid(person.get("uid"))
        if not uid:
            return {"error": "UID가 없어요."}
        src = imaging.load_image(path) if path else _from_data_url(data_url)
        box, deco = self._quick_args(src, person)
        self._queue_put(person, uid, prefixed, src, box, deco)
        return {"ok": True, "count": len(self._queue)}

    @_safe
    def queue_view(self) -> dict:
        return {"queue": self._queue_view()}

    @_safe
    def queue_remove(self, ids: list[str]) -> dict:
        ids = set(ids)
        with self._qlock:
            for it in [i for i in self._queue if i["id"] in ids]:
                self._drop_files(it)
                self._queue.remove(it)
            self._save_queue()
        return {"queue": self._queue_view()}

    @_safe
    def queue_clear(self) -> dict:
        return self.queue_remove([i["id"] for i in self._queue])

    @_safe
    def apply_all(self, force: bool = False) -> dict:
        if not self._queue:
            return {"error": "대기열이 비어 있어요."}
        gdir = Path(self._cfg.graphics_dir)
        if not gdir.parent.exists():
            return {"error": f"FM27 사용자 폴더를 찾지 못했어요: {gdir.parent}\n설정에서 graphics 폴더를 지정해 주세요."}
        hb = gamesetup.heartbeat()
        live = bool(hb and hb.get("alive"))
        if not force and not live and fm_running():
            return {"confirm": "fm_running"}
        items = list(self._queue)
        pairs = [(FaceEntry(it["uid"], bool(it["newgen"]), it.get("name", ""), it.get("club", ""),
                            it.get("kind", "player")), Path(it["png"])) for it in items]
        self._pack().apply(pairs)
        conflicts = find_conflicts(gdir, self._cfg.pack_dir, {it["uid"] for it in items})
        pack = self._pack()
        for it in items:
            self._index.map[it["uid"]] = {"path": str(pack.image_path(it["uid"])), "pack": pack.dir.name,
                                          "ours": True, "regen": bool(it["newgen"])}
        names = {it["uid"]: it.get("name") or it["uid"] for it in items}
        for it in items:
            self._drop_files(it)
        done = {it["id"] for it in items}
        with self._qlock:
            self._queue = [i for i in self._queue if i["id"] not in done]
            self._save_queue()
        self._sync_manager()
        refresh = None
        if self._cfg.auto_refresh and gamesetup.heartbeat() and gamesetup.heartbeat().get("alive"):
            refresh = gamesetup.command("refresh", timeout=30)
        return {
            "count": len(items), "queue": self._queue_view(), "refresh": refresh,
            "conflicts": self._conflict_view(conflicts, names),
        }

    # ---------------------------------------------------------------- 내 감독 사진 (플러그인)
    def _manager_uid(self) -> str | None:
        for p in getattr(self._people, "items", []) or []:
            if p.get("me"):
                return str(p.get("uid")).removeprefix("r-")
        return self._cfg.manager_uid or None

    def _sync_manager(self) -> None:
        """내 감독 사진이 적용돼 있으면 플러그인용 파일을 맞춰 둔다. 감독 사진은 config.xml로는 안 바뀐다."""
        try:
            uid = self._manager_uid()
            raw = gamesetup.manager_photo_path()
            img = self._pack().image_path(uid) if uid else None
            if img is not None and img.exists():
                if not raw.exists() or raw.stat().st_mtime < img.stat().st_mtime:
                    gamesetup.write_manager_photo(img)
            elif uid and raw.exists():
                gamesetup.clear_manager_photo()
        except Exception as e:  # noqa: BLE001
            log.warning("감독 사진 동기화 실패: %s", e)

    # ---------------------------------------------------------------- 적용된 얼굴
    @_safe
    def applied_list(self) -> list[dict]:
        pack = self._pack()
        res = []
        for e in sorted(pack.entries(), key=lambda x: (x.name or "~", x.uid)):
            res.append({"uid": e.uid, "name": e.name, "club": e.club, "kind": e.kind, "newgen": e.newgen,
                        "thumb": _thumb_url(pack.image_path(e.uid), 120)})
        return res

    # 한 장씩 지우기: 바로 지우지 않고 몇 초 기다렸다가 지운다 (그 사이 되돌리기 가능)
    @_safe
    def applied_remove_later(self, uid: str, seconds: float = 6) -> dict:
        import time as _t
        with self._lock:
            if not hasattr(self, "_pend"):
                self._pend = {}
                threading.Thread(target=self._pend_loop, daemon=True).start()
            self._pend[str(uid)] = _t.time() + float(seconds)
        return {"ok": True}

    @_safe
    def applied_undo(self, uid: str) -> dict:
        with self._lock:
            ok = getattr(self, "_pend", {}).pop(str(uid), None) is not None
        return {"ok": ok}

    def _pend_loop(self) -> None:
        import time as _t
        while True:
            _t.sleep(0.3)
            try:
                with self._lock:
                    now = _t.time()
                    due = [u for u, t in self._pend.items() if t <= now]
                    for u in due:
                        self._pend.pop(u, None)
                    more = bool(self._pend)
                if due:
                    self._remove_now(due)
                    if not more:
                        self._refresh_game()
            except Exception as e:  # noqa: BLE001
                log.warning("삭제 처리 실패: %s", e)

    def flush_deletes(self) -> None:
        with self._lock:
            due = list(getattr(self, "_pend", {}))
            if hasattr(self, "_pend"):
                self._pend.clear()
        if due:
            self._remove_now(due, rebuild=False)

    def _refresh_game(self) -> None:
        hb = gamesetup.heartbeat()
        if self._cfg.auto_refresh and hb and hb.get("alive"):
            gamesetup.command("refresh", timeout=30)

    def _remove_now(self, uids: list[str], rebuild: bool = True) -> None:
        self._pack().remove([str(u) for u in uids])
        for u in uids:
            if (self._index.map.get(str(u)) or {}).get("ours"):
                self._index.map.pop(str(u), None)
        if rebuild:
            threading.Thread(target=lambda: self._index.build(self._cfg.graphics_dir, force=True), daemon=True).start()
        self._sync_manager()

    @_safe
    def applied_remove(self, uids: list[str]) -> list[dict]:
        self._pack().remove([str(u) for u in uids])
        for u in uids:
            if (self._index.map.get(str(u)) or {}).get("ours"):
                self._index.map.pop(str(u), None)
        threading.Thread(target=lambda: self._index.build(self._cfg.graphics_dir, force=True), daemon=True).start()
        self._sync_manager()
        return self.applied_list()

    @_safe
    def applied_edit(self, uid: str) -> dict:
        pack = self._pack()
        e = next((x for x in pack.entries() if x.uid == str(uid)), None)
        if not e:
            return {"error": "찾을 수 없어요."}
        payload = {"person": {"uid": e.uid, "name": e.name, "club": e.club, "kind": e.kind,
                              "newgen": e.newgen, "age": "", "nationality": ""}}
        img = pack.image_path(e.uid)
        if img.exists():
            payload["photo"] = self.load_image_path(str(img))
        return payload

    @_safe
    def check_conflicts(self) -> list[dict]:
        pack = self._pack()
        entries = {e.uid: e for e in pack.entries()}
        found = find_conflicts(Path(self._cfg.graphics_dir), self._cfg.pack_dir, set(entries))
        return self._conflict_view(found, {u: e.name or u for u, e in entries.items()})

    @_safe
    def conflict_report(self) -> dict:
        """내 사진과 같은 사람을 지정한 다른 팩을 모두 찾아, 팩별로 이김/짐을 묶는다."""
        from .settings import pack_sort_key
        root = Path(self._cfg.graphics_dir)
        pack = self._pack()
        mine = {e.uid: e for e in pack.entries()}
        if not mine:
            return {"total": 0, "groups": []}
        ours_dir = pack.dir.resolve()
        ours_key = pack_sort_key(pack.dir.name)
        groups: dict[str, dict] = {}
        cfgs = faceindex.FaceIndex._configs(root)
        for cfg, uid, ent in faceindex.iter_records(root, cfgs):
            if uid not in mine or cfg.parent.resolve() == ours_dir:
                continue
            top = faceindex.top_folder(root, cfg)
            g = groups.setdefault(top, {"pack": top, "dir": str(root / top), "win": pack_sort_key(top) <= ours_key,
                                        "items": [], "_seen": set()})
            if uid in g["_seen"]:
                continue
            g["_seen"].add(uid)
            g["items"].append({"uid": uid, "name": mine[uid].name or uid, "other": ent["path"],
                               "mine": str(pack.image_path(uid))})
        out = []
        for g in groups.values():
            g.pop("_seen")
            g["items"].sort(key=lambda x: x["name"])
            out.append(g)
        out.sort(key=lambda g: (g["win"], -len(g["items"])))
        hit = {i["uid"] for g in out for i in g["items"]}
        lost = {i["uid"] for g in out if not g["win"] for i in g["items"]}
        return {"total": len(mine), "overlap": len(hit), "lost": len(lost), "groups": out, "ours": pack.dir.name}

    @_safe
    def thumbs(self, paths: list[str]) -> dict:
        """작은 미리보기 (graphics 폴더 안 파일만)."""
        g = Path(self._cfg.graphics_dir).resolve()
        out = {}
        for p in paths[:200]:
            try:
                rp = Path(p).resolve()
                if g in rp.parents:
                    out[p] = _thumb_url(rp, 64)
            except Exception:  # noqa: BLE001
                out[p] = ""
        return out

    def _conflict_view(self, found: dict, names: dict) -> list[dict]:
        g = Path(self._cfg.graphics_dir)

        def rel(p):
            try:
                return str(Path(p).relative_to(g))
            except ValueError:
                return str(p)
        return [{"uid": u, "name": names.get(u, u), "packs": [rel(p) for p in ps], "dirs": list(ps)}
                for u, ps in found.items()]

    @_safe
    def open_dir(self, path: str) -> bool:
        """겹치는 페이스팩 폴더 열기 (graphics 폴더 안만)."""
        d = Path(path)
        g = Path(self._cfg.graphics_dir).resolve()
        if d.is_dir() and (d.resolve() == g or g in d.resolve().parents) and sys.platform == "win32":
            os.startfile(d)  # type: ignore[attr-defined]
            return True
        return False
