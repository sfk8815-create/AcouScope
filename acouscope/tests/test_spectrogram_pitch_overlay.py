# SPDX-License-Identifier: GPL-3.0-only
"""语谱图音高曲线叠加测试（T-002-1）。PITCH_OVERLAY_TEST_V1"""

import numpy as np
import pytest


@pytest.fixture
def spec_widget(qapp):
    from acouscope.ui.widgets.spectrogram import SpectrogramWidget

    w = SpectrogramWidget()
    freqs = np.linspace(0, 8000, 257)
    times = np.linspace(0, 2.0, 200)
    spec = np.random.RandomState(42).randn(257, 200) * 10 - 60
    for ti in range(200):
        f_signal = 500 + (2000 - 500) * ti / 200
        fi = np.clip(int(f_signal / 8000 * 256), 0, 256)
        spec[fi, ti] += 60
    w.set_data(freqs, times, spec, sample_rate=16000)
    return w


def _track(n=200):
    t = np.linspace(0, 2.0, n)
    f = 440.0 * np.ones(n)
    f[:10] = np.nan  # 前 10 帧未检出
    return t, f


class TestPitchOverlay:
    def test_set_pitch_track_stores(self, spec_widget):
        t, f = _track()
        spec_widget.set_pitch_track(t, f)
        assert spec_widget._pitch_track is not None
        assert spec_widget._pitch_track[0].size == 200

    def test_toggle_creates_curve(self, spec_widget):
        t, f = _track()
        spec_widget.set_pitch_track(t, f)
        assert spec_widget._pitch_curve is None  # 未开启不建曲线
        spec_widget.btn_pitch.setChecked(True)
        assert spec_widget._pitch_curve is not None

    def test_nan_frames_skipped(self, spec_widget):
        t, f = _track()
        spec_widget.set_pitch_track(t, f)
        spec_widget.btn_pitch.setChecked(True)
        x, y = spec_widget._pitch_curve.getData()
        assert len(x) == 190  # 10 帧 NaN 不绘制

    def test_unit_change_refreshes(self, spec_widget):
        t, f = _track()
        spec_widget.set_pitch_track(t, f)
        spec_widget.btn_pitch.setChecked(True)
        _, y_hz = spec_widget._pitch_curve.getData()
        idx = spec_widget.cmb_y_unit.findData("midi")
        spec_widget.cmb_y_unit.setCurrentIndex(idx)
        _, y_midi = spec_widget._pitch_curve.getData()
        assert not np.allclose(y_hz, y_midi)

    def test_uncheck_clears(self, spec_widget):
        t, f = _track()
        spec_widget.set_pitch_track(t, f)
        spec_widget.btn_pitch.setChecked(True)
        spec_widget.btn_pitch.setChecked(False)
        assert spec_widget._pitch_curve is None
