# SPDX-License-Identifier: GPL-3.0-only
"""T-1054 批4d：全仓「无抽屉机制」守卫（防抽屉复活）。

抽屉机制已于批4d 整体退役：`ui/widgets/drawer.py` 删除、在役调用清零、
main_window 登记族/_room_drawer 族死代码清空。本档是**撤除后的防复活守卫**
（教训 BB′：守卫主体不得空置化，故每例都带 tmp_path 反例自证，证明非恒真）。

★ 两条实现要求（否则守卫会「恒红」或「恒真」）：

1. **跳过 AppleDouble 旁车 `._*`** + `errors="replace"`：
   外置卷上 `._*.py` 是非 UTF-8 元数据旁车（src 下曾达 133 个），若照字面
   `rglob("*.py")` + 严格 utf-8 解码 ⇒ **干净实现也 UnicodeDecodeError 恒红**。
   本档第 5 例对本点自证：**在含 `._*` 的树上也全绿**。
2. **反例自证不写 src**：扫描根全部**参数化**（各 helper 收 root），反例树一律
   建在 pytest `tmp_path` 下 ⇒ 对 `src/` **零写入**（无污染/未还原风险）。
"""
import pathlib

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
_WIDGETS = _SRC / "acouscope" / "ui" / "widgets"
_DRAWER_PY = _WIDGETS / "drawer.py"
_MAIN_WINDOW = _SRC / "acouscope" / "ui" / "main_window.py"

# 批4d 清空的死标识符（登记族 7 + _room_drawer 族 3）——任一复活即判红
_DEAD_SYMBOLS = (
    "_register_drawer_entry",
    "_bind_drawer_sync",
    "_drawer_sync_bound",
    "_sync_drawer_entry",
    "_clear_drawer_entries",
    "_drawer_entries_of",
    "_drawer_entries",
    "_room_drawer",
    "_on_room_drawer_cancelled",
    "_room_acoustics_panel",
)


def _scan_files(root: pathlib.Path) -> list:
    """全树 Python 源文件；★ 跳过 AppleDouble `._*`（非 UTF-8 元数据旁车）。"""
    return [
        p for p in sorted(root.rglob("*.py"))
        if not p.name.startswith(".")
    ]


def _read(p: pathlib.Path) -> str:
    """★ errors="replace"：旁车之外的个别非 UTF-8 字节也不得中断判绿。"""
    return p.read_text(encoding="utf-8", errors="replace")


def _text_hits(root: pathlib.Path, needle: str) -> list:
    """在 root 全树（跳过 `._*`）中查找 needle 的命中文件列表。"""
    return [str(p) for p in _scan_files(root) if needle in _read(p)]


def _dead_symbol_hits(root: pathlib.Path) -> list:
    """root 下 main_window.py 中死标识符的命中行。"""
    mw = root / "acouscope" / "ui" / "main_window.py"
    text = _read(mw)
    return [s for s in _DEAD_SYMBOLS if s in text]


def _write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _pkg_tree(root: pathlib.Path) -> pathlib.Path:
    """在 root 下造 src/acouscope/ui/ 骨架，返回其根（反例/正例树共用）。"""
    (root / "acouscope" / "ui").mkdir(parents=True, exist_ok=True)
    return root


# ---------------------------------------------------------------------------
# 判据 1：src 面 open_drawer / DrawerWidget 命中 == 0
# ---------------------------------------------------------------------------


def test_src_has_no_drawer_symbol(tmp_path):
    """src 全树无 `open_drawer` / `DrawerWidget`；反例树（tmp_path）必命中。"""
    for needle in ("open_drawer", "DrawerWidget"):
        assert _text_hits(_SRC, needle) == [], f"src 面仍含 {needle}"

    # 反例自证：注入字样 → 同一 helper 必须报命中（防恒真）
    bad = _pkg_tree(tmp_path / "bad")
    _write(bad / "acouscope" / "ui" / "revived.py",
           "from acouscope.ui.widgets.drawer import open_drawer\n\n\n"
           "class DrawerWidget:\n    pass\n")
    assert _text_hits(bad, "open_drawer") == [str(bad / "acouscope" / "ui" / "revived.py")]
    assert _text_hits(bad, "DrawerWidget") == [str(bad / "acouscope" / "ui" / "revived.py")]


# ---------------------------------------------------------------------------
# 判据 2：drawer.py 文件不存在
# ---------------------------------------------------------------------------


def test_drawer_module_file_absent(tmp_path):
    """`ui/widgets/drawer.py` 已删除；反例树（tmp_path）造同路径文件必判「存在」。"""
    assert not _DRAWER_PY.exists(), f"drawer.py 仍存在：{_DRAWER_PY}"

    bad = _pkg_tree(tmp_path / "bad")
    _write(bad / "acouscope" / "ui" / "widgets" / "drawer.py", "def open_drawer():\n    pass\n")
    assert (bad / "acouscope" / "ui" / "widgets" / "drawer.py").exists()


# ---------------------------------------------------------------------------
# 判据 3：src 面无抽屉模块导入
# ---------------------------------------------------------------------------


def test_src_has_no_drawer_import(tmp_path):
    """src 全树无 `widgets.drawer` 导入（`from … import` / `import …` 两种形态）。"""
    assert _text_hits(_SRC, "widgets.drawer") == []
    assert _text_hits(_SRC, "widgets import drawer") == []

    bad = _pkg_tree(tmp_path / "bad")
    _write(bad / "acouscope" / "ui" / "leak.py",
           "from acouscope.ui.widgets.drawer import DrawerWidget\n")
    assert _text_hits(bad, "widgets.drawer") == [str(bad / "acouscope" / "ui" / "leak.py")]


# ---------------------------------------------------------------------------
# 判据 4：main_window 死标识符全零（与 R2 同一断言，防复活）
# ---------------------------------------------------------------------------


def test_main_window_dead_symbols_absent(tmp_path):
    """main_window.py 内登记族 7 + _room_drawer 族 3 全零；反例树必命中。"""
    assert _read(_MAIN_WINDOW).count("_set_entry_checked") == 5, \
        "在役 _set_entry_checked 应保留 5 处（1 定义 + 4 调用）"
    assert _dead_symbol_hits(_SRC) == []

    bad = _pkg_tree(tmp_path / "bad")
    _write(bad / "acouscope" / "ui" / "main_window.py",
           "class MainWindow:\n"
           "    def _register_drawer_entry(self):\n"
           "        self._room_drawer = None\n")
    hits = _dead_symbol_hits(bad)
    assert "_register_drawer_entry" in hits and "_room_drawer" in hits


# ---------------------------------------------------------------------------
# 判据 5：DRAWER_WIDTH / drawerContent 零命中 + ★ AppleDouble 免疫自证
# ---------------------------------------------------------------------------


def test_src_has_no_drawer_constants_and_apple_double_immune(tmp_path):
    """src 面 `DRAWER_WIDTH` / `drawerContent` 零命中。

    ★ 自证项：扫描 helper 在同一棵树内**含非 UTF-8 的 `._*.py`** 时仍全绿
    —— 证明守卫不受外置卷 AppleDouble 旁车影响（否则干净实现恒红）。
    """
    for needle in ("DRAWER_WIDTH", "drawerContent"):
        assert _text_hits(_SRC, needle) == [], f"src 面仍含 {needle}"

    # 自证：造一棵含非 UTF-8 旁车的树，扫描必须跳过它且不抛 UnicodeDecodeError
    tree = _pkg_tree(tmp_path / "with_apple_double")
    _write(tree / "acouscope" / "ui" / "clean.py", "VALUE = 1\n")
    (tree / "acouscope" / "ui" / "._clean.py").write_bytes(b"\x00\x01\xff\xfe not utf-8")
    apple = [p.name for p in tree.rglob("*.py") if p.name.startswith("._")]
    assert apple == ["._clean.py"], "自证前提：旁车文件确已建于树内"
    assert _text_hits(tree, "DRAWER_WIDTH") == []          # 不抛异常即免疫
    assert _scan_files(tree) == [tree / "acouscope" / "ui" / "clean.py"]

    # 反例自证：真出现常量 → 必命中
    bad = _pkg_tree(tmp_path / "bad")
    _write(bad / "acouscope" / "ui" / "leak.py",
           'DRAWER_WIDTH = 420\nCONTENT = "drawerContent"\n')
    assert _text_hits(bad, "DRAWER_WIDTH") == [str(bad / "acouscope" / "ui" / "leak.py")]
    assert _text_hits(bad, "drawerContent") == [str(bad / "acouscope" / "ui" / "leak.py")]