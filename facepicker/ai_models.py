"""가벼운 AI 모델: 얼굴 찾기(UltraFace, exe에 포함)와 배경 제거(U²-Net, 처음 쓸 때 내려받기).

둘 다 ONNX Runtime 하나로 돌린다 (OpenCV 불필요).
"""
from __future__ import annotations

import hashlib
import os
import sys
import threading
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

from .settings import app_data_dir

BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
FACE_MODEL = BASE / "models" / "ultraface-rfb-320.onnx"

BG_MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net_human_seg.onnx"
BG_MODEL_NAME = "u2net_human_seg.onnx"
BG_MODEL_MIN_BYTES = 100_000_000   # 약 168MB — 덜 받아진 파일 걸러내기

_lock = threading.Lock()
_face_sess = None
_bg_sess = None


def _ort():
    import onnxruntime as ort  # 무거운 import는 필요할 때만
    return ort


def _session(path: Path):
    ort = _ort()
    opts = ort.SessionOptions()
    opts.log_severity_level = 3
    return ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])


# ------------------------------------------------------------------ 얼굴 찾기
def face_available() -> bool:
    try:
        _ort()
    except Exception:
        return False
    return FACE_MODEL.exists()


def _nms(boxes: np.ndarray, scores: np.ndarray, thr: float = 0.3) -> list[int]:
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
        yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
        xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
        yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
        iou = inter / (area[i] + area[order[1:]] - inter + 1e-9)
        order = order[1:][iou < thr]
    return keep


def detect_face(im: Image.Image, threshold: float = 0.7):
    """가장 큰 얼굴의 (x, y, w, h) — 원본 픽셀 기준. 못 찾으면 None."""
    global _face_sess
    if not face_available():
        return None
    with _lock:
        if _face_sess is None:
            _face_sess = _session(FACE_MODEL)
    w, h = im.size
    rgb = im.convert("RGB").resize((320, 240), Image.BILINEAR)
    x = (np.asarray(rgb, dtype=np.float32) - 127.0) / 128.0
    x = x.transpose(2, 0, 1)[None]
    scores, boxes = _face_sess.run(None, {_face_sess.get_inputs()[0].name: x})
    sc = scores[0, :, 1]
    mask = sc > threshold
    if not mask.any():
        return None
    b, s = boxes[0][mask], sc[mask]
    keep = _nms(b, s)
    b = b[keep]
    areas = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    x1, y1, x2, y2 = b[int(areas.argmax())]
    x1, x2 = max(0.0, x1) * w, min(1.0, x2) * w
    y1, y2 = max(0.0, y1) * h, min(1.0, y2) * h
    if x2 - x1 < 8 or y2 - y1 < 8:
        return None
    return (float(x1), float(y1), float(x2 - x1), float(y2 - y1))


# ------------------------------------------------------------------ 배경 제거
def bg_model_path() -> Path:
    d = app_data_dir() / "models"
    d.mkdir(exist_ok=True)
    return d / BG_MODEL_NAME


def bg_ready() -> bool:
    p = bg_model_path()
    return p.exists() and p.stat().st_size >= BG_MODEL_MIN_BYTES


def download_bg_model(progress=None) -> Path:
    """배경 제거 모델 내려받기. progress(받은바이트, 전체바이트)."""
    dst = bg_model_path()
    if bg_ready():
        return dst
    tmp = dst.with_suffix(".part")
    req = urllib.request.Request(BG_MODEL_URL, headers={"User-Agent": "FM27FaceStudio"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if tmp.stat().st_size < BG_MODEL_MIN_BYTES:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("배경 제거 모델을 끝까지 받지 못했어요. 인터넷 연결을 확인하고 다시 시도해 주세요.")
    os.replace(tmp, dst)
    return dst


_bg_timer = None


def _release_bg_later(sec: float = 90) -> None:
    """배경 제거 모델(메모리 수백 MB)은 한동안 안 쓰면 내려놓는다."""
    global _bg_timer
    import threading
    if _bg_timer:
        _bg_timer.cancel()

    def drop():
        global _bg_sess
        with _lock:
            _bg_sess = None
        from . import memlog
        memlog.trim()
        memlog.mark("배경 제거 모델 내려놓음")
    _bg_timer = threading.Timer(sec, drop)
    _bg_timer.daemon = True
    _bg_timer.start()


def remove_background(im: Image.Image) -> Image.Image:
    """사람 영역만 남기고 배경을 투명하게 (U²-Net human seg)."""
    global _bg_sess
    if not bg_ready():
        raise RuntimeError("배경 제거 모델이 아직 없어요.")
    with _lock:
        if _bg_sess is None:
            _bg_sess = _session(bg_model_path())
    src = im.convert("RGB")
    x = np.asarray(src.resize((320, 320), Image.LANCZOS), dtype=np.float32)
    x = x / max(float(x.max()), 1e-6)
    x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
    x = x.transpose(2, 0, 1)[None].astype(np.float32)
    out = _bg_sess.run(None, {_bg_sess.get_inputs()[0].name: x})[0][0, 0]
    _release_bg_later()
    lo, hi = float(out.min()), float(out.max())
    out = (out - lo) / (hi - lo + 1e-9)
    mask = Image.fromarray((out * 255).astype(np.uint8), "L").resize(src.size, Image.LANCZOS)
    res = im.convert("RGBA")
    res.putalpha(Image.fromarray(np.minimum(np.asarray(res.getchannel("A")), np.asarray(mask))))
    return res


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
