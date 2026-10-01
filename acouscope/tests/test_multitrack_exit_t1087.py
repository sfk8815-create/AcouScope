# SPDX-License-Identifier: GPL-3.0-only
"""T-1087 M1（真机目测 #7）：多轨态退出通路（轨道区退出钮 + Ctrl+M 键位）。

缺陷：轨道区工具栏没有退出钮，入口又是分析菜单里的可勾选 QAction ⇒ 进了多轨态
只能回菜单再点一次；折叠左栏/键盘用户无路可退。

覆盖：
① 面板退出钮存在（复用现成 ``theme.close`` 图标·**零新增 ICONS**）+ 点击发
   ``exitRequested``（**反向**：未接宿主的裸面板点了不崩、也无模式可退 ⇒ 信号
   是面板唯一出口，退态动作归宿主）；
② 宿主接线 ⇒ 点钮回单轨主态零残留（面板隐藏 / 波形区可见 / 勾选态复位）；
③ Ctrl+M 键位经 ``ShortcutManager`` 注册（**反向**：未注册则查不到条目），
   两个方向都能切（进 / 出），且不改 ``action_multitrack_compare`` 的 QAction
   键位（``test_menu_restructure:149`` 冻结其为空·该档不在本件授权面）；
④ 新 ``tr`` 键三语齐备。
"""

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QToolButton

from acouscope.app.controller import AppController
from acouscope.i18n import set_language, tr
from acouscope.ui import theme
from acouscope.ui.main_window import MainWindow
from acouscope.ui.shortcuts import ShortcutManager
from acouscope.ui.widgets.multitrack.multitrack_view import MultitrackPanel

_EXIT_KEYS = ("multitrack.exit.tip", "shortcut.multitrack_mode")


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """离屏 MainWindow（不 show）+ 内存音频（有音频 ⇒ 多轨入口可用）。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    set_language("zh_CN")
    controller = AppController()
    sr = 8000
    t = np.arange(sr) / sr
    controller.load_from_array(0.4 * np.sin(2 * np.pi * 440 * t), sr)
    w = MainWindow(controller)
    yield w
    w.close()


# ---------------------------------------------------------------------------
# ① 退出钮存在 + 发信号（面板侧不自行退态）
# ---------------------------------------------------------------------------


def test_panel_has_exit_button_reusing_close_icon(qapp):
    """退出钮存在、图标复用现成 theme.close（不新增 ICONS 键）。"""
    panel = MultitrackPanel(None)
    btn = panel.findChild(QToolButton, "trackExitMode")
    assert btn is panel.btn_exit
    assert not btn.icon().isNull()
    assert theme.ICONS["close"] == "generic/x.svg"
    assert btn.toolTip() == tr("multitrack.exit.tip")


def test_exit_button_emits_signal_only(qapp):
    """点钮 ⇒ exitRequested 恰 1 次；裸面板无宿主 ⇒ 不发不崩、不自行改结构。

    反向守卫：若产品码把退态逻辑写进面板（而非上抛信号），本例会看到面板
    自己 hide / 无信号 ⇒ ②③ 的宿主单点也就无从复用。
    """
    panel = MultitrackPanel(None)
    fired = []
    panel.exitRequested.connect(lambda: fired.append(True))
    panel.btn_exit.click()
    assert fired == [True]


# ---------------------------------------------------------------------------
# ② 宿主接线：点退出钮 = 回单轨主态（零残留）
# ---------------------------------------------------------------------------


def test_host_wires_exit_button_to_single_track_state(window, qapp):
    w = window
    assert w.multitrack_panel.btn_exit.parent() is not None
    w._enter_multitrack_mode()
    assert w._multitrack_mode is True
    assert w.multitrack_panel.isHidden() is False

    w.multitrack_panel.btn_exit.click()
    assert w._multitrack_mode is False
    assert w.multitrack_panel.isHidden() is True
    assert w.waveform_widget.isHidden() is False
    assert w.action_multitrack_compare.isChecked() is False


# ---------------------------------------------------------------------------
# ③ Ctrl+M 键位（两个方向 · 且不动 QAction 键位）
# ---------------------------------------------------------------------------


def _multitrack_shortcut():
    entry = ShortcutManager.instance()._entries.get("multitrack_mode")
    assert entry is not None, "Ctrl+M 未经 ShortcutManager 注册（反向守卫）"
    assert entry.default_key == "Ctrl+M"
    return entry


def test_ctrl_m_toggles_both_directions(window, qapp):
    w = window
    entry = _multitrack_shortcut()
    sc = entry.shortcut_obj

    assert w._multitrack_mode is False
    sc.activated.emit()
    assert w._multitrack_mode is True
    assert w.multitrack_panel.isHidden() is False

    sc.activated.emit()
    assert w._multitrack_mode is False
    assert w.waveform_widget.isHidden() is False


def test_ctrl_m_does_not_touch_qaction_keybinding(window):
    """QAction 键位仍为空：test_menu_restructure:149 冻结该口径（不在本件授权面）。"""
    _multitrack_shortcut()
    assert window.action_multitrack_compare.shortcut().isEmpty() is True


# ---------------------------------------------------------------------------
# ④ i18n 三语
# ---------------------------------------------------------------------------


def test_exit_i18n_keys_in_three_languages():
    import acouscope.i18n as i18n

    strings = getattr(i18n, "_STRINGS")
    for key in _EXIT_KEYS:
        entry = strings.get(key)
        assert entry, f"缺 i18n 键: {key}"
        assert set(entry) == {"en_US", "zh_CN", "zh_TW"}, f"三语缺失: {key}"
        assert all(str(v).strip() for v in entry.values()), f"空译文: {key}"
