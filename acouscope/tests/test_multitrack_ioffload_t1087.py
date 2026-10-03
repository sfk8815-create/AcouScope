# SPDX-License-Identifier: GPL-3.0-only
"""T-1087 M4（path_A）：多轨分析取数挪 worker + LRU 驱逐延后（线程安全守卫）。

破口（§〇-bis M4）：``analyze_all`` 在 ``task_center.submit`` **之前**于主线程做
``resolve_source → track.load_full()``（整文件同步 IO × 未驻留轨），把投递到任务
中心的异步收益整个吃掉。

本件处置（项目负责人裁 path_A）：投递的是 **零 IO 取数计划** ``SourcePlan``；
``resolve()`` 与逐轨分析全在 worker 的 ``run`` 内；LRU 驱逐 ``unload_inactive``
延后到 ``on_done`` 主线程回填之后 ⇒ worker 期不与主线程并发争改样本状态。

覆盖（每条都带反证）：
① 点「逐轨分析」到 submit 返回为止，主线程 ``load_full`` 调用数恒 0；
② 全部取数发生在非主线程；
③ ``unload_inactive`` 只在 worker 结束后、且只在主线程各发生一次（驱逐真生效）；
④ 投递物是 ``SourcePlan``（``resolve()`` 前零 IO）；
⑤ 未注入投递回调（裸面板）⇒ 原同步路径逐字不变。
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
from acouscope.ui.widgets.multitrack.analysis_source import SourcePlan
from acouscope.ui.widgets.multitrack.multitrack_view import MultitrackPanel
from acouscope.ui.widgets.multitrack.track_model import MultitrackSession, TrackModel

_SR = 8000
_DURATION = 2.0


def _wait_until(predicate, timeout_ms: int = 6000) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if predicate():
            return True
        QApplication.processEvents()
        time.sleep(0.005)
    return bool(predicate())


def _session(n: int = 3, *, max_loaded: int = 4) -> MultitrackSession:
    return MultitrackSession(
        max_loaded=max_loaded,
        metadata_reader=lambda p: {"sample_rate": _SR, "channels": 1,
                                   "duration": _DURATION},
        envelope_reader=lambda p, points: (
            np.linspace(0.0, _DURATION, points),
            np.full(points, 0.5, dtype=np.float32),
        ),
        loader=lambda p: (np.linspace(-0.3, 0.3, int(_SR * _DURATION)), _SR),
    )


def _tracks(n: int = 3, **kw) -> MultitrackSession:
    session = _session(n, **kw)
    for i in range(n):
        session.add_path(f"/tmp/m4_{i}.wav", label=f"m4track{i}")
    return session


class _PitchStub:
    times = np.linspace(0.0, 1.0, 8)
    f0_hz = np.full(8, 440.0)


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    controller = AppController()
    t = np.arange(_SR) / _SR
    controller.load_from_array(0.5 * np.sin(2 * np.pi * 440.0 * t), _SR)
    w = MainWindow(controller)
    monkeypatch.setattr(
        mw, "show_toast",
        lambda parent, message, level="info", duration=3500: None,
    )
    yield w
    w.close()


@pytest.fixture
def io_spy(monkeypatch):
    """记录 load_full / unload_inactive 的**线程归属 + 发生序**。"""
    events = []
    real_load = TrackModel.load_full
    real_unload = MultitrackSession.unload_inactive

    def load_full(self):
        events.append(("load_full", self.track_id, threading.current_thread().name))
        return real_load(self)

    def unload_inactive(self, keep=()):
        events.append(
            ("unload_inactive", tuple(keep), threading.current_thread().name)
        )
        return real_unload(self, keep)

    monkeypatch.setattr(TrackModel, "load_full", load_full)
    monkeypatch.setattr(MultitrackSession, "unload_inactive", unload_inactive)
    return events


def _kinds(events):
    return [name for name, _payload, _thread in events]


# ---------------------------------------------------------------------------
# ①② 主线程不再同步取数；取数全在 worker
# ---------------------------------------------------------------------------


def test_submit_path_does_no_main_thread_io(window, monkeypatch, io_spy):
    w = window
    panel = w.multitrack_panel
    panel.set_session(_tracks(3))
    panel.refresh_presentation()

    gate = threading.Event()
    real = asrc.run_analysis_on_tracks

    def runner(source, params):
        gate.wait(timeout=3.0)
        return _PitchStub()

    def wrapper(*args, **kwargs):
        kwargs["runner"] = runner
        return real(*args, **kwargs)

    monkeypatch.setattr(asrc, "run_analysis_on_tracks", wrapper)

    panel.compare_view.btn_analyze.click()
    # ★ 断链反证：若取数仍在 submit 前的主线程，此处会出现主线程 load_full 记录
    #   （worker 线程此刻可能已开跑 ⇒ 只按线程归属判，不按总时序判）
    main = threading.main_thread().name
    assert [e for e in io_spy if e[0] == "load_full" and e[2] == main] == []
    assert [e for e in io_spy if e[0] == "unload_inactive"] == []

    entry = w.task_center.entry(w._multitrack_analysis_task_id)
    assert entry is not None
    gate.set()
    assert _wait_until(lambda: entry.state == "done")

    loads = [e for e in io_spy if e[0] == "load_full"]
    assert len(loads) == 3, f"逐轨取数应恰 3 次（在 worker 内）：{loads}"
    assert all(thread != main for _n, _tid, thread in loads), (
        f"load_full 仍落在主线程：{loads}"
    )
    assert len({tid for _n, tid, _t in loads}) == 3                # 每轨各一次


def test_lru_eviction_deferred_to_main_thread_after_worker(window, monkeypatch, io_spy):
    """★ M4 线程安全核心：worker 期零驱逐；回填后主线程统一驱逐且真有效果。"""
    w = window
    panel = w.multitrack_panel
    session = _tracks(3, max_loaded=1)                             # 逼出驱逐
    panel.set_session(session)
    panel.refresh_presentation()

    gate = threading.Event()
    entered = []
    real = asrc.run_analysis_on_tracks

    def runner(source, params):
        entered.append(source.track_id)
        gate.wait(timeout=3.0)
        return _PitchStub()

    def wrapper(*args, **kwargs):
        kwargs["runner"] = runner
        return real(*args, **kwargs)

    monkeypatch.setattr(asrc, "run_analysis_on_tracks", wrapper)

    panel.compare_view.btn_analyze.click()
    entry = w.task_center.entry(w._multitrack_analysis_task_id)
    assert _wait_until(lambda: len(entered) == 1)                  # 首轨在途
    # worker 期间：驱逐一次都没跑（不与 worker 争改 _data/state）
    assert "unload_inactive" not in _kinds(io_spy)
    assert _kinds(io_spy) == ["load_full"] * 3                     # 取数已在 worker 跑完

    gate.set()
    assert _wait_until(lambda: entry.state == "done")

    main = threading.main_thread().name
    unloads = [e for e in io_spy if e[0] == "unload_inactive"]
    assert unloads, "on_done 未做 LRU 驱逐（延后回填缺位）"
    assert all(thread == main for _n, _p, thread in unloads), unloads
    kinds = _kinds(io_spy)
    split = kinds.index("unload_inactive")                         # 序：取数 → 驱逐
    assert kinds[:split] == ["load_full"] * 3
    assert set(kinds[split:]) == {"unload_inactive"}
    assert len(session.loaded_ids()) == 1                          # 驱逐真生效


# ---------------------------------------------------------------------------
# ④ 投递物 = 零 IO 计划
# ---------------------------------------------------------------------------


def test_analyze_all_delivers_zero_io_plan(qapp, io_spy):
    panel = MultitrackPanel(_tracks(3))
    seen = {}

    def fake_deliver(plan, kind, cache):
        seen["plan"] = plan
        seen["kind"] = kind
        # ★ 反证：投递时刻主线程未取一轨（否则计划形同虚设、仍是旧破口）
        assert _kinds(io_spy) == []
        return []

    panel.set_analysis_deliver(fake_deliver)
    assert panel.analyze_all(kind="pitch") == []
    plan = seen["plan"]
    assert isinstance(plan, SourcePlan)
    assert len(plan) == 3 and seen["kind"] == "pitch"
    assert _kinds(io_spy) == []                                    # resolve 前仍零 IO

    sources = plan.resolve()                                       # worker 侧才取数
    assert len(sources) == 3
    assert _kinds(io_spy) == ["load_full"] * 3
    assert all(len(src) == int(_SR * _DURATION) for src in sources)


# ---------------------------------------------------------------------------
# ⑤ 未注入投递回调 ⇒ 原同步路径逐字不变
# ---------------------------------------------------------------------------


def test_bare_panel_sync_path_unchanged(qapp, io_spy):
    panel = MultitrackPanel(_tracks(2))
    assert panel.analysis_deliver() is None
    handles = panel.analyze_all(kind="pitch", runner=lambda src, p: _PitchStub())
    assert [h.status for h in handles] == ["done", "done"]         # 主线程就地跑完
    assert _kinds(io_spy) == ["load_full", "load_full"]
    assert panel.compare_view.has_results() is True
