# SPDX-License-Identifier: GPL-3.0-only
"""A4 单源守卫（静态）：src/acouscope/** 内不得再出现"写死 440"的 6 类模式。

★ A4-R10 扩面：由单模式 cent_ref 扩为 6 类 PATTERNS（逐字对齐探针 :30-37）。
★ 口径对齐既有探针 .pi/tools/pi_t43/guard_probe.py：
  只扫 src/acouscope/**（tests/** 不扫 —— 测试需已知值作尺子，扫它会制造伪红）。
★ 豁免采用【文件级白名单】（SSoT / 默认语义 / 已裁定不动 / 零 app caller / 非参考用途）。
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src" / "acouscope"

# ★ 文件级白名单（相对 ROOT 的 posix 路径）
EXEMPT_FILES = {
    "dsp/units.py",                     # SSoT：A4_FREQ 定义 + 内部引用 + FREQ_UNITS 标签
    "analysis/spectral.py",             # 指挥裁：独立 tuning_offset 口径（:278），不动
    "analysis/pcp.py",                  # 零 app caller（今日死口径）
    "analysis/note_hmm.py",             # 非参考用途（掩码占位/注释）
    "ui/widgets/settings_dialog.py",    # A4 预设 415/432/440/442（默认语义，合法）
    "utils/config.py",                  # Settings 持久化默认值 / 越界回退（默认语义）
    "ui/main_window.py",                # getattr(..., 440.0) 默认回退注入点
}

# ★ 目录级白名单
EXEMPT_DIRS = ("analysis/tunings",)     # 目录豁免（字段语义）

# ★ 6 类模式（逐字对齐 .pi/tools/pi_t43/guard_probe.py:30-37；★ 名称按语义命名，不带赘字）
PATTERNS = [
    ("A4_FREQ 常引用", re.compile(r"\bA4_FREQ\b")),
    ("cent_ref 字面440", re.compile(r"\bcent_ref\b\s*:\s*float\s*=\s*440|\bcent_ref\s*=\s*440\b")),
    ("440常量定义", re.compile(r"^\s*(_A4|_A4_REF|A4_REF)\b\s*[:=]\s*440")),
    ("log2 以440为ref", re.compile(r"log2\s*\([^)]{0,40}440")),
    ("参考线位440", re.compile(r"pos\s*=\s*440\b|setPos\(\s*0\s*,\s*440\b|freq_to_display\(\s*440")),
    ("A4=440 文案", re.compile(r"A4[^A-Za-z\n]{0,14}440")),
]


def _scan(text: str, rel: str) -> list[tuple[int, list[str], str]]:
    """★ 纯函数：返回 (行号, 命中类名列表, 行内容)；便于正/负对照直接调用。"""
    if rel in EXEMPT_FILES or rel.startswith(EXEMPT_DIRS):
        return []
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        matched = [name for name, rx in PATTERNS if rx.search(line)]
        if matched:
            hits.append((i, matched, line.strip()))
    return hits


def _all_src_files() -> list[Path]:
    """★★ v2（R1 核心修复）：必须排除 __pycache__ 【与 AppleDouble 旁车 `._*.py`】。

    旁车是外置卷/网络卷的明文元数据（非 UTF-8 源码）=> read_text(encoding="utf-8")
    必抛 UnicodeDecodeError => 主判据崩溃（原 v1 逐字码实测 1 fail / 7 pass）。
    本写法【逐字镜像】.pi/tools/pi_t43/guard_probe.py 的同名过滤。
    """
    return sorted(
        p
        for p in ROOT.rglob("*.py")
        if "__pycache__" not in p.parts and not p.name.startswith("._")
    )


def test_a4r8_scan_is_not_empty_guard():
    """★ 守卫自检：扫描面必须非空（防'扫了个空目录'式假绿）。"""
    files = _all_src_files()
    assert len(files) >= 100, f"扫描面异常小：{len(files)} 档"


def test_a4r8_no_hardcoded_440_in_src():
    """★ 主判据：src/acouscope/** 除白名单外，不得出现 6 类"写死 440"模式命中。"""
    offenders = []
    for p in _all_src_files():
        rel = p.relative_to(ROOT).as_posix()
        for lineno, classes, line in _scan(p.read_text(encoding="utf-8"), rel):
            offenders.append(f"{rel}:{lineno}: [{'+'.join(classes)}] {line}")
    assert offenders == [], "A4 单源被破坏（写死 440 回潮）：\n" + "\n".join(offenders)


# ★★ A4-R10 逐类正负对照（12 例 = 6 类 × (1 正 + 1 负)；构成见 A4-R10 §二-2）：
#   ①⑥ 用【真实行】（取自白名单内 LEGAL 命中）；②③④⑤ 用【合成正样本】
#   （该 4 类全 src 命中 = 0，R1~R9 已清净，不存在真实正样本 —— PI-T51 C3 实证）。
#   每例须无歧义：正样本只命中本类（§二-2 注 AJ，禁一行跨两类）。
@pytest.mark.parametrize(
    "cls,sample,expect_hit",
    [
        # ① A4_FREQ 常引用（正=真实行 tunings/templates.py:17）
        ("A4_FREQ 常引用", "from ...dsp.units import A4_FREQ\n", True),
        ("A4_FREQ 常引用", "    freq = get_reference_hz()\n", False),
        # ② cent_ref 字面440（正=合成，R5~R9 修掉的形状）
        ("cent_ref 字面440", "    cent_ref: float = 440.0\n", True),
        ("cent_ref 字面440", '    cent_ref: "float | None" = None\n', False),
        # ③ 440常量定义（正=合成）
        ("440常量定义", "_A4_REF = 440.0\n", True),
        ("440常量定义", "    reference_hz = get_reference_hz()\n", False),
        # ④ log2 以440为ref（正=合成）
        ("log2 以440为ref", "    return 1200 * log2(f / 440.0)\n", True),
        ("log2 以440为ref", "    return 1200 * log2(f / ref_hz)\n", False),
        # ⑤ 参考线位440（正=合成）
        ("参考线位440", "    self.line.setPos(0, 440.0)\n", True),
        ("参考线位440", "    self.line.setPos(0, ref_hz)\n", False),
        # ⑥ A4=440 文案（正=真实行 settings_dialog.py:668）
        ("A4=440 文案", '"""「恢复 440」：把 A4 参考频率置回 440.0 Hz（T-921）。"""\n', True),
        ("A4=440 文案", "    # A4 参考频率（可配置，单点解析）\n", False),
    ],
)
def test_a4r10_pattern_discrimination_by_class(cls, sample, expect_hit):
    """★★ 判别力守卫：6 类模式各 ≥1 正 ≥1 负（正必命中本类且唯一，负必零命中）。"""
    hits = _scan(sample, "analysis/pitch.py")
    if expect_hit:
        assert hits and cls in hits[0][1], f"{cls} 正样本未命中本类：{hits}"
        assert len(hits[0][1]) == 1, f"{cls} 正样本跨类（违 §二-2 注 AJ）：{hits}"
    else:
        assert hits == [], f"{cls} 负样本误命中：{hits}"


def test_a4r8_whitelist_paths_still_exist():
    """★ 白名单防腐：白名单里的档必须真实存在（防'写错路径 ⇒ 静默失效'）。"""
    missing = [f for f in EXEMPT_FILES if not (ROOT / f).is_file()]
    assert missing == [], f"白名单路径不存在：{missing}"
