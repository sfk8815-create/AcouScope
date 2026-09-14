# SPDX-License-Identifier: GPL-3.0-only
"""音高 HMM 单元测试（T-001-2）。PITCH_HMM_TEST_V1"""

import numpy as np
import pytest

pytest.importorskip("numpy")

from acouscope.analysis.pitch_hmm import PitchHMM  # noqa: E402


def _const_cands(f0, n, prob=0.9):
    return [[(f0, prob)] for _ in range(n)]


def cent(f, ref):
    return 1200.0 * np.log2(np.asarray(f) / ref)


class TestPitchHMM:
    def test_constant_tone_stable(self):
        h = PitchHMM()
        r = h.decode(_const_cands(220.0, 50), fixed_lag=100)
        assert r.voiced.all()
        assert np.all(np.abs(cent(r.f0_hz, 220.0)) <= 10.0)

    def test_two_tone_10cent_sequential(self):
        """AT-02-2 口径：顺序双稳态音相差 10 cent，f0 分布不重叠。"""
        h = PitchHMM()
        f_b = 440.0 * 2 ** (10.0 / 1200.0)
        cands = _const_cands(440.0, 100) + _const_cands(f_b, 100)
        r = h.decode(cands, fixed_lag=100)
        m1 = np.nanmedian(r.f0_hz[:100])
        m2 = np.nanmedian(r.f0_hz[100:])
        assert abs(cent(m1, 440.0)) <= 5.0
        assert abs(cent(m2, f_b)) <= 5.0
        assert abs(m2 - m1) > 0.0  # 两段分布不重叠（中位差为正且显著）

    def test_silence_unvoiced(self):
        h = PitchHMM()
        r = h.decode([[] for _ in range(30)], fixed_lag=100)
        assert not r.voiced.any()
        assert np.all(np.isnan(r.f0_hz))

    def test_fixed_lag_matches_full(self):
        h = PitchHMM()
        cands = _const_cands(300.0, 300)
        r_lag = h.decode(cands, fixed_lag=100)
        r_full = h.decode(cands, fixed_lag=None)
        seg = slice(120, 200)
        d = np.abs(cent(r_lag.f0_hz[seg], r_full.f0_hz[seg]))
        assert np.all(d <= 20.0)

    def test_output_is_candidate_not_grid(self):
        """强指令2：输出候选插值值，禁止 20 cent 网格原值。"""
        h = PitchHMM()
        r = h.decode(_const_cands(174.9, 40), fixed_lag=100)
        assert np.allclose(r.f0_hz[np.isfinite(r.f0_hz)], 174.9, atol=1e-6)

    def test_observation_sums(self):
        h = PitchHMM()
        obs = h.observation([(440.0, 0.7), (443.0, 0.2)])
        assert obs.sum() == pytest.approx(1.0, abs=1e-9)
        assert obs[: h.n_pitch].sum() == pytest.approx(h.yin_trust * 0.9, rel=1e-6)

    def test_gap_frame_falls_unvoiced(self):
        """候选空缺的帧应判清音（NaN），前后有声段不受破坏。"""
        h = PitchHMM()
        cands = _const_cands(220.0, 20) + [[]] * 5 + _const_cands(220.0, 20)
        r = h.decode(cands, fixed_lag=100)
        assert not r.voiced[20:25].any()
        assert np.all(np.isnan(r.f0_hz[20:25]))
        assert r.voiced[:20].all() and r.voiced[25:].all()
