# SPDX-License-Identifier: GPL-3.0-only
"""T-1112 守卫：主窗常驻「微信群」闪耀入口与官方群二维码窗（新增 3 例）。

- 例1：闪耀按钮形态（图文并存 / 恒定占位）+ 有限透明度呼吸（反无限循环 / 反瞬弹）；
- 例2：二维码窗非模态（零 exec 字面）、缺图占位容错、关闭按钮与资源在位；
- 例3：主窗接线端到端 —— 行内索引与全局 x 双证在心跳钮左侧、点击开窗且同源复用、
        心跳钮零回归（以结构指纹识别，不直书其类名）、三语文案非空且 label≠tip。

纪律：全离屏（不展示主窗口顶层）；白名单铁律 ⇒ 本档零禁忌字面
（受 test_open_source_clean 全仓扫描约束，见该档白名单）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QAbstractAnimation, QPoint, Qt
from PyQt6.QtWidgets import QDialog, QLabel, QToolButton

from acouscope.i18n import available_languages, get_language, set_language, tr
from acouscope.ui.widgets import weixin_group_button as wb
from acouscope.ui.widgets import weixin_group_dialog as wd
from acouscope.ui.widgets.weixin_group_button import WeixinGroupButton
from acouscope.ui.widgets.weixin_group_dialog import WeixinGroupDialog


# ---------------------------------------------------------------------------
# ① 形态：图文并存 + 恒定占位 + 有限闪耀
# ---------------------------------------------------------------------------


def test_shimmer_button_form_and_finite_animation(qapp):
    btn = WeixinGroupButton()
    assert isinstance(btn, QToolButton)
    # QToolButton 默认 IconOnly 会把文字吞掉不可见 ⇒ 必须显式图文并存（只看 text() 会被骗）
    assert btn.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    assert btn.text() == tr("weixin_group.label")
    assert btn.toolTip() == tr("weixin_group.tip")
    assert btn.icon().isNull() is False

    # 恒定占位：透明度呼吸零尺寸变化 ⇒ 外接矩形与心跳钮一致、行高不抬升
    assert btn.width() == wb._BTN_W_PX
    assert btn.height() == wb._BTN_H_PX <= 28
    assert btn.minimumSize() == btn.maximumSize()

    # 反无限循环 + 反瞬弹：有限圈数、起止同值，一放一收靠中段关键帧
    assert btn._shimmer.loopCount() != 0
    assert btn._shimmer.loopCount() in (wb._SHIMMER_LOOPS, wb._HOVER_LOOPS)
    assert btn._shimmer.duration() == wb._SHIMMER_MS
    assert float(btn._shimmer.startValue()) == float(btn._shimmer.endValue()) == 1.0
    assert float(btn._shimmer.keyValueAt(0.5)) == wb._SHIMMER_MIN_OPACITY
    assert btn.graphicsEffect() is btn._effect
    assert btn._effect.opacity() == 1.0  # QGraphicsOpacityEffect 默认 0.7 ⇒ 须显式归满

    scan = []
    for t_ms in range(0, wb._SHIMMER_MS * wb._SHIMMER_LOOPS + 1, 10):
        btn._shimmer.setCurrentTime(t_ms)
        scan.append(round(float(btn._shimmer.currentValue()), 4))
    assert min(scan) == round(wb._SHIMMER_MIN_OPACITY, 4)
    assert max(scan) == 1.0
    first_loop = scan[: wb._SHIMMER_MS // 10 + 1]
    downs = [i for i in range(1, len(first_loop)) if first_loop[i] < first_loop[i - 1]]
    ups = [i for i in range(1, len(first_loop)) if first_loop[i] > first_loop[i - 1]]
    assert downs and ups and max(downs) < min(ups), "首圈非「先收后放」：中段反弹"

    # 触发纪律：首次可见一次（showEvent 闸门）+ 运行中重入被拦 + 悬停单圈
    assert btn._shimmered is False
    btn.show()
    qapp.processEvents()
    assert btn._shimmered is True
    assert btn._shimmer.state() == QAbstractAnimation.State.Running
    btn._shimmer.stop()
    btn.close()

    btn._start_shimmer(wb._HOVER_LOOPS)
    assert btn._shimmer.loopCount() == wb._HOVER_LOOPS
    btn._start_shimmer(wb._SHIMMER_LOOPS)  # 运行中重入 ⇒ 闸门拦下，圈数不变
    assert btn._shimmer.loopCount() == wb._HOVER_LOOPS
    btn._shimmer.stop()

    # 回调接线：值 → 透明度呼吸；结束 → 归满
    btn._on_shimmer_value(wb._SHIMMER_MIN_OPACITY)
    assert btn._effect.opacity() == wb._SHIMMER_MIN_OPACITY
    btn._on_shimmer_finished()
    assert btn._effect.opacity() == 1.0


# ---------------------------------------------------------------------------
# ② 二维码窗：非模态 / 占位容错 / 关闭
# ---------------------------------------------------------------------------


def test_dialog_non_modal_placeholder_and_close(qapp, monkeypatch, tmp_path):
    # 静态：零 .exec( 字面（非模态硬证；走 show()/close() 路线）
    src = Path(wd.__file__).read_text(encoding="utf-8")
    assert ".exec(" not in src

    # 资源在位：成品 PNG（非源图名）且可解码、文件名固定
    assert wd.GROUP_QR_FILE == "weixin_group.png"
    assert (wd.WEIXIN_DIR / wd.GROUP_QR_FILE).stat().st_size > 0

    dlg = WeixinGroupDialog()
    assert isinstance(dlg, QDialog)
    assert dlg.isModal() is False
    assert dlg.windowTitle() == tr("weixin_group.window_title")
    assert dlg.btn_close.objectName() == "weixinCloseButton"
    assert isinstance(dlg.qr_label(), QLabel)
    pm = dlg.qr_label().pixmap()
    assert pm.isNull() is False
    assert pm.width() <= wd.QR_DISPLAY_PX and pm.height() <= wd.QR_DISPLAY_PX

    dlg.show()
    qapp.processEvents()
    assert dlg.isVisible() is True
    assert dlg.isModal() is False  # show 之后仍非模态
    dlg.btn_close.click()
    assert dlg.isVisible() is False

    # 缺图容错：目录不存在 ⇒ 占位文案、绝不抛异常、pixmap 为空
    monkeypatch.setattr(wd, "WEIXIN_DIR", tmp_path / "no_such_dir")
    assert wd.load_group_qr_pixmap() is None
    fallback = WeixinGroupDialog()
    assert fallback.qr_label().pixmap().isNull() is True
    assert fallback.qr_label().text() == tr("weixin_group.qr_missing")


# ---------------------------------------------------------------------------
# ③ 主窗接线端到端
# ---------------------------------------------------------------------------


@pytest.fixture
def window(qapp, tmp_path):
    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 0.5)) / sr
    controller.load_from_array(0.5 * np.sin(2 * np.pi * 200 * t), sr)
    w = MainWindow(controller)
    yield w
    w.close()


def test_wiring_left_of_encourage_and_instance_reuse(window, qapp):
    btn = window.btn_weixin
    assert isinstance(btn, WeixinGroupButton)
    assert btn.icon().isNull() is False
    assert btn.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    assert btn.text() == tr("weixin_group.label")
    assert btn.height() <= 28
    assert btn.minimumSize() == btn.maximumSize()
    assert btn._shimmer.loopCount() != 0
    assert float(btn._shimmer.startValue()) == float(btn._shimmer.endValue())

    # ① 双证：行内索引 + 全局 x 均在心跳钮左侧
    peer = window.btn_encourage
    row_layout = btn.parentWidget().layout()
    assert peer.parentWidget() is btn.parentWidget(), "两钮须同处提示条行"
    idx_weixin = row_layout.indexOf(btn)
    idx_peer = row_layout.indexOf(peer)
    assert 0 <= idx_weixin < idx_peer, f"行内序：{idx_weixin} !< {idx_peer}"
    row_layout.activate()
    qapp.processEvents()
    x_weixin = btn.mapTo(window, QPoint(0, 0)).x()
    x_peer = peer.mapTo(window, QPoint(0, 0)).x()
    assert x_weixin < x_peer, f"全局 x：{x_weixin} !< {x_peer}"

    # ⑤ 点击 ⇒ 信号一次 + 新框可见 / 非模态 / 二维码在位且尺寸上界
    before = {id(d) for d in window.findChildren(QDialog)}
    hits = []
    btn.weixinRequested.connect(lambda: hits.append(1))
    btn.click()
    assert hits == [1]
    new = [d for d in window.findChildren(QDialog) if id(d) not in before]
    assert len(new) == 1, "点击未产生二维码窗"
    dlg = new[0]
    assert isinstance(dlg, WeixinGroupDialog)
    assert dlg.isVisible() is True
    assert dlg.isModal() is False
    assert dlg.parent() is window
    pm = dlg.qr_label().pixmap()
    assert pm.isNull() is False and pm.width() <= wd.QR_DISPLAY_PX

    # 再点一次复用同一实例
    btn.click()
    again = [d for d in window.findChildren(QDialog) if id(d) not in before]
    assert len(again) == 1 and again[0] is dlg

    # 心跳钮零回归：点击仍开既有的赞助框（本档不直书其类名：结构指纹=双二维码标签）
    for d in window.findChildren(QDialog):
        if d is not dlg:
            d.close()
    qapp.processEvents()
    window.btn_encourage.click()
    qapp.processEvents()
    others = [d for d in window.findChildren(QDialog) if d is not dlg and d.isVisible()]
    assert len(others) == 1, "点击心跳钮后未见既有赞助框（零回归失守）"
    assert len(others[0].qr_labels()) == 2

    # ⑥ 三语：label/tip/body/qr_caption 非空且 label ≠ tip
    lang_backup = get_language()
    try:
        for lang in available_languages():
            set_language(lang)
            label = tr("weixin_group.label")
            tip = tr("weixin_group.tip")
            body = tr("weixin_group.body")
            caption = tr("weixin_group.qr_caption")
            assert label and tip and body and caption, f"{lang} 文案缺失"
            assert label != tip, f"{lang} label 与 tip 雷同（短标签未独立）"
    finally:
        set_language(lang_backup)