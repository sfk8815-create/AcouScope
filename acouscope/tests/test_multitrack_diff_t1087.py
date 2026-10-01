# SPDX-License-Identifier: GPL-3.0-only
"""T-1087 M7：多轨差异量化经任务中心后台化（set_tuning 自动触发不再阻塞主线程）。

现状：``compare_present.compute_diff`` → ``compare_diff`` 逐轨全样本帧循环
（~12000 帧/分/轨）在**主线程**跑；触发面除「差异统计」按钮外，还有宿主
``_apply_tuning_overlay`` → ``set_tuning`` 的**律制推送自动触发**（收益锚点）。

处置（同构投递包裹）：接了投递器 ⇒ 帧循环进 worker、主线程只排期，终态由
``on_done`` 回填；未注入（裸部件 / 离屏单测）⇒ 原同步口径**逐字不变**
（``compute_diff`` 返回值与签名由 ``test_tuning_present_link`` 静态冻结）。

覆盖含反证：① 裸部件仍就地算；② 在途期未回填 + 连点不重投；③ 取数帧循环发生在
非主线程且 ``set_tuning`` 立即返回；④ 世代作废（在途期间轨集变化 ⇒ 脏结果不回填）；
⑤ 导出这条路仍拿得到表。
"""

import threading
import time

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from acouscope.analysis.tunings.templates import get_template
from acouscope.app.controller import AppController
from acouscope.i18n import set_language, tr
from acouscope.ui.main_window import MainWindow
from acouscope.ui.widgets.multitrack import compare_diff
from acouscope.ui.widgets.multitrack.analysis_source import TrackResultCache
from acouscope.ui.widgets.multitrack.compare_present import ComparePresentWidget
from acouscope.ui.widgets.multitrack.track_model import MultitrackSession

_SR = 8000


class _PitchStub:
    def __init__(self, times, f0_hz):
        self.times = np.asarray(times, dtype=float)
        self.f0_hz = np.asarray(f0_hz, dtype=float)


def _session(n=2, duration=1.0, loaded=True):
    session = MultitrackSession(
        metadata_reader=lambda p: {"sample_rate": _SR, "channels": 1,
                                   "duration": duration},
        envelope_reader=lambda p, points: (
            np.linspace(0.0, duration, points),
            np.full(points, 0.5, dtype=np.float32),
        ),
        loader=lambda p: (np.linspace(-0.3, 0.3, int(_SR * duration)), _SR),
    )
    for i in range(n):
        session.add_path(f"/tmp/m7_{i}.wav", label=f"m7track{i}")
    if loaded:
        for track in session.tracks():
            track.load_full()                      # 让 rms 数据源可用（差异含电平项）
    return session


def _cache(session):
    cache = TrackResultCache()
    times = np.linspace(0.0, 1.0, 40)
    for index, freq in enumerate((220.0, 330.0)):
        cache.put(
            TrackResultCache.key(session.tracks()[index].track_id, "pitch", None),
            _PitchStub(times, np.full(40, freq)),
        )
    return cache


def _wait_until(predicate, timeout_ms: int = 6000) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if predicate():
            return True
        QApplication.processEvents()
        time.sleep(0.005)
    return bool(predicate())


@pytest.fixture
def gated_rms(monkeypatch):
    """卡住 ``overall_rms_db``（差异里的重帧循环），并记录其执行线程。"""
    threads = []
    gate = threading.Event()
    real = compare_diff.overall_rms_db

    def spy(audio, sample_rate, **kwargs):
        threads.append(threading.current_thread().name)
        gate.wait(timeout=4.0)
        return real(audio, sample_rate, **kwargs)

    monkeypatch.setattr(compare_diff, "overall_rms_db", spy)
    return gate, threads


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    set_language("zh_CN")
    controller = AppController()
    t = np.arange(_SR) / _SR
    controller.load_from_array(0.4 * np.sin(2 * np.pi * 440 * t), _SR)
    w = MainWindow(controller)
    import acouscope.ui.main_window as _mw

    monkeypatch.setattr(
        _mw, "show_toast",
        lambda parent, message, level="info", duration=3500: None,
    )
    session = _session(2)
    w.multitrack_panel.set_session(session)
    w.multitrack_panel.set_result_cache(_cache(session))
    w.multitrack_panel.refresh_presentation()
    yield w
    w.close()


# ---------------------------------------------------------------------------
# ① 裸部件：未注入投递器 ⇒ 原同步口径逐字不变
# ---------------------------------------------------------------------------


def test_bare_widget_still_computes_inline(qapp):
    session = _session(2)
    widget = ComparePresentWidget(session, _cache(session))
    widget.refresh()
    assert widget.diff_deliver() is None
    assert widget.diff_inflight() is False
    summary = widget.compute_diff()
    assert summary is not None and summary.tracks
    assert widget.diff() is summary                          # 返回值契约保留
    assert widget.btn_diff_csv.isEnabled() is True


# ---------------------------------------------------------------------------
# ② 接宿主：投递 + 在途未回填 + 连点不重投 + 终态回填
# ---------------------------------------------------------------------------


def test_diff_submits_backfills_and_debounces(window, gated_rms, qapp):
    w = window
    gate, threads = gated_rms
    view = w.multitrack_panel.compare_view

    view.btn_diff_stats.click()
    assert w.task_center.active_count() == 1
    assert view.diff_inflight() is True
    assert view.diff() is None                               # ★ 在途：尚未回填
    assert view.btn_diff_csv.isEnabled() is False
    view.btn_diff_stats.click()
    view.btn_diff_stats.click()
    assert w.task_center.active_count() == 1                 # ★ 连点不重投

    gate.set()
    assert _wait_until(lambda: view.diff() is not None)
    assert view.diff_inflight() is False
    assert view.btn_diff_csv.isEnabled() is True             # 导出可用性回填
    assert tr("multitrack.compare.diff_summary").split("{")[0].strip() \
        in view.lbl_hint.text()                              # 摘要 hint 回填
    readout = view.hover_readout_at(0.5)
    assert readout and "t=0.500s" in readout                 # 悬停读数可用


# ---------------------------------------------------------------------------
# ③ set_tuning 自动触发：主线程立即返回，帧循环在 worker
# ---------------------------------------------------------------------------


def test_set_tuning_returns_immediately_and_runs_off_main_thread(window, gated_rms):
    w = window
    gate, threads = gated_rms
    view = w.multitrack_panel.compare_view

    started = time.monotonic()
    view.set_tuning(get_template("12tet"))                   # 宿主律制推送同一路径
    elapsed = time.monotonic() - started
    assert elapsed < 0.5, f"set_tuning 仍阻塞主线程 {elapsed:.2f}s"
    assert view.diff() is None                               # 未同步出结果
    assert view.diff_inflight() is True

    gate.set()
    assert _wait_until(lambda: view.diff() is not None)
    main = threading.main_thread().name
    assert threads and all(name != main for name in threads), threads
    degrees = np.asarray(view.diff().tracks[0].degrees, dtype=int)
    assert degrees.size == 40                                # 带律制的终态结果


# ---------------------------------------------------------------------------
# ④ 世代作废：在途期间轨集变化 ⇒ 脏结果不回填
# ---------------------------------------------------------------------------


def test_stale_inflight_result_is_dropped_after_refresh(window, gated_rms):
    w = window
    gate, _threads = gated_rms
    view = w.multitrack_panel.compare_view

    view.btn_diff_stats.click()
    assert view.diff_inflight() is True
    view.refresh()                                           # 轨集/序列重建 → 作废
    assert view._diff_gen >= 1
    gate.set()
    assert _wait_until(lambda: not view.diff_inflight())
    assert view.diff() is None                               # ★ 脏结果被丢弃
    assert view.btn_diff_csv.isEnabled() is False


# ---------------------------------------------------------------------------
# ⑤ 导出这条路仍拿得到表（一次性主动动作 ⇒ 就地算）
# ---------------------------------------------------------------------------


def test_export_builds_table_even_with_deliver_injected(window, tmp_path, qapp):
    w = window
    view = w.multitrack_panel.compare_view
    assert view.diff_deliver() is not None
    assert view.diff() is None
    target = tmp_path / "diff.csv"

    written = view.export_diff_csv(target)
    assert written == str(target)
    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) > 1 and lines[0].startswith("track")   # 表头 + 数据行
    assert view.diff() is not None                           # 顺带回填


def test_diff_task_title_key_in_three_languages():
    import acouscope.i18n as i18n

    entry = i18n._STRINGS.get("task_center.title.multitrack_diff")
    assert entry, "缺 i18n 键: task_center.title.multitrack_diff"
    assert set(entry) == {"en_US", "zh_CN", "zh_TW"}
    assert all(str(v).strip() for v in entry.values())
