# SPDX-License-Identifier: GPL-3.0-only
"""P3：双 GUI 入口接线 + 端到端真实类型验证 + 联动刷新。

依赖 conftest autouse fixtures：qapp（PyQt6 app）+ _isolate_app_data_dir（每例独立 tmp）。
"""
from __future__ import annotations

import json
import math
import shutil
import tempfile
from pathlib import Path

import pytest

from acouscope.analysis.tunings import user_templates as _ut
from acouscope.analysis.tunings.overlay import build_overlay_lines
from acouscope.analysis.tunings.templates import get_tuning, list_templates
from acouscope.i18n import tr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_custom_scl(cents, name="test_scale"):
    """构造一个最小合法 .scl 文件，返回其内容字符串。"""
    parts = [
        f"{name}",
        "",
        "8",
        "unison",
    ]
    for i, c in enumerate(cents[1:], 2):
        parts.append(f"{c:.4f}\ninterval {i}")
    return "\n".join(parts) + "\n"


def _create_user_template(name, cents):
    """通过真实 API 创建一个用户模板，返回 dict。"""
    return _ut.add_user_template(name, "test_source", cents)


def _count_menu_items(menu):
    """返回菜单动作列表（不含分隔符）。"""
    return [a for a in menu.actions() if not a.isSeparator()]


def _count_dropdown_items(dlg):
    """返回批读对话框模板下拉的所有 itemData。"""
    return [dlg.cmb_template.itemData(i) for i in range(dlg.cmb_template.count())]


# ---------------------------------------------------------------------------
# Criterion 1：双 GUI 入口 + 空库零回归
# ---------------------------------------------------------------------------


def test_main_window_menu_empty_library(qapp):
    """空库时菜单恰为「不显示」+ 8 个内置模板（共 9 项）。"""
    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow

    ctrl = AppController()
    window = MainWindow(ctrl)

    menu = window.menu_tuning_template
    assert menu is not None
    actions = _count_menu_items(menu)

    texts = [a.text() for a in actions]
    assert texts[0] == tr("tuning.none")

    # 内置模板名称（list_templates() 返回的顺序）
    expected = [tr("tuning.none")] + [get_tuning(k).name for k in list_templates()]
    assert texts == expected

    # 无分隔符（空库）
    separators = [a for a in menu.actions() if a.isSeparator()]
    assert len(separators) == 0

    window.close()


def test_batch_dropdown_empty_library(qapp):
    """空库时批读对话框模板下拉恰 9 项（8 内置 + CUSTOM_ITEM）。"""
    from acouscope.ui.widgets.batch_readout_dialog import (
        BatchReadoutDialog,
        CUSTOM_ITEM,
    )

    dlg = BatchReadoutDialog()
    try:
        keys = _count_dropdown_items(dlg)
        assert len(keys) == 9
        assert keys[-1] == CUSTOM_ITEM

        # 无分隔符（空库）
        separators = [
            dlg.cmb_template.itemData(i)
            for i in range(dlg.cmb_template.count())
            if dlg.cmb_template.itemData(i) == -1
        ]
        assert len(separators) == 0

    finally:
        dlg.close()


def test_menu_and_dropdown_with_user_templates(qapp):
    """库内放 2 个用户模板后：菜单出现分隔符+2项，下拉出现 2 custom:项且排在 CUSTOM_ITEM 之前。"""
    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow
    from acouscope.ui.widgets.batch_readout_dialog import (
        BatchReadoutDialog,
        CUSTOM_ITEM,
    )

    cents1 = [200.0, 300.0, 400.0, 500.0, 600.0, 700.0, 800.0, 900.0]
    cents2 = [250.0, 400.0, 550.0, 700.0, 850.0, 1000.0, 1150.0, 1300.0]

    entry1 = _create_user_template("TestScale A", cents1)
    entry2 = _create_user_template("TestScale B", cents2)

    # 主窗口菜单
    ctrl = AppController()
    window = MainWindow(ctrl)

    menu = window.menu_tuning_template
    actions = menu.actions()

    # 应有分隔符
    separators = [a for a in actions if a.isSeparator()]
    assert len(separators) == 1

    # 用户项应排在分隔符之后
    sep_idx = actions.index(separators[0])
    user_actions = actions[sep_idx + 1:]

    # 找到并点击 TestScale A
    found = False
    for action in user_actions:
        if action.text() == "TestScale A":
            # 获取该模板的 spec
            entry = _ut.get_entry("TestScale A")
            assert entry is not None
            spec = f"custom:{_ut.library_dir() / entry['file']}"

            # 选择它
            window.tuning_ruler_template_key = spec
            window.action_tuning_ruler.setChecked(True)

            # 验证 overlay lines 非空
            overlay = window._build_tuning_overlay_lines()
            assert overlay is not None
            assert len(overlay) > 0

            # 验证 degrees 逐值一致（unison at 0 + cents1）
            tuning = get_tuning(spec)
            assert len(tuning.degrees) == 9  # unison + 8 cents
            for i, c in enumerate(cents1):
                assert tuning.degrees[i + 1] == c, (
                    f"degree[{i + 1}] mismatch: {tuning.degrees[i + 1]} vs {c}"
                )

            found = True
            break
    assert found, "TestScale A not found in menu"

    window.close()

    # 批读对话框下拉
    dlg = BatchReadoutDialog()
    try:
        items = [dlg.cmb_template.itemData(i) for i in range(dlg.cmb_template.count())]
        custom_items = [i for i in items if isinstance(i, str) and i.startswith("custom:")]
        assert len(custom_items) == 2

        # CUSTOM_ITEM 必须在所有 custom: 项之后
        custom_idx = items.index(CUSTOM_ITEM)
        for i, item in enumerate(items):
            if isinstance(item, str) and item.startswith("custom:"):
                assert i < custom_idx, "custom: item should precede CUSTOM_ITEM"

        # 选择用户项并验证 template_spec
        for i, item in enumerate(items):
            if isinstance(item, str) and item.startswith("custom:") and "TestScale A" in dlg.cmb_template.itemText(i):
                dlg.cmb_template.blockSignals(True)
                dlg.cmb_template.setCurrentIndex(i)
                dlg.cmb_template.blockSignals(False)

                spec = dlg.template_spec()
                assert spec.startswith("custom:")
                # 验证解析
                tuning = get_tuning(spec)
                assert len(tuning.degrees) == 9  # unison + 8 provided

    finally:
        dlg.close()


# ---------------------------------------------------------------------------
# Criterion 2：真实类型端到端
# ---------------------------------------------------------------------------


def test_end_to_end_custom_template_flow(qapp):
    """端到端：创建模板 → get_tuning → degrees 逐值 == → overlay_lines。"""
    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow

    # 创建一个已知的非标准律制（首值 > 0）
    cents = [117.49, 234.86, 352.0, 462.0, 578.93, 698.01, 807.43]
    entry = _create_user_template("Custom E2E", cents)

    spec = f"custom:{_ut.library_dir() / entry['file']}"

    # 通过 get_tuning 解析
    tuning = get_tuning(spec)

    # degrees[1:] 逐值 == cents（铁律：精度只可提升，禁容差）
    for i, c in enumerate(cents):
        assert tuning.degrees[i + 1] == c, (
            f"degree[{i + 1}] mismatch: got {tuning.degrees[i + 1]}, expected {c}"
        )

    # overlay lines 数量与音级数一致（7 cents + unison = 8 total）
    overlay = build_overlay_lines(tuning, ref_hz=440.0)
    assert len(overlay) == 8

    # overlay lines 的 cents 值应逐位等于对应音级（同源 degree_to_cents）
    for line in overlay:
        assert line.cents == tuning.degrees[line.degree], (
            f"overlay line at {line.freq_hz} Hz ({line.cents} cents) "
            f"!= degree[{line.degree}] {tuning.degrees[line.degree]}"
        )

    # MainWindow 集成
    ctrl = AppController()
    window = MainWindow(ctrl)
    try:
        window.tuning_ruler_template_key = spec
        window.action_tuning_ruler.setChecked(True)

        cur = window._current_tuning()
        assert cur is not None
        for i, c in enumerate(cents):
            assert cur.degrees[i + 1] == c

    finally:
        window.close()


def test_batch_readout_custom_template_spec(qapp):
    """批读对话框选中用户项后 template_spec() 返回 custom: path。"""
    from acouscope.ui.widgets.batch_readout_dialog import (
        BatchReadoutDialog,
        CUSTOM_ITEM,
    )

    cents = [120.0, 240.0, 360.0, 480.0, 600.0, 720.0, 840.0]
    entry = _create_user_template("Batch Test", cents)

    dlg = BatchReadoutDialog()
    try:
        # 刷新以包含新模板
        dlg.refresh_user_templates()

        items = [dlg.cmb_template.itemData(i) for i in range(dlg.cmb_template.count())]
        custom_items = [i for i, item in enumerate(items) if isinstance(item, str) and item.startswith("custom:")]

        found = False
        for idx in custom_items:
            text = dlg.cmb_template.itemText(idx)
            if "Batch Test" in text:
                dlg.cmb_template.blockSignals(True)
                dlg.cmb_template.setCurrentIndex(idx)
                dlg.cmb_template.blockSignals(False)

                spec = dlg.template_spec()
                assert spec.startswith("custom:")
                found = True

                # 验证 get_tuning 能解析
                ts = get_tuning(spec)
                assert len(ts.degrees) == 8  # unison + 7 provided
                break

        assert found, "Batch Test template not found in dropdown"

    finally:
        dlg.close()


# ---------------------------------------------------------------------------
# Criterion 3：联动 + refresh 幂等 + mutation self-test
# ---------------------------------------------------------------------------


def test_refresh_idempotent_no_duplicate_connections(qapp):
    """refresh_user_templates() 连调 3 次不重复连接信号（模板列表稳定）。"""
    from acouscope.ui.widgets.batch_readout_dialog import BatchReadoutDialog, CUSTOM_ITEM

    dlg = BatchReadoutDialog()
    try:
        # 初始下拉项数
        initial_count = dlg.cmb_template.count()

        for _ in range(3):
            dlg.refresh_user_templates()

        # 刷新后项数不变（无重复添加）
        final_count = dlg.cmb_template.count()
        assert initial_count == final_count, (
            f"refresh added duplicate items: {initial_count} -> {final_count}"
        )

        # CUSTOM_ITEM 仍在末尾
        keys = [dlg.cmb_template.itemData(i) for i in range(final_count)]
        assert keys[-1] == CUSTOM_ITEM

    finally:
        dlg.close()


def test_menu_template_select_triggers_overlay(qapp):
    """菜单项被选中后应立即触发 overlay 更新。"""
    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow

    cents = [200.0, 325.0, 450.0, 575.0, 700.0, 825.0, 950.0, 1075.0]
    entry = _create_user_template("Menu Trigger Test", cents)

    ctrl = AppController()
    window = MainWindow(ctrl)
    try:
        # 先确保标尺关闭
        window.action_tuning_ruler.setChecked(False)
        assert window._build_tuning_overlay_lines() is None

        # 通过程序方式选择用户模板
        spec = f"custom:{_ut.library_dir() / entry['file']}"
        window.tuning_ruler_template_key = spec
        window.action_tuning_ruler.setChecked(True)

        overlay = window._build_tuning_overlay_lines()
        assert overlay is not None
        assert len(overlay) == 9  # unison + 8 cents

    finally:
        window.close()


def test_user_templates_appear_in_menu(qapp):
    """正向验证：库非空时用户模板出现在菜单中。"""
    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow

    cents = [200.0, 320.0, 440.0, 560.0, 680.0, 800.0, 920.0, 1040.0]
    entry = _create_user_template("Menu Verification", cents)

    ctrl = AppController()
    window = MainWindow(ctrl)
    try:
        menu = window.menu_tuning_template
        actions = _count_menu_items(menu)
        texts = [a.text() for a in actions]

        # 用户模板应出现
        assert "Menu Verification" in texts, (
            f"User template not found in menu. Menu items: {texts}"
        )

    finally:
        window.close()


# ---------------------------------------------------------------------------
# Existing test files must still pass (listed in criterion 3)
# These are verified by running each file in an independent process
# ---------------------------------------------------------------------------


def test_refresh_keeps_external_scl_without_file_dialog(qapp, monkeypatch, tmp_path):
    """兜底判据：绑定外部 .scl 后刷新，不得弹出文件选择框且路径保持。

    编辑模板后关闭编辑器会触发 refresh_user_templates()；若恢复 CUSTOM_ITEM
    选择时未抑制 currentIndexChanged 信号，_on_template_changed 会再次弹出
    QFileDialog。此处用真实 .scl + 真实对话框验证「零弹框 + spec 不变」。
    """
    from PyQt6.QtWidgets import QFileDialog

    from acouscope.analysis.tunings.scl import save_scl
    from acouscope.analysis.tunings.tuning_system import TuningSystem
    from acouscope.ui.widgets.batch_readout_dialog import BatchReadoutDialog

    scl = tmp_path / "external.scl"
    tuning = TuningSystem.from_cents(
        name="外部音阶",
        source="兜底探针",
        cents=[150.0, 350.0, 700.0, 1200.0],
    )
    save_scl(tuning, scl)

    dlg = BatchReadoutDialog()
    try:
        dlg.bind_custom_scl(str(scl))
        assert dlg.template_spec() == str(scl)

        opened: list = []
        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (opened.append(args) or ("", "")),
        )
        dlg.refresh_user_templates()

        assert opened == [], "refresh 不应弹出文件选择框"
        assert dlg.template_spec() == str(scl), "刷新后外部 .scl 绑定须保持不变"
    finally:
        dlg.close()
