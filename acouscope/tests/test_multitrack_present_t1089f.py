# SPDX-License-Identifier: GPL-3.0-only
"""T-1089 N-F：密度热图的量纲与色标（改前 peak 归一 + 无色标）。

根因（PI-T81 DIM2 2.5）：``_heatmap_image`` 按**逐图 peak** 归一 ⇒ 同一个深浅在不同轨数
/不同视窗下含义不同，5 轨×3s 素材 peak=2 时全图只剩 ``0/128/255`` 三档；且**色标构件根本
不存在**（探针[13b]），读者无从把深浅折成帧数。

处置：

- 归一分母换成**全轨共享**的稳健参考计数（非零格 p95·:data:`HEATMAP_SCALE_PERCENTILE`），
  并走 ``log1p`` 档 ⇒ 稀疏密度下 1 帧/格 也看得见，多图分离各面板同一映射可横向比色；
- 借 SV ``LinearColourScale::paintVertical`` 加竖向色标（逐行取色 + 由步长定小数位），
  旁注**绝对帧数/格**与单位文案；
- ★ T-1087 M8 的守卫语义逐字保留（``test_multitrack_heatmap_t1087.py`` 仅同步换等值标尺）：
  仍是向量化实现与双循环参考实现的**逐像素等值**，零逐像素 Python 循环、零 ``setPixelColor``。

色带档位数观感与位置是否抢戏归 N5。
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QColor

from acouscope.i18n import set_language, tr
from acouscope.ui import theme
from acouscope.ui.widgets.multitrack import compare_diff
from acouscope.ui.widgets.multitrack.analysis_source import TrackResultCache
from acouscope.ui.widgets.multitrack.compare_present import (
    HEATMAP_COLORBAR_TICKS, HEATMAP_FREQ_BINS, HEATMAP_SCALE_PERCENTILE,
    HEATMAP_TIME_BINS, ComparePresentWidget, TrackSeries, build_density_heatmap,
)
from acouscope.ui.widgets.multitrack.track_model import MultitrackSession

_ROWS = HEATMAP_FREQ_BINS
_COLS = HEATMAP_TIME_BINS
_SR = 8000


def _series(count=6, points=3000, *, dense=True):
    """密素材（正弦 F0·每格多帧）⇒ 深浅必须分档；``dense=False`` 给稀疏对照。"""
    out = []
    for index in range(count):
        times = np.linspace(0.0, 3.0, points)
        span = 180.0 if dense else 1500.0
        f0 = 140.0 + index * 55.0 + span * np.sin(times * (index + 1) * (0.5 if dense else 2.0))
        out.append(TrackSeries(
            track_id=f"f{index}", label=f"track{index}", color_index=index,
            times=times, f0_hz=np.abs(f0) + 60.0, is_reference=(index == 0),
        ))
    return out


def _bare_widget(series_list, *, view=(0.0, 3.0)):
    widget = ComparePresentWidget(None, None)
    widget.resize(720, 420)
    widget._series = list(series_list)
    widget._view_range = view
    widget._freq_range = None
    return widget


def _alphas(image):
    return {(image.pixel(x, y) >> 24) & 0xFF
            for y in range(image.height()) for x in range(image.width())}


# ---------------------------------------------------------------------------
# ① 归一口径：绝对参考计数（非 peak）·非三档·可达饱和
# ---------------------------------------------------------------------------


def test_reference_is_p95_of_nonzero_bins_computed_independently(qapp):
    series = _series(6)
    widget = _bare_widget(series)
    lo, hi = widget.freq_range()
    density = build_density_heatmap(series, widget._view_range, fmin=lo, fmax=hi)
    nonzero = density[density > 0]
    expected = float(np.percentile(nonzero, HEATMAP_SCALE_PERCENTILE))
    assert widget._heatmap_reference() == pytest.approx(expected)
    assert expected >= 3.0, "密素材下参考计数应明显大于 1（peak 三档陷阱的前提）"


def test_alpha_levels_are_many_and_reach_full_scale(qapp):
    series = _series(6)
    widget = _bare_widget(series)
    image = widget._heatmap_image(series, widget._plot_rect())
    assert image is not None
    alphas = _alphas(image)
    assert 0 in alphas and 255 in alphas                  # 空格与饱和格都在
    assert len(alphas) > 8, len(alphas)                    # ★ 不再是 0/128/255 三档


def test_normalization_differs_from_legacy_peak_and_matches_log_scale(qapp):
    """反证 + 正照：同一素材下 peak 归一与现口径必不等；与 log1p/参考值口径逐像素等值。"""
    series = _series(6)
    widget = _bare_widget(series)
    produced = widget._heatmap_image(series, widget._plot_rect())
    lo, hi = widget.freq_range()
    density = build_density_heatmap(series, widget._view_range, fmin=lo, fmax=hi)
    reference = widget._heatmap_reference()

    peak_norm = density / float(density.max())
    legacy_alphas = set(np.unique(np.rint(255.0 * peak_norm[::-1, :]).astype(int)))
    assert legacy_alphas != {int(a) for a in _alphas(produced)}   # ★ 改前口径已换掉

    expect = np.clip(np.log1p(density) / np.log1p(reference), 0.0, 1.0)
    expected_alphas = set(np.unique(np.rint(255.0 * expect[::-1, :]).astype(int)))
    assert expected_alphas == {int(a) for a in _alphas(produced)}  # 复刻口径 == 生产


def test_panels_share_one_reference_in_grid_mode(qapp):
    """各面板必须共用**全轨**参考 ⇒ 多图分离下深浅可比（逐图自归一正是旧缺陷）。"""
    dense, sparse = _series(1, points=6000)[0], _series(1, points=200, dense=False)[0]
    widget = _bare_widget([dense, sparse])
    global_reference = widget._heatmap_reference()
    own_reference = widget._heatmap_reference([sparse])
    assert own_reference < global_reference                 # 疏轨自归一会把它整片刷亮
    rect = widget._plot_rect()
    shared = widget._heatmap_image([sparse], rect, reference=global_reference)
    default = widget._heatmap_image([sparse], rect)
    selfish = widget._heatmap_image([sparse], rect, reference=own_reference)
    assert _alphas(default) == _alphas(shared)             # 缺省即全轨参考（面板同源）
    assert max(_alphas(selfish)) > max(_alphas(shared))    # ★ 自归一 ⇒ 更亮（不可比）


def test_empty_window_still_yields_no_image(qapp):
    """保留既有空态语义：视窗内无帧 ⇒ None（不画空色标）。"""
    widget = _bare_widget(_series(2), view=(99.0, 100.0))
    assert widget._heatmap_image(widget._series, widget._plot_rect()) is None
    assert widget._heatmap_reference() == 0.0


# ---------------------------------------------------------------------------
# ② 色标：存在 + 绝对计数刻度 + 单位文案
# ---------------------------------------------------------------------------


def test_colorbar_ticks_are_absolute_counts_top_down(qapp):
    ticks = ComparePresentWidget._colorbar_ticks(12.0)
    assert len(ticks) == HEATMAP_COLORBAR_TICKS + 1
    assert ticks[0][0] == pytest.approx(12.0) and ticks[-1][0] == pytest.approx(0.0)
    assert [text for _v, text in ticks] == ["12", "10", "7", "5", "2", "0"]
    assert ComparePresentWidget._colorbar_ticks(2.0)[1][1] == "1.60"  # 步长 <1 ⇒ 升小数位


def test_small_reference_keeps_decimals(qapp):
    ticks = ComparePresentWidget._colorbar_ticks(0.2)
    assert all("." in text for _v, text in ticks)          # 亚 1 步长 ⇒ 补足小数位
    assert ticks[-1][1] == "0.000"


def test_colorbar_is_painted_only_with_heatmap(qapp):
    session = MultitrackSession(
        metadata_reader=lambda p: {"sample_rate": _SR, "channels": 1, "duration": 3.0},
        envelope_reader=lambda p, points: (
            np.linspace(0.0, 3.0, points), np.full(points, 0.5, dtype=np.float32)),
        loader=lambda p: (np.linspace(-0.3, 0.3, int(_SR * 3.0)), _SR),
    )
    for index in range(4):
        session.add_path(f"/tmp/t1089f{index}.wav", label=f"f{index}")
    cache = TrackResultCache()
    series = _series(4)
    for track, item in zip(session.tracks(), series):
        cache.put(TrackResultCache.key(track.track_id, "pitch", None), item)
    widget = ComparePresentWidget(session, cache)
    widget.resize(720, 420)
    set_language("zh_CN")
    widget.refresh()
    widget.set_view_range(0.0, 3.0)

    widget.set_heatmap(False)
    widget.grab()
    assert widget.paint_stats()["heatmap"] is False
    assert widget.paint_stats()["colorbar"] is False       # ★ 关热图即无色标（不占位）

    widget.set_heatmap(True)
    widget.grab()
    stats = widget.paint_stats()
    assert stats["heatmap"] is True and stats["colorbar"] is True
    data = widget._data_rect()
    tint = QColor(theme.data_ink("tint")).rgb()
    image = widget.grab().toImage()
    ratio_x = image.width() / max(1, widget.width())
    ratio_y = image.height() / max(1, widget.height())
    box = QRectF(data.right() - 150.0, data.top() + 24.0, 148.0, 70.0)
    hits = 0
    for y in range(int(box.top() * ratio_y), int(box.bottom() * ratio_y) + 1):
        for x in range(int(box.left() * ratio_x), int(box.right() * ratio_x) + 1):
            hits += int(image.pixel(x, y) == tint)
    assert hits > 50                                       # 色标底衬成片落笔


def test_colorbar_unit_text_key_in_three_languages(qapp):
    for lang in ("en_US", "zh_CN", "zh_TW"):
        set_language(lang)
        assert tr("multitrack.compare.heatmap_colorbar_unit") != \
            "multitrack.compare.heatmap_colorbar_unit"
    set_language("zh_CN")


# ---------------------------------------------------------------------------
# ③ 边界：量化层零碰（色标只是呈现层映射·不改任何计数）
# ---------------------------------------------------------------------------


def test_density_counts_are_untouched_by_the_new_scale(qapp):
    """新口径只改 alpha 映射：直方图计数与阈值/CSV 量化面逐字无关。"""
    series = _series(4)
    widget = _bare_widget(series)
    lo, hi = widget.freq_range()
    density = build_density_heatmap(series, widget._view_range, fmin=lo, fmax=hi)
    t0, t1 = widget._view_range
    expected = 0
    for item in series:
        in_view = np.asarray(item.times, dtype=float)[item.voiced()]
        expected += int(np.count_nonzero((in_view >= t0) & (in_view <= t1)))
    assert float(density.sum()) == pytest.approx(expected)   # 计数一字未动
    assert density.shape == (_ROWS, _COLS)                 # M8 网格不变
    assert compare_diff.DEFAULT_THRESHOLD_CENTS == 50.0    # 量化层默认零碰
