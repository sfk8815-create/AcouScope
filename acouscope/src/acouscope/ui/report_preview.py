# SPDX-License-Identifier: GPL-3.0-only
"""报告内嵌预览面板（T-1103 · C-2/C-3 里程碑 M-B′-β2 · L-3 破例）。

职责：把 ``report_export.build_report_html`` 产的自包含 HTML 同步渲染为
逐页 ``QPixmap`` 预览——与 ``report_pdf.render_report_pdf`` 导出**同源**：
同一 ``setHtml`` → ``QTextDocument`` 管线，预处理复用 α 的
``_clamp_report_images`` / ``_normalize_tables``（同包 import·不改签名），
预览所见即导出所得。

``QTextDocument`` 只支持 CSS 子集（T-1101 探针口径）：``@page`` / margin 对
本路径是死项，故「排版可调」只在 ``QPageSize`` / ``QPageLayout`` 层——方向
（A4 纵/横）+ 边距（毫米）+ dpi；CSS 字号/主题属后续 β2c 另立项。

页数判据 = 文档几何高 / 版心高（``doc.size().height()`` 切页）。★ 禁
``doc.pageCount()``：α 探针实证其 print 后不可靠。

白底纪律：页图 ``QColor("white")`` 填 + HTML body 白双保险，不引 app 主题。
零 QDialog / QThread / QTimer / 网络 / 新依赖；参数控件变更直连刷新槽
（信号驱动·无去抖定时器），渲染在 GUI 线程同步完成（禁自行开线程绕 pin）。
"""

from __future__ import annotations

import math
from typing import Callable

from PyQt6.QtCore import QMarginsF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QPageLayout,
    QPageSize,
    QPainter,
    QPixmap,
    QTextDocument,
)
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from acouscope.i18n import tr
from acouscope.ui.report_pdf import _clamp_report_images, _normalize_tables

# 绘制宽安全边距（pt）：图钳制阈值 = 版心宽 − 此值（与 α _PAINT_SAFETY_PT 同值同口径）
_CLAMP_SAFETY_PT = 8.0

# 预览页显示最大宽（逻辑单位）：超宽页图等比缩到该宽显示，仅影响观感不改数据
_PREVIEW_DISPLAY_MAX_WIDTH = 900

_DPI_CHOICES = (96, 150, 300)
_DPI_DEFAULT_INDEX = 1  # 150

# AI 展示位滚动区高度上限（逻辑单位·T-1106 MC-2）：长文只在内滚动，不撑页区
_AI_VIEW_MAX_HEIGHT = 180


def render_html_pages(
    html: str,
    *,
    page_size_id: QPageSize.PageSizeId = QPageSize.PageSizeId.A4,
    orientation: QPageLayout.Orientation = QPageLayout.Orientation.Portrait,
    margin_mm: float = 16.0,
    dpi: int = 150,
) -> list[QPixmap]:
    """把自包含 HTML 同步渲染为逐页 pixmap 列表（预览与导出同源·离屏可跑）。

    序列（T-1101 探针实证口径）：``setHtml`` → ``QPageLayout``（毫米边距）取
    版心（点单位·与 ``report_pdf`` 同一 ``paintRect`` 调用形态）→
    ``setPageSize`` 定文档布局宽 → α 复用件钳制超宽图 + 规范化无框表 →
    按几何高切页 → 逐页白底新建图，裁剪 + 缩放（dpi/72）+ 纵向平移
    ``-i*版心高`` 后 ``drawContents`` 绘整文档于文档矩形，落页部分由裁剪截得。
    """
    document = QTextDocument()
    document.setHtml(html)

    page_layout = QPageLayout(
        QPageSize(page_size_id),
        orientation,
        QMarginsF(margin_mm, margin_mm, margin_mm, margin_mm),
        QPageLayout.Unit.Millimeter,
    )
    paint = page_layout.paintRect(QPageLayout.Unit.Point)

    document.setPageSize(paint.size())
    _clamp_report_images(document, paint.width() - _CLAMP_SAFETY_PT)
    _normalize_tables(document)

    page_height = paint.height()
    content_height = document.size().height()
    n_pages = max(1, math.ceil(content_height / page_height))

    ratio = float(dpi) / 72.0
    width = max(1, round(paint.width() * ratio))
    height = max(1, round(page_height * ratio))
    pages: list[QPixmap] = []
    for index in range(n_pages):
        page = QPixmap(width, height)
        page.fill(QColor("white"))
        painter = QPainter(page)
        painter.setClipRect(0, 0, width, height)
        painter.scale(ratio, ratio)
        painter.translate(0.0, -index * page_height)
        document.drawContents(
            painter, QRectF(0.0, 0.0, paint.width(), content_height)
        )
        painter.end()
        pages.append(page)
    return pages


class ReportPreviewPanel(QWidget):
    """报告预览面板（常驻单实例内嵌页·**QWidget 非 QDialog**·守 §三-quarter）。

    顶栏 = 方向 + dpi + 边距（毫米）+ 刷新 + 导出 PDF；正文 = 滚动区纵向堆叠
    逐页 QLabel。html 由宿主经 ``set_html_provider`` 注入（仿图表设计器
    ``set_preview_renderer`` 先例），参数变更信号直连刷新；「导出 PDF」仅发
    ``exportRequested`` 信号，存盘对话框交宿主（面板零 QFileDialog）。
    """

    exportRequested = pyqtSignal()
    exportHtmlRequested = pyqtSignal()
    closeRequested = pyqtSignal()
    aiRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._html_provider: Callable[[], str] | None = None
        self._ai_text = ""

        root = QVBoxLayout(self)

        bar = QHBoxLayout()
        bar.addWidget(QLabel(tr("report.preview_title")))
        self.combo_orientation = QComboBox()
        self.combo_orientation.addItem(
            tr("report.orientation_portrait"), QPageLayout.Orientation.Portrait
        )
        self.combo_orientation.addItem(
            tr("report.orientation_landscape"), QPageLayout.Orientation.Landscape
        )
        bar.addWidget(self.combo_orientation)
        bar.addWidget(QLabel(tr("report.dpi_label")))
        self.combo_dpi = QComboBox()
        for value in _DPI_CHOICES:
            self.combo_dpi.addItem(str(value), value)
        self.combo_dpi.setCurrentIndex(_DPI_DEFAULT_INDEX)
        bar.addWidget(self.combo_dpi)
        bar.addWidget(QLabel(tr("report.margin_label")))
        self.spin_margin = QSpinBox()
        self.spin_margin.setRange(5, 50)
        self.spin_margin.setValue(16)
        self.spin_margin.setSuffix(" mm")
        bar.addWidget(self.spin_margin)
        self.btn_refresh = QPushButton(tr("report.preview_refresh"))
        bar.addWidget(self.btn_refresh)
        self.btn_export = QPushButton(tr("report.preview_export_btn"))
        bar.addWidget(self.btn_export)
        self.btn_export_html = QPushButton(tr("report.preview_export_html_btn"))
        bar.addWidget(self.btn_export_html)
        # T-1104 M-C′·MC-1：AI 解读入口（仅发信号，取数/线程/降级全在宿主）
        self.btn_ai = QPushButton(tr("action.report_ai"))
        bar.addWidget(self.btn_ai)
        self.btn_close = QPushButton(tr("report.preview_close_btn"))
        bar.addWidget(self.btn_close)
        bar.addStretch(1)
        root.addLayout(bar)

        # AI 解读只读展示位（顶栏下方·**非 pages_host 子件**——守 β2 例③⑥页计数）
        # T-1106 MC-2：包进有界滚动区——长文只在内滚动，不再直挂 root 顶高页区
        self.lbl_ai = QLabel(tr("report.ai_placeholder"))
        self.lbl_ai.setWordWrap(True)
        self.lbl_ai.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.lbl_ai.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.ai_scroll = QScrollArea()
        self.ai_scroll.setWidgetResizable(True)
        self.ai_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.ai_scroll.setMaximumHeight(_AI_VIEW_MAX_HEIGHT)
        self.ai_scroll.setWidget(self.lbl_ai)
        root.addWidget(self.ai_scroll)

        self.pages_host = QWidget()
        self.pages_host.setObjectName("reportPreviewPages")
        self.pages_layout = QVBoxLayout(self.pages_host)
        self.pages_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.pages_host)
        root.addWidget(self.scroll, 1)

        # 参数变更 → 直连刷新槽（信号驱动·无 QTimer 去抖·同步渲染）
        self.combo_orientation.currentIndexChanged.connect(self._on_param_changed)
        self.combo_dpi.currentIndexChanged.connect(self._on_param_changed)
        self.spin_margin.valueChanged.connect(self._on_param_changed)
        self.btn_refresh.clicked.connect(self._on_param_changed)
        self.btn_export.clicked.connect(self._on_export_clicked)
        self.btn_export_html.clicked.connect(lambda *_: self.exportHtmlRequested.emit())
        self.btn_ai.clicked.connect(lambda *_: self.aiRequested.emit())
        self.btn_close.clicked.connect(lambda *_: self.closeRequested.emit())

    # ------------------------------------------------------------------
    # 宿主接口
    # ------------------------------------------------------------------

    def set_html_provider(self, provider: Callable[[], str]) -> None:
        """宿主注入 html 产串回调（同源于导出的 build_report_html 产物）。"""
        self._html_provider = provider

    def options(self) -> dict:
        """当前版面参数（供导出侧 ``**`` 透传给 ``render_report_pdf``）。"""
        return {
            "page_size_id": QPageSize.PageSizeId.A4,
            "orientation": self.combo_orientation.currentData(),
            "margin_mm": float(self.spin_margin.value()),
            "dpi": int(self.combo_dpi.currentData()),
        }

    def set_ai_text(self, text: str) -> None:
        """回填 AI 解读全文（T-1104 MC-1）：空则恢复占位文案。

        只存串 + 刷新展示位，不动页图（页区重绘由宿主 refresh 或用户刷新触发，
        provider 侧经 ``ai_text()`` 透传进 ``build_report_html``——预览导出同源）。
        """
        self._ai_text = str(text or "")
        self.lbl_ai.setText(self._ai_text or tr("report.ai_placeholder"))

    def ai_text(self) -> str:
        """当前 AI 解读全文（未生成时为空串·导出/预览透传源）。"""
        return self._ai_text

    def set_ai_busy(self, busy: bool) -> None:
        """跑时置灰 AI 按钮防重点（T-1106 MC-2）：宿主三终态必调 False 恢复。"""
        self.btn_ai.setEnabled(not busy)

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """取 provider html → 同步渲当前参数逐页 → 重建页 QLabel。

        provider 缺席 = 空态直接返回；provider 抛 = 宿主取数失败，页区清空
        不上抛（预览失败不影响主窗，导出侧自有防御）。
        """
        self._clear_pages()
        if self._html_provider is None:
            return
        try:
            html = self._html_provider()
        except Exception:  # noqa: BLE001
            return
        if not html:
            return
        for page in render_html_pages(html, **self.options()):
            label = QLabel(self.pages_host)
            label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            label.setPixmap(self._fit_display_width(page))
            self.pages_layout.addWidget(label, 0, Qt.AlignmentFlag.AlignHCenter)
        self.pages_layout.addStretch(1)

    def _on_param_changed(self, *_args) -> None:
        self.refresh()

    def _on_export_clicked(self, *_args) -> None:
        self.exportRequested.emit()

    @staticmethod
    def _fit_display_width(page: QPixmap) -> QPixmap:
        if page.width() <= _PREVIEW_DISPLAY_MAX_WIDTH:
            return page
        return page.scaledToWidth(
            _PREVIEW_DISPLAY_MAX_WIDTH, Qt.TransformationMode.SmoothTransformation
        )

    def _clear_pages(self) -> None:
        while self.pages_layout.count():
            item = self.pages_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # 先摘父链再 deleteLater：findChildren 计数立即可信（不依赖事件循环）
                widget.setParent(None)
                widget.deleteLater()
