# SPDX-License-Identifier: GPL-3.0-only
"""T-502 设计令牌与暗色默认回归测试。"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from acouscope.ui import theme
from acouscope.utils.config import Settings


def test_tokens_structure():
    t = theme.TOKENS
    assert t["spacing"]["sm"] == 8
    assert t["spacing"]["md"] == 16
    assert t["radius"]["md"] == 8
    assert t["elevation"]["mid"] == 4
    assert t["typography"]["h1"] >= t["typography"]["h2"] >= t["typography"]["body"]
    assert "family" in t["typography"] and "mono" in t["typography"]
    sem = t["semantic"]
    assert sem["warning"] == "#f59e0b"
    assert sem["error"] == "#ef4444"
    assert sem["success"] == "#10b981"
    assert sem["info"] == "#3b82f6"


def test_default_theme_is_dark():
    assert Settings().theme == "dark"


def test_themes_preserved():
    # 9 套主题全保留 + system 跟随
    for tid in ["default", "light", "dark", "ocean", "forest",
                "sunset", "lavender", "graphite", "sepia", "system"]:
        assert tid in theme.THEME_ORDER


def test_apply_dark_and_system(qapp):
    theme.apply_theme("dark")
    assert theme.colors()["id"] == "dark"
    theme.apply_theme("system")  # 跟随系统不抛即可
    theme.apply_theme("dark")


def test_qss_uses_tokens_and_semantic(qapp):
    theme.apply_theme("dark")
    qss = theme._qss(theme.colors())
    assert theme.TOKENS["semantic"]["warning"] in qss
    assert theme.TOKENS["semantic"]["error"] in qss
    assert 'level="success"' in qss and 'level="info"' in qss


def test_icon_layer_safe():
    for name in ["open", "settings", "layers", "inspect", "ai", "files",
                 "play", "chevron_down", "export"]:
        assert name in theme.ICONS
        ic = theme.get_icon(name)  # 资源缺失也不抛
        assert ic is not None
    assert theme.icon_path("__not_exist__") is None
    assert theme.get_icon("__not_exist__") is not None
