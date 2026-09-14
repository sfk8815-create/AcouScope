# SPDX-License-Identifier: GPL-3.0-only
"""分析报告 PDF 拼版模块（T-1003）。

职责边界（任务书 T-1003 §1）：
- 本模块只做 A4 版式拼装与 PDF 落盘（QPdfWriter + QPainter，免附加依赖）；
- 图片数据由调用方经**既有渲染管线**（``visualization/FigureExporter`` +
  ``main_window._export_current_view``）产出后以 ``ReportFigure`` 传入，
  本模块不做任何声学分析计算（禁重复分析）。

排版尺寸纪律豁免（任务书 T-1003 §1 明文）：报告是 A4 打印品，纸张/页边距/
行高等口径本身以业界标准计量单位（毫米）定义，故本文件中的 ``_*_MM`` 毫米
字面值豁免项目「禁硬编码色值 / 像素单位」纪律。颜色只取 ``Qt.GlobalColor``
灰度与黑，零十六进制色值字面量（打印件不随主题变色）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from PyQt6.QtCore import QMarginsF, QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPen,
    QPdfWriter,
)

from acouscope.annotation.metadata import FIELD_TERMS
from acouscope.i18n import tr

# 字段缺失占位符（与 inspector_panel._PH_VIEW 同字符，禁臆造默认值）
MISSING = "—"

# 字段键 → 既有 inspector 行标签 i18n key（同源，避免第二份字段名）
_LABEL_KEYS: dict[str, str] = {
    "Identifier": "inspector.meta.identifier",
    "Title": "inspector.meta.title",
    "Creator": "inspector.meta.creator",
    "Date": "inspector.meta.date",
    "Location": "inspector.meta.location",
    "GenreContext": "inspector.meta.genre_context",
    "ActorRole": "inspector.meta.actor_role",
    "SamplingRate": "inspector.meta.sampling_rate",
    "BitDepth": "inspector.meta.bit_depth",
    "Format": "inspector.meta.format",
    "Channels": "inspector.meta.channels",
    "Duration": "inspector.meta.duration",
    "Filename": "report.filename",
}

# ── 版式常量（毫米；豁免理由见模块 docstring）─────────────────────────
_MARGIN_MM = 16.0
_LABEL_COL_MM = 40.0
_ROW_PAD_MM = 1.4
_GAP_MM = 4.0
_FIG_GAP_MM = 6.0
_FIG_MIN_MM = 40.0

# 字号（pt）
_TITLE_PT = 15.0
_SECTION_PT = 10.0
_BODY_PT = 8.5
_CAPTION_PT = 8.0

# 文本绘制标志：左对齐 + 顶部对齐 + 自动换行
# （TextFlag 与 AlignmentFlag 属不同枚举，PyQt6 下须先各自转 int 再按位或）
_WRAP_FLAGS = (
    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    | int(Qt.TextFlag.TextWordWrap)
)


@dataclass(frozen=True)
class ReportFigure:
    """报告插图：``image`` 为 PNG 路径 / 原图字节 / 已就绪的 QImage；``caption`` 为图题。"""

    image: object
    caption: str = ""

    def load(self) -> QImage:
        """载入为 QImage；失败返回空 QImage（调用方按「图缺失」占位处理，不抛）。"""
        image = self.image
        if isinstance(image, QImage):
            return image
        if isinstance(image, (bytes, bytearray)):
            qimage = QImage()
            qimage.loadFromData(bytes(image))
            return qimage
        return QImage(str(image))


def default_report_name(stem: str) -> str:
    """报告默认文件名（<名>_report.pdf）。"""
    return f"{stem}_report.pdf"


def is_degraded(metadata: Mapping[str, str] | None) -> bool:
    """无任何有效著录字段（控制键 "_" 前缀不计）→ 降级模式。"""
    for key, value in dict(metadata or {}).items():
        if str(key).startswith("_"):
            continue
        if str(value or "").strip():
            return False
    return True


def build_metadata_rows(metadata: Mapping[str, str] | None) -> list[tuple[str, str]]:
    """元数据 → 字段表行 [(标签, 值)]。

    顺序 = ``FIELD_TERMS`` 权威字段序（缺失 → ``MISSING``，禁臆造默认值）；
    其后的自定义字段原样附加，控制键（"_standard" 等）不入表。
    """
    fields = {str(k): ("" if v is None else str(v)) for k, v in dict(metadata or {}).items()}
    rows: list[tuple[str, str]] = []
    for term in FIELD_TERMS:
        value = fields.pop(term.key, "").strip()
        rows.append((tr(_LABEL_KEYS.get(term.key, term.key)), value or MISSING))
    for key, value in fields.items():
        if key.startswith("_"):
            continue
        rows.append((tr(_LABEL_KEYS.get(key, key)), value.strip() or MISSING))
    return rows


def build_tech_rows(tech_info: Mapping[str, str] | None) -> list[tuple[str, str]]:
    """降级模式技术信息 → 字段表行（键序 = 传入序；空值行丢弃）。"""
    rows: list[tuple[str, str]] = []
    for key, value in dict(tech_info or {}).items():
        text = str(value or "").strip()
        if not text:
            continue
        rows.append((tr(_LABEL_KEYS.get(key, key)), text))
    return rows


def export_report(
    target: str | Path,
    *,
    title: str,
    metadata: Mapping[str, str] | None = None,
    figures: Sequence[ReportFigure] | Iterable[ReportFigure] = (),
    tech_info: Mapping[str, str] | None = None,
    degraded_reason: str = "",
    font_family: str = "",
    resolution: int = 300,
    dpr: float = 1.0,
) -> Path:
    """拼版并写出报告 PDF，返回落盘路径。

    Args:
        target: 输出 PDF 路径（父目录自动创建）。
        title: 报告题名（调用方默认传文件名）。
        metadata: 文件级著录元数据（``ProjectFile.metadata``）；空 → 降级。
        figures: 已渲染图列表（顺序即版序）。
        tech_info: 降级模式技术信息（文件名/时长/采样率）。
        degraded_reason: 降级说明文案（空则取 i18n 默认）。
        font_family: 正文字族（空 = 系统默认；CJK 由调用方传入可用字族）。
        resolution: 基准 DPI（默认 300，与 FigureExporter 一致）。
        dpr: 显示缩放因子（参照 theme._render_svg_bytes 的 dpr 模式，
             按比例提升 PDF 光栅解析度，保证高 dpr 屏下插图不糊）。
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    writer = QPdfWriter(str(target))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    # 页边距置 0：留白由本模块按 _MARGIN_MM 自绘（跨平台/跨 Qt 行为一致）
    writer.setPageMargins(QMarginsF(0.0, 0.0, 0.0, 0.0), QPageLayout.Unit.Millimeter)
    writer.setResolution(int(round(max(72.0, float(resolution) * max(0.5, float(dpr))))))

    painter = QPainter(writer)
    try:
        _compose(
            painter,
            writer,
            title=title,
            metadata=metadata,
            figures=list(figures),
            tech_info=tech_info,
            degraded_reason=degraded_reason,
            font_family=font_family,
        )
    finally:
        painter.end()
    return target


def _measure(font: QFont, text: str, width: float, device) -> float:
    """按目标绘制设备度量换行文本高度（设备度量保证与 QPdfWriter 分辨率一致）。"""
    metrics = QFontMetricsF(font, device)
    rect = metrics.boundingRect(QRectF(0.0, 0.0, width, 1e6), _WRAP_FLAGS, text)
    return float(rect.height()) + 1.0


def _compose(
    painter: QPainter,
    writer: QPdfWriter,
    *,
    title: str,
    metadata: Mapping[str, str] | None,
    figures: list[ReportFigure],
    tech_info: Mapping[str, str] | None,
    degraded_reason: str,
    font_family: str,
) -> None:
    """A4 纵向自上而下流式拼版（满页自动翻页）。"""
    units = float(writer.resolution()) / 25.4  # 1 mm = units 设备像素
    page_w = float(writer.width())
    page_h = float(writer.height())
    left = _MARGIN_MM * units
    right = page_w - _MARGIN_MM * units
    top = _MARGIN_MM * units
    bottom = page_h - _MARGIN_MM * units
    content_w = right - left

    base = QFont(font_family) if font_family else QFont()
    state = {"y": top}

    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    def new_page() -> None:
        writer.newPage()
        state["y"] = top

    def ensure(height: float) -> None:
        if state["y"] + height > bottom:
            new_page()

    def draw_text(
        text: str,
        *,
        size: float,
        bold: bool = False,
        gap_mm: float = _GAP_MM,
        indent_mm: float = 0.0,
    ) -> None:
        font = QFont(base)
        font.setPointSizeF(size)
        font.setBold(bold)
        painter.setFont(font)
        x = left + indent_mm * units
        height = _measure(font, text, content_w, writer)
        ensure(height)
        painter.setPen(QColor(Qt.GlobalColor.black))
        painter.drawText(QRectF(x, state["y"], content_w, height), _WRAP_FLAGS, text)
        state["y"] += height + gap_mm * units

    def draw_rule() -> None:
        ensure(1.0)
        pen = QPen(QColor(Qt.GlobalColor.gray), max(1.0, 0.35 * units))
        painter.setPen(pen)
        painter.drawLine(QPointF(left, state["y"]), QPointF(right, state["y"]))
        state["y"] += _GAP_MM * units

    def draw_rows(rows: list[tuple[str, str]]) -> None:
        label_w = min(_LABEL_COL_MM * units, content_w * 0.42)
        value_w = content_w - label_w
        font = QFont(base)
        font.setPointSizeF(_BODY_PT)
        for label, value in rows:
            height = max(
                _measure(font, label, label_w, writer),
                _measure(font, value, value_w, writer),
            ) + 2 * _ROW_PAD_MM * units
            ensure(height)
            painter.setFont(font)
            painter.setPen(QColor(Qt.GlobalColor.black))
            painter.drawText(
                QRectF(left, state["y"] + _ROW_PAD_MM * units, label_w, height),
                _WRAP_FLAGS,
                label,
            )
            painter.drawText(
                QRectF(left + label_w, state["y"] + _ROW_PAD_MM * units, value_w, height),
                _WRAP_FLAGS,
                value,
            )
            state["y"] += height

    # ── 页眉：题名 + 著录元数据表（无元数据 → 技术信息降级 + 注明）──────
    draw_text(title or tr("report.untitled"), size=_TITLE_PT, bold=True)
    draw_rule()

    if is_degraded(metadata):
        draw_text(degraded_reason or tr("report.degraded"), size=_BODY_PT)
        draw_text(tr("report.tech_info"), size=_SECTION_PT, bold=True, gap_mm=2.0)
        draw_rows(build_tech_rows(tech_info))
    else:
        draw_text(tr("report.metadata"), size=_SECTION_PT, bold=True, gap_mm=2.0)
        draw_rows(build_metadata_rows(metadata))
    state["y"] += _GAP_MM * units

    # ── 插图：按内容宽等比缩放，图题紧随其下 ────────────────────────
    for figure in figures:
        image = figure.load()
        caption = figure.caption or ""
        caption_font = QFont(base)
        caption_font.setPointSizeF(_CAPTION_PT)
        caption_h = _measure(caption_font, caption, content_w, writer) if caption else 0.0

        ensure(caption_h + _FIG_MIN_MM * units)
        if image.isNull():
            draw_text(tr("report.figure_missing"), size=_BODY_PT, gap_mm=2.0)
        else:
            image = image.convertToFormat(QImage.Format.Format_RGB32)
            available = bottom - state["y"] - caption_h - _GAP_MM * units
            scale = min(content_w / image.width(), available / image.height())
            width = image.width() * scale
            height = image.height() * scale
            painter.drawImage(QRectF(left, state["y"], width, height), image)
            state["y"] += height + _GAP_MM * units

        if caption:
            draw_text(caption, size=_CAPTION_PT, gap_mm=_FIG_GAP_MM)
