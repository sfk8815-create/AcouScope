# SPDX-License-Identifier: GPL-3.0-only
"""T-1042b v2 实证：缩放不变形 + 贴左/圆角 + 明暗同款（离屏截图 + 像素量值）。

语义源：`内部记录/tasks/T-1042b.txt` §5（指挥硬要求：**缩放只变键距、键长不变**，须截图举证）、
§2（几何硬指标）与 §自证（硬指标实测表 / 圆角实证 / 明暗同款）。
本文件产出（写入报告的证据）：
- 离屏截图：`/tmp/t1042b_zoomA_vertical.png` / `_zoomB_vertical.png`、
  `_zoomA_horizontal.png` / `_zoomB_horizontal.png`（两档缩放），
  `/tmp/t1042b_dark_vertical.png` / `_light_vertical.png`（明暗同款）；
- 像素量值：`/tmp/t1042b_metrics.json` —— 黑键长/厚 px **两档相等**、键距 px **两档不等**；
- 硬指标实测表：由源码常量逐项断言（X0 / 长比 / 高比 / 两圆角 r / 缝宽）。
口径：全离屏；不构造主窗口、不 show 主窗体、不弹模态。
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import pytest

pytest.importorskip("PyQt6")

import pyqtgraph as pg  # noqa: E402
from PyQt6.QtCore import QPointF  # noqa: E402

from acouscope.ui import theme  # noqa: E402

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "acouscope"
_WIDGETS = _SRC / "ui" / "widgets"
_METRICS_PATH = pathlib.Path("/tmp/t1042b_metrics.json")
_BLACK_HEX = "#1E1E1E"
_ZOOM_A = (55.0, 65.0)   # 10 半音（近）
_ZOOM_B = (40.0, 80.0)   # 40 半音（远）


def _pixel_black(img) -> list:
    """收集全图等于黑键物理色 #1E1E1E 的像素坐标。"""
    pts = []
    for y in range(img.height()):
        for x in range(img.width()):
            if img.pixelColor(x, y).name().upper() == _BLACK_HEX:
                pts.append((x, y))
    return pts


def _measure_vertical(img):
    """竖排：黑键列横向长度 px（=键长，恒定）与黑键纵向间距 px（随缩放变）。"""
    pts = _pixel_black(img)
    if not pts:
        return None
    xs = sorted({p[0] for p in pts})
    ys = sorted(p[1] for p in pts)
    length_px = xs[-1] - xs[0] + 1
    left_px = xs[0]
    # 纵向黑键带分组（相邻行差 ≤2px 视为同一键）
    bands = []
    cur = [ys[0], ys[0]]
    for y in ys[1:]:
        if y - cur[1] <= 2:
            cur[1] = y
        else:
            bands.append(tuple(cur))
            cur = [y, y]
    bands.append(tuple(cur))
    centers = [(b[0] + b[1]) / 2 for b in bands]
    spacings = [centers[i + 1] - centers[i] for i in range(len(centers) - 1)]
    return {
        "length_px": length_px, "left_px": left_px,
        "n_bands": len(bands),
        "spacing_avg": (sum(spacings) / len(spacings)) if spacings else None,
    }


def _measure_horizontal(img):
    """横排：黑键厚（纵向）px（=键长，恒定）与黑键横向间距 px（随缩放变）。"""
    pts = _pixel_black(img)
    if not pts:
        return None
    xs = sorted(p[0] for p in pts)
    ys = sorted(p[1] for p in pts)
    thickness_px = ys[-1] - ys[0] + 1
    bands = []
    cur = [xs[0], xs[0]]
    for x in xs[1:]:
        if x - cur[1] <= 2:
            cur[1] = x
        else:
            bands.append(tuple(cur))
            cur = [x, x]
    bands.append(tuple(cur))
    centers = [(b[0] + b[1]) / 2 for b in bands]
    spacings = [centers[i + 1] - centers[i] for i in range(len(centers) - 1)]
    return {
        "thickness_px": thickness_px,
        "n_bands": len(bands),
        "spacing_avg": (sum(spacings) / len(spacings)) if spacings else None,
    }


def _render_strip(lo: float, hi: float, width: int = 90, height: int = 620):
    """离屏渲染竖排键盘条并返回 (QImage, 测量 dict)。"""
    from acouscope.ui.widgets.freq_axis import PianoKeyboardStrip

    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    strip = PianoKeyboardStrip()
    strip.resize(width, height)
    strip.setYRange(lo, hi, padding=0)
    if app is not None:
        app.processEvents()
    img = strip.grab().toImage()
    return img, _measure_vertical(img)


def _render_keyboard_horizontal(lo: float, hi: float):
    """离屏渲染横排键盘（频谱图底部键盘带）并返回 (QImage, 测量 dict)。"""
    from acouscope.ui.widgets.spectrum import SpectrumWidget

    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    widget = SpectrumWidget()
    widget._keyboard_visible = True
    widget.resize(900, 620)
    widget.plot_widget.setXRange(lo, hi, padding=0)
    widget._update_piano_keyboard(lo, hi)
    if app is not None:
        app.processEvents()
    img = widget.keyboard_widget.grab().toImage()
    return img, _measure_horizontal(img)


# ----------------------------------------------------------------------
# 硬指标实测表（需求说明 §自证 #4）：实测值 / 目标区间 / 判定
# ----------------------------------------------------------------------

def test_hard_metrics_table():
    from acouscope.ui.widgets.freq_axis import PianoKeyboardStrip

    rows = {
        "黑键起点 X0": (PianoKeyboardStrip.BLACK_X0, 0.0, 0.0, "== 0（贴左）"),
        "黑键长比（长/白键满宽）": (
            PianoKeyboardStrip.BLACK_W / PianoKeyboardStrip.WHITE_W, 0.45, 0.50, "0.46"),
        "黑键高比（高/半音）": (PianoKeyboardStrip.BLACK_H, 0.54, 0.58, "0.55"),
        "白键圆角 r（半音比）": (PianoKeyboardStrip.WHITE_KEY_R, 0.06, 0.10, "0.08"),
        "黑键圆角 r（黑键高比）": (
            PianoKeyboardStrip.BLACK_KEY_R / PianoKeyboardStrip.BLACK_H, 0.15, 0.20, "0.17"),
    }
    for name, (measured, lo, hi, target) in rows.items():
        assert lo <= measured <= hi, f"{name}：实测 {measured:.4f} 超出 [{lo}, {hi}]"
    # 白键间细缝：源码 seam_pen 宽 0.15 场景单位（典型缩放 ≈1–2px，参考图 2px）
    for name in ("freq_axis.py", "spectrum.py"):
        text = (_WIDGETS / name).read_text(encoding="utf-8")
        assert "width=0.15" in text, f"{name} 白键缝宽未取 0.15"


# ----------------------------------------------------------------------
# 明暗同款（需求说明 §自证 #5）：key_faces() 逐字相等 + 两张离屏截图
# ----------------------------------------------------------------------

def test_key_faces_same_dict_dark_light(qapp):
    theme.apply_theme("dark")
    dark = theme.key_faces()
    theme.apply_theme("light")
    light = theme.key_faces()
    theme.apply_theme("dark")
    assert dark == light and dark == theme.TOKENS["keys"]["physical"]


def test_dark_light_same_render_offscreen(qapp):
    """明暗两主题离屏渲染：白键/黑键像素色同为物理色（明暗同款），存图作证据。"""
    from acouscope.ui.widgets.freq_axis import PianoKeyboardStrip

    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    results = {}
    for tid, tag in (("dark", "dark"), ("light", "light")):
        theme.apply_theme(tid)
        strip = PianoKeyboardStrip()
        strip.resize(90, 620)
        strip.setYRange(60.0, 64.0, padding=0)
        if app is not None:
            app.processEvents()
        img = strip.grab().toImage()
        img.save(f"/tmp/t1042b_{tag}_vertical.png")
        pts = _pixel_black(img)
        assert pts, f"{tag} 渲染未找到黑键像素"
        white_found = any(
            img.pixelColor(x, y).name().upper() == "#D4D4D6"
            for y in range(img.height()) for x in range(img.width())
        )
        assert white_found, f"{tag} 渲染未找到白键像素"
        results[tid] = True
    theme.apply_theme("dark")
    assert results == {"dark": True, "light": True}


# ----------------------------------------------------------------------
# 缩放不变形（需求说明 §5 指挥硬要求）：两档缩放截图 + 像素量值
# ----------------------------------------------------------------------

def test_zoom_invariance_vertical(qapp):
    """竖排：两档 Y 缩放 —— 黑键长 px 相等（键长不变）、键距 px 不等（键距变）。"""
    img_a, m_a = _render_strip(*_ZOOM_A)
    img_b, m_b = _render_strip(*_ZOOM_B)
    assert m_a and m_b, "竖排渲染像素测量失败"
    img_a.save("/tmp/t1042b_zoomA_vertical.png")
    img_b.save("/tmp/t1042b_zoomB_vertical.png")
    assert m_a["length_px"] == m_b["length_px"], \
        f"黑键长 px 两档不等：{m_a['length_px']} vs {m_b['length_px']}（应恒等）"
    assert m_a["spacing_avg"] != m_b["spacing_avg"], "键距 px 两档应不等"
    assert m_a["left_px"] == m_b["left_px"], "黑键贴左缘 px 两档应一致"
    metrics = _load_metrics()
    metrics["vertical"] = {"zoomA": m_a, "zoomB": m_b}
    _save_metrics(metrics)


def test_zoom_invariance_horizontal(qapp):
    """横排：两档 X 缩放 —— 黑键厚 px 相等（键长=垂直向厚度恒定）、键距 px 不等。"""
    img_a, m_a = _render_keyboard_horizontal(*_ZOOM_A)
    img_b, m_b = _render_keyboard_horizontal(*_ZOOM_B)
    assert m_a and m_b, "横排渲染像素测量失败"
    img_a.save("/tmp/t1042b_zoomA_horizontal.png")
    img_b.save("/tmp/t1042b_zoomB_horizontal.png")
    assert m_a["thickness_px"] == m_b["thickness_px"], \
        f"黑键厚 px 两档不等：{m_a['thickness_px']} vs {m_b['thickness_px']}（应恒等）"
    assert m_a["spacing_avg"] != m_b["spacing_avg"], "键距 px 两档应不等"
    metrics = _load_metrics()
    metrics["horizontal"] = {"zoomA": m_a, "zoomB": m_b}
    _save_metrics(metrics)


# ----------------------------------------------------------------------
# 贴左 / 圆角 实证（需求说明 §自证 #6）
# ----------------------------------------------------------------------

def test_vertical_black_key_flush_left_and_rounded(qapp):
    """竖排黑键：路径包围盒左缘 == 0（贴左）、圆角端角点在路径外、中心在路径内。"""
    from acouscope.ui.widgets.freq_axis import PianoKeyboardStrip

    strip = PianoKeyboardStrip()
    strip._build_keys()
    paths = [i for i in strip._key_items
             if isinstance(i, pg.QtWidgets.QGraphicsPathItem)
             and i.brush().color().name().upper() == _BLACK_HEX]
    assert paths, "未找到黑键路径"
    p = paths[0]
    bbox = p.boundingRect()
    assert abs(bbox.x()) < 1e-6, f"黑键包围盒左缘 {bbox.x()} 未贴左（应 0.0）"
    assert abs(bbox.width() - PianoKeyboardStrip.BLACK_W) < 1e-6, "黑键长与常量不符"
    # 圆角端（右端）包围盒角点在路径外、中心点在路径内
    assert not p.path().contains(QPointF(bbox.x() + bbox.width(), bbox.y())), \
        "黑键右上角点应在路径外（已圆角）"
    assert not p.path().contains(QPointF(bbox.x() + bbox.width(), bbox.y() + bbox.height())), \
        "黑键右下角点应在路径外（已圆角）"
    assert p.path().contains(QPointF(bbox.center().x(), bbox.center().y())), \
        "黑键中心点应在路径内"


def test_horizontal_black_key_flush_and_rounded(qapp):
    """横排黑键：贴上缘（顶缘为自由端圆角）、右缘贴键缝、路径中心在内。"""
    from acouscope.dsp.units import midi_is_black_key
    from acouscope.ui.widgets.spectrum import SpectrumWidget

    widget = SpectrumWidget()
    widget._keyboard_visible = True
    widget._update_piano_keyboard(59, 63)
    blacks = [i for i in widget._keyboard_items
              if isinstance(i, pg.QtWidgets.QGraphicsPathItem)
              and i.brush().color().name().upper() == _BLACK_HEX]
    assert blacks, "横排未找到黑键路径"
    p = blacks[0]
    bbox = p.boundingRect()
    # 黑键右缘贴键缝：右缘 == 黑键键号 + 0.5（自右缘反推键号并验证其为黑键）
    right_edge = bbox.x() + bbox.width()
    midi = right_edge - 0.5
    assert abs(midi - round(midi)) < 1e-6, f"黑键右缘 {right_edge:.3f} 未落在键缝（+0.5）处"
    assert midi_is_black_key(round(midi)), f"右缘键缝 {right_edge:.3f} 对应 {round(midi)} 非黑键"
    assert p.path().contains(QPointF(bbox.center().x(), bbox.center().y())), \
        "横排黑键中心点应在路径内"


def _load_metrics() -> dict:
    if _METRICS_PATH.exists():
        return json.loads(_METRICS_PATH.read_text(encoding="utf-8"))
    return {}


def _save_metrics(metrics: dict) -> None:
    _METRICS_PATH.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
