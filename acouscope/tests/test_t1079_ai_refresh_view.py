# SPDX-License-Identifier: GPL-3.0-only
"""T-1079 ⑤：AI 释图面板预载截图随视图切换刷新（离屏；不构造主窗口）。

覆盖判据「面板在视图 A → 切到 B → 附件/标注跟随，草稿正文不清空」：
  ① 预填锚点：进入时附件名 = 「当前视图 · <视图名>」、_prefilled_context 记录；
  ② 切换刷新：refresh_attached_view() 重取 image/context/view_name 三 getter，
     附件 b64/缩略图/标注更新、未改动草稿推新上下文；
  ③ 用户已输入草稿正文：刷新后原样保留、不被覆盖；
  ④ 用户移除预载附件后不复活（refresh 不新增附件）；
  ⑤ 宿主接线（源码形态守卫）：_on_analysis_changed 内、右栏在 AI 页时调用
     refresh_attached_view()（主窗口顶层显示在离屏挂起黑名单内，无法实例化）。
"""

import base64
import pathlib

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
from PyQt6.QtGui import QImage

from acouscope.i18n import tr
from acouscope.ui.widgets import ai_interpret as ai

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_MAIN_WINDOW = _REPO_ROOT / "src" / "acouscope" / "ui" / "main_window.py"

_VIEW_A = "FFT 频谱"
_VIEW_B = "节奏分析"
_CTX_A = "峰值 0.42 / BPM 120"
_CTX_B = "峰值 0.87 / BPM 96"


def _png_bytes(color: int, width: int = 24, height: int = 16) -> bytes:
    img = QImage(width, height, QImage.Format.Format_ARGB32)
    img.fill(color)
    buf = QByteArray()
    dev = QBuffer(buf)
    dev.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(dev, "PNG")
    dev.close()
    return bytes(buf)


class _Switchable:
    """可变视图状态：image/context/view_name 三 getter 同时指向它。"""

    def __init__(self):
        self.view = _VIEW_A
        self.context = _CTX_A
        self.image = _png_bytes(0xFF336699)

    def image_getter(self):
        return self.image

    def context_getter(self):
        return self.context

    def view_name_getter(self):
        return self.view

    def switch_to_b(self):
        self.view = _VIEW_B
        self.context = _CTX_B
        self.image = _png_bytes(0xFFCC2200)


def _make_panel(monkeypatch, state):
    monkeypatch.setattr(ai, "_config_paths", lambda: [])
    return ai.AIInterpretDialog(
        image_getter=state.image_getter,
        context_getter=state.context_getter,
        view_name_getter=state.view_name_getter,
    )


# ----------------------------------------------------------------------
# ① 预填锚点
# ----------------------------------------------------------------------


def test_prefill_records_anchor_with_view_name(qapp, monkeypatch):
    state = _Switchable()
    p = _make_panel(monkeypatch, state)
    try:
        assert len(p.attached_images) == 1
        item = p.attached_images[0]
        assert item is p._prefill_item
        expected = "{} · {}".format(tr("ai_panel.attach_current_view"), _VIEW_A)
        assert item["name"] == expected
        assert item["thumb"].toolTip() == expected
        assert item["b64"] == base64.b64encode(state.image).decode("ascii")
        assert p._prefilled_context == _CTX_A
        assert p.input_edit.toPlainText() == _CTX_A
    finally:
        p.deleteLater()


# ----------------------------------------------------------------------
# ② 切换刷新：附件 + 标注 + 未改动草稿跟随
# ----------------------------------------------------------------------


def test_refresh_follows_view_switch(qapp, monkeypatch):
    state = _Switchable()
    p = _make_panel(monkeypatch, state)
    try:
        old_b64 = p.attached_images[0]["b64"]
        state.switch_to_b()
        p.refresh_attached_view()
        item = p.attached_images[0]
        assert len(p.attached_images) == 1        # 原位更新，不新增
        assert item["b64"] == base64.b64encode(state.image).decode("ascii")
        assert item["b64"] != old_b64
        expected = "{} · {}".format(tr("ai_panel.attach_current_view"), _VIEW_B)
        assert item["name"] == expected
        assert item["thumb"].toolTip() == expected
        # 草稿未改动 → 推新上下文
        assert p.input_edit.toPlainText() == _CTX_B
        assert p._prefilled_context == _CTX_B
    finally:
        p.deleteLater()


# ----------------------------------------------------------------------
# ③ 用户已输入草稿正文：保留不覆盖（附件仍刷新）
# ----------------------------------------------------------------------


def test_refresh_preserves_user_typed_draft(qapp, monkeypatch):
    state = _Switchable()
    p = _make_panel(monkeypatch, state)
    try:
        typed = "这个高频为什么会这样？"
        p.input_edit.setPlainText(typed)
        state.switch_to_b()
        p.refresh_attached_view()
        assert p.input_edit.toPlainText() == typed   # 正文原样保留
        item = p.attached_images[0]
        assert item["b64"] == base64.b64encode(state.image).decode("ascii")
        assert _VIEW_B in item["name"]
    finally:
        p.deleteLater()


# ----------------------------------------------------------------------
# ④ 用户移除预载附件 → 不复活
# ----------------------------------------------------------------------


def test_refresh_does_not_revive_removed_attachment(qapp, monkeypatch):
    state = _Switchable()
    p = _make_panel(monkeypatch, state)
    try:
        p._remove_attachment(p.attached_images[0])
        assert p.attached_images == []
        state.switch_to_b()
        p.refresh_attached_view()
        assert p.attached_images == []           # 不复活
        assert p.input_edit.toPlainText() == _CTX_B  # 草稿仍随未改动语义刷新
    finally:
        p.deleteLater()


# ----------------------------------------------------------------------
# ⑤ 宿主接线源码守卫（主窗口不可离屏实例化）
# ----------------------------------------------------------------------


def test_main_window_calls_refresh_in_analysis_changed():
    """★ 2026-11-10 订正：调用点已由 `_on_analysis_changed` 抽入视图切换共用收尾
    `_sync_analysis_view_chrome`（该函数仍由 _on_analysis_changed 调用），
    断言锚点随迁；三处门控条件不变。"""
    src = _MAIN_WINDOW.read_text(encoding="utf-8")
    caller = src.index("def _on_analysis_changed")
    caller_body = src[caller:src.index("def ", caller + len("def _on_analysis_changed"))]
    assert "_sync_analysis_view_chrome(" in caller_body, "收尾函数须仍由切换入口调用"
    start = src.index("def _sync_analysis_view_chrome")
    body = src[start:src.index("def ", start + len("def _sync_analysis_view_chrome"))]
    # 门控：仅当 _ai_panel 存在且右栏当前页 = AI 宿主（镜像 set_view_name 范式）
    assert "panel_ai.refresh_attached_view()" in body
    assert 'getattr(self, "_ai_panel", None)' in body
    assert "self.right_content.currentWidget() is self._ai_host" in body
