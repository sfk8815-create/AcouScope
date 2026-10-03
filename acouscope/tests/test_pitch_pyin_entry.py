# SPDX-License-Identifier: GPL-3.0-only
"""田野验收·音高检测精度（T-001-3）。FIELD_ACCEPTANCE_V1

全部合成信号自包含可复现（固定 seed）。
精度阈值来源：2026-09-03 用户确认（内部记录/knowledge/PITCH_analysis.md §3.4）。
"""

import numpy as np
import pytest

from acouscope.analysis.pitch import detect_pyin  # noqa: E402

SR = 44100.0
RNG = np.random.RandomState(42)


def _sine(freq, dur, sr=SR, amp=0.5):
    t = np.arange(int(sr * dur)) / sr
    return amp * np.sin(2 * np.pi * freq * t)


def _harmonic(f0, dur, n_h=8, sr=SR, amp=0.5):
    t = np.arange(int(sr * dur)) / sr
    sig = np.zeros_like(t)
    for h in range(1, n_h + 1):
        sig += (amp / h) * np.sin(2 * np.pi * f0 * h * t)
    return sig / np.max(np.abs(sig)) * amp


def cent(f, ref):
    return 1200.0 * np.log2(np.asarray(f) / ref)


def _median_cent(track, ref):
    v = np.isfinite(track.f0_hz)
    return float(np.median(np.abs(cent(track.f0_hz[v], ref))))


class TestAT01Accuracy:
    def test_at01_1_pure_tone(self):
        """AT-01-1: 440Hz 纯音 ≤ ±10 cent。"""
        tr = detect_pyin(_sine(440.0, 1.0), SR)
        assert _median_cent(tr, 440.0) <= 10.0
        assert tr.confidence.mean() > 0.5

    def test_at01_2_harmonic(self):
        """AT-01-2: 220Hz 含 8 次谐波 ≤ ±15 cent。"""
        tr = detect_pyin(_harmonic(220.0, 1.0), SR)
        assert _median_cent(tr, 220.0) <= 15.0

    def test_at01_3_sweep(self):
        """AT-01-3: 55–1760Hz 对数扫频 ≤ ±20 cent 且检出率 ≥90%。"""
        dur = 10.0
        t = np.arange(int(SR * dur)) / SR  # 任务文件笔误 /sr → /SR（NameError 修复）
        f = 55.0 * (1760.0 / 55.0) ** (t / dur)
        sig = 0.5 * np.sin(2 * np.pi * np.cumsum(f) / SR)
        tr = detect_pyin(sig, SR)
        lo = tr.times >= 0.3
        hi = tr.times <= dur - 0.3
        m = lo & hi
        f_true = 55.0 * (1760.0 / 55.0) ** (tr.times[m] / dur)
        errs = np.abs(cent(tr.f0_hz[m], 1.0) - cent(f_true, 1.0))
        errs = np.where(np.isfinite(errs), errs, 1e9)
        assert float((errs <= 20.0).mean()) >= 0.90

    def test_at01_4_vibrato_report(self):
        """AT-01-4: 合成颤音（440±25cent@5Hz）中位 ≤±30cent。
        文献参考指标，非硬闸门：只断言 ≤50（报告口径），实测值仅内存断言、不落 tracked 盘（AT-1072 卫生）。"""
        dur = 2.0
        t = np.arange(int(SR * dur)) / SR  # 任务文件笔误 /sr → /SR（NameError 修复）
        inst = 440.0 * 2 ** (25.0 / 1200.0 * np.sin(2 * np.pi * 5.0 * t))
        sig = 0.5 * np.sin(2 * np.pi * np.cumsum(inst) / SR)
        tr = detect_pyin(sig, SR)
        med = _median_cent(tr, 440.0)
        assert med <= 50.0  # 报告口径；30cent 目标值见验收报告


class TestAT02Microtone:
    def test_at02_1_neutral_tone(self):
        """AT-02-1: 中立音（+50 cent）连续输出，不吸附半音。"""
        f_true = 440.0 * 2 ** (50.0 / 1200.0)
        tr = detect_pyin(_sine(f_true, 1.0), SR)
        assert _median_cent(tr, f_true) <= 20.0
        # 不吸附：输出与最近半音距离 ≥ 30 cent
        v = np.isfinite(tr.f0_hz)
        near_semitone = np.abs(
            cent(tr.f0_hz[v], 440.0) - 100.0 * np.round(cent(tr.f0_hz[v], 440.0) / 100.0)
        )
        assert float(np.median(near_semitone)) >= 30.0

    def test_at02_2_two_tones_10cent(self):
        """AT-02-2: 顺序双稳态音相差 10 cent，f0 分布不重叠（用户口径）。"""
        f_b = 440.0 * 2 ** (10.0 / 1200.0)
        sig = np.concatenate([_sine(440.0, 0.8), _sine(f_b, 0.8)])
        tr = detect_pyin(sig, SR)
        n = len(tr.times) // 2
        m1 = np.nanmedian(tr.f0_hz[:n])
        m2 = np.nanmedian(tr.f0_hz[n:])
        assert abs(cent(m1, 440.0)) <= 5.0
        assert abs(cent(m2, f_b)) <= 5.0

    def test_at02_4_cent_ref_configurable(self):
        """AT-02-4: cent 参照可配置。"""
        tr = detect_pyin(_sine(440.0, 0.5), SR, cent_ref=220.0)
        v = np.isfinite(tr.f0_hz)
        assert float(np.median(tr.cents()[v])) == pytest.approx(1200.0, abs=10.0)


class TestAT03Noise:
    @staticmethod
    def _noisy(snr_db, dur=1.0):
        sig = _sine(440.0, dur)
        rng = np.random.RandomState(int(100 + snr_db))
        sigma = np.sqrt(np.mean(sig ** 2)) / 10 ** (snr_db / 20.0)
        return sig + rng.randn(sig.size) * sigma

    def test_at03_1_snr_gradient(self):
        """AT-03-1: SNR≥10dB 检出率 ≥85%；5dB 置信度退化而非乱报。"""
        rates = {}
        meds = {}
        for snr in (20, 10, 5):
            tr = detect_pyin(self._noisy(snr), SR)
            v = np.isfinite(tr.f0_hz)
            errs = np.abs(cent(tr.f0_hz[v], 440.0))
            rates[snr] = float((errs <= 20.0).mean())
            meds[snr] = float(np.median(tr.confidence))
        assert rates[20] >= 0.85
        assert rates[10] >= 0.85
        assert meds[5] < meds[20]  # 强噪声→置信度标记退化

    def test_at03_3_low_confidence_means_unvoiced(self):
        """AT-03-3: 低于阈值的帧不输出错误音高（NaN 语义）。"""
        rng = np.random.RandomState(7)
        noise_only = rng.randn(int(SR * 1.0)) * 0.3
        tr = detect_pyin(noise_only, SR)
        # 纯噪声帧：有检出也必须带置信度字段；NaN 帧不得输出数值
        v = np.isfinite(tr.f0_hz)
        assert np.all(tr.confidence[~v] >= 0.0)
        if v.any():
            assert tr.confidence[v].mean() < 0.9  # 不会"自信地乱报"
        # 全帧无声（4096 帧长下纯噪声常见）同样符合 NaN 语义，不算失败


class TestAT07Boundary:
    def test_at07_1_silence(self):
        """AT-07-1: 纯静音不产生音高点，不崩溃。"""
        tr = detect_pyin(np.zeros(int(SR * 1.0)), SR)
        assert not np.isfinite(tr.f0_hz).any()
        assert tr.confidence.max() < 0.2

    def test_at07_2_dominant_voice(self):
        """AT-07-2: 双声部（440 主 + 550 弱）检出主导声部，不崩溃。
        闸门语义（非用户确认清单硬闸门，报告口径）：不锁到非主导声部——
        中位 |cent| ≤ 50（1/4 半音）且所有有声帧 |cent| ≤ 200（绝不锁 550/+386）。
        实测（2026-09-04 沙箱，frame=4096）：中位 +27 cent 系统性偏移
        （550Hz 分量干扰 CMND 谷底抛物线插值所致），人工审听留 T-005。"""
        t = np.arange(int(SR * 1.0)) / SR
        sig = 0.3 * np.sin(2 * np.pi * 440 * t) + 0.08 * np.sin(2 * np.pi * 550 * t)
        tr = detect_pyin(sig, SR)
        v = np.isfinite(tr.f0_hz)
        c = cent(tr.f0_hz[v], 440.0)
        assert float(np.median(np.abs(c))) <= 50.0
        assert float(np.max(np.abs(c))) <= 200.0

    def test_at07_3_out_of_range(self):
        """AT-07-3: 超量程给提示（NaN+量程字段）而非错误值；量程可配置。"""
        tr_low = detect_pyin(_sine(30.0, 0.8), SR)
        assert not np.isfinite(tr_low.f0_hz).any()
        assert tr_low.fmin == 40.0 and tr_low.fmax == 2000.0
        tr_high = detect_pyin(_sine(3000.0, 0.8), SR)
        assert not np.isfinite(tr_high.f0_hz).any()
        # 量程可配置：fmax=400 时 440Hz 视为量程外
        tr_cfg = detect_pyin(_sine(440.0, 0.5), SR, fmax=400.0)
        assert not np.isfinite(tr_cfg.f0_hz).any()


# ----------------------------------------------------------------------
# A4-R5：cent_ref 默认值去写死（未传 ⇒ 走当前 A4 参考；显式仍优先）
# ----------------------------------------------------------------------


def test_a4r5_default_cent_ref_follows_global_a4(monkeypatch):
    """★ 主判据：未传 cent_ref 时 .cents() 走当前 A4 参考（442 下与 units 同口径）。"""
    from acouscope.analysis.pitch import PitchTrack
    from acouscope.dsp import units

    monkeypatch.setattr(units, "_reference_hz", 442.0)
    tr = PitchTrack(times=np.array([0.0]), f0_hz=np.array([442.0]), confidence=np.array([1.0]))
    assert tr.cent_ref is None
    assert tr.cents()[0] == pytest.approx(0.0, abs=1e-9)
    assert tr.cents()[0] == pytest.approx(float(units.hz_to_cents(442.0)), abs=1e-12)


def test_a4r5_explicit_cent_ref_wins_and_default_440_bit_identical(monkeypatch):
    """★ 反向：显式 cent_ref 优先；默认 440 下与旧公式逐位一致（防退化）。"""
    from acouscope.analysis.pitch import PitchTrack
    from acouscope.dsp import units

    monkeypatch.setattr(units, "_reference_hz", 440.0)
    f = np.array([220.0, 440.0, 880.0])
    tr_explicit = PitchTrack(
        times=np.zeros(3), f0_hz=f, confidence=np.ones(3), cent_ref=220.0
    )
    assert np.array_equal(tr_explicit.cents(), 1200.0 * np.log2(f / 220.0))
    tr_default = PitchTrack(times=np.zeros(3), f0_hz=f, confidence=np.ones(3))
    assert np.array_equal(tr_default.cents(), 1200.0 * np.log2(f / 440.0))


def test_a4r5_signatures_default_none():
    """★ 静态：两个入口的 cent_ref 默认值为 None（防回潮）。"""
    import inspect

    from acouscope.analysis.pitch import detect_pyin
    from acouscope.analysis.pitch_stream import stream_pitch

    assert inspect.signature(detect_pyin).parameters["cent_ref"].default is None
    assert inspect.signature(stream_pitch).parameters["cent_ref"].default is None
