"""화면(HTML)에서 부르는 기능 모음. pywebview가 window.pywebview.api 로 노출한다.

주의: pywebview는 공개 속성을 모두 화면에 노출하려고 훑기 때문에, 내부 상태는 전부 _로 시작.
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import threading
import traceback
import uuid
from pathlib import Path

from PIL import Image

from . import imaging
from .gemini import GeminiError, generate
from .pack import FaceEntry, FacePack, find_conflicts, fm_running, looks_like_newgen
from .people import People
from .settings import DEFAULT_PROMPT, GEMINI_MODELS, REF_SENTENCE, Settings, app_data_dir

VERSION = "0.3.2"
DISPLAY_MAX = 1400   # 화면에 보낼 편집용 사진 최대 크기


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
    from PIL import ImageOps
    return ImageOps.exif_transpose(im).convert("RGBA")


def _thumb_url(path: Path, size: int = 96) -> str:
    try:
        return _data_url(imaging.thumbnail(Image.open(path), size))
    except Exception:
        return ""


def _safe(fn):
    """예외를 {'error': ...}로 바꿔 화면에 전달."""
    def wrap(self, *a, **k):
        try:
            return fn(self, *a, **k)
        except GeminiError as e:
            return {"error": str(e)}
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return {"error": f"{type(e).__name__}: {e}"}
    wrap.__name__ = fn.__name__
    return wrap


class Api:
    def __init__(self) -> None:
        self._cfg = Settings()
        self._people = People()
        self._lock = threading.Lock()
        self._orig: Image.Image | None = None
        self._work: Image.Image | None = None
        self._nobg: Image.Image | None = None
        self._window = None
        self._qdir = app_data_dir() / "queue"
        self._qdir.mkdir(exist_ok=True)
        self._queue: list[dict] = self._load_queue()
        self._load_people()

    def _set_window(self, w) -> None:
        self._window = w

    # ---------------------------------------------------------------- 상태
    def _pack(self) -> FacePack:
        return FacePack(self._cfg.pack_dir)

    def _load_people(self) -> str:
        p = Path(self._cfg.people_file)
        if not p.exists():
            self._people = People()
            return "missing"
        try:
            self._people.load(p)
            return "ok"
        except Exception as e:  # noqa: BLE001
            return f"error: {e}"

    def _people_info(self) -> dict:
        n = len(self._people.items)
        return {"loaded": n > 0, "count": n, "path": self._cfg.people_file}

    @_safe
    def get_state(self) -> dict:
        c = self._cfg
        return {
            "version": VERSION,
            "settings": {
                "graphics_dir": c.graphics_dir, "people_file": c.people_file, "output_size": c.output_size,
                "gemini_key": c.gemini_key, "gemini_model": c.gemini_model,
                "prompt_template": c.prompt_template, "send_photo": c.send_photo,
            },
            "models": GEMINI_MODELS,
            "default_prompt": DEFAULT_PROMPT,
            "people": self._people_info(),
            "queue": self._queue_view(),
            "rembg": imaging.rembg_available(),
            "pack_dir": str(c.pack_dir),
        }

    @_safe
    def save_settings(self, s: dict) -> dict:
        c = self._cfg
        c.graphics_dir = str(s.get("graphics_dir", c.graphics_dir)).strip()
        c.people_file = str(s.get("people_file", c.people_file)).strip()
        try:
            c.output_size = max(100, min(512, int(s.get("output_size", c.output_size))))
        except (TypeError, ValueError):
            c.output_size = 250
        c.gemini_key = str(s.get("gemini_key", "")).strip()
        c.gemini_model = str(s.get("gemini_model", "")).strip() or GEMINI_MODELS[0]
        c.prompt_template = str(s.get("prompt_template", "")).strip() or DEFAULT_PROMPT
        if "send_photo" in s:
            c.send_photo = bool(s["send_photo"])
        c.save()
        self._load_people()
        return self.get_state()

    @_safe
    def pick_folder(self, initial: str = "") -> str | None:
        if not self._window:
            return None
        import webview
        r = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=initial or "")
        return r[0] if r else None

    @_safe
    def pick_file(self, kind: str = "json") -> str | None:
        if not self._window:
            return None
        import webview
        types = ("JSON (*.json)",) if kind == "json" else ("이미지 (*.png;*.jpg;*.jpeg;*.webp;*.bmp)",)
        r = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=types)
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
        import webbrowser
        if url.startswith("https://"):
            webbrowser.open(url)
        return True

    # ---------------------------------------------------------------- 검색
    @_safe
    def reload_people(self) -> dict:
        status = self._load_people()
        info = self._people_info()
        info["status"] = status
        return info

    @_safe
    def search(self, query: str, kind: str) -> list[dict]:
        pack = self._pack()
        applied = {e.uid for e in pack.entries()}
        res = []
        for p in self._people.search(query, kind, limit=150):
            d = {"uid": p.uid, "name": p.name, "club": p.club, "age": p.age,
                 "nationality": p.nationality, "kind": p.kind, "newgen": p.newgen, "face": ""}
            if p.uid in applied:
                d["face"] = _thumb_url(pack.image_path(p.uid), 72)
            res.append(d)
        return res

    @_safe
    def guess_newgen(self, uid: str) -> bool:
        return looks_like_newgen(str(uid).strip())

    # ---------------------------------------------------------------- 사진
    def _photo_payload(self) -> dict:
        src = self._nobg if self._nobg is not None else self._work
        disp = src.copy()
        disp.thumbnail((DISPLAY_MAX, DISPLAY_MAX), Image.LANCZOS)
        transparent = self._nobg is not None
        return {
            "url": _data_url(disp) if transparent else _data_url(disp, "JPEG", 90),
            "w": src.width, "h": src.height,
            "box": list(imaging.auto_box(self._work)),
            "nobg": transparent,
            "is_original": self._work is self._orig,
        }

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
    def set_nobg(self, on: bool) -> dict:
        if self._work is None:
            return {"error": "사진이 없어요."}
        if on and self._nobg is None:
            if not imaging.rembg_available():
                return {"error": "배경 제거 기능이 설치되지 않았어요. '배경제거_설치.bat'을 실행해 주세요."}
            work = self._work
            out = imaging.remove_background(work)
            if work is self._work:
                self._nobg = out
        elif not on:
            self._nobg = None
        payload = self._photo_payload()
        payload.pop("box")   # 자르기 위치는 화면이 가진 값 유지
        return payload

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
    def ai_generate(self, prompt: str, send_photo: bool) -> dict:
        c = self._cfg
        if not c.gemini_key.strip():
            return {"error": "need_key"}
        photo = self._work if (send_photo and self._work is not None) else None
        if not send_photo:
            prompt = prompt.replace(REF_SENTENCE, "").replace(REF_SENTENCE.strip(), "").strip()
        im = generate(c.gemini_key, c.gemini_model, prompt, photo)
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
    def add_to_queue(self, person: dict, box: list, replace: bool = False) -> dict:
        uid = str(person.get("uid", "")).strip()
        if not uid.isdigit():
            return {"error": "UID(숫자)를 입력하거나 검색 결과에서 인물을 선택해 주세요."}
        src = self._nobg if self._nobg is not None else self._work
        if src is None:
            return {"error": "먼저 사진을 불러오거나 AI로 만들어 주세요."}
        dup = [it for it in self._queue if it["uid"] == uid]
        if dup and not replace:
            return {"confirm": "duplicate"}
        for it in dup:
            Path(it["png"]).unlink(missing_ok=True)
            self._queue.remove(it)
        cx, cy, side = (float(v) for v in box)
        b = imaging.clamp_box(src, cx, cy, side)
        out = imaging.render(src, b, int(self._cfg.output_size or 250))
        iid = uuid.uuid4().hex
        png = self._qdir / f"{iid}.png"
        out.save(png, "PNG", optimize=True)
        self._queue.append({
            "id": iid, "uid": uid, "name": str(person.get("name", "")).strip(),
            "club": str(person.get("club", "")).strip(), "kind": person.get("kind", "player"),
            "newgen": bool(person.get("newgen")), "png": str(png),
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
