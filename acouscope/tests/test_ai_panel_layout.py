# SPDX-License-Identifier: GPL-3.0-only
"""T-1018 归因重写（原 T-1011 布局验收，非静默）：

T-1011 建立的面板内设置控件（模型来源三档下拉 / 云端厂商下拉 / 服务地址·模型名·
密钥输入 / 发送图像开关 / 测试连接 / 模型设置按钮）与左预览栏、数值上下文只读栏、
右结果栏、追问对话区、预置问题区，已由 **T-1018「对话式」重做**整体移除——
模型/厂商/密钥/图像发送设置全部归「设置-AI」，面板只读 `_load_config()` 结果。

因此本文件原「三档下拉写回配置」与「左栏折叠 / 合流视图」用例失去被测对象，
改写为**同一契约的只读口径**：配置（含旧键迁移）→ 只读路由状态与顶部模型行，
外加对话式布局几何与遮挡回归。对话框行为验收见 tests/test_ai_dialog_style.py。
未受 T-1018 影响的用例（设置面板口径一致性、静态纪律）原样保留。

T-1020 归因（非静默）：T-1020 D5 取消模型名省略（真机窄栏截断反馈），原
「长文本 elided」用例改写为 `test_long_model_label_not_truncated_with_tooltip`
（同契约：完整文本 + 全文 tooltip，只是呈现方式由省略改为换行）。
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, "src")
pytest.importorskip("PyQt6")

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtWidgets import QWidget

from acouscope.ui.widgets import ai_interpret as ai

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _make_panel(monkeypatch, paths=()):
    monkeypatch.setattr(ai, "_config_paths", lambda: list(paths))
    return ai.AIInterpretDialog(
        image_getter=lambda: None,
        context_getter=lambda: "C",
        view_name_getter=lambda: "FFT 频谱",
    )


def _with_cfg(monkeypatch, tmp_path, data: dict):
    """写出 ai_config.json 并返回面板（只读装配入口）。"""
    cfg = tmp_path / "ai_config.json"
    cfg.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return _make_panel(monkeypatch, [cfg]), cfg


def _abs_rect(widget, anchor) -> QRect:
    """将任意子控件几何折算到 anchor（面板）坐标系，供跨层级不交叠断言。"""
    top_left = widget.mapTo(anchor, QPoint(0, 0))
    return QRect(top_left, widget.size())


def _host_panel(qapp, monkeypatch, width, height):
    """离屏顶层显示（普通 QWidget，非 MainWindow）返回 panel。"""
    panel = _make_panel(monkeypatch)
    panel.resize(width, height)
    panel.show()
    qapp.processEvents()
    return panel


# ----------------------------------------------------------------------
# 配置只读装配（T-1011 三档写回口径 → T-1018 只读口径）
# ----------------------------------------------------------------------

def test_config_source_and_model_resolved(qapp, monkeypatch, tmp_path):
    """云端档 + OpenAI：source/vendor/model 只读解析正确（不写回配置）。"""
    p, cfg = _with_cfg(monkeypatch, tmp_path, {
        "provider": "openai", "url": "https://api.openai.com/v1",
        "model": "gpt-4o", "key": "sk-x", "send_image": True,
        "ai_v2": {"source": "cloud", "mode": "official"},
    })
    before = cfg.read_bytes()
    try:
        assert p._source == "cloud"
        assert p._vendor == "openai"
        assert p._eng_model == "gpt-4o"
        assert p._engine_for_current()["kind"] == "openai"
        assert p._engine_for_current()["url"] == "https://api.openai.com/v1"
        assert p._current_model_name() == "gpt-4o"
        p.reload_config()
        assert cfg.read_bytes() == before      # 面板不写回配置（设置归设置-AI）
    finally:
        p.deleteLater()


def test_self_hosted_reads_external_url(qapp, monkeypatch, tmp_path):
    """本地部署档：external_ollama_url 优先于 url（对齐设置面板 prefill 口径）。"""
    p, _ = _with_cfg(monkeypatch, tmp_path, {
        "provider": "custom", "url": "http://127.0.0.1:11434",
        "model": "qwen2.5:3b", "key": "",
        "ai_v2": {"source": "self_hosted", "external_ollama": True,
                  "external_ollama_url": "http://192.168.1.20:11434"},
    })
    try:
        assert p._source == "self_hosted"
        eng = p._engine_for_current()
        assert eng["kind"] == "custom"
        assert eng["url"] == "http://192.168.1.20:11434"
        assert eng["model"] == "qwen2.5:3b"
    finally:
        p.deleteLater()


def test_custom_vendor_falls_back_for_unknown_provider(qapp, monkeypatch,
                                                       tmp_path):
    """云端档旧 id（free_remote）已删 → custom 兜底，地址与模型原样保留。"""
    p, _ = _with_cfg(monkeypatch, tmp_path, {
        "provider": "free_remote",
        "url": ai.interpreter.FREE_REMOTE_BASE,
        "model": ai.interpreter.FREE_REMOTE_MODEL,
        "key": "", "send_image": True,
        "ai_v2": {"mode": "official"},
    })
    try:
        assert p._source == "cloud"
        assert p._vendor == "custom"
        assert p._eng_model == ai.interpreter.FREE_REMOTE_MODEL
    finally:
        p.deleteLater()


def test_legacy_ollama_migrates_to_builtin(qapp, monkeypatch, tmp_path):
    """旧 provider=ollama（无 ai_v2.source）→ 内置档；引擎路由 ollama。"""
    p, _ = _with_cfg(monkeypatch, tmp_path, {
        "provider": "ollama", "model": "moondream", "url": "", "key": "",
        "send_image": True,
    })
    try:
        assert p._source == "builtin"
        assert p._engine_for_current()["kind"] == "ollama"
        assert p._engine_for_current()["url"] == ""
        assert p._persisted_v2 == {}          # 旧配置无 ai_v2：不臆造键
    finally:
        p.deleteLater()


def test_settings_dialog_congruence(qapp, monkeypatch):
    """面板读出的配置可被设置面板 reload_ai_config 恢复且 ai_config 一致。"""
    from acouscope.ui.widgets.settings_dialog import SettingsDialog

    cfg_dict = {
        "provider": "custom",
        "url": "http://192.168.1.20:11434",
        "model": "qwen2.5:3b",
        "key": "",
        "send_image": True,
        "ai_v2": {
            "source": "self_hosted",
            "external_ollama": True,
            "external_ollama_url": "http://192.168.1.20:11434",
            "mode": "official",
        },
    }
    sp = SettingsDialog(ai_config={})
    sp.reload_ai_config(cfg_dict)
    assert sp.rbtn_ai_self.isChecked()
    assert sp.edit_self_url.text() == "http://192.168.1.20:11434"
    out = sp.ai_config()
    assert out["ai_v2"]["source"] == "self_hosted"
    assert out["provider"] == "custom"
    assert out["url"] == "http://192.168.1.20:11434"
    sp.deleteLater()


# ----------------------------------------------------------------------
# 布局元素：顶部只读行 / 消息流 / 输入区（对话式）
# ----------------------------------------------------------------------

def test_model_area_no_max_height(qapp, monkeypatch):
    """回归截图问题：顶部模型区不再被 setMaximumHeight(40) 裁切。"""
    p = _make_panel(monkeypatch)
    assert p.model_area.maximumHeight() > 400  # 未设硬性高度上限


def test_main_body_controls_no_overlap(qapp, monkeypatch):
    """几何断言：顶部模型区 / 消息流 / 底部输入区纵向不交叠。"""
    p = _host_panel(qapp, monkeypatch, 900, 640)
    try:
        a = _abs_rect(p.model_area, p)
        b = _abs_rect(p.splitter, p)
        c = _abs_rect(p.msg_scroll, p)
        d = _abs_rect(p.input_panel, p)
        assert a.bottom() <= b.top()
        assert c.bottom() <= d.top()
        assert b.bottom() <= p.height()
    finally:
        p.close()


def test_bottom_controls_present(qapp, monkeypatch):
    from acouscope.i18n import tr

    p = _make_panel(monkeypatch)
    try:
        assert p.input_edit is not None
        assert p.btn_send.text() == tr("ai_panel.send")
        assert p.btn_stop.text() == tr("ai_panel.stop")
        assert not p.btn_stop.isEnabled()          # 空闲时停止不可用
        assert p.btn_send.isEnabled()
        assert p.msg_bubbles == []                 # 起聊为空
        assert p.msg_hint.isHidden() is False      # 起始提示可见
    finally:
        p.deleteLater()


# ----------------------------------------------------------------------
# T-1020 D5 归因改写（非静默）：原「长文本 elided + 完整 tooltip」口径
# ----------------------------------------------------------------------
# 原断言（T-1011 立）要求窄栏把模型名省略成「…」串。真机反馈窄栏下模型名被截成
# 「Qwen2.5...」不可读，T-1020 D5 改为**不截断**（换行完整呈现 + 全文 tooltip），
# 故本用例改为验证新契约：窄宽度下文本仍为完整值、不再产生省略号、
# `elide_to_width` 纯函数本身保留（其它调用面/回归仍可复用）。

def test_long_model_label_not_truncated_with_tooltip(qapp, monkeypatch, tmp_path):
    from acouscope.i18n import tr

    p, _ = _with_cfg(monkeypatch, tmp_path, {
        "provider": "custom", "url": "https://api.example.com/v1",
        "model": "一个非常非常长的模型名称用于测试窄栏完整展示行为",
        "key": "", "ai_v2": {"source": "cloud"},
    })
    try:
        full = p._model_full
        assert full == tr("ai_panel.model_prefix").format(
            model="一个非常非常长的模型名称用于测试窄栏完整展示行为")
        p.lbl_model.setFixedWidth(140)               # 窄栏基准宽度（实测往返）
        shown = p.lbl_model.text()
        assert p.lbl_model.toolTip() == full         # 完整值保留在 tooltip
        assert shown == full                         # T-1020 D5：不截断、不省略
        assert "…" not in shown
        assert p.lbl_model.wordWrap() is True        # 窄栏以换行承载完整文本
        # 模块级纯函数仍在（保留给其它调用面；不再用于模型行）
        fm = p.lbl_model.fontMetrics()
        elided = ai.elide_to_width(full, fm, 80)
        assert len(elided) < len(full)
        assert "…" in elided
    finally:
        p.deleteLater()


# ----------------------------------------------------------------------
# T-1021 D3：顶部行窄栏可见性（T-1020 D5 残留缺陷）
# ----------------------------------------------------------------------

def test_top_row_model_name_visible_in_narrow_pane(qapp, monkeypatch,
                                                   tmp_path):
    """278px（右侧栏真实宽）下模型名必须可见非空、下拉可辨认；420/640 不回归。

    修前实测（幕僚探针 + 本用例复现）：QSizePolicy.Ignored 的模型名标签在
    278/320px 被压成 **0 宽（完全不可见）**，420px 才出现（55px，挤成多行）。
    修后按可用宽自动切「两行」布局：第一行 来源+下拉+⚙，第二行模型名整行。
    """
    p, _ = _with_cfg(monkeypatch, tmp_path, {
        "provider": "custom", "url": "http://192.168.1.20:11434",
        "model": "qwen2.5:3b-instruct-q4_K_M", "key": "",
        "ai_v2": {"source": "self_hosted"},
    })
    p.show()                                   # 普通 QWidget 顶层显示（非 MainWindow）
    try:
        for width in (278, 320, 420, 640):
            p.resize(width, 640)
            qapp.processEvents()
            fm = p.lbl_model.fontMetrics()
            assert p.lbl_model.width() > 0, f"{width}px 下模型名被压为 0 宽"
            assert p.lbl_model.text().strip(), f"{width}px 下模型名为空串"
            assert p.lbl_model.text() == p._model_full    # 不截断（D5 口径保持）
            # 下拉可辨认：至少容得下 8 个平均字宽（非不可读窄条）
            assert p.cmb_source.width() >= fm.averageCharWidth() * 8, \
                f"{width}px 下档位下拉被压成不可读窄条"
            assert p.btn_ai_settings.isVisible()
    finally:
        p.close()


def test_top_row_switches_layout_by_available_width(qapp, monkeypatch):
    """窄栏两行 / 宽栏单行：切换由字体度量阈值驱动（无硬编码像素）。"""
    p = _make_panel(monkeypatch)
    p.show()
    try:
        p.resize(278, 640)
        qapp.processEvents()
        assert p._top_two_row is True
        idx = p._top_grid.indexOf(p.lbl_model)
        assert idx >= 0                                  # 标签在布局内（不悬空）
        assert p._top_grid.getItemPosition(idx)[0] == 1  # 第二行（窄栏）
        p.resize(640, 640)
        qapp.processEvents()
        assert p._top_two_row is False
        assert p._top_grid.getItemPosition(
            p._top_grid.indexOf(p.lbl_model))[0] == 0    # 第一行（宽栏）
    finally:
        p.close()


# ----------------------------------------------------------------------
# 静态纪律（禁词 / hex-px / QDialog / MainWindow.show()）
# ----------------------------------------------------------------------


def test_static_discipline_no_legacy_ui():
    src = (_REPO_ROOT / "src" / "acouscope" / "ui" / "widgets"
           / "ai_interpret.py").read_text(encoding="utf-8")
    assert "cmb_provider" not in src              # 旧只读 provider 下拉已删除
    assert "def _on_provider_changed" not in src
    assert "setMaximumHeight(40)" not in src      # 截图遮挡根因已修复
    assert "class AIInterpretDialog(QDialog)" not in src
    assert "MainWindow" + ".show()" not in src


def test_static_discipline_qapp_sanity(qapp):
    # 宿主为普通 QWidget（构造面与既有 test_ai_drawer 一致，可被实例化）
    from PyQt6.QtWidgets import QDialog

    assert issubclass(ai.AIInterpretDialog, QWidget)
    assert not issubclass(ai.AIInterpretDialog, QDialog)
