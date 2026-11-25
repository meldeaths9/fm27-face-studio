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

from . import ai_models, imaging, providers, savedata
from .pack import FaceEntry, FacePack, find_conflicts, fm_running, looks_like_newgen
from .people import People
from .settings import DEFAULT_PROMPT, REF_SENTENCE, Settings, app_data_dir
from .style import STYLE_LABELS, Deco, decorate

VERSION = "0.4.0"
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


class Api:
    def __init__(self) -> None:
        self._cfg = Settings()
        self._people = People()
        self._people.set(savedata.load_cache(self._cfg.last_save) if self._cfg.last_save else None)
        self._lock = threading.Lock()
        self._orig: Image.Image | None = None
        self._work: Image.Image | None = None
        self._nobg: Image.Image | None = None
        self._progress = {"task": "", "done": 0, "total": 0}
        self._window = None
        self._qdir = app_data_dir() / "queue"
        self._qdir.mkdir(exist_ok=True)
        self._queue: list[dict] = self._load_queue()

    def _set_window(self, w) -> None:
        self._window = w

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
                "ai_provider": c.ai_provider, "deco": c.deco,
            },
            "ai": self._ai_view(),
            "styles": STYLE_LABELS,
            "default_prompt": DEFAULT_PROMPT,
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
            c.prompt_template = str(s["prompt_template"]).strip() or DEFAULT_PROMPT
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
    def build_prompt(self, person: dict, send_photo: bool) -> str:
        age = str(person.get("age", "")).strip()
        nat = str(person.get("nationality", "")).strip()
        kind = person.get("kind", "player")
        has_photo = bool(send_photo) and self._work is not None
        vars_ = {
            "ref": REF_SENTENCE if has_photo else "",
            "role": "professional football player" if kind == "player" else "football club coach",
            "age_text": f"{age} years old" if age else "",
            "nationality_text": (", " if age and nat else "") + (f"from {nat}" if nat else ""),
            "name": str(person.get("name", "")).strip(), "club": str(person.get("club", "")).strip(),
            "age": age, "nationality": nat,
        }
        tpl = self._cfg.prompt_template or DEFAULT_PROMPT
        try:
            text = tpl.format(**vars_)
        except (KeyError, IndexError, ValueError):
            text = tpl
        for a, b in ((" ,", ","), (", .", "."), ("a , ", "a "), ("  ", " ")):
            text = text.replace(a, b)
        return text.strip()

    @_safe
    def ai_web(self, pid: str, send_photo: bool) -> dict:
        """무료 웹 연동: 사이트 열기 + (참고 사진이 있으면) 파일로 저장해서 탐색기로 보여주기."""
        p = providers.BY_ID.get(pid)
        if not p or p["group"] != "free_web":
            return {"error": "웹 연동 방식이 아니에요."}
        ref = None
        if send_photo and self._work is not None:
            ref = providers.save_reference(self._work)
            providers.reveal(ref)
        webbrowser.open(p["url"])
        return {"ok": True, "ref": str(ref) if ref else ""}

    @_safe
    def ai_generate(self, pid: str, prompt: str, send_photo: bool) -> dict:
        cfg = self._cfg.ai_cfg.get(pid, {})
        photo = self._work if (send_photo and self._work is not None) else None
        if photo is None or not providers.BY_ID.get(pid, {}).get("ref"):
            prompt = prompt.replace(REF_SENTENCE, "").replace(REF_SENTENCE.strip(), "").strip()
        try:
            im = providers.generate(pid, cfg, prompt, photo)
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
        if not force and fm_running():
            return {"confirm": "fm_running"}
        items = list(self._queue)
        pairs = [(FaceEntry(it["uid"], bool(it["newgen"]), it.get("name", ""), it.get("club", ""),
                            it.get("kind", "player")), Path(it["png"])) for it in items]
        self._pack().apply(pairs)
        conflicts = find_conflicts(gdir, self._cfg.pack_dir, {it["uid"] for it in items})
        names = {it["uid"]: it.get("name") or it["uid"] for it in items}
        for it in items:
            Path(it["png"]).unlink(missing_ok=True)
        done = {it["id"] for it in items}
        self._queue = [i for i in self._queue if i["id"] not in done]
        self._save_queue()
        return {
            "count": len(items), "queue": self._queue_view(),
            "conflicts": [{"uid": u, "name": names.get(u, u), "packs": [Path(p).parent.name for p in ps]}
                          for u, ps in conflicts.items()],
        }

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
