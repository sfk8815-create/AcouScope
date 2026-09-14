# SPDX-License-Identifier: GPL-3.0-only
"""CB-008 / T-604 回归测试：main_window 4 处工具栏 action 图标走 theme.get_icon。

断言纪律：
- offscreen 全程（conftest 已 setdefault）；构造 MainWindow 但不 .show()、无 QDialog/.exec()；
- 图标非空 = QIcon.isNull() == False；不硬编码绝对像素/位图尺寸。
"""

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from acouscope.app.controller import AppController
from acouscope.ui import theme
from acouscope.ui.main_window import MainWindow

# T-604 四锚点逻辑名（须与 main_window 实际替换名一致；theme.ICONS 已映射到 generic/ SVG）
_T604_ACTION_NAMES = ("open", "undo", "redo", "export")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """带已加载音频的主窗口（绕过付费门控；不 show()，参照 test_view_stack.py）。"""


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


def test_action_icons_from_get_icon_not_null(window):
    """T-604：4 处 standardIcon 替换后，action 图标全部非空（QIcon.isNull()==False）。"""
    for name in _T604_ACTION_NAMES:
        icon = getattr(window, f"action_{name}").icon()
        assert icon is not None and not icon.isNull(), f"action_{name} 图标为空"


def test_t604_icon_mapping_reaches_file(window):
    """图标底层确实落到 resources/icons/generic/ 的 SVG（替换非空转义）。"""
    for name in _T604_ACTION_NAMES:
        p = theme.icon_path(name)
        assert p is not None, f"{name} 无资源映射"
        assert p.exists(), f"{name} 资源文件缺失: {p}"
        assert "generic" in p.parts, f"{name} 未指向 generic/: {p}"


def test_get_icon_open_export_not_null(qapp):
    """acceptance：get_icon("open")/get_icon("export") 非 isNull（图标引擎可渲染非空）。"""
    assert theme.get_icon("open") is not None and not theme.get_icon("open").isNull()
    assert theme.get_icon("export") is not None and not theme.get_icon("export").isNull()


def test_standard_icon_gone_from_main_window():
    """AT-703 防回退：main_window.py 不再引用 standardIcon（源码级守卫，无需 qapp）。"""
    src = MainWindow.__module__
    import importlib
    import pathlib

    mod_file = pathlib.Path(importlib.import_module(src).__file__).resolve()
    text = mod_file.read_text(encoding="utf-8")
    assert "standardIcon" not in text
    assert "QStyle" not in text
