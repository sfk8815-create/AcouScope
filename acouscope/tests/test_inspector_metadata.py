# SPDX-License-Identifier: GPL-3.0-only
"""T-912 音频档案元数据填报（检查器集成）回归测试。

覆盖（任务书 Step 4）：
- 选中支持音频 → 技术字段自动预填正确（采样率/位深/格式/声道/时长）；
  尚无 ProjectFile 条目 → 自动 add_file 登记（自动登记）；
- 未选中/不支持格式 → 空态不报错；
- 标准下拉 3 项；切换 → 说明区文本变化（断言含关键要点）；
- 填写题名/责任者 → 保存 → ProjectFile.metadata 正确；
- 选 DA/T 63-2017 保存 → metadata["_standard"] == "DAT63"（落盘断言）；
- 切换文件 → 加载各自元数据（不串档），_standard 下拉回显正确；
- 标准外字段标注存在；
- 既有检查器回归护栏：inspectorGroupTitle 仍为既有六组；
  i18n 新键三语齐全。

直接实例化 InspectorPanel（离屏，不构造主窗口、不 show）。
禁词 0；禁硬编码 hex/px。
"""

import numpy as np
import pytest

pytest.importorskip("PyQt6")

import soundfile as sf

from acouscope.app.project import ProjectManager
from acouscope.i18n import get_language, set_language, tr
from acouscope.ui.widgets.panels import InspectorPanel


def _write_wav(path, sr, seconds, freq=440.0):
    """写 PCM_16 单声道 wav（soundfile；合成可复现）。"""
    t = np.arange(int(sr * seconds)) / sr
    sf.write(str(path), 0.3 * np.sin(2 * np.pi * freq * t), sr, subtype="PCM_16")


@pytest.fixture
def two_wavs(tmp_path):
    """两个技术参数不同的支持音频（时长/sr 决定预填断言）。"""
    a = tmp_path / "tape_a.wav"
    b = tmp_path / "tape_b.wav"
    _write_wav(a, 8000, 1.0)
    _write_wav(b, 16000, 2.0)
    return a, b


@pytest.fixture
def zh():
    """中文语境（断言含中文关键要点；用毕还原）。"""
    prev = get_language()
    set_language("zh_CN")
    yield
    set_language(prev)


class TestMetadataEditorUi:
    """UI 结构/文案：标准下拉、说明区、标注、i18n、六组标题护栏。"""

    def test_standard_combo_three_items_and_desc_switch(self, qapp, zh):
        panel = InspectorPanel()
        combo = panel.meta_standard_combo
        assert combo.count() == 3
        texts = [combo.itemText(i) for i in range(combo.count())]
        assert texts[0] == tr("inspector.meta.std_dat")
        assert texts[1] == tr("inspector.meta.std_gbt")
        assert texts[2] == tr("inspector.meta.std_custom")
        assert "不指定" in texts[2]

        # 切换 → 说明区随动（断言含关键要点）
        combo.setCurrentIndex(0)
        assert "录音录像类电子档案元数据方案" in panel.lbl_meta_desc.text()
        assert "四实体模式" in panel.lbl_meta_desc.text()
        combo.setCurrentIndex(1)
        assert "图书馆馆藏资源数字化加工规范" in panel.lbl_meta_desc.text()
        assert "人文描述字段" in panel.lbl_meta_desc.text()
        combo.setCurrentIndex(2)
        assert "自定义" in panel.lbl_meta_desc.text()
        assert "田野研究" in panel.lbl_meta_desc.text()

    def test_custom_note_label_present(self, qapp, zh):
        from PyQt6.QtWidgets import QLabel

        panel = InspectorPanel()
        notes = panel.findChildren(QLabel, "metaCustomNote")
        assert len(notes) == 1
        assert tr("inspector.meta.custom_note") == "自定义扩展（非标准元素）"
        assert notes[0].text() == "自定义扩展（非标准元素）"

    def test_meta_field_labels_cover_field_keys(self, qapp):
        # 每个字段键都有编辑框（12 键全覆盖）
        panel = InspectorPanel()
        for key in (
            "SamplingRate", "BitDepth", "Format", "Channels", "Duration",
            "Date", "Identifier", "Title", "Creator",
            "Location", "GenreContext", "ActorRole",
        ):
            assert key in panel.meta_edits, f"缺编辑框: {key}"

    def test_inspector_group_titles_still_six(self, qapp):
        """回归护栏：新增区未给既有六组标题计数引入额外标题。"""
        from PyQt6.QtWidgets import QLabel

        panel = InspectorPanel()
        titles = panel.findChildren(QLabel, "inspectorGroupTitle")
        assert len(titles) == 6

    def test_new_i18n_keys_three_languages(self):
        from acouscope.i18n import _STRINGS

        keys = (
            "inspector.metadata",
            "inspector.meta.save",
            "inspector.meta.saved",
            "inspector.meta.empty",
            "inspector.meta.custom_note",
            "inspector.meta.std_dat",
            "inspector.meta.std_gbt",
            "inspector.meta.std_custom",
            "inspector.meta.desc_dat",
            "inspector.meta.desc_gbt",
            "inspector.meta.desc_custom",
            "inspector.meta.sampling_rate",
            "inspector.meta.bit_depth",
            "inspector.meta.format",
            "inspector.meta.channels",
            "inspector.meta.duration",
            "inspector.meta.date",
            "inspector.meta.identifier",
            "inspector.meta.title",
            "inspector.meta.creator",
            "inspector.meta.location",
            "inspector.meta.genre_context",
            "inspector.meta.actor_role",
        )
        for key in keys:
            entry = _STRINGS.get(key)
            assert entry is not None, f"i18n 缺 key: {key}"
            for lang in ("en_US", "zh_CN", "zh_TW"):
                assert entry.get(lang), f"{key} 缺 {lang}"


class TestMetadataLoadSave:
    """选中文件加载/保存/切换不串档。"""

    def test_auto_register_and_tech_prefill(self, qapp, two_wavs, zh):
        a, _b = two_wavs
        mgr = ProjectManager()
        panel = InspectorPanel()
        panel.set_manager(mgr)
        assert panel.meta_active is False

        registered = panel.show_file_metadata(str(a))
        assert registered is True  # 本次新增登记
        pf = mgr.get_file(str(a))
        assert pf is not None  # 自动登记生效
        assert panel.meta_active is True

        edits = panel.meta_edits
        assert edits["SamplingRate"].text() == "8000"
        assert edits["BitDepth"].text() == "16"
        assert edits["Format"].text() == "WAV"
        assert edits["Channels"].text() == "1"
        assert edits["Duration"].text() == "00:00:01"
        # 自动预填字段可校正且非空
        assert edits["Date"].text()
        assert edits["Identifier"].text()

        # 二次选中同文件：不再新增登记
        assert panel.show_file_metadata(str(a)) is False

    def test_save_title_creator_and_standard_lands(self, qapp, two_wavs, zh):
        a, _b = two_wavs
        mgr = ProjectManager()
        panel = InspectorPanel()
        panel.set_manager(mgr)
        panel.show_file_metadata(str(a))

        panel.meta_edits["Title"].setText("侗族大歌")
        panel.meta_edits["Creator"].setText("传承人吴某")
        panel.meta_edits["Location"].setText("贵州黔东南")
        panel.meta_standard_combo.setCurrentIndex(0)  # DA/T 63-2017
        panel.btn_meta_save.click()

        md = mgr.get_file(str(a)).metadata
        assert md["Title"] == "侗族大歌"
        assert md["Creator"] == "传承人吴某"
        assert md["Location"] == "贵州黔东南"
        assert md["_standard"] == "DAT63"  # 所选标准落盘断言
        assert md["SamplingRate"] == "8000"  # 技术元数据随保存落盘
        assert md["Duration"] == "00:00:01"
        # 空/未填字段不写入
        assert "GenreContext" not in md
        assert "ActorRole" not in md
        assert "BitDepth" in md  # 自动预填 → 保存即写入

    def test_switch_files_no_cross_contamination(self, qapp, two_wavs, zh):
        a, b = two_wavs
        mgr = ProjectManager()
        panel = InspectorPanel()
        panel.set_manager(mgr)

        # A：填题名 + DA/T
        panel.show_file_metadata(str(a))
        panel.meta_edits["Title"].setText("甲档案")
        panel.meta_standard_combo.setCurrentIndex(0)
        panel.btn_meta_save.click()

        # 切到 B：不回显 A 的题名；技术参数按 B 文件预填；_standard 默认 custom
        panel.show_file_metadata(str(b))
        assert panel.meta_edits["Title"].text() == ""
        assert panel.meta_edits["SamplingRate"].text() == "16000"
        assert panel.meta_edits["Duration"].text() == "00:00:02"
        assert panel.meta_standard_combo.currentIndex() == 2  # custom 默认
        panel.meta_edits["Title"].setText("乙档案")
        panel.meta_standard_combo.setCurrentIndex(1)  # GB/T
        panel.btn_meta_save.click()

        # 切回 A：回显 A 的题名与 _standard（不串档）
        panel.show_file_metadata(str(a))
        assert panel.meta_edits["Title"].text() == "甲档案"
        assert panel.meta_edits["SamplingRate"].text() == "8000"
        assert panel.meta_standard_combo.currentIndex() == 0  # DAT63 回显

        # 各自 metadata 独立
        assert mgr.get_file(str(a)).metadata["_standard"] == "DAT63"
        assert mgr.get_file(str(b)).metadata["_standard"] == "GBT31219.4"
        assert mgr.get_file(str(b)).metadata["Title"] == "乙档案"

    def test_standard_echo_from_stored(self, qapp, two_wavs, zh):
        a, _b = two_wavs
        mgr = ProjectManager()
        panel = InspectorPanel()
        panel.set_manager(mgr)
        panel.show_file_metadata(str(a))
        pf = mgr.get_file(str(a))
        pf.metadata["Title"] = "已存题名"
        pf.metadata["_standard"] = "GBT31219.4"
        # 重选 → 下拉按已存 _standard 回显 + 已存题名回显
        panel.show_file_metadata(str(a))
        assert panel.meta_edits["Title"].text() == "已存题名"
        assert panel.meta_standard_combo.currentIndex() == 1


class TestMetadataEdgeCases:
    """空态/无 manager/清空选择 等边界。"""

    def test_unsupported_file_empty_state_no_error(self, qapp, two_wavs, tmp_path):
        a, _b = two_wavs
        mgr = ProjectManager()
        panel = InspectorPanel()
        panel.set_manager(mgr)
        txt = tmp_path / "notes.txt"
        txt.write_text("not audio", encoding="utf-8")

        assert panel.show_file_metadata(str(txt)) is False
        assert panel.meta_active is False
        assert panel.btn_meta_save.isEnabled() is False
        assert mgr.get_file(str(txt)) is None  # 非音频不登记

        # 回到支持音频仍正常
        assert panel.show_file_metadata(str(a)) is True

    def test_clear_metadata_back_to_empty(self, qapp, two_wavs, zh):
        a, _b = two_wavs
        mgr = ProjectManager()
        panel = InspectorPanel()
        panel.set_manager(mgr)
        panel.show_file_metadata(str(a))
        assert panel.meta_active is True
        panel.clear_metadata()
        assert panel.meta_active is False
        assert panel.btn_meta_save.isEnabled() is False

    def test_without_manager_still_prefills_save_disabled(self, qapp, two_wavs):
        a, _b = two_wavs
        panel = InspectorPanel()  # 未注入 manager
        assert panel.show_file_metadata(str(a)) is False
        assert panel.meta_active is True
        assert panel.meta_edits["SamplingRate"].text() == "8000"
        assert panel.btn_meta_save.isEnabled() is False
