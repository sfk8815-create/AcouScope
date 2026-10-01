# SPDX-License-Identifier: GPL-3.0-only
"""T-1080 M-1：图表设计器预览 DPR 感知（高 DPI 不再糊）守卫测。

三态：
- **dpr=1（离屏 / 普通屏）**：与旧实现**逐像素等价**（不回退，判据①要求）；
- **注入假 dpr=2**（retina 面无法离屏复现，故注入）：预览出图 dpi 抬到 `72*dpr`、
  缩放目标按**物理像素**、产出 `pixmap.devicePixelRatio() == label.devicePixelRatioF()`
  ⇒ Qt 1:1 物理映射；
- **红线**：`PREVIEW_DPI` 基线不动（方法 (c) 不采用）、导出 DPI 路径零触（静态守卫）、
  重图防抖档不劣化。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPixmap

from acouscope.ui.widgets import chart_designer as cd
from acouscope.ui.widgets.chart_designer import ChartDesignerPanel

_LOGICAL = (800, 600)


@pytest.fixture
def panel(qapp):
    """裸面板（无宿主），预览标签尺寸固定 → 缩放目标可预测。"""
    p = ChartDesignerPanel(settings=None)
    p.preview_label.resize(*_LOGICAL)
    return p


@pytest.fixture
def shown(panel, monkeypatch):
    """拦 `_show_pixmap` 交给 `setPixmap` 的原图。

    注：`QLabel.pixmap()` 会按标签自身 DPR 重采样返回（Qt6 语义），不能用来断言
    我们产出的 DPR / 物理尺寸，故直接取传入值。
    """
    records: list = []
    original = panel.preview_label.setPixmap

    def _spy(pix):
        records.append(QPixmap(pix))  # 拷贝，保住产出时的尺寸与 DPR
        return original(pix)

    monkeypatch.setattr(panel.preview_label, "setPixmap", _spy)
    return records


def _checker_png(tmp_path, name: str, w: int, h: int) -> Path:
    """造一张 w×h 棋盘源图（非纯色，保证缩放差异可辨）。"""
    from PyQt6.QtCore import QRectF
    from PyQt6.QtGui import QPainter

    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor("#FFFFFF"))
    painter = QPainter(img)
    painter.fillRect(0, 0, w, h, QColor("#FFFFFF"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#101010"))
    for ty in range(0, h, 16):
        for tx in range(0, w, 16):
            if (tx // 16 + ty // 16) % 2 == 0:
                painter.drawRect(QRectF(tx, ty, 16, 16))
    painter.end()
    out = tmp_path / name
    assert img.save(str(out), "PNG")
    return out


def _digest(pix: QPixmap) -> bytes:
    img = pix.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    return bytes(img.constBits().asstring(img.sizeInBytes()))


def _fake_dpr(p, value: float, monkeypatch):
    monkeypatch.setattr(p, "_preview_dpr", lambda: float(value))


# ---------------------------------------------------------------------------
# dpr=1：不回退（判据①「逐像素等价」）
# ---------------------------------------------------------------------------


def test_dpr1_output_device_pixel_ratio_matches_label(panel, shown, tmp_path):
    src = _checker_png(tmp_path, "src.png", 1600, 1200)
    assert panel._show_pixmap(src) is True
    out = shown[-1]
    assert not out.isNull()
    assert out.devicePixelRatio() == panel.preview_label.devicePixelRatioF() == 1.0


def test_dpr1_pixel_identical_to_legacy_impl(panel, shown, tmp_path):
    """dpr=1 时新实现的产出 == 旧实现 `pix.scaled(label.size(), Smooth)`，逐像素同。"""
    src = _checker_png(tmp_path, "src.png", 1600, 1200)
    assert panel._show_pixmap(src) is True
    legacy = QPixmap(str(src)).scaled(
        panel.preview_label.size(),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    out = shown[-1]
    assert out.size() == legacy.size()
    assert _digest(out) == _digest(legacy)


# ---------------------------------------------------------------------------
# 注入 dpr=2：物理像素出图 + 标注 DPR
# ---------------------------------------------------------------------------


def test_dpr2_scales_to_physical_pixels_and_marks_ratio(panel, shown, tmp_path, monkeypatch):
    _fake_dpr(panel, 2.0, monkeypatch)
    src = _checker_png(tmp_path, "src.png", 1600, 1200)
    assert panel._show_pixmap(src) is True
    out = shown[-1]
    # 源图恰填满物理目标 → 1600×1200 物理像素（旧实现只会给 800×600 = 放大一倍糊）
    assert out.width() == _LOGICAL[0] * 2 and out.height() == _LOGICAL[1] * 2
    assert out.devicePixelRatio() == 2.0
    # 逻辑尺寸仍等于标签尺寸 → 1:1 物理映射，无放大
    assert out.width() / out.devicePixelRatio() == _LOGICAL[0]


def test_dpr2_yields_more_physical_pixels_than_dpr1(panel, shown, tmp_path, monkeypatch):
    """同一大小的源图：dpr=2 分支必须比 dpr=1 交付更多物理像素（否则仍糊）。"""
    src = _checker_png(tmp_path, "src.png", 1600, 1200)
    panel._show_pixmap(src)
    base = shown[-1]
    _fake_dpr(panel, 2.0, monkeypatch)
    panel._show_pixmap(src)
    sharp = shown[-1]
    assert sharp.width() > base.width() and sharp.height() > base.height()
    assert base.devicePixelRatio() == 1.0 and sharp.devicePixelRatio() == 2.0


def test_null_pixmap_still_fails(panel, tmp_path):
    assert panel._show_pixmap(tmp_path / "missing.png") is False


# ---------------------------------------------------------------------------
# 预览出图 dpi（方法 a）
# ---------------------------------------------------------------------------


def test_preview_dpi_tracks_dpr_with_72_baseline(panel, monkeypatch):
    assert cd.PREVIEW_DPI == 72  # 基线不动（方法 (c) 未采用）
    _fake_dpr(panel, 1.0, monkeypatch)
    assert panel._preview_dpi() == 72
    _fake_dpr(panel, 2.0, monkeypatch)
    assert panel._preview_dpi() == 144
    _fake_dpr(panel, 2.5, monkeypatch)
    assert panel._preview_dpi() == 180
    _fake_dpr(panel, 0.5, monkeypatch)
    assert panel._preview_dpi() == 72  # 下界恒为基线，绝不低采样


def test_renderer_receives_dpr_aware_dpi(panel, monkeypatch):
    """`_render_preview` 传给宿主的 dpi = `_preview_dpi()`（预览面），非导出 dpi。"""
    calls: list = []
    panel.set_preview_renderer(lambda path, dpi, preview: calls.append((dpi, preview)) or False)
    panel.render_now()
    assert calls == [(72, True)]
    _fake_dpr(panel, 2.0, monkeypatch)
    panel.render_now()
    assert calls[-1] == (144, True)


def test_export_dpi_surface_untouched(panel, monkeypatch):
    """红线：导出 dpi 只来自 `spn_dpi`，与 dpr 无关（抬 dpr 不得污染 params）。"""
    panel.spn_dpi.setValue(300)
    _fake_dpr(panel, 3.0, monkeypatch)
    assert panel.params()["dpi"] == 300
    assert panel._preview_dpi() == 216


def test_preview_path_has_no_export_dpi_reference():
    """静态：`_render_preview` 只经 `_preview_dpi()`，不回读导出 dpi 控件。"""
    import inspect

    src = inspect.getsource(ChartDesignerPanel._render_preview)
    assert "_preview_dpi()" in src and "spn_dpi" not in src
    assert "setDevicePixelRatio" in inspect.getsource(ChartDesignerPanel._show_pixmap)


def test_heavy_mode_debounce_unchanged_with_dpr(panel, monkeypatch):
    """重图仍走 200ms 防抖 + 降采样档（判据①「不劣化」）。"""
    _fake_dpr(panel, 2.0, monkeypatch)
    panel.set_preview_renderer(lambda *a, **k: False)
    panel.set_mode_provider(lambda: 2)  # 语谱图 = 重图
    panel.schedule_preview()
    assert panel._timer.isActive() is True
    assert panel._timer.interval() == cd.PREVIEW_DEBOUNCE_MS == 200
