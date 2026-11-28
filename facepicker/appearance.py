"""게임의 뉴젠 외모 코드 풀기.

플러그인이 모은 문자열(예: 'adē¡qrcaaaafac')은 글자마다 (코드값 - 97)이 숫자 하나다.
FMAX 화면과 12명을 맞춰 본 결과:
  0 성별(0 남/1 여)  1 인종(FM 순서)  2 키(cm)  3 몸무게(kg)  4 나이  5 피부색(1~20)
  6 머리 길이(1 짧음/2 중간)  7 머리색(0 검정, 2 진한 갈색, 5 밝은 갈색 …)
나머지 칸은 아직 모른다.
"""
from __future__ import annotations

ETHNIC = [
    ("북유럽계", "Northern European"), ("지중해/히스패닉계", "Mediterranean/Hispanic"),
    ("북아프리카/중동계", "North African/Middle Eastern"), ("아프리카/카리브계", "African/Caribbean"),
    ("남아시아계(인도 등)", "South Asian"), ("동남아시아계", "Southeast Asian"), ("태평양 원주민계", "Pacific Islander"),
    ("아메리카 원주민계", "Native American"), ("호주 원주민계", "Aboriginal Australian"),
    ("흑인·백인 혼혈", "mixed Black and white heritage"), ("동아시아계", "East Asian"),
]
HAIR_LEN = {0: ("민머리", "bald"), 1: ("짧은 머리", "short hair"), 2: ("중간 길이 머리", "medium-length hair"),
            3: ("긴 머리", "long hair")}
HAIR_COL = {0: ("검은", "black"), 2: ("진한 갈색", "dark brown"), 5: ("밝은 갈색", "light brown")}


def decode(code: str) -> dict | None:
    if not code or len(code) < 8:
        return None
    v = [ord(ch) - 97 for ch in code]
    d = {"female": v[0] == 1, "ethnic": v[1], "height": v[2], "weight": v[3], "age": v[4], "skin": v[5],
         "hair_len": v[6], "hair_col": v[7]}
    if not (120 <= d["height"] <= 230 and 0 <= d["skin"] <= 25):
        return None
    return d


def _skin(n: int, lang: str) -> str:
    ko = ["아주 밝은", "밝은", "밝은 올리브빛", "중간 톤의", "갈색", "진한 갈색", "아주 짙은"]
    en = ["very fair", "fair", "light olive", "medium", "brown", "dark brown", "very dark"]
    i = 0 if n <= 2 else 1 if n <= 5 else 2 if n <= 8 else 3 if n <= 11 else 4 if n <= 14 else 5 if n <= 18 else 6
    return (ko if lang == "ko" else en)[i]


def _build(d: dict, lang: str) -> str:
    try:
        bmi = d["weight"] / ((d["height"] / 100) ** 2)
    except ZeroDivisionError:
        return ""
    if bmi < 21.5:
        return "호리호리하고 마른 체형" if lang == "ko" else "a lean, slim build"
    if bmi < 25.5:
        return "탄탄한 운동선수 체형" if lang == "ko" else "an athletic build"
    return "다부지고 묵직한 체형" if lang == "ko" else "a stocky, heavy build"


def describe(code: str, lang: str = "ko") -> str:
    """프롬프트에 넣을 외모 문장. 모르는 값은 뺀다."""
    d = decode(code)
    if not d:
        return ""
    i = 1 if lang == "en" else 0
    parts = []
    if 0 <= d["ethnic"] < len(ETHNIC):
        parts.append(ETHNIC[d["ethnic"]][i])
    parts.append(f"{_skin(d['skin'], lang)} 피부(20단계 중 {d['skin']})" if lang == "ko" else f"{_skin(d['skin'], lang)} skin")
    col = HAIR_COL.get(d["hair_col"])
    ln = HAIR_LEN.get(d["hair_len"])
    if lang == "ko":
        if col or ln:
            parts.append(" ".join(x for x in ((col[0] if col else ""), (ln[0] if ln else "머리")) if x))
        parts.append(f"키 {d['height']}cm")
    else:
        if col or ln:
            parts.append(" ".join(x for x in ((col[1] if col else ""), (ln[1] if ln else "hair")) if x))
        parts.append(f"{d['height']} cm tall")
    b = _build(d, lang)
    if b:
        parts.append(b)
    return ", ".join(parts)


def summary(code: str) -> str:
    """앱 화면용 짧은 표시."""
    d = decode(code)
    if not d:
        return ""
    eth = ETHNIC[d["ethnic"]][0] if 0 <= d["ethnic"] < len(ETHNIC) else "?"
    col = HAIR_COL.get(d["hair_col"], ("?",))[0]
    ln = HAIR_LEN.get(d["hair_len"], ("?",))[0]
    return f"{eth} · 피부 {d['skin']}/20 · {col} {ln} · {d['height']}cm · {_build(d, 'ko')}"


# ------------------------------------------------------------------ 사진에서 피부·머리 색 짐작
def guess_from_image(im) -> str:
    """게임 3D 얼굴(또는 사진)에서 피부색·머리색을 영어 한 마디로. 못 하면 빈 글자.
    게임에 외모 정보가 없는 뉴젠을 사진 없이 그릴 때 쓴다."""
    try:
        import colorsys
        from PIL import Image
        im = im.convert("RGBA").resize((128, 128), Image.BILINEAR)
        px = im.load()

        def region(x0, x1, y0, y1):
            out = []
            for y in range(int(y0 * 128), int(y1 * 128)):
                for x in range(int(x0 * 128), int(x1 * 128)):
                    r, g, b, a = px[x, y]
                    if a > 200 and not (abs(r - g) < 6 and abs(g - b) < 6 and r > 200):   # 투명·회색 배경 빼기
                        out.append((r, g, b))
            return out

        def median(cs):
            cs = sorted(cs, key=lambda c: sum(c))
            return cs[len(cs) // 2]

        skin = region(0.38, 0.62, 0.50, 0.64)          # 볼·코
        if len(skin) < 40:
            return ""
        r, g, b = median(skin)
        lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        # 게임 3D 얼굴은 조명 때문에 실제보다 조금 어둡게 나온다
        skin_t = ("very fair" if lum > 0.72 else "fair" if lum > 0.60 else "light olive" if lum > 0.53
                  else "tan" if lum > 0.50 else "dark brown" if lum > 0.40 else "very dark brown")
        hair = region(0.30, 0.70, 0.05, 0.20)          # 이마 위
        hair_t = "a shaved head"
        if len(hair) > 120:
            hr, hg, hb = median(hair)
            # 머리 자리 색이 피부와 비슷하면 민머리
            if abs(hr - r) + abs(hg - g) + abs(hb - b) > 60:
                h, s, v = colorsys.rgb_to_hsv(hr / 255, hg / 255, hb / 255)
                if v < 0.16:
                    c = "black"
                elif s < 0.18 and v > 0.55:
                    c = "grey"
                elif (h < 0.07 or h > 0.95) and s > 0.45 and v > 0.3:
                    c = "ginger red"
                elif 0.07 <= h < 0.17 and v > 0.55 and s < 0.55:
                    c = "blonde"
                elif 0.05 <= h < 0.17 and v > 0.42:
                    c = "light brown"
                elif v < 0.3:
                    c = "dark brown"
                else:
                    c = "brown"
                hair_t = f"{c} hair"
        return f"{skin_t} skin, {hair_t}"
    except Exception:  # noqa: BLE001
        return ""
