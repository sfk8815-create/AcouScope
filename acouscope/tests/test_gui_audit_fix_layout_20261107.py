# SPDX-License-Identifier: GPL-3.0-only
"""2026-11-07 真机 GUI 审计「布局 / 设置 / 平台文案」层缺陷守卫。

覆盖 F1 / F5 / F7 / F8 / F9 五个确定性缺陷的可观测行为；每个用例由实现方
在 worktree 内做「把实现改回旧态 → 断言翻红 → 反向字符串替换撤销变异点
→ 断言回绿」变异自检（三段证据见交付回报）。

本文件不构造 MainWindow 顶层窗口：F5 用轻量 QWidget 宿主借调未绑定方法
_rebuild_shortcuts_overview；全程 QT_QPA_PLATFORM=offscreen。
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QMenu, QWidget,
)

# R3-3：qapp 复用 tests/conftest.py 的 session 级夹具，删去本文件 module
# 级重复定义（避免两个 QApplication 生命周期口径并存）。


# ---------------------------------------------------------------------------
# F1：restore_workspace 对左右栏施加内容可读下限（病态窄栏不得原样恢复）
# ---------------------------------------------------------------------------
def test_f1_restore_clamps_side_panels(qapp, tmp_path):
    from acouscope.ui.widgets.panels.workspace import (
        _AUTO_MIN_W, build_workspace_splitter, restore_workspace,
        save_workspace,
    )

    p = tmp_path / "ui_layout.json"
    p.write_text(json.dumps({
        "sizes": [194, 560, 146],
        "left_collapsed": False,
        "right_collapsed": False,
    }), encoding="utf-8")
    ws = build_workspace_splitter(QLabel("center"))
    restore_workspace(ws, path=p)
    sizes = [int(v) for v in ws["splitter"].sizes()]
    print("F1 [194,560,146] -> sizes:", sizes,
          "min(_AUTO_MIN_W)=", _AUTO_MIN_W)
    assert sizes[0] >= _AUTO_MIN_W, f"左栏病态窄值未抬宽: {sizes}"
    assert sizes[2] >= _AUTO_MIN_W, f"右栏病态窄值未抬宽: {sizes}"
    assert sizes[1] >= 320, f"中央栏低于 320: {sizes}"

    # 合法 sizes 的 save -> restore round-trip 不回归（绝对像素精确一致）
    ws2 = build_workspace_splitter(QLabel("center"))
    target = [300, 600, 250]
    base = sum(target) + 2 * ws2["splitter"].handleWidth()
    ws2["splitter"].resize(base, 500)
    ws2["splitter"].setSizes(target)
    rt = tmp_path / "roundtrip.json"
    save_workspace(ws2, path=rt)
    ws3 = build_workspace_splitter(QLabel("center"))
    ws3["splitter"].resize(base, 500)
    restore_workspace(ws3, path=rt)
    got = list(ws3["splitter"].sizes())
    print("F1 round-trip sizes:", got, "target:", target)
    assert got == target, f"合法 sizes 往返被破坏: {got} != {target}"


# ---------------------------------------------------------------------------
# F1（R3-2 守卫）：总和超限分支——按 slack 等比缩减 + residual 补齐
# ---------------------------------------------------------------------------
def test_f1_restore_overflow_shrinks_proportionally(qapp, tmp_path):
    """抬宽后总和超出保存时可用宽：只削减各栏高于下界的富余，三栏不破下限。"""
    from acouscope.ui.widgets.panels.workspace import (
        _AUTO_MIN_W, build_workspace_splitter, restore_workspace,
    )

    sizes_in = [100, 900, 100]          # 左右病态窄；抬到下界后总和 1340
    available = sum(sizes_in)           # 1100：保存时的可用总宽
    p = tmp_path / "ui_layout.json"
    p.write_text(json.dumps({
        "sizes": sizes_in,
        "left_collapsed": False,
        "right_collapsed": False,
    }), encoding="utf-8")
    ws = build_workspace_splitter(QLabel("center"))
    restore_workspace(ws, path=p)
    sizes_out = [int(v) for v in ws["splitter"].sizes()]
    mins = [_AUTO_MIN_W, 320, _AUTO_MIN_W]
    print("F1 shrink before:", sizes_in, "available:", available,
          "-> after:", sizes_out, "sum:", sum(sizes_out), "mins:", mins)
    # 缩减后总和回落到保存时的可用总宽（不撑破布局）
    assert sum(sizes_out) <= available, (
        f"抬宽溢出未按 slack 等比缩减: {sizes_out} sum={sum(sizes_out)}"
        f" > available={available}")
    # 三栏仍分别 ≥ 下限（绝不把任何一栏压回下界以下）
    for i in range(3):
        assert sizes_out[i] >= mins[i], (
            f"第 {i} 栏被压破下限: {sizes_out} < {mins}")
    # 左右病态窄栏确实被抬宽（下限优先），中央栏吃掉溢出缩减
    assert sizes_out[0] > sizes_in[0] and sizes_out[2] > sizes_in[2], (
        f"病态窄栏未被抬宽: {sizes_in} -> {sizes_out}")


# ---------------------------------------------------------------------------
# F5：快捷键总览显示文案走平台口径；QAction 绑定口径一字不动
# ---------------------------------------------------------------------------
def test_f5_overview_uses_platform_display_keys(qapp, monkeypatch):
    import acouscope.ui.shortcuts as shortcuts
    from acouscope.ui.main_window import MainWindow

    monkeypatch.setattr(shortcuts, "is_macos", lambda: True)
    host = QWidget()
    host.menu_shortcuts_overview = QMenu()
    a_open = QAction("打开", host)
    a_open.setShortcut(QKeySequence("Ctrl+O"))
    a_loop = QAction("循环", host)
    a_loop.setShortcut(QKeySequence("Meta+L"))
    bound_before = [a_open.shortcut().toString(),
                    a_loop.shortcut().toString()]

    MainWindow._rebuild_shortcuts_overview(host)

    texts = [a.text() for a in host.menu_shortcuts_overview.actions()]
    print("F5 overview texts:", texts, "bindings:", bound_before)
    assert texts, "总览菜单不应为空"
    joined = " ".join(texts)
    assert "⌘" in joined, f"macOS 口径下应出现 ⌘: {texts}"
    assert "Ctrl+" not in joined and "Meta+" not in joined, (
        f"显示文案残留 Windows 口径字面量: {texts}")
    # 绑定值不得被显示层改写
    assert bound_before == ["Ctrl+O", "Meta+L"]
    assert [a_open.shortcut().toString(),
            a_loop.shortcut().toString()] == bound_before


# ---------------------------------------------------------------------------
# F7：A4 行「恢复 440」按钮 / 端点标签 / 音高算法下拉的最小宽 ≥ 文本需求
# ---------------------------------------------------------------------------
def test_f7_a4_row_and_backend_combo_min_width(qapp):
    from acouscope.ui.widgets.settings_dialog import SettingsDialog

    sel = QWidget()
    lay = QHBoxLayout(sel)
    combo = QComboBox()
    combo.addItem("pYIN (流式) 很长很长很长")  # 放大当前项文本需求
    lay.addWidget(combo)
    dlg = SettingsDialog(ai_config={}, backend_selector=sel)

    btn = dlg.btn_reference_restore
    adv = btn.fontMetrics().horizontalAdvance(btn.text())
    print("F7 btn minimumWidth/advance:", btn.minimumWidth(), adv)
    assert btn.minimumWidth() >= adv, "「恢复」按钮实际最小宽不足文本需求"

    for lbl in (dlg.lbl_reference_min, dlg.lbl_reference_max):
        need = lbl.fontMetrics().horizontalAdvance(lbl.text())
        print("F7 endpoint minimumWidth/advance:", lbl.minimumWidth(),
              need, "text=", repr(lbl.text()))
        assert lbl.minimumWidth() >= need, "端点标签最小宽不足，可能被切成单个字符"

    need = combo.fontMetrics().horizontalAdvance(combo.currentText())
    print("F7 combo minimumWidth/advance:", combo.minimumWidth(), need)
    assert combo.minimumWidth() >= need, "音高算法下拉最小宽不足当前项文本需求"


# ---------------------------------------------------------------------------
# F8：tight 档时钟读数信息完整可辨（不再被 ElideMiddle 挖成 00:…000）
# ---------------------------------------------------------------------------
def test_f8_tight_clock_readable_full_info(qapp):
    from acouscope.ui.widgets.transport_bar import (
        TransportBar, _TIGHT_W, _compact_transport_clock,
    )

    bar = TransportBar()
    bar.set_time_label(1.5, 60.0)
    # 默认 / 宽态：HH:MM:SS.mmm 双读数完整（保护既有 cb013 判据口径）
    assert bar.lbl_current_time.text() == "00:00:01.500 / 00:01:00.000"
    bar.show()
    qapp.processEvents()
    width = 400
    assert width < _TIGHT_W
    bar.resize(width, 60)
    bar._apply_compact(width)
    qapp.processEvents()
    text = bar.lbl_current_time.text()
    print("F8 tight clock:", repr(text), "labelW=",
          bar.lbl_current_time.width())
    assert "…" not in text, f"tight 档仍被中部省略挖空: {text}"
    # R3-1：tight 档是「无损紧凑」——1h 内（小时 00）才去小时段；不再用
    # 正则把「无条件丢弃小时段」的有损格式固化进守卫。断言完整文本更强。
    assert text == "00:01.500 / 01:00.000", (
        f"tight 档读数不是无损短格式: {text}")
    assert _compact_transport_clock("00:01:30.000 / 00:08:00.000") == (
        "01:30.000 / 08:00.000"), "1h 内仍走无损短格式"
    # 未知态 / 非双读数 / 非三段格式一律原样返回（既有语义不变）
    unknown = "--:--:--.--- / --:--:--.---"
    assert _compact_transport_clock(unknown) == unknown, (
        f"未知态被改写: {_compact_transport_clock(unknown)}")
    assert _compact_transport_clock("12:34.000") == "12:34.000"
    assert _compact_transport_clock("12:34 / 56:78") == "12:34 / 56:78"
    bar.close()


# ---------------------------------------------------------------------------
# F8 / R3-1：>1h 读数保留小时信息（duration 可 >3600 s，禁静默丢小时段）
# ---------------------------------------------------------------------------
def test_f8_tight_clock_keeps_hours_over_1h(qapp):
    from acouscope.ui.widgets.transport_bar import (
        TransportBar, _TIGHT_W, _compact_transport_clock,
    )

    full = "01:05:03.000 / 02:10:00.000"
    compact = _compact_transport_clock(full)
    print("F8 >1h _compact_transport_clock:", repr(compact))
    assert "01:" in compact and "02:" in compact, (
        f"小时信息被静默丢弃: {compact}")
    assert compact == full, f">1h 读数未保留完整 HH:MM:SS.mmm: {compact}"

    bar = TransportBar()
    bar.set_time_label(3903.0, 7800.0)  # 01:05:03.000 / 02:10:00.000
    assert bar.lbl_current_time.text() == full
    bar.show()
    qapp.processEvents()
    width = 400
    assert width < _TIGHT_W
    bar.resize(width, 60)
    bar._apply_compact(width)
    qapp.processEvents()
    text = bar.lbl_current_time.text()
    print("F8 >1h tight clock:", repr(text),
          "labelW=", bar.lbl_current_time.width())
    assert "01:" in text and "02:" in text, (
        f"tight 档 >1h 读数丢了小时段: {text}")
    assert "…" not in text, f"tight 档 >1h 读数被省略挖空: {text}"
    bar.close()


# ---------------------------------------------------------------------------
# F9：两个死开关复选框已撤下（消除欺骗性 UI，不新增任何功能/字段）
# ---------------------------------------------------------------------------
def test_f9_dead_checkboxes_removed(qapp):
    from acouscope.ui.widgets.settings_dialog import SettingsDialog

    dlg = SettingsDialog(ai_config={})
    print("F9 hasattr chk_auto_load_last/chk_auto_play:",
          hasattr(dlg, "chk_auto_load_last"), hasattr(dlg, "chk_auto_play"))
    assert not hasattr(dlg, "chk_auto_load_last")
    assert not hasattr(dlg, "chk_auto_play")
    labels = [c.text() for c in dlg.findChildren(QCheckBox)]
    assert "启动时自动加载上次文件" not in labels
    assert "打开文件后自动播放" not in labels


# ---------------------------------------------------------------------------
# G1（真机复核）：tight 档时钟读数实宽 ≥ 文本需求；宽态收起控件恢复可见
# ---------------------------------------------------------------------------
def test_g1_tight_clock_geometry_and_wide_restore(qapp):
    """离屏窄条（宽 ≤560，触发 tight）：lbl_current_time 实宽 ≥ 文本需求、
    无省略；宽态（≥_COMPACT_W）下被收起的次要控件必须恢复可见（无状态泄漏）。"""
    from acouscope.ui.widgets.transport_bar import (
        TransportBar, _TIGHT_W, _COMPACT_W,
    )

    bar = TransportBar()
    bar.set_time_label(1.5, 8.0)  # 全量 00:00:01.500 / 00:00:08.000
    narrow = 560
    assert narrow <= 560 and narrow < _TIGHT_W
    bar.resize(narrow, 60)
    bar.show()
    qapp.processEvents()
    bar._apply_compact(narrow)
    qapp.processEvents()

    lab = bar.lbl_current_time
    fm = lab.fontMetrics()
    need = fm.horizontalAdvance(lab.text())
    width = lab.width()
    print("G1 tight: barW=", bar.width(), "text=", repr(lab.text()),
          "width=", width, "adv=", need)
    assert "…" not in lab.text(), f"tight 档时钟被省略挖空: {lab.text()}"
    assert width >= need, (
        f"G1 tight 档时钟实宽 {width} < 文本需求 {need}"
        f"（同排控件仍把标签压到不可读）")

    minor = ("btn_skip_start", "btn_skip_end", "btn_loop",
             "cmb_record_rate", "cmb_speed")
    wide = 800
    assert wide >= _COMPACT_W
    bar.resize(wide, 60)
    qapp.processEvents()
    bar._apply_compact(wide)
    qapp.processEvents()
    for name in minor:
        w = getattr(bar, name)
        print("G1 wide:", name, "hidden=", w.isHidden(), "width=", w.width())
        assert not w.isHidden(), (
            f"宽态 {name} 未恢复可见（tight 收起状态泄漏到宽态）")
    bar.close()


# ---------------------------------------------------------------------------
# G2（真机复核）：162 px 通用页内 A4 控件 + 音高算法下拉实宽 ≥ 文本需求
# ---------------------------------------------------------------------------
def test_g2_a4_multiline_geometry(qapp):
    """离屏构造宽 162 px 的「通用」页容器：btn / lbl_max / 后端下拉实宽
    各 ≥ 自身文本需求。复现真机「深色主题字号基座晚于控件构造」——构造期
    minimumWidth 按默认字体锁定，显示期主题字号更大，文本需求超过锁定下限；
    字号取排版令牌（非硬编码 px）。单行布局会把按钮钉在旧下限上而翻红。"""
    from acouscope.ui import theme
    from acouscope.ui.widgets.settings_dialog import SettingsDialog

    sel = QWidget()
    lay = QHBoxLayout(sel)
    combo = QComboBox()
    combo.addItem("pYIN (流式)")  # 真机当前项文本
    lay.addWidget(combo)
    dlg = SettingsDialog(ai_config={}, backend_selector=sel)

    pt = theme.TOKENS["typography"]["body"]
    for w in (dlg.btn_reference_restore, dlg.lbl_reference_min,
              dlg.lbl_reference_max, dlg.spin_reference_hz, combo):
        f = w.font()
        f.setPointSize(pt)
        w.setFont(f)

    dlg.setFixedWidth(162)
    dlg.show()
    qapp.processEvents()

    checks = (
        ("btn_reference_restore", dlg.btn_reference_restore,
         dlg.btn_reference_restore.text()),
        ("lbl_reference_max", dlg.lbl_reference_max,
         dlg.lbl_reference_max.text()),
        ("backend_combo", combo, combo.currentText()),
    )
    for name, w, text in checks:
        need = w.fontMetrics().horizontalAdvance(text)
        width = w.width()
        print("G2", name, "width=", width, "adv=", need, "text=", repr(text))
        assert width >= need, (
            f"G2 {name} 实宽 {width} < 文本需求 {need}"
            f"（162 px 通用页内仍被挤压/省略）")
    dlg.close()


# ---------------------------------------------------------------------------
# 独立审查建议 1 收口：_compact_transport_clock 的 len(seg)==3 条件有齿
# ---------------------------------------------------------------------------
def test_f8_compact_guard_two_segment_zero_hour(qapp):
    """2 段 mm:ss.mmm 且首段为 00 的短格式读数必须原样返回——删除
    `len(seg)==3` 条件会把它误去小时成 '01.500 / ...'（本断言翻红）。"""
    from acouscope.ui.widgets.transport_bar import _compact_transport_clock

    full = "00:01.500 / 01:00.000"
    got = _compact_transport_clock(full)
    print("G3 guard:", repr(full), "->", repr(got))
    assert got == full, (
        f"2 段 mm:ss.mmm（首段 00）被误去小时：{got!r} != {full!r}"
    )
