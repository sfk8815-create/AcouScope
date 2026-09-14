# SPDX-License-Identifier: GPL-3.0-only
"""T-304b: 模型商店后端（HTTP /api/pull）测试。

全 monkeypatch：urllib.request.urlopen 以 io.BytesIO 伪造 NDJSON 流响应，
零真实进程、零外网。CLI 子进程路线测试已全部删除。
"""
import io
import json
import sys
sys.path.insert(0, "src")
import urllib.error
import pytest
from acouscope.ai import model_manager as mm
from acouscope.ai.backends.local_registry import OLLAMA_BASE
from acouscope.ai.interpreter import CancelledError


class FakeResp:
    """伪造 urlopen 响应：context manager + 逐行可迭代（NDJSON 字节行）。"""

    def __init__(self, lines: list[dict]):
        payload = b"\n".join(json.dumps(o).encode("utf-8") for o in lines)
        self._buf = io.BytesIO(payload)
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return self

    def __next__(self):
        line = self._buf.readline()
        if not line:
            raise StopIteration
        return line

    def close(self):
        self.closed = True


def _lines(*objs) -> list[dict]:
    return list(objs)


def _fake_urlopen(monkeypatch, lines: list[dict], raise_exc: Exception | None = None):
    """monkeypatch urlopen，返回捕获容器（可断言传入的 Request）。"""
    captured: dict = {}

    def fake(req, timeout=None):
        captured["req"] = req
        captured["timeout"] = timeout
        if raise_exc is not None:
            raise raise_exc
        return FakeResp(lines)

    monkeypatch.setattr(mm.urllib.request, "urlopen", fake)
    return captured


def _set_disk_ok(monkeypatch):
    monkeypatch.setattr(mm, "precheck_disk", lambda m, p=None: (True, "ok"))


# ------------------------------------------------------------- 1. POST 目标
def test_pull_post_target(monkeypatch):
    cap = _fake_urlopen(monkeypatch, _lines({"status": "success"}))
    _set_disk_ok(monkeypatch)
    mm.pull_model("qwen2.5:3b", base_url="http://127.0.0.1:7777")
    req = cap["req"]
    assert req.full_url == "http://127.0.0.1:7777/api/pull"
    assert req.full_url.endswith("/api/pull")
    assert req.get_method() == "POST"
    body = req.data.decode("utf-8")
    assert "qwen2.5:3b" in body
    assert json.loads(body) == {"name": "qwen2.5:3b", "stream": True}
    assert req.get_header("Content-type") == "application/json"


# ------------------------------------------------------- 2. 多层进度聚合
def test_pull_progress_aggregated(monkeypatch):
    lines = _lines(
        {"digest": "a" * 16, "total": 1000, "completed": 0},
        {"digest": "b" * 16, "total": 3000, "completed": 0},
        {"digest": "a" * 16, "total": 1000, "completed": 500},
        {"digest": "b" * 16, "total": 3000, "completed": 1500},
        {"digest": "a" * 16, "total": 1000, "completed": 1000},
        {"digest": "b" * 16, "total": 3000, "completed": 3000},
        {"status": "success"},
    )
    _fake_urlopen(monkeypatch, lines)
    _set_disk_ok(monkeypatch)
    got: list[float] = []
    mm.pull_model("qwen2.5:3b", on_progress=got.append)
    assert got[-1] == 1.0
    assert all(0.0 <= v <= 1.0 for v in got)
    assert all(a <= b for a, b in zip(got, got[1:]))  # 单调不减
    assert abs(got[2] - 500 / 4000) < 1e-9   # a 层 500/4000
    assert abs(got[3] - 2000 / 4000) < 1e-9  # a 满 + b 1500


# --------------------------------------------------------- 3. 仅 success
def test_pull_success_only(monkeypatch):
    _fake_urlopen(monkeypatch, _lines({"status": "success"}))
    _set_disk_ok(monkeypatch)
    got: list[float] = []
    mm.pull_model("spark-x2.5-1.7b", on_progress=got.append)
    assert got == [1.0]


# ---------------------------------------------------------- 4. 错误行
def test_pull_error_line(monkeypatch):
    _fake_urlopen(monkeypatch, _lines({"digest": "c" * 16, "total": 10, "completed": 1},
                                      {"error": "boom"}))
    _set_disk_ok(monkeypatch)
    with pytest.raises(mm.PullError) as ei:
        mm.pull_model("qwen2.5:3b")
    assert str(ei.value) == "boom"


# ----------------------------------------------------------- 5. 取消
def test_pull_cancel(monkeypatch):
    cap = _fake_urlopen(monkeypatch, _lines({"status": "pulling"},
                                            {"status": "pulling"},
                                            {"status": "pulling"}))
    _set_disk_ok(monkeypatch)
    calls = {"n": 0}

    def is_cancelled():
        calls["n"] += 1
        return calls["n"] >= 3  # 第 3 次返回 True

    with pytest.raises(CancelledError):
        mm.pull_model("qwen2.5:3b", is_cancelled=is_cancelled)
    assert calls["n"] == 3
    assert cap["req"] is not None  # 连接已建立后才取消


# ----------------------------------------------------- 6. 连接失败
def test_pull_connection_failure(monkeypatch):
    _fake_urlopen(monkeypatch, [], raise_exc=urllib.error.URLError("refused"))
    _set_disk_ok(monkeypatch)
    with pytest.raises(mm.PullError) as ei:
        mm.pull_model("qwen2.5:3b")
    msg = str(ei.value)
    for word in ["http", "ollama.com", "终端", "安装", "serve", "pull"]:
        assert word not in msg, f"文案含禁词 {word!r}: {msg}"
    assert "本地引擎未就绪" in msg


# -------------------------------------------------- 7/8. 磁盘预检
def test_precheck_disk_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(mm.shutil, "disk_usage",
                        lambda p: type("U", (), {"free": 64 * 10**9})())
    ok, msg = mm.precheck_disk("spark-x2.5-1.7b", tmp_path)
    assert ok is True
    assert msg == "ok"


def test_precheck_disk_insufficient(tmp_path, monkeypatch):
    monkeypatch.setattr(mm.shutil, "disk_usage",
                        lambda p: type("U", (), {"free": 10**9})())  # 1GB
    ok, msg = mm.precheck_disk("spark-x2.5-1.7b", tmp_path)
    assert ok is False
    assert "GB" in msg
    assert "spark-x2.5-1.7b" in msg


# ------------------------------------------ 9. 默认地址（内置实例优先）
def _fake_rt(state: str, base_url: str = ""):
    return type("RT", (), {"state": state, "base_url": base_url})()


def test_default_base_url_prefers_runtime(monkeypatch):
    monkeypatch.setattr(mm, "get_runtime", lambda: _fake_rt("ready", "http://127.0.0.1:5555"))
    assert mm._default_base_url() == "http://127.0.0.1:5555"
    monkeypatch.setattr(mm, "get_runtime", lambda: _fake_rt("stopped", ""))
    assert mm._default_base_url() == OLLAMA_BASE
    monkeypatch.setattr(mm, "get_runtime", lambda: _fake_rt("ready", ""))
    assert mm._default_base_url() == OLLAMA_BASE


# ------------------------------------------- 10. 预检失败 → PullError
def test_pull_precheck_failure(monkeypatch):
    monkeypatch.setattr(mm, "precheck_disk", lambda m, p=None: (False, "磁盘不足"))
    with pytest.raises(mm.PullError) as ei:
        mm.pull_model("qwen2.5:3b")
    assert "磁盘不足" in str(ei.value)


# ---------------------------------------- 11. 默认地址走内置/兜底
def test_pull_uses_default_base_url(monkeypatch):
    monkeypatch.setattr(mm, "get_runtime", lambda: _fake_rt("stopped", ""))
    cap = _fake_urlopen(monkeypatch, _lines({"status": "success"}))
    _set_disk_ok(monkeypatch)
    mm.pull_model("qwen2.5:3b")  # 不传 base_url → 兜底默认地址
    assert cap["req"].full_url == f"{OLLAMA_BASE}/api/pull"


# -------------------------------------------- 12. 未知异常包装（零终端）
def test_pull_wraps_unknown_exception(monkeypatch):
    _fake_urlopen(monkeypatch, [], raise_exc=RuntimeError("segfault at 0xdeadbeef /api/x"))
    _set_disk_ok(monkeypatch)
    with pytest.raises(mm.PullError) as ei:
        mm.pull_model("qwen2.5:3b")
    msg = str(ei.value)
    for word in ["http", "ollama", "segfault", "0x", "安装"]:
        assert word not in msg, f"文案含禁词 {word!r}: {msg}"
