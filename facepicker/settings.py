"""설정 저장/불러오기와 기본 경로 찾기."""
from __future__ import annotations

import json
import os
import sys
import threading as _th
from pathlib import Path

_SAVE_LOCK = _th.RLock()

APP_NAME = "FM27FacePicker"
PACK_FOLDER_NAME = "zzz_FMFaceStudio"    # graphics 폴더 안에 만들 이 프로그램 전용 폴더
# FM은 graphics 안 폴더를 이름순으로 읽고, 뒤에 읽은 폴더가 앞 폴더를 덮어쓴다 → 맨 뒤로 오게 zzz_
OLD_PACK_FOLDER_NAMES = ("FacePicker",)


def valid_pack_name(name: str) -> bool:
    import re
    return bool(name) and len(name) <= 60 and not re.search(r'[\\/:*?"<>|]', name) and name.strip(". ") == name

def pack_sort_key(name: str) -> str:
    return str(name).casefold()
FM_FOLDER_NAME = "Football Manager 27"
SETTINGS_VERSION = 5

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
UNIFORM_PROMPT = (
    "Edit the first attached photo. Keep the person exactly the same: face, identity, expression, hairstyle, "
    "skin tone, pose, head size and position, framing, background and lighting. Only replace the visible clothing "
    "with {kit_text}. Make the new shirt look like a real photo with natural fabric folds that fit the body and pose. "
    "Do not add any other text, watermark or logo."
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
    """FM27 사용자 폴더. 윈도우 '문서' → OneDrive 문서 → 사용자 폴더의 문서 순으로, FM27 폴더가 있는 곳."""
    cands = [documents_dir()]
    od = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    if od:
        cands += [Path(od) / "Documents", Path(od) / "문서"]
    cands.append(Path.home() / "Documents")
    for c in cands:
        p = c / "Sports Interactive" / FM_FOLDER_NAME
        if p.is_dir():
            return p
    return cands[0] / "Sports Interactive" / FM_FOLDER_NAME


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
        self.game_dir: str = ""
        self.auto_refresh: bool = True
        self.pack_folder: str = PACK_FOLDER_NAME   # graphics 안 내 폴더 이름 (이름순으로 뒤일수록 이긴다)
        self.pinned: dict = {}             # 고정한 선수 uid → 이름 (다른 팀을 검색해도 맨 위에)
        self.ab_deco: dict = {}            # AI로 한꺼번에 그리기의 꾸미기
        self.kit_hidden: list = []         # 유니폼 고르기에서 숨긴 유니폼 번호
        self.kit_aliases: dict = {}        # 사용자가 '이 구단 유니폼으로 기억'한 짝: 유니폼 번호 -> 구단 번호
        self.bulk_crop: str = "face"      # 대량·끌어다 놓기 자르기: face(얼굴 맞춤) / keep(그대로, 위쪽 맞춤)
        self.bulk_deco: str = "none"      # 대량·끌어다 놓기 꾸미기: follow(편집 화면 설정) / none
        self.check_updates: bool = True
        self.pause_on_fm: bool = False     # FM27이 켜져 있으면 내 PC 그림도구는 잠깐 멈춤
        self.drawtool_dir: str = ""        # 내 PC 그림도구 폴더 (비우면 %LOCALAPPDATA%\FMFaceStudio_DrawTool)
        self.beta_updates: bool = False   # 테스트 버전(prerelease)도 받기   # 켤 때 GitHub에서 새 버전 확인
        self.skip_version: str = ""       # '이 버전 건너뛰기'
        self.follow_save: bool = False    # 게임의 '가장 최근 세이브'를 자동으로 따라가기 (기본: 끔)
        self.output_size: int = 512
        self.prompt_template: str = ""     # 비어 있으면 기본 프롬프트(언어별)
        self.prompt_lang: str = "ko"       # ko / en (클라우드플레어는 항상 영어)
        self.expression: str = "random"
        self.ref_mode: str = "game"        # game: 참고 사진이 게임 3D 얼굴(느슨하게) / photo: 실제 사진(그대로)
        self.manager_outfit: str = "suit"  # suit / training
        self.manager_uid: str = ""         # 내 감독 UID (세이브 없이 넣었을 때도 기억)
        self.club_hints: dict = {}         # {클럽 이름: "잉글랜드 크로즈비의 클럽"}
        self.send_photo: bool = True
        self.ai_provider: str = "web_gemini"
        self.ai_cfg: dict = {}          # {provider_id: {"key":..., "model":..., "account":...}}
        self.deco: dict = {"caption": False, "style": "gold", "rounded": False, "radius": 14, "border": False}
        self.load()

    @property
    def path(self) -> Path:
        return app_data_dir() / self.FILE

    def load(self) -> None:
        data = None
        for f in (self.path, self.path.with_suffix(".bak")):     # 깨졌으면 지난 정상본으로
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                break
            except Exception:
                continue
        if not isinstance(data, dict):
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
        if old_version < 4:
            self.follow_save = False
            if self.prompt_template.strip() == DEFAULT_PROMPT.strip():
                self.prompt_template = ""
        if old_version < 5:              # 기본 꾸미기를 '없음'으로 (꾸민 건 지우기 어려우니)
            self.bulk_deco = "none"
        if old_version < SETTINGS_VERSION:
            self.settings_version = SETTINGS_VERSION
            self.save()

    def save(self) -> None:
        import threading
        with _SAVE_LOCK:
            keep = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
            text = json.dumps(keep, ensure_ascii=False, indent=2)
            tmp = self.path.with_name(f"settings.{threading.get_ident()}.tmp")
            tmp.write_text(text, encoding="utf-8")
            try:      # 지난 정상본을 .bak으로 (깨지면 거기서 살린다)
                if self.path.exists():
                    os.replace(self.path, self.path.with_suffix(".bak"))
            except OSError:
                pass
            os.replace(tmp, self.path)

    @property
    def pack_name(self) -> str:
        n = str(getattr(self, "pack_folder", "") or "").strip()
        return n if valid_pack_name(n) else PACK_FOLDER_NAME

    @property
    def pack_dir(self) -> Path:
        g = Path(self.graphics_dir)
        new = g / self.pack_name
        if not new.exists():
            for o in OLD_PACK_FOLDER_NAMES:      # 옮기기에 실패했으면(게임이 잡고 있음 등) 예전 폴더를 계속 쓴다
                if (g / o / "config.xml").exists():
                    return g / o
        return new

    def migrate_pack_dir(self) -> str:
        """예전 폴더(FacePicker)를 맨 뒤로 오는 이름으로 옮긴다. 돌려주는 값: 'moved' / 'failed' / ''."""
        g = Path(self.graphics_dir)
        new = g / self.pack_name
        for o in OLD_PACK_FOLDER_NAMES:
            old = g / o
            if old.is_dir() and (old / "config.xml").exists() and not new.exists():
                try:
                    old.rename(new)
                    return "moved"
                except OSError:
                    return "failed"
        return ""
