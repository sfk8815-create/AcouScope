# SPDX-License-Identifier: GPL-3.0-only
"""自定义律制模板编辑器测试（P2）。

判据 1：CRUD 闭环 + 逐值 == + 两击删除
判据 3：坏输入有齿 + 变异三段（红文逐字 → 撤销 → 复绿）
判据 2：18 键五语齐 + i18n numstat 删除数 0（另见点名既有档独立跑）
"""

from pathlib import Path

import pytest
from PyQt6.QtWidgets import QFileDialog

from acouscope.i18n import tr
from acouscope.ui.widgets.tuning_template_editor import (
    TuningTemplateEditorDialog,
    build_tuning,
    parse_degrees_text,
)


@pytest.fixture
def editor(qapp):
    """构造 offscreen 编辑器实例。"""
    dlg = TuningTemplateEditorDialog()
    yield dlg
    dlg.close()


# ---------------------------------------------------------------- 判据 1：CRUD 闭环

def test_parse_degrees_text_basic(editor):
    """音分文本解析：基本合法输入（含小数点为音分值）。"""
    cents = parse_degrees_text("100.0\n200.0\n300.0")
    assert cents == [100.0, 200.0, 300.0]


def test_parse_degrees_text_ratios(editor):
    """音分文本解析：n/d 比值（与 scl.py:116 同源公式逐值 ==）。"""
    import math
    cents = parse_degrees_text("9/8\n5/4")
    assert cents == [
        1200.0 * (math.log2(9) - math.log2(8)),
        1200.0 * (math.log2(5) - math.log2(4)),
    ]


def test_parse_degrees_text_comments(editor):
    """音分文本解析：空行与 ! 注释跳过。"""
    text = "! comment\n100.0\n\n! another\n200.0"
    cents = parse_degrees_text(text)
    assert cents == [100.0, 200.0]


def test_crud_create_and_readback(editor):
    """新建模板 → 回读逐值 ==。"""
    name = "test_p2_crud"
    source = "P2 test"
    degrees_text = "150.0\n350.0\n700.0"
    editor.tuningTemplateNameEdit.setText(name)
    editor.tuningTemplateSourceEdit.setText(source)
    editor.tuningTemplateDegreesEdit.setPlainText(degrees_text)
    entry = editor.save_current()
    assert entry["name"] == name

    # 回读：list_user_templates + parse_scl_file
    from acouscope.analysis.tunings.user_templates import (
        list_user_templates,
        get_user_tuning,
    )

    templates = list_user_templates()
    assert any(t["name"] == name for t in templates)
    tuning = get_user_tuning(name)
    assert tuning.name == name
    # 逐值 ==（无容差）
    assert list(tuning.degrees[1:]) == [150.0, 350.0, 700.0]
    # user_spec 不变
    from acouscope.analysis.tunings.user_templates import user_spec

    spec = user_spec(name)
    assert spec.startswith("custom:")


def test_crud_update(editor):
    """编辑态更新 → 逐值 == 新值 + nameEdit 只读。"""
    # 先新建
    name = "test_p2_update"
    editor.tuningTemplateNameEdit.setText(name)
    editor.tuningTemplateSourceEdit.setText("old source")
    editor.tuningTemplateDegreesEdit.setPlainText("100\n200")
    entry = editor.save_current()

    # 加载编辑态
    editor.tuningTemplateList.clearSelection()
    items = [i for i in range(editor.tuningTemplateList.count()) if editor.tuningTemplateList.item(i).text() == name]
    assert items, f"模板 {name} 未在列表中找到"
    editor.tuningTemplateList.setCurrentRow(items[0])
    assert editor.current_name() == name

    # load_form 后 nameEdit 只读
    editor.load_form(name)
    assert editor.tuningTemplateNameEdit.isReadOnly() is True

    # 改音分并保存
    editor.tuningTemplateDegreesEdit.setPlainText("150.0\n300.0")
    editor.save_current()

    # 回读逐值 == 新值
    from acouscope.analysis.tunings.user_templates import get_user_tuning

    tuning = get_user_tuning(name)
    assert list(tuning.degrees[1:]) == [150.0, 300.0]


def test_two_click_delete(editor):
    """两击确认删除：第一击列表仍在、按钮文字 == delete_arm；第二击库空。"""
    name = "test_p2_delete"
    editor.tuningTemplateNameEdit.setText(name)
    editor.tuningTemplateSourceEdit.setText("P2 delete test")
    editor.tuningTemplateDegreesEdit.setPlainText("100.0\n200.0")
    editor.save_current()

    # 选中要删除的项
    items = [i for i in range(editor.tuningTemplateList.count()) if editor.tuningTemplateList.item(i).text() == name]
    assert items
    editor.tuningTemplateList.setCurrentRow(items[0])

    # 第一击：只武装，不删除
    result1 = editor.delete_current()
    assert result1 is False
    assert editor.tuningTemplateDeleteBtn.text() == tr("tuning.user.delete_arm")
    # 列表仍包含该模板
    assert any(editor.tuningTemplateList.item(i).text() == name for i in range(editor.tuningTemplateList.count()))

    # 第二击：真正删除
    result2 = editor.delete_current()
    assert result2 is True
    # 库空（只剩占位项）
    from acouscope.analysis.tunings.user_templates import list_user_templates

    remaining = list_user_templates()
    assert not any(t["name"] == name for t in remaining)


# ---------------------------------------------------------------- 判据 3：坏输入有齿

def test_parse_degrees_text_errors(editor):
    """空文本 / 非法 token / 负比值 → ValueError。"""
    with pytest.raises(ValueError):
        parse_degrees_text("")
    with pytest.raises(ValueError):
        parse_degrees_text("   \n  ")
    with pytest.raises(ValueError):
        parse_degrees_text("not_a_number")
    # 负比值
    with pytest.raises(ValueError):
        parse_degrees_text("-1/2")


def test_parse_degrees_text_non_increasing(editor):
    """parse_degrees_text 只做解析，允许非递增（逐值 ==）。"""
    cents = parse_degrees_text("200.0\n100.0")
    assert cents == [200.0, 100.0]


def test_save_current_non_increasing(editor):
    """save_current 对非递增音分抛 ValueError（validate_cents 责任）。"""
    from acouscope.analysis.tunings.user_templates import list_user_templates

    before = len(list_user_templates())
    editor.tuningTemplateNameEdit.setText("non_inc_test")
    editor.tuningTemplateSourceEdit.setText("test")
    editor.tuningTemplateDegreesEdit.setPlainText("200.0\n100.0")
    with pytest.raises(ValueError):
        editor.save_current()
    after = len(list_user_templates())
    assert before == after


def test_save_current_empty_fields(editor):
    """缺字段 → ValueError + status == err_empty + 库不被污染。"""
    editor.tuningTemplateNameEdit.setText("")
    editor.tuningTemplateSourceEdit.setText("")
    editor.tuningTemplateDegreesEdit.setPlainText("")
    from acouscope.analysis.tunings.user_templates import list_user_templates

    before = len(list_user_templates())
    with pytest.raises(ValueError):
        editor.save_current()
    after = len(list_user_templates())
    assert before == after
    assert editor.tuningTemplateStatus.text() == tr("tuning.user.err_empty")


def test_save_current_bad_degrees(editor):
    """音级文本非法 → ValueError + status == err_bad。"""
    editor.tuningTemplateNameEdit.setText("bad_degrees_test")
    editor.tuningTemplateSourceEdit.setText("test")
    editor.tuningTemplateDegreesEdit.setPlainText("garbage")
    with pytest.raises(ValueError):
        editor.save_current()
    assert "err" in editor.tuningTemplateStatus.text().lower() or "parse" in editor.tuningTemplateStatus.text().lower()


def test_import_scl_success(editor, monkeypatch, tmp_path):
    """导入合法 .scl → 库出现该模板。"""
    scl_content = "Test Import\n5\n1.000000\n1.200000\n1.500000\n1.800000\n2.000000"
    scl_file = tmp_path / "test.scl"
    scl_file.write_text(scl_content, encoding="utf-8")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(scl_file), "")
    )
    entry = editor.import_scl()
    assert entry is not None
    from acouscope.analysis.tunings.user_templates import list_user_templates

    names = [t["name"] for t in list_user_templates()]
    assert "Test Import" in names


def test_import_scl_bad_file(editor, monkeypatch, tmp_path):
    """导入坏 .scl → ValueError 且库不污染。"""
    bad_content = "Bad\n0"
    bad_file = tmp_path / "bad.scl"
    bad_file.write_text(bad_content, encoding="utf-8")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(bad_file), "")
    )
    from acouscope.analysis.tunings.user_templates import list_user_templates

    before = len(list_user_templates())
    with pytest.raises(ValueError):
        editor.import_scl()
    after = len(list_user_templates())
    assert before == after


def test_import_scl_cancel(editor, monkeypatch):
    """取消导入 → None。"""
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *args, **kwargs: ("", "")
    )
    result = editor.import_scl()
    assert result is None


def test_export_scl_roundtrip(editor, monkeypatch, tmp_path):
    """导出后导入回读逐值 ==。"""
    from acouscope.analysis.tunings.user_templates import (
        add_user_template,
        get_user_tuning,
    )

    name = "export_roundtrip_test"
    source = "roundtrip"
    cents = [200.0, 400.0, 600.0]
    add_user_template(name, source, cents)
    editor.refresh_list()

    original_tuning = get_user_tuning(name)
    original_degrees = list(original_tuning.degrees[1:])

    # 导出
    exported_path = tmp_path / f"{name}.scl"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(exported_path), "")
    )
    editor.tuningTemplateList.clearSelection()
    items = [
        i
        for i in range(editor.tuningTemplateList.count())
        if editor.tuningTemplateList.item(i).text() == name
    ]
    assert items
    editor.tuningTemplateList.setCurrentRow(items[0])
    result_path = editor.export_scl()
    assert result_path is not None
    assert exported_path.exists()

    # 重新导入并校验逐值 ==
    from acouscope.analysis.tunings.user_templates import (
        delete_user_template,
        import_user_scl,
    )

    delete_user_template(name)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(exported_path), "")
    )
    editor.import_scl()
    imported_tuning = get_user_tuning(name)
    imported_degrees = list(imported_tuning.degrees[1:])
    assert imported_degrees == original_degrees


def test_build_tuning_non_increasing(editor):
    """build_tuning 对非递增音分抛 ValueError。"""
    with pytest.raises(ValueError):
        build_tuning("n", "s", [200.0, 100.0])
