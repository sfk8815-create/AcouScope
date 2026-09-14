# SPDX-License-Identifier: GPL-3.0-only
"""内置 Ollama 运行时管理器（T-303b，AT-410 零配置地基）。

OLLAMA_RUNTIME_V1：以受管子进程方式拉起 ``ollama serve``，动态端口监听
127.0.0.1，模型目录沙盒在应用数据目录
（~/Library/Application Support/AcouScope/ollama_models）。

零配置：无需用户自行安装 Ollama；启动时按优先级寻找内置/已装二进制，
找不到则给友好中文文案，绝不向调用方抛异常。

用户可见文案铁律（零终端）：禁出现命令行 / URL / 安装指引；
目标用户是田野研究者而非工程师。
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

# OLLAMA_RUNTIME_V1：内置 Ollama 运行时（零配置，AT-410；受管子进程）

from acouscope.utils.config import get_data_dir

#: 候选二进制固定路径（外部已装回退，bundled 未部署时使用）。
_FALLBACK_BINARIES: tuple[str, ...] = (
    "/Applications/Ollama.app/Contents/Resources/ollama",
    "/usr/local/bin/ollama",
    "/opt/homebrew/bin/ollama",
)

# T-316 包内 bundled ollama（整套资产目录，与 resources/bin/ 下既有 llama-server
# 隔离；serve 按 @loader_path 同目录查找 llama-server → 必须整套同目录）。
# 目录约定（升级策略约束）：bundled = 出厂基准只读目录，版本焊死随 AcouScope
# 发版锁定；未来用户级引擎放应用数据目录、可回滚 bundled（升级/回滚属后续
# 独立任务，本任务不改目录布局）。frozen 形态对应 _MEIPASS/ollama/。
_DEV_OLLAMA_DIR = (
    Path(__file__).resolve().parents[1] / "resources" / "bin" / "ollama"
)
_DEV_OLLAMA_BIN = _DEV_OLLAMA_DIR / "ollama"

# 友好失败文案（零终端：不含命令 / URL / 安装指引）。
_ERR_NO_BINARY = "本地引擎启动失败：未找到内置引擎组件"
_ERR_NOT_READY = "本地引擎启动失败：服务未在规定时间内就绪"
_ERR_PROCESS_EXITED = "本地引擎启动失败：进程意外退出"
_FALLBACK_NOTICE = "本地引擎已自动回退至随软件自带的版本"

#: 回退提示位文案（一次性温和提示，不反复）：用户级引擎启动失败自动
#: 落回 bundled 后置此状态，供调用方在 UI 提示一次。


def _usable(p) -> bool:
    return os.path.isfile(p) and os.access(p, os.X_OK)


def _bundle_dirs() -> list[Path]:
    """bundled 候选目录（frozen 优先 + dev；T-316 整套资产目录）。"""
    dirs: list[Path] = []
    if hasattr(sys, "frozen"):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            dirs.append(Path(meipass) / "ollama")
    dirs.append(_DEV_OLLAMA_DIR)
    return dirs


def _bundled_candidate() -> str | None:
    """仅在 bundled（frozen/dev）目录内寻找可执行 ollama（回退用，不含外部）。"""
    for d in _bundle_dirs():
        if _usable(d / "ollama"):
            return str(d / "ollama")
    return None


def find_ollama_binary() -> str | None:
    """按优先级寻找可执行的 ollama 二进制，返回第一个命中路径；均未命中返回 None。

    顺序（T-319：用户级优先、bundled 兜底，焊死语义保留）：
    ① 环境变量 ACOUSCOPE_OLLAMA_BIN（调试/覆盖逃生门，非空且存在可执行）
    ② 用户级引擎（升级已安装且指针生效，见 ai.ollama_engines.user_binary）
    ③ frozen bundled：sys._MEIPASS/"ollama"/"ollama"（仅 frozen 时）
    ④ dev bundled：<包根>/resources/bin/ollama/ollama（_DEV_OLLAMA_BIN）
    ⑤ 外部回退：/Applications → /usr/local/bin → /opt/homebrew/bin → which。

    焊死语义：bundled（③④）优先于外部已装（⑤），防版本漂移；bundled 目录
    已部署但其中二进制缺失/不可执行时**不静默回退外部**（返回 None → 上层
    _ERR_NO_BINARY 零终端文案）；用户级指针损坏（目录缺/二进制不可执行）
    自动落回 bundled（规格 ④）；bundled 整体未部署（如资产 fetch 前的开发
    环境）时保留外部回退，行为与既有版本一致。
    """
    # ① env 覆盖（高级调试逃生门；显式指定即尊重，不可用继续走链）
    env_bin = os.environ.get("ACOUSCOPE_OLLAMA_BIN", "").strip()
    if env_bin and _usable(env_bin):
        return env_bin

    # ② 用户级引擎（T-319 升级档位；惰性 import 防模块环）
    from acouscope.ai.ollama_engines import user_binary
    user = user_binary()
    if user:
        return user

    # ③ frozen bundled / ④ dev bundled（整套资产目录）
    deployed = False
    for d in _bundle_dirs():
        if not d.is_dir():
            continue
        deployed = True
        if _usable(d / "ollama"):
            return str(d / "ollama")
    if deployed:
        # 已部署但二进制缺失/损坏 → 不静默回退外部（版本焊死语义）
        return None

    # ⑤ 外部回退（bundled 未部署时）
    for p in _FALLBACK_BINARIES:
        if _usable(p):
            return p
    found = shutil.which("ollama")
    if found and _usable(found):
        return found
    return None


def models_dir() -> Path:
    """应用数据目录下的 Ollama 模型沙盒目录（自动创建）。"""
    d = get_data_dir() / "ollama_models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _free_port() -> int:
    """从 127.0.0.1 取一个空闲端口（bind 0 → getsockname → 关闭）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _serve_env(port: int) -> dict:
    """构造受管 serve 子进程的环境变量（纯函数，便于测试断言，禁止真启动进程）。"""
    return {
        **os.environ,
        "OLLAMA_HOST": f"127.0.0.1:{port}",
        "OLLAMA_MODELS": str(models_dir()),
        "OLLAMA_KEEP_ALIVE": "5m",
    }


class OllamaRuntime:
    """受管 Ollama 运行时（单例，由 get_runtime() 获取）。

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
        self._fallback_tried: bool = False
        #: 一次性回退提示位：用户级引擎启动失败自动落回 bundled 后置 True，
        #: 供调用方温和提示一次（不反复；后续正常启动不再置位）。
        self.fallback_notice: str = ""

    # ------------------------------------------------------------- start
    def start(self, timeout: float = 30.0) -> bool:
        """启动内置 Ollama（幂等；state=="ready" 直接 True；绝不抛异常）。

        二进制缺失 → state="failed" + 友好文案 + False；
        就绪 → state="ready"、base_url 赋值动态端口、True；
        超时/进程退出 → 清理并 state="failed"、False。

        T-319 规格 ④：若本次二进制来自用户级引擎且启动失败（Popen / 就绪
        任一环节），自动改用 bundled 重试一次；成功则置一次性回退提示位
        fallback_notice（不反复提示）。
        """
        with self._lock:
            if self.state == "ready":
                return True
            if self.state == "starting":
                return False
            binary = find_ollama_binary()
            if binary is None:
                self.state = "failed"
                self.last_error = _ERR_NO_BINARY
                return False
            is_user = self._is_user_binary(binary)
        if self._spawn_and_wait(binary, timeout):
            return True
        # 用户级启动失败 → 自动落回 bundled 重试一次（一次性提示位）
        if is_user and not self._fallback_tried:
            with self._lock:
                self._fallback_tried = True
            bundled = _bundled_candidate()
            if bundled and self._spawn_and_wait(bundled, timeout):
                with self._lock:
                    self.fallback_notice = _FALLBACK_NOTICE
                return True
        return False

    def _is_user_binary(self, binary: str) -> bool:
        """binary 是否来自用户级引擎（升级档位；惰性 import 防模块环）。"""
        try:
            from acouscope.ai.ollama_engines import user_binary
            user = user_binary()
        except Exception:
            return False
        return bool(user) and os.path.abspath(binary) == os.path.abspath(user)

    def _spawn_and_wait(self, binary: str, timeout: float) -> bool:
        """以指定二进制 Popen serve 并等待就绪；失败清理并置 failed。

        就绪 → state="ready"、base_url 动态端口、True；Popen 异常 / 超时 /
        进程退出 → 清理子进程并 state="failed" + 友好文案、False。
        轮询不持锁（避免与 stop() 互相阻塞）。
        """
        port = _free_port()
        base_url = f"http://127.0.0.1:{port}"
        try:
            proc = subprocess.Popen(
                [binary, "serve"],
                env=_serve_env(port),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
            )
        except Exception as exc:
            with self._lock:
                self._proc = None
                self.state = "failed"
                self.last_error = f"{_ERR_PROCESS_EXITED}（{type(exc).__name__}）"
            return False
        with self._lock:
            self._proc = proc
            self._pending_url = base_url
            self.state = "starting"
            self.base_url = ""
            self.last_error = ""
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
        """轮询内置实例 GET /api/tags 直至就绪（网络访问全部隔离在此）。

        单次请求 timeout=1.0s，间隔 0.3s，总时长 timeout；
        200 且 JSON 可解析 → True；子进程已退出（poll() is not None）
        或超时 → state="failed" + 友好文案 + False。
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
                req = urllib.request.Request(f"{url}/api/tags")
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    if getattr(resp, "status", 200) == 200:
                        json.loads(resp.read().decode("utf-8"))
                        return True
            except Exception:
                pass
            time.sleep(0.3)
        self.state = "failed"
        self.last_error = _ERR_NOT_READY
        return False

    # -------------------------------------------------------------- stop
    def stop(self, timeout: float = 5.0) -> None:
        """停止内置 Ollama（幂等；terminate → wait(timeout) → kill → wait；绝不抛）。"""
        with self._lock:
            proc, self._proc = self._proc, None
            self.base_url = ""
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
        return f"<OllamaRuntime state={self.state!r} base_url={self.base_url!r}>"


_runtime: OllamaRuntime | None = None
_runtime_lock = threading.Lock()


def get_runtime() -> OllamaRuntime:
    """模块级单例（两次调用 is 同一对象）。"""
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = OllamaRuntime()
        return _runtime


atexit.register(lambda: get_runtime().stop())
