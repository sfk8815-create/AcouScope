# SPDX-License-Identifier: GPL-3.0-only
"""CB-006（#15 C2）：WaveformWidget 析构收尾测试。

覆盖 E2 验收口径：
  ① 构造 WaveformWidget → close → processEvents → 本控件 addItem 的全部
     scene item 已移出场景（scene() is None）、控件存活不崩、属性仍可读；
  ② 进程内连续构造/close/析构 50 次，exit 0（无原生崩溃）；
  ③ 全程 offscreen（conftest 顶部已设 QT_QPA_PLATFORM=offscreen）、
     不构造 MainWindow、不 show MainWindow、无 QDialog/.exec()。

说明：close() 只隐藏窗口不销毁 widget，pyqtgraph 内建的场景骨架
（PlotItem/ViewBox/AxisItem/ChildGroup 等）必然仍在场景中，故不断言
『scene item 总数=0』，而断言『本控件 addItem 的全部 scene item 已移出』
（这是 E2 验收『或 widget 已销毁不崩』更精确的等价物；见报告 deviations）。
"""

from __future__ import annotations

import gc

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from acouscope.ui.widgets.waveform import WaveformWidget  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_widget():
    """构造一个已载数据的顶层 WaveformWidget（不 show，留给用例决定）。"""
    w = WaveformWidget()
    w.resize(900, 300)
    sr, n = 1000, 5000
    t = np.arange(n, dtype=np.float32) / np.float32(sr)
    x = (0.3 * np.sin(2 * np.pi * 10 * t)).astype(np.float32)
    w.set_data(t, x, sample_rate=sr)
    return w


def _managed_items(w):
    """本控件 addItem 进场景的全部 item（base 5 + 标注区域/时间点登记）。

    CB-016-1：蓝条已移除，base 由 6 项降为 5 项。
    """
    items = [
        w.curve,
        w.zero_line,
        w.analysis_cursor,
        w.selection_item,
        w.playhead,
    ]
    items += list(w._region_items.values())
    items += list(w._instant_items.values())
    return items


class TestWaveformCloseCleanup:
    def test_close_detaches_all_managed_scene_items(self, qapp):
        w = _make_widget()
        # 加一条区域 + 一个时间点标注，验证标注 item 也进收尾路径
        region = w.add_region(1.0, 2.0, label="r")
        w.add_instant(1.5, label="i")
        w.show()
        qapp.processEvents()

        managed = _managed_items(w)
        assert len(managed) >= 7  # 5 base + 1 region + 1 instant
        scene = w.plot_widget.scene()
        assert all(it.scene() is scene for it in managed)

        # 关闭：收尾应把全部自管 item 移出场景，且控件存活不崩
        assert w.close() is True
        qapp.processEvents()

        assert all(it.scene() is None for it in managed)
        assert all(it not in scene.items() for it in managed)
        # 控件/属性仍可读（close 仅收尾，不销毁、不置 None）
        assert isinstance(w.get_analysis_position(), float)
        assert region.start_time == 1.0
        assert w.isHidden()  # close 已隐藏窗口

    def test_close_idempotent_and_second_close_safe(self, qapp):
        w = _make_widget()
        w.show()
        qapp.processEvents()
        managed = _managed_items(w)
        assert all(it.scene() is not None for it in managed)

        w.close()
        qapp.processEvents()
        # 重复 close 不抛、不清坏状态
        assert w.close() is True
        qapp.processEvents()
        w.close()
        qapp.processEvents()
        assert all(it.scene() is None for it in managed)

    def test_fifty_construct_close_destroy_cycles_exit_zero(self, qapp):
        """进程内连续 50 次构造→close→析构，无崩溃即 pass。"""
        for _ in range(50):
            w = _make_widget()
            w.add_region(1.0, 2.0, label="r")
            w.show()
            qapp.processEvents()
            assert w.close() is True
            qapp.processEvents()
            w.deleteLater()
            qapp.processEvents()
            del w
        gc.collect()
        qapp.processEvents()
