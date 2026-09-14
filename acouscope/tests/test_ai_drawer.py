# SPDX-License-Identifier: GPL-3.0-only
"""T-1010 守卫测试：AI 释图去模态化 + 右栏 tab 承载（原 T-507a 抽屉承载废止）。

覆盖：容器类型迁移 / 源码无模态调用 / 调用侧不再开右抽屉（改路由右栏
「AI 释图」tab，每次打开新建实例）/ set_content 替换旧内容前触发其
closeEvent / shutdown_content 幂等（DrawerWidget 组件契约保留）。
"""

import pathlib

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QDialog, QWidget

from acouscope.ui.widgets import ai_interpret
from acouscope.ui.widgets.drawer import open_drawer

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _make_panel():
    """lambda getter 三件套实例化（签名与测试构造面一致）。"""
    return ai_interpret.AIInterpretDialog(
        image_getter=lambda: None,
        context_getter=lambda: "",
        view_name_getter=lambda: "波形",
    )


def _close_counting_widget():
    """测试替身：重写 closeEvent 计数（event.accept() 保持默认关闭语义）。"""

    class _CountingWidget(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.closed = 0

        def closeEvent(self, event):
            self.closed += 1
            event.accept()

    return _CountingWidget()


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
        # T-1010：AI 释图不再开右抽屉，改由右栏 tab 承载
        assert "open_drawer" not in body
        assert "width=640" not in body
        assert "_activate_ai_tab" in body
        assert "_ai_dialog" not in body


class TestDrawerContentLifecycle:
    def test_set_content_closes_old_widget(self, qapp):
        host = QWidget()
        w1 = _close_counting_widget()
        open_drawer(host, w1, 640)
        assert w1.closed == 0  # 装入本身不关闭
        w2 = _close_counting_widget()
        open_drawer(host, w2, 640)  # 复用同宽抽屉 → set_content 替换 w1
        assert w1.closed == 1  # 删旧内容前已调 close（触发 closeEvent）
        assert w2.closed == 0

    def test_shutdown_content_closes(self, qapp):
        host = QWidget()
        w3 = _close_counting_widget()
        open_drawer(host, w3, 640)
        drawer = host._v099_drawer_640
        drawer.shutdown_content()
        assert w3.closed == 1
        # 幂等：再调一次不报错（契约 D5 仅要求不抛；实测 close() 每次调用
        # 均派发 QCloseEvent，计数递增属 QWidget 正常语义，非泄漏/崩溃）
        drawer.shutdown_content()
        assert w3.closed >= 1
