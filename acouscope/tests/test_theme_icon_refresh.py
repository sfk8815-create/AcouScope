# SPDX-License-Identifier: GPL-3.0-only
"""T-1078/IM-29：运行时换主题后已挂载图标重染回归测（apply_theme 补 refresh_icons 一行）。

覆盖判据②两类图标源：QAction（主工具栏式）与 QPushButton.setIcon（左/右 ribbon
`_icon_btn` 同款），light→dark 后断言 cacheKey 变化且 pixmap 平均亮度显著升高
（暗底亮图标）；另测启动路径（顶层为空）refresh_icons 返回 0、apply_theme 不抛。
纪律：全程离屏（conftest 已设 QT_QPA_PLATFORM=offscreen）；不构造 MainWindow。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtGui import QAction, QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget  # noqa: E402

from acouscope.ui import theme  # noqa: E402
from acouscope.ui.theme import get_icon  # noqa: E402


@pytest.fixture(autouse=True)
def _pin_generic_and_restore_theme():
    """钉 generic 风格 + 复原主题（防跨文件污染，同 test_icon_render_smoke 口径）。"""
    prev_style = theme._icon_style
    prev_id = theme._theme_id
    theme._icon_style = "generic"
    theme._icon_cache.clear()
    yield
    theme._icon_style = prev_style
    theme.apply_theme(prev_id)


def _mean_luma(icon, size: int = 32) -> float:
    """图标 default 态 pixmap 的平均亮度（透明像素计 0；越大=着色越浅）。"""
    pm = icon.pixmap(size, size)
    assert not pm.isNull(), "图标渲染为空 pixmap"
    img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    total = 0.0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            total += (
                (0.2126 * c.red() + 0.7152 * c.green() + 0.0722 * c.blue())
                * c.alpha()
                / 255.0
            )
    return total / (img.width() * img.height())


def test_apply_theme_refreshes_toolbar_action_and_ribbon_button(qapp):
    """light→dark：QAction（工具栏式）与 QPushButton（ribbon 式）图标均须重染。"""
    theme.apply_theme("light")

    window = QWidget()  # QAction 挂在顶层窗口 actions() 上，与 QToolBar 同源可被遍历
    action = QAction(get_icon("save"), "save", window)
    window.addAction(action)
    button = QPushButton(window)  # _icon_btn 同款挂载方式：setIcon(get_icon(...))
    button.setIcon(get_icon("info"))

    key_before = (action.icon().cacheKey(), button.icon().cacheKey())
    luma_before = (_mean_luma(action.icon()), _mean_luma(button.icon()))

    theme.apply_theme("dark")

    assert action.icon().cacheKey() != key_before[0], "QAction（工具栏式）图标未重染"
    assert button.icon().cacheKey() != key_before[1], "QPushButton（ribbon 式）图标未重染"
    assert _mean_luma(action.icon()) > luma_before[0], "QAction 换肤后未变浅（深底应亮图）"
    assert _mean_luma(button.icon()) > luma_before[1], "QPushButton 换肤后未变浅（深底应亮图）"


def test_startup_apply_theme_without_widgets_refresh_zero_no_throw(qapp, monkeypatch):
    """启动路径（建窗前）：顶层为空 → refresh_icons 遍历 0 条、不抛、apply_theme 正常走完。"""
    monkeypatch.setattr(QApplication, "topLevelWidgets", staticmethod(lambda: []))
    assert theme.refresh_icons() == 0
    theme.apply_theme("light")  # 内含 refresh_icons()——空顶层下须不抛
    theme.apply_theme("dark")
