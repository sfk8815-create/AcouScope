# SPDX-License-Identifier: GPL-3.0-only
"""T-303b: 内置 Ollama 运行时管理器（假二进制 + monkeypatch；禁真实 ollama / 禁真实网络）。"""
import os
import stat
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, "src")

from acouscope.ai import ollama_runtime as rt  # noqa: E402
from acouscope.ai.ollama_runtime import (  # noqa: E402
    OllamaRuntime,
    _free_port,
    _serve_env,
    find_ollama_binary,
    get_runtime,
    models_dir,
)

BANNED = ["终端", "ollama serve", "ollama pull", "ollama.com", "http", "请安装", "brew"]


def _fake_bin(tmp_path: Path) -> str:
    p = tmp_path / "ollama_fake"
    p.write_text("#!/bin/sh\nexec sleep 30\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(p)


def _fake_popen_factory():
    calls: list = []

    class FakeProc:
        def __init__(self, cmd, **kwargs):
            self.cmd = cmd
            self.kwargs = kwargs
            self.terminated = False
            self.killed = False
            calls.append(self)

        def poll(self):
            return None  # 假进程“一直活着”

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

        def wait(self, timeout=None):
            return 0

    return calls, mock.MagicMock(side_effect=FakeProc)


def test_find_binary_env_override(tmp_path, monkeypatch):
    fake = _fake_bin(tmp_path)
    monkeypatch.setenv("ACOUSCOPE_OLLAMA_BIN", fake)
    assert find_ollama_binary() == fake


def test_models_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(rt, "get_data_dir", lambda: tmp_path)
    d = models_dir()
    assert d.name == "ollama_models"
    assert d.is_dir()
    assert d == tmp_path / "ollama_models"


def test_free_port():
    p = _free_port()
    assert isinstance(p, int)
    assert 1024 < p < 65536


def test_serve_env(monkeypatch, tmp_path):
    monkeypatch.setattr(rt, "get_data_dir", lambda: tmp_path)
    env = _serve_env(12345)
    assert env["OLLAMA_HOST"] == "127.0.0.1:12345"
    assert env["OLLAMA_MODELS"]
    assert env["OLLAMA_KEEP_ALIVE"] == "5m"


def test_start_stop_lifecycle(tmp_path, monkeypatch):
    fake = _fake_bin(tmp_path)
    monkeypatch.setenv("ACOUSCOPE_OLLAMA_BIN", fake)
    monkeypatch.setattr(rt, "get_data_dir", lambda: tmp_path)
    rt_obj = OllamaRuntime()
    calls, fake_popen = _fake_popen_factory()
    monkeypatch.setattr(rt.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(rt_obj, "_wait_ready", lambda timeout: True)
    assert rt_obj.start() is True
    assert rt_obj.state == "ready"
    assert "127.0.0.1:" in rt_obj.base_url
    assert len(calls) == 1 and calls[0].cmd[1] == "serve"
    rt_obj.stop()
    assert rt_obj.state == "stopped"
    assert calls[0].terminated is True


def test_start_idempotent(tmp_path, monkeypatch):
    fake = _fake_bin(tmp_path)
    monkeypatch.setenv("ACOUSCOPE_OLLAMA_BIN", fake)
    monkeypatch.setattr(rt, "get_data_dir", lambda: tmp_path)
    rt_obj = OllamaRuntime()
    calls, fake_popen = _fake_popen_factory()
    monkeypatch.setattr(rt.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(rt_obj, "_wait_ready", lambda timeout: True)
    assert rt_obj.start() is True
    assert rt_obj.start() is True  # ready → 直接 True
    assert len(calls) == 1  # 未重复构造进程


def test_start_no_binary(monkeypatch):
    monkeypatch.setenv("ACOUSCOPE_OLLAMA_BIN", "/nonexistent/ollama")
    monkeypatch.setattr(rt, "find_ollama_binary", lambda: None)
    monkeypatch.setattr(rt.shutil, "which", lambda _n: None)
    rt_obj = OllamaRuntime()
    assert rt_obj.start() is False
    assert rt_obj.state == "failed"
    assert isinstance(rt_obj.last_error, str) and rt_obj.last_error
    for w in BANNED:
        assert w not in rt_obj.last_error


def test_get_runtime_singleton():
    assert get_runtime() is get_runtime()


def test_fail_paths_zero_terminal(tmp_path, monkeypatch):
    """超时/进程退出/起进程失败：last_error 均为友好中文且零终端。"""
    fake = _fake_bin(tmp_path)
    monkeypatch.setenv("ACOUSCOPE_OLLAMA_BIN", fake)
    monkeypatch.setattr(rt, "get_data_dir", lambda: tmp_path)

    # 1) 超时
    r1 = OllamaRuntime()
    calls1, fp1 = _fake_popen_factory()
    monkeypatch.setattr(rt.subprocess, "Popen", fp1)
    monkeypatch.setattr(r1, "_wait_ready", lambda timeout: False)
    assert r1.start() is False
    assert r1.state == "failed" and r1.last_error
    for w in BANNED:
        assert w not in r1.last_error

    # 2) 进程意外退出（_wait_ready 真实逻辑 + 假 urlopen 恒拒绝）
    r2 = OllamaRuntime()
    calls2, fp2 = _fake_popen_factory()

    def _dead(*a, **k):
        raise OSError("refused")

    class DeadProc:
        def __init__(self, cmd, **kwargs):
            self.cmd = cmd
            calls2.append(self)

        def poll(self):
            return -9  # 已退出

        def terminate(self):
            pass

        def kill(self):
            pass

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(rt.subprocess, "Popen", mock.MagicMock(side_effect=DeadProc))
    monkeypatch.setattr(rt.urllib.request, "urlopen", _dead)
    assert r2.start(timeout=2.0) is False
    assert r2.state == "failed" and r2.last_error
    for w in BANNED:
        assert w not in r2.last_error

    # 3) 起进程抛异常
    r3 = OllamaRuntime()
    monkeypatch.setattr(rt.subprocess, "Popen",
                        mock.MagicMock(side_effect=OSError("boom")))
    assert r3.start() is False
    assert r3.state == "failed" and r3.last_error
    for w in BANNED:
        assert w not in r3.last_error
