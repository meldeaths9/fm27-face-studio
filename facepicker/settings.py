"""설정 저장/불러오기와 기본 경로 찾기."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "FM27FacePicker"
PACK_FOLDER_NAME = "FacePicker"          # graphics 폴더 안에 만들 이 프로그램 전용 폴더
FM_FOLDER_NAME = "Football Manager 27"
SETTINGS_VERSION = 3

GEMINI_MODELS = [
    "gemini-3.1-flash-image",
    "gemini-3.1-flash-image-preview",
    "gemini-2.5-flash-image",
]

DEFAULT_PROMPT = (
    "{ref}Create a realistic head-and-shoulders portrait photo of a {role}, "
    "{age_text}{nationality_text}. Facing the camera, neutral expression, "
    "plain light grey studio background, soft even lighting. Square 1:1 framing, "
    "head centered with a little space above the hair, shoulders visible. "
    "No text, no logos, no watermark."
)
REF_SENTENCE = (
    "Use the attached photo as the reference: keep this person's face, identity, "
    "skin tone and hairstyle. "
)


def documents_dir() -> Path:
    """윈도우 '문서' 폴더 (OneDrive로 옮긴 경우도 포함)."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            # CSIDL_PERSONAL = 5
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
                return Path(buf.value)
        except Exception:
            pass
    return Path.home() / "Documents"


def default_fm_user_dir() -> Path:
    return documents_dir() / "Sports Interactive" / FM_FOLDER_NAME


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA")
    d = Path(base) / APP_NAME if base else Path.home() / f".{APP_NAME}"
    d.mkdir(parents=True, exist_ok=True)
    return d


class Settings:
    FILE = "settings.json"

    def __init__(self) -> None:
        fm = default_fm_user_dir()
        self.settings_version: int = SETTINGS_VERSION
        self.graphics_dir: str = str(fm / "graphics")
        self.last_save: str = ""
        self.output_size: int = 512
        self.prompt_template: str = DEFAULT_PROMPT
        self.send_photo: bool = True
        self.ai_provider: str = "web_gemini"
        self.ai_cfg: dict = {}          # {provider_id: {"key":..., "model":..., "account":...}}
        self.deco: dict = {"caption": False, "style": "gold", "rounded": False, "radius": 14, "border": False}
        self.load()

    @property
    def path(self) -> Path:
        return app_data_dir() / self.FILE

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        old_version = data.get("settings_version", 1)
        for k, v in data.items():
            if hasattr(self, k) and not k.startswith("_"):
                setattr(self, k, v)
        # 예전 버전 설정 옮기기
        if old_version < 3:
            if data.get("gemini_key"):
                self.ai_cfg.setdefault("gemini", {})["key"] = data["gemini_key"]
                self.ai_cfg["gemini"]["model"] = data.get("gemini_model", "")
            if self.output_size == 250:
                self.output_size = 512
            self.settings_version = SETTINGS_VERSION
            self.save()

    def save(self) -> None:
        keep = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(keep, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    @property
    def pack_dir(self) -> Path:
        return Path(self.graphics_dir) / PACK_FOLDER_NAME
