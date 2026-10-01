# SPDX-License-Identifier: GPL-3.0-only
"""UP-2：应用内「检查更新」（只通知）守卫。

覆盖：① 三纯函数（``is_update_available`` 走 ``versioning.is_newer`` **同一对象**）
② 六码映射五态 ③ 每日节流（同日一次；手动入口绕过节流）④ 开关持久化 + 未决策语义
⑤ 主窗接线端到端（帮助菜单序 + ``disabled``/``ok`` 两态 statusBar 文案 + 未决策零 fetch）。

★ 全档**零真实网络**：一律 monkeypatch ``update_checker.urlopen``（替身响应）；
★ 禁在测档调 ``apply_theme``（防污染后续 GUI 度量族）；★ 未 show 主窗、不弹真模态
（首次征询经 ``main_window.QMessageBox`` 替身）。
"""
import sys
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QDialog  # noqa: E402

import acouscope as _pkg  # noqa: E402
from acouscope import state  # noqa: E402
from acouscope import update_checker as uc  # noqa: E402
from acouscope.i18n import tr  # noqa: E402
from acouscope.utils import versioning  # noqa: E402


# ---------------------------------------------------------------------------
# 替身：urlopen 响应 / 网络 / 征询对话框（零真实网络、零真模态）
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
    """urlopen 替身：记录**调用次数**与捕获的 ``Request``；按脚本返回或抛异常。"""

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
    import json

    if exc is not None:
        return _Net(exc=exc)
    if raw is not None:
        return _Net(_Resp(raw))
    return _Net(_Resp(json.dumps(data).encode("utf-8")))


class _FakeBox:
    """``QMessageBox`` 替身（仅首次征询用；计数实例化以断「只问一次」）。"""

    built = 0
    answer = 2

    class Icon:
        Question = "question"

    class StandardButton:
        Yes = 1
        No = 2

    def __init__(self, parent=None):
        self.parent = parent
        _FakeBox.built += 1

    def setIcon(self, *a):
        pass

    def setWindowTitle(self, *a):
        pass

    def setText(self, *a):
        pass

    def setStandardButtons(self, *a):
        pass

    def exec(self):
        return _FakeBox.answer


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
# ① 三纯函数（fetch / parse / compare）+ 同源比较器 + 抓包级零标识
# ---------------------------------------------------------------------------


def test_pure_functions_shared_comparator(monkeypatch):
    # is_update_available 薄引 versioning.is_newer（★ 同一对象，未复写第二份）
    assert uc.is_newer is versioning.is_newer
    assert uc.is_update_available("2.0.0", "1.0.0") is True
    assert uc.is_update_available("1.0.0", "1.0.0") is False

    # parse_manifest：version 缺失 / 非 str ⇒ None；齐备 ⇒ (version, notes_url)
    assert uc.parse_manifest(
        {"version": "9.9", "notes_url": "https://x/y"}) == ("9.9", "https://x/y")
    assert uc.parse_manifest({"notes_url": "https://x/y"}) is None
    assert uc.parse_manifest({"version": 5}) is None

    # fetch_manifest：正常体 + 抓包级零标识（URL 无 query / headers 仅 UA / UA 无数字）
    net = _net(data={"version": "9.9", "notes_url": "https://x"})
    monkeypatch.setattr(uc, "urlopen", net)
    assert uc.fetch_manifest() == {"version": "9.9", "notes_url": "https://x"}
    req = net.requests[0]
    assert "?" not in req.full_url
    assert dict(req.headers) == {"User-agent": uc.USER_AGENT}
    assert not any(ch.isdigit() for ch in uc.USER_AGENT)
    # 对照：版本号必含数字（证明 UA 的零数字非空断言）
    assert any(ch.isdigit() for ch in _pkg.__version__)

    # 断网 ⇒ None（no_network）；畸形体（HTML / 截断）⇒ {}（⇒ parse 失败 ⇒ malformed）
    monkeypatch.setattr(uc, "urlopen", _net(exc=urllib.error.URLError("down")))
    assert uc.fetch_manifest() is None
    monkeypatch.setattr(uc, "urlopen", _net(raw=b"<html>blocked</html>"))
    assert uc.fetch_manifest() == {}


# ---------------------------------------------------------------------------
# ② 六码映射：ok / up_to_date / no_network / malformed（worker 同步跑，零线程）
# ---------------------------------------------------------------------------


def test_worker_result_codes(qapp, monkeypatch):
    def run(data=None, raw=None, exc=None):
        worker = uc.UpdateCheckWorker()
        seen = []
        worker.finished_with.connect(lambda c, v: seen.append((c, v)))
        monkeypatch.setattr(uc, "urlopen", _net(data=data, raw=raw, exc=exc))
        worker.run()  # 同步执行（不经线程，稳定）
        return seen, worker

    # 有新版
    seen, worker = run(data={"version": "9999.0", "notes_url": "https://dl/notes"})
    assert seen == [(uc.CODE_OK, "9999.0")]
    assert worker.new_version == "9999.0"
    assert worker.notes_url == "https://dl/notes"
    # 已最新（与现读值同）
    seen, _ = run(data={"version": _pkg.__version__, "notes_url": "https://dl/notes"})
    assert seen == [(uc.CODE_UP_TO_DATE, "")]
    # 断网（urlopen 抛 URLError ⇒ fetch 返 None）
    seen, _ = run(exc=urllib.error.URLError("down"))
    assert seen == [(uc.CODE_NO_NETWORK, "")]
    # manifest 被墙 / 畸形（200 但返 HTML ⇒ 非清单）
    seen, _ = run(raw=b"<html>blocked</html>")
    assert seen == [(uc.CODE_MALFORMED, "")]


# ---------------------------------------------------------------------------
# ③ 每日节流（同日一次）+ 手动入口绕过节流但绕不过开关
# ---------------------------------------------------------------------------


def test_daily_throttle_and_manual_bypass(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    state.set_update_check_enabled(True)

    # 语义层：首次落盘今日 → 同日二次 False → 跨日 True
    assert state.should_run_update_check() is True
    assert state.should_run_update_check() is False
    assert state.should_run_update_check(now=datetime.now() + timedelta(days=1)) is True

    window = _window(qapp)
    try:
        # 自动路径：同日 ⇒ 静默返回（零 fetch、不起 worker）
        state.set_update_check_enabled(True)
        state.should_run_update_check()          # 占掉今日名额
        net = _net(data={"version": "9999.0"})
        monkeypatch.setattr(uc, "urlopen", net)
        window._on_check_updates(manual=False)
        assert net.calls == 0
        assert getattr(window, "_update_worker", None) is None
        # 手动入口：绕过节流（开关开着）⇒ 照常发起一次
        window._on_check_updates(manual=True)
        _settle(window, qapp)
        assert net.calls == 1
    finally:
        window.close()


# ---------------------------------------------------------------------------
# ④ 开关持久化往返 + 未决策（键缺失 ⇒ None）+ 设置面板开关行
# ---------------------------------------------------------------------------


def test_switch_persistence_and_undecided(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        "acouscope.ai.backends.local_registry.probe_ollama",
        lambda *a, **k: (False, []),
    )

    # 未决策：两键缺失
    assert state.is_update_check_enabled() is None
    assert state.get_last_update_check_date() is None

    # 往返：False ⇒ 不跑；True ⇒ 恢复
    assert state.set_update_check_enabled(False) is True
    assert state.is_update_check_enabled() is False
    assert state.should_run_update_check() is False
    assert state.set_update_check_enabled(True) is True
    assert state.is_update_check_enabled() is True

    # 设置面板开关行：存在且变更即时落盘
    from acouscope.ui.widgets.settings_dialog import SettingsDialog

    dlg = SettingsDialog()
    try:
        assert hasattr(dlg, "chk_update_check")
        assert dlg.chk_update_check.isChecked() is True
        dlg.chk_update_check.setChecked(False)
        assert state.is_update_check_enabled() is False
    finally:
        dlg.deleteLater()


# ---------------------------------------------------------------------------
# ⑤ 主窗接线端到端：菜单序 + disabled/ok 两态 statusBar + 未决策零 fetch
# ---------------------------------------------------------------------------


def test_main_window_wiring(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    window = _window(qapp)
    try:
        # 菜单序：访问网站 → 检查更新 → 关于
        help_action = next(
            a for a in window.menuBar().actions() if a.text() == tr("menu.help"))
        texts = [a.text() for a in help_action.menu().actions()]
        assert (texts.index(tr("action.visit_site"))
                < texts.index(tr("action.check_updates"))
                < texts.index(tr("action.about")))
        assert window.action_check_updates.text() == tr("action.check_updates")

        notes = "https://sfk8815-create.github.io/dl/notes"

        def run_check(net):
            monkeypatch.setattr(uc, "urlopen", net)
            window._on_check_updates(manual=True)
            _settle(window, qapp)
            return window.statusBar().currentMessage()

        # ③-5 开关关 ⇒ disabled 文案 + 零 fetch（不静默吞掉点击）
        state.set_update_check_enabled(False)
        net = _net(data={"version": "9999.0"})
        assert run_check(net) == tr("update.disabled")
        assert net.calls == 0

        # ③-1 有新版 ⇒ statusBar 含新版本号 + notes_url；零新 QDialog；恰一次请求
        state.set_update_check_enabled(True)
        before = len(window.findChildren(QDialog))
        net = _net(data={"version": "9999.0", "notes_url": notes})
        msg = run_check(net)
        assert "9999.0" in msg and notes in msg
        assert net.calls == 1
        assert len(window.findChildren(QDialog)) == before

        # ③-2 已最新 ⇒ up_to_date 文案、无「请到下载页」串
        net = _net(data={"version": _pkg.__version__, "notes_url": notes})
        msg = run_check(net)
        assert msg == tr("update.up_to_date")
        assert "请到下载页" not in msg

        # ③-3 断网（urlopen 抛 URLError）⇒ no_network；恰一次（零重试）
        net = _net(exc=urllib.error.URLError("down"))
        assert run_check(net) == tr("update.no_network")
        assert net.calls == 1

        # ③-4 manifest 被墙 / 畸形（返 HTML）⇒ malformed；恰一次（零重试）
        net = _net(raw=b"<html>blocked</html>")
        assert run_check(net) == tr("update.malformed")
        assert net.calls == 1

        # ③-6 未决策 ⇒ 零 fetch，先征询；答「否」落 False、答「是」落 True（各只问一次）
        monkeypatch.setattr("acouscope.ui.main_window.QMessageBox", _FakeBox)
        state.save_state({})
        assert state.is_update_check_enabled() is None
        _FakeBox.built = 0
        _FakeBox.answer = _FakeBox.StandardButton.No
        net = _net(data={"version": "9999.0"})
        assert run_check(net) == tr("update.disabled")
        assert net.calls == 0
        assert state.is_update_check_enabled() is False
        assert _FakeBox.built == 1

        state.save_state({})
        _FakeBox.built = 0
        _FakeBox.answer = _FakeBox.StandardButton.Yes
        net = _net(data={"version": "9999.0", "notes_url": notes})
        run_check(net)
        assert state.is_update_check_enabled() is True
        assert net.calls == 1
        assert _FakeBox.built == 1

        # ③-8 二次运行不再弹；自动路径同日节流 ⇒ 零 fetch
        assert state.should_run_update_check() is True   # 占掉今日名额
        _FakeBox.built = 0
        net = _net(data={"version": "9999.0"})
        monkeypatch.setattr(uc, "urlopen", net)
        window._on_check_updates(manual=False)
        assert net.calls == 0
        assert _FakeBox.built == 0
    finally:
        window.close()


# ---------------------------------------------------------------------------
# ⑥ UP-2b：重入闸门（M-2）+ 自动路径启动挂载点（M-1）——判据③ 恰 2 例
# ---------------------------------------------------------------------------


def test_reentrancy_gate_blocks_second_worker(qapp, monkeypatch, tmp_path):
    """在飞闸门：连点两次只发一次请求；线程结束后放行（闸门不粘）。

    同步口径：``entered.wait(5)`` 只等「第一次请求已进入 urlopen」以证明在飞，
    **不** ``_settle``（不等待线程结束、不交付结果信号）；第二次调用发生在
    第一次仍在飞时。阻塞替身使「在飞」窗口确定，免调度竞态。
    """
    import threading
    import time

    monkeypatch.setenv("HOME", str(tmp_path))
    state.set_update_check_enabled(True)

    class _GatedNet(_Net):
        """urlopen 替身：进入即置位 ``entered``，并阻塞到 ``release`` 置位。"""

        def __init__(self):
            super().__init__(_Resp(b'{"version": "9999.0"}'))
            self.entered = threading.Event()
            self.release = threading.Event()

        def __call__(self, req, timeout=None):
            self.calls += 1
            self.requests.append(req)
            self.entered.set()
            self.release.wait(5)
            return self._resp

    net = _GatedNet()
    monkeypatch.setattr(uc, "urlopen", net)
    window = _window(qapp)
    try:
        window._on_check_updates(manual=True)      # 第一次：起 worker（在飞）
        assert net.entered.wait(5), "第一次请求应在飞（已进入 urlopen）"
        window._on_check_updates(manual=True)      # 第二次：闸门应静默拦下
        for _ in range(50):                        # ≤0.5s：仅判「是否误起第二请求」
            if net.calls > 1:
                break
            time.sleep(0.01)
        assert net.calls == 1
        net.release.set()
        _settle(window, qapp)                      # 线程结束 ⇒ isRunning() 放行
        window._on_check_updates(manual=True)      # 第三次：闸门不粘
        _settle(window, qapp)
        assert net.calls == 2
    finally:
        net.release.set()
        window.close()


def test_auto_update_mount_point(qapp, monkeypatch, tmp_path):
    """启动挂载点：showEvent 源序 + 常量错峰 + 自动路径语义（正反配对）。"""
    import inspect
    import re

    from acouscope.ui import main_window as mw

    # ⒜ 静态：showEvent 内挂载行引用新常量、走自动路径，且在错峰兄弟挂载之后
    # （既有正延迟挂载的常量名按源内首个 DELAY 常量动态取——本档在白名单外，
    #  禁写该功能 ASCII 字样，见 test_open_source_clean 白名单守卫）
    src = inspect.getsource(mw.MainWindow.showEvent)
    assert "_UPDATE_CHECK_DELAY_MS" in src
    assert "manual=False" in src
    prior = re.search(r"singleShot\((_[A-Z_]+_DELAY_MS)", src)
    assert prior is not None and prior.group(1) != "_UPDATE_CHECK_DELAY_MS"
    assert src.index("_UPDATE_CHECK_DELAY_MS") > src.index(prior.group(1))

    # ⒝ 常量：既有拍数为正延迟，且本件常量更大（错峰时间序）
    prior_delay = getattr(mw, prior.group(1))
    assert prior_delay > 0
    assert mw._UPDATE_CHECK_DELAY_MS > prior_delay

    # ⒞ 语义：开关开 + 未占当日名额 ⇒ 自动路径发起一次；同日二次 ⇒ 零 fetch
    monkeypatch.setenv("HOME", str(tmp_path))
    state.set_update_check_enabled(True)
    window = _window(qapp)
    try:
        net = _net(data={"version": "9999.0"})
        monkeypatch.setattr(uc, "urlopen", net)
        window._on_check_updates(manual=False)
        _settle(window, qapp)
        assert net.calls == 1
        net2 = _net(data={"version": "9999.0"})
        monkeypatch.setattr(uc, "urlopen", net2)
        window._on_check_updates(manual=False)
        assert net2.calls == 0
    finally:
        window.close()
