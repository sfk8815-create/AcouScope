# SPDX-License-Identifier: GPL-3.0-only
"""T-1087 M8：密度热图绘制层向量化（逐像素等值 + 复杂度守卫）+ freq_range 去 N² 重扫。

改前：``_heatmap_image`` = 固定 96×240 ≈ **23k 像素/面板/帧**的纯 Python 双循环
``setPixelColor``（MODE_GRID 下按轨数翻倍，绘制期直接掉帧）；``freq_range`` 又由每条
曲线的 ``curve_points`` 各调一次 ⇒ 每帧对全部轨数组 N² 遍 min/max 重扫。
本件**不进任务中心**（绘制层即时性 ⇒ 后台化会给不出当帧图像）。

守卫：
① 正照：新实现逐像素 == 旧双循环参考实现（含"低频在下"的行序、半偶舍入）；
   ★ 归一口径由 T-1089 N-F 由 peak 改为全轨非零格 p95（本档随改·M8 等值语义不削）；
② 对照：把行序翻转/alpha 取整口径改坏 ⇒ 必须与生产结果不等（证明①有判别力）；
③ 复杂度：``_heatmap_image`` 内 Python 行事件计数 ≪ 像素数（无逐像素循环）+
   源码不再出现 ``setPixelColor``；
④ freq_range：一帧内多曲线共用一次扫描（``np.min`` 调用数 == 1）。
"""

import ast
import inspect
import sys
import textwrap

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtGui import QColor, QImage

from acouscope.i18n import set_language
from acouscope.ui import theme
from acouscope.ui.widgets.multitrack.compare_present import (
    HEATMAP_FREQ_BINS, HEATMAP_TIME_BINS, ComparePresentWidget, TrackSeries,
    build_density_heatmap,
)

_ROWS = HEATMAP_FREQ_BINS
_COLS = HEATMAP_TIME_BINS


def _series(count=4, points=400):
    out = []
    for index in range(count):
        times = np.linspace(0.0, 2.0, points)
        f0 = 120.0 + index * 90.0 + 30.0 * np.sin(times * (index + 1))
        out.append(TrackSeries(
            track_id=f"t{index}", label=f"track{index}", color_index=index,
            times=times, f0_hz=f0, is_reference=(index == 0),
        ))
    return out


def _widget(qapp, series_list):
    set_language("zh_CN")
    widget = ComparePresentWidget(None, None)
    widget.resize(640, 360)
    widget._series = list(series_list)
    widget._view_range = (0.0, 2.0)
    widget._freq_range = None
    return widget


def _scale_of(widget, series_list=None):
    """N-F 归一分母的**独立复刻**（非零格 p95·绝对计数参考）。

    ★ T-1089 N-F 授权改的就是这一处等值口径：归一分母由逐图 ``peak`` 换成全轨共享的
    稳健参考值。M8 的守卫语义**逐字保留**——仍是「双循环 setPixelColor vs 向量化」的
    逐像素等值（含低频在下的行序与半偶舍入），且例②的两个负对照照旧必红。
    """
    lo, hi = ComparePresentWidget.freq_range(widget)
    source = widget._series if series_list is None else series_list
    density = build_density_heatmap(source, widget._view_range, fmin=lo, fmax=hi)
    nonzero = density[density > 0]
    return float(np.percentile(nonzero, 95.0)) if nonzero.size else 0.0


def _reference_image(widget, series_list):
    """旧实现的逐字复刻（双循环 setPixelColor）——本件的等价性标尺。"""
    lo, hi = ComparePresentWidget.freq_range(widget)
    density = build_density_heatmap(series_list, widget._view_range, fmin=lo, fmax=hi)
    scale = _scale_of(widget)
    assert scale > 0.0
    norm = np.clip(np.log1p(density) / np.log1p(scale), 0.0, 1.0)
    base = QColor(theme.colors()["accent"])
    rows, cols = norm.shape
    image = QImage(int(cols), int(rows), QImage.Format.Format_ARGB32)
    for row in range(int(rows)):
        source = norm[int(rows) - 1 - row]              # 低频在下
        for col in range(int(cols)):
            alpha = int(round(255.0 * float(source[col])))
            image.setPixelColor(
                col, row, QColor(base.red(), base.green(), base.blue(), alpha)
            )
    return image


def _pixels(image):
    return [
        image.pixelColor(col, row).rgba()
        for row in range(image.height())
        for col in range(image.width())
    ]


# ---------------------------------------------------------------------------
# ① 正照：逐像素等值
# ---------------------------------------------------------------------------


def test_vectorized_heatmap_is_pixel_exact_vs_legacy_loop(qapp):
    series = _series(4)
    widget = _widget(qapp, series)
    image = widget._heatmap_image(series, widget._plot_rect())
    reference = _reference_image(widget, series)

    assert image is not None
    assert (image.width(), image.height()) == (_COLS, _ROWS)
    assert image.format() == QImage.Format.Format_ARGB32
    assert _pixels(image) == _pixels(reference)          # ★ 逐像素等值（非抽样）
    opaque = [p for p in _pixels(image) if ((p >> 24) & 0xFF) > 0]
    assert 0 < len(opaque) < _ROWS * _COLS               # 确有密度、且非满幅
    alphas = {(pixel >> 24) & 0xFF for pixel in _pixels(image)}
    assert 0 in alphas and 255 in alphas                 # 达参考计数即饱和（色标可读）
    assert alphas != {0, 128, 255}                       # ★ 旧 peak 三档口径已换掉


def test_empty_density_still_returns_none(qapp):
    series = _series(1)
    widget = _widget(qapp, series)
    widget._view_range = (9.0, 10.0)                     # 窗口内无数据 → peak 0
    widget._freq_range = None
    assert widget._heatmap_image(series, widget._plot_rect()) is None


# ---------------------------------------------------------------------------
# ② 对照：故意改坏行序 / 取整 ⇒ 必与生产结果不等（证明①不是恒等式）
# ---------------------------------------------------------------------------


def test_wrong_row_order_and_truncation_would_be_caught(qapp):
    series = _series(4)
    widget = _widget(qapp, series)
    produced = _pixels(widget._heatmap_image(series, widget._plot_rect()))

    density = build_density_heatmap(
        series, widget._view_range, fmin=widget.freq_range()[0], fmax=widget.freq_range()[1]
    )
    norm = np.clip(np.log1p(density) / np.log1p(_scale_of(widget)), 0.0, 1.0)
    base = QColor(theme.colors()["accent"])
    rows, cols = norm.shape

    def build(flip: bool, floor_instead_of_round: bool):
        image = QImage(cols, rows, QImage.Format.Format_ARGB32)
        for row in range(rows):
            source = norm[rows - 1 - row] if flip else norm[row]
            for col in range(cols):
                raw = 255.0 * float(source[col])
                alpha = int(raw) if floor_instead_of_round else int(round(raw))
                image.setPixelColor(
                    col, row, QColor(base.red(), base.green(), base.blue(), alpha)
                )
        return _pixels(image)

    assert build(True, False) == produced               # 复刻口径 == 生产（正向自证）
    assert build(False, False) != produced              # 行序不翻 → 上下镜像 → 必红
    assert build(True, True) != produced                # 截断代替半偶舍入 → 必红


# ---------------------------------------------------------------------------
# ③ 复杂度守卫：绘制期不再有逐像素 Python 循环
# ---------------------------------------------------------------------------


def _count_line_events(fn, *args, **kwargs):
    hits = [0]
    name = fn.__name__

    def tracer(frame, event, _arg):
        if event == "line" and frame.f_code.co_name == name:
            hits[0] += 1
        return tracer

    previous = sys.gettrace()
    sys.settrace(tracer)
    try:
        out = fn(*args, **kwargs)
    finally:
        sys.settrace(previous)
    return hits[0], out


def test_heatmap_has_no_per_pixel_python_loop(qapp):
    series = _series(4)
    widget = _widget(qapp, series)
    lines, image = _count_line_events(
        ComparePresentWidget._heatmap_image, widget, series, widget._plot_rect()
    )
    assert image is not None
    pixels = _ROWS * _COLS
    assert lines * 50 < pixels, f"仍有逐像素级 Python 循环痕迹：lines={lines}"
    tree = ast.parse(textwrap.dedent(
        inspect.getsource(ComparePresentWidget._heatmap_image)
    ))
    assert [n for n in ast.walk(tree) if isinstance(n, ast.For)] == []   # 零循环体
    called = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "setPixelColor" not in called


# ---------------------------------------------------------------------------
# ④ freq_range 缓存：一帧内多曲线只扫一次
# ---------------------------------------------------------------------------


def test_freq_range_is_scanned_once_per_series_generation(qapp, monkeypatch):
    series = _series(6)
    widget = _widget(qapp, series)
    calls = []
    real_min = np.min

    def spy_min(values, *args, **kwargs):
        calls.append(len(values))
        return real_min(values, *args, **kwargs)

    monkeypatch.setattr(np, "min", spy_min)
    first = widget.freq_range()
    scanned = len(calls)                                 # 首调：每条序列一次 min
    assert scanned == len(series)
    second = widget.freq_range()
    assert first == second
    assert len(calls) == scanned                         # 命中缓存 ⇒ 零重扫

    for item in series:                                  # 模拟一帧内逐条曲线取点
        widget.curve_points(item)
    assert len(calls) == scanned                         # ★ N 条曲线不再 N 次重扫

    widget._series = _series(6, points=400)              # 换代必须作废缓存
    widget._freq_range = None
    widget.freq_range()
    assert len(calls) > 2


def test_refresh_invalidates_freq_range_cache(qapp):
    series = _series(3)
    widget = _widget(qapp, series)
    assert widget._freq_range is None
    widget.freq_range()
    assert widget._freq_range is not None
    widget.refresh()                                     # 轨集/结果变化 → 缓存作废
    assert widget._freq_range is None
