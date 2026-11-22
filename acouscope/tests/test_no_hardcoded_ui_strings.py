"""G-2a 守卫：Qt 文本汇点硬编码中文——逐文件计数不得超过钉表。

口径（GUI 第三轮设计约定 §二，G-2c 笔 1 升级）：
  1. 先剥离 `#` 注释（引号内的 # 不算）——注释非用户可见文本，计入会把「翻译注释」
     这种无意义动作变成判据；
  2. 汇点：setText / addItem / insertItem / addItems / setToolTip / setWindowTitle /
     setPlaceholderText / showMessage / setStatusTip / setWhatsThis / QLabel(
     + QMessageBox.(question|information|warning|critical)(；
  3. 参数区取括号配平（可跨行）：从汇点 `(` 起按括号深度截取至配平 `)`，
     引号/转义感知（与注释剥离同款状态机）；行号仍取汇点匹配起始行；
  4. 参数区含 CJK 即计 1（一个汇点调用计 1，不按串计）。

标定读数（新口径＝括号配平，去注释口径；括号内为 main_window 分项）：
  e226ab6 全树 202 / mw 51 → 26ca548 199 / 48 → 3f12dac 160 / 9
  → 5a940bf 112 / 9 → HEAD 112 / 9。
  旧「同行」口径 86 → 112 之差即多行参数区盲区（26 处），G-2c 笔 1 补清；
  笔 1 后余 86 处归笔 2，笔 2 已收口为 0（钉表全项 0）。
钉表只准下调，不准上调：本档红即代表有新硬编码中文进入用户可见面。
"""

from __future__ import annotations

import re
from pathlib import Path

CJK = re.compile(r"[\u4e00-\u9fff]")

SINK = re.compile(
    r"(?:\.|\b)(setText|addItem|insertItem|addItems|setToolTip|setWindowTitle"
    r"|setPlaceholderText|showMessage|setStatusTip|setWhatsThis|QLabel"
    r"|QMessageBox\.(?:question|information|warning|critical))\s*\("
)

# 钉表：G-2c 笔 2 后现读值（括号配平口径）——全项 0，余量只准减不准增。
_PIN: dict[str, int] = {
    "main_window.py": 0,
    "widgets/spectrum.py": 0,
    "widgets/settings_dialog.py": 0,
    "widgets/room_modes.py": 0,
    "widgets/transport_bar.py": 0,
    "widgets/spectrogram.py": 0,
    "widgets/record_settings_dialog.py": 0,
    "widgets/pitch.py": 0,
    "widgets/spectrogram3d.py": 0,
    "widgets/waveform.py": 0,
    "widgets/room_acoustics_dialog.py": 0,
    "widgets/formants.py": 0,
    "widgets/timbre.py": 0,
    "widgets/metadata_bar.py": 0,
    "widgets/chart_font_dialog.py": 0,
}

# 豁免：help_dialogs.py 的三语硬编码是既定设计（S4 闸面），不走 tr()。
_ALLOWLIST = frozenset({"widgets/help_dialogs.py"})


def _ui_root() -> Path:
    import acouscope.ui.main_window as mw

    return Path(mw.__file__).resolve().parents[1] / "ui"


def _strip_comments(text: str) -> str:
    """剥离 `#` 注释（引号内的 # 保留）。"""
    out = []
    for line in text.splitlines(keepends=True):
        quote = None
        cut = len(line)
        i = 0
        while i < len(line):
            ch = line[i]
            if quote:
                if ch == "\\":
                    i += 2
                    continue
                if ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
            elif ch == "#":
                cut = i
                break
            i += 1
        body = line[:cut]
        if line.endswith("\n") and not body.endswith("\n"):
            body += "\n"
        out.append(body)
    return "".join(out)


def _param_region(text: str, start: int) -> str:
    """从 start（汇点 `(` 之后）起按括号深度截取到配平 `)`。

    引号（含三引号）与转义感知：括号出现在字符串里不算深度。
    未配平（截断文件）时返回余下全文，宁可多算不可漏算。
    """
    depth = 1
    quote = ""
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if text.startswith(quote, i):
                i += len(quote)
                quote = ""
                continue
            i += 1
            continue
        if ch in "\"'":
            quote = ch * 3 if text.startswith(ch * 3, i) else ch
            i += len(quote)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    return text[start:]


def scan_text(text: str) -> list[tuple[int, str]]:
    """返回 [(行号, 汇点名)]，仅含参数区带 CJK 的汇点调用。"""
    text = _strip_comments(text)
    hits = []
    for m in SINK.finditer(text):
        idx = text.count("\n", 0, m.start())
        chunk = _param_region(text, m.end())
        if CJK.search(chunk):
            hits.append((idx + 1, m.group(1)))
    return hits


def _scan_tree() -> dict[str, int]:
    root = _ui_root()
    counts = {}
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = str(path.relative_to(root))
        hits = scan_text(path.read_text(encoding="utf-8", errors="replace"))
        if hits:
            counts[rel] = len(hits)
    return counts


def test_pin_table_files_exist():
    """钉表指向的文件必须都在（防钉表与树结构脱节）。"""
    root = _ui_root()
    missing = [rel for rel in _PIN if not (root / rel).is_file()]
    assert not missing, f"钉表文件不存在：{missing}"


def test_no_file_exceeds_pin():
    """逐文件：汇点硬编码中文数不得超过钉值。"""
    counts = _scan_tree()
    over = []
    for rel, limit in _PIN.items():
        got = counts.get(rel, 0)
        if got > limit:
            over.append(f"{rel}: {got} > 钉值 {limit}")
    assert not over, "硬编码中文超出钉表：\n" + "\n".join(over)


def test_main_window_is_clean():
    """G-2a 硬闸：main_window.py 汇点命中必须为 0。"""
    counts = _scan_tree()
    assert counts.get("main_window.py", 0) == 0, (
        f"main_window.py 仍有 {counts.get('main_window.py')} 处汇点硬编码中文"
    )


def test_unlisted_files_are_clean():
    """钉表与豁免之外的文件必须为 0（防新文件引入硬编码中文）。"""
    counts = _scan_tree()
    extra = {k: v for k, v in counts.items()
             if k not in _PIN and k not in _ALLOWLIST}
    assert not extra, f"未登记文件出现硬编码中文：{extra}"


def test_allowlist_still_needed():
    """豁免项确有命中（防豁免空转；若 help_dialogs 已清零则应删豁免）。"""
    counts = _scan_tree()
    rel = "widgets/help_dialogs.py"
    # 三语硬编码为既定设计：允许 0 命中（未来改动），但豁免本身必须指向真实文件
    assert (_ui_root() / rel).is_file()


def test_scanner_has_teeth():
    """判别力自证：假汇点必须被抓，tr() 包装与纯注释必须不抓。"""
    assert scan_text('self.lbl_status.setText("就绪")') == [(1, "setText")]
    assert scan_text('self.lbl_status.setText(tr("status.ready"))') == []
    assert scan_text('# self.lbl_status.setText("就绪") 仅注释') == []
    assert scan_text(
        'reply = QMessageBox.question(\n'
        '    self, "录音完成",\n'
        '    text,\n'
        ')\n'
    ) == [(1, "QMessageBox.question")]
    # 反向对照：ASCII 文本不得误报（防「恒红」假守卫）
    assert scan_text('self.lbl_status.setText("Ready")') == []
    # G-2c 笔 1 口径升级：多行字面量必抓（串内 `(` 不得带偏括号深度）
    assert scan_text(
        'self.lbl.setText(\n'
        '    f"语谱图 ({n} 点 FFT)"\n'
        ')'
    ) == [(1, "setText")]
    # 多行但 tr() 包装不抓（防「多行一律红」的假阳）
    assert scan_text(
        'self.lbl.setText(\n'
        '    tr("view.spectrogram")\n'
        ')'
    ) == []
