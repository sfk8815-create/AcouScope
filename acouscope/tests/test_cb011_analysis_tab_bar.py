# SPDX-License-Identifier: GPL-3.0-only
"""CB-011 B-1：功能区横向标签卡（替代原分析工具栏功能区下拉）。

覆盖验收：
  ① 结构：analysis_panel 内容区左下方存在 analysis_tab_bar（QTabBar），
     7 标签顺序严格 波形→FFT→频谱→音高→共振峰→音色→3D（双语 tr，同 cmb.* key 序）；
  ② 切换：点击标签（setCurrentIndex 等价信号驱动）→ view_container 切对应页
     （currentWidget/currentIndex 断言）+ _sync_transport_visibility 同步触发；
  ③ 状态源单一：标签 currentChanged 仍为唯一切换入口（不经旧下拉框）。

断言纪律：offscreen 全程；不 MainWindow.show() / QDialog / .exec()；
几何断言不落硬编码绝对像素（currentIndex 一律 indexOf 换算）。
CB-016-1 改写：原 CB-009 蓝条叠加层显隐断言随蓝条移除整删，
改为断言传输条（_sync_transport_visibility，存续行为）。
T-906 语义变更：传输条全局化（跨视图常驻），显隐断言一律改正向（恒可见）。
CB-016b 审计修正：显隐断言一律用 isHidden()（非 isVisible）——offscreen 全程
不 MainWindow.show()，isVisible() 要求顶层窗口已 show 恒为 False；isHidden()
只反映显式 setVisible 状态，与窗口是否 show 无关，才是正确断言口径。
"""

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QTabBar

from acouscope.app.controller import AppController
from acouscope.i18n import tr
from acouscope.ui.main_window import MainWindow

# 7 个逻辑视图的 i18n key（与 main_window.analysis_tab_bar / 导航器同序）
_VIEW_KEYS = (
    "cmb.waveform",
    "cmb.fft",
    "cmb.spectrogram",
    "cmb.pitch",
    "cmb.formants",
    "cmb.timbre",
    "cmb.spectrogram3d",
)


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
    """带已加载音频 + 波形数据的 MainWindow（不 show）；teardown close。"""

    monkeypatch.setenv("HOME", str(tmp_path))

    controller = AppController()
    sr, t, x = _sig()
    controller.load_from_array(x, sr)
    w = MainWindow(controller)
    w.waveform_widget.set_data(t, x, sample_rate=sr)
    yield w
    w.close()


def _stub_build_views(window):
    """把懒构建替换为轻量登记：每视图仅向堆叠器加一个占位 QWidget。

    只喂结构路径，不触发真实分析计算；等价断言切换/传输条显隐接线。
    """
    def _fake_build(index: int) -> None:
        page = QApplication.instance() and __import__("PyQt6.QtWidgets", fromlist=["QWidget"]).QWidget()
        page.setObjectName(f"fakeView{index}")
        window._view_widgets[index] = page
        window.view_container.addWidget(page)
        window.view_container.setCurrentWidget(page)

    window._build_analysis_view = _fake_build


def test_analysis_tab_bar_seven_tabs_in_order(window):
    """验收①：analysis_tab_bar 为 QTabBar，7 标签顺序与 cmb.* 视图 key 一致。"""
    tabs = window.analysis_tab_bar
    assert isinstance(tabs, QTabBar)
    assert tabs.count() == 7
    assert [tabs.tabText(i) for i in range(7)] == [tr(k) for k in _VIEW_KEYS]
    # 父容器 = analysis_panel（内容区左下方，view_container 下方）
    assert tabs.parent() is window.analysis_panel


def test_tab_click_switches_view_and_syncs_transport(window, qapp):
    """验收②③：点击标签 → view_container 切对应页 + 传输条恒可见（T-906）。"""
    _stub_build_views(window)
    # 初始 index0 波形视图 → 传输条可见。
    # isHidden 口径（非 isVisible）：本测试纪律不 MainWindow.show()，isVisible()
    # 要求顶层窗口已 show 恒为 False；isHidden() 只反映显式 setVisible 状态，
    # 与窗口是否 show 无关，故用它断言 _sync_transport_visibility 的落点。
    assert not window.transport_bar.isHidden()

    # 点击 FFT（index=1）→ 页面切到该视图 + 传输条仍可见（T-906 全局化）
    window.analysis_tab_bar.setCurrentIndex(1)
    qapp.processEvents()
    assert window.analysis_tab_bar.currentIndex() == 1
    page = window.view_container.currentWidget()
    assert page is window._view_widgets[1]
    assert window.view_container.currentIndex() == window.view_container.indexOf(page)
    assert not window.transport_bar.isHidden(), "T-906：分析视图下传输条应常驻可见"

    # 切回波形（index=0）→ 页面切到波形视图 + 传输条仍可见
    window.analysis_tab_bar.setCurrentIndex(0)
    qapp.processEvents()
    assert window.analysis_tab_bar.currentIndex() == 0
    page0 = window.view_container.currentWidget()
    assert page0 is window._view_widgets[0]
    assert window.view_container.currentIndex() == window.view_container.indexOf(page0)
    assert not window.transport_bar.isHidden()

    # 再开语谱图（index=2）→ 传输条仍可见（状态不被 index0 往返破坏）
    window.analysis_tab_bar.setCurrentIndex(2)
    qapp.processEvents()
    assert window.view_container.currentWidget() is window._view_widgets[2]
    assert not window.transport_bar.isHidden(), "T-906：语谱图视图下传输条应常驻可见"


def test_tab_current_synced_by_set_analysis_view_on_restore(window, qapp, tmp_path):
    """验收③：_restore_view_index 恢复路径 → _set_analysis_view 同步标签选中。"""
    from acouscope.audio.io import AudioInfo

    def _info():
        return AudioInfo(
            filepath="synthetic.wav", duration=2.0, sample_rate=8000,
            channels=1, samples=int(8000 * 2), bit_depth=16,
            format="WAV", file_size=0,
        )

    # 首次同步（无持久化）：_restore_view_index None → 按下拉/标签 0 构建
    assert window._restore_view_index is None
    window._sync_after_open(_info())
    qapp.processEvents()
    assert window.analysis_tab_bar.currentIndex() == 0

    # 设置上次视图 = 音高(3)，再走一次 D 路径 → 标签同步选中 3
    window._restore_view_index = 3
    window._sync_after_open(_info())
    qapp.processEvents()
    assert window._restore_view_index is None  # 单次消费
    assert window.analysis_tab_bar.currentIndex() == 3  # _set_analysis_view 同步标签卡
