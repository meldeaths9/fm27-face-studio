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


def _hex(v: str):
    v = str(v or "").strip()
    if len(v) == 7 and v.startswith("#"):
        try:
            return tuple(int(v[i:i + 2], 16) for i in (1, 3, 5))
        except ValueError:
            return None
    return None


@dataclass
class Deco:
    caption: bool = False
    text: str = ""
    style: str = "gold"
    rounded: bool = False
    radius: int = 14          # 한 변의 %
    border: bool = False
    text_color: str = ""      # "#rrggbb" — 비우면 스타일 기본색
    border_color: str = ""
    band: str = ""            # "gunzo" → 건조용 구단 색 띠 (caption 대신)
    band_color: str = ""      # "#rrggbb" 구단 색
    sub: str = ""             # 띠 왼쪽 작은 글자 (포지션: GK·DF·MF·FW)

    @classmethod
    def from_dict(cls, d: dict | None) -> "Deco":
        d = d or {}
        out = cls()
        for k in asdict(out):
            if k in d and d[k] is not None:
                setattr(out, k, type(getattr(out, k))(d[k]))
        out.radius = max(0, min(50, out.radius))
        out.border = False            # 테두리 기능은 뺐다 (예전 설정이 남아 있어도 안 그림)
        if out.style not in STYLES:
            out.style = "gold"
        for k in ("text_color", "border_color", "band_color"):
            if _hex(getattr(out, k)) is None:
                setattr(out, k, "")
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
    if _hex(deco.text_color):                 # 직접 고른 글씨 색
        color = _hex(deco.text_color) + (255,)
    if _hex(deco.border_color):               # 직접 고른 테두리 색
        border_rgba = _hex(deco.border_color) + (235,)

    # 하단 이름
    text = deco.text.strip()
    if deco.band == "gunzo" and text:
        _gunzo_band(im, text, deco.sub.strip(), _hex(deco.band_color) or (20, 30, 70))
    elif deco.caption and text:
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

    # 둥근 모서리 먼저 자르고
    if radius_px > 0:
        mask = _round_mask(S, radius_px)
        im.putalpha(ImageChops.multiply(im.getchannel("A"), mask))

    # 테두리는 그 뒤에 같은 둥글기로 (모서리에서 잘리지 않게)
    if deco.border:
        w = max(2, S // 170)
        k = 4
        ov = Image.new("RGBA", (S * k, S * k), (0, 0, 0, 0))
        ImageDraw.Draw(ov).rounded_rectangle((0, 0, S * k - 1, S * k - 1), radius=radius_px * k,
                                              outline=border_rgba, width=w * k)
        ov = ov.resize((S, S), Image.LANCZOS)
        if radius_px > 0:       # 테두리도 바깥 모양 안쪽에만
            ov.putalpha(ImageChops.multiply(ov.getchannel("A"), _round_mask(S, radius_px)))
        im.alpha_composite(ov)
    return im


def _gunzo_band(im: Image.Image, text: str, sub: str, rgb: tuple) -> None:
    """건조용 이름띠: 아래쪽에 구단 색 띠, 위에 얇은 밝은 선, 왼쪽에 포지션 칸."""
    S = im.width
    top = int(S * 0.815)
    lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    fg = (20, 20, 24, 255) if lum > 170 else (255, 255, 255, 255)
    dark = tuple(int(c * 0.55) for c in rgb)
    ov = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for y in range(int(S * 0.70), top):            # 띠 위로 살짝 어두워지게
        a = int(150 * max(0.0, (y - S * 0.70) / max(1, top - S * 0.70)) ** 1.6)
        d.line((0, y, S, y), fill=(0, 0, 0, a))
    d.rectangle((0, top, S, S), fill=rgb + (240,))
    line = max(2, S // 110)
    d.rectangle((0, top, S, top + line), fill=(255, 255, 255, 210))
    x0 = 0
    if sub:
        w = int(S * 0.20)
        slant = int(S * 0.045)
        d.polygon([(0, top + line), (w + slant, top + line), (w, S), (0, S)], fill=dark + (255,))
        fs = max(9, int(S * 0.06))
        d.text(((w + slant / 2) / 2 + 1, (top + line + S) / 2), sub, font=caption_font(fs), anchor="mm",
               fill=(255, 255, 255, 235))
        x0 = w + slant
    im.alpha_composite(ov)
    d = ImageDraw.Draw(im)
    size = max(10, int(S * 0.075))
    font = caption_font(size)
    max_w = S - x0 - S * 0.08
    while d.textlength(text, font=font) > max_w and size > 10:
        size -= 1
        font = caption_font(size)
    if d.textlength(text, font=font) > max_w:
        while text and d.textlength(text + "…", font=font) > max_w:
            text = text[:-1]
        text += "…"
    cy = (top + line + S) / 2
    if sub:
        d.text((x0 + S * 0.035, cy), text, font=font, anchor="lm", fill=fg)
    else:
        d.text((S / 2, cy), text, font=font, anchor="mm", fill=fg)


def kit_color(kit: Image.Image) -> str:
    """유니폼 그림에서 주된 색 (회색·흰색보다 색이 있는 쪽을 고른다) → "#rrggbb"."""
    import colorsys
    im = kit.convert("RGBA")
    im.thumbnail((96, 96))
    px = [p[:3] for p in im.getdata() if p[3] > 200]
    px = [p for p in px if not (abs(p[0] - 235) < 6 and abs(p[1] - 235) < 6 and abs(p[2] - 235) < 6)]   # 깐 회색 배경 빼기
    if not px:
        return ""
    q = Image.new("RGB", (len(px), 1))
    q.putdata(px)
    pal = q.quantize(colors=6)
    counts = sorted(pal.getcolors(), reverse=True)
    colors = pal.getpalette()
    best, best_score = None, -1.0
    total = sum(c for c, _ in counts)
    for c, i in counts:
        r, g, b = colors[i * 3:i * 3 + 3]
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        score = (c / total) * (0.35 + s) * (1.0 if 0.12 < l < 0.85 else 0.4)
        if score > best_score:
            best, best_score = (r, g, b), score
    r, g, b = best
    return f"#{r:02x}{g:02x}{b:02x}"
