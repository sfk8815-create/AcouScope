# SPDX-License-Identifier: GPL-3.0-only
"""T-914 批量更改元数据模块（Batch Workspace 首个业务模块）回归测试。

覆盖任务书 Step 4：
① 范围与标准：3 文件 → 步骤① N=3 + 新登记/已入档明示；标准下拉 3 项 + 说明区切换；
② 批量字段：共同字段填一次 → 应用 → 3 文件 metadata 均含该值；技术字段逐文件自动且不串；
③ 题名：默认=文件名；留空回退文件名（兜底）；统一前缀模式；
④ 责任者空 → 拦截（apply 不写任何文件 + 核对清单警告 + [应用并完成] 不退出）；
⑤ 标准批量落盘：选 DA/T 63-2017 → 3 文件 metadata["_standard"] == "DAT63"；
⑥ 核对清单：每文件最终摘要 + 技术列只读 + 应用后报告 N 成功（框架 _fmt_result 契约）；
⑦ 框架集成：模块可枚举/激活；MainWindow 右键入口（addContextAction 无参回调）
    → 进入 index1 并 activate 本模块；框架级「批处理…」入口行为不变（不激活模块）；
⑧ 无 manager → apply 逐文件失败（不崩、不登记）。
另：i18n 键三语齐全（含复用 T-912 的标准/说明区键）；禁词 0；禁硬编码 hex/px。

口径：离屏独立构造（qapp fixture）；MainWindow 仅构造不 show（纪律）。
"""

import re
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

import soundfile as sf

from acouscope.app.controller import AppController
from acouscope.app.project import ProjectManager
from acouscope.i18n import get_language, set_language, tr
from acouscope.ui import theme
from acouscope.ui.main_window import MainWindow
from acouscope.ui.widgets.batch_metadata_module import (
    MetadataBatchModule,
    module_name,
)
from acouscope.ui.widgets.batch_workspace import (
    BatchWorkspace,
    clear_modules,
    register_module,
    registered_modules,
)

# 禁词以拼接构造，避免模式字面量自身被扫中（同 test_batch_workspace.py 口径）。
_BANNED = "Mel" + "odyne"

_SRC = Path(__file__).resolve().parent.parent / "src" / "acouscope"
_MODULE_PY = _SRC / "ui" / "widgets" / "batch_metadata_module.py"

# 核对清单列序（与模块常量一致）
_COL_FILE, _COL_TITLE, _COL_TECH, _COL_SUMMARY, _COL_WARN = range(5)

# 本模块消费的 batch.meta.* 键（i18n 完整性验证）
_META_KEYS = [
    "batch.meta.module_name", "batch.meta.action", "batch.meta.step1",
    "batch.meta.step2", "batch.meta.step3", "batch.meta.prev",
    "batch.meta.next", "batch.meta.apply", "batch.meta.cancel",
    "batch.meta.scope_standard", "batch.meta.scope_summary",
    "batch.meta.scope_note", "batch.meta.common_title", "batch.meta.recorder",
    "batch.meta.date_placeholder", "batch.meta.date_range",
    "batch.meta.title_mode", "batch.meta.title_mode_file",
    "batch.meta.title_mode_prefix", "batch.meta.title_mode_manual",
    "batch.meta.prefix", "batch.meta.identifier_prefix",
    "batch.meta.id_prefix_placeholder", "batch.meta.identifier_hint",
    "batch.meta.tech_title", "batch.meta.tech_note", "batch.meta.step3_hint",
    "batch.meta.col_file", "batch.meta.col_title", "batch.meta.col_tech",
    "batch.meta.col_summary", "batch.meta.col_warn",
    "batch.meta.standard_label", "batch.meta.warn_creator",
    "batch.meta.blocked", "batch.meta.err_creator_required",
    "batch.meta.err_no_manager", "batch.meta.applied", "batch.meta.progress",
]

# 复用 T-912 检查器元数据区的键（两处文案逐字一致，禁双份维护）
_REUSED_KEYS = [
    "inspector.meta.std_dat", "inspector.meta.std_gbt", "inspector.meta.std_custom",
    "inspector.meta.desc_dat", "inspector.meta.desc_gbt", "inspector.meta.desc_custom",
    "inspector.meta.custom_note", "inspector.meta.creator", "inspector.meta.date",
    "inspector.meta.title", "inspector.meta.identifier", "inspector.meta.location",
    "inspector.meta.genre_context", "inspector.meta.actor_role",
]


def _write_wav(path, sr, seconds, freq=440.0):
    """写 PCM_16 单声道 wav（soundfile；合成可复现）。"""
    t = np.arange(int(sr * seconds)) / sr
    sf.write(str(path), 0.3 * np.sin(2 * np.pi * freq * t), sr, subtype="PCM_16")


@pytest.fixture()
def zh():
    """中文语境（断言中文文案；用毕还原）。"""
    prev = get_language()
    set_language("zh_CN")
    yield
    set_language(prev)


@pytest.fixture()
def wavs(tmp_path):
    """3 个技术参数不同的支持音频（a/c = 8k，b = 16k → 技术逐文件不串）。"""
    a = tmp_path / "tape_a.wav"
    b = tmp_path / "tape_b.wav"
    c = tmp_path / "tape_c.wav"
    _write_wav(a, 8000, 1.0)
    _write_wav(b, 16000, 2.0)
    _write_wav(c, 8000, 3.0)
    return a, b, c


@pytest.fixture()
def wired(qapp, zh, wavs):
    """框架 + 本模块（框架注入 ProjectManager）+ 3 文件装载并激活。"""
    clear_modules()
    manager = ProjectManager()
    ws = BatchWorkspace()
    ws.set_manager(manager)
    mod = register_module(MetadataBatchModule(ws))
    ws.refresh_modules()
    ws.set_files([str(p) for p in wavs])
    assert ws.activate(mod.name) is True
    yield ws, mod, manager, wavs
    ws.close()
    clear_modules()


def _by_name(ws) -> dict:
    """框架勾选路径 → {文件名: 绝对路径}。"""
    return {Path(p).name: p for p in ws.included_paths()}


# ---------------------------------------------------------------------------
# ① 范围与标准
# ---------------------------------------------------------------------------


class TestScopeStep:
    def test_scope_counts_new_and_archived(self, wired, zh):
        ws, mod, manager, wavs = wired
        # 3 伪音频全部未入档 → N=3 / 新登记 3 / 已入档 0
        assert mod.scope_summary_label.text() == tr(
            "batch.meta.scope_summary"
        ).format(n=3, new=3, archived=0)
        # 入档 1 个 → 新登记 2 / 已入档 1（入档判定走框架注入的 manager）
        manager.add_file(str(wavs[0]), label=wavs[0].name)
        mod.refresh()
        assert mod.scope_summary_label.text() == tr(
            "batch.meta.scope_summary"
        ).format(n=3, new=2, archived=1)

    def test_standard_combo_three_items_and_desc_switch(self, wired, zh):
        ws, mod, manager, wavs = wired
        combo = mod.standard_combo
        assert combo.count() == 3
        codes = [combo.itemData(i) for i in range(3)]
        assert codes == ["DAT63", "GBT31219.4", "custom"]
        # 说明区随下拉切换（文案照抄 i18n，含关键要点）
        combo.setCurrentIndex(0)
        assert "录音录像类电子档案元数据方案" in mod.desc_label.text()
        assert "四实体模式" in mod.desc_label.text()
        combo.setCurrentIndex(1)
        assert "图书馆馆藏资源数字化加工规范" in mod.desc_label.text()
        assert "人文描述字段" in mod.desc_label.text()
        combo.setCurrentIndex(2)
        assert "田野研究" in mod.desc_label.text()
        # 状态跟随（apply 落盘用）
        assert mod._standard_code() == "custom"

    def test_step_navigation_three_pages(self, wired, zh):
        ws, mod, manager, wavs = wired
        assert mod.stack.count() == 3
        assert mod.stack.currentIndex() == 0
        assert len(mod.step_chips) == 3
        assert mod.btn_prev.isEnabled() is False
        mod.btn_next.click()
        assert mod.stack.currentIndex() == 1
        assert mod.btn_prev.isEnabled() is True
        mod.btn_next.click()
        assert mod.stack.currentIndex() == 2
        assert mod.btn_next.isEnabled() is False
        mod.btn_prev.click()
        assert mod.stack.currentIndex() == 1


# ---------------------------------------------------------------------------
# ② 批量字段 → 应用（共同字段一次填写 + 技术逐文件自动）
# ---------------------------------------------------------------------------


class TestApplyCommonFields:
    def test_common_fields_applied_to_all_files(self, wired, zh):
        ws, mod, manager, wavs = wired
        mod.creator_edit.setText("传承人甲")
        mod.recorder_edit.setText("摄录者乙")
        mod.location_edit.setText("云南大理")
        mod.genre_edit.setText("白族民歌")
        mod.actor_role_edit.setText("领唱")
        mod.standard_combo.setCurrentIndex(0)  # DA/T 63-2017
        ws.run_active()
        by_name = _by_name(ws)
        for name, path in by_name.items():
            md = manager.get_file(path).metadata
            assert md["Creator"] == "传承人甲"
            assert md["Recorder"] == "摄录者乙"
            assert md["Location"] == "云南大理"
            assert md["GenreContext"] == "白族民歌"
            assert md["ActorRole"] == "领唱"
            assert md["_standard"] == "DAT63"
            assert md["Title"] == Path(name).stem
        # 标识符按规则含三位序号（逐文件不同）
        assert manager.get_file(by_name["tape_a.wav"]).metadata["Identifier"] == "ID-001"
        assert manager.get_file(by_name["tape_c.wav"]).metadata["Identifier"] == "ID-003"

    def test_technical_fields_per_file_not_crossed(self, wired, zh):
        ws, mod, manager, wavs = wired
        mod.creator_edit.setText("传承人甲")
        ws.run_active()
        by_name = _by_name(ws)
        md_a = manager.get_file(by_name["tape_a.wav"]).metadata
        md_b = manager.get_file(by_name["tape_b.wav"]).metadata
        # 逐文件自动提取且不串（a=8k/1s，b=16k/2s）
        assert md_a["SamplingRate"] == "8000"
        assert md_b["SamplingRate"] == "16000"
        assert md_a["SamplingRate"] != md_b["SamplingRate"]
        assert md_a["Duration"] == "00:00:01"
        assert md_b["Duration"] == "00:00:02"
        assert md_a["Format"] == md_b["Format"] == "WAV"
        assert md_a["Channels"] == "1"

    def test_registration_of_missing_entries(self, wired, zh):
        """无 ProjectFile 条目 → 应用时经框架 manager 登记（T-907 约束 1）。"""
        ws, mod, manager, wavs = wired
        assert manager.get_file(str(wavs[0])) is None
        mod.creator_edit.setText("传承人甲")
        ws.run_active()
        for p in ws.included_paths():
            assert manager.get_file(p) is not None

    def test_result_report_contract(self, wired, zh):
        """返回形状 [{"path","ok","reason"}] → 框架 _fmt_result 逐文件报告 N 成功。"""
        ws, mod, manager, wavs = wired
        mod.creator_edit.setText("传承人甲")
        ws.run_active()
        paths = ws.included_paths()
        assert len(mod._last_results) == 3
        assert all(set(r) >= {"path", "ok", "reason"} for r in mod._last_results)
        assert [r["path"] for r in mod._last_results] == paths
        assert ws.results_list.count() == len(paths)
        ok = tr("batch.result_ok")
        assert ws.results_list.item(0).text() == f"{ok} {paths[0]}"


# ---------------------------------------------------------------------------
# ③ 题名（默认/前缀/留空兜底）
# ---------------------------------------------------------------------------


class TestTitleModes:
    def test_default_title_is_file_stem(self, wired, zh):
        ws, mod, manager, wavs = wired
        mod.creator_edit.setText("传承人甲")
        mod._goto(2)
        assert mod.review_table.item(0, _COL_TITLE).text() == wavs[0].stem
        ws.run_active()
        by_name = _by_name(ws)
        assert manager.get_file(by_name["tape_b.wav"]).metadata["Title"] == "tape_b"

    def test_prefix_mode_and_blank_fallback(self, wired, zh):
        ws, mod, manager, wavs = wired
        mod.creator_edit.setText("传承人丙")
        mod.title_mode_combo.setCurrentIndex(1)  # 统一前缀 + 文件名
        assert mod.prefix_edit.isEnabled() is True
        mod.prefix_edit.setText("田野_")
        mod._goto(2)
        assert mod.review_table.item(0, _COL_TITLE).text() == f"田野_{wavs[0].stem}"
        # 逐行微调清空 → 回退文件名（兜底，不留空题名）
        mod.review_table.item(0, _COL_TITLE).setText("")
        ws.run_active()
        paths = ws.included_paths()
        assert manager.get_file(paths[0]).metadata["Title"] == wavs[0].stem
        assert manager.get_file(paths[1]).metadata["Title"] == f"田野_{wavs[1].stem}"

    def test_manual_mode_override_used(self, wired, zh):
        ws, mod, manager, wavs = wired
        mod.creator_edit.setText("传承人丙")
        mod.title_mode_combo.setCurrentIndex(2)  # 逐条编辑
        mod._goto(2)
        mod.review_table.item(1, _COL_TITLE).setText("白族民歌·第三段")
        ws.run_active()
        paths = ws.included_paths()
        assert manager.get_file(paths[1]).metadata["Title"] == "白族民歌·第三段"


# ---------------------------------------------------------------------------
# ④ 必填拦截（责任者）
# ---------------------------------------------------------------------------


class TestRequiredCreator:
    def test_apply_blocks_when_creator_missing(self, wired, zh):
        ws, mod, manager, wavs = wired
        ws.run_active()
        # 未登记任何条目、未写任何 metadata
        for p in ws.included_paths():
            assert manager.get_file(p) is None
        assert all(r["ok"] is False for r in mod._last_results)
        assert all(r["reason"] == tr("batch.meta.err_creator_required")
                   for r in mod._last_results)
        assert ws.results_list.item(0).text().startswith(tr("batch.result_fail"))

    def test_review_warns_missing_creator(self, wired, zh):
        ws, mod, manager, wavs = wired
        mod._goto(2)
        warn = mod.review_table.item(0, _COL_WARN)
        assert warn.text() == tr("batch.meta.warn_creator")
        # 必填缺失高亮（语义色令牌，非硬编码 hex）
        assert warn.foreground().color().name().lower() == theme.TOKENS["semantic"]["error"]
        mod.creator_edit.setText("传承人甲")
        mod._goto(2)
        assert mod.review_table.item(0, _COL_WARN).text() == "—"

    def test_apply_button_blocks_and_stays(self, wired, zh):
        ws, mod, manager, wavs = wired
        got = []
        ws.exitRequested.connect(lambda: got.append(1))
        mod.btn_apply.click()
        assert got == []                      # 拦截：不退出
        assert mod.stack.currentIndex() == 1  # 回第 2 步补填
        assert mod.warn_label.text() == tr("batch.meta.blocked")
        assert mod._last_results == []

    def test_apply_button_runs_and_exits(self, wired, zh):
        ws, mod, manager, wavs = wired
        mod.creator_edit.setText("传承人丁")
        got = []
        ws.exitRequested.connect(lambda: got.append(1))
        mod.btn_apply.click()
        assert got == [1]                     # 框架回常规页
        assert mod.status_label.text() == tr("batch.meta.applied").format(ok=3, fail=0)
        assert ws.results_list.count() == 3

    def test_cancel_button_exits_without_writing(self, wired, zh):
        ws, mod, manager, wavs = wired
        mod.creator_edit.setText("传承人甲")
        got = []
        ws.exitRequested.connect(lambda: got.append(1))
        mod.btn_cancel.click()
        assert got == [1]
        for p in ws.included_paths():
            assert manager.get_file(p) is None  # 取消不改动


# ---------------------------------------------------------------------------
# ⑤ 核对清单（大表格）
# ---------------------------------------------------------------------------


class TestReviewTable:
    def test_review_rows_summary_and_readonly(self, wired, zh):
        ws, mod, manager, wavs = wired
        mod.creator_edit.setText("传承人戊")
        mod.standard_combo.setCurrentIndex(0)
        mod._goto(2)
        assert mod.review_table.rowCount() == 3
        # 每行最终摘要含题名/责任者/标准代码
        summary = mod.review_table.item(0, _COL_SUMMARY).text()
        assert "传承人戊" in summary
        assert "DAT63" in summary
        assert tr("inspector.meta.title") in summary
        # 技术列只读、题名列可编辑
        assert not (mod.review_table.item(0, _COL_TECH).flags()
                    & Qt.ItemFlag.ItemIsEditable)
        assert mod.review_table.item(0, _COL_TITLE).flags() & Qt.ItemFlag.ItemIsEditable
        # 文件名列绑定绝对路径（逐行微调定位用）
        bound = mod.review_table.item(0, _COL_FILE).data(Qt.ItemDataRole.UserRole)
        assert bound in ws.included_paths()
        # 技术列逐文件显示各自采样率（不串）
        assert "8000" in mod.review_table.item(0, _COL_TECH).text()
        assert "16000" in mod.review_table.item(1, _COL_TECH).text()

    def test_review_refresh_tracks_fileset(self, wired, zh):
        ws, mod, manager, wavs = wired
        mod._goto(2)
        assert mod.review_table.rowCount() == 3
        ws.set_files([str(wavs[0])])
        mod.refresh()
        assert mod.review_table.rowCount() == 1


# ---------------------------------------------------------------------------
# ⑥ 无 manager 兜底
# ---------------------------------------------------------------------------


class TestApplyWithoutManager:
    def test_apply_without_manager_reports_failure(self, qapp, wavs, zh):
        host = QWidget()
        mod = MetadataBatchModule()
        mod.build_config_ui(host)
        mod.creator_edit.setText("传承人己")
        progress = []
        results = mod.apply([str(wavs[0])], None, progress.append)
        assert results == [{
            "path": str(wavs[0]),
            "ok": False,
            "reason": tr("batch.meta.err_no_manager"),
        }]
        host.close()


# ---------------------------------------------------------------------------
# ⑦ 框架集成 + MainWindow 接线
# ---------------------------------------------------------------------------


class TestFrameworkIntegration:
    def test_module_registered_and_activatable(self, qapp, zh, wavs):
        clear_modules()
        ws = BatchWorkspace()
        try:
            mod = register_module(MetadataBatchModule(ws))
            ws.refresh_modules()
            assert [m.name for m in registered_modules()] == [mod.name]
            assert ws.nav_list.count() == 1
            assert ws.nav_list.item(0).text() == mod.name
            assert ws.current_module() is None
            ws.set_files([str(p) for p in wavs])
            assert ws.activate(mod.name) is True
            assert ws.current_module() is mod
            assert ws.btn_run.isEnabled() is True
            assert ws.param_host.findChild(QWidget, "metaBatchConfig") is not None
        finally:
            ws.close()
            clear_modules()

    def test_module_name_is_translated(self, zh):
        assert module_name() == "批量更改元数据"
        assert tr("batch.meta.action") == "批量更改元数据…"


@pytest.fixture()
def window(qapp, zh, monkeypatch, tmp_path):
    """离屏 MainWindow（不 show）；teardown close。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    w = MainWindow(AppController())
    yield w
    w.close()


class TestMainWindowWiring:
    def test_context_action_enters_and_activates(self, window, qapp, tmp_path):
        w = window
        a = tmp_path / "entry_a.wav"
        b = tmp_path / "entry_b.wav"
        _write_wav(a, 8000, 0.5)
        _write_wav(b, 16000, 0.5)
        w.file_browser.set_current_file(str(a))
        w.file_browser._select_paths([str(Path(str(a)).resolve()),
                                      str(Path(str(b)).resolve())])
        qapp.processEvents()
        actions = w.file_browser._extra_actions
        assert len(actions) == 1
        assert actions[0].text() == tr("batch.meta.action")
        # 无参回调（addContextAction 内部已吞掉 Qt checked 入参）
        actions[0].trigger()
        qapp.processEvents()
        assert w.central_stack.currentIndex() == 1
        assert w.batch_workspace.current_module() is w.batch_metadata_module
        assert sorted(Path(p).name for p in w.batch_workspace.included_paths()) == [
            "entry_a.wav", "entry_b.wav",
        ]

    def test_framework_entry_still_activates_nothing(self, window, qapp, tmp_path):
        """回归护栏：框架级「批处理…」入口行为零变化（仅切页、不激活模块）。"""
        w = window
        a = tmp_path / "plain.wav"
        _write_wav(a, 8000, 0.5)
        w.file_browser.batchRequested.emit([str(a)])
        qapp.processEvents()
        assert w.central_stack.currentIndex() == 1
        assert w.batch_workspace.current_module() is None

    def test_batch_requested_signal_path_unchanged(self, window, qapp, tmp_path):
        """_open_batch_workspace 新增可选 module_name 后，单参调用仍兼容。"""
        w = window
        a = tmp_path / "one.wav"
        _write_wav(a, 8000, 0.5)
        w._open_batch_workspace([str(a)])
        qapp.processEvents()
        assert w.central_stack.currentIndex() == 1
        assert w.batch_workspace.included_paths() == [str(a)]
        assert w.batch_workspace.current_module() is None


# ---------------------------------------------------------------------------
# ⑧ 合规（i18n / 禁词 / 禁硬编码样式）
# ---------------------------------------------------------------------------


class TestCompliance:
    def test_i18n_keys_three_languages(self):
        from acouscope.i18n import _STRINGS

        for key in _META_KEYS + _REUSED_KEYS:
            entry = _STRINGS[key]
            assert entry["en_US"].strip(), key
            assert entry["zh_CN"].strip(), key
            assert entry["zh_TW"].strip(), key

    def test_banned_word_zero_hits(self):
        for f in (_MODULE_PY, Path(__file__)):
            assert _BANNED not in f.read_text(encoding="utf-8")

    def test_no_hardcoded_hex_or_px(self):
        text = _MODULE_PY.read_text(encoding="utf-8")
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", text), "禁硬编码颜色"
        assert not re.search(r"\b\d+(\.\d+)?px\b", text), "禁硬编码像素"

    def test_no_second_signal_path(self):
        """入口激活沿用既有 batchRequested（不新增并行信号，勿双发）。"""
        text = (_SRC / "ui" / "main_window.py").read_text(encoding="utf-8")
        assert "batchModuleRequested" not in text
