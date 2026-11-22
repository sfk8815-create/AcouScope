# SPDX-License-Identifier: GPL-3.0-only
"""T-321 结果缓存分级治理回归测试（离屏）。

进程内结果缓存 _result_cache 治理：全文件结果 ≤ 12 / 区间结果 ≤ 10 的分级
LRU 淘汰 + 语谱图结果入统一缓存（同音频/同区间二次进入免重算）+ 换音频
（fp 变）失效口径不变。

纯策略测试与链路测试共用真实 MainWindow(controller) 但均不 show()；链路测试
以 stub STFT 引擎计数 compute 次数，策略测试直接调用 _cache_* 注入合成键。
"""

import re
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from acouscope.app.controller import AppController
from acouscope.ui.main_window import MainWindow

_SR = 8000
_DURATION = 10.0
_MAIN_PY = (
    Path(__file__).resolve().parent.parent
    / "src" / "acouscope" / "ui" / "main_window.py"
)

# 禁词以拼接构造，避免模式字面量自身被扫中（同 test_file_browser.py 口径）。
_BANNED = "Mel" + "odyne"


def _fp(i):
    """合成全文件指纹（模拟不同音频内容）。"""
    return (_SR, i, 0.0)


class TestRetentionPolicy:
    """分级上限与淘汰序（纯逻辑，不触发任何 UI/分析）。"""

    def test_full_cap_thirteenth_evicts_oldest_full(self, window):
        """全文件 12 上限：第 13 个全文件 → 淘汰最旧全文件。"""
        w = window  # 函数级 fixture：每测试新 MainWindow，缓存为空
        for i in range(13):
            w._cache_put(("pitch", _fp(i)), f"p{i}")
        assert len(w._result_cache) == 12
        assert ("pitch", _fp(0)) not in w._result_cache, "最旧全文件应被淘汰"
        assert ("pitch", _fp(12)) in w._result_cache

    def test_region_cap_eleventh_evicts_only_oldest_region(self, window):
        """区间 10 上限：第 11 个区间 → 只淘汰最旧区间，全文件不淘汰。"""
        w = window  # 函数级 fixture：每测试新 MainWindow，缓存为空
        w._cache_put(("pitch", _fp(0)), "F0")
        w._cache_put(("formant", _fp(0)), "F1")
        for i in range(10):
            w._cache_put(("pitch", _fp(0), 0.0, float(i)), f"r{i}")
        w._cache_put(("pitch", _fp(0), 0.0, 10.0), "r10")
        regions = [k for k in w._result_cache if w._cache_is_region_key(k)]
        fulls = [k for k in w._result_cache if not w._cache_is_region_key(k)]
        assert len(regions) == 10
        assert len(fulls) == 2, "区间超限不得误伤全文件结果"
        assert ("pitch", _fp(0), 0.0, 0.0) not in regions, "最旧区间应被淘汰"
        assert ("pitch", _fp(0), 0.0, 10.0) in regions

    def test_overflow_bounded_with_regions_present(self, window):
        """全文件连续超限：只兜底淘汰最旧全文件，区间结果保持不动（全文件常驻语义反证）。"""
        w = window  # 函数级 fixture：每测试新 MainWindow，缓存为空
        for i in range(10):
            w._cache_put(("pitch", _fp(0), 0.0, float(i)), f"r{i}")
        for i in range(15):  # 15 个全文件（超 12）
            w._cache_put(("pitch", _fp(i)), f"p{i}")
        fulls = [k for k in w._result_cache if not w._cache_is_region_key(k)]
        regions = [k for k in w._result_cache if w._cache_is_region_key(k)]
        assert len(fulls) == 12, "全文件档应封顶 12"
        assert len(regions) == 10, "全文件淘汰不得触碰区间档"
        assert ("pitch", _fp(0)) not in fulls
        assert ("pitch", _fp(14)) in fulls
        assert len(w._result_cache) <= 22, "总条目必须封顶（12+10），不得无限增长"

    def test_get_refreshes_recency_order(self, window):
        """读取刷新使用序：超限时淘汰的是最久未用而非最早插入。"""
        w = window  # 函数级 fixture：每测试新 MainWindow，缓存为空
        for i in range(12):
            w._cache_put(("pitch", _fp(i)), f"p{i}")
        w._cache_get(("pitch", _fp(0)))  # 0 变最近使用
        w._cache_put(("pitch", _fp(12)), "p12")
        assert ("pitch", _fp(0)) in w._result_cache, "被刷新的键不得淘汰"
        assert ("pitch", _fp(1)) not in w._result_cache, "应淘汰最久未用的 1"

    def test_update_existing_key_keeps_single_entry(self, window):
        """覆盖写既有键：不产生重复条目，读回最新值。"""
        w = window  # 函数级 fixture：每测试新 MainWindow，缓存为空
        w._cache_put(("pitch", _fp(0)), "v1")
        w._cache_put(("pitch", _fp(0)), "v2")
        assert len(w._result_cache) == 1
        assert w._cache_get(("pitch", _fp(0))) == "v2"

    def test_region_key_shape_with_rounding(self, window):
        """_cache_key 区间键含 round(t0,3)/round(t1,3)，全文件键形态 (kind, fp)。"""
        w = window  # 函数级 fixture：每测试新 MainWindow，缓存为空
        fp = _fp(7)
        assert w._cache_key("pitch", fp) == ("pitch", fp)
        assert w._cache_key("pitch", fp, (2.0004, 4.0)) == (
            "pitch", fp, 2.0, 4.0)
        assert w._cache_is_region_key(("pitch", fp)) is False
        assert w._cache_is_region_key(("pitch", fp, 2.0, 4.0)) is True


# ---------------------------------------------------------------------------
# 第二段：语谱图入缓存链路测试（真实 MainWindow 但不 show，stub STFT 计数）
# ---------------------------------------------------------------------------


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


def _stub_stft(monkeypatch):
    """用假 STFT 引擎替换真实引擎，统计 magnitude（＝compute）调用次数。"""
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

    monkeypatch.setattr("acouscope.dsp.stft.STFTEngine", _FakeSTFT)
    return calls


class TestSpectrogramCache:
    def test_same_region_second_entry_hits(self, window, monkeypatch):
        """同区间二次进入命中缓存：STFT compute 仅 1 次，键含区间。"""
        calls = _stub_stft(monkeypatch)
        _set_tab(window, 2)
        window._on_spectrogram_analysis(region=(2.0, 4.0))
        assert len(calls) == 1
        window._on_spectrogram_analysis(region=(2.0, 4.0))
        assert len(calls) == 1, "同区间二次进入应命中缓存、免 STFT compute"
        fp = window._audio_fingerprint()
        assert ("spectrogram", fp, 2.0, 4.0) in window._result_cache
        spec = window._live_widget("_spectrogram_widget")
        assert spec is not None, "命中仍须完成视图构建（控件重建/游标/叠加接线）"

    def test_different_regions_miss_each_other(self, window, monkeypatch):
        """不同区间互不命中。"""
        calls = _stub_stft(monkeypatch)
        _set_tab(window, 2)
        window._on_spectrogram_analysis(region=(2.0, 4.0))
        window._on_spectrogram_analysis(region=(5.0, 7.0))
        assert len(calls) == 2, "不同区间不得互相命中缓存"

    def test_full_file_second_entry_hits(self, window, monkeypatch):
        """全文件语谱图二次进入命中：STFT compute 仅 1 次。"""
        calls = _stub_stft(monkeypatch)
        _set_tab(window, 2)
        window._on_spectrogram_analysis()
        assert len(calls) == 1
        window._on_spectrogram_analysis()
        assert len(calls) == 1, "全文件语谱图二次进入应命中缓存"
        fp = window._audio_fingerprint()
        assert ("spectrogram", fp) in window._result_cache

    def test_region_and_full_keys_no_cross(self, window, monkeypatch):
        """语谱图全文件键与区间键互不污染（沿用 T-916 断言口径）。"""
        calls = _stub_stft(monkeypatch)
        _set_tab(window, 2)
        fp = window._audio_fingerprint()
        window._on_spectrogram_analysis(region=(2.0, 4.0))
        assert ("spectrogram", fp) not in window._result_cache, "区间结果不得写全文件键"
        window._on_spectrogram_analysis()
        assert ("spectrogram", fp) in window._result_cache
        assert ("spectrogram", fp, 2.0, 4.0) in window._result_cache
        assert len(calls) == 2

    def test_fp_change_invalidates_spectrogram(self, window, monkeypatch):
        """换音频（fp 变）→ 语谱图不复用旧结果，重新 compute。"""
        calls = _stub_stft(monkeypatch)
        _set_tab(window, 2)
        window._on_spectrogram_analysis()
        assert len(calls) == 1
        t = np.arange(int(_SR * _DURATION)) / _SR
        window.controller.load_from_array(0.5 * np.sin(2 * np.pi * 660.0 * t), _SR)
        window._on_spectrogram_analysis()
        assert len(calls) == 2, "音频指纹变化后不得命中旧缓存"

    def test_pitch_overlay_reads_unified_cache(self, window, monkeypatch):
        """pitch overlay 读缓存走统一封装不回归：语谱图命中 pitch 缓存即叠加。"""
        from acouscope.analysis import pitch as pitch_mod

        calls = _stub_stft(monkeypatch)
        monkeypatch.setattr(
            "acouscope.ui.main_window.MainWindow._run_analysis_async",
            lambda self, status, compute_fn, on_done, err: on_done(compute_fn()),
        )
        monkeypatch.setattr(
            "acouscope.analysis.pitch_grid.build_pitch_grid",
            lambda times, f0, conf, mode, **kwargs: None,
        )

        class _FakeTrack:
            def __init__(self, n_frames):
                self.times = np.arange(n_frames) * 256 / _SR
                self.f0_hz = np.full(n_frames, 220.0)
                self.confidence = np.full(n_frames, 0.9)

        monkeypatch.setattr(
            pitch_mod, "detect_pyin",
            lambda signal, sr, **kw: _FakeTrack(max(1, (len(signal) - 4096) // 256 + 1)),
        )

        _set_tab(window, 3)
        window._on_pitch_analysis()
        fp = window._audio_fingerprint()
        assert ("pitch", fp) in window._result_cache

        _set_tab(window, 2)
        window._on_spectrogram_analysis()
        assert len(calls) == 1
        spec = window._live_widget("_spectrogram_widget")
        assert spec is not None and getattr(spec, "_pitch_track", None) is not None, (
            "语谱图应命中 pitch 缓存并叠加音高轨迹（PITCH_OVERLAY 不回归）"
        )


class TestStatic:
    def test_banned_word_zero_hits(self):
        """禁词 0 命中（主窗 + 本测试文件）。"""
        for f in (_MAIN_PY, Path(__file__)):
            assert _BANNED not in f.read_text(encoding="utf-8")

    def test_no_hex_px_in_added_lines(self):
        """新增 T-321 标记行无硬编码 hex/px。"""
        src = _MAIN_PY.read_text(encoding="utf-8")
        added = [ln for ln in src.splitlines() if "T-321" in ln]
        assert added, "应存在 T-321 标记行"
        for ln in added:
            assert not re.search(r"#[0-9a-fA-F]{6}\b", ln), f"hex 硬编码: {ln}"
            assert "px" not in ln, f"px 硬编码: {ln}"

    def test_no_new_qdialog(self):
        """T-321 标记行无新建 QDialog。"""
        src = _MAIN_PY.read_text(encoding="utf-8")
        for ln in src.splitlines():
            if "T-321" in ln:
                assert "QDialog" not in ln, f"禁新建 QDialog: {ln}"

    def test_cache_helpers_no_third_party_import(self):
        """分级缓存 helper 段仅用内建 dict，禁引第三方缓存库。"""
        src = _MAIN_PY.read_text(encoding="utf-8")
        seg = src.split("# T-321: 结果缓存统一读写封装", 1)[1]
        seg = seg.split("def _run_analysis_async", 1)[0]
        for ln in seg.splitlines():
            assert "import" not in ln, f"helper 段禁 import: {ln}"
        assert "self._result_cache[key] = result" in seg

