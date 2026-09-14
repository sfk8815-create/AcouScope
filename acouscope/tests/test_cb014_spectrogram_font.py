# SPDX-License-Identifier: GPL-3.0-only
"""CB-014-2：3D 谱图表字体刻度路径回归测试（真机日志 2026-09-07）。

根因：matplotlib 3.10.9 已移除 Axis.get_major_ticks；spectrogram3d.py
_apply_chart_font 原对 ax.xaxis/yaxis/zaxis 与 colorbar.ax 调 get_major_ticks()
取 Tick 再 set label1/label2 → AttributeError，被外层 try/except 吞为 warning，
3D 图字体设置静默失效。

修复：两处改 ``axis.get_majorticklabels()``（返回 Text 列表直接
set_fontfamily）；色条侧用 ``self._colorbar.ax.yaxis.get_majorticklabels()``。

口径说明（最小修复）：get_majorticklabels() 返回主轴主（下/左）侧刻度标签；
原 label1/label2 双标签中的 label2（上/右）侧默认不显示、非本波范围，主侧恢复
字体设置即达标。

覆盖验收（离屏，参照 tests/test_spectrogram3d.py fixture）：
  ① set_chart_font 全路径（render 内自动 _apply_chart_font）不抛、无告警
  ② caplog 无 'get_major_ticks' 引用（遗留 API 若在会以 warning 形式出现）
  ③ 3D 主轴主侧刻度 + 色条 y 轴刻度 Text 的 fontfamily == font_chain 目标链
"""

import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("matplotlib")

from PyQt6.QtWidgets import QApplication

from acouscope.ui.widgets.spectrogram3d import Spectrogram3DWidget

SR = 44100


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def widget(qapp):
    w = Spectrogram3DWidget()
    w.resize(1000, 600)
    yield w
    w.close()


def _harmonic_tone(dur=3.0, f0=440.0):
    """含 4 次谐波的稳定乐音。"""
    t = np.arange(int(SR * dur)) / SR
    sig = np.zeros_like(t)
    for k in (1, 2, 3, 4):
        sig += 0.5 / k * np.sin(2 * np.pi * f0 * k * t)
    return sig


def test_chart_font_applies_to_major_tick_labels(widget, caplog):
    """set_chart_font 全路径：不触 get_major_ticks，主侧刻度字体链生效。"""
    from acouscope.visualization.mpl_style import font_chain

    widget.set_audio(_harmonic_tone(), SR)
    widget.cmb_mode.setCurrentIndex(0)  # 曲面模式 → render 建 colorbar

    # acouscope 根 logger propagate=False（utils/log.py），须对目标子 logger 捕获
    with caplog.at_level(logging.WARNING,
                         logger="acouscope.ui.widgets.spectrogram3d"):
        widget.set_chart_font("Arial", "Songti SC")  # 公开路径：render 内 _apply_chart_font
        widget.canvas.draw()                          # 布局出实际刻度 Text 集合
        widget._apply_chart_font(widget.ax_3d)        # 对最终刻度集确定性重放（防首绘时 tick 尚未物化）

    assert not any("get_major_ticks" in r.message for r in caplog.records), (
        f"仍触已移除的 get_major_ticks：{[r.message for r in caplog.records]}"
    )
    assert not any("操作失败" in r.message for r in caplog.records), (
        f"字体应用路径出现告警：{[r.message for r in caplog.records]}"
    )

    chain = font_chain("Arial", "Songti SC")

    # 3D 主轴主侧刻度标签（结构性断言：Text 的 fontfamily == 应用链，禁几何硬编码）
    assert widget.ax_3d.xaxis.get_majorticklabels(), "x 轴主侧刻度标签为空"
    for axis in (widget.ax_3d.xaxis, widget.ax_3d.yaxis, widget.ax_3d.zaxis):
        for lab in axis.get_majorticklabels():
            assert lab.get_fontfamily() == chain, (
                f"{axis.axis_name} 刻度字体链未生效: {lab.get_fontfamily()}"
            )

    # 色条 y 轴刻度标签（CB-014-2 修复第二处）
    assert widget._colorbar is not None
    cbar_labels = widget._colorbar.ax.yaxis.get_majorticklabels()
    assert cbar_labels, "色条 y 轴主侧刻度标签为空"
    for lab in cbar_labels:
        assert lab.get_fontfamily() == chain, (
            f"色条刻度字体链未生效: {lab.get_fontfamily()}"
        )
