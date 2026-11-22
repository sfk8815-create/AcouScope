# SPDX-License-Identifier: GPL-3.0-only
"""统一时间标尺格式（全模块共用）。

规则（用户规范）：
- t < 1 s        → 毫秒精度小数秒，如 0.125
- 1 s ≤ t < 60 s → 秒（去尾零），如 5、12.5
- t ≥ 60 s       → 60 进制 MM:SS（含毫秒时 MM:SS.mmm），如 01:00、01:08、01:08.25

apply_time_axis(widget) 给 pg.PlotWidget 换装统一时间底轴；
matplotlib 画布用 MatplotlibTimeFormatter。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pyqtgraph as pg


def format_seconds(t: float) -> str:
    """按统一规范格式化秒数。"""
    t = float(t)
    if t < 0:
        t = 0.0
    if t < 60:
        s = f"{t:.3f}".rstrip("0").rstrip(".")
        return s if s else "0"
    minutes = int(t // 60)
    secs = t - minutes * 60
    frac = f"{secs:.3f}".rstrip("0").rstrip(".")
    whole, _, ms = frac.partition(".")
    if ms:
        return f"{minutes:02d}:{int(whole):02d}.{ms}"
    return f"{minutes:02d}:{int(whole):02d}"


def apply_time_axis(widget, min_label_px: float = 22.0) -> None:
    """给 pg.PlotWidget 的底轴换装 Audacity 风格时间刻度。

    刻度位置/密度由 nice_ticks（Audacity Ruler TimeFormat/RealFormat 引擎）
    生成，标签走 format_seconds 统一格式；视图缩放/平移/控件尺寸变化时，
    pyqtgraph 经 sigXRangeChanged/sigResized 回调 linkedViewChanged 自动
    重算，无需外部手动刷新。刻度密度由 axis_fit.best_tickset 按字体度量
    自适应（G4a-3），min_label_px 仅作 best_tickset 不可用时的回退口径
    （默认 22 = Audacity 原默认；90 只作 axis_fit 末档兜底）。

    换轴前迁移旧底轴的 labelText/labelUnits/labelUnitPrefix（G4a-3：调用方
    先 setLabel 再换轴，旧实现未迁移 → 轴标题丢失为 ''；见取证档 §二）。
    旧轴无标签（labelText 与 labelUnits 皆空）则跳过回填。
    """
    plot_item = widget.getPlotItem()
    old = plot_item.axes.get("bottom")
    label_text = label_units = label_prefix = None
    if old is not None:
        old_item = old["item"]
        label_text = getattr(old_item, "labelText", "") or ""
        label_units = getattr(old_item, "labelUnits", "") or ""
        label_prefix = getattr(old_item, "labelUnitPrefix", "") or ""
        plot_item.layout.removeItem(old_item)
        old_item.deleteLater()
        plot_item.axes.pop("bottom", None)
    axis = AudacityTimeAxis(orientation="bottom", min_label_px=min_label_px)
    plot_item.setAxisItems({"bottom": axis})
    # G1：本类用 setTicks 提供 format_seconds 秒值字符串，pyqtgraph 不缩放
    # 刻度文字；AxisItem 默认 autoSIPrefix=True 会在 0–0.5 s 量级把 units
    # 前缀自动加 m → 标题变「时间 (ms)」而刻度仍为秒值（差 1000 倍）。
    # 换轴后禁用自动 SI 前缀，使标题恒为「时间 (s)」。
    axis.enableAutoSIPrefix(False)
    if label_text or label_units:
        # 迁移旧轴标签（G4a-3 A3）；labelStyle 由各视图 _apply_canvas_theme 重设
        axis.setLabel(label_text, units=label_units, unitPrefix=label_prefix)
    axis.refresh_ticks()


@dataclass(frozen=True)
class TickSet:
    """nice_ticks 输出（零 Qt 依赖，纯数据）。

    Attributes:
        majors: 主刻度位置列表（秒，升序）。
        minors: 次刻度位置列表（秒，升序）。
        major_step: 主刻度步长（秒）。
        minor_step: 次刻度步长（秒）；major_step 必为 minor_step 的整数倍。
        digits: 子秒标签小数位数（minor_step < 1.0 时 >0；≥1.0 时为 0）。
    """
    majors: list
    minors: list
    major_step: float
    minor_step: float
    digits: int


def _time_tick_sizes(units: float) -> tuple[float, float, int]:
    """Audacity TimeFormat::SetTickSizes 的 Python 移植（TimeFormat.cpp:21-102）。

    - units > 0.5：硬编码时间表（5s/15s/30s/1min/5min/15min/30min/1h/6h/1d/1w）
    - units <= 0.5：fallthrough 到 RealFormat::SetTickSizes 的 {1,2,5}×10ⁿ 子秒引擎

    Args:
        units: 最小可接受 minor 间距（秒）= min_label_px * (t1-t0)/pixel_width。

    Returns:
        (minor_step, major_step, digits)。
        digits 仅在 minor_step < 1.0 时用于 format_seconds 的小数位。
    """
    if units > 0.5:
        # 硬编码时间表（移植自 TimeFormat.cpp:25-95）
        if units < 1.0:
            return (1.0, 5.0, 0)
        if units < 5.0:
            return (5.0, 15.0, 0)
        if units < 10.0:
            return (10.0, 30.0, 0)
        if units < 15.0:
            return (15.0, 60.0, 0)
        if units < 30.0:
            return (30.0, 60.0, 0)
        if units < 60.0:
            return (60.0, 300.0, 0)
        if units < 300.0:
            return (300.0, 900.0, 0)
        if units < 600.0:
            return (600.0, 1800.0, 0)
        if units < 900.0:
            return (900.0, 3600.0, 0)
        if units < 1800.0:
            return (1800.0, 3600.0, 0)
        if units < 3600.0:
            return (3600.0, 6 * 3600.0, 0)
        if units < 6 * 3600.0:
            return (6 * 3600.0, 24 * 3600.0, 0)
        if units < 24 * 3600.0:
            return (24 * 3600.0, 7 * 24 * 3600.0, 0)
        week = 24.0 * 7.0 * 3600.0
        return (week, week, 0)

    # units <= 0.5：{1,2,5}×10ⁿ 子秒引擎（移植自 RealFormat.cpp:26-58）
    d = 0.000001  # 1e-6
    digits = 6
    while True:
        if units < d:
            return (d, d * 5.0, digits)
        d *= 5.0
        if units < d:
            return (d, d * 2.0, digits)
        d *= 2.0
        digits -= 1
        if digits < -10:
            return (d, d * 2.0, digits)


def nice_ticks(t0: float, t1: float, pixel_width: float, min_label_px: float = 90.0) -> TickSet:
    """Audacity 风格时间刻度生成（零 Qt 依赖，纯函数可单测）。

    对标 Audacity au3/src/widgets/Ruler + LinearUpdater + TimeFormat/RealFormat：
    - UPP = (t1 - t0) / pixel_width（每像素秒数）
    - units = min_label_px * UPP（最小可接受 minor 间距，秒）
    - _time_tick_sizes(units) 得 (minor_step, major_step, digits)
    - 主/次刻度位置：在 [t0, t1] 内对 step 取整对齐的整数倍位置

    Args:
        t0, t1: 时间范围（秒，要求 t0 < t1）。
        pixel_width: 标尺像素宽度（>0）。
        min_label_px: 相邻 minor 刻度最小像素间距（Audacity 默认 22；
                      中文标签 + 单位需更大，默认 90）。

    Returns:
        TickSet(majors, minors, major_step, minor_step, digits)。
        输入非法（t0>=t1 或 pixel_width<=0）时返回空刻度集。
    """
    if t0 >= t1 or pixel_width <= 0:
        return TickSet([], [], 0.0, 0.0, 0)
    upp = (t1 - t0) / float(pixel_width)
    units = float(min_label_px) * upp
    minor_step, major_step, digits = _time_tick_sizes(units)
    if minor_step <= 0 or major_step <= 0:
        return TickSet([], [], 0.0, 0.0, digits)

    def _grid(step: float) -> list[float]:
        # 第一个 >= t0 的 step 整数倍位置（避免 -0）
        start = math.ceil(t0 / step) * step
        out: list[float] = []
        k = 0
        # 步进用整数倍累加，避免浮点漂移；末点用 step*1e-9 容差
        while True:
            v = start + k * step
            if v > t1 + step * 1e-9:
                break
            out.append(v)
            k += 1
        return out

    minors = _grid(minor_step)
    majors = _grid(major_step)
    return TickSet(majors, minors, major_step, minor_step, digits)


def _tickset_to_pgticks(ts: TickSet) -> list:
    """把 TickSet 转为 pyqtgraph AxisItem.setTicks 的两级刻度格式。

    返回 [[(major_pos, label_str), ...], [(minor_pos, None), ...]]：
    主刻度带 format_seconds 文字标签；次刻度标签为 None（pyqtgraph 对 None
    标签只画刻度线、跳过文字）；与主刻度位置重合的次刻度剔除，避免重复画线。
    """
    majors = [(float(v), format_seconds(float(v))) for v in ts.majors]
    minors = []
    for v in ts.minors:
        fv = float(v)
        coincident = any(
            abs(fv - float(m))
            <= 1e-9 * max(1.0, abs(fv), abs(float(m)), ts.minor_step)
            for m in ts.majors
        )
        if not coincident:
            minors.append((fv, None))
    return [majors, minors]


class AudacityTimeAxis(pg.AxisItem):
    """底轴：刻度由 nice_ticks 生成（Audacity 风格），随视图变化自动重算。

    pyqtgraph 的 linkToView 已把 ViewBox.sigXRangeChanged/sigResized 连到
    linkedViewChanged；覆写该方法即可在缩放/平移/尺寸变化时重算 setTicks，
    无需外部再手动连接信号。
    """

    def __init__(self, *args, min_label_px: float = 22.0, **kwargs):
        super().__init__(*args, **kwargs)
        self._min_label_px = float(min_label_px)
        self._last_tickset = None  # 最近一次刻度结果（供诊断/测试检视）

    def linkedViewChanged(self, view, newRange=None):
        super().linkedViewChanged(view, newRange)
        self.refresh_ticks()

    def refresh_ticks(self) -> None:
        """按当前 ViewBox 可见范围与轴像素宽度重算刻度并 setTicks。

        密度由 axis_fit.best_tickset 按本轴 QFontMetrics 实测标签宽自适应
        （G4a-3）；fm 不可用时回退 nice_ticks(self._min_label_px)。
        """
        view = self.linkedView()
        if view is None:
            return
        x0, x1 = view.viewRange()[0]
        x0 = max(0.0, float(x0))  # 时间语义非负：空态/屏幕外元素不应引入负刻度
        pixel_width = float(self.geometry().width())
        if pixel_width <= 1.0:
            # 轴尚未完成布局（首次挂载）时退用 ViewBox 宽度
            pixel_width = float(view.geometry().width())
        if pixel_width <= 1.0:
            pixel_width = 900.0  # 保守默认；布局完成后 sigResized 会立即重算
        from acouscope.ui.widgets.axis_fit import best_tickset  # 惰性：避免环导入

        try:
            from PyQt6.QtGui import QFontMetrics

            fm = QFontMetrics(self.font())
            ts = best_tickset(float(x0), float(x1), pixel_width, fm, format_seconds)
        except Exception:
            # 字体度量不可用（无 QGuiApplication 等）→ 旧口径回退
            ts = nice_ticks(float(x0), float(x1), pixel_width, self._min_label_px)
        self._last_tickset = ts
        self.setTicks(_tickset_to_pgticks(ts))


_NICE_TICKS_LOCATOR_CLS = None


def _get_nice_ticks_locator_cls():
    """惰性构建（仅 3D matplotlib 场景触发；消除启动期 matplotlib 导入）。"""
    global _NICE_TICKS_LOCATOR_CLS
    if _NICE_TICKS_LOCATOR_CLS is None:
        from matplotlib.ticker import Locator as _MplLocator

        class _NiceTicksLocator(_MplLocator):
            """matplotlib Locator：刻度位置由 nice_ticks（Audacity 风格）生成。

            用于 3D 频谱图 matplotlib 时间轴；与 MatplotlibTimeFormatter 配合
            （Formatter 负责标签文本，Locator 负责刻度位置）。minor=True 时
            返回次刻度位置，否则返回主刻度位置。

            实现：__call__ 取 self.axis.get_view_interval() 得 (vmin,vmax)，
            调 tick_values → _get_pixel_width 从 axes.bbox 取像素宽 → nice_ticks
            生成 TickSet → 返回 majors 或 minors。
            """

            def __init__(self, min_label_px: float = 90.0, minor: bool = False):
                super().__init__()
                self._min_label_px = float(min_label_px)
                self._minor = bool(minor)

            def __call__(self):
                vmin, vmax = self.axis.get_view_interval()
                return self.tick_values(vmin, vmax)

            def tick_values(self, vmin, vmax):
                vmin, vmax = float(vmin), float(vmax)
                if vmin > vmax:
                    # 反转区间（如瀑布图 set_ylim(t1, t0)）：swap 归一化后喂 nice_ticks，
                    # 否则 span 为负返回空 TickSet → 3D 瀑布模式时间轴无刻度
                    vmin, vmax = vmax, vmin
                pixel_width = self._get_pixel_width()
                ts = nice_ticks(vmin, vmax, pixel_width, self._min_label_px)
                return self.raise_if_exceeds(ts.minors if self._minor else ts.majors)

            def _get_pixel_width(self) -> float:
                """从关联 axes 的 bbox 取像素宽度，不可用时退 900。"""
                try:
                    ax = self.axis.axes
                    if ax is not None:
                        w = float(ax.bbox.width)
                        if w > 1.0:
                            return w
                except Exception:
                    pass
                return 900.0


        _NICE_TICKS_LOCATOR_CLS = _NiceTicksLocator
    return _NICE_TICKS_LOCATOR_CLS


def __getattr__(name):
    if name == "NiceTicksLocator":
        return _get_nice_ticks_locator_cls()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class MatplotlibTimeFormatter:
    """matplotlib FuncFormatter 兼容对象（3D 频谱图时间轴用）。"""

    def __call__(self, value, _pos=None) -> str:
        return format_seconds(value)
