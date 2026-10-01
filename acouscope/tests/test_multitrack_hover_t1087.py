# SPDX-License-Identifier: GPL-3.0-only
"""T-1087 M3（N4 hover）：多轨呈现带的悬停读数接到状态栏（复用单轨 Pδ 注入器）。

现状：`ComparePresentWidget._hover_update` → `hover_readout_at` → `_on_hover_readout`
链在部件内已完整，但宿主从未注入回调 ⇒ 多轨态悬停只有右上角 overlay、状态栏不响应。
本件按单轨同款口径注入（`_inject_hover_readout`），**注入对象仅 compare_view**：
波形区 `MultitrackView.mouseMoveEvent` 无 hover 产出源，造读数属新增功能（越 `L-3`）。

覆盖含**反证**：撤掉注入 ⇒ 悬停不再改状态栏（证明是接线起效、不是别处顺带刷的）；
鼠标离开 ⇒ 临时段回到 D4「轨 N/M」而非被清空。
"""

import time

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from acouscope.app.controller import AppController
from acouscope.i18n import set_language, tr
from acouscope.ui.main_window import MainWindow
from acouscope.ui.widgets.multitrack.analysis_source import TrackResultCache
from acouscope.ui.widgets.multitrack.track_model import MultitrackSession

_SR = 8000


def _wait_until(predicate, timeout_ms: int = 6000) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if predicate():
            return True
        QApplication.processEvents()
        time.sleep(0.005)
    return bool(predicate())


class _PitchStub:
    def __init__(self, times, f0_hz):
        self.times = np.asarray(times, dtype=float)
        self.f0_hz = np.asarray(f0_hz, dtype=float)


def _session(n=2, duration=2.0):
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
        session.add_path(f"/tmp/hover{i}.wav", label=f"track{i}")
    return session


def _seeded_cache(session):
    """两轨已知 F0（220 / 330 Hz）⇒ 差异可用 ⇒ 悬停读数非空。"""
    cache = TrackResultCache()
    times = np.linspace(0.0, 1.5, 30)
    for index, freq in enumerate((220.0, 330.0)):
        cache.put(
            TrackResultCache.key(session.tracks()[index].track_id, "pitch", None),
            _PitchStub(times, np.full(30, freq)),
        )
    return cache


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
    yield w
    w.close()


@pytest.fixture
def hovered(qapp, window):
    """进多轨态 + 两轨 F0 结果 + 差异**已回填终态**，返回 ``(window, compare_view)``。

    ★ 宿主已接 M7 投递器 ⇒ ``compute_diff()`` 是 fire-and-forget（同步返回 None）；
    悬停读数要有值，必须先把后台任务等到终态。
    """
    w = window
    session = _session(2)
    w.multitrack_panel.set_session(session)
    w.multitrack_panel.set_result_cache(_seeded_cache(session))
    w._enter_multitrack_mode()
    view = w.multitrack_panel.compare_view
    view.resize(480, 260)
    view.set_view_range(0.0, 1.5)
    view.compute_diff()
    assert _wait_until(lambda: view.diff() is not None)
    return w, view


def _hover(view, x):
    """绕过 20Hz 节流，走真实悬停入口（`_hover_update`）。"""
    view._last_hover_at = 0.0
    view._hover_update(x)


# ---------------------------------------------------------------------------
# ① 注入面：只注 compare_view，波形区不造第二套读数
# ---------------------------------------------------------------------------


def test_hover_callback_injected_into_compare_presentation_only(window):
    w = window
    panel = w.multitrack_panel
    assert panel.compare_view._on_hover_readout == w._on_view_hover_readout
    # ★ 反向：波形区（MultitrackView）无 hover 源 ⇒ 宿主不得向其注入
    assert not hasattr(panel.view, "_on_hover_readout")


# ---------------------------------------------------------------------------
# ② 悬停 → 状态栏临时段（并证明"是这条接线起效"）
# ---------------------------------------------------------------------------


def test_hover_writes_status_temporary_segment(hovered):
    w, view = hovered
    seg = w.status_segments
    x = view.x_at(0.6)
    expected = view.hover_readout_at(view.t_at(x))
    assert expected and "t=0.600s" in expected

    _hover(view, x)
    assert seg._temp_label.text() == expected                     # 读数进状态栏
    assert view._hover_overlay.text() == expected                 # overlay 同值（既有行为）


def test_hover_without_injection_leaves_status_untouched(hovered):
    """反证：撤掉注入回调 ⇒ 悬停不得改状态栏（否则本例假绿）。"""
    w, view = hovered
    seg = w.status_segments
    before = seg._temp_label.text()
    view._on_hover_readout = None
    _hover(view, view.x_at(0.6))
    assert seg._temp_label.text() == before


def test_mouse_leave_restores_multitrack_status_not_blank(hovered):
    """离开 ⇒ 临时段回到 D4「轨 N/M · 健康提示」，不是清空。"""
    w, view = hovered
    seg = w.status_segments
    _hover(view, view.x_at(0.9))
    assert "t=0.900s" in seg._temp_label.text()

    view._hover_clear()
    text = seg._temp_label.text()
    assert "t=0.900s" not in text
    assert tr("multitrack.status").split("{")[0].strip() in text  # 轨 N/M 回来
    assert text != ""


def test_readout_none_outside_multitrack_still_clears(hovered):
    """单轨态原语义零扰动：无读数 ⇒ 清空临时段（不回灌多轨状态文案）。"""
    w, view = hovered
    seg = w.status_segments
    w._exit_multitrack_mode()
    seg.set_temporary_text("probe")
    view._on_hover_readout(None)
    assert seg._temp_label.text() == ""
    assert w._multitrack_mode is False
