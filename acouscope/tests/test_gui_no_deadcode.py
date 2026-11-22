"""G-3 死码守卫：登记表防回潮 + 活路径正对照。

背景（GUI-3 设计约定）：`main_window._run_sota_analysis` 为整块死码
（自带 SotaWorker、`self._sota_worker` 仅赋值零读取），生产路径实际走
`_detect_with_sota`。G-3 已删该块，本档钉死「删掉的不许长回来」。

判据来源：`grep -rn "_run_sota_analysis" acouscope/src` = 0；
`grep -c "_sota_worker" main_window.py` = 0；`grep -rn "_detect_with_sota" acouscope/src` = 2。

G-4 待证候选（**未删、本档不约束**，仅备查）：ai_interpret._selected_llama_info /
refresh_for_current_view、batch_metadata_module.set_workspace、align.reference_ms、
compare_diff.over_time_s / voiced_time_s、track_header.track_id_of、
empty_state.set_message / set_drop_hint / set_action_text、panel_container.add_widget、
workspace.toggle_index。
"""

from __future__ import annotations

from pathlib import Path

# 登记表：文件 → 已退役符号。删过的名字一旦在源码里重新出现，本档即红。
_RETIRED: dict[str, tuple[str, ...]] = {
    "ui/main_window.py": ("_run_sota_analysis", "_sota_worker"),
}


def _src_root() -> Path:
    """返回 acouscope 包根（src/acouscope）。"""
    import acouscope.ui.main_window as mw

    # .../src/acouscope/ui/main_window.py → parents[1] = .../src/acouscope
    return Path(mw.__file__).resolve().parents[1]


def _find_symbols(text: str, symbols: tuple[str, ...]) -> list[str]:
    """在源码文本中查找退役符号（逐行子串匹配，含注释/字符串内的回潮）。"""
    found = []
    for sym in symbols:
        for line in text.splitlines():
            if sym in line:
                found.append(sym)
                break
    return found


def test_run_sota_analysis_is_gone():
    """`_run_sota_analysis` 必须不存在（删码后的反证断言）。"""
    from acouscope.ui.main_window import MainWindow

    assert not hasattr(MainWindow, "_run_sota_analysis"), (
        "死码 _run_sota_analysis 回潮：生产零引用，活路径是 _detect_with_sota"
    )


def test_sota_worker_attribute_is_gone():
    """`_sota_worker` 属性名不得再现（原为死码块内唯一赋值、零读取）。"""
    from acouscope.ui.main_window import MainWindow

    assert not hasattr(MainWindow, "_sota_worker")


def test_retired_symbols_not_resurrected():
    """登记表逐条：已退役符号不得在包内任何 .py 中重新出现。"""
    root = _src_root()
    offenders = []
    for rel, symbols in _RETIRED.items():
        path = root / rel
        assert path.is_file(), f"登记表指向的文件不存在：{rel}"
        found = _find_symbols(path.read_text(encoding="utf-8"), symbols)
        if found:
            offenders.append((rel, found))
    assert not offenders, f"已退役符号回潮：{offenders}"


def test_registry_scan_has_teeth():
    """判别力自证：同一扫描器对含退役符号的假源码必须报红。"""
    fake = (
        "class MainWindow:\n"
        "    def _run_sota_analysis(self, data, sr, backend_name):\n"
        "        self._sota_worker = None\n"
    )
    found = _find_symbols(fake, ("_run_sota_analysis", "_sota_worker"))
    assert found == ["_run_sota_analysis", "_sota_worker"], (
        f"守卫无判别力：假源码应被抓到，实际 {found}"
    )
    # 反向对照：干净源码必须零命中（防「恒红」假守卫）
    assert _find_symbols("def _detect_with_sota(self):\n    pass\n",
                         ("_run_sota_analysis",)) == []


def test_live_path_detect_with_sota_intact():
    """正对照：活路径 `_detect_with_sota` 定义与调用点均在（删码未误伤）。"""
    root = _src_root()
    text = (root / "ui/main_window.py").read_text(encoding="utf-8")
    assert "def _detect_with_sota(self" in text
    assert text.count("_detect_with_sota") >= 2, (
        "活路径引用数下降：应至少含定义 + 调用点各一处"
    )
