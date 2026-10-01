# SPDX-License-Identifier: GPL-3.0-only
"""T-1087 M6：一键自动对齐经任务中心 fire-and-forget（真异步·防抖·回填）。

改前：``MultitrackPanel.auto_align`` 同步跑 ``align_session``（逐轨 ``load_full``
+ ``align.frame_db_curve`` 帧循环，8 轨 × 3min ≈ 10⁵ 帧）⇒ 点一下 UI 冻一截。
改后（指挥裁）：投递任务中心 ⇒ **返回值语义随之改变**（不再是 ``AlignResult``，
而是投递句柄；终态结果读 ``panel.align_result()``），既有 ``test_multitrack_align``
的两处返回值断言已按令同改（保判别力）。

覆盖（含反证）：
① 点钮即返回、任务在途，**此刻**偏移与轨道头尚未变（真异步，非同步冒充）；
② 取数/检测发生在非主线程；
③ 在途连点不重投（任务恰 1）；
④ 终态后回填：``align_result`` + 会话偏移 + 轨道头 + 门闩复位，且可再次投递；
⑤ 宿主已接投递器（``align_deliver``）+ 新 i18n 三语键。
"""

import threading
import time

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from acouscope.app.controller import AppController
from acouscope.i18n import set_language, tr
from acouscope.ui.main_window import MainWindow
from acouscope.ui.widgets.multitrack.track_model import MultitrackSession

SR = 8000
AMP = 0.5


def _wait_until(predicate, timeout_ms: int = 6000) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if predicate():
            return True
        QApplication.processEvents()
        time.sleep(0.005)
    return bool(predicate())


def _tone(n, amp=AMP, freq=440.0):
    t = np.arange(int(n), dtype=np.float64) / float(SR)
    return amp * np.sin(2.0 * np.pi * freq * t)


def _clip(onset_s, dur_s=1.0):
    return np.concatenate([
        np.zeros(int(round(SR * onset_s)), dtype=np.float64),
        _tone(int(round(SR * dur_s))),
    ])


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    set_language("zh_CN")
    controller = AppController()
    t = np.arange(SR) / SR
    controller.load_from_array(0.4 * np.sin(2 * np.pi * 440 * t), SR)
    w = MainWindow(controller)
    import acouscope.ui.main_window as _mw

    monkeypatch.setattr(
        _mw, "show_toast",
        lambda parent, message, level="info", duration=3500: None,
    )
    yield w
    w.close()


@pytest.fixture
def gated(monkeypatch):
    """两轨会话（late 0.30s / early 0.0s）+ 卡住取数的门闩与线程记录。"""
    table = {"/tmp/m6_late.wav": _clip(0.30), "/tmp/m6_early.wav": _clip(0.0)}
    threads = []
    gate = threading.Event()

    def loader(path):
        threads.append(threading.current_thread().name)
        gate.wait(timeout=4.0)
        return table[str(path)], SR

    session = MultitrackSession(
        metadata_reader=lambda p: {"sample_rate": SR, "channels": 1, "duration": 1.0},
        envelope_reader=lambda p, points: (
            np.linspace(0.0, 1.0, points), np.full(points, 0.5, dtype=np.float32)
        ),
        loader=loader,
    )
    for name in table:
        session.add_path(name, label=name.rsplit("/", 1)[-1][:-4])
    return session, gate, threads


def _armed(window, qapp, gated):
    session, gate, threads = gated
    window.multitrack_panel.set_session(session)
    window.multitrack_panel.refresh_presentation()
    return session, gate, threads


# ---------------------------------------------------------------------------
# ①② 真异步：点钮即在途、未回填，取数在非主线程
# ---------------------------------------------------------------------------


def test_auto_align_is_fire_and_forget_and_off_main_thread(window, qapp, gated):
    session, gate, threads = _armed(window, qapp, gated)
    panel = window.multitrack_panel
    late = session.tracks()[0].track_id
    header = panel.header_column.header_for(late)
    main = threading.main_thread().name

    panel.btn_align.click()
    assert window.task_center.active_count() == 1                  # 已投递
    assert panel.align_inflight() is True
    assert panel.align_result() is None                            # ★ 尚未回填
    assert session.get(late).offset_ms == 0.0                      # 会话偏移未动
    assert header.offset_ms() == 0.0                               # 轨道头未动
    assert _wait_until(lambda: len(threads) >= 1)
    assert all(name != main for name in threads), threads          # ★ 取数在 worker

    gate.set()
    assert _wait_until(lambda: not panel.align_inflight())
    result = panel.align_result()
    assert result is not None
    assert result.reference_id == session.tracks()[1].track_id     # 最早发声轨
    assert session.get(late).offset_ms == pytest.approx(-300)
    assert panel.header_column.header_for(late).offset_ms() == pytest.approx(-300)
    assert panel.header_column.header_for(late).align_state() == "detected"


# ---------------------------------------------------------------------------
# ③ 在途连点不重投
# ---------------------------------------------------------------------------


def test_debounce_does_not_resubmit_while_in_flight(window, qapp, gated):
    session, gate, threads = _armed(window, qapp, gated)
    panel = window.multitrack_panel

    panel.btn_align.click()
    assert _wait_until(lambda: len(threads) >= 1)
    panel.btn_align.click()
    panel.btn_align.click()
    panel.auto_align()
    assert window.task_center.active_count() == 1                  # ★ 恰 1 条
    entry = window.task_center.running_entries()[0]
    assert entry.title == tr("task_center.title.multitrack_align").format(n=2)

    gate.set()
    assert _wait_until(lambda: entry.state == "done")
    assert panel.align_inflight() is False
    # 终态后门闩已解 ⇒ 可再次投递（幂等覆盖；门闩不复位即为本例要抓的 bug）
    panel.auto_align()
    assert window.task_center.active_count() == 1
    second = window.task_center.running_entries()[0]
    assert second.task_id != entry.task_id
    assert _wait_until(lambda: second.state == "done")
    assert panel.align_result() is not None


# ---------------------------------------------------------------------------
# ④ 防御与接线
# ---------------------------------------------------------------------------


def test_auto_align_without_tracks_submits_nothing(window, qapp):
    panel = window.multitrack_panel
    panel.set_session(MultitrackSession(
        metadata_reader=lambda p: {"sample_rate": SR, "channels": 1, "duration": 1.0},
        envelope_reader=lambda p, points: (np.zeros(points), np.zeros(points)),
        loader=lambda p: (np.zeros(SR), SR),
    ))
    assert panel.auto_align() is None
    assert window.task_center.active_count() == 0                  # 不占调度额度
    assert panel.align_result() is None


def test_host_injects_align_deliverer(window):
    panel = window.multitrack_panel
    assert panel.align_deliver() == window._deliver_multitrack_task
    assert panel.analysis_deliver() == window._deliver_multitrack_analysis
    assert panel.compare_view.diff_deliver() == window._deliver_multitrack_task


def test_align_task_title_key_in_three_languages():
    import acouscope.i18n as i18n

    entry = i18n._STRINGS.get("task_center.title.multitrack_align")
    assert entry, "缺 i18n 键: task_center.title.multitrack_align"
    assert set(entry) == {"en_US", "zh_CN", "zh_TW"}
    assert all(str(v).strip() for v in entry.values())
    assert "{n}" in entry["zh_CN"]
