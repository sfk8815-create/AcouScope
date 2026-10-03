# SPDX-License-Identifier: GPL-3.0-only
"""T-1042c 钢琴键面 v3 —— **像素级合成判据**（判据 a~g，竖/横各一套）。

真源：`内部记录/tasks/T-1042c.txt` §三-3.1（判据表 a~g）+ `ARCH_ui_visual_language.md §五c v1.6`
（**§3-ter 键床连续** · **§3-quater 像素级合成判据**）。

★ 本文件的存在理由（**教训 AR**）：属性级探针（brush/pen/zValue/元素计数/可见性）**不能替代
观感级验收** —— T-1042b 全部属性达标而观感被否决，且「切钢琴卷帘后键面一个像素都没画出来」
长期隐身（左轴自然宽 65px ≥ 条宽 62px → ViewBox 塌缩成 8px）。
故本文件一律 **离屏渲染 → 扫像素**，判据 g 直接正面证明「键面真被画出来了」。

口径（写死，可复核；均落在本文件内，不依赖外部快照）：
- 键面物理色：白 `keys.white` / 黑 `keys.black` / 缝 `keys.white_seam` / 音名 `keys.label`
  —— 唯一取色入口 `theme.key_faces()`；背景色 = 键带底画布色 `theme.colors()["bg2"]`。
- **键床中线**：竖排 = 键床列范围中点列（自上而下扫）；横排 = 键床行范围中点行（自左向右扫）。
  该线落在黑键深度之外（黑键 0.46 < 0.5），故线上只应出现键床白底 + 细缝 + 键床内音名文字。
- 键床内音名文字（§2.1-②）像素单列 `label` 类，**不计入**「背景色段」与「缝段」；
  判据 a/d 先取最近色分类，再只统计 `bg` / 缝外偏差段。
- 判据 c 是**紧区间**（0.54–0.58）：半音仅 13px 时 0.55 半音 = 7.32px，量化误差就 ≥0.03。
  故 c 在**判据基准缩放**下测（竖排 4 半音/620px ≈ 154.8px/半音；横排 10 半音/1425px ≈ 142.5px/半音），
  其余判据在自然缩放（竖排 48–84；横排 ≈25–108）下测。两档实测数字均进报告。
- 全离屏；**不构造主窗口、不 show 主窗体**。仅判据 f 用 `WA_DontShowOnScreen` + `show()`
  取 `isVisible()` 真值（否则离屏无窗口时 Qt 恒返回 False，无法正面证明）。
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from acouscope.ui import theme  # noqa: E402

_REPO = pathlib.Path(__file__).resolve().parents[2]
_EVID = pathlib.Path("/tmp/t1042c_evidence")
_REF_KEYFACE = _REPO / "内部记录/knowledge/assets/T-1042b_reference_keyface.png"
_BAD_HORIZONTAL = _REPO / "内部记录/knowledge/assets/T-1042c_now_horizontal_BAD.png"

_ROLES = ("white", "black", "white_seam", "label")
_BG_RUN_MAX = 2          # 判据 a（背景色像素段）/ d（缝宽）
_COVER_MIN = 0.95        # 判据 e
_RATIO_LEN = (0.45, 0.50)    # 判据 c：黑键长/键床宽（竖）· 黑键厚/键床高（横）
_RATIO_SEMI = (0.54, 0.58)   # 判据 c：黑键半音向/半音高
_VIEWBOX_MIN = 30        # §2.1 判据：ViewBox 实测宽 ≥ 30px

# 判据基准缩放（见模块 docstring「口径」）
_ZOOM_V_MEASURE = (60.0, 64.0)      # 竖排 4 半音
_ZOOM_H_MEASURE = (55.0, 65.0)      # 横排 10 半音
_RANGE_V_NATURAL = (48.0, 84.0)     # 竖排自然缩放（36 半音）
_RANGE_H_NATURAL = (20.5, 108.5)    # 横排自然缩放（钢琴卷帘 = 88 键固定区间）


# ----------------------------------------------------------------------
# 一、像素工具（无第三方依赖：QImage → numpy(RGB) → 分类/掩码）
# ----------------------------------------------------------------------

def _hex_rgb(hexcolor: str) -> np.ndarray:
    s = hexcolor.lstrip("#")
    return np.array([int(s[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.int16)


def _rgb_array(img: QImage) -> np.ndarray:
    """QImage → (h, w, 3) uint8 RGB 数组。"""
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    h, w = img.height(), img.width()
    bpl = img.bytesPerLine()
    buf = img.constBits()
    buf.setsize(bpl * h)
    arr = np.frombuffer(buf, dtype=np.uint8).reshape(h, bpl // 4, 4)
    return np.ascontiguousarray(arr[:, :w, 2::-1])


def _bg_hex() -> str:
    return theme.colors()["bg2"]


def _anchor_cols() -> np.ndarray:
    return np.stack([_hex_rgb(theme.key_face(r)) for r in _ROLES]
                    + [_hex_rgb(_bg_hex())])


def _classify(arr: np.ndarray):
    """最近色分类 → (类别索引图, 类别名列表)。类别 = 4 键面色 + bg。"""
    cols = _anchor_cols()
    d = np.abs(arr.astype(np.int16)[:, :, None, :] - cols[None, None, :, :]).sum(axis=3)
    return np.argmin(d, axis=2), list(_ROLES) + ["bg"]


def _mask(arr: np.ndarray, role: str) -> np.ndarray:
    """键面角色色值的**精确**掩码（用于几何量测，避免混叠像素污染）。"""
    return np.all(arr == _hex_rgb(theme.key_face(role)), axis=2)


def _bed_extent(white_m: np.ndarray, black_m: np.ndarray):
    """键床范围：任一键面像素出现的列/行范围（含首尾）。"""
    both = white_m | black_m
    cols = np.where(both.any(axis=0))[0]
    rows = np.where(both.any(axis=1))[0]
    return int(cols.min()), int(cols.max()), int(rows.min()), int(rows.max())


def _runs(flags: np.ndarray):
    """一维布尔序列 → [(值, 段长), ...]。"""
    out = []
    cur = bool(flags[0])
    n = 1
    for v in flags[1:]:
        v = bool(v)
        if v == cur:
            n += 1
        else:
            out.append((cur, n))
            cur, n = v, 1
    out.append((cur, n))
    return out


def _max_run(flags: np.ndarray) -> int:
    return max([n for v, n in _runs(flags) if v] or [0])


def _midline(arr: np.ndarray, vertical: bool):
    """键床中线（竖排=中点列，横排=中点行）+ 键床范围。"""
    white_m, black_m = _mask(arr, "white"), _mask(arr, "black")
    c0, c1, r0, r1 = _bed_extent(white_m, black_m)
    if vertical:
        return arr[:, (c0 + c1) // 2], (c0, c1, r0, r1)
    return arr[(r0 + r1) // 2, :], (c0, c1, r0, r1)


def _seam_deviations(line: np.ndarray) -> np.ndarray:
    """中线上「非键床白底 / 非黑键 / 非音名文字 / 非背景」的像素 = 细缝（含混叠）。

    这四种像素都不属于「缝」，其余一律计入缝宽口径（判据 a/d 用同一分类）。
    """
    cat, names = _classify(line.reshape(1, -1, 3))
    cat = cat[0]
    keep = {names.index(r) for r in _ROLES if r != "white_seam"} | {names.index("bg")}
    return ~np.isin(cat, list(keep))


def _bg_flags(line: np.ndarray) -> np.ndarray:
    cat, names = _classify(line.reshape(1, -1, 3))
    return cat[0] == names.index("bg")


# ----------------------------------------------------------------------
# 二、离屏渲染（竖排键条 / 横排键带）
# ----------------------------------------------------------------------

def _render_vertical(lo: float, hi: float, width: int = 62, height: int = 620):
    """竖排键盘条离屏渲染 → (strip, RGB 数组)。"""
    from acouscope.ui.widgets.freq_axis import PianoKeyboardStrip

    strip = PianoKeyboardStrip()
    strip.resize(width, height)
    strip.setYRange(lo, hi, padding=0)
    QApplication.processEvents()
    return strip, _rgb_array(strip.grab().toImage())


def _keyboard_band(arr: np.ndarray):
    """在整窗截图中按像素定位横排键带（键床像素占过半宽度的行段，取最靠下的一段）。

    不用 `mapTo()`/`geometry()`：离屏布局在首次 grab 前会返回过期几何（实测 mapTo 由
    (0,485) 变为 (0,328)），按渲染结果定位才稳定。
    """
    keyish = _mask(arr, "white") | _mask(arr, "black")
    rows = np.where(keyish.sum(axis=1) > 0.5 * arr.shape[1])[0]
    assert rows.size, "整窗截图中未找到横排键带（键床像素占半宽的整行）"
    bands = []
    cur = [int(rows[0]), int(rows[0])]
    for r in rows[1:]:
        if r - cur[1] <= 2:
            cur[1] = int(r)
        else:
            bands.append(tuple(cur))
            cur = [int(r), int(r)]
    bands.append(tuple(cur))
    return max(bands, key=lambda b: b[1])


def _render_horizontal(zoom=None, size=(1425, 620), key_height=None):
    """横排键带离屏渲染 → (widget, keyboard_widget, xrange, RGB 数组)。

    走**应用同一路径**：喂入真实频谱数据 → `_update_freq_range()`（钢琴卷帘 = 88 键固定
    区间 20.5–108.5）→ `_update_piano_keyboard()` 建键床。`zoom=(lo, hi)` 时额外把视图
    缩放到指定区间（判据基准缩放）后按同一路径重建，杜绝「键床与视图范围不匹配」的假失败。
    键带区间按**像素**在整窗截图中定位（离屏首次 grab 前 `mapTo()/geometry()` 会返回过期几何）。
    `key_height` 用于把键带拉高（判据 c 的厚度量测基准；52px 高的键带 0.46 半音只有
    23.9px，整像素吸附即 ±0.02，量不准比例）。
    """
    from acouscope.ui.widgets.spectrum import SpectrumWidget

    widget = SpectrumWidget()
    widget._keyboard_visible = True
    widget.resize(*size)
    widget.layout().activate()
    QApplication.processEvents()
    freqs = np.linspace(20.0, 20000.0, 512)
    widget.set_data(freqs, np.full(512, 1e-3))
    QApplication.processEvents()
    kw = widget.keyboard_widget
    if key_height is not None:
        kw.setMinimumHeight(key_height)
        kw.setMaximumHeight(key_height)
        widget.resize(size[0], key_height + 260)
        widget.layout().activate()
        QApplication.processEvents()
    if zoom is not None:
        kw.plotItem.vb.setXRange(zoom[0], zoom[1], padding=0)
    for _ in range(3):
        QApplication.processEvents()
        widget._sync_piano_keyboard()
    QApplication.processEvents()
    arr = _rgb_array(widget.grab().toImage())
    r0, r1 = _keyboard_band(arr)
    x0, x1 = kw.plotItem.vb.viewRange()[0]
    return widget, kw, (float(x0), float(x1)), arr[r0:r1 + 1, :]


def _viewbox_width_px(kw) -> float:
    return float(kw.getPlotItem().vb.sceneBoundingRect().width())


def _semitone_px(vertical: bool, extent, xrange, lo: float, hi: float) -> float:
    """每半音像素数：竖排按行跨度/半音数，横排按列跨度/半音数。"""
    c0, c1, r0, r1 = extent
    span = (r1 - r0 + 1) if vertical else (c1 - c0 + 1)
    n_semi = (hi - lo) if vertical else (xrange[1] - xrange[0])
    return span / n_semi


def _alpha(arr: np.ndarray) -> np.ndarray:
    """键面覆盖度（0=键床白底，1=黑键面）：用于半音向的**反混叠加权**量测。"""
    lw = float(0.2126 * 212 + 0.7152 * 212 + 0.0722 * 214)   # keys.white 亮度
    lb = float(0.2126 * 30 + 0.7152 * 30 + 0.0722 * 30)      # keys.black 亮度
    lum = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
    return np.clip((lw - lum) / (lw - lb), 0.0, 1.0)


def _dark_bands(flags: np.ndarray) -> list:
    """一维「黑键面」布尔序列的连续段 [(start, end), ...]（≥2px 记一段，去毛刺）。"""
    idx = np.flatnonzero(flags)
    if idx.size == 0:
        return []
    out = []
    start = prev = int(idx[0])
    for i in idx[1:]:
        i = int(i)
        if i - prev <= 1:
            prev = i
        else:
            out.append((start, prev))
            start = prev = i
    out.append((start, prev))
    return [b for b in out if b[1] - b[0] + 1 >= 2]


def _median(xs: list) -> float:
    return float(np.median(np.asarray(xs, dtype=float)))


# ----------------------------------------------------------------------
# 三、判据 a ~ g（竖/横同口径）
# ----------------------------------------------------------------------

@pytest.mark.parametrize("vertical", [True, False], ids=["vertical", "horizontal"])
def test_a_bed_continuity_no_background_runs(qapp, vertical):
    """判据 a：沿键床中线扫描，**背景色像素段 ≤ 2px**（键床连续 = 不是「豆腐块」）。"""
    if vertical:
        _, arr = _render_vertical(*_RANGE_V_NATURAL)
    else:
        _, _, _, arr = _render_horizontal()
    line, _ = _midline(arr, vertical)
    flags = _bg_flags(line)
    worst = _max_run(flags)
    assert worst <= _BG_RUN_MAX, (
        f"{'竖' if vertical else '横'}排键床中线出现 {worst}px 背景色段"
        f"（阈值 ≤{_BG_RUN_MAX}px）；背景色像素共 {int(flags.sum())}px，"
        f"背景色 = {_bg_hex()}（键带底画布色）"
    )


@pytest.mark.parametrize("vertical", [True, False], ids=["vertical", "horizontal"])
def test_b_black_key_flush_to_hinge_edge(qapp, vertical):
    """判据 b：黑键像素段与「贴边侧」边缘（竖=左缘 / 横=上缘）间隙 **= 0px**。"""
    if vertical:
        _, arr = _render_vertical(*_RANGE_V_NATURAL)
    else:
        _, _, _, arr = _render_horizontal()
    white_m, black_m = _mask(arr, "white"), _mask(arr, "black")
    c0, _c1, r0, _r1 = _bed_extent(white_m, black_m)
    if vertical:
        gap = int(np.where(black_m.any(axis=0))[0].min() - c0)
    else:
        gap = int(np.where(black_m.any(axis=1))[0].min() - r0)
    assert gap == 0, f"黑键距贴边侧间隙 {gap}px（要求 0px：竖排贴左缘 / 横排贴上缘）"


@pytest.mark.parametrize("vertical", [True, False], ids=["vertical", "horizontal"])
def test_c_black_key_ratios(qapp, vertical):
    """判据 c：黑键长/键床宽 ∈[0.45,0.50]、黑键半音向/半音高 ∈[0.54,0.58]（基准缩放下实测）。

    两处「长度」均取**覆盖度求和**（=面积法）：精确色掩码会丢掉黑键两端的反混叠像素
    （半音 13px 时 0.55 半音 = 7.32px，量成 7px → 比值 0.53，属假失败），
    逐像素 alpha 求和则还原几何长度。
    """
    if vertical:
        _, arr = _render_vertical(*_ZOOM_V_MEASURE)
        white_m, black_m = _mask(arr, "white"), _mask(arr, "black")
        c0, c1, r0, r1 = _bed_extent(white_m, black_m)
        alpha = _alpha(arr)
        # 求和只在**键床范围**内（键床外的画布底色 bg2 偏暗，混入会虚增覆盖度）
        bed = alpha[r0:r1 + 1, c0:c1 + 1]
        col = 2                      # 键床内一列（黑键深度内，且避开局外底色列）
        bands = _dark_bands(bed[:, col] > 0.5)
        assert bands, "竖排未测到黑键段"
        row_mid = (bands[0][0] + bands[0][1]) // 2
        ratio_len = float(bed[row_mid, :].sum()) / (c1 - c0 + 1)
        semi_px = _semitone_px(True, (c0, c1, r0, r1), None, *_ZOOM_V_MEASURE)
        lengths = [float(bed[max(0, s - 1):e + 2, col].sum()) for s, e in bands]
    else:
        _, _, xr, arr = _render_horizontal(_ZOOM_H_MEASURE, key_height=400)
        white_m, black_m = _mask(arr, "white"), _mask(arr, "black")
        c0, c1, r0, r1 = _bed_extent(white_m, black_m)
        alpha = _alpha(arr)
        bed = alpha[r0:r1 + 1, c0:c1 + 1]
        row = 2                      # 键床内一行（黑键厚度内，且避开局外底色行）
        bands = _dark_bands(bed[row, :] > 0.5)
        assert bands, "横排未测到黑键段"
        col_mid = (bands[0][0] + bands[0][1]) // 2
        prof = bed[:, col_mid]
        row_mid = sum(_dark_bands(prof > 0.5)[0]) // 2
        ratio_len = float(prof.sum()) / (r1 - r0 + 1)
        semi_px = _semitone_px(False, (c0, c1, r0, r1), xr, None, None)
        lengths = [float(bed[row_mid, max(0, s - 1):e + 2].sum())
                   for s, e in _dark_bands(bed[row_mid, :] > 0.5)]
    ratio_semi = _median(lengths) / semi_px
    assert _RATIO_LEN[0] <= ratio_len <= _RATIO_LEN[1], (
        f"黑键长比实测 {ratio_len:.4f} 超出 {_RATIO_LEN}"
        f"（{'长/键床宽' if vertical else '厚/键床高'}）")
    assert _RATIO_SEMI[0] <= ratio_semi <= _RATIO_SEMI[1], (
        f"黑键半音向比实测 {ratio_semi:.4f} 超出 {_RATIO_SEMI}"
        f"（半音 = {semi_px:.2f}px，黑键段 {[round(v, 1) for v in lengths[:4]]}px，缩放 = "
        f"{_ZOOM_V_MEASURE if vertical else _ZOOM_H_MEASURE}）")


@pytest.mark.parametrize("vertical", [True, False], ids=["vertical", "horizontal"])
def test_d_white_key_seam_within_2px(qapp, vertical):
    """判据 d：白键间细缝宽度 ≤ 2px（缝=键床内非白底/非黑键/非音名文字/非背景的像素段）。"""
    if vertical:
        _, arr = _render_vertical(*_RANGE_V_NATURAL)
    else:
        _, _, _, arr = _render_horizontal()
    line, _ = _midline(arr, vertical)
    worst = _max_run(_seam_deviations(line))
    assert worst <= _BG_RUN_MAX, (
        f"{'竖' if vertical else '横'}排白键细缝实测最宽 {worst}px > {_BG_RUN_MAX}px"
    )
    # 陪伴断言（非主判据）：细缝色仍取自 keys.white_seam（唯一源 theme.py）
    assert theme.key_face("white_seam") == theme.TOKENS["keys"]["physical"]["white_seam"]


@pytest.mark.parametrize("vertical", [True, False], ids=["vertical", "horizontal"])
def test_e_bed_coverage_ge_95pct(qapp, vertical):
    """判据 e：键床（非背景像素）/ 控件可见区 ≥ 0.95。"""
    if vertical:
        _, arr = _render_vertical(*_RANGE_V_NATURAL, height=620)
    else:
        _, _, _, arr = _render_horizontal()
    bg_flags = _bg_flags(arr.reshape(-1, 3))
    cover = 1.0 - float(bg_flags.sum()) / float(arr.shape[0] * arr.shape[1])
    assert cover >= _COVER_MIN, (
        f"{'竖' if vertical else '横'}排键床覆盖率 {cover:.4f} < {_COVER_MIN}"
        f"（背景色 = {_bg_hex()}）"
    )


@pytest.mark.parametrize("vertical", [True, False], ids=["vertical", "horizontal"])
def test_g_key_pixels_positive_and_viewbox_ge_30(qapp, vertical):
    """判据 g（★ 本次修复核心）：grab 中白键色 + 黑键色像素数 **> 0**；ViewBox 宽 ≥ 30px。"""
    if vertical:
        strip, arr = _render_vertical(*_RANGE_V_NATURAL)
        viewbox_w = _viewbox_width_px(strip)
    else:
        _w, kw, xr, arr = _render_horizontal()
        viewbox_w = _viewbox_width_px(kw)
        # 钢琴卷帘 = 88 键固定区间；键盘自身 X 范围经联动后可比宿主略宽（实测 16.97–108.5），
        # 但右端必须落在 88 键区间右界、左端不得越过其左界（键床按实际可见范围铺满）
        assert abs(xr[1] - _RANGE_H_NATURAL[1]) < 0.6, \
            f"横排右界 {xr[1]} 不在钢琴卷帘 88 键区间右界 {_RANGE_H_NATURAL[1]}"
        assert xr[0] <= _RANGE_H_NATURAL[0] + 0.6, \
            f"横排左界 {xr[0]} 超出钢琴卷帘 88 键区间左界 {_RANGE_H_NATURAL[0]}"
    n_white = int(_mask(arr, "white").sum())
    n_black = int(_mask(arr, "black").sum())
    assert viewbox_w >= _VIEWBOX_MIN, f"ViewBox 实测宽 {viewbox_w:.1f}px < {_VIEWBOX_MIN}px"
    assert n_white + n_black > 0, (
        f"键像素 = 0（白 {n_white} + 黑 {n_black}）—— 键面没被画出来（缺陷 A 复发）"
    )
    assert n_white > 0 and n_black > 0, (
        f"白键像素 {n_white} / 黑键像素 {n_black} 必须都 > 0"
    )


def test_g_viewbox_width_across_host_widths(qapp):
    """§1.1 四个对照实验的**修复后复测**：条宽 62/90/120 → ViewBox ≥30px 且键像素 > 0。"""
    rows = []
    for width in (62, 90, 120):
        strip, arr = _render_vertical(*_RANGE_V_NATURAL, width=width)
        n = int(_mask(arr, "white").sum() + _mask(arr, "black").sum())
        rows.append((width, _viewbox_width_px(strip), n))
    for width, vb_w, n in rows:
        assert vb_w >= _VIEWBOX_MIN, f"条宽 {width}px → ViewBox {vb_w:.1f}px < 30px"
        assert n > 0, f"条宽 {width}px → 键像素 0"


# ----------------------------------------------------------------------
# 四、判据 f：可见性只取决于单位（与有无数据无关）—— 缺陷 B
# ----------------------------------------------------------------------

def _piano_index(combo) -> int:
    return [combo.itemData(i) for i in range(combo.count())].index("piano")


def _shown(widget):
    """离屏「已显示」语义（无真实窗口）：`isVisible()` 才能取到真值。"""
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    widget.show()
    QApplication.processEvents()
    return widget


def _spec_data(n_freq: int = 64, n_time: int = 24):
    freqs = np.linspace(20.0, 8000.0, n_freq)
    times = np.linspace(0.0, 1.0, n_time)
    mag = (-60.0 + 60.0 * np.random.default_rng(1042).random((n_freq, n_time)))
    return freqs, times, mag


@pytest.mark.parametrize("with_data", [False, True], ids=["no-data", "with-data"])
def test_f_visibility_spectrogram_only_depends_on_unit(qapp, with_data):
    """判据 f：语谱图**空数据/有数据**切「钢琴卷帘」→ `isVisible()` 且 `isVisibleTo(parent)`
    且宽度 > 0；切回 hz → 隐藏（双向都验，防「有数据反而不可见」反例）。"""
    from acouscope.ui.widgets.spectrogram import SpectrogramWidget

    w = _shown(SpectrogramWidget())
    try:
        w.resize(700, 500)
        if with_data:
            w.set_data(*_spec_data())
        QApplication.processEvents()
        ks = w.kb_strip
        assert not ks.isVisible(), "默认 Hz 模式键面应隐藏"
        w.cmb_y_unit.setCurrentIndex(_piano_index(w.cmb_y_unit))
        QApplication.processEvents()
        assert ks.isVisible(), f"piano 模式键面不可见（with_data={with_data}）"
        assert ks.isVisibleTo(w), f"piano 模式 isVisibleTo(parent) 为假（with_data={with_data}）"
        assert ks.width() > 0, "piano 模式键条宽度为 0"
        w.cmb_y_unit.setCurrentIndex(0)
        QApplication.processEvents()
        assert not ks.isVisible(), "切回 Hz 后键面未隐藏（残留）"
    finally:
        w.close()


@pytest.mark.parametrize("view", ["pitch", "formants", "spectrogram"])
def test_f_visibility_regression_three_views(qapp, view):
    """回归守卫：三视图（pitch / formants / spectrogram）切 piano 均可见，切回均隐藏。"""
    if view == "pitch":
        from acouscope.ui.widgets.pitch import PitchContourWidget
        w = PitchContourWidget()
    elif view == "formants":
        from acouscope.ui.widgets.formants import FormantWidget
        w = FormantWidget()
    else:
        from acouscope.ui.widgets.spectrogram import SpectrogramWidget
        w = SpectrogramWidget()
    w = _shown(w)
    try:
        w.resize(700, 500)
        w.cmb_y_unit.setCurrentIndex(_piano_index(w.cmb_y_unit))
        QApplication.processEvents()
        ks = w.kb_strip
        assert ks.isVisibleTo(ks.parentWidget() or w), f"{view}：piano 模式键面不可见"
        assert ks.width() > 0, f"{view}：键条宽度 0"
        w.cmb_y_unit.setCurrentIndex(0)
        QApplication.processEvents()
        assert not ks.isVisibleTo(ks.parentWidget() or w), f"{view}：切回 Hz 后键面残留"
    finally:
        w.close()


# ----------------------------------------------------------------------
# 五、图像证据（§3.2）：4 图 + 50px 缩略 2 张 + 对照 2 张 + 三视图 3 张 + 缩放 2 张
# ----------------------------------------------------------------------

def _save(qimage: QImage, name: str) -> pathlib.Path:
    _EVID.mkdir(parents=True, exist_ok=True)
    path = _EVID / name
    qimage.save(str(path))
    return path


def _grab_vertical(theme_id: str, lo: float, hi: float, width: int = 62,
                   height: int = 620) -> QImage:
    theme.apply_theme(theme_id)
    strip, _arr = _render_vertical(lo, hi, width=width, height=height)
    img = strip.grab().toImage()
    theme.apply_theme("dark")
    return img


def _grab_horizontal(theme_id: str, zoom=None) -> QImage:
    theme.apply_theme(theme_id)
    _w, _kw, _xr, arr = _render_horizontal(zoom)
    theme.apply_theme("dark")
    return _arr_to_qimage(arr)


def _arr_to_qimage(arr: np.ndarray) -> QImage:
    h, w = arr.shape[:2]
    buf = np.dstack([arr[:, :, 2], arr[:, :, 1], arr[:, :, 0],
                     np.full((h, w), 255, dtype=np.uint8)]).astype(np.uint8)
    return QImage(buf.tobytes(), w, h, QImage.Format.Format_RGB32).copy()


def _hstack(images: list, h: int, gap: int = 8) -> QImage:
    """等比缩放到统一高度后横向拼接（间隙填白，便于人工比对）。"""
    from PyQt6.QtGui import QColor, QPainter

    scaled = [i.scaledToHeight(h, Qt.TransformationMode.SmoothTransformation)
              for i in images]
    w = sum(i.width() for i in scaled) + gap * (len(scaled) - 1)
    out = QImage(w, h, QImage.Format.Format_RGB32)
    out.fill(QColor(255, 255, 255))
    p = QPainter(out)
    x = 0
    for i in scaled:
        p.drawImage(x, 0, i)
        x += i.width() + gap
    p.end()
    return out


def test_evidence_dark_light_and_thumbnails(qapp):
    """证据 ①②：竖/横 × 暗/亮 4 张 + 50px 缩略 2 张（缩到 50px 仍一眼辨为键盘）。"""
    v_dark = _grab_vertical("dark", *_RANGE_V_NATURAL)
    v_light = _grab_vertical("light", *_RANGE_V_NATURAL)
    h_dark = _grab_horizontal("dark")
    h_light = _grab_horizontal("light")
    paths = [
        _save(v_dark, "vertical_dark.png"), _save(v_light, "vertical_light.png"),
        _save(h_dark, "horizontal_dark.png"), _save(h_light, "horizontal_light.png"),
        # 缩略口径：竖排按宽 50px、横排按高 50px（各自的长边缩到 50px）
        _save(v_dark.scaledToWidth(50, Qt.TransformationMode.SmoothTransformation),
              "thumb_vertical_50px.png"),
        _save(h_dark.scaledToHeight(50, Qt.TransformationMode.SmoothTransformation),
              "thumb_horizontal_50px.png"),
    ]
    for p in paths:
        assert p.exists() and p.stat().st_size > 0, f"证据图缺失：{p}"
    # 缩略图仍须可辨出两种键面色（最近色分类，容忍缩放混叠）
    for name in ("thumb_vertical_50px.png", "thumb_horizontal_50px.png"):
        arr = _rgb_array(QImage(str(_EVID / name)))
        cat, names = _classify(arr)
        n_w = int((cat == names.index("white")).sum())
        n_b = int((cat == names.index("black")).sum())
        assert n_w > 0 and n_b > 0, f"{name} 缩略后键面色消失（白 {n_w} / 黑 {n_b}）"


def test_evidence_side_by_side_reference_and_before(qapp):
    """证据 ③：与参考图并排对照 1 张 + 修复前（BAD 横排）对照 1 张。"""
    ref = QImage(str(_REF_KEYFACE))
    v_dark = _grab_vertical("dark", *_RANGE_V_NATURAL)
    # 参考图取顶部同高窗口（原生宽度 84px），与修复后竖排同尺度并排
    ref_crop = ref.copy(0, 0, ref.width(), min(ref.height(), 620))
    _save(_hstack([ref_crop, v_dark], 620), "compare_reference_vs_fixed_vertical.png")

    bad = QImage(str(_BAD_HORIZONTAL))
    fixed = _grab_horizontal("dark")
    _save(_hstack([bad, fixed], 120), "compare_before_bad_vs_fixed_horizontal.png")
    assert (_EVID / "compare_reference_vs_fixed_vertical.png").exists()
    assert (_EVID / "compare_before_bad_vs_fixed_horizontal.png").exists()


def test_evidence_three_views_piano(qapp):
    """证据 ④：spectrogram / pitch / formants 切 piano 后各 1 张（证明「从不出现」已消除）。

    三视图都须**先有数据**：piano 模式下 Y 轴才落到 MIDI 域（pitch/formants 把 f0/共振峰
    经 freq_to_display 换算到 MIDI；无数据时 Y 仍是 Hz，键条纵使可见也不会显示键面）。
    """
    from acouscope.ui.widgets.formants import FormantWidget
    from acouscope.ui.widgets.pitch import PitchContourWidget
    from acouscope.ui.widgets.spectrogram import SpectrogramWidget

    times = np.linspace(0.0, 1.0, 40)
    cases = {
        "pitch": (PitchContourWidget, lambda w: w.set_data(times, np.full(40, 440.0))),
        "formants": (FormantWidget, lambda w: w.set_data(
            times, np.tile([500.0, 1500.0, 2500.0], (40, 1)),
            np.tile([80.0, 120.0, 160.0], (40, 1)))),
        "spectrogram": (SpectrogramWidget, lambda w: w.set_data(*_spec_data())),
    }
    for name, (make, feed) in cases.items():
        w = _shown(make())
        try:
            w.resize(700, 500)
            feed(w)
            w.cmb_y_unit.setCurrentIndex(_piano_index(w.cmb_y_unit))
            QApplication.processEvents()
            feed(w)
            QApplication.processEvents()
            img = w.grab().toImage()
            _save(img, f"view_{name}_piano.png")
            # 键面像素以**键条自身**的截图为据（整窗截图可能掺入图表颜色，不做为正证）
            ks = w.kb_strip
            assert ks.isVisibleTo(ks.parentWidget() or w), f"{name}：键条不可见"
            strip_arr = _rgb_array(ks.grab().toImage())
            n_key = int(_mask(strip_arr, "white").sum() + _mask(strip_arr, "black").sum())
            assert n_key > 0, f"{name}：切 piano 后键条截图里没有键面像素（键面未出现）"
        finally:
            w.close()
    for name in cases:
        assert (_EVID / f"view_{name}_piano.png").exists()


def test_evidence_zoom_pair_and_invariance(qapp):
    """证据 ⑤：两档缩放 2 张 + T-1042b 语义仍成立（只变键距，键长恒定）。"""
    img_a, arr_a = _render_vertical(*_ZOOM_V_MEASURE)
    img_b, arr_b = _render_vertical(50.0, 70.0)
    _save(img_a.grab().toImage(), "zoom_level_a.png")
    _save(img_b.grab().toImage(), "zoom_level_b.png")

    def measure(arr):
        black_m = _mask(arr, "black")
        xs = np.where(black_m.any(axis=0))[0]
        rows = np.where(black_m.any(axis=1))[0]
        col = int(xs.min()) + 2
        bands = [n for v, n in _runs(black_m[:, col]) if v]
        return int(xs.max() - xs.min() + 1), int(rows.max() - rows.min() + 1), len(bands)

    len_a, span_a, n_a = measure(arr_a)
    len_b, span_b, n_b = measure(arr_b)
    assert len_a == len_b, f"黑键长 px 两档不等：{len_a} vs {len_b}（键长应恒定）"
    assert span_a != span_b, "两档缩放的半音跨度应不同（键距随缩放变）"
    assert n_a != n_b, f"两档可见黑键带数应不同（键距随缩放变）：{n_a} vs {n_b}"


