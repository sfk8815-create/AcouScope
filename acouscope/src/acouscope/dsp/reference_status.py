# SPDX-License-Identifier: GPL-3.0-only
"""A4 基准的**来源记录**（T-1006／任务件-20261026 · T-4）。

**为什么另立一档而不改 :mod:`dsp.units`：**
:mod:`acouscope.dsp.units` 是 A4 参考频率的**全局单源**，且已被守卫测试列为禁碰档
（``tests/test_a4_reference.py``／``test_tuning_present_link.py``：改 A4 的调用者
只允许 ``dsp/units.py`` 与 ``ui/main_window.py`` 两档）。三态语义属**元信息**，
不属换算本身，故记在本记录里：``units`` 只管「当前值是多少」，本模块只管
「这个值从哪来」。

三态，**不得混称**：

- ``default-nominal`` —— 平台默认名义基准（无人声明过来源）；
- ``user-set``        —— 由使用者／设置项显式设定；
- ``calibrated``      —— 经参考音实测校准（**须附参考音标识与误差范围**；
  无标识即拒记 —— D 档未到 ⇒ 平台不伪标）。

状态**随声明动作记录**，不由数值反推：值等于 440 既可能是默认，也可能是使用者
设定。若调用方改了全局值而未声明，本记录仍报 ``default-nominal`` —— 这是
**已知且登记的缺口**（见回执 §缺口），不是静默猜值。
"""

from __future__ import annotations

__all__ = [
    "REF_STATUSES",
    "REF_STATUS_CALIBRATED",
    "REF_STATUS_DEFAULT_NOMINAL",
    "REF_STATUS_USER_SET",
    "SYNTHETIC_SOURCE_MARKERS",
    "declare_reference",
    "get_reference_status",
    "reset_reference_status",
]

REF_STATUS_DEFAULT_NOMINAL = "default-nominal"
REF_STATUS_USER_SET = "user-set"
REF_STATUS_CALIBRATED = "calibrated"
REF_STATUSES = (REF_STATUS_DEFAULT_NOMINAL, REF_STATUS_USER_SET, REF_STATUS_CALIBRATED)

_status = REF_STATUS_DEFAULT_NOMINAL
_source = "platform-default"
_detail: dict = {}


def get_reference_status() -> dict:
    """当前 A4 参考频率**及其来源语义**（导出件随件字段，T-4）。

    ``reference_hz`` 恒为 :func:`dsp.units.get_reference_hz` 的**实时值**；
    ``reference_status``／``source``／``detail`` 来自 :func:`declare_reference`
    的最近一次声明，未声明 ⇒ ``default-nominal``（不猜值、不伪造校准）。
    """
    from .units import get_reference_hz

    return {
        "reference_hz": float(get_reference_hz()),
        "reference_status": _status,
        "source": _source,
        "detail": dict(_detail),
    }


#: 合成／链路自检信号的来源标记（小写比对）。``calibrated`` 的 ``source``／``reference_id``
#: 命中任一即拒（2026-11-22 修正：运行 ``1d11038c87927099`` 曾以平台音高发生器所产
#: 440 Hz 正弦声明 ``calibrated``，与 :mod:`analysis.reference_calibration`「不得用合成
#: 信号冒充标定」口径相悖）。合成信号只验链路，应以 ``chain_check`` 随件登记。
SYNTHETIC_SOURCE_MARKERS = (
    "synth", "sine_wave", "sine-wave", "sine wave", "sinewave", "generator",
    "chain_only", "chain-only", "合成", "正弦", "发生器",
)


def _looks_synthetic(*texts: str) -> bool:
    low = " ".join(str(t or "") for t in texts).lower()
    return any(marker in low for marker in SYNTHETIC_SOURCE_MARKERS)


def declare_reference(*, status: str, source: str = "",
                      reference_id: str = "", error_range_cents=None,
                      synthetic: bool = False, chain_check: dict | None = None) -> dict:
    """**声明** A4 基准的来源（调用方义务；平台不猜）。

    ``status`` 取 :data:`REF_STATUSES` 之一；``calibrated`` 须给 ``reference_id``，
    否则抛 ``ValueError`` —— **无参考音标识不得记为 calibrated**。
    ``error_range_cents`` 为二元组 ``(lo, hi)``（音分），缺省 None = 未给误差范围。

    **合成信号不得记 calibrated**（2026-11-22）：``synthetic=True``，或 ``source``／
    ``reference_id`` 命中 :data:`SYNTHETIC_SOURCE_MARKERS`，而 ``status`` 为
    ``calibrated`` ⇒ ``ValueError``。合成信号的链路自检结果以 ``chain_check``（dict，
    原样浅拷贝入 ``detail["chain_check"]``）随 ``default-nominal``／``user-set`` 登记，
    不改变状态语义。

    **本函数不写全局值**：改值仍走 ``dsp.units.set_reference_hz``（单点写入面）；
    本记录只登记「来源」。故调用顺序应为**先设值、后声明**，使实时值与声明同指一物。
    """
    if status not in REF_STATUSES:
        raise ValueError(
            f"未知 reference_status：{status!r}（可用：{list(REF_STATUSES)}）"
        )
    if status == REF_STATUS_CALIBRATED and not str(reference_id or "").strip():
        raise ValueError("calibrated 态须附参考音标识 reference_id（无标识即未校准）")
    if status == REF_STATUS_CALIBRATED and (bool(synthetic) or _looks_synthetic(source, reference_id)):
        raise ValueError(
            "合成信号只验链路，不得记为 calibrated；请以 chain_check 随 "
            "default-nominal／user-set 登记（口径见 analysis.reference_calibration）"
        )
    if chain_check is not None and not isinstance(chain_check, dict):
        raise ValueError("chain_check 须为 dict")
    if chain_check is not None and status == REF_STATUS_CALIBRATED:
        raise ValueError("chain_check 只随 default-nominal／user-set 登记，不与 calibrated 并用")
    global _status, _source, _detail
    detail: dict = {}
    if status == REF_STATUS_CALIBRATED:
        detail["reference_id"] = str(reference_id).strip()
        if error_range_cents is not None:
            try:
                lo, hi = (float(x) for x in error_range_cents)
            except (TypeError, ValueError):
                raise ValueError("error_range_cents 须为 (lo, hi) 二元组") from None
            detail["error_range_cents"] = [lo, hi]
    if chain_check is not None:
        detail["chain_check"] = dict(chain_check)
    _status, _source, _detail = status, str(source or "") or "declared", detail
    return get_reference_status()


def reset_reference_status() -> None:
    """清空来源声明，回到「未声明 ＝ 默认名义基准」。仅供测试／会话重置。"""
    global _status, _source, _detail
    _status = REF_STATUS_DEFAULT_NOMINAL
    _source = "platform-default"
    _detail = {}
