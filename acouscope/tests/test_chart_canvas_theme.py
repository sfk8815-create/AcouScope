# SPDX-License-Identifier: GPL-3.0-only
"""T-1032 图表画布并入主题回归守卫。

守住两条线：
1. **屏幕**：深色主题下画布底色为深色（`bg1`，嵌套画布 `bg2`），轴/刻度/网格随主题
   着色，且主题往返切换实时生效（pyqtgraph / matplotlib 均不走 QSS）；
2. **导出**（学术红线）：`spectrogram3d` 图导出与报告插图导出的底色仍为**白**，
   全局 `rcParams` 颜色项未被改动。

离屏：仅构造控件本体，禁 `MainWindow`、禁 `show()`。
"""

import re
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("pyqtgraph")
pytest.importorskip("matplotlib")

from acouscope.ui import theme

_WIDGETS_DIR = (
    Path(__file__).resolve().parent.parent / "src" / "acouscope" / "ui" / "widgets"
)

# 改动面 10 文件（18 处画布锚点分布其中）
CANVAS_FILES = (
    "waveform.py", "spectrum.py", "spectrogram.py", "pitch.py", "formants.py",
    "timbre.py", "room_modes.py", "realtime_features.py", "freq_axis.py",
    "spectrogram3d.py",
)

DARK_BG1 = "#171A1E"   # §2.2 暗骨架 bg1（panel）
DARK_BG2 = "#1E2227"   # §2.2 暗骨架 bg2（嵌套/次级画布）
WHITE = "#FFFFFF"      # §2.3 明骨架 bg1（浅色主题画布底 = 零回归基线）

# 键面（钢琴键）原硬编码 hex —— 定案 F‴ 要求全部令牌化
_KEY_FACE_HEX = ("#fef3c7", "#1f2937", "#9ca3af", "#111827", "#f59e0b", "#ffffff")


@pytest.fixture(autouse=True)
def _restore_theme():
    """主题为全局态：用例结束还原为运行前生效配色。

    ``colors()["id"]`` 仅在 ``apply_theme`` 之后存在（模块初始态无 id），
    故初始态不还原（初始配色即 dark，与还原等价）。
    """
    previous = theme.colors().get("id")
    yield
    if previous:
        theme.apply_theme(previous)


@pytest.fixture(scope="module")
def canvas_probe(qapp):
    """(锚点, 画布对象, 底色角色) —— 覆盖 10 文件 18 处锚点。"""
    from acouscope.ui.widgets.formants import FormantWidget
    from acouscope.ui.widgets.freq_axis import PianoKeyboardStrip
    from acouscope.ui.widgets.pitch import PitchContourWidget
    from acouscope.ui.widgets.realtime_features import RealtimePanel
    from acouscope.ui.widgets.room_modes import RoomModesWidget
    from acouscope.ui.widgets.spectrogram import SpectrogramWidget
    from acouscope.ui.widgets.spectrogram3d import Spectrogram3DWidget
    from acouscope.ui.widgets.spectrum import SpectrumWidget
    from acouscope.ui.widgets.timbre import TimbreWidget
    from acouscope.ui.widgets.waveform import WaveformWidget

    waveform = WaveformWidget()
    spectrum = SpectrumWidget()
    spectrogram = SpectrogramWidget()
    pitch = PitchContourWidget()
    formants = FormantWidget()
    timbre = TimbreWidget()
    room_modes = RoomModesWidget()
    realtime = RealtimePanel()
    keyboard_strip = PianoKeyboardStrip()
    spectrogram3d = Spectrogram3DWidget()

    probes = [
        ("waveform.py:438", waveform.plot_widget, "bg1"),
        ("spectrum.py:432", spectrum.plot_widget, "bg1"),
        ("spectrum.py:502", spectrum.keyboard_widget, "bg2"),
        ("spectrogram.py:296", spectrogram.plot_widget, "bg1"),
        ("spectrogram.py:314", spectrogram.colorbar_widget, "bg2"),
        ("pitch.py:70", pitch.plot_widget, "bg1"),
        ("formants.py:72", formants.plot_widget, "bg1"),
        ("timbre.py:247", timbre.mfcc_plot, "bg1"),
        ("timbre.py:257", timbre.mfcc_colorbar, "bg2"),
        ("timbre.py:275", timbre.hnr_plot, "bg1"),
        ("timbre.py:295", timbre.feature_plot, "bg1"),
        ("timbre.py:316", timbre.dim_plot, "bg1"),
        ("room_modes.py:154", room_modes.plot_widget, "bg1"),
        ("realtime_features.py:240", realtime.plot_bands, "bg1"),
        ("realtime_features.py:285", realtime.plot_spectrum, "bg1"),
        ("realtime_features.py:323", realtime.plot_bars, "bg1"),
        ("freq_axis.py:180", keyboard_strip, "bg2"),
    ]
    return {
        "probes": probes,
        "spectrogram3d": spectrogram3d,
        "widgets": [
            waveform, spectrum, spectrogram, pitch, formants, timbre,
            room_modes, realtime, keyboard_strip, spectrogram3d,
        ],
    }


def _bg(canvas):
    return canvas.backgroundBrush().color().name().upper()


def _probe_ok(entry):
    return entry if len(entry) == 3 else (entry[0], entry[1], "bg1")


# ----------------------------------------------------------------------
# 屏幕画布：底色 / 轴色 / 网格 / 实时切换
# ----------------------------------------------------------------------

def test_dark_canvas_background_uses_neutral_roles(canvas_probe):
    """深色主题：主画布底 == bg1，嵌套/次级画布底 == bg2（定案 A‴）。"""
    theme.apply_theme("dark")
    expected = {"bg1": DARK_BG1, "bg2": DARK_BG2}
    for name, canvas, role in (_probe_ok(e) for e in canvas_probe["probes"]):
        assert _bg(canvas) == expected[role], f"{name} 底色未随主题（期望 {expected[role]}）"


def test_light_canvas_background_is_white_zero_change(canvas_probe):
    """浅色主题：18 处画布底一律 #FFFFFF（浅色零变化，定案 A‴）。"""
    theme.apply_theme("light")
    for name, canvas, _role in (_probe_ok(e) for e in canvas_probe["probes"]):
        assert _bg(canvas) == WHITE, f"{name} 浅色下非白底（回归）"
    theme.apply_theme("default")
    for name, canvas, _role in (_probe_ok(e) for e in canvas_probe["probes"]):
        assert _bg(canvas) == WHITE, f"{name} default 主题下非白底（回归）"


def test_theme_switch_is_live_for_canvas(qapp, canvas_probe):
    """主题往返切换：底色随之变化（不只看是否抛异常，定案 C‴）。"""
    theme.apply_theme("dark")
    dark_values = [_bg(c) for _n, c, _r in (_probe_ok(e) for e in canvas_probe["probes"])]
    theme.apply_theme("light")
    light_values = [_bg(c) for _n, c, _r in (_probe_ok(e) for e in canvas_probe["probes"])]
    theme.apply_theme("dark")
    back_values = [_bg(c) for _n, c, _r in (_probe_ok(e) for e in canvas_probe["probes"])]

    assert dark_values != light_values
    assert all(v == WHITE for v in light_values)
    assert back_values == dark_values


def test_axis_pen_and_labels_follow_theme(canvas_probe):
    """轴/刻度 == text_sub，轴标签 == text，网格线随之着色（定案 B‴）。"""
    theme.apply_theme("dark")
    c = theme.colors()
    for name, canvas, _role in (_probe_ok(e) for e in canvas_probe["probes"]):
        for side in ("left", "bottom"):
            axis = canvas.getAxis(side)
            assert axis.pen().color().name().upper() == c["text_sub"].upper(), (
                f"{name} {side} 轴笔未随主题"
            )
            assert axis.textPen().color().name().upper() == c["text_sub"].upper(), (
                f"{name} {side} 刻度文字未随主题"
            )
            assert axis.labelStyle.get("color", "").upper() == c["text"].upper(), (
                f"{name} {side} 轴标签未随主题"
            )


def test_grid_is_not_near_white_in_dark_theme(canvas_probe):
    """深色下网格不得沿用近白灰线（轴笔即网格色，定案 B‴）。"""
    theme.apply_theme("dark")
    for name, canvas, _role in (_probe_ok(e) for e in canvas_probe["probes"]):
        for side in ("left", "bottom"):
            axis = canvas.getAxis(side)
            if axis.grid is False:
                continue
            color = axis.pen().color()
            assert max(color.red(), color.green(), color.blue()) < 200, (
                f"{name} {side} 网格/轴颜色过亮（近白）"
            )


# ----------------------------------------------------------------------
# spectrogram3d（唯一 matplotlib 屏上画布）
# ----------------------------------------------------------------------

def _rgba_like(color, target_hex):
    """RGB 通道比对（忽略 alpha：3D 面板默认半透明，叠在同色 figure 上仍为同色）。"""
    from matplotlib.colors import to_rgba

    expected = to_rgba(target_hex)
    return all(abs(float(a) - float(b)) < 0.01 for a, b in zip(color[:3], expected[:3]))


def test_matplotlib_canvas_follows_theme(canvas_probe):
    """matplotlib 画布（figure + 全部 axes）随主题：深色 bg1 / 浅色白。"""
    widget = canvas_probe["spectrogram3d"]
    theme.apply_theme("dark")
    assert _rgba_like(widget.figure.get_facecolor(), DARK_BG1)
    assert _rgba_like(widget.ax_3d.get_facecolor(), DARK_BG1)
    theme.apply_theme("light")
    assert _rgba_like(widget.figure.get_facecolor(), WHITE)
    assert _rgba_like(widget.ax_3d.get_facecolor(), WHITE)


def test_matplotlib_screen_pixels_follow_theme(canvas_probe):
    """屏幕抽样像素：深色主题下 matplotlib 画布为深色，浅色主题下为白。"""
    widget = canvas_probe["spectrogram3d"]
    widget.resize(420, 300)

    theme.apply_theme("dark")
    widget.canvas.draw()
    dark_pixels = np.asarray(widget.canvas.buffer_rgba())
    dark_corner = dark_pixels[2, 2]
    assert max(int(v) for v in dark_corner[:3]) < 90, f"深色下屏幕画布非深：{dark_corner}"

    theme.apply_theme("light")
    widget.canvas.draw()
    light_pixels = np.asarray(widget.canvas.buffer_rgba())
    light_corner = light_pixels[2, 2]
    assert min(int(v) for v in light_corner[:3]) >= 235, f"浅色下屏幕画布非白：{light_corner}"


def test_spectrogram3d_export_is_white_while_screen_is_dark(
    qapp, tmp_path, monkeypatch, canvas_probe
):
    """★ 学术红线回归锁：屏幕深色 ≠ 导出白底（figure + axes 面板均白）。

    ① 深色主题下屏幕画布为深色；② 导出 PNG 抽样像素为白；③ 导出后屏幕恢复深色。
    """
    from matplotlib import image as mpl_image

    from PyQt6.QtWidgets import QFileDialog

    widget = canvas_probe["spectrogram3d"]
    theme.apply_theme("dark")
    assert _rgba_like(widget.figure.get_facecolor(), DARK_BG1)

    target = tmp_path / "s3d.png"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (str(target), "PNG 图片 (*.png)")),
    )
    widget._save_figure()

    assert target.exists(), "导出未产出文件"
    pixels = mpl_image.imread(str(target))
    corners = [pixels[0, 0], pixels[0, -1], pixels[-1, 0], pixels[-1, -1]]
    for corner in corners:
        assert float(np.min(corner[:3])) >= 0.98, f"导出产物底色非白：{corner}"
    center = pixels[pixels.shape[0] // 2, pixels.shape[1] // 2]
    assert float(np.min(center[:3])) >= 0.75, f"导出产物面板区非浅色：{center}"

    # 导出后必须恢复屏幕主题呈现
    assert _rgba_like(widget.figure.get_facecolor(), DARK_BG1)


def test_export_white_covers_axes_panes(qapp, canvas_probe):
    """导出白底须覆盖 axes 面板（仅 print_figure(facecolor=) 管不到，定案 E‴）。"""
    from matplotlib.colors import to_rgba

    widget = canvas_probe["spectrogram3d"]
    theme.apply_theme("dark")
    widget._apply_export_white()
    try:
        assert _rgba_like(widget.figure.get_facecolor(), WHITE)
        assert _rgba_like(widget.ax_3d.get_facecolor(), WHITE)
        assert _rgba_like(widget.ax_3d.xaxis.pane.get_facecolor(), WHITE)
        assert _rgba_like(widget.ax_3d.zaxis.pane.get_facecolor(), WHITE)
        for axis in (widget.ax_3d.xaxis, widget.ax_3d.yaxis, widget.ax_3d.zaxis):
            label_rgba = to_rgba(axis.label.get_color())
            assert max(label_rgba[:3]) < 0.5, "导出期轴标签应为深色"
    finally:
        widget._restore_canvas_theme()
    assert _rgba_like(widget.figure.get_facecolor(), DARK_BG1)


def test_report_figure_export_stays_white_under_dark_theme(qapp, tmp_path):
    """报告插图（FigureExporter）在深色主题下仍白底（定案 D‴）。"""
    from matplotlib import image as mpl_image

    from acouscope.visualization.exporters import FigureExporter

    theme.apply_theme("dark")
    times = np.linspace(0.0, 1.0, 512)
    out = FigureExporter().export_waveform(
        times, np.sin(2 * np.pi * 5.0 * times), tmp_path / "waveform.png",
        fmt="png", dpi=100,
    )
    pixels = mpl_image.imread(str(out))
    for corner in (pixels[0, 0], pixels[0, -1], pixels[-1, 0], pixels[-1, -1]):
        assert float(np.min(corner[:3])) >= 0.98, f"报告插图底色非白：{corner}"


def test_global_rcparams_colors_unchanged(qapp, canvas_probe):
    """禁改全局 rcParams 颜色项（学术白底红线，定案 D‴）。"""
    matplotlib = pytest.importorskip("matplotlib")

    theme.apply_theme("dark")
    widget = canvas_probe["spectrogram3d"]
    widget.render()
    assert str(matplotlib.rcParams["figure.facecolor"]).lower() in ("w", "white", "#ffffff")
    assert str(matplotlib.rcParams["axes.facecolor"]).lower() in ("w", "white", "#ffffff")
    assert str(matplotlib.rcParams["savefig.facecolor"]).lower() in ("w", "white", "auto")


# ----------------------------------------------------------------------
# 静态守卫：10 文件令牌化 / 订阅齐备
# ----------------------------------------------------------------------

def _read(name: str) -> str:
    return (_WIDGETS_DIR / name).read_text(encoding="utf-8")


def test_no_hardcoded_white_background_left():
    """10 文件不再有硬编码白底 setBackground；且均有主题刷新入口。"""
    for name in CANVAS_FILES:
        text = _read(name)
        assert not re.search(r"setBackground\(\s*[\"']w[\"']\s*\)", text), name
        assert not re.search(r"setBackground\(\s*[\"'](#fff|#ffffff)[\"']\s*\)", text, re.I), name
        assert "on_theme_change(" in text, f"{name} 未订阅主题刷新"


def test_canvas_theme_helper_present():
    """9 个 pyqtgraph 文件走同一 helper；matplotlib 画布走恢复式 helper。"""
    for name in CANVAS_FILES:
        text = _read(name)
        if name == "spectrogram3d.py":
            assert "_restore_canvas_theme" in text, name
            assert "_style_mpl_figure" in text, name
        else:
            assert "_apply_canvas_theme" in text, name


def test_piano_key_face_hex_removed():
    """键面六种硬编码 hex 已全部令牌化（定案 F‴）。"""
    for name in ("freq_axis.py", "spectrum.py"):
        text = _read(name)
        for literal in _KEY_FACE_HEX:
            assert literal not in text, f"{name} 仍含键面硬编码 {literal}"


def test_theme_api_untouched_by_canvas_task():
    """定案 A‴：不得新增 THEMES 色角色 / 不改 ui/theme.py 的角色表。"""
    theme_src = (
        Path(__file__).resolve().parent.parent
        / "src" / "acouscope" / "ui" / "theme.py"
    ).read_text(encoding="utf-8")
    roles = theme.TOKENS["neutral"]["roles"]
    assert roles == [
        "bg0", "bg1", "bg2", "bg3", "border", "border_strong",
        "text", "text_sub", "text_faint", "accent", "accent_text", "sel_bg",
    ]
    for theme_id in ("dark", "light"):
        entry = theme.THEMES[theme_id]
        assert set(roles) <= set(entry)
    # 主题集不降（既有硬锁的轻量复述，避免依赖 test_theme_tokens 执行顺序）
    assert len(theme.THEME_ORDER) >= 10
    assert "TOKENS" in theme_src and "semantic" in theme_src


def test_i18n_not_touched_by_canvas_task():
    """定案 J‴：本任务零新文案（i18n 不出现画布主题相关键）。"""
    i18n_path = (
        Path(__file__).resolve().parent.parent
        / "src" / "acouscope" / "i18n" / "__init__.py"
    )
    text = i18n_path.read_text(encoding="utf-8").lower()
    assert "canvas" not in text, "i18n 出现未申报的画布文案键"
