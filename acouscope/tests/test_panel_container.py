# SPDX-License-Identifier: GPL-3.0-only
"""T-1012 无标题栏 PanelContainer 回归测试（标题栏横条已取消）。"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtWidgets import QLabel
from acouscope.ui.widgets.panels import PanelContainer


def test_no_header_widgets(qapp):
    """验收：无标题栏横条——panelHeader/lblTitle/lblIcon/btnCollapse 一律不存在，
    内容区占满整面板；构造参数 title/icon_name 仅作兼容保留、不渲染。"""
    p = PanelContainer("项目 / 图层", icon_name="files")
    assert not hasattr(p, "panelHeader")
    assert not hasattr(p, "lblTitle")
    assert not hasattr(p, "lblIcon")
    assert not hasattr(p, "btnCollapse")
    assert p.panelContent is not None
    assert not p.is_collapsed()


def test_set_content(qapp):
    p = PanelContainer("检查器")
    inner = QLabel("hello")
    p.set_content(inner)
    assert inner.parent() is p.panelContent
    # 替换内容不残留
    p.set_content(QLabel("second"))
    assert inner.parent() is None


def test_collapse_toggle_signal(qapp):
    """折叠契约保留：toggle/set_collapsed 只隐藏内容并发射 collapsedChanged。"""
    p = PanelContainer("P")
    p.set_content(QLabel("x"))
    events = []
    p.collapsedChanged.connect(lambda b: events.append(b))
    p.toggle()
    assert p.is_collapsed() is True
    assert not p.panelContent.isVisible()
    p.toggle()
    assert p.is_collapsed() is False
    assert p.panelContent.isVisible()
    assert events == [True, False]


def test_set_collapsed_idempotent(qapp):
    p = PanelContainer("P")
    n = [0]
    p.collapsedChanged.connect(lambda _: n.__setitem__(0, n[0] + 1))
    p.set_collapsed(True)
    p.set_collapsed(True)  # 重复同态不发信号
    assert n[0] == 1


def test_serialize_restore(qapp):
    p = PanelContainer("P")
    p.set_collapsed(True)
    state = p.serialize()
    assert state == {"collapsed": True}
    p2 = PanelContainer("P2")
    p2.restore(state)
    assert p2.is_collapsed() is True
    p2.restore({})
    assert p2.is_collapsed() is False
