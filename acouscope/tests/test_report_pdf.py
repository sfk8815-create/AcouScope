# SPDX-License-Identifier: GPL-3.0-only
"""T-1101 报告 PDF 渲染核测试（M-B′-α · 全离屏 · 不触 main_window · 不调 apply_theme）。

覆盖：
① 渲染落盘合法（``%PDF-1.4`` 头）；② PDF Title 元数据；③ ReportFigure 经
同源 HTML 内嵌为 PDF 图像对象；④ A4 页面 MediaBox；⑤ 12 张大图分页
（★ 探针实证 ``doc.pageCount()`` 在 print 后不可靠，禁用其作判据，
改字节级 ``/Type /Page`` 计数）；⑥ 超宽图钳制直测；⑦ 无框表规范化直测；
⑧ 降级三态 HTML 仍可渲出合法 PDF。
"""

from __future__ import annotations

import base64
import re

import pytest
from PyQt6.QtCore import Qt, QBuffer, QIODevice
from PyQt6.QtGui import QColor, QImage, QTextCursor, QTextDocument, QTextFrameFormat

from acouscope.ui.report_export import ReportFigure, build_report_html
from acouscope.ui.report_pdf import (
    _clamp_report_images,
    _normalize_tables,
    render_report_pdf,
)

_PLAIN_HTML = "<html><body><p>hello t-1101</p></body></html>"


def _solid_image(width: int, height: int) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(Qt.GlobalColor.white))
    return image


def _image_data_uri(image: QImage) -> str:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.ReadWrite)
    image.save(buffer, "PNG")
    payload = base64.b64encode(bytes(buffer.data())).decode("ascii")
    buffer.close()
    return "data:image/png;base64," + payload


def _figures_html(count: int, *, size=(200, 120)) -> str:
    # 逐张变高度：字节全同的图会被 Qt PDF 写手归并为同一图像对象
    figures = [
        ReportFigure(
            image=_solid_image(size[0], size[1] + index), caption=f"fig {index}"
        )
        for index in range(count)
    ]
    return build_report_html(
        title="demo", metadata={"Title": "阿诗玛"}, figures=figures
    )


def _first_image_format(doc: QTextDocument):
    cursor = QTextCursor(doc)
    while not cursor.atEnd():
        char_format = cursor.charFormat()
        if char_format.isImageFormat():
            return char_format.toImageFormat()
        cursor.movePosition(QTextCursor.MoveOperation.NextCharacter)
    return None


# ---------------------------------------------------------------------------
# ① 合法 PDF
# ---------------------------------------------------------------------------


def test_render_writes_valid_pdf(qapp, tmp_path):
    target = render_report_pdf(_PLAIN_HTML, tmp_path / "demo.pdf")
    assert target.exists()
    data = target.read_bytes()
    assert len(data) > 0, "PDF 为空文件"
    assert data.startswith(b"%PDF-1.4"), "缺 %PDF-1.4 头"


# ---------------------------------------------------------------------------
# ② Title 元数据
# ---------------------------------------------------------------------------


def test_pdf_title_metadata(qapp, tmp_path):
    target = render_report_pdf(
        _PLAIN_HTML, tmp_path / "title.pdf", title="t-1101-probe"
    )
    assert b"/Title" in target.read_bytes()


# ---------------------------------------------------------------------------
# ③ 内嵌插图 → PDF 图像对象
# ---------------------------------------------------------------------------


def test_pdf_embeds_figure_images(qapp, tmp_path):
    target = render_report_pdf(_figures_html(2), tmp_path / "figures.pdf")
    data = target.read_bytes()
    assert len(re.findall(rb"/Subtype\s*/Image", data)) >= 2, "两图未各自嵌入 PDF"


# ---------------------------------------------------------------------------
# ④ A4 页面版式
# ---------------------------------------------------------------------------


def test_a4_page_layout(qapp, tmp_path):
    target = render_report_pdf(_PLAIN_HTML, tmp_path / "a4.pdf")
    match = re.search(rb"/MediaBox\s*\[[^\]]*\]", target.read_bytes())
    assert match is not None, "PDF 内未见 MediaBox"
    assert b"595" in match.group(0), "A4 纵向页宽应为 595pt 级"


# ---------------------------------------------------------------------------
# ⑤ 大图分页（禁用 doc.pageCount 作判据·字节级计数）
# ---------------------------------------------------------------------------


def test_pagination_multi_page(qapp, tmp_path):
    target = render_report_pdf(
        _figures_html(12, size=(600, 450)), tmp_path / "pages.pdf"
    )
    pages = re.findall(rb"/Type\s*/Page(?!s)", target.read_bytes())
    assert len(pages) >= 2, f"12 张大图应多页，实得 {len(pages)}"


# ---------------------------------------------------------------------------
# ⑥ 超宽图钳制（直测 helper）
# ---------------------------------------------------------------------------


def test_clamps_oversize_image(qapp):
    doc = QTextDocument()
    doc.setHtml('<img src="{}" />'.format(_image_data_uri(_solid_image(3000, 80))))
    assert _clamp_report_images(doc, 100.0) == 1
    image_format = _first_image_format(doc)
    assert image_format is not None
    assert image_format.width() <= 100.0, "钳制后图元宽度仍超阈值"
    assert image_format.height() < 80.0, "高度须同比缩小"


# ---------------------------------------------------------------------------
# ⑦ 无框表规范化（直测 helper）
# ---------------------------------------------------------------------------


def test_normalize_table_borders(qapp):
    doc = QTextDocument()
    doc.setHtml("<table><tr><td>abc</td></tr></table>")
    assert _normalize_tables(doc) == 1
    frames = doc.rootFrame().childFrames()
    assert len(frames) == 1
    table_format = frames[0].format()
    assert table_format.border() > 0, "边框未被规范化"
    assert table_format.borderStyle() == QTextFrameFormat.BorderStyle.BorderStyle_Solid


# ---------------------------------------------------------------------------
# ⑧ 降级三态 HTML 可渲
# ---------------------------------------------------------------------------


def test_degraded_html_renders(qapp, tmp_path):
    html = build_report_html(
        title="demo",
        metadata={},
        tech_info={"Filename": "demo.wav", "Duration": "1.000 s", "SamplingRate": "48000 Hz"},
        degraded_reason="著录字段暂缺（自定说明）",
    )
    target = render_report_pdf(html, tmp_path / "degraded.pdf")
    data = target.read_bytes()
    assert data.startswith(b"%PDF"), "降级态未渲出合法 PDF"
    assert len(data) > 0
