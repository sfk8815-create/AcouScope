# SPDX-License-Identifier: GPL-3.0-only
"""CB-016b hotfix：事件面回归测试（pyqtgraph 单击 release 单派发 / 双击 / 拖选）。

真机根因（CB-016b 契约，架构师探针实证，2026-09-07）：
  ① pyqtgraph MouseClickEvent 无 isFinish()（那是 DragEvent 的 API），旧守卫
     每个单击都抛 AttributeError 被 pyqtgraph try/except 吞 → 单击/双击全废；
  ② 旧吞噬 flag 前提错误：pyqtgraph 仅对 press 后无 drag 的 release 派发一次
     mouseClickEvent；拖选序列（press→move→release）的 finish 走
     mouseDragEvent、不发尾随 click → 旧 flag 永无消费方，残留吞掉下一次真单击。

修复（waveform._vb_mouse_click / _vb_mouse_drag）：
  ① 删除 isFinish 守卫与吞噬 flag——单击天然只在 release 派发一次；
  ② 拖选 finish 后释放无尾随 click，无需吞 flag；微拖（手抖）当单击定位。

测试口径（需求说明强制）：事件对注入——press 带 buttons=LeftButton、
release 带 buttons=NoButton，经 QApplication.sendEvent 走 Qt 层注入
（单事件合成测不出本回归，参照 test_cb014_waveform_axis_drag 先例）。
"""

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from acouscope.ui.widgets.waveform import WaveformWidget


def _make_widget(qapp):
    """已 set_data 的 WaveformWidget（5s 正弦波）。"""
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
    """向波形 viewport 注入 QMouseEvent（Qt 层事件对口径）。"""
    g = w.plot_widget.mapToGlobal(local.toPoint())
    L = Qt.MouseButton.LeftButton
    btn = L if etype != QEvent.Type.MouseMove else Qt.MouseButton.NoButton
    ev = QMouseEvent(
        etype, local, QPointF(g.x(), g.y()), btn, buttons,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(w.plot_widget.viewport(), ev)
    qapp.processEvents()


def _click_pair(qapp, w, t):
    """单击事件对：press（buttons=LeftButton）+ release（buttons=NoButton）。"""
    p = _t_to_local(w, t)
    L = Qt.MouseButton.LeftButton
    _send(qapp, w, QEvent.Type.MouseButtonPress, p, L)
    _send(qapp, w, QEvent.Type.MouseButtonRelease, p, Qt.MouseButton.NoButton)


def _drag_pair(qapp, w, t0, t1):
    """拖选事件对：press → move×2 → release（buttons 逐段为 LeftButton/NoButton）。"""
    p0, p1 = _t_to_local(w, t0), _t_to_local(w, t1)
    pm = QPointF((p0.x() + p1.x()) / 2, p0.y())
    L = Qt.MouseButton.LeftButton
    _send(qapp, w, QEvent.Type.MouseButtonPress, p0, L)
    _send(qapp, w, QEvent.Type.MouseMove, pm, L)
    _send(qapp, w, QEvent.Type.MouseMove, p1, L)
    _send(qapp, w, QEvent.Type.MouseButtonRelease, p1, Qt.MouseButton.NoButton)


def test_click_event_pair_seeks_exactly_once_no_select_all(qapp):
    """① 单击事件对 → playheadSeek 恰一次、不误判双击（无全选）。"""
    w = _make_widget(qapp)
    try:
        seen = []
        w.playheadSeek.connect(lambda v: seen.append(v))
        _click_pair(qapp, w, 3.5)
        assert len(seen) == 1, f"单击应恰一次 playheadSeek（seen={seen}）"
        assert abs(w.playhead.value() - 3.5) < 0.05
        # P3/P4 核心：press+release 双触发不得让单击变成双击全选
        assert w.get_selection() is None, "单击被误判为双击（全选）"
    finally:
        w.close()


def test_drag_event_pair_selects_once_not_swallowed_on_release(qapp):
    """② 拖选事件对 → selectionChanged 恰一次、release 不吞选区。"""
    w = _make_widget(qapp)
    try:
        seen = []
        w.selectionChanged.connect(lambda s: seen.append(s))
        _drag_pair(qapp, w, 0.5, 1.5)
        sel = w.get_selection()
        assert sel is not None, "拖选应建选区"
        assert abs(sel[0] - 0.5) < 0.1 and abs(sel[1] - 1.5) < 0.1
        # P3/P4：拖选后的尾随 click 不得把选区吞掉/清空
        values = [v for v in seen if v is not None]
        assert len(values) == 1, f"selectionChanged 应恰一次非空（seen={seen}）"
    finally:
        w.close()


def test_drag_then_click_seeks_once_and_clears_selection(qapp):
    """③ 拖选后紧跟单击 → playheadSeek 恰一次新位置、选区清除。

    CB-016b 探针④口径：pyqtgraph 拖选 release 不发尾随 click，旧吞噬 flag
    残留（永无消费方）会吞掉下一次真单击——本断言防该类残留回潮。
    """
    w = _make_widget(qapp)
    try:
        seen = []
        w.playheadSeek.connect(lambda v: seen.append(v))
        _drag_pair(qapp, w, 0.5, 1.5)
        assert w.get_selection() is not None, "前置：拖选应已建选区"
        _click_pair(qapp, w, 2.5)
        assert len(seen) == 1, f"拖选后单击应恰一次 playheadSeek（seen={seen}）"
        assert abs(w.playhead.value() - 2.5) < 0.05, (
            f"playhead={w.playhead.value():.3f} ≠ 新位置 2.5"
        )
        assert w.get_selection() is None, "拖选后单击应清除选区"
    finally:
        w.close()


def _make_downsampled_widget(qapp):
    """降采样形态 WaveformWidget：10000 点峰值包络跨 ~10s（44.1kHz 长文件）。

    复刻 controller.get_waveform(max_points=10000) 输出形态：
    times=arange(10000)*44/44100（跨全时长）、data 仅 10000 点。
    旧误算（点数÷采样率）= 10000/44100 ≈ 0.227s。
    """
    w = WaveformWidget()
    w.resize(1200, 400)
    w.show()
    sr, n_out, step = 44100, 10000, 44
    t = (np.arange(n_out) * step / sr).astype(np.float32)
    x = (0.3 * np.sin(2 * np.pi * 10 * t)).astype(np.float32)
    w.set_data(t, x, sample_rate=sr)
    qapp.processEvents()
    return w


def test_clamp_t_downsampled_uses_full_duration(qapp):
    """P3 回归①：降采样形态下 _clamp_t 上界=times[-1]（~10s），
    不得用点数÷采样率误算成 0.227s。"""
    w = _make_downsampled_widget(qapp)
    try:
        got = w._clamp_t(5.0)
        assert abs(got - 5.0) < 1e-6, (
            f"_clamp_t(5.0)={got:.4f} 被钳到 {got:.3f}s"
            "（旧误算 10000/44100≈0.227s，应跨全时长）"
        )
        # 越界值夹到 times[-1]（~9.999s）而非 0.227s
        assert abs(w._clamp_t(99.0) - float(w._times[-1])) < 1e-3
    finally:
        w.close()


def test_single_click_downsampled_seeks_past_0227s(qapp):
    """P3 回归②：降采样形态单击 5s 处 → playheadSeek=5.0（不被钳到 0.227s）。"""
    w = _make_downsampled_widget(qapp)
    try:
        seen = []
        w.playheadSeek.connect(lambda v: seen.append(v))
        _click_pair(qapp, w, 5.0)
        assert len(seen) == 1, f"单击应恰一次 playheadSeek（seen={seen}）"
        assert abs(seen[0] - 5.0) < 0.05, (
            f"playheadSeek={seen[0]:.4f} ≠ 5.0（被钳到 0.227s？）"
        )
    finally:
        w.close()


def test_double_click_downsampled_selects_full_duration(qapp):
    """P3 回归③：降采样形态双击全选 → 选区=[0, ~10s] 全时长（非 [0, 0.227s]）。"""
    w = _make_downsampled_widget(qapp)
    try:
        _click_pair(qapp, w, 5.0)
        _click_pair(qapp, w, 5.0)  # 同位置第二次单击 → 双击全选
        sel = w.get_selection()
        assert sel is not None, "双击应全选"
        assert abs(sel[0]) < 1e-3, f"选区起点应为 0（sel={sel}）"
        assert sel[1] > 9.0, (
            f"选区终点={sel[1]:.4f} 应≈全时长 ~10s"
            "（旧误算 len(times)/sr≈0.227s）"
        )
    finally:
        w.close()


def test_micro_drag_2px_seeks_once_no_selection(qapp):
    """④ 微拖 2px（手抖）→ 当单击：playheadSeek 恰一次定位、无选区残留。

    CB-016b 探针⑥口径：拖动幅度 < 视宽 0.4% 的微拖按单击处理，不得留下选区。
    """
    w = _make_widget(qapp)
    try:
        seen = []
        w.playheadSeek.connect(lambda v: seen.append(v))
        p0 = _t_to_local(w, 2.5)
        p1 = QPointF(p0.x() + 2.0, p0.y())  # 2px 手抖
        L = Qt.MouseButton.LeftButton
        _send(qapp, w, QEvent.Type.MouseButtonPress, p0, L)
        _send(qapp, w, QEvent.Type.MouseMove, p1, L)
        _send(qapp, w, QEvent.Type.MouseButtonRelease, p1, Qt.MouseButton.NoButton)
        assert len(seen) == 1, f"微拖应恰一次 playheadSeek（seen={seen}）"
        assert abs(w.playhead.value() - 2.5) < 0.1, (
            f"playhead={w.playhead.value():.3f} ≠ 微拖起点 2.5"
        )
        assert w.get_selection() is None, "微拖不得留下选区"
    finally:
        w.close()
