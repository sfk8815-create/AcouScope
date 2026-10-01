# SPDX-License-Identifier: GPL-3.0-only
"""T-1084 守卫测：O-4 图标扩容（ICONS 30→31 授权单键）边界与派生幂等。

断言纪律：全离屏；构造 MainWindow 但不 show()、不弹模态。
"""

import ast
import importlib.util
import pathlib
import shutil
import subprocess

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

from acouscope.app.controller import AppController
from acouscope.ui import theme
from acouscope.ui.main_window import MainWindow
from tests._pin_baselines import ICONS_LOGICAL_NAME_COUNT

_PKG_ROOT = pathlib.Path(__file__).resolve().parents[1]
_REPO_ROOT = _PKG_ROOT.parent
_ICON_ROOT = _PKG_ROOT / "src" / "acouscope" / "resources" / "icons"
_THEME_PY = _PKG_ROOT / "src" / "acouscope" / "ui" / "theme.py"
_DERIVE_PY = _PKG_ROOT / "scripts" / "derive_icon_styles.py"
_STYLES = ("generic", "macos", "win", "mint")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 20.0)) / sr
    controller.load_from_array(0.5 * np.sin(2 * np.pi * 300 * t), sr)

    w = MainWindow(controller)
    yield w
    w.close()


def test_tuning_ruler_action_icon_not_null(window):
    assert not window.action_tuning_ruler.icon().isNull()


def test_tuning_ruler_assets_complete_four_styles():
    for style in _STYLES:
        svg = _ICON_ROOT / style / "tuning_ruler.svg"
        assert svg.exists(), f"{style}/tuning_ruler.svg 缺失"
        assert svg.stat().st_size > 0, f"{style}/tuning_ruler.svg 为空"


def test_icons_expanded_to_31():  # 名内 31 系 T-1084 历史里程碑（改名动 nodeid·保名）；真实计数现由 ICONS_LOGICAL_NAME_COUNT 把守（现 33）
    assert len(theme.ICONS) == ICONS_LOGICAL_NAME_COUNT
    assert theme.ICONS["tuning_ruler"] == "generic/tuning_ruler.svg"


def _icon_styles_keys(source: str) -> list:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "ICON_STYLES":
                return sorted(
                    elt.value for elt in node.value.elts
                    if isinstance(elt, ast.Constant)
                )
    raise AssertionError("theme.py 未找到 ICON_STYLES 赋值")


def test_icon_styles_registry_untouched_vs_head():
    out = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "show",
         "HEAD:acouscope/src/acouscope/ui/theme.py"],
        capture_output=True, text=True, check=True,
    )
    head_keys = _icon_styles_keys(out.stdout)
    now_keys = _icon_styles_keys(_THEME_PY.read_text(encoding="utf-8"))
    assert set(now_keys) ^ set(head_keys) == set(), \
        f"ICON_STYLES 键集越界：对称差 {set(now_keys) ^ set(head_keys)}"


def test_derivation_idempotent_existing_svgs_unchanged(tmp_path):
    work = tmp_path / "icons"
    shutil.copytree(_ICON_ROOT, work)
    before = {
        p.relative_to(work): p.read_bytes()
        for style in _STYLES for p in (work / style).glob("*.svg")
    }
    spec = importlib.util.spec_from_file_location("t1084_derive", _DERIVE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.build(work)
    after = {
        p.relative_to(work): p.read_bytes()
        for style in _STYLES for p in (work / style).glob("*.svg")
    }
    assert set(before) <= set(after)
    for rel, blob in before.items():
        assert after[rel] == blob, f"派生改动了既有图标：{rel}"
