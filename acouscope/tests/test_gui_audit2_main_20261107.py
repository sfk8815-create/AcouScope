# SPDX-License-Identifier: GPL-3.0-only
"""真机 GUI 审计第二轮「主窗口 / 检查器 / 传输条」5 项缺陷守卫（2026-11-07）。

覆盖 M1 / M3 / M5 / L2 / L3，全部离屏（conftest QT_QPA_PLATFORM=offscreen）。
每条守卫在交付时做「改回旧态 → 断言翻红 → 撤销变异 → 回绿」三段变异自检：

- M1：快捷键 / 分析槽经 _set_analysis_view 切视图时，检查器「当前视图」必须
  同步刷新（旧态 blockSignals 跳过 currentChanged → 整组同步丢失，读数 stale）；
  且标签点击路径（直接 setCurrentIndex，不 block）整组同步只执行一次。
- M3：主工具栏单一溢出 affordance——1000 / 1600 两档均不得出现 Qt 原生
  「»」（qt_toolbar_ext_button）；1000 档「更多」菜单仍含 批处理 / 房间模态 /
  房间声学 三入口；1600 档三工作区开关可见。
- M5：检查器「音频」摘要行窄宽以 ElideRight 收口（显示文本以 … 结尾），
  tooltip 承载全文（旧态 wordWrap 硬裁切无省略号）。
- L2：传输时钟任何档位不得 elide——窄宽下文本不含 '…' 且含两个完整时间读数
  （旧态中间档 ElideMiddle 挖成 00:00:0…:08.000）。
- L3：工作区页开关 toggleChartDesignerBtn 的 accessibleName 走消歧键
  「图表设计器（工作区）」，与对话框入口可区分（旧态共用「图表设计器」）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QToolBar, QToolButton

from acouscope.app.controller import AppController
from acouscope.i18n import tr
from acouscope.ui.main_window import MainWindow


def _settle(qapp, n=4):
    for _ in range(n):
        qapp.processEvents()


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """无音频 MainWindow（不 show）；teardown close（沿用 cb012 夹具口径）。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    w = MainWindow(AppController())
    yield w
    w.close()


@pytest.fixture
def window_audio(qapp, monkeypatch, tmp_path):
    """带已加载 2s 合成音频 + 波形数据的 MainWindow（不 show，沿用 cb011 口径）。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 2.0)) / sr
    x = 0.5 * np.sin(2 * np.pi * 440 * t)
    controller.load_from_array(x, sr)
    w = MainWindow(controller)
    w.waveform_widget.set_data(t, x, sample_rate=sr)
    yield w
    w.close()


# ---------------------------------------------------------------------------
# M1：_set_analysis_view 切视图同步检查器；标签点击路径同步只一次
# ---------------------------------------------------------------------------
def test_m1_set_analysis_view_refreshes_inspector_and_click_syncs_once(
    window_audio, monkeypatch
):
    w = window_audio
    # 判别主断言：经 _set_analysis_view 切到 FFT(1)，检查器当前视图须刷新。
    w._set_analysis_view(1)
    assert w.inspector_panel.lbl_view.text() == "FFT 频谱", (
        f"_set_analysis_view 切视图后检查器当前视图 stale: "
        f"{w.inspector_panel.lbl_view.text()!r}"
    )
    # 标签点击路径（直接 setCurrentIndex，不 block）整组同步只执行一次。
    # 懒构建置空避免真实分析计算；以 _save_view_index 计数同步收尾。
    w._show_or_build_view = lambda index: None
    calls: list[int] = []
    monkeypatch.setattr(w, "_save_view_index", lambda index: calls.append(index))
    w.analysis_tab_bar.setCurrentIndex(3)
    assert calls == [3], f"标签点击路径同步收尾应恰执行一次，实际 {calls}"


# ---------------------------------------------------------------------------
# M3：单一溢出 affordance —— 原生「»」不再出现
# ---------------------------------------------------------------------------
def _file_toolbar(w) -> QToolBar:
    tb = w.btn_toolbar_overflow.parent()
    assert isinstance(tb, QToolBar)
    return tb


def _ext_visible(tb) -> bool:
    ext = tb.findChild(QToolButton, "qt_toolbar_ext_button")
    return ext is not None and ext.isVisible()


def test_m3_no_native_extension_button_at_1000_and_1600(window, qapp):
    w = window
    tb = _file_toolbar(w)
    w.show()
    _settle(qapp)
    try:
        # 宽档：无原生「»」，三工作区开关可见。
        w.resize(1600, 800)
        _settle(qapp)
        assert not _ext_visible(tb), "1600 档出现 Qt 原生扩展钮「»」"
        for name in (
            "btn_toggle_batch_workspace",
            "btn_toggle_room_modal",
            "btn_toggle_room_acoustic",
        ):
            assert getattr(w, name).isVisible(), f"1600 档 {name} 应可见"

        # 窄档：仍无原生「»」（设计内「更多」菜单为唯一溢出 affordance）。
        w.resize(1000, 800)
        _settle(qapp)
        assert not _ext_visible(tb), (
            "1000 档仍出现 Qt 原生扩展钮「»」（双重溢出未收口）"
        )
        # 「更多」菜单仍含三工作区入口（隐藏工具栏钮不删菜单可达性）。
        menu = w.btn_toolbar_overflow.menu()
        names = {a.objectName() for a in menu.actions()}
        assert {"overflowBatch", "overflowRoomModal", "overflowRoomAcoustic"} <= names
    finally:
        w.close()
        _settle(qapp)


# ---------------------------------------------------------------------------
# M5：检查器音频摘要行 ElideRight + tooltip 全文
# ---------------------------------------------------------------------------
def test_m5_inspector_audio_elides_with_full_tooltip(qapp):
    from acouscope.ui.widgets.panels import InspectorPanel

    panel = InspectorPanel()
    # 面板有最小宽（约 331），140 宽不可达；用真机同样会出现的长摘要验证收口。
    full = ("48000 Hz · 2 声道 · 00:00:08.000 · WAV · 24 bit · "
            "峰值 -1.2 dBFS · RMS -24.4 dBFS")
    panel.set_audio_info(full)
    panel.resize(140, 600)
    panel.show()
    _settle(qapp)
    try:
        lbl = panel.lbl_audio
        text = lbl.text()
        print("M5 audio label:", repr(text), "width=", lbl.width(),
              "tooltip=", repr(lbl.toolTip()))
        assert lbl.toolTip() == full, f"tooltip 应承载全文: {lbl.toolTip()!r}"
        assert text.endswith("…"), f"窄宽音频摘要应以省略号收口（非硬裁切）: {text!r}"
        assert text != full, "窄宽下应发生省略而非原样硬裁切"
    finally:
        panel.close()
        panel.deleteLater()


# ---------------------------------------------------------------------------
# L2：传输时钟任何档位不得 elide
# ---------------------------------------------------------------------------
def test_l2_transport_clock_never_elides_in_narrow(qapp):
    from acouscope.ui.widgets.transport_bar import TransportBar

    bar = TransportBar()
    bar.set_time_label(1.5, 8.0)  # 00:00:01.500 / 00:00:08.000
    bar.show()
    _settle(qapp)
    try:
        # 中间档（曾触发 ElideMiddle 挖空）：条宽落在窄态区间。
        width = 700
        bar.resize(width, 60)
        bar._apply_compact(width)
        _settle(qapp)
        text = bar.lbl_current_time.text()
        print("L2 narrow clock:", repr(text), "labelW=", bar.lbl_current_time.width())
        assert "…" not in text, f"窄档时钟被省略号挖空: {text!r}"
        assert text.count("/") == 1, f"应含两个时间读数分隔: {text!r}"
        left, right = (p.strip() for p in text.split("/"))
        # 两个完整时间读数（MM:SS.mmm 或 HH:MM:SS.mmm），非截字片段。
        import re
        pat = re.compile(r"^(?:\d{2}:)?\d{2}:\d{2}\.\d{3}$")
        assert pat.match(left) and pat.match(right), (
            f"时钟两端读数不完整（截字）: {left!r} / {right!r}"
        )
    finally:
        bar.close()
        bar.deleteLater()


# ---------------------------------------------------------------------------
# L3：图表设计器两入口 accessibleName 消歧
# ---------------------------------------------------------------------------
def test_l3_chart_designer_workspace_accessible_name_disambiguated(window):
    w = window
    ws_btn = w.btn_toggle_chart_designer
    analysis_tb = w.btn_ai_interpret.parent()
    dlg_btn = analysis_tb.widgetForAction(w.action_chart_designer)
    assert dlg_btn is not None
    print("L3 ws.accessibleName=", repr(ws_btn.accessibleName()),
          "dlg.accessibleName=", repr(dlg_btn.accessibleName()))
    assert ws_btn.accessibleName() == tr("overflow.chart_designer_workspace"), (
        f"工作区页开关 accessibleName 应走消歧键: {ws_btn.accessibleName()!r}"
    )
    assert ws_btn.accessibleName() != dlg_btn.accessibleName(), (
        "两入口 accessibleName 不得相同（读屏不可区分）"
    )