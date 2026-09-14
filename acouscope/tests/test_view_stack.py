# SPDX-License-Identifier: GPL-3.0-only
"""T-505a 守卫测试：分析视图区 QStackedWidget 懒构建 + 常驻 + 视图索引持久化。

fixture 完全参照 tests/test_async_analysis.py：
qapp + window + monkeypatch 门控 + HOME=tmp_path + 合成音频，window 不 show()。
"""

import time

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QStackedWidget

from acouscope.app.controller import AppController
from acouscope.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """带已加载音频的主窗口（绕过付费门控）。"""


    # 设置写入指向临时目录，避免污染用户配置
    monkeypatch.setenv("HOME", str(tmp_path))
    # 隔离实证：get_data_dir 被 main_window 持久化函数以函数内 import 使用，
    # monkeypatch 模块属性即生效（ui_analysis_view.json 落入 tmp_path）
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 20.0)) / sr
    sweep = 0.5 * np.sin(2 * np.pi * (200 + 300 * t) * t)
    controller.load_from_array(sweep, sr)

    w = MainWindow(controller)
    yield w
    w.close()


def _wait_for(qapp, predicate, timeout_ms=20000, poll_ms=50):
    """轮询等待条件成立，期间持续处理事件（模拟界面响应）。"""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(poll_ms / 1000)
    return False


def _view_path(qapp, tmp_path):
    from acouscope.utils.config import get_data_dir

    return get_data_dir() / "ui_analysis_view.json"


class TestViewStack:
    def test_view_container_is_qstackedwidget(self, window, qapp):
        """视图容器是 QStackedWidget（已加载音频的 window 直接断言）。"""
        assert isinstance(window.view_container, QStackedWidget)
        # 第 0 页为常驻提示页
        assert window.view_container.count() >= 1

    def test_lazy_build_and_reuse_across_switches(self, window, qapp):
        """懒构建 + 常驻复用：切走再切回是同一控件对象（零重建）。"""
        # 切到 FFT（同步构建）
        window._on_analysis_changed(1)
        qapp.processEvents()
        assert _wait_for(
            qapp, lambda: window._view_widgets.get(1) is not None
        ), "FFT 视图未在超时内构建"
        w1 = window.view_container.currentWidget()
        assert w1 is window._view_widgets[1]

        # 切到音高（异步构建）
        window._on_analysis_changed(3)
        assert _wait_for(
            qapp, lambda: window._view_widgets.get(3) is not None
        ), "音高视图未在超时内构建"

        # 切走后 FFT 控件仍存活（未被销毁），且不在当前页
        try:
            w1.parent()
            alive = True
        except RuntimeError:
            alive = False
        assert alive, "切走后 FFT 控件被销毁（违反常驻契约）"
        assert window.view_container.currentWidget() is not w1

        # 切回 FFT：同一对象，零重建
        window._on_analysis_changed(1)
        qapp.processEvents()
        assert window.view_container.currentWidget() is w1, "切回 FFT 发生重建"

    def test_invalidate_destroys_all_pages(self, window, qapp):
        """_invalidate_analysis_views：清空全部常驻页并回提示页。"""
        # 先建 2 个视图（FFT 同步 + 实时面板同步）
        window._on_analysis_changed(1)
        qapp.processEvents()
        assert _wait_for(qapp, lambda: window._view_widgets.get(1) is not None)
        window._on_analysis_changed(0)
        qapp.processEvents()
        assert _wait_for(qapp, lambda: window._view_widgets.get(0) is not None)
        assert len(window._view_widgets) == 2

        fft_w = window._view_widgets[1]
        rt_w = window._view_widgets[0]

        window._invalidate_analysis_views()

        assert window._view_widgets == {}
        assert window.view_container.currentIndex() == 0
        assert not hasattr(window, "_realtime_panel")
        assert not hasattr(window, "_spectrum_widget")

        # 旧控件应已真正销毁（processEvents 不处理 DeferredDelete，
        # 用 sendPostedEvents 显式冲刷，等价于事件循环跑一拍）
        from PyQt6.QtCore import QEvent

        QApplication.sendPostedEvents(fft_w, QEvent.Type.DeferredDelete)
        QApplication.sendPostedEvents(rt_w, QEvent.Type.DeferredDelete)
        for w in (fft_w, rt_w):
            with pytest.raises(RuntimeError):
                w.parent()

    def test_view_index_persistence_roundtrip(self, window, qapp, tmp_path):
        """索引持久化往返 + 垃圾 JSON / 越界均静默返回 None。"""
        path = _view_path(qapp, tmp_path)

        window._save_view_index(3)
        assert window._load_view_index() == 3
        assert path.exists()

        # 越界（9）→ None
        window._save_view_index(9)
        assert window._load_view_index() is None

        # 垃圾 JSON → None（全静默，不抛）
        path.write_text("{not valid json", encoding="utf-8")
        assert window._load_view_index() is None

    def test_resident_view_reattaches_waveform_link(self, window, qapp):
        """常驻切回：重挂波形指针联动（同一回调对象，零重建）。"""
        # FFT（index 1，同步构建）：构建时挂载联动并 stash 在控件上
        window._on_analysis_changed(1)
        assert _wait_for(qapp, lambda: window._view_widgets.get(1) is not None)
        cb1 = window.waveform_widget.position_changed_callback
        assert cb1 is not None
        assert window._view_widgets[1]._wave_link_callback is cb1

        # 切到实时面板：联动断开
        window._on_analysis_changed(0)
        qapp.processEvents()
        assert window.waveform_widget.position_changed_callback is None

        # 切回 FFT：零重建 + 重挂同一回调对象
        window._on_analysis_changed(1)
        qapp.processEvents()
        assert window.view_container.currentWidget() is window._view_widgets[1]
        assert window.waveform_widget.position_changed_callback is cb1

        # 语谱图（index 2，同步构建）同样验证
        window._on_analysis_changed(2)
        assert _wait_for(qapp, lambda: window._view_widgets.get(2) is not None)
        cb2 = window.waveform_widget.position_changed_callback
        assert cb2 is not None

        window._on_analysis_changed(0)
        qapp.processEvents()
        assert window.waveform_widget.position_changed_callback is None

        window._on_analysis_changed(2)
        qapp.processEvents()
        assert window.view_container.currentWidget() is window._view_widgets[2]
        assert (
            window.waveform_widget.position_changed_callback
            is window._view_widgets[2]._wave_link_callback
        )

    def test_restore_view_index_on_load(self, window, qapp, tmp_path):
        """D 路径：_restore_view_index 单次消费 → 打开音频后停留在上次视图。"""
        from acouscope.audio.io import AudioInfo

        def _info():
            return AudioInfo(
                filepath="synthetic.wav", duration=20.0, sample_rate=8000,
                channels=1, samples=int(8000 * 20), bit_depth=16,
                format="WAV", file_size=0,
            )

        # 首次打开（HOME=tmp_path 全新目录，无持久化文件）→ 按下拉框 0 构建
        assert window._restore_view_index is None
        window._sync_after_open(_info())
        assert _wait_for(qapp, lambda: window._view_widgets.get(0) is not None)
        assert window._restore_view_index is None  # 已消费

        # 设置上次视图 = 音高，再走一次 D 路径
        window._restore_view_index = 3
        window._sync_after_open(_info())
        assert _wait_for(
            qapp, lambda: window._view_widgets.get(3) is not None
        ), "restore=3 后音高视图未在超时内构建"
        assert window._restore_view_index is None  # 单次消费
        assert window.view_container.currentWidget() is window._view_widgets[3]
        assert window.analysis_tab_bar.currentIndex() == 3  # _set_analysis_view 同步标签卡
        # 旧视图（实时面板）已被 invalidate 销毁
        assert 0 not in window._view_widgets
