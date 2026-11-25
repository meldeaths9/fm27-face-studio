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

    def search(self, name: str, team: str, kind: str, limit: int = 200, mine_if_empty: bool = False) -> list[dict]:
        n_toks, t_toks = norm(name).split(), norm(team).split()
        if not n_toks and not t_toks:
            if not mine_if_empty:
                return []
            res = [p for p in self.items if p.get("mine") and (not kind or p.get("kind") == kind)]
            res.sort(key=lambda p: (not p.get("me"), norm(p.get("name"))))
            return res[:limit]
        res = []
        for p, (nk, tk) in zip(self.items, self._keys):
            if kind and p.get("kind") != kind:
                continue
            if all(t in nk for t in n_toks) and all(t in tk for t in t_toks):
                res.append(p)
        # 내 감독 → 내 팀 → 이름순
        res.sort(key=lambda p: (not p.get("me"), not p.get("mine"), norm(p.get("name"))))
        return res[:limit]
