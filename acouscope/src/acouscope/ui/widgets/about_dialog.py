# SPDX-License-Identifier: GPL-3.0-only
"""关于对话框：LOGO + 版本 + 作者/版权 + 特别鸣谢 + 致谢 + 系统信息。

内容随界面语言切换（zh_CN / zh_TW / en_US）。
LOGO 自动裁剪空白边缘并保持原比例缩放。

模态形态沿革：
- T-504e 曾随帮助/设置族去模态化（QWidget + 抽屉承载）；
- CB-010 用户特批「关于」回归模态 QDialog（AboutDialog 为模态例外，
  快速入门/用户手册维持 QWidget 抽屉不动），本模块即该例外的宿主。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QPushButton,
)

# 双下划线名在类体内会被 Python 名字改写（_ClassName__x），
# 故导入为普通别名，类内一律用别名
from acouscope import (
    __app_name__ as _APP_NAME,
    __app_name_cn__ as _APP_NAME_CN,
    __version__ as _APP_VERSION,
    __version_suffix as _APP_VERSION_SUFFIX,
)
from acouscope.i18n import tr
from acouscope.ui import theme
from acouscope.ui.constants import SITE_MAIN_URL, open_site


def _logo_path() -> Path:
    """定位 LOGO SVG（开发目录 / PyInstaller 解包目录均可）。"""
    return Path(__file__).resolve().parents[2] / "resources" / "jinyun_logo.svg"


def render_logo(height_px: int = 76) -> QPixmap | None:
    """渲染工作室 LOGO。

    先按 SVG 原生尺寸渲染，扫描非透明像素裁掉空白边缘，
    再等比缩放到目标高度（不改变原比例）。
    """
    path = _logo_path()
    if not path.exists():
        return None

    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        return None

    size = renderer.defaultSize()
    img = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    renderer.render(painter)
    painter.end()

    # 自动裁剪：扫描 alpha 通道找内容包围盒
    # PyQt6 constBits() 返回 sip.voidptr，须用 asstring() 取字节
    bpl = img.bytesPerLine()
    try:
        buf = img.constBits().asstring(img.sizeInBytes())
    except AttributeError:
        buf = img.constBits().tobytes()  # 兼容支持 buffer 协议的版本
    if buf is None or bpl <= 0:
        return None
    arr = np.frombuffer(buf, dtype=np.uint8).reshape(img.height(), bpl)
    alpha = arr[:, : img.width() * 4].reshape(img.height(), img.width(), 4)[:, :, 3]
    ys, xs = np.nonzero(alpha > 8)
    if len(xs) == 0 or len(ys) == 0:
        return None

    left, right = int(xs.min()), int(xs.max()) + 1
    top, bottom = int(ys.min()), int(ys.max()) + 1
    cropped = img.copy(left, top, right - left, bottom - top)

    pm = QPixmap.fromImage(cropped)
    w = max(1, round(pm.width() * height_px / pm.height()))
    return pm.scaled(
        w, height_px,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _hline() -> QFrame:
    from acouscope.ui.theme import style_when_theme

    line = QFrame()
    line.setFrameShape(QFrame.Shape.NoFrame)
    line.setFixedHeight(1)
    style_when_theme(line, lambda c: f"background: {c['border']};")
    return line


class ClickableLabel(QLabel):
    """可点击 QLabel：左键单击发 clicked（悬停手型）。

    T-1015 供 LOGO（关于对话框 / 主工具栏）复用为可点击链接控件；
    点击处理由调用方 connect clicked 完成，控件自身不打开任何外链。
    """

    clicked = pyqtSignal()

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class AboutDialog(QDialog):
    """关于 AcouScope 对话框（模态，CB-010 用户特批回归）。

    内容/样式与抽屉版本完全一致，仅承载形态由 QWidget（抽屉宿主）改为
    QDialog：模态 exec() 弹出、居中主窗，关闭按钮/窗口 ✕ 均关闭。
    快速入门/用户手册仍为 QWidget 抽屉，不受本例外影响。
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle(tr("about.title"))
        self.setMinimumWidth(560)
        self.setModal(True)  # CB-010 用户特批模态（登记 deviations）

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(24, 20, 24, 16)

        # ---- LOGO（居中；T-1015 可点击 → 主站）----
        logo = render_logo(72)
        if logo is not None:
            logo_row = QHBoxLayout()
            logo_row.addStretch(1)
            self.lbl_logo = ClickableLabel()
            self.lbl_logo.setPixmap(logo)
            self.lbl_logo.setObjectName("aboutLogo")
            self.lbl_logo.setToolTip(
                f"{tr('action.visit_site')}\n{SITE_MAIN_URL}"
            )
            self.lbl_logo.clicked.connect(self._open_main_site)
            logo_row.addWidget(self.lbl_logo)
            logo_row.addStretch(1)
            layout.addLayout(logo_row)
            layout.addSpacing(4)

        # ---- 应用名 + 版本 ----
        title = QLabel(
            f"<div style='text-align:center;'>"
            f"<span style='font-size:20px; font-weight:600;'>{_APP_NAME}</span>"
            f"&nbsp;&nbsp;<span style='font-size:13px; color:{theme.colors()['text_sub']};'>{_APP_NAME_CN}</span>"
            f"</div>"
        )
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        ver = QLabel(
            f"<span style='color:{theme.colors()['text_sub']}; font-size:12px;'>"
            f"{tr('about.version')}: {_APP_VERSION} ({_APP_VERSION_SUFFIX})"
            f"</span>"
        )
        ver.setTextFormat(Qt.TextFormat.RichText)
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(ver)

        # ---- 主站地址行（T-1015：列出主站，点击链接 → 主站；仅用户点击触发）----
        self.lbl_site_link = QLabel(
            f"{tr('about.website')}: "
            f"<a href='{SITE_MAIN_URL}'>{SITE_MAIN_URL}</a>"
        )
        self.lbl_site_link.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_site_link.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_site_link.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        # openExternalLinks 保持 False：链接激活经 linkActivated → open_site
        # （QDesktopServices.openUrl），便于统一封装与测试观测
        self.lbl_site_link.linkActivated.connect(open_site)
        layout.addWidget(self.lbl_site_link)

        layout.addWidget(_hline())

        # ---- 描述 / 技术栈 / 许可 ----
        for text in (tr("about.desc"), tr("about.tech"), tr("about.license")):
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("font-size: 12px;")
            layout.addWidget(lbl)

        layout.addWidget(_hline())

        # ---- 作者 / 版权 ----
        author_row = QLabel(
            f"<table width='100%' style='font-size:12px;' cellspacing='0' cellpadding='2'>"
            f"<tr>"
            f"<td style='color:{theme.colors()['text_sub']}; text-align:right; width:32%; padding-right:8px;'>{tr('about.author_label')}</td>"
            f"<td>{tr('about.author_name')}</td>"
            f"</tr><tr>"
            f"<td style='color:{theme.colors()['text_sub']}; text-align:right; padding-right:8px;'>Copyright</td>"
            f"<td>{tr('about.copyright')}</td>"
            f"</tr></table>"
        )
        author_row.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(author_row)

        rights = QLabel(tr("about.rights"))
        rights.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rights.setStyleSheet("font-size: 12px;")
        layout.addWidget(rights)

        layout.addWidget(_hline())

        # ---- 特别鸣谢并献予 ----
        ded = QLabel(
            f"<div style='text-align:center;'>"
            f"<span style='font-size:12px; color:{theme.colors()['text_sub']};'>{tr('about.ded_title')}</span><br/>"
            f"<span style='font-size:15px; font-weight:600;'>{tr('about.ded_name')}</span><br/>"
            f"<span style='font-size:11px; color:{theme.colors()['text_sub']};'>{tr('about.ded_desc')}</span>"
            f"</div>"
        )
        ded.setTextFormat(Qt.TextFormat.RichText)
        ded.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(ded)

        layout.addWidget(_hline())

        # ---- 致谢 ----
        ack = QLabel(f"<b>{tr('about.ack_title')}</b><br/>{tr('about.ack_body')}")
        ack.setTextFormat(Qt.TextFormat.RichText)
        ack.setWordWrap(True)
        ack.setStyleSheet("font-size: 12px;")
        layout.addWidget(ack)

        layout.addWidget(_hline())

        # ---- 系统信息 ----
        import platform as _plt

        sys_info = QLabel(
            f"<table style='font-size:11px; color:{theme.colors()['text_sub']};' cellspacing='0' cellpadding='1'>"
            f"<tr><td style='text-align:right; padding-right:8px;'>Python:</td><td>{_plt.python_version()}</td></tr>"
            f"<tr><td style='text-align:right; padding-right:8px;'>OS:</td><td>{_plt.system()} {_plt.machine()}</td></tr>"
            f"</table>"
        )
        sys_info.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(sys_info)

        # ---- 关闭按钮（模态对话框语义：accept 关闭并结束 exec）----
        self.btn_close = QPushButton(tr("btn.close"))
        self.btn_close.clicked.connect(self.accept)
        layout.addWidget(self.btn_close)

    def _open_main_site(self) -> None:
        """LOGO / 网站链接点击 → 打开主站（T-1015；仅用户点击触发，禁自动打开）。"""
        open_site(SITE_MAIN_URL)
