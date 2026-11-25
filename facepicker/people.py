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
               squad: str = "") -> list[dict]:
        n_toks, t_toks = norm(name).split(), norm(team).split()
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
