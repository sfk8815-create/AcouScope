# SPDX-License-Identifier: GPL-3.0-only
"""PI-G4a-1 / G4a-4 布局预算守卫。

G4a-1 口径（G4a-1 设计约定 §2.2）：
  1. `MetadataBar.minimumSizeHint().width() <= 520`（D3：不再把 analysis_panel 顶宽）；
  2. 源码浅色 hex 计数 `== 0`（D7：色值一律走 `theme.colors()` 令牌）；
  3. `apply_theme("dark")` 后文件名声明色 vs `colors()["bg2"]` 对比度 `>= 4.5`
     （WCAG AA 小字；声明色取 QLabel 调色板，不取像素）。

G4a-4 口径（PI-G4a-4 六视图工具行溢出）：
  4. 逐页 `minimumSizeHint().width()` 预算：FFT / 语谱图 / 共振峰 `<= 620`、
     3D `<= 700`（工具行改 QToolBar 后由 Qt overflow 接管，不再把整页顶宽）；
  5. 750 宽「截断控件数」`== 0`（判定式 `have < minimumSizeHint`，扣页面顶层）；
  6. 工具行必须是 QToolBar（不可拖动/不可浮动）且窄宽下扩展入口真实出现；
  7. 本轮改动文件零新增中文硬编码（汇点口径复用 G-2a 守卫的扫描器）。

G4a-4-Δ2 口径（限高换机制：不钉高，清工具行内部上下边距）：
  8. 逐页 `tool_row.height() <= 40`。行高不写死：QSS `padding` 于 Δ3 归零，
     行高由「可见子件最小高」自然导出（实测 36/37）；`_zero_row_vmargins`
     只作个别风格/平台写回上下边距时的兜底（正常路径早退）。
     必须在**生产入口基座**（Fusion + 全局字号）下测：不施基座时自然高只有 30
     上下，`<= 40` 会退化成恒真断言（无守护力）。
  9. 逐页工具行可见子件 `height() >= minimumSizeHint().height()`（禁「压子件换
     行高」：`setFixedHeight(38)` 时代，子件被压到 26 < 其最小高 36）。

G4a-4-Δ3 口径（子件不得越出行底）：
 10. 逐页工具行可见子件 `mapTo(row).y() + height() <= row.height()`。第 8/9 条
     查不出「装不下」：`height()` 合格、子件也没被压扁，但行内定位偏移让每个
     子件底边越出 6 px（底描边与底圆角被父件裁掉）。

G4a-2 口径（画布让位下限 + 传输条收口 + 侧栏并发上限）：
 11. `TransportBar().minimumSizeHint().width() <= 620`（生产入口基座：Fusion +
     `typography.body` 字号 + `apply_theme("dark")`；finally 还原主题/字体）。
 12. 1000×700 + 开「设置」与「AI 释图」后：`waveform_widget.width() >= 400`
     且 `isVisible()`（D1：画布不被面板挤到 0）。
 13. 侧栏并发上限：连开左栏 2 页 + 右栏 2 页后，可见面板数 == 2（1 左 1 右），
     且两侧当前页 == 最后打开的那页（互斥函数先关旧页）。

离屏、不 `show()` 主窗、不触网；本文件各条断言同进程合计 < 8 s。
（第 12/13 条例外：需要真实几何/可见性，故 fixture 内 `show()` 离屏主窗。）
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QFont, QPalette
from PyQt6.QtWidgets import QApplication, QToolBar, QToolButton, QWidget

from acouscope.audio.io import AudioInfo
from acouscope.ui import theme
from acouscope.ui.widgets.metadata_bar import MetadataBar

_SRC = (
    Path(__file__).resolve().parents[1]
    / "src" / "acouscope" / "ui" / "widgets" / "metadata_bar.py"
)
# D7 原 7 处写死浅色 + 同族近白（f9fafb/fff）一并禁用
_LIGHT_HEX = re.compile(r"#(?:ffffff|fff|e5e7eb|111827|374151|6b7280|f9fafb|d1d5db)", re.I)

# 60 字符文件名（含 CJK 宽字）+ 完整参数 + 峰值统计：最不利夹具
_FILENAME = "2026-10-18_现场录音_维也纳金色大厅_第三乐章_完整版_母带_48k24bit_final.wav"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _fake_info() -> AudioInfo:
    return AudioInfo(
        filepath="/tmp/" + _FILENAME,
        duration=327.45,
        sample_rate=48000,
        channels=2,
        samples=15717600,
        bit_depth=24,
        format="WAV",
        file_size=94_310_400,
    )


def _fake_data() -> np.ndarray:
    rng = np.random.default_rng(7)
    return (0.4 * rng.standard_normal(48000)).astype(np.float32)


def _luminance(hexcolor: str) -> float:
    """WCAG 相对亮度。"""
    raw = hexcolor.lstrip("#")
    chans = []
    for i in (0, 2, 4):
        v = int(raw[i:i + 2], 16) / 255
        chans.append(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * chans[0] + 0.7152 * chans[1] + 0.0722 * chans[2]


def _contrast(fg: str, bg: str) -> float:
    la, lb = _luminance(fg), _luminance(bg)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def test_metadata_bar_min_width_budget(qapp):
    """D3：三段全文进条，最小宽仍须 ≤ 520（否则向上顶宽 analysis_panel）。"""
    bar = MetadataBar()
    bar.set_info(_fake_info(), _fake_data(), 48000)
    width = bar.minimumSizeHint().width()
    assert width <= 520, f"MetadataBar.minimumSizeHint().width()={width} > 520"


def test_metadata_bar_has_no_light_hex(qapp):
    """D7：色值一律取 theme.colors()，源码不得残留浅色 hex。"""
    hits = _LIGHT_HEX.findall(_SRC.read_text(encoding="utf-8"))
    assert hits == [], f"metadata_bar.py 残留浅色 hex：{hits}"


def test_metadata_bar_dark_filename_contrast(qapp):
    """D7：暗色下文件名声明色对比度须达 WCAG AA 小字 4.5。"""
    theme.apply_theme("dark")
    bar = MetadataBar()
    bar.set_info(_fake_info(), _fake_data(), 48000)
    bar.lbl_filename.ensurePolished()
    fg = bar.lbl_filename.palette().color(QPalette.ColorRole.WindowText).name()
    bg = theme.colors()["bg2"]
    ratio = _contrast(fg, bg)
    assert ratio >= 4.5, f"dark 文件名对比度 {ratio:.2f} < 4.5（{fg} on {bg}）"


# ======================================================================
# G4a-4：六视图工具行溢出（先 FFT，再语谱图/3D）
# ======================================================================

_UI_DIR = Path(__file__).resolve().parents[1] / "src" / "acouscope" / "ui"
# 本轮改动文件（中文硬编码零新增的扫描面）
_G4A4_FILES = (
    "widgets/spectrum.py",
    "widgets/spectrogram.py",
    "widgets/spectrogram3d.py",
    "widgets/formants.py",
    "widgets/timbre.py",
)
# 逐页最小宽预算（PI-G4a-4 判据 A2）
_MIN_W_BUDGET = {"FFT": 620, "语谱图": 620, "3D": 700, "共振峰": 620}
_SQUEEZE_W = 750


def _make_views():
    """按产品构建路径建四个视图页（FFT / 语谱图 / 3D / 共振峰）。

    均灌入真实形状的数据：空控件的 minimumSizeHint 偏小（FFT 空页 213、
    有数据 477），不灌数据等于把判据放宽。
    """
    from acouscope.ui.widgets.formants import FormantWidget
    from acouscope.ui.widgets.spectrogram import SpectrogramWidget
    from acouscope.ui.widgets.spectrogram3d import Spectrogram3DWidget
    from acouscope.ui.widgets.spectrum import SpectrumWidget

    sr = 8000
    t = np.arange(int(sr * 20.0)) / sr
    sig = 0.5 * np.sin(2 * np.pi * (200 + 300 * t) * t)

    freqs = np.linspace(0.0, sr / 2, 2048)
    mag = np.exp(-((freqs - 440.0) ** 2) / (2 * 40.0 ** 2)) + 0.02
    fft = SpectrumWidget()
    fft.set_data(freqs, mag, "FFT (20.000s)", sample_rate=sr, signal_data=sig)

    ft = np.linspace(0.0, sr / 2, 256)
    tt = np.linspace(0.0, 20.0, 400)
    spec_db = -60.0 + 55.0 * np.exp(-((ft[:, None] - 440.0) ** 2) / 2e4)
    spec = SpectrogramWidget()
    spec.set_data(ft, tt, np.broadcast_to(spec_db, (256, 400)), sr)

    d3 = Spectrogram3DWidget()
    d3.set_audio(sig, sr)

    times = np.linspace(0.0, 20.0, 400)
    fr = np.tile(np.array([[700.0, 1200.0, 2600.0]]), (400, 1))
    bws = np.tile(np.array([[80.0, 90.0, 120.0]]), (400, 1))
    formants = FormantWidget()
    formants.set_data(times, fr, bws)

    return {"FFT": fft, "语谱图": spec, "3D": d3, "共振峰": formants}


@pytest.fixture(scope="module")
def views(qapp):
    return _make_views()


def _squeeze(page, width=_SQUEEZE_W, height=900):
    """把页面挂到无布局宿主上并压到指定宽（离屏 show，不建主窗）。

    直接 `page.resize()` 对顶层窗无效（Qt 会按 sizeHint 顶回），故用
    「无布局宿主 + setGeometry」：宿主定死，页面拿到真实窄宽。
    """
    host = QWidget()
    page.setParent(host)
    page.setGeometry(0, 0, width, height)
    host.resize(width + 10, height + 20)
    host.show()
    page.show()
    QApplication.processEvents()
    return host


def _truncated(page):
    """可见子孙中 `have < minimumSizeHint` 的控件（扣页面顶层自身）。"""
    bad = []
    for child in page.findChildren(QWidget):
        if child is page or not child.isVisibleTo(page):
            continue
        need = child.minimumSizeHint().width()
        if child.width() < need:
            text = (child.text() if hasattr(child, "text") else "") or ""
            bad.append(f"{child.__class__.__name__}{text!r}({child.width()}<{need})")
    return bad


def test_view_page_min_width_budget(views):
    """A2：工具行溢出后，逐页最小宽回到预算内（不再顶宽 analysis_panel）。"""
    for name, page in views.items():
        width = page.minimumSizeHint().width()
        budget = _MIN_W_BUDGET[name]
        assert width <= budget, f"{name} 页 minimumSizeHint().width()={width} > {budget}"


def test_view_pages_no_truncation_at_750(views):
    """A3：750 宽下逐页截断控件数为 0（扣页面顶层）。"""
    for name, page in views.items():
        host = _squeeze(page)
        try:
            bad = _truncated(page)
        finally:
            page.setParent(None)
            host.deleteLater()
        assert bad == [], f"{name} 页 750 宽仍有 {len(bad)} 处截断：{bad[:6]}"


def test_tool_row_overflow_entry(views):
    """A4：工具行是 QToolBar（不可拖动/浮动），窄宽下「»」扩展入口真实出现。"""
    page = views["FFT"]
    row = page.tool_row
    assert isinstance(row, QToolBar), f"工具行容器={type(row).__name__}，应为 QToolBar"
    assert row.isMovable() is False, "QToolBar 必须 setMovable(False)"
    assert row.isFloatable() is False, "QToolBar 必须 setFloatable(False)"
    ext = row.findChild(QToolButton, "qt_toolbar_ext_button")
    assert ext is not None, "找不到 QToolBar 扩展按钮（qt_toolbar_ext_button）"

    host = _squeeze(page)
    try:
        assert ext.isVisible(), "750 宽下扩展入口不可见 —— 溢出未生效"
    finally:
        page.setParent(None)
        host.deleteLater()


def test_g4a4_no_new_hardcoded_chinese():
    """A4：本轮改动文件零新增中文硬编码（汇点口径复用 G-2a 扫描器）。"""
    spec = importlib.util.spec_from_file_location(
        "_g2a_guard", Path(__file__).with_name("test_no_hardcoded_ui_strings.py")
    )
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)

    hits = {}
    for rel in _G4A4_FILES:
        found = guard.scan_text((_UI_DIR / rel).read_text(encoding="utf-8"))
        if found:
            hits[rel] = found
    assert hits == {}, f"新增中文硬编码（文件→[(行号, 汇点)]）：{hits}"


# ======================================================================
# G4a-4-Δ：工具行限高（一行 + 一条断言）
# ======================================================================


def _row_child_floor(row):
    """工具行可见子件的 (名字, 最小高, 实际高) —— 用于查「压子件换行高」。"""
    out = []
    for child in row.findChildren(QWidget):
        if child is row or not child.isVisibleTo(row):
            continue
        need = child.minimumSizeHint().height()
        if need < 0:  # 无有效 hint（纯占位 spacer）不计
            continue
        text = (child.text() if hasattr(child, "text") else "") or ""
        out.append((child.__class__.__name__ + repr(text), need, child.height()))
    return out


def test_tool_row_height_budget(views, qapp):
    """Δ2：逐页 `tool_row.height() <= 40` 且不压子件（行高自然导出）。

    口径必须是**生产入口基座**：`__main__.py` 的 Fusion + 全局字号，叠加
    `apply_theme` 的 QSS（控件内边距由 QSS 给）。缺任一环，自然高只有 30 上下，
    `<= 40` 恒真 —— 改坏边距收口也不红，等于没有守护。故本测自带基座。
    """
    prev_style = qapp.style().name()
    prev_font = qapp.font()
    try:
        qapp.setStyle("Fusion")
        font = QFont(prev_font)
        font.setFamilies(theme.ui_font_families())
        font.setPointSize(theme.TOKENS["typography"]["body"])
        qapp.setFont(font)
        theme.apply_theme("dark")

        for name, page in views.items():
            host = _squeeze(page)
            try:
                height = page.tool_row.height()
                kids = _row_child_floor(page.tool_row)
            finally:
                page.setParent(None)
                host.deleteLater()
            assert height <= 40, (
                f"{name} 页 tool_row.height()={height} > 40（上下边距未收口）"
            )
            # Δ2：子件实际高必须 ≥ 自身最小高（禁「压子件换行高」）
            squeezed = [f"{n}({a}<{m})" for n, m, a in kids if a < m]
            assert squeezed == [], (
                f"{name} 页工具行压子件换行高（实际高 < 最小高）：{squeezed[:6]}"
            )

            # Δ3：子件不得越出行底（行高缩到装不下 → 底边/底圆角被裁；
            #      高度断言查不出：height() 合格但 bottom 出界）
            row_h = page.tool_row.height()
            over = []
            for child in page.tool_row.findChildren(QWidget):
                if child is page.tool_row or not child.isVisibleTo(page.tool_row):
                    continue
                bottom = child.mapTo(page.tool_row, QPoint(0, 0)).y() + child.height()
                if bottom > row_h:
                    over.append(f"{child.__class__.__name__}(底{bottom}>{row_h})")
            assert over == [], (
                f"{name} 页工具行子件越出行底（被裁切）：{over[:6]}"
            )
    finally:
        qapp.setStyle(prev_style)
        qapp.setFont(prev_font)


# ======================================================================
# G4a-2：画布让位下限 + 传输条收口 + 侧栏并发上限（断言 11–13）
# ======================================================================

_CANVAS_MIN_W = 560
_TRANSPORT_MIN_W_BUDGET = 620


def _restore_theme(prev_theme_id: str, prev_colors_id):
    """复原主题态（同 test_theme_token_discipline 口径，防跨测试污染）。"""
    if prev_colors_id is None:
        theme._theme_id = "dark"
        theme._current.clear()
        theme._current.update(theme.THEMES["dark"])
    else:
        theme.apply_theme(prev_theme_id)


@pytest.fixture
def main_window(qapp, monkeypatch, tmp_path):
    """带已加载音频的主窗口（离屏 `show()`，供真实几何/可见性读数）。

    HOME + 两处 get_data_dir 全部指向 tmp_path：布局存档不落用户目录。
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg
    import acouscope.ui.widgets.panels.workspace as _ws

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(_ws, "get_data_dir", lambda: tmp_path)

    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 20.0)) / sr
    controller.load_from_array(0.5 * np.sin(2 * np.pi * (200 + 300 * t) * t), sr)

    win = MainWindow(controller)
    win.resize(1000, 700)
    win.show()
    qapp.processEvents()
    yield win
    win.close()


def _visible_side_pages(win):
    """左右栏 QStackedWidget 中当前可见的页（可见面板计数口径）。"""
    out = []
    for stack in (win.left_content, win.right_content):
        for i in range(stack.count()):
            page = stack.widget(i)
            if page is not None and page.isVisible():
                out.append(page)
    return out


def test_transport_bar_min_width_budget(qapp):
    """A1：传输条 `minimumSizeHint().width() <= 620`（生产入口基座，同 2.2）。"""
    from acouscope.ui.widgets.transport_bar import TransportBar

    prev_style = qapp.style().name()
    prev_font = qapp.font()
    prev_theme_id = theme._theme_id
    prev_colors_id = theme.colors().get("id")
    try:
        qapp.setStyle("Fusion")
        font = QFont(prev_font)
        font.setFamilies(theme.ui_font_families())
        font.setPointSize(theme.TOKENS["typography"]["body"])
        qapp.setFont(font)
        theme.apply_theme("dark")

        bar = TransportBar()
        width = bar.minimumSizeHint().width()
        assert width <= _TRANSPORT_MIN_W_BUDGET, (
            f"TransportBar.minimumSizeHint().width()={width} > {_TRANSPORT_MIN_W_BUDGET}"
        )
    finally:
        qapp.setStyle(prev_style)
        qapp.setFont(prev_font)
        _restore_theme(prev_theme_id, prev_colors_id)


def test_canvas_keeps_floor_with_both_panels(main_window, qapp):
    """A2：1000×700 + 设置/AI 全开 → 画布 ≥ 400 且可见；面板宽 ≤ min(28%, 420)。"""
    win = main_window
    win._activate_settings_tab()
    win._activate_ai_tab()
    qapp.processEvents()
    qapp.processEvents()

    wave = win.waveform_widget
    assert wave.width() >= 400, (
        f"1000×700 双栏全开 waveform_widget.width()={wave.width()} < 400（D1 画布被挤）"
    )
    assert wave.isVisible(), "1000×700 双栏全开 waveform_widget 不可见"
    assert win.central_stack.minimumWidth() >= _CANVAS_MIN_W, (
        f"画布层 minimumWidth={win.central_stack.minimumWidth()} < {_CANVAS_MIN_W}"
    )

    cap = min(int(win.width() * 0.28), 420)
    for name in ("left_panel", "right_panel"):
        panel = getattr(win, name)
        if not panel.is_collapsed():
            assert panel.width() <= cap, f"{name}.width()={panel.width()} > {cap}"


def test_side_pages_mutex_one_left_one_right(main_window, qapp):
    """A4：连开左栏 2 页 + 右栏 2 页 → 可见面板数 == 2（1 左 1 右），末页为当前页。"""
    win = main_window
    win._activate_settings_tab()                    # 左 1：设置
    win._show_left_content(win._quickstart_page)    # 左 2：快速入门
    win._show_right_content(win.inspector_panel)    # 右 1：检查器
    win._activate_ai_tab()                          # 右 2：AI 释图
    qapp.processEvents()

    visible = _visible_side_pages(win)
    assert len(visible) == 2, (
        f"可见面板数={len(visible)}（应 1 左 + 1 右）：{[type(v).__name__ for v in visible]}"
    )
    assert win.left_content.currentWidget() is win._quickstart_page, (
        "左栏当前页不是最后打开的「快速入门」（旧页未关/未切）"
    )
    assert win.right_content.currentWidget() is win._ai_host, (
        "右栏当前页不是最后打开的「AI 释图」"
    )
    settings_page = win._settings_panel
    if settings_page is not None:
        assert not settings_page.isVisible(), "旧页「设置」仍在显示（互斥失效）"
