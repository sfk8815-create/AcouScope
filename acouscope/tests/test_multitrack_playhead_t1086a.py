# SPDX-License-Identifier: GPL-3.0-only
"""T-1086 里程碑 A 守卫测：多轨播放头同步（_update_multitrack_playhead）。

覆盖：① 播放驱动下 view.playhead 随 get_position+offset 前进；
② offset_ms 折算正确；③ is_playing=False 时 timer 自停；
④ 反证：无位置广播则 view 播放头不动。
全离屏，不 show/不弹窗。
"""

import numpy as np
import pytest
import soundfile as sf

pytest.importorskip("PyQt6")

from acouscope.app.controller import AppController
from acouscope.i18n import set_language
from acouscope.ui.main_window import MainWindow
from acouscope.ui.widgets.multitrack.track_model import TrackModel


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    set_language("zh_CN")
    controller = AppController()
    sr = 8000
    t = np.arange(sr) / sr
    controller.load_from_array(0.4 * np.sin(2 * np.pi * 440 * t), sr)
    w = MainWindow(controller)
    yield w
    w.close()


class _FakePlayer:
    def __init__(self, playing=True, position=0.0):
        self._playing = playing
        self._position = position

    def is_playing(self):
        return self._playing

    def get_position(self):
        return self._position

    def load(self, data, sample_rate):
        pass

    def play(self):
        self._playing = True

    def stop(self):
        self._playing = False

    def set_level_callback(self, cb):
        pass

    def set_error_callback(self, cb):
        pass


def _add_fake_track(w, tmp_path, track_id="t1", offset_ms=0.0, duration=10.0):
    path = tmp_path / f"{track_id}.wav"
    sr = 44100
    n = int(sr * duration)
    sf.write(str(path), 0.3 * np.sin(2 * np.pi * 440 * np.arange(n) / sr), sr)
    track = TrackModel(str(path), track_id=track_id, label=f"Track {track_id}")
    track.duration = duration
    track.sample_rate = sr
    track.offset_ms = offset_ms
    w.multitrack_session.add_track(track)
    return track


def test_playhead_advances_with_position(window, tmp_path):
    w = window
    _add_fake_track(w, tmp_path, "t1", offset_ms=0.0)
    fake = _FakePlayer(playing=True, position=1.5)
    w._multitrack_player = fake
    w.multitrack_panel.set_playing("t1")

    w._update_multitrack_playhead()
    assert w.multitrack_panel.view.playhead() == pytest.approx(1.5, abs=0.01)

    fake._position = 3.0
    w._update_multitrack_playhead()
    assert w.multitrack_panel.view.playhead() == pytest.approx(3.0, abs=0.01)


def test_playhead_offset_conversion(window, tmp_path):
    w = window
    _add_fake_track(w, tmp_path, "t1", offset_ms=500.0)
    fake = _FakePlayer(playing=True, position=2.0)
    w._multitrack_player = fake
    w.multitrack_panel.set_playing("t1")

    w._update_multitrack_playhead()
    expected = 2.0 + 500.0 / 1000.0
    assert w.multitrack_panel.view.playhead() == pytest.approx(expected, abs=0.01)


def test_timer_stops_when_not_playing(window, tmp_path):
    w = window
    _add_fake_track(w, tmp_path, "t1")
    fake = _FakePlayer(playing=False, position=0.0)
    w._multitrack_player = fake
    w.multitrack_panel.set_playing("t1")
    w._mt_play_timer.start()

    assert w._mt_play_timer.isActive()
    w._update_multitrack_playhead()
    from PyQt6.QtWidgets import QApplication
    QApplication.processEvents()
    assert not w._mt_play_timer.isActive()


def test_negative_no_broadcast_without_timer(window, tmp_path):
    w = window
    _add_fake_track(w, tmp_path, "t1")
    fake = _FakePlayer(playing=True, position=5.0)
    w._multitrack_player = fake
    w.multitrack_panel.set_playing("t1")

    initial = w.multitrack_panel.view.playhead()
    assert w.multitrack_panel.view.playhead() == initial
