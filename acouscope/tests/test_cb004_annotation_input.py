# SPDX-License-Identifier: GPL-3.0-only
"""CB-004 D11 波形标注标签输入去模态测试。

覆盖锚点：
- W-1/W-2/W-3：waveform.py 内原生模态文本输入调用 = 0（源码扫描）；
  区域/时间点标注经非模态 popover（Qt.Popup，QWidget/QFrame）提交才创建。
- 交互语义：回车提交 / Esc 取消 / 失焦（隐藏）提交 / 空标签=可留空。
- 全部结构特征断言（isinstance / windowFlags / 标注字段），离屏运行，
  不构造 MainWindow、不 show() 主窗；禁硬编码绝对像素几何断言。
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QLineEdit, QWidget

from acouscope.ui.widgets.waveform import _LabelPopover, WaveformWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_widget(qapp) -> WaveformWidget:
    w = WaveformWidget()
    w.resize(900, 300)
    sr = 44100
    duration = 2.0
    t = np.linspace(0, duration, int(sr * duration))
    signal = np.sin(2 * np.pi * 440 * t) * np.exp(-t * 0.5)
    w.set_data(t, signal, sample_rate=sr)
    w.show()
    qapp.processEvents()
    return w


def _active_popover(w) -> _LabelPopover:
    pop = getattr(w, "_label_popover", None)
    assert pop is not None, "预期存在打开的标签输入 popover"
    return pop


class TestAnnotationLabelInputNonModal:
    """D11 收口：标签输入由原生模态输入改为非模态 popover。"""

    def test_waveform_source_has_no_modal_text_input(self):
        """源码扫描：QInputDialog = 0（含 import 清理，W-1/W-2/W-3 锚点）。"""
        import acouscope.ui.widgets.waveform as wf
        from pathlib import Path

        src = Path(wf.__file__).read_text(encoding="utf-8")
        assert "QInputDialog" not in src
        # 唯一阻塞调用须为白名单右键菜单（K2/QMenu）
        lines = src.splitlines()
        for i, line in enumerate(lines, 1):
            if ".exec(" in line:
                assert "menu.exec" in line, f"L{i} 出现非白名单 .exec("

    def test_region_label_input_is_non_modal_popover(self, qapp):
        """W-1：右键触发区域标注 → 原位非模态输入框（禁 QDialog/.exec）。"""
        w = _make_widget(qapp)
        assert not w.annotations.regions  # 输入前未创建（提交才创建）

        w._add_region_at(0.5)
        pop = _active_popover(w)

        # 结构特征：非模态 popover（QWidget 系 + Qt.Popup + QLineEdit），禁 QDialog
        assert isinstance(pop, QWidget)
        assert isinstance(pop, _LabelPopover)
        assert not isinstance(pop, QDialog)
        assert bool(pop.windowFlags() & Qt.WindowType.Popup)
        assert isinstance(pop.edit, QLineEdit)
        assert not w.annotations.regions  # 仍等待用户输入

        # 输入标签并回车 → 仅此时才创建区域
        pop.edit.setText("verse")
        QTest.keyClick(pop.edit, Qt.Key.Key_Return)
        regions = w.annotations.regions
        assert len(regions) == 1
        region = regions[0]
        assert region.label == "verse"
        assert region.start_time < 0.5 < region.end_time
        # 提交后引用清理（同一时刻最多一个输入框）
        assert getattr(w, "_label_popover", None) is None

    def test_region_commit_selects_region_and_notifies(self, qapp):
        """W-1：区域提交后选中并走 region_selected_callback（与旧行为一致）。"""
        w = _make_widget(qapp)
        selected = []
        w.region_selected_callback = selected.append

        w._add_region_at(1.0)
        pop = _active_popover(w)
        QTest.keyClick(pop.edit, Qt.Key.Key_Return)  # 空标签提交 = 可留空
        assert w.annotations.regions
        assert w.selected_region() is w.annotations.regions[0]
        assert selected and selected[-1] is w.annotations.regions[0]

    def test_instant_label_input_esc_cancels_then_commit(self, qapp):
        """W-2：时间点标注 Esc 取消不创建；回车提交才创建。"""
        w = _make_widget(qapp)
        assert not w.annotations.instants

        w._add_instant_at(0.8)
        pop = _active_popover(w)
        assert isinstance(pop, QWidget) and not isinstance(pop, QDialog)
        pop.edit.setText("cancel-me")
        QTest.keyClick(pop, Qt.Key.Key_Escape)  # Esc 取消
        assert not w.annotations.instants
        assert getattr(w, "_label_popover", None) is None

        # 重新触发（仍由右键入口方法驱动）并输入提交
        w._add_instant_at(0.8)
        pop = _active_popover(w)
        pop.edit.setText("onset")
        QTest.keyClick(pop.edit, Qt.Key.Key_Return)
        instants = w.annotations.instants
        assert len(instants) == 1
        assert abs(instants[0].time - 0.8) < 1e-9
        assert instants[0].label == "onset"

    def test_focus_out_hides_and_commits(self, qapp):
        """方案 A 语义：失焦（点击外部隐藏）即提交；空标签可留空。"""
        w = _make_widget(qapp)
        w._add_region_at(1.0)
        pop = _active_popover(w)
        pop.edit.setText("   ")  # 全空白 = 留空
        pop.hide()  # 模拟失焦自动关闭
        assert not getattr(w, "_label_popover", None)  # hideEvent 提交后清理
        regions = w.annotations.regions
        assert len(regions) == 1
        assert regions[0].label == ""
