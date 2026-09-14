# SPDX-License-Identifier: GPL-3.0-only
"""T-916 选区区间分析分派回归测试。

离屏环境：构造 MainWindow(controller) 但不 show()；
用 stub 替换真实重计算（pYIN/LPC/MFCC/STFT），只验证主窗分派逻辑：
区间裁剪 / times 偏移 +t0 / 缓存键含区间（防串档）/ 视图复用 / 默认路径零改变。
"""

import re
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from acouscope.app.controller import AppController
from acouscope.i18n import tr
from acouscope.ui.main_window import MainWindow

_SR = 8000
_DURATION = 10.0
_MAIN_PY = (
    Path(__file__).resolve().parent.parent
    / "src" / "acouscope" / "ui" / "main_window.py"
)

# 禁词以拼接构造，避免模式字面量自身被扫中（同 test_file_browser.py 口径）。
_BANNED = "Mel" + "odyne"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """带已加载音频的主窗口（绕过付费门控）。"""

    monkeypatch.setenv("HOME", str(tmp_path))

    controller = AppController()
    t = np.arange(int(_SR * _DURATION)) / _SR
    data = 0.5 * np.sin(2 * np.pi * 440.0 * t)
    controller.load_from_array(data, _SR)

    w = MainWindow(controller)
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


@pytest.fixture
def sync_analysis(window, monkeypatch):
    monkeypatch.setattr(MainWindow, "_run_analysis_async", _sync_async)


class _FakePitchTrack:
    """伪 PitchTrack：times 从 0 起（相对时间），供 +t0 偏移断言。"""

    def __init__(self, n_frames, sr, hop=256):
        self.times = np.arange(n_frames) * hop / sr
        self.f0_hz = np.full(n_frames, 220.0)
        self.confidence = np.full(n_frames, 0.9)


def _fake_detect_pyin(calls):
    def detect(signal, sr, **kw):
        calls.append(len(signal))
        n = max(1, (len(signal) - 4096) // 256 + 1)
        return _FakePitchTrack(n, sr)

    return detect


class TestValidation:
    def test_invalid_region_no_recompute(self, window, monkeypatch):
        """t1<=t0 → 不触发重算且有提示。"""
        from acouscope.analysis import pitch as pitch_mod

        calls = []
        monkeypatch.setattr(pitch_mod, "detect_pyin", _fake_detect_pyin(calls))
        monkeypatch.setattr(
            "acouscope.analysis.pitch_grid.build_pitch_grid",
            lambda times, f0, conf, mode: ("GRID", times),
        )
        toasts = []
        monkeypatch.setattr(
            "acouscope.ui.main_window.show_toast",
            lambda w, msg, level="info": toasts.append((level, msg)),
        )

        _set_tab(window, 3)
        window._on_analyze_region(2.0, 2.0)  # t1 == t0
        window._on_analyze_region(3.0, 2.0)  # t1 < t0

        assert calls == [], "非法区间不得触发重算"
        assert any(msg == tr("analyze_region.invalid") for _lv, msg in toasts)

    def test_idx0_no_offline(self, window, monkeypatch):
        """idx=0 波形视图 → 提示无离线分析且不重算。"""
        toasts = []
        monkeypatch.setattr(
            "acouscope.ui.main_window.show_toast",
            lambda w, msg, level="info": toasts.append((level, msg)),
        )
        _set_tab(window, 0)
        window._on_analyze_region(1.0, 2.5)

        assert ("info", tr("analyze_region.no_offline")) in toasts
        assert window._live_widget("_spectrogram_widget") is None
        assert window._live_widget("_pitch_widget") is None

    def test_status_bar_text(self, window):
        """状态栏显示区间（i18n 三语 key 格式化）。

        用 idx=0：分派前状态栏已写入区间文本，idx=0 早退不覆写
        （idx≥1 的模块函数会以自己的完成文案收尾，属既有行为）。
        """
        _set_tab(window, 0)
        window._on_analyze_region(1.0, 2.5)
        expected = tr("analyze_region.status").format(t0="1.000", t1="2.500")
        assert window.lbl_status.text() == expected


class TestSpectrogramRegion:
    def test_region_slicing_and_times_offset(self, window, monkeypatch):
        """idx=2：STFT 输入长度 ≈ 区间样点数（±1），结果 times[0] ≈ t0。"""
        from acouscope.dsp import stft as stft_mod

        calls = []

        class _FakeSTFT:
            def __init__(self, n_fft=2048, hop_length=512, window="hann"):
                self.n_fft = n_fft
                self.hop_length = hop_length

            def magnitude(self, signal, sample_rate, db_scale=True, db_ref=1.0):
                calls.append(len(signal))
                n = max(1, (len(signal) - self.n_fft) // self.hop_length + 1)
                freqs = np.linspace(0.0, sample_rate / 2, self.n_fft // 2 + 1)
                times = np.arange(n) * self.hop_length / sample_rate
                mag = np.zeros((len(freqs), n))
                return freqs, times, mag

        monkeypatch.setattr(stft_mod, "STFTEngine", _FakeSTFT)
        _set_tab(window, 2)
        window._on_analyze_region(2.0, 4.0)

        expected = int((4.0 - 2.0) * _SR)
        assert calls and abs(calls[0] - expected) <= 1, (
            f"STFT 输入长度 {calls[0] if calls else None} ≠ 区间样点数 {expected}±1"
        )
        spec = window._live_widget("_spectrogram_widget")
        assert spec is not None
        assert abs(spec._times[0] - 2.0) < 1e-9, "语谱图横轴须为绝对时间（+t0）"


class TestPitchRegion:
    def _stub(self, window, monkeypatch):
        from acouscope.analysis import pitch as pitch_mod

        calls = []
        monkeypatch.setattr(pitch_mod, "detect_pyin", _fake_detect_pyin(calls))
        monkeypatch.setattr(
            "acouscope.analysis.pitch_grid.build_pitch_grid",
            lambda times, f0, conf, mode: ("GRID", times),
        )
        return calls

    def test_region_slicing_and_times_offset(self, window, monkeypatch, sync_analysis):
        """idx=3：检测输入长度 ≈ 区间样点数（±1），结果 times[0] ≈ t0。"""
        calls = self._stub(window, monkeypatch)
        _set_tab(window, 3)
        window._on_analyze_region(2.0, 4.0)

        expected = int((4.0 - 2.0) * _SR)
        assert calls and abs(calls[0] - expected) <= 1, (
            f"pYIN 输入长度 {calls[0] if calls else None} ≠ 区间样点数 {expected}±1"
        )
        fp = window._audio_fingerprint()
        cached = window._result_cache.get(("pitch", fp, 2.0, 4.0))
        assert cached is not None, "区间结果须写入含区间的缓存键"
        times, f0, _grid = cached
        assert abs(times[0] - 2.0) < 1e-9, "音高横轴须为绝对时间（+t0）"

    def test_cache_same_region_hit(self, window, monkeypatch, sync_analysis):
        """同区间二次调用命中缓存（不重算）。"""
        calls = self._stub(window, monkeypatch)
        _set_tab(window, 3)
        window._on_analyze_region(2.0, 4.0)
        n1 = len(calls)
        assert n1 == 1
        window._on_analyze_region(2.0, 4.0)
        assert len(calls) == n1, "同区间二次调用应命中缓存"

    def test_cache_different_region_miss(self, window, monkeypatch, sync_analysis):
        """不同区间互不命中。"""
        calls = self._stub(window, monkeypatch)
        _set_tab(window, 3)
        window._on_analyze_region(2.0, 4.0)
        window._on_analyze_region(5.0, 7.0)
        assert len(calls) == 2, "不同区间不得互相命中缓存"

    def test_cache_no_cross_pollution(self, window, monkeypatch, sync_analysis):
        """全文件键与区间键互不污染。"""
        calls = self._stub(window, monkeypatch)
        _set_tab(window, 3)
        fp = window._audio_fingerprint()

        window._on_analyze_region(2.0, 4.0)
        assert ("pitch", fp) not in window._result_cache, "区间结果不得写入全文件键"

        window._on_pitch_analysis()  # region=None 默认路径
        assert ("pitch", fp) in window._result_cache, "全文件结果须写入全文件键"
        assert ("pitch", fp, 2.0, 4.0) in window._result_cache

        n_before = len(calls)
        window._on_analyze_region(2.0, 4.0)  # 区间键已存在 → 命中
        assert len(calls) == n_before, "区间键命中后不得重算"


class TestFormantRegion:
    def test_region_slicing_and_times_offset(self, window, monkeypatch, sync_analysis):
        """idx=4：LPC 输入长度 ≈ 区间样点数（±1），结果 times[0] ≈ t0。"""
        import acouscope.analysis as analysis_pkg

        calls = []

        class _FakeFormantAnalyzer:
            def __init__(self, sr):
                self.sr = sr

            def extract_lpc(self, data, frame_size=1024, hop_length=512):
                calls.append(len(data))
                n = max(1, (len(data) - frame_size) // hop_length + 1)
                times = np.arange(n) * hop_length / self.sr
                freqs = np.zeros((n, 3))
                bws = np.zeros((n, 3))
                return times, freqs, bws

        monkeypatch.setattr(analysis_pkg, "FormantAnalyzer", _FakeFormantAnalyzer)
        _set_tab(window, 4)
        window._on_analyze_region(2.0, 4.0)

        expected = int((4.0 - 2.0) * _SR)
        assert calls and abs(calls[0] - expected) <= 1, (
            f"LPC 输入长度 {calls[0] if calls else None} ≠ 区间样点数 {expected}±1"
        )
        fp = window._audio_fingerprint()
        cached = window._result_cache.get(("formant", fp, 2.0, 4.0))
        assert cached is not None
        times, _freqs, _bws = cached
        assert abs(times[0] - 2.0) < 1e-9, "共振峰横轴须为绝对时间（+t0）"


class TestTimbreRegion:
    def test_region_slicing_and_times_offset(self, window, monkeypatch, sync_analysis):
        """idx=5：MFCC/HNR 输入长度 ≈ 区间样点数（±1），times/hnr_times[0] ≈ t0。"""
        import acouscope.analysis as analysis_pkg

        calls = []

        class _FakeTimbreAnalyzer:
            def __init__(self, sr):
                self.sr = sr

            def mfcc(self, data, n_mfcc=13, n_fft=2048, hop_length=512):
                calls.append(len(data))
                n = max(1, (len(data) - n_fft) // hop_length + 1)
                times = np.arange(n) * hop_length / self.sr
                return times, np.zeros((n, n_mfcc))

            def hnr(self, data, frame_size=2048, hop_length=512):
                calls.append(len(data))
                n = max(1, (len(data) - frame_size) // hop_length + 1)
                times = np.arange(n) * hop_length / self.sr
                return times, np.zeros(n)

            def spectral_features(self, data):
                return {}

            def global_features(self, data):
                return {}

        monkeypatch.setattr(analysis_pkg, "TimbreAnalyzer", _FakeTimbreAnalyzer)
        _set_tab(window, 5)
        window._on_analyze_region(2.0, 4.0)

        expected = int((4.0 - 2.0) * _SR)
        assert calls and all(abs(c - expected) <= 1 for c in calls), (
            f"音色各分析输入长度 {calls} ≠ 区间样点数 {expected}±1"
        )
        fp = window._audio_fingerprint()
        cached = window._result_cache.get(("timbre", fp, 2.0, 4.0))
        assert cached is not None
        times, _mfcc, hnr_times, _hnr, _feat, _glob = cached
        assert abs(times[0] - 2.0) < 1e-9, "MFCC 横轴须为绝对时间（+t0）"
        assert abs(hnr_times[0] - 2.0) < 1e-9, "HNR 横轴须为绝对时间（+t0）"


class TestFFTRegion:
    def test_region_average_spectrum(self, window, monkeypatch):
        """idx=1：区域平均谱分支被调用（STFT 输入 = 区间，标题含「区域平均谱」）。"""
        from acouscope.dsp import stft as stft_mod

        calls = []

        class _FakeSTFT:
            def __init__(self, n_fft=2048, hop_length=512, window="hann"):
                self.n_fft = n_fft
                self.hop_length = hop_length

            def magnitude(self, signal, sample_rate, db_scale=True, db_ref=1.0):
                calls.append(len(signal))
                n = max(1, (len(signal) - self.n_fft) // self.hop_length + 1)
                freqs = np.linspace(0.0, sample_rate / 2, self.n_fft // 2 + 1)
                times = np.arange(n) * self.hop_length / sample_rate
                mag = np.ones((len(freqs), n))
                return freqs, times, mag

        monkeypatch.setattr(stft_mod, "STFTEngine", _FakeSTFT)
        _set_tab(window, 1)
        window._on_analyze_region(2.0, 4.0)

        expected = int((4.0 - 2.0) * _SR)
        assert calls and abs(calls[0] - expected) <= 1, (
            f"区域平均谱 STFT 输入 {calls[0] if calls else None} ≠ 区间样点数 {expected}±1"
        )
        spec = window._live_widget("_spectrum_widget")
        assert spec is not None
        assert "区域平均谱" in spec.lbl_title.text()

    def test_region_too_short_degrades(self, window, monkeypatch):
        """区域过短（不足一帧）→ 显式降级提示，不得静默失败。"""
        from acouscope.dsp import stft as stft_mod

        class _EmptySTFT:
            def __init__(self, n_fft=2048, hop_length=512, window="hann"):
                self.n_fft = n_fft

            def magnitude(self, signal, sample_rate, db_scale=True, db_ref=1.0):
                freqs = np.linspace(0.0, sample_rate / 2, self.n_fft // 2 + 1)
                return freqs, np.array([]), np.zeros((len(freqs), 0))

        toasts = []
        monkeypatch.setattr(stft_mod, "STFTEngine", _EmptySTFT)
        monkeypatch.setattr(
            "acouscope.ui.main_window.show_toast",
            lambda w, msg, level="info": toasts.append((level, msg)),
        )
        _set_tab(window, 1)
        window._on_analyze_region(0.0, 0.05)

        assert ("warning", tr("analyze_region.fft_unsupported")) in toasts


class TestDefaultPathUnchanged:
    def test_full_file_cache_keys_in_source(self):
        """region=None 默认路径：全文件缓存键语义逐字保留（源码锚点断言）。"""
        src = _MAIN_PY.read_text(encoding="utf-8")
        assert 'cache_key = ("pitch", fp)' in src
        assert 'cache_key = ("formant", fp)' in src
        assert 'cache_key = ("timbre", fp)' in src

    def test_full_file_pitch_unchanged(self, window, monkeypatch, sync_analysis):
        """region=None：全文件重算，times 从 0 起（无偏移），写全文件键。"""
        from acouscope.analysis import pitch as pitch_mod

        calls = []
        monkeypatch.setattr(pitch_mod, "detect_pyin", _fake_detect_pyin(calls))
        monkeypatch.setattr(
            "acouscope.analysis.pitch_grid.build_pitch_grid",
            lambda times, f0, conf, mode: ("GRID", times),
        )
        _set_tab(window, 3)
        window._on_pitch_analysis()

        assert calls and abs(calls[0] - int(_SR * _DURATION)) <= 1, (
            "全文件模式输入长度须为全长"
        )
        fp = window._audio_fingerprint()
        cached = window._result_cache.get(("pitch", fp))
        assert cached is not None
        times, _f0, _grid = cached
        assert abs(times[0]) < 1e-9, "全文件模式 times 不得偏移"


class TestStatic:
    def test_banned_word_zero_hits(self):
        """禁词 0 命中（主窗 + 本测试文件）。"""
        for f in (_MAIN_PY, Path(__file__)):
            assert _BANNED not in f.read_text(encoding="utf-8")

    def test_no_hex_px_in_added_lines(self):
        """新增 T-916 行无硬编码 hex/px。"""
        src = _MAIN_PY.read_text(encoding="utf-8")
        added = [ln for ln in src.splitlines() if "T-916" in ln]
        assert added, "应存在 T-916 标记行"
        for ln in added:
            assert not re.search(r"#[0-9a-fA-F]{6}\b", ln), f"hex 硬编码: {ln}"
            assert "px" not in ln, f"px 硬编码: {ln}"

    def test_no_new_qdialog(self):
        """无新建 QDialog（T-916 标记行不得出现 QDialog）。"""
        src = _MAIN_PY.read_text(encoding="utf-8")
        for ln in src.splitlines():
            if "T-916" in ln:
                assert "QDialog" not in ln, f"禁新建 QDialog: {ln}"
