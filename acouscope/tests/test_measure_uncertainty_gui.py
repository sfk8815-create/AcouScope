# SPDX-License-Identifier: GPL-3.0-only
"""PI-P7-PREC-A T01/T03：不确定度显示与有效数字（离屏 Qt，禁 show 主窗）。

覆盖：
  ① 真实 SpectrogramWidget 的 440→660 测量：含 ±、u ∈ [1,40] cent、
     dc 为整数（u≥5 档生效）；
  ② 无 freq_uncertainty_cent 的旧视图仍含 "702.0"（旧断言逐字保留）；
  ③ 三个 u 档位（<0.5 / [0.5,5) / ≥5）格式化单测；
  ④ formants 返回 None 时不加 ±；formants 时间轴插值端点/缺值/越界不变；
  ⑤ spectrogram 静音时 freq_uncertainty_cent 仍返回 float（440 兜底，
     未插值口径）；
  ⑥ _on_region_stats 追加不确定度行且既有 "440.0"/"+0.0"/"41/41"/"0.400"
     子串原样保留。
"""

import math
import re

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QWidget  # noqa: E402

from acouscope.i18n import get_language, set_language  # noqa: E402


# ----------------------------------------------------------------------
# 桩视图 / 窗口 fixture
# ----------------------------------------------------------------------

class _FakeMeasureView(QWidget):
    """无 freq_uncertainty_cent 的旧视图替身：freq_at 返回 440/660。"""

    def __init__(self):
        super().__init__()
        self.marker_calls = []
        self.overlay_calls = []

    def freq_at(self, t: float):
        return 440.0 if float(t) <= 0.35 else 660.0

    def measure_markers_show(self, t0, t1, f0, f1):
        self.marker_calls.append((t0, t1, f0, f1))

    def measure_markers_clear(self):
        pass

    def set_readout_overlay(self, text):
        self.overlay_calls.append(text)


class _FakeUncView(_FakeMeasureView):
    """带 freq_uncertainty_cent 的桩视图：u0/u1 可注入以覆盖三档格式化。"""

    def __init__(self, u0, u1):
        super().__init__()
        self._u0, self._u1 = u0, u1

    def freq_uncertainty_cent(self, t: float):
        return self._u0 if float(t) <= 0.35 else self._u1


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """带已加载音频 + 波形的 MainWindow（离屏构建，不 show）。"""
    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow

    monkeypatch.setenv("HOME", str(tmp_path))
    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 2.0)) / sr
    controller.load_from_array(0.5 * np.sin(2 * np.pi * 440.0 * t), sr)
    playing = {"v": False}
    monkeypatch.setattr(controller, "is_playing", lambda: playing["v"])
    monkeypatch.setattr(controller, "play", lambda: None)
    monkeypatch.setattr(controller, "pause", lambda: None)
    monkeypatch.setattr(controller, "set_position", lambda *_: None)
    monkeypatch.setattr(controller, "get_position", lambda: 0.0)
    w = MainWindow(controller)
    w.waveform_widget.set_data(t, 0.5 * np.sin(2 * np.pi * 440.0 * t), sample_rate=sr)
    yield w
    w.close()


def _status_text(window) -> str:
    seg = window.status_segments
    return seg._temp_label.text() if getattr(seg, "_temp_label", None) else ""


def _measure(window, monkeypatch, view, t0, t1) -> str:
    monkeypatch.setattr(window.waveform_widget, "get_selection", lambda: (t0, t1))
    monkeypatch.setattr(window, "_current_measure_widget", lambda: view)
    window._on_measure_selection()
    return _status_text(window)


def _parabolic_spectrogram_widget(qapp):
    """真实 SpectrogramWidget：两列谱峰精确落在 440/660 Hz（抛物线三点）。"""
    from acouscope.ui.widgets.spectrogram import SpectrogramWidget

    sr, n_fft = 44100.0, 1024
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    res = float(freqs[1] - freqs[0])
    times = np.array([0.0, 1.0])
    lin = np.empty((freqs.size, 2))
    for col, f_true in enumerate((440.0, 660.0)):
        m = f_true / res
        lin[:, col] = np.maximum(1e-6, 1.0 - 0.1 * (np.arange(freqs.size) - m) ** 2)
    db = 20.0 * np.log10(lin)
    w = SpectrogramWidget()
    w.set_data(freqs, times, db, sample_rate=sr)
    return w, freqs, res


# ----------------------------------------------------------------------
# ① 真实语谱图视图：±、u 量级、dc 整数
# ----------------------------------------------------------------------

def test_spectrogram_measure_shows_uncertainty(window, monkeypatch, qapp):
    original = get_language()
    set_language("en_US")
    w = None
    try:
        w, freqs, res = _parabolic_spectrogram_widget(qapp)
        # 打桩 UI 副作用（overlay/marker 非本用例被测对象，离屏零 show）
        monkeypatch.setattr(w, "set_readout_overlay", lambda text: None)
        monkeypatch.setattr(w, "measure_markers_show", lambda *a: None)
        assert w.freq_at(0.0) == pytest.approx(440.0, abs=1e-6)
        assert w.freq_at(1.0) == pytest.approx(660.0, abs=1e-6)
        u0, u1 = w.freq_uncertainty_cent(0.0), w.freq_uncertainty_cent(1.0)
        assert isinstance(u0, float) and isinstance(u1, float)
        assert u0 > 0 and u1 > 0

        text = _measure(window, monkeypatch, w, 0.0, 1.0)
        assert "±" in text, text
        us = text.split("±")[1].split("|")[0].strip()
        u = float(us)
        assert 1.0 <= u <= 40.0, (u, text)
        assert u >= 5.0, (u, text)  # u≥5 档 → dc 取整数
        dc_seg = text.split("Δcent")[1].split("±")[0].strip()
        assert re.fullmatch(r"-?\d+", dc_seg), (dc_seg, text)
        assert "220.0" in text and "1.500" in text
        assert math.hypot(u0, u1) == pytest.approx(u, abs=0.05)
    finally:
        if w is not None:
            w.close()
        set_language(original)


# ----------------------------------------------------------------------
# ② 旧视图：702.0 逐字保留
# ----------------------------------------------------------------------

def test_legacy_view_without_unc_method_keeps_7020(window, monkeypatch):
    original = get_language()
    set_language("en_US")
    try:
        view = _FakeMeasureView()
        assert not hasattr(view, "freq_uncertainty_cent")  # getattr 兼容路径
        text = _measure(window, monkeypatch, view, 0.2, 0.5)
        assert "702.0" in text, text
        assert "±" not in text, text
        assert "220.0" in text and "1.500" in text
    finally:
        view.close()
        set_language(original)


# ----------------------------------------------------------------------
# ③ 三个 u 档位格式化
# ----------------------------------------------------------------------

@pytest.mark.parametrize("u0,u1,expected_u,expected_dc", [
    (0.1, 0.1, "0.141", "702.0"),   # u≈0.141 < 0.5 → 3 位小数
    (1.0, 1.0, "1.41", "702.0"),    # u≈1.414 ∈ [0.5,5) → 2 位小数
    (5.0, 5.0, "7.1", "702"),       # u≈7.071 ≥ 5 → 1 位小数 + dc 整数
])
def test_uncertainty_format_tiers(window, monkeypatch, u0, u1, expected_u, expected_dc):
    original = get_language()
    set_language("en_US")
    view = _FakeUncView(u0, u1)
    try:
        text = _measure(window, monkeypatch, view, 0.2, 0.5)
        assert "±" in text, text
        assert f"± {expected_u}" in text, text
        assert f"Δcent {expected_dc} ±" in text, text
        assert "220.0" in text and "1.500" in text
    finally:
        view.close()
        set_language(original)


# ----------------------------------------------------------------------
# ④ formants：None 不加 ± / 时间插值端点不变
# ----------------------------------------------------------------------

def test_formants_none_unc_adds_no_pm(window, monkeypatch, qapp):
    from acouscope.ui.widgets.formants import FormantWidget

    original = get_language()
    set_language("en_US")
    w = FormantWidget()
    try:
        times = np.array([0.0, 0.5, 1.0])
        freqs = np.zeros((3, 4))
        freqs[:, 0] = [440.0, 550.0, 660.0]
        w.set_data(times, freqs, np.zeros_like(freqs))
        assert w.freq_uncertainty_cent(0.0) is None
        monkeypatch.setattr(w, "set_readout_overlay", lambda text: None)
        monkeypatch.setattr(w, "measure_markers_show", lambda *a: None)
        text = _measure(window, monkeypatch, w, 0.0, 1.0)
        assert "±" not in text, text
        assert "702.0" in text, text
    finally:
        w.close()
        set_language(original)


def test_formants_time_interpolation_keeps_endpoints(qapp):
    """时间插值（非频谱插值）：端点/帧上值/缺值/越界逐位不变，中间线性插值。"""
    from acouscope.ui.widgets.formants import FormantWidget

    w = FormantWidget()
    try:
        times = np.array([0.0, 0.1, 0.2])
        freqs = np.zeros((3, 4))
        freqs[:, 0] = [400.0, 500.0, 600.0]
        w.set_data(times, freqs, np.zeros_like(freqs))
        assert w.freq_at(0.0) == 400.0       # 首端点不变
        assert w.freq_at(0.1) == 500.0       # 落在帧上不变
        assert w.freq_at(0.2) == 600.0       # 末端点不变
        assert w.freq_at(0.15) == pytest.approx(550.0)  # 两有效帧之间线性插值
        assert w.freq_at(-1.0) == 400.0      # 越界不变
        assert w.freq_at(5.0) == 600.0       # 越界不变
        assert w.freq_uncertainty_cent(0.15) is None

        # 缺值/端点口径与既有 test_hover_readout_measure.py 同形
        times2 = np.arange(4, dtype=np.float64) * 0.05
        freqs2 = np.zeros((4, 4))
        freqs2[1, 0] = 500.0
        freqs2[3, 0] = 600.0
        w.set_data(times2, freqs2, np.zeros_like(freqs2))
        assert w.freq_at(0.05) == 500.0
        assert w.freq_at(0.15) == 600.0
        assert w.freq_at(0.10) is None
        assert w.freq_at(0.0) is None
    finally:
        w.close()


# ----------------------------------------------------------------------
# ⑤ spectrogram 静音兜底
# ----------------------------------------------------------------------

def test_spectrogram_silent_uncertainty_uses_440_fallback(qapp):
    from acouscope.ui.widgets.spectrogram import SpectrogramWidget

    w = SpectrogramWidget()
    try:
        sr = 44100.0
        freqs = np.fft.rfftfreq(1024, 1.0 / sr)
        db = np.full((freqs.size, 2), -90.0)  # 全静音
        w.set_data(freqs, np.array([0.0, 1.0]), db, sample_rate=sr)
        assert w.freq_at(0.0) is None
        u = w.freq_uncertainty_cent(0.0)
        assert isinstance(u, float) and u > 0
        half_bin_hz = float(freqs[1] - freqs[0]) / 2.0
        expected = 1200.0 * math.log2((440.0 + half_bin_hz) / 440.0) / math.sqrt(3.0)
        assert u == pytest.approx(expected, abs=1e-9)  # 未插值口径（÷√3，不÷8）
    finally:
        w.close()


# ----------------------------------------------------------------------
# ⑥ 区间统计追加行 + 既有子串保留
# ----------------------------------------------------------------------

def test_region_stats_appends_uncertainty_row_keeps_legacy_text(window, monkeypatch):
    original = get_language()
    set_language("en_US")
    try:
        monkeypatch.setattr(window.waveform_widget, "get_selection", lambda: (0.5, 0.9))
        times = np.arange(0.0, 2.0, 0.01)
        f0 = np.zeros_like(times)
        f0[(times >= 0.5) & (times <= 0.9)] = 440.0

        class _V(QWidget):
            def result_arrays(self):
                return (times, f0)

        window._pitch_widget = _V()
        window._on_region_stats()
        text = window.inspector_panel.lbl_region_stats.text()
        for legacy in ("0.400", "41/41", "440.0", "+0.0"):
            assert legacy in text, (legacy, text)
        assert "±" in text, text
        assert "uncertainty" in text.lower(), text
    finally:
        set_language(original)
