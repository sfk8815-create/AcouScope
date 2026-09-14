# SPDX-License-Identifier: GPL-3.0-only
"""llama_models 单测（T-313）：全本地 ThreadingHTTPServer mock，零外网。

所有下载指向 127.0.0.1 随机端口的本地 server（fixture 内起停，daemon 线程）；
models_dir / GGUF_MODELS 均 monkeypatch 到 tmp 路径。handler 支持 200 全量、
206 Range（Content-Range + 剩余字节）、可注入 HTML 错误页。
"""
from __future__ import annotations

import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import acouscope.ai.llama_models as lm
from acouscope.ai.interpreter import CancelledError
from acouscope.ai.llama_models import (
    GGUF_MODELS,
    LlamaModelError,
    ModelInfo,
    download_model,
    get_model_info,
    is_model_ready,
    list_models,
    model_path,
    precheck_disk,
    verify_file,
)

TEST_ID = "test-model"


def _make_info(base: str, est_bytes: int, sha256: str | None) -> ModelInfo:
    return ModelInfo(
        model_id=TEST_ID,
        display_name="Test Model",
        filename="test-model.gguf",
        urls=(f"{base}/test-model.gguf",),
        est_bytes=est_bytes,
        sha256=sha256,
    )


class _MockHandler(BaseHTTPRequestHandler):
    """本地 mock：支持 200 全量 / 206 Range / 注入 404+HTML 错误页。

    状态挂在 server 实例上（每 fixture 一份）：
    - server.store: path -> bytes
    - server.requests: [(path, headers-dict), ...]
    - server.fail_mode: "off" | "html"
    - server.force_416: 异常场景注入——收到 Range 请求一律回 416
      （模拟 .part 未完成时服务端 Range 不可满足，仅测试用，默认 False）
    """

    def log_message(self, *args):  # 静默
        pass

    def do_GET(self):
        srv = self.server
        path = self.path
        headers = {k: v for k, v in self.headers.items()}
        srv.requests.append((path, headers))
        if srv.fail_mode == "html":
            # 代理/镜像以 200 返回 HTML 鉴权/404 错误页（Experience 454351 真实场景）
            body = b"<html><body>404 Not Found</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if srv.fail_mode == "404":
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        data = srv.store.get(path)
        if data is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        rng = self.headers.get("Range")
        if rng:
            if getattr(srv, "force_416", False):
                # 异常场景：.part 未完成却回 416（换镜像语义防御，T-315b-fix）
                self.send_response(416)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            try:
                # 只实现 bytes=N-（起始位 ~ 末尾）
                start = int(rng.split("=", 1)[1].split("-", 1)[0])
            except (ValueError, IndexError):
                start = 0
            if start >= len(data):
                self.send_response(416)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = data[start:]
            self.send_response(206)
            self.send_header(
                "Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def local_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _MockHandler)
    srv.store = {}
    srv.requests = []
    srv.fail_mode = "off"
    srv.force_416 = False
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def patched(tmp_path, monkeypatch, local_server):
    """models_dir→tmp 沙盒；GGUF_MODELS→单条指向本地 server 的 ModelInfo。"""
    models_dir = tmp_path / "models"

    def _mdir():  # 对齐真实 models_dir 语义：自动 mkdir
        models_dir.mkdir(parents=True, exist_ok=True)
        return models_dir

    monkeypatch.setattr(lm, "models_dir", _mdir)
    base = f"http://127.0.0.1:{local_server.server_address[1]}"
    body = b"GGUF" + bytes(range(256)) * 1024  # 256KB，魔数正确
    local_server.store["/test-model.gguf"] = body
    info = _make_info(base, est_bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
    monkeypatch.setattr(lm, "GGUF_MODELS", (info,))
    return {"dir": models_dir, "base": base, "body": body, "info": info,
            "srv": local_server}


def test_catalog_shape():
    """契约 A.3 形状断言（真实目录，非 mock）。

    T-1022 归因（非静默）：目录整体替换——纯文本 Instruct 档（1.5B/3B）已下架，
    现目录只上**视觉**模型（Qwen2.5-VL 3B/7B，含 mmproj 视觉塔）。原「1.5b/3b
    instruct 必须在目录内」的断言已失效，改写为等价强度的新契约：视觉模型必须
    在目录内、每条带 vision=True、含 mmproj 双文件、体积为两文件之和。
    """
    assert len(GGUF_MODELS) >= 2
    for m in GGUF_MODELS:
        assert any("huggingface.co" in u for u in m.urls)
        assert any("hf-mirror.com" in u for u in m.urls)
        assert m.urls.index(
            next(u for u in m.urls if "huggingface.co" in u)) < m.urls.index(
            next(u for u in m.urls if "hf-mirror.com" in u))
        assert m.filename.endswith(".gguf")
        assert m.est_bytes > 1e8
        assert m.model_id
        assert m.display_name
        assert m.vision is True                      # 硬门禁依据
        assert m.mmproj is not None                  # 视觉塔（可读图）
        assert m.mmproj.filename.endswith(".gguf")
        assert m.mmproj.role == "mmproj"
        files = m.files
        assert [f.role for f in files] == ["weights", "mmproj"]
        assert sum(f.size for f in files) == m.est_bytes
        assert files[0].filename == m.filename and files[0].sha256 == m.sha256
    assert get_model_info(GGUF_MODELS[0].model_id) is GGUF_MODELS[0]
    assert "qwen2.5-vl-3b-instruct-q4_k_m" in [m.model_id for m in GGUF_MODELS]
    assert "qwen2.5-vl-7b-instruct-q4_k_m" in [m.model_id for m in GGUF_MODELS]
    # 纯文本档已下架（T-1022）：不得再出现在目录内
    ids = [m.model_id for m in GGUF_MODELS]
    assert "qwen2.5-1.5b-instruct-q4_k_m" not in ids
    assert "qwen2.5-3b-instruct-q4_k_m" not in ids
    with pytest.raises(LlamaModelError):
        get_model_info("no-such-model")
    assert len(list_models()) >= 2


def test_magic_verify_ok_bad(tmp_path):
    good = tmp_path / "good.gguf"
    good.write_bytes(b"GGUF" + b"\x00" * 32)
    ok, msg = verify_file(good, None)
    assert ok is True and msg == "ok"
    bad = tmp_path / "bad.gguf"
    bad.write_bytes(b"<html><body>404</body></html>")
    ok2, msg2 = verify_file(bad, None)
    assert ok2 is False
    assert "://" not in msg2
    assert "curl" not in msg2 and "wget" not in msg2 and "pip" not in msg2


def test_download_full_and_progress(patched):
    target = patched["dir"] / "test-model.gguf"
    progresses: list[float] = []
    ret = download_model(TEST_ID, on_progress=lambda p: progresses.append(p))
    assert ret == target and target.exists()
    assert target.read_bytes() == patched["body"]
    assert progresses and progresses[-1] == 1.0
    assert all(b >= a for a, b in zip(progresses, progresses[1:]))
    assert all(0.0 <= p <= 1.0 for p in progresses)


def test_resume_range(patched):
    srv, body = patched["srv"], patched["body"]
    target = patched["dir"] / "test-model.gguf"
    part = target.with_suffix(target.suffix + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    preseed = body[: len(body) // 2]
    part.write_bytes(preseed)  # 预置前半
    download_model(TEST_ID)
    got = [h for p, h in srv.requests if p == "/test-model.gguf"]
    assert got, "server 未收到请求"
    assert any(h.get("Range", "") == f"bytes={len(preseed)}-"
               for h in got), f"Range 头缺失: {got}"
    assert target.read_bytes() == body
    assert not part.exists()


def test_cancel_keeps_part(patched):
    target = patched["dir"] / "test-model.gguf"
    part = target.with_suffix(target.suffix + ".part")
    calls = {"n": 0}

    def cancelled():
        calls["n"] += 1
        return calls["n"] >= 2  # 第 2 次调用返回 True

    with pytest.raises(CancelledError):
        download_model(TEST_ID, is_cancelled=cancelled)
    assert not target.exists()
    assert part.exists() and part.stat().st_size > 0


def test_mirror_fallback(patched, monkeypatch):
    srv = patched["srv"]
    good_sha = hashlib.sha256(patched["body"]).hexdigest()
    # 第一条 url 指向不可达端口，第二条指向本地 server → 回退成功
    info = ModelInfo(
        model_id=TEST_ID, display_name="Test Model", filename="test-model.gguf",
        urls=("http://127.0.0.1:1/test-model.gguf",
              patched["base"] + "/test-model.gguf"),
        est_bytes=len(patched["body"]), sha256=good_sha)
    monkeypatch.setattr(lm, "GGUF_MODELS", (info,))
    target = download_model(TEST_ID)
    assert target.exists()
    assert target.read_bytes() == patched["body"]
    assert any(p == "/test-model.gguf" for p, _ in srv.requests)


def test_bad_magic_renamed_bad(patched):
    target = patched["dir"] / "test-model.gguf"
    bad = target.with_suffix(target.suffix + ".bad")
    srv = patched["srv"]
    srv.fail_mode = "html"  # 404 + HTML 错误页
    with pytest.raises(LlamaModelError) as ei:
        download_model(TEST_ID)
    assert "://" not in str(ei.value)
    assert not target.exists()
    assert bad.exists()
    assert bad.read_bytes().startswith(b"<html")


def test_sha256_mismatch_fails(patched, monkeypatch):
    body = patched["body"]
    target = patched["dir"] / "test-model.gguf"
    bad = target.with_suffix(target.suffix + ".bad")

    # 故意写错 sha256 → 失败 + .bad 保留
    wrong = _make_info(patched["base"], len(body), sha256="0" * 64)
    monkeypatch.setattr(lm, "GGUF_MODELS", (wrong,))
    with pytest.raises(LlamaModelError) as ei:
        download_model(TEST_ID)
    assert "://" not in str(ei.value)
    assert not target.exists()
    assert bad.exists()

    # 正确 sha256（hashlib 实算）→ 成功
    bad.unlink()
    right = _make_info(patched["base"], len(body),
                       sha256=hashlib.sha256(body).hexdigest())
    monkeypatch.setattr(lm, "GGUF_MODELS", (right,))
    ret = download_model(TEST_ID)
    assert ret == target and target.read_bytes() == body
    assert not bad.exists()


def test_precheck_disk_insufficient(patched, monkeypatch):
    class _U:
        total = 10 << 30
        used = (10 << 30) - 100
        free = 100  # 极小

    monkeypatch.setattr(lm.shutil, "disk_usage", lambda p: _U())
    with pytest.raises(LlamaModelError) as ei:
        download_model(TEST_ID)
    msg = str(ei.value)
    assert "磁盘" in msg and "GB" in msg
    assert "://" not in msg

    # 直接调 precheck_disk 亦失败
    ok, m2 = precheck_disk(patched["info"])
    assert ok is False and "磁盘" in m2


def test_is_model_ready_and_idempotent(patched):
    assert not is_model_ready(TEST_ID)
    ret1 = download_model(TEST_ID)
    assert is_model_ready(TEST_ID) is True
    assert ret1 == model_path(TEST_ID)
    n_req = len(patched["srv"].requests)
    assert n_req >= 1
    ret2 = download_model(TEST_ID)  # 幂等：零网络
    assert ret2 == ret1
    assert len(patched["srv"].requests) == n_req


def test_messages_zero_terminal(patched, monkeypatch, tmp_path):
    """枚举各失败路径的 LlamaModelError 消息：零终端铁律。"""
    body = patched["body"]

    def _collect(msg):
        s = str(msg)
        assert "://" not in s, s
        assert "curl" not in s.lower(), s
        assert "wget" not in s.lower(), s
        assert "pip " not in s.lower(), s

    # 1) 未知模型 id
    with pytest.raises(LlamaModelError) as e1:
        get_model_info("no-such")
    _collect(e1.value)

    # 2) 全部镜像不可达
    dead = ModelInfo(model_id=TEST_ID, display_name="t",
                     filename="test-model.gguf",
                     urls=("http://127.0.0.1:1/a",),
                     est_bytes=len(body), sha256=None)
    monkeypatch.setattr(lm, "GGUF_MODELS", (dead,))
    with pytest.raises(LlamaModelError) as e2:
        download_model(TEST_ID)
    _collect(e2.value)

    # 3) 校验失败（HTML 错误页 → 魔数错）
    monkeypatch.setattr(lm, "GGUF_MODELS", (patched["info"],))
    patched["srv"].fail_mode = "html"
    with pytest.raises(LlamaModelError) as e3:
        download_model(TEST_ID)
    patched["srv"].fail_mode = "off"
    _collect(e3.value)

    # 4) 磁盘不足
    class _U:
        total = 1 << 30
        used = (1 << 30) - 10
        free = 10

    monkeypatch.setattr(lm.shutil, "disk_usage", lambda p: _U())
    with pytest.raises(LlamaModelError) as e4:
        download_model(TEST_ID)
    _collect(e4.value)

    # 5) verify_file 失败消息
    html_file = tmp_path / "err.gguf"
    html_file.write_bytes(b"<html><body>404</body></html>")
    ok, m_bad = verify_file(html_file, None)
    assert ok is False
    _collect(m_bad)

    sha_file = tmp_path / "sha.gguf"
    sha_file.write_bytes(b"GGUF" + b"x" * 16)
    ok2, m_sha = verify_file(sha_file, "0" * 64)
    assert ok2 is False
    _collect(m_sha)


def test_resume_complete_returns_true(patched):
    """T-315b-fix 契约 B.1：.part 已达完整大小（100% 前一刻中断）重试。

    Range: bytes=<est_bytes>- → 本地 fake server 如实回 416
    （Range Not Satisfiable）→ _download_from_url 不得判“源不可用”，
    返回 True（文件实际已完整，由上层 verify_file 正常校验 / 改名）。
    """
    srv, body = patched["srv"], patched["body"]
    target = patched["dir"] / "test-model.gguf"
    part = target.with_suffix(target.suffix + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(body)  # 预置 .part = 完整大小（est_bytes）
    ok = lm._download_from_url(patched["base"] + "/test-model.gguf",
                               part, len(body), len(body), None, None)
    assert ok is True, ".part 完整大小下 416 不得误判“源不可用”"
    # 请求确实以 Range: bytes=<总大小>- 发出（复现实证场景）
    got = [h for p, h in srv.requests if p == "/test-model.gguf"]
    assert any(h.get("Range", "") == f"bytes={len(body)}-" for h in got), got


def test_resume_partial_416_falls_back(patched):
    """T-315b-fix 契约 B.2：.part 未完成却收到 416（异常场景）→ 返回 False。

    换镜像回退语义保留：fake server 对 Range: bytes=<half>- 注入 416 →
    _download_from_url 返回 False（由 download_model 换下一镜像）。
    """
    srv, body = patched["srv"], patched["body"]
    target = patched["dir"] / "test-model.gguf"
    part = target.with_suffix(target.suffix + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    half = len(body) // 2
    part.write_bytes(body[:half])  # 预置 .part = 半量（< est_bytes）
    srv.force_416 = True  # 异常注入：Range 一律 416
    try:
        ok = lm._download_from_url(patched["base"] + "/test-model.gguf",
                                   part, half, len(body), None, None)
    finally:
        srv.force_416 = False
    assert ok is False, ".part 未完成的 416 应保留换镜像语义（返回 False）"


def test_download_model_resume_complete_both_sources_416(patched, monkeypatch):
    """T-315b-fix 契约 B.3（集成口径）：.part == est_bytes 且双源均 416。

    download_model 不得抛 LlamaModelError：首个 URL 即 416 → 视为完成 →
    走 verify_file 正常校验（魔数 + sha256 全过）→ .part 原子改名，
    用户重试自愈（不再误报“网络连接中断或模型源暂不可用”）。
    """
    srv, body = patched["srv"], patched["body"]
    target = patched["dir"] / "test-model.gguf"
    part = target.with_suffix(target.suffix + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(body)  # 预置 .part = 完整大小
    # 双源均指向本地 server（完整 Range 必然 416）→ 模拟双镜像同态
    two = ModelInfo(
        model_id=TEST_ID, display_name="Test Model", filename="test-model.gguf",
        urls=(patched["base"] + "/test-model.gguf",
              patched["base"] + "/test-model.gguf"),
        est_bytes=len(body),
        sha256=hashlib.sha256(body).hexdigest())
    monkeypatch.setattr(lm, "GGUF_MODELS", (two,))
    ret = download_model(TEST_ID)  # 不得抛 LlamaModelError
    assert ret == target and target.exists()
    assert target.read_bytes() == body
    assert not part.exists()
    # 仅首个 URL 命中 416 即视为完成（未耗尽双源）
    hits = [p for p, _ in srv.requests if p == "/test-model.gguf"]
    assert len(hits) == 1
