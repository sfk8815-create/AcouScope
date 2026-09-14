# SPDX-License-Identifier: GPL-3.0-only
"""T-1027（IM-09）配置隔离回归锁：测试进程不得读写真实用户配置目录。

背景：`theme.icon_style()` 惰性自举 → `Settings.load()` → `get_config_dir()` +
`_settings_candidates()`（其内部再取 `config_dir_candidates()`）。若 conftest 只隔离
`get_data_dir`，真实 `settings.json` 会外泄进测试进程——本机 `icon_style=macos` 时
`test_cb007_icon_engine` 的 generic 断言恒红，掩盖真实回归信号。

断言纪律：offscreen；不构造 MainWindow / 不 show()；除 tmp_path 外不写任何路径。
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from acouscope.ui import theme
from acouscope.utils import config as cfg


def test_config_dir_is_isolated_under_tmp_path(tmp_path):
    """配置/数据目录及其候选链全部落在测试临时目录内（零真实用户路径）。"""
    for d in (cfg.get_config_dir(), cfg.get_data_dir()):
        assert d.is_relative_to(tmp_path), f"目录未隔离到 tmp_path: {d}"
    for chain in (cfg.config_dir_candidates(), cfg.data_dir_candidates()):
        assert chain, "候选链不得为空"
        for d in chain:
            assert d.is_relative_to(tmp_path), f"候选链外泄真实路径: {d}"


def test_settings_load_does_not_read_real_user_config():
    """`Settings.load()` 默认路径不读真实 settings.json。

    判据：默认值即可证伪外泄——若读到真实配置（本机 icon_style=macos）则失败。"""
    loaded = cfg.Settings.load()
    assert loaded.icon_style == "generic"
    assert loaded._filepath.is_relative_to(cfg.get_config_dir())


def test_settings_load_reads_isolated_file(tmp_path):
    """隔离目录内的 settings.json 仍被正常读取（隔离 ≠ 断路）。"""
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"icon_style": "macos"}), encoding="utf-8")
    loaded = cfg.Settings.load()
    assert loaded.icon_style == "macos"
    assert loaded._filepath == p


def test_icon_style_lazy_bootstrap_is_generic_here():
    """回归锁（T-1027 ④）：进程内置 `_icon_style = None` 后 `icon_style()` 必须回落
    generic —— 即便真实机器配置为 macos，测试环境也不得读真实配置。"""
    saved = theme._icon_style
    try:
        theme._icon_style = None
        assert theme.icon_style() == "generic"
    finally:
        theme._icon_style = saved


def test_icon_path_stays_in_generic_after_reset():
    """端到端复现原失败用例的读取路径：重置风格后 `icon_path("ai")` 落在 generic/。"""
    base = pathlib.Path(theme.__file__).resolve().parent.parent
    generic = base / "resources" / "icons" / "generic"
    saved = theme._icon_style
    try:
        theme._icon_style = None
        p = theme.icon_path("ai")
        assert p is not None, "ai 无资源"
        assert p.is_relative_to(generic), f"ai 未指向 generic/: {p}"
    finally:
        theme._icon_style = saved
