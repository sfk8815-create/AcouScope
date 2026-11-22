# SPDX-License-Identifier: GPL-3.0-only
"""PI-P5-B3-01i 判据：论文图导出 GUI 入口（全离屏，禁 MainWindow.show()）。

五条（设计约定 ★任务-4）：

① 菜单项存在：``导出 ▸ 论文图导出…`` 在导出子菜单内，objectName 唯一，
   排在「导出田野元数据」与「报告预览」之间，且不抢既有 Ctrl+E；
② 对话框三预设齐全；``paper_C`` 缺锚时导出按钮禁用、给锚后可用；
③ 导出真的调平台 API：``segment_curve``／``type_oscillation``／
   ``reference_comparison`` 被调用，实参 ``dpi==300``、``formats==("png","pdf")``、
   ``stem`` 与预设对应；
④ 校验失败路径：``paper_A`` 段起止非法（end ≤ start）→ 可见错误，不崩、不静默吞；
⑤ 无音频保护：``controller.has_audio()`` 为 False 时只 toast，不弹对话框、不抛异常。

口径：判据只验「接线与参数」，绘图逻辑归 ``tests/test_figures_export.py``。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QMenu

from acouscope.app.controller import AppController
from acouscope.i18n import set_language, tr
from acouscope.ui.main_window import MainWindow
from acouscope.ui.widgets import paper_figure_dialog as pf
from acouscope.ui.widgets.paper_figure_dialog import DPI, FORMATS, PaperFigureDialog
from acouscope.visualization.presets import get_preset, list_presets

#: 预设 → 通用图形（内部值由 get_preset 给，测试侧只做交叉核对）
_EXPECTED_FIGURE = {
    "paper_A": "segment_curve",
    "paper_B": "type_oscillation",
    "paper_C": "reference_comparison",
}


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_window(monkeypatch, tmp_path, *, with_audio: bool) -> MainWindow:
    """离屏 MainWindow（不 show）；HOME / 数据目录隔离到 tmp。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    set_language("zh_CN")

    controller = AppController()
    if with_audio:
        sr = 8000
        t = np.arange(int(sr * 2.0)) / sr
        controller.load_from_array(0.5 * np.sin(2 * np.pi * 440.0 * t), sr)
    return MainWindow(controller)


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    w = _make_window(monkeypatch, tmp_path, with_audio=True)
    yield w
    w.close()


@pytest.fixture
def silent_window(qapp, monkeypatch, tmp_path):
    w = _make_window(monkeypatch, tmp_path, with_audio=False)
    yield w
    w.close()


def _menu(window, key: str) -> QMenu:
    """按菜单标题取原生 QMenu（export_menu 为局部变量，不外露）。"""
    title = tr(key)
    found = [m for m in window.findChildren(QMenu) if m.title() == title]
    assert found, f"缺少菜单 {key}"
    return found[0]


# ---------------------------------------------------------------------------
# ① 菜单项存在
# ---------------------------------------------------------------------------


def test_export_paper_figure_action_in_export_menu(window):
    export_menu = _menu(window, "menu.export")
    acts = [a for a in export_menu.actions() if not a.isSeparator()]
    hits = [a for a in acts if a.objectName() == "export_paper_figure"]
    assert len(hits) == 1, f"导出子菜单应恰有 1 项 export_paper_figure，实得 {len(hits)}"
    act = hits[0]

    assert act.text() == tr("action.export_paper_figure")
    assert act.shortcut().isEmpty(), "新入口不得抢既有键位（Ctrl+E 归 action_export）"

    # 位置：紧跟「导出田野元数据」，其后为「报告预览」
    idx = acts.index(act)
    assert "导出田野元数据" in acts[idx - 1].text(), [a.text() for a in acts]
    assert acts[idx + 1] is window.action_report_preview

    # 既有 action_export 语义不动（同实例、同键位、仍在导出菜单）
    assert window.action_export in export_menu.actions()
    assert window.action_export.shortcut().toString() == "Ctrl+E"


# ---------------------------------------------------------------------------
# ② 三预设齐全 + paper_C 缺锚禁用
# ---------------------------------------------------------------------------


def test_dialog_three_presets_and_anchor_gate(qapp):
    dlg = PaperFigureDialog(None)
    try:
        assert dlg.preset_names() == list_presets() == ["paper_A", "paper_B", "paper_C"]
        combos = [dlg.cmb_preset.itemData(i) for i in range(dlg.cmb_preset.count())]
        assert combos == ["paper_A", "paper_B", "paper_C"]
        assert [dlg.cmb_preset.itemText(i) for i in range(dlg.cmb_preset.count())] == [
            tr("figure_export.preset_a"),
            tr("figure_export.preset_b"),
            tr("figure_export.preset_c"),
        ]
        # 内部值来自 get_preset(name)["figure"]（不另立映射）
        assert {n: get_preset(n)["figure"] for n in combos} == _EXPECTED_FIGURE

        # 出版要求不降级
        assert (DPI, FORMATS) == (300, ("png", "pdf"))
        assert dlg.lbl_publication.text() == "300 dpi · PNG + PDF"
        assert dlg.edit_dir.isReadOnly() is True
        assert dlg.output_dir().endswith("Documents")

        # 各预设专用行只露自己那一块
        dlg.cmb_preset.setCurrentIndex(dlg.cmb_preset.findData("paper_A"))
        assert dlg.section_a.isVisibleTo(dlg) and not dlg.section_b.isVisibleTo(dlg)
        dlg.cmb_preset.setCurrentIndex(dlg.cmb_preset.findData("paper_B"))
        assert dlg.section_b.isVisibleTo(dlg) and not dlg.section_c.isVisibleTo(dlg)
        dlg.cmb_preset.setCurrentIndex(dlg.cmb_preset.findData("paper_C"))
        assert dlg.section_c.isVisibleTo(dlg) and not dlg.section_a.isVisibleTo(dlg)

        # paper_C 缺锚 → 导出按钮禁用；界面写明「平台不猜」
        assert dlg.chk_anchor_pending.isChecked() is True
        assert dlg.anchor_offset_cents() is None
        assert dlg.btn_export.isEnabled() is False
        assert "平台不猜" in dlg.lbl_anchor_note.text()

        # 给锚（未提供复选框取消）→ 可用；默认 0 是「用户填了 0」，与「不填」区分
        dlg.chk_anchor_pending.setChecked(False)
        assert dlg.btn_export.isEnabled() is True
        assert dlg.anchor_offset_cents() == 0.0
        dlg.spin_anchor.setValue(-14.5)
        assert dlg.anchor_offset_cents() == -14.5

        # 回到 A 之后即使锚仍未给也允许导出（锚只约束 paper_C）
        dlg.chk_anchor_pending.setChecked(True)
        dlg.cmb_preset.setCurrentIndex(dlg.cmb_preset.findData("paper_A"))
        assert dlg.btn_export.isEnabled() is True
    finally:
        dlg.close()


# ---------------------------------------------------------------------------
# ③ 导出真的调平台 API（dpi / formats / stem / labels）
# ---------------------------------------------------------------------------


def test_export_calls_platform_api_with_publication_params(qapp, monkeypatch, tmp_path):
    from acouscope.visualization import figures

    calls: dict[str, tuple] = {}

    def _recorder(name, result):
        def _fn(*args, **kwargs):
            calls[name] = (args, kwargs)
            return result

        return _fn

    monkeypatch.setattr(
        figures, "segment_curve_data", _recorder("segment_curve_data", {"segment_id": "1.000-2.000"})
    )
    monkeypatch.setattr(figures, "segment_curve", _recorder("segment_curve", {"kind": "segment_curve"}))
    monkeypatch.setattr(
        figures,
        "type_oscillation_data",
        _recorder("type_oscillation_data", {"types": [], "bins": [], "panels": [{"label": "stub"}]}),
    )
    monkeypatch.setattr(
        figures, "type_oscillation", _recorder("type_oscillation", {"kind": "type_oscillation"})
    )
    monkeypatch.setattr(
        figures,
        "reference_comparison_data",
        _recorder("reference_comparison_data", {"anchor": {"offset_cents": 0.0, "source": ""}, "templates": []}),
    )
    monkeypatch.setattr(
        figures,
        "reference_comparison",
        _recorder("reference_comparison", {"kind": "reference_comparison"}),
    )
    # 建模型链路打桩（真读音频/真分析归 test_figures_export.py；此处只验参数透传）
    monkeypatch.setattr(figures, "_read_window", lambda *a, **k: (None, 44100, 0.0))
    monkeypatch.setattr(figures, "_analyze", lambda *a, **k: (None, None, object(), None))

    toasts: list[str] = []
    monkeypatch.setattr(pf, "show_toast", lambda parent, message, level="info", duration=3500: toasts.append(message))

    wav = tmp_path / "probe.wav"
    wav.write_bytes(b"")
    panels = tmp_path / "panels.json"
    panels.write_text(
        json.dumps({"panels": [{"label": "甲组", "rows": []}]}, ensure_ascii=False), encoding="utf-8"
    )
    out_dir = tmp_path / "figs"

    dlg = PaperFigureDialog(wav)
    try:
        dlg.edit_dir.setText(str(out_dir))

        # --- paper_A：段曲线 ---
        dlg.cmb_preset.setCurrentIndex(dlg.cmb_preset.findData("paper_A"))
        dlg.spin_start.setValue(1.0)
        dlg.spin_end.setValue(2.0)
        assert dlg.export() == {"kind": "segment_curve"}
        args, kwargs = calls["segment_curve"]
        assert args[0] == {"segment_id": "1.000-2.000"}
        assert args[1] == str(out_dir)
        assert kwargs["dpi"] == 300
        assert kwargs["formats"] == ("png", "pdf")
        assert kwargs["stem"] == "paper_a"
        assert kwargs["labels"] == get_preset("paper_A")["labels"]
        assert calls["segment_curve_data"][0][1:3] == (1.0, 2.0)

        # --- paper_B：分面（_load_panels 真读 JSON，未打桩）---
        dlg.cmb_preset.setCurrentIndex(dlg.cmb_preset.findData("paper_B"))
        dlg.edit_panels.setText(str(panels))
        assert dlg.export() == {"kind": "type_oscillation"}
        args_b, kwargs_b = calls["type_oscillation"]
        assert args_b[1] == str(out_dir)
        assert kwargs_b["dpi"] == 300
        assert kwargs_b["formats"] == ("png", "pdf")
        assert kwargs_b["stem"] == "paper_b"
        assert kwargs_b["labels"] == get_preset("paper_B")["labels"]
        assert calls["type_oscillation_data"][0][0][0]["label"] == "甲组"

        # --- paper_C：参照系对比（锚定偏移必须原样透传）---
        dlg.cmb_preset.setCurrentIndex(dlg.cmb_preset.findData("paper_C"))
        dlg.chk_anchor_pending.setChecked(False)
        dlg.spin_anchor.setValue(12.5)
        dlg.edit_anchor_source.setText("literature A=440")
        # 01j：C 分支改走一站式公开入口，结果带回取数窗登记三键（同一契约的严格化）
        assert dlg.export() == {
            "kind": "reference_comparison",
            "window_start_s": 0.0,
            "window_s": 30.0,
            "tuning_template": "12tet",
        }
        data_kwargs = calls["reference_comparison_data"][1]
        assert data_kwargs["anchor_offset_cents"] == 12.5
        assert data_kwargs["anchor_source"] == "literature A=440"
        args_c, kwargs_c = calls["reference_comparison"]
        assert args_c[1] == str(out_dir)
        assert kwargs_c["dpi"] == 300
        assert kwargs_c["formats"] == ("png", "pdf")
        assert kwargs_c["stem"] == "paper_c"
        assert kwargs_c["labels"] == get_preset("paper_C")["labels"]
        assert kwargs_c["require_anchor"] is True

        # 成功路径有可见反馈（toast 文案走 tr，不含硬编码）
        assert toasts == [tr("figure_export.done").format(path=str(out_dir))] * 3
    finally:
        dlg.close()


# ---------------------------------------------------------------------------
# ④ 校验失败路径：可见错误、不崩、不静默吞
# ---------------------------------------------------------------------------


def test_paper_a_invalid_range_reports_visible_error(qapp, monkeypatch, tmp_path):
    shown: list[tuple] = []

    class _FakeMessageBox:
        @staticmethod
        def warning(parent, title, text):
            shown.append((title, text))

    monkeypatch.setattr(pf, "QMessageBox", _FakeMessageBox)
    # 成功路径不该被走到
    monkeypatch.setattr(pf, "show_toast", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该 toast")))

    dlg = PaperFigureDialog(tmp_path / "absent.wav")
    try:
        dlg.cmb_preset.setCurrentIndex(dlg.cmb_preset.findData("paper_A"))
        dlg.spin_start.setValue(5.0)
        dlg.spin_end.setValue(4.0)  # end <= start → 平台 ValueError
        assert dlg.export() is None  # 不抛、返回 None
        assert dlg.last_result is None
        assert len(shown) == 1
        title, text = shown[0]
        assert title == tr("figure_export.failed")
        assert text and text == dlg.last_error
        assert text != tr("figure_export.need_audio")  # 真走到段校验，而非「无音频」兜底
    finally:
        dlg.close()


# ---------------------------------------------------------------------------
# ⑤ 无音频保护
# ---------------------------------------------------------------------------


def test_no_audio_shows_toast_and_skips_dialog(silent_window, monkeypatch):
    import acouscope.ui.main_window as mw

    assert silent_window.controller.has_audio() is False

    toasts: list[tuple] = []
    monkeypatch.setattr(
        mw,
        "show_toast",
        lambda parent, message, level="info", duration=3500: toasts.append((message, level)),
    )
    opened: list[tuple] = []
    monkeypatch.setattr(pf, "PaperFigureDialog", lambda *a, **k: opened.append((a, k)))

    silent_window._on_export_paper_figure()  # 不抛异常

    assert toasts == [(tr("msg.no_audio"), "info")]
    assert opened == []


# ---------------------------------------------------------------------------
# ⑥ 图 C 窗起点（PI-P5-B3-01j）：取数参数须真传给公开入口；私有名不得回潮
# ---------------------------------------------------------------------------


def test_paper_c_window_start_passed_and_no_private_names(qapp, monkeypatch, tmp_path):
    """C 预设把「窗起点」设为非 0 → 打桩入口须收到 window_start_s；源码禁 figures._。"""
    from pathlib import Path

    from acouscope.visualization import figures

    calls: dict[str, tuple] = {}

    def _recorder(*args, **kwargs):
        calls["reference_comparison_from_audio"] = (args, kwargs)
        return {"kind": "reference_comparison"}

    monkeypatch.setattr(figures, "reference_comparison_from_audio", _recorder)
    monkeypatch.setattr(
        pf, "show_toast", lambda parent, message, level="info", duration=3500: None
    )

    dlg = PaperFigureDialog(tmp_path / "probe.wav")
    try:
        # 控件规格：3 位小数、0–3600、默认 0；仅 paper_C 可见
        assert dlg.spin_window_start.decimals() == 3
        assert (dlg.spin_window_start.minimum(), dlg.spin_window_start.maximum()) == (0.0, 3600.0)
        assert dlg.spin_window_start.value() == 0.0
        dlg.cmb_preset.setCurrentIndex(dlg.cmb_preset.findData("paper_C"))
        assert dlg.spin_window_start.isVisibleTo(dlg) is True
        dlg.cmb_preset.setCurrentIndex(dlg.cmb_preset.findData("paper_B"))
        assert dlg.spin_window_start.isVisibleTo(dlg) is False
        dlg.cmb_preset.setCurrentIndex(dlg.cmb_preset.findData("paper_A"))
        assert dlg.spin_window_start.isVisibleTo(dlg) is False

        # 非 0 窗起点 ＋ 已给锚 → 导出；实参须原样带上（换窗即换数）
        dlg.cmb_preset.setCurrentIndex(dlg.cmb_preset.findData("paper_C"))
        dlg.chk_anchor_pending.setChecked(False)
        dlg.spin_anchor.setValue(12.5)
        dlg.spin_window_start.setValue(47.5)
        assert dlg.export() == {"kind": "reference_comparison"}
        args, kwargs = calls["reference_comparison_from_audio"]
        assert args[0] == str(tmp_path / "probe.wav")
        assert args[1] == dlg.output_dir()
        assert kwargs["window_start_s"] == 47.5
        assert kwargs["anchor_offset_cents"] == 12.5
        assert kwargs["require_anchor"] is True
        assert kwargs["dpi"] == 300
        assert kwargs["formats"] == ("png", "pdf")
        assert kwargs["stem"] == "paper_c"
        assert kwargs["labels"] == get_preset("paper_C")["labels"]
    finally:
        dlg.close()

    # 私有名回潮闸：对话框源码不得再直调 figures 私有名（防通用层一改名就断）
    src = Path(pf.__file__).read_text(encoding="utf-8")
    assert "figures._" not in src, "对话框不得直调 figures 私有名"
