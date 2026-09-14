# SPDX-License-Identifier: GPL-3.0-only
"""T-915：波形右键「分析此区域」菜单项 + analyzeRegionRequested 信号。

离屏、独立构造 WaveformWidget；禁 MainWindow、禁 show()、禁真实分析计算。
QMenu.exec 用 monkeypatch 捕获（不跑嵌套事件循环，同 test_file_browser.py 口径）。
"""

import os, sys
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
import pytest
pytest.importorskip("PyQt6")
import numpy as np
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QMenu
from acouscope.i18n import tr
from acouscope.ui.widgets.waveform import WaveformWidget

# 禁词以拼接构造，避免模式字面量自身被扫中（同 test_file_browser.py 口径）。
_BANNED = "Mel" + "odyne"

_WAVEFORM_PY = (
    Path(__file__).resolve().parent.parent
    / "src" / "acouscope" / "ui" / "widgets" / "waveform.py"
)


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def widget(qapp):
    w = WaveformWidget()
    w.resize(1200, 400)
    sr = 1000; n = 5000
    t = np.arange(n, dtype=np.float32) / sr
    x = (0.3 * np.sin(2 * np.pi * 10 * t)).astype(np.float32)
    w.set_data(t, x, sample_rate=sr)
    qapp.processEvents()
    yield w
    w.close()


@pytest.fixture
def capture_menu(monkeypatch):
    """捕获 QMenu.exec：记录菜单本体、不跑嵌套事件循环。"""
    captured: dict = {}

    def fake_exec(self, *args, **kwargs):
        captured["menu"] = self
        return None

    monkeypatch.setattr(QMenu, "exec", fake_exec)
    return captured


def open_menu(widget, capture_menu) -> QMenu:
    """直接调用 _on_context_menu（位置任意），返回捕获到的菜单。"""
    widget._on_context_menu(QPoint(10, 10))
    return capture_menu["menu"]


def actions_of(menu: QMenu) -> list:
    return [a for a in menu.actions() if not a.isSeparator()]


def find_action(menu: QMenu, text: str):
    for a in menu.actions():
        if not a.isSeparator() and a.text() == text:
            return a
    return None


class TestMenuVisibility:
    def test_no_selection_no_action(self, widget, capture_menu):
        """无选区 → 菜单中不出现「分析此区域」动作。"""
        widget.clear_selection(emit=False)
        menu = open_menu(widget, capture_menu)
        assert find_action(menu, tr("ctx.analyze_region")) is None

    def test_with_selection_action_present(self, widget, capture_menu):
        """set_selection(1.0, 2.5) 后 → 菜单含该动作，且 text == tr 键值。"""
        widget.set_selection(1.0, 2.5)
        menu = open_menu(widget, capture_menu)
        act = find_action(menu, tr("ctx.analyze_region"))
        assert act is not None
        assert act.text() == tr("ctx.analyze_region")

    def test_action_is_first_item(self, widget, capture_menu):
        """动作位置 = 菜单第一项（在「添加区域标注」之前）。"""
        widget.set_selection(1.0, 2.5)
        menu = open_menu(widget, capture_menu)
        acts = actions_of(menu)
        assert acts[0].text() == tr("ctx.analyze_region")

    def test_clear_selection_action_disappears(self, widget, capture_menu):
        """clear_selection() 后再次打开菜单 → 该动作消失。"""
        widget.set_selection(1.0, 2.5)
        widget.clear_selection()
        menu = open_menu(widget, capture_menu)
        assert find_action(menu, tr("ctx.analyze_region")) is None


class TestSignal:
    def test_trigger_emits_signal(self, widget, capture_menu):
        """触发该动作 → analyzeRegionRequested 收到 (1.0, 2.5)。"""
        received = []
        widget.analyzeRegionRequested.connect(lambda a, b: received.append((a, b)))
        widget.set_selection(1.0, 2.5)
        menu = open_menu(widget, capture_menu)
        act = find_action(menu, tr("ctx.analyze_region"))
        assert act is not None
        act.trigger()
        assert len(received) == 1
        t0, t1 = received[0]
        assert abs(t0 - 1.0) < 1e-6 and abs(t1 - 2.5) < 1e-6

    def test_signal_args_float_ordered(self, widget, capture_menu):
        """参数类型为 float；反向输入经 set_selection 已排序（lo < hi）。"""
        received = []
        widget.analyzeRegionRequested.connect(lambda a, b: received.append((a, b)))
        widget.set_selection(2.5, 1.0)  # 反向输入
        menu = open_menu(widget, capture_menu)
        act = find_action(menu, tr("ctx.analyze_region"))
        assert act is not None
        act.trigger()
        assert len(received) == 1
        t0, t1 = received[0]
        assert isinstance(t0, float) and isinstance(t1, float)
        assert t0 < t1


class TestRegression:
    def test_existing_menu_items_unchanged(self, widget, capture_menu):
        """既有菜单项仍在（防回归）。"""
        widget.set_selection(1.0, 2.5)
        menu = open_menu(widget, capture_menu)
        texts = [a.text() for a in actions_of(menu)]
        assert "添加区域标注" in texts
        assert "添加时间点标注" in texts
        assert "清除全部标注" in texts
        assert "归一化显示（0dB 峰值）" in texts


class TestStatic:
    def test_banned_word_zero_hits(self):
        """禁词（The Pitch Grid 文档文件名首段品牌词）0 命中。"""
        for f in (_WAVEFORM_PY, Path(__file__)):
            assert _BANNED not in f.read_text(encoding="utf-8")

    def test_no_hex_px_in_added_lines(self):
        """T-915 新增行（按标识定位）无 hex/px 硬编码。"""
        import re
        lines = _WAVEFORM_PY.read_text(encoding="utf-8").splitlines()
        added = [ln for ln in lines
                 if ("T-915" in ln or "analyzeRegionRequested" in ln
                     or "_on_analyze_region" in ln or "ctx.analyze_region" in ln)]
        assert added, "应能定位到 T-915 新增行"
        for ln in added:
            assert not re.search(r"#[0-9a-fA-F]{6}\b", ln), f"hex 硬编码: {ln}"
            assert "px" not in ln, f"px 硬编码: {ln}"

    def test_no_qdialog_added(self):
        """未新增 QDialog（文件 0 处）。"""
        assert "QDialog" not in _WAVEFORM_PY.read_text(encoding="utf-8")
