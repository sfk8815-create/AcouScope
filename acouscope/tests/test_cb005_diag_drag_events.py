# SPDX-License-Identifier: GPL-3.0-only
"""CB-005 D3 诊断用例集（默认不收集：需 CB005_DIAG=1 显式运行）。

复现/对照对象：test_waveform_editing.py::test_drag_creates_selection 的全量回归
偶发 offscreen teardown 原生 segfault（GUI_backlog #15）。本文件只做对照实验
与事件路由探针，不改变任何标注交互语义、不触碰 src/：

  CB005_DIAG=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \\
      tests/test_cb005_diag_drag_events.py -v

分组：
  - 事件序列分解（②）：缺 release / move 零步进 / 双 press / 仅 move 等
  - teardown 时机（④）：close / deleteLater / 立即 GC / keepref 生命周期
  - eventFilter 手势路径探针（③）：观察 scrub 关闭时场景过滤器是否纯放行
配合 conftest 的 faulthandler 落栈（D1）在原生崩溃时把 Python 栈写入
内部运行日志 flaky_segfault.log。
"""

from __future__ import annotations

import gc

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QEvent, QObject, QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QMouseEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# 构造与事件注入辅助（与 test_waveform_editing.py 同一套手工 QMouseEvent 手法）
# ---------------------------------------------------------------------------


def _widget(qapp):
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


def _t_to_local(w, t):
    vb = w.plot_widget.plotItem.vb
    vr = vb.viewRect()
    scene = vb.mapViewToScene(QPointF(t, vr.top() + vr.height() * 0.5))
    local = w.plot_widget.mapFromScene(scene)
    return QPointF(local.x(), local.y())


def _send(qapp, w, etype, local, buttons, modifiers=None):
    modifiers = modifiers or Qt.KeyboardModifier.NoModifier
    g = w.plot_widget.mapToGlobal(local.toPoint())
    btn = (Qt.MouseButton.LeftButton if etype != QEvent.Type.MouseMove
           else Qt.MouseButton.NoButton)
    ev = QMouseEvent(
        etype, local, QPointF(g.x(), g.y()), btn, buttons, modifiers,
    )
    QApplication.sendEvent(w.plot_widget.viewport(), ev)
    qapp.processEvents()


def _run_seq(qapp, w, seq, t0=0.5, t1=1.5):
    """事件序列：baseline 之外包含省略/异常组合（诊断用，不复刻产品语义）。"""
    p0, p1 = _t_to_local(w, t0), _t_to_local(w, t1)
    pm = QPointF((p0.x() + p1.x()) / 2, p0.y())
    L = Qt.MouseButton.LeftButton
    N = Qt.MouseButton.NoButton
    if seq == "baseline":
        _send(qapp, w, QEvent.Type.MouseButtonPress, p0, L)
        _send(qapp, w, QEvent.Type.MouseMove, pm, L)
        _send(qapp, w, QEvent.Type.MouseMove, p1, L)
        _send(qapp, w, QEvent.Type.MouseButtonRelease, p1, N)
    elif seq == "norelease":  # 缺 release：拖拽态保持 open
        _send(qapp, w, QEvent.Type.MouseButtonPress, p0, L)
        _send(qapp, w, QEvent.Type.MouseMove, pm, L)
        _send(qapp, w, QEvent.Type.MouseMove, p1, L)
    elif seq == "zeromove":  # move 零步进：press 同点 release（=单击）
        _send(qapp, w, QEvent.Type.MouseButtonPress, p0, L)
        _send(qapp, w, QEvent.Type.MouseButtonRelease, p0, N)
    elif seq == "doublepress":  # 双 press（未 release 再次 press）
        _send(qapp, w, QEvent.Type.MouseButtonPress, p0, L)
        _send(qapp, w, QEvent.Type.MouseButtonPress, p1, L)
        _send(qapp, w, QEvent.Type.MouseButtonRelease, p1, N)
    elif seq == "movesonly":  # 无 press 直接 move（Qt 下按键态为空）
        _send(qapp, w, QEvent.Type.MouseMove, pm, L)
        _send(qapp, w, QEvent.Type.MouseMove, p1, L)
        _send(qapp, w, QEvent.Type.MouseButtonRelease, p1, N)
    else:
        raise ValueError(f"unknown seq {seq!r}")


def _seq_passed(qapp, w):
    """基线语义（对应真用例断言）：空白处拖拽建选区且红针不被挪动。"""
    pos0 = w.get_analysis_position()
    _run_seq(qapp, w, "baseline")
    sel = w.get_selection()
    assert sel is not None and abs(sel[0] - 0.5) < 0.1
    assert abs(sel[1] - 1.5) < 0.1
    assert abs(w.get_analysis_position() - pos0) < 1e-6


# ---------------------------------------------------------------------------
# ① 事件序列分解（② 实录嫌疑组合）
# ---------------------------------------------------------------------------


def test_diag_seq_baseline_green(qapp):
    w = _widget(qapp)
    _seq_passed(qapp, w)
    w.close()


def test_diag_seq_norelease_no_python_error(qapp):
    w = _widget(qapp)
    _run_seq(qapp, w, "norelease")
    # 拖拽态未 release：选区可能已部分建立；诊断只验证无 Python 异常且控件可正常收尾
    w.hide()
    w.close()


def test_diag_seq_zeromove_no_python_error(qapp):
    w = _widget(qapp)
    _run_seq(qapp, w, "zeromove")
    w.hide()
    w.close()


def test_diag_seq_doublepress_no_python_error(qapp):
    w = _widget(qapp)
    _run_seq(qapp, w, "doublepress")
    w.hide()
    w.close()


def test_diag_seq_movesonly_no_python_error(qapp):
    w = _widget(qapp)
    _run_seq(qapp, w, "movesonly")
    w.hide()
    w.close()


# ---------------------------------------------------------------------------
# ④ teardown 时机/顺序假设
# ---------------------------------------------------------------------------


def test_diag_teardown_deleteLater(qapp):
    w = _widget(qapp)
    _seq_passed(qapp, w)
    w.deleteLater()
    qapp.processEvents()


def test_diag_teardown_immediate_del_gc(qapp):
    w = _widget(qapp)
    _seq_passed(qapp, w)
    w.close()
    del w
    gc.collect()


def test_diag_teardown_noclose_del_gc(qapp):
    w = _widget(qapp)
    _seq_passed(qapp, w)
    del w
    gc.collect()


_KEEPREF_POOL = []


def test_diag_teardown_keepref_module_lifetime(qapp):
    # 故意不 close/del：由模块结束后的 Python GC 决定析构时机
    w = _widget(qapp)
    _seq_passed(qapp, w)
    _KEEPREF_POOL.append(w)


def test_diag_teardown_hide_then_close(qapp):
    w = _widget(qapp)
    _seq_passed(qapp, w)
    w.hide()
    w.close()


# ---------------------------------------------------------------------------
# ③ eventFilter 手势路径探针（测试侧观测，不改业务）
# ---------------------------------------------------------------------------


class _CountingFilter(QObject):
    """观测用事件过滤器：只计数，不拦截（return False 原样放行）。"""

    def __init__(self, tag):
        super().__init__()
        self.tag = tag
        self.seen = []

    def eventFilter(self, obj, ev):
        self.seen.append(int(ev.type()))
        return False


def test_diag_eventfilter_passive_when_scrub_off(qapp):
    """scrub 关闭时挂在 scene 的 WaveformWidget.eventFilter 不参与拖拽手势。"""
    w = _widget(qapp)
    scene = w.plot_widget.scene()
    assert w.btn_scrub.isChecked() is False  # 目标用例从不开 scrub

    f = _CountingFilter("scene-probe")
    scene.installEventFilter(f)
    _seq_passed(qapp, w)
    scene.removeEventFilter(f)

    seen_types = set(f.seen)
    # GraphicsSceneMouse* 已被过滤器观察到 → 过滤器收到事件但只放行（否则拖拽不会成功）
    assert QEvent.Type.GraphicsSceneMousePress in seen_types
    assert QEvent.Type.GraphicsSceneMouseRelease in seen_types
    assert w.get_selection() is not None  # 手势仍生效 → 过滤器确为纯观测
    w.close()
