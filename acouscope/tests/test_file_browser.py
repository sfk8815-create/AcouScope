# SPDX-License-Identifier: GPL-3.0-only
"""T-910 文件管理器（FileBrowser）测试。

覆盖任务书 Step 3 全部要求：
① 目录含支持(.wav) + 不支持(.txt/.png/.acouproj) → 黑/灰判定正确；
② 有项目（伪 manager.filepath）→ 显示其 parent 目录；无项目回退当前文件目录；
③ 单选 → fileSelected 恰一次；多选 → selectionChanged(paths) 正确；
④ 双击/回车 → fileActivated；
⑤ addContextAction 追加项出现在右键菜单（可触发）；「批处理…」enabled、
  触发 → batchRequested(paths)（T-913 框架级入口）；
⑥ remove_file 经菜单触发（伪 manager 验证调用）。
另：入档 "✓" 标识、refresh 保留选中、空态、禁词 0 命中。
另（T-1071·IM-26 β）：右键目标 ≡ 扩展点 slot ≡ 批处理目标（三向一致守卫）。

口径：离屏独立构造（qapp fixture），禁 MainWindow.show()；
右键菜单经 monkeypatch QMenu.exec 捕获（不跑嵌套事件循环）。
"""

from pathlib import Path

import pytest
from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtGui import QColor, QKeyEvent
from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QMenu

from acouscope.i18n import tr
from acouscope.ui import theme
from acouscope.ui.widgets.file_browser import FileBrowser

# 禁词以拼接构造，避免模式字面量自身被扫中（同 test_project_new_dialog.py 口径）。
_BANNED = "Mel" + "odyne"

_BROWSER_PY = (
    Path(__file__).resolve().parent.parent
    / "src" / "acouscope" / "ui" / "widgets" / "file_browser.py"
)


class FakeManager:
    """伪 ProjectManager：仅实现 FileBrowser 消费的 filepath/get_file/remove_file。"""

    def __init__(self, filepath=None):
        self.filepath = Path(filepath) if filepath is not None else None
        self._files: set[str] = set()
        self.removed: list[str] = []

    def add(self, path) -> None:
        self._files.add(str(path))

    def get_file(self, path):
        return object() if str(path) in self._files else None

    def remove_file(self, path) -> bool:
        if str(path) in self._files:
            self._files.discard(str(path))
            self.removed.append(str(path))
            return True
        return False


@pytest.fixture()
def files_dir(tmp_path):
    """伪项目目录：支持(.wav) + 不支持(.txt/.png/.acouproj) + 子目录（不应列出）。"""
    d = tmp_path / "projdir"
    d.mkdir()
    (d / "a.wav").write_bytes(b"")
    (d / "b.txt").write_text("x")
    (d / "c.png").write_bytes(b"")
    (d / "proj.acouproj").write_text("{}")
    sub = d / "subdir"
    sub.mkdir()
    (sub / "d.wav").write_bytes(b"")  # 子目录内文件：本任务不列（T-915 候选）
    return d


@pytest.fixture()
def browser(qapp, files_dir):
    """有项目（伪 manager.filepath 指向 files_dir）的离屏 FileBrowser。"""
    mgr = FakeManager(files_dir / "proj.acouproj")
    b = FileBrowser(manager=mgr)
    b.list.resize(400, 300)  # 离屏下保证 rectOfItem 有效（右键菜单测试用）
    yield b
    b.close()


@pytest.fixture()
def capture_menu(monkeypatch):
    """捕获 QMenu.exec：记录菜单本体、不跑嵌套事件循环。"""
    captured: dict = {}

    def fake_exec(self, *args, **kwargs):
        captured["menu"] = self
        return None

    monkeypatch.setattr(QMenu, "exec", fake_exec)
    return captured


def open_menu(browser, index: int, capture_menu) -> QMenu:
    """对第 index 项发右键（先选中该项），返回捕获到的菜单。"""
    item = browser.list.item(index)
    browser.list.clearSelection()
    item.setSelected(True)
    rect = browser.list.rectForIndex(browser.list.indexFromItem(item))
    browser._on_context_menu(QPoint(rect.center()))
    return capture_menu["menu"]


def paths_of(browser) -> list[str]:
    return [browser.list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(browser.list.count())]


def right_click(browser, index: int, capture_menu) -> QMenu:
    """对第 index 项发右键（**不改选中态**：用于「右键未选中项」构造）。"""
    item = browser.list.item(index)
    rect = browser.list.rectForIndex(browser.list.indexFromItem(item))
    browser._on_context_menu(QPoint(rect.center()))
    return capture_menu["menu"]


def three_way_reads(browser, index: int, capture_menu) -> dict:
    """右键第 index 项并触发各入口 → 三向读数 builtin/extension/batch（+ selected）。"""
    opened: list[str] = []
    slots: list[list[str]] = []
    batches: list[list[str]] = []
    browser.fileActivated.connect(opened.append)
    browser.addContextAction("T-1071 探针",
                             lambda: slots.append(browser.selected_paths()))
    browser.batchRequested.connect(lambda p: batches.append(list(p)))
    menu = right_click(browser, index, capture_menu)
    next(a for a in menu.actions() if a.text() == tr("file_browser.open")).trigger()
    next(a for a in menu.actions() if a.text() == "T-1071 探针").trigger()
    next(a for a in menu.actions() if a.text() == tr("file_browser.batch")).trigger()
    return {
        "builtin": opened,           # 「打开」→ fileActivated(paths[0])：内建即时 paths 口径
        "extension": slots[-1],      # 扩展点 slot 触发时自读 selected_paths()
        "batch": batches[-1],        # batchRequested(paths)
        "selected": browser.selected_paths(),
    }


class TestDirectoryRule:
    def test_project_dir_shown(self, browser):
        """② 有项目 → 显示 .acouproj 所在目录（本目录文件平铺）。"""
        names = sorted(Path(p).name for p in paths_of(browser))
        assert names == ["a.wav", "b.txt", "c.png", "proj.acouproj"]

    def test_subdir_not_listed(self, browser):
        """子目录不列行（T-915 候选）：subdir/d.wav 不出现在列表。"""
        names = [Path(p).name for p in paths_of(browser)]
        assert "d.wav" not in names
        assert "subdir" not in names

    def test_fallback_current_file_dir(self, qapp, files_dir):
        """② 无项目但打开过音频 → 回退该音频所在目录。"""
        b = FileBrowser(manager=None, current_file=files_dir / "a.wav")
        try:
            names = sorted(Path(p).name for p in paths_of(b))
            assert names == ["a.wav", "b.txt", "c.png", "proj.acouproj"]
        finally:
            b.close()

    def test_empty_state(self, qapp):
        """② 两者皆无 → 空态提示（列表隐藏、提示可见）。"""
        b = FileBrowser()
        try:
            assert b.list.count() == 0
            assert not b.list.isVisibleTo(b)
            assert b._lbl_empty.text() == tr("file_browser.empty")
            assert b._lbl_empty.isVisibleTo(b)
        finally:
            b.close()

    def test_set_manager_switches_dir(self, qapp, files_dir, tmp_path):
        """set_manager 更新目录源后 refresh 切换显示。"""
        other = tmp_path / "other"
        other.mkdir()
        (other / "x.wav").write_bytes(b"")
        b = FileBrowser(manager=None, current_file=other / "x.wav")
        try:
            assert [Path(p).name for p in paths_of(b)] == ["x.wav"]
            b.set_manager(FakeManager(files_dir / "proj.acouproj"))
            names = sorted(Path(p).name for p in paths_of(b))
            assert names == ["a.wav", "b.txt", "c.png", "proj.acouproj"]
        finally:
            b.close()


class TestSupportedColors:
    def test_supported_normal_color(self, browser):
        """① 支持格式（.wav）→ 正文色（colors()['text']）。"""
        c = theme.colors()
        item = browser.list.item(0)  # a.wav（排序首位）
        assert item.data(Qt.ItemDataRole.UserRole + 1) is True
        assert item.foreground().color() == QColor(c["text"])

    def test_unsupported_gray(self, browser):
        """① 不支持（.txt/.png/.acouproj）→ 次级灰（colors()['sub']）。"""
        c = theme.colors()
        for i in range(1, browser.list.count()):
            item = browser.list.item(i)
            assert item.data(Qt.ItemDataRole.UserRole + 1) is False
            assert item.foreground().color() == QColor(c["sub"])

    def test_theme_switch_recolors(self, browser, monkeypatch):
        """主题变化 → 逐 item 前景色随角色重刷（不真实切全局主题，打桩 colors()）。"""
        light = dict(theme.THEMES["light"])
        monkeypatch.setattr(theme, "colors", lambda: light)
        browser._refresh_style()
        assert browser.list.item(0).foreground().color() == QColor(light["text"])
        assert browser.list.item(1).foreground().color() == QColor(light["sub"])


class TestSelectionSignals:
    def test_single_click_file_selected_once(self, browser):
        """③ 点选单个 → fileSelected 恰一次（路径正确）。"""
        got: list[str] = []
        browser.fileSelected.connect(got.append)
        browser.list.itemClicked.emit(browser.list.item(0))
        assert got == [paths_of(browser)[0]]

    def test_multi_select_selection_changed(self, browser):
        """③ 多选 → selectionChanged(paths) 为全部选中路径（列表顺序）。"""
        got: list[list[str]] = []
        browser.selectionChanged.connect(lambda p: got.append(list(p)))
        all_paths = paths_of(browser)
        browser.list.item(0).setSelected(True)
        browser.list.item(2).setSelected(True)
        assert got[-1] == [all_paths[0], all_paths[2]]
        assert browser.selected_paths() == [all_paths[0], all_paths[2]]

    def test_double_click_activated(self, browser):
        """④ 双击 → fileActivated（路径正确）。"""
        got: list[str] = []
        browser.fileActivated.connect(got.append)
        browser.list.itemDoubleClicked.emit(browser.list.item(1))
        assert got == [paths_of(browser)[1]]

    def test_enter_key_activated(self, browser):
        """④ 回车 → fileActivated（当前项）。"""
        got: list[str] = []
        browser.fileActivated.connect(got.append)
        browser.list.setCurrentRow(2)
        ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                       Qt.KeyboardModifier.NoModifier)
        browser.keyPressEvent(ev)
        assert got == [paths_of(browser)[2]]


class TestContextMenu:
    def test_menu_items_present(self, browser, capture_menu):
        """⑤ 右键含常规项：打开 / 在 Finder 显示 / 从项目移除 / 「批处理…」占位。"""
        menu = open_menu(browser, 0, capture_menu)
        texts = [a.text() for a in menu.actions()]
        assert tr("file_browser.open") in texts
        assert tr("file_browser.reveal") in texts
        assert tr("file_browser.remove") in texts
        assert tr("file_browser.batch") in texts

    def test_batch_entry_wired_and_emits_request(self, browser, capture_menu):
        """⑤ 「批处理…」（T-913 框架级入口）enabled，触发 → batchRequested(右键目标集)。"""
        got: list[list[str]] = []
        browser.batchRequested.connect(lambda p: got.append(list(p)))
        menu = open_menu(browser, 0, capture_menu)
        batch = next(a for a in menu.actions() if a.text() == tr("file_browser.batch"))
        assert batch.isEnabled() is True
        batch.trigger()
        assert got == [[paths_of(browser)[0]]]

    def test_remove_enabled_only_when_in_project(self, browser, capture_menu):
        """⑥ 「从项目移除」仅已入档可用（伪 manager 判定）。"""
        menu = open_menu(browser, 0, capture_menu)  # a.wav 未入档
        remove = next(a for a in menu.actions() if a.text() == tr("file_browser.remove"))
        assert remove.isEnabled() is False
        browser._manager.add(paths_of(browser)[0])  # a.wav 入档
        menu = open_menu(browser, 0, capture_menu)
        remove = next(a for a in menu.actions() if a.text() == tr("file_browser.remove"))
        assert remove.isEnabled() is True

    def test_remove_triggers_manager(self, browser, capture_menu):
        """⑥ 触发「从项目移除」→ manager.remove_file(path) 被调 + 重列。"""
        all_paths = paths_of(browser)
        browser._manager.add(all_paths[0])
        menu = open_menu(browser, 0, capture_menu)
        remove = next(a for a in menu.actions() if a.text() == tr("file_browser.remove"))
        remove.trigger()
        assert browser._manager.removed == [all_paths[0]]
        # 重列后 a.wav 仍在目录（只移出项目），但 "✓" 标识消失
        names = [browser.list.item(i).text() for i in range(browser.list.count())]
        assert "a.wav" in names

    def test_open_action_emits_activated(self, browser, capture_menu):
        """右键「打开」→ fileActivated（接线方据此调 controller.open_file）。"""
        got: list[str] = []
        browser.fileActivated.connect(got.append)
        menu = open_menu(browser, 1, capture_menu)
        act = next(a for a in menu.actions() if a.text() == tr("file_browser.open"))
        act.trigger()
        assert got == [paths_of(browser)[1]]

    def test_add_context_action(self, browser, capture_menu):
        """⑤ addContextAction 扩展点：追加项出现在菜单且可触发。"""
        calls: list[str] = []
        browser.addContextAction("T-914 测试项", lambda: calls.append("hit"))
        menu = open_menu(browser, 0, capture_menu)
        texts = [a.text() for a in menu.actions()]
        assert "T-914 测试项" in texts
        act = next(a for a in menu.actions() if a.text() == "T-914 测试项")
        act.trigger()
        assert calls == ["hit"]


class TestContextMenuTargetAlignment:
    """IM-26（T-1071 β）：右键目标 ≡ 扩展点 slot 目标 ≡ 批处理目标。"""

    def test_right_click_unselected_item_three_way_aligned(self, browser, capture_menu):
        """核心：多选 {A,B} 下右键**未选中** C → 归一为 [C]，三向逐字相等。"""
        all_paths = paths_of(browser)
        browser.list.item(0).setSelected(True)
        browser.list.item(1).setSelected(True)
        assert browser.selected_paths() == [all_paths[0], all_paths[1]]  # 前置：旧多选 {A,B}
        r = three_way_reads(browser, 2, capture_menu)
        assert r["builtin"] == [all_paths[2]]
        assert r["extension"] == [all_paths[2]]
        assert r["batch"] == [all_paths[2]]
        assert r["selected"] == [all_paths[2]]
        assert r["builtin"] == r["extension"] == r["batch"]  # 三向一致

    def test_right_click_within_multi_selection_not_degraded(self, browser, capture_menu):
        """负例：多选 {A,B} 内右键 A（已选中）→ 不归一、保持 [A,B]。"""
        all_paths = paths_of(browser)
        browser.list.item(0).setSelected(True)
        browser.list.item(2).setSelected(True)
        r = three_way_reads(browser, 0, capture_menu)
        assert r["selected"] == [all_paths[0], all_paths[2]]
        assert r["extension"] == [all_paths[0], all_paths[2]]
        assert r["batch"] == [all_paths[0], all_paths[2]]

    def test_strip_beta_reproduces_mismatch(self, browser, capture_menu, monkeypatch):
        """反证有牙（仿 T-1069 R-6）：剥 β → 三向错位复现、守卫 1 必 FAIL。"""
        all_paths = paths_of(browser)
        browser.list.item(0).setSelected(True)
        browser.list.item(1).setSelected(True)
        # 剥 β：归一两步（clearSelection + setSelected）同时失效 ⇒ 选中集与即时 paths 分叉
        monkeypatch.setattr(QListWidget, "clearSelection", lambda self: None)
        monkeypatch.setattr(QListWidgetItem, "setSelected", lambda self, sel: None)
        r = three_way_reads(browser, 2, capture_menu)
        assert r["builtin"] == [all_paths[2]]                                    # 内建：右键项 C
        assert r["batch"] == [all_paths[2]]                                      # 批处理：右键项 C
        assert r["extension"] == [all_paths[0], all_paths[1]]                    # 扩展点：旧多选
        assert r["selected"] == [all_paths[0], all_paths[1]]
        with pytest.raises(AssertionError):
            assert r["builtin"] == r["extension"] == r["batch"]  # 守卫 1 于此必 FAIL


class TestInProjectMark:
    def test_mark_added_for_registered(self, browser):
        """入档标识：已入 Project.files → 文件名尾 "✓"；未入档不加。"""
        all_paths = paths_of(browser)
        browser._manager.add(all_paths[0])
        browser.refresh()
        texts = [browser.list.item(i).text() for i in range(browser.list.count())]
        assert "a.wav  ✓" in texts
        assert "b.txt" in texts  # 未入档无角标

    def test_no_manager_no_mark(self, qapp, files_dir):
        """无 manager → 不加任何角标。"""
        b = FileBrowser(manager=None, current_file=files_dir / "a.wav")
        try:
            texts = [b.list.item(i).text() for i in range(b.list.count())]
            assert all("✓" not in t for t in texts)
        finally:
            b.close()


class TestRefreshKeepsSelection:
    def test_refresh_preserves_selection(self, browser):
        """refresh 重列后尽力保留选中（按路径匹配）。"""
        all_paths = paths_of(browser)
        browser.list.item(0).setSelected(True)
        browser.refresh()
        assert browser.selected_paths() == [all_paths[0]]

    def test_refresh_relists_new_files(self, browser, files_dir):
        """目录新增文件后 refresh 可见。"""
        (files_dir / "new.flac").write_bytes(b"")
        browser.refresh()
        names = [Path(p).name for p in paths_of(browser)]
        assert "new.flac" in names
        # .flac 为支持格式 → 正文色
        c = theme.colors()
        idx = names.index("new.flac")
        assert browser.list.item(idx).foreground().color() == QColor(c["text"])


class TestBannedWord:
    def test_banned_word_zero_hits(self):
        """禁词（The Pitch Grid 文档文件名首段品牌词）0 命中。"""
        for f in (_BROWSER_PY, Path(__file__)):
            assert _BANNED not in f.read_text(encoding="utf-8")
