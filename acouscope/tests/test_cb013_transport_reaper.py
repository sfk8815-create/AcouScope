# SPDX-License-Identifier: GPL-3.0-only
"""CB-013b D-1 回归测试：传输条毫秒时钟 + 速度读数 + main_window 快捷键接线。

CB-013b 硬规则：只独立构造 TransportBar()（禁构造 MainWindow，GUI_backlog #6）；
main_window 的 D-1 快捷键接线（_on_record_shortcut / _on_escape）以源码锚点
断言佐证——两方法必须「有定义且被 _setup_shortcuts 引用」，防构造期 AttributeError
（阻断缺陷）回退。
"""

import re

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from acouscope.ui.main_window import MainWindow
from acouscope.ui.widgets.transport_bar import TransportBar


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def bar(qapp):
    b = TransportBar()
    yield b
    b.close()


_TIME_PAIR_RE = re.compile(r"\d{2}:\d{2}:\d{2}\.\d{3}")


def test_current_time_label_three_part_millis_clock(bar):
    """验收①：lbl_current_time 存在，set_time_label 后文本为 HH:MM:SS.mmm 双读数。"""
    assert bar.lbl_current_time is not None
    bar.set_time_label(1.5, 60.0)
    text = bar.lbl_current_time.text()
    tokens = _TIME_PAIR_RE.findall(text)
    assert tokens == ["00:00:01.500", "00:01:00.000"], (
        f"毫秒三段式读数不符: {text}"
    )


def test_speed_readout_follows_combo(bar):
    """验收②：lbl_speed_readout 存在，速率切 0.5x → 读数变 '0.50x'。"""
    assert bar.lbl_speed_readout is not None
    assert bar.lbl_speed_readout.text() == "1.00x"
    bar.cmb_speed.setCurrentIndex(0)  # 0.5x
    assert bar.lbl_speed_readout.text() == "0.50x"


def test_speed_readout_visible_in_wide_state(bar):
    """A10：宽态（≥_COMPACT_W）下速度读数位必须**真的展开**。

    盲区成因（P3b 审计实证）：_COMPACT_W 若被改成永不展开（如 2000），
    宽度守门条与 test_speed_readout_follows_combo 均恒绿——无判据锁住
    「宽态下读数位可见」。本条先窄态（确保隐藏）再宽态，直锁
    _apply_compact 的展开分支（reviewer 建议 2：两步式才真正走 show()）。
    """
    bar._apply_compact(400)                     # 400 < _COMPACT_W(760) ⇒ 窄态折叠
    bar._apply_compact(800)                     # 800 ≥ _COMPACT_W(760) ⇒ 宽态展开
    assert bar.lbl_speed_readout.isHidden() is False, (
        f"宽态（800 ≥ _COMPACT_W）下速度读数位应展开，"
        f"实际 isHidden={bar.lbl_speed_readout.isHidden()}"
    )


def _main_window_source() -> str:
    import inspect
    from pathlib import Path

    return Path(inspect.getsourcefile(MainWindow)).read_text(encoding="utf-8")


def test_main_window_shortcut_handlers_defined_and_referenced():
    """D-1 阻断回归：两处理器有 def 且文本中至少各出现 2 次（1 定义 + 1 引用）。

    背景：CB-013 主体在 _setup_shortcuts 注册 self._on_record_shortcut 与
    self._on_escape，但两方法缺失 → register_global(connect) 在 MainWindow
    构造期即 AttributeError（阻断级）。本锚点以文本计数佐证「已补齐」。
    """
    src = _main_window_source()
    for name in ("_on_record_shortcut", "_on_escape"):
        assert f"def {name}" in src, f"main_window 缺少 def {name}"
        assert src.count(name) >= 2, (
            f"{name} 应至少出现 2 次（1 定义 + 1 注册引用），实际 {src.count(name)}"
        )
