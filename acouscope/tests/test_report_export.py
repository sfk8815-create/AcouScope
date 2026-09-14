# SPDX-License-Identifier: GPL-3.0-only
"""T-1003 分析报告 PDF 拼版测试（纯数据驱动，不构造主窗口、不 show）。

覆盖：
① 拼版纯逻辑：元数据缺字段 "—" 兜底 / 无元数据 → 题名 + 技术信息降级；
② PDF 落盘：文件非空且以 %PDF 头起始（单图 / 多图）；
③ 默认文件名 <stem>_report.pdf；目录不可写 → 复用 _fallback_export_path 降级；
④ 入口 toast 分支（无音频 info / 成功 success / 失败 error）；
⑤ i18n report.* 键三语齐全；
⑥ 静态纪律：禁词 0 / 无 QDialog（QFileDialog 属系统保存框豁免）/ hex·px
   （报告 mm 尺寸豁免，故报告模块与 T-1003 新增块须零 px、零 hex）/ 不 show 主窗。
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
    build_tech_rows,
    default_report_name,
    export_report,
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


def _assert_pdf(path: Path) -> None:
    assert path.exists(), f"{path} 未生成"
    blob = path.read_bytes()
    assert len(blob) > 0, "PDF 为空文件"
    assert blob[:4] == b"%PDF", f"PDF 头校验失败: {blob[:8]!r}"


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
# ① 拼版纯逻辑
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
# ② PDF 落盘
# ---------------------------------------------------------------------------


def test_export_report_writes_pdf(qapp, tmp_path, figure):
    target = export_report(
        tmp_path / "demo_report.pdf",
        title="demo",
        metadata={"Title": "阿诗玛", "Creator": "佚名"},
        figures=[figure, ReportFigure(image=figure.image, caption="fft | 0.000 – 1.000 s")],
        tech_info={"Filename": "demo.wav"},
    )
    _assert_pdf(Path(target))


def test_export_report_degraded_writes_pdf(qapp, tmp_path, figure):
    """无元数据 → 题名 + 技术信息降级仍产出可用 PDF。"""
    target = export_report(
        tmp_path / "degraded.pdf",
        title="demo",
        metadata={},
        figures=[figure],
        tech_info={"Filename": "demo.wav", "Duration": "1.000 s", "SamplingRate": "48000 Hz"},
    )
    _assert_pdf(Path(target))


def test_export_report_without_figures(qapp, tmp_path):
    """零图（仅页眉）也须产出合法 PDF，不抛。"""
    target = export_report(tmp_path / "header_only.pdf", title="demo", metadata={"Title": "t"})
    _assert_pdf(Path(target))


def test_default_report_name():
    assert default_report_name("demo") == "demo_report.pdf"


# ---------------------------------------------------------------------------
# ③ 目录不可写 → 复用既有 _fallback_export_path
# ---------------------------------------------------------------------------


def test_fallback_export_path_relocates(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    blocked = tmp_path / "blocked"
    blocked.write_text("not a dir", encoding="utf-8")  # 父级不能当目录用 → 不可写
    host = _HostStub()

    assert MainWindow._dir_writable(blocked) is False
    resolved = MainWindow._fallback_export_path(host, blocked / "demo_report.pdf")
    assert resolved.name == "demo_report.pdf"
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
    MainWindow._on_report_done(_ToastHost(), tmp_path / "demo_report.pdf", False)
    assert len(toasts) == 1
    message, level = toasts[0]
    assert level == "success"
    assert "demo_report.pdf" in message


def test_done_toast_success_relocated(qapp, monkeypatch, tmp_path):
    """改存路径 → 成功 toast 附「无写入权限」说明。"""
    toasts = _capture_toasts(monkeypatch)
    MainWindow._on_report_done(_ToastHost(), tmp_path / "demo_report.pdf", True)
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
        "report.dialog_title",
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
    """T-1003 新增块（报告导出）单独扫描：零 hex·px、零新建对话框类、不 show。"""
    text = _MAIN_WINDOW.read_text(encoding="utf-8")
    start = text.index("T-1003：分析报告 PDF 导出")
    end = text.index("SOTA 深度分析后端集成", start)
    block = text[start:end]
    assert block.strip(), "未定位到 T-1003 新增块"
    assert _BANNED not in block
    assert _SHOW not in block
    assert not _HEX.search(block), "新增块含硬编码 hex 色值"
    assert "px" not in block, "新增块含 px 单位"
    # QFileDialog（系统保存框）为既有导出同款豁免；其余对话框类禁新增
    assert re.search(r"(?<!File)QDialog", block) is None
