# SPDX-License-Identifier: GPL-3.0-only
"""resources/bin 打包资源冒烟测试（T-315）：全 stat 断言，零进程 / 零网络。

llama.cpp b10818 官方 macOS arm64 每日构建已入包（架构师直营，内容只读）：
llama-server 薄壳 + 10 个 lib*.dylib 实体 + @rpath 引用 symlink（git 原生
symlink 模式 120000）+ ggml-metal-tuning + LICENSE-llama.cpp.txt。

铁律：禁真起 llama-server 进程（只 stat / os.access / resolve）；禁网络。
非 macOS 环境 dylib 层测试 skip（本机 macOS 必跑）。
"""
from __future__ import annotations

import os
import ssl
import urllib.error
from pathlib import Path

import pytest

import acouscope.ai.llama_models as lm
from acouscope.ai.llama_models import (
    LlamaModelError,
    ModelInfo,
    _build_opener,
    _is_ssl_cert_error,
    download_model,
)
from acouscope.ai.llama_runtime import find_llama_binary

BIN_DIR = Path(__file__).resolve().parents[1] / "src" / "acouscope" / "resources" / "bin"

# 11 个 @rpath 依赖名（llama-server 薄壳的完整 dylib 闭包）
_RPATH_DEPS = (
    "libggml.0.dylib",
    "libggml-base.0.dylib",
    "libggml-blas.0.dylib",
    "libggml-cpu.0.dylib",
    "libggml-metal.0.dylib",
    "libggml-rpc.0.dylib",
    "libllama.0.dylib",
    "libllama-common.0.dylib",
    "libllama-server-impl.dylib",
    "libmtmd.0.dylib",
    "libggml.dylib",  # 额外 symlink 层（→ libggml.0.dylib）
)

# 实测（2026-09-06 b10818）：libggml / libggml-blas 为薄壳 stub 实体
# （60128 / 58776 字节），低于任务书预设的 100KB 阈值 → 单独降档断言
# （>10KB），deviations 已如实上报；其余 9 个均 >100KB。
_STUB_DEPS = ("libggml.0.dylib", "libggml-blas.0.dylib", "libggml.dylib")


def _real_size(name: str) -> int:
    """依赖名 → resolve 后实体的字节数（symlink 不直接 stat）。"""
    p = BIN_DIR / name
    resolved = p.resolve()
    return resolved.stat().st_size


def test_binary_present():
    """llama-server 薄壳：存在、可执行、>10KB。"""
    bin_path = BIN_DIR / "llama-server"
    assert bin_path.is_file(), f"缺内置引擎：{bin_path.name}"
    assert os.access(bin_path, os.X_OK), "llama-server 无执行权限"
    assert bin_path.stat().st_size > 10 * 1024, "llama-server 体积异常（<10KB）"


@pytest.mark.skipif(not (BIN_DIR / "llama-server").is_file(),
                    reason="resources/bin 未随包分发（非 macOS 构建环境）")
def test_dylib_closure():
    """11 个 @rpath 依赖名逐一存在、可 resolve 到实体、实体体积达标。"""
    for name in _RPATH_DEPS:
        p = BIN_DIR / name
        assert p.exists(), f"缺 @rpath 依赖：{name}"
        resolved = p.resolve()
        assert resolved.is_file(), f"依赖 resolve 后非实体文件：{name}"
        size = resolved.stat().st_size
        threshold = 10 * 1024 if name in _STUB_DEPS else 100 * 1024
        assert size > threshold, (
            f"依赖实体体积异常：{name} resolved={resolved.name} "
            f"size={size} <= {threshold}")
    # symlink 层健全：libggml.dylib 至少 resolve 一层后指向不同实体名
    assert (BIN_DIR / "libggml.dylib").resolve().name == \
        "libggml.0.23.0.dylib"


def test_license_present():
    """LICENSE-llama.cpp.txt 存在且含 MIT 授权标识。"""
    lic = BIN_DIR / "LICENSE-llama.cpp.txt"
    assert lic.is_file(), "缺 LICENSE-llama.cpp.txt"
    assert "MIT" in lic.read_text(encoding="utf-8"), "LICENSE 不含 MIT 标识"


def test_find_llama_binary_finds_bundle(monkeypatch):
    """env 清空后 find_llama_binary 命中 bundled 路径且为真实文件。"""
    monkeypatch.delenv("ACOUSECOPE_LLAMA_BIN", raising=False)
    found = find_llama_binary()
    assert found is not None, "未找到内置引擎二进制"
    r = Path(found)
    assert r.is_file()
    assert r == BIN_DIR / "llama-server"


def test_certifi_opener_used(monkeypatch):
    """_build_opener 传入 certifi.where() 作 CA；certifi 异常时仍可用。"""
    # 1) 正常路径：ssl.create_default_context 收到 certifi.where() 的 cafile
    cafile_seen: list = []
    real_where = lm.certifi.where

    def _fake_where():
        p = real_where()
        cafile_seen.append(p)
        return p

    def _fake_ctx(cafile=None):
        assert cafile in cafile_seen, "cafile 参数未来自 certifi.where()"
        return "FAKE-CONTEXT"

    monkeypatch.setattr(lm.certifi, "where", _fake_where)
    monkeypatch.setattr(lm.ssl, "create_default_context", _fake_ctx)
    op = _build_opener()
    assert cafile_seen, "certifi.where() 未被调用"
    assert cafile_seen[0] == real_where(), "cafile 参数与 certifi.where() 不一致"
    handlers = [h for h in op.handlers
                if isinstance(h, urllib.request.HTTPSHandler)]
    assert handlers, "opener 未挂 HTTPSHandler"
    # HTTPSHandler 将 ctx 存于 _context（私有属性，测试专用）
    assert getattr(handlers[0], "_context", None) == "FAKE-CONTEXT"

    # 2) 容错路径：certifi.where 抛异常 → 回退默认 opener（仍可构造）
    monkeypatch.setattr(lm.certifi, "where",
                        lambda: (_ for _ in ()).throw(OSError("no cert")))
    op2 = _build_opener()
    assert op2 is not None


def _ssl_cert_exc() -> urllib.error.URLError:
    """构造真实 ssl.SSLCertVerificationError 包裹的 URLError（零网络）。"""
    try:
        raise ssl.SSLCertVerificationError(
            "[SSL: CERTIFICATE_VERIFY_FAILED] "
            "certificate verify failed (_ssl.c:1006)")
    except ssl.SSLCertVerificationError as e:
        return urllib.error.URLError(e)


def test_ssl_error_reason_propagates(monkeypatch, tmp_path):
    """证书失败 → 全败文案透出证书类中文 reason（零终端）；判定器口径。"""
    # 判定器：直抛 / URLError 包裹 / 普通网络错误 三形态
    assert _is_ssl_cert_error(_ssl_cert_exc()) is True
    assert _is_ssl_cert_error(
        ssl.SSLCertVerificationError("certificate verify failed")) is True
    assert _is_ssl_cert_error(urllib.error.URLError("Connection refused")) \
        is False

    class _FakeOpener:
        def open(self, req, timeout=None):
            raise _ssl_cert_exc()

    # _build_opener 打桩（契约 B.6 口径：fake opener 抛证书错误）
    monkeypatch.setattr(lm, "_build_opener", lambda: _FakeOpener())

    body = b"GGUF" + b"\x00" * 28  # 魔数占位（下载失败不会走到校验）
    dead = ModelInfo(model_id="ssl-test", display_name="t",
                     filename="ssl-test.gguf",
                     urls=("https://unreachable.invalid/a.gguf",),
                     est_bytes=len(body), sha256=None)
    monkeypatch.setattr(lm, "GGUF_MODELS", (dead,))

    def _mdir():
        d = tmp_path / "mdl"
        d.mkdir(parents=True, exist_ok=True)
        return d

    monkeypatch.setattr(lm, "models_dir", _mdir)

    with pytest.raises(LlamaModelError) as ei:
        download_model("ssl-test")
    msg = str(ei.value)
    assert "证书" in msg, msg
    # 零终端：不得出现命令行工具名 / 路径 / URL 细节
    low = msg.lower()
    assert "ssl" not in low, msg
    assert "curl" not in low, msg
    assert "://" not in msg, msg
    assert "/Users" not in msg and "/Library" not in msg, msg


def test_no_terminal_in_new_code():
    """本任务改动文件新增行无终端词。

    口径（契约 B.7）：llama_models.py / test_llama_runtime.py 为已跟踪
    文件 → 只查相对 backup 提交（HEAD）的 diff 新增行（既有 _hf_urls
    常量区 URL 及模块 docstring 既有“零终端”说明均不计）；新测试文件
    全部行皆为新增 → 直接扫描（仅豁免禁词表字面量定义行）。
    """
    import re
    import subprocess
    root = Path(__file__).resolve().parents[2]
    pattern = re.compile(
        r"curl|wget|openssl|\bsecurity\b|huggingface\.co", re.IGNORECASE)
    # 1) 已跟踪文件：只看 diff 新增行
    for rel in ("src/acouscope/ai/llama_models.py",
                "tests/test_llama_runtime.py"):
        diff = subprocess.run(
            ["git", "diff", "HEAD", "--", rel], cwd=root,
            capture_output=True, text=True, check=True).stdout
        for line in diff.splitlines():
            if not line.startswith("+") or line.startswith("+++"):
                continue
            body = line[1:]
            m = pattern.search(body)
            assert m is None, f"{rel} 新增行命中终端词: {body.strip()}"
    # 2) 本测试文件（未跟踪，全部行即新增）：直接扫描
    me = Path(__file__).resolve()
    quoted = re.compile(
        r'"(?:' + pattern.pattern + r')"', re.IGNORECASE)
    for i, line in enumerate(me.read_text(encoding="utf-8").splitlines(), 1):
        if pattern.pattern in line:  # 禁词表字面量构造/定义行豁免
            continue
        if quoted.search(line):  # 断言行以引号字面量引用禁词（测试目标本身）
            continue
        m = pattern.search(line)
        assert m is None, f"test_llama_binary_bundle.py:{i}: {line.strip()}"
