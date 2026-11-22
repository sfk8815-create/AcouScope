# SPDX-License-Identifier: GPL-3.0-only
"""分析报告 HTML 模型模块（T-1003 立项 · T-1100 回炉 M-A′）。

职责边界（需求说明 T-1100 §〇/§一）：
- 本模块只做**自包含 HTML 报告**的组装与落盘：标题 + 元数据表 / 技术信息 +
  内嵌插图 + 降级说明，产物为单份 `.html`（用户拿去浏览器 / Word / 编辑器可编辑）；
- 图片由 ``ReportFigure.load()`` 载入后转 PNG 字节再 **base64 ``data:`` 内嵌**，
  零外链 / CDN / 本地相对路径，单文件自足、不随主题；
- 图片数据由调用方经**既有渲染管线**（``visualization/FigureExporter`` +
  ``main_window._export_current_view``）产出后以 ``ReportFigure`` 传入，
  本模块不做任何声学分析计算（禁重复分析）。

HTML→PDF 渲染（``QTextDocument``+``QPdfWriter``）与 AI 解读段分属后续里程碑
（M-B′/M-C′），本模块只到「生成并写出可编辑 ``.html``」，不引渲染类。

版式纪律：``@page`` 以 A4 + 毫米页边距定义（打印品口径豁免「禁硬编码尺寸」）；
颜色只取 CSS 关键字中性色（white / black / gray），零十六进制色值、不引 app 主题
变量（打印与导出件恒白底、不随主题变色）。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from html import escape as _esc
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from PyQt6.QtCore import QBuffer, QIODevice
from PyQt6.QtGui import QImage

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
    # M-8a：DA/T 四项自动/预设（报告同源；「Filename」=report 降级技术行既有键，互不影响）
    "FileName": "inspector.meta.file_name",
    "FileSize": "inspector.meta.file_size",
    "AggregationLevel": "inspector.meta.aggregation_level",
    "RetentionPeriod": "inspector.meta.retention_period",
    "Filename": "report.filename",
}

# 内置默认样式表（含 @page A4 + 毫米边距；中性色 white/black/gray·零十六进制色值）
_DEFAULT_CSS = """
@page { size: A4; margin: 16mm; }
body { background: white; color: black; margin: 0; padding: 0; }
h1 { font-size: 15pt; margin: 0 0 4mm; }
h2 { font-size: 10pt; margin: 5mm 0 2mm; }
section { margin: 0 0 6mm; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 0.5pt solid gray; padding: 1.4mm; text-align: left; vertical-align: top; font-size: 8.5pt; }
th.label { width: 40mm; }
figure { margin: 0 0 6mm; }
figcaption { font-size: 8pt; color: gray; margin-top: 1mm; }
img { max-width: 100%; height: auto; }
.degraded { color: gray; }
.rule { border: 0; border-top: 0.5pt solid gray; margin: 2mm 0 4mm; }
""".strip()


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
    """报告默认文件名（<名>_report.html）。"""
    return f"{stem}_report.html"


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


def _image_data_uri(image: QImage) -> str:
    """QImage → PNG 字节 → base64 ``data:`` URI（内嵌·零外链）。空图返回空串。"""
    if image.isNull():
        return ""
    image = image.convertToFormat(QImage.Format.Format_RGB32)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.ReadWrite)
    image.save(buffer, "PNG")
    payload = base64.b64encode(bytes(buffer.data())).decode("ascii")
    buffer.close()
    return "data:image/png;base64," + payload


def _rows_to_table(rows: Sequence[tuple[str, str]]) -> str:
    """[(标签, 值)] → <table> 行 HTML（值缺省走 MISSING·全文本 escape）。"""
    body = "".join(
        "<tr><th class=\"label\">{}</th><td>{}</td></tr>".format(_esc(label), _esc(value))
        for label, value in rows
    )
    return "<table>\n<tbody>\n{}\n</tbody>\n</table>".format(body)


def _figures_to_html(figures: Iterable[ReportFigure]) -> str:
    """每张 ReportFigure → <figure>（<img data:> 内嵌）；空图 → 降级占位文本。"""
    blocks: list[str] = []
    for figure in figures:
        data_uri = _image_data_uri(figure.load())
        caption = _esc(figure.caption or "")
        if not data_uri:
            figure_html = "<p class=\"degraded\">{}</p>".format(_esc(tr("report.figure_missing")))
        else:
            figure_html = "<img src=\"{}\" />".format(data_uri)
        cap_html = "\n<figcaption>{}</figcaption>".format(caption) if caption else ""
        blocks.append("<figure>{}{}</figure>".format(figure_html, cap_html))
    return "\n".join(blocks)


def build_report_html(
    *,
    title: str,
    metadata: Mapping[str, str] | None = None,
    figures: Sequence[ReportFigure] | Iterable[ReportFigure] = (),
    tech_info: Mapping[str, str] | None = None,
    degraded_reason: str = "",
    font_family: str = "",
    ai_text: str = "",
) -> str:
    """组装自包含 HTML 报告字符串（离屏纯函数·无渲染·无网络）。

    Args:
        title: 报告题名（调用方默认传文件名）。
        metadata: 文件级著录元数据（``ProjectFile.metadata``）；空 → 降级。
        figures: 已渲染图列表（顺序即版序），每张 base64 内嵌 ``data:`` URI。
        tech_info: 降级模式技术信息（文件名/时长/采样率）。
        degraded_reason: 降级说明文案（降级节标题下渲染·空则取 i18n 默认）。
        font_family: 正文字族（空 = 浏览器默认；CJK 由调用方传入可用字族）。
        ai_text: AI 解读段全文（T-1104 M-C′·MC-1；空 = 与旧版逐字节等价）。

    样式内置且**恒白底中性色**（不随主题）；零外链。
    """
    style = _DEFAULT_CSS
    if font_family:
        family = _esc(str(font_family), quote=True)
        style = style.replace(
            "body { background: white; color: black; margin: 0; padding: 0; }",
            'body { background: white; color: black; margin: 0; padding: 0; '
            'font-family: "' + family + '", sans-serif; }',
        )

    degraded = is_degraded(metadata) or bool(degraded_reason)
    if degraded:
        reason = _esc(degraded_reason or tr("report.degraded"))
        meta_section = (
            "<section>\n<h2>{}</h2>\n<p class=\"degraded\">{}</p>\n</section>".format(
                _esc(tr("report.tech_info")), reason
            )
        )
        table = _rows_to_table(build_tech_rows(tech_info))
    else:
        meta_section = "<section>\n<h2>{}</h2>\n</section>".format(_esc(tr("report.metadata")))
        table = _rows_to_table(build_metadata_rows(metadata))

    figures_html = _figures_to_html(list(figures))
    heading = _esc(title) if title else _esc(tr("report.untitled"))

    # T-1104 M-C′·MC-1：AI 解读段（纯文本节·不引 class/主题；全文本 _esc 防标签注入）。
    # ai_text 空白 ⇒ ai_section 恒空串 ⇒ 输出与旧版**逐字节等价**（向后兼容判据）。
    ai_section = ""
    if str(ai_text or "").strip():
        paragraphs = "".join(
            "<p>{}</p>\n".format(_esc(line.strip()))
            for line in str(ai_text).splitlines()
            if line.strip()
        )
        ai_section = "<section>\n<h2>{}</h2>\n{}</section>\n".format(
            _esc(tr("report.ai_section_title")), paragraphs
        )

    return (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head>\n"
        "<meta charset=\"utf-8\" />\n"
        "<title>{title}</title>\n"
        "<style>\n{style}\n</style>\n"
        "</head>\n"
        "<body>\n"
        "<h1>{heading}</h1>\n"
        "<hr class=\"rule\" />\n"
        "{meta_section}\n{table}\n"
        "{figures_html}\n"
        "{ai_section}"
        "</body>\n"
        "</html>\n"
    ).format(
        title=heading,
        style=style,
        heading=heading,
        meta_section=meta_section,
        table=table,
        figures_html=figures_html,
        ai_section=ai_section,
    )


def export_report_html(
    target: str | Path,
    *,
    title: str,
    metadata: Mapping[str, str] | None = None,
    figures: Sequence[ReportFigure] | Iterable[ReportFigure] = (),
    tech_info: Mapping[str, str] | None = None,
    degraded_reason: str = "",
    font_family: str = "",
) -> Path:
    """生成自包含 HTML 报告并落盘（父目录自动创建），返回落盘路径。

    参数与 ``build_report_html`` 一致；写文件用 UTF-8（``data:`` 内嵌保证单文件自足）。
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    html = build_report_html(
        title=title,
        metadata=metadata,
        figures=figures,
        tech_info=tech_info,
        degraded_reason=degraded_reason,
        font_family=font_family,
    )
    target.write_text(html, encoding="utf-8")
    return target
