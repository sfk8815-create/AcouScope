# SPDX-License-Identifier: GPL-3.0-only
"""T-912 音频档案元数据填报（检查器集成）回归测试。

覆盖（需求说明 Step 4）：
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

    def test_standard_combo_four_items_and_desc_switch(self, qapp, zh):
        panel = InspectorPanel()
        combo = panel.meta_standard_combo
        assert combo.count() == 4
        texts = [combo.itemText(i) for i in range(combo.count())]
        assert texts[0] == tr("inspector.meta.std_dat")
        assert texts[1] == tr("inspector.meta.std_gbt")
        assert texts[2] == tr("inspector.meta.std_custom")
        assert texts[3] == tr("inspector.meta.std_imdi")
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
        # 第四项 IMDI（M-4）：说明区
        combo.setCurrentIndex(3)
        assert panel.lbl_meta_desc.text() == tr("inspector.meta.desc_imdi")

    def test_custom_note_label_present(self, qapp, zh):
        from PyQt6.QtWidgets import QLabel

        panel = InspectorPanel()
        notes = panel.findChildren(QLabel, "metaCustomNote")
        assert len(notes) == 1
        assert tr("inspector.meta.custom_note") == "自定义扩展（非标准元素）"
        assert notes[0].text() == "自定义扩展（非标准元素）"

    def test_meta_field_labels_cover_field_keys(self, qapp):
        # 手填 12 键集有编辑框（M-8a 的自动四项不入手填表，见 M-8a 设计约定）
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
            "inspector.meta.std_imdi",
            "inspector.meta.desc_dat",
            "inspector.meta.desc_gbt",
            "inspector.meta.desc_custom",
            "inspector.meta.desc_imdi",
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
        panel.meta_edits["Creator"].setText("张三")
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


class TestMetadataRequiredByStandard:
    """M-4b-2：检查器保存接必填集（缺必填拦盘 / 空集标准照旧 / Date 两形格式）。"""

    def test_empty_required_standards_save_as_before(self, qapp, two_wavs, zh):
        """三家空集标准（custom/GBT/IMDI）：空表保存照旧成功（空集=现行为零变化）。

        注：Date 自动预填为文件 mtime（%Y-%m-%d %H:%M），属 M-4b 补令两形之一
        （M14「件级应含日期与时间」）→ 不触格式警告，状态行照旧 saved。
        """
        a, _b = two_wavs
        mgr = ProjectManager()
        panel = InspectorPanel()
        panel.set_manager(mgr)
        panel.show_file_metadata(str(a))
        for code, idx in (("custom", 2), ("GBT31219.4", 1), ("IMDI", 3)):
            panel.meta_standard_combo.setCurrentIndex(idx)
            panel.btn_meta_save.click()
            pf = mgr.get_file(str(a))
            assert pf.metadata["_standard"] == code  # 空集不拦、照旧写盘
            assert pf.metadata["SamplingRate"] == "8000"
            assert panel.lbl_meta_status.text() == tr("inspector.meta.saved")

    def test_dat63_missing_format_blocked(self, qapp, two_wavs, zh):
        """DAT63 缺 Format → 不写盘且状态行含缺项中文名（焦点回缺项）。"""
        a, _b = two_wavs
        mgr = ProjectManager()
        panel = InspectorPanel()
        panel.set_manager(mgr)
        panel.show_file_metadata(str(a))
        panel.meta_edits["Format"].setText("")  # 抹掉自动预填
        panel.meta_edits["Title"].setText("甲档案")
        panel.meta_standard_combo.setCurrentIndex(0)  # DAT63
        panel.btn_meta_save.click()

        pf = mgr.get_file(str(a))
        assert "_standard" not in pf.metadata  # 未写盘
        assert "Title" not in pf.metadata
        status = panel.lbl_meta_status.text()
        assert "格式" in status  # 缺项中文名（FIELD_TERMS.label_zh）
        assert status != tr("inspector.meta.saved")

    def test_dat63_complete_saves(self, qapp, two_wavs, zh):
        """DAT63 填齐 6 必填 → 写盘成功（预填 Date 属两形之一 → saved）。"""
        a, _b = two_wavs
        mgr = ProjectManager()
        panel = InspectorPanel()
        panel.set_manager(mgr)
        panel.show_file_metadata(str(a))
        panel.meta_edits["Title"].setText("甲档案")
        panel.meta_edits["Creator"].setText("张三")
        panel.meta_standard_combo.setCurrentIndex(0)  # DAT63
        panel.btn_meta_save.click()

        pf = mgr.get_file(str(a))
        assert pf.metadata["_standard"] == "DAT63"
        assert pf.metadata["Title"] == "甲档案"
        assert pf.metadata["Creator"] == "张三"
        assert pf.metadata["Format"] == "WAV"  # 自动预填随保存落盘
        assert panel.lbl_meta_status.text() == tr("inspector.meta.saved")

    def test_date_format_two_forms(self, qapp, two_wavs, zh):
        """Date 两形：自家预填形（2026-10-13 22:04）→ saved；两形皆不合（2026-13-45）→ 仍存且格式提示。"""
        a, _b = two_wavs
        mgr = ProjectManager()
        panel = InspectorPanel()
        panel.set_manager(mgr)
        panel.show_file_metadata(str(a))
        # 反向保护（护住 M-4b 补令 〇-6-3 放宽）：日期+时间形合法 → saved 而非 format_warn
        panel.meta_edits["Date"].setText("2026-10-13 22:04")
        panel.btn_meta_save.click()  # 默认 custom（空集）
        pf = mgr.get_file(str(a))
        assert pf.metadata["Date"] == "2026-10-13 22:04"
        assert panel.lbl_meta_status.text() == tr("inspector.meta.saved")
        # 两形皆不合 → 仍保存（不阻断真实数据）且状态行为格式提示
        panel.meta_edits["Date"].setText("2026-13-45")
        panel.btn_meta_save.click()
        pf = mgr.get_file(str(a))
        assert pf.metadata["Date"] == "2026-13-45"
        status = panel.lbl_meta_status.text()
        assert status != tr("inspector.meta.saved")
        assert "YYYY-MM-DD" in status


class TestMetaStatusLabelLocalized:
    """M-4b-3：检查器状态行字段名改用本地化标签（zh_TW 不嵌简体、en 不嵌中文）。

    守卫 missing_required / format_warn 两处 fields 拼装改走 tr(_META_LABEL_KEY…)，
    并结构守卫 inspector_panel 源码不再出现 _META_LABEL_ZH / label_zh（简体源）。
    """

    def test_missing_required_label_localized(self, qapp, two_wavs):
        """DAT63 只填 Title → 拦盘；状态行字段名随 locale 本地化。

        zh_TW：含繁体「責任者/傳承人」且不含简体「创作者/传承人」；
        en_US：含「Creator / Inheritor」且整行零汉字（CJK 统一表意文字区间）。
        """
        import re

        a, _b = two_wavs

        def _status_only_title(lang):
            prev = get_language()
            set_language(lang)
            try:
                mgr = ProjectManager()
                panel = InspectorPanel()
                panel.set_manager(mgr)
                panel.show_file_metadata(str(a))
                panel.meta_edits["Title"].setText("甲档案")
                panel.meta_standard_combo.setCurrentIndex(0)  # DAT63
                panel.btn_meta_save.click()
                return panel.lbl_meta_status.text()
            finally:
                set_language(prev)

        status_tw = _status_only_title("zh_TW")
        assert "責任者/傳承人" in status_tw
        assert "创作者" not in status_tw
        assert "传承人" not in status_tw

        status_en = _status_only_title("en_US")
        assert "Creator / Inheritor" in status_en
        assert re.search(r"[\u4e00-\u9fff]", status_en) is None

    def test_format_warn_label_localized(self, qapp, two_wavs):
        """护 format_warn——zh_TW 下 Date 非法值 → 状态行字段名本地化。

        含繁体「攝錄時間」、不含简体「摄录时间」。
        """
        a, _b = two_wavs
        prev = get_language()
        set_language("zh_TW")
        try:
            mgr = ProjectManager()
            panel = InspectorPanel()
            panel.set_manager(mgr)
            panel.show_file_metadata(str(a))
            panel.meta_standard_combo.setCurrentIndex(2)  # custom（空必填集 → 直达格式检查）
            panel.meta_edits["Date"].setText("2026-13-45")  # 两形皆不合
            panel.btn_meta_save.click()
            status = panel.lbl_meta_status.text()
        finally:
            set_language(prev)
        assert "攝錄時間" in status
        assert "摄录时间" not in status

    def test_no_hardcoded_simplified_labels(self):
        """结构守卫：inspector_panel 源码不得再现 _META_LABEL_ZH 与 label_zh（防退回旧形）。"""
        import inspect

        from acouscope.ui.widgets.panels import inspector_panel

        src = inspect.getsource(inspector_panel)
        assert "_META_LABEL_ZH" not in src
        assert "label_zh" not in src

