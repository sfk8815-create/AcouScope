# SPDX-License-Identifier: GPL-3.0-only
"""G2：生产路径 Qt 标准按钮本地化判据（第三轮 · 阻断级时序修复）。

前两轮靠 monkeypatch get_language() 通过，但生产路径失效：i18n 模块默认
en_US，直到 MainWindow(controller) 构造内 set_language(...) 才变 zh_CN
（默认 Settings.language="zh_CN"）。故 install_qt_translation(app) 必须排在
MainWindow 之后；且「设置→应用」切语言后须联动同步 Qt 标准按钮翻译。

install_qt_translation 现位于共享模块 acouscope.utils.qt_translation（幂等同步）：
zh_CN→qt_zh_CN.qm / zh_TW→qt_zh_TW.qm（QLibraryInfo 取目录）；en_US/未知
语言先卸载旧 translator 再返回 None。

判据：
  J1 端到端（不 monkeypatch 语言）：真构造 MainWindow(AppController()) 后
     get_language()=="zh_CN"、安装返回非 None、按钮含中文且无 &Yes/&No。
  J2 时序 AST：main() 里 install_qt_translation(app) 在
     `window = MainWindow(controller)` 赋值之后、`window.show()` 之前。
  J3 运行期联动：en_US 卸载回 &Yes/&No、zh_CN 回中文；并用源码/AST 断言
     _on_settings_applied 的 set_language(new_lang) 之后存在 install 调用。
  测试结束一律复原语言，禁污染后续档。
"""

import ast
import inspect
import os
import re
import sys
import textwrap
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QMessageBox

import acouscope.i18n as i18n
from acouscope.utils.qt_translation import install_qt_translation

_CJK = re.compile(r"[\u4e00-\u9fff]")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _no_translator_leak(qapp):
    """每测试后卸载安装的 translator，避免污染 session 级 qapp。"""
    yield
    translator = getattr(qapp, "_qt_zh_translator", None)
    if translator is not None:
        qapp.removeTranslator(translator)
        del qapp._qt_zh_translator


def _yes_no_texts():
    box = QMessageBox()
    box.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    return [b.text() for b in box.buttons()]


# ---------------------------------------------------------------------------
# 行为三档：install_qt_translation 本身（共享模块）；app is None 安全
# ---------------------------------------------------------------------------

def test_zh_cn_localizes_standard_buttons(qapp, monkeypatch):
    monkeypatch.setattr(i18n, "get_language", lambda: "zh_CN")
    assert install_qt_translation(qapp) is not None
    texts = _yes_no_texts()
    assert len(texts) == 2
    assert all(_CJK.search(x) for x in texts), f"中文按钮文字缺失: {texts}"
    assert all("&Yes" not in x and "&No" not in x for x in texts), (
        f"英文标准按钮残留: {texts}"
    )


def test_en_us_does_not_install(qapp, monkeypatch):
    monkeypatch.setattr(i18n, "get_language", lambda: "en_US")
    assert install_qt_translation(qapp) is None
    texts = _yes_no_texts()
    assert any("&Yes" in x for x in texts)
    assert any("&No" in x for x in texts)


def test_zh_tw_loads_tw_qm(qapp, monkeypatch):
    import PyQt6.QtCore as qc

    calls = []
    _orig = qc.QTranslator

    class _SpyTranslator(_orig):
        def load(self, *args, **kwargs):
            calls.append(args)
            return super().load(*args, **kwargs)

    monkeypatch.setattr(qc, "QTranslator", _SpyTranslator)
    monkeypatch.setattr(i18n, "get_language", lambda: "zh_TW")
    assert install_qt_translation(qapp) is not None
    assert any(a and a[0] == "qt_zh_TW.qm" for a in calls), (
        f"未加载 qt_zh_TW.qm: {calls}"
    )
    texts = _yes_no_texts()
    assert all(_CJK.search(x) for x in texts)


def test_app_none_is_safe():
    """R2：app is None 须安全返回 None（联动在「设置→应用」无 app 时不得抛）。"""
    assert install_qt_translation(None) is None


# ---------------------------------------------------------------------------
# J2 时序 AST：install 调用在 MainWindow 赋值之后、window.show() 之前
# ---------------------------------------------------------------------------

def _main_src_tree():
    import acouscope.__main__ as entry

    src = textwrap.dedent(inspect.getsource(entry.main))
    return ast.parse(src)


def test_main_install_after_mainwindow_before_show():
    """C1 升级为时序判据：仅「存在调用」不足，必须排在语言就绪点之后。

    变异：把 install_qt_translation(app) 移回 QApplication 之后（即
    `window = MainWindow(controller)` 之前）或删除调用行 ⇒ 本判据翻红。
    """
    tree = _main_src_tree()

    assign_lines = []
    install_lines = []
    show_lines = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
            f = n.value.func
            if isinstance(f, ast.Name) and f.id == "MainWindow":
                assign_lines.append(n.lineno)
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name) and f.id == "install_qt_translation":
                if (n.args and isinstance(n.args[0], ast.Name)
                        and n.args[0].id == "app"):
                    install_lines.append(n.lineno)
            if (isinstance(f, ast.Attribute) and f.attr == "show"
                    and isinstance(f.value, ast.Name) and f.value.id == "window"):
                show_lines.append(n.lineno)

    assert assign_lines, "main() 中未找到 `window = MainWindow(controller)` 赋值"
    assert install_lines, (
        "main() 函数体内未找到 install_qt_translation(app) 调用："
        "生产入口接线缺失（仅定义函数 / 仅注释提及不算接线）"
    )
    assert show_lines, "main() 中未找到 window.show()"
    assign_line = assign_lines[0]
    install_line = install_lines[0]
    show_line = show_lines[0]
    assert assign_line < install_line, (
        f"install_qt_translation(app) 出现在 MainWindow(controller) 之前："
        f"调用@{install_line} 赋值@{assign_line} —— 此时语言尚未就绪(en_US)，"
        f"中文界面按钮仍是 &Yes/&No"
    )
    assert install_line < show_line, (
        f"install_qt_translation(app) 未在 window.show() 之前："
        f"调用@{install_line} show@{show_line}"
    )


# ---------------------------------------------------------------------------
# J1 端到端（不 monkeypatch 语言）：生产路径真生效
# ---------------------------------------------------------------------------

def test_end_to_end_production_path_language_ready(qapp, monkeypatch, tmp_path):
    """不 monkeypatch get_language：真构造 MainWindow(AppController())。

    默认 Settings.language="zh_CN"，MainWindow.__init__ 内 set_language 后
    语言才就绪；此时安装 Qt 中文翻译，按钮须含中文且不含 &Yes/&No。
    """
    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow

    monkeypatch.setenv("HOME", str(tmp_path))  # 与已验收 G3 夹具口径一致
    before = i18n.get_language()
    try:
        controller = AppController()
        window = MainWindow(controller)
        try:
            lang = i18n.get_language()
            assert lang == "zh_CN", (
                f"MainWindow 构造后语言仍未就绪: {lang}（期望 zh_CN）"
            )
            ret = install_qt_translation(qapp)
            assert ret is not None, (
                "语言就绪(zh_CN) 后 install_qt_translation(app) 仍返回 None "
                "⇒ 生产路径失效，QMessageBox 按钮仍是 &Yes/&No"
            )
            texts = _yes_no_texts()
            print(f"[J1] get_language() after MainWindow = {lang}")
            print(f"[J1] install_qt_translation(app) returns = {type(ret).__name__} (not None)")
            print(f"[J1] zh_CN Yes/No button texts = {texts}")
            assert len(texts) == 2
            assert all(_CJK.search(x) for x in texts), f"中文按钮文字缺失: {texts}"
            assert all("&Yes" not in x and "&No" not in x for x in texts), (
                f"英文标准按钮残留: {texts}"
            )
        finally:
            window.close()
    finally:
        i18n.set_language(before)  # 复原，禁污染后续档


# ---------------------------------------------------------------------------
# J3 运行期联动：两态切换按钮随语言变化 + 源码/AST 接线判据
# ---------------------------------------------------------------------------

def test_settings_applied_wires_install_after_set_language():
    """源码/AST：_on_settings_applied 里 set_language(new_lang) 之后存在
    install_qt_translation( 调用（删掉联动调用行 ⇒ 翻红）。
    """
    from acouscope.ui.main_window import MainWindow

    src = textwrap.dedent(inspect.getsource(MainWindow._on_settings_applied))
    tree = ast.parse(src)
    set_lines = []
    install_lines = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            if n.func.id == "set_language":
                set_lines.append(n.lineno)
            elif n.func.id == "install_qt_translation":
                install_lines.append(n.lineno)
    assert set_lines, "_on_settings_applied 未找到 set_language(new_lang)"
    assert install_lines, (
        "_on_settings_applied 的 set_language(new_lang) 之后未找到 "
        "install_qt_translation(...) 联动调用：切语言后按钮不会同步"
    )
    assert max(install_lines) > min(set_lines), (
        f"install 调用@{install_lines} 未排在 set_language@{set_lines} 之后"
    )


def test_runtime_language_switch_syncs_qt_buttons(qapp):
    """运行态：en_US 卸载回 &Yes/&No；zh_CN 回中文；幂等同步不叠加、不残留。"""
    before = i18n.get_language()
    try:
        # 切换前：中文态
        i18n.set_language("zh_CN")
        assert install_qt_translation(qapp) is not None
        zh0 = _yes_no_texts()
        assert all(_CJK.search(x) for x in zh0), f"初始中文态失败: {zh0}"

        # 设置→应用切到 en_US：联动应卸载并返回 None，按钮回 &Yes/&No
        i18n.set_language("en_US")
        assert install_qt_translation(qapp) is None
        en = _yes_no_texts()
        print(f"[J3] en_US Yes/No button texts = {en}")
        assert any("&Yes" in x for x in en), f"en_US 未回到 &Yes: {en}"
        assert any("&No" in x for x in en), f"en_US 未回到 &No: {en}"
        assert not any(_CJK.search(x) for x in en), f"en_US 残留中文按钮: {en}"

        # 再切回 zh_CN：按钮回中文
        i18n.set_language("zh_CN")
        assert install_qt_translation(qapp) is not None
        zh1 = _yes_no_texts()
        print(f"[J3] zh_CN Yes/No button texts = {zh1}")
        assert all(_CJK.search(x) for x in zh1), f"zh_CN 未回中文: {zh1}"
        assert all("&Yes" not in x and "&No" not in x for x in zh1), (
            f"zh_CN 残留英文按钮: {zh1}"
        )
    finally:
        i18n.set_language(before)  # 复原，禁污染后续档
