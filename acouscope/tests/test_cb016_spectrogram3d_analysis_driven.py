# SPDX-License-Identifier: GPL-3.0-only
"""CB-016-4：3D 频谱图改分析位置驱动（main_window 接线）。

契约（需求说明）：_build_spectrogram3d 在 widget.set_audio 后以分析位置为中心调
widget.set_time_range(pos-half, pos+half)——half=帧宽/2（与分析窗口语义一致），
帧宽不可得时回退 ±2.0s；pointer_getter 既有接线保留；spectrogram3d.py 零改动。
"""

import inspect

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QWidget

from acouscope.ui.main_window import MainWindow


class _FakeS3D(QWidget):
    """记录调用的 Spectrogram3DWidget 替身（不触发真实 STFT/渲染）。"""

    def __init__(self):
        super().__init__()
        self.pointer_getter = None
        self.time_ranges = []
        self.data = None
        self.sr = None

    @property
    def segment(self):
        return self.time_ranges[-1] if self.time_ranges else (0.0, 0.1)

    @property
    def cmb_mode(self):
        class _Mode:
            @staticmethod
            def currentText():
                return "fake-mode"
        return _Mode()

    def set_audio(self, data, sample_rate):
        self.data = data
        self.sr = sample_rate

    def set_time_range(self, start, end):
        self.time_ranges.append((float(start), float(end)))


def _make_window(qapp, monkeypatch, tmp_path):
    """带已加载音频的 MainWindow（不 show，替身 3D 控件；teardown close）。"""
    from acouscope.app.controller import AppController

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        "acouscope.ui.widgets.spectrogram3d.Spectrogram3DWidget", _FakeS3D
    )

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 2.0)) / sr
    x = 0.5 * np.sin(2 * np.pi * 440 * t)
    controller.load_from_array(x, sr)
    w = MainWindow(controller)
    w.waveform_widget.set_data(t, x, sample_rate=sr)
    return w


def test_build_spectrogram3d_centers_on_analysis_position(qapp, monkeypatch, tmp_path):
    """分析位置驱动：set_time_range(pos±half)，half=帧宽/2（默认 1.0/2=0.5）。"""
    w = _make_window(qapp, monkeypatch, tmp_path)
    try:
        w._build_spectrogram3d(w._analysis_gen)
        fake = w._spectrogram3d_widget
        assert isinstance(fake, _FakeS3D)
        assert fake.pointer_getter is not None
        # 2s 信号 → 红针默认中点 1.0，帧宽 1.0 → half 0.5 → [0.5, 1.5]
        assert fake.time_ranges, "未调用 set_time_range"
        start, end = fake.time_ranges[-1]
        assert start == pytest.approx(0.5, abs=0.01)
        assert end == pytest.approx(1.5, abs=0.01)
        assert fake.sr == 8000
    finally:
        w.close()


def test_build_spectrogram3d_falls_back_to_2s(qapp, monkeypatch, tmp_path):
    """帧宽不可得（get_frame_size 异常）→ 回退 ±2.0s。"""
    w = _make_window(qapp, monkeypatch, tmp_path)
    try:
        def _boom():
            raise RuntimeError("frame size unavailable")

        monkeypatch.setattr(w.waveform_widget, "get_frame_size", _boom)
        w._build_spectrogram3d(w._analysis_gen)
        fake = w._spectrogram3d_widget
        start, end = fake.time_ranges[-1]
        # 位置 1.0 ± 2.0 → [-1.0, 3.0]
        assert start == pytest.approx(-1.0, abs=0.01)
        assert end == pytest.approx(3.0, abs=0.01)
    finally:
        w.close()


def test_build_spectrogram3d_source_anchor(qapp):
    """源码锚点：_build_spectrogram3d 含 分析位置→set_time_range 链与 ±2.0 回退。"""
    src = inspect.getsource(MainWindow._build_spectrogram3d)
    assert "get_analysis_position" in src, "缺分析位置读取（CB-016-4 驱动源）"
    assert "get_frame_size" in src, "缺帧宽读取"
    assert "set_time_range" in src, "缺 set_time_range 接线"
    assert "half = 2.0" in src, "缺 ±2.0s 回退分支"
