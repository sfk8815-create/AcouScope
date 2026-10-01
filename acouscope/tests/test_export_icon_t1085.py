# SPDX-License-Identifier: GPL-3.0-only
"""T-1085 守卫测：真机目测 #4 —— ICONS["export"] 改指 generic/download.svg。

最小解（非扩容）：export 键已存在，仅值不再与 save 同指 save.svg；
键计数不变（31），download.svg 为既有四风格空闲图标。
断言纪律：全离屏，不 show()、不弹模态。
"""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from acouscope.ui import theme
from tests._pin_baselines import ICONS_LOGICAL_NAME_COUNT


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_export_no_longer_shares_save_asset():
    assert theme.ICONS["export"] != theme.ICONS["save"]


def test_export_points_to_download_svg():
    assert theme.ICONS["export"] == "generic/download.svg"


def test_export_icon_renders_offscreen(qapp):
    assert not theme.get_icon("export").isNull()


def test_icons_count_unchanged_31():  # 名内 31 系 T-1085 历史里程碑（改名动 nodeid·保名）；真实计数现由 ICONS_LOGICAL_NAME_COUNT 把守（现 33）
    assert len(theme.ICONS) == ICONS_LOGICAL_NAME_COUNT


def test_save_untouched_still_save_svg():
    assert theme.ICONS["save"] == "generic/save.svg"
    assert not theme.get_icon("save").isNull()
