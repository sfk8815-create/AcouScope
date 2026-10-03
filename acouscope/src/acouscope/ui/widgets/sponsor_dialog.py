# SPDX-License-Identifier: GPL-3.0-only
"""极温和赞助致谢对话框（开源化后的启动问候；第 5 次启动起、此后每次启动均弹，非推广）。

形态（项目负责人定稿；T-1110 反转 #3 后语义）：
- QDialog **非模态**（``setModal(False)`` + ``show()``，**禁 ``exec()``**），Esc 可关闭；
- 无强制等待、不采集设备标识、不影响任何功能；
- 自动弹条件 = 第 5 次启动起、此后每次启动均弹（计数依据见 :mod:`acouscope.state`）；
- 停弹**只**由「已支持，不再提醒」永久生效，只写入 ``app_state.json``
  （见 :mod:`acouscope.state`），与旧许可状态文件完全切割。

GUI 白名单登记：``内部记录/knowledge/GUI_dialog_inventory.md``（本类新增一行）。
"""

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
from acouscope.state import set_sponsor_reminder_dismissed

#: 二维码显示边长（逻辑尺寸；整数参数交给 QPixmap.scaled，样式表内无长度字面量）
QR_CODE_SIZE = 180

#: 二维码资源目录（随包分发）
PAYMENTS_DIR = Path(__file__).resolve().parents[2] / "resources" / "payments"

#: （i18n 键后缀, 文件名）——支付宝 / 微信并排
QR_CODES = (
    ("zhifubao", "zhifubao.JPG"),
    ("weixin", "weixin.JPG"),
)


def load_qr_pixmap(filename: str) -> QPixmap | None:
    """加载二维码位图并等比缩放。

    Returns:
        缩放后的 QPixmap；文件缺失或解码失败返回 None（由调用方显示占位）。
    """
    path = PAYMENTS_DIR / filename
    if not path.exists():
        return None
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return None
    return pixmap.scaled(
        QR_CODE_SIZE,
        QR_CODE_SIZE,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class SponsorDialog(QDialog):
    """赞助致谢框（非模态；两枚按钮：继续使用 / 已支持，不再提醒）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("sponsor.window_title"))
        self.setModal(False)
        self._centered = False
        self._qr_labels: list[QLabel] = []
        self._build_ui()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        heading = QLabel(tr("sponsor.heading"), self)
        heading.setWordWrap(True)
        root.addWidget(heading)

        body = QLabel(tr("sponsor.body"), self)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(body)

        root.addLayout(self._build_qr_row())
        root.addLayout(self._build_buttons())

    def _build_qr_row(self) -> QHBoxLayout:
        """支付宝 / 微信二维码并排；缺失侧显示占位文案。"""
        row = QHBoxLayout()
        for key, filename in QR_CODES:
            column = QVBoxLayout()
            pixmap = load_qr_pixmap(filename)
            if pixmap is None:
                label = QLabel(tr("sponsor.qr_missing"), self)
            else:
                label = QLabel(self)
                label.setPixmap(pixmap)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._qr_labels.append(label)
            column.addWidget(label)

            caption = QLabel(tr(f"sponsor.qr_{key}"), self)
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column.addWidget(caption)
            row.addLayout(column)
        return row

    def _build_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch(1)

        self.btn_continue = QPushButton(tr("sponsor.continue"), self)
        self.btn_continue.setObjectName("sponsorContinueButton")
        self.btn_continue.setDefault(True)
        self.btn_continue.clicked.connect(self._on_continue)
        row.addWidget(self.btn_continue)

        self.btn_dismiss = QPushButton(tr("sponsor.dismiss"), self)
        self.btn_dismiss.setObjectName("sponsorDismissButton")
        self.btn_dismiss.clicked.connect(self._on_dismiss)
        row.addWidget(self.btn_dismiss)
        return row

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _on_continue(self) -> None:
        """「继续使用」：直接关闭（不写任何状态）。"""
        self.close()

    def _on_dismiss(self) -> None:
        """「已支持，不再提醒」：持久化标记后关闭（写失败也不阻塞关闭）。"""
        set_sponsor_reminder_dismissed(True)
        self.close()

    def qr_labels(self) -> list[QLabel]:
        """二维码/占位标签列表（供测试断言，顺序同 QR_CODES）。"""
        return list(self._qr_labels)

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
