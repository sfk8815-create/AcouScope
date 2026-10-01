# SPDX-License-Identifier: GPL-3.0-only
"""T-1089 N-A 停并报**取证档**（本件未落地变体 b·档内全部断言当树为真）。

令文 N-A 变体 b 的落点（``refresh`` 末 ``_invalidate_diff()`` 后追加
``if self._diff_deliver is not None: self.compute_diff()``）经离屏真宿主探针 + 本档坐实
**两个硬阻断**，任一都越出授权面 ⇒ 按 C-4③/④ 停并报，未擅自扩面：

① **宿主呈现带的 refresh 是"两次突发"**：``MultitrackPanel.refresh_presentation()``
   = ``compare_view.set_session()``（内部 refresh）+ ``compare_view.refresh()`` ⇒
   每次入口触发 ``compare_present.refresh`` **恰 2 次**、``_diff_gen`` **+2**。
   第一击的自动投被第二击的 ``_invalidate_diff()`` 作废，第二击又被 M7 在途门闩挡回
   ⇒ 真宿主路径（进多轨态 / 分析 on_done / 偏移微调）上"自动出"**恒为空**（本档例 ③④）。
   修法只有两处，均在禁碰/未授权面：``multitrack_view.py`` 去掉那一次冗余 refresh
   （禁碰九档 R-1），或把 ``_submit_diff`` 升级成"来路 + 输入签名 + settle 后按签名补投"
   （须同时改 ``test_multitrack_diff_t1087.py`` ④ 的「在途 refresh ⇒ 结果必丢弃且不补算」断言）。
② **反而吞掉用户主动点钮**：突发在途期间点「差异统计」被同一门闩挡回，且该在途任务
   依令文口径必被作废 ⇒ 落地变体 b 会把"点了没反应"引入主路径（本档例 ⑤），
   净效果劣于现状（现状该点击立即就地/后台算出）。

因此本档**不**断言 ``refresh`` 后 ``diff() is not None``（那是解阻后的验收判据，已在
报告与例 ④ 的对照里写明），只把上述现状钉成回归锚点。
"""

from __future__ import annotations

import time

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from acouscope.ui.widgets.multitrack.analysis_source import TrackResultCache
from acouscope.ui.widgets.multitrack.compare_present import ComparePresentWidget
from acouscope.ui.widgets.multitrack.track_model import MultitrackSession

_SR = 8000


class _PitchStub:
    def __init__(self, times, f0_hz):
        self.times = np.asarray(times, dtype=float)
        self.f0_hz = np.asarray(f0_hz, dtype=float)


def _session(n=2, duration=1.5, sr=_SR) -> MultitrackSession:
    session = MultitrackSession(
        metadata_reader=lambda p: {"sample_rate": sr, "channels": 1,
                                   "duration": duration},
        envelope_reader=lambda p, points: (
            np.linspace(0.0, duration, points),
            np.full(points, 0.5, dtype=np.float32),
        ),
        loader=lambda p: (np.linspace(-0.3, 0.3, int(sr * duration)), sr),
    )
    for index in range(n):
        session.add_path(f"/tmp/t1089a{index}.wav", label=f"track{index}")
    return session


def _cache(session, *, offset_cents=80.0) -> TrackResultCache:
    cache = TrackResultCache()
    times = np.linspace(0.0, 1.5, 30)
    freqs = (440.0, 440.0 * (2.0 ** (offset_cents / 1200.0)))
    for index, freq in enumerate(freqs):
        cache.put(
            TrackResultCache.key(session.tracks()[index].track_id, "pitch", None),
            _PitchStub(times, np.full(30, freq)),
        )
    return cache


class _DeferredDeliver:
    """替身投递器：收下任务不跑（模拟 worker 在途）·settle 次序同宿主。"""

    def __init__(self):
        self.titles: list[str] = []
        self._pending: list[tuple] = []

    def __call__(self, title, work, on_done, on_settle):
        self.titles.append(str(title))
        self._pending.append((work, on_done, on_settle))
        return len(self.titles)

    @property
    def submitted(self) -> int:
        return len(self.titles)

    def settle_all(self) -> int:
        pending, self._pending = self._pending, []
        for work, on_done, on_settle in pending:
            result = work(None)
            on_settle()
            on_done(result)
        return len(pending)


def _wait_until(predicate, timeout_ms: int = 4000) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if predicate():
            return True
        QApplication.processEvents()
        time.sleep(0.005)
    return bool(predicate())


@pytest.fixture
def host(qapp, monkeypatch, tmp_path):
    """真宿主：MainWindow + 任务中心投递链（不 show）。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow

    controller = AppController()
    t = np.arange(_SR) / _SR
    controller.load_from_array(0.4 * np.sin(2 * np.pi * 440 * t), _SR)
    window = MainWindow(controller)
    monkeypatch.setattr(
        "acouscope.ui.main_window.show_toast",
        lambda parent, message, level="info", duration=3500: None,
    )
    session = _session(2)
    panel = window.multitrack_panel
    panel.set_session(session)                       # 此刻缓存为空 ⇒ 不产生任务
    panel.set_result_cache(_cache(session))          # ★ 有结果 ⇒ 呈现带就绪
    yield window, panel.compare_view, session
    window.close()


# ---------------------------------------------------------------------------
# ① 裸部件旧契约（变体 b 亦不得破·当树逐字不变）
# ---------------------------------------------------------------------------


def test_bare_widget_refresh_never_computes_diff(qapp):
    session = _session(2)
    widget = ComparePresentWidget(session, _cache(session))
    widget.resize(480, 260)
    assert widget.diff_deliver() is None
    widget.refresh()
    assert widget.diff() is None
    assert widget.diff_inflight() is False
    assert widget.btn_diff_csv.isEnabled() is False
    assert widget.hover_readout_at(0.5) == ""
    widget.btn_diff_stats.click()                    # 手动路径仍立即算出
    assert widget.diff() is not None
    widget.refresh()
    assert widget.diff() is None                     # test_multitrack_diff.py:553 契约


# ---------------------------------------------------------------------------
# ② 现状缺口：宿主注入态 refresh 后差异仍空（N-A 要修的正是这里）
# ---------------------------------------------------------------------------


def test_host_state_refresh_still_leaves_diff_empty(qapp):
    session = _session(2)
    deliver = _DeferredDeliver()
    widget = ComparePresentWidget(session, _cache(session))
    widget.resize(480, 260)
    widget.set_diff_deliver(deliver)
    widget.refresh()
    widget.refresh()
    assert deliver.submitted == 0                    # ★ refresh 不重算（现状）
    assert widget.diff() is None
    widget.btn_diff_stats.click()                    # 只有点钮才投
    assert deliver.submitted == 1
    deliver.settle_all()
    assert widget.diff() is not None


# ---------------------------------------------------------------------------
# ③ 阻断点①·取证：呈现带 refresh 是"两次突发"（世代 +2）
# ---------------------------------------------------------------------------


def test_presentation_band_refresh_is_a_two_refresh_burst(host):
    window, view, session = host
    calls = []
    real = view.refresh

    def spy():
        calls.append(view._diff_gen)
        real()

    view.refresh = spy
    window.multitrack_panel.refresh_presentation()
    assert len(calls) == 2, f"呈现带入口应触发两次 refresh·实为 {calls}"
    assert calls[1] - calls[0] >= 1                  # 第二击再作废一次
    assert view._diff_gen >= calls[1] + 1            # ⇒ 第一击的自动投必被世代丢弃


# ---------------------------------------------------------------------------
# ④ 阻断点①·对照：单次 compute_diff 能走到终态；紧跟一次 refresh 即被作废
# ---------------------------------------------------------------------------


def test_single_compute_reaches_terminal_state_in_host(host):
    _window, view, _session = host
    assert view.diff_deliver() is not None
    view.compute_diff()                              # 变体 b 想自动做的那一步
    assert _wait_until(lambda: view.diff() is not None)
    assert view.diff().has_data()
    assert view.btn_diff_csv.isEnabled() is True     # ★ 投递缝本身可达终态


def test_refresh_burst_drops_the_auto_submission_in_host(host):
    _window, view, _session = host
    view.compute_diff()                              # 模拟"refresh 末自动投"第一击
    assert view.diff_inflight() is True
    view.refresh()                                   # ★ 同突发第二击：作废 + 门闩挡回
    assert _wait_until(lambda: not view.diff_inflight())
    assert view.diff() is None                       # 结果被世代丢弃 ⇒ 无人补算
    view.compute_diff()                              # 下一次状态变化才自愈
    assert _wait_until(lambda: view.diff() is not None)


# ---------------------------------------------------------------------------
# ⑤ 阻断点②·危害：突发在途期用户主动点钮被同一门闩吞掉
# ---------------------------------------------------------------------------


def test_user_click_inside_refresh_burst_is_swallowed(host):
    _window, view, _session = host
    view.compute_diff()                              # 第一击的自动投（依令文必被作废）
    view.refresh()                                   # 第二击：作废 + 挡回重投
    view.btn_diff_stats.click()                      # 用户主动点 ⇒ 仍在途 ⇒ 被挡
    assert view.diff_inflight() is True
    assert _wait_until(lambda: not view.diff_inflight())
    assert view.diff() is None                       # ★ 点钮无果（现状不会如此）
