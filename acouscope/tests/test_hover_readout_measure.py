# SPDX-License-Identifier: GPL-3.0-only
"""T-326 Pδ 悬停读数 + 两点测量 离屏测试。

覆盖（规格 E）：
  ① pitch/formants/spectrogram 合成数据视图：
     hover_readout_at 已知 (t, f) → 文本含期望 Hz/音分(±0.1)/dB；
  ② freq_at(t) 已知端点 → 期望 f0/F1/谱峰；无声段/空数据 → None；
  ③ A/B 测量标记 measure_markers_show/clear（覆盖式重复调用）；
  ④ 悬停节流 ≤20Hz + 鼠标离开清零（overlay 隐藏 + 回调 None）；
  ⑤ StatusBarSegments.set_temporary_text 显示/清空（不入 keys() 注册表）；
  ⑥ main_window 层测量：注入桩视图（freq_at 440/660）→ Δt/ΔHz=220/
     Δcent≈701.955/比率 1.5 断言；任一频 None/0 → 只留 Δt；除零防御；
     清除测量/选区清除联动；enable 规则。

纪律：不展示主窗口（禁 show 主窗）；controller 播放打桩；不触发分析 spy（
monkeypatch _on_*_analysis 抛错证明测量路径零分析调用）。
"""

import math

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QWidget  # noqa: E402

from acouscope.i18n import tr  # noqa: E402
from acouscope.ui.widgets.statusbar_segments import StatusBarSegments  # noqa: E402


# ----------------------------------------------------------------------
# 视图层（pitch）
# ----------------------------------------------------------------------

def _pitch_widget(qapp):
    from acouscope.ui.widgets.pitch import PitchContourWidget

    w = PitchContourWidget()
    times = np.arange(20, dtype=np.float64) * 0.02  # 0.00 ~ 0.38
    f0 = np.zeros(20)
    f0[5] = 440.0  # t=0.10
    f0[6] = 442.0  # t=0.12
    f0[15] = 660.0  # t=0.30
    w.set_data(times, f0)
    return w


def test_pitch_hover_readout_contains_hz_and_cents(qapp):
    w = _pitch_widget(qapp)
    text = w.hover_readout_at(0.123, 550.0)  # y=550 Hz（hz 单位）
    assert "t=0.123s" in text, text
    assert "550.0 Hz" in text, text
    cents = 1200.0 * math.log2(550.0 / 440.0)
    assert f"{cents:+.1f} cents" in text, text  # ≈ +386.3


def test_pitch_hover_readout_nonpositive_freq_dash(qapp):
    w = _pitch_widget(qapp)
    text = w.hover_readout_at(0.05, -5.0)
    assert "t=0.050s" in text and "--" in text and "cents" not in text, text


def test_pitch_freq_at_voiced_nearest_and_unvoiced(qapp):
    w = _pitch_widget(qapp)
    assert w.freq_at(0.10) == 440.0  # 帧内最近 voiced
    assert w.freq_at(0.13) == 442.0  # 最近 voiced 帧 t=0.12
    assert w.freq_at(0.30) == 660.0
    assert w.freq_at(1000.0) == 660.0  # 越界夹取到最近 voiced
    # 全无声数据 → None
    w.set_data(np.arange(5) * 0.1, np.zeros(5))
    assert w.freq_at(0.2) is None
    # 空数据 → None
    w.set_data(np.array([]), np.array([]))
    assert w.freq_at(0.2) is None


def test_pitch_overlay_show_and_clear_via_hover(qapp):
    w = _pitch_widget(qapp)
    got = []
    w._on_hover_readout = got.append
    w.set_readout_overlay("t=0.100s | 440.0 Hz | +0.0 cents")
    assert w._hover_overlay.isHidden() is False
    assert w._hover_overlay.text().startswith("t=0.100s")
    w._hover_clear()
    assert w._hover_overlay.isHidden() is True
    assert got == [None]


# ----------------------------------------------------------------------
# A4-R1：音高视图 A4 口径（参考线 / 标签 / 游标 / 悬停音分读当前 A4）
# ----------------------------------------------------------------------

def test_pitch_ref_line_and_label_follow_current_a4(qapp, monkeypatch):
    """A4=442：参考线 y==freq_to_display(442)，标签含 442 且不含 440（反对照）。"""
    from acouscope.dsp import units
    from acouscope.ui.widgets.freq_axis import freq_to_display
    from acouscope.ui.widgets.pitch import PitchContourWidget

    monkeypatch.setattr(units, "_reference_hz", 442.0)
    w = PitchContourWidget()
    times = np.arange(20, dtype=np.float64) * 0.02
    f0 = np.zeros(20)
    f0[5] = 440.0
    w.set_data(times, f0)
    assert w.ref_line.value() == pytest.approx(freq_to_display(442.0, "hz"))
    assert "442" in w.ref_label.toPlainText(), w.ref_label.toPlainText()
    assert "440" not in w.ref_label.toPlainText(), w.ref_label.toPlainText()  # ★ 仍写死 440 则必红


def test_pitch_cursor_and_hover_cents_follow_current_a4(qapp, monkeypatch):
    """A4=442：游标/悬停音分 == units.hz_to_cents（仍按 440 算则 ≈+8 必红）。"""
    from acouscope.dsp import units
    from acouscope.ui.widgets.pitch import PitchContourWidget

    monkeypatch.setattr(units, "_reference_hz", 442.0)
    w = PitchContourWidget()
    times = np.arange(20, dtype=np.float64) * 0.02
    f0 = np.zeros(20)
    f0[6] = 442.0  # t=0.12 唯一 voiced
    w.set_data(times, f0)
    w._on_cursor_moved()  # 游标默认在 t=0.2 → 最近 voiced f=442
    assert w.lbl_cents.text() == tr("pitch.cents").format(value="+0"), w.lbl_cents.text()  # ★ 反对照
    text = w.hover_readout_at(0.123, 442.0)
    assert f"{float(units.hz_to_cents(442.0)):+.1f} cents" in text, text
    assert "+0.0 cents" in text, text  # ★ 仍按 440 算（+7.8）则必红


def test_pitch_default_a4_unchanged(qapp, monkeypatch):
    """A4=440（默认）：参考线/标签/游标/悬停逐字逐位不变。"""
    from acouscope.dsp import units
    from acouscope.ui.widgets.freq_axis import freq_to_display
    from acouscope.ui.widgets.pitch import PitchContourWidget

    monkeypatch.setattr(units, "_reference_hz", 440.0)
    w = PitchContourWidget()
    times = np.arange(20, dtype=np.float64) * 0.02
    f0 = np.zeros(20)
    f0[5] = 440.0
    f0[6] = 442.0
    w.set_data(times, f0)
    assert w.ref_line.value() == pytest.approx(freq_to_display(440.0, "hz"))
    assert w.ref_label.toPlainText() == "A4 (440 Hz)", w.ref_label.toPlainText()  # 逐字不变
    w._on_cursor_moved()  # 最近 voiced f=442 → +7.85 → "+8"
    assert w.lbl_cents.text() == tr("pitch.cents").format(value="+8"), w.lbl_cents.text()
    text = w.hover_readout_at(0.123, 550.0)
    cents = 1200.0 * math.log2(550.0 / 440.0)
    assert f"{cents:+.1f} cents" in text, text  # ≈ +386.3，与既有用例同口径


# ----------------------------------------------------------------------
# A4-R2：共振峰 / 语谱图 悬停音分读当前 A4（照 R1 形态）
# ----------------------------------------------------------------------

def test_formant_hover_cents_follow_current_a4(qapp, monkeypatch):
    """A4=442：共振峰悬停音分 == units.hz_to_cents（仍按 440 算则 +386.3 必红）。"""
    from acouscope.dsp import units

    monkeypatch.setattr(units, "_reference_hz", 442.0)
    w = _formant_widget(qapp)
    text = w.hover_readout_at(0.077, 550.0)
    assert f"{float(units.hz_to_cents(550.0)):+.1f} cents" in text, text
    assert "+378.5 cents" in text, text  # ★ 反对照：仍按 440 算（+386.3）则必红
    assert "+386.3 cents" not in text, text


def test_spec_hover_cents_follow_current_a4(qapp, monkeypatch):
    """A4=442：语谱图悬停音分 == units.hz_to_cents（仍按 440 算则 -165.0 必红）。"""
    from acouscope.dsp import units

    monkeypatch.setattr(units, "_reference_hz", 442.0)
    w = _spec_widget(qapp)
    text = w.hover_readout_at(0.03, 400.0)
    assert f"{float(units.hz_to_cents(400.0)):+.1f} cents" in text, text
    assert "-172.9 cents" in text, text  # ★ 反对照：仍按 440 算（-165.0）则必红
    assert "-165.0 cents" not in text, text
    assert "-12.0 dB" in text, text  # 其余字段不变


def test_formant_spec_default_a4_unchanged(qapp, monkeypatch):
    """A4=440（默认）：共振峰/语谱图悬停读数逐字逐位不变。"""
    from acouscope.dsp import units

    monkeypatch.setattr(units, "_reference_hz", 440.0)
    fm = _formant_widget(qapp)
    text = fm.hover_readout_at(0.077, 550.0)
    assert "t=0.077s | 550.0 Hz | +386.3 cents" == text, text  # 与既有用例逐字同
    sp = _spec_widget(qapp)
    text = sp.hover_readout_at(0.03, 400.0)
    assert "t=0.030s | 400.0 Hz | -165.0 cents | -12.0 dB" == text, text


def test_pitch_measure_markers_show_and_clear(qapp):
    w = _pitch_widget(qapp)
    w.measure_markers_show(0.10, 0.30, 440.0, 660.0)
    assert len(w._measure_items) == 2
    assert all(it.isVisible() for it in w._measure_items)
    assert w._measure_item_labels[0].toPlainText() == "A(0.100s)"
    assert w._measure_item_labels[1].toPlainText() == "B(0.300s)"
    # 再次测量 = 覆盖（不重建、不抛）
    w.measure_markers_show(0.05, 0.15, 220.0, 330.0)
    assert len(w._measure_items) == 2
    assert w._measure_item_labels[1].toPlainText() == "B(0.150s)"
    w.measure_markers_clear()
    assert all(not it.isVisible() for it in w._measure_items)


# ----------------------------------------------------------------------
# 视图层（spectrogram）
# ----------------------------------------------------------------------

def _spec_widget(qapp):
    from acouscope.ui.widgets.spectrogram import SpectrogramWidget

    w = SpectrogramWidget()
    freqs = np.array([100.0, 200.0, 400.0, 800.0, 1600.0])
    times = np.arange(8, dtype=np.float64) * 0.01  # 0.00 ~ 0.07
    mag = np.full((len(freqs), len(times)), -90.0)
    mag[2, 3] = -12.0  # 400 Hz @ t=0.03（列峰）
    mag[3, 3] = -15.0
    mag[:, 5] = -60.0  # t=0.05 列整体弱 → 无声判据
    w.set_data(freqs, times, mag)
    return w


def test_spec_hover_readout_contains_hz_cents_db(qapp):
    w = _spec_widget(qapp)
    text = w.hover_readout_at(0.03, 400.0)  # y=400 Hz（hz 单位）
    assert "t=0.030s" in text, text
    assert "400.0 Hz" in text, text
    cents = 1200.0 * math.log2(400.0 / 440.0)
    assert f"{cents:+.1f} cents" in text, text  # ≈ -165.0
    assert "-12.0 dB" in text, text


def test_spec_freq_at_peak_and_silent(qapp):
    w = _spec_widget(qapp)
    # T01：该列谱峰改由抛物线插值读数（非整 bin argmax）；容差 ≤1e-6，禁删断言。
    assert w.freq_at(0.03) == pytest.approx(227.39393042171278, abs=1e-6)
    assert w.freq_at(0.029) == pytest.approx(227.39393042171278, abs=1e-6)  # 取 ≥t 首列（searchsorted 口径与 hover 一致）
    assert w.freq_at(0.031) is None  # 落入 0.04 无声列
    assert w.freq_at(0.05) is None  # 列能量 ≤ 阈值（无声）
    # 空数据 → None
    from acouscope.ui.widgets.spectrogram import SpectrogramWidget

    empty = SpectrogramWidget()
    assert empty.freq_at(0.1) is None
    # ★ T01：插值读数比未插值 bin 更接近注入真频率（均匀 bin Hann 合成谱）
    sr, n_fft = 44100.0, 2048
    f_true = 445.3  # 刻意落在两个 FFT bin 之间
    lin = np.abs(np.fft.rfft(
        np.sin(2 * np.pi * f_true * np.arange(n_fft) / sr) * np.hanning(n_fft)
    ))
    db = 20.0 * np.log10(np.maximum(lin, 1e-12))
    fq = np.fft.rfftfreq(n_fft, 1.0 / sr)
    w_lin = SpectrogramWidget()
    try:
        w_lin.set_data(fq, np.array([0.0, 1.0]),
                       np.column_stack((db, db)), sample_rate=sr)
        f_read = w_lin.freq_at(0.0)
        f_bin = float(fq[int(np.argmax(db))])
        assert f_read is not None
        assert abs(f_read - f_true) < abs(f_bin - f_true), (f_read, f_bin, f_true)
    finally:
        w_lin.close()


def test_spec_hover_throttle_and_leave_clear(qapp):
    """节流 ≤20Hz（0.05s 内二次移动不刷新）；离开清零不节流。"""
    import time as _time

    w = _spec_widget(qapp)
    got = []
    w._on_hover_readout = got.append
    w._hover_update_at(0.03, 400.0)
    first = w._hover_overlay.text()
    assert w._hover_overlay.isHidden() is False
    w._last_hover_at = _time.monotonic()  # 伪造刚刷新
    w._hover_update_at(0.03, 800.0)  # 节流窗口内 → 拒绝
    assert w._hover_overlay.text() == first
    assert len(got) == 1
    w._hover_clear()  # 离开：不节流立即清
    assert w._hover_overlay.isHidden() is True
    assert got[-1] is None
    # 清零后再次移动立即可用
    w._hover_update_at(0.03, 800.0)
    assert w._hover_overlay.isHidden() is False


def test_spec_measure_markers_show_and_clear(qapp):
    w = _spec_widget(qapp)
    w.measure_markers_show(0.01, 0.05, 400.0, 800.0)
    assert len(w._measure_items) == 2
    assert w._measure_item_labels[0].toPlainText() == "A(0.010s)"
    w.measure_markers_clear()
    assert all(not it.isVisible() for it in w._measure_items)


# ----------------------------------------------------------------------
# 视图层（formants）
# ----------------------------------------------------------------------

def _formant_widget(qapp):
    from acouscope.ui.widgets.formants import FormantWidget

    w = FormantWidget()
    times = np.arange(4, dtype=np.float64) * 0.05  # 0.00 / 0.05 / 0.10 / 0.15
    freqs = np.zeros((4, 4))
    freqs[1, 0] = 500.0  # F1 @ t=0.05
    freqs[3, 0] = 600.0  # F1 @ t=0.15
    w.set_data(times, freqs, np.zeros_like(freqs))
    return w


def test_formant_hover_readout_text(qapp):
    w = _formant_widget(qapp)
    text = w.hover_readout_at(0.077, 550.0)
    assert "t=0.077s" in text and "550.0 Hz" in text and "386.3 cents" in text, text


def test_formant_freq_at_f1_nearest_frame(qapp):
    w = _formant_widget(qapp)
    assert w.freq_at(0.05) == 500.0
    assert w.freq_at(0.15) == 600.0
    assert w.freq_at(0.10) is None  # 最近帧 F1 为 0 → 该时刻不可用
    assert w.freq_at(0.0) is None  # 最近帧 F1 为 0


# ----------------------------------------------------------------------
# StatusBarSegments 临时段（Pδ 落点）
# ----------------------------------------------------------------------

def test_statusbar_temporary_text_show_clear_not_in_keys(qapp):
    seg = StatusBarSegments()
    try:
        assert "seg_temp_readout" not in seg.keys()
        seg.set_temporary_text("Δt 0.300 s")
        assert seg._temp_label.isHidden() is False
        assert seg._temp_label.text() == "Δt 0.300 s"
        assert "seg_temp_readout" not in seg.keys()  # 不入注册表/右键/持久化
        seg.clear_temporary()
        assert seg._temp_label.isHidden() is True
        assert seg._temp_label.text() == ""
        seg.set_temporary_text(None)  # None 等价清空，零异常
        assert seg._temp_label.isHidden() is True
    finally:
        seg.close()


# ----------------------------------------------------------------------
# main_window 层：测量（复用选区）分发与 enable
# ----------------------------------------------------------------------

class _FakeMeasureView(QWidget):
    """测量读数替身：freq_at + A/B 标记/overlay 桩（零绘图）。"""

    def __init__(self, freq_at=None):
        super().__init__()
        self._freq_at = freq_at if freq_at is not None else (lambda t: None)
        self.marker_calls = []
        self.clear_calls = 0
        self.overlay_calls = []

    def freq_at(self, t: float):
        return self._freq_at(float(t))

    def measure_markers_show(self, t0, t1, f0, f1):
        self.marker_calls.append((float(t0), float(t1), f0, f1))

    def measure_markers_clear(self):
        self.clear_calls += 1

    def set_readout_overlay(self, text):
        self.overlay_calls.append(text)


def _sig():
    sr = 8000
    t = np.arange(int(sr * 2.0)) / sr
    return sr, t, 0.5 * np.sin(2 * np.pi * 440 * t)


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """带已加载音频 + 波形数据的 MainWindow（不 show）；controller 播放打桩。"""
    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow

    monkeypatch.setenv("HOME", str(tmp_path))

    controller = AppController()
    sr, t, x = _sig()
    controller.load_from_array(x, sr)
    playing = {"v": False}
    monkeypatch.setattr(controller, "is_playing", lambda: playing["v"])
    monkeypatch.setattr(controller, "play", lambda: None)
    monkeypatch.setattr(controller, "pause", lambda: None)
    monkeypatch.setattr(controller, "set_position", lambda *_: None)
    monkeypatch.setattr(controller, "get_position", lambda: 0.0)

    w = MainWindow(controller)
    w.waveform_widget.set_data(t, x, sample_rate=sr)
    yield w
    w.close()


def _status_text(window) -> str:
    seg = window.status_segments
    return seg._temp_label.text() if getattr(seg, "_temp_label", None) else ""


def test_measure_selection_full_readout(window, monkeypatch):
    """freq_at 返回 440/660 → Δt/ΔHz=220/Δcent≈701.955/比率 1.5。"""
    fake = _FakeMeasureView(lambda t: 440.0 if t <= 0.3 else 660.0)
    monkeypatch.setattr(window.waveform_widget, "get_selection", lambda: (0.2, 0.5))
    monkeypatch.setattr(window, "_current_measure_widget", lambda: fake)
    # 禁触发分析 spy：测量路径不得触碰任何 _on_*_analysis
    monkeypatch.setattr(window, "_on_spectrogram_analysis", lambda *a, **k: pytest.fail("不应触发分析"))
    monkeypatch.setattr(window, "_on_pitch_analysis", lambda *a, **k: pytest.fail("不应触发分析"))
    monkeypatch.setattr(window, "_on_formant_analysis", lambda *a, **k: pytest.fail("不应触发分析"))

    window._on_measure_selection()

    text = _status_text(window)
    assert "0.300" in text, text  # Δt
    assert "220.0" in text, text  # ΔHz
    assert "702.0" in text, text  # Δcent≈701.955 → 1 位小数
    assert "1.500" in text, text  # 比率
    assert fake.marker_calls == [(0.2, 0.5, 440.0, 660.0)]
    assert fake.overlay_calls and fake.overlay_calls[-1] == text
    assert window._measure_active is True
    assert window.action_measure_clear.isEnabled() is True


def test_measure_selection_freq_none_dt_only(window, monkeypatch):
    """任一频率不可用（None）→ 只留 Δt，A/B 标记仍画。"""
    fake = _FakeMeasureView(lambda t: None)
    monkeypatch.setattr(window.waveform_widget, "get_selection", lambda: (0.2, 0.5))
    monkeypatch.setattr(window, "_current_measure_widget", lambda: fake)
    window._on_measure_selection()

    text = _status_text(window)
    assert "0.300" in text and "ΔHz" not in text, text
    assert fake.marker_calls == [(0.2, 0.5, None, None)]


def test_measure_selection_zero_freq_defensive(window, monkeypatch):
    """f0=0（无声/除零防御）→ 不除零、只留 Δt。"""
    fake = _FakeMeasureView(lambda t: 0.0)
    monkeypatch.setattr(window.waveform_widget, "get_selection", lambda: (0.2, 0.5))
    monkeypatch.setattr(window, "_current_measure_widget", lambda: fake)
    window._on_measure_selection()
    text = _status_text(window)
    assert "0.300" in text and "ΔHz" not in text and "ratio" not in text, text


def test_measure_no_selection_toast(window, monkeypatch):
    """无选区 → 温和 toast（禁选中区不存在时崩溃）。"""
    import acouscope.ui.main_window as mw_mod

    toasts = []
    monkeypatch.setattr(mw_mod, "show_toast",
                        lambda parent, msg, level="info": toasts.append(msg))
    monkeypatch.setattr(window.waveform_widget, "get_selection", lambda: None)
    window._on_measure_selection()
    assert len(toasts) == 1 and toasts[0]  # 温和提示一次


def test_measure_clear_action(window, monkeypatch):
    """清除测量：markers 清 + 临时段清 + enable 联动（不动选区）。"""
    fake = _FakeMeasureView(lambda t: 440.0 if t <= 0.3 else 660.0)
    window._spectrogram_widget = fake  # _on_measure_clear 遍历真实属性
    monkeypatch.setattr(window.waveform_widget, "get_selection", lambda: (0.2, 0.5))
    monkeypatch.setattr(window, "_current_measure_widget", lambda: fake)
    window._on_measure_selection()
    assert fake.clear_calls == 0
    window._on_measure_clear()
    assert fake.clear_calls == 1
    assert window._measure_active is False
    assert _status_text(window) == ""
    assert window.action_measure_clear.isEnabled() is False


def test_selection_clear_clears_measure_markers(window, monkeypatch):
    """Esc/清选区（selectionChanged None）→ 测量标记随之清除（规格 C）。"""
    fake = _FakeMeasureView(lambda t: 440.0 if t <= 0.3 else 660.0)
    window._spectrogram_widget = fake  # 测量清除联动遍历真实属性
    monkeypatch.setattr(window, "_current_measure_widget", lambda: fake)
    window.waveform_widget.set_selection(0.2, 0.5)  # 真实选区（emit 变更）
    window._on_measure_selection()
    assert window._measure_active is True
    window.waveform_widget.clear_selection()  # → selectionChanged(None)
    assert window._measure_active is False
    assert fake.clear_calls == 1
    assert _status_text(window) == ""


def test_measure_actions_enable_rules(window, monkeypatch):
    """enable：测量选区=有选区且当前激活时间类视图；清除测量=有标记时。"""
    fake = _FakeMeasureView()
    # 无选区 → 禁
    window._update_measure_actions()
    assert window.action_measure_selection.isEnabled() is False
    # 有选区但当前激活视图不在时间类/未构建 → 禁
    monkeypatch.setattr(window.waveform_widget, "get_selection", lambda: (0.2, 0.5))
    window._update_measure_actions()
    assert window.action_measure_selection.isEnabled() is False
    # 有选区 + 激活时间类视图 → 启
    monkeypatch.setattr(window, "_current_measure_widget", lambda: fake)
    window._update_measure_actions()
    assert window.action_measure_selection.isEnabled() is True
    assert window.action_measure_clear.isEnabled() is False
    # 清除测量 enable=有标记时（测量后）
    window._on_measure_selection()
    assert window.action_measure_clear.isEnabled() is True
    window._on_measure_clear()
    assert window.action_measure_clear.isEnabled() is False


def test_hover_readout_upload_to_statusbar(window):
    """视图 hover 上抛 → 状态栏临时段；None 清空。"""
    window._on_view_hover_readout("t=1.000s | 440.0 Hz | +0.0 cents")
    assert _status_text(window) == "t=1.000s | 440.0 Hz | +0.0 cents"
    window._on_view_hover_readout(None)
    assert _status_text(window) == ""


def test_hover_leave_restores_measure_text(window, monkeypatch):
    """悬停读数临时接管状态栏；鼠标离开(None)恢复测量结果文本。"""
    fake = _FakeMeasureView(lambda t: 440.0 if t <= 0.3 else 660.0)
    monkeypatch.setattr(window.waveform_widget, "get_selection", lambda: (0.2, 0.5))
    monkeypatch.setattr(window, "_current_measure_widget", lambda: fake)
    window._on_measure_selection()
    measure_text = _status_text(window)
    assert measure_text
    window._on_view_hover_readout("t=1.000s | 440.0 Hz | +0.0 cents")
    assert _status_text(window).startswith("t=1.000s")
    window._on_view_hover_readout(None)
    assert _status_text(window) == measure_text  # 恢复测量结果
    window._on_measure_clear()
    window._on_view_hover_readout(None)
    assert _status_text(window) == ""


# ----------------------------------------------------------------------
# A4-R3：频谱「音符」读数统一基准 + 区间统计 cent 均值读当前 A4
# ----------------------------------------------------------------------

def _spectrum_note_text(qapp, freq_hz):
    """频谱游标信息栏的「音符:」读数文本（默认 piano 单位：x 即 Hz）。"""
    from acouscope.ui.widgets.spectrum import SpectrumWidget

    w = SpectrumWidget()
    try:
        freqs = np.linspace(0.0, 8000.0, 513)
        w.set_data(freqs, np.zeros_like(freqs), sample_rate=16000.0)
        w.v_line.setValue(w._hz_to_display_x(float(freq_hz)))
        w._on_cursor_moved()
        return w.lbl_note.text()
    finally:
        w.close()


def test_spectrum_note_readout_single_reference_at_442(qapp, monkeypatch):
    """A4=442：550Hz 音符读数音名与音分同基准（音分仍按 440 算则 -14 必红）。"""
    from acouscope.dsp import units

    monkeypatch.setattr(units, "_reference_hz", 442.0)
    text = _spectrum_note_text(qapp, 550.0)
    assert "音符: C#5 (-22 音分)" in text, text  # ★ 442 口径（音名 C#5 亦按 442 取整）
    assert "(-14 音分)" not in text, text  # ★ 反对照：音分仍写死 440 则必红
    # 动态交叉验证：音分 == 相对"按当前 A4 取整半音"的偏差
    midi_round = round(float(units.hz_to_midi(550.0)))
    cents = float(units.hz_to_cents(550.0)) - float(
        units.hz_to_cents(units.midi_to_hz(midi_round)))
    assert f"({cents:+.0f} 音分)" in text, text


def test_region_cent_mean_follows_current_a4(monkeypatch):
    """A4=442：pitch_stats.cent_mean == hz_to_cents(550)（写死 440 则 386.31 必红）。"""
    from acouscope.dsp import units
    from acouscope.ui.region_stats import pitch_stats

    monkeypatch.setattr(units, "_reference_hz", 442.0)
    times = np.array([0.0, 0.02, 0.04])
    f0 = np.array([550.0, 550.0, 0.0])
    st = pitch_stats(times, f0, 0.0, 0.04)
    assert st["cent_mean"] == pytest.approx(float(units.hz_to_cents(550.0)))
    assert st["cent_mean"] == pytest.approx(378.4623, abs=1e-3)  # ★ 442 口径
    assert abs(st["cent_mean"] - 386.3137) > 0.5  # ★ 反对照：仍写死 440 则必红


def test_spectrum_note_and_region_default_a4_unchanged(qapp, monkeypatch):
    """A4=440（默认）：音符读数与 cent 均值逐字/逐位不变。"""
    from acouscope.dsp import units
    from acouscope.ui.region_stats import pitch_stats

    monkeypatch.setattr(units, "_reference_hz", 440.0)
    assert _spectrum_note_text(qapp, 550.0) == "音符: C#5 (-14 音分)"  # 逐字不变
    times = np.array([0.0, 0.02])
    f0 = np.array([550.0, 550.0])
    st = pitch_stats(times, f0, 0.0, 0.02)
    assert st["cent_mean"] == pytest.approx(386.3137138648348)  # 逐位不变


# ----------------------------------------------------------------------
# A4-R4：两处文案去写死 440（静态断言 + 反向防退化）
# ----------------------------------------------------------------------

def test_a4r4_freq_units_cents_tip_and_menu_refline_have_no_440():
    """★ 静态断言（主判据）：cents 提示与 menu_refline 三语值均不含字面 440。"""
    from acouscope.dsp.units import FREQ_UNITS
    from acouscope.i18n import _STRINGS

    cents_tip = next(tip for label, key, tip in FREQ_UNITS if key == "cents")
    assert "440" not in cents_tip, cents_tip
    entry = _STRINGS["pitch.menu_refline"]
    for lang in ("en_US", "zh_CN", "zh_TW"):
        assert "440" not in entry[lang], (lang, entry[lang])


def test_a4r4_reverse_no_structural_regression():
    """★ 反向（防退化）：FREQ_UNITS 仍含 cents 键且仍 6 项；menu_refline 三语齐、键名未变。"""
    from acouscope.dsp.units import FREQ_UNITS
    from acouscope.i18n import _STRINGS

    assert len(FREQ_UNITS) == 6
    assert any(key == "cents" for _label, key, _tip in FREQ_UNITS)
    assert "pitch.menu_refline" in _STRINGS
    entry = _STRINGS["pitch.menu_refline"]
    assert set(entry) == {"en_US", "zh_CN", "zh_TW"}
    for lang in ("en_US", "zh_CN", "zh_TW"):
        assert entry[lang], (lang, entry[lang])


