"""AI 프롬프트 만들기. 기본은 한국어(화면에서 한눈에 보이게), 영어만 잘 알아듣는 모델은 영어."""
from __future__ import annotations

import random

# 사용자가 직접 만든 템플릿에서 쓸 수 있는 자리: {ref} {subject} {outfit} {expression} {badge_note}
#   {role} {name} {club} {age} {age_text} {nationality} {nationality_text}
FACE = {
    "ko": ("{ref}{subject}의 사실적인 머리·어깨 인물 사진을 만들어 주세요. {features}{outfit}"
           "카메라를 정면으로 보고 있고, {expression}. {realism}"
           "배경은 단색 밝은 회색 스튜디오, 조명은 부드럽고 고르게 해 주세요. "
           "1:1 정사각형 구도에 머리는 가운데, 머리카락 위로 약간 여백을 두고 어깨까지 보이게 해 주세요. "
           "글자와 워터마크는 넣지 마세요{badge_note}."),
    "en": ("{ref}Create a realistic head-and-shoulders portrait photo of {subject}. {features}{outfit}"
           "Facing the camera, {expression}. {realism}Plain light grey studio background, soft even lighting. "
           "Square 1:1 framing, head centered with a little space above the hair, shoulders visible. "
           "No added text or watermark{badge_note}."),
}

REF = {
    "ko": "첫 번째 첨부 사진을 참고해서 이 사람의 얼굴, 생김새, 피부색, 머리 모양을 그대로 유지해 주세요. ",
    "en": "Use the first attached photo as the reference: keep this person's face, identity, skin tone and hairstyle. ",
}

# 참고 사진이 게임의 3D 뉴젠 얼굴일 때: 따라 그리지 말고 실제 사진을 새로 찍게 한다
REF_GAME = {
    "ko": ("첫 번째 첨부 사진은 게임 속 3D 그래픽 얼굴이에요. 이 그림을 고치거나 따라 그리지 말고, "
           "이 사람이 실제로 있다면 찍혔을 법한 새 실제 사진을 처음부터 만들어 주세요. "
           "그림에서 참고할 것은 피부색, 머리 색과 머리 모양, 나이대뿐이에요. 얼굴 생김새는 아래 설명을 따라 새로 만들어 주세요. "
           "눈 색은 그래픽의 회색빛을 따르지 말고 실제 사람처럼 자연스럽게 해 주세요. "),
    "en": ("The first attached image is a 3D video-game render of a face. Do not edit, trace or copy that render. "
           "Create a brand-new real photograph of how this person would look in real life. Take only these from the "
           "render: skin tone, hair colour and hairstyle, and age range. Build the facial features from the description below. "
           "Do not copy the render's grey eye colour; give natural, realistic eyes. "),
}

REALISM = {
    "ko": ("실제 카메라(85mm 렌즈)로 찍은 사진처럼 모공이 보이는 자연스러운 피부 결, 살짝 비대칭인 실제 사람 얼굴로 해 주세요. "
           "3D 렌더, CG, 게임 그래픽, 일러스트, 매끈한 플라스틱 피부, 과한 보정 느낌은 피해 주세요. "),
    "en": ("It must look like a real DSLR photo (85mm lens): natural skin texture with visible pores, a slightly "
           "asymmetric real human face. Avoid any 3D render, CGI, video-game, illustration, smooth plastic skin or "
           "heavy retouching look. "),
}

# 참고 사진이 없을 때 얼굴이 다 똑같아지지 않게 섞는 특징 (인종·피부색과는 상관없는 것만)
FEATURES = {
    "hair": [("짧게 민 머리", "a short buzz cut"), ("옆가르마를 탄 짧은 머리", "short hair with a side parting"),
             ("뒤로 넘긴 머리", "slicked-back hair"), ("윗부분만 길고 옆은 짧은 머리", "longer on top, short on the sides"),
             ("어깨에 살짝 닿는 긴 머리", "shoulder-length hair"), ("덥수룩하게 헝클어진 머리", "messy, tousled hair"),
             ("이마를 덮는 앞머리", "a fringe covering the forehead")],
    "face": [("갸름한 얼굴", "a narrow face"), ("각진 턱", "a square jaw"), ("둥근 얼굴", "a round face"),
             ("광대가 도드라진 얼굴", "prominent cheekbones"), ("긴 얼굴", "a long face")],
    "brow": [("짙은 눈썹", "thick eyebrows"), ("옅은 눈썹", "thin, light eyebrows"), ("일자 눈썹", "straight eyebrows")],
    "nose": [("콧대가 높은 코", "a high-bridged nose"), ("넓적한 코", "a broad nose"), ("작고 동그란 코", "a small rounded nose"),
             ("매부리코", "a slightly hooked nose")],
    "eyes": [("쌍꺼풀 없는 가는 눈", "narrow eyes"), ("큰 눈", "large eyes"), ("깊게 들어간 눈", "deep-set eyes"),
             ("처진 눈매", "downturned eyes")],
    "extra": [("주근깨", "freckles"), ("작은 흉터 하나", "a small scar"), ("튀어나온 귀", "slightly protruding ears"),
              ("두꺼운 입술", "full lips"), ("얇은 입술", "thin lips"), ("", ""), ("", "")],
    "beard": [("깔끔하게 면도한 얼굴", "clean-shaven"), ("살짝 자란 수염", "light stubble"), ("짧게 다듬은 수염", "a short trimmed beard")],
}


def _features(person: dict, age: str, lang: str, has_ref: bool, ref_mode: str) -> str:
    """게임에 정해진 외모가 있으면 그것(인종·피부색·머리·키·체형)을 먼저 쓰고, 얼굴 세부만 랜덤으로 섞는다."""
    from . import appearance
    look = appearance.describe(str(person.get("look", "")), lang)
    if has_ref and ref_mode == "photo":
        # 사진이 있어도 인종·피부색은 꼭 적는다 (사진을 안 붙였거나 AI가 무시해도 엇나가지 않게)
        if look:
            return (f"이 사람의 외모: {look}. " if lang == "ko" else f"This person's appearance: {look}. ")
        return ""
    if look:
        head = (f"게임에 정해진 외모: {look}. " if lang == "ko" else f"Appearance set in the game: {look}. ")
        return head + random_features(age, lang, with_hair=False)
    return random_features(age, lang, with_hair=not has_ref)


def random_features(age: str, lang: str, with_hair: bool = True) -> str:
    """with_hair=False: 게임 얼굴을 참고할 때 (머리는 그림을 따르고 얼굴 생김새만 섞는다)"""
    i = 1 if lang == "en" else 0
    pick = [random.choice(FEATURES[k])[i] for k in (("hair",) if with_hair else ()) + ("face", "brow", "nose", "eyes", "extra")]
    pick = [x for x in pick if x]
    try:
        adult = int(age) >= 20
    except (TypeError, ValueError):
        adult = True
    if adult:
        pick.append(random.choice(FEATURES["beard"])[i])
    if lang == "en":
        return "Distinct look: " + ", ".join(pick) + ". "
    return "생김새: " + ", ".join(pick) + ". "


UNIFORM = {
    "ko": ("첫 번째 첨부 사진을 수정해 주세요. 사람은 완전히 그대로 두세요. 얼굴, 생김새, 표정, 머리 모양, 피부색, "
           "자세, 머리 크기와 위치, 구도, 배경, 조명까지 모두요. 보이는 옷만 바꿔 주세요. 바꿀 옷: {kit_text}. "
           "새 옷은 몸과 자세에 맞게 자연스러운 주름이 있는 실제 사진처럼 보여야 해요. "
           "그 밖의 글자나 워터마크는 넣지 마세요."),
    "en": ("Edit the first attached photo. Keep the person exactly the same: face, identity, expression, hairstyle, "
           "skin tone, pose, head size and position, framing, background and lighting. Only replace the visible "
           "clothing with {kit_text}. Make it look like a real photo with natural fabric folds that fit the body "
           "and pose. Do not add any other text or watermark."),
}

EXPRESSIONS = {
    "smile": {"label": "웃음", "ko": "이가 살짝 보이게 자연스럽게 웃고 있어요",
              "en": "with a natural smile showing a little teeth"},
    "soft": {"label": "미소", "ko": "입꼬리만 살짝 올라간 옅은 미소를 짓고 있어요",
             "en": "with a subtle closed-mouth smile"},
    "serious": {"label": "진지", "ko": "차분하고 진지한 표정이에요",
                "en": "with a calm, serious, focused expression"},
    "smug": {"label": "도도", "ko": "턱을 아주 약간 들고 한쪽 입꼬리만 살짝 올린, 자신감 있고 약간 도도한 표정이에요",
             "en": "with a confident, slightly smug look, chin raised a touch and one corner of the mouth lifted"},
    "confident": {"label": "자신감", "ko": "눈빛이 또렷하고 입을 다문 채 살짝 웃는, 자신감 있는 표정이에요",
                  "en": "with a self-assured look, steady eyes and a faint closed-mouth smile"},
    "determined": {"label": "결연", "ko": "눈썹에 살짝 힘이 들어간, 결연하고 집중한 표정이에요",
                   "en": "with a determined, focused look, brows slightly tensed"},
    "blank": {"label": "무덤덤", "ko": "아무 감정 없이 담담하고 무심한 표정이에요",
              "en": "with a blank, matter-of-fact, unbothered expression"},
    "playful": {"label": "장난기", "ko": "눈가가 살짝 웃고 있는, 장난기 어린 표정이에요",
                "en": "with a playful, mischievous look, eyes smiling slightly"},
    "shy": {"label": "수줍음", "ko": "살짝 어색하고 수줍게 웃는 표정이에요",
            "en": "with a slightly awkward, shy smile"},
    "tired": {"label": "피곤", "ko": "조금 지쳐 보이는, 졸린 듯한 표정이에요",
              "en": "looking a little tired and sleepy-eyed"},
    "proud": {"label": "뿌듯", "ko": "가슴을 살짝 펴고 뿌듯해하는, 기분 좋은 표정이에요",
              "en": "looking proud and pleased, chest slightly out"},
    "grin": {"label": "활짝", "ko": "이가 다 보이게 활짝 웃고 있어요",
             "en": "with a big, wide grin showing teeth"},
}
EXPRESSION_LABELS = {"random": "랜덤", **{k: v["label"] for k, v in EXPRESSIONS.items()}}

ROLE = {
    "player": {"ko": "프로 축구 선수", "en": "professional football player"},
    "staff": {"ko": "축구 클럽 코치", "en": "football club coach"},
    "support": {"ko": "축구 클럽 직원", "en": "football club office staff member"},
    "manager": {"ko": "축구 감독", "en": "football manager"},
}


def pick_expression(expr: str) -> str:
    if expr in EXPRESSIONS:
        return expr
    return random.choice([k for k in EXPRESSIONS if k not in ("tired", "shy")])   # 랜덤엔 무난한 것만


def club_text(club: str, hint: str, lang: str) -> str:
    club, hint = club.strip(), hint.strip()
    if not club:
        return ""
    if not hint:
        return club
    return f"{club}({hint})" if lang == "ko" else f"{club} ({hint})"


def kit_ref_text(index: int, lang: str) -> str:
    if lang == "ko":
        n = "첫 번째" if index == 1 else "두 번째"
        return f"{n} 첨부 사진의 축구 유니폼(색, 무늬, 깃, 엠블럼, 스폰서까지 똑같이)"
    n = "first" if index == 1 else "second"
    return f"the football kit shown in the {n} attached photo (same colours, pattern, collar, badge and sponsor)"


def outfit_text(kind: str, club: str, kit_index: int, manager_outfit: str, lang: str) -> tuple[str, bool]:
    """(옷 문장, 엠블럼 허용 여부)"""
    ko = lang == "ko"
    if kit_index and kind in ("player", "staff", "manager"):
        k = kit_ref_text(kit_index, lang)
        return (f"{k}을 입고 있어요. " if ko else f"Wearing {k}. "), True
    if kind == "player":
        if club:
            return (f"{club}의 현재 홈 유니폼을 입고 있어요. " if ko else f"Wearing the current home kit of {club}. "), True
        return ("축구 유니폼을 입고 있어요. " if ko else "Wearing a football kit. "), False
    if kind == "staff" or (kind == "manager" and manager_outfit == "training"):
        if club:
            return (f"{club}의 트레이닝복 상의를 입고 있어요. " if ko else f"Wearing a {club} training top. "), True
        return ("축구 클럽 트레이닝복 상의를 입고 있어요. " if ko else "Wearing a football club training top. "), False
    return ("깔끔한 정장 차림이에요. " if ko else "Wearing a smart suit. "), False


def face_prompt(person: dict, *, lang: str, template: str, has_ref: bool, has_kit: bool,
                expression: str, club_hint: str, manager_outfit: str, ref_mode: str = "game") -> tuple[str, str]:
    """(프롬프트, 고른 표정 키)"""
    lang = "en" if lang == "en" else "ko"
    kind = person.get("kind", "player")
    if person.get("me"):
        kind = "manager"
    age = str(person.get("age", "")).strip()
    nat = str(person.get("nationality", "")).strip()
    plain_club = str(person.get("club", "")).strip()
    club = club_text(plain_club, club_hint, lang)      # 처음 한 번만 설명을 붙인다
    expr = pick_expression(expression)
    role = ROLE.get(kind, ROLE["staff"])[lang]
    if lang == "ko":
        parts = [f"{club} 소속" if club else "", f"{age}세" if age else "", f"{nat} 출신" if nat else "", role]
        subject = " ".join(x for x in parts if x)
    else:
        bits = [f"a {age}-year-old" if age else "a", role]
        subject = " ".join(bits) + (f" from {nat}" if nat else "") + (f" at {club}" if club else "")
    kit_index = (2 if has_ref else 1) if has_kit else 0
    outfit, badge_ok = outfit_text(kind, plain_club, kit_index, manager_outfit, lang)
    vars_ = {
        "ref": ((REF_GAME if ref_mode == "game" else REF)[lang]) if has_ref else "",
        "features": _features(person, age, lang, has_ref, ref_mode),
        "realism": REALISM[lang],
        "subject": subject, "outfit": outfit, "expression": EXPRESSIONS[expr][lang],
        "badge_note": (" (유니폼의 엠블럼과 스폰서는 괜찮아요)" if lang == "ko" else " (the kit's badge and sponsor are fine)") if badge_ok else "",
        "role": role, "name": str(person.get("name", "")).strip(), "club": club, "age": age,
        "age_text": (f"{age}세" if lang == "ko" else f"{age} years old") if age else "",
        "nationality": nat, "nationality_text": nat,
    }
    tpl = template.strip() or FACE[lang]
    try:
        text = tpl.format(**vars_)
    except (KeyError, IndexError, ValueError):
        text = tpl
    while "  " in text:
        text = text.replace("  ", " ")
    return text.strip(), expr


def uniform_prompt(person: dict, *, lang: str, has_kit: bool, club_hint: str) -> str:
    lang = "en" if lang == "en" else "ko"
    club = club_text(str(person.get("club", "")), club_hint, lang)
    if has_kit:
        kit = kit_ref_text(2, lang)
    elif club:
        kit = f"{club}의 현재 홈 유니폼" if lang == "ko" else f"the current home football kit of {club}"
    else:
        kit = "무지 어두운색 축구 훈련복" if lang == "ko" else "a plain dark football training top"
    return UNIFORM[lang].format(kit_text=kit)


def strip_ref(text: str) -> str:
    for r in list(REF.values()) + list(REF_GAME.values()):
        text = text.replace(r, "").replace(r.strip(), "")
    return text.strip()


# ---------------------------------------------------------------- 건조 (경기 중 모습)
POS_GROUP = {"gk": "gk", "sw": "df", "dl": "df", "dc": "df", "dr": "df", "wbl": "df", "wbr": "df",
             "dm": "mf", "ml": "mf", "mc": "mf", "mr": "mf", "aml": "fw", "amc": "fw", "amr": "fw", "stc": "fw"}
POS_LABEL = {"gk": "GK", "df": "DF", "mf": "MF", "fw": "FW"}

ACTIONS = {
    "dribble": ("공을 몰고 앞으로 드리블하는 모습", "dribbling the ball forward at speed"),
    "shoot": ("힘껏 슈팅하는 순간", "striking a powerful shot"),
    "celebrate": ("골을 넣고 두 팔을 벌려 환호하며 세리머니하는 모습", "celebrating a goal with arms spread wide, shouting with joy"),
    "tackle": ("몸을 던져 태클하는 순간", "making a committed sliding tackle"),
    "header": ("높이 뛰어올라 헤딩하는 순간", "leaping high to head the ball"),
    "pass": ("고개를 들고 정확하게 패스하는 순간", "playing a precise pass with head up"),
    "run": ("전력으로 질주하는 모습", "sprinting at full speed"),
    "save": ("몸을 날려 공을 막아 내는 골키퍼", "a goalkeeper diving full stretch to make a save, wearing goalkeeper gloves"),
    "catch": ("높은 공을 두 손으로 잡아 내는 골키퍼", "a goalkeeper catching a high ball with both hands, wearing goalkeeper gloves"),
    "touchline": ("터치라인에서 손짓하며 지시하는 모습", "standing on the touchline, gesturing and giving instructions"),
    "fist": ("주먹을 불끈 쥐고 포효하는 모습", "clenching his fist and roaring with passion"),
    "clap": ("관중을 향해 박수 치는 모습", "applauding the fans with both hands"),
    "point": ("손가락으로 동료를 가리키며 외치는 모습", "pointing at a teammate and shouting"),
    "gk_hold": ("공을 가슴에 안고 차분하게 서 있는 골키퍼", "a goalkeeper standing calmly, holding the ball against his chest with both gloved hands"),
    "gk_throw": ("공을 동료에게 던져 주려는 골키퍼", "a goalkeeper about to throw the ball out to a teammate, ball held at shoulder height, wearing goalkeeper gloves"),
    "gk_shout": ("한 손을 들어 수비에게 지시하며 외치는 골키퍼", "a goalkeeper raising one gloved hand and shouting instructions to his defenders"),
}
AUTO_ACTIONS = {
    "gk": ["gk_hold", "gk_throw", "gk_shout"],      # 골키퍼는 차분하게 (선방·캐칭은 직접 고를 때만)
    "df": ["tackle", "header", "run", "pass"],
    "mf": ["pass", "dribble", "run", "shoot"],
    "fw": ["shoot", "celebrate", "dribble", "header"],
    "": ["dribble", "shoot", "celebrate", "run", "pass"],
}
GUNZO = {
    "ko": ("{ref}{subject}의 실제 경기 중 사진을 만들어 주세요. {action}. {features}{outfit}"
           "프로 스포츠 사진기자가 망원 렌즈(300mm)로 찍은 듯한 사진이에요. 빠른 셔터로 움직임이 또렷하고, 땀과 근육의 긴장감이 살아 있게 해 주세요. "
           "배경은 밤 경기 축구장으로, 관중석과 조명이 크게 흐려져(보케) 있고 잔디가 보여요. "
           "{realism}1:1 정사각형 구도에 허리 위 상반신이 크게 들어오게, 얼굴이 잘 보이게 해 주세요. "
           "글자, 등번호 숫자, 워터마크는 새로 넣지 마세요{badge_note}."),
    "en": ("{ref}Create a real in-match action photo of {subject}, {action}. {features}{outfit}"
           "Shot by a professional sports photographer with a 300mm telephoto lens: fast shutter, crisp motion, visible sweat "
           "and muscle tension. Background is a floodlit football stadium at night with the crowd and lights in heavy bokeh, "
           "grass visible. {realism}Square 1:1 framing, waist-up, face clearly visible. "
           "Do not add text, shirt numbers or watermarks{badge_note}."),
}


LOCAL_ACTIONS = ["celebrate", "run", "fist", "clap", "point"]    # 그림도구: 다리를 안 쓰는 상체 동작만


def pick_action(person: dict, action: str, local: bool = False) -> str:
    if action in ACTIONS:
        return action
    if person.get("kind", "player") != "player":
        return "touchline"
    grp = POS_GROUP.get(str(person.get("pos", "")).lower(), "")
    if local and grp != "gk":
        return random.choice(LOCAL_ACTIONS)
    return random.choice(AUTO_ACTIONS[grp])


GK_FACE = ("공은 가슴 높이에서 잡고 머리 위로 들어 올리지 않게, 공·장갑·뻗은 팔이 얼굴 앞을 가리지 않게 얼굴을 또렷하게 보여 주세요. ",
           "He holds the ball at chest height, never above his head; the ball, gloves and arms must not cover the face, which stays clearly visible. ")
FACE_CLEAR = ("얼굴에 손, 팔, 공의 그림자가 드리우지 않게 얼굴이 밝게 보이게 해 주세요. 팔 둘, 손가락 다섯, 몸 구조가 자연스럽게. ",
              "No shadows from hands, arms or the ball on the face; the face is well lit. Anatomically correct: two arms, five fingers per hand. ")
WAIST_UP = ("허리 위까지만 크게 담고 다리와 발은 화면 밖으로 나가게 해 주세요. ",
            "Frame from the waist up only; the legs and feet are outside the frame. ")


def youth_text(person: dict, lang: str) -> str:
    """작은 모델은 나이를 잘 안 따라와서 어린 선수는 더 세게 적는다."""
    try:
        age = int(str(person.get("age", "")).strip())
    except ValueError:
        return ""
    if age > 21:
        return ""
    if age >= 20:
        if lang == "ko":
            return f"{age}세, 20대 초반의 젊은 얼굴이에요. 주름이 없고 실제 나이보다 늙어 보이면 안 돼요. "
        return f"He is {age}, a young man in his early twenties with a fresh young face and no wrinkles; he must not look older. "
    if lang == "ko":
        return f"{age}세 10대 소년다운 앳된 얼굴이에요. 피부가 매끈하고 주름이 없고, 어른처럼 보이면 안 돼요. "
    return f"He is a {age}-year-old teenager with a youthful boyish face, smooth skin and no wrinkles; he must not look like an adult. "


def gunzo_prompt(person: dict, *, lang: str, has_ref: bool, ref_mode: str, has_kit: bool, action: str,
                 club_hint: str, local: bool = False) -> tuple[str, str]:
    """(프롬프트, 고른 동작)"""
    lang = "en" if lang == "en" else "ko"
    ko = lang == "ko"
    kind = person.get("kind", "player")
    act = pick_action(person, action)
    age = str(person.get("age", "")).strip()
    nat = str(person.get("nationality", "")).strip()
    plain_club = str(person.get("club", "")).strip()
    club = club_text(plain_club, club_hint, lang)
    role = ROLE.get(kind, ROLE["staff"])[lang]
    if ko:
        subject = " ".join(x for x in [f"{club} 소속" if club else "", f"{age}세" if age else "", f"{nat} 출신" if nat else "", role] if x)
    else:
        subject = " ".join([f"a {age}-year-old" if age else "a", role]) + (f" from {nat}" if nat else "") + (f" at {club}" if club else "")
    kit_index = (2 if has_ref else 1) if has_kit else 0
    if act == "touchline":
        outfit, badge_ok = outfit_text(kind, plain_club, kit_index, "training", lang)
    else:
        outfit, badge_ok = outfit_text("player", plain_club, kit_index, "", lang)
    vars_ = {
        "ref": ((REF_GAME if ref_mode == "game" else REF)[lang]) if has_ref else "",
        "subject": subject, "action": ACTIONS[act][0 if ko else 1], "outfit": outfit,
        "features": _features(person, age, lang, has_ref, ref_mode),
        "realism": REALISM[lang],
        "badge_note": (" (유니폼의 엠블럼과 스폰서는 괜찮아요)" if ko else " (the kit's badge and sponsor are fine)") if badge_ok else "",
    }
    text = GUNZO[lang].format(**vars_)
    i = 0 if ko else 1
    text += " " + FACE_CLEAR[i]
    if act in ("save", "catch", "gk_hold", "gk_throw", "gk_shout"):
        text += GK_FACE[i]
    if local:                       # 내 PC 그림도구: 다리를 자주 틀려서 아예 안 나오게, 나이는 더 세게
        text += WAIST_UP[i] + youth_text(person, lang)
    while "  " in text:
        text = text.replace("  ", " ")
    return text.strip(), act


def pos_label(person: dict) -> str:
    if person.get("kind", "player") != "player":
        return ""
    return POS_LABEL.get(POS_GROUP.get(str(person.get("pos", "")).lower(), ""), "")


# ---------------------------------------------------------------- 내 PC 그림도구용 짧은 프롬프트
# 그림도구는 프롬프트를 앞에서부터 일정 길이(약 512토큰)까지만 읽는다 → 중요한 것부터 짧게.
# 순서: 사람(나이·생김새) → 같은 사람 → 동작 → 유니폼 → 구도 → 배경
GK_BALL = "He holds the ball at chest height, never above his head and never in front of his face. "


def _local_person(person: dict, has_ref: bool, ref_mode: str) -> str:
    """피부색·머리를 맨 첫 마디에 (뒤에 두면 잘 안 따라옴)."""
    from . import appearance
    kind = person.get("kind", "player")
    age = str(person.get("age", "")).strip()
    nat = str(person.get("nationality", "")).strip()
    role = ROLE.get(kind, ROLE["staff"])["en"]
    who = (f"a {age}-year-old " if age else "a ") + role + (f" from {nat}" if nat else "")
    if has_ref and ref_mode == "photo":
        return (f"The exact same person as in image 1 (same face, hair, skin tone and age), {who}. "
                + youth_text(person, "en"))
    look = appearance.describe(str(person.get("look", "")), "en") or str(person.get("look_guess", ""))
    s = (f"{look[0].upper()}{look[1:]}: {who}. " if look else f"{who[0].upper()}{who[1:]}. ") + youth_text(person, "en")
    if has_ref:          # 게임 얼굴: 머리·피부는 따르되 진짜 사람처럼
        s += "Use image 1 (a 3D game face) for his hair, skin tone and face shape; make him a real human. "
    else:
        s += random_features(age, "en", with_hair=not look)
    return s


def _local_kit(person: dict, kit_index: int, club: str) -> str:
    if kit_index:
        return f"He wears the football kit shown in image {kit_index} (same colours, badge and sponsor). "
    return f"He wears the {club} home football kit. " if club else "He wears a plain football kit. "


def local_prompt(person: dict, *, task: str, has_ref: bool, ref_mode: str, has_kit: bool, action: str = "auto",
                 expression: str = "", club_hint: str = "") -> tuple[str, str]:
    """(프롬프트, 고른 동작)  task: face · kit · gunzo"""
    club = club_text(str(person.get("club", "")).strip(), club_hint, "en")
    kit_index = (2 if has_ref else 1) if has_kit else 0
    if task == "kit":
        s = ("Edit image 1. Keep the person exactly the same: face, hair, expression, pose, framing, background and lighting. "
             "Only change the clothes. " + _local_kit(person, 2 if has_kit else 0, club) + "Realistic photo. No text.")
        return s, ""
    if task == "gunzo":
        act = pick_action(person, action, local=True)
        s = _local_person(person, has_ref, ref_mode)
        s += f"In a night football match, {ACTIONS[act][1]}. "
        if act == "catch":
            s += GK_BALL
        if act != "touchline":
            s += _local_kit(person, kit_index, club)
        s += ("Waist-up shot, legs and feet outside the frame. His face is clearly visible, well lit, nothing covering it. "
              "Two arms, five fingers per hand. Telephoto sports photo, stadium floodlights and crowd blurred. "
              "Realistic photo, natural skin. No text, no numbers, no watermark.")
        return s, act
    expr = pick_expression(expression)
    s = _local_person(person, has_ref, ref_mode)
    s += f"He looks at the camera {EXPRESSIONS[expr]['en']}. "
    if person.get("kind", "player") == "player":
        s += _local_kit(person, kit_index, club)
    else:
        s += "He wears a club training jacket. "
    s += ("Head-and-shoulders portrait, centered, plain light grey studio background, soft even light. "
          "Realistic photo, natural skin texture. No text, no watermark.")
    return s, ""
