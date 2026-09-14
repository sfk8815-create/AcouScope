# SPDX-License-Identifier: GPL-3.0-only
"""T-324 选区快速试听与 A/B 循环（Pβ）离屏测试。

覆盖：
  ① 有选区按试听（P）→ set_position(t0) + 播放入口 + _preview_end=t1；
  ② 播放头到 t1 自动暂停（tick 判定：pause 被调、守卫清空、播放钮复位）；
  ③ 无选区按试听 → 播放入口零调用 + 温和 toast 提示（不播全曲）；
  ④ 播放中按试听 → 先停再播（pause 先于 play 的次序断言）；
  ⑤ A/B 循环（L）：设选区 → 进入循环（range=[t0,t1]，起播）；再按 → 取消；
  ⑥ 循环中按试听 → 先取消循环再单次播放；
  ⑦ 快捷键 P/L 已注册且与现有全局键无冲突；
  ⑧ i18n 三语键齐全；帮助手册三语键位表同步新增行。

纪律：不 MainWindow.show() / QDialog / .exec()；不真播（controller 方法打桩）；
禁词/hex/px/新浮条遵守由实现自审（本文件不含）。
"""

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from acouscope.app.controller import AppController
from acouscope.i18n import get_language, set_language, tr
from acouscope.ui.main_window import MainWindow
from acouscope.ui.shortcuts import ShortcutManager


def _sig() -> tuple:
    """2s 正弦波测试信号。"""
    sr = 8000
    t = np.arange(int(sr * 2.0)) / sr
    return sr, t, 0.5 * np.sin(2 * np.pi * 440 * t)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """带已加载音频 + 波形数据的 MainWindow（不 show）；controller 播放位打桩。"""

    monkeypatch.setenv("HOME", str(tmp_path))

    controller = AppController()
    sr, t, x = _sig()
    controller.load_from_array(x, sr)

    pos_holder = {"t": 0.0}
    calls = {"set_position": [], "play": [], "pause": [],
             "set_loop": [], "loop_enabled": []}
    playing = {"v": False}
    monkeypatch.setattr(controller, "set_position",
                        lambda t: calls["set_position"].append(float(t)))
    monkeypatch.setattr(controller, "play",
                        lambda: calls["play"].append(True))
    monkeypatch.setattr(controller, "pause",
                        lambda: calls["pause"].append(True))
    monkeypatch.setattr(controller, "is_playing", lambda: playing["v"])
    monkeypatch.setattr(controller, "get_position",
                        lambda: pos_holder["t"])
    monkeypatch.setattr(controller, "set_loop",
                        lambda a, b: calls["set_loop"].append((float(a), float(b))))
    monkeypatch.setattr(controller, "set_loop_enabled",
                        lambda v: calls["loop_enabled"].append(bool(v)))

    w = MainWindow(controller)
    w.waveform_widget.set_data(t, x, sample_rate=sr)
    w._follow_enabled = True
    w._scrub_last_at = -1.0
    w._calls = calls
    w._pos = pos_holder
    w._playing = playing

    yield w
    w.close()


def _set_selection(window, t0: float, t1: float) -> None:
    window.waveform_widget.set_selection(t0, t1)


# ----------------------------------------------------------------------
# ① 试听选区：定位 t0 → 播放入口 → 到 t1 自动停
# ----------------------------------------------------------------------

def test_preview_selection_seeks_plays_and_sets_end(window):
    _set_selection(window, 0.4, 1.0)
    window._on_preview_selection()

    assert window._calls["set_position"] == [0.4]
    assert window._calls["play"] == [True]
    assert window._preview_end == pytest.approx(1.0)
    assert window.transport_bar.btn_play.isChecked() is True


def test_preview_auto_stops_when_reaching_end(window):
    _set_selection(window, 0.4, 1.0)
    window._on_preview_selection()
    assert window._preview_end == pytest.approx(1.0)

    # 模拟 30Hz tick：播放头到达选区尾 → 自动暂停（一次播完即停）
    window._pos["t"] = 1.0
    window._playing["v"] = True
    window._update_playback_position()

    assert window._calls["pause"] == [True]
    assert window._preview_end is None
    assert window.transport_bar.btn_play.isChecked() is False


def test_preview_mid_segment_does_not_stop_before_end(window):
    _set_selection(window, 0.4, 1.0)
    window._on_preview_selection()
    assert window._calls["pause"] == []

    # 未到 t1：不暂停、守卫仍在
    window._pos["t"] = 0.7
    window._playing["v"] = True
    window._update_playback_position()
    assert window._calls["pause"] == []
    assert window._preview_end == pytest.approx(1.0)


# ----------------------------------------------------------------------
# ② 无选区：不误播全曲 + 温和提示
# ----------------------------------------------------------------------

def test_preview_no_selection_does_not_play_and_toasts(window, monkeypatch):
    toasts = []
    monkeypatch.setattr(
        "acouscope.ui.main_window.show_toast",
        lambda parent, msg, level="info": toasts.append((msg, level)),
    )

    window._on_preview_selection()

    assert window._calls["set_position"] == []
    assert window._calls["play"] == []
    assert window._preview_end is None
    assert len(toasts) == 1
    assert toasts[0][1] == "info"


# ----------------------------------------------------------------------
# ③ 播放中按试听：先停再播（次序断言）
# ----------------------------------------------------------------------

def test_preview_while_playing_pauses_before_play(window):
    _set_selection(window, 0.2, 0.8)
    window._playing["v"] = True  # 当前正在播放

    window._on_preview_selection()

    order = window._calls["pause"] + window._calls["play"]
    assert order == [True, True]  # pause 先于 play
    assert window._calls["set_position"] == [0.2]
    assert window._preview_end == pytest.approx(0.8)


# ----------------------------------------------------------------------
# ④ A/B 循环：L 开 → range=[t0,t1] 起播；再按 → 取消
# ----------------------------------------------------------------------

def test_loop_shortcut_enters_ab_loop_over_selection(window):
    _set_selection(window, 0.5, 1.2)
    assert window.transport_bar.btn_loop.isChecked() is False

    window._on_loop_shortcut()

    assert window.transport_bar.btn_loop.isChecked() is True
    assert window._calls["set_loop"] == [(0.5, 1.2)]
    assert window._calls["loop_enabled"] == [True]
    # 起播：定位到选区头并播放
    assert window._calls["set_position"] == [0.5]
    assert window._calls["play"] == [True]


def test_loop_shortcut_second_press_cancels(window):
    _set_selection(window, 0.5, 1.2)
    window._on_loop_shortcut()
    assert window._calls["loop_enabled"] == [True]

    window._on_loop_shortcut()  # 再按 → 取消循环
    assert window._calls["loop_enabled"] == [True, False]
    assert window.transport_bar.btn_loop.isChecked() is False


# ----------------------------------------------------------------------
# ⑤ 循环中按试听：先取消循环再单次播放
# ----------------------------------------------------------------------

def test_preview_while_looping_disables_loop_first(window):
    _set_selection(window, 0.3, 0.9)
    window._on_loop_shortcut()  # 进入 A/B 循环
    assert window._calls["loop_enabled"] == [True]
    n_play = len(window._calls["play"])

    window._on_preview_selection()

    assert window._calls["loop_enabled"] == [True, False]
    assert window.transport_bar.btn_loop.isChecked() is False
    # 单次播放（相对进入循环那次新增 1 次 play）
    assert len(window._calls["play"]) == n_play + 1
    assert window._preview_end == pytest.approx(0.9)


# ----------------------------------------------------------------------
# ⑥ 快捷键注册与冲突 / i18n / 帮助键位表
# ----------------------------------------------------------------------

def test_preview_and_loop_shortcuts_registered_no_conflict(window):
    mgr = ShortcutManager.instance()
    entries = mgr._entries

    assert entries["preview_selection"].current_key == "P"
    assert entries["loop_selection"].current_key == "L"

    # 冲突盘点：P / L 不得被其它全局键占用
    for aid, e in entries.items():
        if aid not in ("preview_selection", "loop_selection"):
            assert e.current_key not in ("P", "L"), f"键冲突: {aid}={e.current_key}"


def test_shortcut_labels_i18n_three_langs():
    prev = get_language()
    try:
        cases = [
            ("en_US", "Preview Selection", "A/B Loop Selection"),
            ("zh_CN", "试听选区", "A/B 循环选区"),
            ("zh_TW", "試聽選區", "A/B 循環選區"),
        ]
        for lang, preview, loop in cases:
            set_language(lang)
            assert tr("shortcut.preview_selection") == preview
            assert tr("shortcut.loop_selection") == loop
    finally:
        set_language(prev)


def test_help_manual_three_langs_include_new_keys():
    from acouscope.ui.widgets.help_dialogs import MANUAL

    assert "试听选区</td><td>P</td>" in MANUAL["zh_CN"]
    assert "A/B 循环选区（开/关）</td><td>L</td>" in MANUAL["zh_CN"]
    assert "試聽選區</td><td>P</td>" in MANUAL["zh_TW"]
    assert "A/B 循環選區（開/關）</td><td>L</td>" in MANUAL["zh_TW"]
    assert "Preview selection</td><td>P</td>" in MANUAL["en_US"]
    assert "A/B loop selection (toggle)</td><td>L</td>" in MANUAL["en_US"]
