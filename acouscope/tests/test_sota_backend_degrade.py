# SPDX-License-Identifier: GPL-3.0-only
"""PI-P3a：SOTA 后端探测失败的降级判据（收窄 except + 留证 + 离屏禁模态）。

覆盖三条落笔要求：
  ① 探测失败（模型缺失 / onnxruntime 不可用）必须**留证**——ERROR 日志含后端名
     与异常类型名；不得静默 `except Exception: pass`（此前构造期 RuntimeError 被
     吞掉后直接流入模态分支）。
  ② 致命异常（BaseException 家族，如 KeyboardInterrupt）不得被降级逻辑误吞。
  ③ 离屏/无头环境不得进入 `QMessageBox.question` 模态分支——模态 exec 事件循环
     在无头下无人应答 ⇒ 永久阻塞（2026-10-21 实证），改为留证 + 回退 pYIN。

离屏环境（QT_QPA_PLATFORM=offscreen）下构造 MainWindow 但不 show()；切换链路
全部走桩（后端可用性 / QMessageBox.question / _download_sota_model），禁真实
模型探测与真实下载线程。
"""

import logging
import os
import re
import signal
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QMessageBox

from acouscope.app.controller import AppController

# ★模块导入期即导入 main_window：触发 acouscope logger 的 _configure_root()
#   （root.propagate=False），使 pytest 的 caplog 能在**首条**用例就挂上捕获
#   handler（否则首条用例抓不到 acouscope.* 的 ERROR 记录）。
from acouscope.ui.main_window import MainWindow

_SR = 8000
_DURATION = 2.0
_MAIN_PY = (
    Path(__file__).resolve().parent.parent
    / "src" / "acouscope" / "ui" / "main_window.py"
)

# 看门狗：signal.alarm + os._exit（与 test_gui_p2a_annotations.py:11-32 同机制；
# 作用域取 function 以便更早定位是哪条用例挂死）⇒ 99 = 看门狗击杀。
_WATCHDOG_S = 30


def _on_alarm(signum, frame):  # noqa: ARG001
    """看门狗到点：直接退进程，避免模态挂死把整轮测试拖成死局。"""
    os._exit(99)


signal.signal(signal.SIGALRM, _on_alarm)


@pytest.fixture(autouse=True)
def _watchdog():
    """每条用例 30 s 看门狗。"""
    signal.alarm(_WATCHDOG_S)
    yield
    signal.alarm(0)


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


def _select_backend(window, data_name):
    """把后端下拉切到指定后端（不触发信号，随后手动调 _on_backend_changed）。

    ★禁裸 `setCurrentIndex`：combo.currentIndexChanged 已连 _on_backend_changed，
    裸切会触发真实探测、污染判据（照 test_pitch_backend_switch.py:74-83 口径）。
    以 itemData（后端标识）匹配，避开翻译文本耦合。
    """
    combo = window._backend_combo
    for i in range(combo.count()):
        if combo.itemData(i) == data_name:
            combo.blockSignals(True)
            combo.setCurrentIndex(i)
            combo.blockSignals(False)
            return
    raise AssertionError(f"后端下拉无该项: {data_name}")


class _UnavailableBackend:
    """桩：构造成功但 is_available() 为 False（模拟模型缺失）。"""

    def __init__(self):
        pass

    def is_available(self):
        return False


class _BoomBackend:
    """桩：构造期抛 RuntimeError（模拟 SwiftF0Backend.__init__ 的模型缺失路径）。"""

    def __init__(self):
        raise RuntimeError("SwiftF0 模型未找到（判据桩）")

    def is_available(self):
        return False


class _FatalBackend:
    """桩：构造期抛 BaseException 家族异常（致命异常不得被误吞）。"""

    def __init__(self):
        raise KeyboardInterrupt("判据桩：致命中断")

    def is_available(self):
        return False


def _patch_backend(monkeypatch, cls):
    """把 SwiftF0Backend 整个替换为桩类（禁真实模型探测）。"""
    monkeypatch.setattr("acouscope.analysis.backends.swift_f0.SwiftF0Backend", cls)


def _stub_modal(monkeypatch, reply):
    """桩 QMessageBox.question：记录调用并返回指定答复。

    ★离屏下真模态会永久阻塞（无窗口系统 ⇒ exec 事件循环永不退出）⇒ 所有
    触达模态分支的用例都必须桩掉它。
    """
    asked = []

    def _question(*args, **kwargs):  # noqa: ARG001
        asked.append(args)
        return reply

    monkeypatch.setattr(QMessageBox, "question", _question)
    return asked


def _stub_download(window, monkeypatch):
    """桩 _download_sota_model：记录下载调用（禁真实下载）。"""
    downloads = []
    monkeypatch.setattr(window, "_download_sota_model", lambda name: downloads.append(name))
    return downloads


def test_headed_branch_asks_then_falls_back(window, monkeypatch):
    """① 有头分支语义守恒：不可用 ⇒ 询问下载 ⇒ 答 No ⇒ 回退 pYIN（且不下载）。"""
    _patch_backend(monkeypatch, _UnavailableBackend)
    monkeypatch.setattr(
        "acouscope.ui.main_window._is_headless_qt", lambda: False, raising=False
    )
    asked = _stub_modal(monkeypatch, QMessageBox.StandardButton.No)
    downloads = _stub_download(window, monkeypatch)

    _select_backend(window, "SwiftF0")
    window._on_backend_changed()

    assert asked, "有头分支必须弹出模型缺失询问"
    assert downloads == [], f"答 No 后不得触发下载（实际 {downloads}）"
    assert window._pitch_backend == "pYIN"
    assert window._backend_combo.currentIndex() == 0


def test_headless_env_skips_modal_prompt(window, monkeypatch, caplog):
    """★离屏闸门（有齿）：无头环境不得进入模态分支——留证 + 回退 pYIN。"""
    _patch_backend(monkeypatch, _UnavailableBackend)
    monkeypatch.setattr(
        "acouscope.ui.main_window._is_headless_qt", lambda: True, raising=False
    )
    # 桩掉模态：Step 1（未改码）下闸门不存在会真的调模态 ⇒ 离屏永久挂死而非红。
    asked = _stub_modal(monkeypatch, QMessageBox.StandardButton.No)
    downloads = _stub_download(window, monkeypatch)

    with caplog.at_level(logging.ERROR, logger="acouscope"):
        _select_backend(window, "SwiftF0")
        window._on_backend_changed()

    assert asked == [], (
        f"离屏闸门未生效：模态不应被调用（实际调用 {len(asked)} 次）"
    )
    assert downloads == [], f"离屏闸门不得触发下载（实际 {downloads}）"
    assert window._pitch_backend == "pYIN"
    assert window._backend_combo.currentIndex() == 0
    errs = [
        r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR
    ]
    assert errs, "离屏闸门须留 ERROR 留证（caplog 未捕获到 ERROR 留证）"
    assert any("headless" in m for m in errs), (
        f"离屏闸门的留证须说明无头环境（实际 ERROR 记录：{errs}）"
    )


def test_probe_failure_is_logged_with_backend_and_exc_type(window, monkeypatch, caplog):
    """★留证（有齿）：探测失败必须留 ERROR，且含后端名与异常类型名。"""
    _patch_backend(monkeypatch, _BoomBackend)
    monkeypatch.setattr(
        "acouscope.ui.main_window._is_headless_qt", lambda: True, raising=False
    )
    _stub_modal(monkeypatch, QMessageBox.StandardButton.No)
    _stub_download(window, monkeypatch)

    with caplog.at_level(logging.ERROR, logger="acouscope"):
        _select_backend(window, "SwiftF0")
        window._on_backend_changed()

    errs = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    hit = [m for m in errs if "SwiftF0" in m and "RuntimeError" in m]
    assert hit, (
        f"未捕获到 ERROR 留证（须含后端名与异常类型名）；实际 ERROR 记录：{errs}"
    )


def test_fatal_exception_is_not_swallowed(window, monkeypatch):
    """② 致命异常（BaseException 家族）必须向上传播，不得被降级逻辑吞掉。"""
    _patch_backend(monkeypatch, _FatalBackend)
    monkeypatch.setattr(
        "acouscope.ui.main_window._is_headless_qt", lambda: True, raising=False
    )
    _stub_modal(monkeypatch, QMessageBox.StandardButton.No)

    _select_backend(window, "SwiftF0")
    with pytest.raises(KeyboardInterrupt):
        window._on_backend_changed()


# 「except Exception: pass」语义形态：except 子句的**第一条语句**就是 pass。
# 源码里 `except Exception:` 与 `pass` 分两行（缩进不同），故按「下一条语句为
# pass」匹配，而非同一行的字面串。
_SILENT_PASS_RE = re.compile(r"except\s+Exception\b[^\n]*:[ \t]*\n[ \t]*pass\b")


def test_on_backend_changed_has_no_silent_except_pass():
    """③ 静态纪律：_on_backend_changed 方法体内不得有静默吞异常的 except pass。"""
    mw = _MAIN_PY.read_text(encoding="utf-8")
    chunks = [c for c in mw.split("\n    def ") if c.startswith("_on_backend_changed")]
    assert len(chunks) == 1, f"_on_backend_changed 方法体定位失败（命中 {len(chunks)} 处）"
    body = chunks[0].split("\n    def ")[0]
    hits = _SILENT_PASS_RE.findall(body)
    assert not hits, (
        f"_on_backend_changed 内不得出现 'except Exception: pass' 静默吞异常"
        f"（命中 {len(hits)} 处）"
    )


def test_headless_helper_follows_qt_platform_name(qapp):
    """helper 判定须以 QApplication.platformName() 为准（环境变量仅作无实例兜底）。"""
    import acouscope.ui.main_window as mw

    plat = (qapp.platformName() or "").lower()
    assert plat, "无法取得 Qt 平台名"
    expected = plat in ("offscreen", "minimal")
    actual = mw._is_headless_qt()
    assert actual is expected, (
        f"_is_headless_qt() 判定与 Qt 平台名不一致：platformName={plat!r} "
        f"实际={actual} 期望={expected}"
    )
