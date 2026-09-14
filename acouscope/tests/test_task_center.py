# SPDX-License-Identifier: GPL-3.0-only
"""T-928：非模态「任务进度中心」回归测试。

覆盖：
① 调度层：FIFO 串行（并发 1）/ 排队上限拒绝 / 可置顶 / 取消（排队 + 运行中）/
   失败终态 / 进度单调且不伪造 / 完成历史上限 / 耗时可测 / 外部任务生命周期；
② 面板层：四态（空态 / 进行中 / 排队 / 完成历史）+ 折叠 toggle + 进度呈现模式；
③ 主窗接线：分析入口经 TaskCenter 提交、下载取消-回退链语义保留、批处理聚合桥接、
   状态栏 toggle 显隐与计数；
④ 静态纪律：禁词 0 / 无 QDialog / 无硬编码 hex·px / 图标名不新增 /
   权威常量与 Settings 两处口径一致。

离屏环境：构造窗口但不显示窗体（本文件不出现主窗显示的调用字面量）；
线程类断言一律「后台线程 + 主线程 processEvents 收敛」，不做固定 sleep 判定。
"""

import ast
import json
import re
import threading
import time
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QDialog, QProgressBar, QPushButton, QWidget

from acouscope.app.controller import AppController
from acouscope.i18n import tr
from acouscope.ui import theme
from acouscope.ui.main_window import MainWindow
from acouscope.ui.widgets.batch_workspace import (
    BaseBatchModule,
    BatchWorkspace,
    clear_modules,
    register_module,
    registered_modules,
)
from acouscope.ui.widgets.task_center import (
    KIND_ANALYSIS,
    KIND_BATCH,
    PROGRESS_DETERMINATE,
    PROGRESS_INDETERMINATE,
    PROGRESS_TEXT,
    STATE_CANCELLED,
    STATE_DONE,
    STATE_FAILED,
    STATE_RUNNING,
    TASK_CENTER_MAX_CONCURRENCY,
    TASK_CENTER_PANEL_WIDTH,
    TASK_CENTER_QUEUE_LIMIT,
    TaskCenter,
    TaskCenterPanel,
    format_duration,
)
from acouscope.utils.config import Settings

_SRC = Path(__file__).resolve().parent.parent / "src" / "acouscope"
_TC_PY = _SRC / "ui" / "widgets" / "task_center.py"
_MW_PY = _SRC / "ui" / "main_window.py"
_BW_PY = _SRC / "ui" / "widgets" / "batch_workspace.py"
_I18N_PY = _SRC / "i18n" / "__init__.py"

# 禁词以拼接构造，避免模式字面量自身被扫中（同 test_batch_workspace.py 口径）。
_BANNED = "Mel" + "odyne"

_SR = 8000
_DURATION = 1.0


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _wait_until(predicate, timeout_ms: int = 4000) -> bool:
    """后台线程收敛：主线程 processEvents 直到谓词成立或超时。"""
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if predicate():
            return True
        QApplication.processEvents()
        time.sleep(0.005)
    return bool(predicate())


class _ReporterStub:
    """同步替身：仅记录 stage 调用（供同步提交点断言用）。"""

    def __init__(self):
        self.stages = []

    def stage(self, text):
        self.stages.append(text)

    def progress(self, value):  # pragma: no cover — 本替身不用于确定式任务
        pass


def _blocker(gate):
    """协作式阻塞任务：轮询 gate 与取消请求（有界，禁无限阻塞留悬挂线程）。"""

    def _run(reporter):
        for _ in range(800):
            if gate.is_set() or reporter.cancelled:
                return "released"
            time.sleep(0.01)
        return "timeout"

    return _run


def _drain(center, timeout_ms: int = 6000) -> bool:
    """等待调度中心归零（收尾用，防测试结束时仍有线程在跑）。"""
    return _wait_until(lambda: not center.is_busy(), timeout_ms)


def _raise_oserror(*_args, **_kwargs):
    """固定抛 OSError（T-1040 静默路径断言用）。"""
    raise OSError("denied")


@pytest.fixture()
def window(qapp, monkeypatch, tmp_path):
    """离屏主窗（已载合成音频；不显示窗体，绕开付费门控）。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    controller = AppController()
    t = np.arange(int(_SR * _DURATION)) / _SR
    controller.load_from_array(0.5 * np.sin(2 * np.pi * 440.0 * t), _SR)
    w = MainWindow(controller)
    yield w
    w.close()


class _FakeModule(BaseBatchModule):
    """批处理 fake 模块（观察者事件断言用）。"""

    def __init__(self, name: str, raise_on_apply=None):
        super().__init__()
        self.name = name
        self._raise = raise_on_apply

    def build_config_ui(self, parent: QWidget) -> QWidget:
        w = QWidget(parent)
        w.setObjectName("fakeCfg_" + self.name)
        return w

    def apply(self, files, params, progress_cb):
        progress_cb("half")
        if self._raise is not None:
            raise self._raise
        return [{"path": p, "ok": True} for p in files]


# ---------------------------------------------------------------------------
# ① 调度层
# ---------------------------------------------------------------------------


class TestScheduler:
    def test_authoritative_constants_match_settings(self):
        """权威常量与 Settings 两处口径一致（裁定 F″）。"""
        s = Settings()
        assert TASK_CENTER_MAX_CONCURRENCY == s.task_center_max_concurrency == 1
        assert TASK_CENTER_QUEUE_LIMIT == s.task_center_queue_limit == 32
        center = TaskCenter()
        assert center.max_concurrency == s.task_center_max_concurrency
        assert center.queue_limit == s.task_center_queue_limit

    def test_invalid_center_options_fall_back_to_defaults(self):
        """非法/越界并发与上限回退默认值（与 Settings.load 同范式）。"""
        assert TaskCenter(max_concurrency=0).max_concurrency == 1
        assert TaskCenter(max_concurrency=99).max_concurrency == 1
        assert TaskCenter(max_concurrency="x").max_concurrency == 1
        assert TaskCenter(queue_limit=0).queue_limit == 32
        assert TaskCenter(queue_limit=9999).queue_limit == 32
        assert TaskCenter(max_concurrency=2).max_concurrency == 2

    def test_settings_load_clamps_task_center_fields(self, tmp_path):
        """Settings.load：越界/非法回退默认（两字段）。"""
        import json

        fp = tmp_path / "settings.json"
        fp.write_text(
            json.dumps(
                {"task_center_max_concurrency": 9, "task_center_queue_limit": -3}
            ),
            encoding="utf-8",
        )
        s = Settings.load(fp)
        assert s.task_center_max_concurrency == 1
        assert s.task_center_queue_limit == 32
        fp.write_text(
            json.dumps(
                {"task_center_max_concurrency": "bad", "task_center_queue_limit": None}
            ),
            encoding="utf-8",
        )
        s2 = Settings.load(fp)
        assert s2.task_center_max_concurrency == 1
        assert s2.task_center_queue_limit == 32
        fp.write_text(
            json.dumps(
                {"task_center_max_concurrency": 3, "task_center_queue_limit": 64}
            ),
            encoding="utf-8",
        )
        s3 = Settings.load(fp)
        assert s3.task_center_max_concurrency == 3
        assert s3.task_center_queue_limit == 64

    def test_fifo_serial_execution_order(self, qapp):
        """并发 1：任务按提交序串行执行（任何时刻只在跑一个）。"""
        center = TaskCenter()
        order = []
        peaks = []
        lock = threading.Lock()

        def run(tag):
            def _run(reporter):
                with lock:
                    order.append(tag)
                    _in_flight.add(tag)
                    peaks.append(len(_in_flight))
                time.sleep(0.02)
                with lock:
                    _in_flight.discard(tag)
                return tag

            return _run

        _in_flight = set()
        entries = [center.submit(f"t{i}", run(f"t{i}")) for i in range(3)]
        assert _wait_until(lambda: all(e.is_terminal() for e in entries))
        assert order == ["t0", "t1", "t2"], "FIFO 串行序"
        assert max(peaks) == 1, "并发上限 1：禁并行叠加"
        assert all(e.state == STATE_DONE for e in entries)
        assert all(e.elapsed() >= 0.0 for e in entries), "耗时字段可测（非负）"
        assert center.running_entries() == [] and center.queued_entries() == []

    def test_queue_limit_rejects_and_reports(self, qapp):
        """排队超上限 → 拒绝并发出 taskRejected（不静默丢弃）。"""
        gate = threading.Event()
        center = TaskCenter(queue_limit=2)
        rejected = []
        center.taskRejected.connect(rejected.append)
        try:
            first = center.submit("A", _blocker(gate))
            second = center.submit("B", lambda r: None)
            third = center.submit("C", lambda r: None)
            assert first is not None and second is not None and third is not None
            over = center.submit("D", lambda r: None)
            assert over is None, "超上限应拒绝"
            assert rejected == ["D"]
            assert len(center.queued_entries()) == 2
            assert center.active_count() == 3, "1 在跑 + 2 排队"
        finally:
            gate.set()
        assert _drain(center)

    def test_bump_moves_queued_task_to_front(self, qapp):
        """置顶：排队中的任务可被提到队首（FIFO 的显式例外）。"""
        gate = threading.Event()
        center = TaskCenter(queue_limit=4)
        try:
            first = center.submit("A", _blocker(gate))
            second = center.submit("B", lambda r: None)
            third = center.submit("C", lambda r: None)
            assert [e.task_id for e in center.queued_entries()] == [
                second.task_id,
                third.task_id,
            ]
            assert center.bump(third.task_id) is True
            assert [e.task_id for e in center.queued_entries()] == [
                third.task_id,
                second.task_id,
            ]
            assert center.bump(first.task_id) is False, "运行中任务不可置顶"
        finally:
            gate.set()
        assert _drain(center)

    def test_cancel_queued_task_never_runs(self, qapp):
        """取消排队任务：终态可辨（taskCancelled）且工作函数不执行。"""
        gate = threading.Event()
        center = TaskCenter(queue_limit=4)
        ran = []
        try:
            first = center.submit("A", _blocker(gate))
            second = center.submit("B", lambda r: ran.append("B"))
            assert center.active_count() == 2
            cancelled = []
            center.taskCancelled.connect(lambda e: cancelled.append(e.task_id))
            assert center.cancel(second.task_id) is True
            assert center.entry(second.task_id).state == STATE_CANCELLED
            assert cancelled == [second.task_id]
            assert center.cancel(second.task_id) is False, "已终态不可再取消"
        finally:
            gate.set()
        assert _wait_until(lambda: center.entry(first.task_id).is_terminal())
        assert _drain(center)
        assert ran == [], "被取消的排队任务不得执行"

    def test_cancel_running_cooperative_task(self, qapp):
        """取消运行中任务（协作式）：终态为已取消，结果作废。"""
        center = TaskCenter()
        started = threading.Event()

        def _run(reporter):
            started.set()
            for _ in range(400):
                if reporter.cancelled:
                    return "aborted"
                time.sleep(0.005)
            return "late"

        entry = center.submit("长任务", _run)
        assert started.wait(2.0)
        assert center.cancel(entry.task_id) is True
        assert _wait_until(lambda: entry.is_terminal())
        assert entry.state == STATE_CANCELLED
        assert center.history()[0].task_id == entry.task_id

    def test_failure_terminal_state_and_callback(self, qapp):
        """异常 → 失败终态 + on_fail 主线程回调（含错误文本）。"""
        center = TaskCenter()
        seen = []

        def _boom(reporter):
            raise ValueError("boom")

        entry = center.submit("失败任务", _boom, on_fail=seen.append)
        assert _wait_until(lambda: entry.is_terminal())
        assert entry.state == STATE_FAILED
        assert "boom" in entry.error
        assert seen and "boom" in seen[0]

    def test_progress_signal_is_monotonic_and_capped(self, qapp):
        """确定式进度：单调不减、封顶 100（禁伪造 / 禁回退）。"""
        center = TaskCenter()
        seen = []
        center.taskProgress.connect(lambda e, v: seen.append(v))

        def _run(reporter):
            reporter.progress(10)
            reporter.progress(4)      # 回退 → 忽略
            reporter.progress(150)    # 超界 → 封顶 100
            return None

        entry = center.submit("进度任务", _run)
        assert _wait_until(lambda: entry.is_terminal())
        assert seen == [10.0, 100.0]
        assert entry.progress == 100.0

    def test_history_limit_keeps_recent_only(self, qapp):
        """完成历史保留最近 N 条（默认 10；此处限 2）。"""
        center = TaskCenter(history_limit=2)
        ids = []
        for i in range(3):
            e = center.register(f"ext{i}")
            ids.append(e.task_id)
            center.finish(e.task_id, ok=True)
        assert [e.task_id for e in center.history()] == [ids[2], ids[1]]
        assert center.entry(ids[0]) is None, "被淘汰的历史条目应出注册表"

    def test_external_task_lifecycle_and_cancel_action(self, qapp):
        """外部任务：登记即进行中；取消触发 cancel_action 且终态为已取消。"""
        center = TaskCenter()
        called = []
        entry = center.register(
            "下载", cancellable=True, cancel_action=lambda: called.append(True)
        )
        assert entry.state == STATE_RUNNING
        center.set_stage(entry.task_id, "half")
        assert entry.stage == "half"
        center.set_progress(entry.task_id, 42)
        assert entry.progress == 42
        assert center.cancel(entry.task_id) is True
        assert entry.state == STATE_CANCELLED
        assert called == [True]
        # 幂等：取消后到达的完成信号不得改写终态
        center.finish(entry.task_id, ok=True)
        assert entry.state == STATE_CANCELLED

    def test_external_task_does_not_consume_queue_slot(self, qapp):
        """外部任务不占调度队列额度（并发/上限只约束调度任务）。"""
        center = TaskCenter(queue_limit=1)
        gate = threading.Event()
        ext = center.register("下载")
        assert center.queued_entries() == []
        try:
            first = center.submit("A", _blocker(gate))
            assert first is not None, "外部任务不应占用排队名额"
            assert center.active_count() == 2, "外部任务计入进行中（不含排队）"
            center.finish(ext.task_id, ok=True)
        finally:
            gate.set()
        assert _drain(center)

    def test_shutdown_cancels_queue_and_running(self, qapp):
        """关窗收尾：拒绝新任务 + 排队/在跑任务一律收敛为「已取消」。"""
        gate = threading.Event()
        center = TaskCenter(queue_limit=4)
        center.submit("A", _blocker(gate))
        queued = center.submit("B", lambda r: None)
        assert center.active_count() == 2
        center.shutdown(timeout_ms=2000)
        assert center.entry(queued.task_id).state == STATE_CANCELLED
        assert all(
            e.state == STATE_CANCELLED
            for e in center.history()
        ), "关窗后在跑任务亦收敛为已取消"
        assert center.running_entries() == []
        assert center.submit("C", lambda r: None) is None, "收尾后拒绝新任务"
        gate.set()  # 释放协作线程（线程已收尾，仅防残留）
        # 收尾后仍须把在途 finished 投递消费掉（不留跨测试的悬垂投递）
        assert _wait_until(lambda: not center._threads)  # noqa: SLF001 — 测试内窥探

    def test_format_duration_mm_ss(self):
        assert format_duration(0) == "00:00"
        assert format_duration(65) == "01:05"
        assert format_duration(-3) == "00:00"


# ---------------------------------------------------------------------------
# ② 面板层（四态 + 折叠 + 进度呈现口径）
# ---------------------------------------------------------------------------


class TestPanel:
    def test_empty_state_visible_and_text(self, qapp):
        """空态：文案存在且给出提示（禁空白面板）。"""
        host = QWidget()
        center = TaskCenter()
        panel = TaskCenterPanel(center, host)
        assert panel.empty_state_visible() is True
        assert panel.lbl_empty.text() == tr("task_center.empty")
        assert panel.lbl_empty.text().strip() != ""
        assert panel.lbl_empty_hint.text().strip() != ""
        assert panel.groups["running"].isHidden()
        assert panel.groups["history"].isHidden()

    def test_running_row_uses_indeterminate_busy_bar(self, qapp):
        """进行中：不定式 busy 条 + 阶段文本（分析任务无真实百分比）。"""
        host = QWidget()
        gate = threading.Event()
        center = TaskCenter()
        panel = TaskCenterPanel(center, host)
        try:
            entry = center.submit(
                "检测音高…", _blocker(gate), progress_mode=PROGRESS_INDETERMINATE
            )
            assert _wait_until(lambda: len(panel.rows("running")) == 1)
            row = panel.rows("running")[0]
            assert row.entry.task_id == entry.task_id
            assert isinstance(row.progress, QProgressBar)
            assert (row.progress.minimum(), row.progress.maximum()) == (0, 0), "不定式"
            assert row.btn_cancel is not None, "运行中任务应可取消"
        finally:
            gate.set()
        assert _drain(center)

    def test_queued_row_and_cancel_from_panel(self, qapp):
        """排队态：独立分组 + 面板取消按钮生效。"""
        host = QWidget()
        gate = threading.Event()
        center = TaskCenter(queue_limit=4)
        panel = TaskCenterPanel(center, host)
        try:
            first = center.submit("A", _blocker(gate))
            second = center.submit("B", lambda r: None)
            assert _wait_until(lambda: len(panel.rows("queued")) == 1)
            row = panel.rows("queued")[0]
            assert row.entry.task_id == second.task_id
            assert isinstance(row.btn_cancel, QPushButton)
            row.btn_cancel.click()
            assert center.entry(second.task_id).state == STATE_CANCELLED
        finally:
            gate.set()
        assert _wait_until(lambda: center.entry(first.task_id).is_terminal())
        assert _drain(center)

    def test_history_row_determinate_progress(self, qapp):
        """完成历史：终态文案 + 确定式进度条（真实数值）。"""
        host = QWidget()
        center = TaskCenter()
        panel = TaskCenterPanel(center, host)
        entry = center.register("下载", progress_mode=PROGRESS_DETERMINATE)
        center.set_progress(entry.task_id, 60)
        center.finish(entry.task_id, ok=True)
        assert _wait_until(lambda: len(panel.rows("history")) == 1)
        row = panel.rows("history")[0]
        assert row.lbl_state.text() == tr("task_center.state.done")
        assert row.progress is not None and row.progress.value() == 60
        assert row.btn_cancel is None, "终态行不给取消按钮"

    def test_failed_and_cancelled_history_states(self, qapp):
        """失败 / 已取消：终态可辨。"""
        host = QWidget()
        center = TaskCenter()
        panel = TaskCenterPanel(center, host)
        bad = center.submit("失败", lambda r: (_ for _ in ()).throw(RuntimeError("x")))
        assert _wait_until(lambda: bad.is_terminal())
        ext = center.register("外部")
        center.cancel(ext.task_id)
        texts = {row.entry.task_id: row.lbl_state.text() for row in panel.rows("history")}
        assert texts.get(bad.task_id) == tr("task_center.state.failed")
        assert texts.get(ext.task_id) == tr("task_center.state.cancelled")

    def test_collapse_toggle_hides_body_only(self, qapp):
        """折叠：仅隐藏主体，面板头保留；按钮状态同步。"""
        host = QWidget()
        panel = TaskCenterPanel(TaskCenter(), host)
        assert panel.is_collapsed() is False
        assert panel.body.isHidden() is False
        panel.btn_collapse.click()
        assert panel.is_collapsed() is True
        assert panel.body.isHidden() is True
        assert panel.header.isHidden() is False
        panel.set_collapsed(False)
        assert panel.body.isHidden() is False
        assert panel.btn_collapse.isChecked() is False

    def test_panel_has_no_modal_dialog(self, qapp):
        """面板层禁新建 QDialog / 禁模态 exec（非模态铁律；注释与文案不计）。"""
        tree = ast.parse(_TC_PY.read_text(encoding="utf-8"))
        uses = [
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id == "QDialog"
        ]
        attrs = [
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr == "QDialog"
        ]
        assert uses == [] and attrs == [], "新模块禁引用 QDialog"
        panel = TaskCenterPanel(TaskCenter())
        assert isinstance(panel, QWidget) and not isinstance(panel, QDialog)


# ---------------------------------------------------------------------------
# ③ 主窗接线
# ---------------------------------------------------------------------------


class TestMainWindowWiring:
    def test_status_bar_toggle_shows_and_hides_panel(self, window):
        """状态栏 toggle → 非模态面板显隐（不进侧栏；面板为 MainWindow 子件）。"""
        w = window
        assert w.btn_task_center.isCheckable()
        assert w._task_center_panel is None, "面板懒建（未触发前不存在）"
        w.btn_task_center.setChecked(True)
        panel = w._task_center_panel
        assert panel is not None
        assert panel.parent() is w, "面板为悬浮内联子件（非侧栏/非对话框）"
        assert not panel.isHidden()
        assert panel.width() == TASK_CENTER_PANEL_WIDTH
        assert panel.x() >= 0 and panel.y() >= 0
        # 离屏未显示的窗口不投递 resizeEvent → 显式触发贴靠后校验仍在窗内
        w.resize(w.width() - 40, w.height() - 30)
        w._position_task_center_panel()
        assert panel.x() + panel.width() <= w.width()
        assert panel.y() + panel.height() <= w.height()
        w.btn_task_center.setChecked(False)
        assert panel.isHidden()

    def test_toggle_text_tracks_active_count(self, window):
        """toggle 文案随「进行中 + 排队」计数（0 → 无计数）。"""
        w = window
        gate = threading.Event()
        base = w.btn_task_center.text()
        assert base == tr("task_center.toggle")
        try:
            entry = w.task_center.submit("A", _blocker(gate))
            assert _wait_until(lambda: w.btn_task_center.text() != base)
            assert "1" in w.btn_task_center.text()
        finally:
            gate.set()
        assert _wait_until(lambda: w.task_center.entry(entry.task_id).is_terminal())
        assert _drain(w.task_center)
        assert _wait_until(lambda: w.btn_task_center.text() == base)

    def test_analysis_async_submits_through_task_center(self, window):
        """分析入口经统一提交口（TaskCenter）提交，回调仍在主线程。"""
        w = window
        seen = {}
        done = []

        def _fake_submit(title, run, **kwargs):
            seen["title"] = title
            seen["kwargs"] = kwargs
            result = run(_ReporterStub())
            kwargs["on_done"](result)
            return None

        w.task_center.submit = _fake_submit
        w._run_analysis_async("检测音高...", lambda: 42, done.append, "音高检测失败")
        assert seen["title"] == "检测音高..."
        assert seen["kwargs"]["kind"] == KIND_ANALYSIS
        assert seen["kwargs"]["progress_mode"] == PROGRESS_INDETERMINATE
        assert done == [42]

    def test_analysis_async_real_center_delivers_result(self, window):
        """真实调度链：工作线程计算 → 主线程回调 → 完成历史落条。"""
        w = window
        done = []
        w._run_analysis_async("检测音高...", lambda: 7, done.append, "音高检测失败")
        assert _wait_until(lambda: done == [7])
        assert w.task_center.history()[0].state == STATE_DONE

    def test_analysis_failure_toasts_error_level(self, window, monkeypatch):
        """失败必 toast（error）且状态复位。"""
        w = window
        seen = []
        monkeypatch.setattr(
            "acouscope.ui.main_window.show_toast",
            lambda parent, msg, level="info": seen.append((msg, level)),
        )

        def _boom():
            raise RuntimeError("compute failed")

        w._run_analysis_async("检测音高...", _boom, lambda r: None, "音高检测失败")
        assert _wait_until(lambda: bool(seen))
        assert seen[0][1] == "error"
        assert "音高检测失败" in seen[0][0]
        assert w.lbl_status.text() == "就绪"

    def test_download_cancel_chain_preserved(self, window):
        """下载取消-回退链（T-304b/T-305b）语义保留 + 聚合条目收敛。"""
        w = window
        terminated = []

        class _FakeWorker:
            _finished = False

            def isRunning(self):  # noqa: N802 — 仿 QThread 接口
                return True

            def terminate(self):
                terminated.append(True)

        entry = w.task_center.register("下载", kind="download")
        w._download_task_id = entry.task_id
        w._cancel_sota_download(_FakeWorker())
        assert terminated == [True], "取消须终止下载线程"
        assert w._pitch_backend == "pYIN", "取消须回退 pYIN"
        assert entry.state == STATE_CANCELLED

    def test_download_handlers_update_task_entry(self, window):
        """下载进度/终态回调同步到聚合条目（真实字节进度留在内联面板）。"""
        w = window
        entry = w.task_center.register("下载", kind="download")
        w._download_task_id = entry.task_id
        w._on_download_progress(5, 10, "SwiftF0")
        assert "50%" in entry.stage
        w._on_download_done(False, "下载失败", "SwiftF0")
        assert entry.state == STATE_FAILED
        assert w._download_task_id is None

    def test_download_source_registers_task_without_double_bar(self):
        """下载入口静态口径：登记聚合条目（文本模式）+ 内联面板承载真实进度。"""
        body = _method_source(MainWindow, "_download_sota_model")
        assert "task_center.register" in body
        assert "PROGRESS_TEXT" in body
        assert "show_toast" in body, "面板不可见时的提交提示保留"
        assert "canceled.connect" in body, "取消链路保留"

    def test_batch_observer_wired_and_feeds_task_center(self, window):
        """批处理桥接：观察者已挂 + 事件驱动聚合条目（start/stage/finish）。"""
        w = window
        assert w.batch_workspace._task_observer is not None
        w._on_batch_task_event("start", {"n": 2, "module": "fake"})
        tid = w._batch_task_id
        entry = w.task_center.entry(tid)
        assert entry is not None
        assert entry.kind == KIND_BATCH
        assert entry.progress_mode == PROGRESS_TEXT, "批处理无可靠数值进度 → 不重复进度条"
        assert entry.cancellable is False, "同步执行无中断通道 → 不给无效取消按钮"
        w.batch_workspace._on_progress("2/2")  # 经真实观察者接线透传
        assert entry.stage == "2/2"
        w._on_batch_task_event("finish", {"ok": True, "error": ""})
        assert entry.state == STATE_DONE
        assert w._batch_task_id is None

    def test_batch_workspace_emits_observer_events(self, qapp):
        """BatchWorkspace 观察者事件：start / stage / finish（失败路径 ok=False）。"""
        preexisting = list(registered_modules())
        try:
            clear_modules()
            ws = BatchWorkspace()
            events = []
            ws.set_task_observer(lambda e, p: events.append((e, dict(p))))
            mod = _FakeModule("t928fake")
            register_module(mod)
            ws.refresh_modules()
            ws.set_files([str(Path(__file__).parent / "a.wav")])
            ws.activate("t928fake")
            ws.run_active()
            assert [e for e, _ in events] == ["start", "stage", "finish"]
            assert events[0][1]["n"] == 1
            assert events[2][1]["ok"] is True
            # 失败路径：finish 事件 ok=False + 错误文本（既有结果区行为不变）
            events.clear()
            mod2 = _FakeModule("t928bad", raise_on_apply=ValueError("nope"))
            register_module(mod2)
            ws.refresh_modules()
            ws.activate("t928bad")
            ws.run_active()
            assert events[-1][0] == "finish" and events[-1][1]["ok"] is False
            assert "nope" in events[-1][1]["error"]
            ws.close()
        finally:
            clear_modules()
            for m in preexisting:
                register_module(m)

    def test_batch_observer_none_keeps_legacy_behavior(self, qapp):
        """观察者为 None：批处理既有行为零变化（事件不产生、结果区照旧）。"""
        preexisting = list(registered_modules())
        try:
            clear_modules()
            ws = BatchWorkspace()
            mod = _FakeModule("t928plain")
            register_module(mod)
            ws.refresh_modules()
            ws.set_files([str(Path(__file__).parent / "a.wav")])
            ws.activate("t928plain")
            ws.run_active()
            assert ws.lbl_progress.text() == tr("batch.run_done").format(n=1)
            assert ws.results_list.count() == 1
            ws.close()
        finally:
            clear_modules()
            for m in preexisting:
                register_module(m)

    # T-1040：任务中心两态持久化（显隐 + 折叠；新档 ui_task_center.json）
    # ---------------------------------------------------------------

    def test_task_center_visible_state_roundtrip(self, qapp, monkeypatch, tmp_path):
        """显隐落盘 → 新窗口恢复：btn_task_center 勾选态跨窗口保持。"""
        monkeypatch.setenv("HOME", str(tmp_path))
        w1 = MainWindow(AppController())
        assert w1._task_center_panel is None  # 触发前保持懒建
        w1.btn_task_center.setChecked(True)
        assert w1._task_center_panel is not None
        w1.close()

        w2 = MainWindow(AppController())
        assert w2.btn_task_center.isChecked() is True
        w2.close()

    def test_task_center_collapsed_state_roundtrip(self, qapp, monkeypatch, tmp_path):
        """折叠落盘 → 新窗口：面板首次创建后 is_collapsed() 恢复。"""
        monkeypatch.setenv("HOME", str(tmp_path))
        w1 = MainWindow(AppController())
        w1.btn_task_center.setChecked(True)  # 懒建面板
        w1._task_center_panel.set_collapsed(True)
        assert w1._task_center_panel.is_collapsed() is True
        w1.close()

        w2 = MainWindow(AppController())
        assert w2.btn_task_center.isChecked() is True  # 显隐同步恢复 → 自动懒建
        assert w2._task_center_panel is not None
        assert w2._task_center_panel.is_collapsed() is True
        w2.close()

    def test_task_center_panel_stays_lazy(self, window):
        """持久化不破坏懒建：未触发前 _task_center_panel is None（与 :549 同口径）。"""
        w = window
        assert w._task_center_panel is None, "面板懒建（未触发前不存在）"

    def test_task_center_state_load_robust(self, qapp, monkeypatch, tmp_path):
        """损坏 / 非 dict / 非法类型 → 静默回落默认（不抛；合法字段保留）。"""
        monkeypatch.setenv("HOME", str(tmp_path))
        w = MainWindow(AppController())
        target = tmp_path / "ui_task_center.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{not-json", encoding="utf-8")
        assert w._load_task_center_state() is None
        target.write_text("[]", encoding="utf-8")
        assert w._load_task_center_state() is None
        target.write_text('{"visible": "yes"}', encoding="utf-8")
        assert w._load_task_center_state() is None
        target.write_text('{"visible": true, "collapsed": 1}', encoding="utf-8")
        assert w._load_task_center_state() == {"visible": True}  # 非法字段回落默认
        w.close()

    def test_task_center_state_save_silent_on_oserror(self, qapp, monkeypatch, tmp_path):
        """写盘 OSError → _save_task_center_state() 全静默不抛。"""
        monkeypatch.setenv("HOME", str(tmp_path))
        w = MainWindow(AppController())
        w.btn_task_center.setChecked(True)  # 懒建面板，保证两态可读
        monkeypatch.setattr("builtins.open", _raise_oserror)
        w._save_task_center_state()  # 不抛
        w.close()

    def test_task_center_state_file_path(self, qapp, monkeypatch, tmp_path):
        """落盘路径 = get_data_dir() / ui_task_center.json（禁塞 settings.json）。"""
        monkeypatch.setenv("HOME", str(tmp_path))
        w = MainWindow(AppController())
        w.btn_task_center.setChecked(True)  # 触发落盘
        target = tmp_path / "ui_task_center.json"
        assert target.exists()
        assert json.loads(target.read_text(encoding="utf-8"))["visible"] is True
        assert not (tmp_path / "settings.json").exists()  # 不污染用户偏好档
        w.close()


# ---------------------------------------------------------------------------
# ④ 静态纪律
# ---------------------------------------------------------------------------


class TestStatic:
    def test_banned_word_zero_hits(self):
        for path in (_TC_PY, _MW_PY, _BW_PY, _I18N_PY, Path(__file__)):
            assert _BANNED.lower() not in path.read_text(encoding="utf-8").lower()

    def test_no_hardcoded_hex_or_px_in_new_module(self):
        """新模块一律走 TOKENS/主题色（禁 hex / 禁字面量像素）。"""
        src = _TC_PY.read_text(encoding="utf-8")
        assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", src), "禁硬编码颜色"
        assert not re.findall(r"\b\d+(?:\.\d+)?px\b", src), "禁硬编码像素"

    def test_no_new_qdialog_or_modal(self):
        tree = ast.parse(_TC_PY.read_text(encoding="utf-8"))
        bases = {
            b.id
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
            for b in node.bases
            if isinstance(b, ast.Name)
        }
        assert "QDialog" not in bases
        assert "exec(" not in _TC_PY.read_text(encoding="utf-8")

    def test_no_new_icon_names(self):
        """图标名冻结（30 名）：toggle 用既有名；T-1025 授权新增 9 名（多轨 6 + 批0 前置 3）。"""
        assert len(theme.ICONS) == 30
        assert "gauge" not in theme.ICONS
        assert "layers" in theme.ICONS
        src = _MW_PY.read_text(encoding="utf-8")
        assert 'get_icon("layers")' in src

    def test_i18n_keys_complete_for_three_languages(self):
        """新增文案三语齐备（用户可见文案零终端）。"""
        import acouscope.i18n as i18n

        keys = [k for k in i18n._STRINGS if k.startswith("task_center.")]  # noqa: SLF001
        assert len(keys) >= 20, f"task_center 文案键偏少: {len(keys)}"
        for key in keys:
            entry = i18n._STRINGS[key]  # noqa: SLF001
            for lang in i18n.LANGUAGES:
                text = str(entry.get(lang, ""))
                assert text.strip() != "", f"{key} 缺 {lang}"
        for key in (
            "task_center.title",
            "task_center.toggle",
            "task_center.empty",
            "task_center.queue_full",
            "task_center.cancel",
            "task_center.state.done",
        ):
            assert tr(key) != key, f"{key} 未在 i18n 表中"

    def test_queue_full_message_uses_i18n(self, window):
        """排队超上限提示为用户可见 i18n 文案（零终端命令、零英文硬编码）。"""
        w = window
        message = tr("task_center.queue_full").format(n=w.task_center.queue_limit)
        assert "{n}" not in message
        assert str(w.task_center.queue_limit) in message
        assert w.task_center.queue_limit == TASK_CENTER_QUEUE_LIMIT


def _method_source(cls, name: str) -> str:
    """取类内某方法的源码（只读取该方法，避免整文件入上下文）。"""
    import inspect

    return inspect.getsource(getattr(cls, name))
