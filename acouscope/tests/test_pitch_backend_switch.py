# SPDX-License-Identifier: GPL-3.0-only
"""T-1014 音高算法后端切换即时生效回归测试。

离屏环境：构造 MainWindow(controller) 但不 show()；切换链路全部走桩
（可用性 is_available / QMessageBox.question / show_toast / 重算钩子
_on_analysis_changed），禁真实分析线程，验证：
  ① 切换到可用后端且音高视图在 → 仅失效 pitch 缓存键 + 销毁音高控件
     （其他视图/结果保留）+ 当前即音高视图时触发重算 + toast「正在重新分析」；
  ② 音高视图已构建但非当前 → 失效与销毁执行、不触发立即重算（下次进入自动重算）；
  ③ 无音高结果且不在音高视图 → 仅 toast「下次分析生效」，不触发重算；
  ④ 不可用后端 → 既有下载询问分支（QMessageBox.question）保留，
     拒绝后回退 pYIN（_pitch_backend 与下拉复位）且不打扰；
  ⑤ 有效后端未变化（回退仍回原后端）→ 不触发任何失效/重算/toast；
  ⑥ i18n 三语键 + 静态纪律（禁词 0 / T-1014 行无 hex-px / 无新建 QDialog /
     测试全程不 show() / 重算走 _on_analysis_changed→_run_analysis_async 异步壳）。
"""

import re
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QWidget

from acouscope.app.controller import AppController
from acouscope.i18n import _STRINGS, tr
from acouscope.ui.main_window import MainWindow

_SR = 8000
_DURATION = 2.0
_MAIN_PY = (
    Path(__file__).resolve().parent.parent
    / "src" / "acouscope" / "ui" / "main_window.py"
)

# 禁词以拼接构造，避免模式字面量自身被扫中（同 test_file_browser.py 口径）。
_BANNED = "Mel" + "odyne"

_TOAST_REANALYZE = {
    "backend": lambda b: tr("pitch_backend.switched_reanalyze").format(backend=b),
}
_TOAST_NEXT = {
    "backend": lambda b: tr("pitch_backend.switched_next").format(backend=b),
}


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """带已加载音频的主窗口（不 show，禁真实分析构建）。"""
    monkeypatch.setenv("HOME", str(tmp_path))

    controller = AppController()
    t = np.arange(int(_SR * _DURATION)) / _SR
    data = 0.5 * np.sin(2 * np.pi * 440.0 * t)
    controller.load_from_array(data, _SR)

    w = MainWindow(controller)
    qapp.processEvents()
    yield w
    w.close()


def _set_tab(window, index):
    """设标签索引但不触发 _on_analysis_changed（避免真实重算）。"""
    bar = window.analysis_tab_bar
    bar.blockSignals(True)
    bar.setCurrentIndex(index)
    bar.blockSignals(False)


def _select_backend(window, text):
    """把后端下拉切到指定文本项（不触发信号，随后手动调 _on_backend_changed）。"""
    combo = window._backend_combo
    for i in range(combo.count()):
        if combo.itemText(i) == text:
            combo.blockSignals(True)
            combo.setCurrentIndex(i)
            combo.blockSignals(False)
            return
    raise AssertionError(f"后端下拉无该项: {text}")


def _set_available(monkeypatch, name):
    """把 SOTA 后端可用性置 True（桩，禁真实模型探测）。"""
    if name == "SwiftF0":
        from acouscope.analysis.backends.swift_f0 import SwiftF0Backend
        monkeypatch.setattr(SwiftF0Backend, "is_available", lambda self: True)
    else:
        from acouscope.analysis.backends.rmvpe import RMVPEBackend
        monkeypatch.setattr(RMVPEBackend, "is_available", lambda self: True)


def _set_unavailable(monkeypatch, name):
    """把 SOTA 后端可用性置 False（桩）。"""
    if name == "SwiftF0":
        from acouscope.analysis.backends.swift_f0 import SwiftF0Backend
        monkeypatch.setattr(SwiftF0Backend, "is_available", lambda self: False)
    else:
        from acouscope.analysis.backends.rmvpe import RMVPEBackend
        monkeypatch.setattr(RMVPEBackend, "is_available", lambda self: False)


def _capture_toasts(monkeypatch):
    """替换 show_toast 为捕获器（禁真实窗口 show()）。"""
    toasts = []
    monkeypatch.setattr(
        "acouscope.ui.main_window.show_toast",
        lambda w, msg, level="info": toasts.append((level, msg)),
    )
    return toasts


def _spy_recompute(monkeypatch):
    """替换 _on_analysis_changed 为记录器（禁真实重算/线程）。"""
    calls = []
    monkeypatch.setattr(
        MainWindow, "_on_analysis_changed",
        lambda self, index: calls.append(index),
    )
    return calls


def _seed_pitch_view(window):
    """构造『音高视图已构建』态（伪控件 + 登记），不触发真实分析。"""
    w = QWidget()
    window.view_container.addWidget(w)
    window._pitch_widget = w
    window._view_widgets[3] = w
    window._pitch_grid_model = "STALE_GRID"
    return w


class TestSwitchApply:
    """切换生效链路：失效/重算/toast 两分支。"""

    def test_active_pitch_view_invalidates_and_recomputes(
        self, window, monkeypatch
    ):
        """可用后端 + 音高视图在 + 当前即音高 → 失效 pitch 键 + 重算 + toast。"""
        _set_available(monkeypatch, "SwiftF0")
        toasts = _capture_toasts(monkeypatch)
        recalc = _spy_recompute(monkeypatch)

        fp = window._audio_fingerprint()
        window._result_cache[("pitch", fp)] = ("P", "OLD")
        window._result_cache[("pitch", fp, 0.0, 1.0)] = ("P", "OLD_REG")
        window._result_cache[("fft", fp)] = ("F", "KEEP")
        old = _seed_pitch_view(window)
        _set_tab(window, 3)

        _select_backend(window, "SwiftF0 (深度)")
        window._on_backend_changed()

        # 失效：仅 pitch 键被清，其他结果保留
        assert ("pitch", fp) not in window._result_cache
        assert ("pitch", fp, 0.0, 1.0) not in window._result_cache
        assert ("fft", fp) in window._result_cache
        # 销毁：音高控件/网格模型已摘除
        assert not hasattr(window, "_pitch_widget")
        assert not hasattr(window, "_pitch_grid_model")
        assert window._view_widgets.get(3) is None
        assert window.view_container.indexOf(old) == -1
        # 重算触发 + toast + 后端更新
        assert recalc == [3]
        assert ("success", _TOAST_REANALYZE["backend"]("SwiftF0")) in toasts
        assert window._pitch_backend == "SwiftF0"

    def test_inactive_pitch_view_invalidates_without_immediate_recalc(
        self, window, monkeypatch
    ):
        """可用后端 + 音高视图在但非当前 → 失效销毁、不触发立即重算。"""
        _set_available(monkeypatch, "RMVPE")
        toasts = _capture_toasts(monkeypatch)
        recalc = _spy_recompute(monkeypatch)

        fp = window._audio_fingerprint()
        window._result_cache[("pitch", fp)] = ("P", "OLD")
        window._result_cache[("fft", fp)] = ("F", "KEEP")
        _seed_pitch_view(window)
        _set_tab(window, 1)  # 当前在 FFT 视图

        _select_backend(window, "RMVPE (人声)")
        window._on_backend_changed()

        assert ("pitch", fp) not in window._result_cache
        assert ("fft", fp) in window._result_cache
        assert not hasattr(window, "_pitch_widget")
        assert window._view_widgets.get(3) is None
        assert recalc == [], "非当前视图不得立即重算（下次进入自动重算）"
        assert ("success", _TOAST_REANALYZE["backend"]("RMVPE")) in toasts
        assert window._pitch_backend == "RMVPE"

    def test_no_pitch_result_only_toast(self, window, monkeypatch):
        """无音高结果且不在音高视图 → 仅 toast「下次分析生效」，不触发重算。"""
        _set_available(monkeypatch, "SwiftF0")
        toasts = _capture_toasts(monkeypatch)
        recalc = _spy_recompute(monkeypatch)

        _set_tab(window, 0)
        _select_backend(window, "SwiftF0 (深度)")
        window._on_backend_changed()

        assert recalc == []
        assert window._result_cache == {}
        assert not hasattr(window, "_pitch_widget")
        assert ("success", _TOAST_NEXT["backend"]("SwiftF0")) in toasts
        assert window._pitch_backend == "SwiftF0"

    def test_switch_to_pyin_reanalyzes_when_previous_sota(
        self, window, monkeypatch
    ):
        """pYIN 切换（原为 SwiftF0）→ 有效变化 → 同样失效+重算+toast。"""
        toasts = _capture_toasts(monkeypatch)
        recalc = _spy_recompute(monkeypatch)

        window._pitch_backend = "SwiftF0"
        fp = window._audio_fingerprint()
        window._result_cache[("pitch", fp)] = ("P", "OLD")
        _seed_pitch_view(window)
        _set_tab(window, 3)

        _select_backend(window, "pYIN (流式)")
        window._on_backend_changed()

        assert ("pitch", fp) not in window._result_cache
        assert recalc == [3]
        assert ("success", _TOAST_REANALYZE["backend"]("pYIN")) in toasts
        assert window._pitch_backend == "pYIN"

    def test_no_effective_change_noop(self, window, monkeypatch):
        """有效后端未变化（回退仍回 pYIN）→ 不失效/不重算/不 toast。"""
        toasts = _capture_toasts(monkeypatch)
        recalc = _spy_recompute(monkeypatch)

        # 默认即为 pYIN，缓存与视图预留
        fp = window._audio_fingerprint()
        window._result_cache[("pitch", fp)] = ("P", "OLD")
        _seed_pitch_view(window)
        _set_tab(window, 3)

        _select_backend(window, "pYIN (流式)")
        window._on_backend_changed()  # prev==backend → 无有效变化

        assert ("pitch", fp) in window._result_cache, "无有效变化不得清缓存"
        assert hasattr(window, "_pitch_widget")
        assert recalc == []
        assert toasts == []


class TestUnavailableBranch:
    """不可用后端：既有下载询问分支 + 回退 pYIN 保持（不回归）。"""

    def test_unavailable_asks_then_fallback_pyin(self, window, monkeypatch):
        """模型不可用 → 询问下载；拒绝 → 回退 pYIN 且不打扰。"""
        from PyQt6.QtWidgets import QMessageBox

        _set_unavailable(monkeypatch, "SwiftF0")
        toasts = _capture_toasts(monkeypatch)
        recalc = _spy_recompute(monkeypatch)

        asked = []
        monkeypatch.setattr(
            QMessageBox, "question",
            lambda *a, **k: (asked.append(a) or QMessageBox.StandardButton.No),
        )

        fp = window._audio_fingerprint()
        window._result_cache[("pitch", fp)] = ("P", "OLD")
        _seed_pitch_view(window)
        _set_tab(window, 3)
        _select_backend(window, "SwiftF0 (深度)")

        assert window._pitch_backend == "pYIN"  # 前置：默认 pYIN
        window._on_backend_changed()

        assert asked, "不可用后端必须走下载询问分支"
        # 拒绝 → 回退 pYIN：下拉复位 + 后端复位；因未发生有效变化 → 零打扰
        assert window._backend_combo.currentIndex() == 0
        assert window._pitch_backend == "pYIN"
        assert ("pitch", fp) in window._result_cache
        assert hasattr(window, "_pitch_widget")
        assert recalc == []
        assert toasts == []

    def test_unavailable_yes_still_downloads(self, window, monkeypatch):
        """询问选 Yes → 走既有下载路径（_download_sota_model 被调，不重算）。"""
        from PyQt6.QtWidgets import QMessageBox

        _set_unavailable(monkeypatch, "RMVPE")
        _capture_toasts(monkeypatch)
        recalc = _spy_recompute(monkeypatch)

        dl = []
        monkeypatch.setattr(window, "_download_sota_model", lambda name: dl.append(name))
        monkeypatch.setattr(
            QMessageBox, "question",
            lambda *a, **k: QMessageBox.StandardButton.Yes,
        )

        _select_backend(window, "RMVPE (人声)")
        window._on_backend_changed()

        assert dl == ["RMVPE"]
        assert recalc == []


class TestRecomputePathAsync:
    """重算走既有 _on_analysis_changed → 懒构建 → _run_analysis_async 异步壳。"""

    def test_active_switch_dispatches_async_shell(self, window, monkeypatch):
        """当前即音高视图的立即重算最终落在 _run_analysis_async（非同步长调）。"""
        _set_available(monkeypatch, "SwiftF0")
        _capture_toasts(monkeypatch)
        async_calls = []
        monkeypatch.setattr(
            MainWindow, "_run_analysis_async",
            lambda self, status, compute, on_done, err: async_calls.append(status),
        )

        fp = window._audio_fingerprint()
        window._result_cache[("pitch", fp)] = ("P", "OLD")
        _seed_pitch_view(window)
        _set_tab(window, 3)
        _select_backend(window, "SwiftF0 (深度)")

        # 不桩 _on_analysis_changed → 走真实懒构建重算路径
        window._on_backend_changed()

        assert async_calls and "音高" in async_calls[0], "重算须经 _run_analysis_async"
        assert window._pitch_backend == "SwiftF0"


class TestI18n:
    """新增 toast 文案 i18n 三语齐全。"""

    @pytest.mark.parametrize("key", [
        "pitch_backend.switched_reanalyze",
        "pitch_backend.switched_next",
    ])
    def test_three_languages_present(self, key):
        entry = _STRINGS.get(key)
        assert entry is not None
        for lang in ("en_US", "zh_CN", "zh_TW"):
            assert entry.get(lang), f"{key} 缺 {lang}"

    def test_backend_placeholder_formats(self):
        for key in ("pitch_backend.switched_reanalyze",
                    "pitch_backend.switched_next"):
            msg = _STRINGS[key]["zh_CN"].format(backend="SwiftF0")
            assert "SwiftF0" in msg


class TestStatic:
    """静态纪律：禁词 0 / T-1014 行无 hex-px / 无新建 QDialog / 无 .show()。"""

    def test_banned_word_zero_hits(self):
        for f in (_MAIN_PY, Path(__file__)):
            assert _BANNED not in f.read_text(encoding="utf-8")

    def test_no_hex_px_in_added_lines(self):
        src = _MAIN_PY.read_text(encoding="utf-8")
        added = [ln for ln in src.splitlines() if "T-1014" in ln]
        assert added, "应存在 T-1014 标记行"
        for ln in added:
            assert not re.search(r"#[0-9a-fA-F]{6}\b", ln), f"hex 硬编码: {ln}"
            assert "px" not in ln, f"px 硬编码: {ln}"

    def test_no_new_qdialog_in_added_lines(self):
        src = _MAIN_PY.read_text(encoding="utf-8")
        for ln in src.splitlines():
            if "T-1014" in ln:
                assert "QDialog" not in ln, f"禁新建 QDialog: {ln}"

    def test_no_main_window_show_in_test(self):
        text = Path(__file__).read_text(encoding="utf-8")
        assert ("MainWindow" + ".show()") not in text
        assert (".ex" + "ec(") not in text  # 拼接避免自扫命中

    def test_marker_lines_have_no_modal_call(self):
        """T-1014 实现行无模态/阻塞调用（重算仅走异步壳接线）。"""
        src = _MAIN_PY.read_text(encoding="utf-8")
        for ln in src.splitlines():
            if "T-1014" in ln and ("_on_backend_changed" in ln
                                   or "_apply_backend_switch" in ln):
                assert (".ex" + "ec(") not in ln
                assert "question(" not in ln
