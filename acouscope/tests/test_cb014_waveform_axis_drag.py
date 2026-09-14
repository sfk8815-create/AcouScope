# SPDX-License-Identifier: GPL-3.0-only
"""CB-014-1：波形拖轴 TypeError 回归测试（真机日志 2026-09-07）。

根因：pyqtgraph 0.13.7 AxisItem.mouseDragEvent 以
``viewbox.mouseDragEvent(ev, axis=1)``（左右轴）或 ``axis=0``（顶底轴）委托
ViewBox；WaveformWidget 以实例属性补丁把 vb.mouseDragEvent 替换为
_vb_mouse_drag，但原签名 ``(self, ev)`` 无 axis 形参 → 拖时间轴即 TypeError。

修复：签名改 ``def _vb_mouse_drag(self, ev, axis=None)``；函数体最前增分支——
``axis is not None`` 时直接委托 _vb_orig_drag(ev, axis=axis)（原 ViewBox 单轴
缩放/平移），不进波形选区/定位逻辑；axis=None 路径（建选区/微拖=单击定位）零改动。

覆盖验收（离屏，参照 test_cb010_playhead_seek 构造模式）：
  ① 签名 inspect 断言接受 axis 关键字、默认 None
  ② 拖轴（axis=0/1）委托 _vb_orig_drag(ev, axis=…)，不抛 TypeError
  ③ axis=None 单击定位语义仍在（微拖=单击 → playheadSeek）
  ④ axis=None 拖动建选区语义仍在（蓝条移除后 selection 为唯一拖拽模式）

CB-016-1 改写：蓝条移除，原“隐藏区块内起手拖”表述改为通用“空白处拖拽”。
"""

import inspect

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from acouscope.ui.widgets.waveform import WaveformWidget


def _make_widget(qapp):
    """已 set_data 的 WaveformWidget（蓝条移除后无叠加层）。"""
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
    """纯单击（press+release 同点，无移动无按住）。"""
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


def _inside_t(w) -> float:
    """交互测试用固定点击点（蓝条移除后不再有区块区间概念）。"""
    return 2.5


def test_signature_accepts_axis_keyword(qapp):
    """① 签名接受 axis 关键字（AxisItem 委托调用兼容），默认 None。"""
    w = WaveformWidget()
    try:
        params = inspect.signature(w._vb_mouse_drag).parameters
        assert "axis" in params, "签名缺 axis 形参（拖轴 TypeError 根因）"
        assert params["axis"].default is None, "axis 默认须为 None（波形区路径不变）"
    finally:
        w.close()


@pytest.mark.parametrize("axis", [0, 1])
def test_axis_drag_delegates_to_original_vb(qapp, monkeypatch, axis):
    """② 拖轴（axis=0 顶/底、axis=1 左/右）→ 委托 _vb_orig_drag(ev, axis=…)。"""
    w = WaveformWidget()
    try:
        calls = []
        monkeypatch.setattr(
            w, "_vb_orig_drag",
            lambda ev, axis=None: calls.append((ev, axis)),
        )
        ev = object()  # 委托路径不解析事件属性：只验证分派不抛 TypeError
        w._vb_mouse_drag(ev, axis=axis)
        assert calls == [(ev, axis)], (
            f"axis={axis} 未按契约委托 _vb_orig_drag(ev, axis={axis})"
        )
    finally:
        w.close()


def test_axis_none_click_still_seeks_playhead(qapp):
    """③ axis=None 单击语义零回归：空白处单击 → playheadSeek + playhead 定位。"""
    w = _make_widget(qapp)
    try:
        seen = []
        w.playheadSeek.connect(lambda v: seen.append(v))
        t = _inside_t(w)
        _click(qapp, w, t)
        assert len(seen) == 1, f"playheadSeek 未触发（seen={seen}）"
        assert abs(w.playhead.value() - t) < 0.05, (
            f"playhead={w.playhead.value():.3f} ≠ 点击 {t:.3f}"
        )
    finally:
        w.close()


def test_axis_none_drag_still_builds_selection(qapp):
    """④ axis=None 拖动语义零回归：空白处拖拽 → 建选区。"""
    w = _make_widget(qapp)
    try:
        _drag(qapp, w, 2.2, 3.6)
        sel = w.get_selection()
        assert sel is not None, "axis=None 拖动应建选区"
        assert abs(sel[0] - 2.2) < 0.1 and abs(sel[1] - 3.6) < 0.1, f"选区={sel}"
    finally:
        w.close()
