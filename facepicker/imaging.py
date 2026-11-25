"""사진 불러오기, 얼굴 위치 찾기, 자르기, 배경 제거."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

try:  # 얼굴 자동 인식 (없어도 동작)
    import cv2  # type: ignore
    import numpy as np  # type: ignore
    _CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
except Exception:  # pragma: no cover
    cv2 = None
    _CASCADE = None

_rembg_session = None


def rembg_available() -> bool:
    try:
        import rembg  # noqa: F401
        return True
    except Exception:
        return False


def load_image(path: str | Path) -> Image.Image:
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)
    return im.convert("RGBA")


def detect_face(im: Image.Image):
    """가장 큰 얼굴의 (x, y, w, h). 못 찾으면 None."""
    if _CASCADE is None or _CASCADE.empty():
        return None
    small = im.convert("L")
    scale = 1.0
    if max(small.size) > 1200:
        scale = 1200 / max(small.size)
        small = small.resize((int(small.width * scale), int(small.height * scale)))
    arr = np.array(small)
    faces = _CASCADE.detectMultiScale(arr, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    return (float(x) / scale, float(y) / scale, float(w) / scale, float(h) / scale)


def auto_box(im: Image.Image) -> tuple[float, float, float]:
    """자르기 정사각형 (중심x, 중심y, 한 변). FM 얼굴 사진처럼 머리~어깨가 들어가게."""
    w, h = im.size
    face = detect_face(im)
    if face:
        fx, fy, fw, fh = face
        side = fw * 2.4
        cx = fx + fw / 2
        cy = fy + fh / 2 + fh * 0.12
    else:
        side = min(w, h) * 0.95
        cx = w / 2
        cy = side / 2 + (h - side) * 0.15 if h > w else h / 2
    return clamp_box(im, cx, cy, side)


def clamp_box(im: Image.Image, cx: float, cy: float, side: float) -> tuple[float, float, float]:
    w, h = im.size
    side = max(16.0, min(side, float(max(w, h))))
    # 상자가 사진 밖으로 너무 나가지 않게 (사진보다 큰 경우엔 가운데)
    if side <= w:
        cx = min(max(cx, side / 2), w - side / 2)
    else:
        cx = w / 2
    if side <= h:
        cy = min(max(cy, side / 2), h - side / 2)
    else:
        cy = h / 2
    return cx, cy, side


def crop_square(im: Image.Image, box: tuple[float, float, float]) -> Image.Image:
    cx, cy, side = box
    left, top = cx - side / 2, cy - side / 2
    s = int(round(side))
    canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    region = im.crop((int(round(left)), int(round(top)), int(round(left)) + s, int(round(top)) + s))
    canvas.paste(region, (0, 0))
    return canvas


def render(im: Image.Image, box: tuple[float, float, float], size: int) -> Image.Image:
    """최종 결과: size x size PNG (RGBA)."""
    return crop_square(im, box).resize((size, size), Image.LANCZOS)


def remove_background(im: Image.Image) -> Image.Image:
    global _rembg_session
    from rembg import new_session, remove  # type: ignore

    if _rembg_session is None:
        _rembg_session = new_session("u2net_human_seg")
    out = remove(im.convert("RGBA"), session=_rembg_session)
    return out.convert("RGBA")


def thumbnail(im: Image.Image, size: int) -> Image.Image:
    t = im.copy()
    t.thumbnail((size, size), Image.LANCZOS)
    bg = Image.new("RGBA", (size, size), (60, 63, 70, 255))
    bg.alpha_composite(t.convert("RGBA"), ((size - t.width) // 2, (size - t.height) // 2))
    return bg
