# SPDX-License-Identifier: GPL-3.0-only
"""T-1004 M1 双模式容器与生命周期回归（全离屏，禁 MainWindow.show()）。

覆盖：单轨主态零变化（默认结构/可见性/动作态）、入口 enable 口径、
进/出多轨态往返（波形区切轨道区、只读动作灰化与恢复、状态栏轨 N/M + 健康提示）、
当前轨播放（懒加载全量样本 + 专用播放器复用）、换音频清空会话、
主态拖入=打开 / 白名单过滤、区域命名（轨道区 / 波形区）文案。
"""

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from pathlib import Path

import soundfile as sf
from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import QSplitter

from acouscope.app.controller import AppController
from acouscope.i18n import set_language, tr
from acouscope.ui.main_window import MainWindow


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """离屏 MainWindow（不 show）；带一条内存音频（controller 有音频）。"""
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


@pytest.fixture
def wav_pair(tmp_path):
    """两个真实 wav（多选轨源）。"""
    paths = []
    for i, (sr, freq) in enumerate(((8000, 220.0), (16000, 330.0))):
        path = tmp_path / f"track_{i}.wav"
        t = np.arange(sr) / sr
        sf.write(str(path), 0.3 * np.sin(2 * np.pi * freq * t), sr)
        paths.append(str(path))
    return paths


# ---------------------------------------------------------------------------
# ① 单轨主态零变化（硬门槛）
# ---------------------------------------------------------------------------


def test_single_state_structure_and_visibility_unchanged(window):
    w = window
    # 既有结构断言路径（T-1013/T-913 口径）不变
    regular = w.central_stack.widget(0)
    assert isinstance(regular, QSplitter)
    assert regular.widget(0) is w.waveform_view
    assert regular.widget(1) is w.analysis_panel
    lay = w.waveform_view.layout()
    assert lay.itemAt(0).widget() is w.transport_bar
    assert lay.itemAt(1).widget() is w.waveform_widget
    assert w.transport_bar.parent() is w.waveform_view
    assert w.waveform_widget.parent() is w.waveform_view
    # 多轨容器默认隐藏，且不参与单轨可见性
    assert w.multitrack_panel.isHidden() is True
    assert w._multitrack_mode is False
    assert w.multitrack_panel.view.isVisible() is False


def test_multitrack_action_checkable_and_enable_rule(qapp, monkeypatch, tmp_path, window):
    w = window
    act = w.action_multitrack_compare
    assert act.isCheckable() is True
    assert act.objectName() == "multitrack_compare"
    assert act.isEnabled() is bool(w.controller.has_audio()) is True
    assert act.toolTip() == tr("multitrack.action_tip")

    # 无音频且无轨 → 不可进入（勾选被回退，不进入多轨态）
    monkeypatch.setattr(w.controller, "has_audio", lambda: False)
    w._update_measure_actions()
    assert w.action_multitrack_compare.isEnabled() is False
    w.action_multitrack_compare.setChecked(True)
    assert w._multitrack_mode is False
    assert w.action_multitrack_compare.isChecked() is False


# ---------------------------------------------------------------------------
# ② 进 / 出多轨态往返
# ---------------------------------------------------------------------------


def test_enter_and_exit_multitrack_round_trip(window, wav_pair, qapp):
    w = window
    w.file_browser.set_current_file(wav_pair[0])
    w.file_browser._select_paths(wav_pair)
    qapp.processEvents()
    cut_before = w.action_cut.isEnabled()

    w.action_multitrack_compare.setChecked(True)
    assert w._multitrack_mode is True
    assert w.waveform_widget.isHidden() is True
    assert w.multitrack_panel.isHidden() is False
    assert len(w.multitrack_session) == 2                       # 多选轨源入轨
    assert len(w.multitrack_panel.header_column.headers()) == 2
    # 只读（D6）：编辑类灰化 + 轨道区标题 + 状态栏轨 N/M
    assert w.action_cut.isEnabled() is False
    assert w.multitrack_panel.lbl_area.text() == tr("multitrack.area_title")
    assert w.status_segments._temp_label.text().startswith("轨 1/2")

    w.action_multitrack_compare.setChecked(False)
    assert w._multitrack_mode is False
    assert w.waveform_widget.isHidden() is False
    assert w.multitrack_panel.isHidden() is True
    assert w.action_cut.isEnabled() is cut_before               # 原态恢复
    assert w.multitrack_session.tracks()                        # 轨列表保留（视图态）


def test_status_and_health_hint_text(window, wav_pair, qapp):
    w = window
    w.file_browser.set_current_file(wav_pair[0])
    w.file_browser._select_paths(wav_pair)
    qapp.processEvents()
    w.action_multitrack_compare.setChecked(True)
    seg = w.status_segments
    text = seg._temp_label.text()
    assert tr("multitrack.status").split("{")[0].strip() in text
    assert tr("multitrack.health").split("{")[0].strip() in text
    assert "轨 1/2" in text                                     # 当前轨 = 首轨
    # 切轨 → 状态与 lbl_audio_info 跟随（D4）
    second = w.multitrack_session.tracks()[1]
    w.multitrack_panel.header_column.header_for(second.track_id).currentRequested.emit(
        second.track_id
    )
    assert "轨 2/2" in seg._temp_label.text()
    assert second.label in w.lbl_audio_info.text()
    w.action_multitrack_compare.setChecked(False)


def test_invalidate_clears_multitrack_state(window, wav_pair, qapp):
    w = window
    w.file_browser.set_current_file(wav_pair[0])
    w.file_browser._select_paths(wav_pair)
    qapp.processEvents()
    w.action_multitrack_compare.setChecked(True)
    assert len(w.multitrack_session) == 2
    w._invalidate_analysis_views()
    assert w._multitrack_mode is False
    assert len(w.multitrack_session) == 0
    assert w.waveform_widget.isHidden() is False


# ---------------------------------------------------------------------------
# ③ 当前轨播放（懒加载 + 专用播放器复用）
# ---------------------------------------------------------------------------


def test_play_current_track_loads_full_samples(monkeypatch, window, wav_pair, qapp):
    w = window
    w.file_browser.set_current_file(wav_pair[0])
    w.file_browser._select_paths(wav_pair)
    qapp.processEvents()
    w.action_multitrack_compare.setChecked(True)
    track = w.multitrack_session.tracks()[0]
    assert track.path.name == "track_0.wav"
    assert track.has_data is False                              # 进态仅元数据 + 粗包络

    from acouscope.audio import player as player_mod

    calls = []

    class _FakePlayer:
        def __init__(self):
            self.loads = []

        def set_level_callback(self, cb):
            calls.append(("level_cb", cb))

        def set_error_callback(self, cb):
            calls.append(("error_cb", cb))

        def load(self, data, sample_rate):
            self.loads.append((len(data), sample_rate))

        def play(self):
            calls.append(("play", True))

        def stop(self):
            calls.append(("stop", True))

    monkeypatch.setattr(player_mod, "AudioPlayer", _FakePlayer)
    w._multitrack_player = None
    w.multitrack_panel.view.playToggled.emit(track.track_id)
    assert track.has_data is True                               # 懒加载第三级
    assert w.multitrack_panel.playing_id() == track.track_id
    assert calls[0][0] == "level_cb"
    assert any(entry[0] == "play" for entry in calls)
    w.multitrack_panel.view.playToggled.emit(track.track_id)    # 再点 = 停止
    assert w.multitrack_panel.playing_id() is None
    assert any(entry[0] == "stop" for entry in calls)
    assert w.multitrack_panel.header_column.header_for(
        track.track_id
    ).btn_play.toolTip() == tr("multitrack.tt.play")


def test_play_applies_track_volume_gain(window, wav_pair, qapp, monkeypatch):
    w = window
    w.file_browser.set_current_file(wav_pair[0])
    w.file_browser._select_paths(wav_pair)
    qapp.processEvents()
    w.action_multitrack_compare.setChecked(True)
    track = w.multitrack_session.tracks()[0]
    w.multitrack_session.set_volume(track.track_id, 0.5)

    from acouscope.audio import player as player_mod

    captured = {}

    class _FakePlayer:
        def set_level_callback(self, cb):
            pass

        def set_error_callback(self, cb):
            pass

        def load(self, data, sample_rate):
            captured["peak"] = float(np.max(np.abs(data)))

        def play(self):
            captured["played"] = True

        def stop(self):
            pass

    monkeypatch.setattr(player_mod, "AudioPlayer", _FakePlayer)
    w._multitrack_player = None
    w.multitrack_panel.view.playToggled.emit(track.track_id)
    assert captured["played"] is True
    assert captured["peak"] == pytest.approx(0.3 * 0.5, abs=0.02)   # D10 音量生效


# ---------------------------------------------------------------------------
# ④ 拖放（D9）
# ---------------------------------------------------------------------------


def _mime(paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
    return mime


def _drop_event(mime):
    """构造 drop 事件；调用方须持有 mime 引用（Qt 不接管所有权）。"""
    return QDropEvent(QPointF(5.0, 5.0), Qt.DropAction.CopyAction, mime,
                      Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


def _drag_enter_event(mime):
    return QDragEnterEvent(QPoint(1, 1), Qt.DropAction.CopyAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


def test_single_state_drop_opens_first_supported_file(window, wav_pair, monkeypatch):
    w = window
    opened = []
    monkeypatch.setattr(w, "_load_file", lambda path: opened.append(path))
    mixed = _mime(wav_pair + ["/tmp/notes.txt"])
    w.dropEvent(_drop_event(mixed))
    assert opened == [wav_pair[0]]                              # 白名单过滤后取首个
    assert w._dropped_audio_paths(_mime(["/tmp/notes.txt"])) == []
    assert w._dropped_audio_paths(_mime(wav_pair)) == wav_pair


def test_drag_enter_accepts_only_supported(window):
    w = window
    mime_ok = _mime(["/tmp/a.wav"])
    supported = _drag_enter_event(mime_ok)
    w.dragEnterEvent(supported)
    assert supported.isAccepted() is True

    mime_bad = _mime(["/tmp/notes.txt"])
    blocked = _drag_enter_event(mime_bad)
    w.dragEnterEvent(blocked)
    assert blocked.isAccepted() is False
    assert mime_ok.hasUrls() and mime_bad.hasUrls()         # 引用保活（Qt 不接管）


def test_multitrack_mode_drop_is_left_to_panel(window, monkeypatch):
    w = window
    monkeypatch.setattr(w, "_multitrack_mode", True)             # 主窗多轨态不抢事件
    opened = []
    monkeypatch.setattr(w, "_load_file", lambda path: opened.append(path))
    mime = _mime(["/tmp/a.wav"])
    event = _drop_event(mime)
    w.dropEvent(event)
    assert opened == []
    assert event.isAccepted() is False


# ---------------------------------------------------------------------------
# ⑤ 区域命名与入口细节
# ---------------------------------------------------------------------------


def test_area_naming_copy_distinguishes_modes(window, wav_pair, qapp):
    w = window
    assert tr("multitrack.area_title", "x") != "x"
    assert tr("multitrack.area_title") != tr("multitrack.waveform_area")
    w.file_browser.set_current_file(wav_pair[0])
    qapp.processEvents()
    w.action_multitrack_compare.setChecked(True)
    assert w.multitrack_panel.lbl_area.text() == tr("multitrack.area_title")
    assert w.multitrack_panel.lbl_hint.text() == tr("multitrack.readonly")
    w.action_multitrack_compare.setChecked(False)


def test_add_from_browser_requires_selection(window, qapp):
    w = window
    w.file_browser._select_paths([])
    w.action_multitrack_compare.setChecked(True)
    count = len(w.multitrack_session)
    w._on_multitrack_add_from_browser()                          # 无选中 → toast，不改轨集
    assert len(w.multitrack_session) == count
    w.action_multitrack_compare.setChecked(False)


def test_record_blocked_in_multitrack_mode(window, wav_pair, qapp, monkeypatch):
    """D6：多轨态录音被拦下并复位按钮（只读对比，编辑/录音回单轨模式）。"""
    w = window
    w.file_browser.set_current_file(wav_pair[0])
    w.file_browser._select_paths(wav_pair)
    qapp.processEvents()
    w.action_multitrack_compare.setChecked(True)
    started = []
    monkeypatch.setattr(w, "_get_recorder", lambda: started.append(True))
    w.transport_bar.btn_record.setChecked(True)
    assert w.transport_bar.btn_record.isChecked() is False        # 已复位
    assert started == []                                          # 录音链未被触达
    w.action_multitrack_compare.setChecked(False)


def test_sources_ignore_non_file_current_audio(window):
    """内存音频（无实际文件路径）不构成轨源；无选中时轨源为空。"""
    w = window
    w.file_browser._select_paths([])
    assert not Path(str(w.controller.current_file)).exists()      # fixture 为内存音频
    assert w._multitrack_sources() == []                          # 不制造幽灵轨
    w.action_multitrack_compare.setChecked(True)                  # 空会话仍可进入轨道区
    assert w._multitrack_mode is True and len(w.multitrack_session) == 0
    w.action_multitrack_compare.setChecked(False)
