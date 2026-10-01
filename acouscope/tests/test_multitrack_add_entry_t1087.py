# SPDX-License-Identifier: GPL-3.0-only
"""T-1087 M2（真机目测 #5）：「加入多轨」无选中时的两级兜底。

缺陷：入口只读**折叠左栏**里 FileBrowser 的选中项，用户看不见列表 ⇒ 点按钮只得到
一句「请先在文件列表中选择」，实际上无路可走（`_on_multitrack_add_from_browser`
无选中即 return）。

两级兜底（`_multitrack_add_fallback`）：① 左栏折叠 ⇒ 先展开列表（本次不改轨集）；
② 已展开仍无选中 ⇒ 开系统文件框直选（白名单过滤仍在容器内）。

覆盖含**反向守卫**：折叠态不得弹框（否则绕过项目列表、并把既有「无选中仅提示」
契约改道进模态）；有选中时一条兜底路径都不该走。
"""

import numpy as np
import pytest

pytest.importorskip("PyQt6")

import soundfile as sf
from PyQt6.QtWidgets import QFileDialog

from acouscope.app.controller import AppController
from acouscope.i18n import set_language, tr
from acouscope.ui import main_window as mw
from acouscope.ui.main_window import MainWindow

_SR = 8000


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
    yield w
    w.close()


@pytest.fixture
def wavs(tmp_path):
    """两个真 wav + 一个 txt（白名单外）。"""
    paths = []
    for i, freq in enumerate((220.0, 330.0)):
        path = tmp_path / f"pick_{i}.wav"
        t = np.arange(_SR) / _SR
        sf.write(str(path), 0.3 * np.sin(2 * np.pi * freq * t), _SR)
        paths.append(str(path))
    other = tmp_path / "notes.txt"
    other.write_text("not audio", encoding="utf-8")
    return paths + [str(other)]


@pytest.fixture
def dialog(monkeypatch):
    """系统文件框替身：记录调用次数、按脚本返回路径（**禁真起框**）。"""
    state = {"calls": 0, "return": [], "args": None}

    def fake(parent=None, caption="", directory="", filter_string="", *a, **kw):
        state["calls"] += 1
        state["args"] = (caption, directory, filter_string)
        return list(state["return"]), ""

    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(fake))

    def setup(paths):
        state["return"] = list(paths)
        return state

    return setup


def _toasts(monkeypatch, window):
    seen = []
    monkeypatch.setattr(
        mw, "show_toast",
        lambda parent, message, level="info", duration=3500: seen.append(
            (message, level)
        ),
    )
    return seen


# ---------------------------------------------------------------------------
# ① 左栏折叠 ⇒ 只展开，不弹框、不改轨集
# ---------------------------------------------------------------------------


def test_collapsed_left_panel_expands_instead_of_dialog(window, dialog, monkeypatch):
    w = window
    w.file_browser._select_paths([])
    w.left_panel.set_collapsed(True)
    state = dialog(["/tmp/never.wav"])
    before = len(w.multitrack_session)

    w._on_multitrack_add_from_browser()
    assert w.left_panel.is_collapsed() is False                   # 列表已可见
    assert len(w.multitrack_session) == before                    # 本次不塞幽灵轨
    assert state["calls"] == 0                                    # ★ 反向：折叠态不弹框


# ---------------------------------------------------------------------------
# ② 已展开仍无选中 ⇒ 系统文件框直选并入轨
# ---------------------------------------------------------------------------


def test_expanded_panel_falls_back_to_file_dialog(window, wavs, dialog, monkeypatch):
    w = window
    w.left_panel.set_collapsed(False)
    w.file_browser._select_paths([])
    state = dialog(wavs[:2])

    w._on_multitrack_add_from_browser()
    assert state["calls"] == 1
    assert state["args"][0] == tr("multitrack.add_dialog_title")
    assert "*.wav" in state["args"][2]                            # 音频白名单过滤式
    labels = [t.label for t in w.multitrack_session.tracks()]
    assert labels == ["pick_0", "pick_1"]                         # 按选择序入轨
    assert w._multitrack_mode is True                             # 加轨后进多轨态


def test_dialog_mix_rejected_by_container_whitelist(window, wavs, dialog, monkeypatch):
    """文件框里挑到非音频 ⇒ 容器白名单拒绝 + warning toast（不产生空轨）。"""
    w = window
    toasts = _toasts(monkeypatch, w)
    w.left_panel.set_collapsed(False)
    w.file_browser._select_paths([])
    dialog(wavs)                                                  # 2 wav + 1 txt

    w._on_multitrack_add_from_browser()
    assert len(w.multitrack_session) == 2                         # txt 未成幽灵轨
    assert [t.path.name for t in w.multitrack_session.tracks()] == [
        "pick_0.wav", "pick_1.wav",
    ]
    assert any(level == "warning" and "notes.txt" in m for m, level in toasts)


def test_dialog_cancel_keeps_tracks_and_only_toasts(window, dialog, monkeypatch):
    w = window
    toasts = _toasts(monkeypatch, w)
    w.left_panel.set_collapsed(False)
    w.file_browser._select_paths([])
    state = dialog([])                                            # 用户取消
    before = len(w.multitrack_session)

    w._on_multitrack_add_from_browser()
    assert state["calls"] == 1
    assert len(w.multitrack_session) == before                    # ★ 反向：取消不塞轨
    assert w._multitrack_mode is False
    assert toasts and toasts[-1][0] == tr("multitrack.no_selection")


# ---------------------------------------------------------------------------
# ③ 有选中 ⇒ 兜底路径一步都不走
# ---------------------------------------------------------------------------


def test_existing_selection_bypasses_both_fallbacks(window, wavs, dialog):
    w = window
    w.file_browser.set_current_file(wavs[0])
    w.file_browser.refresh()
    w.file_browser._select_paths(wavs[:2])
    state = dialog(["/tmp/must_not_be_used.wav"])

    w._on_multitrack_add_from_browser()
    assert state["calls"] == 0                                    # 不弹框
    assert w.left_panel.is_collapsed() is True                    # 也不强行展开
    assert [t.label for t in w.multitrack_session.tracks()] == [
        "pick_0", "pick_1"
    ]
