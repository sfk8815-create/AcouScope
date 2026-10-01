# SPDX-License-Identifier: GPL-3.0-only
"""应用内「检查更新」——**只通知**（UP-2）。

本模块是 app 自更新线唯一的一环「能被发现、能被通知到」：读取一个小 JSON 清单，
判定本机版本是否为最新，并把结论告知用户。**零下载、零替换、零子进程、零自启浏览器**
（下载与校验属后续件）。

隐私红线（AD-5）：请求**零标识**——UA 不含版本号、URL 不含 query 参数；网络与解析
失败一律**静默返回**、**绝不重试**（禁重试风暴）。线程与网络代码只住本档。
"""

from __future__ import annotations

import json
from urllib.request import Request, urlopen

from PyQt6.QtCore import QThread, pyqtSignal

import acouscope
from acouscope.utils.versioning import is_newer

#: 权威清单源（AD-10：官网 Pages 站；AD-2 单一真值源）
MANIFEST_URL = "https://sfk8815-create.github.io/dl/latest.json"

#: 请求标识（★ 必无版本号、必无数字；AD-5）
USER_AGENT = "AcouScope"

#: 自动检查的最小间隔（天）——每日至多一次
CHECK_INTERVAL_DAYS = 1

#: 单次请求超时上限（秒）
TIMEOUT_S = 8

# ---- 结果六码契约（与引擎自更新同族）----
CODE_OK = "ok"                  # 有新版
CODE_UP_TO_DATE = "up_to_date"  # 已最新
CODE_NO_NETWORK = "no_network"  # 网络不可达（fetch 返 None）
CODE_MALFORMED = "malformed"    # 清单内容不可解析
CODE_DISABLED = "disabled"      # 开关关
CODE_THROTTLED = "throttled"    # 同日已查过


def fetch_manifest(url: str = MANIFEST_URL, timeout: float = TIMEOUT_S) -> dict | None:
    """读取并解析更新清单（纯函数·零 Qt·可脱离 GUI 单测）。

    Args:
        url: 清单地址（默认权威源；测试可注入本地 ``file://`` 或替身）。
        timeout: 单次请求超时上限（秒）。

    Returns:
        清单字典；**网络不可达 / 非 200** ⇒ ``None``（调用侧判为 ``no_network``）；
        响应体不是可解析的 JSON 对象 ⇒ 空字典 ``{}``（调用侧判为 ``malformed``）。

    ★ 绝不抛异常、绝不重试、不写日志以外的副作用。
    """
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", None)
            if status is not None and status != 200:
                return None
            raw = resp.read()
    except Exception:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def parse_manifest(data: dict) -> tuple[str, str] | None:
    """从清单字典取 ``(version, notes_url)``（纯函数）。

    ``version`` 缺失 / 非字符串 ⇒ ``None``（调用侧判为 ``malformed``）；
    ``notes_url`` 缺失 / 非字符串时回落空串（不影响版本判定）。
    """
    version = data.get("version")
    if not isinstance(version, str) or not version:
        return None
    notes_url = data.get("notes_url")
    if not isinstance(notes_url, str):
        notes_url = ""
    return version, notes_url


def is_update_available(new: str, current: str) -> bool:
    """``new`` 是否严格高于 ``current``（薄引 ``versioning.is_newer``·同一实现）。

    ★ 只复用 UP-0 的比较器，**禁复制第二份**；导入失败即报错，不静默降级。
    """
    return is_newer(new, current)


class UpdateCheckWorker(QThread):
    """后台执行「读清单 → 判版本」全流程（非模态；线程与网络只住本档）。

    结果经 :attr:`finished_with` 交回 UI 线程；``ok`` 时版本号与 ``notes_url``
    分别由 :attr:`new_version` / :attr:`notes_url` 携带。★ 禁 ``QTimer``——节流
    用日期串比较，见 :mod:`acouscope.state`。
    """

    #: 结果信号：(六码之一, 新版本号；无新版时为 "")
    finished_with = pyqtSignal(str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.new_version = ""
        self.notes_url = ""

    def run(self) -> None:
        """线程体：只调三个纯函数 + 现读 ``acouscope.__version__``。"""
        data = fetch_manifest()
        if data is None:
            self.finished_with.emit(CODE_NO_NETWORK, "")
            return
        parsed = parse_manifest(data)
        if parsed is None:
            self.finished_with.emit(CODE_MALFORMED, "")
            return
        new_version, notes_url = parsed
        self.new_version = new_version
        self.notes_url = notes_url
        if is_update_available(new_version, acouscope.__version__):
            self.finished_with.emit(CODE_OK, new_version)
        else:
            self.finished_with.emit(CODE_UP_TO_DATE, "")
