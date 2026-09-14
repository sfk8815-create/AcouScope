# SPDX-License-Identifier: GPL-3.0-only
"""概率化 YIN 单元测试（T-001-1）。PYIN_CLEANROOM_V1"""

import numpy as np
import pytest

from acouscope.analysis.pyin import (  # noqa: E402
    PYIN_MIN_FREQ,
    pyin_candidates,
    pyin_frame,
)

GRID_MIN = PYIN_MIN_FREQ


def _sine(freq, dur=0.5, sr=44100.0, amp=0.5):
    t = np.arange(int(sr * dur)) / sr
    return amp * np.sin(2 * np.pi * freq * t)


def cent_err(f0, ref):
    return abs(1200.0 * np.log2(f0 / ref))


class TestPyinFrame:
    def test_pure_tone_top_candidate(self):
        cands, vp = pyin_frame(_sine(440.0), 44100.0)
        assert cands, "纯音应有候选"
        assert cent_err(cands[0][0], 440.0) <= 10.0  # AT-01-1 口径
        assert vp > 0.5

    def test_candidates_structure(self):
        cands, _ = pyin_frame(_sine(220.0), 44100.0)
        assert all(0.0 < p <= 1.0 for _, p in cands)
        probs = [p for _, p in cands]
        assert probs == sorted(probs, reverse=True)
        assert all(40.0 <= f <= 2000.0 for f, _ in cands)

    def test_silence_no_candidates(self):
        cands, vp = pyin_frame(np.zeros(2048), 44100.0)
        assert cands == []
        assert vp < 0.2

    def test_two_tones_10cent_separable(self):
        """AT-02-2 口径（单帧层）：相差 10 cent 的两音分别检出且分布不重叠。"""
        f_a = 440.0
        f_b = 440.0 * 2 ** (10.0 / 1200.0)
        c_a, _ = pyin_frame(_sine(f_a), 44100.0)
        c_b, _ = pyin_frame(_sine(f_b), 44100.0)
        assert c_a and c_b
        assert cent_err(c_a[0][0], f_a) <= 5.0
        assert cent_err(c_b[0][0], f_b) <= 5.0

    def test_interpolation_not_grid_snapped(self):
        """抛物线插值：输出不精确落在 20 cent 网格点上。"""
        cands, _ = pyin_frame(_sine(174.9), 44100.0)
        assert cands
        f0 = cands[0][0]
        grid = GRID_MIN * 2 ** (round(60 * np.log2(f0 / GRID_MIN)) / 60)
        assert abs(f0 - grid) > 1e-9


class TestPyinCandidates:
    def test_times_semantics(self):
        """times[i] = (i*hop + frame_size//4)/sr（毫秒级帧中心语义）。"""
        sr = 44100.0
        times, _, _ = pyin_candidates(_sine(440.0, 1.0), sr, 2048, 256)
        expect = (np.arange(len(times)) * 256 + 512) / sr
        np.testing.assert_allclose(times, expect)

    def test_batch_matches_frame(self):
        sig = _sine(300.0, 0.3)
        _, cands, vp = pyin_candidates(sig, 44100.0, 2048, 512)
        c1, v1 = pyin_frame(sig[:2048], 44100.0)
        assert cands[0] == c1
        assert vp[0] == pytest.approx(v1)
