"""AI로 한꺼번에 그리기: 여러 사람을 차례로 그려서 결과를 모아 둔다.

사람마다 (프롬프트, 참고 사진들)을 만드는 일은 api 쪽 make_job 함수가 한다.
여기서는 순서대로 돌리고, 실패하면 잠깐 쉬었다 다시 하고, 결과를 파일로 남긴다.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path

from . import providers

log = logging.getLogger("batch")

# 1장 예상 요금 (미국 달러, 1024px 한 장 기준 · 참고 사진 입력 포함 대략값)
PRICE_USD = {
    **{m["id"]: m["usd"] for ms in providers.MODEL_CHOICES.values() for m in ms},
    "gemini-2.5-flash-image": 0.039,
    "gpt-image-2": 0.06,
    "gpt-image-1": 0.05,
    "grok-imagine-image-2.0": 0.07,
}
WON_PER_USD = 1450
AUTO_ENGINES = ("gemini", "openai", "xai", "codex", "cloudflare")


def price_of(pid: str, model: str, size: str = "") -> dict:
    """{"kind": "paid"|"free"|"sub", "usd": 1장 값}"""
    if pid == "cloudflare":
        return {"kind": "free", "usd": 0.0}
    if pid == "codex":
        return {"kind": "sub", "usd": 0.0}
    m = (model or providers.DEFAULT_MODELS.get(pid, "")).strip()
    if size == "512":
        small = next((x.get("small_usd") for ms in providers.MODEL_CHOICES.values() for x in ms if x["id"] == m), None)
        if small:
            return {"kind": "paid", "usd": small}
    usd = PRICE_USD.get(m)
    if usd is None:
        usd = next((v for k, v in PRICE_USD.items() if m.startswith(k.rsplit("-", 1)[0])), 0.07)
    return {"kind": "paid", "usd": usd}


class Batch:
    def __init__(self, folder: Path):
        self.dir = folder
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.items: list[dict] = []
        self.meta: dict = {}
        self.running = False
        self._stop = False
        self._thread: threading.Thread | None = None
        self._load()

    # ------------------------------------------------------------ 저장
    def _file(self) -> Path:
        return self.dir / "batch.json"

    def _load(self) -> None:
        try:
            d = json.loads(self._file().read_text(encoding="utf-8"))
            self.items = d.get("items", [])
            self.meta = d.get("meta", {})
        except Exception:
            self.items, self.meta = [], {}
        for it in self.items:          # 꺼진 사이 '그리는 중'이던 건 다시 대기로
            if it.get("status") == "running":
                it["status"] = "wait"
            if it.get("png") and not Path(it["png"]).exists():
                it["png"], it["status"] = "", "wait" if it.get("status") == "done" else it.get("status")

    def save(self) -> None:
        with self.lock:
            tmp = self._file().with_suffix(f".{uuid.uuid4().hex[:6]}.tmp")
            tmp.write_text(json.dumps({"items": self.items, "meta": self.meta}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._file())

    # ------------------------------------------------------------ 목록
    def reset(self, people: list[dict], meta: dict) -> None:
        with self.lock:
            for it in self.items:
                self._drop(it)
            self.items = [{"id": uuid.uuid4().hex, "uid": str(p.get("uid", "")).removeprefix("r-"), "person": p,
                           "status": "wait", "png": "", "err": "", "tries": 0} for p in people]
            self.meta = dict(meta)
            self.meta["spent"] = 0
            self.save()

    @staticmethod
    def _drop(it: dict) -> None:
        if it.get("png"):
            Path(it["png"]).unlink(missing_ok=True)

    def find(self, iid: str) -> dict | None:
        return next((i for i in self.items if i["id"] == iid), None)

    def drop(self, ids: list[str]) -> None:
        ids = set(ids)
        with self.lock:
            for it in [i for i in self.items if i["id"] in ids]:
                self._drop(it)
                self.items.remove(it)
            self.save()

    def again(self, ids: list[str]) -> None:
        with self.lock:
            for it in self.items:
                if it["id"] in ids and it["status"] != "running":
                    it["status"], it["err"] = "wait", ""
            self.save()

    # ------------------------------------------------------------ 돌리기
    def start(self, make_job, workers: int = 2) -> None:
        """make_job(item, meta) -> (prompt, photos) / 사람마다 한 번씩."""
        with self.lock:
            if self.running:
                return
            self.running, self._stop = True, False
        self._thread = threading.Thread(target=self._run, args=(make_job, max(1, min(int(workers), 4))), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop = True

    def _next(self) -> dict | None:
        with self.lock:
            it = next((i for i in self.items if i["status"] == "wait"), None)
            if it:
                it["status"] = "running"
            return it

    def _run(self, make_job, workers: int) -> None:
        try:
            ts = [threading.Thread(target=self._worker, args=(make_job,), daemon=True) for _ in range(workers)]
            for t in ts:
                t.start()
                time.sleep(0.4)
            for t in ts:
                t.join()
        finally:
            with self.lock:
                for it in self.items:
                    if it["status"] == "running":
                        it["status"] = "wait"
                self.running = False
                self.save()

    def _worker(self, make_job) -> None:
        pid, cfg = self.meta.get("engine"), dict(self.meta.get("cfg") or {})
        while not self._stop:
            it = self._next()
            if not it:
                return
            try:
                prompt, photos = make_job(it, self.meta)
                im = _square(self._gen(pid, cfg, prompt, photos))
                png = self.dir / f"{it['id']}_{int(time.time())}.png"
                im.save(png, "PNG")
                with self.lock:
                    self._drop(it)
                    it.update(status="done", png=str(png), err="", prompt=prompt)
                    it["tries"] = it.get("tries", 0) + 1
                    self.meta["spent"] = self.meta.get("spent", 0) + 1
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                log.warning("대량 그리기 실패 %s: %s", it.get("uid"), msg)
                with self.lock:
                    it.update(status="fail", err=_friendly(msg))
                if msg == "need_key" or "API key" in msg or "HTTP 401" in msg or "HTTP 403" in msg:
                    self._stop = True      # 키 문제면 남은 사람도 다 실패하니 멈춘다
            self.save()

    def _gen(self, pid, cfg, prompt, photos):
        wait = 15
        for n in range(4):
            if self._stop:
                raise RuntimeError("멈췄어요")
            try:
                return providers.generate(pid, cfg, prompt, photos or None)
            except Exception as e:  # noqa: BLE001
                s = str(e)
                busy = "429" in s or "RESOURCE_EXHAUSTED" in s or "503" in s or "overloaded" in s.lower() or "UNAVAILABLE" in s
                if not busy or n == 3:
                    raise
                for _ in range(wait):        # 사용량 제한 → 쉬었다 다시
                    if self._stop:
                        raise RuntimeError("멈췄어요") from None
                    time.sleep(1)
                wait *= 2
        raise RuntimeError("실패")

    # ------------------------------------------------------------ 화면용
    def counts(self) -> dict:
        c = {"wait": 0, "running": 0, "done": 0, "fail": 0}
        for it in self.items:
            c[it["status"]] = c.get(it["status"], 0) + 1
        return c


def _square(im):
    """AI가 가끔 정사각형이 아닌 그림을 준다 → 가운데 기준으로 잘라 맞춘다."""
    w, h = im.size
    if w == h:
        return im
    s = min(w, h)
    left = (w - s) // 2
    top = 0 if h > w else (h - s) // 2          # 세로로 길면 위쪽(머리) 기준
    return im.crop((left, top, left + s, top + s))


def _friendly(msg: str) -> str:
    if msg == "need_key":
        return "설정에서 API 키를 먼저 넣어 주세요."
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
        return "사용량 제한에 걸렸어요. 잠시 뒤 다시 해 보세요. (결제 등록이 안 된 키일 수도 있어요)"
    if "SAFETY" in msg or "PROHIBITED" in msg or "blockReason" in msg or "차단" in msg:
        return "AI가 그리기를 거절했어요. 다시 그리기를 눌러 보세요."
    if "HTTP 400" in msg and "billing" in msg.lower():
        return "결제가 등록되지 않은 키예요. 구글 AI 스튜디오에서 결제를 연결해 주세요."
    return msg[:300]
