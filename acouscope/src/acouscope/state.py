# SPDX-License-Identifier: GPL-3.0-only
"""应用状态记录（跨启动持久化的轻量状态）。

与旧 ``license.json`` **完全切割**：本模块只读写 ``get_data_dir()/app_state.json``，
不读不写任何许可/授权文件。

字段：

- ``first_run_timestamp``：首次运行时间（ISO8601 字符串，视为安装时间）
- ``sponsor_reminder_dismissed``：是否已点「已支持，不再提醒」

读写一律容错：文件缺失 / 内容损坏 / 无权限 / 非字典时返回默认值，**绝不抛异常**
（启动路径上的状态读取不得影响主流程）。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from acouscope.utils import config as _config

#: 触发赞助提示所需的运行时长——首次运行满 2 小时后
SPONSOR_REMINDER_DELAY = timedelta(hours=2)

#: 状态文件名（位于数据目录）
_STATE_FILENAME = "app_state.json"

#: 状态字段名
FIELD_FIRST_RUN = "first_run_timestamp"
FIELD_SPONSOR_DISMISSED = "sponsor_reminder_dismissed"


def state_path() -> Path:
    """应用状态文件路径（数据目录下的 app_state.json）。

    数据目录经 :func:`acouscope.utils.config.get_data_dir` 动态获取，
    便于测试经 monkeypatch 重定向。
    """
    return _config.get_data_dir() / _STATE_FILENAME


def load_state() -> dict:
    """读取状态字典。

    Returns:
        状态字典；文件缺失 / 损坏 / 非字典时返回空字典（绝不抛）。
    """
    try:
        with state_path().open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(state: dict) -> bool:
    """写回状态字典。

    Returns:
        写入成功为 True；失败（无权限 / 非法内容等）为 False（绝不抛）。
    """
    try:
        path = state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _parse_timestamp(value: object) -> datetime | None:
    """把状态中的时间字段解析为 datetime；非法值返回 None。"""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def get_first_run_timestamp() -> datetime | None:
    """首次运行时间；未记录或损坏时返回 None。"""
    return _parse_timestamp(load_state().get(FIELD_FIRST_RUN))


def ensure_first_run(now: datetime | None = None) -> datetime:
    """确保首次运行时间已落盘并返回它。

    首次运行（字段缺失或损坏）时把当前时间（视为安装时间）写入状态文件。

    Args:
        now: 供测试注入的时间；None 时取 :func:`datetime.now`。
    """
    now = now or datetime.now()
    existing = get_first_run_timestamp()
    if existing is not None:
        return existing
    state = load_state()
    state[FIELD_FIRST_RUN] = now.isoformat(timespec="seconds")
    save_state(state)
    return now


def is_sponsor_reminder_dismissed() -> bool:
    """是否已点「已支持，不再提醒」。"""
    return bool(load_state().get(FIELD_SPONSOR_DISMISSED, False))


def set_sponsor_reminder_dismissed(dismissed: bool = True) -> bool:
    """持久化「不再提醒」标记。

    Returns:
        写入成功为 True（绝不抛）。
    """
    state = load_state()
    state[FIELD_SPONSOR_DISMISSED] = bool(dismissed)
    return save_state(state)


def should_show_sponsor_reminder(now: datetime | None = None) -> bool:
    """是否应弹出赞助致谢框。

    判定：已点「不再提醒」→ False；否则「首次运行满 2 小时」→ True。
    首次运行时间缺失 / 损坏 / 时区不可比时按「不弹」处理（绝不抛）。
    """
    if is_sponsor_reminder_dismissed():
        return False
    first_run = get_first_run_timestamp()
    if first_run is None:
        return False
    now = now or datetime.now()
    try:
        elapsed = now - first_run
    except TypeError:  # naive / aware 混用等
        return False
    return elapsed >= SPONSOR_REMINDER_DELAY
