# SPDX-License-Identifier: GPL-3.0-only
"""T-1054 批4a：图表设计器 → 中央 index4 全铺页（令 §四 判据 2/3/4/5/9）。

覆盖：
  2 切页往返：工具栏钮 → index4 + 该钮 checked + 另三钮未勾选；再点 → index0 + 全未勾选；
  3 菜单/工具栏同源（禁分裂态）：action.trigger() → index4；工具栏钮点一下 → action 反勾选；
  4 抽屉归零（设计器面）：main_window `open_drawer` = 0 · src 面 `open_drawer` = 0（批4d 已删 drawer.py） ·
    `_chart_designer` + `_drawer` 拼接串在 src/tests 均 0 命中（M2：只许拼接写法）；
  5 ★ 半成品守卫：index4 页实存于栈第 4 位（防「开关启用但页未建 ⇒ 亮灯空页」）
    + 面板常驻单实例（切页不重建，同 id()）；
  9 预览产物存在性：切到 index4 后经 `_render_chart_designer_preview` 落盘 1 张（/tmp），
    断言文件存在 + 尺寸抽样（体积不作硬门槛）。

fixture 参照 tests/test_chart_designer.py（qapp + window 不 show）。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtGui import QImage

from acouscope.app.controller import AppController
from acouscope.ui.main_window import MainWindow

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
_TESTS = _REPO_ROOT / "tests"

# M2：串拼接构造，避免本档自命中（grep 面判据 4 要求 src 零命中）
_DESIGNER_DRAWER_ATTR = "_chart_designer" + "_drawer"

# 开关组 4 钮（顺序与工具栏一致；checked 序列断言用）
_SWITCH_NAMES = (
    "btn_toggle_batch_workspace",
    "btn_toggle_room_modal",
    "btn_toggle_room_acoustic",
    "btn_toggle_chart_designer",
)


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """主窗口（不 show()）；HOME 与数据目录隔离到 tmp_path，载入 2s 合成音频。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 2.0)) / sr
    controller.load_from_array(0.2 * np.sin(2 * np.pi * 440.0 * t), sr)
    w = MainWindow(controller)
    yield w
    w.close()


def _checked(window) -> list:
    return [getattr(window, n).isChecked() for n in _SWITCH_NAMES]


# ---------------------------------------------------------------------------
# 判据 2 切页往返 + 互斥
# ---------------------------------------------------------------------------


def test_page_roundtrip_index4(window):
    """判据 2：工具栏钮 → index4（该钮 checked、另三钮未勾选）；再点 → index0 全未勾选。"""
    btn = window.btn_toggle_chart_designer
    assert window.central_stack.currentIndex() == 0
    btn.click()
    assert window.central_stack.currentIndex() == 4
    assert btn.isChecked() is True
    assert _checked(window) == [False, False, False, True]
    btn.click()
    assert window.central_stack.currentIndex() == 0
    assert _checked(window) == [False, False, False, False]


def test_switch_group_mutual_exclusion_includes_index4(window):
    """判据 2（互斥）：房间模态页 ↔ 图表设计器页切换后至多一个 checked（禁分裂态）。"""
    window.btn_toggle_room_modal.click()
    assert window.central_stack.currentIndex() == 2
    window.btn_toggle_chart_designer.click()
    assert window.central_stack.currentIndex() == 4
    assert window.btn_toggle_room_modal.isChecked() is False
    assert sum(_checked(window)) == 1


# ---------------------------------------------------------------------------
# 判据 3 菜单 / 工具栏同源
# ---------------------------------------------------------------------------


def test_menu_and_toolbar_share_one_state_source(window):
    """判据 3：action.trigger() → index4；工具栏钮再点 → 收回 index0 且 action 反勾选。"""
    act = window.action_chart_designer
    act.trigger()
    assert window.central_stack.currentIndex() == 4
    assert act.isChecked() is True
    assert window.btn_toggle_chart_designer.isChecked() is True
    window.btn_toggle_chart_designer.click()
    assert window.central_stack.currentIndex() == 0
    assert act.isChecked() is False
    assert window.btn_toggle_chart_designer.isChecked() is False


# ---------------------------------------------------------------------------
# 判据 4 抽屉归零（设计器面）
# ---------------------------------------------------------------------------


def test_open_drawer_counts_and_designer_drawer_absent():
    """判据 4：main_window `open_drawer` = 0 · src 面 = 0 · 设计器抽屉属性零命中。

    批4c：录音设置亦改左栏常驻页 ⇒ main_window 无在役调用者（import 一并删除）；
    批4d：抽屉机制整体退役（drawer.py 整档删除）⇒ src 面 open_drawer 亦归零。
    """
    mw = (_SRC / "acouscope" / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert mw.count("open_drawer") == 0, "main_window.py open_drawer 应 2→0（批4c 拆录音抽屉）"
    assert "from acouscope.ui.widgets.drawer import open_drawer" not in mw, \
        "批4c 后 main_window 不得再 import open_drawer（无在役调用者，禁 F401）"

    src_hits = [
        p for p in sorted(_SRC.rglob("*.py"))
        if not p.name.startswith("._")  # AppleDouble 旁车（外置卷非 UTF-8 元数据），非源码
        and "open_drawer" in p.read_text(encoding="utf-8")
    ]
    assert len(src_hits) == 0, [str(p) for p in src_hits]  # 批4d：drawer.py 删除 ⇒ src 面归零
    total = sum(
        p.read_text(encoding="utf-8").count("open_drawer") for p in src_hits
    )
    assert total == 0, total
    # 批4d：抽屉实现整档删除（原 drawer.py(4) 基础设施 + chart_font_dialog(1) 表述均已清）
    assert not (_SRC / "acouscope" / "ui" / "widgets" / "drawer.py").exists()

    for p in sorted(_SRC.rglob("*.py")):
        if p.name.startswith("._"):  # AppleDouble 旁车（外置卷非 UTF-8 元数据），非源码
            continue
        assert _DESIGNER_DRAWER_ATTR not in p.read_text(encoding="utf-8"), p.name
    for p in sorted(_TESTS.glob("test_*.py")):
        assert _DESIGNER_DRAWER_ATTR not in p.read_text(encoding="utf-8"), p.name


# ---------------------------------------------------------------------------
# 判据 5 ★ 半成品守卫：页实存 + 面板常驻单实例
# ---------------------------------------------------------------------------


def test_page_exists_at_index4_and_panel_is_resident_single_instance(window):
    """判据 5：index4 页实存（防亮灯空页）+ 常驻单实例（切页不重建，同 id()）。"""
    page = window.chart_designer_page
    assert page is not None, "index4 页未建（开关启用但页缺失 = 亮灯空页）"
    assert window.central_stack.indexOf(page) == 4
    assert window.central_stack.count() == 6, "central_stack 应为 6 页（index0~5）"

    panel = window.chart_designer_panel
    assert panel is not None
    assert window._chart_designer_panel() is panel     # 语义：常驻（非「未打开 None」）
    assert panel.parent() is page                      # 页包装内嵌（_wrap_room_page）

    window.btn_toggle_chart_designer.click()
    assert window.central_stack.currentWidget() is page
    window.btn_toggle_chart_designer.click()
    assert window.central_stack.currentIndex() == 0
    window.action_chart_designer.trigger()
    assert window.central_stack.currentWidget() is page
    assert window.chart_designer_panel is panel, "切页不得重建面板（常驻单实例）"
    assert id(window.chart_designer_panel) == id(panel)


def test_project_reachable_from_page_host(window):
    """判据 5（宿主迁移前提）：宿主由抽屉迁页后 `_project()` 父链仍可达 controller.project。"""
    panel = window.chart_designer_panel
    assert panel._project() is window.controller.project.current
    proj_store, glob_store, sess_store = panel._preset_stores()
    assert proj_store is window.controller.project.current.presets
    assert glob_store is not None and sess_store is not None


# ---------------------------------------------------------------------------
# 判据 9 预览产物存在性（/tmp，尺寸抽样；体积不作硬门槛）
# ---------------------------------------------------------------------------


def test_preview_artifact_written_to_tmp(window):
    """判据 9：切到 index4 后经 `_render_chart_designer_preview` 落盘 1 张（/tmp）。"""
    window.btn_toggle_chart_designer.click()
    assert window.central_stack.currentIndex() == 4

    out = Path(tempfile.gettempdir()) / "t1054a_preview_probe.png"
    if out.exists():
        out.unlink()
    assert window._render_chart_designer_preview(out, 72) is True
    assert out.exists() and out.stat().st_size > 0

    pix = QImage(str(out))
    assert not pix.isNull(), "预览产物不可解码"
    assert pix.width() > 0 and pix.height() > 0
    # 尺寸抽样：72dpi 下横纵比应为画幅比（默认模板 6.4 x 4.8 in → 4:3），容差 ±15%
    ratio = pix.width() / pix.height()
    assert abs(ratio - (6.4 / 4.8)) / (6.4 / 4.8) <= 0.15, ratio
