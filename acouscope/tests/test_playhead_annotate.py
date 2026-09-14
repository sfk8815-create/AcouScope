# SPDX-License-Identifier: GPL-3.0-only
"""T-325 播放中打点标注（Pγ）离屏测试。

覆盖：
  ① T：播放/停止态在播放头落纯时间点（时间=播放头，光标不停顿）；
  ② 同刻连击去重：<50ms 重复触发只落 1 点（防抖动连击）；
  ③ M：先落纯点再弹标签输入 popover（非模态）；回车提交更新 label；
  ④ M：Esc/取消 → 保留纯点（label 空）；
  ⑤ 无音频按 T/M → 温和 toast 提示、零落点；
  ⑥ Shift+T：撤销最近一次播放打点（时间匹配才删）；
  ⑦ 打点全程不停播：无 pause/play/set_position 调用、播放态保持；
  ⑧ 快捷键 T/M/Shift+T 已注册且与现有全局键无冲突；
  ⑨ i18n 三语键齐全；帮助手册三语键位表同步新增行。

纪律：不 MainWindow.show() / QDialog / .exec()；不真播（controller 打桩）；
禁词/hex/px/新浮条遵守由实现自审（本文件不含）。
"""

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from acouscope.app.controller import AppController
from acouscope.i18n import get_language, set_language, tr
from acouscope.ui.main_window import MainWindow
from acouscope.ui.shortcuts import ShortcutManager


def _sig() -> tuple:
    """2s 正弦波测试信号。"""
    sr = 8000
    t = np.arange(int(sr * 2.0)) / sr
    return sr, t, 0.5 * np.sin(2 * np.pi * 440 * t)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """带已加载音频 + 波形数据的 MainWindow（不 show）；controller 位置/播放态打桩。"""

    monkeypatch.setenv("HOME", str(tmp_path))

    controller = AppController()
    sr, t, x = _sig()
    controller.load_from_array(x, sr)

    pos_holder = {"t": 0.0}
    calls = {"set_position": [], "play": [], "pause": [], "set_loop": []}
    playing = {"v": False}
    monkeypatch.setattr(controller, "set_position",
                        lambda t: calls["set_position"].append(float(t)))
    monkeypatch.setattr(controller, "play",
                        lambda: calls["play"].append(True))
    monkeypatch.setattr(controller, "pause",
                        lambda: calls["pause"].append(True))
    monkeypatch.setattr(controller, "set_loop",
                        lambda a, b: calls["set_loop"].append((float(a), float(b))))
    monkeypatch.setattr(controller, "is_playing", lambda: playing["v"])
    monkeypatch.setattr(controller, "get_position",
                        lambda: pos_holder["t"])

    w = MainWindow(controller)
    w.waveform_widget.set_data(t, x, sample_rate=sr)
    w._calls = calls
    w._pos = pos_holder
    w._playing = playing

    yield w
    w.close()


def _instant_times(window) -> list:
    return [float(i.time) for i in window.waveform_widget.annotations.instants]


# ----------------------------------------------------------------------
# ① T：在播放头落纯时间点；光标不停顿
# ----------------------------------------------------------------------

def test_T_adds_instant_at_playhead(window):
    window._pos["t"] = 0.65
    window._on_annotate_playhead()

    assert _instant_times(window) == [0.65]
    # 全程零播放控制调用 = 光标不停、不停播
    assert window._calls["play"] == []
    assert window._calls["pause"] == []
    assert window._calls["set_position"] == []


def test_T_works_while_playing_without_interrupt(window):
    window._pos["t"] = 0.4
    window._playing["v"] = True  # 正在播放

    window._on_annotate_playhead()

    assert _instant_times(window) == [0.4]
    assert window._calls["play"] == []
    assert window._calls["pause"] == []
    assert window._playing["v"] is True  # 播放状态未变


def test_T_works_when_stopped_at_playhead(window):
    window._pos["t"] = 1.2
    window._on_annotate_playhead()  # 停止态
    assert _instant_times(window) == [1.2]


# ----------------------------------------------------------------------
# ② 同刻连击去重：<50ms 只落 1 点
# ----------------------------------------------------------------------

def test_rapid_duplicate_T_is_deduplicated(window):
    window._pos["t"] = 0.5
    window._on_annotate_playhead()
    window._on_annotate_playhead()  # <50ms 内连按 → 拦截
    window._on_annotate_playhead()

    assert _instant_times(window) == [0.5]  # 仅落 1 点


def test_spaced_marks_both_land(window, monkeypatch):
    window._pos["t"] = 0.3
    window._on_annotate_playhead()
    # 模拟超过 50ms 后的第二次打点（重置去重钟）
    window._last_annotate_mono = None
    window._pos["t"] = 0.9
    window._on_annotate_playhead()

    assert _instant_times(window) == [0.3, 0.9]


# ----------------------------------------------------------------------
# ③/④ M：先落纯点 → popover 输入；提交更新 label；Esc 保留纯点
# ----------------------------------------------------------------------

def test_M_lands_point_then_opens_label_popover(window):
    window._pos["t"] = 0.7
    window._on_annotate_playhead_text()

    # 先落纯点（防丢）且非模态输入 popover 已创建
    assert _instant_times(window) == [0.7]
    pop = window.waveform_widget._label_popover
    assert pop is not None
    # 播放不受打断
    assert window._calls["pause"] == []
    assert window._calls["play"] == []


def test_M_commit_updates_label(window):
    window._pos["t"] = 0.55
    window._on_annotate_playhead_text()
    pop = window.waveform_widget._label_popover
    assert pop is not None

    pop.edit.setText("onset-01")
    pop._commit()

    last = window.waveform_widget.annotations.instants[-1]
    assert float(last.time) == pytest.approx(0.55)
    assert last.label == "onset-01"


def test_M_esc_keeps_bare_point(window):
    window._pos["t"] = 0.8
    window._on_annotate_playhead_text()
    pop = window.waveform_widget._label_popover
    assert pop is not None

    pop._cancel()

    last = window.waveform_widget.annotations.instants[-1]
    assert float(last.time) == pytest.approx(0.8)
    assert last.label == ""  # Esc = 保留纯点


# ----------------------------------------------------------------------
# ⑤ 无音频按 T/M → 温和提示、零落点
# ----------------------------------------------------------------------

def test_T_no_audio_toasts_and_lands_nothing(window, monkeypatch):
    toasts = []
    monkeypatch.setattr("acouscope.ui.main_window.show_toast",
                        lambda parent, msg, level="info": toasts.append((msg, level)))
    monkeypatch.setattr(window.controller, "has_audio", lambda: False)

    window._on_annotate_playhead()
    window._on_annotate_playhead_text()

    assert window.waveform_widget.annotations.instants == []
    assert len(toasts) == 2
    assert all(level == "info" for _, level in toasts)


# ----------------------------------------------------------------------
# ⑥ Shift+T：撤销最近一次播放打点
# ----------------------------------------------------------------------

def test_undo_last_marker_deletes_recent_mark(window):
    window._pos["t"] = 0.2
    window._on_annotate_playhead()
    window._last_annotate_mono = None
    window._pos["t"] = 1.1
    window._on_annotate_playhead()
    assert _instant_times(window) == [0.2, 1.1]

    window._on_undo_playhead_annotate()  # 撤销最近一次（1.1）

    assert _instant_times(window) == [0.2]


def test_undo_without_marker_is_noop(window):
    before = window.waveform_widget.annotations.instants
    window._on_undo_playhead_annotate()  # 无最近打点 → 空操作零异常
    assert window.waveform_widget.annotations.instants == before


def test_undo_after_delete_second_mark_keeps_first(window):
    window._pos["t"] = 0.4
    window._on_annotate_playhead()
    window._last_annotate_mono = None
    window._pos["t"] = 0.7
    window._on_annotate_playhead()
    assert _instant_times(window) == [0.4, 0.7]

    window._on_undo_playhead_annotate()
    assert _instant_times(window) == [0.4]

    # 撤销钟已清空：再次撤销不误删最早的 0.4
    window._on_undo_playhead_annotate()
    assert _instant_times(window) == [0.4]


# ----------------------------------------------------------------------
# ⑧/⑨ 快捷键注册与冲突 / i18n / 帮助键位表
# ----------------------------------------------------------------------

def test_annotate_shortcuts_registered_no_conflict(window):
    mgr = ShortcutManager.instance()
    entries = mgr._entries

    assert entries["annotate_instant"].current_key == "T"
    assert entries["annotate_instant_text"].current_key == "M"
    assert entries["undo_last_marker"].current_key == "Shift+T"

    # 冲突盘点：T / M / Shift+T 不得被其它全局键占用
    for aid, e in entries.items():
        if aid not in ("annotate_instant", "annotate_instant_text", "undo_last_marker"):
            assert e.current_key not in ("T", "M", "Shift+T"), \
                f"键冲突: {aid}={e.current_key}"


def test_annotate_shortcut_labels_i18n_three_langs():
    prev = get_language()
    try:
        cases = [
            ("en_US", "Add Time Mark", "Add Text Mark", "Undo Last Mark"),
            ("zh_CN", "打时间点", "打文本点", "撤销上一打点"),
            ("zh_TW", "打時間點", "打文本點", "撤銷上一打點"),
        ]
        for lang, t_label, m_label, u_label in cases:
            set_language(lang)
            assert tr("shortcut.annotate_instant") == t_label
            assert tr("shortcut.annotate_instant_text") == m_label
            assert tr("shortcut.undo_last_marker") == u_label
    finally:
        set_language(prev)


def test_help_manual_three_langs_include_annotate_keys():
    from acouscope.ui.widgets.help_dialogs import MANUAL

    assert "<tr><td>打时间点</td><td>T</td></tr>" in MANUAL["zh_CN"]
    assert "<tr><td>撤销上一打点</td><td>Shift+T</td></tr>" in MANUAL["zh_CN"]
    assert "<tr><td>打時間點</td><td>T</td></tr>" in MANUAL["zh_TW"]
    assert "<tr><td>撤銷上一打點</td><td>Shift+T</td></tr>" in MANUAL["zh_TW"]
    assert "<tr><td>Add time mark</td><td>T</td></tr>" in MANUAL["en_US"]
    assert "<tr><td>Undo last mark</td><td>Shift+T</td></tr>" in MANUAL["en_US"]
