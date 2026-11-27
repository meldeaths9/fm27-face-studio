"""인물 목록 검색 (이름칸·팀칸 따로)."""
from __future__ import annotations

import unicodedata


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


class People:
    def __init__(self) -> None:
        self.items: list[dict] = []
        self.my_clubs: list[dict] = []
        self.save: str = ""
        self._keys: list[tuple[str, str]] = []

    def set(self, data: dict | None) -> None:
        data = data or {}
        self.items = list(data.get("people", []))
        self.my_clubs = list(data.get("my_clubs", []))
        self.save = data.get("save", "")
        self._keys = [(norm(p.get("name")) + " " + p.get("uid", ""), norm(p.get("club"))) for p in self.items]
        self.version = getattr(self, "version", 0) + 1

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
