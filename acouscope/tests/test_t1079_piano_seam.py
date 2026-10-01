# SPDX-License-Identifier: GPL-3.0-only
"""T-1079 ① —— 白键缝线**设备像素可见**（竖排 PianoKeyboardStrip + 横排键盘带）。

根因（真机目测轮 ①，QUEUE §〇-bis 四十五续）：`seam_pen` 原以 0.15 **场景单位**
（=半音）为宽，缩小视图（竖排全音域 620px/128 半音 ≈4.8px/半音）下缝宽 ≈0.7 设备
像素 → 抗锯齿吞没、白键间几乎无缝。修法：`freq_axis.make_seam_pen()` 把缝笔置为
cosmetic（设备像素宽、不随 ViewBox 缩放），色值仍取 `keys.white_seam`（theme.py 零改、
不回写；离屏实测 old 路径全音域仅个位数缝像素、new 路径 ≈127 条 ≥1px 缝）。

判据口径（本文件内自足，不 import 其它测档）：
- 扫描线落在键床内（黑键深度之外），逐像素取「与 keys.white 的亮度差 diff」；
  `diff ∈ [3, 18]` 的连续段 = 一条缝（≥3 排除 AA 微染噪点，≤18 上限恒真，长度 ≤3px
  排除音名文字混入），与 `test_piano_key_face_pixels.py` 判据 d 的 ≤2px 口径相容。
- 「可见缝计数」≥ 0.8 × 视内白键边数（129 条边，端部裁切/音名遮挡留余量）；
  反证：把 `make_seam_pen` 打回 identity（=修复前 0.15 场景单位线宽）后同幅渲染，
  可见缝计数 ≤ 0.3 × 边数——证明本判据能区分修复前后。
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtGui import QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from acouscope.ui import theme  # noqa: E402

_WHITE_RGB = np.array([0xD4, 0xD4, 0xD6], dtype=np.int16)   # keys.white（仅测档口径用）
_LUMA = np.array([0.299, 0.587, 0.114])
_RUN_MAX = 3            # 缝段宽上限（含 AA；判据 d ≤2 相容）
_COVER_MIN = 0.8        # 修复后：视内白键边被缝覆盖比例下限
_OLD_MAX = 0.3          # 反证（修复前 old 路径）：覆盖比例上限


def _hex_rgb(hexcolor: str) -> np.ndarray:
    s = hexcolor.lstrip("#")
    return np.array([int(s[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.int16)


def _rgb_array(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    h, w, bpl = img.height(), img.width(), img.bytesPerLine()
    buf = img.constBits()
    buf.setsize(bpl * h)
    arr = np.frombuffer(buf, dtype=np.uint8).reshape(h, bpl // 4, 4)
    return np.ascontiguousarray(arr[:, :w, 2::-1])


def _white_edges():
    """全部白键边界（竖排=横向缝线所在半音坐标；横排=纵向缝线所在半音坐标）。"""
    from acouscope.dsp.units import midi_is_white_key

    whites = [m for m in range(128) if midi_is_white_key(m)]
    return sorted({m - 0.5 for m in whites} | {m + 0.5 for m in whites})


def _seam_runs(line: np.ndarray) -> list:
    """一维 RGB 扫描线 → 缝段长度表（diff=对白键面的亮度降幅 ∈[3,18] 的连续段）。"""
    diff = (_WHITE_RGB @ _LUMA) - line.astype(np.int16) @ _LUMA
    hit = (diff >= 3) & (diff <= 18)
    runs, n = [], 0
    for v in hit:
        if v:
            n += 1
        elif n:
            runs.append(n)
            n = 0
    if n:
        runs.append(n)
    return [r for r in runs if r <= _RUN_MAX]


def _best_run_count(arr: np.ndarray, vertical: bool, frac_band) -> int:
    """在键床内沿扫描方向取多条候选线（避开黑键/音名），返回最大「可见缝段数」。"""
    white_m = np.all(arr == _WHITE_RGB, axis=2)
    if vertical:
        cols = np.where(white_m.any(axis=0))[0]
        c0, c1 = int(cols.min()), int(cols.max())
        lines = [arr[:, c0 + int(f * (c1 - c0))] for f in frac_band]
    else:
        rows = np.where(white_m.any(axis=1))[0]
        r0, r1 = int(rows.min()), int(rows.max())
        lines = [arr[r0 + int(f * (r1 - r0)), :] for f in frac_band]
    return max(len(_seam_runs(ln)) for ln in lines)


def _render_vertical(qapp, lo: float, hi: float, width=62, height=620):
    from acouscope.ui.widgets.freq_axis import PianoKeyboardStrip

    strip = PianoKeyboardStrip()
    strip.resize(width, height)
    strip.setYRange(lo, hi, padding=0)
    for _ in range(3):
        qapp.processEvents()
    return strip, _rgb_array(strip.grab().toImage())


def _render_horizontal(qapp, width=560, height=240):
    """横排键盘带全音域，键盘窗压窄到 ~500px（128 半音 ≈3.9px/半音 → old 缝 <1 设备像素）。

    ★ 离屏首 grab 前 ViewBox 按过期几何（默认 640×480 系）渲染（T-1042c 同款坑）：
    每次改宽/改范围后先 `widget.grab()` 暖一次布局，再走最终 `kw.grab()`。
    """
    from acouscope.ui.widgets.spectrum import SpectrumWidget

    widget = SpectrumWidget()
    widget._keyboard_visible = True
    widget.resize(width, height)
    kw = widget.keyboard_widget
    kw.setFixedWidth(500)
    kw.setFixedHeight(160)
    widget.layout().activate()
    widget.grab()
    widget.plot_widget.setXRange(-0.5, 127.5, padding=0)
    for _ in range(3):
        qapp.processEvents()
    widget._update_piano_keyboard(0.0, 127.0)
    for _ in range(3):
        qapp.processEvents()
    kw.plotItem.vb.setXRange(-0.5, 127.5, padding=0)
    widget.grab()
    qapp.processEvents()
    return widget, _rgb_array(kw.grab().toImage())


# ----------------------------------------------------------------------
# ① 属性级：cosmetic 设备像素笔 + 色值零改（不回写 theme）
# ----------------------------------------------------------------------

def test_make_seam_pen_is_cosmetic_device_px(qapp):
    import pyqtgraph as pg

    from acouscope.ui.widgets.freq_axis import make_seam_pen

    faces = theme.key_faces()
    pen = make_seam_pen(pg.mkPen(faces["white_seam"], width=0.15))
    assert pen.isCosmetic(), "缝笔未置 cosmetic（仍随 ViewBox 缩放 → 缩小下 <1 设备像素）"
    assert pen.width() == 1
    assert pen.color().name().upper() == faces["white_seam"].upper()
    # theme 色值零改（红线：M-1 只准渲染面生效，缝色唯一源仍是 theme.py 原值）
    assert theme.key_face("white_seam") == theme.TOKENS["keys"]["physical"]["white_seam"]
    assert theme.key_face("white_seam").upper() == "#C6C6C8"


def test_vertical_white_key_pens_cosmetic(qapp):
    import pyqtgraph as pg

    from acouscope.ui.widgets.freq_axis import PianoKeyboardStrip

    strip = PianoKeyboardStrip()
    strip._build_keys()
    whites = [i for i in strip._key_items
              if isinstance(i, pg.QtWidgets.QGraphicsPathItem)
              and i.brush().color().name().upper() == theme.key_face("white").upper()]
    assert whites, "未建出白键路径"
    for it in whites[:5]:
        assert it.pen().isCosmetic() and it.pen().width() == 1


# ----------------------------------------------------------------------
# ② 像素法证：缩小全音域视图下 ≥1px 缝列可见（竖/横两带）
# ----------------------------------------------------------------------

def test_vertical_seam_visible_when_zoomed_out(qapp):
    n_edges = len(_white_edges())
    _, arr = _render_vertical(qapp, 0.0, 128.0)
    runs = _best_run_count(arr, vertical=True, frac_band=(0.50, 0.58, 0.66, 0.74))
    assert runs >= _COVER_MIN * n_edges, (
        f"竖排全音域可见缝段 {runs} < {_COVER_MIN}×边数 {n_edges}（缝仍被缩放到亚像素？）")


def test_horizontal_seam_visible_when_zoomed_out(qapp):
    n_edges = len(_white_edges())
    _, arr = _render_horizontal(qapp)
    runs = _best_run_count(arr, vertical=False, frac_band=(0.55, 0.63, 0.71))
    assert runs >= _COVER_MIN * n_edges, (
        f"横排全音域可见缝段 {runs} < {_COVER_MIN}×边数 {n_edges}")


def test_old_subpixel_pen_swallowed_negative_control(qapp):
    """反证：identity 打回修复前（0.15 场景单位非 cosmetic）→ 同判据下缝几乎不可见（竖+横）。"""
    from acouscope.ui.widgets import freq_axis

    n_edges = len(_white_edges())
    orig = freq_axis.make_seam_pen
    try:
        freq_axis.make_seam_pen = lambda p: p
        _, arr_old = _render_vertical(qapp, 0.0, 128.0)
        old_v = _best_run_count(arr_old, vertical=True, frac_band=(0.50, 0.58, 0.66, 0.74))
        _, arr_old_h = _render_horizontal(qapp)
        old_h = _best_run_count(arr_old_h, vertical=False, frac_band=(0.55, 0.63, 0.71))
    finally:
        freq_axis.make_seam_pen = orig
    _, arr_new = _render_vertical(qapp, 0.0, 128.0)
    new_v = _best_run_count(arr_new, vertical=True, frac_band=(0.50, 0.58, 0.66, 0.74))
    _, arr_new_h = _render_horizontal(qapp)
    new_h = _best_run_count(arr_new_h, vertical=False, frac_band=(0.55, 0.63, 0.71))
    assert old_v <= _OLD_MAX * n_edges, (
        f"反证失效：竖排 old 路径竟有 {old_v} 条可见缝（判据不具区分度）")
    assert old_h <= _OLD_MAX * n_edges, (
        f"反证失效：横排 old 路径竟有 {old_h} 条可见缝")
    assert new_v >= _COVER_MIN * n_edges and new_h >= _COVER_MIN * n_edges
    assert new_v > old_v * 2 and new_h > old_h * 2, (
        f"new(v={new_v},h={new_h}) 未显著优于 old(v={old_v},h={old_h})")


# ----------------------------------------------------------------------
# ③ 离屏自证图：/tmp/pi_t1079_piano.png（竖排 @三档缩放 + 底部横排全音域）
# ----------------------------------------------------------------------

def _png_from_rgb(arr: np.ndarray, path: str) -> None:
    h, w, _ = arr.shape
    bgra = np.dstack([arr[:, :, ::-1], np.full((h, w, 1), 255, np.uint8)])
    img = QImage(np.ascontiguousarray(bgra).tobytes(), w, h, w * 4,
                 QImage.Format.Format_RGB32)
    assert img.save(path)


def test_evidence_render_multi_zoom(qapp):
    out = pathlib.Path("/tmp/pi_t1079_piano.png")
    strips = [_render_vertical(qapp, lo, hi)[1]
              for lo, hi in ((0.0, 128.0), (48.0, 84.0), (60.0, 64.0))]
    h = max(a.shape[0] for a in strips)
    pads = [np.pad(a, ((0, h - a.shape[0]), (0, 2), (0, 0)),
                   constant_values=0x80) for a in strips]
    top = np.hstack(pads)
    band = _render_horizontal(qapp)[1]
    band = np.pad(band, ((2, 0), (0, 0), (0, 0)), constant_values=0x80)
    w = max(top.shape[1], band.shape[1])
    top = np.pad(top, ((0, 0), (0, w - top.shape[1]), (0, 0)), constant_values=0x80)
    band = band[:, :w]
    _png_from_rgb(np.vstack([top, band]), str(out))
    assert out.exists() and out.stat().st_size > 1000
    print(f"\n[T-1079①] evidence -> {out}")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
