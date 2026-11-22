# SPDX-License-Identifier: GPL-3.0-only
"""分面 B GUI 呈现层修复守卫（2026-11-06 · 全离屏 · 不触网 · 不建真 GUI 循环）。

B1  BatchReadoutDialog.lbl_template_info：超长模板信息（URL + 64 位 sha256）
    单行省略 + tooltip 全文 + 底部按钮不被无限换行压掉。
B2  工具行按钮按文本宽兜底：ReportPreviewPanel 五按钮 / Spectrogram3DWidget
    「字体…」按钮，width 与 minimumWidth 均 >= 文本宽 + 16。
B3  status.fft_info_hint 三语补零语义（key / {n} 占位符不变）+ FFT 数值派生
    源码锚点仍在（数值零改动由交付回报的 git diff 机器证据佐证）。
B4  状态栏 ElidedLabel / 空态覆盖提示显隐 / 全铺页清残留 / 窄窗可见性 /
    TipBar 定宽口径与轮换间隔 + 60 条 tip 三语 ≥80% 不触发跑马灯。

每条断言配外部变异自检（变异前→红文→撤销后），见交付回报「变异三段」。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PyQt6")

import numpy as np  # noqa: E402
from PyQt6.QtGui import QFontMetrics  # noqa: E402
from PyQt6.QtWidgets import QVBoxLayout, QWidget  # noqa: E402

from acouscope.i18n import _STRINGS, get_language, set_language, tr  # noqa: E402

_SRC = Path(__file__).resolve().parents[1] / "src" / "acouscope"

# 含 URL + 64 位 sha256 的最不利模板信息
_URL = "https://example.org/a/very/long/template/source/path/template.scl"
_FP = "a1b2c3d4" * 8  # 64 位十六进制指纹

_REPORT_BTNS = (
    "btn_refresh", "btn_export", "btn_export_html", "btn_ai", "btn_close",
)


# ======================================================================
# B1 长文本单行省略 + tooltip 全文
# ======================================================================


def test_b1_template_info_single_line_full_tooltip_and_buttons(qapp):
    """注入 URL+64 位哈希：标签高度单行、tooltip 含全文、底部按钮在其下方。"""
    from acouscope.ui.widgets.batch_readout_dialog import BatchReadoutDialog

    dlg = BatchReadoutDialog()
    try:
        dlg.set_template_info("12tet", _URL, _FP)
        dlg.show()
        qapp.processEvents()

        lbl = dlg.lbl_template_info
        fm = QFontMetrics(lbl.font())
        assert lbl.height() <= fm.height() * 1.6, (
            f"lbl_template_info.height()={lbl.height()} > "
            f"fontMetrics.height()*1.6={fm.height() * 1.6:.1f}（无限换行）"
        )
        assert _FP in lbl.toolTip(), "tooltip 未含完整 fingerprint"
        assert _URL in lbl.toolTip(), "tooltip 未含完整来源 URL"
        assert _FP in lbl.text(), "text() 全文不得因 elide 丢数据"

        bottom = lbl.geometry().bottom()
        for name in ("btn_cancel", "btn_run"):
            btn = getattr(dlg, name)
            assert btn.y() >= bottom, (
                f"{name}.y()={btn.y()} < lbl_template_info.bottom()={bottom}"
                "（底部按钮行被压到标签上方）"
            )
    finally:
        dlg.close()


# ======================================================================
# B2 工具行按钮文本宽兜底
# ======================================================================


def _need(btn) -> int:
    return QFontMetrics(btn.font()).horizontalAdvance(btn.text()) + 16


def test_b2_report_preview_buttons_at_1000px(qapp):
    """resize 到 1000px 宽：每个按钮 width / minimumWidth >= 文本宽 + 16。

    minimumWidth 断言是齿：撤掉 setMinimumWidth 后恒为 0 ⇒ 必翻红。
    """
    from acouscope.ui.report_preview import ReportPreviewPanel

    panel = ReportPreviewPanel()
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.addWidget(panel)
    try:
        panel.resize(1000, 560)
        host.resize(1000, 560)
        host.show()
        panel.show()
        qapp.processEvents()
        assert panel.width() >= 900, f"面板未到 1000px 宽：{panel.width()}"
        for name in _REPORT_BTNS:
            btn = getattr(panel, name)
            need = _need(btn)
            assert btn.width() >= need, (
                f"{name}.width()={btn.width()} < need={need}（文字被 elide）"
            )
            assert btn.minimumWidth() >= need, (
                f"{name}.minimumWidth()={btn.minimumWidth()} < need={need}"
                "（撤掉文本宽兜底即翻红）"
            )
        assert panel.tools_scroll.objectName() == "reportPreviewTools", (
            "工具行缺单一横向溢出出口"
        )
    finally:
        panel.setParent(None)
        host.deleteLater()


def test_b2_spectrogram3d_font_button_text_width(qapp):
    """3D「字体…」按钮同口径：窄宽下不被 pin_tool_row_widths 锁成碎片。"""
    from acouscope.ui.widgets.spectrogram3d import Spectrogram3DWidget

    d3 = Spectrogram3DWidget()
    host = QWidget()
    try:
        d3.setParent(host)
        d3.setGeometry(0, 0, 750, 600)
        host.resize(760, 620)
        host.show()
        d3.show()
        qapp.processEvents()
        btn = d3.btn_font
        need = _need(btn)
        assert btn.width() >= need, (
            f"btn_font.width()={btn.width()} < need={need}（不可读碎片）"
        )
        assert btn.minimumWidth() >= need, (
            f"btn_font.minimumWidth()={btn.minimumWidth()} < need={need}"
        )
    finally:
        d3.setParent(None)
        host.deleteLater()


# ======================================================================
# B3 FFT 文案口径（只改显示文案，数值派生零改动）
# ======================================================================


def _assert_zero_pad(entry) -> None:
    """B3 守门锚点①：三语补零语义 + {n} 占位符（断言逐字等同原用例）。"""
    assert "补零" in entry["zh_CN"], "zh_CN 缺「补零」语义"
    assert "zero-pad" in entry["en_US"].lower(), "en_US 缺 zero-pad 语义"
    assert "補零" in entry["zh_TW"], "zh_TW 缺「補零」语义"
    assert "窗长由下拉设置" in entry["zh_CN"], "zh_CN 未说明窗长由下拉设置"
    assert "窗長由下拉設定" in entry["zh_TW"], "zh_TW 未说明窗长由下拉设置"
    for lang in ("en_US", "zh_CN", "zh_TW"):
        assert "{n}" in entry[lang], f"{lang} 丢了 {{n}} 占位符"


def _assert_fft_anchor(src: str) -> None:
    """B3 守门锚点②：fft_size 派生源码锚点仍原样（禁改分析数值）。"""
    assert "while fft_size < frame_samples:" in src
    assert "fft_size = max(fft_size, 8192)" in src


def test_b3_fft_info_hint_three_languages_zero_pad():
    """三语各含补零语义；key 不变；{n} 占位符保留（.format(n=fft_size) 依赖）。"""
    _assert_zero_pad(_STRINGS["status.fft_info_hint"])


def test_b3_fft_size_derivation_source_anchor_unchanged():
    """正对照：5742-5749 的 fft_size 派生源码锚点仍原样（禁改分析数值）。"""
    src = (_SRC / "ui" / "main_window.py").read_text(encoding="utf-8")
    _assert_fft_anchor(src)


def test_b3_anchor_mutation_self_check():
    """测试内变异自检：坏文案 / 坏源码必须让两个锚点函数各自翻红（守门有齿）。"""
    good = _STRINGS["status.fft_info_hint"]

    bad_zh = dict(good)
    bad_zh["zh_CN"] = good["zh_CN"].replace("补零", "")
    assert bad_zh["zh_CN"] != good["zh_CN"], "变异点①未命中（正对照）"
    with pytest.raises(AssertionError):
        _assert_zero_pad(bad_zh)

    bad_en = dict(good)
    bad_en["en_US"] = good["en_US"].replace("zero-pad", "")
    assert bad_en["en_US"] != good["en_US"], "变异点②未命中（正对照）"
    with pytest.raises(AssertionError):
        _assert_zero_pad(bad_en)

    bad_n = dict(good)
    bad_n["zh_CN"] = good["zh_CN"].replace("{n}", "")
    assert bad_n["zh_CN"] != good["zh_CN"], "变异点③未命中（正对照）"
    with pytest.raises(AssertionError):
        _assert_zero_pad(bad_n)

    src = (_SRC / "ui" / "main_window.py").read_text(encoding="utf-8")
    bad_src1 = src.replace("while fft_size < frame_samples:", "while False:")
    assert bad_src1 != src, "变异点④未命中（正对照）"
    with pytest.raises(AssertionError):
        _assert_fft_anchor(bad_src1)

    bad_src2 = src.replace("fft_size = max(fft_size, 8192)", "fft_size = fft_size")
    assert bad_src2 != src, "变异点⑤未命中（正对照）"
    with pytest.raises(AssertionError):
        _assert_fft_anchor(bad_src2)


# ======================================================================
# B4 状态 / 空态 / 全铺页 / 窄窗 / tip
# ======================================================================


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """无音频 MainWindow（离屏 show，供真实几何/可见性读数）。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow

    w = MainWindow(AppController())
    w.resize(1000, 700)
    w.show()
    qapp.processEvents()
    yield w
    w.close()


def test_b4_status_label_is_elided_label(window):
    """lbl_status 必须是 ElidedLabel 且 minimumWidth()==0（长说明不挤四段）。"""
    from acouscope.ui.widgets.statusbar_segments import ElidedLabel

    assert isinstance(window.lbl_status, ElidedLabel), (
        f"lbl_status 类型={type(window.lbl_status).__name__}"
    )
    assert window.lbl_status.minimumWidth() == 0


def test_b4_empty_hint_visible_then_hidden_after_wav(window, qapp, tmp_path):
    """初始 analysis_empty_state 可见；_load_file 后随 view_container 切页隐藏。

    空态已由 EmptyState 完整承担（说明 + 打开文件按钮 + 拖放提示），重复的
    waveformEmptyHint 标签已删：main_window.py 中该字符串零命中。
    """
    from acouscope.audio import AudioIO

    empty = window.analysis_empty_state
    assert empty.isVisible() is True, "无音频时 analysis_empty_state 应可见"
    src = (_SRC / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert "waveformEmptyHint" not in src, "重复空态标签未删净"

    wav = tmp_path / "tone_b.wav"
    AudioIO().save(np.zeros(8000, dtype=np.float32), 8000, str(wav))
    window._load_file(str(wav))
    qapp.processEvents()
    assert empty.isVisible() is False, "加载音频后 analysis_empty_state 未随切页隐藏"
    assert window.view_container.currentIndex() != 0, (
        "加载后未切离 index0 提示页（判据空转）"
    )


def test_b4_full_page_clears_stale_view_status(window, qapp):
    """切报告预览全铺页后 lbl_status 不残留「3D 频谱图」/「FFT 频谱」。"""
    window.report_preview_panel.set_html_provider(lambda: "")  # 空态早退，零渲染
    window.lbl_status.setText("3D 频谱图 (8192 点 FFT)")
    window._show_report_preview()
    qapp.processEvents()
    text = window.lbl_status.text()
    assert "3D 频谱图" not in text, f"残留上一视图文案：{text!r}"
    assert "FFT 频谱" not in text, f"残留 FFT 视图文案：{text!r}"


def test_b4_narrow_window_keeps_tab_bar_statusbar_and_canvas(window, qapp):
    """resize(1000,700)：标签卡/状态栏可见 + central_stack.width()>=560。"""
    window.resize(1000, 700)
    qapp.processEvents()
    assert window.analysis_tab_bar.isVisible() is True
    assert window.statusBar().isVisible() is True
    assert window.central_stack.width() >= 560, (
        f"central_stack.width()={window.central_stack.width()} < 560"
    )


def test_b4_tip_interval_and_no_marquee_for_most_tips(window, qapp):
    """轮换 >=12000ms；_N_CHARS>=36、minimumWidth=0；60 条 tip 三语 >=80% 不滚动。"""
    from acouscope.ui.widgets import tip_bar as tbmod

    assert window._tip_timer.interval() >= 12000
    assert tbmod._N_CHARS >= 36

    bar = tbmod.TipBar()
    assert bar.minimumWidth() == 0, "tip_bar 须保持可被压缩（LOGO 常驻）"
    max_w = int(tbmod._CHAR_W * tbmod._N_CHARS + tbmod._PAD * 2)
    inner = max_w - tbmod._PAD * 2
    fm = bar._fm

    saved = get_language()
    try:
        for lang in ("zh_CN", "en_US", "zh_TW"):
            set_language(lang)
            prefix = tr("tip.prefix")
            ok = sum(
                1 for i in range(1, 61)
                if fm.horizontalAdvance(f"{prefix}  {tr(f'tip.{i}')}") <= inner
            )
            assert ok >= 48, (
                f"{lang} 仅 {ok}/60 条不触发跑马灯（<80%），_N_CHARS={tbmod._N_CHARS}"
            )
    finally:
        set_language(saved)


# ======================================================================
# C1：state.py 对 JSON Infinity（float('inf')）的启动容错（4 处 OverflowError）
# ======================================================================


def _write_raw_state(tmp_path, raw: str) -> None:
    """直接写 app_state.json 原始文本（保留 Infinity 字面量，绕过 json.dump）。"""
    (tmp_path / "app_state.json").write_text(raw, encoding="utf-8")


def test_c1_get_launch_count_inf_falls_back_to_zero(tmp_path):
    """launch_count=inf → int(inf) 抛 OverflowError → 回退 0。"""
    import acouscope.state as _state

    _write_raw_state(tmp_path, '{"launch_count": Infinity}')
    assert _state.get_launch_count() == 0


def test_c1_bump_launch_count_inf_falls_back_to_one(tmp_path):
    """launch_count=inf → bump 回退 1（启动路径不得崩）。"""
    import acouscope.state as _state

    _write_raw_state(tmp_path, '{"launch_count": Infinity}')
    assert _state.bump_launch_count() == 1


def test_c1_get_snooze_until_launch_inf_falls_back_to_zero(tmp_path):
    """sponsor_snooze_until_launch=inf → 回退 0。"""
    import acouscope.state as _state

    _write_raw_state(tmp_path, '{"sponsor_snooze_until_launch": Infinity}')
    assert _state.get_sponsor_snooze_until_launch() == 0


def test_c1_snooze_sponsor_reminder_inf_step_zero(tmp_path):
    """snooze_sponsor_reminder(float('inf')) → step=0，绝不抛、写入基准计数。"""
    import acouscope.state as _state

    _write_raw_state(tmp_path, '{"launch_count": 5}')
    assert _state.snooze_sponsor_reminder(float("inf")) is True
    assert _state.get_sponsor_snooze_until_launch() == 5  # 5 + step(0)


# ======================================================================
# C4：AI 释图页右栏宽度（宽窗裁字修复）+ 切回检查器撤销
# ======================================================================


def test_c4_ai_tab_widens_right_panel_and_restores(window, qapp):
    """resize(1600,980) 切 AI 页：右栏 ≥320、中央 ≥560、长文本标签不被裁；
    切回检查器后强制最小宽撤销（minimumWidth()==0，恢复原口径）。"""
    window.resize(1600, 980)
    qapp.processEvents()
    window._activate_ai_tab()
    qapp.processEvents()
    qapp.processEvents()

    right = window.right_panel
    assert right.width() >= 320, (
        f"AI 页 right_panel.width()={right.width()} < 320（裁字）"
    )
    assert window.central_stack.width() >= 560, (
        f"AI 页 central_stack.width()={window.central_stack.width()} < 560"
    )
    panel = window._ai_panel
    assert panel is not None, "AI 面板未构建（判据空转）"
    assert panel.lbl_probe.geometry().right() <= right.width(), (
        f"硬件结论标签被裁：right={panel.lbl_probe.geometry().right()} "
        f"> right_panel.width()={right.width()}"
    )
    assert panel.msg_hint.geometry().right() <= right.width(), (
        f"开场提示标签被裁：right={panel.msg_hint.geometry().right()} "
        f"> right_panel.width()={right.width()}"
    )

    window._show_right_content(window.inspector_panel)
    qapp.processEvents()
    assert right.minimumWidth() == 0, (
        f"切回检查器后仍被强制最小宽：minimumWidth()={right.minimumWidth()}"
    )


def test_c4_ai_tab_collapse_clears_width_guard(window, qapp):
    """AI 页激活后直接折叠右栏：强制最小宽须撤销，右栏压到 0（不卡在 320）。"""
    window.resize(1600, 980)
    qapp.processEvents()
    window._activate_ai_tab()
    qapp.processEvents()
    qapp.processEvents()
    right = window.right_panel
    assert right.minimumWidth() == 320, "AI 页未建立强制最小宽（判据空转）"
    window._collapse_right_panel()
    qapp.processEvents()
    assert right.minimumWidth() == 0, (
        f"折叠后仍被强制最小宽：minimumWidth()={right.minimumWidth()}"
    )
    assert right.width() == 0, (
        f"折叠后右栏未压到 0：width()={right.width()}"
    )


def test_c4_ai_tab_resize_narrow_clears_width_guard(window, qapp):
    """宽窗激活 AI 页后再缩到 <1280：守卫须随 resizeEvent 撤销，中央画布保底。"""
    window.resize(1600, 980)
    qapp.processEvents()
    window._activate_ai_tab()
    qapp.processEvents()
    qapp.processEvents()
    right = window.right_panel
    assert right.minimumWidth() == 320, "AI 页未建立强制最小宽（判据空转）"
    window.resize(1000, 700)
    qapp.processEvents()
    qapp.processEvents()
    assert right.minimumWidth() == 0, (
        f"缩窄后仍被强制最小宽：minimumWidth()={right.minimumWidth()}"
    )
    assert getattr(window, "_ai_width_guard", False) is False, (
        "缩窄后 _ai_width_guard 未复位"
    )
    assert window.central_stack.width() >= 560, (
        f"缩窄后中央画布被挤：{window.central_stack.width()} < 560"
    )
