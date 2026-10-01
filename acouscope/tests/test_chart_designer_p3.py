# SPDX-License-Identifier: GPL-3.0-only
"""T-1046 图表设计器 P3（主题预设三层 + 样式 JSON 导入/导出 + 报告 PDF 参数贯通）。

覆盖任务书 §二 三件 + §三 硬判据：
  件1 三层存取：会话（settings=None 兜底不报错）/ 项目（Project.presets 往返）/
       全局（Settings.chart_style_presets 落盘往返）；重名覆盖两击确认（禁静默覆盖）；
       删除两击确认 + 不残留。
  件2 样式 JSON：往返等值；坏 JSON / 缺 format / 错 version / 未知键 —— 各有用例
       （外来格式显式拒绝 ValueError；未知键忽略并告警）。
  件3 报告同源：title 非空 + mode==3 下，报告侧自建 exporter（不带参数）经
       `_export_current_view` 覆写后，与直接导出 exporter 在内容外壳/参考线上一致；
       ref_ink 走 exporter.ink["ref_line"]（构造期已固化）。
反例自证：① 导入拒绝外来格式（故意破坏 → FAIL → 恢复 → PASS）
          ② 项目级预设往返（save→reload 等值）。

夹具参照 tests/test_chart_designer.py（qapp + window 不 show）。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from acouscope.app.project import ProjectManager  # noqa: E402
from acouscope.i18n import _STRINGS  # noqa: E402
from acouscope.ui.main_window import MainWindow  # noqa: E402
from acouscope.ui.widgets.chart_designer import (  # noqa: E402
    STYLE_FORMAT,
    STYLE_VERSION,
    ChartDesignerPanel,
)
from acouscope.utils.config import Settings  # noqa: E402
from acouscope.visualization.exporters import FigureExporter  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src" / "acouscope"
_DESIGNER = _SRC / "ui" / "widgets" / "chart_designer.py"

_P3_NEW_KEYS = (
    "chart_designer.preset.name", "chart_designer.preset.name_hint",
    "chart_designer.preset.save", "chart_designer.preset.overwrite",
    "chart_designer.preset.load", "chart_designer.preset.delete",
    "chart_designer.preset.delete_confirm", "chart_designer.preset.import",
    "chart_designer.preset.export", "chart_designer.preset.name_required",
    "chart_designer.preset.saved", "chart_designer.preset.deleted",
    "chart_designer.preset.import_ok", "chart_designer.preset.import_warning",
    "chart_designer.preset.import_reject", "chart_designer.preset.import_version",
    "chart_designer.preset.import_bad_json", "chart_designer.preset.import_missing_params",
    "chart_designer.preset.export_ok",
)


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """主窗口（不 show()）；HOME 与数据目录隔离到 tmp_path。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    from acouscope.app.controller import AppController

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 2.0)) / sr
    controller.load_from_array(0.2 * np.sin(2 * np.pi * 440.0 * t), sr)
    w = MainWindow(controller)
    # T-1046 件3：预置音高控件数据（mode==3 导出走真实渲染路径；异步分析在测试不可依赖）
    from acouscope.ui.widgets.pitch import PitchContourWidget

    srw = 8000
    tw = np.arange(int(srw * 1.0)) / srw
    pw = PitchContourWidget()
    pw.set_data(tw, 440.0 * np.ones(len(tw)))
    w._pitch_widget = pw
    yield w
    w.close()


# ---------------------------------------------------------------------------
# 件1 · 主题预设三层存取
# ---------------------------------------------------------------------------


def test_session_layer_fallback_no_project_no_settings(qapp):
    """会话层兜底：settings=None + 无 parent → 保存/加载不报错（三处既有测试同构）。"""
    panel = ChartDesignerPanel(settings=None)
    panel.edt_title.setText("SESS")
    panel.edt_preset_name.setText("sess_style")
    panel._on_preset_save()
    assert "sess_style" in panel._session_presets
    assert panel._preset_names() == ["sess_style"]

    panel.cmb_preset.setCurrentIndex(panel.cmb_preset.findData("sess_style"))
    panel._on_preset_load()
    assert panel.params()["title"] == "SESS"


def test_project_layer_preset_roundtrip(window, tmp_path):
    """项目层：保存 → 项目落盘 → 新管理器加载（切项目再切回）→ 参数逐一相等。"""
    window.action_chart_designer.trigger()
    panel = window.chart_designer_panel
    panel.edt_title.setText("PJ 标题")
    panel.spn_dpi.setValue(600)
    panel.edt_ref_values.setText("440, 880")
    panel.paramsChanged.emit()
    panel.edt_preset_name.setText("proj_style")
    panel._on_preset_save()

    project = window.controller.project.current
    assert "proj_style" in project.presets, "预设应写入项目层（parent()→controller.project）"
    snapshot = project.presets["proj_style"]
    assert snapshot["title"] == "PJ 标题"
    assert snapshot["dpi"] == 600
    assert snapshot["ref_values"] == [440.0, 880.0]

    # 切项目再切回：保存到盘 → 全新管理器加载（模拟切换后再打开）
    path = tmp_path / "proj.acouproj"
    window.controller.project.save(path)
    reloaded = ProjectManager().load(path)
    assert reloaded.presets["proj_style"] == snapshot, "项目级预设往返等值"

    # 加载到另一面板（同窗口通道）→ params 逐一相等
    panel2 = ChartDesignerPanel(settings=None, parent=window)
    panel2.cmb_preset.setCurrentIndex(panel2.cmb_preset.findData("proj_style"))
    panel2._on_preset_load()
    for key, value in snapshot.items():
        assert panel2.params()[key] == value, key


def test_global_layer_preset_roundtrip(tmp_path):
    """全局层：保存 → Settings 落盘 → 重启进程模拟（新 Settings.load）→ 仍在；删除不残留。"""
    settings = Settings()
    panel = ChartDesignerPanel(settings=settings)  # 无 parent → 无项目 → 落全局
    panel.edt_title.setText("GLB 标题")
    panel.edt_ref_values.setText("440")
    panel.edt_preset_name.setText("global_style")
    panel._on_preset_save()

    assert settings.chart_style_presets["global_style"]["title"] == "GLB 标题"
    path = tmp_path / "settings.json"
    settings.save(path)
    s2 = Settings.load(path)
    assert s2.chart_style_presets["global_style"]["title"] == "GLB 标题"
    assert s2.chart_style_presets["global_style"]["ref_values"] == [440.0]

    # 删除后不残留（两击确认）
    panel.cmb_preset.setCurrentIndex(panel.cmb_preset.findData("global_style"))
    panel._on_preset_delete()
    assert panel._armed == "del:global_style", "删除第一击仅武装"
    assert "global_style" in settings.chart_style_presets, "未确认不得删除"
    panel._on_preset_delete()
    assert "global_style" not in settings.chart_style_presets
    assert "global_style" not in panel._preset_names()


def test_save_overwrite_requires_two_clicks(qapp):
    """重名策略：禁静默覆盖 —— 重名第一击武装，第二击才覆盖。"""
    panel = ChartDesignerPanel(settings=None)
    panel.edt_title.setText("V1")
    panel.edt_preset_name.setText("dup")
    panel._on_preset_save()
    assert panel._preset_snapshot("dup")["title"] == "V1"

    panel.edt_title.setText("V2")
    panel._on_preset_save()
    assert panel._armed == "save:dup", "重名第一击应武装"
    assert panel._preset_snapshot("dup")["title"] == "V1", "未确认不得静默覆盖"
    panel._on_preset_save()
    assert panel._preset_snapshot("dup")["title"] == "V2"


def test_delete_requires_two_clicks(qapp):
    """删除确认：第一击武装，第二击删除且列表不残留。"""
    panel = ChartDesignerPanel(settings=None)
    panel.edt_title.setText("X")
    panel.edt_preset_name.setText("delme")
    panel._on_preset_save()
    panel.cmb_preset.setCurrentIndex(panel.cmb_preset.findData("delme"))
    panel._on_preset_delete()
    assert panel._armed == "del:delme"
    assert "delme" in panel._session_presets
    panel._on_preset_delete()
    assert "delme" not in panel._session_presets
    assert "delme" not in panel._preset_names()


# ---------------------------------------------------------------------------
# 件2 · 样式 JSON 导入/导出
# ---------------------------------------------------------------------------


def test_style_json_roundtrip(qapp, tmp_path):
    """导出 → 导入 → params() 逐一相等（往返等值）。"""
    panel = ChartDesignerPanel(settings=None)
    panel.edt_title.setText("RT 标题")
    panel.edt_subtitle.setText("SUB")
    panel.edt_source.setText("SRC")
    panel.edt_footer.setText("FTR")
    panel.edt_ref_values.setText("440, 880")
    panel.cmb_palette.setCurrentIndex(panel.cmb_palette.findData("viridis"))
    panel.spn_dpi.setValue(600)
    panel.chk_at01.setChecked(True)

    before = panel.params()
    out = tmp_path / "style.json"
    panel.export_style_json(out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["format"] == STYLE_FORMAT
    assert data["version"] == STYLE_VERSION

    panel2 = ChartDesignerPanel(settings=None)
    after = panel2.import_style_json(out)
    for key in before:
        assert after[key] == before[key], key


def test_import_rejects_foreign_format(qapp, tmp_path):
    """导入显式拒绝外来格式（与 annotation/export.py 同款 ValueError）。"""
    panel = ChartDesignerPanel(settings=None)
    foreign = tmp_path / "foreign.json"
    foreign.write_text(
        json.dumps({"format": "other-format", "version": 1, "params": {}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        panel.import_style_json(foreign)


def test_import_rejects_bad_json(qapp, tmp_path):
    """坏 JSON → ValueError（不崩）。"""
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        ChartDesignerPanel(settings=None).import_style_json(bad)


def test_import_rejects_missing_format_and_wrong_version(qapp, tmp_path):
    """缺 format / 错 version → ValueError。"""
    panel = ChartDesignerPanel(settings=None)
    nofmt = tmp_path / "nofmt.json"
    nofmt.write_text(json.dumps({"params": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        panel.import_style_json(nofmt)

    ver = tmp_path / "ver.json"
    ver.write_text(
        json.dumps({"format": STYLE_FORMAT, "version": 99, "params": {}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        panel.import_style_json(ver)


def test_import_unknown_keys_ignored_with_warning(qapp, tmp_path):
    """未知键 → 忽略 + 计入告警（策略写入报告）；已知键正常应用。"""
    panel = ChartDesignerPanel(settings=None)
    panel.edt_title.setText("KEEP")
    f = tmp_path / "unk.json"
    f.write_text(
        json.dumps({
            "format": STYLE_FORMAT,
            "version": STYLE_VERSION,
            "params": {"title": "NEW", "mystery_key": 1},
        }),
        encoding="utf-8",
    )
    result = panel.import_style_json(f)
    assert result["title"] == "NEW"
    assert panel._import_warnings == ["mystery_key"]


def test_import_missing_params_body_rejected(qapp, tmp_path):
    """缺参数体 → ValueError。"""
    f = tmp_path / "noparams.json"
    f.write_text(
        json.dumps({"format": STYLE_FORMAT, "version": STYLE_VERSION}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        ChartDesignerPanel(settings=None).import_style_json(f)


# ---------------------------------------------------------------------------
# 件3 · 报告 PDF 参数贯通（同源；不做模板引擎）
# ---------------------------------------------------------------------------


def _capture_export_caps(monkeypatch, exporter, name, caps):
    """打桩 _save → 捕获取色/文本/参考线证据（读真实渲染路径产物）。"""

    def fake_save(fig, output_path, fmt, dpi):  # noqa: ANN001
        caps[name] = {
            "fig_texts": [t.get_text() for t in fig.texts],
            "ax_texts": [t.get_text() for t in fig.axes[0].texts],
            "hlines": sorted(
                (round(float(ln.get_ydata()[0]), 3), ln.get_color(), ln.get_linestyle())
                for ln in fig.axes[0].get_lines()
                if ln.get_linestyle() in ("--", ":")  # 只捕参考线/闸门（散点轨迹 linestyle=None）
            ),
        }
        return Path(output_path)

    monkeypatch.setattr(exporter, "_save", fake_save)


def test_report_same_source_content_shell_and_ref_lines(window, monkeypatch, tmp_path):
    """件3 判据：title 非空 + mode==3 下，报告图与直接导出图在内容外壳/参考线上一致。"""
    window.action_chart_designer.trigger()
    panel = window.chart_designer_panel
    panel.edt_title.setText("T1046 同源标题")
    panel.edt_subtitle.setText("SUB_SRC_SAME")
    panel.edt_source.setText("SRC_SAME")
    panel.edt_footer.setText("FTR_SAME")
    panel.edt_ref_values.setText("440, 880")
    panel.edt_ref_ink.setText("#A00000")
    panel.chk_at01.setChecked(True)
    panel.paramsChanged.emit()

    params = window._current_chart_designer_params()
    assert params["title"] == "T1046 同源标题", "判据前提：title 非空"

    latin, cjk = window._current_chart_fonts()
    # 报告侧 exporter 自建（同 _collect_report_figures 口径：不带设计器参数）
    report_exporter = FigureExporter(font_latin=latin, font_cjk=cjk)
    direct_exporter = window._build_chart_exporter()

    caps: dict = {}
    _capture_export_caps(monkeypatch, report_exporter, "report", caps)
    _capture_export_caps(monkeypatch, direct_exporter, "direct", caps)
    for name, exporter in (("report", report_exporter), ("direct", direct_exporter)):
        window._export_current_view(exporter, 3, tmp_path / f"{name}.png", "png", dpi=72)

    rep, dct = caps["report"], caps["direct"]
    joined_rep = "".join(rep["fig_texts"] + rep["ax_texts"])
    joined_dct = "".join(dct["fig_texts"] + dct["ax_texts"])
    for token in ("SUB_SRC_SAME", "SRC_SAME", "FTR_SAME"):
        assert token in joined_rep, f"报告图缺内容外壳: {token}"
        assert token in joined_dct
    assert rep["hlines"] == dct["hlines"], "报告/直接导出参考线不一致"
    assert len(rep["hlines"]) == 6, "440/880 两条 + AT-01 闸门 4 条"
    assert all(color == "#A00000" for _, color, _ in rep["hlines"]), "ref_ink 应经 ink[ref_line] 生效"


def test_report_empty_params_no_content_shell(window, monkeypatch, tmp_path):
    """C⑤ 前提：未打开设计器（会话参数空）→ 报告图不带内容外壳/参考线。"""
    latin, cjk = window._current_chart_fonts()
    exporter = FigureExporter(font_latin=latin, font_cjk=cjk)
    caps: dict = {}
    _capture_export_caps(monkeypatch, exporter, "bare", caps)
    window._export_current_view(exporter, 3, tmp_path / "bare.png", "png", dpi=72)
    bare = caps["bare"]
    assert not bare["fig_texts"], "会话参数空 → 报告图不应带内容外壳"
    assert not bare["hlines"], "会话参数空 → 报告图不应带参考线"


# ---------------------------------------------------------------------------
# i18n：P3 新增键三语齐（硬判据）+ 静态纪律（新增代码 hex/px = 0）
# ---------------------------------------------------------------------------


def test_p3_new_keys_three_languages_hard():
    """i18n 新增键三语齐（en_US/zh_CN/zh_TW 硬判据；本实现按 P2 惯例五语全齐）。"""
    for key in _P3_NEW_KEYS:
        entry = _STRINGS[key]
        for lang in ("en_US", "zh_CN", "zh_TW"):
            assert lang in entry and entry[lang], (key, lang)
        for lang in ("ko_KR", "ja_JP"):
            assert lang in entry and entry[lang], (key, lang)


def test_p3_new_code_static_discipline():
    """静态：chart_designer.py 新增行 hex/px = 0、无 QDialog/show()（沿用 P2 口径）。"""
    import re

    hex_pat = re.compile(r"#[0-9a-fA-F]{3,8}\b")
    px_pat = re.compile(r"\d+px")
    text = _DESIGNER.read_text(encoding="utf-8")
    # 既有占位 "#RRGGBB"（非 hex）不受影响；禁新增真 hex / px 字面量
    assert not hex_pat.findall(text), "chart_designer.py 含 hex 字面量"
    assert not px_pat.findall(text), "chart_designer.py 含 px 字面量"
    assert "show()" not in text
    assert "QDialog" not in text


def test_p3_i18n_existing_keys_unchanged():
    """只加不改：既有键值未变（抽样）。"""
    assert _STRINGS["chart_designer.at01_hint"]["zh_CN"] == "测量精度闸门 — 报警阈值，非精度承诺"
    assert _STRINGS["chart_designer.export"]["zh_CN"] == "导出…"
