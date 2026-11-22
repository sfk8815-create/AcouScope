# SPDX-License-Identifier: GPL-3.0-only
"""应用状态记录（跨启动持久化的轻量状态）。

与旧 ``license.json`` **完全切割**：本模块只读写 ``get_data_dir()/app_state.json``，
不读不写任何许可/授权文件。

字段：

- ``first_run_timestamp``：首次运行时间（ISO8601 字符串，视为安装时间；仅装机记录，不参与赞助判定）
- ``sponsor_reminder_dismissed``：是否已点「已支持，不再提醒」（永久停弹条件）
- ``launch_count``：已启动次数（达到阈值 5 后起弹的计数依据，T-1110）
- ``sponsor_snooze_until_launch``：「继续使用」节流到的启动序号（缺键按 0）

读写一律容错：文件缺失 / 内容损坏 / 无权限 / 非字典时返回默认值，**绝不抛异常**
（启动路径上的状态读取不得影响主流程）。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from acouscope.utils import config as _config

#: 赞助提示的启动次数阈值——第 5 次启动起弹（项目负责人 2026-09-26 定案；
#: 值不变。「此后每次启动均弹」改由 :func:`snooze_sponsor_reminder` 节流）
SPONSOR_PROMPT_LAUNCH_THRESHOLD = 5

#: 状态文件名（位于数据目录）
_STATE_FILENAME = "app_state.json"

#: 状态字段名
FIELD_FIRST_RUN = "first_run_timestamp"
FIELD_SPONSOR_DISMISSED = "sponsor_reminder_dismissed"
FIELD_LAUNCH_COUNT = "launch_count"
#: 「继续使用」节流目标（启动序号）；缺键按 0，绝不抛
FIELD_SPONSOR_SNOOZE_UNTIL_LAUNCH = "sponsor_snooze_until_launch"


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


def get_launch_count() -> int:
    """已启动次数（键缺失 / 非整数一律按 0，绝不抛）。"""
    value = load_state().get(FIELD_LAUNCH_COUNT, 0)
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 0


def bump_launch_count() -> int:
    """本次启动 +1 并落盘，返回落盘后的计数。

    写盘失败仍返回计算值（启动路径不得因赞助计数抛异常或阻塞）。
    """
    state = load_state()
    try:
        count = int(state.get(FIELD_LAUNCH_COUNT, 0)) + 1
    except (TypeError, ValueError, OverflowError):
        count = 1
    state[FIELD_LAUNCH_COUNT] = count
    save_state(state)
    return count


def get_sponsor_snooze_until_launch() -> int:
    """「继续使用」节流到的启动序号（键缺失 / 非整数一律按 0，绝不抛）。"""
    value = load_state().get(FIELD_SPONSOR_SNOOZE_UNTIL_LAUNCH, 0)
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 0


def snooze_sponsor_reminder(launches: int = 5) -> bool:
    """「继续使用」：把起弹的启动序号推迟 ``launches`` 次并落盘。

    以当前启动计数为基准（``get_launch_count() + launches``），故「第 5 次启动
    点继续使用」后须到第 10 次启动才再弹。旧 app_state.json 缺键 / 非整数
    一律兼容；写盘失败仅返回 False，绝不抛、不阻塞对话框关闭。

    Returns:
        写入成功为 True（绝不抛）。
    """
    state = load_state()
    try:
        step = int(launches)
    except (TypeError, ValueError, OverflowError):
        step = 0
    state[FIELD_SPONSOR_SNOOZE_UNTIL_LAUNCH] = get_launch_count() + step
    return save_state(state)


def should_show_sponsor_reminder() -> bool:
    """是否应弹出赞助致谢框（阈值 5 起弹，且不受「继续使用」节流抑制）。

    停弹条件：用户点过「已支持，不再提醒」（永久），或当前启动序号尚未到达
    ``sponsor_snooze_until_launch``（可节流）。旧状态文件里残留的
    ``sponsor_prompt_shown`` / ``sponsor_acknowledged`` 键一律**不再读取**（自然失效）。
    """
    if is_sponsor_reminder_dismissed():
        return False
    count = get_launch_count()
    if count < SPONSOR_PROMPT_LAUNCH_THRESHOLD:
        return False
    return count >= get_sponsor_snooze_until_launch()


# ---------------------------------------------------------------------------
# UP-2：应用更新检查的开关与每日节流（键名逐字；一律走既有 app_state.json）
# ---------------------------------------------------------------------------

#: 更新检查开关字段名（★ C·2026-11-06：缺键 = 默认关闭，取消首次征询）
FIELD_UPDATE_CHECK_ENABLED = "update_check_enabled"

#: 上次更新检查的本地日期串（``YYYY-MM-DD``）
FIELD_LAST_UPDATE_CHECK_DATE = "last_update_check_date"


def is_update_check_enabled() -> bool:
    """更新检查开关（★ C·2026-11-06：默认关闭，取消首次运行征询）。

    Returns:
        ``True`` / ``False``；键缺失 ⇒ ``False``（默认关闭，绝不抛）。
        不再返回 ``None``——「未决策」态已取消；用户想开就去设置里打开。
    """
    state = load_state()
    if FIELD_UPDATE_CHECK_ENABLED not in state:
        return False
    return bool(state.get(FIELD_UPDATE_CHECK_ENABLED))


def set_update_check_enabled(value: bool) -> bool:
    """持久化更新检查开关。

    Returns:
        写入成功为 ``True``；写盘失败为 ``False``（绝不抛）。
    """
    state = load_state()
    state[FIELD_UPDATE_CHECK_ENABLED] = bool(value)
    return save_state(state)


def get_last_update_check_date() -> str | None:
    """上次检查更新的本地日期串（``YYYY-MM-DD``）；未记录 / 非法 ⇒ ``None``。"""
    value = load_state().get(FIELD_LAST_UPDATE_CHECK_DATE)
    return value if isinstance(value, str) and value else None


def should_run_update_check(now: datetime | None = None) -> bool:
    """是否应执行**自动**更新检查（★ 每日至多一次的实现点）。

    - 开关为 ``False``（含 C·2026-11-06 缺键默认关闭）⇒ 首行短路 ``False``，
      **不写** ``last_update_check_date``、不发请求、不弹框；
    - 开关为 ``True``（用户去设置里打开后）⇒ 走每日节流；
    - 同日已查 ⇒ ``False``；否则落盘今日日期并返回 ``True``；
    - 写盘失败 ⇒ ``False`` 且不写（绝不抛）。★ 手动入口不受本函数约束（见调用侧）。
    """
    if is_update_check_enabled() is False:
        return False
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    if get_last_update_check_date() == today:
        return False
    state = load_state()
    state[FIELD_LAST_UPDATE_CHECK_DATE] = today
    if not save_state(state):
        return False
    return True
