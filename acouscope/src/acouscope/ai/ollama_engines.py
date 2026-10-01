# SPDX-License-Identifier: GPL-3.0-only
"""用户级本地模型引擎升级 / 恢复默认（T-319，升级策略 C 落地）。

设计约束（四层防崩，见 AI_ENGINE_ollama_requirements §三）：
1. bundled 只读目录 = 出厂基准（resources/bin/ollama/ 或 frozen _MEIPASS/ollama/），
   本模块永不写 bundled（bundled 替换属 T-317 直营，不在此）；
2. 用户级引擎放应用数据目录 get_data_dir()/engines/ollama/<version>/，
   独立版本目录并存，不覆盖 bundled；
3. 升级 = sha256 硬校验（官方 sha256sum.txt）→ .part 下载 → 解压全新目录
   → 指针原子切换；失败任一环节零改动现状（bundled 恒可用）；
4. 恢复默认 = 清指针 → 回 bundled，已下载版本目录保留（可再切回）。

用户可见文案铁律：面向田野研究者，模块返回 (code, version) 结构化结果，
不上抛原始异常 / URL / 命令；文案归属 UI 层（i18n）与运行时（零终端）。
升级只作用于本地内置模型档的引擎；其余模型通道不受影响。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

from acouscope.ai.interpreter import CancelledError
from acouscope.utils.config import get_data_dir

#: 官方下载 / 版本查询 URL（仅存在于本文件常量；绝不进入用户可见文案）。
_RELEASE_BASE = "https://github.com/ollama/ollama/releases/download"
_LATEST_API_URL = "https://api.github.com/repos/ollama/ollama/releases/latest"

#: 升级资产按平台映射（当前交付 macOS arm64 通道；Windows/Linux 属 T-317b 域，
#: 其余平台 perform_upgrade 返回 unsupported，bundled 恒可用）。
_PLATFORM_ASSET = {"darwin": "ollama-darwin.tgz"}

#: 用户级版本目录名 / 指针文件允许的字符（防路径穿越：拒绝 / \\ .. 等）。
_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _bundle_dir() -> Path:
    """bundled 资产目录（<包根>/resources/bin/ollama；frozen 为 _MEIPASS/ollama）。"""
    p = Path(__file__).resolve().parents[1] / "resources" / "bin" / "ollama"
    meipass = getattr(sys, "_MEIPASS", None)
    if not p.is_dir() and meipass:
        p = Path(meipass) / "ollama"
    return p


# ---------------------------------------------------------------------------
# 用户级引擎目录 / 指针文件（发现顺序：env → 用户级 → bundled → 外部）
# ---------------------------------------------------------------------------

def user_engines_root() -> Path:
    """用户级引擎根目录（get_data_dir()/engines/ollama）。"""
    return get_data_dir() / "engines" / "ollama"


def _ensure_root() -> Path:
    root = user_engines_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def current_file() -> Path:
    """「当前版本」指针文件（内容 = 生效的版本目录名，如 v0.34.0）。"""
    return user_engines_root() / "current.txt"


def _valid_version_token(v: str) -> bool:
    """版本 token 是否可安全用作目录名（防路径穿越 / 文件名注入）。"""
    return bool(v) and bool(_TAG_RE.match(v)) and ".." not in v


def read_current_version() -> str | None:
    """读取指针指向的版本目录名；不存在 / 非法 → None（bundled 语义）。"""
    try:
        f = current_file()
        if not f.is_file():
            return None
        v = f.read_text(encoding="utf-8").strip()
        return v if _valid_version_token(v) else None
    except OSError:
        return None


def _usable(p: Path) -> bool:
    return p.is_file() and os.access(p, os.X_OK)


def user_binary() -> str | None:
    """用户级当前生效二进制（指针存在且 <root>/<version>/ollama 可执行）。"""
    v = read_current_version()
    if not v:
        return None
    p = user_engines_root() / v / "ollama"
    return str(p) if _usable(p) else None


def _set_current_version(v: str) -> None:
    """原子切换指针（tmp + os.replace；失败保留旧值）。"""
    _ensure_root()
    f = current_file()
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(v, encoding="utf-8")
    os.replace(tmp, f)


def restore_default() -> None:
    """恢复默认：清空指针 → 运行时回落 bundled；保留已下载版本目录。"""
    try:
        current_file().unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# bundled 版本登记读取（BUNDLE_INFO.txt「版本：」行；只读，永不写）
# ---------------------------------------------------------------------------

def bundled_version() -> str | None:
    """bundled 出厂版本号（去 v 前缀，如 0.33.3）；登记缺失 → None。"""
    try:
        p = _bundle_dir() / "BUNDLE_INFO.txt"
        if not p.is_file():
            return None
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("版本"):
                m = re.search(r"\bv?(\d+(?:\.\d+)+)", line)
                if m:
                    return m.group(1)
    except OSError:
        return None
    return None


def active_version() -> str | None:
    """当前生效引擎版本：用户级指针有效 → 其版本；否则 bundled 版本。

    指针损坏（目录缺二进制）时视作回退 bundled（与运行时 find 语义一致），
    避免 UI 显示已更新而实际回退。
    """
    v = read_current_version()
    if v and _usable(user_engines_root() / v / "ollama"):
        return v
    return bundled_version()


def engine_state() -> tuple[bool, str]:
    """(是否用户级生效, 版本号) 供 UI 状态行与比较使用。

    用户级指针指向的目录存在可执行二进制 → (True, 版本号)；
    否则视为回退 bundled → (False, bundled 版本号或 "")。
    """
    v = read_current_version()
    if v and _usable(user_engines_root() / v / "ollama"):
        return (True, v)
    return (False, bundled_version() or "")


from acouscope.utils.versioning import is_newer, ver_tuple as _ver_tuple  # UP-0 提取为公共模块


# ---------------------------------------------------------------------------
# 远端版本查询（隔离网络：测试 monkeypatch 本函数，零真实网络）
# ---------------------------------------------------------------------------

def _http_get_text(url: str, timeout: float = 15.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "AcouScope/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _fetch_latest_version() -> str | None:
    """查询官方最新 release tag（如 'v0.34.0'）；网络 / 解析失败 → None。"""
    try:
        text = _http_get_text(_LATEST_API_URL, timeout=15.0)
        tag = str((json.loads(text) or {}).get("tag_name") or "").strip()
        return tag or None
    except Exception:
        return None


def _fetch_asset_sha256(tag: str) -> str | None:
    """下载官方 sha256sum.txt 并解析本平台资产的期望 sha256；失败 → None。"""
    asset = _PLATFORM_ASSET.get(sys.platform)
    if not asset:
        return None
    try:
        text = _http_get_text(f"{_RELEASE_BASE}/{tag}/sha256sum.txt")
    except Exception:
        return None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].lstrip("*") == asset:
            return parts[0].lower()
    return None


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 16):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# 升级执行器（下载 → sha256 硬校验 → 解压全新版本目录 → 原子切换指针）
# ---------------------------------------------------------------------------

def _download_asset(url: str, tgz: Path, on_progress, is_cancelled) -> bool:
    """下载官方 tgz 到 .part（复用 llama_models 的 Range/416/取消下载链）。"""
    from acouscope.ai.llama_models import _download_from_url
    part = tgz.with_suffix(tgz.name + ".part")
    resume = part.stat().st_size if part.is_file() else 0
    ok = _download_from_url(url, part, resume, 0, is_cancelled, on_progress)
    if not ok or not part.is_file():
        return False
    part.replace(tgz)
    return True


def _extract_tgz(tgz: Path, ver_dir: Path) -> bool:
    """解压 tgz 到目标版本目录（已存在先清空；失败清理不留半成品）。

    整套同目录铁律由「整体解压 + 完整目录切换」保证，绝不单文件落位。
    """
    if ver_dir.exists():
        shutil.rmtree(ver_dir, ignore_errors=True)
    try:
        ver_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tgz, "r:gz") as tar:
            tar.extractall(ver_dir)
        if not _usable(ver_dir / "ollama"):
            raise OSError("no ollama binary after extract")
        return True
    except Exception:
        shutil.rmtree(ver_dir, ignore_errors=True)
        return False


def perform_upgrade(
    on_progress=None,
    is_cancelled=None,
) -> tuple[str, str]:
    """应用内升级执行器（阻塞；由 UI 后台线程调用）。

    流程：查最新 → 与当前生效版本（用户级或 bundled）比较 → 下载官方 tgz
    → sha256 对官方 sha256sum.txt 硬校验 → 解压到全新版本目录 → 原子写指针
    → 清理下载件。任一步失败 → 零改动现状（bundled 恒可用），保留 .part
    （重发续传）。

    返回 (code, version)：
      ok           已安装并生效 version
      up_to_date   已是当前最新 version
      no_network   无法连接更新服务
      unsupported  当前平台暂无自动更新通道（bundled 保持可用）
      cancelled    用户取消（已保留 .part）
      failed       下载 / 校验 / 解压失败（现状未动）
    """
    if sys.platform not in _PLATFORM_ASSET:
        return ("unsupported", "")
    try:
        tag = _fetch_latest_version()
    except Exception:
        tag = None
    if not tag or not _valid_version_token(tag):
        return ("no_network", "")

    cur = active_version()
    if cur and not is_newer(tag, cur):
        return ("up_to_date", cur)

    root = _ensure_root()
    asset = _PLATFORM_ASSET[sys.platform]

    # 已存在完整目标版本目录（历史升级遗留 / 指针清空后重切）→ 零下载直接切
    ver_dir = root / tag
    if _usable(ver_dir / "ollama"):
        try:
            _set_current_version(tag)
        except OSError:
            return ("failed", "")
        return ("ok", tag)

    # 1) 官方 sha256sum.txt 取期望哈希
    want = _fetch_asset_sha256(tag)
    if not want:
        return ("no_network", "")

    # 2) 下载（.part 续传；取消上抛 CancelledError）
    dl_dir = root / ".downloads"
    try:
        dl_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return ("failed", "")
    tgz = dl_dir / asset
    try:
        if not _download_asset(f"{_RELEASE_BASE}/{tag}/{asset}",
                               tgz, on_progress, is_cancelled):
            return ("failed", "")
    except CancelledError:
        return ("cancelled", "")
    except Exception:
        return ("failed", "")

    # 3) sha256 硬校验（纯 sha；tgz 非 GGUF，勿用 GGUF 魔数版 verify_file）
    if _sha256_of(tgz).lower() != want:
        try:
            tgz.unlink(missing_ok=True)
            tgz.with_name(tgz.name + ".bad").write_bytes(b"")
        except OSError:
            pass
        return ("failed", "")

    # 4) 解压全新版本目录 → 原子写指针；5) 清理下载件
    if not _extract_tgz(tgz, ver_dir):
        return ("failed", "")
    try:
        _set_current_version(tag)
        tgz.unlink(missing_ok=True)
    except OSError:
        return ("failed", "")
    return ("ok", tag)

