"""세이브 인물 목록(people.json) 검색.

2단계에서 만들 FM27 플러그인이 아래 형식으로 내보낼 예정:
[{"uid": "12345", "name": "...", "club": "...", "age": 21, "nationality": "...",
  "kind": "player" | "staff", "newgen": false}, ...]
"""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


@dataclass
class Person:
    uid: str
    name: str
    club: str = ""
    age: str = ""
    nationality: str = ""
    kind: str = "player"
    newgen: bool = False
    key: str = ""


class People:
    def __init__(self) -> None:
        self.items: list[Person] = []
        self.source: Path | None = None
        self.mtime: float = 0

    def load(self, path: str | Path) -> int:
        p = Path(path)
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw = raw.get("people", [])
        items = []
        for r in raw:
            uid = str(r.get("uid", "")).strip()
            if not uid.isdigit():
                continue
            person = Person(
                uid=uid, name=str(r.get("name", "")), club=str(r.get("club", "") or ""),
                age=str(r.get("age", "") or ""), nationality=str(r.get("nationality", "") or ""),
                kind="staff" if r.get("kind") == "staff" else "player", newgen=bool(r.get("newgen")),
            )
            person.key = norm(f"{person.name} {person.club} {person.uid}")
            items.append(person)
        self.items, self.source, self.mtime = items, p, p.stat().st_mtime
        return len(items)

    def search(self, query: str, kind: str, limit: int = 300) -> list[Person]:
        toks = norm(query).split()
        res = []
        for p in self.items:
            if kind and p.kind != kind:
                continue
            if all(t in p.key for t in toks):
                res.append(p)
                if len(res) >= limit:
                    break
        return res
