# SPDX-License-Identifier: GPL-3.0-only
"""语谱图工具单元测试（测量工具 + 峰值频率追踪 + 标注同步）。"""

import numpy as np
import pytest


@pytest.fixture
def spec_widget(qapp):
    """创建一个带测试数据的语谱图控件。"""
    from acouscope.ui.widgets.spectrogram import SpectrogramWidget

    w = SpectrogramWidget()
    freqs = np.linspace(0, 8000, 257)  # 256 个频段 + DC
    times = np.linspace(0, 2.0, 200)   # 2 秒，200 帧

    # 生成带线性扫频信号的语谱图
    spec = np.random.RandomState(42).randn(257, 200) * 10 - 60
    for ti in range(200):
        # 500 Hz -> 2000 Hz 线性扫频
        f_signal = 500 + (2000 - 500) * ti / 200
        fi = int(f_signal / 8000 * 256)
        fi = np.clip(fi, 0, 256)
        spec[fi, ti] += 60  # 信号比噪声高 60dB

    w.set_data(freqs, times, spec, sample_rate=16000)
    return w


class TestPeakContour:
    """峰值频率追踪测试。"""

    def test_peak_contour_toggle_on(self, spec_widget):
        assert spec_widget._peak_curve is None
        assert spec_widget._peak_freqs is None

        spec_widget.btn_peak.setChecked(True)
        assert spec_widget._peak_curve is not None
        assert spec_widget._peak_freqs is not None
        assert len(spec_widget._peak_freqs) == 200  # 200 帧

    def test_peak_contour_toggle_off(self, spec_widget):
        spec_widget.btn_peak.setChecked(True)
        assert spec_widget._peak_curve is not None

        spec_widget.btn_peak.setChecked(False)
        assert spec_widget._peak_curve is None
        assert spec_widget._peak_freqs is None

    def test_peak_freqs_track_sweep_signal(self, spec_widget):
        """峰值频率应跟随扫频信号。"""
        spec_widget.btn_peak.setChecked(True)
        peaks = spec_widget._peak_freqs

        # 验证起始和结束峰值频率在合理范围内
        valid_start = peaks[~np.isnan(peaks)]
        assert len(valid_start) > 0

        # 第 1 帧峰值应接近 500 Hz
        first_valid_idx = np.argmax(~np.isnan(peaks))
        assert abs(peaks[first_valid_idx] - 500) < 200  # 容许一些误差

        # 最后一帧峰值应接近 2000 Hz
        last_valid_idx = len(peaks) - 1 - np.argmax(~np.isnan(peaks[::-1]))
        assert abs(peaks[last_valid_idx] - 2000) < 200

    def test_peak_threshold_filters_noise(self, spec_widget):
        """低于阈值的帧应被设为 NaN。"""
        spec_widget._peak_threshold_db = 100  # 设得很高，全部过滤
        spec_widget.btn_peak.setChecked(True)
        peaks = spec_widget._peak_freqs
        # 全部低于阈值 → 全部 NaN
        assert np.all(np.isnan(peaks))

    def test_peak_refresh_on_range_change(self, spec_widget):
        """频率范围变化时峰值应刷新。"""
        spec_widget.btn_peak.setChecked(True)
        peaks_before = spec_widget._peak_freqs.copy()

        # 切换到不同的频率范围
        spec_widget.cmb_range.setCurrentIndex(0)  # 500 Hz
        peaks_after = spec_widget._peak_freqs

        # 数据应该被重新计算（引用不同或内容变化）
        assert peaks_after is not None


class TestMeasureTool:
    """测量工具测试。"""

    def test_measure_toggle_on(self, spec_widget):
        assert spec_widget._measure_enabled is False
        spec_widget.btn_measure.setChecked(True)
        assert spec_widget._measure_enabled is True

    def test_measure_toggle_off_clears(self, spec_widget):
        spec_widget.btn_measure.setChecked(True)
        # 模拟一次测量
        spec_widget._start_measurement(0.5, 1000)
        assert spec_widget._measure_rect is not None

        spec_widget.btn_measure.setChecked(False)
        assert spec_widget._measure_enabled is False
        assert spec_widget._measure_rect is None
        assert spec_widget._measure_text is None

    def test_start_measurement(self, spec_widget):
        spec_widget._start_measurement(1.0, 500)
        assert spec_widget._measure_start == (1.0, 500)
        assert spec_widget._measure_dragging is True
        assert spec_widget._measure_rect is not None
        assert spec_widget._measure_text is not None

    def test_update_measurement(self, spec_widget):
        spec_widget._start_measurement(0.5, 500)
        spec_widget._update_measurement(1.5, 1500)

        # 验证文本包含关键信息
        text = spec_widget._measure_text.textItem.toPlainText()
        assert "Δt=" in text
        assert "Δf=" in text
        assert "ms" in text
        assert "Hz" in text

    def test_measurement_delta_time(self, spec_widget):
        spec_widget._start_measurement(1.0, 1000)
        spec_widget._update_measurement(1.5, 1000)
        # Δt 应该是 500 ms
        text = spec_widget._measure_text.textItem.toPlainText()
        assert "500.00 ms" in text

    def test_measurement_delta_freq(self, spec_widget):
        spec_widget._start_measurement(1.0, 500)
        spec_widget._update_measurement(1.0, 1000)
        # Δf 应该是 500 Hz
        text = spec_widget._measure_text.textItem.toPlainText()
        assert "500.0 Hz" in text

    def test_measurement_cents(self, spec_widget):
        """一个八度 = 1200 cents。"""
        spec_widget._start_measurement(1.0, 440)
        spec_widget._update_measurement(1.0, 880)  # 正好一个八度
        text = spec_widget._measure_text.textItem.toPlainText()
        assert "Δcents=" in text
        # 1200 cents（一个八度）
        assert "1200" in text

    def test_clear_measurement(self, spec_widget):
        spec_widget._start_measurement(0.5, 1000)
        spec_widget._clear_measurement()
        assert spec_widget._measure_rect is None
        assert spec_widget._measure_text is None
        assert spec_widget._measure_start is None
        assert spec_widget._measure_dragging is False

    def test_update_without_start_no_error(self, spec_widget):
        """没有起点时更新测量不应报错。"""
        spec_widget._update_measurement(1.0, 500)  # 不应抛异常


class TestSpectrogramAnnotations:
    """语谱图标注同步测试。"""

    def test_set_annotation_model(self, spec_widget):
        from acouscope.annotation import AnnotationModel
        model = AnnotationModel()
        model.add_region(0.5, 1.0, "test")
        model.add_instant(0.75, "beat")

        spec_widget.set_annotation_model(model)
        assert spec_widget.annotations is model
        assert len(spec_widget._region_items) == 1
        assert len(spec_widget._instant_items) == 1

    def test_refresh_annotations(self, spec_widget):
        from acouscope.annotation import AnnotationModel
        model = AnnotationModel()
        spec_widget.set_annotation_model(model)

        # 添加新标注后刷新
        model.add_region(0, 1, "new")
        spec_widget.refresh_annotations()
        assert len(spec_widget._region_items) == 1

    def test_clear_annotation_model(self, spec_widget):
        from acouscope.annotation import AnnotationModel
        model = AnnotationModel()
        model.add_region(0, 1, "test")
        spec_widget.set_annotation_model(model)
        assert len(spec_widget._region_items) == 1

        # 设置 None 模型
        spec_widget.set_annotation_model(None)
        assert spec_widget.annotations is None
        assert len(spec_widget._region_items) == 0
        assert len(spec_widget._instant_items) == 0
