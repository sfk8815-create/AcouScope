# SPDX-License-Identifier: GPL-3.0-only
"""T-327 Pε 选区区间统计 离屏测试。

覆盖：
  ① region_stats 纯函数（构造断言）：RMS/峰值 dB+线性、帧中心归属切片、
     f0 均值/中位/范围/voiced 占比数值、音分均值（A4=440）；
  ② 防御：空片段/静音/无 voiced → None 或占位；形状不一致 → ValueError；
     无重叠/空 times → None；
  ③ pitch 控件 result_arrays 只读访问器；InspectorPanel 统计只读文本 +
     复制按钮（clipboard）；reset 回占位；
  ④ main_window 层：注入桩音高源（result_arrays）+ 真实音频 →
     输出文本含 时长/RMS/voiced 计数/f0 均值，检查器只读区更新；分析 spy
     抛错证明零分析调用；无选区/无缓存 → toast 引导；enable 规则。

纪律：不 show 主窗；controller 播放打桩；不触发分析（monkeypatch 抛错）。
"""

import math

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from acouscope.ui.region_stats import (  # noqa: E402
    pitch_stats,
    region_peak,
    region_rms,
    slice_in_region,
)


# ----------------------------------------------------------------------
# ① 纯函数构造断言
# ----------------------------------------------------------------------

def test_rms_sine_amplitude_half():
    """0.5 幅度正弦 → RMS 线性 0.3536 / dB -9.03。"""
    sr = 8000
    t = np.arange(sr) / sr
    x = 0.5 * np.sin(2 * np.pi * 440.0 * t)
    lin, db = region_rms(x)
    assert lin is not None and db is not None
    assert lin == pytest.approx(0.5 / math.sqrt(2), abs=1e-4)
    assert db == pytest.approx(20.0 * math.log10(lin), abs=1e-3)


def test_rms_silence_and_empty_none():
    assert region_rms(np.zeros(64)) == (None, None)
    assert region_rms(np.array([])) == (None, None)


def test_peak_values():
    x = np.array([0.0, -0.6, 0.3, 0.9, -0.2])
    lin, db = region_peak(x)
    assert lin == pytest.approx(0.9)
    assert db == pytest.approx(20.0 * math.log10(0.9), abs=1e-3)
    assert region_peak(np.zeros(8)) == (None, None)
    assert region_peak(np.array([])) == (None, None)


def test_slice_in_region_inclusive_and_empty():
    times = np.arange(10, dtype=np.float64) * 0.1  # 0.0 ~ 0.9
    values = np.arange(10, dtype=np.float64)
    tt, vv = slice_in_region(times, values, 0.2, 0.5)
    assert list(tt) == pytest.approx([0.2, 0.3, 0.4, 0.5])
    assert list(vv) == [2.0, 3.0, 4.0, 5.0]
    tt, vv = slice_in_region(times, values, 2.0, 3.0)  # 无覆盖
    assert tt.size == 0 and vv.size == 0
    tt, vv = slice_in_region(np.array([]), np.array([]), 0.0, 1.0)
    assert tt.size == 0


def test_slice_shape_mismatch_raises():
    with pytest.raises(ValueError):
        slice_in_region(np.arange(4), np.arange(3), 0.0, 1.0)


def test_pitch_stats_numeric():
    """已知区间 [0.2,0.7]：voiced 5/6；mean 528 / median 440 / 220 range / cent≈280.8。"""
    # 字面量时间轴 + 字面量边界（同字面量双等精确命中，避免浮点乘积累差）
    times = np.array([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
    f0 = np.array([0, 0, 440, 440, 440, 0, 660, 660, 0, 0], dtype=np.float64)
    s = pitch_stats(times, f0, 0.2, 0.7)
    assert s is not None
    assert s["frames"] == 6 and s["voiced"] == 5
    assert s["voiced_ratio"] == pytest.approx(5 / 6)
    assert s["f0_mean"] == pytest.approx(528.0)
    assert s["f0_median"] == pytest.approx(440.0)
    assert s["f0_min"] == pytest.approx(440.0)
    assert s["f0_max"] == pytest.approx(660.0)
    assert s["f0_range"] == pytest.approx(220.0)
    cent_660 = 1200.0 * math.log2(660.0 / 440.0)  # ≈701.955
    assert s["cent_mean"] == pytest.approx((3 * 0.0 + 2 * cent_660) / 5, abs=1e-3)


def test_pitch_stats_no_voiced_fields_none():
    times = np.arange(5, dtype=np.float64) * 0.1
    f0 = np.zeros(5)
    s = pitch_stats(times, f0, 0.0, 0.4)
    assert s is not None and s["voiced"] == 0 and s["voiced_ratio"] == 0.0
    assert s["f0_mean"] is None and s["cent_mean"] is None


def test_pitch_stats_empty_and_no_overlap_none():
    assert pitch_stats(np.array([]), np.array([]), 0.0, 1.0) is None
    times = np.arange(5, dtype=np.float64) * 0.1
    f0 = np.full(5, 440.0)
    assert pitch_stats(times, f0, 2.0, 3.0) is None  # 区间无帧


# ----------------------------------------------------------------------
# ② 视图/面板层
# ----------------------------------------------------------------------

def test_pitch_widget_result_arrays_accessor(qapp):
    from acouscope.ui.widgets.pitch import PitchContourWidget

    w = PitchContourWidget()
    times = np.arange(20, dtype=np.float64) * 0.02
    f0 = np.zeros(20)
    f0[5] = 440.0
    w.set_data(times, f0)
    rt, rf = w.result_arrays()
    assert np.array_equal(rt, times) and np.array_equal(rf, f0)


def test_inspector_stats_set_copy_and_reset(qapp):
    from acouscope.ui.widgets.panels.inspector_panel import InspectorPanel

    panel = InspectorPanel()
    try:
        assert panel.lbl_region_stats.text() == "—"
        assert panel.btn_copy_stats.isEnabled() is False
        text = "选区 0.500–0.900 s · 时长 0.400 s"
        panel.set_region_stats(text)
        assert panel.lbl_region_stats.text() == text
        assert panel.btn_copy_stats.isEnabled() is True
        QApplication.clipboard().setText("")  # 清空后复制
        panel._copy_stats()
        assert QApplication.clipboard().text() == text
        panel.set_region_stats(None)
        assert panel.lbl_region_stats.text() == "—"
        assert panel.btn_copy_stats.isEnabled() is False
        panel.reset()
        assert panel.lbl_region_stats.text() == "—"
    finally:
        panel.close()


# ----------------------------------------------------------------------
# ③ main_window 层
# ----------------------------------------------------------------------

def _sig():
    sr = 8000
    t = np.arange(int(sr * 2.0)) / sr
    return sr, t, 0.5 * np.sin(2 * np.pi * 440.0 * t)


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


class _FakePitchView(QWidget):
    """音高数据替身：只暴露 result_arrays（区间统计只读源）。"""

    def __init__(self, times, f0):
        super().__init__()
        self._times = times
        self._f0 = f0

    def result_arrays(self):
        return (self._times, self._f0)


def _pitch_over_region(t0, t1):
    """覆盖 [t0,t1] 的全浊音 f0=440 轨迹（帧步长 0.01）。"""
    times = np.arange(0.0, 2.0, 0.01)
    f0 = np.zeros_like(times)
    f0[(times >= t0) & (times <= t1)] = 440.0
    return times, f0


def _spy_no_analysis(window, monkeypatch):
    for name in ("_on_spectrogram_analysis", "_on_pitch_analysis",
                 "_on_formant_analysis", "_on_timbre_analysis",
                 "_on_fft_analysis", "_on_spectrogram3d_analysis"):
        monkeypatch.setattr(window, name, lambda *a, **k: pytest.fail("不应触发分析"))


def test_region_stats_full_output(window, monkeypatch):
    """选区 (0.5,0.9)：dt=0.400、RMS≈-9.0dB、peak≈-6.0dB、音高 41/41 @440Hz。"""
    monkeypatch.setattr(window.waveform_widget, "get_selection", lambda: (0.5, 0.9))
    times, f0 = _pitch_over_region(0.5, 0.9)
    window._pitch_widget = _FakePitchView(times, f0)
    _spy_no_analysis(window, monkeypatch)

    window._on_region_stats()

    text = window.inspector_panel.lbl_region_stats.text()
    assert "0.400" in text, text  # 时长
    assert "0.500" in text and "0.900" in text, text  # 起止
    assert "-9.0 dB" in text, text  # RMS dB
    assert "0.3536" in text, text  # RMS 线性
    assert "-6.0 dB" in text, text  # 峰值
    assert "41/41" in text, text  # voiced 计数
    assert "440.0" in text, text  # f0 均值（全 440）
    assert "+0.0" in text, text  # 音分均值（A4=440）
    assert window.inspector_panel.btn_copy_stats.isEnabled() is True


def test_region_stats_via_action_trigger(window, monkeypatch):
    """动作 trigger 等效 handler：菜单入口可用并落检查器。"""
    monkeypatch.setattr(window.waveform_widget, "get_selection", lambda: (0.2, 0.8))
    times, f0 = _pitch_over_region(0.2, 0.8)
    window._pitch_widget = _FakePitchView(times, f0)
    _spy_no_analysis(window, monkeypatch)
    window._update_measure_actions()  # enable 刷新（有音频有选区 → 动作可触发）
    assert window.action_region_stats.isEnabled() is True

    window.action_region_stats.trigger()

    text = window.inspector_panel.lbl_region_stats.text()
    assert "时长" in text or "duration" in text, text
    assert "0.600" in text, text  # dt = 0.8 - 0.2
    stats = pitch_stats(times, f0, 0.2, 0.8)
    assert f"{stats['voiced']}/{stats['frames']}" in text, text  # 帧计数自洽
    assert "440.0" in text, text


def test_region_stats_no_selection_toast(window, monkeypatch):
    import acouscope.ui.main_window as mw_mod

    toasts = []
    monkeypatch.setattr(mw_mod, "show_toast",
                        lambda parent, msg, level="info": toasts.append(msg))
    monkeypatch.setattr(window.waveform_widget, "get_selection", lambda: None)
    window._on_region_stats()
    assert len(toasts) == 1 and toasts[0]


def test_region_stats_no_cache_toast(window, monkeypatch):
    """无任何音高结果（无控件/无缓存）→ 引导 toast「请先分析此区域」。"""
    import acouscope.ui.main_window as mw_mod
    from acouscope.i18n import tr

    monkeypatch.setattr(window.waveform_widget, "get_selection", lambda: (0.5, 0.9))
    monkeypatch.delattr(window, "_pitch_widget", raising=False)
    # 缓存为空：pitch 区间键/全文件键均未命中
    toasts = []
    monkeypatch.setattr(mw_mod, "show_toast",
                        lambda parent, msg, level="info": toasts.append(msg))
    window._on_region_stats()
    assert len(toasts) == 1
    assert toasts[0] == tr("region_stats.no_cache")


def test_region_stats_actions_enable(window):
    """enable：区间统计 = 有音频且有选区（经 set_selection 真实链路刷新）。"""
    assert window.action_region_stats.isEnabled() is False  # 无选区
    window.waveform_widget.set_selection(0.2, 0.5)  # 触发 selectionChanged → 刷新
    assert window.action_region_stats.isEnabled() is True
    window.waveform_widget.clear_selection()
    assert window.action_region_stats.isEnabled() is False
