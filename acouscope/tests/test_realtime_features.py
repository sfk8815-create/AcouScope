# SPDX-License-Identifier: GPL-3.0-only
"""实时特征分析（借鉴 Realtime_PyAudio_FFT）单元测试。"""

import numpy as np
import pytest

from acouscope.analysis.realtime_features import (
    BAND_RANGES,
    analyze_all,
    compute_band_envelopes,
    compute_frame_log_spectrogram,
    compute_log_spectrum,
    detect_onsets,
    estimate_bpm,
    log_bin_map,
    tau_to_alpha,
)


@pytest.fixture
def drum_signal():
    """120 BPM 鼓机信号：kick 每 0.5 s + 高频击打每 0.25 s。"""
    sr = 44100
    t = np.arange(int(sr * 8)) / sr
    sig = np.zeros_like(t)
    rng = np.random.default_rng(7)
    for k in range(16):
        i0 = int(k * 0.5 * sr)
        seg = min(int(0.08 * sr), len(t) - i0)
        if seg <= 0:
            break
        sig[i0:i0 + seg] += 0.9 * np.sin(2*np.pi*70*t[:seg]) * np.exp(-t[:seg]*40)
        hi = min(int(0.03 * sr), len(t) - i0)
        sig[i0:i0 + hi] += 0.3 * rng.standard_normal(hi) * np.exp(-np.arange(hi)/sr*150)
    return sig, sr


class TestBandEnvelopes:
    def test_output_ranges(self, drum_signal):
        sig, sr = drum_signal
        times, bands = compute_band_envelopes(sig, sr)
        assert len(times) == len(bands["low"]) == len(bands["mid"]) == len(bands["high"])
        for name in BAND_RANGES:
            assert bands[name].min() >= 0.0
            assert bands[name].max() <= 1.0
            # 鼓声信号应有明显动态
            assert bands[name].max() > 0.5

    def test_kick_drives_low_band(self, drum_signal):
        sig, sr = drum_signal
        times, bands = compute_band_envelopes(sig, sr)
        # 低频包络在 kick 时刻（0, 0.5, 1.0, ...）附近应有峰值
        for kick_t in (0.05, 1.05, 3.05):
            i = int(kick_t / (times[1] - times[0]))
            assert bands["low"][i] > 0.3

    def test_empty_input(self):
        times, bands = compute_band_envelopes(np.zeros(0), 44100)
        assert len(times) == 0
        assert all(len(b) == 0 for b in bands.values())


class TestLogSpectrum:
    def test_bin_geometry(self, drum_signal):
        sig, sr = drum_signal
        centers, db = compute_log_spectrum(sig, sr, n_bins=128)
        assert len(centers) == 128 == len(db)
        assert db.min() >= -90.0
        # 对数分布：相邻 bin 比值恒定
        ratios = centers[1:] / centers[:-1]
        assert np.allclose(ratios, ratios[0], rtol=1e-6)

    def test_tone_detection(self):
        sr = 44100
        t = np.arange(sr) / sr
        sig = 0.8 * np.sin(2 * np.pi * 440 * t)
        centers, db = compute_log_spectrum(sig, sr)
        peak_bin = int(np.argmax(db))
        assert abs(centers[peak_bin] - 440) / 440 < 0.15


class TestLogBinMap:
    def test_all_bins_mapped(self):
        assign, counts, centers = log_bin_map(513, 44100, n_bins=128, f_min=30.0)
        valid = assign[assign >= 0]
        assert len(valid) > 400          # 30 Hz ~ 22.05 kHz 覆盖绝大多数 bin
        assert valid.max() < 128
        assert counts.sum() == len(valid)
        assert len(centers) == 128


class TestOnsetDetection:
    def test_kick_onsets_counted(self, drum_signal):
        sig, sr = drum_signal
        times, bands = compute_band_envelopes(sig, sr)
        result = detect_onsets(bands["low"], 10.0, "low")
        # 16 个 kick，允许边界误差
        assert 14 <= len(result.times) <= 16
        # onset 时刻应接近 0.5 s 的倍数
        for t_on in result.times:
            assert min(abs(t_on - k * 0.5) for k in range(17)) < 0.1

    def test_novelty_nonnegative(self, drum_signal):
        sig, sr = drum_signal
        _, bands = compute_band_envelopes(sig, sr)
        result = detect_onsets(bands["mid"], 10.0, "mid")
        assert (result.novelty >= 0).all()

    def test_silence_no_onsets(self):
        result = detect_onsets(np.zeros(500), 10.0, "low")
        assert len(result.times) == 0


class TestBpmEstimate:
    def test_exact_120(self):
        onsets = np.arange(8) * 0.5
        assert estimate_bpm(onsets) == pytest.approx(120.0)

    def test_octave_folding(self):
        # 0.25s 间隔 = 240 BPM → 折叠到 120
        onsets = np.arange(8) * 0.25
        assert estimate_bpm(onsets) == pytest.approx(120.0)
        # 1.0s 间隔 = 60 BPM → 保持 60
        onsets = np.arange(8) * 1.0
        assert estimate_bpm(onsets) == pytest.approx(60.0)

    def test_insufficient_samples(self):
        assert estimate_bpm(np.array([0.0, 0.5, 1.0])) == 0.0

    def test_outlier_rejection(self):
        # 均匀 0.5s 间隔 + 一个 5s 的异常间隔
        onsets = np.array([0, 0.5, 1.0, 1.5, 2.0, 7.0, 7.5, 8.0])
        assert estimate_bpm(onsets) == pytest.approx(120.0)


class TestAnalyzeAll:
    def test_end_to_end(self, drum_signal):
        sig, sr = drum_signal
        r = analyze_all(sig, sr)
        assert r["bpm"] == pytest.approx(120.0, abs=2.0)
        assert set(r["bands"].keys()) == set(BAND_RANGES)
        assert set(r["onsets"].keys()) == set(BAND_RANGES)
        assert len(r["spectrum_freqs"]) == 128


class TestFrameLogSpectrogram:
    def test_shape_and_range(self, drum_signal):
        sig, sr = drum_signal
        times, centers, dbm = compute_frame_log_spectrogram(sig, sr, hop_ms=20.0)
        assert dbm.dtype == np.float32
        assert dbm.shape == (len(times), 128)
        assert len(centers) == 128
        assert dbm.min() >= -90.0
        # 帧间隔应接近 hop_ms
        assert abs((times[1] - times[0]) - 0.02) < 0.005
        # 总时长覆盖全文件
        assert times[-1] <= len(sig) / sr and times[-1] > len(sig) / sr - 0.1

    def test_time_varying_spectrum(self):
        """前半 220 Hz、后半 880 Hz：对应帧的峰值 bin 应不同。"""
        sr = 44100
        t = np.arange(sr * 2) / sr
        sig = np.where(t < 1.0, np.sin(2*np.pi*220*t), np.sin(2*np.pi*880*t))
        times, centers, dbm = compute_frame_log_spectrogram(sig, sr)
        i_early = int(np.searchsorted(times, 0.3))
        i_late = int(np.searchsorted(times, 1.7))
        early_peak = centers[int(np.argmax(dbm[i_early]))]
        late_peak = centers[int(np.argmax(dbm[i_late]))]
        assert abs(early_peak - 220) / 220 < 0.2
        assert abs(late_peak - 880) / 880 < 0.2
        assert early_peak < late_peak

    def test_empty_input(self):
        times, centers, dbm = compute_frame_log_spectrogram(np.zeros(0), 44100)
        assert len(times) == 0
        assert dbm.shape == (0, 128)


class TestTauToAlpha:
    def test_limits(self):
        assert tau_to_alpha(0.01, 1e-6) > 0.999   # tau→0: 全速跟随
        assert tau_to_alpha(0.01, 1e9) < 1e-5     # tau→∞: 不动
