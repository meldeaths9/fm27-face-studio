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

from . import ai_models, appearance, clipboard, faceindex, gamesetup, imaging, prompts, providers, savedata
from .pack import FaceEntry, FacePack, find_conflicts, fm_running, looks_like_newgen
from .people import People
from .settings import Settings, app_data_dir
from .style import STYLE_LABELS, Deco, decorate

VERSION = "0.8.2"
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


class Api:
    def __init__(self) -> None:
        self._cfg = Settings()
        self._people = People()
        self._people.set(savedata.load_cache(self._cfg.last_save) if self._cfg.last_save else None)
        self._lock = threading.Lock()
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
        threading.Thread(target=lambda: self._index.build(self._cfg.graphics_dir), daemon=True).start()
        threading.Thread(target=self._maybe_reload, daemon=True).start()

    def _set_window(self, w) -> None:
        self._window = w
        self._maxed = False
        try:
            w.events.maximized += lambda *a: setattr(self, "_maxed", True)
            w.events.restored += lambda *a: setattr(self, "_maxed", False)
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
            w.maximize()
            self._maxed = True
        return self._maxed

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
            "version": VERSION,
            "settings": {
                "graphics_dir": c.graphics_dir, "output_size": c.output_size,
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
    def browse(self, name: str, team: str, kind: str, filt: str = "all", offset: int = 0, limit: int = 50,
               squad: str = "") -> dict:
        idx = self._index
        limit = min(int(limit), BROWSE_MAX)
        offset = 0
        items = self._people.search(name, team, kind, limit=100000, mine_if_empty=True, squad=squad)
        def face_of(p):
            return idx.get(p["uid"])
        if filt == "none":
            items = [p for p in items if not face_of(p)]
        elif filt == "has":
            items = [p for p in items if face_of(p)]
        elif filt == "ours":
            items = [p for p in items if (face_of(p) or {}).get("ours")]
        page = []
        for p in items[int(offset):int(offset) + int(limit)]:
            f = face_of(p)
            d = dict(p)
            d["face"] = self._face_thumb(f["path"]) if f else ""
            d["face_state"] = "ours" if f and f.get("ours") else "has" if f else "none"
            d["pack"] = f["pack"] if f else ""
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
    def open_diag_folder(self) -> bool:
        d = gamesetup.diag_dir()
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
        elif key == "follow_save":
            self._cfg.follow_save = bool(value)
            if value:
                threading.Thread(target=self._maybe_reload, daemon=True).start()
        elif key == "game_dir" and gamesetup.valid_game(value):
            self._cfg.game_dir = str(value)
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
        for it in dup:
            Path(it["png"]).unlink(missing_ok=True)
            self._queue.remove(it)
        b = imaging.clamp_box(src, *(float(v) for v in box))
        out = decorate(imaging.render(src, b, int(self._cfg.output_size or 512)), Deco.from_dict(deco))
        iid = uuid.uuid4().hex
        png = self._qdir / f"{iid}.png"
        out.save(png, "PNG", optimize=True)
        self._queue.append({
            "id": iid, "uid": uid, "name": str(person.get("name", "")).strip(),
            "club": str(person.get("club", "")).strip(), "kind": person.get("kind", "player"),
            "newgen": bool(person.get("newgen")) or prefixed, "png": str(png),
        })
        if person.get("me") and uid != self._cfg.manager_uid:
            self._cfg.manager_uid = uid
            self._cfg.save()
        self._save_queue()
        return {"queue": self._queue_view()}

    @_safe
    def queue_remove(self, ids: list[str]) -> dict:
        ids = set(ids)
        for it in [i for i in self._queue if i["id"] in ids]:
            Path(it["png"]).unlink(missing_ok=True)
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
            Path(it["png"]).unlink(missing_ok=True)
        done = {it["id"] for it in items}
        self._queue = [i for i in self._queue if i["id"] not in done]
        self._save_queue()
        self._sync_manager()
        refresh = None
        if self._cfg.auto_refresh and gamesetup.heartbeat() and gamesetup.heartbeat().get("alive"):
            refresh = gamesetup.command("refresh", timeout=30)
        return {
            "count": len(items), "queue": self._queue_view(), "refresh": refresh,
            "conflicts": [{"uid": u, "name": names.get(u, u), "packs": [Path(p).parent.name for p in ps]}
                          for u, ps in conflicts.items()],
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
        return [{"uid": u, "name": entries[u].name or u, "packs": ps} for u, ps in found.items()]
