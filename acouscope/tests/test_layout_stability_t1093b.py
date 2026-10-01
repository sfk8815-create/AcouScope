# SPDX-License-Identifier: GPL-3.0-only
"""T-1093 M-B/M-C 主窗布局稳定性守卫测（B-2 抖动·全离屏，禁 MainWindow.show()）。

M-B 根因（§〇-bis）：`central_stack` 是 QStackedWidget，其 `minimumSizeHint` 恒取
**全页并集最大**（实测 836×578·高 578 来自图表设计器页），未封顶时任一页的自然
min 高都顶住中央 splitter 可用高 ⇒ 切页顶高波形/分析区分界 = 抖动。
修法：`_wrap_room_page`（wrapper 侧）+ index1 各 `setMinimumSize(0, 200)`
（口径同 `_add_analysis_widget`），**不改 room_modes 本体（R-5）·不换骨架（R-2）**。

M-C：① `build_workspace_splitter` 给中央栏 `setStretchFactor(1, 1)`，窗口增减宽
全部由中央吸收、两侧栏不被无端牵动（★ Qt6 无 stretchFactor getter ⇒ 行为化判据）；
② `splitterMoved → 落盘` 改尾部合并（150ms 单发 QTimer·仅 main_window 接线层）。

★ PI-T84 口径：N-3 判据改「封页 1-4 后 stack.msh 随页切换恒定 且 height ≤435
（==index0 自然值）」，反证「撤封顶 → 578」；N-2 禁锚绝对窗宽（窗 msh 被显式
`setMinimumSize(1000,700)` 锁死、对封顶不敏感，离屏不可复现 1510）；N-6 debounce
禁沉入 `workspace.save_workspace` 本体；「窗体抖不抖」的视觉终判归 N5（真机）。
"""

import os

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt

from acouscope.app.controller import AppController

CAP_MIN_H = 200          # 全铺页封顶地板（产品码同值）
CAPPED_STACK_MIN_H = 435  # 封顶后 stack 级 min 高 == index0 自然值
UNION_STACK_MIN_H = 578   # 撤封顶后的并集高（反证基准）


@pytest.fixture(scope="module")
def window(qapp, tmp_path_factory):
    """离屏 MainWindow（构造 ~10s ⇒ 模块级复用；不 show）+ HOME/数据目录隔离。"""
    from acouscope.i18n import set_language
    from acouscope.ui.main_window import MainWindow
    import acouscope.utils.config as _cfg

    tmp = tmp_path_factory.mktemp("t1093b")
    old_home = os.environ.get("HOME")
    old_data_dir = _cfg.get_data_dir
    os.environ["HOME"] = str(tmp)
    _cfg.get_data_dir = lambda: tmp
    set_language("zh_CN")

    controller = AppController()
    sr = 8000
    t = np.arange(sr) / sr
    controller.load_from_array(0.4 * np.sin(2 * np.pi * 440 * t), sr)
    w = MainWindow(controller)
    yield w
    w.close()
    _cfg.get_data_dir = old_data_dir
    if old_home is not None:
        os.environ["HOME"] = old_home


def _stack_min_h_by_page(window, qapp) -> list:
    """逐页 setCurrentIndex 后读 stack 级 minimumSizeHint 高（切页稳定性实测）。"""
    st = window.central_stack
    heights = []
    for i in range(st.count()):
        st.setCurrentIndex(i)
        qapp.processEvents()
        heights.append(st.minimumSizeHint().height())
    st.setCurrentIndex(0)
    qapp.processEvents()
    return heights


# ----------------------------------------------------------------------
# ① 封顶落地：页 1-4 各 minSize(0, 200)
# ----------------------------------------------------------------------


def test_full_pages_are_capped_at_floor(window):
    st = window.central_stack
    assert st.count() == 6, f"中央页数与令文口径（1+5 全铺页）不符: {st.count()}"
    for i in range(1, st.count()):
        page = st.widget(i)
        assert page.minimumSize().width() == 0, f"index{i} 封顶宽度应不限"
        assert page.minimumSize().height() == CAP_MIN_H, (
            f"index{i} 未封顶（{page.minimumSize().height()}）"
        )


# ----------------------------------------------------------------------
# ② 核心数值判据（PI-T84 N-3）：切页恒定 且 ≤435（==index0 自然值）
# ----------------------------------------------------------------------


def test_stack_minimum_height_is_constant_across_pages_and_capped(window, qapp):
    heights = _stack_min_h_by_page(window, qapp)
    assert len(set(heights)) == 1, f"stack 级 min 高随页变化 = 抖动源未消: {heights}"
    assert heights[0] <= CAPPED_STACK_MIN_H, f"min 高未被压到 index0 自然值: {heights}"
    assert heights == [CAPPED_STACK_MIN_H] * 6


def test_stack_min_height_equals_regular_page_natural_value(window):
    """封顶后 stack 地板 == index0（常规页）自然值 ⇒ 隐藏页不再撑大。"""
    natural = window.central_stack.widget(0).minimumSizeHint().height()
    assert window.central_stack.minimumSizeHint().height() == natural


# ----------------------------------------------------------------------
# ③ 反证：撤封顶 → 并集高 578（隐藏页重新撑大 stack）
# ----------------------------------------------------------------------


def test_counter_evidence_uncap_restores_union_minimum(window, qapp):
    st = window.central_stack
    saved = {i: st.widget(i).minimumSize() for i in range(1, st.count())}
    try:
        for i in range(1, st.count()):
            st.widget(i).setMinimumSize(0, 0)
        heights = _stack_min_h_by_page(window, qapp)
        assert heights[0] == UNION_STACK_MIN_H, (
            f"撤封顶后应回到并集高 {UNION_STACK_MIN_H}，实测 {heights}"
        )
        assert heights[0] > CAPPED_STACK_MIN_H
    finally:
        for i, size in saved.items():
            st.widget(i).setMinimumSize(size)
        qapp.processEvents()
    assert _stack_min_h_by_page(window, qapp) == [CAPPED_STACK_MIN_H] * 6


# ----------------------------------------------------------------------
# ④ R-5/R-2 边界：封顶只在 wrapper 侧，页内容自然 hint 与骨架不变
# ----------------------------------------------------------------------


def test_cap_lives_on_wrapper_not_on_page_content(window):
    """房间模态页：wrapper min 被压到 200，其自身自然 hint 未动（room_modes 零改动）。"""
    page = window.room_modes_page
    inner = page.layout().itemAt(0).widget()
    assert type(inner).__name__ == "RoomModesWidget"
    assert page.minimumSize().height() == CAP_MIN_H
    assert page.minimumSizeHint().height() >= 500, (
        f"页自然 hint 被改动（{page.minimumSizeHint().height()}）⇒ 疑触碰页本体"
    )
    assert inner.minimumSize().height() == 0, "RoomModesWidget 本体被设了 min（违 R-5）"


def test_central_stack_skeleton_unchanged(window):
    """R-2：未换骨架——central_stack 仍是 QStackedWidget、五页构成不变。"""
    from PyQt6.QtWidgets import QSplitter, QStackedWidget

    from acouscope.ui.widgets.batch_workspace import BatchWorkspace
    from acouscope.ui.widgets.room_modes import RoomModesWidget

    st = window.central_stack
    assert isinstance(st, QStackedWidget)
    assert isinstance(st.widget(0), QSplitter), "index0 仍是垂直 splitter（未换骨架）"
    assert st.widget(0).orientation() == Qt.Orientation.Vertical
    assert isinstance(st.widget(1), BatchWorkspace)
    assert isinstance(st.widget(2).layout().itemAt(0).widget(), RoomModesWidget)
    assert st.widget(3) is window.room_acoustics_page
    assert st.widget(4) is window.chart_designer_page


# ----------------------------------------------------------------------
# ⑤ M-C-a：中央栏吸收全部富余宽（`setStretchFactor(1, 1)`）
#    ★ Qt6 QSplitter 无 stretchFactor() getter ⇒ 行为化判据：改 host 宽看增量落点。
# ----------------------------------------------------------------------


@pytest.fixture
def make_ws(qapp, tmp_path):
    """工厂夹具：按需搭裸三栏 workspace（左收起 / 双侧展开）+ show 的极小 host。"""
    from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

    from acouscope.ui.widgets.panels.workspace import (
        build_workspace_splitter,
        restore_workspace,
    )

    created = []

    def _make(both_expanded=False):
        state = build_workspace_splitter(QLabel("center"))
        state["left"].set_content(QLabel("L" * 60))
        state["right"].set_content(QLabel("R" * 60))
        restore_workspace(state, path=tmp_path / "missing.json")
        if both_expanded:
            state["left"].set_collapsed(False)
        host = QWidget()
        host.resize(1300, 600)
        lay = QHBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(state["splitter"])
        host.show()
        qapp.processEvents()
        state["host"] = host
        created.append(state)
        return state

    yield _make
    for state in created:
        state["host"].close()


def _grow_host(qapp, host, splitter, extra=400):
    before = list(splitter.sizes())
    host.resize(host.width() + extra, host.height())
    qapp.processEvents()
    return before, list(splitter.sizes())


@pytest.mark.parametrize("both_expanded", [False, True])
def test_window_growth_goes_to_center_only(qapp, make_ws, both_expanded):
    """宿主变宽 400px → 增量全落中央栏，左右栏分毫不动（无 stretch 时被摊走）。"""
    ws = make_ws(both_expanded=both_expanded)
    before, after = _grow_host(qapp, ws["host"], ws["splitter"])
    assert after[1] - before[1] == 400, f"中央栏未吸收全部增量: {before}->{after}"
    assert after[0] == before[0] and after[2] == before[2], (
        f"侧栏被牵动（抖动放大源）: {before}->{after}"
    )


def test_counter_evidence_without_stretch_side_panels_move(qapp, make_ws):
    """反证：双侧展开 + 把中央 stretch 归零（等价未施工）→ 中央不再独吞增量、侧栏被无端牵动。"""
    ws = make_ws(both_expanded=True)
    sp = ws["splitter"]
    sp.setStretchFactor(1, 0)  # 撤销产品码设定，复刻修复前分布
    before, after = _grow_host(qapp, ws["host"], sp)
    assert after[1] - before[1] < 400, (
        f"未 stretch 时中央竟仍独吞全部增量: {before}->{after} ⇒ 反证前提失效"
    )
    assert (after[0] - before[0]) > 0 or (after[2] - before[2]) > 0, (
        f"侧栏未被牵动，本反证无判别力: {before}->{after}"
    )


# ----------------------------------------------------------------------
# ⑥ M-C-b：splitterMoved 落盘 debounce（★ N-6：只在接线层）
# ----------------------------------------------------------------------


class _DumpCounter:
    """只替 `workspace` 模块内的 json 引用计 dump 次数，其余属性委派真 json。"""

    def __init__(self, real):
        self._real = real
        self.dumps = 0

    def dump(self, *args, **kwargs):
        self.dumps += 1
        return self._real.dump(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


def _spin(qapp, msec):
    from PyQt6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.setInterval(msec)
    timer.timeout.connect(loop.quit)
    timer.start()
    loop.exec()


@pytest.fixture
def dump_counter(monkeypatch):
    import json

    from acouscope.ui.widgets.panels import workspace as workspace_mod

    counter = _DumpCounter(json)
    monkeypatch.setattr(workspace_mod, "json", counter)
    return counter


def test_splitter_moved_burst_persists_once(window, qapp, dump_counter):
    """拖 N 像素（20 次 splitterMoved）→ 落盘 ≤1 次：拖拽期 0 次、停手后恰好 1 次。"""
    sp = window.ws_splitter
    dump_counter.dumps = 0
    for k in range(20):
        sp.splitterMoved.emit(k, 1)
    assert dump_counter.dumps == 0, (
        "splitterMoved 逐像素同步落盘 = 卡顿源未消除（或 json 计数装置失效）"
    )
    _spin(qapp, 600)
    assert dump_counter.dumps == 1, (
        f"尾部合并失效：20 次拖拽事件落盘 {dump_counter.dumps} 次"
    )


def test_counter_evidence_undebiounced_burst_would_write_every_pixel(
    window, qapp, dump_counter
):
    """反证：同一信号按修复前的直连方式接一次 → 20 像素 = 20 次 dump（装置有牙）。"""
    from acouscope.ui.widgets.panels.workspace import save_workspace

    sp = window.ws_splitter
    window._ws_layout_save_timer.stop()  # 不让产品侧 debounce 混进本测计数
    dump_counter.dumps = 0
    slot = lambda *_: save_workspace(window._ws_state)  # noqa: E731 — 复刻旧直连
    sp.splitterMoved.connect(slot)
    try:
        for k in range(20):
            sp.splitterMoved.emit(k, 1)
    finally:
        sp.splitterMoved.disconnect(slot)
        window._ws_layout_save_timer.stop()
    assert dump_counter.dumps == 20, (
        f"未节流应逐次落盘，实测 {dump_counter.dumps} ⇒ 计数装置失效"
    )


def test_debounce_lives_in_wiring_not_in_save_workspace(qapp, dump_counter, tmp_path):
    """N-6 边界：`workspace.save_workspace` 本体仍同步落盘（未授权档 test_workspace.py 依赖）。"""
    from PyQt6.QtWidgets import QLabel

    from acouscope.ui.widgets.panels.workspace import (
        build_workspace_splitter,
        save_workspace,
    )

    ws = build_workspace_splitter(QLabel("center"))
    target = tmp_path / "ui_layout.json"
    dump_counter.dumps = 0
    save_workspace(ws, path=target)
    assert dump_counter.dumps == 1, "save_workspace 本体被节流 = 越界（违 N-6）"
    assert target.exists()


def test_save_timer_is_parented_and_single_shot(window):
    """定时器父=主窗（随窗体析构·无悬垂回调）且单发（合并一次拖拽）。"""
    timer = window._ws_layout_save_timer
    assert timer.parent() is window
    assert timer.isSingleShot()
    assert timer.interval() > 0


def test_close_flushes_pending_layout_save_without_waiting(window, qapp, dump_counter):
    """退出补存：拖完立刻关窗不得丢末次布局，且补存后定时器已停不重复落盘。"""
    window.ws_splitter.splitterMoved.emit(5, 1)
    assert dump_counter.dumps == 0, "停手前不应落盘"
    window.close()
    flushed = dump_counter.dumps
    assert flushed >= 1, "closeEvent 未补存末次布局（debounce 丢盘）"
    _spin(qapp, 600)
    assert dump_counter.dumps == flushed, "补存后定时器未 stop → 重复落盘"
