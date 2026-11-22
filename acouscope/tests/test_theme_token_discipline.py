# SPDX-License-Identifier: GPL-3.0-only
"""主题令牌纪律守卫：静态扫描（D7）+ 运行时随动（G4a-1b 构造期冻结）回归。

守护对象：
- D7（写死浅色 → 深底隐形）：静态扫描 `ui/**/*.py`（theme.py 除外），
  散落字面 hex 必须为 0（白名单待裁项除外）——写死的浅色在暗主题下会隐形，
  一律须走 `theme.colors()` 角色令牌。
- G4a-1b（构造期冻结）：`RecordSettingsDialog` 的样式须经 `style_when_theme`
  动态注册、随主题随动；dark↔light 切换后 styleSheet 必须真变化，
  且不得冻结在构造瞬间的取值。

口径：全离屏（conftest 已设 QT_QPA_PLATFORM=offscreen）；不构造主窗口、不 show、
不弹模态、不跑事件循环。进入前快照 QSS/palette/令牌三项，收尾原样写回并比快照
自检（不污染别的测试；只回令牌字典不算复原，视觉态须一并复原）。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtGui import QPalette  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

from acouscope.i18n import tr  # noqa: E402
from acouscope.ui import theme  # noqa: E402
from acouscope.ui.widgets.record_settings_dialog import (  # noqa: E402
    RecordSettingsDialog,
)

_UI = Path(__file__).resolve().parents[1] / "src" / "acouscope" / "ui"
# 字面 hex（与 test_ui_visual_language 同一口径正则）。
_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")

# 白名单：仍残留字面 hex 的文件上限（键相对 ui/ 目录）。
# 铁律：禁僵尸项——某文件清零后必须删对应条目（实际 0 却留条目 = 本测试红）。
# 禁把上限调宽迁就现状（新增散落 hex 一律先令牌化再入本表）。
#   transport_bar.py        = 13 → G4a-2 已令牌化清零，条目已删（见 git 历史）。
#   record_settings_dialog  = 1   → 唯一残留 #b45309 为待裁语义色（浅底可读性
#                优于 semantic.warning，源内已注「暂留待裁」）；定案后须入
#                TOKENS 语义集并删本条目。
ALLOW = {
    "widgets/record_settings_dialog.py": 1,
}


def _scan_ui_hex() -> dict[str, int]:
    """遍历 ui/**/*.py（theme.py 除外），逐行剥「整行注释」（strip() 以 # 开头），
    统计字面 hex 出现次数；仅返回计数 > 0 的文件。"""
    found: dict[str, int] = {}
    for p in sorted(_UI.rglob("*.py")):
        if p.name == "theme.py":
            continue
        cnt = 0
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("#"):
                continue  # 整行注释剥离（口径：仅去整行注释，行内注释不剥）
            cnt += len(_HEX.findall(line))
        if cnt:
            found[p.relative_to(_UI).as_posix()] = cnt
    return found


def test_static_hex_discipline():
    """D7 静态守卫：ui/**（除 theme.py）散落字面 hex——白名单外必须为 0；
    白名单条目实际 ≤ 上限 且 > 0（禁僵尸项）。"""
    found = _scan_ui_hex()
    # (a) 白名单外文件必须零字面 hex（写死浅色 → 深底隐形，D7）
    offenders = {f: c for f, c in found.items() if f not in ALLOW}
    assert offenders == {}, f"白名单外散落字面 hex（D7 写死色）: {offenders}"
    # (b) 白名单条目：实际 ≤ 上限 且 > 0（清零后须删条目，禁僵尸项）
    for f, cap in ALLOW.items():
        actual = found.get(f, 0)
        assert actual <= cap, (
            f"{f} 字面 hex {actual} 处，超白名单上限 {cap}（须先令牌化再入表）"
        )
        assert actual > 0, f"白名单条目 {f} 为僵尸项（实际 {actual}=0，须删条目）"


def _find_label_by_text(root, text: str):
    """在 root 子树里按文字定位 QLabel（loc_label 为构造期局部变量，非 self 属性）。"""
    for lab in root.findChildren(QLabel):
        try:
            if lab.text() == text:
                return lab
        except RuntimeError:
            continue  # C++ 对象已回收（use-after-free 兜底）
    return None


def _snapshot_theme_state() -> dict:
    """进入前快照三项：QSS、QPalette（拷贝）、令牌字典（浅拷贝），须在任何 apply_theme 之前。"""
    app = QApplication.instance()
    return {
        "qss": app.styleSheet(),
        "palette": QPalette(app.palette()),
        "win_color": app.palette().window().color(),
        "theme_id": theme._theme_id,
        "current": dict(theme._current),
    }


def _restore_theme_state(snap: dict) -> None:
    """三项原样写回（防跨测试污染）：先 QSS/palette，再令牌字典（apply_theme 会重新刷 QSS）。

    snap["current"] 无 id 键 = 模块初态：精确复现暗色且无 id 键；否则按进入前
    _theme_id 重放 apply_theme（含调色/QSS/图标全量刷新）。
    """
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(snap["qss"])
        app.setPalette(snap["palette"])
    if snap["current"].get("id") is None:
        theme._theme_id = "dark"
        theme._current.clear()
        theme._current.update(theme.THEMES["dark"])
    else:
        theme.apply_theme(snap["theme_id"])


def _assert_restored(snap: dict) -> None:
    """收尾自检比快照：QSS 与 palette 窗口色须与首快照逐字相同（视觉态一并复原）。"""
    app = QApplication.instance()
    assert app.styleSheet() == snap["qss"], (
        f"污染：收尾 QSS {len(app.styleSheet())} B != 首快照 {len(snap['qss'])} B"
    )
    assert app.palette().window().color() == snap["win_color"], (
        f"污染：收尾 window={app.palette().window().color().name()}"
        f" != 首快照 {snap['win_color'].name()}"
    )


@pytest.fixture(autouse=True)
def _restore_theme(qapp):
    """兜底复原：进入前快照三项，teardown 原样写回并比快照自检。"""
    snap = _snapshot_theme_state()
    yield snap
    _restore_theme_state(snap)
    _assert_restored(snap)


def test_runtime_theme_follows(qapp, _restore_theme):
    """G4a-1b 守卫：RecordSettingsDialog 样式须随主题随动（防构造期冻结）。

    构造面板 → 记 loc_label / lbl_preview 的 styleSheet → apply_theme("dark") 记 A、
    apply_theme("light") 记 B；断言两标签各自随动（A != B 严格式）且 B 含
    light.text_sub；finally 复原进入前三项并比首快照自检（QSS/palette）。
    """
    snap = _restore_theme

    dlg = RecordSettingsDialog()
    try:
        loc_label = _find_label_by_text(dlg, tr("record_settings.output_location"))
        assert loc_label is not None, "未找到「输出位置」标签（loc_label）"

        theme.apply_theme("dark")
        a_loc, a_prev = loc_label.styleSheet(), dlg.lbl_preview.styleSheet()
        theme.apply_theme("light")
        b_loc, b_prev = loc_label.styleSheet(), dlg.lbl_preview.styleSheet()

        # (i) 未冻结（A != B 的严格式）：两标签 styleSheet 须各自真变化——单标签
        #     冻结也必须红（否则 A1 反证无鉴别力：合成元组比较会放过单标签冻结）。
        assert a_loc != b_loc, (
            f"loc_label 构造期冻结：dark/light 样式相同（{a_loc!r}）"
        )
        assert a_prev != b_prev, (
            f"lbl_preview 构造期冻结：dark/light 样式相同（{a_prev!r}）"
        )
        # (ii) D7 取色正确：light 态必须取 light 主题 text_sub（写死浅色 → 深底隐形）
        assert theme.THEMES["light"]["text_sub"] in b_prev, (
            f"lbl_preview light 态未取 light.text_sub（{theme.THEMES['light']['text_sub']}）"
        )
    finally:
        # 复原进入前三项（即便断言失败也执行）
        _restore_theme_state(snap)

    # 收尾自检比快照（不许污染别的测试）
    _assert_restored(snap)