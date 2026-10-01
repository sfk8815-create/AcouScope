# SPDX-License-Identifier: GPL-3.0-only
"""CB-007 图标引擎回归测试（T-601 四态染色渲染 + T-602 通用图标库）。

断言纪律：
- offscreen 全程（conftest 已 setdefault）；不构造 MainWindow / 不 QDialog / 不 .show()；
- 颜色断言走主题语义色（icon_state_color）与像素采样（采样点由 SVG viewBox 中心推导，
  不硬编码绝对布局像素）；图标库几何断言用 viewBox 结构特征（24×24）而非位图尺寸。
"""
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import pytest


from acouscope.ui import theme

# T-602：ICONS 中本波须落到 generic/ 的既有映射名 + T-604 待替换名
_MAPPED_NAMES = [
    "ai", "settings", "layers", "inspect", "files",
    "chevron_down", "chevron_right", "close", "download", "info",
    "open", "undo", "redo", "export",
]
_STATES = ("default", "hover", "active", "disabled")


@pytest.fixture(autouse=True)
def _theme_dark(qapp):
    """本模块用例统一从 dark 主题出发，结束后还原 dark，避免污染会话内其它主题测试。

    T-1027（IM-09）防御性 pin：本模块断言要求既有映射名解析到 generic/，而
    theme.icon_style() 会惰性自举读盘（真实用户配置 icon_style=macos 时本模块恒红）。
    故进入时把 _icon_style 钉为 "generic"（不读盘），退出时还原进入前的原值。
    """
    _prev_icon_style = theme._icon_style
    theme._icon_style = "generic"
    theme.apply_theme("dark")
    yield
    theme._icon_style = _prev_icon_style
    theme.apply_theme("dark")


def _generic_dir() -> pathlib.Path:
    base = pathlib.Path(theme.__file__).resolve().parent.parent / "resources" / "icons"
    return base / "generic"


def _icon_svg_files() -> list:
    return sorted(p for p in _generic_dir().glob("*.svg"))


# ---------------------------------------------------------------------------
# T-602：resources/icons/generic 图标库结构（viewBox 结构特征断言）
# ---------------------------------------------------------------------------

def test_generic_catalog_at_least_14_and_conforms():
    """≥14 个 SVG：24×24 viewBox / width-height / currentColor 单色 / 线宽 1.5-2 / 许可声明。"""
    files = _icon_svg_files()
    assert len(files) >= 14
    for p in files:
        text = p.read_text(encoding="utf-8")
        assert re.search(r'viewBox="0 0 24 24"', text), f"{p.name} viewBox"
        assert re.search(r'width="24"', text) and re.search(r'height="24"', text), f"{p.name} w/h"
        # 单色：颜色属性只允许 none / currentColor，不允许残留具体 hex
        for m in re.finditer(r'(?:fill|stroke)="([^"]+)"', text):
            assert m.group(1) in ("none", "currentColor"), f"{p.name} 残留色值 {m.group(1)}"
        assert "currentColor" in text, f"{p.name} 缺 currentColor"
        sw = re.search(r'stroke-width="([\d.]+)"', text)
        assert sw is not None and 1.5 <= float(sw.group(1)) <= 2, f"{p.name} 线宽 {sw and sw.group(1)}"
        # 开源来源 + 许可声明（T-602 借库铁律）
        assert "Source:" in text and "License:" in text, f"{p.name} 缺来源/许可声明"


def test_icons_mapping_resolves_to_generic():
    """ICONS 中既有映射名 + T-604 4 名全部落到 resources/icons/generic/ 真实文件。"""
    generic = _generic_dir()
    for name in _MAPPED_NAMES:
        assert name in theme.ICONS
        p = theme.icon_path(name)
        assert p is not None, f"{name} 无资源"
        assert p.is_relative_to(generic), f"{name} 未指向 generic/: {p}"


def test_signature_dir_placeholder_exists():
    """signature/ 专业业务目录本波留空但目录结构就位（README 占位）。"""
    base = pathlib.Path(theme.__file__).resolve().parent.parent / "resources" / "icons"
    assert (base / "signature").is_dir()
    assert (base / "signature" / "README.md").exists()


# ---------------------------------------------------------------------------
# T-601：四态染色渲染 + 旧签名兼容 + 空回退 + 缓存
# ---------------------------------------------------------------------------

def _icon_svg_center() -> tuple:
    """采样点取 generic/x.svg 的 viewBox 中心（两对角笔画交点），推导而非硬编码像素。"""
    text = (_generic_dir() / "x.svg").read_text(encoding="utf-8")
    vb = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', text)
    assert vb is not None
    return int(float(vb.group(1)) // 2), int(float(vb.group(2)) // 2)


def _sample(icon, size: int = 24):
    pm = icon.pixmap(size, size)
    assert not pm.isNull()
    return pm.toImage().pixelColor(*_icon_svg_center())


def _rgb(hexcolor: str):
    return tuple(int(hexcolor.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))


def test_four_state_colors_follow_theme_semantics(qapp):
    """四态渲染：采样色随 state 语义色变化，且与主题角色值一致（default≠disabled）。"""
    theme.apply_theme("dark")
    for state in _STATES:
        icon = theme.get_icon("close", state)
        assert icon is not None and not icon.isNull(), state
        expected = _rgb(theme.icon_state_color(state))
        got = _sample(icon)
        assert got.alpha() > 0, f"{state} 采样点透明（未渲染出笔画）"
        # 通道误差 ≤2：抗锯齿/色彩空间容差内应等于替换后的语义色
        diffs = (abs(got.red() - expected[0]),
                 abs(got.green() - expected[1]),
                 abs(got.blue() - expected[2]))
        assert all(d <= 2 for d in diffs), \
            f"{state}: 采样 {got.red(), got.green(), got.blue()} ≠ 语义 {expected}"
    # 语义色映射 = 当前主题角色派生，且四态不互相依赖
    c = theme.colors()
    assert theme.icon_state_color("default") == c["text"]
    assert theme.icon_state_color("hover") == c["accent"]
    assert theme.icon_state_color("active") == c["accent_text"]
    assert theme.icon_state_color("disabled") == c["sub"]
    assert theme.icon_state_color("default") != theme.icon_state_color("disabled")


def test_icon_state_color_unknown_falls_back():
    """未知 state 回落 default 语义色，不抛异常。"""
    c = theme.colors()
    assert theme.icon_state_color("__bogus__") == c["text"]


def test_legacy_signature_default_state_compatible(qapp):
    """get_icon(name) 旧调用兼容：无 state 参数 = default 语义染色；缺失名空回退不抛。"""
    icon_default = theme.get_icon("close")
    icon_explicit = theme.get_icon("close", "default")
    assert not icon_default.isNull() and not icon_explicit.isNull()
    assert _rgb(theme.colors()["text"]) == _rgb(theme.icon_state_color("default"))
    # 资源缺失（含 ICONS 已映射但文件未补入）→ 空 QIcon，不抛
    assert theme.icon_path("__no_such__") is None
    empty = theme.get_icon("__no_such__")
    assert empty is not None and empty.isNull()
    # T-1001：generic 已补齐 play/stop/record → 改用临时注入映射，等价覆盖
    # 「ICONS 已映射但文件缺失 → 空 QIcon」分支（守卫不降，非静默归因）
    theme.ICONS["__mapped_missing__"] = "generic/__absent__.svg"
    try:
        missing_but_mapped = theme.get_icon("__mapped_missing__")
        assert missing_but_mapped is not None and missing_but_mapped.isNull()
    finally:
        theme.ICONS.pop("__mapped_missing__", None)


def test_icon_cache_identity_and_theme_invalidation(qapp):
    """缓存：(name,state) 二次取同实例；主题切换后失效重建。"""
    theme.apply_theme("dark")
    a = theme.get_icon("settings", "hover")
    b = theme.get_icon("settings", "hover")
    assert a is b, "同 name+state 未命中缓存"
    c = theme.get_icon("settings", "disabled")
    assert c is not a, "不同 state 应不同实例"
    theme.apply_theme("light")
    d = theme.get_icon("settings", "hover")
    assert d is not a, "主题切换后图标缓存应失效重建"
    # light 主题下 hover = 其 accent；再切回 dark 恢复原色
    theme.apply_theme("dark")
    e = theme.get_icon("settings", "hover")
    assert e is not a  # 主题往返 = 缓存重建（同一语义不同实例亦可）

def test_cache_does_not_leak_across_theme(qapp):
    """主题切换后取回的图标颜色跟随新主题。"""
    theme.apply_theme("light")
    icon = theme.get_icon("close", "disabled")
    expected = _rgb(theme.colors()["sub"])
    got = _sample(icon)
    diffs = (abs(got.red() - expected[0]),
             abs(got.green() - expected[1]),
             abs(got.blue() - expected[2]))
    assert all(d <= 2 for d in diffs)
