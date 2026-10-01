# SPDX-License-Identifier: GPL-3.0-only
"""「微信群」常驻入口的二维码窗（非模态；二维码随包分发，缺图回落占位文案）。"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from acouscope.i18n import tr

#: 二维码显示边长（逻辑尺寸；整数参数交给 QPixmap.scaled，样式表内无长度字面量）
QR_DISPLAY_PX = 280

#: 二维码资源目录（随包分发）
WEIXIN_DIR = Path(__file__).resolve().parents[2] / "resources" / "weixin"

#: 群二维码文件名（PNG 二值化无损图；目标名固定，禁沿用源图名）
GROUP_QR_FILE = "weixin_group.png"

#: 版面小间距（间距一律走布局默认 + 本常量，禁 px 字面量）
_GAP_PX = 8


def load_group_qr_pixmap() -> QPixmap | None:
    """加载群二维码位图并等比缩放。

    Returns:
        缩放后的 QPixmap；文件缺失或解码失败返回 None（由调用方显示占位）。
    """
    path = WEIXIN_DIR / GROUP_QR_FILE
    if not path.exists():
        return None
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return None
    return pixmap.scaled(
        QR_DISPLAY_PX,
        QR_DISPLAY_PX,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class WeixinGroupDialog(QDialog):
    """官方微信群二维码窗（非模态；单实例复用由宿主持有，与赞助框同构）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("weixin_group.window_title"))
        self.setModal(False)
        self._centered = False
        self._build_ui()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        heading = QLabel(tr("weixin_group.heading"), self)
        heading.setWordWrap(True)
        root.addWidget(heading)

        body = QLabel(tr("weixin_group.body"), self)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(body)

        pixmap = load_group_qr_pixmap()
        self._qr_label = QLabel(self)
        if pixmap is None:
            self._qr_label.setText(tr("weixin_group.qr_missing"))
        else:
            self._qr_label.setPixmap(pixmap)
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._qr_label)

        root.addSpacing(_GAP_PX)
        qr_caption = QLabel(tr("weixin_group.qr_caption"), self)
        qr_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(qr_caption)

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_close = QPushButton(tr("weixin_group.close"), self)
        self.btn_close.setObjectName("weixinCloseButton")
        self.btn_close.clicked.connect(self.close)
        row.addWidget(self.btn_close)
        root.addLayout(row)

    # ------------------------------------------------------------------
    # 对外只读
    # ------------------------------------------------------------------
    def qr_label(self) -> QLabel:
        """二维码/占位标签（供测试断言）。"""
        return self._qr_label

    def showEvent(self, event) -> None:
        """首次显示时相对父窗口居中（非模态，不抢模态焦点）。"""
        super().showEvent(event)
        if self._centered:
            return
        self._centered = True
        parent = self.parentWidget()
        if parent is None:
            return
        frame = self.frameGeometry()
        frame.moveCenter(parent.frameGeometry().center())
        self.move(frame.topLeft())