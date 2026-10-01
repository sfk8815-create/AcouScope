"""T-1041a 轮 B：多轨分析经任务中心投递（宿主接线 · 全离屏 · 后台线程收敛）。

覆盖：
① 正向：投递注册（kind / progress_mode / cancellable）→ 完成回调（计数 +
   toast 恰 1 发 + 缓存落账 + refresh 真发生）+ 反向禁双投递（spy 可数：
   0 = 断链 · 2 = 双跑 · 1 = 正确）；
② 取消：协作式（taskFinished 0 次 / 未跑轨 cancelled / 已跑轨 done / id 清空）；
③ 静态：零新增 taskProgress / taskFinished 连接 + 注入行恰 1 +
   analyzeRequested.connect 仍恰 1。

★ 禁固定 task_id（终态条目滞留 `_entries` 直至 history_limit 溢出 ⇒ 之后
  永久拒绝的陷阱）；★ 禁断言投递返回句柄（投递同步返回、句柄待 worker
  结束才存在 ⇒ 恒 ``[]``，句柄不可补）。
"""

import threading
import time
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

import acouscope.ui.main_window as mw
import acouscope.ui.widgets.multitrack.analysis_source as asrc
from acouscope.app.controller import AppController
from acouscope.ui.main_window import MainWindow
from acouscope.ui.widgets.multitrack.track_model import MultitrackSession
from acouscope.ui.widgets.task_center import STATE_CANCELLED
from tests._pin_baselines import MULTITRACK_ANALYZE_REQUEST_CONNECTS

_MW_DIR = Path(mw.__file__).resolve().parent

_SR = 8000
_DURATION = 2.0


def _wait_until(predicate, timeout_ms: int = 6000) -> bool:
    """后台线程收敛：主线程 processEvents 直到谓词成立或超时。"""
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if predicate():
            return True
        QApplication.processEvents()
        time.sleep(0.005)
    return bool(predicate())


def _session(n: int = 3) -> MultitrackSession:
    """合成会话：n 轨（假读取器；样本为线性斜坡，无需真实音频文件）。"""
    session = MultitrackSession(
        metadata_reader=lambda p: {"sample_rate": _SR, "channels": 1,
                                   "duration": _DURATION},
        envelope_reader=lambda p, points: (
            np.linspace(0.0, _DURATION, points),
            np.full(points, 0.5, dtype=np.float32),
        ),
        loader=lambda p: (np.linspace(-0.3, 0.3, int(_SR * _DURATION)), _SR),
    )
    for i in range(n):
        session.add_path(f"/tmp/taskb{i}.wav", label=f"track{i}")
    return session


class _PitchStub:
    """逐轨音高结果桩（只含呈现层消费的 times / f0_hz）。"""

    def __init__(self):
        self.times = np.linspace(0.0, 1.0, 8)
        self.f0_hz = np.full(8, 440.0)


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """离屏主窗（不显示窗体；合成音频绕付费门控）。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    controller = AppController()
    t = np.arange(_SR) / _SR
    controller.load_from_array(0.5 * np.sin(2 * np.pi * 440.0 * t), _SR)
    w = MainWindow(controller)
    yield w
    w.close()


def _arm(window, monkeypatch, gate):
    """接好投递链：3 轨会话 + 刷新呈现 + spy 真函数（注入 stub runner）+
    toast 截获。返回 ``(panel, toasts, calls, results, runner_calls)``。

    - ``calls``：真 ``run_analysis_on_tracks`` 被调次数（0=断链 · 2=双跑）；
    - ``results``：每次真调用的句柄列表（取消例断言各轨 status 用）；
    - ``runner_calls``：stub runner 被调的 track_id（取消后不再增长断言用）。
    """
    panel = window.multitrack_panel
    panel.set_session(_session(3))
    panel.refresh_presentation()      # compare_view.set_session → btn 可用

    runner_calls = []

    def runner(source, params):
        runner_calls.append(source.track_id)
        gate.wait(timeout=2.0)        # 有界阻塞：给连点/取消留「在途」窗口
        return _PitchStub()

    calls, results = [], []
    real = asrc.run_analysis_on_tracks

    def wrapper(*args, **kwargs):
        calls.append(args)
        kwargs["runner"] = runner
        out = real(*args, **kwargs)
        results.append(out)
        return out

    monkeypatch.setattr(asrc, "run_analysis_on_tracks", wrapper)

    toasts = []
    monkeypatch.setattr(
        mw, "show_toast",
        lambda parent, message, level="info", duration=3500:
            toasts.append((message, level)),
    )
    return panel, toasts, calls, results, runner_calls


# ---------------------------------------------------------------------------
# 例 1：注册 + 完成 + 反向禁双投递
# ---------------------------------------------------------------------------


def test_deliver_registers_completes_and_blocks_double_submit(
    window, monkeypatch,
):
    gate = threading.Event()
    panel, toasts, calls, results, _runner_calls = _arm(window, monkeypatch, gate)

    panel.compare_view.btn_analyze.click()
    task_id = window._multitrack_analysis_task_id
    entry = window.task_center.entry(task_id)
    assert window.task_center.active_count() == 1
    assert entry is not None                      # 投递已登记
    assert entry.kind == "analysis"
    assert entry.progress_mode == "indeterminate"
    assert entry.cancellable is True

    # 反向：在途连点 2 次 ⇒ 不重复投递（中心条目恰 1；spy 恒 1）
    panel.compare_view.btn_analyze.click()
    panel.compare_view.btn_analyze.click()
    assert window.task_center.active_count() == 1
    assert window.task_center.entry(window._multitrack_analysis_task_id) is entry

    gate.set()                                    # 放行 stub → 三轨跑完
    assert _wait_until(lambda: entry.state == "done")
    assert entry.finished_at is not None
    assert len(calls) == 1                        # 真 run_analysis_on_tracks 恰 1
    assert len(results) == 1                      # spy 只此一次（0=断链 · 2=双跑）
    assert len(window.multitrack_result_cache) == 3   # 缓存条目数 == 轨数
    assert panel.compare_view.has_results() is True   # refresh 真发生
    assert len(toasts) == 1 and toasts[0][1] == "info"  # analyzed toast 恰 1 发


# ---------------------------------------------------------------------------
# 例 2：取消（协作式 · 5 条断言缺一不可）
# ---------------------------------------------------------------------------


def test_deliver_cancel_is_cooperative(window, monkeypatch):
    gate = threading.Event()
    panel, _toasts, calls, results, runner_calls = _arm(window, monkeypatch, gate)

    finished = []
    window.task_center.taskFinished.connect(lambda *a: finished.append(a))

    panel.compare_view.btn_analyze.click()
    entry = window.task_center.entry(window._multitrack_analysis_task_id)
    assert _wait_until(lambda: len(runner_calls) == 1)   # 首轨在途（已入 stub）

    assert window.task_center.cancel(entry.task_id) is True
    n_at_cancel = len(runner_calls)
    gate.set()                     # 放行首轨 → 取消已请求 ⇒ 未跑轨不再启动
    assert _wait_until(lambda: entry.state == STATE_CANCELLED)

    assert entry.state == STATE_CANCELLED            # ① 终态
    assert finished == []                            # ② taskFinished 发射 0 次
    assert len(runner_calls) == n_at_cancel == 1     # ③ stub 计数取消后不再增长
    assert len(calls) == 1 and len(results) == 1
    handles = results[-1]
    assert [h.status for h in handles] == [          # ④ 未跑 cancelled · 已跑 done
        "done", "cancelled", "cancelled",
    ]
    assert window._multitrack_analysis_task_id is None   # ⑤ id 已清


# ---------------------------------------------------------------------------
# 例 3：静态纪律
# ---------------------------------------------------------------------------


def test_static_seam_and_single_connect():
    source = (_MW_DIR / "main_window.py").read_text()
    assert "taskProgress.connect" not in source      # ① 零新增连接
    assert "taskFinished.connect" not in source
    assert source.count("taskRejected.connect") == 1  # 既有 taskRejected 不动
    assert source.count(
        "self.multitrack_panel.set_analysis_deliver("
    ) == 1                                           # ② 注入行恰 1
    mv_src = (
        _MW_DIR / "widgets" / "multitrack" / "multitrack_view.py"
    ).read_text()
    assert (
        mv_src.count("analyzeRequested.connect") == MULTITRACK_ANALYZE_REQUEST_CONNECTS
    )  # ③ 仍恰 1 处
