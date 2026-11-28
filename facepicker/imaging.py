"""사진 불러오기, 자르기 영역 계산, 자르기.

자르기 영역(box)은 원본 사진 좌표의 (중심x, 중심y, 한 변). 편집 화면에서는 이 영역이
고정된 틀에 맞게 보이도록 사진을 움직이고 확대한다. 틀은 항상 사진으로 꽉 차야 하므로
한 변은 사진의 짧은 변을 넘지 않는다.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

from . import ai_models

MIN_SIDE = 16.0


def load_image(path: str | Path) -> Image.Image:
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)
    return im.convert("RGBA")


def clamp_box(im: Image.Image, cx: float, cy: float, side: float) -> tuple[float, float, float]:
    """틀이 사진 밖으로 나가지 않게(빈 공간 없이) 맞춤."""
    w, h = im.size
    side = max(MIN_SIDE, min(float(side), float(min(w, h))))
    cx = min(max(float(cx), side / 2), w - side / 2)
    cy = min(max(float(cy), side / 2), h - side / 2)
    return cx, cy, side


def default_box(im: Image.Image) -> tuple[float, float, float]:
    """얼굴을 못 찾았을 때: 짧은 변 전체, 세로 사진이면 윗부분."""
    w, h = im.size
    side = float(min(w, h))
    cy = side / 2 + (h - side) * 0.12 if h > w else h / 2
    return clamp_box(im, w / 2, cy, side)


def auto_box(im: Image.Image) -> tuple[float, float, float]:
    """FM 얼굴 사진처럼 머리~어깨가 들어가게 얼굴 기준으로 맞춤."""
    try:
        face = ai_models.detect_face(im)
    except Exception:
        face = None
    if not face:
        return default_box(im)
    fx, fy, fw, fh = face
    side = max(fw, fh) * 2.4
    return clamp_box(im, fx + fw / 2, fy + fh / 2 + fh * 0.12, side)


def waist_box(im: Image.Image) -> tuple[float, float, float] | None:
    """건조: 얼굴을 기준으로 머리부터 허리쯤까지 (다리·발은 잘라 냄). 얼굴을 못 찾으면 None."""
    try:
        face = ai_models.detect_face(im)
    except Exception:
        face = None
    if not face:
        return None
    fx, fy, fw, fh = face
    side = max(fw, fh) * 4.4
    if side >= min(im.size) * 0.97:          # 이미 상반신이면 그대로
        return None
    top = fy - fh * 0.55                     # 머리 위 여백 조금
    return clamp_box(im, fx + fw / 2, top + side / 2, side)


def crop_square(im: Image.Image, box: tuple[float, float, float]) -> Image.Image:
    cx, cy, side = clamp_box(im, *box)
    left, top = int(round(cx - side / 2)), int(round(cy - side / 2))
    s = int(round(side))
    return im.crop((left, top, left + s, top + s))


def render(im: Image.Image, box: tuple[float, float, float], size: int) -> Image.Image:
    """꾸미기 전 결과: size x size RGBA."""
    return crop_square(im, box).resize((size, size), Image.LANCZOS)


def thumbnail(im: Image.Image, size: int) -> Image.Image:
    t = im.copy()
    t.thumbnail((size, size), Image.LANCZOS)
    bg = Image.new("RGBA", (size, size), (60, 63, 70, 255))
    bg.alpha_composite(t.convert("RGBA"), ((size - t.width) // 2, (size - t.height) // 2))
    return bg
