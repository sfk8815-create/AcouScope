# SPDX-License-Identifier: GPL-3.0-only
"""T-1090 增量快捷键守卫测（全离屏，禁 MainWindow.show()）。

覆盖：
① 四个缺口 action 键位非空且 == 指定键（★ PI-T82 E-4：``action_chart_designer``
   无 setObjectName ⇒ 一律按属性 ``window.action_*`` 取件，不走 objectName/findChild）；
② 全 QAction 键位两两不撞（复用 ``test_menu_restructure::test_action_shortcuts_are_unique``
   同口径扫描：白名单为空，任一重复即失败）；
③ 四个新键不与 ``ShortcutManager.register_global`` 注册表撞（读实例条目比对）；
④ ``action_multitrack_compare.shortcut().isEmpty()`` 仍为 True
   （``test_menu_restructure:149`` + ``test_multitrack_exit_t1087:129`` 双冻结不回退）；
⑤ 反证：两 action 同键 ⇒ ② 的扫描必红（扫描本身有牙）。
"""

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtGui import QAction, QKeySequence

from acouscope.app.controller import AppController
from acouscope.i18n import set_language
from acouscope.ui.main_window import MainWindow
from acouscope.ui.shortcuts import ShortcutManager

# 施工令 T-1090 M-1 映射（PI-T82 预检实测四键空闲）
SHORTCUT_MAP = {
    "action_tuning_ruler": "F9",
    "action_chart_designer": "F10",
    "action_region_stats": "Ctrl+Shift+S",
    # T-1109 IM-32：Ctrl+Shift+P 改挂报告预览入口（原 action_export_report）
    "action_report_preview": "Ctrl+Shift+P",
}


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """离屏 MainWindow（不 show）+ 内存音频；HOME/数据目录隔离到 tmp。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    set_language("zh_CN")
    controller = AppController()
    sr = 8000
    t = np.arange(sr) / sr
    controller.load_from_array(0.4 * np.sin(2 * np.pi * 440 * t), sr)
    w = MainWindow(controller)
    yield w
    w.close()


def _scan_qaction_key_conflicts(window) -> tuple[dict, list]:
    """窗口内全部 QAction 键位 → (键 → holder, 冲突列表)。

    holder 口径与 ``test_menu_restructure`` 唯一性扫描一致：objectName 回落 text。
    """
    seen: dict = {}
    conflicts: list = []
    for act in window.findChildren(QAction):
        for seq in act.shortcuts():
            key = seq.toString()
            if not key:
                continue
            holder = f"{act.objectName() or act.text()}"
            if key in seen and seen[key] != holder:
                conflicts.append((key, seen[key], holder))
            else:
                seen[key] = holder
    return seen, conflicts


# ---------------------------------------------------------------------------
# ① 四 action 键位非空且 == 指定键
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("attr,expected", sorted(SHORTCUT_MAP.items()))
def test_increment_shortcut_assigned(window, attr, expected):
    act = getattr(window, attr)
    assert not act.shortcut().isEmpty(), f"{attr} 缺快捷键"
    assert act.shortcut().toString() == expected


# ---------------------------------------------------------------------------
# ② 全 QAction 键位两两不撞（含新增四键）
# ---------------------------------------------------------------------------


def test_all_qaction_shortcuts_unique(window):
    _, conflicts = _scan_qaction_key_conflicts(window)
    assert not conflicts, f"键位冲突: {conflicts}"


# ---------------------------------------------------------------------------
# ③ 新键不撞 ShortcutManager 全局注册表
# ---------------------------------------------------------------------------


def test_new_keys_do_not_collide_with_global_registry(window):
    entries = ShortcutManager.instance()._entries
    assert entries, "全局注册表为空 ⇒ 本测失去意义（反向守卫）"
    registered = {
        QKeySequence(key).toString()
        for e in entries.values()
        for key in (e.default_key, e.current_key)
    }
    for attr in SHORTCUT_MAP:
        key = getattr(window, attr).shortcut().toString()
        assert key, f"{attr} 键位为空"
        assert key not in registered, (
            f"{attr} 新键 {key} 与全局注册键撞: {sorted(registered)}"
        )


# ---------------------------------------------------------------------------
# ④ multitrack_compare 键位仍空（双冻结不回退）
# ---------------------------------------------------------------------------


def test_multitrack_compare_keybinding_stays_empty(window):
    assert window.action_multitrack_compare.shortcut().isEmpty() is True


# ---------------------------------------------------------------------------
# ⑤ 反证：人为制造同键 ⇒ 唯一性扫描必红
# ---------------------------------------------------------------------------


def test_duplicate_key_makes_scan_red(window):
    assert getattr(window, "action_tuning_ruler").shortcut().toString() == "F9"
    window.action_fft.setShortcut("F9")
    _, conflicts = _scan_qaction_key_conflicts(window)
    assert any(c[0] == "F9" for c in conflicts), (
        f"人为同键 F9 未被扫描判红: {conflicts}"
    )
