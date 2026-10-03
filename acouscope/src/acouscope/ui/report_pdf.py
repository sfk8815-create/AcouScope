# SPDX-License-Identifier: GPL-3.0-only
"""分析报告 PDF 渲染核（T-1101 · C-2/C-3 里程碑 M-B′-α · L-3 破例）。

职责：把 ``report_export.build_report_html`` 产出的自包含 HTML 字符串渲染为
PDF——仅用 Qt 自带 ``QTextDocument`` + ``QPdfWriter``，零外部依赖、零 pip、
零线程、零对话框、零定时器、零网络。本模块不 import ``report_export``
（输入即 html 字符串），M-A′ 对渲染类的禁引红线不破。

``QTextDocument`` 只支持 CSS 子集（T-1101 审计探针 15 项实测口径）：
``@page`` 与毫米间距对 PDF 路径是死项（浏览器/Word 路径仍需，故不清理）；
表格的 CSS 边框也是死项，由 ``_normalize_tables`` 补偿；超宽图无自动钳制，
由 ``_clamp_report_images`` 防溢出。

白底纪律：PDF 页默认白 + HTML body 白双保险，本模块不引 app 主题色。
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QMarginsF, QUrl
from PyQt6.QtGui import (
    QColor,
    QPageLayout,
    QPageSize,
    QPdfWriter,
    QTextCursor,
    QTextDocument,
    QTextFrameFormat,
    QTextImageFormat,
    QTextTableFormat,
)

# 绘制宽安全边距（pt）：图钳制阈值 = 版心宽 − 此值（T-1101 探针 8 号实证）
_PAINT_SAFETY_PT = 8.0


def _clamp_report_images(doc: QTextDocument, max_width_pt: float) -> int:
    """把宽超过 ``max_width_pt`` 的内嵌图同比缩到阈值内，返回钳制图数。

    以光标逐字符遍历全文（含表格单元格内块）；图资源经
    ``doc.resource(ImageResource, QUrl(fmt.name()))`` 取回（PyQt6 为 QPixmap），
    资源取不到（类型不符 / 空）跳过不抛。块分隔符会继承前一图元的字符
    格式，故按 ``objectIndex`` 去重防双计。
    """
    clamped = 0
    seen = set()
    cursor = QTextCursor(doc)
    total = doc.characterCount()
    position = 0
    while position < total - 1:
        cursor.setPosition(position)
        char_format = cursor.charFormat()
        position += 1
        if not char_format.isImageFormat():
            continue
        if char_format.objectIndex() in seen:
            continue
        seen.add(char_format.objectIndex())
        image_format = char_format.toImageFormat()
        resource = doc.resource(
            QTextDocument.ResourceType.ImageResource, QUrl(image_format.name())
        )
        width = getattr(resource, "width", None)
        height = getattr(resource, "height", None)
        if callable(width) and callable(height) and width() > max_width_pt > 0:
            scale = max_width_pt / width()
            updated = QTextImageFormat(image_format)
            updated.setWidth(width() * scale)
            updated.setHeight(height() * scale)
            cursor.setPosition(position - 1)
            cursor.setPosition(position, QTextCursor.MoveMode.KeepAnchor)
            cursor.mergeCharFormat(updated)
            clamped += 1
    return clamped


def _collect_table_frames(frame):
    """递归收集文档内所有表格帧（含嵌套表）。"""
    tables = []
    for child in frame.childFrames():
        if isinstance(child.format(), QTextTableFormat):
            tables.append(child)
        tables.extend(_collect_table_frames(child))
    return tables


def _normalize_tables(doc: QTextDocument) -> int:
    """给无框表格补灰色实线框 + 单元格留白，返回规范化表数。

    QTextDocument 忽略表格的 CSS 边框（T-1101 探针实测 border 恒 0），
    故对 ``border <= 0`` 的表做排版层补偿；已有边框的表不动。
    """
    normalized = 0
    for frame in _collect_table_frames(doc.rootFrame()):
        table_format = frame.format()
        if not isinstance(table_format, QTextTableFormat):
            continue
        if table_format.border() > 0:
            continue
        table_format.setBorder(1.0)
        table_format.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
        table_format.setBorderBrush(QColor("gray"))
        table_format.setCellPadding(3.0)
        frame.setFormat(table_format)
        normalized += 1
    return normalized


def render_report_pdf(
    html: str,
    target: str | Path,
    *,
    page_size_id: QPageSize.PageSizeId = QPageSize.PageSizeId.A4,
    orientation: QPageLayout.Orientation = QPageLayout.Orientation.Portrait,
    margin_mm: float = 16.0,
    dpi: int = 300,
    title: str = "",
) -> Path:
    """把自包含 HTML 字符串渲染为 PDF 并落盘，返回落盘路径。

    序列（T-1101 探针实证口径）：setHtml → QPdfWriter 页面布局（毫米边距）
    → 超宽图钳制（版心宽 − 安全边距）→ 无框表规范化 → ``doc.print(writer)``
    （PyQt6 方法名即 ``print``，无 ``print_`` 别名）。纯渲染，无网络。
    """
    document = QTextDocument()
    document.setHtml(html)

    writer = QPdfWriter(str(target))
    page_layout = QPageLayout(
        QPageSize(page_size_id),
        orientation,
        QMarginsF(margin_mm, margin_mm, margin_mm, margin_mm),
        QPageLayout.Unit.Millimeter,
    )
    writer.setPageLayout(page_layout)
    writer.setResolution(dpi)
    if title:
        writer.setTitle(title)

    max_width_pt = writer.pageLayout().paintRect(QPageLayout.Unit.Point).width() - _PAINT_SAFETY_PT
    _clamp_report_images(document, max_width_pt)
    _normalize_tables(document)
    document.print(writer)
    return Path(target)
