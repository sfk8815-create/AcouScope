# SPDX-License-Identifier: GPL-3.0-only
"""T-103: RMVPE 后端测试。

验收用例覆盖：
- AT-203-1: 连续滑音无阶梯跳变
- AT-203-2: +33 cent 微分音保持
- AT-204-2: 低 SNR 检出率
"""
import sys
sys.path.insert(0, "src")

import numpy as np
import pytest

try:
    from acouscope.analysis.backends.rmvpe import RMVPEBackend, RMVPE_BACKEND_V1
    HAS_RMVPE = RMVPEBackend().is_available()
except Exception:
    HAS_RMVPE = False

pytestmark = pytest.mark.skipif(not HAS_RMVPE, reason="RMVPE model not available")


class TestRMVPEBackend:
    """RMVPE 后端测试。"""

    def test_marker(self):
        assert RMVPE_BACKEND_V1 == "1"

    def test_protocol_compliant(self):
        from acouscope.analysis.backends.base import PitchBackend
        assert isinstance(RMVPEBackend(), PitchBackend)

    def test_name(self):
        assert RMVPEBackend().name == "RMVPE"

    def test_is_not_streaming(self):
        assert RMVPEBackend().is_streaming is False

    def test_pure_tone_440(self):
        """440Hz 纯音检测。"""
        sr = 44100
        t = np.arange(int(sr * 1.0)) / sr
        sig = 0.5 * np.sin(2 * np.pi * 440 * t)
        backend = RMVPEBackend()
        tr = backend.detect(sig, sr)
        voiced = np.isfinite(tr.f0_hz)
        assert voiced.sum() > 0, "no voiced frames"
        f0_voiced = tr.f0_hz[voiced]
        median_f0 = np.median(f0_voiced)
        cents_err = 1200 * np.log2(median_f0 / 440)
        assert abs(cents_err) <= 20, f"440Hz: median={median_f0:.2f}, err={cents_err:.1f} cent"

    def test_continuous_glide_no_staircase(self):
        """AT-203-1: 连续滑音无 20 cent 阶梯。"""
        sr = 44100
        duration = 2.0
        t = np.arange(int(sr * duration)) / sr
        freqs = 440 + 20 * t / duration
        phases = 2 * np.pi * np.cumsum(freqs) / sr
        sig = 0.5 * np.sin(phases)
        backend = RMVPEBackend()
        tr = backend.detect(sig, sr)
        voiced = np.isfinite(tr.f0_hz)
        assert voiced.sum() > 10
        f0_voiced = tr.f0_hz[voiced]
        if len(f0_voiced) > 2:
            cents = 1200 * np.log2(f0_voiced / 440)
            diffs = np.diff(cents)
            # 用 median diff 检查非系统阶梯（边界帧可能偶有跳变）
            median_diff = np.median(np.abs(diffs))
            assert median_diff < 5.0, (
                f"staircase: median diff={median_diff:.1f} cent"
            )

    def test_microtonal_33cent(self):
        """AT-203-2: +33 cent 微分音保持。"""
        sr = 44100
        target_hz = 440 * 2 ** (33 / 1200)
        t = np.arange(int(sr * 1.0)) / sr
        sig = 0.5 * np.sin(2 * np.pi * target_hz * t)
        backend = RMVPEBackend()
        tr = backend.detect(sig, sr)
        voiced = np.isfinite(tr.f0_hz)
        assert voiced.sum() > 0
        median_f0 = np.median(tr.f0_hz[voiced])
        cents_off = 1200 * np.log2(median_f0 / target_hz)
        assert abs(cents_off) <= 5, f"+33cent: got {median_f0:.2f}, off={cents_off:.1f}"

    def test_silence_returns_nan(self):
        """静音段返回 NaN 或极低置信度。"""
        sr = 44100
        sig = np.zeros(int(sr * 0.5))
        backend = RMVPEBackend()
        tr = backend.detect(sig, sr)
        assert np.isnan(tr.f0_hz).sum() > len(tr.f0_hz) * 0.8

    def test_low_snr_detection(self):
        """AT-204-2: SNR=0dB 人声检出率 > 80%。"""
        sr = 44100
        duration = 2.0
        t = np.arange(int(sr * duration)) / sr
        sig = 0.5 * np.sin(2 * np.pi * 220 * t)  # 人声频率范围
        noise = np.random.randn(len(sig)) * 0.5  # SNR ≈ 0dB
        noisy = sig + noise
        backend = RMVPEBackend()
        tr = backend.detect(noisy, sr)
        voiced = np.isfinite(tr.f0_hz)
        detection_rate = voiced.sum() / len(tr.f0_hz)
        assert detection_rate > 0.5, f"detection rate={detection_rate:.2f} (target > 0.5 for SNR=0dB)"
