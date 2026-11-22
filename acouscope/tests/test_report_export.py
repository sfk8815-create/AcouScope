# SPDX-License-Identifier: GPL-3.0-only
"""T-1003/T-1100 分析报告 HTML 模型测试（纯数据驱动，不构造主窗口、不 show）。

覆盖：
① 拼表纯逻辑（逐字保留自 T-1003）：元数据缺字段 "—" 兜底 / 无元数据 → 降级；
② HTML 落盘：自包含单文件（DOCTYPE / 图 base64 内嵌 / 零外链 / 白底中性色）；
③ 默认文件名 <stem>_report.html；目录不可写 → 复用 _fallback_export_path 降级；
④ 入口 toast 分支（无音频 info / 成功 success / 失败 error）；
⑤ i18n report.* 键三语齐全；
⑥ 静态纪律：禁词 0 / 无 QDialog（QFileDialog 属系统保存框豁免）/ hex·px
   （报告 mm 尺寸豁免，故报告模块与新增块须零 px、零 hex）/ 不 show 主窗；
⑦ 判据③ 同源三态：同一 figures 喂 build_report_html（含图/无图/降级）各节相应。
"""

from __future__ import annotations

import re
import types
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QLabel, QWidget

from acouscope.annotation.metadata import FIELD_TERMS
from acouscope.i18n import tr
from acouscope.ui.main_window import MainWindow
from acouscope.ui.report_export import (
    MISSING,
    ReportFigure,
    build_metadata_rows,
    build_report_html,
    build_tech_rows,
    default_report_name,
    export_report_html,
    is_degraded,
)

_SRC = Path(__file__).resolve().parents[1] / "src" / "acouscope"
_MODULE = _SRC / "ui" / "report_export.py"
_MAIN_WINDOW = _SRC / "ui" / "main_window.py"

# 禁词以拼接构造，避免本文件自身被扫中（同 test_icon_styles.py 口径）
_BANNED = "Mel" + "odyne"
_SHOW = "." + "show()"
_QDIALOG_PLAIN = "Q" + "Dialog"  # 非 QFileDialog（系统保存框豁免）
_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


# ---------------------------------------------------------------------------
# 夹具 / 工具
# ---------------------------------------------------------------------------


@pytest.fixture
def figure(tmp_path: Path) -> ReportFigure:
    """已渲染插图（QImage → PNG，等价于既有 FigureExporter 产物）。"""
    image = QImage(320, 200, QImage.Format.Format_RGB32)
    image.fill(QColor(Qt.GlobalColor.white))
    path = tmp_path / "waveform.png"
    assert image.save(str(path)) is True
    return ReportFigure(image=path, caption="waveform | 0.000 – 1.000 s")


def _assert_html(text: str, *, with_figure: bool = True) -> None:
    """自包含 HTML 硬校：DOCTYPE 头 + 白底中性色 + 零外链（http/file:）+ 图内嵌。"""
    assert text.startswith("<!DOCTYPE html>"), "缺 DOCTYPE 头"
    assert "background: white" in text, "样式未恒白底"
    assert "color: black" in text, "正文色须为中性黑（不随主题）"
    lowered = text.lower()
    assert "http://" not in lowered, "HTML 含 http 外链"
    assert "https://" not in lowered, "HTML 含 https 外链"
    assert "file:" not in lowered, "HTML 含 file: 本地外链"
    if with_figure:
        assert "data:image/png;base64," in text, "插图未 base64 内嵌"


def _read_html(path: Path, *, with_figure: bool = True) -> str:
    assert path.exists(), f"{path} 未生成"
    assert path.suffix == ".html"
    text = path.read_text(encoding="utf-8")
    assert len(text) > 0, "HTML 为空文件"
    _assert_html(text, with_figure=with_figure)
    return text


class _HostStub:
    """只承载 main_window 路径 helper 的宿主（不构造 MainWindow）。"""

    _dir_writable = staticmethod(MainWindow._dir_writable)
    _fallback_export_path = MainWindow._fallback_export_path

    def __init__(self) -> None:
        self.controller = types.SimpleNamespace(current_file=None)


class _ToastHost(QWidget):
    """最小宿主：仅 lbl_status + QWidget 身份（toast 打桩后不依赖真实窗口）。"""

    def __init__(self) -> None:
        super().__init__()
        self.lbl_status = QLabel("", self)


def _capture_toasts(monkeypatch) -> list:
    import acouscope.ui.main_window as mw_mod

    toasts: list[tuple[str, str]] = []
    monkeypatch.setattr(
        mw_mod,
        "show_toast",
        lambda parent, msg, level="info": toasts.append((msg, level)),
    )
    return toasts


# ---------------------------------------------------------------------------
# ① 拼表纯逻辑（保留自 T-1003·逐字不动）
# ---------------------------------------------------------------------------


def test_metadata_rows_missing_fields_use_placeholder():
    """缺字段一律 "—"，禁臆造默认值；字段序 = FIELD_TERMS 权威序。"""
    rows = build_metadata_rows({})
    assert [len(rows)] == [len(FIELD_TERMS)]
    assert all(value == MISSING for _label, value in rows)
    assert all(label for label, _value in rows)

    rows = build_metadata_rows({"Title": "阿诗玛", "Custom": "自定"})
    mapping = dict(rows)
    assert mapping[tr("inspector.meta.title")] == "阿诗玛"
    assert mapping[tr("inspector.meta.creator")] == MISSING
    assert mapping["Custom"] == "自定"


def test_metadata_rows_skip_control_key():
    """控制键（"_standard"）不入表，避免内部字段泄漏到报告。"""
    labels = [label for label, _v in build_metadata_rows({"_standard": "DAT63"})]
    assert "_standard" not in labels


def test_metadata_rows_m8a_autofour_localized():
    """M-8a 四键走 i18n 标签（裸键不外泄）；传值原样出现，未传落 MISSING。"""
    given = {
        "FileName": "field_take.wav", "FileSize": "15360",
        "AggregationLevel": "件", "RetentionPeriod": "永久",
    }
    labels = [label for label, _v in build_metadata_rows(given)]
    for bare in ("FileName", "FileSize", "AggregationLevel", "RetentionPeriod"):
        assert bare not in labels  # 本地化标签，非英文裸键
    mapping = dict(build_metadata_rows(given))
    assert mapping[tr("inspector.meta.file_name")] == "field_take.wav"
    assert mapping[tr("inspector.meta.file_size")] == "15360"
    assert mapping[tr("inspector.meta.aggregation_level")] == "件"
    assert mapping[tr("inspector.meta.retention_period")] == "永久"
    absent = dict(build_metadata_rows({}))
    assert absent[tr("inspector.meta.file_name")] == MISSING
    assert absent[tr("inspector.meta.retention_period")] == MISSING


def test_is_degraded_semantics():
    assert is_degraded({}) is True
    assert is_degraded(None) is True
    assert is_degraded({"_standard": "DAT63"}) is True  # 仅控制键 = 无著录字段
    assert is_degraded({"Title": "  "}) is True
    assert is_degraded({"Title": "阿诗玛"}) is False


def test_tech_rows_drop_empty_values():
    rows = build_tech_rows({"Filename": "a.wav", "Duration": "", "SamplingRate": None})
    assert rows == [(tr("report.filename"), "a.wav")]


# ---------------------------------------------------------------------------
# ② HTML 落盘
# ---------------------------------------------------------------------------


def test_export_report_html_writes_file(qapp, tmp_path, figure):
    target = export_report_html(
        tmp_path / "demo_report.html",
        title="demo",
        metadata={"Title": "阿诗玛", "Creator": "佚名"},
        figures=[figure, ReportFigure(image=figure.image, caption="fft | 0.000 – 1.000 s")],
        tech_info={"Filename": "demo.wav"},
    )
    text = _read_html(Path(target))
    assert text.count("<img") == 2, "两图须各自内嵌"
    assert tr("report.metadata") in text


def test_export_report_html_degraded_writes_file(qapp, tmp_path, figure):
    """无元数据 → 题名 + 降级说明 + 技术信息表仍产出可用 HTML。"""
    target = export_report_html(
        tmp_path / "degraded.html",
        title="demo",
        metadata={},
        figures=[figure],
        tech_info={"Filename": "demo.wav", "Duration": "1.000 s", "SamplingRate": "48000 Hz"},
    )
    text = _read_html(Path(target))
    assert tr("report.degraded") in text, "降级说明节缺失"
    assert tr("report.tech_info") in text
    assert tr("report.filename") in text


def test_export_report_html_without_figures(qapp, tmp_path):
    """零图（仅头部 + 元数据表）也须产出合法 HTML，不抛。"""
    target = export_report_html(
        tmp_path / "header_only.html", title="demo", metadata={"Title": "t"}
    )
    text = _read_html(Path(target), with_figure=False)
    assert "<img" not in text


def test_default_report_name():
    assert default_report_name("demo") == "demo_report.html"


# ---------------------------------------------------------------------------
# ②-b 判据③：同源 figures 三态（含图 / 无图仅头 / 降级说明节）
# ---------------------------------------------------------------------------


def test_build_report_html_three_states_same_figures(figure):
    """同一 figures 喂三态 → HTML 分别含 <img> / 无图仅头 / 降级说明节。"""
    with_figures = build_report_html(
        title="demo", metadata={"Title": "阿诗玛"}, figures=[figure]
    )
    _assert_html(with_figures)
    assert tr("report.metadata") in with_figures
    assert tr("report.degraded") not in with_figures, "非降级态不得渲染降级说明"

    header_only = build_report_html(
        title="demo", metadata={"Title": "阿诗玛"}, figures=()
    )
    _assert_html(header_only, with_figure=False)
    assert "<img" not in header_only

    degraded = build_report_html(
        title="demo",
        metadata={},
        figures=[figure],
        tech_info={"Filename": "demo.wav"},
    )
    _assert_html(degraded)
    assert tr("report.degraded") in degraded
    assert tr("report.tech_info") in degraded
    assert "<h2>" + tr("report.metadata") + "</h2>" not in degraded, "降级态以技术信息表替代元数据表"


def test_build_report_html_custom_degraded_reason_and_font(figure):
    """degraded_reason 非空 → 渲染自定文案；font_family 非空 → 入 CSS 字族。"""
    text = build_report_html(
        title="demo",
        metadata={"Title": "阿诗玛"},
        figures=[figure],
        degraded_reason="著录字段暂缺（自定说明）",
        font_family="Noto Sans CJK SC",
    )
    assert "著录字段暂缺（自定说明）" in text
    assert "Noto Sans CJK SC" in text


def test_build_report_html_escapes_text():
    """元数据/题名为任意文本时须 escape，防标签注入破坏自包含性。"""
    text = build_report_html(
        title="<script>alert(1)</script>",
        metadata={"Title": "a<b>c"},
        figures=(),
    )
    assert "<script>" not in text
    assert "&lt;script&gt;" in text
    assert "a&lt;b&gt;c" in text


# ---------------------------------------------------------------------------
# ③ 目录不可写 → 复用既有 _fallback_export_path
# ---------------------------------------------------------------------------


def test_fallback_export_path_relocates(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    blocked = tmp_path / "blocked"
    blocked.write_text("not a dir", encoding="utf-8")  # 父级不能当目录用 → 不可写
    host = _HostStub()

    assert MainWindow._dir_writable(blocked) is False
    resolved = MainWindow._fallback_export_path(host, blocked / "demo_report.html")
    assert resolved.name == "demo_report.html"
    assert resolved.parent != blocked
    assert resolved.parent == tmp_path / "Documents" / "AcouScope导出"


# ---------------------------------------------------------------------------
# ④ 入口 toast 分支
# ---------------------------------------------------------------------------


def test_entry_no_audio_toast_info(monkeypatch):
    toasts = _capture_toasts(monkeypatch)
    host = types.SimpleNamespace(
        controller=types.SimpleNamespace(has_audio=lambda: False)
    )
    MainWindow._on_export_report(host)
    assert toasts == [(tr("msg.no_audio"), "info")]


def test_done_toast_success(qapp, monkeypatch, tmp_path):
    toasts = _capture_toasts(monkeypatch)
    MainWindow._on_report_done(_ToastHost(), tmp_path / "demo_report.html", False)
    assert len(toasts) == 1
    message, level = toasts[0]
    assert level == "success"
    assert "demo_report.html" in message


def test_done_toast_success_relocated(qapp, monkeypatch, tmp_path):
    """改存路径 → 成功 toast 附「无写入权限」说明。"""
    toasts = _capture_toasts(monkeypatch)
    MainWindow._on_report_done(_ToastHost(), tmp_path / "demo_report.html", True)
    assert len(toasts) == 1
    assert tr("report.relocated") in toasts[0][0]


def test_failed_toast_error(qapp, monkeypatch):
    toasts = _capture_toasts(monkeypatch)
    MainWindow._on_report_failed(_ToastHost(), "boom")
    assert len(toasts) == 1
    message, level = toasts[0]
    assert level == "error"
    assert "boom" in message


# ---------------------------------------------------------------------------
# ⑤ i18n 三语齐全
# ---------------------------------------------------------------------------


def test_report_i18n_keys_three_languages():
    from acouscope.i18n import _STRINGS

    for key in (
        "action.export_report",
        "report.dialog_title",
        "report.filter_html",
        "report.exporting",
        "report.exported",
        "report.failed",
        "report.relocated",
        "report.metadata",
        "report.tech_info",
        "report.filename",
        "report.degraded",
        "report.untitled",
        "report.figure_missing",
        "report.caption_range",
    ):
        entry = _STRINGS[key]
        assert set(entry) == {"en_US", "zh_CN", "zh_TW"}, f"{key} 语言不全"
        assert all(entry.values()), f"{key} 存在空文案"


def test_export_report_labels_format_neutral():
    """T-1100 回炉：菜单/存盘文案格式中性（不再钉 PDF 字样）."""
    from acouscope.i18n import _STRINGS

    for key in ("action.export_report", "report.dialog_title"):
        for lang, text in _STRINGS[key].items():
            assert "PDF" not in text, f"{key}[{lang}] 仍钉 PDF 字样"


# ---------------------------------------------------------------------------
# ⑥ 静态纪律
# ---------------------------------------------------------------------------


def test_static_discipline_report_module():
    """报告模块：禁词 0 / 零 QDialog / 零 hex·px（mm 尺寸豁免不含 px 字面量）。"""
    text = _MODULE.read_text(encoding="utf-8")
    assert _BANNED not in text
    assert _SHOW not in text
    assert _QDIALOG_PLAIN not in text
    assert not _HEX.search(text), "报告模块含硬编码 hex 色值"
    assert "px" not in text, "报告模块含 px 单位（mm 豁免不等于可用 px）"


def test_static_discipline_main_window_report_block():
    """报告导出块单独扫描：零 hex·px、零新建对话框类、不 show。"""
    text = _MAIN_WINDOW.read_text(encoding="utf-8")
    start = text.index("T-1003/T-1100：分析报告 HTML 导出")
    end = text.index("SOTA 深度分析后端集成", start)
    block = text[start:end]
    assert block.strip(), "未定位到报告导出新增块"
    assert _BANNED not in block
    assert _SHOW not in block
    assert not _HEX.search(block), "新增块含硬编码 hex 色值"
    assert "px" not in block, "新增块含 px 单位"
    # QFileDialog（系统保存框）为既有导出同款豁免；其余对话框类禁新增
    assert re.search(r"(?<!File)QDialog", block) is None
