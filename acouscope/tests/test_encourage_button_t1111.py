# SPDX-License-Identifier: GPL-3.0-only
"""T-1111 守卫：主窗常驻「支持一下」心跳按钮（新增 3 例）。

- 例1：图文并存形态（QToolButton 默认 IconOnly 会吞文字）+ 三语 i18n 键齐备；
- 例2：反无限循环（loopCount≠0 且有限）+ 尺寸纪律（恒定占位 / 峰值上界）；
- 例3：主窗接线端到端（行内序在 LOGO 左侧 / 点击后同源开框且框可见）。

纪律：全离屏，不展示主窗口顶层（承既有赞助框测试纪律）；
白名单铁律 ⇒ 本档**零**禁忌字面（见 test_open_source_clean 白名单）。
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QAbstractAnimation, QSize, Qt
from PyQt6.QtWidgets import QDialog, QToolButton

from acouscope.i18n import available_languages, get_language, set_language, tr
from acouscope.ui.widgets import encourage_button as eb
from acouscope.ui.widgets.encourage_button import EncourageButton


# ---------------------------------------------------------------------------
# ① 形态：图文并存 + i18n
# ---------------------------------------------------------------------------


def test_text_beside_icon_and_i18n_keys(qapp):
    btn = EncourageButton()
    assert isinstance(btn, QToolButton)
    # QToolButton 默认 IconOnly 会把文字吞掉不可见 ⇒ 必须显式图文并存（只看 text() 会被骗）
    assert btn.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    assert btn.text() == tr("encourage.label")
    assert btn.toolTip() == tr("encourage.tip")
    assert btn.icon().isNull() is False

    lang_backup = get_language()
    try:
        for key in ("encourage.label", "encourage.tip"):
            for lang in available_languages():
                set_language(lang)
                assert tr(key), f"{key} 在 {lang} 为空"
        set_language("zh_CN")
        assert tr("encourage.label") == "支持一下"
    finally:
        set_language(lang_backup)


# ---------------------------------------------------------------------------
# ② 心跳有限性 + 尺寸纪律
# ---------------------------------------------------------------------------


def test_finite_pulse_and_size_discipline(qapp):
    btn = EncourageButton()
    # 反无限循环：Alternate 方向下 Qt 语义 loopCount==0 即永久 ⇒ 必有限
    assert btn._anim.loopCount() != 0
    assert btn._anim.loopCount() in (eb._PULSE_LOOPS, eb._HOVER_LOOPS)
    assert btn._anim.duration() == eb._PULSE_MS
    assert float(btn._anim.startValue()) == eb._ICON_BASE_PX
    assert float(btn._anim.endValue()) <= 20  # 峰值上界

    # ★ 波形形状（T-1111a）：必须「一放一收」——start==end==基线、半程恰为峰值。
    #   反例=锯齿（start=16/end=20 ⇒ 到峰瞬间弹回基线，观感是「啪地弹」不是心跳）。
    assert int(btn._anim.startValue()) == int(btn._anim.endValue()) == eb._ICON_BASE_PX
    assert int(btn._anim.keyValueAt(0.5)) == eb._ICON_PEAK_PX
    btn._anim.setCurrentTime(eb._PULSE_MS // 2)
    assert round(float(btn._anim.currentValue())) == eb._ICON_PEAK_PX
    # 平滑性：10ms 步进扫三圈，单步落差必 ≤1px（无瞬弹），且确曾回到基线
    scan = []
    for t_ms in range(0, eb._PULSE_MS * eb._PULSE_LOOPS + 1, 10):
        btn._anim.setCurrentTime(t_ms)
        scan.append(round(float(btn._anim.currentValue())))
    assert max(b - a for a, b in zip(scan, scan[1:])) <= 1, f"存在瞬弹：{scan}"
    assert min(scan) == eb._ICON_BASE_PX and max(scan) == eb._ICON_PEAK_PX

    # 恒定占位：setIconSize 逐帧变化不得改变外接矩形（防整行横向抖动）
    assert btn.width() == eb._BTN_W_PX
    assert btn.height() <= 28
    assert btn.minimumSize() == btn.maximumSize()
    assert btn.iconSize() == QSize(eb._ICON_BASE_PX, eb._ICON_BASE_PX)

    # 悬停一次 = 有限 loopCount，且可停
    btn._start_pulse(eb._HOVER_LOOPS)
    assert btn._anim.loopCount() == 1
    btn._anim.stop()
    assert btn._anim.state() == QAbstractAnimation.State.Stopped


# ---------------------------------------------------------------------------
# ③ 主窗接线端到端
# ---------------------------------------------------------------------------


@pytest.fixture
def window(qapp, tmp_path):
    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 0.5)) / sr
    controller.load_from_array(0.5 * np.sin(2 * np.pi * 200 * t), sr)
    w = MainWindow(controller)
    yield w
    w.close()


def test_wiring_left_of_logo_and_click_opens_dialog(window):
    btn = window.btn_encourage
    assert isinstance(btn, EncourageButton)
    assert btn.icon().isNull() is False
    assert btn.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    assert btn.text() == tr("encourage.label")
    assert btn.height() <= 28

    # 行内索引序：按钮在 LOGO 左侧
    row_layout = btn.parentWidget().layout()
    idx_btn = row_layout.indexOf(btn)
    assert idx_btn >= 0, "按钮未入提示条行"
    logo = getattr(window, "lbl_logo", None)
    if logo is not None:
        assert idx_btn < row_layout.indexOf(logo), "按钮须在 LOGO 左侧"

    # 接线在工具栏构建段内（槽复用既有单一入口，非新写开框函数）
    toolbar_src = inspect.getsource(type(window)._create_toolbar)
    assert "encourageRequested.connect(" in toolbar_src

    # 点击 ⇒ 信号触发 + 新框可见（非模态）
    before = {id(d) for d in window.findChildren(QDialog)}
    hits = []
    btn.encourageRequested.connect(lambda: hits.append(1))
    btn.click()
    assert hits == [1]
    new = [d for d in window.findChildren(QDialog) if id(d) not in before]
    assert len(new) == 1, "点击未产生新框"
    dlg = new[0]
    assert dlg.isVisible() is True
    assert dlg.isModal() is False
    assert dlg.parent() is window

    # 同源硬证：再点一次复用**同一实例**（既有入口的单实例复用语义）
    btn.click()
    again = [d for d in window.findChildren(QDialog) if id(d) not in before]
    assert len(again) == 1 and again[0] is dlg
