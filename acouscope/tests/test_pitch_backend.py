# SPDX-License-Identifier: GPL-3.0-only
"""T-101: PitchBackend Protocol + PyinBackend 测试。"""
import sys
sys.path.insert(0, "src")

import numpy as np
import pytest
from acouscope.analysis.backends.base import (
    PitchBackend, PyinBackend, BACKEND_PROTOCOL_V1,
)


class TestBackendProtocol:
    """Protocol 定义与 PyinBackend 适配。"""

    def test_protocol_marker(self):
        assert BACKEND_PROTOCOL_V1 == "1"

    def test_pyin_backend_is_protocol_compliant(self):
        """PyinBackend 满足 PitchBackend Protocol。"""
        backend = PyinBackend()
        assert isinstance(backend, PitchBackend)

    def test_pyin_backend_name(self):
        assert PyinBackend().name == "pYIN"

    def test_pyin_backend_is_streaming(self):
        """pYIN 是流式后端（用户强制指令）。"""
        assert PyinBackend().is_streaming is True

    def test_pyin_backend_is_available(self):
        assert PyinBackend().is_available() is True


class TestPyinBackendDetect:
    """PyinBackend.detect 调用既有 detect_pyin。"""

    def test_pure_tone_440(self):
        """440Hz 纯音检测。"""
        sr = 44100
        t = np.arange(int(sr * 0.5)) / sr
        sig = 0.5 * np.sin(2 * np.pi * 440 * t)
        backend = PyinBackend()
        tr = backend.detect(sig, sr)
        assert hasattr(tr, "f0_hz")
        assert hasattr(tr, "times")
        assert hasattr(tr, "confidence")
        # 至少有一些有声帧
        voiced = np.isfinite(tr.f0_hz)
        assert voiced.sum() > 0
        # 有声帧中位频率接近 440Hz
        f0_voiced = tr.f0_hz[voiced]
        median_f0 = np.median(f0_voiced)
        assert 430 < median_f0 < 450, f"median f0={median_f0}"

    def test_silence_returns_nan(self):
        """静音段返回 NaN。"""
        sr = 44100
        sig = np.zeros(int(sr * 0.5))
        backend = PyinBackend()
        tr = backend.detect(sig, sr)
        assert np.all(np.isnan(tr.f0_hz))

    def test_returns_pitchtrack_type(self):
        """返回 PitchTrack 实例。"""
        from acouscope.analysis.pitch import PitchTrack
        sr = 44100
        t = np.arange(int(sr * 0.3)) / sr
        sig = 0.5 * np.sin(2 * np.pi * 440 * t)
        backend = PyinBackend()
        tr = backend.detect(sig, sr)
        assert isinstance(tr, PitchTrack)
