"""얼굴 사진 꾸미기: 하단 이름, 둥근 모서리, 테두리.

미리보기와 최종 저장이 같은 함수를 쓰므로 보이는 그대로 저장된다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

STYLES = {
    # 이름: (글자색, 띠 색, 띠 진하기, 테두리색)
    "gold":  ((222, 195, 139, 255), (8, 8, 12), 235, (224, 209, 175, 150)),
    "white": ((255, 255, 255, 255), (8, 10, 18), 230, (255, 255, 255, 120)),
    "navy":  ((236, 240, 250, 255), (14, 22, 52), 230, (123, 140, 255, 150)),
}
STYLE_LABELS = {"gold": "금색", "white": "흰색", "navy": "남색 띠"}


@dataclass
class Deco:
    caption: bool = False
    text: str = ""
    style: str = "gold"
    rounded: bool = False
    radius: int = 14          # 한 변의 %
    border: bool = False

    @classmethod
    def from_dict(cls, d: dict | None) -> "Deco":
        d = d or {}
        out = cls()
        for k in asdict(out):
            if k in d and d[k] is not None:
                setattr(out, k, type(getattr(out, k))(d[k]))
        out.radius = max(0, min(50, out.radius))
        if out.style not in STYLES:
            out.style = "gold"
        return out

    def to_dict(self) -> dict:
        return asdict(self)


def _font_dirs() -> list[Path]:
    dirs = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    dirs += [Path("/usr/share/fonts/opentype/noto"), Path("/usr/share/fonts/truetype/noto"),
             Path("/usr/share/fonts/truetype/dejavu")]
    return dirs


@lru_cache(maxsize=32)
def caption_font(size: int) -> ImageFont.FreeTypeFont:
    names = ["malgunbd.ttf", "malgun.ttf", "NotoSansCJK-Bold.ttc", "NotoSansKR-Bold.otf",
             "arialbd.ttf", "DejaVuSans-Bold.ttf"]
    for d in _font_dirs():
        for n in names:
            p = d / n
            if p.exists():
                try:
                    if p.suffix == ".ttc":
                        return ImageFont.truetype(str(p), size, index=1)   # 한국어(KR)
                    return ImageFont.truetype(str(p), size)
                except OSError:
                    continue
    return ImageFont.load_default(size=size)


def _round_mask(size: int, radius_px: int, scale: int = 4) -> Image.Image:
    big = Image.new("L", (size * scale, size * scale), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, size * scale - 1, size * scale - 1),
                                          radius=radius_px * scale, fill=255)
    return big.resize((size, size), Image.LANCZOS)


def decorate(img: Image.Image, deco: Deco) -> Image.Image:
    im = img.convert("RGBA").copy()
    S = im.width
    color, band_rgb, band_alpha, border_rgba = STYLES.get(deco.style, STYLES["gold"])

    # 하단 이름
    text = deco.text.strip()
    if deco.caption and text:
        top = int(S * 0.70)
        band = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        bd = ImageDraw.Draw(band)
        for y in range(top, S):
            t = (y - top) / max(1, S - top)
            a = int(band_alpha * min(1.0, t * 1.35) ** 1.15)
            bd.line((0, y, S, y), fill=band_rgb + (a,))
        im.alpha_composite(band)
        size = max(10, int(S * 0.088))
        font = caption_font(size)
        d = ImageDraw.Draw(im)
        max_w = S * 0.86
        while d.textlength(text, font=font) > max_w and size > 10:
            size -= 1
            font = caption_font(size)
        if d.textlength(text, font=font) > max_w:      # 그래도 길면 말줄임
            while text and d.textlength(text + "…", font=font) > max_w:
                text = text[:-1]
            text += "…"
        y = int(S * 0.905)
        stroke = max(1, S // 170)
        d.text((S / 2, y), text, font=font, anchor="mm", fill=color,
               stroke_width=stroke, stroke_fill=(0, 0, 0, 120))

    radius_px = int(S * deco.radius / 100) if deco.rounded else 0

    # 테두리
    if deco.border:
        w = max(2, S // 170)
        ov = Image.new("RGBA", (S * 4, S * 4), (0, 0, 0, 0))
        ImageDraw.Draw(ov).rounded_rectangle(
            (w * 2, w * 2, S * 4 - 1 - w * 2, S * 4 - 1 - w * 2),
            radius=max(0, radius_px * 4 - w * 2), outline=border_rgba, width=w * 4)
        im.alpha_composite(ov.resize((S, S), Image.LANCZOS))

    # 둥근 모서리
    if radius_px > 0:
        mask = _round_mask(S, radius_px)
        im.putalpha(ImageChops.multiply(im.getchannel("A"), mask))
    return im
