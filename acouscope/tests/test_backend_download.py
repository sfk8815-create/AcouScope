# SPDX-License-Identifier: GPL-3.0-only
"""T-1051 供应链守卫：权重运行时下载（域名 / 出仓规则 / 下载目标 / sha256 清理）。

纯测试追加（不改动任何既有用例）。覆盖（对应当令 D4）：
D4-1 静态：rmvpe.py 不含 `huggingface.io`，含 `huggingface.co`；
D4-2 静态：.gitignore 含 `models/*.onnx`（权重出仓 = 运行时下载）；
D4-3 行为：模型缺失时下载目标为用户数据目录（monkeypatch 断言目标路径，不真下载）；
D4-4 行为：sha256 不符 → 失败并清理临时文件（monkeypatch 上游响应）。

说明：ffmpeg（对应 D2）依 2026-09-12 指挥裁定「D2 挂起」——ffmpeg 仍留仓库且不新增
fetch_ffmpeg.sh，故本文件**不**含对 ffmpeg 出仓规则或 fetch 脚本的断言。
"""

import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = _ROOT / "src" / "acouscope"
_ROOT_GITIGNORE = _ROOT.parent / ".gitignore"

from acouscope.analysis.backends import rmvpe, swift_f0  # noqa: E402


# ---- D4-1 静态：供应链域名修正（huggingface.io → .co） ----

def test_rmvpe_url_domain_fixed():
    """`_RMVPE_URL` 不得含非官方 `huggingface.io`，必须含 `.co`。"""
    assert "huggingface.io" not in rmvpe._RMVPE_URL
    assert "huggingface.co" in rmvpe._RMVPE_URL


def test_rmvpe_file_has_no_dot_io_literal():
    """rmvpe.py 全文件不得出现 `huggingface.io` 字面（含注释）。"""
    text = (SRC / "analysis" / "backends" / "rmvpe.py").read_text("utf-8")
    assert "huggingface.io" not in text


def test_swift_f0_url_domain_unchanged():
    """swift_f0 上游为 GitHub Release（域名本就正确，无需改）。"""
    assert swift_f0._SWIFTF0_URL.startswith("https://github.com/")


# ---- D4-2 静态：.gitignore 权重出仓规则 ----

def test_gitignore_ignores_onnx_weights():
    """权重改为运行时下载 → .gitignore 必须存在 `models/*.onnx` 出仓规则。"""
    text = _ROOT_GITIGNORE.read_text("utf-8")
    assert "models/*.onnx" in text


# ---- D4-3 行为：模型缺失时下载目标 = 用户数据目录 ----

def test_rmvpe_download_target_is_user_data_dir(monkeypatch, tmp_path):
    """模型缺失时，download_model 的下载目标位于 get_data_dir()/models 下（不真下载）。"""
    captured = {}

    def fake_get_data_dir():
        return tmp_path

    monkeypatch.setattr(rmvpe, "get_data_dir", fake_get_data_dir)
    # 视"无模型可用"（含随包/开发副本全部视为不存在 → 触发下载分支）
    monkeypatch.setattr(rmvpe, "_resolve_model_path", lambda: None)
    monkeypatch.setattr(swift_f0, "_resolve_model_path", lambda: None)

    def fake_download(target, progress_cb=None):
        captured["target"] = target
        return True

    monkeypatch.setattr(rmvpe, "_download_model", fake_download)
    assert rmvpe.RMVPEBackend.download_model() is True
    assert captured["target"] == str(tmp_path / "models" / "rmvpe.onnx")


def test_swift_f0_download_target_is_user_data_dir(monkeypatch, tmp_path):
    """SwiftF0 同法：缺失时目标位于用户数据目录 models/ 下。"""
    captured = {}

    def fake_get_data_dir():
        return tmp_path

    monkeypatch.setattr(swift_f0, "get_data_dir", fake_get_data_dir)
    monkeypatch.setattr(swift_f0, "_resolve_model_path", lambda: None)

    def fake_download(target, progress_cb=None):
        captured["target"] = target
        return True

    monkeypatch.setattr(swift_f0, "_download_model", fake_download)
    assert swift_f0.SwiftF0Backend.download_model() is True
    assert captured["target"] == str(tmp_path / "models" / "swift_f0.onnx")


# ---- D4-4 行为：sha256 不符 → 失败并清理临时文件 ----

class _FakeResp:
    def __init__(self, payload: bytes):
        self._payload = payload
        self.headers = {"Content-Length": str(len(payload))}

    def read(self, n: int):
        if self._payload:
            chunk, self._payload = self._payload[:n], self._payload[n:]
            return chunk
        return b""


def test_rmvpe_sha256_mismatch_cleans_tmp(monkeypatch, tmp_path):
    """sha256 不符 → download_model 返回 False 且临时文件被清理、最终文件不存在。"""
    import urllib.request

    target = str(tmp_path / "models" / "rmvpe.onnx")
    monkeypatch.setattr(rmvpe, "_RMVPE_SHA256", "0" * 64)  # 强制触发不符
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **k: _FakeResp(b"nonsense-payload")
    )
    assert rmvpe._download_model(target) is False
    assert not pathlib.Path(target + ".tmp").exists()  # 临时文件已清理
    assert not pathlib.Path(target).exists()  # 未落成最终文件


def test_swift_f0_sha256_mismatch_cleans_tmp(monkeypatch, tmp_path):
    """SwiftF0 同法：sha256 不符 → 失败并清理临时文件。"""
    import urllib.request

    target = str(tmp_path / "models" / "swift_f0.onnx")
    monkeypatch.setattr(swift_f0, "_SWIFTF0_SHA256", "0" * 64)
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **k: _FakeResp(b"nonsense-payload")
    )
    assert swift_f0._download_model(target) is False
    assert not pathlib.Path(target + ".tmp").exists()
    assert not pathlib.Path(target).exists()