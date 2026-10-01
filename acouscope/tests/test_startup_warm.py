# SPDX-License-Identifier: GPL-3.0-only
"""T-1075 守卫测试：G-B 冷启动预热常量化（零行为变更）。

覆盖令文判据②三断言：
  (a) 延迟常量在位且数值恒 8.0（T-901b「延后以不与冷启动争核」的意图不被改值）。
  (b) 预热内部异常被吞并走 _log.warning 降级（不外抛、不崩启动）。
  (c) 预热不触发 Qt 后端导入（Qt 后端须主线程，见 _warm_matplotlib 文档）。

纪律：不起 QApplication、不启动 main()；(c) 逐出预热会导入的子模块以逼出真实
导入路径，monkeypatch 在 teardown 复原 sys.modules，不污染同进程其他测试。
"""

import sys

import matplotlib

from acouscope import __main__ as entry


def test_warm_delay_constant_is_8_seconds():
    assert entry.MATPLOTLIB_WARM_DELAY_S == 8.0


def test_warm_swallows_import_error_and_warns(monkeypatch):
    calls = []

    class FakeLog:
        def warning(self, msg, *args):
            calls.append((msg, args))

    monkeypatch.setattr(entry, "_log", FakeLog())
    # sys.modules 里的 None 条目让 `import matplotlib` 抛 ImportError。
    monkeypatch.setitem(sys.modules, "matplotlib", None)

    entry._warm_matplotlib()  # 不得外抛

    assert len(calls) == 1
    msg, args = calls[0]
    assert "预热失败" in msg
    assert isinstance(args[0], ImportError)


def test_warm_does_not_import_qt_backend(monkeypatch):
    # 逐出预热要导入的子模块，逼出真实导入路径（matplotlib 本体保留，后端状态不受扰）。
    for name in ("matplotlib.font_manager", "matplotlib.figure"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    qt_before = {n for n in sys.modules if "qt" in n.lower()}
    backend_before = matplotlib.get_backend()

    entry._warm_matplotlib()

    assert "matplotlib.font_manager" in sys.modules
    assert "matplotlib.figure" in sys.modules
    assert {n for n in sys.modules if "qt" in n.lower()} == qt_before
    assert matplotlib.get_backend() == backend_before
