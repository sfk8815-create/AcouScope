# SPDX-License-Identifier: GPL-3.0-only
"""W-14 B5 GUI 冒烟（九面；``QT_QPA_PLATFORM=offscreen``）。

只验接线与同源：控件存在、可操作、无死按钮；GUI 展示与平台 API 逐值一致。
**不含真实录音**（合成音频／合成 payload），真实夹具截图见
`03_Docs_and_Assets/platform_w14_20261102/gui_acceptance/`。
"""

import json

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from acouscope.i18n import set_language, tr  # noqa: E402
from acouscope.ui.widgets.batch_readout_dialog import (  # noqa: E402
    CUSTOM_ITEM,
    BatchReadoutDialog,
)
from acouscope.ui.widgets.cavity_core_dialog import CavityCoreDialog  # noqa: E402
from acouscope.ui.widgets.paper_figure_dialog import PaperFigureDialog  # noqa: E402
from acouscope.ui.widgets.panels.inspector_panel import InspectorPanel  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    set_language("zh_CN")
    yield app


@pytest.fixture(scope="module")
def custom_scl(tmp_path_factory):
    from acouscope.analysis.tunings.scl import save_scl
    from acouscope.analysis.tunings.tuning_system import TuningSystem

    tuning = TuningSystem.from_cents(
        name="冒烟用五音", source="测试夹具（非文献）", cents=[150.0, 350.0, 700.0, 1200.0]
    )
    return save_scl(tuning, tmp_path_factory.mktemp("scl") / "smoke5.scl")


# ---------------------------------------------------------------- 面板 1／5
def test_batch_dialog_template_surface(qapp, custom_scl):
    """面 1／5：模板下拉含八内置＋自定义项；日志行含名称/来源/指纹。"""
    dlg = BatchReadoutDialog()
    keys = [dlg.cmb_template.itemData(i) for i in range(dlg.cmb_template.count())]
    assert len(keys) == 9
    assert keys[-1] == CUSTOM_ITEM
    assert "indian_22_shruti" in keys and "arabic_24_tone" in keys
    # 默认模板的日志行与 template_record 逐值一致（与 run_descriptor 同源函数）
    block = dlg.template_info()
    assert block["template_key"] == "12tet"
    text = dlg.lbl_template_info.text()
    assert block["template_name"] in text
    assert block["template_fingerprint"] in text

    dlg.bind_custom_scl(str(custom_scl))
    assert dlg.template_spec() == str(custom_scl)
    spec = dlg.spec()
    assert spec["params"]["template"] == str(custom_scl)
    block = dlg.template_info()
    assert block["template_key"].startswith("custom:")
    assert len(block["template_sha256"]) == 64
    dlg.close()


def test_batch_dialog_custom_bad_file_reports(qapp, tmp_path):
    """面 1：坏 .scl 显式报错，不静默回退 12TET。"""
    bad = tmp_path / "bad.scl"
    bad.write_text("not a scl file\n", encoding="utf-8")
    dlg = BatchReadoutDialog()
    with pytest.raises(ValueError):
        dlg.bind_custom_scl(str(bad))
    assert dlg.template_spec() == "12tet"       # 仍在原模板，未被悄悄改成 12TET 之外
    assert "bad.scl" in dlg.lbl_template_info.text() or dlg.lbl_template_info.text()
    dlg.close()


# ---------------------------------------------------------------- 面板 3
def test_cavity_core_dialog_table_matches_payload(qapp):
    """面 3：候选表与 JSON 逐值一致；空表如实为空。"""
    payload = {
        "format": "acouscope-cavity-core-candidates-v2",
        "version": 2,
        "recording_id": "smoke",
        "template": "qin_lu",
        "params": {"max_gap_s": 0.3, "min_frame_share": None},
        "filter_status": "not_applied",
        "n_candidates": 2,
        "candidates": [
            {
                "candidate_id": "aaaa1111", "start_s": 0.0, "end_s": 1.0,
                "degree_index": 3, "degree_deviation_cents": 4.5,
                "frame_share": 0.5, "duration_s": 1.0, "median_ci95_cents": 1.25,
                "template": "qin_lu",
            },
            {
                "candidate_id": "bbbb2222", "start_s": 2.0, "end_s": 3.5,
                "degree_index": 5, "degree_deviation_cents": -2.0,
                "frame_share": 0.9, "duration_s": 1.5, "median_ci95_cents": None,
                "template": "qin_lu",
            },
        ],
        "rejected": [],
    }
    dlg = CavityCoreDialog(audio_path=None, template="qin_lu")
    dlg.set_payload(payload)
    rows = dlg.table_rows()
    assert len(rows) == 2
    assert rows[0]["candidate_id"] == "aaaa1111"
    assert rows[0]["range"] == "0.000–1.000"
    assert rows[0]["frame_share"] == "0.500"
    assert rows[1]["median_ci95_cents"] == ""       # None ⇒ 空串（不写 0）
    # 导出与表同源
    exported = json.loads(dlg.payload_json_text())
    assert [c["candidate_id"] for c in exported["candidates"]] == [
        row["candidate_id"] for row in rows
    ]
    # 空表如实为空（不伪造行）
    dlg.set_payload({**payload, "candidates": [], "n_candidates": 0})
    assert dlg.table.rowCount() == 0
    dlg.close()


# ---------------------------------------------------------------- 面板 6／7
def test_paper_figure_dialog_calibre_controls(qapp):
    """面 6／7：音名口径开关与分母口径三档；默认值不改旧行为。"""
    dlg = PaperFigureDialog(None)
    assert dlg.note_name() is False                 # 默认不增出（旧行为）
    assert dlg.denominator() == "all"
    assert [
        dlg.cmb_denominator.itemData(i) for i in range(dlg.cmb_denominator.count())
    ] == ["all", "judgable", "body"]
    dlg.chk_note_name.setChecked(True)
    assert dlg.note_name() is True
    dlg.cmb_denominator.setCurrentIndex(2)
    assert dlg.denominator() == "body"
    dlg.close()


# ---------------------------------------------------------------- 面板 2
class _StubProjectFile:
    def __init__(self, path):
        self.path = str(path)
        self.metadata = {}


class _StubManager:
    def __init__(self):
        self.files = {}

    def get_file(self, path):
        return self.files.get(str(path))

    def add_file(self, path, label=""):
        self.files[str(path)] = _StubProjectFile(path)
        return self.files[str(path)]


def test_inspector_morphology_roundtrip(qapp, tmp_path):
    """面 2：形态学组可见、保存/回读、校验拦截。"""
    wav = tmp_path / "tone.wav"
    import numpy as np
    import soundfile as sf

    sr = 16000
    t = np.arange(sr) / sr
    sf.write(str(wav), 0.2 * np.sin(2 * np.pi * 440.0 * t), sr)

    panel = InspectorPanel()
    manager = _StubManager()
    panel.set_manager(manager)
    assert panel.show_file_metadata(str(wav)) is True
    assert panel.morph_box.objectName() == "morphologyBox"  # 组已建立（显隐随编辑区）
    assert set(panel.morph_edits) == {
        "CavityPosition", "NotePosition", "annotator", "method", "template", "confidence",
    }
    assert panel.morph_cavity_combo.count() == 5          # 空 + 四值

    # 缺 annotator/method/template ⇒ 保存被拦（写盘前校验）
    panel.morph_cavity_combo.setCurrentIndex(1)            # 上趋
    panel.morph_edits["annotator"].setText("A1")
    panel._on_meta_save()
    pf = manager.get_file(str(wav))
    assert pf is not None
    assert pf.metadata.get("_morphology", "") == ""       # 未通过校验 ⇒ 未写入块
    assert tr("w14.morph.invalid").split("{")[0] in panel.lbl_meta_status.text()

    # 补齐三必填 + confidence ⇒ 通过并写入
    panel.morph_edits["method"].setText("stable 中位偏离")
    panel.morph_edits["template"].setText("qin_lu")
    panel.morph_edits["confidence"].setText("0.8")
    panel.morph_edits["CavityPosition"].setText("一弦")
    panel._on_meta_save()
    stored = json.loads(pf.metadata["_morphology"])
    assert stored["CavityType"] == "上趋"
    assert stored["CavityCoreAnnotation"]["annotator"] == "A1"
    assert stored["CavityCoreAnnotation"]["confidence"] == pytest.approx(0.8)

    # 回读：另起面板读同一文件 ⇒ 字段回到控件
    again = InspectorPanel()
    again.set_manager(manager)
    again.show_file_metadata(str(wav))
    assert again.morph_edits["annotator"].text() == "A1"
    assert again.morph_cavity_combo.currentData() == "上趋"
    assert again.morph_edits["confidence"].text() == "0.8"
    panel.close()
    again.close()


# ---------------------------------------------------------------- 面板 8
def test_i18n_new_keys_five_languages():
    """面 8：W-14 新增键五语齐（zh/en/zh_TW/ko/ja 逐键有值）。"""
    from acouscope.i18n import _STRINGS

    keys = [key for key in _STRINGS if key.startswith("w14.")]
    assert len(keys) >= 40
    for key in keys:
        for locale in ("en_US", "zh_CN", "zh_TW", "ko_KR", "ja_JP"):
            assert _STRINGS[key].get(locale), f"{key} 缺 {locale}"


# ---------------------------------------------------------------- 面板 9
def test_all_new_controls_are_wired(qapp, custom_scl):
    """面 9：新增控件都有 clicked/信号接线（无死按钮）。"""
    dlg = BatchReadoutDialog()
    for button in (dlg.btn_save_scl, dlg.btn_cavity, dlg.btn_tuning_infer):
        assert button.receivers(button.clicked) > 0
    assert dlg.cmb_template.receivers(dlg.cmb_template.currentIndexChanged) > 0
    dlg.close()
    cavity = CavityCoreDialog()
    for button in (cavity.btn_run, cavity.btn_export, cavity.btn_close):
        assert button.receivers(button.clicked) > 0
    cavity.close()
    figure = PaperFigureDialog(None)
    assert figure.btn_export.receivers(figure.btn_export.clicked) > 0
    figure.close()
