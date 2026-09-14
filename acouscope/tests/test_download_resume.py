# SPDX-License-Identifier: GPL-3.0-only
"""T-1023：模型下载器「短读检测 + 有限次自动续传」单测（全打桩，零网络）。

打桩方式：monkeypatch `llama_models._build_opener` 返回脚本化 opener，其
`open()` 按预设计划依次返回**伪响应对象**（或抛异常），全程不建 socket、
不发起任何真实请求、不下载任何真实模型文件。

覆盖（对应 T-1023 交付 §1/§2/§3 与测试清单）：
- 200 全量一次成功（进度单调、终值 1.0）；
- 206 续传一次成功（预置 .part，断言 Range 头）；
- **核心**：中途截断一次 → 自动续传成功（断言发生续传请求 + 最终 sha 通过）；
- 连续截断达上限 → LlamaModelError（文案含「重试」）+ .part 保留、无 .bad；
- 无 Content-Length（分块）→ sha 兜底、不误判；
- 取消即时生效（退避期间即刻 CancelledError）、进度回调单调不回退；
- 镜像回退顺序不变（连接层失败不占用续传重试预算）。
"""
from __future__ import annotations

import hashlib
import urllib.error

import pytest

import acouscope.ai.llama_models as lm
from acouscope.ai.interpreter import CancelledError
from acouscope.ai.llama_models import LlamaModelError, ModelInfo, download_model

TEST_ID = "test-model"
NAME = "test-model.gguf"
URL_A = "http://stub.invalid/a/test-model.gguf"
URL_B = "http://stub.invalid/b/test-model.gguf"


class _FakeHeaders:
    """伪响应头：只支持 Content-Length（缺失 → get 返回 default）。"""

    def __init__(self, content_length: int | None):
        self._cl = content_length

    def get(self, key, default=None):
        if key.lower() == "content-length" and self._cl is not None:
            return str(self._cl)
        return default


class _FakeResponse:
    """伪流式响应：按 Content-Length 声明长度，但只投递 `data` 实有字节。

    `data` 短于声明长度 = 服务器提前关流（T-1023 根因场景：短读）。
    """

    def __init__(self, code: int, data: bytes,
                 content_length: int | None = None,
                 on_eof=None):
        self._code = code
        self._data = data
        self._pos = 0
        self._on_eof = on_eof
        self.headers = _FakeHeaders(content_length)
        self.closed = False

    def getcode(self) -> int:
        return self._code

    def read(self, n: int = -1) -> bytes:
        if self._pos >= len(self._data):
            if self._on_eof is not None:
                hook, self._on_eof = self._on_eof, None
                hook()
            return b""
        if n is None or n < 0:
            chunk = self._data[self._pos:]
            self._pos = len(self._data)
            return chunk
        chunk = self._data[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False


class _ScriptedOpener:
    """脚本化 opener：open() 依次消费计划项（响应工厂 / 待抛异常）。

    工厂签名为 `f(req) -> _FakeResponse`，便于在工厂内断言 Range 头。
    """

    def __init__(self, plans):
        self._plans = list(plans)
        self.requests: list = []

    def open(self, req, timeout=60):
        self.requests.append(req)
        if not self._plans:
            raise AssertionError(f"未预期的多余请求：{req.full_url}")
        plan = self._plans.pop(0)
        if isinstance(plan, BaseException):
            raise plan
        return plan(req)


def _range_of(req) -> str | None:
    return req.get_header("Range")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """models_dir → tmp 沙盒；GGUF_MODELS → 单条打桩条目；退避 → 0（免等待）。"""
    models_dir = tmp_path / "models"

    def _mdir():
        models_dir.mkdir(parents=True, exist_ok=True)
        return models_dir

    body = b"GGUF" + bytes(range(256)) * 4  # 1028B，魔数正确
    monkeypatch.setattr(lm, "models_dir", _mdir)
    monkeypatch.setattr(lm, "_RESUME_BACKOFF_S", (0.0,))  # 退避不真等
    info = ModelInfo(
        model_id=TEST_ID,
        display_name="Test Model",
        filename=NAME,
        urls=(URL_A,),
        est_bytes=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
    )
    monkeypatch.setattr(lm, "GGUF_MODELS", (info,))
    return {"dir": models_dir, "body": body, "info": info, "urls": (URL_A,)}


def _install(monkeypatch, opener, urls=(URL_A,), body=b"", sha256=None,
             est_bytes=None):
    """替换 opener 与目录条目（多镜像 / 变体场景用）。"""
    info = ModelInfo(
        model_id=TEST_ID,
        display_name="Test Model",
        filename=NAME,
        urls=tuple(urls),
        est_bytes=len(body) if est_bytes is None else est_bytes,
        sha256=sha256,
    )
    monkeypatch.setattr(lm, "GGUF_MODELS", (info,))
    monkeypatch.setattr(lm, "_build_opener", lambda: opener)
    return info


def _target(env):
    return env["dir"] / NAME


def _part(env):
    return _target(env).with_suffix(".gguf.part")


def _bad(env):
    return _target(env).with_suffix(".gguf.bad")


def test_full_200_success_progress_monotonic(env, monkeypatch):
    """200 全量：一次请求成功、进度单调、终值 1.0、.part 原子改名。"""
    body = env["body"]
    opener = _ScriptedOpener([
        lambda req: _FakeResponse(200, body, content_length=len(body)),
    ])
    _install(monkeypatch, opener, body=body,
             sha256=env["info"].sha256)

    progresses: list[float] = []
    ret = download_model(TEST_ID, on_progress=progresses.append)

    assert ret == _target(env)
    assert _target(env).read_bytes() == body
    assert not _part(env).exists()
    assert len(opener.requests) == 1
    assert _range_of(opener.requests[0]) is None, "全量首请求不应带 Range"
    assert progresses and progresses[-1] == 1.0
    assert all(b >= a for a, b in zip(progresses, progresses[1:]))


def test_resume_206_success(env, monkeypatch):
    """206 续传：预置 .part 半量 → 带 Range 续传成功。"""
    body = env["body"]
    half = len(body) // 2
    _part(env).parent.mkdir(parents=True, exist_ok=True)
    _part(env).write_bytes(body[:half])

    def _resp(req):
        assert _range_of(req) == f"bytes={half}-"
        return _FakeResponse(206, body[half:], content_length=len(body) - half)

    opener = _ScriptedOpener([_resp])
    _install(monkeypatch, opener, body=body, sha256=env["info"].sha256)

    ret = download_model(TEST_ID)
    assert ret == _target(env)
    assert _target(env).read_bytes() == body
    assert not _part(env).exists()
    assert len(opener.requests) == 1


def test_truncated_then_resume_succeeds(env, monkeypatch):
    """核心用例：流被截断一次 → 自动续传请求 → 最终 sha256 通过。

    修前行为：截断被当作「下载完成」→ sha256 失败 → .part 改名 .bad 报错；
    修后行为：短读被检测 → 保留 .part → Range 续传 → 成功入档。
    """
    body = env["body"]
    cut = 400  # 第 1 次只投递前 400B，却声明 len(body)

    def _first(req):
        assert _range_of(req) is None
        return _FakeResponse(200, body[:cut], content_length=len(body))

    def _second(req):
        assert _range_of(req) == f"bytes={cut}-", "续传必须按已下字节数发 Range"
        return _FakeResponse(206, body[cut:], content_length=len(body) - cut)

    opener = _ScriptedOpener([_first, _second])
    _install(monkeypatch, opener, body=body, sha256=env["info"].sha256)

    progresses: list[float] = []
    ret = download_model(TEST_ID, on_progress=progresses.append)

    assert len(opener.requests) == 2, "截断后应发生一次自动续传请求"
    assert ret == _target(env)
    assert _target(env).read_bytes() == body          # 与打桩真值逐字节一致
    assert hashlib.sha256(_target(env).read_bytes()).hexdigest() \
        == env["info"].sha256                          # sha256 通过
    assert not _part(env).exists()
    assert not _bad(env).exists(), "续传成功不得产生 .bad"
    assert progresses and progresses[-1] == 1.0
    assert all(b >= a for a, b in zip(progresses, progresses[1:])), progresses


def test_truncation_exhausts_retries_keeps_part(env, monkeypatch):
    """连续截断达上限 → LlamaModelError（含「重试」）+ .part 保留、无 .bad。"""
    body = env["body"]
    cut = 400
    plans = [
        (lambda req: _FakeResponse(200, body[:cut], content_length=len(body)))
        for _ in range(1 + lm._MAX_RESUME_RETRIES)  # 首投 + 上限次续传
    ]
    opener = _ScriptedOpener(plans)
    _install(monkeypatch, opener, body=body, sha256=env["info"].sha256)

    with pytest.raises(LlamaModelError) as ei:
        download_model(TEST_ID)

    msg = str(ei.value)
    assert "重试" in msg, msg
    assert "://" not in msg and "curl" not in msg.lower()
    assert len(opener.requests) == 1 + lm._MAX_RESUME_RETRIES, \
        "重试次数必须恰好等于上限（不得无限重试）"
    assert not _target(env).exists()
    assert not _bad(env).exists(), "未完成的 .part 不得被改名 .bad"
    assert _part(env).exists() and _part(env).stat().st_size == cut, \
        ".part 应保留供用户重试继续续传"
    # 续传确实按 Range 语义发出（第 2 次起）
    ranges = [_range_of(r) for r in opener.requests]
    assert ranges[0] is None and ranges[1:] == [f"bytes={cut}-"] * 3, ranges


def test_no_content_length_full_stream_succeeds(env, monkeypatch):
    """无 Content-Length（分块）但流完整 → 不得误判为短读。"""
    body = env["body"]
    opener = _ScriptedOpener([
        lambda req: _FakeResponse(200, body, content_length=None),
    ])
    _install(monkeypatch, opener, body=body, sha256=env["info"].sha256)

    ret = download_model(TEST_ID)
    assert ret == _target(env)
    assert _target(env).read_bytes() == body
    assert not _bad(env).exists()


def test_no_content_length_truncated_falls_to_sha256(env, monkeypatch):
    """无 Content-Length 且流被截断 → 不做短读判定，以 sha256 兜底（报错）。"""
    body = env["body"]
    opener = _ScriptedOpener([
        lambda req: _FakeResponse(200, body[:400], content_length=None),
    ])
    _install(monkeypatch, opener, body=body, sha256=env["info"].sha256)

    with pytest.raises(LlamaModelError) as ei:
        download_model(TEST_ID)
    assert "校验失败" in str(ei.value)
    assert not _target(env).exists(), "坏文件绝不入档"
    assert len(opener.requests) == 1, "无长度信息时不得当成短读去重试"


def test_cancel_during_backoff_is_immediate(env, monkeypatch):
    """退避期间取消 → 立即 CancelledError（不再发第二次请求）、.part 保留。"""
    body = env["body"]
    state = {"cancelled": False}
    cut = 400

    def _mark(_req):
        # 流读尽（截断点）后置取消标记 → 退避阶段应即时生效
        return _FakeResponse(200, body[:cut], content_length=len(body),
                             on_eof=lambda: state.update(cancelled=True))

    opener = _ScriptedOpener([_mark])
    _install(monkeypatch, opener, body=body, sha256=env["info"].sha256)

    with pytest.raises(CancelledError):
        download_model(TEST_ID, is_cancelled=lambda: state["cancelled"])

    assert len(opener.requests) == 1, "取消后不得再发续传请求"
    assert not _target(env).exists()
    assert _part(env).exists() and _part(env).stat().st_size == cut


def test_progress_never_regresses_on_rewrite(env, monkeypatch):
    """服务端忽略 Range 全量重发（200 重写）→ 进度回调不得回退。"""
    body = env["body"]
    cut = 400

    def _first(req):
        return _FakeResponse(200, body[:cut], content_length=len(body))

    def _second(req):
        # 忽略 Range：仍回 200 全量，但只投递完整 body（重写从头开始）
        assert _range_of(req) == f"bytes={cut}-"
        return _FakeResponse(200, body, content_length=len(body))

    opener = _ScriptedOpener([_first, _second])
    _install(monkeypatch, opener, body=body, sha256=env["info"].sha256)

    progresses: list[float] = []
    download_model(TEST_ID, on_progress=progresses.append)
    assert progresses and progresses[-1] == 1.0
    assert all(b >= a for a, b in zip(progresses, progresses[1:])), progresses


def test_mirror_fallback_order_unchanged(env, monkeypatch):
    """连接层失败（404）→ 立即顺序回退下一镜像（不占用续传重试预算）。"""
    body = env["body"]
    err = urllib.error.HTTPError(URL_A, 404, "Not Found", {}, None)

    def _ok(req):
        assert req.full_url == URL_B
        return _FakeResponse(200, body, content_length=len(body))

    opener = _ScriptedOpener([err, _ok])
    _install(monkeypatch, opener, urls=(URL_A, URL_B), body=body,
             sha256=env["info"].sha256)

    ret = download_model(TEST_ID)
    assert ret == _target(env)
    assert [r.full_url for r in opener.requests] == [URL_A, URL_B]
    assert _target(env).read_bytes() == body


def test_unreachable_source_no_retry_falls_back(env, monkeypatch):
    """源不可达（连接层）→ 沿用镜像回退语义：不重试、立即换源（零终端文案）。"""
    body = env["body"]
    opener = _ScriptedOpener([
        urllib.error.URLError("connection refused"),
    ])
    _install(monkeypatch, opener, body=body, sha256=env["info"].sha256)

    with pytest.raises(LlamaModelError) as ei:
        download_model(TEST_ID)
    msg = str(ei.value)
    assert "模型源暂时不可用" in msg
    assert "://" not in msg and "curl" not in msg.lower()
    assert len(opener.requests) == 1, "连接层失败不得占用续传重试预算"
