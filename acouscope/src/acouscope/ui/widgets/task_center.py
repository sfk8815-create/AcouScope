# SPDX-License-Identifier: GPL-3.0-only
"""T-928：非模态「任务进度中心」（TaskCenter）。

分两层，**严格分离**（调度层禁碰 UI）：

- §1 调度层 `TaskCenter`（QObject）：FIFO 队列 + 可置顶 + 并发上限 + 排队上限；
  跨线程一律经 Qt 信号回主线程，工作线程内只允许改数据字段与发信号。
- §2 面板层 `TaskCenterPanel`（QWidget，非模态、可折叠）：状态栏 toggle 驱动，
  四态呈现（空态 / 进行中 / 排队 / 完成历史）。

进度呈现口径（禁伪造百分比）：
- `PROGRESS_DETERMINATE`：有真实数值进度（0–100）；
- `PROGRESS_INDETERMINATE`：无数值进度 → 不定式 busy 条 + 阶段文本；
- `PROGRESS_TEXT`：进度由他处专属明细承载（如下载的状态栏内联面板、批处理的
  内联进度文本）→ 本面板只呈现阶段文本与终态，**不再重复一条进度条**。

权威常量（并发上限 / 排队上限）定义在本模块模块级；`utils/config.py:Settings`
两字段默认值与此一致，越界/非法在 `Settings.load()` 回退到本处默认值。
"""

from __future__ import annotations

import time
import uuid

from dataclasses import dataclass, field

from PyQt6.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from acouscope.i18n import tr
from acouscope.ui.theme import TOKENS, get_icon, style_when_theme

# ---------------------------------------------------------------------------
# §0 权威常量与枚举（唯一源）
# ---------------------------------------------------------------------------

# 并发上限：默认 1（串行，防内存峰值叠加）
TASK_CENTER_MAX_CONCURRENCY = 1
# 排队上限：超出即拒绝提交（不静默丢弃）
TASK_CENTER_QUEUE_LIMIT = 32
# 完成历史保留条数
TASK_CENTER_HISTORY_LIMIT = 10
# 面板默认宽度（悬浮/内联托管时由宿主使用；由令牌派生，禁字面量像素）
TASK_CENTER_PANEL_WIDTH = TOKENS["spacing"]["xxl"] * 9

# 终态
STATE_QUEUED = "queued"
STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_FAILED = "failed"
STATE_CANCELLED = "cancelled"
TERMINAL_STATES = frozenset({STATE_DONE, STATE_FAILED, STATE_CANCELLED})

# 进度呈现模式
PROGRESS_DETERMINATE = "determinate"
PROGRESS_INDETERMINATE = "indeterminate"
PROGRESS_TEXT = "text"

# 任务类别（仅用于标题归属，不影响调度）
KIND_ANALYSIS = "analysis"
KIND_DOWNLOAD = "download"
KIND_BATCH = "batch"

# 状态 → i18n 键
_STATE_KEYS = {
    STATE_QUEUED: "task_center.state.queued",
    STATE_RUNNING: "task_center.state.running",
    STATE_DONE: "task_center.state.done",
    STATE_FAILED: "task_center.state.failed",
    STATE_CANCELLED: "task_center.state.cancelled",
}

# 状态 → 终态标签的 QSS 动态属性值（单一强调色之外的语义功能色，禁装饰色）
_STATE_PROP = {
    STATE_DONE: "done",
    STATE_FAILED: "failed",
    STATE_CANCELLED: "muted",
}

# 回调「无参数」哨兵（区分 f() 与 f(arg)）
_NO_ARG = object()


def format_duration(seconds: float) -> str:
    """秒 → mm:ss（不足一小时；负值按 0 处理）。"""
    total = int(max(0.0, float(seconds)))
    return f"{total // 60:02d}:{total % 60:02d}"


def _safe_tr(key: str, default: str) -> str:
    """i18n 取值（缺键时回退默认文案，绝不抛）。"""
    text = ""
    try:
        text = tr(key)
    except Exception:  # noqa: BLE001 — i18n 缺失不得影响任务执行
        return default
    return text or default


# ---------------------------------------------------------------------------
# §1 调度层
# ---------------------------------------------------------------------------


@dataclass
class TaskEntry:
    """一条任务记录（调度层数据；面板只读它渲染）。

    `progress_mode` 决定面板呈现方式；`progress` 仅在
    `PROGRESS_DETERMINATE` 下有意义（0–100，单调不减）。
    """

    task_id: str
    title: str
    kind: str = KIND_ANALYSIS
    progress_mode: str = PROGRESS_INDETERMINATE
    state: str = STATE_QUEUED
    stage: str = ""
    progress: float = 0.0
    created_at: float = field(default_factory=time.monotonic)
    started_at: float | None = None
    finished_at: float | None = None
    error: str = ""
    cancellable: bool = True
    external: bool = False
    cancel_action: object = None
    priority: bool = False

    def is_terminal(self) -> bool:
        """是否已到终态（完成/失败/取消）。"""
        return self.state in TERMINAL_STATES

    def elapsed(self, now: float | None = None) -> float:
        """耗时秒数：运行中 = 现在 − 开始；终态 = 结束 − 开始；未开始 = 0。"""
        if self.started_at is None:
            return 0.0
        end = self.finished_at
        if end is None:
            end = time.monotonic() if now is None else now
        return max(0.0, float(end) - float(self.started_at))


class TaskReporter:
    """交给工作线程的进度上报句柄（线程内可安全调用；**禁**在此触 UI）。

    `stage(text)` / `progress(value)` 只改数据字段并发信号；接收者在主线程 →
    Qt 自动连接按队列投递，面板在主线程被唤醒。
    """

    def __init__(self, center: "TaskCenter", entry: TaskEntry):
        self._center = center
        self.entry = entry
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        """是否已被请求取消（协作式：工作函数应周期性检查）。"""
        return self._cancelled

    def request_cancel(self) -> None:
        """标记取消请求（仅调度层调用）。"""
        self._cancelled = True

    def stage(self, text: str) -> None:
        """更新阶段文本（不定式/确定式任务都可用）。"""
        self.entry.stage = str(text)
        self._center.taskStage.emit(self.entry, self.entry.stage)

    def progress(self, value: float) -> None:
        """上报确定式进度（0–100）；单调不减，且不会越过 100。"""
        try:
            number = float(value)
        except (TypeError, ValueError):
            return
        number = min(100.0, max(0.0, number))
        if number < self.entry.progress:
            return
        self.entry.progress = number
        self._center.taskProgress.emit(self.entry, number)


class _TaskThread(QThread):
    """调度层工作线程：只跑调用方给的纯计算函数，禁触 UI。"""

    def __init__(self, parent, entry: TaskEntry, run, reporter: TaskReporter):
        super().__init__(parent)
        self.entry = entry
        self._run = run
        self._reporter = reporter
        self.ok = False
        self.error = ""
        self.result = None

    def run(self):  # noqa: D102 — QThread 入口
        try:
            self.result = self._run(self._reporter)
            self.ok = True
        except Exception as exc:  # noqa: BLE001 — 任务异常收敛为失败终态
            import traceback

            self.error = f"{exc}\n{traceback.format_exc(limit=3)}"


class TaskCenter(QObject):
    """任务调度中心：FIFO + 可置顶 + 并发上限 + 排队上限；跨线程信号回主线程。

    两类任务：
    - **调度执行**（`submit`）：本中心起 QThread 跑 `run(reporter)`；支持取消
      （协作式，见 `cancel`）。
    - **外部驱动**（`register`）：工作由调用方自己的线程/同步流程完成，本中心
      只登记生命周期（`set_stage` / `set_progress` / `finish`），`cancel` 时回调
      `cancel_action`。外部任务**不占**调度队列额度与并发位。
    """

    taskAdded = pyqtSignal(object)                # TaskEntry
    taskStarted = pyqtSignal(object)              # TaskEntry
    taskProgress = pyqtSignal(object, float)      # TaskEntry, 0–100
    taskStage = pyqtSignal(object, str)           # TaskEntry, 阶段文本
    taskFinished = pyqtSignal(object, bool, str)  # TaskEntry, ok, err
    taskCancelled = pyqtSignal(object)            # TaskEntry
    taskRejected = pyqtSignal(str)                # 标题（排队超上限）
    queueChanged = pyqtSignal()

    def __init__(
        self,
        parent=None,
        *,
        max_concurrency: int | None = None,
        queue_limit: int | None = None,
        history_limit: int | None = None,
    ):
        super().__init__(parent)
        self.max_concurrency = self._clamp_int(
            max_concurrency, TASK_CENTER_MAX_CONCURRENCY, 1, 4
        )
        self.queue_limit = self._clamp_int(queue_limit, TASK_CENTER_QUEUE_LIMIT, 1, 256)
        self.history_limit = self._clamp_int(
            history_limit, TASK_CENTER_HISTORY_LIMIT, 1, 100
        )
        self._queue: list[TaskEntry] = []
        self._running: dict[str, TaskEntry] = {}
        self._history: list[TaskEntry] = []
        self._entries: dict[str, TaskEntry] = {}
        self._threads: dict[str, _TaskThread] = {}
        self._reporters: dict[str, TaskReporter] = {}
        self._callbacks: dict[str, dict] = {}
        self._shutting_down = False

    # -- 工具 ---------------------------------------------------------------

    @staticmethod
    def _clamp_int(value, default: int, low: int, high: int) -> int:
        """非法/越界一律回退默认（与 Settings.load 钳位同口径）。"""
        try:
            number = int(value)
        except (TypeError, ValueError):
            return default
        if number < low or number > high:
            return default
        return number

    @staticmethod
    def new_id() -> str:
        """生成任务 id（外部任务可自带 id）。"""
        return uuid.uuid4().hex[:12]

    # -- 查询 ---------------------------------------------------------------

    def entry(self, task_id: str) -> TaskEntry | None:
        return self._entries.get(task_id)

    def running_entries(self) -> list[TaskEntry]:
        """进行中任务（按开始时间先后）。"""
        items = [e for e in self._entries.values() if e.state == STATE_RUNNING]
        items.sort(key=lambda e: e.started_at or 0.0)
        return items

    def queued_entries(self) -> list[TaskEntry]:
        """排队任务（按队列顺序，置顶项在前）。"""
        return list(self._queue)

    def history(self) -> list[TaskEntry]:
        """完成历史（最近在前，上限 `history_limit`）。"""
        return list(self._history)

    def active_count(self) -> int:
        """进行中 + 排队总数（状态栏 toggle 计数用）。"""
        return len(self._running) + len(self._queue)

    def is_busy(self) -> bool:
        return self.active_count() > 0

    # -- 提交（调度执行） ---------------------------------------------------

    def submit(
        self,
        title: str,
        run,
        *,
        kind: str = KIND_ANALYSIS,
        progress_mode: str = PROGRESS_INDETERMINATE,
        task_id: str | None = None,
        cancellable: bool = True,
        on_done=None,
        on_fail=None,
        on_cancelled=None,
    ) -> TaskEntry | None:
        """提交一条由本中心调度执行的任务。

        Args:
            title: 用户可见标题（面板默认阶段文本）。
            run: `(reporter) -> result`，在**工作线程**执行，禁触 UI。
            kind: 任务类别（analysis/download/batch）。
            progress_mode: 见模块级 `PROGRESS_*`。
            task_id: 指定 id（重复则拒绝）；默认自动生成。
            cancellable: 面板是否给出取消按钮。
            on_done/on_fail/on_cancelled: 主线程回调（可选）。

        Returns:
            新建的 `TaskEntry`；排队超上限或 id 冲突时返回 None
            （后者并发 `taskRejected`，供调用方提示）。
        """
        if self._shutting_down:
            return None
        if task_id is not None and task_id in self._entries:
            return None
        if len(self._queue) >= self.queue_limit:
            self.taskRejected.emit(str(title))
            return None
        entry = TaskEntry(
            task_id=task_id or self.new_id(),
            title=str(title),
            kind=kind,
            progress_mode=progress_mode,
            stage=str(title),
            cancellable=bool(cancellable),
        )
        self._entries[entry.task_id] = entry
        self._callbacks[entry.task_id] = {
            "done": on_done,
            "fail": on_fail,
            "cancelled": on_cancelled,
            "run": run,
        }
        self._queue.append(entry)
        self.taskAdded.emit(entry)
        self.queueChanged.emit()
        self._pump()
        return entry

    # -- 登记（外部驱动） ---------------------------------------------------

    def register(
        self,
        title: str,
        *,
        kind: str = KIND_ANALYSIS,
        progress_mode: str = PROGRESS_TEXT,
        cancellable: bool = True,
        cancel_action=None,
    ) -> TaskEntry:
        """登记一条由调用方自行驱动的任务（立即进行中，不占调度额度）。

        Args:
            title: 用户可见标题。
            kind: 任务类别。
            progress_mode: 见模块级 `PROGRESS_*`。
            cancellable: 面板是否给出取消按钮。
            cancel_action: 取消时在主线程调用的回调（外部任务自行收尾）。
        """
        entry = TaskEntry(
            task_id=self.new_id(),
            title=str(title),
            kind=kind,
            progress_mode=progress_mode,
            state=STATE_RUNNING,
            stage=str(title),
            cancellable=bool(cancellable),
            external=True,
            cancel_action=cancel_action,
        )
        entry.started_at = time.monotonic()
        self._entries[entry.task_id] = entry
        self._running[entry.task_id] = entry
        self.taskAdded.emit(entry)
        self.taskStarted.emit(entry)
        self.queueChanged.emit()
        return entry

    # -- 生命周期更新（外部任务用） ----------------------------------------

    def set_stage(self, task_id: str, text: str) -> None:
        """更新阶段文本（终态任务忽略）。"""
        entry = self._entries.get(task_id)
        if entry is None or entry.is_terminal():
            return
        entry.stage = str(text)
        self.taskStage.emit(entry, entry.stage)

    def set_progress(self, task_id: str, value: float) -> None:
        """更新确定式进度（0–100，单调不减；终态任务忽略）。"""
        entry = self._entries.get(task_id)
        if entry is None or entry.is_terminal():
            return
        try:
            number = min(100.0, max(0.0, float(value)))
        except (TypeError, ValueError):
            return
        if number < entry.progress:
            return
        entry.progress = number
        self.taskProgress.emit(entry, number)

    def finish(self, task_id: str, ok: bool = True, error: str = "") -> None:
        """收敛为终态（完成/失败）；**幂等**：已是终态则忽略（防取消后被改写）。"""
        entry = self._entries.get(task_id)
        if entry is None or entry.is_terminal():
            return
        self._running.pop(task_id, None)
        callbacks = self._callbacks.pop(task_id, {})
        if ok:
            self._settle(entry, STATE_DONE)
            self.taskFinished.emit(entry, True, "")
            self._invoke(callbacks.get("done"), _NO_ARG)
        else:
            entry.error = str(error)
            self._settle(entry, STATE_FAILED)
            self.taskFinished.emit(entry, False, entry.error)
            self._invoke(callbacks.get("fail"), entry.error)
        self._pump()

    # -- 取消 / 置顶 --------------------------------------------------------

    def cancel(self, task_id: str) -> bool:
        """请求取消（外部任务立即收敛；调度任务协作式，完成后结果作废）。

        Returns:
            True = 已受理；False = 未知 id / 已终态。
        """
        entry = self._entries.get(task_id)
        if entry is None or entry.is_terminal():
            return False
        if entry.external:
            action = entry.cancel_action
            self._running.pop(task_id, None)
            callbacks = self._callbacks.pop(task_id, {})
            self._settle(entry, STATE_CANCELLED)
            self.taskCancelled.emit(entry)
            self._invoke(callbacks.get("cancelled"), _NO_ARG)
            if action is not None:
                try:
                    action()
                except Exception:  # noqa: BLE001 — 取消回调异常不得中断调度
                    pass
            return True
        if entry.state == STATE_QUEUED:
            try:
                self._queue.remove(entry)
            except ValueError:
                return False
            callbacks = self._callbacks.pop(task_id, {})
            self._settle(entry, STATE_CANCELLED)
            self.taskCancelled.emit(entry)
            self._invoke(callbacks.get("cancelled"), _NO_ARG)
            self.queueChanged.emit()
            return True
        # 运行中：置取消请求（工作函数协作式检查；不终止线程，避免半途破坏）
        reporter = self._reporters.get(task_id)
        if reporter is not None:
            reporter.request_cancel()
        entry.stage = _safe_tr("task_center.cancelling", "Cancelling…")
        self.taskStage.emit(entry, entry.stage)
        return True

    def bump(self, task_id: str) -> bool:
        """把排队中的任务置顶（FIFO 中的例外，用户显式操作）。"""
        entry = self._entries.get(task_id)
        if entry is None or entry.state != STATE_QUEUED:
            return False
        try:
            self._queue.remove(entry)
        except ValueError:
            return False
        entry.priority = True
        self._queue.insert(0, entry)
        self.queueChanged.emit()
        return True

    def clear_history(self) -> None:
        """清空完成历史（仅呈现层记录，不影响任何在跑任务）。"""
        for entry in self._history:
            self._entries.pop(entry.task_id, None)
        self._history.clear()
        self.queueChanged.emit()

    # -- 收尾 ---------------------------------------------------------------

    def shutdown(self, timeout_ms: int = 3000, drain: bool = True) -> None:
        """关窗收尾：拒绝新任务 + 取消排队 + 等待（必要时终止）在跑线程。

        在跑任务**一律收敛为「已取消」**终态（关窗后不再有结果消费方）。
        """
        self._shutting_down = True
        for entry in list(self._queue):
            self._queue.remove(entry)
            self._settle(entry, STATE_CANCELLED)
        self._queue.clear()
        # 注意：线程句柄**不在此处清空**——QThread 的 Python 包装须活到其
        # `finished` 信号被投递（包装提前释放 + C++ 子对象仍在 → 悬垂，
        # 已在 T-928 复现为后续 processEvents SIGSEGV）；清理统一由
        # `_on_thread_finished` 完成。
        for task_id, thread in list(self._threads.items()):
            reporter = self._reporters.get(task_id)
            if reporter is not None:
                reporter.request_cancel()
            if not thread.wait(timeout_ms):
                thread.terminate()
                thread.wait(timeout_ms)
            entry = self._entries.get(task_id)
            self._running.pop(task_id, None)
            if entry is not None and not entry.is_terminal():
                self._settle(entry, STATE_CANCELLED)
                self.taskCancelled.emit(entry)
        # T-1060 件2：先「停」再 drain —— 线程均已 wait/terminate 收敛；drain 之后
        # 再断开 finished 连接，关闭「迟到排队投递」窗口。
        # ⚠ 实测（/tmp 探针 t1060_probe_drain）：**断开必须放在 drain 之后**——先断
        # 连会让在途 queued finished 投递失效（不再被消费）→ `_on_thread_finished`
        # 不执行、线程包装留在册＝T-928 悬垂窗口复现。故顺序为「停 → drain → 断」。
        if drain:
            self._drain_pending()
        self._disconnect_thread_signals()

    def _disconnect_thread_signals(self) -> None:
        """断开仍在册线程的 `finished` 连接（幂等、绝不出错）。

        仅断连接，**不**清线程句柄（句柄仍由 `_on_thread_finished` 收尾）；
        调用点必须在 `_drain_pending()` 之后（见上面实测说明）。
        """
        for thread in list(self._threads.values()):
            try:
                thread.finished.disconnect()
            except (TypeError, RuntimeError):
                pass

    def _drain_pending(self) -> None:
        """消费在途 `finished` 投递（**限定事件类型**的挂起投递消费）。

        坑点（T-928 实测复现）：线程已结束但 `finished` 投递仍在队列时，
        若 QThread 的 Python 包装先被释放，后续事件派发会命中悬垂投递 →
        SIGSEGV。收尾时显式消费一次即可闭合该窗口。

        ★ T-1060 件2：**不再用裸 `app.processEvents()`**——无差别事件泵会把
        定时器（`QTimer::timerEvent`）等与收尾无关的挂起投递一并派发，C3 崩溃
        正落在此行的下游。改为 `QCoreApplication.sendPostedEvents(None, 43)`
        （`QEvent.Type.MetaCall`）：只消费 queued **调用**投递，定时器/绘制/
        网络事件一概不在此派发。
        实测（/tmp 探针 t1060_probe_drain）：`finished` 的 queued 投递 receiver
        既不是线程对象也不是本中心（PyQt 内部槽代理），无法按 receiver 精确
        限定 → 采用事件类型限定；`finished` 一条不少（T-928 语义不回退）。
        """
        from PyQt6.QtCore import QCoreApplication, QEvent
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None or QThread.currentThread() is not app.thread():
            return
        try:
            QCoreApplication.sendPostedEvents(None, QEvent.Type.MetaCall)
        except RuntimeError:
            pass  # 控件销毁途中：收尾路径不抛

    # -- 内部 ---------------------------------------------------------------

    def _settle(self, entry: TaskEntry, state: str) -> None:
        """置终态 + 入历史（超出上限的最旧条目连同注册表一并清理）。"""
        entry.state = state
        if entry.finished_at is None:
            entry.finished_at = time.monotonic()
        self._history.insert(0, entry)
        while len(self._history) > self.history_limit:
            dropped = self._history.pop()
            self._entries.pop(dropped.task_id, None)
        self.queueChanged.emit()

    @staticmethod
    def _invoke(callback, arg) -> None:
        """主线程回调投递（异常不得影响调度；回调自身负责提示）。"""
        if callback is None:
            return
        try:
            if arg is _NO_ARG:
                callback()
            else:
                callback(arg)
        except Exception:  # noqa: BLE001
            import traceback

            traceback.print_exc()

    def _pump(self) -> None:
        """按并发上限启动排队任务（串行默认 1）。"""
        started = False
        while len(self._running) < self.max_concurrency and self._queue:
            entry = self._queue.pop(0)
            if entry.is_terminal():
                continue
            self._start(entry)
            started = True
        if started:
            self.queueChanged.emit()

    def _start(self, entry: TaskEntry) -> None:
        run = self._callbacks.get(entry.task_id, {}).get("run")
        if run is None:  # 防御：缺 run 视为失败终态，不静默悬挂
            callbacks = self._callbacks.pop(entry.task_id, {})
            self._settle(entry, STATE_FAILED)
            entry.error = _safe_tr("task_center.no_runner", "Task runner missing")
            self.taskFinished.emit(entry, False, entry.error)
            self._invoke(callbacks.get("fail"), entry.error)
            return
        entry.state = STATE_RUNNING
        entry.started_at = time.monotonic()
        self._running[entry.task_id] = entry
        reporter = TaskReporter(self, entry)
        self._reporters[entry.task_id] = reporter
        thread = _TaskThread(self, entry, run, reporter)
        self._threads[entry.task_id] = thread
        thread.finished.connect(lambda tid=entry.task_id: self._on_thread_finished(tid))
        thread.start()
        self.taskStarted.emit(entry)

    def _on_thread_finished(self, task_id: str) -> None:
        thread = self._threads.pop(task_id, None)
        reporter = self._reporters.pop(task_id, None)
        entry = self._entries.get(task_id)
        if entry is None or thread is None:
            self._pump()
            return
        callbacks = self._callbacks.pop(task_id, {})
        self._running.pop(task_id, None)
        thread.deleteLater()  # 线程对象交 Qt 事件循环回收（不在自身 finished 中析构）
        if entry.is_terminal():
            # 收尾（shutdown）已把该任务收敛为终态 → 结果作废，不重复广播
            self._pump()
            return
        if reporter is not None and reporter.cancelled:
            self._settle(entry, STATE_CANCELLED)
            self.taskCancelled.emit(entry)
            self._invoke(callbacks.get("cancelled"), _NO_ARG)
        elif thread.ok:
            self._settle(entry, STATE_DONE)
            self.taskFinished.emit(entry, True, "")
            self._invoke(callbacks.get("done"), thread.result)
        else:
            entry.error = thread.error
            self._settle(entry, STATE_FAILED)
            self.taskFinished.emit(entry, False, entry.error)
            self._invoke(callbacks.get("fail"), entry.error)
        self._pump()


# ---------------------------------------------------------------------------
# §2 面板层（非模态 QWidget，可折叠；禁 QDialog/模态）
# ---------------------------------------------------------------------------


class TaskRow(QWidget):
    """单条任务行（进行中 / 排队 / 历史共用）。"""

    def __init__(self, entry: TaskEntry, center: TaskCenter, parent=None):
        super().__init__(parent)
        self.setObjectName("taskRow")
        self.entry = entry
        self._center = center
        sp = TOKENS["spacing"]

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(sp["sm"])

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(sp["xxs"])
        self.lbl_title = QLabel(entry.title, self)
        self.lbl_title.setObjectName("taskRowTitle")
        text_box.addWidget(self.lbl_title)
        self.lbl_stage = QLabel("", self)
        self.lbl_stage.setObjectName("taskRowStage")
        self.lbl_stage.setWordWrap(True)
        text_box.addWidget(self.lbl_stage)
        root.addLayout(text_box, 1)

        self.progress = None
        if entry.progress_mode == PROGRESS_DETERMINATE:
            self.progress = QProgressBar(self)
            self.progress.setObjectName("taskRowProgress")
            self.progress.setRange(0, 100)
            self.progress.setValue(int(entry.progress))
            self.progress.setTextVisible(False)
            root.addWidget(self.progress)
        elif entry.progress_mode == PROGRESS_INDETERMINATE:
            self.progress = QProgressBar(self)
            self.progress.setObjectName("taskRowProgress")
            self.progress.setRange(0, 0)  # 不定式 busy（无百分比可汇报）
            self.progress.setTextVisible(False)
            root.addWidget(self.progress)

        self.lbl_state = QLabel("", self)
        self.lbl_state.setObjectName("taskRowState")
        root.addWidget(self.lbl_state)
        self.lbl_elapsed = QLabel("", self)
        self.lbl_elapsed.setObjectName("taskRowElapsed")
        root.addWidget(self.lbl_elapsed)

        self.btn_cancel = None
        if entry.cancellable and not entry.is_terminal():
            self.btn_cancel = QPushButton(_safe_tr("task_center.cancel", "Cancel"), self)
            self.btn_cancel.setObjectName("taskRowCancel")
            self.btn_cancel.setAutoDefault(False)
            self.btn_cancel.clicked.connect(
                lambda _checked=False, tid=entry.task_id: center.cancel(tid)
            )
            root.addWidget(self.btn_cancel)

        self.refresh()

    def refresh(self) -> None:
        """按当前记录刷新文本/状态/进度（面板定时器与信号回调共用）。"""
        entry = self.entry
        self.lbl_stage.setText("" if entry.is_terminal() else (entry.stage or ""))
        if entry.is_terminal():
            self.lbl_state.setText(
                _safe_tr(_STATE_KEYS[entry.state], entry.state)
            )
            self.lbl_state.setProperty("stateLevel", _STATE_PROP[entry.state])
        else:
            self.lbl_state.setText("")
            self.lbl_state.setProperty("stateLevel", "running")
        self.lbl_elapsed.setText(
            f"{_safe_tr('task_center.elapsed', 'Elapsed')} "
            f"{format_duration(entry.elapsed())}"
            if entry.started_at is not None
            else ""
        )
        if self.progress is not None and entry.progress_mode == PROGRESS_DETERMINATE:
            self.progress.setValue(int(entry.progress))


class TaskCenterPanel(QWidget):
    """任务进度中心面板：非模态、可折叠；四态 = 空态 / 进行中 / 排队 / 完成历史。"""

    collapsedChanged = pyqtSignal(bool)  # T-1040：折叠态变化（set_collapsed 末尾 emit，供落盘）

    def __init__(self, center: TaskCenter | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("taskCenterPanel")
        self._center: TaskCenter | None = None
        self._connections: list = []
        self._collapsed = False
        self._rows: dict[str, list[TaskRow]] = {"running": [], "queued": [], "history": []}
        spc = TOKENS["spacing"]
        ctl = TOKENS["control"]
        sem = TOKENS["semantic"]

        root = QVBoxLayout(self)
        root.setContentsMargins(spc["sm"], spc["sm"], spc["sm"], spc["sm"])
        root.setSpacing(spc["xs"])

        # -- 面板头：左标题 + 右操作区（统一构件：高 h_lg，底边最弱 1 像素分隔） --
        self.header = QWidget(self)
        self.header.setObjectName("taskCenterHeader")
        head = QHBoxLayout(self.header)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(spc["sm"])
        self.lbl_title = QLabel(
            _safe_tr("task_center.title", "Task Center"), self.header
        )
        self.lbl_title.setObjectName("taskCenterTitle")
        head.addWidget(self.lbl_title)
        head.addStretch(1)
        self.btn_clear = QPushButton(
            _safe_tr("task_center.clear_history", "Clear history"), self.header
        )
        self.btn_clear.setObjectName("taskCenterClear")
        self.btn_clear.setAutoDefault(False)
        self.btn_clear.setFixedHeight(ctl["h_sm"])
        self.btn_clear.clicked.connect(self._on_clear_history)
        head.addWidget(self.btn_clear)
        self.btn_collapse = QPushButton(self.header)
        self.btn_collapse.setObjectName("taskCenterCollapse")
        self.btn_collapse.setCheckable(True)
        self.btn_collapse.setAutoDefault(False)
        self.btn_collapse.setIcon(get_icon("chevron_down"))
        self.btn_collapse.setFixedHeight(ctl["h_sm"])
        self.btn_collapse.toggled.connect(self.set_collapsed)
        head.addWidget(self.btn_collapse)
        self.header.setFixedHeight(ctl["h_lg"])
        root.addWidget(self.header)

        # -- 主体：空态 + 三组（进行中 / 排队 / 完成历史） --
        self.body = QWidget(self)
        self.body.setObjectName("taskCenterBody")
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, spc["xs"], 0, 0)
        body.setSpacing(spc["xs"])

        self.lbl_empty = QLabel(
            _safe_tr("task_center.empty", "No active tasks"), self.body
        )
        self.lbl_empty.setObjectName("taskCenterEmpty")
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty.setWordWrap(True)
        body.addWidget(self.lbl_empty)
        self.lbl_empty_hint = QLabel(_safe_tr("task_center.empty_hint", ""), self.body)
        self.lbl_empty_hint.setObjectName("taskCenterEmptyHint")
        self.lbl_empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty_hint.setWordWrap(True)
        body.addWidget(self.lbl_empty_hint)

        self.groups: dict[str, QWidget] = {}
        self._rows_lay: dict[str, QVBoxLayout] = {}
        for key, title_key, default in (
            ("running", "task_center.group.running", "Running"),
            ("queued", "task_center.group.queued", "Queued"),
            ("history", "task_center.group.history", "Completed"),
        ):
            holder = QWidget(self.body)
            holder.setObjectName(f"taskCenterGroup_{key}")
            lay = QVBoxLayout(holder)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(spc["xxs"])
            label = QLabel(_safe_tr(title_key, default), holder)
            label.setObjectName(f"taskCenterGroupTitle_{key}")
            lay.addWidget(label)
            rows_lay = QVBoxLayout()
            rows_lay.setContentsMargins(0, 0, 0, 0)
            rows_lay.setSpacing(spc["xs"])
            lay.addLayout(rows_lay)
            body.addWidget(holder)
            self.groups[key] = holder
            self._rows_lay[key] = rows_lay

        body.addStretch(1)
        root.addWidget(self.body, 1)

        style_when_theme(
            self,
            lambda c: (
                f"QWidget#taskCenterPanel {{ background: {c['panel']}; "
                f"border: {TOKENS['elevation']['border']}px solid {c['border']}; "
                f"border-radius: {TOKENS['radius']['md']}px; }}"
                f"QWidget#taskCenterHeader {{ "
                f"border-bottom: {TOKENS['elevation']['border']}px solid "
                f"{c['border']}; }}"
                f"QLabel#taskCenterTitle {{ color: {c['text']}; }}"
                f"QLabel#taskCenterEmpty, QLabel#taskCenterEmptyHint, "
                f"QLabel#taskRowElapsed, QLabel#taskRowStage {{ "
                f"color: {c['text_sub']}; }}"
                f"QLabel#taskRowState[stateLevel=\"done\"] {{ "
                f"color: {sem['success']}; }}"
                f"QLabel#taskRowState[stateLevel=\"failed\"] {{ "
                f"color: {sem['error']}; }}"
                f"QLabel#taskRowState[stateLevel=\"muted\"] {{ "
                f"color: {c['text_faint']}; }}"
            ),
        )

        # 运行中任务的耗时秒表（仅在有运行任务时走 1s 定时刷新）
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

        self.setMinimumWidth(TASK_CENTER_PANEL_WIDTH)
        self._sync_collapse_button()
        if center is not None:
            self.set_center(center)
        else:
            self.refresh()

    # -- 接线 ---------------------------------------------------------------

    def set_center(self, center: TaskCenter) -> None:
        """绑定调度中心（信号驱动刷新；重复绑定先断开旧中心）。"""
        for sig, slot in self._connections:
            try:
                sig.disconnect(slot)
            except TypeError:
                pass
        self._connections = []
        self._center = center
        pairs = (
            (center.taskAdded, self._on_structure_changed),
            (center.taskStarted, self._on_structure_changed),
            (center.taskProgress, self._on_entry_changed),
            (center.taskStage, self._on_entry_changed),
            (center.taskFinished, self._on_structure_changed),
            (center.taskCancelled, self._on_structure_changed),
            (center.queueChanged, self._on_structure_changed),
        )
        for sig, slot in pairs:
            sig.connect(slot)
        self._connections = list(pairs)
        self.refresh()

    def center(self) -> TaskCenter | None:
        return self._center

    # -- 折叠 ---------------------------------------------------------------

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool) -> None:
        """折叠/展开（折叠只隐藏主体，面板头保留）。"""
        self._collapsed = bool(collapsed)
        self.body.setVisible(not self._collapsed)
        self._sync_collapse_button()
        self.collapsedChanged.emit(self._collapsed)

    def _sync_collapse_button(self) -> None:
        if self.btn_collapse.isChecked() != self._collapsed:
            self.btn_collapse.blockSignals(True)
            self.btn_collapse.setChecked(self._collapsed)
            self.btn_collapse.blockSignals(False)
        self.btn_collapse.setIcon(
            get_icon("chevron_right" if self._collapsed else "chevron_down")
        )
        self.btn_collapse.setToolTip(
            _safe_tr("task_center.expand", "Expand")
            if self._collapsed
            else _safe_tr("task_center.collapse", "Collapse")
        )

    # -- 刷新 ---------------------------------------------------------------

    def rows(self, group: str) -> list[TaskRow]:
        """取某组的行控件（测试/断言用）。"""
        return list(self._rows.get(group, []))

    def empty_state_visible(self) -> bool:
        """空态是否可见（无进行中、无排队、无历史）。"""
        return not self.lbl_empty.isHidden()

    def _on_structure_changed(self, *_args) -> None:
        """任务集合/终态变化 → 重建三组。"""
        self.refresh()

    def _on_entry_changed(self, entry, *_args) -> None:
        """阶段文本/进度变化 → 只刷新对应行（不重建控件，避免高频抖动）。"""
        for rows in self._rows.values():
            for row in rows:
                if row.entry.task_id == getattr(entry, "task_id", None):
                    row.refresh()
                    return
        self.refresh()

    def refresh(self) -> None:
        """按调度中心当前状态重建三组（记录数有界：运行 + 排队 + 历史）。"""
        center = self._center
        running = center.running_entries() if center is not None else []
        queued = center.queued_entries() if center is not None else []
        history = center.history() if center is not None else []

        self._rebuild("running", running)
        self._rebuild("queued", queued)
        self._rebuild("history", history)

        self.groups["running"].setVisible(bool(running))
        self.groups["queued"].setVisible(bool(queued))
        self.groups["history"].setVisible(bool(history))
        show_empty = not (running or queued or history)
        self.lbl_empty.setVisible(show_empty)
        self.lbl_empty_hint.setVisible(show_empty)
        self.btn_clear.setEnabled(bool(history))
        if running:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    def _rebuild(self, group: str, entries: list[TaskEntry]) -> None:
        lay = self._rows_lay[group]
        for row in self._rows[group]:
            lay.removeWidget(row)
            row.deleteLater()
        self._rows[group] = []
        center = self._center
        if center is None:
            return
        for entry in entries:
            row = TaskRow(entry, center, self.groups[group])
            lay.addWidget(row)
            self._rows[group].append(row)

    def _tick(self) -> None:
        """1s 定时：刷新运行中行的耗时（mm:ss）。"""
        for row in self._rows["running"]:
            row.refresh()
        if not self._rows["running"]:
            self._timer.stop()

    def _on_clear_history(self) -> None:
        if self._center is not None:
            self._center.clear_history()
        self.refresh()
