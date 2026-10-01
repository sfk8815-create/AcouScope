# SPDX-License-Identifier: GPL-3.0-only
"""T-1010 守卫测试：AI 释图去模态化 + 右栏内容宿主承载（原 T-507a 抽屉承载废止）。

覆盖：容器类型迁移 / 源码无模态调用 / 调用侧不再开右抽屉（改路由右栏
「AI 释图」页，每次打开新建实例）/ 入口重入时旧面板先 close 再移出宿主 /
面板 close() 幂等。
T-1054d：抽屉机制整体退役（drawer.py 整档删除），原 DrawerWidget 契约面
用例改写为右栏内容宿主的等价在役语义。
"""

import pathlib

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QDialog, QWidget

from acouscope.app.controller import AppController
from acouscope.ui.main_window import MainWindow
from acouscope.ui.widgets import ai_interpret

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """带已加载音频的主窗口（绕过付费门控；不 show，参照 test_sidebar_tabs.py）。"""

    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 20.0)) / sr
    sweep = 0.5 * np.sin(2 * np.pi * (200 + 300 * t) * t)
    controller.load_from_array(sweep, sr)

    w = MainWindow(controller)
    yield w
    w.close()


def _make_panel():
    """lambda getter 三件套实例化（签名与测试构造面一致）。"""
    return ai_interpret.AIInterpretDialog(
        image_getter=lambda: None,
        context_getter=lambda: "",
        view_name_getter=lambda: "波形",
    )


class TestAiPanelContainer:
    def test_ai_panel_is_qwidget_not_dialog(self, qapp):
        assert issubclass(ai_interpret.AIInterpretDialog, QWidget)
        assert not issubclass(ai_interpret.AIInterpretDialog, QDialog)
        panel = _make_panel()
        assert isinstance(panel, QWidget)
        assert not isinstance(panel, QDialog)

    def test_ai_source_no_modal(self):
        src = (_REPO_ROOT / "src" / "acouscope" / "ui" / "widgets" / "ai_interpret.py").read_text(
            encoding="utf-8"
        )
        assert "class AIInterpretDialog(QDialog)" not in src
        # _on_failed 的 MRO 写法（_t504g_modal）不含 ".exec(" 字面量，此处断言安全
        assert ".exec(" not in src


def _main_window_source() -> str:
    return (_REPO_ROOT / "src" / "acouscope" / "ui" / "main_window.py").read_text(encoding="utf-8")


def _on_ai_interpret_body() -> str:
    """按缩进边界提取 _on_ai_interpret 函数体（到下一同级 def/class/顶层语句为止）。"""
    src = _main_window_source()
    start = src.index("def _on_ai_interpret")
    lines = src[start:].splitlines()
    body = [lines[0]]
    for line in lines[1:]:
        if line.strip() == "":  # 函数体内空行（如 docstring 内）不截断
            body.append(line)
            continue
        if not line.startswith("    "):
            break
        if line.startswith("    def ") or line.startswith("    class "):
            break
        body.append(line)
    return "\n".join(body)


class TestMainWindowAiRouting:
    def test_main_window_routes_to_right_tab_not_drawer(self):
        body = _on_ai_interpret_body()
        assert ".exec()" not in body
        # T-1010：AI 释图不再开右抽屉，改由右栏内容页承载
        assert "open_drawer" not in body
        assert "width=640" not in body
        assert "_activate_ai_tab" in body
        assert "_ai_dialog" not in body
        # T-1054d 强化：抽屉能力面已整档退役（源文件不存在）
        assert not (
            _REPO_ROOT / "src" / "acouscope" / "ui" / "widgets" / "drawer.py"
        ).exists()


class TestRightContentLifecycle:
    """T-1054d：原 DrawerWidget 契约面（set_content 替换旧内容 / shutdown_content
    幂等）改写为右栏「AI 释图」内容宿主的等价在役语义。"""

    def test_ai_entry_closes_old_panel(self, window, qapp):
        """入口重入 → 旧 AI 面板实例先被 close 再移出宿主（原 set_content 语义）。"""
        window.inspector_panel.aiRequested.emit()
        qapp.processEvents()
        old = window._ai_panel
        assert isinstance(old, ai_interpret.AIInterpretDialog)
        assert old.parent() is window._ai_host

        closed = []
        _orig_close = old.close
        # 实例级探针：记录旧面板的 close 调用（close 语义仍走原实现）
        old.close = lambda: (closed.append(True), _orig_close())[1]
        try:
            window.action_ai_interpret.trigger()
            qapp.processEvents()
            assert closed == [True]  # 替换前已调 close（触发其 closeEvent）
            assert window._ai_panel is not old  # 每次入口新建实例
            assert old.parent() is None  # 旧实例已移出宿主
            assert window._ai_panel.parent() is window._ai_host
        finally:
            window._ai_panel.close()

    def test_ai_panel_close_idempotent(self, window, qapp):
        """AI 释图面板 close() 幂等：重复 close 不抛异常（worker 收尾一次）。"""
        window.action_ai_interpret.trigger()
        qapp.processEvents()
        panel = window._ai_panel
        assert isinstance(panel, ai_interpret.AIInterpretDialog)
        panel.close()
        # 幂等：再次 close 不报错（契约仅要求不抛；实例仍被主窗跟踪）
        panel.close()
        assert window._ai_panel is panel
