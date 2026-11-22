# SPDX-License-Identifier: GPL-3.0-only
"""G1：底轴单位错标修复判据（禁用 autoSIPrefix → 标题恒为「时间 (s)」）。

真机截图里底轴刻度为 0 / 0.05 / … / 0.45（秒），标题却是「时间 (ms)」：
AudacityTimeAxis 默认 autoSIPrefix=True，在 0–0.5 s 量级把 units 前缀自动
加 m；但本类 setTicks 提供的是 format_seconds 秒值字符串，pyqtgraph 不再
缩放刻度文字 ⇒ 单位与数值差 1000 倍。apply_time_axis 换轴后禁用该前缀。

变异：把 enableAutoSIPrefix(False) 改回 True（回退态）后，离屏实测只有
下列真齿翻红——「axis.autoSIPrefix is False」以及 setXRange(0, 0.5)
缩放后的「标题仍含 (s)」「标题不含 (ms)」两条（label 变「时间 (ms)」）；
这几条直接钉住 SI 前缀被禁用的修复点。其余都是守门型/描述性判据，
回退态仍绿、本身无齿：axis 类型、labelUnits=="s"、未缩放时的
(s)/(ms) 标题、刻度文字 == format_seconds(pos)、秒值小数仍在等，
只用于钉住恒定期望、防回归，不作本修复的独立真齿。
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

import pyqtgraph as pg

from acouscope.ui.widgets.time_axis import (
    AudacityTimeAxis,
    apply_time_axis,
    format_seconds,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def axis_plot(qapp):
    w = pg.PlotWidget()
    w.resize(900, 500)
    w.setLabel("bottom", "时间", units="s")
    apply_time_axis(w)
    w.show()
    qapp.processEvents()
    yield w
    w.close()


def test_auto_si_prefix_disabled_and_units_s(axis_plot):
    axis = axis_plot.getPlotItem().getAxis("bottom")
    assert isinstance(axis, AudacityTimeAxis)
    assert axis.autoSIPrefix is False
    assert axis.labelUnits == "s"
    label = axis.labelString()
    assert "(s)" in label
    assert "(ms)" not in label


def test_seconds_range_keeps_second_labels(axis_plot, qapp):
    axis = axis_plot.getPlotItem().getAxis("bottom")
    axis_plot.setXRange(0, 0.5, padding=0)
    qapp.processEvents()
    axis.refresh_ticks()
    label = axis.labelString()
    assert "(s)" in label, f"缩放后标题被加了 SI 前缀: {label}"
    assert "(ms)" not in label, f"缩放后标题被加了 SI 前缀: {label}"
    levels = axis._tickLevels
    assert levels and levels[0]
    for pos, text in levels[0]:
        assert text == format_seconds(pos)
    labels = [text for _, text in levels[0]]
    # 秒值小数仍在（未出现 50 / 100 / … 的千倍缩放毫秒值）
    assert any(x in labels for x in ("0.05", "0.1", "0.25", "0.5"))
    assert not any(x in ("50", "100", "150", "500") for x in labels)
