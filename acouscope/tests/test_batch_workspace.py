# SPDX-License-Identifier: GPL-3.0-only
"""T-913 批处理工作区框架测试。

覆盖任务书 Step 4 要求：
① 注册表：register / registered / activate（fake 模块）；激活后参数宿主装入其
   config_ui；同名覆盖；类型/空名校验；clear_modules。
② 空态：无模块时导航显示空态提示、无业务 UI、执行钮禁用。
③ 文件集区：增（去重）/删/勾选/全选；入档状态（已入档/新登记）显示。
④ 执行：run_active 调 active.apply(files, params, progress_cb) 并把结果写入
   报告区；模块异常不崩框架；无模块 → 空操作；[退出] → exitRequested。
⑤ main_window 接线：central_stack 四页（index0 常规 / index1 批处理 / index2 房间模态 / index3 房间声学，T-1054b3）；
   batchRequested → 进入 index1 并预载文件集；[退出] → 回 index0。
另：i18n batch.* 键三语齐全；禁词 0 命中；不构造主窗口、不 show（纪律措辞）。

口径：离屏独立构造（qapp fixture）。MainWindow 测试仅构造不显示窗口。
"""

from pathlib import Path

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QLabel,
    QVBoxLayout,
    QWidget,
)

from acouscope.app.controller import AppController
from acouscope.i18n import tr
from acouscope.ui.main_window import MainWindow
from acouscope.ui.widgets.batch_workspace import (
    BaseBatchModule,
    BatchWorkspace,
    activate_module,
    clear_modules,
    register_module,
    registered_modules,
)

# 禁词以拼接构造，避免模式字面量自身被扫中（同 test_file_browser.py 口径）。
_BANNED = "Mel" + "odyne"

_BATCH_PY = (
    Path(__file__).resolve().parent.parent
    / "src" / "acouscope" / "ui" / "widgets" / "batch_workspace.py"
)

# 本模块消费的 batch.* 键（i18n 完整性验证）
_BATCH_KEYS = [
    "batch.title", "batch.exit", "batch.nav_title", "batch.nav_empty",
    "batch.files_title", "batch.files_empty", "batch.files_add",
    "batch.files_remove", "batch.files_check_all", "batch.status_archived",
    "batch.status_new", "batch.param_title", "batch.param_empty",
    "batch.progress_title", "batch.run", "batch.run_done", "batch.run_error",
    "batch.result_ok", "batch.result_fail",
]


class _FakeModule(BaseBatchModule):
    """测试 fake 模块：config_ui objectName 可寻；apply 记录调用并回逐文件结果。"""

    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.apply_calls: list[list[str]] = []
        self.params_seen: list = []
        self.progress = []
        self.raise_on_apply: Exception | None = None

    def build_config_ui(self, parent: QWidget) -> QWidget:
        w = QWidget(parent)
        w.setObjectName("fakeCfg_" + self.name)
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel(self.name + " cfg", w))
        return w

    def apply(self, files, params, progress_cb):
        self.apply_calls.append(list(files))
        self.params_seen.append(params)
        self.progress.append("applying " + self.name)
        progress_cb("progress " + self.name)
        if self.raise_on_apply is not None:
            raise self.raise_on_apply
        return [{"path": p, "ok": True} for p in files]


class _FakeManager:
    """伪 ProjectManager：仅实现 BatchWorkspace 消费的 get_file。"""

    def __init__(self, archived: list[str] | None = None):
        self._archived = set(archived or [])

    def get_file(self, path):
        return object() if str(path) in self._archived else None


@pytest.fixture()
def workspace(qapp):
    """注册表清空 + 全新 BatchWorkspace（测试隔离）。"""
    clear_modules()
    w = BatchWorkspace()
    yield w
    w.close()
    clear_modules()


def _register(name: str) -> _FakeModule:
    mod = _FakeModule(name)
    register_module(mod)
    return mod


def _paths(*names: str):
    return [str(Path(__file__).parent / n) for n in names]


# ---------------------------------------------------------------------------
# ① 注册表
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_register_and_list_order(self):
        clear_modules()
        try:
            _register("aa")
            _register("bb")
            assert [m.name for m in registered_modules()] == ["aa", "bb"]
        finally:
            clear_modules()

    def test_same_name_register_overwrites_keeps_order(self):
        clear_modules()
        try:
            _register("aa")
            mod2 = _register("aa")
            mods = registered_modules()
            assert len(mods) == 1
            assert mods[0] is mod2
        finally:
            clear_modules()

    def test_register_validation(self):
        clear_modules()
        try:
            with pytest.raises(TypeError):
                register_module(object())  # type: ignore[arg-type]
            empty = _FakeModule("")
            with pytest.raises(ValueError):
                register_module(empty)
        finally:
            clear_modules()

    def test_activate_returns_module_and_unknown_none(self):
        clear_modules()
        try:
            mod = _register("aa")
            assert activate_module("aa") is mod
            assert activate_module("nope") is None
        finally:
            clear_modules()

    def test_clear_modules(self):
        clear_modules()
        _register("aa")
        assert registered_modules()
        clear_modules()
        assert registered_modules() == []


# ---------------------------------------------------------------------------
# ② 空态（无模块时无业务 UI）
# ---------------------------------------------------------------------------


class TestEmptyState:
    def test_empty_nav_hint_and_no_business_ui(self, workspace):
        ws = workspace
        assert ws.nav_list.count() == 0
        assert not ws.nav_list.isVisibleTo(ws)
        assert ws.lbl_nav_empty.isVisibleTo(ws)
        assert ws.lbl_nav_empty.text() == tr("batch.nav_empty")
        # 无激活模块：参数宿主为空态提示，执行钮禁用
        assert ws.current_module() is None
        assert ws.lbl_param_empty.isVisibleTo(ws)
        assert ws.lbl_param_empty.text() == tr("batch.param_empty")
        assert ws.btn_run.isEnabled() is False
        # 文件集区空态
        assert ws.file_list.count() == 0
        assert ws.lbl_files_empty.isVisibleTo(ws)
        assert ws.lbl_files_empty.text() == tr("batch.files_empty")

    def test_run_no_module_is_noop(self, workspace):
        ws = workspace
        ws.run_active()
        assert ws.results_list.count() == 0


# ---------------------------------------------------------------------------
# 导航 ↔ 激活 ↔ 参数宿主
# ---------------------------------------------------------------------------


class TestNavigationAndActivation:
    def test_refresh_lists_registered(self, workspace):
        _register("aa")
        _register("bb")
        workspace.refresh_modules()
        ws = workspace
        assert ws.nav_list.count() == 2
        assert [ws.nav_list.item(i).text() for i in range(2)] == ["aa", "bb"]
        assert ws.nav_list.isVisibleTo(ws)

    def test_nav_click_activates_and_mounts_config(self, workspace):
        mod = _register("aa")
        workspace.refresh_modules()
        ws = workspace
        ws.nav_list.itemClicked.emit(ws.nav_list.item(0))
        assert ws.current_module() is mod
        assert ws.btn_run.isEnabled() is True
        found = ws.param_host.findChildren(QWidget, "fakeCfg_aa")
        assert len(found) == 1
        assert found[0].parent() is ws.param_host
        assert not ws.lbl_param_empty.isVisibleTo(ws)

    def test_activate_by_name_true_and_loads(self, workspace):
        mod = _register("aa")
        workspace.refresh_modules()
        ws = workspace
        assert ws.activate("aa") is True
        assert ws.current_module() is mod
        assert len(ws.param_host.findChildren(QWidget, "fakeCfg_aa")) == 1

    def test_activate_unknown_false_keeps_empty_host(self, workspace):
        ws = workspace
        assert ws.activate("nope") is False
        assert ws.current_module() is None
        assert ws.lbl_param_empty.isVisibleTo(ws)
        assert ws.btn_run.isEnabled() is False

    def test_activate_switch_module_remounts_host(self, workspace):
        _register("aa")
        _register("bb")
        workspace.refresh_modules()
        ws = workspace
        ws.activate("aa")
        ws.activate("bb")
        assert len(ws.param_host.findChildren(QWidget, "fakeCfg_aa")) == 0
        assert len(ws.param_host.findChildren(QWidget, "fakeCfg_bb")) == 1

    def test_cleared_registry_reverts_to_empty(self, workspace):
        _register("aa")
        workspace.refresh_modules()
        ws = workspace
        ws.activate("aa")
        assert ws.current_module() is not None
        clear_modules()
        ws.refresh_modules()
        assert ws.current_module() is None
        assert ws.nav_list.count() == 0
        assert ws.lbl_param_empty.isVisibleTo(ws)
        assert ws.btn_run.isEnabled() is False


# ---------------------------------------------------------------------------
# ③ 待处理文件集区
# ---------------------------------------------------------------------------


class TestFileSet:
    def test_set_files_preloads_checked(self, workspace):
        paths = _paths("a.wav", "b.wav")
        workspace.set_files(paths)
        ws = workspace
        assert ws.file_list.count() == 2
        assert ws.included_paths() == paths
        assert not ws.lbl_files_empty.isVisibleTo(ws)
        for i in range(2):
            assert ws.file_list.item(i).checkState() == Qt.CheckState.Checked

    def test_add_paths_dedup(self, workspace):
        paths = _paths("a.wav", "b.wav")
        workspace.add_paths(paths[:1])
        workspace.add_paths(paths)  # a 重复 + b 新
        workspace.add_paths([])
        assert workspace.file_list.count() == 2
        assert workspace.included_paths() == paths

    def test_remove_selected(self, workspace):
        paths = _paths("a.wav", "b.wav", "c.wav")
        workspace.set_files(paths)
        ws = workspace
        ws.file_list.setCurrentRow(1)  # b
        ws.remove_selected()
        assert ws.included_paths() == [paths[0], paths[2]]

    def test_uncheck_excludes_and_check_all_restores(self, workspace):
        paths = _paths("a.wav", "b.wav")
        workspace.set_files(paths)
        ws = workspace
        ws.file_list.item(1).setCheckState(Qt.CheckState.Unchecked)
        assert ws.included_paths() == [paths[0]]
        ws.btn_check_all.click()
        assert ws.included_paths() == paths

    def test_status_tags_archived_vs_new(self, workspace):
        paths = _paths("a.wav", "b.wav")
        workspace.set_files(paths)
        ws = workspace
        ws.set_manager(_FakeManager(archived=[paths[0]]))
        assert tr("batch.status_archived") in ws.file_list.item(0).text()
        assert tr("batch.status_new") in ws.file_list.item(1).text()
        assert ws.file_list.item(0).data(Qt.ItemDataRole.UserRole) == paths[0]


# ---------------------------------------------------------------------------
# ④ 执行与结果报告
# ---------------------------------------------------------------------------


class TestRunAndResults:
    def test_run_active_applies_module(self, workspace):
        mod = _register("aa")
        paths = _paths("a.wav", "b.wav")
        workspace.refresh_modules()
        ws = workspace
        ws.set_files(paths)
        ws.activate("aa")
        ws.btn_run.click()
        assert mod.apply_calls == [paths]
        # params = 模块 config_ui（宿主内同名控件即该对象）
        assert mod.params_seen == [ws._config_ui]
        assert ws.results_list.count() == len(paths)
        ok = tr("batch.result_ok")
        assert ws.results_list.item(0).text() == f"{ok} {paths[0]}"
        assert ws.lbl_progress.text() == tr("batch.run_done").format(n=2)

    def test_run_module_error_does_not_crash(self, workspace):
        mod = _register("aa")
        mod.raise_on_apply = ValueError("boom")
        workspace.refresh_modules()
        ws = workspace
        ws.set_files(_paths("a.wav"))
        ws.activate("aa")
        ws.run_active()
        assert ws.results_list.count() == 1
        assert tr("batch.run_error") in ws.results_list.item(0).text()
        assert "boom" in ws.results_list.item(0).text()
        assert ws.btn_run.isEnabled() is True


class TestExitSignal:
    def test_exit_button_emits_exit_requested(self, workspace):
        got = []
        workspace.exitRequested.connect(lambda: got.append(1))
        workspace.btn_exit.click()
        assert got == [1]


# ---------------------------------------------------------------------------
# ⑤ main_window 中央接线（离屏构造、不显示窗口）
# ---------------------------------------------------------------------------


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """离屏 MainWindow（不 show）；teardown close。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    w = MainWindow(AppController())
    yield w
    w.close()


class TestCentralWiring:
    def test_batch_entry_preloads_and_exit_returns(self, window, qapp, tmp_path):
        w = window
        a = tmp_path / "a.wav"
        a.write_bytes(b"")
        stack = w.central_stack
        # central_stack 五页：index0 常规 / index1 批处理 / index2 房间模态 / index3 房间声学 /
        # index4 图表设计器（T-1054a）
        assert stack.count() == 6
        assert stack.currentIndex() == 0
        assert stack.widget(1) is w.batch_workspace
        # 框架级入口：FileBrowser.batchRequested（右键「批处理…」所发）
        # → 进入 index1 并预载文件集（菜单级覆盖见 test_file_browser.py）
        w.file_browser.batchRequested.emit([str(a)])
        qapp.processEvents()
        assert stack.currentIndex() == 1
        assert stack.currentWidget() is w.batch_workspace
        assert w.batch_workspace.included_paths() == [str(a)]
        # [退出] → 回常规页 index0（波形随整页恢复）
        w.batch_workspace.btn_exit.click()
        qapp.processEvents()
        assert stack.currentIndex() == 0
        assert stack.currentWidget() is stack.widget(0)

    def test_reentry_switches_fileset(self, window, qapp, tmp_path):
        """再次进入批处理：文件集整体替换为新的右键目标集。"""
        w = window
        a = tmp_path / "a.wav"
        b = tmp_path / "b.wav"
        a.write_bytes(b"")
        b.write_bytes(b"")
        w.file_browser.batchRequested.emit([str(a)])
        qapp.processEvents()
        w.file_browser.batchRequested.emit([str(b), str(a)])
        qapp.processEvents()
        assert w.central_stack.currentIndex() == 1
        assert w.batch_workspace.included_paths() == [str(b), str(a)]


# ---------------------------------------------------------------------------
# i18n / 禁词 / 纪律
# ---------------------------------------------------------------------------


class TestCompliance:
    def test_batch_i18n_keys_complete(self):
        from acouscope.i18n import _STRINGS

        for key in _BATCH_KEYS:
            entry = _STRINGS[key]
            assert entry["en_US"].strip()
            assert entry["zh_CN"].strip()
            assert entry["zh_TW"].strip()

    def test_banned_word_zero_hits(self):
        for f in (_BATCH_PY, Path(__file__)):
            assert _BANNED not in f.read_text(encoding="utf-8")
