"""인물 목록 검색 (이름칸·팀칸 따로)."""
from __future__ import annotations

import sys
import unicodedata

_FIELDS = ("uid", "name", "club", "age", "kind", "newgen", "job", "mine", "me", "squad", "cuid", "crep", "cnat",
           "pos", "h", "alt")
_INTERN = ("club", "kind", "job", "squad", "pos", "alt")


class Person:
    """인물 한 명. dict처럼 쓰지만 (p.get, p["x"], dict(p), {**p}) 메모리는 1/3쯤만 쓴다.
    세이브에 수만~수십만 명이 있어서 dict로 들고 있으면 수백 MB가 된다."""
    __slots__ = _FIELDS + ("_x",)

    def __init__(self, d: dict) -> None:
        for k in _FIELDS:
            v = d.get(k)
            if k in _INTERN and isinstance(v, str):
                v = sys.intern(v)
            object.__setattr__(self, k, v)
        extra = {k: v for k, v in d.items() if k not in _FIELDS}
        object.__setattr__(self, "_x", extra or None)

    @classmethod
    def from_row(cls, row):
        o = cls.__new__(cls)
        for k, v in zip(_FIELDS, row):
            if k in _INTERN and isinstance(v, str):
                v = sys.intern(v)
            object.__setattr__(o, k, v)
        object.__setattr__(o, "_x", None)
        return o

    def get(self, k, default=None):
        if k in _FIELDS:
            v = getattr(self, k)
            return default if v is None else v
        x = self._x
        return x.get(k, default) if x else default

    def __getitem__(self, k):
        if k in _FIELDS:
            v = getattr(self, k)
            if v is None:
                raise KeyError(k)
            return v
        if self._x and k in self._x:
            return self._x[k]
        raise KeyError(k)

    def __setitem__(self, k, v) -> None:
        if k in _FIELDS:
            object.__setattr__(self, k, v)
        else:
            if self._x is None:
                object.__setattr__(self, "_x", {})
            self._x[k] = v

    def __contains__(self, k) -> bool:
        return self.get(k) is not None

    def keys(self):
        out = [k for k in _FIELDS if getattr(self, k) is not None]
        if self._x:
            out += list(self._x)
        return out

    def items(self):
        return [(k, self[k]) for k in self.keys()]

    def __iter__(self):
        return iter(self.keys())

    def __len__(self) -> int:
        return len(self.keys())

    def to_dict(self) -> dict:
        return {k: self[k] for k in self.keys()}


def plain(obj):
    """화면(JSON)으로 보내기 전에 Person을 dict로."""
    if isinstance(obj, Person):
        return obj.to_dict()
    if isinstance(obj, dict):
        return {k: plain(v) for k, v in obj.items()} if any(isinstance(v, (Person, list, dict)) for v in obj.values()) else obj
    if isinstance(obj, list):
        return [plain(v) for v in obj] if any(isinstance(v, (Person, list, dict)) for v in obj) else obj
    return obj


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


class People:
    def __init__(self) -> None:
        self.items: list[dict] = []
        self.my_clubs: list[dict] = []
        self.save: str = ""
        self._keys: list[tuple[str, str]] = []
        self._by_uid = None

    def set(self, data: dict | None) -> None:
        data = data or {}
        cols = data.pop("cols", None)
        if cols:
            n = len(cols.get("uid") or [])
            get = [cols.get(k) or [None] * n for k in _FIELDS]
            self.items = [Person.from_row(row) for row in zip(*get)]
            cols.clear()
        else:
            self.items = [p if isinstance(p, Person) else Person(p) for p in data.get("people", [])]
        data.pop("people", None)          # 원본 목록은 바로 버린다
        self.my_clubs = list(data.get("my_clubs", []))
        self.save = data.get("save", "")
        club_keys: dict = {}
        def ck(c):
            k = club_keys.get(c)
            if k is None:
                k = club_keys[c] = norm(c)
            return k
        self._keys = [(norm(p.get("name")) + " " + str(p.get("uid", "")), ck(p.get("club") or "")) for p in self.items]
        self.version = getattr(self, "version", 0) + 1
        self._by_uid = None
        try:
            from . import memlog
            memlog.trim()
            memlog.mark(f"세이브 인물 {len(self.items)}명 올림")
        except Exception:  # noqa: BLE001
            pass

    def by_uid(self, uid):
        """UID → 사람 (r- 떼고). 처음 찾을 때 한 번 만든다."""
        if self._by_uid is None:
            self._by_uid = {str(p.get("uid", "")).removeprefix("r-"): p for p in self.items}
        return self._by_uid.get(str(uid).removeprefix("r-"))

    def clubs(self, team: str, limit: int = 12) -> list[dict]:
        """팀 이름 입력 → 고를 수 있는 클럽 목록 (같은 이름이어도 클럽 번호로 따로)."""
        t_toks = norm(team).split()
        if not t_toks:
            return []
        acc: dict = {}
        for p, (_nk, tk) in zip(self.items, self._keys):
            cu = p.get("cuid")
            if not cu or not p.get("club") or not all(t in tk for t in t_toks):
                continue
            c = acc.setdefault(str(cu), {"cuid": str(cu), "name": p["club"], "alt": p.get("alt", ""), "mine": bool(p.get("mine")),
                                         "players": 0, "rep": p.get("crep") or 0, "_best": None})
            if p.get("kind") == "player":
                c["players"] += 1
                if not p.get("newgen") and c["_best"] is None:
                    c["_best"] = p.get("name")
        out = sorted(acc.values(), key=lambda c: (not c["mine"], bool(c["alt"]), -(c["rep"] or 0), c["name"]))[:limit]
        for c in out:
            c["example"] = c.pop("_best") or ""
        return out

    @staticmethod
    def _kind_ok(p: dict, kind: str) -> bool:
        if not kind:
            return True
        if kind == "manager":
            return bool(p.get("me"))
        if kind == "staff":
            return p.get("kind") == "staff" and not p.get("me")
        return p.get("kind") == kind

    def search(self, name: str, team: str, kind: str, limit: int = 200, mine_if_empty: bool = False,
               squad: str = "", club: str = "") -> list[dict]:
        n_toks, t_toks = norm(name).split(), norm(team).split()
        if club:          # 목록에서 고른 클럽 하나 (이름이 같은 다른 나라 클럽은 빼고)
            res = [p for p, (nk, _tk) in zip(self.items, self._keys)
                   if str(p.get("cuid", "")) == str(club) and self._kind_ok(p, kind)
                   and (not squad or p.get("squad") == squad) and all(t in nk for t in n_toks)]
            order = {"1군": 0, "2군": 1, "U-21": 2, "U-18": 3}
            res.sort(key=lambda p: (not p.get("me"), order.get(p.get("squad", ""), 9), norm(p.get("name"))))
            return res[:limit]
        if not n_toks and not t_toks:
            if not mine_if_empty and kind != "manager":
                return []
            res = [p for p in self.items if (p.get("mine") or kind == "manager") and self._kind_ok(p, kind)
                   and (not squad or p.get("squad") == squad)]
            order = {"1군": 0, "2군": 1, "U-21": 2, "U-18": 3}
            res.sort(key=lambda p: (not p.get("me"), order.get(p.get("squad", ""), 9), norm(p.get("name"))))
            return res[:limit]
        res = []
        for p, (nk, tk) in zip(self.items, self._keys):
            if not self._kind_ok(p, kind):
                continue
            if squad and p.get("squad") != squad:
                continue
            if all(t in nk for t in n_toks) and all(t in tk for t in t_toks):
                res.append(p)
        # 내 감독 → 내 팀 → 이름순
        res.sort(key=lambda p: (not p.get("me"), not p.get("mine"), bool(p.get("alt")), norm(p.get("name"))))
        return res[:limit]
