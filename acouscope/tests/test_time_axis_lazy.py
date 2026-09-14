# SPDX-License-Identifier: GPL-3.0-only
"""T-901a: time_axis 惰性工厂化 matplotlib 依赖的行为验证。

- import time_axis 后 sys.modules 不得含 matplotlib（消除冷启动 import 链）
- 模块级属性 NiceTicksLocator 由模块级 __getattr__ 惰性工厂提供，
  构造结果仍为 matplotlib.ticker.Locator 子类
- format_seconds 既有格式规范不变
"""

import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"

CHILD_CHECK = (
    "import sys\n"
    "sys.path.insert(0, {src!r})\n"
    "import acouscope.ui.widgets.time_axis\n"
    "assert 'matplotlib' not in sys.modules\n"
    "print('LAZY_OK')\n"
)


def test_import_time_axis_no_matplotlib():
    """子进程安全：独立解释器 import time_axis 断言 matplotlib 未加载（防同进程测试顺序污染）。"""
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("MPLBACKEND", "Agg")
    r = subprocess.run(
        [sys.executable, "-c", CHILD_CHECK.format(src=str(SRC))],
        capture_output=True, text=True, timeout=180, env=env,
    )
    assert r.returncode == 0, "child rc=%d stderr=%s" % (r.returncode, r.stderr[-2000:])
    assert "LAZY_OK" in r.stdout


def test_nice_ticks_locator_still_works():
    """模块级属性 NiceTicksLocator（惰性工厂）仍须是 matplotlib.ticker.Locator 子类。"""
    import matplotlib.ticker

    from acouscope.ui.widgets.time_axis import NiceTicksLocator

    loc = NiceTicksLocator()
    assert isinstance(loc, matplotlib.ticker.Locator)


def test_format_seconds_smoke():
    """既有格式规范 3 断言（与 test_new_features.py 口径一致）。"""
    from acouscope.ui.widgets.time_axis import format_seconds

    assert format_seconds(0.125) == "0.125"
    assert format_seconds(5) == "5"
    assert format_seconds(68.25) == "01:08.25"
