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
CACHE_VERSION = 2

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
            my_club_names = {c["name"] for c in my_clubs}

            for pl in s.players():
                uid = pl.unique_id
                if uid is None:
                    continue
                club = pl.club_name or ""
                people.append({
                    "uid": str(uid), "name": _name(pl), "club": club, "age": pl.age or "",
                    "kind": "player", "newgen": looks_like_newgen(str(uid)), "job": "",
                    "mine": club in my_club_names, "me": False,
                })
            for st in s.staff():
                uid = st.unique_id
                if uid is None:
                    continue
                job = ""
                if st.job is not None and getattr(st.job, "label", None) is not None:
                    job = JOB_KO.get(st.job.label.name, "")
                club = st.club_name or ""
                people.append({
                    "uid": str(uid), "name": _name(st), "club": club, "age": st.age or "",
                    "kind": "staff", "newgen": bool(st.is_human_manager) or looks_like_newgen(str(uid)),
                    "job": "내 감독" if st.is_human_manager else job,
                    "mine": club in my_club_names, "me": bool(st.is_human_manager),
                })
    data = {
        "version": CACHE_VERSION, **_stamp(p),
        "game": f"{getattr(getattr(info, 'version', None), 'major', '')}",
        "my_clubs": my_clubs, "people": people, "read_seconds": round(time.time() - t0, 1),
    }
    tmp = cache_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, cache_path())
    log.info("세이브 읽음: %s명, %.1f초", len(people), time.time() - t0)
    return data
