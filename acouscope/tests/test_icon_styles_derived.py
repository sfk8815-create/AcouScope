# SPDX-License-Identifier: GPL-3.0-only
"""T-1076：generic 基准与 macos/win/mint 派生件四风格一致性回归。

背景：T-1076 手改 generic 三枚 svg（add_track / room_acoustic / room_modal）后必须
重跑 `scripts/derive_icon_styles.py`，否则派生套与基准漂移。本测档把「派生已同步」
钉成可机检断言：
  ① 每名 × 每风格同名文件存在；rect/path/circle/polygon 标签计数一致，
     <g> 计数恒为 generic+1（derive 外裹一层 <g transform>，已知可预期变换）；
  ② 派生件图元行与基准逐字一致（与脚本 _assert_semantics_preserved 同口径，
     但检盘上现状，防「改了 generic 忘重跑 derive」）；
  ③ T-1076 几何断言：add_track 轨条右缘与加号横笔间隙 ≥1px；
     room 两枚元素集合显性不同（modal 无共用外框）。
纪律：零子进程、零 Qt 依赖（纯文本核对）。
"""
import importlib.util
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

_ICON_ROOT = (Path(__file__).resolve().parents[1]
              / "src" / "acouscope" / "resources" / "icons")
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "derive_icon_styles.py"
_DERIVED = ("macos", "win", "mint")
_TAGS = ("rect", "path", "circle", "polygon")


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "t1076_derive_icon_styles", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _count(text: str, tag: str) -> int:
    return len(re.findall(rf"<{tag}[ >/]", text))


def test_generic_and_derived_tag_counts_match():
    """① 每个 generic 名的三套派生件：图元标签计数一致；<g> 恒 +1（外裹层）。"""
    bases = sorted((_ICON_ROOT / "generic").glob("*.svg"))
    assert bases, "generic 目录为空"
    for base in bases:
        g_text = base.read_text(encoding="utf-8")
        for style in _DERIVED:
            d = _ICON_ROOT / style / base.name
            assert d.exists(), f"{style}/{base.name} 缺派生件（derive 未重跑？）"
            d_text = d.read_text(encoding="utf-8")
            for tag in _TAGS:
                assert _count(d_text, tag) == _count(g_text, tag), \
                    f"{style}/{base.name} <{tag}> 计数漂移"
            assert _count(d_text, "g") == _count(g_text, "g") + 1, \
                f"{style}/{base.name} <g> 外裹层数量异常"


def test_derived_files_not_stale_vs_generic():
    """② 盘上派生件图元行与基准逐字一致（改 generic 忘重跑 derive 即红）。"""
    mod = _load_script()
    bases = sorted((_ICON_ROOT / "generic").glob("*.svg"))
    for base in bases:
        base_text = base.read_text(encoding="utf-8")
        for style in _DERIVED:
            d_text = (_ICON_ROOT / style / base.name).read_text(encoding="utf-8")
            out_el = [e for e in mod._elements(d_text)
                      if e != "</g>" and not e.startswith("<g ")]
            assert mod._elements(base_text) == out_el, \
                f"{style}/{base.name} 与 generic 漂移（需重跑 derive 脚本）"


def test_t1076_add_track_plus_clearance():
    """③a M-1(b)：轨条右缘 16 与加号横笔起 17 间隙 ≥1px；旧式 M15.5 已消失。"""
    text = (_ICON_ROOT / "generic" / "add_track.svg").read_text(encoding="utf-8")
    assert "M15.5" not in text
    rect = re.search(r'<rect x="([\d.]+)" y="[\d.]+" width="([\d.]+)"', text)
    assert rect, "add_track 缺轨条 rect"
    rail_right = float(rect.group(1)) + float(rect.group(2))
    hline = re.search(r'<path d="M([\d.]+) 12h', text)
    assert hline, "add_track 加号横笔缺失"
    assert float(hline.group(1)) - rail_right >= 1.0, "加号与轨条间隙不足 1px"


def test_t1076_room_pair_distinguishable():
    """③b M-2(A)：room_modal 无共用外框、以节点环构成；与 acoustic 元素集合显性不同。"""
    acoustic = (_ICON_ROOT / "generic" / "room_acoustic.svg").read_text(encoding="utf-8")
    modal = (_ICON_ROOT / "generic" / "room_modal.svg").read_text(encoding="utf-8")
    assert 'rect x="3" y="4" width="18"' in acoustic  # acoustic 保留外框（现状）
    assert "<rect" not in modal, "modal 仍共用外框，未分化"
    assert _count(modal, "circle") >= 9, "modal 节点数不足"
    sig = lambda t: {_count(t, tag) for tag in _TAGS}  # noqa: E731
    assert sig(acoustic) != sig(modal), "两枚元素计数集合相同，未显性分化"


def test_t1077_chart_designer_open_frame():
    """T-1077：chart_designer 去封闭外框（零 rect）、真源常量与 generic 盘上件一致。"""
    text = (_ICON_ROOT / "generic" / "chart_designer.svg").read_text(encoding="utf-8")
    assert "<rect" not in text, "chart_designer 残留封闭外框"
    assert _count(text, "path") >= 5, "轴/柱/滑块元素不齐"
    mod = _load_script()
    assert mod.render_base("chart_designer") == text, \
        "generic 盘上件与真源 MISSING_GENERIC_PRIMITIVES 漂移"
