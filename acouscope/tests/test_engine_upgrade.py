# SPDX-License-Identifier: GPL-3.0-only
"""T-319：应用内「检查引擎更新 / 恢复默认引擎」（升级策略 C，零网络零真实下载）。

覆盖（需求说明 Step 6，全离屏 / 全 mock / 临时目录）：
- 发现顺序：env → 用户级优先 → bundled 兜底 → 用户级损坏落回 bundled；
- 升级：版本判定 → 下载 mock → sha256 不符零副作用 → 成功解压切指针；
- 恢复默认：清指针回 bundled（保留版本目录）；
- 运行时：用户级「启动失败」→ 自动回退 bundled + 提示位仅一次；
- UI：内置档状态区含版本行 / 更新 / 恢复按钮，回调刷新状态与温和提示；
- 纪律：零黑话 / 无 QDialog / 无真实网络 / 无 Popen 真实调用。
"""
import hashlib
import io
import stat
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, "src")
import pytest
pytest.importorskip("PyQt6")

from acouscope.ai import ollama_engines as oe
from acouscope.ai import ollama_runtime as rt
from acouscope.ai.ollama_runtime import OllamaRuntime, find_ollama_binary

_SRC = Path(__file__).resolve().parents[1] / "src" / "acouscope"


def _mk_exec(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n# fake-binary\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR
               | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """每用例独立：清 env 覆盖 + 清外部候选（which → None）。"""
    monkeypatch.delenv("ACOUSCOPE_OLLAMA_BIN", raising=False)
    monkeypatch.setattr(rt, "_FALLBACK_BINARIES", ())
    monkeypatch.setattr(rt.shutil, "which", lambda _n: None)


def _deploy_bundled(monkeypatch, tmp_path, version="0.33.3", broken=False):
    """打桩 bundled 树：tmp/bundled（可执行 ollama + BUNDLE_INFO 登记）。"""
    b = tmp_path / "bundled"
    b.mkdir(parents=True, exist_ok=True)
    if not broken:
        _mk_exec(b / "ollama")
    (b / "BUNDLE_INFO.txt").write_text(
        f"版本：        ollama v{version}（官方 release）\n"
        "tgz sha256：  0000\n", encoding="utf-8")
    monkeypatch.setattr(rt, "_DEV_OLLAMA_DIR", b)
    monkeypatch.setattr(oe, "_bundle_dir", lambda: b)
    return b


def _mk_user_engine(monkeypatch, data_dir: Path, version: str,
                    broken=False) -> Path:
    """打桩用户级引擎树：<data>/engines/ollama/（指针 + 版本目录）。"""
    monkeypatch.setattr(oe, "get_data_dir", lambda: data_dir)
    root = data_dir / "engines" / "ollama"
    root.mkdir(parents=True, exist_ok=True)
    (root / "current.txt").write_text(version, encoding="utf-8")
    if not broken:
        _mk_exec(root / version / "ollama")
    return root


def _tar_bytes(script: bytes = b"#!/bin/sh\n# fake ollama\n") -> bytes:
    """构造含 ./ollama（0o755）的微型 tgz（sha 由调用方如实计算）。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        ti = tarfile.TarInfo("./ollama")
        ti.size = len(script)
        ti.mode = 0o755
        ti.type = tarfile.REGTYPE
        tar.addfile(ti, io.BytesIO(script))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. 发现顺序：用户级优先 / bundled 兜底 / 损坏落回（需求说明规格 1）
# ---------------------------------------------------------------------------

def test_discover_user_wins_over_bundled(monkeypatch, tmp_path):
    _deploy_bundled(monkeypatch, tmp_path)
    root = _mk_user_engine(monkeypatch, tmp_path / "data", "v9.9.9")
    user_bin = root / "v9.9.9" / "ollama"
    assert find_ollama_binary() == str(user_bin)


def test_discover_no_user_uses_bundled(monkeypatch, tmp_path):
    _deploy_bundled(monkeypatch, tmp_path)
    b = tmp_path / "bundled"
    monkeypatch.setattr(oe, "get_data_dir", lambda: tmp_path / "no-data")
    assert find_ollama_binary() == str(b / "ollama")


def test_discover_user_broken_falls_back_bundled(monkeypatch, tmp_path):
    """指针存在但二进制损坏（缺失/不可执行）→ 自动落回 bundled（规格 ④）。"""
    _deploy_bundled(monkeypatch, tmp_path)
    root = _mk_user_engine(monkeypatch, tmp_path / "data", "v9.9.9",
                           broken=True)
    assert (root / "current.txt").is_file()  # 指针仍在
    assert find_ollama_binary() == str(tmp_path / "bundled" / "ollama")


def test_discover_user_and_bundle_broken_no_external(monkeypatch, tmp_path):
    """用户级损坏 + bundled 损坏 + 外部存在 → None（焊死语义不回退外部）。"""
    _deploy_bundled(monkeypatch, tmp_path, broken=True)
    _mk_user_engine(monkeypatch, tmp_path / "data", "v9.9.9", broken=True)
    ext = _mk_exec(tmp_path / "ext" / "ollama")
    monkeypatch.setattr(rt, "_FALLBACK_BINARIES", (ext,))
    assert find_ollama_binary() is None


def test_discover_env_still_wins(monkeypatch, tmp_path):
    """env ACOUSCOPE_OLLAMA_BIN 仍为最高优先级（调试逃生门不变）。"""
    _deploy_bundled(monkeypatch, tmp_path)
    _mk_user_engine(monkeypatch, tmp_path / "data", "v9.9.9")
    env_bin = _mk_exec(tmp_path / "envdir" / "ollama")
    monkeypatch.setenv("ACOUSCOPE_OLLAMA_BIN", env_bin)
    assert find_ollama_binary() == env_bin


# ---------------------------------------------------------------------------
# 2. 升级：版本判定 / sha256 不符零副作用 / 成功切换指针（规格 2）
# ---------------------------------------------------------------------------

def test_upgrade_up_to_date_skips_download(monkeypatch, tmp_path):
    """当前已是最新（bundled 0.33.3 == 远端）→ up_to_date，零下载。"""
    _deploy_bundled(monkeypatch, tmp_path)
    monkeypatch.setattr(oe, "get_data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(oe, "_fetch_latest_version", lambda: "v0.33.3")
    calls = []
    monkeypatch.setattr(oe, "_download_asset",
                        lambda *a, **k: calls.append(1) or True)
    code, ver = oe.perform_upgrade()
    assert code == "up_to_date" and ver == "0.33.3"
    assert not calls, "已最新仍触发下载"
    assert not (tmp_path / "data" / "engines" / "ollama" / "current.txt").exists()


def test_upgrade_network_failure_keeps_bundled(monkeypatch, tmp_path):
    _deploy_bundled(monkeypatch, tmp_path)
    monkeypatch.setattr(oe, "get_data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(oe, "_fetch_latest_version", lambda: None)
    code, _ = oe.perform_upgrade()
    assert code == "no_network"


def test_upgrade_sha_mismatch_zero_side_effect(monkeypatch, tmp_path):
    """sha256 不符 → failed 且指针/现状零改动（bundled 仍生效）。"""
    _deploy_bundled(monkeypatch, tmp_path)
    monkeypatch.setattr(oe, "get_data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(oe, "_fetch_latest_version", lambda: "v9.9.9")
    monkeypatch.setattr(oe, "_fetch_asset_sha256", lambda tag: "0" * 64)

    bad = _tar_bytes(b"#!/bin/sh\n# tampered\n")

    def _fake_download(url, tgz, on_progress, is_cancelled):
        tgz.parent.mkdir(parents=True, exist_ok=True)
        tgz.write_bytes(bad)
        return True

    monkeypatch.setattr(oe, "_download_asset", _fake_download)
    code, _ = oe.perform_upgrade()
    assert code == "failed"
    root = tmp_path / "data" / "engines" / "ollama"
    assert not (root / "current.txt").exists(), "失败仍写指针"
    assert not (root / "v9.9.9").exists(), "校验失败仍解压目录"
    assert find_ollama_binary() == str(tmp_path / "bundled" / "ollama")


def test_upgrade_ok_switches_pointer(monkeypatch, tmp_path):
    """成功：下载(已验 sha) → 解压全新目录 → 原子写指针 → 再发现命中用户级。"""
    _deploy_bundled(monkeypatch, tmp_path)
    monkeypatch.setattr(oe, "get_data_dir", lambda: tmp_path / "data")
    payload = _tar_bytes()
    want = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(oe, "_fetch_latest_version", lambda: "v9.9.9")
    monkeypatch.setattr(oe, "_fetch_asset_sha256", lambda tag: want)

    def _fake_download(url, tgz, on_progress, is_cancelled):
        tgz.parent.mkdir(parents=True, exist_ok=True)
        if on_progress:
            on_progress(0.4)
        tgz.write_bytes(payload)
        return True

    monkeypatch.setattr(oe, "_download_asset", _fake_download)
    code, ver = oe.perform_upgrade()
    assert code == "ok" and ver == "v9.9.9"
    root = tmp_path / "data" / "engines" / "ollama"
    assert (root / "current.txt").read_text(encoding="utf-8") == "v9.9.9"
    assert (root / "v9.9.9" / "ollama").is_file()
    assert oe.engine_state() == (True, "v9.9.9")
    assert not (root / ".downloads" / "ollama-darwin.tgz").exists(), \
        "下载件未清理"
    assert find_ollama_binary() == str(root / "v9.9.9" / "ollama")


def test_upgrade_existing_dir_skips_redownload(monkeypatch, tmp_path):
    """目标版本目录已完整（历史升级遗留）→ 零下载零解压仅切指针。"""
    _deploy_bundled(monkeypatch, tmp_path)
    root = _mk_user_engine(monkeypatch, tmp_path / "data", "v9.9.9")
    monkeypatch.setattr(oe, "get_data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(oe, "_fetch_latest_version", lambda: "v9.9.9")
    monkeypatch.setattr(oe, "active_version", lambda: "0.33.3")
    calls = []
    monkeypatch.setattr(oe, "_download_asset",
                        lambda *a, **k: calls.append(1) or True)
    monkeypatch.setattr(oe, "_extract_tgz",
                        lambda *a, **k: calls.append(2) or True)
    code, ver = oe.perform_upgrade()
    assert code == "ok" and ver == "v9.9.9"
    assert not calls
    assert (root / "current.txt").read_text(encoding="utf-8") == "v9.9.9"
    assert find_ollama_binary() == str(root / "v9.9.9" / "ollama")


# ---------------------------------------------------------------------------
# 3. 恢复默认：清指针回 bundled，保留已下载版本目录（规格 3）
# ---------------------------------------------------------------------------

def test_restore_default_back_to_bundled(monkeypatch, tmp_path):
    _deploy_bundled(monkeypatch, tmp_path)
    root = _mk_user_engine(monkeypatch, tmp_path / "data", "v9.9.9")
    assert find_ollama_binary() == str(root / "v9.9.9" / "ollama")
    oe.restore_default()
    assert not (root / "current.txt").exists(), "指针未清空"
    assert (root / "v9.9.9").is_dir(), "已下载版本目录被误删（应保留可再切回）"
    assert oe.user_binary() is None
    assert find_ollama_binary() == str(tmp_path / "bundled" / "ollama")


def test_restore_default_idempotent(monkeypatch, tmp_path):
    """bundled 默认态（无指针）恢复默认 → 幂等，仍 bundled。"""
    _deploy_bundled(monkeypatch, tmp_path)
    monkeypatch.setattr(oe, "get_data_dir", lambda: tmp_path / "data")
    oe.restore_default()
    oe.restore_default()
    assert find_ollama_binary() == str(tmp_path / "bundled" / "ollama")


# ---------------------------------------------------------------------------
# 4. 运行时回退：用户级启动失败 → 自动 bundled 重试 + 提示位仅一次（规格 4）
# ---------------------------------------------------------------------------

def _fake_proc(calls):
    class FakeProc:
        def __init__(self, cmd, **kwargs):
            self.cmd = cmd
            self.kwargs = kwargs
            self.terminated = False
            self.killed = False
            calls.append(self)

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

        def wait(self, timeout=None):
            return 0
    return FakeProc


def test_runtime_user_failure_falls_back_bundled_once(monkeypatch, tmp_path):
    """用户级二进制启动抛异常 → 自动用 bundled 重试成功；提示位一次性。"""
    bundled = _deploy_bundled(monkeypatch, tmp_path)
    root = _mk_user_engine(monkeypatch, tmp_path / "data", "v9.9.9")
    user_bin = str(root / "v9.9.9" / "ollama")
    assert find_ollama_binary() == user_bin

    calls: list = []
    cmds: list = []
    FakeProc = _fake_proc(calls)

    def raising_then_ok(cmd, **kwargs):
        cmds.append(cmd)
        if len(cmds) == 1:  # 第一次（用户级）启动抛异常
            raise OSError("boom")
        return FakeProc(cmd, **kwargs)

    monkeypatch.setattr(rt.subprocess, "Popen", raising_then_ok)
    rt_obj = OllamaRuntime()
    monkeypatch.setattr(rt_obj, "_wait_ready", lambda timeout: True)

    assert rt_obj.start() is True
    assert len(cmds) == 2, "应恰好尝试两次（用户级 + bundled）"
    assert cmds[0][0] == user_bin
    assert cmds[1][0] == str(bundled / "ollama")
    assert rt_obj.state == "ready"
    assert rt_obj.fallback_notice == rt._FALLBACK_NOTICE
    assert rt_obj._fallback_tried is True

    # 一次性：stop 后再启仍失败 → 不再回退（提示位不反复、不追加）
    rt_obj.stop()
    assert rt_obj.state == "stopped"

    def always_raise(cmd, **kwargs):
        cmds.append("extra")
        raise OSError("boom again")

    monkeypatch.setattr(rt.subprocess, "Popen", always_raise)
    assert rt_obj.start() is False
    assert len([c for c in cmds if c == "extra"]) == 1, "重复回退被触发"
    assert rt_obj.state == "failed"
    assert rt_obj.fallback_notice == rt._FALLBACK_NOTICE  # 原提示保留


# ---------------------------------------------------------------------------
# 5. UI：内置档状态区含版本行 / 检查更新 / 恢复默认（规格 5，零黑话）
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def ui_engine_stub(monkeypatch):
    """probe_ollama 打桩（零网络）+ engine_state 打桩 + 语言 pin（确定性）。"""
    import acouscope.ai.backends.local_registry as lr
    import acouscope.i18n as i18n
    monkeypatch.setattr(i18n, "_current_lang", "en_US")
    monkeypatch.setattr(lr, "probe_ollama", lambda *a, **k: (False, []))
    monkeypatch.setattr(oe, "engine_state", lambda: (False, "0.33.3"))


def test_ui_engine_area_present(app, monkeypatch, ui_engine_stub):
    """内置档状态区：版本行 / 检查更新 / 恢复默认存在且随档显隐。"""
    from acouscope.ui.widgets.settings_dialog import SettingsDialog
    dlg = SettingsDialog(ai_config={})
    assert dlg.rbtn_ai_builtin.isChecked() is True
    assert dlg.grp_engine_state.isHidden() is False
    assert "Bundled with the app" in dlg.lbl_engine_version.text()
    assert dlg.btn_engine_update.text() == "Check for Updates"
    assert dlg.btn_engine_reset.text() == "Restore Default"
    assert dlg.prog_engine.isHidden() is True
    assert dlg.lbl_engine_work.isHidden() is True
    # 切走内置档 → 整个版本区隐藏
    dlg.rbtn_ai_self.setChecked(True)
    assert dlg.grp_engine_state.isHidden() is True
    dlg.deleteLater()


def test_ui_done_handler_refreshes_state(app, monkeypatch, ui_engine_stub):
    """升级完成回调：还原忙碌态、版本行刷新、按钮回「检查更新」。"""
    from acouscope.ui.widgets.settings_dialog import SettingsDialog
    dlg = SettingsDialog(ai_config={})
    assert dlg._engine_busy is False

    # 模拟后台忙碌 → 回调完成（code=ok）→ 忙碌结束
    dlg._engine_start_busy("checking")
    assert dlg._engine_busy is True
    assert dlg.btn_engine_reset.isEnabled() is False
    monkeypatch.setattr(oe, "engine_state", lambda: (True, "v9.9.9"))
    dlg._on_engine_update_done("ok", "v9.9.9")
    assert dlg._engine_busy is False
    assert "v9.9.9" in dlg.lbl_engine_version.text()
    assert dlg.btn_engine_update.text() == "Check for Updates"
    assert dlg.btn_engine_update.isEnabled() is True
    assert dlg.btn_engine_reset.isEnabled() is True
    assert dlg.prog_engine.isHidden() is True
    dlg.deleteLater()


def test_ui_reset_toast(app, monkeypatch, ui_engine_stub):
    """恢复默认回调：清指针 + 版本行回 bundled + 温和提示（不弹模态）。"""
    from acouscope.ui.widgets.settings_dialog import SettingsDialog
    restored = {"called": False}

    def _restore():
        restored["called"] = True

    monkeypatch.setattr(oe, "restore_default", _restore)
    dlg = SettingsDialog(ai_config={})
    monkeypatch.setattr(oe, "engine_state", lambda: (False, "0.33.3"))
    dlg._on_engine_reset_clicked()
    assert restored["called"] is True
    assert "Bundled with the app" in dlg.lbl_engine_version.text()
    dlg.deleteLater()


def test_ui_worker_blackbox(app):
    """worker 存在且信号齐（禁旧名回潮，见 test_settings_ai_v2）。"""
    from acouscope.ui.widgets import settings_dialog as sd
    worker_cls = sd._EngineUpdateWorker
    assert hasattr(worker_cls, "progress")
    assert hasattr(worker_cls, "done")
    for old in ("_ModelPullWorker", "_LlamaPullWorker"):
        assert not hasattr(sd, old)


# ---------------------------------------------------------------------------
# 6. 纪律自断言：零真实网络 / 零黑话 UI / 无模态（拼接构造防自扫中）
# ---------------------------------------------------------------------------

def test_no_real_download_in_tests():
    """本测试文件不引入真实网络 / 子进程启动 API。"""
    src = Path(__file__).read_text(encoding="utf-8")
    for banned in ("urllib" + ".request.urlopen", "requests" + ".get",
                   "subprocess" + ".run"):
        assert banned not in src, f"禁用 API 出现: {banned!r}"


def test_engine_module_ui_source_discipline():
    """UI 层设置源码不含模态与黑话痕迹（引擎区零开发概念）。"""
    settings_src = (_SRC / "ui" / "widgets" / "settings_dialog.py").read_text(
        encoding="utf-8")
    for banned in ("Q" + "Dialog", "QMessageBox" + "(",
                   "o" + "MLX", "Mac " + "Studio", "ollama " + "serve",
                   "ollama " + "pull", "brew " + "install"):
        assert banned not in settings_src, f"设置源码禁词命中: {banned!r}"

