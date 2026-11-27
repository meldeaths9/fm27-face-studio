"""FM27 세이브 파일(.fm)에서 인물 목록 읽기 — fmsave (MIT, Randal S. Olson) 사용.

게임을 켜지 않아도 되고, BepInEx도 필요 없다. 읽은 결과는 캐시해 두고
세이브 파일이 바뀌지 않았으면 다시 읽지 않는다.
"""
from __future__ import annotations

import json
import logging
import os
import time
import warnings
from pathlib import Path

from .pack import looks_like_newgen
from .settings import app_data_dir, default_fm_user_dir

log = logging.getLogger("savedata")
CACHE_VERSION = 5

JOB_KO = {
    "COACH": "코치", "CHAIRPERSON": "회장", "DIRECTOR": "이사", "MANAGING_DIRECTOR": "대표이사",
    "DIRECTOR_OF_FOOTBALL": "단장", "PHYSIO": "물리치료사", "SCOUT": "스카우트", "MANAGER": "감독",
    "ASSISTANT_MANAGER": "수석코치", "SET_PIECE_COACH": "세트피스 코치", "FITNESS_COACH": "피지컬 코치",
    "GOALKEEPING_COACH": "골키퍼 코치", "CHIEF_DOCTOR": "의무팀장", "HEAD_OF_SPORTS_SCIENCE": "스포츠과학 팀장",
    "CHIEF_SCOUT": "수석 스카우트", "DOCTOR": "팀닥터", "SPORTS_SCIENTIST": "스포츠 과학자",
    "HEAD_PHYSIO": "수석 물리치료사", "RECRUITMENT_ANALYST": "영입 분석관", "PERFORMANCE_ANALYST": "경기 분석관",
    "HEAD_PERFORMANCE_ANALYST": "수석 분석관", "HEAD_OF_YOUTH_DEVELOPMENT": "유스 총괄", "OWNER": "구단주",
    "PRESIDENT": "회장", "LOAN_MANAGER": "임대 담당", "TECHNICAL_DIRECTOR": "기술이사",
}


def _pos(pl) -> str:
    """가장 잘하는 포지션 코드 (gk·dc·stc …). 모르면 빈칸."""
    try:
        nat = getattr(pl, "natural_positions", None) or getattr(pl, "accomplished_positions", None) or ()
        if nat:
            return str(nat[0]).lower()
        ps = getattr(pl, "positions", None)
        if ps is not None:
            keys = ("gk", "sw", "dl", "dc", "dr", "dm", "ml", "mc", "mr", "aml", "amc", "amr", "stc", "wbl", "wbr")
            best = max(keys, key=lambda k: int(getattr(ps, k, 0) or 0))
            return best if int(getattr(ps, best, 0) or 0) > 0 else ""
    except Exception:  # noqa: BLE001
        pass
    return ""


def default_games_dir() -> Path:
    return default_fm_user_dir() / "games"


def cache_path() -> Path:
    return app_data_dir() / "save_cache.json"


def _stamp(path: Path) -> dict:
    st = path.stat()
    return {"save": str(path), "size": st.st_size, "mtime": st.st_mtime}


def load_cache(path: str | Path | None = None) -> dict | None:
    """캐시가 있고(경로를 주면 그 세이브가 그대로일 때) 돌려줌."""
    try:
        data = json.loads(cache_path().read_text(encoding="utf-8"))
    except Exception:
        return None
    if data.get("version") != CACHE_VERSION:
        return None
    if path is not None:
        p = Path(path)
        try:
            if _stamp(p) != {k: data.get(k) for k in ("save", "size", "mtime")}:
                return None
        except OSError:
            return None
    return data


def _name(rec) -> str:
    for attr in ("name", "common_name", "full_name"):
        v = getattr(rec, attr, None)
        if v:
            return str(v)
    first, last = getattr(rec, "first_name", None), getattr(rec, "last_name", None)
    return " ".join(x for x in (first, last) if x) or ""


SQUADS = ("1군", "2군", "U-21", "U-18")


def _label_squads(players: list[dict], keys: list[tuple]) -> None:
    """클럽 안의 팀 칸(slot)으로 1군/2군/U-21/U-18을 나눈다.
    세이브에는 칸 번호만 있고 어느 칸이 유스팀인지는 없어서, 0번 칸은 1군, 나머지는 그 칸 선수들의 평균 나이로 정한다."""
    from collections import defaultdict
    ages: dict[tuple, list[int]] = defaultdict(list)
    for p, (cuid, tclub, slot) in zip(players, keys):
        if slot is None or cuid is None:
            continue
        try:
            ages[(cuid, tclub, slot)].append(int(p["age"]))
        except (TypeError, ValueError):
            pass
    label: dict[tuple, str] = {}
    for k, a in ages.items():
        cuid, tclub, slot = k
        if slot == 0 and (tclub is None or tclub == cuid):
            label[k] = "1군"
            continue
        avg = sum(a) / len(a) if a else 99
        label[k] = "U-18" if avg < 18.6 else "U-21" if avg < 21.6 else "2군"
    for p, k in zip(players, keys):
        p["squad"] = label.get(k, "")


def _mark_same_name_clubs(people: list[dict], my_club_uids: set) -> None:
    """이름이 같은 다른 클럽(예: 잉글랜드 Liverpool / 우루과이 Liverpool)을 구분한다.
    내 클럽, 없으면 평판이 가장 높은 클럽이 '본' 클럽이고 나머지에 표시를 붙인다."""
    from collections import defaultdict
    clubs: dict[str, dict] = defaultdict(dict)       # name -> {uid: (rep, nation)}
    for p in people:
        if p.get("club") and p.get("cuid") is not None:
            cur = clubs[p["club"]].get(p["cuid"], (0, None))
            clubs[p["club"]][p["cuid"]] = (max(cur[0], p.get("crep") or 0), cur[1] if cur[1] is not None else p.get("cnat"))
    main: dict[str, tuple] = {}
    for name, m in clubs.items():
        if len(m) < 2:
            continue
        mine = [u for u in m if u in my_club_uids]
        uid = mine[0] if mine else max(m, key=lambda u: m[u][0])
        main[name] = (uid, m[uid][1])
    for p in people:
        p["alt"] = ""
        mm = main.get(p.get("club", ""))
        if not mm or p.get("cuid") is None or p["cuid"] == mm[0]:
            continue
        nat = p.get("cnat")
        p["alt"] = "다른 나라" if (nat is not None and mm[1] is not None and nat != mm[1]) else "동명 클럽"


def read_save(path: str | Path) -> dict:
    """세이브를 읽어 인물 목록을 만들고 캐시에 저장."""
    import fmsave  # 무거운 import는 필요할 때만

    p = Path(path)
    t0 = time.time()
    people: list[dict] = []
    my_clubs: list[dict] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with fmsave.open(p) as s:
            info = s.info
            for m in s.managed_clubs():
                my_clubs.append({"uid": m.club_uid, "name": m.club_name, "short": m.club_short_name,
                                 "manager": m.manager_name, "manager_staff_uid": m.manager_staff_uid})
            my_club_uids = {c["uid"] for c in my_clubs}

            squad_keys: list[tuple] = []
            for pl in s.players():
                uid = pl.unique_id
                if uid is None:
                    continue
                club = pl.club_name or ""
                slot = getattr(pl, "team_slot", None)
                tclub = getattr(pl, "team_club_uid", None)
                cuid = getattr(pl, "club_uid", None)
                squad_keys.append((cuid, tclub, slot))
                people.append({
                    "uid": str(uid), "name": _name(pl), "club": club, "age": pl.age or "",
                    "kind": "player", "newgen": looks_like_newgen(str(uid)), "job": "",
                    "mine": cuid is not None and cuid in my_club_uids, "me": False, "squad": "",
                    "cuid": cuid, "crep": getattr(pl, "club_reputation", None) or 0,
                    "cnat": getattr(pl, "club_nation_id", None), "pos": _pos(pl),
                })
            _label_squads([p for p in people if p["kind"] == "player"], squad_keys)
            for st in s.staff():
                uid = st.unique_id
                if uid is None:
                    continue
                job = ""
                if st.job is not None and getattr(st.job, "label", None) is not None:
                    job = JOB_KO.get(st.job.label.name, "")
                club = st.club_name or ""
                scuid = getattr(st, "club_uid", None)
                people.append({
                    "uid": str(uid), "name": _name(st), "club": club, "age": st.age or "",
                    "kind": "staff", "newgen": bool(st.is_human_manager) or looks_like_newgen(str(uid)),
                    "job": "내 감독" if st.is_human_manager else job,
                    "mine": scuid is not None and scuid in my_club_uids, "me": bool(st.is_human_manager),
                    "cuid": scuid, "crep": 0, "cnat": None,
                })
    if my_clubs and not any(p["mine"] for p in people):       # 클럽 번호가 안 맞으면 예전처럼 이름으로
        names = {c["name"] for c in my_clubs}
        for p in people:
            p["mine"] = p["club"] in names
    _mark_same_name_clubs(people, my_club_uids)
    data = {
        "version": CACHE_VERSION, **_stamp(p),
        "game": f"{getattr(getattr(info, 'version', None), 'major', '')}",
        "my_clubs": my_clubs, "people": people, "read_seconds": round(time.time() - t0, 1), "read_at": time.time(),
    }
    tmp = cache_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, cache_path())
    log.info("세이브 읽음: %s명, %.1f초", len(people), time.time() - t0)
    return data


# ------------------------------------------------------------------ 현재 세이브 찾기
def preferences_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / "Sports Interactive" / "Football Manager 27" / "Preferences"


_FM_PATH_RX = None


def last_saved_game() -> str:
    """게임이 기억하는 '가장 최근 세이브' 경로 (Preferences\\version N\\last_saved_game.xml).
    없으면 games 폴더에서 가장 최근에 저장된 .fm."""
    import re
    global _FM_PATH_RX
    if _FM_PATH_RX is None:
        _FM_PATH_RX = re.compile(r'(?:"|>)([^"<>|\r\n]+?\.fm)(?="|<)', re.I)
    pref = preferences_dir()
    candidates: list[tuple[float, str]] = []
    if pref.is_dir():
        for xml in pref.rglob("last_save*.xml"):
            try:
                text = xml.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for m in _FM_PATH_RX.finditer(text):
                p = Path(m.group(1).strip())
                if p.exists():
                    candidates.append((xml.stat().st_mtime, str(p)))
    if candidates:
        return max(candidates)[1]
    games = default_games_dir()
    if games.is_dir():
        fms = sorted(games.glob("*.fm"), key=lambda p: p.stat().st_mtime, reverse=True)
        if fms:
            return str(fms[0])
    return ""
