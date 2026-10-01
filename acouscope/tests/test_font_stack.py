# SPDX-License-Identifier: GPL-3.0-only
"""T-1037 守卫（跨平台字体回落链）。

语义源：`.pi/knowledge/RELEASE_T-1037.md`（裁定 O1~O6）+ `.pi/knowledge/DESIGN_inspiration_notes.md §8.3`。
覆盖：
① 三平台覆盖：`ui_font_families()` / `ui_mono_families()` 各含 macOS / Windows / Linux 至少一个目标族名；
② 顺序即优先级：macOS 目标仍在链首（禁改 macOS 现有观感）；
③ 泛型剔除：helper 返回值不含泛型关键字（QFont.setFamilies 只接受具体族名）；
④ 数据源保留泛型兜底：`TOKENS["typography"]["family"|"mono"]` 字符串末尾仍为泛型；
⑤ 基座传整链：`__main__.py` 源码含 `setFamilies(`，且不含 family 的「只取首项」旧写法；
⑥ 唯一源：生产源码中族名字面量只允许出现在 `theme.py`（`visualization/**` 自有链单独登记）；
⑦ 静态：新增 helper 与基座片段的行内 hex/px = 0。

口径：全离屏、纯源码级/纯函数级断言（与环境字体安装情况无关）；
不在测试进程内施加 Fusion 基座（会静默改动其它 GUI 测试的控件度量 —— 基座实效由独立
离屏进程单独实测，见报告）。
"""

import inspect
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import pytest

pytest.importorskip("PyQt6")

from acouscope.ui import theme  # noqa: E402

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "acouscope"
_MAIN_PY = _SRC / "__main__.py"

# 平台目标白名单（按「该族名默认随哪个平台的系统提供」归类，用于覆盖性断言）
MAC_FAMILIES = {"PingFang SC", "Helvetica Neue", "SF Mono", "Menlo"}
WIN_FAMILIES = {"Segoe UI", "Consolas", "Microsoft YaHei UI", "Microsoft YaHei"}
LINUX_FAMILIES = {
    "Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Micro Hei", "DejaVu Sans",
    "DejaVu Sans Mono", "Liberation Mono", "Noto Sans Mono CJK SC",
}
PLATFORM_SETS = (MAC_FAMILIES, WIN_FAMILIES, LINUX_FAMILIES)

GENERIC_KEYWORDS = {
    "sans-serif", "serif", "monospace", "cursive", "fantasy", "system-ui",
}

# 生产源码中的族名字面量扫描目标（含旧链目标，防「链外再写一份」）
FAMILY_LITERALS = sorted(MAC_FAMILIES | WIN_FAMILIES | LINUX_FAMILIES)

_HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_PX_RE = re.compile(r"\b\d+px\b")


def _src_py_files() -> list[pathlib.Path]:
    return sorted(p for p in _SRC.rglob("*.py") if p.is_file() and not p.name.startswith("._"))  # AppleDouble 旁车（非 UTF-8），非源码


# ----------------------------------------------------------------------
# ① / ② 三平台覆盖 + macOS 链首
# ----------------------------------------------------------------------

def test_family_chain_covers_three_platforms():
    for name, chain in (("ui_font_families", theme.ui_font_families()),
                        ("ui_mono_families", theme.ui_mono_families())):
        assert chain, f"{name}() 不得为空"
        for label, group in (("macOS", MAC_FAMILIES), ("Windows", WIN_FAMILIES),
                             ("Linux", LINUX_FAMILIES)):
            assert group & set(chain), f"{name}() 缺 {label} 目标族名（链={chain}）"


def test_macos_targets_stay_at_chain_head():
    assert theme.ui_font_families()[0] in MAC_FAMILIES
    assert theme.ui_mono_families()[0] in MAC_FAMILIES


# ----------------------------------------------------------------------
# ③ 泛型剔除
# ----------------------------------------------------------------------

def test_generic_keywords_excluded_from_helper_output():
    for name, chain in (("ui_font_families", theme.ui_font_families()),
                        ("ui_mono_families", theme.ui_mono_families())):
        hit = [f for f in chain if f.lower() in GENERIC_KEYWORDS]
        assert not hit, f"{name}() 返回列表含泛型关键字：{hit}"


# ----------------------------------------------------------------------
# ④ 数据源保留泛型兜底（未把泛型从数据源删除）
# ----------------------------------------------------------------------

def test_source_chain_keeps_generic_fallback_at_tail():
    fam = theme.TOKENS["typography"]["family"]
    mono = theme.TOKENS["typography"]["mono"]
    assert fam.strip().endswith("sans-serif")
    assert mono.strip().endswith("monospace")
    # 泛型兜底仍在链尾（顺序即优先级）
    assert [p.strip() for p in fam.split(",")][-1] == "sans-serif"
    assert [p.strip() for p in mono.split(",")][-1] == "monospace"


# ----------------------------------------------------------------------
# ⑤ 基座传整链（源码级，防回退）
# ----------------------------------------------------------------------

def test_main_entry_passes_full_chain():
    main_src = _MAIN_PY.read_text(encoding="utf-8")
    assert "setFamilies(" in main_src
    assert "ui_font_families()" in main_src
    # 反向断言：不再「只取首项」
    assert 'split(",")[0]' not in main_src
    assert 'TOKENS["typography"]["family"].split' not in main_src


# ----------------------------------------------------------------------
# ⑥ 唯一源：族链字面量只在 theme.py；helper 引用只在 入口/定义 两处
# ----------------------------------------------------------------------

def test_family_literals_single_source():
    offenders: dict[str, list[str]] = {}
    viz_hits: dict[str, list[str]] = {}
    for path in _src_py_files():
        if path == _SRC / "ui" / "theme.py":
            continue
        text = path.read_text(encoding="utf-8")
        hit = [name for name in FAMILY_LITERALS if name in text]
        if not hit:
            continue
        rel = str(path.relative_to(_SRC))
        (viz_hits if rel.startswith("visualization" + "/") else offenders)[rel] = hit
    assert offenders == {}, f"theme.py 之外出现族名字面量：{offenders}"
    # visualization/** 自持图表侧链（本任务只读核对，不统一）→ 允许命中但须唯一
    assert set(viz_hits) <= {"visualization/mpl_style.py"}, viz_hits


def test_helper_references_confined_to_entry_and_definition():
    ref_files: set[str] = set()
    for path in _src_py_files():
        text = path.read_text(encoding="utf-8")
        if "ui_font_families" in text or "ui_mono_families" in text:
            ref_files.add(str(path.relative_to(_SRC)))
    assert ref_files <= {"ui/theme.py", "__main__.py"}, f"族链 helper 越界引用：{ref_files}"
    assert "__main__.py" in ref_files


# ----------------------------------------------------------------------
# ⑦ 静态：新增行为零 hex / 零 px
# ----------------------------------------------------------------------

def test_new_code_has_no_literal_hex_or_px():
    helper_src = "\n".join(
        inspect.getsource(obj)
        for obj in (theme._parse_family_chain, theme.ui_font_families,
                    theme.ui_mono_families)
    )
    main_lines = _MAIN_PY.read_text(encoding="utf-8").splitlines()
    base_src = "\n".join(main_lines[50:70])  # 基座段
    for label, src in (("helper", helper_src), ("base", base_src)):
        assert not _HEX_RE.search(src), f"{label} 出现字面 hex"
        assert not _PX_RE.search(src), f"{label} 出现字面 px"
