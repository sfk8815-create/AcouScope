# SPDX-License-Identifier: GPL-3.0-only
"""T-1087 M5：加轨时的粗包络整文件块式读经任务中心后台化（on_done 回填）。

破口（§〇-bis M5）：``add_files`` → ``session.add_path`` → ``load_envelope`` →
``default_envelope_reader`` **每轨块式读完整个文件**（多轨大文件加轨秒级冻结）。

处置：轨道登记 + 文件头元数据留主线程（轨道立即可见、时长可得），粗包络那一步
（``session.prepare_track``）交 worker；包络就绪后由 ``on_done`` 在主线程 ``refresh()``
回填轨头峰值与呈现。三级懒加载 / LRU 语义零改（只把第二级的**执行线程**挪走）。

覆盖含反证：未注入投递器（裸面板）⇒ 就地同步读、立刻 envelope_ready。
"""

import threading
import time

import numpy as np
import pytest

pytest.importorskip("PyQt6")

import soundfile as sf
from PyQt6.QtWidgets import QApplication

from acouscope.app.controller import AppController
from acouscope.i18n import set_language, tr
from acouscope.ui.main_window import MainWindow
from acouscope.ui.widgets.multitrack.multitrack_view import MultitrackPanel
from acouscope.ui.widgets.multitrack.track_model import MultitrackSession

_SR = 8000


@pytest.fixture
def wav_pair(tmp_path):
    paths = []
    for i, freq in enumerate((220.0, 330.0)):
        path = tmp_path / f"addt{i}.wav"
        t = np.arange(_SR) / _SR
        sf.write(str(path), 0.3 * np.sin(2 * np.pi * freq * t), _SR)
        paths.append(str(path))
    return paths


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    set_language("zh_CN")
    controller = AppController()
    t = np.arange(_SR) / _SR
    controller.load_from_array(0.4 * np.sin(2 * np.pi * 440 * t), _SR)
    w = MainWindow(controller)
    import acouscope.ui.main_window as _mw

    monkeypatch.setattr(
        _mw, "show_toast",
        lambda parent, message, level="info", duration=3500: None,
    )
    yield w
    w.close()


@pytest.fixture
def prepare_spy(monkeypatch):
    """记录 prepare_track 的执行线程，并用门闩卡住包络读。"""
    calls = []
    gate = threading.Event()
    real = MultitrackSession.prepare_track

    def spy(self, track):
        calls.append((track.track_id, threading.current_thread().name))
        gate.wait(timeout=4.0)
        return real(self, track)

    monkeypatch.setattr(MultitrackSession, "prepare_track", spy)
    return calls, gate


def _wait_until(predicate, timeout_ms: int = 6000) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if predicate():
            return True
        QApplication.processEvents()
        time.sleep(0.005)
    return bool(predicate())


# ---------------------------------------------------------------------------
# ① 接宿主：投递任务 + 包络延后回填 + 读不在主线程
# ---------------------------------------------------------------------------


def test_add_files_submits_prepare_task_and_backfills(window, wav_pair, prepare_spy):
    w = window
    calls, gate = prepare_spy
    panel = w.multitrack_panel

    added, rejected = panel.add_files(wav_pair + ["/tmp/notes.txt"])
    assert [str(p) for p in added] == wav_pair and rejected == ["/tmp/notes.txt"]
    tracks = panel.session().tracks()
    assert len(tracks) == 2                                    # 轨道立刻在列（可见）
    assert all(t.duration > 0.0 for t in tracks)               # 元数据主线程已读
    assert all(not t.envelope_ready for t in tracks)           # ★ 包络尚未回填
    assert len(panel.header_column.headers()) == 2             # 头先出（无峰值）
    assert w.task_center.active_count() == 1                   # 已投递
    assert panel.track_prepare_inflight() is True

    gate.set()
    # 等"投递任务终态 + 门闩复位"（包络位由 worker 置起，早于主线程 settle ⇒ 以后者为准）
    assert _wait_until(lambda: not panel.track_prepare_inflight())
    assert all(t.envelope_ready for t in panel.session().tracks())
    assert w.task_center.active_count() == 0
    main = threading.main_thread().name
    assert len(calls) == 2 and all(thread != main for _id, thread in calls), calls
    # on_done 回填：轨道头峰值随包络就绪而出现
    header = panel.header_column.header_for(tracks[0].track_id)
    assert header is not None


def test_prepare_task_title_uses_new_i18n_key(window, wav_pair, prepare_spy):
    w = window
    _calls, gate = prepare_spy
    w.multitrack_panel.add_files(wav_pair[:1])
    entry = w.task_center.running_entries() or w.task_center.queued_entries()
    assert entry[0].title == tr("task_center.title.multitrack_add").format(n=1)
    gate.set()
    assert _wait_until(lambda: not w.multitrack_panel.track_prepare_inflight())


# ---------------------------------------------------------------------------
# ② 反证 + 语义不变
# ---------------------------------------------------------------------------


def test_bare_panel_still_prepares_envelopes_inline(qapp, wav_pair):
    """未注入投递器 ⇒ 原同步口径（就地读完包络、不产生任何任务面）。"""
    session = MultitrackSession()
    panel = MultitrackPanel(session)
    assert panel.track_prepare_deliver() is None
    panel.add_files(wav_pair)
    assert all(t.envelope_ready for t in session.tracks())
    assert len(panel.header_column.headers()) == 2


def test_add_path_semantics_unchanged(wav_pair):
    """``add_path`` 仍"元数据 + 粗包络"两步就地跑完（三级懒加载语义零改）。"""
    session = MultitrackSession()
    track = session.add_path(wav_pair[0])
    assert track.metadata_ready is True and track.envelope_ready is True
    assert track.has_data is False                             # 第三级仍按需
    assert session.tracks()[0] is track
    times, peaks = track.envelope()
    assert times.size and peaks.size
