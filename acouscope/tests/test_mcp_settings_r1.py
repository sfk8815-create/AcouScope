"""MCP 设置页往返、配置与零进程、i18n 五语齐三判据测试。"""
import json
import os
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication, QCheckBox, QLabel, QScrollArea

from acouscope.i18n import tr
from acouscope.ui.widgets.settings_dialog import SettingsDialog


@pytest.fixture()
def mcp_config_dir(tmp_path, monkeypatch):
    """隔离 Settings.load()/save() 到临时目录。"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(
        "acouscope.utils.config.get_config_dir",
        lambda: config_dir,
    )
    return config_dir


def test_settings_dialog_six_tabs_with_mcp_group(qapp, mcp_config_dir):
    """判据 1a (REWORK-4)：nav_list.count()==6、stack.count()==6，MCP 嵌于通用页。"""
    dlg = SettingsDialog(parent=None)
    assert dlg.nav_list.count() == 6, f"预期 6 个 tab，实际 {dlg.nav_list.count()}"
    assert dlg.stack.count() == 6, f"预期 stack 6，实际 {dlg.stack.count()}"

    # MCP 控件应位于通用页（第 0 项）内
    general_page = dlg.stack.widget(0)
    # _wrap_page 包了 QScrollArea
    if isinstance(general_page, QScrollArea):
        general_widget = general_page.widget()
    else:
        general_widget = general_page

    chk = dlg.findChild(QCheckBox, "mcpEnabled")
    assert chk is not None, "通用页内未找到 mcpEnabled 控件"

    # chk_mcp_enabled 应为通用页后代
    assert dlg.chk_mcp_enabled is not None
    found = False
    for child in general_widget.findChildren(QCheckBox):
        if child.objectName() == "mcpEnabled":
            found = True
            break
    assert found, "chk_mcp_enabled 不是通用页的后代"

    # settings.tab.mcp 作为分组标题出现在通用页
    labels = general_widget.findChildren(QLabel)
    section_found = False
    for lbl in labels:
        if lbl.text() == tr("settings.tab.mcp"):
            section_found = True
            break
    assert section_found, f"通用页内未找到分组标题 '{tr('settings.tab.mcp')}'"


def test_old_config_loads_defaults(qapp, mcp_config_dir):
    """判据 1b：旧 settings.json（不含 3 新键）加载后 3 控件为 False/""/""。"""
    settings_file = mcp_config_dir / "settings.json"
    old_data = {"language": "zh_CN", "theme": "dark"}
    settings_file.write_text(json.dumps(old_data), encoding="utf-8")

    dlg = SettingsDialog(parent=None)
    vals = dlg.mcp_settings()
    assert vals["mcp_enabled"] is False, f"预期 False，实际 {vals['mcp_enabled']}"
    assert vals["mcp_allowed_roots"] == "", f"预期 ''，实际 {repr(vals['mcp_allowed_roots'])}"
    assert vals["mcp_out_dir"] == "", f"预期 ''，实际 {repr(vals['mcp_out_dir'])}"


def test_settings_persist_roundtrip(qapp, mcp_config_dir):
    """判据 1c/d：改控件值 → apply → Settings.load() 读回逐值相等；第二对话框初值一致。"""
    from acouscope.utils.config import Settings

    roots = "/tmp/mcp_root1:/tmp/mcp_root2"
    out_dir = "/tmp/mcp_out"

    dlg = SettingsDialog(parent=None)
    dlg.chk_mcp_enabled.setChecked(True)
    dlg.edit_mcp_roots.setText(roots)
    dlg.edit_mcp_out.setText(out_dir)

    # 点击「应用」按钮（通过 applied signal）
    dlg.applied.emit()

    # Settings.load() 读回并校验逐值相等
    loaded = Settings.load()
    assert loaded.mcp_enabled is True, f"mcp_enabled 预期 True，实际 {loaded.mcp_enabled}"
    assert loaded.mcp_allowed_roots == roots, (
        f"mcp_allowed_roots 预期 {repr(roots)}，实际 {repr(loaded.mcp_allowed_roots)}"
    )
    assert loaded.mcp_out_dir == out_dir, (
        f"mcp_out_dir 预期 {repr(out_dir)}，实际 {repr(loaded.mcp_out_dir)}"
    )

    # 第二个 SettingsDialog 初值应与刚保存的值一致
    dlg2 = SettingsDialog(parent=None)
    vals2 = dlg2.mcp_settings()
    assert vals2["mcp_enabled"] is True, f"第二对话框 mcp_enabled 预期 True，实际 {vals2['mcp_enabled']}"
    assert vals2["mcp_allowed_roots"] == roots, (
        f"第二对话框 mcp_allowed_roots 预期 {repr(roots)}，实际 {repr(vals2['mcp_allowed_roots'])}"
    )
    assert vals2["mcp_out_dir"] == out_dir, (
        f"第二对话框 mcp_out_dir 预期 {repr(out_dir)}，实际 {repr(vals2['mcp_out_dir'])}"
    )


def test_mcp_copy_host_config(qapp, mcp_config_dir):
    """判据 2a：btn_mcp_copy.click() 后剪贴板可 json.loads，含正确 mcpServers 结构。"""
    dlg = SettingsDialog(parent=None)
    # MCP 现嵌于通用页（第 0 项），无需切换 tab

    # 清空剪贴板
    QApplication.clipboard().clear()

    dlg.btn_mcp_copy.click()

    clipboard_text = QApplication.clipboard().text()
    assert clipboard_text, "剪贴板为空"

    config = json.loads(clipboard_text)
    assert "mcpServers" in config, f"配置缺少 mcpServers 键：{list(config.keys())}"
    server = config["mcpServers"]["acouscope"]
    assert "command" in server, f"缺少 command 键：{list(server.keys())}"
    assert "args" in server, f"缺少 args 键：{list(server.keys())}"
    assert "env" in server, f"缺少 env 键：{list(server.keys())}"
    assert server["args"] == ["-m", "acouscope.mcp_server"], (
        f"args 预期 ['-m', 'acouscope.mcp_server']，实际 {server['args']}"
    )


def test_mcp_check_no_process(qapp, mcp_config_dir):
    """判据 2b：btn_mcp_check.click() 后 lbl_mcp_status.text() 非空，mcp_enabled=False 时为 not_ready。"""
    dlg = SettingsDialog(parent=None)

    # mcp_enabled 默认为 False
    assert dlg.chk_mcp_enabled.isChecked() is False

    dlg.btn_mcp_check.click()

    status = dlg.lbl_mcp_status.text()
    assert status, "就绪检查后状态标签为空"
    assert tr("settings.mcp.not_ready") in status, (
        f"mcp_enabled=False 时状态应含 '{tr('settings.mcp.not_ready')}'，实际：{status}"
    )


def test_mcp_check_empty_roots_no_exception(qapp, mcp_config_dir, tmp_path):
    """回归断言 3a：roots 为空、out 为真实目录时 _on_mcp_check() 不抛异常（UnboundLocalError 路径）。"""
    out_dir = tmp_path / "mcp_out"
    out_dir.mkdir()

    dlg = SettingsDialog(parent=None)
    dlg.edit_mcp_roots.setText("")  # roots 为空
    dlg.edit_mcp_out.setText(str(out_dir))

    # 不应抛出 UnboundLocalError: local variable 'Path' referenced before assignment
    dlg.btn_mcp_check.click()

    status = dlg.lbl_mcp_status.text()
    assert status, "就绪检查后状态标签为空"
    # 应报 not_ready（因为 mcp_enabled=False），但不应该崩溃


def test_mcp_check_pathsep_semicolon(qapp, mcp_config_dir, tmp_path, monkeypatch):
    """回归断言 3b：Windows 语义（pathsep=';'）下，分号分隔的两个存在目录能通过就绪检查。"""
    import os

    root1 = tmp_path / "root1"
    root1.mkdir()
    root2 = tmp_path / "root2"
    root2.mkdir()
    out_dir = tmp_path / "mcp_out"
    out_dir.mkdir()

    # monkeypatch os.pathsep 为分号（模拟 Windows）
    monkeypatch.setattr(os, "pathsep", ";")

    dlg = SettingsDialog(parent=None)
    dlg.chk_mcp_enabled.setChecked(True)
    # 用分号分隔的两个存在目录
    dlg.edit_mcp_roots.setText(f"{root1};{root2}")
    dlg.edit_mcp_out.setText(str(out_dir))

    # 即使 mcp package 未安装，也不应报 "root dir missing"
    dlg.btn_mcp_check.click()

    status = dlg.lbl_mcp_status.text()
    assert "root dir missing" not in status, (
        f"分号分隔的存在目录不应报 root dir missing，实际状态：{status}"
    )


def test_mcp_check_real_pathsep_and_hint_text(qapp, mcp_config_dir, tmp_path):
    """REWORK-3 新断言：本机真实 os.pathsep 拼接两目录不报 missing；hint 不含 per line/每行/줄바꿈/改行。"""
    import os

    root1 = tmp_path / "real_root1"
    root1.mkdir()
    root2 = tmp_path / "real_root2"
    root2.mkdir()
    out_dir = tmp_path / "mcp_out_real"
    out_dir.mkdir()

    # 用本机真实 pathsep 拼接两个存在目录
    dlg = SettingsDialog(parent=None)
    dlg.chk_mcp_enabled.setChecked(True)
    dlg.edit_mcp_roots.setText(f"{root1}{os.pathsep}{root2}")
    dlg.edit_mcp_out.setText(str(out_dir))

    # 即使 mcp package 未安装，也不应报 "root dir missing"
    dlg.btn_mcp_check.click()

    status = dlg.lbl_mcp_status.text()
    assert "root dir missing" not in status, (
        f"本机 pathsep 分隔的存在目录不应报 root dir missing，实际状态：{status}"
    )

    # 防文案再次与单行控件冲突：hint 不得出现「每行 / per line / 줄바꿈 / 改行」字面
    hint = tr("settings.mcp.roots_hint")
    assert "per line" not in hint, f"hint 含 'per line'：{hint}"
    assert "每行" not in hint, f"hint 含 '每行'：{hint}"
    assert "줄바꿈" not in hint, f"hint 含 '줄바꿈'：{hint}"
    assert "改行" not in hint, f"hint 含 '改行'：{hint}"


def test_m4_general_page_min_width(qapp, mcp_config_dir):
    """REWORK-5 回归断言：通用页嵌入 MCP 分组后 minimumSizeHint().width() <= 310（M4 同尺子）。"""
    dlg = SettingsDialog(parent=None)
    dlg.resize(320, 800)
    qapp.processEvents()

    general_page = dlg.stack.widget(0)
    if isinstance(general_page, QScrollArea):
        general_widget = general_page.widget()
    else:
        general_widget = general_page

    min_w = general_widget.minimumSizeHint().width()
    assert min_w <= 310, f"通用页嵌入 MCP 后最小宽 {min_w} > 310（M4 回归）"


def test_i18n_mcp_keys_all_five_languages():
    """判据 3a：9 个新键每个五语齐（en_US/zh_CN/zh_TW/ko_KR/ja_JP）。"""
    from acouscope.i18n import _STRINGS

    mcp_keys = [
        "settings.tab.mcp",
        "settings.mcp.enable",
        "settings.mcp.roots_hint",
        "settings.mcp.out_hint",
        "settings.mcp.check",
        "settings.mcp.copy",
        "settings.mcp.ready",
        "settings.mcp.not_ready",
        "settings.mcp.title",
    ]

    expected_langs = {"en_US", "zh_CN", "zh_TW", "ko_KR", "ja_JP"}

    for key in mcp_keys:
        assert key in _STRINGS, f"键缺失：{key}"
        langs = set(_STRINGS[key].keys())
        assert langs == expected_langs, (
            f"键 {key} 语言集合 {langs} != 预期 {expected_langs}"
        )
