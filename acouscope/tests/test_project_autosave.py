# SPDX-License-Identifier: GPL-3.0-only
"""T-322 项目自动保存与异常恢复回归测试（离屏）。

两级轻量数据保护：周期自动保存（脏标记 + 已命名→原路径 / 未命名→autosave 快照）
+ 正常退出干净标志闭环 + 异常退出恢复探测。不自动保存音频数据本身。

禁 MainWindow.show()；构造 MainWindow(controller) 但不 show；closeEvent 用显式
QCloseEvent 触发（离屏隐藏窗口 close() 不派发关闭事件）。
"""

import json
import re
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication

from acouscope.app.controller import AppController
from acouscope.ui.main_window import MainWindow

_SR = 8000
_DURATION = 5.0
_MAIN_PY = (
    Path(__file__).resolve().parent.parent
    / "src" / "acouscope" / "ui" / "main_window.py"
)

# 禁词以拼接构造，避免模式字面量自身被扫中（同 test_file_browser.py 口径）。
_BANNED = "Mel" + "odyne"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """带已加载音频的主窗口（禁 show；HOME→tmp 防污染真实用户数据目录）。"""

    monkeypatch.setenv("HOME", str(tmp_path))

    controller = AppController()
    t = np.arange(int(_SR * _DURATION)) / _SR
    controller.load_from_array(0.5 * np.sin(2 * np.pi * 440.0 * t), _SR)

    w = MainWindow(controller)
    yield w
    try:
        w.close()
    except Exception:
        pass


def _snapshots(window):
    d = window._autosave_dir()
    if not d.is_dir():
        return []
    return list(d.glob("autosave_*.acouproj"))


def _close_window(window):
    """显式派发关闭事件（离屏未 show 时 close() 不触发 closeEvent）。"""
    window.closeEvent(QCloseEvent())


class TestDirtyMark:
    def test_initial_not_dirty(self, window):
        assert window._project_dirty is False

    def test_manual_save_clears_then_annotation_marks(self, window, tmp_path):
        """手动保存成功 → 清脏；标注 add/move/remove → 置脏。"""
        p = tmp_path / "p.acouproj"
        window._do_save_project(p)
        assert p.exists(), "手动保存应真实写盘"
        assert window._project_dirty is False

        model = window.waveform_widget.annotations
        model.add_region(1.0, 2.0, label="A")
        assert window._project_dirty is True, "标注新增应置脏"
        window._do_save_project(p)
        assert window._project_dirty is False

        model.add_instant(3.0)
        assert window._project_dirty is True
        window._do_save_project(p)
        assert window._project_dirty is False
        model.clear_regions()
        assert window._project_dirty is True

    def test_selection_and_playhead_do_not_mark_dirty(self, window):
        """选区/播放位置（非持久内容）不得置脏。"""
        window.waveform_widget.set_selection(1.0, 2.5)
        window.waveform_widget.set_playhead(1.0)
        window.waveform_widget.get_analysis_position()
        assert window._project_dirty is False, "选区/播放头不得触发自动保存"


class TestAutosaveTick:
    def test_tick_without_dirty_no_write(self, window):
        """dirty=False 时 tick 不落盘。"""
        window._on_autosave_tick()
        assert _snapshots(window) == []
        assert window._project_dirty is False

    def test_tick_dirty_unnamed_writes_snapshot_and_loadable(self, window):
        """未命名项目 → autosave 快照；不把项目改名为快照路径；可 load 回。"""
        window._mark_project_dirty()
        window._on_autosave_tick()

        snaps = _snapshots(window)
        assert len(snaps) == 1, "未命名 + 脏 → 应写 autosave 快照"
        assert window.controller.project.filepath is None, "快照不得改变项目命名路径"
        assert window._project_dirty is False

        project, _info = window.controller.load_project(snaps[0])
        assert project is not None, "快照应可 load 回项目"

    def test_tick_dirty_named_writes_original_path(self, window, tmp_path, monkeypatch):
        """已命名项目 → 写原路径（不产生快照）；可经 spy 断言调用路径。"""
        p = tmp_path / "named.acouproj"
        window._do_save_project(p)
        window._mark_project_dirty()

        calls = []
        monkeypatch.setattr(
            MainWindow, "_save_project_to",
            lambda self, filepath: calls.append(Path(filepath)),
        )
        window._on_autosave_tick()
        assert calls == [p], f"已命名自动保存应写原路径 {p}，实得 {calls}"
        assert window._project_dirty is False
        assert _snapshots(window) == []

    def test_tick_keeps_single_latest_snapshot(self, window):
        """autosave 快照只保留最近 1 份。"""
        window._mark_project_dirty()
        window._on_autosave_tick()
        window._mark_project_dirty()
        window._on_autosave_tick()
        snaps = _snapshots(window)
        assert len(snaps) == 1, "应只保留最近一份快照"

    def test_tick_failure_warns_once_only(self, window, monkeypatch):
        """自动保存失败只温和提示一次（不反复打扰）。"""
        def boom(*_args, **_kwargs):
            raise OSError("disk full")
        monkeypatch.setattr(window.controller, "save_project", boom)
        toasts = []
        monkeypatch.setattr(
            "acouscope.ui.main_window.show_toast",
            lambda w, msg, level="info": toasts.append((level, msg)),
        )
        window._mark_project_dirty()
        window._on_autosave_tick()
        window._on_autosave_tick()
        assert len(toasts) == 1, "失败提示仅一次"


class TestCleanExitAndRestore:
    def test_close_normal_writes_flag_and_cleans_snapshot(self, window):
        """正常退出：清理快照 + 写干净标志（闭环）。"""
        d = window._autosave_dir()
        d.mkdir(parents=True, exist_ok=True)
        snap = d / "autosave_20260909_120000.acouproj"
        snap.write_text("{}", encoding="utf-8")

        _close_window(window)

        assert (d / "clean.flag").exists(), "正常退出应写干净标志"
        assert not snap.exists(), "正常退出应清理快照"

    def test_close_without_autosave_dir_no_side_effect(self, window):
        """从未用过 autosave（目录不存在）时正常退出零文件副作用。"""
        d = window._autosave_dir()
        assert not d.exists()
        _close_window(window)
        assert not d.exists(), "无 autosave 目录时不得新建/写文件"

    def test_detect_restore_only_without_clean_flag(self, window):
        """异常恢复探测：无 clean 标志且有快照 → 可恢复；有 clean 标志 → 不提示。"""
        d = window._autosave_dir()
        d.mkdir(parents=True, exist_ok=True)
        snap = d / "autosave_20260909_120000.acouproj"
        snap.write_text(json.dumps({"name": "crash-session"}), encoding="utf-8")

        assert window._detect_restorable_snapshot() == snap, "无干净标志应探测到快照"
        (d / "clean.flag").write_text("2026-09-09", encoding="utf-8")
        assert window._detect_restorable_snapshot() is None, "有干净标志不提示恢复"
        (d / "clean.flag").unlink()


class TestStatic:
    def test_banned_word_zero_hits(self):
        """禁词 0 命中（主窗 + 本测试文件）。"""
        for f in (_MAIN_PY, Path(__file__)):
            assert _BANNED not in f.read_text(encoding="utf-8")

    def test_no_hex_px_in_added_lines(self):
        """新增 T-322 标记行无硬编码 hex/px。"""
        src = _MAIN_PY.read_text(encoding="utf-8")
        added = [ln for ln in src.splitlines() if "T-322" in ln]
        assert added, "应存在 T-322 标记行"
        for ln in added:
            assert not re.search(r"#[0-9a-fA-F]{6}\b", ln), f"hex 硬编码: {ln}"
            assert "px" not in ln, f"px 硬编码: {ln}"
            assert "print(" not in ln, f"零终端被违反: {ln}"

    def test_no_new_qdialog(self):
        """T-322 标记行无新建 QDialog。"""
        src = _MAIN_PY.read_text(encoding="utf-8")
        for ln in src.splitlines():
            if "T-322" in ln:
                assert "QDialog" not in ln, f"禁新建 QDialog: {ln}"
