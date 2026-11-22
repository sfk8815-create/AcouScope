# SPDX-License-Identifier: GPL-3.0-only
"""2026-11-06 约定 C 专属有齿判据：取消首次运行征询、自动检查默认关闭。

推翻 UP-2b「AD-12 默认开 + 首次征询、只问一次」语义。逐条可判定：

- C1 缺键默认关闭：``is_update_check_enabled()`` 返回 ``False``（非 ``None``）；
  ``should_run_update_check()`` 首行短路，不写盘 / 不发请求 / 不弹框；
  ``SettingsDialog`` 复选框不勾选。
- C2 删除征询：``main_window.py`` 源码 AST 中 ``_ask_update_check_optin``
  的定义与调用均不存在；空 state 下手动 / 自动两入口零弹框（计数替身）、
  零 ``urlopen``；手动入口仍给 ``update.disabled`` 文案（不静默吞点击）。
- C3 保留自动挂载点 + 开启后恢复：showEvent 的 ``_UPDATE_CHECK_DELAY_MS``
  挂载行仍在；开启后手动恰一次 fetch、自动路径当日首次 True / 同日二次 False。

★ 零真实网络（一律 monkeypatch ``update_checker.urlopen`` 替身）；
★ 零真模态（``QMessageBox`` 计数替身）；★ 未 show 主窗、禁 apply_theme。
"""
import ast
import inspect
import json
import sys
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

pytest.importorskip("PyQt6")

from acouscope import state  # noqa: E402
from acouscope import update_checker as uc  # noqa: E402
from acouscope.i18n import tr  # noqa: E402


# ---------------------------------------------------------------------------
# 替身：urlopen 响应 / 网络 / QMessageBox 计数（零真实网络、零真模态）
# ---------------------------------------------------------------------------


class _Resp:
    """urlopen 替身响应：上下文管理器 + ``read`` / ``status``。"""

    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Net:
    """urlopen 替身：记录**调用次数**；按脚本返回或抛异常。"""

    def __init__(self, resp=None, exc=None):
        self._resp = resp
        self._exc = exc
        self.calls = 0
        self.requests = []

    def __call__(self, req, timeout=None):
        self.calls += 1
        self.requests.append(req)
        if self._exc is not None:
            raise self._exc
        return self._resp


def _net(data=None, raw=None, exc=None) -> _Net:
    if exc is not None:
        return _Net(exc=exc)
    if raw is not None:
        return _Net(_Resp(raw))
    return _Net(_Resp(json.dumps(data).encode("utf-8")))


class _CountingBox:
    """``QMessageBox`` 计数替身：任何实例化都计数（断「零弹框」）。"""

    built = 0

    def __init__(self, *a, **k):
        type(self).built += 1


def _window(qapp):
    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow

    return MainWindow(AppController())


def _settle(window, qapp) -> None:
    """等待后台 worker 结束并把结果信号交付主线程。"""
    worker = getattr(window, "_update_worker", None)
    if worker is not None:
        worker.wait(5000)
    qapp.processEvents()


# ---------------------------------------------------------------------------
# J1 / C1：缺键默认关闭（有齿：改回 return None ⇒ 至少两条翻红）
# ---------------------------------------------------------------------------


def test_c1_missing_key_default_off(qapp, monkeypatch, tmp_path):
    """缺键 ⇒ False；首行短路不写盘；设置复选框不勾选。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    state.save_state({})                         # 缺 update_check_enabled 键
    assert state.is_update_check_enabled() is False
    assert state.should_run_update_check() is False
    assert state.get_last_update_check_date() is None   # 未写盘

    # 设置面板：缺键时复选框不勾选（C4）
    monkeypatch.setattr(
        "acouscope.ai.backends.local_registry.probe_ollama",
        lambda *a, **k: (False, []),
    )
    from acouscope.ui.widgets.settings_dialog import SettingsDialog

    dlg = SettingsDialog()
    try:
        assert dlg.chk_update_check.isChecked() is False
    finally:
        dlg.deleteLater()


# ---------------------------------------------------------------------------
# J2 / C2：删除征询（有齿：插回调用分支 ⇒ 零引用判据翻红）
# ---------------------------------------------------------------------------


def test_c2_no_optin_symbol_in_source():
    """AST + 源码字面：_ask_update_check_optin 定义与调用均不存在。"""
    from acouscope.ui import main_window as mw

    src = Path(mw.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    defined = {n.name for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    called = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute):
                called.add(f.attr)
            elif isinstance(f, ast.Name):
                called.add(f.id)
    # 正对照：AST 确实能看到既有方法名（证明「零命中」非空跑）
    assert "_on_check_updates" in defined
    assert "_on_update_checked" in defined
    assert "_on_check_updates" in src
    # 判据：征询方法的定义 / 调用 / 源码字面均不存在
    assert "_ask_update_check_optin" not in defined
    assert "_ask_update_check_optin" not in called
    assert "_ask_update_check_optin" not in src


def test_c2_zero_dialog_zero_fetch_disabled(qapp, monkeypatch, tmp_path):
    """空 state 两入口：零弹框、零 fetch、手动给 disabled 文案、零写盘。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    state.save_state({})
    window = _window(qapp)
    try:
        monkeypatch.setattr("acouscope.ui.main_window.QMessageBox", _CountingBox)
        # 正对照：计数替身确实会计数（证明 built==0 非空跑）
        _CountingBox.built = 0
        _CountingBox()
        assert _CountingBox.built == 1
        _CountingBox.built = 0

        net = _net(data={"version": "9999.0"})
        monkeypatch.setattr(uc, "urlopen", net)
        window._on_check_updates(manual=True)
        assert window.statusBar().currentMessage() == tr("update.disabled")
        window._on_check_updates(manual=False)
        _settle(window, qapp)
        assert _CountingBox.built == 0                 # 零弹框
        assert net.calls == 0                          # 零网络请求
        assert state.get_last_update_check_date() is None   # 零写盘
        assert "update_check_enabled" not in state.load_state()
    finally:
        window.close()


# ---------------------------------------------------------------------------
# J3 / C3：保留自动挂载点 + 开启后恢复（有齿：删挂载行 ⇒ 静态判据翻红）
# ---------------------------------------------------------------------------


def test_c3_mount_point_preserved():
    """showEvent 仍以正延迟挂载自动路径（与 up2 ⒜ 同源判据）。"""
    from acouscope.ui import main_window as mw

    src = inspect.getsource(mw.MainWindow.showEvent)
    assert "_UPDATE_CHECK_DELAY_MS" in src
    assert "manual=False" in src
    assert "self._on_check_updates(manual=False)" in src


def test_c3_enable_restores_fetch_and_throttle(qapp, monkeypatch, tmp_path):
    """开启后：手动恰一次 fetch + ok 文案；自动当日首次 True、同日二次 False。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    state.save_state({})
    state.set_update_check_enabled(True)         # 用户去设置里打开
    window = _window(qapp)
    try:
        net = _net(data={"version": "9999.0", "notes_url": "https://dl/notes"})
        monkeypatch.setattr(uc, "urlopen", net)
        window._on_check_updates(manual=True)
        _settle(window, qapp)
        assert net.calls == 1                       # 恰一次 fetch
        assert "9999.0" in window.statusBar().currentMessage()
        # 自动路径每日节流（UP-2 保留）
        assert state.should_run_update_check() is True
        assert state.should_run_update_check() is False
        assert state.should_run_update_check(
            now=datetime.now() + timedelta(days=1)) is True
    finally:
        window.close()
