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
