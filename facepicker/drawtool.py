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
            "sentencepiece", "protobuf", "pillow", "bitsandbytes"]
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
            with self.lock:
                ms = self.task.get("model")                  # 모델 받는 중: 받은 파일 수로 (빈 파일을 미리 만들어서 크기로는 못 잼)
                if ms and self.task.get("files"):
                    a, b = self.task["files"]
                    n = ms[0] + ms[1] * (a / max(1, b))
                elif ms:
                    n = ms[0]
                self.task["done"] = max(self.task.get("done", 0), min(n, self.task.get("total", n)))
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
            for part in line.replace("\r", "\n").split("\n"):
                part = part.strip()
                if not part:
                    continue
                import re as _re
                m = _re.search(r"Fetching (\d+) files:.*?(\d+)/(\d+)", part)
                with self.lock:
                    if m:
                        self.task["files"] = [int(m.group(2)), int(m.group(3))]
                    self.task["last"] = part[-140:]
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
                with self.lock:
                    self.task["model"] = [self.task.get("done", 0), m["size"]]
                    self.task.pop("files", None)
                code = ("import sys\nfrom huggingface_hub import snapshot_download\n"
                        "snapshot_download(sys.argv[1], local_dir=sys.argv[2], allow_patterns=sys.argv[3].split(','), max_workers=8)\n")
                self._run([self.py, "-c", code, m["repo"], self.model_dir(k), ",".join(m["allow"])])
                st = self.state()
                st["models"] = sorted(set(st.get("models", [])) | {k})
                self._save_state(st)
                with self.lock:
                    self.task.pop("model", None)
                    self.task.pop("files", None)
            shutil.rmtree(self.root / "cache" / "hf" / "xet", ignore_errors=True)    # 빠른 받기 조각 캐시
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
        r = _RUNNERS.get(str(self.root))
        if r:
            r.stop()
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


SERVER_PY = r"""
# FM Face Studio 그림도구 — 앱이 켜고 끄는 그리기 일꾼. 한 줄 JSON으로 주고받는다.
import gc, json, os, random, sys, time, traceback
proto = sys.stdout
sys.stdout = sys.stderr            # 라이브러리 출력은 기록으로만
def say(**kw):
    proto.write("@@" + json.dumps(kw, ensure_ascii=False) + "\n"); proto.flush()
try:
    import torch
    from PIL import Image
    from diffusers import Flux2KleinPipeline
    model_dir = sys.argv[1]
    t0 = time.time()
    vram = torch.cuda.get_device_properties(0).total_memory / 2**30
    mode = "bf16"
    pipe = None
    def quantized(parts):
        from diffusers.quantizers import PipelineQuantizationConfig
        qc = PipelineQuantizationConfig(
            quant_backend="bitsandbytes_4bit",
            quant_kwargs={"load_in_4bit": True, "bnb_4bit_quant_type": "nf4", "bnb_4bit_compute_dtype": torch.bfloat16},
            components_to_quantize=parts)
        return Flux2KleinPipeline.from_pretrained(model_dir, quantization_config=qc, torch_dtype=torch.bfloat16)
    if vram < 20:
        # 12GB 등: 그림 본체만 4비트로 줄이고, 글 이해 부품은 원래 크기로 둔다 (4비트로 줄이면 지시를 잘 못 알아들음).
        # 글 이해 부품은 글을 읽을 때만 그래픽카드에 올렸다 내린다 (model cpu offload).
        try:
            pipe = quantized(["transformer"])
            pipe.enable_model_cpu_offload()
            mode = "nf4+te16"
        except Exception:
            print("글 이해 부품 원래 크기 실패, 모두 4비트로:\n" + traceback.format_exc())
            pipe = None
            gc.collect(); torch.cuda.empty_cache()
            try:
                pipe = quantized(["transformer", "text_encoder"])
                try:
                    pipe.to("cuda")
                except Exception:
                    pipe.vae.to("cuda")
                mode = "nf4"
            except Exception:
                print("4비트 실패, 원래 크기로:\n" + traceback.format_exc())
                pipe = None
                gc.collect(); torch.cuda.empty_cache()
    if pipe is None:
        pipe = Flux2KleinPipeline.from_pretrained(model_dir, torch_dtype=torch.bfloat16)
        if vram < 20:
            pipe.enable_model_cpu_offload()
        else:
            pipe.to("cuda")
    pipe.set_progress_bar_config(disable=True)
    def cap():
        # 넘쳐서 일반 메모리로 새는 것만 막는 느슨한 한도 (너무 조이면 비웠다 잡았다 반복하느라 오히려 느려짐)
        torch.cuda.set_per_process_memory_fraction(0.92)
    cap()
    print(f"켜짐: {mode}, {time.time() - t0:.1f}초, 그래픽카드 메모리 {torch.cuda.memory_allocated() / 2**30:.1f}GB")
    say(ready=True, secs=round(time.time() - t0, 1), gpu=torch.cuda.get_device_name(0), mode=mode)
except Exception as e:
    say(ready=False, error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-1500:])
    sys.exit(1)
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
        if req.get("quit"):
            break
        def load_refs(side):
            out = []
            for p in req.get("refs") or []:
                im = Image.open(p).convert("RGB")
                im.thumbnail((side, side))     # 참고 사진은 작게 (메모리·속도)
                out.append(im)
            return out
        refs = load_refs(640)
        cap()
        seed = int(req.get("seed") or random.randint(1, 2**31 - 1))
        kw = dict(prompt=req["prompt"], height=int(req.get("h", 1024)), width=int(req.get("w", 1024)),
                  guidance_scale=float(req.get("guidance", 1.0)), num_inference_steps=int(req.get("steps", 4)),
                  generator=torch.Generator(device="cpu").manual_seed(seed))
        if refs:
            kw["image"] = refs if len(refs) > 1 else refs[0]
        n = kw["num_inference_steps"]
        last = [time.time()]
        def on_step(p, i, t, k):
            now = time.time()
            free = torch.cuda.mem_get_info()[0] / 2**30
            print(f"  단계 {i + 1}/{n}: {now - last[0]:.1f}초, 남은 그래픽카드 메모리 {free:.1f}GB")
            last[0] = now
            say(progress=i + 1, steps=n)
            return k
        kw["callback_on_step_end"] = on_step
        say(progress=0, steps=n)
        t0 = time.time()
        try:
            ntok = len(pipe.tokenizer(req["prompt"]).input_ids)
        except Exception:
            ntok = -1
        print(f"그리기 시작 (참고 {len(refs)}장, 프롬프트 {ntok}토큰{' — 512 넘어서 뒤가 잘릴 수 있음' if ntok > 512 else ''}, 남은 그래픽카드 메모리 {torch.cuda.mem_get_info()[0] / 2**30:.1f}GB)")
        def run(kw):
            try:
                return pipe(**kw).images[0]
            except TypeError as e:
                if "callback" not in str(e):
                    raise
                kw.pop("callback_on_step_end", None)
                return pipe(**kw).images[0]
        try:
            img = run(kw)
        except torch.cuda.OutOfMemoryError:
            if not refs:
                raise
            print("메모리 부족 → 참고 사진을 512px로 줄여 다시")
            gc.collect(); torch.cuda.empty_cache(); cap()
            refs = load_refs(512)
            kw["image"] = refs if len(refs) > 1 else refs[0]
            say(progress=0, steps=n)
            img = run(kw)
        img.save(req["out"])
        print(f"그림 {time.time() - t0:.1f}초 (참고 {len(refs)}장, 최대 {torch.cuda.max_memory_allocated() / 2**30:.1f}GB)")
        del img
        gc.collect(); torch.cuda.empty_cache(); torch.cuda.reset_peak_memory_stats()     # 쥐고 있던 메모리 돌려주기
        say(id=req.get("id"), ok=True, secs=round(time.time() - t0, 1), seed=seed)
    except torch.cuda.OutOfMemoryError as e:
        gc.collect(); torch.cuda.empty_cache()
        say(id=req.get("id") if isinstance(req, dict) else None, ok=False, error="그래픽카드 메모리가 모자라요. 게임 등 다른 프로그램을 끄고 다시 해 보세요.")
    except Exception as e:
        say(id=req.get("id") if isinstance(req, dict) else None, ok=False, error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-1500:])
"""


class Runner:
    """그리기 일꾼(모델을 올려 둔 파이썬)을 켜 두고 하나씩 그리게 한다. 오래 놀면 끈다."""
    IDLE = 180

    def __init__(self, dt: "DrawTool"):
        self.dt = dt
        self.proc: subprocess.Popen | None = None
        self.lock = threading.Lock()
        self.state = "off"           # off · loading · ready
        self.last = 0.0
        self.info: dict = {}
        self.progress: dict = {}
        self.killed = False
        threading.Thread(target=self._idle_loop, daemon=True).start()

    def _idle_loop(self):
        while True:
            time.sleep(30)
            if self.state == "ready" and time.time() - self.last > self.IDLE and not self.lock.locked():
                self.stop()

    def _read(self, timeout: float) -> dict:
        assert self.proc and self.proc.stdout
        end = time.time() + timeout
        while time.time() < end:
            raw = self.proc.stdout.readline()
            if not raw:
                if self.killed:
                    raise RuntimeError("__stopped__")
                raise RuntimeError("그림도구가 꺼졌어요. 그림도구 폴더의 draw.log를 확인해 주세요.")
            s = raw.decode("utf-8", "replace").strip()
            if s.startswith("@@"):
                d = json.loads(s[2:])
                if "progress" in d:          # 그리는 중 단계 알림
                    if d["progress"] == 0:
                        self.progress = {"step": 0, "steps": d.get("steps", 4), "since": time.time()}
                    else:
                        self.progress.update(step=d["progress"], steps=d.get("steps", 4))
                    continue
                return d
        raise RuntimeError("그림도구가 응답하지 않아요.")

    def _start(self, key: str = "std"):
        dt = self.dt
        mdir = dt.model_dir(key)
        if not (mdir / "model_index.json").exists():
            raise RuntimeError("그림도구 모델이 없어요. 'AI로 한꺼번에 그리기'에서 설치해 주세요.")
        self.state = "loading"
        try:                                    # 예전에 설치한 사람: 4비트 부품 추가 (실패해도 원래 크기로 켜짐)
            subprocess.run([str(dt.py), "-c", "import bitsandbytes"], check=True, capture_output=True,
                           env=dt._env(), timeout=120, creationflags=NO_WINDOW)
        except Exception:  # noqa: BLE001
            try:
                dt._get_uv()
                subprocess.run([str(dt.uv), "pip", "install", "--python", str(dt.py), "bitsandbytes"], capture_output=True,
                               env=dt._env(), timeout=1800, creationflags=NO_WINDOW)
            except Exception as e:  # noqa: BLE001
                log.warning("4비트 부품 설치 실패: %s", e)
        script = dt.root / "server.py"
        script.write_text(SERVER_PY, encoding="utf-8")
        logf = open(dt.root / "draw.log", "ab")
        self.state = "loading"
        self.proc = subprocess.Popen([str(dt.py), "-u", str(script), str(mdir)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=logf, env=dt._env(), cwd=str(dt.root),
                                     creationflags=NO_WINDOW)
        r = self._read(900)
        if not r.get("ready"):
            self.stop()
            raise RuntimeError("그림도구를 켜지 못했어요: " + str(r.get("error", ""))[:300])
        self.info = r
        self.state = "ready"
        log.info("그림도구 켜짐 (%.1f초)", r.get("secs", 0))

    def view(self) -> dict:
        pr = dict(self.progress)
        if pr:
            pr["secs"] = int(time.time() - pr.get("since", time.time()))
        return {"state": self.state, "progress": pr, "mode": self.info.get("mode", "")}

    def busy(self) -> bool:
        return self.lock.locked()

    def stop(self, force: bool = False):
        if self.lock.locked() and not force:      # 켜는 중·그리는 중이면 끄지 않음
            return False
        if force and self.lock.locked():
            self.killed = True
            p = self.proc
            if p and p.poll() is None:
                try:
                    p.kill()
                except Exception:  # noqa: BLE001
                    pass
            return True
        p, self.proc = self.proc, None
        self.state = "off"
        if p and p.poll() is None:
            try:
                p.stdin.write(b'{"quit":true}\n'); p.stdin.flush()      # type: ignore[union-attr]
                p.wait(10)
            except Exception:  # noqa: BLE001
                try:
                    p.kill()
                except Exception:  # noqa: BLE001
                    pass
        return True

    def draw(self, prompt: str, refs: list, out: Path, steps: int = 4, seed: int = 0) -> dict:
        with self.lock:
            self.killed = False
            if not self.proc or self.proc.poll() is not None:
                try:
                    self._start()
                except Exception:
                    self.stop()
                    raise
            tmp = self.dt.root / "tmp"
            tmp.mkdir(exist_ok=True)
            paths = []
            for i, im in enumerate(refs or []):
                p = tmp / f"ref{i}.png"
                im.convert("RGB").save(p)
                paths.append(str(p))
            req = {"id": int(time.time() * 1000), "prompt": prompt, "refs": paths, "out": str(out),
                   "steps": steps, "seed": seed}
            self.proc.stdin.write((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))   # type: ignore[union-attr]
            self.proc.stdin.flush()                                                               # type: ignore[union-attr]
            try:
                r = self._read(900)
            except RuntimeError:
                if self.killed:
                    self.proc, self.state = None, "off"
                raise
            finally:
                self.progress = {}
            self.last = time.time()
            if not r.get("ok"):
                raise RuntimeError(r.get("error") or "그리기 실패")
            return r


_RUNNERS: dict[str, Runner] = {}


def runner(root: Path) -> Runner:
    k = str(root)
    if k not in _RUNNERS:
        _RUNNERS[k] = Runner(DrawTool(root))
    return _RUNNERS[k]


def stop_all():
    for r in _RUNNERS.values():
        r.stop(force=True)
        r.stop()
