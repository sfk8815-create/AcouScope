# SPDX-License-Identifier: GPL-3.0-only
"""T-1018：AI 释图窗「对话式」重做验收（离屏；不 MainWindow.show() / QDialog / 模态 exec）。

覆盖（需求说明 Step 5）：
- 顶部只读模型行（读 ai_config；未配置 → 设置引导）+ ⚙ 设置按钮（点击 → 设置-AI
  两步序列 spy：_activate_settings_tab() → switch_to_tab("ai")）；
- 去设置项：无发送图像开关 / 模型设置按钮 / 测试连接按钮（findChildren 断言）；
  T-1020 D 起顶部含**模型来源三档下拉**（仅写 ai_v2.source 单键，见
  tests/test_ai_config_persist.py），故下拉相关断言按非静默归因收紧改写；
- 消息对话流：用户消息含图片缩略图（QPixmap 非空）、AI 流式追加、自动滚底（scrollbar）；
- 输入框：数值上下文预填且可编辑、Ctrl+V 贴图与拖入图片 → attachedImages 增加 + 预览 + 移除、
  回车发送 / Shift+Enter 换行；
- 输入区可拉高（QSplitter 拖拽，clamp 上下限）；复用既有释图流程（引擎零改）；
- 静态纪律（禁词 / hex-px / QDialog / setHandleWidth 字面量）。
"""

import json
import pathlib
import re
import sys

import pytest

sys.path.insert(0, "src")
pytest.importorskip("PyQt6")

from PyQt6.QtCore import (
    QBuffer,
    QByteArray,
    QEvent,
    QIODevice,
    QMimeData,
    Qt,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import QImage, QKeyEvent, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)

from acouscope.i18n import tr
from acouscope.ui.widgets import ai_interpret as ai

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SRC = (_REPO_ROOT / "src" / "acouscope" / "ui" / "widgets" / "ai_interpret.py")
_BANNED = "Mel" + "odyne"

_CONTEXT = "【数值上下文】测试上下文"


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------

def _png_bytes(width: int = 24, height: int = 16) -> bytes:
    img = QImage(width, height, QImage.Format.Format_ARGB32)
    img.fill(0xFF336699)
    buf = QByteArray()
    dev = QBuffer(buf)
    dev.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(dev, "PNG")
    dev.close()
    return bytes(buf)


def _pixmap() -> QPixmap:
    pix = QPixmap()
    pix.loadFromData(_png_bytes())
    return pix


def _make_panel(monkeypatch, image_getter=None, context_getter=None,
                paths=()):
    """离屏面板（_config_paths 打桩，绝不写真实用户配置）。"""
    monkeypatch.setattr(ai, "_config_paths", lambda: list(paths))
    return ai.AIInterpretDialog(
        image_getter=image_getter if image_getter is not None else (lambda: None),
        context_getter=(context_getter if context_getter is not None
                        else (lambda: _CONTEXT)),
        view_name_getter=lambda: "FFT 频谱",
    )


def _shown(qapp, monkeypatch, width=560, height=460, **kw):
    """顶层直显（普通 QWidget，非 MainWindow）：精确控制面板尺寸供几何断言。"""
    panel = _make_panel(monkeypatch, **kw)
    panel.resize(width, height)
    panel.show()
    qapp.processEvents()
    return panel


def _key(key, modifiers=Qt.KeyboardModifier.NoModifier) -> QKeyEvent:
    return QKeyEvent(QEvent.Type.KeyPress, key, modifiers, "")


def _write_cfg(tmp_path, data: dict):
    cfg = tmp_path / "ai_config.json"
    cfg.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return cfg


# ----------------------------------------------------------------------
# §1 顶部只读状态行 + 设置按钮
# ----------------------------------------------------------------------

def test_top_model_line_reads_config(qapp, monkeypatch, tmp_path):
    """只读模型行读 ai_config（T-320 键契约），面板不含可编辑参数控件。

    T-1020 归因（非静默）：T-1018 的「面板无任何下拉框」断言已由 T-1020 D 项
    局部取代——顶部新增**模型来源三档下拉**（仅写 ai_v2.source 单键，见
    tests/test_ai_config_persist.py 的切档落盘用例）。此处断言相应收紧为
    「恰好一个下拉 = 模型来源下拉，且没有 url/model/key 等参数输入控件」，
    守卫强度不降反增。
    """
    cfg = _write_cfg(tmp_path, {
        "provider": "openai", "url": "https://api.openai.com/v1",
        "model": "gpt-4o", "key": "sk-x", "send_image": True,
        "ai_v2": {"source": "cloud", "mode": "official"},
    })
    p = _make_panel(monkeypatch, paths=[cfg])
    try:
        assert p.lbl_model.toolTip() == tr("ai_panel.model_prefix").format(
            model="gpt-4o")
        combos = p.findChildren(QComboBox)
        assert [c.objectName() for c in combos] == ["aiSourceCombo"]
        assert p.cmb_source.currentData() == "cloud"   # 下拉随配置同步
        assert not p.findChildren(QLineEdit)     # 无地址/模型名/密钥输入
        assert p._source == "cloud"
        assert p._current_model_name() == "gpt-4o"
    finally:
        p.deleteLater()


def test_top_model_line_unconfigured_points_to_settings(qapp, monkeypatch,
                                                        tmp_path):
    """未配置模型（自建档空模型名）→ 显示「设置 → AI」引导文案。"""
    cfg = _write_cfg(tmp_path, {
        "provider": "custom", "url": "http://127.0.0.1:11434", "model": "",
        "key": "", "send_image": False,
        "ai_v2": {"source": "self_hosted"},
    })
    p = _make_panel(monkeypatch, paths=[cfg])
    try:
        assert p.lbl_model.toolTip() == tr("ai_panel.unconfigured")
    finally:
        p.deleteLater()


def test_settings_button_jumps_to_settings_ai_tab(qapp, monkeypatch):
    """⚙ → 既有 API 两步序列：_activate_settings_tab() → switch_to_tab("ai")。"""
    calls = []

    class _FakeSettings(QWidget):
        applied = pyqtSignal()

        def __init__(self):
            super().__init__()
            self.tabs = []

        def switch_to_tab(self, name: str):
            self.tabs.append(name)
            calls.append(("tab", name))

    host = QWidget()
    host._activate_settings_tab = lambda: calls.append(("activate", None))
    fake = _FakeSettings()
    host._settings_panel = fake

    monkeypatch.setattr(ai, "_config_paths", lambda: [])
    p = ai.AIInterpretDialog(
        image_getter=lambda: None,
        context_getter=lambda: _CONTEXT,
        view_name_getter=lambda: "FFT 频谱",
        parent=host,
    )
    try:
        assert p.btn_ai_settings.toolTip() == tr("ai_panel.settings_tip")
        p.btn_ai_settings.click()
        assert calls[0] == ("activate", None)      # 先构建/切到设置 tab
        assert calls[1] == ("tab", "ai")           # 再定位 AI 页
        assert fake.tabs == ["ai"]
        # 设置「应用」后重读配置（同会话同步）
        fake.applied.emit()
    finally:
        p.deleteLater()
        host.deleteLater()


# ----------------------------------------------------------------------
# §5 去设置项（控件层面零残留）
# ----------------------------------------------------------------------

def test_no_settings_controls_remain(qapp, monkeypatch):
    """去设置项：参数设置控件（地址/模型名/密钥/开关/测试连接）零残留。

    T-1020 归因（非静默）：原「无任何下拉框」断言把 D 项新增的**模型来源三档
    下拉**也一并否定；该下拉只写 ai_v2.source 单键（非参数控件），故此处改为
    断言「唯一的下拉是来源档位下拉，且档位键值恰为三档」，参数控件与旧控件
    属性名的守卫全部保留（强度不降）。
    """
    p = _make_panel(monkeypatch)
    try:
        combos = p.findChildren(QComboBox)
        assert [c.objectName() for c in combos] == ["aiSourceCombo"]
        assert [p.cmb_source.itemData(i) for i in range(p.cmb_source.count())] \
            == ["builtin", "self_hosted", "cloud"]
        assert not p.findChildren(QCheckBox)
        assert not p.findChildren(QLineEdit)
        texts = [b.text() for b in p.findChildren(QPushButton)]
        for gone in ("测试连接", "模型设置", "开始释图", "发送图像"):
            assert all(gone not in t for t in texts)
        for attr in ("cmb_tier", "cmb_cloud_vendor", "chk_image", "btn_test",
                     "edit_url", "edit_model", "edit_key",
                     "edit_cloud_url", "edit_cloud_model", "edit_cloud_key"):
            assert not hasattr(p, attr), f"旧设置控件残留：{attr}"
    finally:
        p.deleteLater()


# ----------------------------------------------------------------------
# §2 消息对话流
# ----------------------------------------------------------------------

def test_user_message_carries_image_thumbnail(qapp, monkeypatch):
    p = _make_panel(monkeypatch)
    try:
        pix = _pixmap()
        bubble = p._add_bubble("user", "请释读这张图", [pix])
        assert bubble.role == "user"
        assert bubble.thumb_labels, "用户消息应有图片缩略图"
        thumb_pix = bubble.thumb_labels[0].pixmap()
        assert thumb_pix is not None and not thumb_pix.isNull()
        assert bubble.text_view.toPlainText() == "请释读这张图"
        assert bubble.text_view.isReadOnly()          # 可选中复制
        assert p.msg_bubbles == [bubble]
        assert p.msg_hint.isHidden()                  # 起聊后隐藏起始提示
    finally:
        p.deleteLater()


def test_stream_appends_and_scrolls_to_bottom(qapp, monkeypatch):
    """AI 流式追加进当前气泡；消息溢出后自动滚到底（scrollbar value 断言）。"""
    p = _shown(qapp, monkeypatch, height=380,
               image_getter=lambda: _png_bytes())
    try:
        monkeypatch.setattr(ai._InterpretWorker, "start", lambda self: None)
        monkeypatch.setattr(p, "_make_provider", lambda: object())
        captured = []
        monkeypatch.setattr(
            ai, "build_messages",
            lambda **kw: captured.append(kw) or [{"role": "user", "content": "m"}])

        p.input_edit.setPlainText("释读一下")
        p._on_run()
        assert captured and captured[0]["user_question"] == "释读一下"
        assert captured[0]["context"] == _CONTEXT     # 数值上下文仍单点注入
        assert [b.role for b in p.msg_bubbles] == ["user", "assistant"]
        assert p._worker is not None
        assert p.btn_send.isEnabled() is False        # 发送中禁用（防重复）
        assert p.btn_stop.isEnabled() is True

        p._on_chunk("好")
        p._on_chunk("的")
        assert "好的" in p.msg_bubbles[1].text_view.toPlainText()

        for _ in range(14):                           # 造出可滚动内容
            p._add_bubble("assistant", "内容" * 60)
        qapp.processEvents()
        qapp.processEvents()
        bar = p.msg_scroll.verticalScrollBar()
        assert bar.maximum() > 0
        assert bar.value() == bar.maximum()           # 自动滚到底

        p._on_done("完成的答复")
        assert p.btn_send.isEnabled() is True
        assert p.btn_stop.isEnabled() is False
        assert p._chat_messages[-1] == {"role": "assistant",
                                        "content": "完成的答复"}
    finally:
        p.close()


# ----------------------------------------------------------------------
# §3 底部输入框（数值上下文预填 / 图片附件 / 发送键位）
# ----------------------------------------------------------------------

def test_context_prefilled_and_editable(qapp, monkeypatch):
    p = _make_panel(monkeypatch, context_getter=lambda: "【数值上下文】ctx-1",
                    image_getter=lambda: _png_bytes())
    try:
        assert isinstance(p.input_edit, QPlainTextEdit)
        assert p.input_edit.toPlainText() == "【数值上下文】ctx-1"   # 可编辑预填
        assert p.input_edit.isReadOnly() is False
        assert len(p.attached_images) == 1                        # 当前视图截图预附
        assert not p.attached_images[0]["pixmap"].isNull()
        assert p.attach_bar.isHidden() is False                   # 预览行可见
    finally:
        p.deleteLater()


def test_paste_image_becomes_attachment(qapp, monkeypatch):
    """Ctrl+V（剪贴板图片）→ attachedImages 增加 + 缩略图预览；可移除。"""
    p = _make_panel(monkeypatch)
    try:
        p.input_edit.setPlainText("")                 # 清空预填：断言图片不入文本域
        md = QMimeData()
        md.setImageData(QImage.fromData(_png_bytes()))
        QApplication.clipboard().setMimeData(md)
        p.input_edit.paste()
        assert len(p.attached_images) == 1
        thumb = p.attached_images[0]["thumb"]
        assert thumb.pixmap() is not None and not thumb.pixmap().isNull()
        assert p.attached_images[0]["b64"]
        assert p.input_edit.toPlainText() == ""       # 图片不进文本域

        p._remove_attachment(p.attached_images[0])
        assert p.attached_images == []
        assert p.attach_bar.isHidden() is True
    finally:
        p.deleteLater()


def test_dropped_image_file_becomes_attachment(qapp, monkeypatch, tmp_path):
    """拖入图片文件（urls 形态，与 dropEvent 同路径）→ 附件预览。"""
    png = tmp_path / "shot.png"
    png.write_bytes(_png_bytes())
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(png))])
    p = _make_panel(monkeypatch)
    try:
        p.input_edit.setPlainText("")                 # 清空预填：断言不落文件路径文本
        assert p.input_edit.canInsertFromMimeData(md) is True
        p.input_edit.insertFromMimeData(md)
        assert len(p.attached_images) == 1
        assert p.input_edit.toPlainText() == ""
    finally:
        p.deleteLater()


def test_enter_sends_shift_enter_newline(qapp, monkeypatch):
    p = _shown(qapp, monkeypatch, height=420)
    try:
        # 回车会真触发发送 → 打桩 provider/worker，避免真起引擎（零网络/零落盘）
        monkeypatch.setattr(ai._InterpretWorker, "start", lambda self: None)
        monkeypatch.setattr(p, "_make_provider", lambda: object())
        p.input_edit.setPlainText("你好")
        fired = []
        p.input_edit.send_requested.connect(lambda: fired.append(1))
        p.input_edit.keyPressEvent(_key(Qt.Key.Key_Return))
        assert fired == [1]                           # 回车 → 发送
        p.input_edit.keyPressEvent(
            _key(Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier))
        assert fired == [1]                           # Shift+Enter 不发送
        assert p.input_edit.toPlainText().endswith("\n")
    finally:
        p.deleteLater()


# ----------------------------------------------------------------------
# §3 输入区可拉高（QSplitter 拖拽 + 上下限 clamp）
# ----------------------------------------------------------------------

def test_input_area_dragged_taller_with_clamp(qapp, monkeypatch):
    p = _shown(qapp, monkeypatch, height=560)
    try:
        before = p.input_panel.height()
        assert before > 0
        p.splitter.moveSplitter(0, 1)                  # 向上拖到底 → 输入区最大
        qapp.processEvents()
        tall = p.input_panel.height()
        assert tall > before                           # 可向上拉高
        assert tall <= p.input_panel.maximumHeight()   # 上限 clamp

        p.splitter.moveSplitter(p.splitter.height(), 1)  # 向下拖到底 → 输入区最小
        qapp.processEvents()
        low = p.input_panel.height()
        assert low >= p.input_panel.minimumSizeHint().height()   # 下限 clamp
        assert low < tall
        assert p.msg_scroll.height() >= ai._MSG_MIN_HEIGHT
    finally:
        p.close()


# ----------------------------------------------------------------------
# 静态纪律
# ----------------------------------------------------------------------

def test_static_discipline():
    src = _SRC.read_text(encoding="utf-8")
    assert _BANNED not in src
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", src), "禁硬编码 hex 颜色"
    assert not re.search(r"\d+px", src), "禁硬编码像素字面量"
    assert "setHandleWidth(" not in src
    assert "QDialog" not in src                     # 禁新建 QDialog
    assert ".exec(" not in src                      # 禁模态调用字面量
    assert "MainWindow" + ".show()" not in src
    for attr in ("cmb_tier", "cmb_cloud_vendor", "chk_image", "btn_test",
                 "edit_url", "edit_model", "edit_key", "edit_cloud_"):
        assert attr not in src, f"旧设置控件残留：{attr}"


def test_engine_surface_untouched():
    """释图引擎面零改动自检：worker 四信号 + 纯函数路由仍可用。"""
    for sig in ("chunk", "notice", "finished_ok", "failed"):
        assert hasattr(ai._InterpretWorker, sig)
    assert ai._effective_send_image(True, True) is False
    assert ai.friendly_error(Exception("x"))
    assert ai.trim_history([{"role": "user", "content": "a"}])
    assert ai.build_messages("s", "q", "c")[0] == {"role": "system",
                                                   "content": "s"}
