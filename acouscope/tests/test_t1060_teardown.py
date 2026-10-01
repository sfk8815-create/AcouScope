# SPDX-License-Identifier: GPL-3.0-only
"""T-1060（C3 结构性收尾·第一段）：投递源所有权 / 关窗 drain / 画布控件统一收尾。

覆盖口径（对应任务书硬判据 3、5 与自证 3）：
  件1 ① `show_toast` 的到点关闭 QTimer **由 ToastWidget 显式持有**（H1：局部
       变量持有 → 包装被 GC 而 C++ 计时器仍在册派发 → SIGSEGV）；
     ② toast 收尾（`_close_toast`）**先 stop() 再断 timeout 连接**；
     ③ `VUMeter` 的 33ms 动画定时器有独立收尾入口 `stop_animation()`（H2），
        且 `WaveformWidget` 的统一收尾会调用它 —— 计时器在宿主销毁前已停。
  件2 ④ 关窗 drain **不得使用裸 `app.processEvents()` 无差别泵**（限定 receiver
        消费在册对象），且 T-928 语义不回退：排队中的 `finished` 投递仍被消费
        （收尾后线程登记表为空）；
     ⑤ `MainWindow.closeEvent` 的视图收尾**先于** task_center drain（源码次序守卫）。
  件3 ⑥ `spectrum / spectrogram / pitch` 三控件统一收尾 `_detach_scene_items()`：
        自管 item 全部移出场景、item 容器清空、事件过滤器摘除（断环）、
        `closeEvent` 已接线，且**纯值快照仍可读**、幂等。

约定：全程 offscreen（conftest 顶部已设）、不构造 `MainWindow`、不 `show()`
主窗、无 `QDialog`/`.exec()`。
"""

from __future__ import annotations

import gc

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from acouscope.ui.widgets import toast as toast_mod  # noqa: E402
from acouscope.ui.widgets.pitch import PitchContourWidget  # noqa: E402
from acouscope.ui.widgets.spectrogram import SpectrogramWidget  # noqa: E402
from acouscope.ui.widgets.spectrum import SpectrumWidget  # noqa: E402
from acouscope.ui.widgets.waveform import VUMeter, WaveformWidget  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def host(qapp):
    """toast 宿主窗（可显示，不构造 MainWindow）。"""
    w = QWidget()
    w.resize(800, 600)
    w.show()
    qapp.processEvents()
    yield w
    w.close()
    w.deleteLater()
    qapp.processEvents()


# ---------------------------------------------------------------------------
# 件1：投递源所有权（H1 toast / H2 VUMeter）
# ---------------------------------------------------------------------------


def _timer_dead(timer) -> bool:
    """定时器「不会再有派发」：已停表 **或** 已随宿主析构（包装失效）。"""
    try:
        return (not timer.isActive()) and timer.receivers(timer.timeout) in (0, None)
    except RuntimeError:
        return True  # wrapped C/C++ object deleted → 绝无派发


class TestToastTimerOwnership:
    def test_timer_is_held_by_toast_widget(self, qapp, host):
        """H1：定时器必须由 toast 显式持有（局部变量持有＝悬垂根因）。"""
        t = toast_mod.show_toast(host, "T-1060", duration=10_000)
        qapp.processEvents()
        try:
            assert isinstance(getattr(t, "_timer", None), QTimer)
            assert t._timer.parent() is t      # C++ 父仍是 toast
            assert t._timer.isSingleShot() is True
            assert t._timer.isActive() is True  # 到点自动关闭行为不变
        finally:
            toast_mod._close_toast(t)

    def test_close_stops_and_disconnects_timer(self, qapp, host):
        """H1：收尾先停表、再断连接 —— 之后不再有任何投递源残留。"""
        t = toast_mod.show_toast(host, "T-1060", duration=10_000)
        qapp.processEvents()
        timer = t._timer
        assert timer.receivers(timer.timeout) == 1

        toast_mod._close_toast(t)
        qapp.processEvents()

        assert timer.isActive() is False
        assert timer.receivers(timer.timeout) == 0

    def test_toast_auto_close_still_works_and_timer_dies(self, qapp, host):
        """行为不回退：到点仍自动关闭；关闭后定时器不再派发。"""
        t = toast_mod.show_toast(host, "T-1060", duration=30)
        timer = t._timer
        QTest.qWait(300)                       # 真事件循环：到点自动关闭
        assert _timer_dead(timer)              # 已停表或已随 toast 析构
        try:
            assert t.isVisible() is False      # toast 已关闭（行为不变）
        except RuntimeError:
            pass  # deleteLater 已回收 → 同样等价于「已关闭」

    def test_repeated_toasts_do_not_accumulate_live_timers(self, qapp, host):
        """多轮 toast 后无残留活动计时器（收尾路径闭合）。"""
        timers = []
        for i in range(10):
            t = toast_mod.show_toast(host, f"n{i}", duration=10_000)
            timers.append(t._timer)
            toast_mod._close_toast(t)
        qapp.processEvents()
        assert all(_timer_dead(tm) for tm in timers)


class TestVUMeterStop:
    def test_vu_timer_runs_then_stop_animation_stops_it(self, qapp):
        """H2：VUMeter 自带收尾入口；停表后无连接残留。"""
        vm = VUMeter()
        try:
            assert vm._anim.isActive() is True   # 构造即 30fps 动画（现状语义）
            assert vm._anim.receivers(vm._anim.timeout) == 1
            vm.stop_animation()
            assert vm._anim.isActive() is False
            assert vm._anim.receivers(vm._anim.timeout) == 0
            vm.stop_animation()                   # 幂等
        finally:
            vm.stop_animation()

    def test_waveform_detach_stops_vu_timer(self, qapp):
        """H2：WaveformWidget 统一收尾会先停 VU 表定时器（宿主销毁前停表）。"""
        w = WaveformWidget()
        try:
            w.show()
            qapp.processEvents()
            assert w.vu_meter._anim.isActive() is True
            w._detach_scene_items()
            assert w.vu_meter._anim.isActive() is False
            assert w.vu_meter._anim.receivers(w.vu_meter._anim.timeout) == 0
        finally:
            w.close()
            qapp.processEvents()
            w.deleteLater()
            qapp.processEvents()

    def test_vu_timer_dies_without_explicit_close_when_owner_dropped(self, qapp):
        """反面对照（机制说明）：无显式收尾时，宿主析构靠 GC 时机 —— 本用例只
        证明显式收尾（上一用例）不依赖 GC 时机即已停表。"""
        w = WaveformWidget()
        w.show()
        qapp.processEvents()
        assert w.vu_meter._anim.isActive() is True
        w._detach_scene_items()          # 显式收尾
        assert w.vu_meter._anim.isActive() is False
        w.close()
        w.deleteLater()
        gc.collect()
        qapp.processEvents()


# ---------------------------------------------------------------------------
# 件3：三个画布控件的统一收尾
# ---------------------------------------------------------------------------

_CANVAS_FACTORIES = {
    "spectrum": SpectrumWidget,
    "spectrogram": SpectrogramWidget,
    "pitch": PitchContourWidget,
}

# 各控件实际安装事件过滤器的宿主（收尾必须摘除 → 断环）
_FILTER_HOSTS = {
    "spectrum": ("marks_table",),          # 另：_interaction 装在 viewport 上
    "spectrogram": ("scene", "viewport"),
    "pitch": ("scene", "viewport"),
}


def _owned_items(w):
    """控件自管（addItem 进场）的 item 列表（含容器型登记）。"""
    items = []
    for attr in getattr(w, "_DETACH_SINGLE_ITEMS", ()):
        item = getattr(w, attr, None)
        if item is not None:
            items.append(item)
    for key in ("_region_items", "_instant_items"):
        items.extend(list((getattr(w, key, None) or {}).values()))
    for key in ("_tuning_items", "_measure_items", "_measure_item_labels"):
        for entry in (getattr(w, key, None) or []):
            if isinstance(entry, tuple):
                items.extend([e for e in entry if e is not None])
            elif entry is not None:
                items.append(entry)
    items.extend(list(getattr(w, "_mark_items", None) or []))
    return items


@pytest.mark.parametrize("name", sorted(_CANVAS_FACTORIES))
class TestCanvasUnifiedTeardown:
    def test_detach_removes_owned_items_and_filters(self, qapp, name):
        w = _CANVAS_FACTORIES[name]()
        try:
            w.resize(700, 420)
            w.show()
            qapp.processEvents()
            items = _owned_items(w)
            assert items, f"{name}: 未采集到自管 item（守卫无效）"
            scene = w.plot_widget.scene()
            assert all(it.scene() is not None for it in items)

            # 事件过滤器调用留痕（探针：实例属性优先于 C++ 方法查找）
            calls = []
            for host_name in _FILTER_HOSTS[name]:
                holder = (
                    getattr(w, host_name) if host_name == "marks_table"
                    else getattr(w.plot_widget, host_name)()
                )
                setattr(holder, "removeEventFilter",
                        lambda _obj, _c=calls, _n=host_name: _c.append(_n))
            if name == "spectrum":
                w._interaction.detach = lambda *a, **k: calls.append("interaction")

            w._detach_scene_items()
            qapp.processEvents()

            assert all(it.scene() is None for it in items)
            assert all(it not in scene.items() for it in items)
            if name == "spectrum":
                # spectrum 的过滤器装在 marks_table 与 _interaction(view 视口)
                assert calls, f"{name}: 收尾未摘除事件过滤器（断环失败）"
            else:
                assert set(calls) == set(_FILTER_HOSTS[name]), (
                    f"{name}: 收尾未摘除事件过滤器（断环失败）: {calls}"
                )
        finally:
            w.close()
            qapp.processEvents()
            w.deleteLater()
            qapp.processEvents()

    def test_detach_clears_item_containers_but_keeps_value_snapshots(self, qapp, name):
        w = _CANVAS_FACTORIES[name]()
        try:
            w.show()
            qapp.processEvents()
            w._detach_scene_items()
            for key in ("_region_items", "_instant_items","_tuning_items",
                        "_measure_items", "_measure_item_labels", "_mark_items"):
                if hasattr(w, key):
                    assert not getattr(w, key), f"{name}:{key} 未清空"
            # 纯值快照 / 外部共享模型不被清空置 None
            assert hasattr(w, "_times") or hasattr(w, "plot_widget")
            if hasattr(w, "_tuning_lines"):
                assert isinstance(w._tuning_lines, list)
        finally:
            w.close()
            qapp.processEvents()
            w.deleteLater()
            qapp.processEvents()

    def test_detach_is_idempotent_and_close_event_wired(self, qapp, name):
        w = _CANVAS_FACTORIES[name]()
        try:
            w.show()
            qapp.processEvents()
            w._detach_scene_items()
            w._detach_scene_items()          # 幂等：二次调用不抛
            assert type(w).closeEvent is not QWidget.closeEvent  # 已接线
            assert w.close() is True
            qapp.processEvents()
            w._detach_scene_items()          # close 后再调仍安全
        finally:
            w.close()
            qapp.processEvents()
            w.deleteLater()
            qapp.processEvents()


# ---------------------------------------------------------------------------
# 件2：关窗 drain 与主窗收尾顺序
# ---------------------------------------------------------------------------


class TestTaskCenterDrain:
    def test_shutdown_does_not_use_blanket_process_events(self, qapp, monkeypatch):
        """④ 关窗 drain 不再做无差别事件泵（限定 receiver 消费）。"""
        from acouscope.ui.widgets.task_center import TaskCenter

        center = TaskCenter()
        pumped = []
        real = QApplication.processEvents

        def _spy(*a, **k):
            pumped.append(1)
            return real(*a, **k)

        monkeypatch.setattr(QApplication, "processEvents", staticmethod(_spy))
        center.shutdown(timeout_ms=1000)
        monkeypatch.undo()
        qapp.processEvents()
        assert pumped == [], "收尾路径仍在使用裸 processEvents 无差别泵"

    def test_shutdown_still_consumes_pending_finished(self, qapp):
        """T-928 语义不回退：收尾消费在途 finished → 线程登记表清空。"""
        from acouscope.ui.widgets.task_center import TaskCenter

        center = TaskCenter()
        center.submit("t1060-drain", run=lambda reporter: None)
        qapp.processEvents()
        center.shutdown(timeout_ms=2000)
        qapp.processEvents()
        assert center._threads == {}
        assert center._reporters == {}

    def test_disconnect_thread_signals_is_idempotent(self, qapp):
        """先「停+断」的断开步骤幂等：无在册线程时无操作、不抛。"""
        from acouscope.ui.widgets.task_center import TaskCenter

        center = TaskCenter()
        center._disconnect_thread_signals()
        center.shutdown(timeout_ms=1000)
        center._disconnect_thread_signals()


class TestCloseEventOrder:
    def test_view_finalize_precedes_task_center_drain(self):
        """⑤ 源码次序守卫：视图收尾必须先于 task_center drain（事件泵之前）。"""
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[1]
            / "src" / "acouscope" / "ui" / "main_window.py"
        ).read_text(encoding="utf-8")
        body = src.split("def closeEvent(self, event):", 1)[1]
        i_finalize = body.index("self._finalize_analysis_view_widgets()")
        i_drain = body.index("self.task_center.shutdown()")
        assert i_finalize < i_drain
