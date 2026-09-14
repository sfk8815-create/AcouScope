# SPDX-License-Identifier: GPL-3.0-only
"""异步分析回归测试：视图切换不阻塞事件循环 + 帮助菜单三语。"""

import time

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

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

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 20.0)) / sr
    sweep = 0.5 * np.sin(2 * np.pi * (200 + 300 * t) * t)
    controller.load_from_array(sweep, sr)

    w = MainWindow(controller)
    yield w
    w.close()


def _wait_for(qapp, predicate, timeout_ms=15000, poll_ms=50):
    """轮询等待条件成立，期间持续处理事件（模拟界面响应）。"""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(poll_ms / 1000)
    return False


class TestAsyncAnalysis:
    def test_pitch_analysis_runs_async_and_keeps_ui_alive(self, window, qapp, monkeypatch):
        """切换到音高视图：计算在后台线程，事件循环保持响应。"""
        # 注入 600ms 延迟，保证确定性的计算窗口（不依赖机器快慢）
        from acouscope.analysis.pitch import PitchAnalyzer

        orig_detect = PitchAnalyzer.detect_yin

        def slow_detect(self, data, **kw):
            time.sleep(0.6)
            return orig_detect(self, data, **kw)

        monkeypatch.setattr(PitchAnalyzer, "detect_yin", slow_detect)

        tick_count = [0]
        timer = QTimer()
        timer.setInterval(30)
        timer.timeout.connect(lambda: tick_count.__setitem__(0, tick_count[0] + 1))
        timer.start()

        window.analysis_tab_bar.setCurrentIndex(3)  # 音高
        qapp.processEvents()

        ok = _wait_for(
            qapp,
            lambda: window._live_widget("_pitch_widget") is not None,
        )
        timer.stop()

        assert ok, "音高控件未在超时内出现"
        # 600ms 注入延迟 + 正常计算期间，30ms 定时器应跳多次；
        # 若计算阻塞主线程，tick 几乎为 0
        assert tick_count[0] >= 5, (
            f"计算期间事件循环被阻塞（仅 {tick_count[0]} 次定时器触发），界面会假死"
        )

    def test_pitch_result_cached_on_second_switch(self, window, qapp):
        """第二次切换音高视图应命中结果缓存（无 worker 启动）。"""
        window.analysis_tab_bar.setCurrentIndex(3)
        assert _wait_for(
            qapp, lambda: window._live_widget("_pitch_widget") is not None
        )

        window.analysis_tab_bar.setCurrentIndex(0)  # 切走
        qapp.processEvents()

        fp = window._audio_fingerprint()
        assert ("pitch", fp) in window._result_cache

        window.analysis_tab_bar.setCurrentIndex(3)  # 切回（应走缓存）
        qapp.processEvents()
        assert window._live_widget("_pitch_widget") is not None

    def test_stale_worker_result_discarded(self, window, qapp):
        """计算期间切走视图，陈旧结果不得覆盖新视图。"""
        window.analysis_tab_bar.setCurrentIndex(3)  # 启动音高计算
        window.analysis_tab_bar.setCurrentIndex(0)  # 立即切回波形
        qapp.processEvents()

        assert _wait_for(qapp, lambda: window._live_widget("_realtime_panel") is not None)
        # 再等一拍，确认迟到的音高结果没有挤掉实时面板
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.05)
        assert window._live_widget("_realtime_panel") is not None

    def test_3d_analysis_deferred_build(self, window, qapp):
        """3D 视图延迟构建：singleShot 回调最终生成控件。"""
        window.analysis_tab_bar.setCurrentIndex(6)
        assert _wait_for(
            qapp, lambda: window._live_widget("_spectrogram3d_widget") is not None
        )


class TestHelpMenu:
    def test_help_menu_contains_quickstart_manual_about(self, window):
        """帮助菜单应含 快速入门 / 用户手册 / 关于 三项。"""
        menubar = window.menuBar()
        help_menu = next(
            (m for m in menubar.actions()
             if "帮助" in m.text() or "Help" in m.text() or "說明" in m.text()),
            None,
        )
        assert help_menu is not None
        texts = [a.text() for a in help_menu.menu().actions()]
        assert any("快速入门" in t or "Quick Start" in t for t in texts)
        assert any("用户手册" in t or "User Manual" in t or "手冊" in t for t in texts)
        assert any("关于" in t or "About" in t or "關於" in t for t in texts)

    def test_quickstart_manual_open(self, window, qapp):
        """帮助对话框可打开（三语内容均已注册）。"""
        from acouscope.ui.widgets.help_dialogs import QuickStartDialog, ManualDialog

        d1 = QuickStartDialog(window)
        d2 = ManualDialog(window)
        assert d1.windowTitle()
        assert d2.windowTitle()
        d1.deleteLater()
        d2.deleteLater()

    def test_about_dialog_texts_three_languages(self):
        """关于对话框的作者/版权/致谢在三种语言下都有译文。"""
        from acouscope.i18n import set_language, tr

        for lang in ("zh_CN", "zh_TW", "en_US"):
            set_language(lang)
            assert tr("about.author_name")
            assert "Copyright © 2026" in tr("about.copyright")
            assert tr("about.rights")
            assert tr("about.ack_body")
        set_language("zh_CN")
