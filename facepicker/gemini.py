"""Gemini(나노 바나나) 이미지 생성 API 호출 — 추가 라이브러리 없이 표준 HTTP로."""
from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.request

from PIL import Image

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiError(Exception):
    pass


def _encode(im: Image.Image) -> dict:
    im = im.convert("RGB")
    im.thumbnail((1024, 1024), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    return {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}}


def _post(url: str, key: str, body: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="ignore")
        try:
            msg = json.loads(raw)["error"]["message"]
        except Exception:
            msg = raw[:500]
        raise GeminiError(f"HTTP {e.code}: {msg}") from None
    except urllib.error.URLError as e:
        raise GeminiError(f"연결 실패: {e.reason}") from None


def generate(key: str, model: str, prompt: str, photo=None, timeout: int = 180) -> Image.Image:
    """photo: 사진 한 장 또는 여러 장(list)."""
    if not key.strip():
        raise GeminiError("설정에서 제미나이 API 키를 먼저 입력하세요.")
    parts: list[dict] = [{"text": prompt}]
    for ph in (photo if isinstance(photo, (list, tuple)) else [photo]):
        if ph is not None:
            parts.append(_encode(ph))
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"], "imageConfig": {"aspectRatio": "1:1"}},
    }
    url = API.format(model=model.strip())
    try:
        data = _post(url, key.strip(), body, timeout)
    except GeminiError as e:
        # 일부 모델은 imageConfig를 지원하지 않음 → 빼고 재시도
        if "imageConfig" in str(e) or "aspect" in str(e).lower():
            body["generationConfig"].pop("imageConfig", None)
            data = _post(url, key.strip(), body, timeout)
        else:
            raise

    texts = []
    for cand in data.get("candidates", []):
        for part in (cand.get("content") or {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return Image.open(io.BytesIO(base64.b64decode(inline["data"]))).convert("RGBA")
            if part.get("text"):
                texts.append(part["text"])
        reason = cand.get("finishReason")
        if reason and reason != "STOP":
            texts.append(f"(종료 사유: {reason})")
    block = (data.get("promptFeedback") or {}).get("blockReason")
    if block:
        texts.append(f"(차단 사유: {block})")
    raise GeminiError("이미지가 오지 않았습니다. " + " ".join(texts)[:400])
