# SPDX-License-Identifier: GPL-3.0-only
"""T-1019 region 类型契约回归测试（「region 类型污染」bug 防线）。

真机 bug（2026-09-10）：QAction.triggered(bool checked) 直连六个分析槽时，
checked(False) 成为 region 的位置实参 → 槽内 ``t0, _t1 = region`` 抛
``TypeError: cannot unpack non-iterable bool object``，从「分析」菜单进入
FFT/语谱/音高/共振峰/音色/3D 全部失败。

本文件锁定三条契约（离屏环境：构造主窗口但**不做任何显示调用**）：
A. 触发路径进入分析槽时，region ∈ {tuple[float, float], None}，**绝不 bool**；
B. 分析槽类型守卫：误传 bool / 标注区域对象 / 长度异常 → 退化为 None（全文件），
   不抛异常（第二道防线，根因修复在 _create_actions 的 λ 包装）；
C. 波形 getter 契约解耦：get_selection() = 分析区间（元组/None）；
   selected_region() = 标注区域对象（对象/None，带 .start_time/.end_time）。
"""

import re
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from acouscope.app.controller import AppController
from acouscope.ui.main_window import MainWindow, _normalize_region

_SR = 8000
_DURATION = 4.0

_SLOTS = ("fft", "spectrogram", "pitch", "formant", "timbre", "spectrogram3d")
_ACTIONS = {
    "fft": "action_fft",
    "spectrogram": "action_spectrogram",
    "pitch": "action_pitch",
    "formant": "action_formants",
    "timbre": "action_timbre",
    "spectrogram3d": "action_spectrogram3d",
}
# 分析标签索引（_on_analyze_region 分派口径）：1 FFT / 2 语谱 / 3 音高 / 4 共振峰 / 5 音色 / 6 3D
_TAB_INDEX = {
    "fft": 1,
    "spectrogram": 2,
    "pitch": 3,
    "formant": 4,
    "timbre": 5,
    "spectrogram3d": 6,
}

_SRC = Path(__file__).resolve().parent.parent / "src" / "acouscope"
_MAIN_PY = _SRC / "ui" / "main_window.py"
_WAVEFORM_PY = _SRC / "ui" / "widgets" / "waveform.py"
# 禁词以拼接构造，避免模式字面量自身被扫中（同 test_file_browser.py 口径）
_BANNED = "Mel" + "odyne"


def _assert_no_bool(recorded, where=""):
    """契约断言：记录到的 region 只允许 tuple[float, float] 或 None。"""
    for name, region in recorded:
        assert not isinstance(region, bool), (
            f"{where} {name} 收到 bool region={region!r}（region 类型污染回归）"
        )
        assert region is None or (
            isinstance(region, tuple)
            and len(region) == 2
            and all(isinstance(v, float) for v in region)
        ), f"{where} {name} 收到非法 region={region!r}（{type(region).__name__}）"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _load_waveform(window):
    """给波形控件喂数据（选区/标注 API 均要求 _times 非空）。"""
    t = np.arange(int(_SR * _DURATION)) / _SR
    x = (0.5 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
    window.waveform_widget.set_data(t.astype(np.float32), x, sample_rate=float(_SR))


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """带已加载音频的主窗口（离屏，不做显示调用）。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    controller = AppController()
    t = np.arange(int(_SR * _DURATION)) / _SR
    controller.load_from_array(0.5 * np.sin(2 * np.pi * 440.0 * t), _SR)
    w = MainWindow(controller)
    _load_waveform(w)
    yield w
    w.close()


@pytest.fixture
def quiet_playback(window, monkeypatch):
    """屏蔽真实播放副作用（只验 region 语义，不验音频输出）。"""
    c = window.controller
    for name, value in (
        ("play", lambda: None),
        ("pause", lambda: None),
        ("set_position", lambda pos: None),
        ("is_playing", lambda: False),
        ("set_loop", lambda a, b: None),
        ("set_loop_enabled", lambda flag: None),
    ):
        monkeypatch.setattr(c, name, value, raising=False)
    return window


@pytest.fixture
def spy_window(qapp, monkeypatch, tmp_path):
    """构造前替换 6 个分析槽为记录器 → QAction/信号接线绑定记录器。

    记录 (槽名, 收到的 region)，用于断言真实触发路径的 region 实参类型。
    """
    recorded = []

    for slot in _SLOTS:
        def _make(name):
            def _spy(self, region=None, *args, **kwargs):
                recorded.append((name, region))

            return _spy

        monkeypatch.setattr(MainWindow, f"_on_{slot}_analysis", _make(slot))

    monkeypatch.setenv("HOME", str(tmp_path))
    controller = AppController()
    t = np.arange(int(_SR * _DURATION)) / _SR
    controller.load_from_array(0.5 * np.sin(2 * np.pi * 440.0 * t), _SR)
    w = MainWindow(controller)
    _load_waveform(w)
    w._t1019_recorded = recorded
    yield w
    w.close()


def _set_tab(window, index):
    """设标签索引但不触发 _on_analysis_changed（避免真实重算）。"""
    bar = window.analysis_tab_bar
    bar.blockSignals(True)
    bar.setCurrentIndex(index)
    bar.blockSignals(False)


def _sync_async(self, status_text, compute_fn, on_done, error_prefix):
    """异步壳替换为同步执行（确定性，无 QThread 时序）。"""
    on_done(compute_fn())


class _FakeSTFT:
    def __init__(self, n_fft=2048, hop_length=512, window="hann"):
        self.n_fft = n_fft
        self.hop_length = hop_length

    def magnitude(self, signal, sample_rate, db_scale=True, db_ref=1.0):
        n = max(1, (len(signal) - self.n_fft) // self.hop_length + 1)
        freqs = np.linspace(0.0, sample_rate / 2, self.n_fft // 2 + 1)
        times = np.arange(n) * self.hop_length / sample_rate
        return freqs, times, np.zeros((len(freqs), n))


class _FakeFormantAnalyzer:
    def __init__(self, sr):
        self.sr = sr

    def extract_lpc(self, data, frame_size=1024, hop_length=512):
        n = max(1, (len(data) - frame_size) // hop_length + 1)
        times = np.arange(n) * hop_length / self.sr
        return times, np.zeros((n, 3)), np.zeros((n, 3))


class _FakeTimbreAnalyzer:
    def __init__(self, sr):
        self.sr = sr

    def mfcc(self, data, n_mfcc=13, n_fft=2048, hop_length=512):
        n = max(1, (len(data) - n_fft) // hop_length + 1)
        return np.arange(n) * hop_length / self.sr, np.zeros((n, n_mfcc))

    def hnr(self, data, frame_size=2048, hop_length=512):
        n = max(1, (len(data) - frame_size) // hop_length + 1)
        return np.arange(n) * hop_length / self.sr, np.zeros(n)

    def spectral_features(self, data):
        return {}

    def global_features(self, data):
        return {}


@pytest.fixture
def heavy_stub(window, monkeypatch):
    """替换重算内核（pYIN/LPC/MFCC/STFT），并记录各内核收到的输入长度。"""
    from acouscope.analysis import pitch as pitch_mod
    from acouscope.dsp import stft as stft_mod
    import acouscope.analysis as analysis_pkg

    calls = []

    def _detect_pyin(signal, sr, **kw):
        calls.append(("pitch", len(signal)))

        class _Track:
            def __init__(self, n, sample_rate):
                self.times = np.arange(n) * 256 / sample_rate
                self.f0_hz = np.full(n, 220.0)
                self.confidence = np.full(n, 0.9)

        return _Track(max(1, (len(signal) - 4096) // 256 + 1), sr)

    class _RecordingFormant(_FakeFormantAnalyzer):
        def extract_lpc(self, data, frame_size=1024, hop_length=512):
            calls.append(("formant", len(data)))
            return super().extract_lpc(data, frame_size, hop_length)

    class _RecordingTimbre(_FakeTimbreAnalyzer):
        def mfcc(self, data, n_mfcc=13, n_fft=2048, hop_length=512):
            calls.append(("timbre", len(data)))
            return super().mfcc(data, n_mfcc, n_fft, hop_length)

        def hnr(self, data, frame_size=2048, hop_length=512):
            calls.append(("timbre", len(data)))
            return super().hnr(data, frame_size, hop_length)

    class _RecordingSTFT(_FakeSTFT):
        def magnitude(self, signal, sample_rate, db_scale=True, db_ref=1.0):
            calls.append(("stft", len(signal)))
            return super().magnitude(signal, sample_rate, db_scale, db_ref)

    monkeypatch.setattr(MainWindow, "_run_analysis_async", _sync_async)
    monkeypatch.setattr(pitch_mod, "detect_pyin", _detect_pyin)
    monkeypatch.setattr(
        "acouscope.analysis.pitch_grid.build_pitch_grid",
        lambda times, f0, conf, mode: ("GRID", times),
    )
    monkeypatch.setattr(analysis_pkg, "FormantAnalyzer", _RecordingFormant)
    monkeypatch.setattr(analysis_pkg, "TimbreAnalyzer", _RecordingTimbre)
    monkeypatch.setattr(stft_mod, "STFTEngine", _RecordingSTFT)
    window._t1019_calls = calls
    return window


class TestTriggerPathRegionContract:
    """A. 真实触发路径（菜单 QAction / 选区信号 / 试听循环）→ region 只允许元组或 None。"""

    def test_six_actions_trigger_without_audio_region_none(self, spy_window):
        """六个分析 QAction 触发：region 恒 None（QAction.triggered(bool) 不得当 region）。"""
        rec = spy_window._t1019_recorded
        for slot, action in _ACTIONS.items():
            rec.clear()
            getattr(spy_window, action).trigger()
            assert [name for name, _ in rec] == [slot], f"{action} 未落到 {slot}"
            _assert_no_bool(rec, where=f"{action} 触发")
            assert rec[0][1] is None, f"{action} 默认全文件路径 region 应为 None，实得 {rec[0][1]!r}"

    def test_six_actions_trigger_with_selection_region_none(self, spy_window):
        """有波形选区时点菜单：仍走全文件（region=None），且不把选区对象当 region。"""
        spy_window.waveform_widget.set_selection(1.0, 2.0)
        assert spy_window.waveform_widget.get_selection() == (1.0, 2.0)
        rec = spy_window._t1019_recorded
        for action in _ACTIONS.values():
            rec.clear()
            getattr(spy_window, action).trigger()
            _assert_no_bool(rec, where=f"{action} 有选区触发")
            assert all(r is None for _n, r in rec)

    def test_analyze_region_signal_passes_tuple(self, spy_window):
        """右键「分析此区域」→ analyzeRegionRequested(t0, t1) → 六槽收元组 [t0, t1]。"""
        rec = spy_window._t1019_recorded
        for slot, index in _TAB_INDEX.items():
            _set_tab(spy_window, index)
            rec.clear()
            spy_window.waveform_widget.analyzeRegionRequested.emit(1.0, 2.0)
            assert [name for name, _ in rec] == [slot]
            _assert_no_bool(rec, where=f"分析此区域 idx={index}")
            assert rec[0][1] == (1.0, 2.0), f"{slot} 应收到分析区间元组，实得 {rec[0][1]!r}"

    def test_annotation_region_present_does_not_pollute(self, spy_window, quiet_playback):
        """存在标注区域对象时：触发六动作仍 None，A/B 循环用对象解出元组（解耦）。"""
        wf = spy_window.waveform_widget
        region = wf.add_region(1.0, 2.0, "R")
        wf._selected_region = region
        assert not isinstance(region, tuple), "标注区域必须是对象而非元组"
        assert hasattr(region, "start_time") and hasattr(region, "end_time")

        rec = spy_window._t1019_recorded
        for action in _ACTIONS.values():
            rec.clear()
            getattr(spy_window, action).trigger()
            _assert_no_bool(rec, where=f"标注区域存在时 {action}")
        # A/B 循环路径消费标注区域对象（对象→元组），不得污染分析槽
        rec.clear()
        spy_window._on_toggle_loop(True)
        _assert_no_bool(rec, where="A/B 循环")
        assert rec == [], "A/B 循环不得调用任何分析槽"

    def test_empty_selection_preview_shows_toast_no_analysis(self, spy_window, monkeypatch):
        """空选集试听：温和提示、不触发任何分析槽、region 无 bool。"""
        toasts = []
        monkeypatch.setattr(
            "acouscope.ui.main_window.show_toast",
            lambda w, msg, level="info": toasts.append((level, msg)),
        )
        assert spy_window.waveform_widget.get_selection() is None
        rec = spy_window._t1019_recorded
        spy_window._on_preview_selection()
        assert toasts, "空选集试听应有提示"
        assert rec == [], "空选集试听不得调用分析槽"

    def test_preview_and_loop_with_selection_region_contract(self, spy_window, quiet_playback):
        """有选区试听 / A/B 循环：解包均来自元组，分析槽不被 bool 污染。"""
        spy_window.waveform_widget.set_selection(0.5, 1.5)
        rec = spy_window._t1019_recorded
        spy_window._on_preview_selection()
        spy_window._on_toggle_loop(True)
        _assert_no_bool(rec, where="试听/循环")
        assert rec == [], "试听与循环路径不得调用分析槽"


class TestSlotRegionGuard:
    """B. 分析槽类型守卫：误传非法 region → 退化为 None，不抛异常。"""

    _BAD = [False, True, 0, 3.14, "abc", object(), (1.0,), (1.0, 2.0, 3.0), ([1.0, 2.0],)]

    def test_all_six_slots_reject_bad_region(self, heavy_stub, monkeypatch, qapp):
        """六槽 × 非法 region：绝不抛 cannot unpack bool，且 3D 拿到 None。"""
        w = heavy_stub
        seen_3d = []
        monkeypatch.setattr(
            MainWindow,
            "_build_spectrogram3d",
            lambda self, gen, region=None: seen_3d.append(region),
        )
        for slot in _SLOTS:
            fn = getattr(w, f"_on_{slot}_analysis")
            for bad in self._BAD:
                fn(bad)  # 不抛异常即通过（根因修复前：bool → cannot unpack）
        qapp.processEvents()  # 3D 走 QTimer.singleShot(0) 延迟一拍，泵事件后落账
        _assert_no_bool([("spectrogram3d", r) for r in seen_3d], where="guard")
        assert seen_3d and all(r is None for r in seen_3d), (
            f"3D 延迟构建收到的 region 应全部为 None，实得 {seen_3d!r}"
        )

    def test_bad_region_degrades_to_full_file_input(self, heavy_stub):
        """非法 region → 重算输入为全长（全文件语义），而合法元组 → 区间采样点数。"""
        w = heavy_stub
        full = int(_SR * _DURATION)
        cases = (("pitch", w._on_pitch_analysis), ("formant", w._on_formant_analysis),
                 ("timbre", w._on_timbre_analysis))
        for kind, fn in cases:
            w._t1019_calls.clear()
            fn(False)
            lengths = [n for k, n in w._t1019_calls if k == kind]
            assert lengths, f"{kind} 未触发重算"
            assert all(abs(n - full) <= 1 for n in lengths), (
                f"{kind} 非法 region 应退化为全文件输入，实得 {lengths}"
            )

            w._t1019_calls.clear()
            fn((0.5, 1.5))
            lengths = [n for k, n in w._t1019_calls if k == kind]
            expected = int(1.0 * _SR)
            assert lengths and all(abs(n - expected) <= 1 for n in lengths), (
                f"{kind} 合法区间应裁剪到区间采样点数，实得 {lengths}"
            )

    def test_normalize_region_table(self):
        """_normalize_region 取值表（契约最小实现）。"""
        assert _normalize_region(None) is None
        for bad in (False, True, 0, "abc", object(), (1.0,), (1.0, 2.0, 3.0), (None, 2.0)):
            assert _normalize_region(bad) is None, f"{bad!r} 应兜底为 None"
        assert _normalize_region((1, 2)) == (1.0, 2.0)
        assert _normalize_region([1.5, 2.5]) == (1.5, 2.5)
        assert isinstance(_normalize_region((1, 2))[0], float)


class TestWaveformGetterContract:
    """C. 波形 getter 契约解耦（分析区间 vs 标注区域）。"""

    def test_get_selection_tuple_or_none(self, window):
        wf = window.waveform_widget
        assert wf.get_selection() is None
        wf.set_selection(1.0, 2.0)
        sel = wf.get_selection()
        assert isinstance(sel, tuple) and len(sel) == 2
        assert all(isinstance(v, float) for v in sel)
        wf.clear_selection()
        assert wf.get_selection() is None

    def test_selected_region_object_or_none(self, window):
        wf = window.waveform_widget
        assert wf.selected_region() is None
        region = wf.add_region(1.0, 2.0, "R")
        wf._selected_region = region
        got = wf.selected_region()
        assert got is region
        assert not isinstance(got, tuple), "标注区域 getter 不得返回元组"
        assert hasattr(got, "start_time") and hasattr(got, "end_time")
        assert (float(got.start_time), float(got.end_time)) == (1.0, 2.0)

    def test_two_getters_are_decoupled(self, window):
        """同一时刻两者各自成立：选区元组 ≠ 标注对象，互不替代。"""
        wf = window.waveform_widget
        wf.set_selection(0.5, 1.5)
        region = wf.add_region(2.0, 3.0, "R2")
        wf._selected_region = region
        assert wf.get_selection() == (0.5, 1.5)
        assert wf.selected_region() is region


class TestStatic:
    def test_banned_word_zero_hits(self):
        for f in (_MAIN_PY, _WAVEFORM_PY, Path(__file__)):
            assert _BANNED not in f.read_text(encoding="utf-8")

    def test_no_hex_px_in_t1019_lines(self):
        for f in (_MAIN_PY, _WAVEFORM_PY):
            src = f.read_text(encoding="utf-8")
            marked = [ln for ln in src.splitlines() if "T-1019" in ln]
            assert marked, f"{f.name} 应存在 T-1019 标记行"
            for ln in marked:
                assert not re.search(r"#[0-9a-fA-F]{6}\b", ln), f"hex 硬编码: {ln}"
                assert "px" not in ln, f"px 硬编码: {ln}"

    def test_no_new_qdialog(self):
        for f in (_MAIN_PY, _WAVEFORM_PY):
            for ln in f.read_text(encoding="utf-8").splitlines():
                if "T-1019" in ln:
                    assert "QDialog" not in ln, f"禁新建 QDialog: {ln}"

    def test_source_has_lambda_wiring(self):
        """根因修复锚点：六动作经 λ 吞掉 checked（防被回退成直连）。"""
        src = _MAIN_PY.read_text(encoding="utf-8")
        for slot in _SLOTS:
            assert f"lambda _checked=False: self._on_{slot}_analysis()" in src, (
                f"action_{slot} 应经 λ 包装触发"
            )
