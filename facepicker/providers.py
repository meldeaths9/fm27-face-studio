"""AI 그림 연결: 무료 웹 연동 / 무료 자동(Cloudflare) / 구독(ChatGPT Codex CLI) / API 키.

모든 자동 방식은 generate(...) -> PIL.Image 하나로 통일한다.
"""
from __future__ import annotations

import base64
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from PIL import Image

from . import gemini

PROVIDERS = [
    # id, 이름, 묶음, 사진 참고 가능, 설명
    {"id": "web_gemini", "name": "제미나이 웹", "group": "free_web", "ref": True,
     "url": "https://gemini.google.com/app", "desc": "프롬프트를 복사하고 제미나이를 열어요. 무료 계정으로 하루 여러 장."},
    {"id": "web_grok", "name": "그록 웹", "group": "free_web", "ref": True,
     "url": "https://grok.com/imagine", "desc": "프롬프트를 복사하고 그록을 열어요."},
    {"id": "cloudflare", "name": "Cloudflare (FLUX)", "group": "free_auto", "ref": False,
     "desc": "무료 계정만 있으면 버튼 하나로 자동 생성. 하루 무료 사용량 안에서. 참고 사진은 못 보내요."},
    {"id": "codex", "name": "ChatGPT 구독 (Codex CLI)", "group": "sub", "ref": True,
     "desc": "ChatGPT 구독 사용량으로 생성. Codex CLI 설치와 로그인이 필요해요. (실험 기능)"},
    {"id": "gemini", "name": "Google Gemini API", "group": "api", "ref": True,
     "desc": "쓴 만큼 요금. 결제를 등록한 키가 필요해요."},
    {"id": "openai", "name": "OpenAI API", "group": "api", "ref": True,
     "desc": "쓴 만큼 요금 (gpt-image)."},
    {"id": "xai", "name": "xAI (그록) API", "group": "api", "ref": False,
     "desc": "쓴 만큼 요금 (Grok Imagine)."},
]
BY_ID = {p["id"]: p for p in PROVIDERS}
DEFAULT_MODELS = {
    "gemini": "gemini-3.1-flash-image",
    "openai": "gpt-image-2",
    "xai": "grok-imagine-image-2.0",
    "cloudflare": "@cf/black-forest-labs/flux-1-schnell",
}


class ProviderError(Exception):
    pass


def _http(url: str, body: bytes, headers: dict, timeout: int = 180) -> dict:
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="ignore")
        try:
            j = json.loads(raw)
            msg = (j.get("error") or {}).get("message") if isinstance(j.get("error"), dict) else None
            msg = msg or j.get("error") or (j.get("errors") or [{}])[0].get("message") or raw[:400]
        except Exception:
            msg = raw[:400]
        raise ProviderError(f"HTTP {e.code}: {msg}") from None
    except urllib.error.URLError as e:
        raise ProviderError(f"연결 실패: {e.reason}") from None


def _multipart(fields: dict, files: list[tuple[str, str, bytes, str]]) -> tuple[bytes, str]:
    boundary = "----fs" + uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for name, filename, data, mime in files:
        out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                  f"Content-Type: {mime}\r\n\r\n".encode())
        out.write(data)
        out.write(b"\r\n")
    out.write(f"--{boundary}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


def _png_bytes(im: Image.Image, max_side: int = 1024) -> bytes:
    im = im.convert("RGB")
    im.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _b64_image(data: str) -> Image.Image:
    if "," in data[:80]:
        data = data.split(",", 1)[1]
    return Image.open(io.BytesIO(base64.b64decode(data))).convert("RGBA")


def _fetch_image(url: str) -> Image.Image:
    req = urllib.request.Request(url, headers={"User-Agent": "FM27FaceStudio"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return Image.open(io.BytesIO(r.read())).convert("RGBA")


def _images_response(j: dict) -> Image.Image:
    for item in j.get("data") or []:
        if item.get("b64_json"):
            return _b64_image(item["b64_json"])
        if item.get("url"):
            return _fetch_image(item["url"])
    raise ProviderError("이미지가 오지 않았어요: " + json.dumps(j, ensure_ascii=False)[:300])


# ------------------------------------------------------------------ 자동 방식들
def _photos(photo) -> list:
    if photo is None:
        return []
    return [p for p in (photo if isinstance(photo, (list, tuple)) else [photo]) if p is not None]


def gen_openai(cfg: dict, prompt: str, photo) -> Image.Image:
    key = cfg.get("key", "").strip()
    if not key:
        raise ProviderError("need_key")
    model = cfg.get("model") or DEFAULT_MODELS["openai"]
    headers = {"Authorization": f"Bearer {key}"}
    photos = _photos(photo)
    if photos:
        body, ctype = _multipart({"model": model, "prompt": prompt, "size": "1024x1024"},
                                 [("image[]", f"ref{i}.png", _png_bytes(ph), "image/png") for i, ph in enumerate(photos)])
        headers["Content-Type"] = ctype
        return _images_response(_http("https://api.openai.com/v1/images/edits", body, headers))
    headers["Content-Type"] = "application/json"
    body = json.dumps({"model": model, "prompt": prompt, "size": "1024x1024"}).encode()
    return _images_response(_http("https://api.openai.com/v1/images/generations", body, headers))


def gen_xai(cfg: dict, prompt: str, photo: Image.Image | None) -> Image.Image:
    key = cfg.get("key", "").strip()
    if not key:
        raise ProviderError("need_key")
    body = json.dumps({"model": cfg.get("model") or DEFAULT_MODELS["xai"], "prompt": prompt,
                       "response_format": "b64_json", "aspect_ratio": "1:1"}).encode()
    return _images_response(_http("https://api.x.ai/v1/images/generations", body,
                                  {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}))


def gen_cloudflare(cfg: dict, prompt: str, photo: Image.Image | None) -> Image.Image:
    acc, token = cfg.get("account", "").strip(), cfg.get("key", "").strip()
    if not acc or not token:
        raise ProviderError("need_key")
    model = cfg.get("model") or DEFAULT_MODELS["cloudflare"]
    url = f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/{model}"
    body = json.dumps({"prompt": prompt[:2048], "steps": 8}).encode()
    j = _http(url, body, {"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    res = j.get("result") or {}
    if isinstance(res, dict) and res.get("image"):
        img = res["image"]
        return _fetch_image(img) if str(img).startswith("http") else _b64_image(img)
    errs = j.get("errors") or []
    raise ProviderError("이미지가 오지 않았어요: " + (errs[0].get("message") if errs else json.dumps(j)[:300]))


def gen_gemini(cfg: dict, prompt: str, photo: Image.Image | None) -> Image.Image:
    key = cfg.get("key", "").strip()
    if not key:
        raise ProviderError("need_key")
    try:
        return gemini.generate(key, cfg.get("model") or DEFAULT_MODELS["gemini"], prompt, photo)
    except gemini.GeminiError as e:
        msg = str(e)
        if "429" in msg or "quota" in msg.lower():
            msg += "\n\n무료 키로는 제미나이 이미지 생성이 안 돼요. 결제를 등록하거나 '제미나이 웹'을 써 주세요."
        raise ProviderError(msg) from None


def codex_path() -> str | None:
    return shutil.which("codex") or shutil.which("codex.cmd")


def gen_codex(cfg: dict, prompt: str, photo) -> Image.Image:
    exe = codex_path()
    if not exe:
        raise ProviderError("Codex CLI를 찾지 못했어요. 'npm i -g @openai/codex' 설치 후 'codex login'으로 로그인해 주세요.")
    work = Path(tempfile.mkdtemp(prefix="fs_codex_"))
    args = [exe, "exec", "--skip-git-repo-check", "--full-auto", "-C", str(work)]
    for i, ph in enumerate(_photos(photo)):
        ref = work / f"reference{i}.png"
        ref.write_bytes(_png_bytes(ph))
        args += ["-i", str(ref)]
    task = ("Use $imagegen to create one square image for this request, then save the final PNG as "
            f"result.png in the current directory. Request: {prompt}")
    args.append(task)
    start = time.time()
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=420, cwd=str(work),
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise ProviderError("Codex 응답이 너무 오래 걸려요(7분 초과).") from None
    pngs = sorted((p for p in work.rglob("*.png") if not p.name.startswith("reference") and p.stat().st_mtime >= start - 1),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    if not pngs:
        tail = (proc.stderr or proc.stdout or "").strip()[-500:]
        raise ProviderError("Codex가 이미지를 만들지 못했어요.\n" + tail)
    return Image.open(pngs[0]).convert("RGBA")


GENERATORS = {"openai": gen_openai, "xai": gen_xai, "cloudflare": gen_cloudflare,
              "gemini": gen_gemini, "codex": gen_codex}


def generate(pid: str, cfg: dict, prompt: str, photo) -> Image.Image:
    if pid not in GENERATORS:
        raise ProviderError("이 방식은 자동 생성이 아니에요.")
    if photo is not None and not BY_ID[pid]["ref"]:
        photo = None
    return GENERATORS[pid](cfg, prompt, photo)


def status(pid: str, cfg: dict) -> str:
    """설정 화면에 보일 상태 글."""
    p = BY_ID.get(pid, {})
    if p.get("group") == "free_web":
        return "바로 사용"
    if pid == "codex":
        return "설치됨" if codex_path() else "설치 안 됨"
    if pid == "cloudflare":
        return "키 있음" if cfg.get("key") and cfg.get("account") else "키 없음"
    return "키 있음" if cfg.get("key") else "키 없음"


def save_reference(photo: Image.Image, name: str = "참고사진") -> Path:
    """웹 연동용: 참고 사진을 임시 파일로 저장 (사이트에 붙여넣기 쉽게)."""
    d = Path(tempfile.gettempdir()) / "FM27FaceStudio"
    d.mkdir(exist_ok=True)
    p = d / f"{name}.png"
    p.write_bytes(_png_bytes(photo, 1536))
    return p


def reveal(path: Path) -> None:
    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", str(path)])
