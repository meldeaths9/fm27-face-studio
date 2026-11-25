"""FM27 Face Studio 실행 파일."""
import sys
from pathlib import Path

BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def selftest() -> int:
    """빌드 서버에서 exe가 제대로 묶였는지 확인 (창은 띄우지 않음)."""
    try:
        from facepicker import imaging
        from facepicker.api import Api
        import webview  # noqa: F401
        assert (BASE / "ui" / "index.html").exists(), "ui 없음"
        assert imaging._CASCADE is not None and not imaging._CASCADE.empty(), "얼굴 인식 데이터 없음"
        if sys.platform == "win32":
            import webview.platforms.winforms  # noqa: F401  (.NET/WebView2 연결 확인)
        Api().get_state()
        return 0
    except Exception:
        import traceback
        (Path.cwd() / "selftest_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        return 1


def close_splash(*_a) -> None:
    """exe 스플래시 화면 닫기 (exe가 아닐 때는 아무 일 없음)."""
    try:
        import pyi_splash  # type: ignore
        pyi_splash.close()
    except Exception:
        pass


def main() -> None:
    import webview
    from facepicker.api import Api, VERSION

    api = Api()
    window = webview.create_window(
        f"FM27 Face Studio v{VERSION}",
        str(BASE / "ui" / "index.html"),
        js_api=api,
        width=1440, height=900, min_size=(1240, 760),
        background_color="#0a0f1d",
    )
    api._set_window(window)
    window.events.shown += close_splash
    window.events.loaded += close_splash
    webview.start(private_mode=False, icon=str(BASE / "assets" / "icon.png"))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        close_splash()
        sys.exit(selftest())
    main()
