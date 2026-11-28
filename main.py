"""FM Face Studio 실행 파일."""
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
        ctypes.windll.user32.MessageBoxW(None, msg, "FM Face Studio 오류", 0x10)
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
        from facepicker import ai_models, style
        from facepicker.api import Api
        import webview  # noqa: F401
        import fmsave  # noqa: F401
        import fmsave._layouts.fm27_27_0_0  # noqa: F401  (FM27 세이브 구조)
        from PIL import Image
        assert len(build_html()) > 20000, "ui 없음"
        assert ai_models.face_available(), "얼굴 인식 모델 없음"
        from facepicker import gamesetup, updater
        assert gamesetup.PLUGIN_DLL.exists(), "플러그인 파일 없음"
        assert updater.is_newer("9.0.0", "0.1.0")
        print("update check:", (updater.latest() or {}).get("version"))
        ai_models.detect_face(Image.new("RGB", (320, 240), (128, 128, 128)))
        style.decorate(Image.new("RGBA", (128, 128)), style.Deco(caption=True, text="테스트", rounded=True, border=True))
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

    from facepicker import memlog
    memlog.mark("시작")
    api = Api()
    memlog.mark("Api 준비됨")
    memlog.start_watch(300)
    webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True   # 헤더의 빈 곳만 잡히게 (버튼은 그대로 눌림)
    window = webview.create_window(
        f"FM Face Studio v{VERSION}",
        html=build_html(),
        js_api=api,
        width=1440, height=900, min_size=(1240, 760),
        background_color="#0a0f1d",
        frameless=True, easy_drag=False,      # 제목줄은 앱이 직접 그린다 (헤더를 잡고 끌기)
    )
    api._set_window(window)
    window.events.shown += close_splash
    window.events.loaded += close_splash
    window.events.shown += lambda *_: log.info("창 표시됨")
    window.events.loaded += lambda *_: log.info("화면 로드됨")
    log.info("webview.start 호출")
    webview.start(private_mode=False, debug="--debug" in sys.argv)
    try:
        api.flush_deletes()       # 되돌리기 기다리던 삭제는 끄기 전에 마저 지운다
        from facepicker import drawtool
        drawtool.stop_all()       # 그림도구 일꾼(그래픽카드 메모리) 끄기
    except Exception as e:  # noqa: BLE001
        log.warning("남은 삭제 처리 실패: %s", e)
    log.info("정상 종료")


if __name__ == "__main__":
    if "--install-plugin" in sys.argv:      # 관리자 권한으로 다시 실행됐을 때
        i = sys.argv.index("--install-plugin")
        from facepicker import gamesetup
        sys.exit(gamesetup.cli_install(sys.argv[i + 1], sys.argv[i + 2]))
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
