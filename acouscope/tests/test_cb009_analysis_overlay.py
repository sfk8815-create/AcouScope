# SPDX-License-Identifier: GPL-3.0-only
"""CB-016-1 改写：原 CB-009 蓝条显隐测试随蓝条移除整删。

蓝条实体与其全部方法链（显隐开关 / 空态显隐 / 咬合防反馈等）已移除，相应
显隐/三样式断言对应功能不复存在（功能删除逐项归因见 CB-016 报告）。本文件
改写为红针/分析位置的存续语义断言：
  ① 空态/加载态红针位置 set/get 语义存续（空数据守卫、加载后位置可读写）；
  ② 越界位置钳制（既有红针行为，与蓝条无耦合）；
  ③ set_analysis_position(emit=True) → analysisPositionChanged 信号触发
     （CB-016-3 新信号，防死信号回潮）。
"""

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from acouscope.ui.widgets.waveform import WaveformWidget


def _sig() -> tuple:
    """2s 正弦波测试信号。"""
    sr = 8000
    t = np.arange(int(sr * 2.0)) / sr
    return sr, t, 0.5 * np.sin(2 * np.pi * 440 * t)


def test_set_position_empty_data_guard_and_load_roundtrip(qapp):
    """空数据 set_analysis_position 守卫返回；加载后位置可读写（存续语义）。"""
    sr, t, x = _sig()
    w = WaveformWidget()
    try:
        # 空态守卫：不抛且不移动（位置线保持 0）
        w.set_analysis_position(0.5)
        assert w.get_analysis_position() == pytest.approx(0.0)

        w.set_data(t, x, sample_rate=sr)
        # 加载后默认指针 = 中点 1.0
        assert w.get_analysis_position() == pytest.approx(1.0, abs=0.01)
        w.set_analysis_position(1.25, emit=False)
        assert w.get_analysis_position() == pytest.approx(1.25, abs=1e-6)
    finally:
        w.close()


def test_position_clamp_out_of_range(qapp):
    """越界位置钳到数据范围（既有红针钳制语义，CB-016-1 后存续）。"""
    sr, t, x = _sig()
    w = WaveformWidget()
    try:
        w.set_data(t, x, sample_rate=sr)
        w.set_analysis_position(99.0, emit=False)
        assert w.get_analysis_position() <= 2.0 + 1e-6
        w.set_analysis_position(-5.0, emit=False)
        assert w.get_analysis_position() >= 0.0 - 1e-6
    finally:
        w.close()


def test_set_position_emits_analysis_changed_signal(qapp):
    """set_analysis_position(emit=True) → analysisPositionChanged 恰一次。"""
    sr, t, x = _sig()
    w = WaveformWidget()
    try:
        w.set_data(t, x, sample_rate=sr)
        got = []
        w.analysisPositionChanged.connect(got.append)
        w.set_analysis_position(1.5)
        assert got == [1.5], f"信号应恰 emit 一次（got={got}）"
    finally:
        w.close()
