# SPDX-License-Identifier: GPL-3.0-only
"""CB-010 P0-1：波形单击定位回归测试（CB-016-1 改写版）。

原版覆盖“分析区块显/隐两态”的单击定位/拖拽语义；CB-016-1 移除蓝条全链后，
区块显隐维度不复存在，统一为“波形空白区单击定位播放头 / 拖拽建选区 /
双击全选”。本文件改写保留存续行为断言：
  ① 单击（press+release 事件对）→ playheadSeek 恰一次且 playhead=点击秒数
  ② 拖拽建选区（拖选 release 后选区不被吞）
  ③ 双击仍全选

P3/P4 事件对细节（拖选尾随 click 吞噬等）见 test_cb016_waveform_event_pairs.py。
"""

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from acouscope.ui.widgets.waveform import WaveformWidget


def _make_widget(qapp):
    """已 set_data 的 WaveformWidget（无蓝条叠加层）。"""
    w = WaveformWidget()
    w.resize(1200, 400)
    w.show()
    sr, n = 1000, 5000
    t = np.arange(n, dtype=np.float32) / np.float32(sr)
    x = (0.3 * np.sin(2 * np.pi * 10 * t)).astype(np.float32)
    w.set_data(t, x, sample_rate=sr)
    qapp.processEvents()
    return w


def _t_to_local(w, t: float) -> QPointF:
    """数据时间 → 波形视口局部坐标（像素）。"""
    vb = w.plot_widget.plotItem.vb
    vr = vb.viewRect()
    scene = vb.mapViewToScene(QPointF(t, vr.top() + vr.height() * 0.5))
    return QPointF(w.plot_widget.mapFromScene(scene))


def _send(qapp, w, etype, local, buttons):
    """向波形 viewport 注入 QMouseEvent（参照 test_waveform_editing 手法）。"""
    g = w.plot_widget.mapToGlobal(local.toPoint())
    L = Qt.MouseButton.LeftButton
    btn = L if etype != QEvent.Type.MouseMove else Qt.MouseButton.NoButton
    ev = QMouseEvent(
        etype, local, QPointF(g.x(), g.y()), btn, buttons,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(w.plot_widget.viewport(), ev)
    qapp.processEvents()


def _click(qapp, w, t):
    """纯单击（press+release 事件对：press 带 LeftButton，release 无按键）。"""
    p = _t_to_local(w, t)
    L = Qt.MouseButton.LeftButton
    _send(qapp, w, QEvent.Type.MouseButtonPress, p, L)
    _send(qapp, w, QEvent.Type.MouseButtonRelease, p, Qt.MouseButton.NoButton)


def _drag(qapp, w, t0, t1):
    """拖拽（press→move→release）。"""
    p0, p1 = _t_to_local(w, t0), _t_to_local(w, t1)
    pm = QPointF((p0.x() + p1.x()) / 2, p0.y())
    L = Qt.MouseButton.LeftButton
    _send(qapp, w, QEvent.Type.MouseButtonPress, p0, L)
    _send(qapp, w, QEvent.Type.MouseMove, pm, L)
    _send(qapp, w, QEvent.Type.MouseMove, p1, L)
    _send(qapp, w, QEvent.Type.MouseButtonRelease, p1, Qt.MouseButton.NoButton)


def test_single_click_seeks_playhead_once(qapp):
    """① 单击事件对 → playheadSeek 恰一次，playhead 落在点击秒数上。"""
    w = _make_widget(qapp)
    try:
        seen = []
        w.playheadSeek.connect(lambda v: seen.append(v))
        _click(qapp, w, 3.5)
        assert len(seen) == 1, f"playheadSeek 未恰一次触发（seen={seen}）"
        assert abs(w.playhead.value() - 3.5) < 0.05, (
            f"playhead={w.playhead.value():.3f} ≠ 点击 3.5"
        )
        # 单击不误判为双击：不得全选
        assert w.get_selection() is None
    finally:
        w.close()


def test_drag_creates_selection_and_not_swallowed(qapp):
    """② 拖拽建选区；release 后选区保持（P3/P4：拖选后不被尾随 click 吞掉）。"""
    w = _make_widget(qapp)
    try:
        seen = []
        w.selectionChanged.connect(lambda s: seen.append(s))
        _drag(qapp, w, 2.2, 3.6)
        sel = w.get_selection()
        assert sel is not None, "拖拽应建选区"
        assert abs(sel[0] - 2.2) < 0.1 and abs(sel[1] - 3.6) < 0.1
        assert len(seen) == 1, f"selectionChanged 应恰一次（seen={seen}）"
    finally:
        w.close()


def test_double_click_still_selects_all(qapp):
    """③ 双击仍全选（红针/选区交互不受 P3/P4 修复影响）。"""
    w = _make_widget(qapp)
    try:
        _click(qapp, w, 2.0)
        _click(qapp, w, 2.02)
        sel = w.get_selection()
        assert sel is not None and sel[0] <= 0.01 and sel[1] >= 4.99
    finally:
        w.close()
