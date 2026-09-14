# SPDX-License-Identifier: GPL-3.0-only
"""T-1044 图表设计器 P1（导出前设计交互）测试。

覆盖放行令 RELEASE_T-1044「验证 §5 专项断言 ①~⑪」：
  ① 配色真实生效（逐色 ∈ COLOR_PALETTES）/ ② viridis 分支（cmap 不炸）
  ③ 未知 palette 回退 default（不抛）/ ④ exporters.py 源码 hex = 0
  ⑤ 导出恒白底（四角像素）/ ⑥ 零 rcParams 颜色污染 / ⑦ 向后兼容
  ⑧ 预览与导出同源（同一 `_export_current_view` 路径抽核）
  ⑨ 开关语义（checkable + 再点即关 + 可见 ✕）/ ⑩ EXPORT_INK ↔ theme.data_ink(light)
  ⑪ 静态纪律（无 QDialog/模态、新增代码 hex·px = 0、未新增 ICONS 名、禁词 0）
另含 Step 0 结论落地（防抖档 + 重图降采样步长）与持久化两层（会话 + 全局默认）。

夹具参照 tests/test_toggle_semantics.py：qapp（conftest）+ window（**不 show**）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QFileDialog, QFrame, QPushButton

from acouscope.app.controller import AppController
from acouscope.i18n import tr
from acouscope.ui import theme
from acouscope.ui.main_window import MainWindow
from acouscope.visualization.exporters import FigureExporter
from acouscope.visualization.mpl_style import (
    COLOR_PALETTES,
    EXPORT_INK,
    JOURNAL_TEMPLATES,
    palette_cycle,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src" / "acouscope"
_EXPORTERS = _SRC / "visualization" / "exporters.py"
_DESIGNER = _SRC / "ui" / "widgets" / "chart_designer.py"
_MAIN_WINDOW = _SRC / "ui" / "main_window.py"

# 禁词以拼接构造，避免本文件自身被扫中（同 test_report_export.py 口径）
_BANNED = "Mel" + "odyne"
_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_PX = re.compile(r"\d+px")


# ---------------------------------------------------------------------------
# 夹具 / 工具
# ---------------------------------------------------------------------------


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """主窗口（不 show()）；HOME 与数据目录隔离到 tmp_path。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 2.0)) / sr
    controller.load_from_array(0.2 * np.sin(2 * np.pi * 440.0 * t), sr)
    w = MainWindow(controller)
    yield w
    w.close()


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def _capture_export_colors(monkeypatch, exporter, call) -> dict:
    """捕获取色证据：真实渲染的 figure 上逐 artist 取色（比像素更确定）。

    `_save` 被打桩为「读 figure → 不落盘」，故断言的是**渲染路径真实产物**。
    """
    seen: dict = {}

    def fake_save(fig, output_path, fmt, dpi):  # noqa: ANN001
        ax = fig.axes[0]
        seen["lines"] = [ln.get_color() for ln in ax.get_lines()]
        seen["face"] = fig.get_facecolor()
        return Path(output_path)

    monkeypatch.setattr(exporter, "_save", fake_save)
    call(exporter)
    return seen


def _waveform(dpi: int = 72):
    t = np.arange(4000) / 8000.0
    return t, (0.5 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)


def _spectrogram_data():
    freqs = np.linspace(0, 4000, 129)
    times = np.linspace(0, 1.0, 200)
    rng = np.random.default_rng(1044)
    return freqs, times, rng.random((129, 200)).astype(np.float32)


# ---------------------------------------------------------------------------
# ① / ② / ③ 取色 API
# ---------------------------------------------------------------------------


def test_palette_cycle_copy_none_and_unknown_fallback():
    """③ 未知 palette → 回退 default 副本（不抛）；② viridis/inferno → None。"""
    seq = palette_cycle("colorblind")
    assert seq == COLOR_PALETTES["colorblind"]
    seq.append("#000000")
    assert "#000000" not in COLOR_PALETTES["colorblind"], "必须返回副本，不得改数据源"

    assert palette_cycle("viridis") is None
    assert palette_cycle("inferno") is None
    assert palette_cycle("no-such-palette") == COLOR_PALETTES["default"]


def test_export_line_colors_follow_palette(monkeypatch, tmp_path):
    """① 配色真实生效：序列线逐色取自所选调色板（default / colorblind / grayscale）。"""
    times, signal = _waveform()
    for name in ("default", "colorblind", "grayscale"):
        exporter = FigureExporter(palette=name)
        seen = _capture_export_colors(
            monkeypatch, exporter,
            lambda e: e.export_waveform(times, signal, tmp_path / f"w_{name}.png", fmt="png", dpi=72),
        )
        # 波形：line[0] = 数据序列，line[1] = 零轴基线（结构线，不走调色板）
        assert seen["lines"][0] == COLOR_PALETTES[name][0], name
        assert seen["lines"][1] == EXPORT_INK["axis"], name
        assert seen["lines"][1] not in COLOR_PALETTES[name], name


def test_reference_line_does_not_follow_palette(monkeypatch, tmp_path):
    """① / R5：谐波标记竖线属**参考线族** → 取中性墨色，禁随调色板变色。"""
    freqs = np.linspace(0, 2000, 256)
    mag = np.linspace(-80, 0, 256)
    exporter = FigureExporter(palette="colorblind")
    seen = _capture_export_colors(
        monkeypatch, exporter,
        lambda e: e.export_spectrum(
            freqs, mag, tmp_path / "s.png", fmt="png", dpi=72,
            markers=[(440.0, "A4")],
        ),
    )
    colors = seen["lines"]
    assert colors[0] == COLOR_PALETTES["colorblind"][0]
    assert colors[-1] == EXPORT_INK["ref_line"]
    assert colors[-1] not in COLOR_PALETTES["colorblind"]


def test_formant_series_colors_follow_palette(monkeypatch, tmp_path):
    """① 多序列（共振峰 F1~F4）逐序取palette[0..3]。"""
    times = np.arange(50) / 50.0
    formants = np.column_stack([
        500 + 10 * np.arange(50),
        1500 + 20 * np.arange(50),
        2500 + 30 * np.arange(50),
        3500 + 40 * np.arange(50),
    ]).astype(np.float32)
    exporter = FigureExporter(palette="colorblind")
    seen = _capture_export_colors(
        monkeypatch, exporter,
        lambda e: e.export_formants(times, formants, tmp_path / "f.png", fmt="png", dpi=72),
    )
    assert seen["lines"] == COLOR_PALETTES["colorblind"][:4]


def test_viridis_branch_uses_colormap(monkeypatch, tmp_path):
    """② viridis：无离散序列色（None）→ 序列回退 default、热图走 colormap，不炸。"""
    exporter = FigureExporter(palette="viridis")
    assert exporter._cmap("magma") == "viridis"
    assert exporter._series_color(0) == COLOR_PALETTES["default"][0]
    assert FigureExporter(palette="default")._cmap("magma") == "magma"
    assert FigureExporter(palette="inferno")._cmap("viridis") == "inferno"

    freqs, times, matrix = _spectrogram_data()
    assert exporter.export_spectrogram(
        freqs, times, matrix, tmp_path / "sp.png", fmt="png", dpi=72
    ).exists()
    mfcc = np.random.default_rng(7).random((200, 13)).astype(np.float32)
    assert exporter.export_mfcc(
        times, mfcc, tmp_path / "mfcc.png", fmt="png", dpi=72
    ).exists()


# ---------------------------------------------------------------------------
# ④ / ⑤ / ⑥ 静态与白底 / 零污染
# ---------------------------------------------------------------------------


def test_exporters_source_has_no_hex_literals():
    """④ 源码级：exporters.py 内 `#hex` 命中 = 0。"""
    text = _EXPORTERS.read_text(encoding="utf-8")
    assert not _HEX.findall(text), "exporters.py 仍有硬编码 hex 色值"


def test_export_white_background_four_corners(tmp_path):
    """⑤ 导出恒白底：各 palette 下 PNG 四角像素为白（复用 T-1032 像素手法）。"""
    from PIL import Image

    times, signal = _waveform()
    for name in ("default", "grayscale", "colorblind", "viridis"):
        path = FigureExporter(palette=name).export_waveform(
            times, signal, tmp_path / f"bg_{name}.png", fmt="png", dpi=72
        )
        with Image.open(path) as im:
            rgb = im.convert("RGB")
            w, h = rgb.size
            corners = [
                rgb.getpixel((0, 0)), rgb.getpixel((w - 1, 0)),
                rgb.getpixel((0, h - 1)), rgb.getpixel((w - 1, h - 1)),
            ]
        assert corners == [(255, 255, 255)] * 4, (name, corners)


def test_no_rcparams_color_pollution(tmp_path):
    """⑥ 零全局污染：操作前后 rcParams 颜色项逐值不变。"""
    from matplotlib import rcParams

    def snapshot() -> dict:
        return {
            k: repr(v) for k, v in rcParams.items() if "color" in k or "cmap" in k
        }

    before = snapshot()
    times, signal = _waveform()
    freqs, times_s, matrix = _spectrogram_data()
    for name in ("default", "colorblind", "grayscale", "viridis"):
        exporter = FigureExporter(palette=name, grid=False)
        exporter.export_waveform(times, signal, tmp_path / f"w_{name}.png", fmt="png", dpi=72)
        exporter.export_spectrogram(freqs, times_s, matrix, tmp_path / f"s_{name}.png", fmt="png", dpi=72)
    assert snapshot() == before


# ---------------------------------------------------------------------------
# ⑦ 向后兼容
# ---------------------------------------------------------------------------


def test_backward_compatible_constructor_and_defaults(tmp_path):
    """⑦ 既有调用形式（不给新参数）行为不变：默认 palette=default / 画幅随模板 / 网格开。"""
    exporter = FigureExporter(font_latin="auto", font_cjk="auto")
    assert exporter.palette == "default"
    assert exporter.width is None and exporter.height is None
    assert exporter.grid is True
    assert exporter._linewidth(0.8) == 0.8
    times, signal = _waveform()
    out = exporter.export_waveform(times, signal, tmp_path / "compat.png", fmt="png", dpi=72)
    assert out.exists() and out.stat().st_size > 0


def test_new_params_are_keyword_only():
    """⑦ 新参数一律 keyword-only（位置参数仅前四个，签名零破坏）。"""
    import inspect

    sig = inspect.signature(FigureExporter.__init__)
    positional = [
        name for name, p in sig.parameters.items()
        if p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD and name != "self"
    ]
    assert positional == ["template", "language", "font_latin", "font_cjk"]
    for name in ("palette", "ref_ink", "line_width", "width", "height", "grid"):
        assert sig.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY, name
        assert sig.parameters[name].default is not inspect.Parameter.empty, name


def test_report_figure_path_still_works(window, monkeypatch, tmp_path):
    """⑦ 报告插图路径（既有调用形式 `_export_current_view(exporter, 0, p, "png")`）仍工作。"""
    latin, cjk = window._current_chart_fonts()
    exporter = FigureExporter(font_latin=latin, font_cjk=cjk)
    out = window._export_current_view(exporter, 0, tmp_path / "wave.png", "png")
    assert Path(out).exists()


# ---------------------------------------------------------------------------
# ⑧ / ⑨ 入口、开关语义、同源
# ---------------------------------------------------------------------------


def test_entry_is_switch_and_drawer_has_visible_close(window):
    """⑨ 入口为开关（再点即关）+ 抽屉有可见 ✕（drawerCloseBtn，复用既有构件）。"""
    act = window.action_chart_designer
    assert act.isCheckable() is True

    act.trigger()
    drawer = window._chart_designer_drawer
    assert drawer.is_open() is True
    header = drawer.findChild(QFrame, "drawerHeader")
    assert header is not None
    btn = drawer.findChild(QPushButton, "drawerCloseBtn")
    assert btn is not None and not btn.isHidden() and btn.toolTip()

    act.trigger()  # 同一入口再点 = 关闭（幂等 toggle）
    assert drawer.is_open() is False
    assert act.isChecked() is False


def test_two_entries_share_one_action(window):
    """⑨ 两处入口（文件▸导出 与 分析工具栏）**共用同一 QAction 实例**。"""
    from PyQt6.QtWidgets import QMenu

    act = window.action_chart_designer
    hosts = [m for m in window.findChildren(QMenu) if any(a is act for a in m.actions())]
    assert hosts, "菜单入口缺失"
    assert any(m.title() == tr("menu.export") for m in hosts), [m.title() for m in hosts]

    analysis_tb = window.btn_ai_interpret.parent()
    assert any(a is act for a in analysis_tb.actions()), "分析工具栏入口缺失"
    # 同一实例只出现一次于工具栏（禁重复挂载）
    assert [a for a in analysis_tb.actions() if a is act].__len__() == 1


def test_close_button_releases_entry(window):
    """⑨ 可见 ✕ 关闭 → 入口勾选态反同步（T-1043 注册表复用，零新造）。"""
    window.action_chart_designer.trigger()
    drawer = window._chart_designer_drawer
    drawer.btn_close.click()
    assert drawer.is_open() is False
    assert window.action_chart_designer.isChecked() is False


def test_preview_and_export_share_one_path(window, monkeypatch, tmp_path):
    """⑧ 预览与导出同源：同一 `_export_current_view` 路径 + 同一 exporter 构造。"""
    window.action_chart_designer.trigger()
    panel = window._chart_designer_drawer.content()
    panel.cmb_palette.setCurrentIndex(panel.cmb_palette.findData("colorblind"))
    assert window._current_chart_designer_params()["palette"] == "colorblind"

    calls: list = []

    def spy(exporter, mode, path, fmt, **kwargs):
        calls.append({
            "cls": type(exporter).__name__,
            "palette": exporter.palette,
            "fmt": fmt,
            "dpi": kwargs.get("dpi"),
            "preview": bool(kwargs.get("preview")),
        })
        return Path(path)

    monkeypatch.setattr(window, "_export_current_view", spy)

    preview_path = tmp_path / "preview.png"
    assert window._render_chart_designer_preview(preview_path, 72, True) is True
    assert panel.render_now() is True

    target = tmp_path / "out.png"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (str(target), "PNG 位图 (*.png)")),
    )
    window._on_chart_designer_export()

    assert len(calls) == 3
    assert calls[0]["preview"] is True and calls[0]["dpi"] == 72
    assert calls[1]["preview"] is True and calls[1]["dpi"] == 72
    assert calls[2]["preview"] is False and calls[2]["dpi"] == 300
    assert {c["cls"] for c in calls} == {"FigureExporter"}
    assert {c["palette"] for c in calls} == {"colorblind"}


def test_preview_refreshes_on_param_change(window, tmp_path):
    """验收口径 1：改一项 → 预览刷新（`previewUpdated` 有断言）。"""
    window.action_chart_designer.trigger()
    panel = window._chart_designer_drawer.content()
    seen: list = []
    panel.previewUpdated.connect(seen.append)

    panel.cmb_palette.setCurrentIndex(panel.cmb_palette.findData("grayscale"))
    assert seen and seen[-1] is True

    panel.chk_grid.setChecked(not panel.chk_grid.isChecked())
    assert seen[-1] is True


# ---------------------------------------------------------------------------
# Step 0 结论落地 + 参数区规范 + 持久化
# ---------------------------------------------------------------------------


def test_step0_strategy_landed(window, qapp):
    """Step 0：轻图实时（不防抖）/ 重图防抖 200ms + 降采样步长口径。"""
    from acouscope.ui.widgets import chart_designer as cd

    assert cd.PREVIEW_DPI == 72
    assert cd.PREVIEW_DEBOUNCE_MS == 200
    assert cd.HEAVY_MODES == (2, 5)
    assert MainWindow._preview_stride(3000, 500) == 6
    assert MainWindow._preview_stride(200, 500) == 1

    panel = cd.ChartDesignerPanel(settings=None)
    rendered: list = []
    panel.set_preview_renderer(lambda *a, **k: rendered.append(a) or False)

    panel.set_mode_provider(lambda: 2)          # 语谱图 = 重图 → 防抖
    panel.schedule_preview()
    assert panel._timer.isActive() is True
    assert rendered == []

    panel.set_mode_provider(lambda: 0)          # 波形 = 轻图 → 立即
    panel.schedule_preview()
    assert panel._timer.isActive() is False
    assert len(rendered) == 1


def test_panel_four_groups_three_segment_and_range_hints(qapp):
    """§五-7 三段式 + §五-8 参数范围可见性（禁裸数字框）：四组 + 端点提示。"""
    from acouscope.ui.widgets.chart_designer import ChartDesignerPanel, _ParamField
    from acouscope.ui.widgets.panels import SectionHeader

    panel = ChartDesignerPanel(settings=None)
    titles = [s.title() for s in panel.findChildren(SectionHeader)]
    assert titles == [
        tr("chart_designer.group.layout"),
        tr("chart_designer.group.palette"),
        tr("chart_designer.group.font"),
        tr("chart_designer.group.export"),
    ]
    fields = panel.findChildren(_ParamField)
    assert len(fields) >= 6, "三段式参数列缺失"
    for field in fields:
        assert field.name_label.text(), "参数名（三段式第一段）缺失"

    def _hint(ctrl) -> str:
        return next(f.unit_label.text() for f in fields if f.isAncestorOf(ctrl))

    assert _hint(panel.spn_width) == "2.0 – 12.0 in"
    assert _hint(panel.spn_height) == "1.5 – 10.0 in"
    assert _hint(panel.spn_dpi) == "72 – 1200"
    # 7 套期刊模板全在列；配色只暴露 4 档（inferno 登记不暴露）
    assert panel.cmb_template.count() == len(JOURNAL_TEMPLATES) == 7
    assert [panel.cmb_palette.itemData(i) for i in range(panel.cmb_palette.count())] == [
        "default", "grayscale", "colorblind", "viridis",
    ]
    assert panel.cmb_format.count() == len(FigureExporter.SUPPORTED_FORMATS) == 6


def test_two_layer_persistence(window, monkeypatch):
    """持久化两层：① 会话（内存）② 全局默认（Settings + 落盘）；项目级留 P3。"""
    window.action_chart_designer.trigger()
    panel = window._chart_designer_drawer.content()
    panel.cmb_palette.setCurrentIndex(panel.cmb_palette.findData("colorblind"))
    panel.spn_dpi.setValue(600)

    params = window._current_chart_designer_params()
    assert params["palette"] == "colorblind" and params["dpi"] == 600

    saved: list = []
    monkeypatch.setattr(window.controller.settings, "save", lambda *a, **k: saved.append(1))
    window._persist_chart_designer_defaults()
    settings = window.controller.settings
    assert settings.chart_designer_palette == "colorblind"
    assert settings.default_dpi == 600
    assert saved == [1]


def test_settings_clamp_chart_designer_fields(tmp_path):
    """② 全局默认钳位：非法/越界一律回退（画幅 0.0 = 用模板值；配色回退 default）。"""
    from acouscope.utils.config import Settings

    bad = tmp_path / "settings.json"
    bad.write_text(json.dumps({
        "chart_designer_palette": "   ",
        "chart_designer_figsize_w": 99.0,
        "chart_designer_figsize_h": 0.2,
        "chart_designer_grid": False,
    }), encoding="utf-8")
    settings = Settings.load(bad)
    assert settings.chart_designer_palette == "default"
    assert settings.chart_designer_figsize_w == 0.0
    assert settings.chart_designer_figsize_h == 0.0
    assert settings.chart_designer_grid is False

    good = tmp_path / "settings2.json"
    good.write_text(json.dumps({
        "chart_designer_palette": "colorblind",
        "chart_designer_figsize_w": 6.0,
        "chart_designer_figsize_h": 4.0,
    }), encoding="utf-8")
    ok = Settings.load(good)
    assert ok.chart_designer_palette == "colorblind"
    assert (ok.chart_designer_figsize_w, ok.chart_designer_figsize_h) == (6.0, 4.0)


# ---------------------------------------------------------------------------
# ⑩ / ⑪ 对账与静态纪律
# ---------------------------------------------------------------------------


def test_export_ink_reconciles_with_theme_light():
    """⑩ 导出侧墨色与主题同源对账（theme 仍是唯一权威源，漂移即红）。"""
    light = theme.THEMES["light"]
    assert EXPORT_INK["ref_line"] == theme.data_ink("ref_line", light)
    assert EXPORT_INK["axis"] == theme.data_ink("ref_line", light)
    for value in EXPORT_INK.values():
        assert value in theme._LIGHT_DATA.values()  # noqa: SLF001 (对账口径)


def test_static_discipline_new_code():
    """⑪ 静态：无 QDialog/模态、hex·px = 0、未新增 ICONS 名、禁词 0、无 show()。"""
    text = _DESIGNER.read_text(encoding="utf-8")
    assert "Q" + "Dialog" not in text
    assert not _HEX.findall(text), "设计器面板含硬编码 hex"
    assert not _PX.findall(text), "设计器面板含数值 px 字面量"
    assert _BANNED not in text
    assert "show()" not in text
    assert "style_when_theme" in text, "样式必须经 theme 注册（禁旁路 setStyleSheet）"
    assert "setStyleSheet" not in text

    main_text = _MAIN_WINDOW.read_text(encoding="utf-8")
    assert not _HEX.findall(main_text), "main_window 新增块含硬编码 hex"
    assert len(theme.ICONS) == 30, "禁新增 theme.ICONS 逻辑名（T-1025 授权扩容 21→30：track/add_track/solo/mute/align/volume/room_modal/room_acoustic/chart_designer）"


# ---------------------------------------------------------------------------
# T-1052 设计器「预览/导出」导出等效白底（修 mode==6 抓屏幕态缺陷）
# ---------------------------------------------------------------------------


def _tone(dur: float = 1.5, f0: float = 440.0, sr: int = 44100):
    """含 4 次谐波的稳定乐音（3D 频谱图用）。"""
    t = np.arange(int(sr * dur)) / sr
    sig = np.zeros_like(t)
    for k in (1, 2, 3, 4):
        sig += 0.5 / k * np.sin(2 * np.pi * f0 * k * t)
    return sig, sr


def _png_corners(path) -> list:
    """读 PNG 四角像素（复用 T-1032 像素手法）。"""
    from PIL import Image

    with Image.open(path) as im:
        rgb = im.convert("RGB")
        w, h = rgb.size
        return [
            rgb.getpixel((0, 0)), rgb.getpixel((w - 1, 0)),
            rgb.getpixel((0, h - 1)), rgb.getpixel((w - 1, h - 1)),
        ]


def test_mode6_no_hardcoded_white_in_main_window():
    """T-1052：`facecolor=\"white\"` 字面在 main_window 命中 = 0（改走 EXPORT_FACE）。"""
    text = _MAIN_WINDOW.read_text(encoding="utf-8")
    assert 'facecolor="white"' not in text, "mode==6 分支仍硬编码白框字面"


def test_mode6_delegates_to_widget_export_entry(window, monkeypatch, tmp_path):
    """T-1052 ⑥：mode==6 分支委托 widget.export_current_view（不再直接抓画布只设白框）。

    伪造 widget（带 `_stft_times` 非空）→ 若分支仍直接访问 `widget.canvas.print_figure`
    会因无 `canvas` 属性而 AttributeError；改委后仅调用 `export_current_view`。
    """
    calls: list = []

    class _FakeWidget:
        _stft_times = [0.0]

        def export_current_view(self, path, *, fmt="png", dpi=300):
            calls.append((str(path), fmt, dpi))

    monkeypatch.setattr(window, "_live_widget", lambda name: _FakeWidget())
    exporter = window._build_chart_exporter()
    out = window._export_current_view(
        exporter, 6, tmp_path / "m6.png", "png", dpi=72, preview=True
    )
    assert str(out) == str(tmp_path / "m6.png")
    assert calls == [(str(tmp_path / "m6.png"), "png", 72)]


def test_3d_export_current_view_white_and_theme_restored(qapp, tmp_path):
    """T-1052 ②/④：3D 导出等效白底 + 导出后屏幕主题恢复（不留白副作用）。"""
    from acouscope.ui.widgets.spectrogram3d import Spectrogram3DWidget

    widget = Spectrogram3DWidget()
    sig, sr = _tone()
    widget.set_audio(sig, sr)
    widget.canvas.draw()
    before = widget.figure.get_facecolor()  # 屏幕主题（暗）
    out = tmp_path / "m3d_preview.png"
    widget.export_current_view(out, fmt="png", dpi=72)
    after = widget.figure.get_facecolor()
    try:
        assert after == before, (before, after)  # R5：屏幕主题已恢复
        assert _png_corners(out) == [(255, 255, 255)] * 4
    finally:
        widget.close()


@pytest.mark.parametrize("mode", list(range(7)))
def test_preview_white_background_all_modes(mode, qapp, tmp_path):
    """T-1052 ③：设计器作用于当前活动视图 → 7 个模式预览（72dpi）四角皆白。

    mode 0..5 走 exporter 新建图（与 main_window 各分支同一渲染实现）；
    mode 6 走 3D 导出等效白底入口（R4：预览与导出同源，仅 DPI 不同）。
    """
    out = tmp_path / f"preview_mode{mode}.png"
    if mode == 6:
        from acouscope.ui.widgets.spectrogram3d import Spectrogram3DWidget

        widget = Spectrogram3DWidget()
        sig, sr = _tone()
        widget.set_audio(sig, sr)
        widget.canvas.draw()
        widget.export_current_view(out, fmt="png", dpi=72)
        widget.close()
    else:
        exporter = FigureExporter()
        if mode == 0:
            t, s = _waveform()
            exporter.export_waveform(t, s, out, fmt="png", dpi=72)
        elif mode == 1:
            exporter.export_spectrum(
                np.linspace(0, 4000, 256), np.linspace(-80, 0, 256),
                out, fmt="png", dpi=72,
            )
        elif mode == 2:
            freqs, times, matrix = _spectrogram_data()
            exporter.export_spectrogram(freqs, times, matrix, out, fmt="png", dpi=72)
        elif mode == 3:
            exporter.export_pitch_contour(
                np.linspace(0, 1, 100), 440 * np.ones(100), out, fmt="png", dpi=72
            )
        elif mode == 4:
            formants = np.column_stack(
                [400 + 100 * i * np.ones(60) for i in range(4)]
            ).astype(np.float32)
            exporter.export_formants(
                np.linspace(0, 1, 60), formants, out, fmt="png", dpi=72
            )
        elif mode == 5:
            mfcc = np.random.default_rng(7).random((200, 13)).astype(np.float32)
            exporter.export_mfcc(
                np.linspace(0, 1, 200), mfcc, out, fmt="png", dpi=72
            )
    assert _png_corners(out) == [(255, 255, 255)] * 4, f"mode {mode} 预览非白底"
