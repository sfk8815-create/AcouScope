# SPDX-License-Identifier: GPL-3.0-only
"""Qt 绘制路径守卫：禁「先红失效」的 render()/grab() 判据写法。

背景（2026-10-21 实证，配方见 MEMORY「Qt 绘制路径判据配方」）：
  PyQt6 把 C++→Python 边界（render()→paintEvent）内抛出的 Python 异常
  **打印到 stderr 后吞掉** ⇒ pytest 见绿，而真实 GUI 会 SIGABRT。
  ⇒ 用 render()/grab() 写「先红」判据 = **假绿**（D14-fix 轮踩过）。

本守卫把这条认知固化为**可执行断言**：
  ① 探针：paintEvent 抛异常 ⇒ grab() 路径下 pytest 仍绿（吞没）
     （**证明吞没确实存在**）；
  ② 探针：同一异常在**直调 paintEvent(QPaintEvent(QRect(...)))** 下
     **正常传播**（⇒ 这才是「先红」有效的写法）；常规运行以 pytest.raises
     锁形态（绿），自证时以 PAINT_GUARD_RAW_PROBE=1 跑原声探针（设计为红，
     形态 AttributeError）；
  ③ 静态：全仓 tests/ 内**禁用** render()/grab() 写「期望抛异常」类判据
     （只禁「断言异常」这一种误用；不禁正常的像素取值判据 —— A7/A8 仍在用 grab）。
"""

import ast
import os
import signal
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")

from PyQt6.QtCore import QRect
from PyQt6.QtGui import QPaintEvent
from PyQt6.QtWidgets import QApplication, QWidget

# 原声探针开关：置 1 时把「②直调传播」切成不套 pytest.raises 的形态（期望红）
_RAW_PROBE = os.environ.get("PAINT_GUARD_RAW_PROBE") == "1"
_WATCHDOG_S = 90


def _on_alarm(signum, frame):  # noqa: ARG001
    os._exit(99)


signal.signal(signal.SIGALRM, _on_alarm)


@pytest.fixture(autouse=True)
def _watchdog():
    signal.alarm(_WATCHDOG_S)
    yield
    signal.alarm(0)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


_PAINT_ENTRIES: list = []


class _BoomWidget(QWidget):
    """绘制探针：paintEvent 进入即登记，随后必抛 AttributeError。

    登记用于区分「没进 paintEvent」与「进了但异常被吞」。
    """

    def paintEvent(self, event):  # noqa: N802 (Qt 命名)
        _PAINT_ENTRIES.append(True)
        _ = self.this_attribute_does_not_exist  # noqa: B018 ⇒ AttributeError
        super().paintEvent(event)  # 不可达


def test_render_path_swallows_paint_event_exception(qapp):
    """① 吞没探针（期望**绿**）：grab() 触发 paintEvent 抛 AttributeError，
    PyQt6 在 C++→Python 边界打印后吞掉 ⇒ grab() 正常返回、pytest 见绿。"""
    probe = _BoomWidget()
    try:
        probe.resize(64, 24)
        before = len(_PAINT_ENTRIES)
        pm = probe.grab()
        assert len(_PAINT_ENTRIES) > before, "paintEvent 未执行（探针失效）"
        assert pm is not None and not pm.isNull(), "grab() 应返回有效 QPixmap"
    finally:
        probe.close()


@pytest.mark.skipif(
    _RAW_PROBE, reason="原声模式下由 raw 探针承担（设计为红）"
)
def test_direct_paint_event_call_propagates_exception(qapp):
    """② 直调探针（守门形态，期望**绿**）：直调走纯 Python 栈，
    AttributeError 正常传播 ⇒ 以 pytest.raises 锁住形态。"""
    probe = _BoomWidget()
    try:
        probe.resize(64, 24)
        before = len(_PAINT_ENTRIES)
        with pytest.raises(AttributeError):
            probe.paintEvent(QPaintEvent(QRect(0, 0, 64, 24)))
        assert len(_PAINT_ENTRIES) > before, "paintEvent 未执行（探针失效）"
    finally:
        probe.close()


@pytest.mark.skipif(
    not _RAW_PROBE,
    reason="原声探针：仅自证时以 PAINT_GUARD_RAW_PROBE=1 运行（期望红）",
)
def test_direct_paint_event_raw_probe_is_red(qapp):
    """② 原声探针（**设计为红**）：不套 pytest.raises，直调 paintEvent
    ⇒ AttributeError 传播 ⇒ pytest 红、形态 AttributeError。"""
    probe = _BoomWidget()
    try:
        probe.resize(64, 24)
        probe.paintEvent(QPaintEvent(QRect(0, 0, 64, 24)))
    finally:
        probe.close()


def _with_has_raises(with_node: ast.With) -> bool:
    for item in with_node.items:
        ctx = item.context_expr
        if isinstance(ctx, ast.Call):
            fn = ctx.func
            if (getattr(fn, "attr", None) or getattr(fn, "id", None)) == "raises":
                return True
    return False


def _render_grab_calls_inside_raises(src: str, filename: str) -> list:
    """列出位于 pytest.raises 上下文内的 .render()/.grab() 调用点（只禁此一种）。"""
    tree = ast.parse(src)
    parents: dict = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def _in_raises(node) -> bool:
        cur = parents.get(node)
        while cur is not None:
            if isinstance(cur, ast.With) and _with_has_raises(cur):
                return True
            cur = parents.get(cur)
        return False

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "attr", None) not in ("render", "grab"):
            continue
        if _in_raises(node):
            offenders.append(f"{filename}:{node.lineno}")
    return offenders


def test_static_scan_no_render_grab_raise_assertion(qapp):
    """③ 静态扫描：tests/ 内不得出现「用 render()/grab() 断言抛异常」。"""
    offenders: list = []
    for path in sorted(Path(__file__).resolve().parent.rglob("test_*.py")):
        try:
            src = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            offenders += _render_grab_calls_inside_raises(src, path.name)
        except SyntaxError:
            continue
    assert not offenders, (
        "render()/grab() 不可用于「断言抛异常」类判据（PyQt 吞没 ⇒ 假绿）；"
        f"误用点：{offenders}。像素取值请照 A7/A8 相对差异法（本守卫不禁 grab）。"
    )
