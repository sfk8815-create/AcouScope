# SPDX-License-Identifier: GPL-3.0-only
"""波形编辑与选区交互测试。"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from acouscope.audio.editing import Clipboard, EditError, EditingController  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# 编辑核心
# ---------------------------------------------------------------------------

class TestEditingController:
    def setup_method(self):
        self.ed = EditingController()
        self.sr = 1000
        self.data = np.ones(10, dtype=np.float32)

    def test_copy_requires_selection(self):
        with pytest.raises(EditError):
            self.ed.copy(self.data, self.sr, None)

    def test_cut_delete_silence_trim(self):
        sel = (0.002, 0.005)
        assert len(self.ed.cut(self.data, self.sr, sel)) == 7
        assert len(self.ed.delete(self.data, self.sr, sel)) == 7
        silenced = self.ed.silence(self.data, self.sr, sel)
        assert np.allclose(silenced[:2], 1) and np.allclose(silenced[2:5], 0)
        assert len(self.ed.trim(self.data, self.sr, sel)) == 3

    def test_paste_and_undo_redo(self):
        self.ed.copy(self.data, self.sr, (0.002, 0.005))
        pasted = self.ed.paste(self.data, self.sr, 0.0)
        assert len(pasted) == 13
        assert len(self.ed.undo(pasted, self.sr)) == 10
        assert len(self.ed.redo(self.data, self.sr)) == 13

    def test_clipboard_resample(self):
        cb = Clipboard()
        cb.put(np.ones(10, dtype=np.float32), 1000)
        assert len(cb.get(2000)) == 20
        assert len(cb.get(500)) == 5

    def test_history_limit(self):
        ed = EditingController(history_limit=2)
        d = self.data
        for i in range(5):
            d = ed.silence(d, self.sr, (0.0, 0.004))
        assert ed.can_undo()
        n_undo = 0
        while ed.can_undo():
            d = ed.undo(d, self.sr)
            n_undo += 1
        assert n_undo == 2


# ---------------------------------------------------------------------------
# 波形控件：选区 / 咬合 / 夹取
# ---------------------------------------------------------------------------

class TestWaveformSelection:
    def _widget(self, qapp):
        from acouscope.ui.widgets.waveform import WaveformWidget

        w = WaveformWidget()
        w.resize(900, 300)
        sr = 1000
        n = 5000
        t = np.arange(n, dtype=np.float32) / np.float32(sr)
        x = (0.3 * np.sin(2 * np.pi * 10 * t)).astype(np.float32)
        w.set_data(t, x, sample_rate=sr)
        return w

    def test_selection_roundtrip(self, qapp):
        w = self._widget(qapp)
        assert w.get_selection() is None
        w.set_selection(2.5, 1.0)   # 乱序自动纠正
        assert w.get_selection() == (1.0, 2.5)
        w.clear_selection()
        assert w.get_selection() is None

    def test_selection_clamps_to_duration(self, qapp):
        w = self._widget(qapp)
        w.set_selection(3.0, 99.0)
        # 夹取到时长 5.0（覆盖最后一个采样），而非末采样点 4.999
        assert w.get_selection() == (3.0, 5.0)

    def test_analysis_position_roundtrip_and_clamp(self, qapp):
        # CB-016 迁移（原 test_cb009/test_analysis_region_drag 蓝条专属用例删除后，
        # 红针 set/get 钳制语义为存续行为，归入本存续文件）：
        w = self._widget(qapp)
        w.set_analysis_position(2.0, emit=False)
        assert abs(w.get_analysis_position() - 2.0) < 1e-6
        # 越界位置钳到数据范围（红针既有钳制语义，与蓝条无关）
        w.set_analysis_position(99.0, emit=False)
        assert abs(w.get_analysis_position() - 5.0) < 0.01
        w.set_analysis_position(-3.0, emit=False)
        assert abs(w.get_analysis_position() - 0.0) < 0.01

    def test_cursor_not_movable_by_default(self, qapp):
        w = self._widget(qapp)
        assert w.analysis_cursor.movable is False

    def test_zoom(self, qapp):
        w = self._widget(qapp)
        w.set_selection(1.0, 2.0)
        w.zoom_to_selection()
        x0, x1 = w.plot_widget.viewRange()[0]
        assert abs(x0 - 1.0) < 0.1 and abs(x1 - 2.0) < 0.1
        w.zoom_fit()
        x0, x1 = w.plot_widget.viewRange()[0]
        assert abs(x0) < 0.01 and abs(x1 - 5.0) < 0.05


class TestWaveformMouseInteraction:
    """真实 QMouseEvent 注入的交互测试。

    注意：pyqtgraph GraphicsScene 只在 move 事件携带按键状态时才派发
    拖动（QTest.mouseMove 不带按钮），必须手工构造 QMouseEvent。
    """

    def _widget(self, qapp):
        from acouscope.ui.widgets.waveform import WaveformWidget

        w = WaveformWidget()
        w.resize(900, 300)
        w.show()
        sr, n = 1000, 5000
        t = np.arange(n, dtype=np.float32) / np.float32(sr)
        x = (0.3 * np.sin(2 * np.pi * 10 * t)).astype(np.float32)
        w.set_data(t, x, sample_rate=sr)
        qapp.processEvents()
        return w

    @staticmethod
    def _t_to_local(w, t):
        from PyQt6.QtCore import QPointF

        vb = w.plot_widget.plotItem.vb
        vr = vb.viewRect()
        scene = vb.mapViewToScene(QPointF(t, vr.top() + vr.height() * 0.5))
        local = w.plot_widget.mapFromScene(scene)
        return QPointF(local.x(), local.y())

    def _send(self, qapp, w, etype, local, buttons,
              modifiers=None):
        from PyQt6.QtCore import QEvent, QPointF, Qt
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtWidgets import QApplication

        modifiers = modifiers or Qt.KeyboardModifier.NoModifier
        g = w.plot_widget.mapToGlobal(local.toPoint())
        ev = QMouseEvent(
            etype, local, QPointF(g.x(), g.y()),
            Qt.MouseButton.LeftButton if etype != QEvent.Type.MouseMove
            else Qt.MouseButton.NoButton,
            buttons, modifiers,
        )
        QApplication.sendEvent(w.plot_widget.viewport(), ev)
        qapp.processEvents()

    def _drag(self, qapp, w, t0, t1, modifiers=None):
        from PyQt6.QtCore import QEvent, QPointF, Qt

        p0, p1 = self._t_to_local(w, t0), self._t_to_local(w, t1)
        pm = QPointF((p0.x() + p1.x()) / 2, p0.y())
        self._send(qapp, w, QEvent.Type.MouseButtonPress, p0,
                   Qt.MouseButton.LeftButton, modifiers)
        self._send(qapp, w, QEvent.Type.MouseMove, pm,
                   Qt.MouseButton.LeftButton, modifiers)
        self._send(qapp, w, QEvent.Type.MouseMove, p1,
                   Qt.MouseButton.LeftButton, modifiers)
        self._send(qapp, w, QEvent.Type.MouseButtonRelease, p1,
                   Qt.MouseButton.NoButton, modifiers)

    def _click(self, qapp, w, t):
        from PyQt6.QtCore import QEvent, Qt

        p = self._t_to_local(w, t)
        self._send(qapp, w, QEvent.Type.MouseButtonPress, p,
                   Qt.MouseButton.LeftButton)
        self._send(qapp, w, QEvent.Type.MouseButtonRelease, p,
                   Qt.MouseButton.NoButton)

    def test_drag_creates_selection(self, qapp):
        # 任意空白处拖拽建选区（蓝条已移除，拖拽不再有分析窗边缘/整体移动分支）
        w = self._widget(qapp)
        pos0 = w.get_analysis_position()
        self._drag(qapp, w, 0.5, 1.5)
        sel = w.get_selection()
        assert sel is not None and abs(sel[0] - 0.5) < 0.1
        assert abs(sel[1] - 1.5) < 0.1
        assert abs(w.get_analysis_position() - pos0) < 1e-6
        w.close()

    def test_drag_outside_region_creates_selection(self, qapp):
        # 拖拽建选区（红针不被无 Shift 拖拽移动）
        w = self._widget(qapp)
        pos0 = w.get_analysis_position()
        self._drag(qapp, w, 0.5, 1.5)
        sel = w.get_selection()
        assert sel is not None
        assert abs(w.get_analysis_position() - pos0) < 1e-6
        w.close()

    def test_click_positions_playhead(self, qapp):
        w = self._widget(qapp)
        w.set_selection(1.0, 2.0)
        self._click(qapp, w, 4.0)
        assert abs(w.playhead.value() - 4.0) < 0.05
        assert w.get_selection() is None
        w.close()

    def test_double_click_selects_all(self, qapp):
        w = self._widget(qapp)
        self._click(qapp, w, 2.0)
        self._click(qapp, w, 2.02)
        sel = w.get_selection()
        assert sel is not None and sel[0] <= 0.01 and sel[1] >= 4.99
        w.close()

    def test_shift_drag_moves_cursor(self, qapp):
        from PyQt6.QtCore import Qt

        w = self._widget(qapp)
        w.set_analysis_position(2.0, emit=False)
        self._drag(qapp, w, 2.0, 3.0, Qt.KeyboardModifier.ShiftModifier)
        assert abs(w.get_analysis_position() - 3.0) < 0.1
        w.close()

    def test_drag_without_shift_does_not_move_cursor(self, qapp):
        # 无 Shift 拖拽建选区，红针不动
        w = self._widget(qapp)
        pos0 = w.get_analysis_position()
        self._drag(qapp, w, 0.5, 1.5)
        assert w.get_selection() is not None
        assert abs(w.get_analysis_position() - pos0) < 0.01
        w.close()
