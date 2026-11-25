"""개발/테스트용: 일반 브라우저에서 화면을 열어보는 서버 (http://127.0.0.1:8765)."""
import json
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from facepicker.api import Api  # noqa: E402

API = Api()
UI = Path(__file__).parent / "ui"


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(UI), **k)

    def do_POST(self):
        name = self.path.rsplit("/", 1)[-1]
        args = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"[]")
        fn = getattr(API, name, None)
        res = fn(*args) if (fn and not name.startswith("_")) else {"error": "no such api"}
        body = json.dumps(res, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8765), H).serve_forever()
