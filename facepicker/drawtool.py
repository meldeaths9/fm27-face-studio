"""내 PC 그림도구: 설치·상태·지우기.

모든 것(파이썬, 패키지, 모델, 내려받기 캐시)을 폴더 하나에 넣는다 → 지우기는 그 폴더만 통째로.
설치는 uv(파이썬·패키지 설치 도구)로 하고, 모델은 허깅페이스에서 받는다.
"""
from __future__ import annotations

import io
import json
import tarfile
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

log = logging.getLogger("drawtool")

FOLDER_NAME = "FMFaceStudio_DrawTool"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
UV_ZIP = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
PBS_API = "https://api.github.com/repos/astral-sh/python-build-standalone/releases?per_page=2"
TORCH_INDEX = "https://download.pytorch.org/whl/cu128"
PACKAGES = ["diffusers>=0.37", "transformers", "accelerate", "safetensors", "huggingface_hub", "hf_xet",
            "sentencepiece", "protobuf", "pillow"]
PKG_EST = 5.5e9            # 파이썬 + PyTorch + 나머지 (대략)

MODELS = {
    "std": {"name": "실사 표준 (FLUX.2 klein 4B)", "repo": "black-forest-labs/FLUX.2-klein-4B", "dir": "klein4b",
            "allow": ["model_index.json", "scheduler/*", "text_encoder/*", "tokenizer/*", "transformer/*", "vae/*"],
            "size": 15.98e9, "required": True},
    "adv": {"name": "실사 고급 (Z-Image-Turbo)", "repo": "Tongyi-MAI/Z-Image-Turbo", "dir": "zimage",
            "allow": ["model_index.json", "scheduler/*", "text_encoder/*", "tokenizer/*", "transformer/*", "vae/*"],
            "size": 32.85e9, "required": False},
}


def default_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / FOLDER_NAME


def gpu_info() -> dict:
    """엔비디아 그래픽카드 확인 (nvidia-smi)."""
    exe = shutil.which("nvidia-smi")
    if not exe and sys.platform == "win32":
        p = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe"
        exe = str(p) if p.exists() else None
    if not exe:
        return {"ok": False, "reason": "엔비디아 그래픽카드를 찾지 못했어요. 그림도구는 엔비디아(RTX) 그래픽카드에서만 돼요."}
    try:
        out = subprocess.run([exe, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW).stdout
        rows = [r.split(",") for r in out.strip().splitlines() if r.strip()]
        if not rows:
            raise RuntimeError("빈 응답")
        best = max(rows, key=lambda r: float(r[1]))
        name, mem, drv = best[0].strip(), float(best[1]) / 1024, best[2].strip()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"그래픽카드 정보를 읽지 못했어요: {e}"}
    ok = mem >= 7.5
    return {"ok": ok, "name": name, "vram": round(mem, 1), "driver": drv,
            "reason": "" if ok else "그래픽카드 메모리가 8GB보다 작아서 그림도구를 쓰기 어려워요.",
            "tight": mem < 11.5}


def dir_size(p: Path) -> int:
    total = 0
    stack = [p]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(Path(e.path))
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def free_space(p: Path) -> int:
    q = p
    while not q.exists() and q.parent != q:
        q = q.parent
    try:
        return shutil.disk_usage(q).free
    except OSError:
        return 0


class DrawTool:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.task: dict = {"active": False}
        self._proc: subprocess.Popen | None = None
        self._cancel = False

    # ------------------------------------------------------------ 경로
    @property
    def uv(self) -> Path:
        return self.root / "uv" / "uv.exe"

    @property
    def venv(self) -> Path:
        return self.root / "venv"

    @property
    def py(self) -> Path:
        return self.venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

    def model_dir(self, key: str) -> Path:
        return self.root / "models" / MODELS[key]["dir"]

    def _state_file(self) -> Path:
        return self.root / "state.json"

    def state(self) -> dict:
        try:
            return json.loads(self._state_file().read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_state(self, st: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._state_file().write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")

    def installed(self) -> bool:
        st = self.state()
        return bool(st.get("ready")) and self.py.exists() and bool(st.get("models"))

    def models_ready(self) -> list[str]:
        st = self.state()
        return [k for k in st.get("models", []) if (self.model_dir(k) / "model_index.json").exists()]

    def _env(self) -> dict:
        env = dict(os.environ)
        env.update({
            "UV_CACHE_DIR": str(self.root / "cache" / "uv"),
            "UV_PYTHON_INSTALL_DIR": str(self.root / "python"),
            "UV_PYTHON_PREFERENCE": "only-system",
            "UV_PYTHON_DOWNLOADS": "never",
            "UV_NO_PROGRESS": "1",
            "HF_HOME": str(self.root / "cache" / "hf"),
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "HF_XET_HIGH_PERFORMANCE": "1",            # 빠르게 받기 (파일을 쪼개 여러 연결로)
            "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
            "PYTHONIOENCODING": "utf-8",
            "VIRTUAL_ENV": str(self.venv),
        })
        env.pop("PYTHONHOME", None)
        env.pop("PYTHONPATH", None)
        return env

    # ------------------------------------------------------------ 상태 (화면용)
    def status(self) -> dict:
        with self.lock:
            task = dict(self.task)
        st = self.state()
        models = {}
        for k, m in MODELS.items():
            models[k] = {"name": m["name"], "size": m["size"], "required": m["required"],
                         "installed": k in self.models_ready()}
        return {"root": str(self.root), "installed": self.installed(), "models": models,
                "free": free_space(self.root), "pkg_est": PKG_EST, "task": task,
                "used": st.get("used", 0), "torch": st.get("torch", ""), "cuda": st.get("cuda", "")}

    # ------------------------------------------------------------ 설치
    def start_install(self, keys: list[str]) -> dict:
        with self.lock:
            if self.task.get("active"):
                return {"error": "이미 설치 중이에요."}
            keys = [k for k in MODELS if k in keys or MODELS[k]["required"]]
            need_pkg = not (self.state().get("ready") and self.py.exists())
            todo = [k for k in keys if k not in self.models_ready()]
            total = (PKG_EST if need_pkg else 0) + sum(MODELS[k]["size"] for k in todo)
            if free_space(self.root) < total * 1.1 + 2e9:
                return {"error": f"디스크 공간이 모자라요. 약 {total / 1e9 + 2:.0f}GB가 필요해요."}
            self._cancel = False
            self.task = {"active": True, "step": "준비 중", "done": 0, "total": total, "error": "", "keys": keys,
                         "started": time.time(), "base": dir_size(self.root) if self.root.exists() else 0}
        threading.Thread(target=self._install, args=(keys, need_pkg), daemon=True).start()
        threading.Thread(target=self._measure, daemon=True).start()
        return {"ok": True}

    def cancel(self) -> None:
        self._cancel = True
        p = self._proc
        if p and p.poll() is None:
            try:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, creationflags=NO_WINDOW)
                else:
                    p.kill()
            except Exception:  # noqa: BLE001
                pass

    def _measure(self) -> None:
        """받은 양 = 폴더 크기 증가분 (패키지·모델 모두)."""
        while True:
            with self.lock:
                if not self.task.get("active"):
                    return
                base = self.task.get("base", 0)
            n = max(0, dir_size(self.root) - base)
            now = time.time()
            with self.lock:
                prev = self.task.get("_prev")
                if prev and now > prev[1]:
                    sp = max(0.0, (n - prev[0]) / (now - prev[1]))
                    self.task["speed"] = sp if not self.task.get("speed") else self.task["speed"] * 0.6 + sp * 0.4
                self.task["_prev"] = (n, now)
                self.task["done"] = min(n, self.task.get("total", n))
            time.sleep(2)

    def _step(self, text: str) -> None:
        log.info("그림도구 설치: %s", text)
        with self.lock:
            self.task["step"] = text
        self._log(f"== {text}")

    def _log(self, text: str) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with open(self.root / "install.log", "a", encoding="utf-8") as f:
                f.write(text.rstrip() + "\n")
        except OSError:
            pass

    def _run(self, args: list, timeout: float = 7200) -> str:
        if self._cancel:
            raise RuntimeError("취소했어요.")
        self._log("$ " + " ".join(str(a) for a in args))
        self._proc = subprocess.Popen([str(a) for a in args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      env=self._env(), cwd=str(self.root), creationflags=NO_WINDOW)
        out = []
        t0 = time.time()
        for raw in self._proc.stdout:     # type: ignore[union-attr]
            line = raw.decode("utf-8", "replace")
            out.append(line)
            self._log(line)
            if time.time() - t0 > timeout:
                self.cancel()
        code = self._proc.wait()
        self._proc = None
        if self._cancel:
            raise RuntimeError("취소했어요.")
        if code != 0:
            tail = "".join(out[-12:]).strip()
            raise RuntimeError(f"실행 실패 (코드 {code})\n{tail[-800:]}")
        return "".join(out)

    def _get_uv(self) -> None:
        if self.uv.exists():
            return
        self._step("설치 도구 받는 중")
        with urllib.request.urlopen(UV_ZIP, timeout=120) as r:
            data = r.read()
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for n in z.namelist():
                if n.endswith("uv.exe") or n.endswith("uvx.exe"):
                    t = self.uv.parent / Path(n).name
                    t.parent.mkdir(parents=True, exist_ok=True)
                    t.write_bytes(z.read(n))
        if not self.uv.exists():
            raise RuntimeError("설치 도구(uv)를 풀지 못했어요.")

    @property
    def base_py(self) -> Path:
        return self.root / "python" / "python.exe"

    def _get_python(self) -> None:
        """파이썬을 직접 받아 폴더에 푼다 (uv의 파이썬 관리 기능은 윈도우 연결 폴더를 만들다 막히는 PC가 있어 안 씀)."""
        if self.base_py.exists():
            return
        self._step("파이썬 받는 중")
        req = urllib.request.Request(PBS_API, headers={"Accept": "application/vnd.github+json", "User-Agent": "FMFaceStudio"})
        with urllib.request.urlopen(req, timeout=60) as r:
            rels = json.loads(r.read().decode())
        url = ""
        for rel in rels:
            for a in rel.get("assets", []):
                n = a.get("name", "")
                if n.startswith("cpython-3.12.") and n.endswith("-x86_64-pc-windows-msvc-install_only.tar.gz"):
                    url = a.get("browser_download_url", "")
                    break
            if url:
                break
        if not url:
            raise RuntimeError("파이썬 내려받을 주소를 찾지 못했어요.")
        self._log("python: " + url)
        tmp = self.root / "python.tar.gz"
        with urllib.request.urlopen(url, timeout=600) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        shutil.rmtree(self.root / "python", ignore_errors=True)
        with tarfile.open(tmp, "r:gz") as t:          # 안에 python/ 폴더 하나
            t.extractall(self.root, filter="data") if hasattr(tarfile, "data_filter") else t.extractall(self.root)
        tmp.unlink(missing_ok=True)
        if not self.base_py.exists():
            raise RuntimeError("파이썬을 풀지 못했어요.")

    def _install(self, keys: list[str], need_pkg: bool) -> None:
        err = ""
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            st = self.state()
            if need_pkg:
                self._get_uv()
                self._get_python()
                self._step("파이썬 준비 중")
                if not self.py.exists():
                    shutil.rmtree(self.venv, ignore_errors=True)
                    self._run([self.uv, "venv", "--no-python-downloads", "--python", self.base_py, self.venv])
                self._step("PyTorch 받는 중 (약 3GB, 가장 오래 걸려요)")
                self._run([self.uv, "pip", "install", "--python", self.py, "torch", "--index-url", TORCH_INDEX])
                self._step("그림 프로그램 받는 중")
                self._run([self.uv, "pip", "install", "--python", self.py, *PACKAGES])
                ok = self._run([self.py, "-c", "import diffusers; print(hasattr(diffusers, 'Flux2KleinPipeline'))"])
                if "True" not in ok:
                    self._step("그림 프로그램 최신판 받는 중")
                    self._run([self.uv, "pip", "install", "--python", self.py,
                               "diffusers @ https://github.com/huggingface/diffusers/archive/refs/heads/main.zip"])
                self._step("그래픽카드 연결 확인 중")
                chk = self._run([self.py, "-c",
                                 "import torch;print('CUDA', torch.cuda.is_available(), torch.version.cuda, torch.__version__);"
                                 "print('GPU', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"])
                if "CUDA True" not in chk:
                    raise RuntimeError("PyTorch가 그래픽카드를 못 찾았어요. 그래픽카드 드라이버를 최신으로 업데이트해 주세요.\n" + chk[-300:])
                for line in chk.splitlines():
                    if line.startswith("CUDA"):
                        parts = line.split()
                        st["cuda"], st["torch"] = parts[2], parts[3]
                st["ready"] = True
                self._save_state(st)
                self._run([self.uv, "cache", "clean"])           # 받은 꾸러미 사본은 지워 용량 아끼기
            if not need_pkg:                     # 예전에 설치한 사람: 빠르게 받기 부품만 추가
                try:
                    self._run([self.py, "-c", "import hf_xet"])
                except RuntimeError:
                    if self._cancel:
                        raise
                    self._get_uv()
                    self._step("빠르게 받기 부품 설치 중")
                    self._run([self.uv, "pip", "install", "--python", self.py, "-U", "huggingface_hub", "hf_xet"])
            for k in keys:
                if k in self.models_ready():
                    continue
                m = MODELS[k]
                self._step(f"{m['name']} 받는 중 (약 {m['size'] / 1e9:.0f}GB)")
                code = ("import sys\nfrom huggingface_hub import snapshot_download\n"
                        "snapshot_download(sys.argv[1], local_dir=sys.argv[2], allow_patterns=sys.argv[3].split(','), max_workers=8)\n")
                self._run([self.py, "-c", code, m["repo"], self.model_dir(k), ",".join(m["allow"])])
                st = self.state()
                st["models"] = sorted(set(st.get("models", [])) | {k})
                self._save_state(st)
            st = self.state()
            st["used"] = dir_size(self.root)
            self._save_state(st)
            self._step("설치 끝")
        except Exception as e:  # noqa: BLE001
            err = str(e)
            log.warning("그림도구 설치 실패: %s", err)
            self._log("!! " + err)
        finally:
            with self.lock:
                self.task.update(active=False, error=err, finished=time.time())

    # ------------------------------------------------------------ 지우기
    def uninstall(self) -> dict:
        with self.lock:
            if self.task.get("active"):
                return {"error": "설치 중에는 지울 수 없어요. 먼저 취소해 주세요."}
        if not self.root.exists():
            return {"freed": 0}
        if self.root.name != FOLDER_NAME:          # 엉뚱한 폴더를 지우지 않게
            return {"error": "그림도구 폴더가 아니라서 지우지 않았어요."}
        size = dir_size(self.root)

        def onerr(func, path, _exc):
            try:
                os.chmod(path, 0o700)
                func(path)
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(self.root, onerror=onerr)
        left = dir_size(self.root) if self.root.exists() else 0
        return {"freed": size - left, "left": left}
