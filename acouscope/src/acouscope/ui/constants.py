# SPDX-License-Identifier: GPL-3.0-only
"""网站链接常量与打开封装（T-1015）。

主站 / 副站地址只在此集中登记，各处一律引用本模块常量，禁止散落硬编码字符串。
副站本轮仅登记不链接（后续要用再单独裁决）。

打开方式统一走 open_site() → QDesktopServices.openUrl（复用 file_browser.py
既有模式）；仅由用户点击触发，禁止自动打开。
"""

from __future__ import annotations

# 主站：AcouScope 官方网站（logo / 帮助菜单 / 工具栏 / 左图标栏入口均指向此）
SITE_MAIN_URL = "https://sfk8815-create.github.io"

# 副站：镜像站点（T-1015 仅登记，不链接）
SITE_MIRROR_URL = "https://acouscope.vercel.app"


def open_site(url: str | None = None) -> None:
    """在系统默认浏览器打开站点 URL（缺省 = 主站）。

    仅在用户点击触发时调用；模块内不做任何自动打开。
    """
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices

    QDesktopServices.openUrl(QUrl(url if url else SITE_MAIN_URL))
