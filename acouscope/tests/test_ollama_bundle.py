# SPDX-License-Identifier: GPL-3.0-only
"""T-316：包内 bundled Ollama 发现层（macOS arm64 试点，AT-410 开箱即用）。

覆盖（任务书 Step 3，全离屏、零进程零网络）：
- `_DEV_OLLAMA_BIN` 推导锚点（包根 resources/bin/ollama/ollama）；
- 外部候选全缺 + bundled 已部署（tmp 可执行假二进制）→ 命中 bundled；
- bundled 与外部已装同时存在 → 命中 bundled（版本焊死语义锚点）；
- env ACOUSCOPE_OLLAMA_BIN 存在 → 优先于 bundled（覆盖逃生门）；
- bundled 目录已部署但二进制缺失/不可执行 → 返回 None，**不静默回退外部**
  （规格 2；「目录整体未部署」保留外部回退，见 deviations 口径说明）；
- bundled 未部署 → 外部回退（T-317 入库前 dev 行为保持）；
- frozen 分支：sys.frozen/_MEIPASS 候选含 ollama/ollama（仅构造断言）；
- 失败文案零终端（沿用 T-303b 7 词禁词表）。

禁真下载 / 真起 ollama / 真网络：全部 tmp_path 假文件 + monkeypatch。

分节 7（T-317 增补）：真资产存在断言（stat 只读，零进程零网络）——若
`resources/bin/ollama/` 整套已由 `scripts/fetch_ollama.sh` 落位则逐一校验
（ollama/llama-server/llama-quantize 可执行、dylib symlink 可 resolve、
mlx_metal_v3/v4、BUNDLE_INFO.txt sha256/版本登记）；未落位环境（如其他
平台构建机）整体 skip，不影响本地真实回归。
"""
import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, "src")
import pytest

from acouscope.ai import ollama_runtime as rt
from acouscope.ai.ollama_runtime import find_ollama_binary

BANNED = ["终端", "ollama serve", "ollama pull", "ollama.com", "http",
          "请安装", "brew"]


def _mk_exec(path: Path) -> str:
    """造一个可执行假文件（结构测试用，零进程零网络）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n# fake-bundle-binary\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """每个用例独立：清 env 覆盖 + 清外部候选（which→None）。"""
    monkeypatch.delenv("ACOUSCOPE_OLLAMA_BIN", raising=False)
    monkeypatch.setattr(rt, "_FALLBACK_BINARIES", ())
    monkeypatch.setattr(rt.shutil, "which", lambda _n: None)


def _deploy_bundled(monkeypatch, tmp_path, broken=False) -> Path:
    """把 dev bundled 目录打桩到 tmp（含/不含可执行 ollama）。"""
    d = tmp_path / "ollama"
    d.mkdir(parents=True, exist_ok=True)
    if not broken:
        _mk_exec(d / "ollama")
    monkeypatch.setattr(rt, "_DEV_OLLAMA_DIR", d)
    return d


# ---------------------------------------------------------------------------
# 1. 常量推导锚点
# ---------------------------------------------------------------------------

def test_dev_bin_constant_shape():
    """_DEV_OLLAMA_BIN 以 <包根>/resources/bin/ollama/ollama 结尾（与
    llama-server 同级 bin/ 下、以 ollama/ 子目录隔离——名冲突防回潮）。"""
    p = str(rt._DEV_OLLAMA_BIN)
    assert p.endswith(str(Path("resources") / "bin" / "ollama" / "ollama"))
    # 推导锚点：bundled 目录相对包根 = resources/bin/ollama（包根 = src/acouscope）
    pkg_root = Path(rt.__file__).resolve().parents[1]
    assert rt._DEV_OLLAMA_DIR.relative_to(pkg_root) == \
        Path("resources") / "bin" / "ollama"


# ---------------------------------------------------------------------------
# 2. bundled 命中 / 焊死优先
# ---------------------------------------------------------------------------

def test_bundled_hit_when_no_external(monkeypatch, tmp_path):
    """外部候选全缺 + bundled 已部署 → 命中 bundled 路径。"""
    _deploy_bundled(monkeypatch, tmp_path)
    found = find_ollama_binary()
    assert found == str(tmp_path / "ollama" / "ollama")


def test_bundled_wins_over_external(monkeypatch, tmp_path):
    """bundled 与外部已装同时存在 → 命中 bundled（版本焊死语义锚点）。"""
    _deploy_bundled(monkeypatch, tmp_path)
    ext = _mk_exec(tmp_path / "ext" / "ollama")
    monkeypatch.setattr(rt, "_FALLBACK_BINARIES", (ext,))
    assert find_ollama_binary() == str(tmp_path / "ollama" / "ollama")


def test_env_overrides_bundled(monkeypatch, tmp_path):
    """env ACOUSCOPE_OLLAMA_BIN 存在 → 优先于 bundled（覆盖逃生门）。"""
    _deploy_bundled(monkeypatch, tmp_path)
    env_bin = _mk_exec(tmp_path / "envdir" / "ollama")
    monkeypatch.setenv("ACOUSCOPE_OLLAMA_BIN", env_bin)
    assert find_ollama_binary() == env_bin


# ---------------------------------------------------------------------------
# 3. 焊死：已部署损坏不回退外部（规格 2）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("broken_mode", ["missing", "not_exec"])
def test_bundled_broken_no_silent_fallback(monkeypatch, tmp_path, broken_mode):
    """bundled 目录已部署但二进制缺失/不可执行 + 外部存在 → None（不回退）。"""
    d = tmp_path / "ollama"
    d.mkdir(parents=True, exist_ok=True)
    if broken_mode == "not_exec":
        f = d / "ollama"
        f.write_text("#!/bin/sh\n# no-x-bit\n")  # 无可执行位
    monkeypatch.setattr(rt, "_DEV_OLLAMA_DIR", d)
    ext = _mk_exec(tmp_path / "ext" / "ollama")
    monkeypatch.setattr(rt, "_FALLBACK_BINARIES", (ext,))
    assert find_ollama_binary() is None


def test_bundled_missing_binary_only_dir(monkeypatch, tmp_path):
    """bundled 目录存在但 ollama 文件缺失 + 外部全缺 → None。"""
    monkeypatch.setattr(rt, "_DEV_OLLAMA_DIR", tmp_path / "ollama")
    (tmp_path / "ollama").mkdir(parents=True, exist_ok=True)
    assert find_ollama_binary() is None


# ---------------------------------------------------------------------------
# 4. 未部署：外部回退保持（T-317 入库前 dev 行为）
# ---------------------------------------------------------------------------

def test_undeployed_falls_back_external(monkeypatch, tmp_path):
    """bundled 目录整体未部署 + 外部存在 → 返回外部路径（既有行为保持）。"""
    monkeypatch.setattr(rt, "_DEV_OLLAMA_DIR",
                        tmp_path / "no-such-bundle")
    ext = _mk_exec(tmp_path / "ext" / "ollama")
    monkeypatch.setattr(rt, "_FALLBACK_BINARIES", (ext,))
    assert find_ollama_binary() == ext


def test_undeployed_and_no_external_returns_none(monkeypatch, tmp_path):
    """bundled 未部署 + 外部全缺 → None（全部候选落空）。"""
    monkeypatch.setattr(rt, "_DEV_OLLAMA_DIR", tmp_path / "no-such-bundle")
    assert find_ollama_binary() is None


# ---------------------------------------------------------------------------
# 5. frozen 分支（仅构造断言）
# ---------------------------------------------------------------------------

def test_frozen_meipass_candidate(monkeypatch, tmp_path):
    """frozen：_MEIPASS/ollama/ollama 可用 → 命中；且优先于 dev bundled。"""
    frozen_root = tmp_path / "meipass"
    _mk_exec(frozen_root / "ollama" / "ollama")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(frozen_root), raising=False)
    # dev bundled 同样部署 → frozen 优先
    _deploy_bundled(monkeypatch, tmp_path)
    assert find_ollama_binary() == str(frozen_root / "ollama" / "ollama")


def test_frozen_broken_no_silent_fallback(monkeypatch, tmp_path):
    """frozen：_MEIPASS/ollama 目录存在但二进制缺失 + 外部存在 → None。"""
    frozen_root = tmp_path / "meipass"
    (frozen_root / "ollama").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(frozen_root), raising=False)
    monkeypatch.setattr(rt, "_DEV_OLLAMA_DIR", tmp_path / "no-such-bundle")
    ext = _mk_exec(tmp_path / "ext" / "ollama")
    monkeypatch.setattr(rt, "_FALLBACK_BINARIES", (ext,))
    assert find_ollama_binary() is None


# ---------------------------------------------------------------------------
# 6. 零终端文案（T-303b 7 词禁词表）
# ---------------------------------------------------------------------------

def test_error_copy_zero_terminal():
    """失败文案不含命令/URL/安装指引（零终端铁律）。"""
    for err in (rt._ERR_NO_BINARY, rt._ERR_NOT_READY, rt._ERR_PROCESS_EXITED):
        assert err, "失败文案不得为空"
        for w in BANNED:
            assert w not in err, f"零终端禁词命中: {w!r}"
        assert "://" not in err and "curl" not in err


def test_no_real_download_or_network():
    """本测试文件纪律自断言：无真下载/真起进程/真网络痕迹（拼接构造防自扫中）。"""
    src = Path(__file__).read_text(encoding="utf-8")
    for banned in ("urllib" + ".request.urlopen", "requests" + ".get",
                   "Popen" + "(", "subprocess" + ".run"):
        assert banned not in src, f"禁用 API 出现: {banned!r}"
    assert os.access(__file__, os.R_OK)  # 文件可读（仅结构断言的 sanity）


# ---------------------------------------------------------------------------
# 7. T-317 真资产存在断言（stat 只读；零进程零网络；未 fetch 环境整体 skip）
# ---------------------------------------------------------------------------

# 真资产根：<包根>/resources/bin/ollama（find_ollama_binary ③ dev bundled 同路径）
_OLLAMA_DIR = Path(__file__).resolve().parents[1] / "src" / "acouscope" / \
    "resources" / "bin" / "ollama"

# 官方 v0.33.3 ollama-darwin.tgz sha256（与 BUNDLE_INFO.txt 登记比对，
# 防登记值被无意识改错；来源 = 官方 releases sha256sum.txt，2026-09-09 实测）
_OFFICIAL_TGZ_SHA256 = "342db03df80bb9db84ff64246031bd5f70c09b59ff52fa5cc9aaae3476cc4a9d"

_BUNDLE_DEPLOYED = (_OLLAMA_DIR / "ollama").is_file()


@pytest.mark.skipif(not _BUNDLE_DEPLOYED,
                    reason="resources/bin/ollama 未由 fetch_ollama.sh 落位（非本机环境）")
def test_real_ollama_binary_present():
    """真资产：ollama 主二进制存在、可执行、体积合理（>10KB，实际 ~66MB）。"""
    p = _OLLAMA_DIR / "ollama"
    assert p.is_file(), f"缺内置 ollama：{p}"
    assert os.access(p, os.X_OK), "ollama 无执行权限"
    assert p.stat().st_size > 10 * 1024, "ollama 体积异常（<10KB）"
    # 与发现层命中路径一致（dev bundled = _DEV_OLLAMA_BIN）
    assert str(p) == str(rt._DEV_OLLAMA_BIN), "真资产路径与发现层常量不一致"


@pytest.mark.skipif(not _BUNDLE_DEPLOYED,
                    reason="resources/bin/ollama 未由 fetch_ollama.sh 落位（非本机环境）")
def test_real_runner_closure_present():
    """整套同目录铁律：llama-server / llama-quantize 存在、可执行。"""
    for name in ("llama-server", "llama-quantize"):
        p = _OLLAMA_DIR / name
        assert p.is_file(), f"整套缺 {name}（禁单独替换/删除——serve 按 @loader_path 找）"
        assert os.access(p, os.X_OK), f"{name} 无执行权限"
        assert p.stat().st_size > 10 * 1024, f"{name} 体积异常"


@pytest.mark.skipif(not _BUNDLE_DEPLOYED,
                    reason="resources/bin/ollama 未由 fetch_ollama.sh 落位（非本机环境）")
def test_real_metal_dir_closure():
    """mlx_metal_v3/v4 存在且 v4 含 mlx.metallib（Metal 推理内核闭包）。"""
    for name in ("mlx_metal_v3", "mlx_metal_v4"):
        d = _OLLAMA_DIR / name
        assert d.is_dir(), f"整套缺 {name}/"
    assert (_OLLAMA_DIR / "mlx_metal_v4" / "mlx.metallib").is_file(), \
        "mlx_metal_v4/mlx.metallib 缺失"


@pytest.mark.skipif(not _BUNDLE_DEPLOYED,
                    reason="resources/bin/ollama 未由 fetch_ollama.sh 落位（非本机环境）")
def test_real_dylib_symlinks_resolve():
    """dylib symlink 闭包：无后缀/`.0` 层可 resolve 到版本号实体。"""
    for link in ("libggml.dylib", "libllama.dylib", "libmtmd.dylib"):
        p = _OLLAMA_DIR / link
        assert p.is_symlink(), f"{link} 应为 symlink（tar 原样保持）"
        resolved = p.resolve()
        assert resolved.is_file(), f"{link} resolve 后非实体文件"
        assert resolved.stat().st_size > 10 * 1024, f"{link} 实体体积异常"
    assert (_OLLAMA_DIR / "libmtmd.0.dylib").resolve().name != \
        "libmtmd.0.dylib", "多级 symlink 未展开"


@pytest.mark.skipif(not _BUNDLE_DEPLOYED,
                    reason="resources/bin/ollama 未由 fetch_ollama.sh 落位（非本机环境）")
def test_real_bundle_info_registration():
    """BUNDLE_INFO.txt 登记：含 v0.33.3 与官方 sha256（fetch 脚本写回同源）。"""
    info = _OLLAMA_DIR / "BUNDLE_INFO.txt"
    assert info.is_file(), "缺 BUNDLE_INFO.txt（版本/校验登记）"
    text = info.read_text(encoding="utf-8")
    assert "0.33.3" in text, "BUNDLE_INFO 未登记版本 0.33.3"
    assert _OFFICIAL_TGZ_SHA256 in text, \
        "BUNDLE_INFO 登记 sha256 与官方值不一致（防登记被无意识改错）"
    assert "整套" in text and "mlx_metal_v4" in text, "BUNDLE_INFO 缺整套约束提示"
