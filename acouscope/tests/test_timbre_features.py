# SPDX-License-Identifier: GPL-3.0-only
"""音色特征补全的数值验证测试。"""
import numpy as np

from acouscope.analysis import TimbreAnalyzer

SR = 44100


def _tone(freq=440.0, dur=2.0, amp=0.5):
    t = np.arange(int(SR * dur)) / SR
    return amp * np.sin(2 * np.pi * freq * t)


def _decaying_tone(freq=440.0, dur=3.0, amp=0.5, tau=0.5):
    t = np.arange(int(SR * dur)) / SR
    # 起振 20ms 线性爬升，随后指数衰减
    env = np.exp(-t / tau)
    ramp = np.minimum(t / 0.02, 1.0)
    return amp * ramp * env * np.sin(2 * np.pi * freq * t)


def _mid_frames(arr, n_edge=3):
    """剔除 STFT reflect 填充产生的边界帧。"""
    return arr[n_edge : len(arr) - n_edge] if len(arr) > 2 * n_edge else arr


class TestSpectralFlux:
    def test_steady_tone_flux_near_zero(self):
        """稳态正弦中间各帧通量远小于谱峰（边界帧有 reflect 填充效应，已剔除）。

        残余通量（≈主瓣 -90 dB）来自非整周期截断的加窗泄漏随帧起始
        相位的微小起伏，属真实物理现象。
        """
        feats = TimbreAnalyzer(SR).spectral_features(_tone())
        flux = feats["spectral_flux"]
        assert len(flux) == len(feats["times"])
        # 谱峰幅度约 0.5×0.5×1024≈256，阈值 0.1 为其 -68 dB
        assert np.max(_mid_frames(flux)) < 0.1

    def test_noise_flux_much_larger(self):
        """白噪声帧间频谱随机变化 → 通量显著大于稳态音。"""
        rng = np.random.default_rng(0)
        noise = rng.standard_normal(int(SR * 2)) * 0.1
        ta = TimbreAnalyzer(SR)
        f_tone = ta.spectral_features(_tone())["spectral_flux"]
        f_noise = ta.spectral_features(noise)["spectral_flux"]
        assert np.mean(_mid_frames(f_noise)) > 1000 * max(
            np.mean(_mid_frames(f_tone)), 1e-12
        )

    def test_onset_produces_flux_spike(self):
        """静音后突发音 → 起音处通量出现尖峰。"""
        silence = np.zeros(int(SR * 0.5))
        sig = np.concatenate([silence, _tone(dur=1.0)])
        feats = TimbreAnalyzer(SR).spectral_features(sig)
        flux = feats["spectral_flux"]
        times = feats["times"]
        onset_mask = (times > 0.4) & (times < 0.7)
        assert np.max(flux[onset_mask]) > 10 * np.median(flux[~onset_mask])


class TestSpectralFlatness:
    def test_noise_flatter_than_tone(self):
        rng = np.random.default_rng(1)
        noise = rng.standard_normal(int(SR * 2)) * 0.1
        ta = TimbreAnalyzer(SR)
        f_tone = float(np.mean(ta.spectral_features(_tone())["spectral_flatness"]))
        f_noise = float(np.mean(ta.spectral_features(noise)["spectral_flatness"]))
        assert f_noise > 10 * f_tone

    def test_flatness_range(self):
        feats = TimbreAnalyzer(SR).spectral_features(_tone())
        assert np.all(feats["spectral_flatness"] >= 0)
        assert np.all(feats["spectral_flatness"] <= 1 + 1e-9)


class TestEnvelopeStats:
    def test_decaying_tone_attack_decay(self):
        ta = TimbreAnalyzer(SR)
        stats = ta._envelope_stats(_decaying_tone())
        assert "attack_time" in stats and 0 <= stats["attack_time"] < 0.15
        # tau=0.5 的指数衰减到 10% 需 ln(10)·τ ≈ 1.15 s
        assert "decay_time" in stats and 0.8 < stats["decay_time"] < 1.8

    def test_steady_tone_no_decay(self):
        """稳态音不衰减 → decay_time 不在结果中。"""
        stats = TimbreAnalyzer(SR)._envelope_stats(_tone(dur=2.0))
        assert "decay_time" not in stats

    def test_short_signal_returns_empty(self):
        stats = TimbreAnalyzer(SR)._envelope_stats(np.zeros(1000))
        assert len(stats) == 0

    def test_new_envelope_features(self):
        """新增时间包络特征（对齐 TimbreToolbox TEErep）。"""
        stats = TimbreAnalyzer(SR)._envelope_stats(_decaying_tone())
        assert "attack_slope" in stats
        assert "temporal_centroid" in stats
        assert "effective_duration" in stats


class TestGlobalFeatures:
    def test_keys_present_for_decaying_tone(self):
        g = TimbreAnalyzer(SR).global_features(_decaying_tone())
        expected = [
            "peak_dbfs", "rms_db", "crest_factor", "dc_offset",
            "zcr", "attack_time", "decay_time",
            "spectral_centroid", "spectral_bandwidth", "spectral_rolloff",
            "spectral_flatness", "spectral_skewness", "spectral_kurtosis",
        ]
        for key in expected:
            assert key in g, f"缺少特征: {key}"

    def test_sine_levels(self):
        """0.5 幅度正弦：峰值 ≈ -6 dBFS，RMS ≈ -9 dBFS，波峰因数 ≈ 3 dB。"""
        g = TimbreAnalyzer(SR).global_features(_tone(amp=0.5))
        assert abs(g["peak_dbfs"] - (-6.02)) < 0.1
        assert abs(g["rms_db"] - (-9.03)) < 0.1
        assert abs(g["crest_factor"] - 3.01) < 0.1
        assert abs(g["dc_offset"]) < 0.01

    def test_dc_offset_detected(self):
        sig = _tone(amp=0.4) + 0.05
        g = TimbreAnalyzer(SR).global_features(sig)
        assert abs(g["dc_offset"] - 5.0) < 0.1

    def test_centroid_of_tone(self):
        g = TimbreAnalyzer(SR).global_features(_tone(freq=1000.0))
        assert abs(g["spectral_centroid"] - 1000.0) < 30
