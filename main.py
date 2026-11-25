"""FM27 Face Studio 실행 파일."""
import logging
import os
import sys
import traceback
from pathlib import Path

BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def log_dir() -> Path:
    base = os.environ.get("APPDATA")
    d = Path(base) / "FM27FacePicker" if base else Path.home() / ".FM27FacePicker"
    d.mkdir(parents=True, exist_ok=True)
    return d


LOG_PATH = log_dir() / "app.log"


def setup_logging() -> None:
    handlers = [logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")]
    if sys.stderr is not None:   # 진단용(콘솔) exe에서는 화면에도 출력
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(level=logging.DEBUG, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        import faulthandler
        faulthandler.enable(open(log_dir() / "crash.log", "w", encoding="utf-8"))
    except Exception:
        pass


def error_box(msg: str) -> None:
    close_splash()
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg, "FM27 Face Studio 오류", 0x10)
    except Exception:
        print(msg, file=sys.stderr)


def close_splash(*_a) -> None:
    """exe 스플래시 화면 닫기 (스플래시가 없으면 아무 일 없음)."""
    if "_PYI_SPLASH_IPC" not in os.environ:
        return
    try:
        import pyi_splash  # type: ignore
        pyi_splash.close()
    except Exception:
        pass


def build_html() -> str:
    """index.html에 style.css·app.js를 직접 넣은 한 덩어리 화면.
    (파일 경로나 내부 웹서버에 의존하지 않아서 어떤 PC에서도 그대로 뜸)"""
    ui = BASE / "ui"
    html = (ui / "index.html").read_text(encoding="utf-8")
    css = (ui / "style.css").read_text(encoding="utf-8")
    js = (ui / "app.js").read_text(encoding="utf-8").replace("</script", "<\\/script")
    html = html.replace('<link rel="stylesheet" href="style.css">', f"<style>\n{css}\n</style>")
    html = html.replace('<script src="app.js"></script>', f"<script>\n{js}\n</script>")
    assert "href=\"style.css\"" not in html and "src=\"app.js\"" not in html, "화면 파일 합치기 실패"
    return html


def selftest() -> int:
    """빌드 서버에서 exe가 제대로 묶였는지 확인 (창은 띄우지 않음)."""
    try:
        from facepicker import imaging
        from facepicker.api import Api
        import webview  # noqa: F401
        assert len(build_html()) > 20000, "ui 없음"
        assert imaging._CASCADE is not None and not imaging._CASCADE.empty(), "얼굴 인식 데이터 없음"
        if sys.platform == "win32":
            import webview.platforms.winforms  # noqa: F401  (.NET/WebView2 연결 확인)
        Api().get_state()
        return 0
    except Exception:
        (Path.cwd() / "selftest_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        return 1


def main() -> None:
    log = logging.getLogger("main")
    log.info("시작: python %s, frozen=%s, base=%s", sys.version.split()[0], getattr(sys, "frozen", False), BASE)
    import webview
    from facepicker.api import Api, VERSION
    log.info("pywebview %s 불러옴", getattr(webview, "__version__", "?"))

    api = Api()
    log.info("Api 준비됨")
    window = webview.create_window(
        f"FM27 Face Studio v{VERSION}",
        html=build_html(),
        js_api=api,
        width=1440, height=900, min_size=(1240, 760),
        background_color="#0a0f1d",
    )
    api._set_window(window)
    window.events.shown += close_splash
    window.events.loaded += close_splash
    window.events.shown += lambda *_: log.info("창 표시됨")
    window.events.loaded += lambda *_: log.info("화면 로드됨")
    log.info("webview.start 호출")
    webview.start(private_mode=False, debug="--debug" in sys.argv)
    log.info("정상 종료")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        close_splash()
        sys.exit(selftest())
    setup_logging()
    try:
        main()
    except Exception:
        tb = traceback.format_exc()
        logging.getLogger("main").error("실행 실패\n%s", tb)
        last = tb.strip().splitlines()[-1]
        hint = ""
        if "WebView2" in tb or "EdgeChromium" in tb or "clr" in tb.lower() or "pythonnet" in tb.lower():
            hint = ("\n\nMicrosoft Edge WebView2 런타임이 필요할 수 있어요.\n"
                    "https://go.microsoft.com/fwlink/p/?LinkId=2124703 에서 설치 후 다시 실행해 보세요.")
        error_box(f"프로그램을 시작하지 못했어요.\n\n{last}{hint}\n\n자세한 기록: {LOG_PATH}")
        sys.exit(1)
