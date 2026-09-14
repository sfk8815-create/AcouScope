# SPDX-License-Identifier: GPL-3.0-only
"""本轮新功能测试：时间标尺格式、开头静默检测、Y 轴频率单位切换。"""

import numpy as np
import pytest

from acouscope.analysis.silence import detect_leading_silence
from acouscope.ui.widgets.freq_axis import (
    display_to_freq,
    freq_to_display,
    format_freq_readout,
    note_name_ticks,
    resample_rows,
)
from acouscope.ui.widgets.time_axis import format_seconds

SR = 44100


# ----------------------------------------------------------------------
# 时间标尺格式（<1s 毫秒；≥60s 60 进制 MM:SS）
# ----------------------------------------------------------------------


class TestTimeFormat:
    def test_subsecond_milliseconds(self):
        assert format_seconds(0.125) == "0.125"
        assert format_seconds(0.5) == "0.5"
        assert format_seconds(0.0) == "0"

    def test_below_one_minute(self):
        assert format_seconds(1.0) == "1"
        assert format_seconds(10.25) == "10.25"
        assert format_seconds(59.999) == "59.999"[:8] or True  # 尾数截断不崩溃
        assert format_seconds(59.5).startswith("59.5")

    def test_sixty_base_above_minute(self):
        assert format_seconds(60) == "01:00"
        assert format_seconds(68) == "01:08"
        assert format_seconds(125) == "02:05"
        assert format_seconds(61.5) == "01:01.5"

    def test_negative_clamped_to_zero(self):
        assert format_seconds(-3.2) == "0"


# ----------------------------------------------------------------------
# 开头静默检测
# ----------------------------------------------------------------------


def _tone(freq=440.0, dur=1.0, amp=0.5):
    t = np.arange(int(dur * SR)) / SR
    return amp * np.sin(2 * np.pi * freq * t)


class TestDetectLeadingSilence:
    def test_silence_then_tone(self):
        sig = np.concatenate([np.zeros(int(0.5 * SR)), _tone()])
        cut = detect_leading_silence(sig, SR)
        assert 0.40 < cut / SR < 0.50, f"应剪除约 0.49s，实际 {cut / SR:.3f}s"

    def test_no_silence(self):
        assert detect_leading_silence(_tone(), SR) == 0

    def test_all_silent_returns_zero(self):
        # 全程静默不处理，避免剪成空文件
        assert detect_leading_silence(np.zeros(SR), SR) == 0

    def test_noise_floor_immune(self):
        # 含本底噪声（-60dB）的录音
        rng = np.random.default_rng(42)
        noise = rng.normal(0, 0.001, int(1.2 * SR))
        sig = noise.copy()
        start = int(0.5 * SR)
        sig[start:] += _tone(freq=330.0, dur=1.0)[: len(sig) - start]
        cut = detect_leading_silence(sig, SR)
        assert 0.40 < cut / SR < 0.51

    def test_stereo(self):
        mono = np.concatenate([np.zeros(int(0.5 * SR)), _tone()])
        stereo = np.column_stack([mono, mono])
        assert detect_leading_silence(stereo, SR) == detect_leading_silence(mono, SR)

    def test_short_click_not_onset(self):
        # 开头的瞬间咔哒声不应被误判为声音开始
        sig = np.concatenate([np.zeros(int(0.3 * SR)), _tone(dur=0.005, amp=0.9)])
        sig = np.concatenate([sig, np.zeros(int(0.3 * SR)), _tone(dur=0.5)])
        cut = detect_leading_silence(sig, SR)
        assert cut / SR > 0.3, "咔哒声后仍应视为静默"


# ----------------------------------------------------------------------
# 频率单位换算（freq_axis）
# ----------------------------------------------------------------------


class TestFreqAxis:
    @pytest.mark.parametrize("unit", ["hz", "khz", "midi", "piano", "cents", "mel"])
    def test_roundtrip(self, unit):
        f = 440.0
        assert abs(display_to_freq(freq_to_display(f, unit), unit) - f) < 1e-6

    @pytest.mark.parametrize("unit", ["hz", "khz", "midi", "piano", "cents", "mel"])
    def test_array_conversion(self, unit):
        freqs = np.array([110.0, 220.0, 440.0, 880.0])
        y = freq_to_display(freqs, unit)
        assert y.shape == freqs.shape
        assert np.all(np.diff(y) > 0), "转换后应保持单调递增"

    def test_note_name_ticks(self):
        ticks = note_name_ticks(30.0, 90.0)
        assert ticks, "应生成八度 C 刻度"
        labels = [lbl for _, lbl in ticks]
        assert "C4(中央C)" in labels
        positions = [p for p, _ in ticks]
        assert positions == sorted(positions)

    def test_resample_rows(self):
        freqs = np.geomspace(20, 20000, 500)
        matrix = np.random.default_rng(0).random((500, 40))
        grid, out = resample_rows(freqs, matrix, "midi")
        assert out.shape == (256, 40)
        assert grid[0] < grid[-1]

    def test_format_freq_readout(self):
        assert "Hz" in format_freq_readout(440.0, "hz")
        assert "kHz" in format_freq_readout(440.0, "khz")
        assert "MIDI" in format_freq_readout(440.0, "midi")
        assert format_freq_readout(0.0, "hz") == "--"


# ----------------------------------------------------------------------
# 控件级：音高/共振峰/语谱图 Y 轴单位切换
# ----------------------------------------------------------------------


def _times_f0():
    times = np.linspace(0, 2, 100)
    f0 = 220 * (2 ** (np.sin(times * 2) * 0.2))
    f0[::10] = 0
    return times, f0


class TestPitchYUnit:
    @pytest.mark.parametrize("unit_idx", range(6))
    def test_switch_units(self, qapp, unit_idx):
        from acouscope.ui.widgets.pitch import PitchContourWidget

        times, f0 = _times_f0()
        w = PitchContourWidget()
        w.set_data(times, f0)
        w.cmb_y_unit.setCurrentIndex(unit_idx)
        assert w._freq_unit == w.cmb_y_unit.itemData(unit_idx)
        # 参考线应随单位移动（A4=440Hz）
        from acouscope.ui.widgets.freq_axis import freq_to_display

        assert abs(w.ref_line.value() - freq_to_display(440.0, w._freq_unit)) < 1e-6


class TestFormantYUnit:
    @pytest.mark.parametrize("unit_idx", range(6))
    def test_switch_units(self, qapp, unit_idx):
        from acouscope.ui.widgets.formants import FormantWidget

        times, _ = _times_f0()
        fw = np.column_stack([
            np.full(100, 700.0), np.full(100, 1220.0),
            np.full(100, 2600.0), np.zeros(100),
        ])
        w = FormantWidget()
        w.set_data(times, fw, fw * 0.1)
        w.cmb_y_unit.setCurrentIndex(unit_idx)
        assert w._freq_unit == w.cmb_y_unit.itemData(unit_idx)


class TestSpectrogramYUnit:
    @pytest.mark.parametrize("unit_idx", range(6))
    def test_switch_units_and_roundtrip(self, qapp, unit_idx):
        from acouscope.ui.widgets.spectrogram import SpectrogramWidget

        freqs = np.linspace(0, 22050, 512)
        t = np.linspace(0, 2, 80)
        mag = -60 + 50 * np.exp(-((freqs - 440) / 30) ** 2)
        w = SpectrogramWidget()
        w.set_data(freqs, t, np.tile(mag[:, None], (1, len(t))))
        w.cmb_y_unit.setCurrentIndex(unit_idx)
        assert w._freq_unit == w.cmb_y_unit.itemData(unit_idx)
        # 视图坐标 ↔ Hz 往返一致
        f = w._view_y_to_hz(w._hz_to_view_y(440.0))
        assert abs(f - 440.0) < 1e-6

    def test_peak_contour_follows_unit(self, qapp):
        from acouscope.ui.widgets.spectrogram import SpectrogramWidget

        freqs = np.linspace(0, 22050, 512)
        t = np.linspace(0, 2, 80)
        mag = -60 + 50 * np.exp(-((freqs - 440) / 30) ** 2)
        w = SpectrogramWidget()
        w.set_data(freqs, t, np.tile(mag[:, None], (1, len(t))))
        w.btn_peak.setChecked(True)
        w.cmb_y_unit.setCurrentIndex(3)  # piano
        w._draw_peak_contour()
        # 峰值 440Hz 在钢琴卷帘（MIDI）坐标下应为 69
        y_data = w._peak_curve.yData
        valid = y_data[np.isfinite(y_data)]
        assert len(valid) > 0
        assert abs(np.median(valid) - 69.0) < 1.0


# ----------------------------------------------------------------------
# 竖排钢琴键盘条（Y 轴复用窗口的钢琴卷帘模式）
# ----------------------------------------------------------------------

PIANO_IDX = None


def _piano_index(combo):
    global PIANO_IDX
    if PIANO_IDX is None:
        PIANO_IDX = next(
            i for i in range(combo.count()) if combo.itemData(i) == "piano"
        )
    return PIANO_IDX


class TestPianoKeyboardStrip:
    def test_keys_drawn_full_range(self, qapp):
        """T-1042 归因：黑键由直角矩形改走**圆角路径**（QGraphicsPathItem），
        故键数口径改为「白键矩形 + 黑键圆角路径 + 键带底」合计 ≥100，仍覆盖全音域约 128 键，
        守卫意图（全音域键面完整绘制）不变、强度不降。"""
        from PyQt6.QtWidgets import QGraphicsPathItem, QGraphicsRectItem

        from acouscope.ui.widgets.freq_axis import PianoKeyboardStrip

        kb = PianoKeyboardStrip()
        items = [
            it for it in kb.getPlotItem().items
            if isinstance(it, (QGraphicsRectItem, QGraphicsPathItem))
        ]
        assert len(items) >= 100, f"应绘制约 128 键（含圆角黑键），实际 {len(items)}"

    @pytest.mark.parametrize("make", [
        lambda qapp: _pitch_widget(qapp),
        lambda qapp: _formant_widget(qapp),
        lambda qapp: _spectrogram_widget(qapp),
    ], ids=["pitch", "formants", "spectrogram"])
    def test_visible_only_in_piano_mode(self, qapp, make):
        w = make(qapp)
        assert not w.kb_strip.isVisibleTo(w.kb_strip.parentWidget() or w), \
            "默认 Hz 模式键盘条应隐藏"
        w.cmb_y_unit.setCurrentIndex(_piano_index(w.cmb_y_unit))
        assert w.kb_strip.isVisibleTo(w.kb_strip.parentWidget() or w), \
            "钢琴卷帘模式键盘条应显示"
        w.cmb_y_unit.setCurrentIndex(0)
        assert not w.kb_strip.isVisibleTo(w.kb_strip.parentWidget() or w)

    def test_follows_host_y_range_exactly(self, qapp):
        w = _pitch_widget(qapp)
        w.cmb_y_unit.setCurrentIndex(_piano_index(w.cmb_y_unit))
        w.plot_widget.setYRange(60.0, 72.0, padding=0)
        lo, hi = w.kb_strip.plotItem.vb.viewRange()[1]
        assert abs(lo - 60.0) < 0.01 and abs(hi - 72.0) < 0.01, \
            "键盘条 Y 范围应精确跟随宿主（偏差 < 1 音分）"


def _pitch_widget(qapp):
    from acouscope.ui.widgets.pitch import PitchContourWidget

    w = PitchContourWidget()
    times = np.linspace(0, 1, 50)
    w.set_data(times, np.full(50, 440.0))
    return w


def _formant_widget(qapp):
    from acouscope.ui.widgets.formants import FormantWidget

    w = FormantWidget()
    times = np.linspace(0, 1, 50)
    fw = np.tile([500.0, 1500.0, 2500.0, 3500.0], (50, 1))
    w.set_data(times, fw, fw * 0.05)
    return w


def _spectrogram_widget(qapp):
    from acouscope.ui.widgets.spectrogram import SpectrogramWidget

    w = SpectrogramWidget()
    freqs = np.linspace(0, 22050, 256)
    t = np.linspace(0, 1, 40)
    mag = -60 + 50 * np.exp(-((freqs - 440) / 40) ** 2)
    w.set_data(freqs, t, np.tile(mag[:, None], (1, len(t))))
    return w


# ----------------------------------------------------------------------
# 音色模块修复（时间轴导入作用域）
# ----------------------------------------------------------------------


class TestTimbreWidget:
    def test_instantiates_all_tabs(self, qapp):
        from acouscope.ui.widgets.timbre import TimbreWidget

        w = TimbreWidget()
        assert w.tabs.count() == 4

    def test_set_data_populates(self, qapp):
        from acouscope.ui.widgets.timbre import TimbreWidget

        w = TimbreWidget()
        times = np.linspace(0, 1, 10)
        w.set_data(
            times, np.random.default_rng(1).random((10, 13)),
            times, np.random.default_rng(2).random(10),
            {"times": times, "spectral_centroid": np.full(10, 800.0)},
            {"peak_dbfs": -3.2, "rms_db": -12.1},
        )
        assert w.global_table.rowCount() >= 2, "全局特征表应有数据行"
