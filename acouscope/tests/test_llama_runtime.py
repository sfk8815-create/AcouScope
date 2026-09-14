# SPDX-License-Identifier: GPL-3.0-only
"""T-312 守卫测试：内置 llama.cpp runtime（受管子进程 + 动态端口）。

全 mock：subprocess.Popen 与 urllib.request.urlopen 一律 monkeypatch
（fake proc + fake resp 序列）；不真起进程、不真联网、不真下载；
不要求 resources/bin/llama-server 存在（T-315 才入包）。
不 import ollama_runtime（模块独立）。
"""

import urllib.error
from pathlib import Path

from acouscope.ai import llama_runtime as lr
from acouscope.ai.llama_runtime import (
    LlamaRuntime,
    _ERR_NO_BINARY,
    _ERR_NO_MODEL,
    _ERR_NOT_READY,
    _ERR_PROCESS_EXITED,
    _free_port,
    _serve_args,
    find_llama_binary,
    get_runtime,
    models_dir,
)


class FakeProc:
    """受管 fake 子进程：poll 返回给定 returncode（None=存活），记录清理调用。

    T-1022：补 `pid` 属性以镜像 `subprocess.Popen` 接口——引擎启动时会把
    (kind, pid, port, exe_path) 登记进状态文件（崩溃兜底），假进程若无 pid
    则无法走该分支（守卫强度不降：状态登记路径由 tests/test_engine_lifecycle.py
    另行逐点断言）。
    """

    def __init__(self, returncode=None):
        self._rc = returncode
        self.pid = 4242
        self.terminated = 0
        self.killed = 0
        self.waits: list = []

    def poll(self):
        return self._rc

    def terminate(self):
        self.terminated += 1

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if self._rc is None:
            self._rc = 0

    def kill(self):
        self.killed += 1


class FakeResp:
    """fake urlopen 上下文管理器：带 status 与 read()。"""

    def __init__(self, status=200, body=b"ok"):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_executable(p: Path) -> str:
    p.write_bytes(b"#!/bin/sh\nexit 0\n")
    p.chmod(0o755)
    return str(p)


class TestPureHelpers:
    def test_serve_args_pure(self):
        argv = _serve_args("/bin/llama-server", "/tmp/m.gguf", 51234, 4096)
        assert argv == [
            "/bin/llama-server",
            "-m",
            "/tmp/m.gguf",
            "--host",
            "127.0.0.1",
            "--port",
            "51234",
            "--ctx-size",
            "4096",
        ]
        # 字段语义：模型路径紧跟 -m，host 恒 127.0.0.1，port/ctx 为 str
        assert argv[argv.index("-m") + 1] == "/tmp/m.gguf"
        assert argv[argv.index("--host") + 1] == "127.0.0.1"
        assert argv[argv.index("--port") + 1] == "51234"
        assert argv[argv.index("--ctx-size") + 1] == "4096"

    def test_free_port_is_localhost_dynamic(self, monkeypatch):
        binds: list = []

        class FakeSock:
            def __init__(self, family=None, type=None):
                pass

            def bind(self, addr):
                binds.append(addr)

            def getsockname(self):
                return ("127.0.0.1", 45678)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(lr.socket, "socket", lambda *a, **k: FakeSock())
        port = _free_port()
        assert binds == [("127.0.0.1", 0)]
        assert isinstance(port, int) and port > 0

    def test_find_binary_env_override(self, monkeypatch, tmp_path):
        fake = _fake_executable(tmp_path / "llama-server-fake")
        monkeypatch.setenv("ACOUSECOPE_LLAMA_BIN", fake)
        assert find_llama_binary() == fake
        # 均不存在 → None（不报错）
        # 注：T-315 后 resources/bin 已入包，dev 候选③会命中 bundled
        # 二进制；此处将 _DEV_LLAMA_BIN 打桩到不存在路径以还原原前置条件。
        monkeypatch.setenv("ACOUSECOPE_LLAMA_BIN", str(tmp_path / "nope"))
        monkeypatch.setattr(lr, "_DEV_LLAMA_BIN", tmp_path / "no-dev-bin")
        monkeypatch.setattr(lr.shutil, "which", lambda name: None)
        assert find_llama_binary() is None

    def test_models_dir_sandboxed(self, monkeypatch, tmp_path):
        monkeypatch.setattr(lr, "get_data_dir", lambda: tmp_path)
        d = models_dir()
        assert d == tmp_path / "llama_models"
        assert d.is_dir()


class _StartHarness:
    """start() 全 mock 脚手架：fake Popen + 可脚本化 fake urlopen。"""

    def __init__(self, monkeypatch, tmp_path, proc, urlopen_side_effects):
        self.proc = proc
        self.popen_calls: list = []
        model = tmp_path / "model.gguf"
        model.write_bytes(b"GGUF-fake")
        self.model = model
        fake_bin = _fake_executable(tmp_path / "llama-server-fake")

        monkeypatch.setattr(
            lr, "find_llama_binary", lambda: fake_bin, raising=False
        )
        monkeypatch.setenv("ACOUSECOPE_LLAMA_BIN", fake_bin)

        def fake_popen(argv, **kwargs):
            self.popen_calls.append((list(argv), kwargs))
            return proc

        monkeypatch.setattr(lr.subprocess, "Popen", fake_popen)

        state = {"i": 0}

        def fake_urlopen(req, timeout=None):
            i = state["i"]
            state["i"] += 1
            effect = urlopen_side_effects[min(i, len(urlopen_side_effects) - 1)]
            if isinstance(effect, Exception):
                raise effect
            return effect

        monkeypatch.setattr(lr.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(lr.time, "sleep", lambda s: None)


def _http_503():
    return urllib.error.HTTPError(
        url="http://127.0.0.1:1/health", code=503, msg="Service Unavailable",
        hdrs=None, fp=None,
    )


def _conn_refused():
    return urllib.error.URLError(ConnectionRefusedError("refused"))


class TestStart:
    def test_start_no_binary_friendly_fail(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ACOUSECOPE_LLAMA_BIN", raising=False)
        monkeypatch.setattr(lr, "find_llama_binary", lambda: None)
        model = tmp_path / "model.gguf"
        model.write_bytes(b"x")
        rt = LlamaRuntime()
        assert rt.start(model) is False
        assert rt.state == "failed"
        assert rt.last_error == _ERR_NO_BINARY

    def test_start_no_model_friendly_fail(self, monkeypatch, tmp_path):
        calls: list = []
        monkeypatch.setattr(
            lr.subprocess, "Popen", lambda *a, **k: calls.append(1)
        )
        fake_bin = _fake_executable(tmp_path / "llama-server-fake")
        monkeypatch.setenv("ACOUSECOPE_LLAMA_BIN", fake_bin)
        monkeypatch.setattr(lr, "find_llama_binary", lambda: fake_bin)
        rt = LlamaRuntime()
        assert rt.start("") is False
        assert rt.state == "failed"
        assert rt.last_error == _ERR_NO_MODEL
        assert calls == []  # 未启进程
        # 不存在的模型路径同样友好失败
        assert rt.start(tmp_path / "missing.gguf") is False
        assert rt.last_error == _ERR_NO_MODEL

    def test_start_ready_after_503_then_200(self, monkeypatch, tmp_path):
        h = _StartHarness(
            monkeypatch, tmp_path, FakeProc(),
            [_http_503(), _http_503(), FakeResp(200)],
        )
        rt = LlamaRuntime()
        assert rt.start(h.model) is True
        assert rt.state == "ready"
        assert "127.0.0.1:" in rt.base_url
        port = int(rt.base_url.rsplit(":", 1)[1])
        assert port not in (8080, 11434, 1234)
        assert rt.last_error == ""
        assert len(h.popen_calls) == 1

    def test_start_timeout_failed(self, monkeypatch, tmp_path):
        proc = FakeProc()
        h = _StartHarness(
            monkeypatch, tmp_path, proc, [_conn_refused()]
        )
        rt = LlamaRuntime()
        assert rt.start(h.model, timeout=0.2) is False
        assert rt.state == "failed"
        assert rt.last_error == _ERR_NOT_READY
        assert proc.terminated >= 1  # 失败路径清理了进程

    def test_start_proc_exited_failed(self, monkeypatch, tmp_path):
        h = _StartHarness(
            monkeypatch, tmp_path, FakeProc(returncode=1), [_conn_refused()]
        )
        rt = LlamaRuntime()
        assert rt.start(h.model) is False
        assert rt.state == "failed"
        assert rt.last_error == _ERR_PROCESS_EXITED


class TestLifecycle:
    def test_stop_idempotent(self, monkeypatch, tmp_path):
        proc = FakeProc()
        h = _StartHarness(
            monkeypatch, tmp_path, proc,
            [_http_503(), FakeResp(200)],
        )
        rt = LlamaRuntime()
        assert rt.start(h.model) is True
        rt.stop()
        assert rt.state == "stopped"
        rt.stop()  # 幂等：二次 stop 不抛
        assert rt.state == "stopped"
        assert proc.terminated >= 1
        assert proc.waits  # wait 被调用（记录 timeout 参数）

    def test_singleton_and_state_isolation(self):
        assert get_runtime() is get_runtime()
        rt = LlamaRuntime()
        rt2 = LlamaRuntime()
        rt.state = "ready"
        rt.base_url = "http://127.0.0.1:1"
        assert rt2.state == "stopped" and rt2.base_url == ""
