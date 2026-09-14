# SPDX-License-Identifier: GPL-3.0-only
"""内置 llama.cpp 运行时管理器（T-312）。

LLAMA_RUNTIME_V1：以受管子进程方式拉起内置 ``llama-server``（llama.cpp 官方
server，OpenAI 兼容 /v1），动态端口监听 127.0.0.1，模型目录沙盒在应用数据目录
（~/Library/Application Support/AcouScope/llama_models）。

零配置：无需用户自行安装 llama.cpp；启动时按优先级寻找内置/已装二进制，
找不到则给友好中文文案，绝不向调用方抛异常。

与 OllamaRuntime（T-303b）的差异（其余结构逐点照搬）：
- llama-server 必须带模型参数启动：模型路径走 argv ``-m``，不走 env；
- 就绪探测端点 ``GET /health``：模型加载中 503、就绪 200（ollama 是 /api/tags）；
- 模型加载可达数十秒 → start 默认 timeout=180.0；
- 无独立 serve 子命令、无 OLLAMA_* 环境变量三件套。

用户可见文案铁律（零终端）：禁出现命令行 / URL / 安装指引；
目标用户是田野研究者而非工程师。
"""
from __future__ import annotations

import atexit
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

# LLAMA_RUNTIME_V1：内置 llama.cpp 运行时（零配置；受管子进程）

from acouscope.utils.config import get_data_dir

#: 开发模式内置二进制（参照 ffmpeg 内置位置：包根 resources/bin/）。
#: 本文件位于 src/acouscope/ai/，parents[1] = src/acouscope（包根）。
_DEV_LLAMA_BIN = (
    Path(__file__).resolve().parents[1] / "resources" / "bin" / "llama-server"
)

# 友好失败文案（零终端：不含命令 / URL / 安装指引）。
_ERR_NO_BINARY = "本地引擎启动失败：未找到内置引擎组件"
_ERR_NO_MODEL = "本地模型未就绪，请先在设置中完成模型准备"
_ERR_NOT_READY = "本地引擎启动失败：服务未在规定时间内就绪"
_ERR_PROCESS_EXITED = "本地引擎启动失败：进程意外退出"


def find_llama_binary() -> str | None:
    """按优先级寻找可执行的 llama-server 二进制，返回第一个命中路径；均未命中返回 None。

    顺序：① 环境变量 ACOUSECOPE_LLAMA_BIN（非空且存在可执行）
    ② PyInstaller 打包目录 sys._MEIPASS/"llama-server"（仅 frozen 时）
    ③ 开发模式 <包根>/resources/bin/llama-server（参照 ffmpeg 内置位置）
    ④ shutil.which("llama-server")。
    """
    candidates: list[str] = []
    env_bin = os.environ.get("ACOUSECOPE_LLAMA_BIN", "").strip()
    if env_bin:
        candidates.append(env_bin)
    if hasattr(sys, "_MEIPASS"):
        candidates.append(str(Path(sys._MEIPASS) / "llama-server"))
    candidates.append(str(_DEV_LLAMA_BIN))

    def _usable(p: str) -> bool:
        return os.path.isfile(p) and os.access(p, os.X_OK)

    for c in candidates:
        if _usable(c):
            return c
    found = shutil.which("llama-server")
    if found and _usable(found):
        return found
    return None


def models_dir() -> Path:
    """应用数据目录下的 llama.cpp 模型沙盒目录（自动创建）。"""
    d = get_data_dir() / "llama_models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _free_port() -> int:
    """从 127.0.0.1 取一个空闲端口（bind 0 → getsockname → 关闭）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _serve_args(
    binary: str, model_path: str | Path, port: int, ctx_size: int,
    mmproj: str | Path | None = None,
) -> list[str]:
    """构造 llama-server 启动参数（纯函数，便于测试逐字段断言，禁止真启动进程）。

    T-1022 §4：传入 `mmproj`（多模态投影 / 视觉塔）时附加 `--mmproj <file>`，
    使内置引擎能读图；None（纯文本模型）时 argv 与既有完全一致。
    """
    args = [
        binary,
        "-m",
        str(model_path),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--ctx-size",
        str(ctx_size),
    ]
    if mmproj:
        args += ["--mmproj", str(mmproj)]
    return args


def _mmproj_for(model_path: str | Path) -> Path | None:
    """按模型文件自动定位同目录视觉塔（mmproj）文件；无/G 不存在 → None。

    依据受管目录条目的 `mmproj.filename` 同名匹配（纯文本条目返回 None），
    文件缺失时返回 None（引擎退回纯文本行为，绝不因缺文件中止启动）。
    """
    try:
        from acouscope.ai import llama_models
        target = Path(model_path)
        for info in llama_models.list_models():
            if Path(info.filename).name != target.name or info.mmproj is None:
                continue
            cand = target.parent / info.mmproj.filename
            return cand if cand.is_file() else None
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# T-1022 §9.1：受管引擎状态文件（崩溃/强杀兜底——启动时清理陈旧实例）
# ---------------------------------------------------------------------------

def engine_state_path() -> Path:
    """受管引擎状态文件路径（应用数据目录；记录 kind/pid/port/exe_path）。

    数据目录**调用期解析**（`acouscope.utils.config.get_data_dir` 现场取），
    以便宿主/测试重定向数据目录后本函数随之生效（不在 import 期绑定死）。
    """
    from acouscope.utils.config import get_data_dir as _get_data_dir
    return _get_data_dir() / "engine_state.json"


def _app_resource_roots() -> tuple[Path, ...]:
    """**本应用**资源目录（只有落在这些目录内的可执行文件才允许被清理逻辑终止）。

    覆盖：PyInstaller 解包目录（sys._MEIPASS）、开发模式包根 `<包根>/resources`
    （内含 llama-server 与 bundled ollama 两处内置组件）。**用户自装**的
    ollama / llama-server（/usr/local/bin、/opt/homebrew/bin、Applications…）
    一律不在其中 → 绝不被本模块终止。
    """
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    roots.append(_DEV_LLAMA_BIN.parent.parent)      # <包根>/resources
    return tuple(roots)


def is_app_owned_exe(exe_path: str | Path | None) -> bool:
    """可执行文件是否属于本应用资源目录（禁误杀外部引擎的判据）。"""
    if not exe_path:
        return False
    try:
        real = Path(str(exe_path)).resolve()
    except Exception:
        return False
    for root in _app_resource_roots():
        try:
            real.relative_to(root.resolve())
            return True
        except Exception:
            continue
    return False


def _pid_alive(pid: int) -> bool:
    """进程是否仍在（os.kill(pid, 0)；无权限视为存活）。"""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False
    return True


def _exe_path_of(pid: int) -> str | None:
    """进程可执行文件路径（Linux /proc → ps 兜底）；取不到返回 None。"""
    proc = Path(f"/proc/{pid}/exe")
    try:
        if proc.exists():
            return os.readlink(proc)
    except Exception:
        pass
    try:
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True, timeout=5.0, check=False,
        )
        if out.returncode == 0:
            text = out.stdout.decode("utf-8", errors="replace").strip()
            return text or None
    except Exception:
        pass
    return None


def _run(argv: list[str]) -> str | None:
    """执行外部命令返回 stdout；失败返回 None（绝不抛）。"""
    try:
        out = subprocess.run(argv, capture_output=True, timeout=5.0, check=False)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    try:
        return out.stdout.decode("utf-8", errors="replace")
    except Exception:
        return None


def _port_owner_pids(port: int) -> set[int]:
    """监听指定端口的进程号集合（lsof → netstat 兜底）。

    取不到（命令缺失 / 权限受限）→ 空集合（保守：宁可不清，绝不误杀）。
    """
    if port <= 0:
        return set()
    out = _run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"])
    if out:
        return {int(t) for t in out.split() if t.strip().isdigit()}
    win = _run(["netstat", "-ano"])
    if not win:
        return set()
    pids: set[int] = set()
    for line in win.splitlines():
        parts = line.split()
        if len(parts) >= 5 and f":{port}" in parts[1] and "listening" in \
                parts[3].lower():
            if parts[-1].isdigit():
                pids.add(int(parts[-1]))
    return pids


def _kill_pid(pid: int) -> None:
    """终止进程（先 SIGTERM，短超时后 SIGKILL；绝不抛）。"""
    import signal
    try:
        os.kill(pid, signal.SIGTERM)
    except Exception:
        return
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except Exception:
        pass


def read_engine_state() -> dict | None:
    """读状态文件（缺失/损坏 → None；绝不抛）。"""
    try:
        import json
        data = json.loads(engine_state_path().read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def clear_engine_state() -> None:
    """删除状态文件（幂等；绝不抛）。"""
    try:
        engine_state_path().unlink(missing_ok=True)
    except Exception:
        pass


def write_engine_state(kind: str, pid: int, port: int,
                       exe_path: str | Path) -> None:
    """登记受管引擎实例（kind/pid/port/exe_path/started_at；绝不抛）。"""
    import json
    payload = {
        "kind": str(kind),
        "pid": int(pid),
        "port": int(port),
        "exe_path": str(exe_path),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    try:
        path = engine_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        pass


def stale_entry_is_reapable(entry: dict, *, alive: bool,
                            exe_path: str | None,
                            port_pids: set[int]) -> bool:
    """陈旧实例是否可清理（三项**全部**命中才允许终止，纯函数）。

    ① PID 是否仍在；② exe_path 是否落在本应用资源目录内；
    ③ 端口是否由该 PID 占用。任一项不符 → 不得杀（禁误杀用户自装引擎）。
    """
    if not alive:
        return False
    pid = int(entry.get("pid") or 0)
    if pid <= 0 or pid not in port_pids:
        return False
    return is_app_owned_exe(exe_path)


def cleanup_stale_engines(
    state: dict | None = None,
    *,
    alive_fn=None,
    exe_fn=None,
    port_pids_fn=None,
    kill_fn=None,
) -> list[int]:
    """启动时清理陈旧受管引擎（崩溃/强杀兜底）；返回被终止的 PID 列表。

    默认探测一律走真实系统调用；测试可注入四个探针（alive_fn / exe_fn /
    port_pids_fn / kill_fn）以离屏走查各分支。三项校验任一不符即**不动**
    （用户自装的外部 ollama / llama-server 永不被误杀）；状态文件在清理后
    删除，避免重复判定。
    """
    entry = read_engine_state() if state is None else state
    if not isinstance(entry, dict) or not entry:
        clear_engine_state()
        return []
    alive_fn = alive_fn or _pid_alive
    exe_fn = exe_fn or _exe_path_of
    port_pids_fn = port_pids_fn or _port_owner_pids
    kill_fn = kill_fn or _kill_pid
    pid = int(entry.get("pid") or 0)
    if pid == os.getpid():
        clear_engine_state()
        return []
    try:
        alive = bool(alive_fn(pid))
        # ② 归属校验用**实时解析**的 exe 路径（比状态文件里的记录更可信：
        # 记录可能过期/被改，实时路径才是即将被终止的那个进程的真身）
        exe = exe_fn(pid) if alive else None
        ports = set(port_pids_fn(int(entry.get("port") or 0))) if alive \
            else set()
    except Exception:
        clear_engine_state()
        return []
    if stale_entry_is_reapable(entry, alive=alive, exe_path=exe,
                               port_pids=ports):
        try:
            kill_fn(pid)
        except Exception:
            pass
        clear_engine_state()
        return [pid]
    clear_engine_state()
    return []


class LlamaRuntime:
    """受管 llama.cpp 运行时（单例，由 get_runtime() 获取）。

    状态机：stopped → starting → ready | failed；stop() 回到 stopped。
    所有公开方法绝不向调用方抛异常；网络访问全部隔离在 _wait_ready() 内。
    """

    def __init__(self) -> None:
        self.state: str = "stopped"
        self.base_url: str = ""
        self.last_error: str = ""
        self._proc: subprocess.Popen | None = None
        self._pending_url: str = ""
        self._lock = threading.Lock()

    # ------------------------------------------------------------- start
    def start(
        self, model_path: str | Path, ctx_size: int = 4096,
        timeout: float = 180.0, mmproj: str | Path | None = None,
    ) -> bool:
        """启动内置 llama-server（幂等；state=="ready" 直接 True；绝不抛异常）。

        模型缺失 → state="failed" + 友好文案 + False（不启进程）；
        二进制缺失 → state="failed" + 友好文案 + False；
        就绪 → state="ready"、base_url 赋值动态端口、True；
        超时/进程退出 → 清理并 state="failed"、False。

        T-1022：`mmproj` 为 None 时按条目**自动**寻找同目录视觉塔文件（视觉
        模型下载后即可读图）；启动成功登记引擎状态文件（崩溃/强杀兜底），
        启动前先清理陈旧受管实例（三项校验，绝不误杀外部引擎）。
        """
        with self._lock:
            if self.state == "ready":
                return True
            if self.state == "starting":
                return False
            model = Path(model_path) if str(model_path).strip() else None
            if model is None or not model.is_file():
                self.state = "failed"
                self.last_error = _ERR_NO_MODEL
                return False
            binary = find_llama_binary()
            if binary is None:
                self.state = "failed"
                self.last_error = _ERR_NO_BINARY
                return False
            # 崩溃/强杀兜底：清理上一次未正常退出而残留的受管实例
            try:
                cleanup_stale_engines()
            except Exception:
                pass
            vision = Path(mmproj) if mmproj else _mmproj_for(model)
            port = _free_port()
            base_url = f"http://127.0.0.1:{port}"
            try:
                proc = subprocess.Popen(
                    _serve_args(binary, model, port, ctx_size, vision),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                )
            except Exception as exc:
                self._proc = None
                self.state = "failed"
                self.last_error = f"{_ERR_PROCESS_EXITED}（{type(exc).__name__}）"
                return False
            self._proc = proc
            self._pending_url = base_url
            self.state = "starting"
            self.base_url = ""
            self.last_error = ""
            # 轮询可能持续很久（模型加载可达数十秒）：不持锁等待，避免与 stop() 互相阻塞
        write_engine_state("llama_cpp", proc.pid, port, binary)
        ok = self._wait_ready(timeout)
        with self._lock:
            if ok:
                self.state = "ready"
                self.base_url = self._pending_url
                self.last_error = ""
                return True
            # 失败路径：清理进程，保留 _wait_ready 写好的 failed 语义
            proc, self._proc = self._proc, None
            self.base_url = ""
            clear_engine_state()
            if proc is not None:
                try:
                    proc.terminate()
                    proc.wait(5.0)
                except Exception:
                    try:
                        proc.kill()
                        proc.wait()
                    except Exception:
                        pass
            self.state = "failed"
            if not self.last_error:
                self.last_error = _ERR_NOT_READY
            return False

    # --------------------------------------------------------- _wait_ready
    def _wait_ready(self, timeout: float) -> bool:
        """轮询内置实例 GET /health 直至就绪（网络访问全部隔离在此）。

        单次请求 timeout=1.0s，间隔 0.3s，总时长 timeout；
        HTTP 200 → True；HTTP 503 / 连接拒绝 → 继续（模型加载中）；
        子进程已退出（poll() is not None）→ _ERR_PROCESS_EXITED；
        超时 → _ERR_NOT_READY。
        """
        url = self._pending_url
        deadline = time.monotonic() + max(timeout, 0.0)
        while time.monotonic() < deadline:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                self.state = "failed"
                self.last_error = _ERR_PROCESS_EXITED
                return False
            try:
                req = urllib.request.Request(f"{url}/health")
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    if getattr(resp, "status", 200) == 200:
                        return True
            except Exception:
                pass
            time.sleep(0.3)
        self.state = "failed"
        self.last_error = _ERR_NOT_READY
        return False

    # -------------------------------------------------------------- stop
    def stop(self, timeout: float = 5.0) -> None:
        """停止内置 llama-server（幂等；terminate → wait(timeout) → kill → wait；绝不抛）。

        T-1022 §9.1「关闭即停」：同时清理引擎状态文件（幂等）；语义是**停进程
        释放内存**，绝不删除用户已下载的模型文件（删除是另一个显式动作）。
        """
        with self._lock:
            proc, self._proc = self._proc, None
            self.base_url = ""
        clear_engine_state()
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout)
            except Exception:
                try:
                    proc.kill()
                    proc.wait()
                except Exception:
                    pass
        with self._lock:
            self.state = "stopped"

    # -------------------------------------------------------------- repr
    def __repr__(self) -> str:  # 调试用
        return f"<LlamaRuntime state={self.state!r} base_url={self.base_url!r}>"


_runtime: LlamaRuntime | None = None
_runtime_lock = threading.Lock()


def get_runtime() -> LlamaRuntime:
    """模块级单例（两次调用 is 同一对象）。"""
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = LlamaRuntime()
        return _runtime


atexit.register(lambda: get_runtime().stop())
