# SPDX-License-Identifier: GPL-3.0-only
"""T-1072 测试卫生静态守卫：禁止测试以**字面仓库相对** `.pi/` 路径写盘。

背景（AT-01-4 卫生隐患）：`test_pitch_pyin_entry.py::test_at01_4_vibrato_report`
曾算出颤音中位后，以「Path 直接吃字面仓库相对 .pi/logs 档」+ write_text 落盘；pytest
常规 CWD 为 `acouscope/` ⇒ 落到其内部日志子目录，且根/子两份 json 皆被 git
跟踪 ⇒ 只要音高行为有变动，跑测即弄脏 tracked 副产物/覆盖已录值。本守卫把该类写法
钉死为 FAIL（本档自身也受扫，故此处只作描述、不复写字面形态）。

判定式（三类，对齐 T-1072 §2-2·纯文本扫，不 spawn 任何进程）：
  1. `open(` 直接接字面仓库相对 `.pi/` 路径；
  2. `Path(` 直接接字面仓库相对 `.pi/` 路径；
  3. 字面仓库相对 `.pi/(logs|reports)/…` 字符串后随 `.write_text(` /
     `.write_bytes(` / `.touch(`。

边界：只认**字面仓库相对路径**。走绝对路径的写法（如 conftest 的
`Path(__file__).resolve().parents[2] / ".pi" / "logs"`，CB-005 诊断落栈、目标
`*.log` 已被 .gitignore 忽略）与 `tmp_path` 类写法都不命中——它们不随 CWD 漂移、
不写 tracked 面。
"""

import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

# 三类判定式（逐字对齐 T-1072 §2-2）
_PATTERNS = (
    re.compile(r"""open\(\s*['"]\.pi[/\\]"""),
    re.compile(r"""Path\(\s*['"]\.pi[/\\]"""),
    re.compile(
        r"""['"]\.pi/(?:logs|reports)/[^'"]+['"]\)?\.(?:write_text|write_bytes|touch)\("""
    ),
)


def _scan_dir(directory: Path) -> list:
    """扫目录下全部 `*.py`，返回命中行（`文件:行号: 原文`）；无命中返回 []。

    跳过 macOS AppleDouble 元数据档（`._*.py`：二进制资源叉、未纳管、非源码）。
    """
    findings = []
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("._"):
            continue
        source = path.read_text(encoding="utf-8")
        for no, line in enumerate(source.splitlines(), start=1):
            if any(pat.search(line) for pat in _PATTERNS):
                findings.append(f"{path.name}:{no}: {line.strip()}")
    return findings


def test_no_repo_relative_pi_writes_in_tests():
    """正例：`acouscope/tests/*.py` 无一以字面仓库相对 `.pi/` 路径写盘。"""
    findings = _scan_dir(TESTS_DIR)
    assert findings == [], "测试以字面仓库相对 .pi/ 路径写盘：\n" + "\n".join(findings)


def test_guard_teeth_on_injected_scratch(tmp_path):
    """★ 负对照有牙：往 scratch（本文件外）注入一行 `.pi/` 写盘 ⇒ 守卫必 FAIL；
    撤注入 ⇒ PASS。注入行由片段拼接，避免守卫档自身被误命中。"""
    scratch = tmp_path / "_t1072_scratch_inject.py"
    injected = "Path(" + '".pi/logs' + '/xx.json").write_text("{}")\n'
    scratch.write_text(injected, encoding="utf-8")
    findings = _scan_dir(tmp_path)
    assert len(findings) == 1, f"注入未被判出（守卫无牙）：{findings}"
    assert findings[0].startswith("_t1072_scratch_inject.py:1:")

    scratch.unlink()  # 撤注入
    assert _scan_dir(tmp_path) == []


def test_guard_ignores_absolute_path_and_tmp_writes(tmp_path):
    """反假阳：绝对路径（不随 CWD 漂移）与 tmp_path 类写盘不命中（判别不过宽）。"""
    legit = tmp_path / "_t1072_scratch_legit.py"
    legit.write_text(
        "from pathlib import Path\n"
        "ROOT = Path(__file__).resolve().parents[2]\n"
        'LOG = ROOT / ".pi" / "logs" / "diag.log"\n'
        "def w(tmp):\n"
        '    with open(LOG, "a", encoding="utf-8") as fh:\n'
        '        fh.write("x")\n'
        '    (tmp / "out.json").write_text("{}")\n',
        encoding="utf-8",
    )
    assert _scan_dir(tmp_path) == []