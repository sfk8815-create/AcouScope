# SPDX-License-Identifier: GPL-3.0-only
"""matplotlib 学术出图样式。"""

from __future__ import annotations

import re

import matplotlib
import matplotlib.pyplot as plt
from matplotlib import rcParams

from acouscope.utils.log import get_logger

_log = get_logger(__name__)


# 期刊模板配置
JOURNAL_TEMPLATES = {
    "default": {
        "name": "默认",
        "figure_width": 6.0,  # 英寸
        "figure_height": 4.0,
        "font_size": 10,
        "line_width": 1.0,
        "axis_line_width": 0.8,
        "dpi": 300,
    },
    "ieee": {
        "name": "IEEE",
        "figure_width": 3.5,  # 单栏 ~8.9cm
        "figure_height": 2.5,
        "font_size": 8,
        "line_width": 0.8,
        "axis_line_width": 0.6,
        "dpi": 600,
    },
    "ieee_double": {
        "name": "IEEE 双栏",
        "figure_width": 7.0,  # 双栏 ~17.8cm
        "figure_height": 4.0,
        "font_size": 9,
        "line_width": 0.8,
        "axis_line_width": 0.6,
        "dpi": 600,
    },
    "springer": {
        "name": "Springer",
        "figure_width": 3.54,  # 单栏 9cm
        "figure_height": 2.8,
        "font_size": 9,
        "line_width": 0.8,
        "axis_line_width": 0.6,
        "dpi": 500,
    },
    "elsevier": {
        "name": "Elsevier",
        "figure_width": 3.74,  # 单栏 9.5cm
        "figure_height": 3.0,
        "font_size": 9,
        "line_width": 0.8,
        "axis_line_width": 0.6,
        "dpi": 500,
    },
    "acm": {
        "name": "ACM",
        "figure_width": 3.33,  # 单栏 ~8.5cm
        "figure_height": 2.5,
        "font_size": 8,
        "line_width": 0.7,
        "axis_line_width": 0.5,
        "dpi": 600,
    },
    "chinese_science": {
        "name": "中国科学",
        "figure_width": 3.54,  # 单栏 9cm
        "figure_height": 2.8,
        "font_size": 9,
        "line_width": 0.8,
        "axis_line_width": 0.6,
        "dpi": 600,
    },
}

# 配色方案
COLOR_PALETTES = {
    "default": ["#2563eb", "#0891b2", "#d97706", "#059669", "#dc2626", "#7c3aed"],
    "grayscale": ["#000000", "#404040", "#707070", "#a0a0a0", "#c0c0c0", "#e0e0e0"],
    "colorblind": ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#F0E442", "#56B4E9"],
    "viridis": None,  # 使用 matplotlib viridis colormap
    "inferno": None,
}

# 线型（黑白模式使用）
LINE_STYLES = ["-", "--", "-.", ":", (0, (5, 5)), (0, (3, 5, 1, 5))]

# T-1044：导出侧**结构线 / 参考线**中性墨色（零轴基线、谐波标记线与其文字）。
# 语义归属：结构线与参考线**不走数据序列色板**（否则 colorblind 下零轴会变蓝、
# 标记线变橙 → 语义错误）。导出恒白底 → 恒取 light 骨架值，与
# `acouscope.ui.theme._LIGHT_DATA` 同源；一致性由
# tests/test_chart_designer.py 对账锁死（theme 仍是唯一权威源，漂移即红）。
# ★ 禁在此处 import acouscope.ui.*（防 visualization → ui 反向分层依赖）。
EXPORT_INK: dict[str, str] = {
    "ref_line": "#5A6570",  # = ui/theme._LIGHT_DATA["ref_line"]（参考线/标记线及其文字）
    "axis": "#5A6570",      # 零轴基线：同一结构墨色（旧值 #999）
}


def palette_cycle(name: str = "default") -> list[str] | None:
    """取数据序列色板（T-1044 接线 `COLOR_PALETTES`）。

    Args:
        name: 配色方案名（default / grayscale / colorblind / viridis / inferno）

    Returns:
        色列表副本；`viridis` / `inferno` 返回 `None`（信号 = 走 matplotlib
        colormap，无离散序列色）；未知 name → 记 warning 并回退 `default` 副本
        （**禁抛异常** —— UI 里炸比降级更糟）。
    """
    if name in COLOR_PALETTES:
        seq = COLOR_PALETTES[name]
        return None if seq is None else list(seq)
    _log.warning("未知配色方案 %s，回退 default", name)
    return list(COLOR_PALETTES["default"])


def _filter_available_fonts(families: list[str]) -> list[str]:
    """过滤出系统实际可用的字体，避免 findfont 告警刷屏。"""
    try:
        from matplotlib import font_manager as fm

        available = {f.name for f in fm.fontManager.ttflist}
        found = [f for f in families if f in available]
    except Exception as e:
        _log.warning("字体可用性检查失败，使用原始字体列表: %s", e)
        found = []
    result = found if found else families
    return result + ["sans-serif"]


# 推荐字体（供用户选择时置顶展示，仅列出系统实际存在的）
RECOMMENDED_LATIN_FONTS = [
    "Times New Roman", "Arial", "Helvetica", "DejaVu Serif", "DejaVu Sans",
    "Georgia", "Palatino", "Garamond", "Verdana", "Courier New",
]
RECOMMENDED_CJK_FONTS = [
    "PingFang SC", "Hiragino Sans GB", "Songti SC", "STSong", "STKaiti",
    "STFangsong", "Arial Unicode MS", "Noto Sans CJK SC", "Noto Serif CJK SC",
    "WenQuanYi Micro Hei", "SimSun", "SimHei", "KaiTi", "FangSong",
    "Microsoft YaHei",
]
RECOMMENDED_FONTS = RECOMMENDED_LATIN_FONTS + RECOMMENDED_CJK_FONTS

# 中文字体名称特征（用于从系统字体中识别 CJK 字体）
_CJK_NAME_RE = re.compile(
    r"PingFang|Hiragino|Songti|Heiti|Kaiti|Fangsong|STSong|STKai|STFangsong|"
    r"SimSun|SimHei|KaiTi|FangSong|YaHei|CJK|WenQuanYi|Source Han|"
    r"Arial Unicode|Noto Sans SC|Noto Serif SC|Ming|Gothic|Mincho",
    re.IGNORECASE,
)

# 用户选定西文字体时的中文回退链（保证中文标签不出方块）
_CJK_FALLBACK = [
    "PingFang SC", "Hiragino Sans GB", "Arial Unicode MS",
    "Noto Sans CJK SC", "WenQuanYi Micro Hei", "SimHei",
]

# 默认图表字体：西文/数字用 Times New Roman，中文用宋体
DEFAULT_LATIN_FONT = "Times New Roman"
# 宋体候选（按系统可用性取第一个：macOS=Songti SC，Windows=SimSun）
_SONG_FONT_CANDIDATES = [
    "Songti SC", "STSong", "SimSun", "NSimSun",
    "Source Han Serif SC", "Noto Serif CJK SC", "Songti TC",
]


def _available_font_names() -> set[str]:
    try:
        from matplotlib import font_manager as fm

        return {f.name for f in fm.fontManager.ttflist}
    except Exception as e:
        _log.warning("枚举系统字体失败: %s", e)
        return set()


def default_cjk_font() -> str:
    """默认中文字体（宋体）：返回系统实际可用的第一个宋体候选；无则返回空串。"""
    available = _available_font_names()
    for f in _SONG_FONT_CANDIDATES:
        if f in available:
            return f
    return ""


def list_latin_fonts() -> list[str]:
    """西文/数字字体选项（推荐置顶，剔除 CJK 字体）。"""
    available = _available_font_names()
    if not available:
        return []
    recommended = [f for f in RECOMMENDED_LATIN_FONTS if f in available]
    others = sorted(
        f for f in available
        if f not in RECOMMENDED_FONTS and not _CJK_NAME_RE.search(f)
    )
    return recommended + others


def list_cjk_fonts() -> list[str]:
    """中文字体选项（推荐置顶 + 名称特征识别出的其他 CJK 字体）。"""
    available = _available_font_names()
    if not available:
        return []
    recommended = [f for f in RECOMMENDED_CJK_FONTS if f in available]
    others = sorted(
        f for f in available
        if f not in RECOMMENDED_FONTS and _CJK_NAME_RE.search(f)
    )
    return recommended + others


def font_chain(
    font_latin: str = "auto",
    font_cjk: str = "auto",
    language: str = "zh_CN",
) -> list[str]:
    """按「西文字体 + 中文字体」组合构造 font.family 回退链。

    - 两者皆 auto：默认链（西文 Times New Roman + 中文宋体）
    - 只设西文：西文优先 + 中文回退链兜底（中文标签不出方块）
    - 只设中文：默认西文在前（数字/英文用西文），中文用所选字体
    - 两者都设：[西文, 中文] + 兜底
    """
    both_auto = (not font_latin or font_latin == "auto") and \
                (not font_cjk or font_cjk == "auto")
    if both_auto and language != "zh_CN":
        return _filter_available_fonts(["Arial", "Helvetica"])

    # 将 auto 解析为默认字体：西文 Times New Roman，中文宋体
    if not font_latin or font_latin == "auto":
        font_latin = DEFAULT_LATIN_FONT
    if not font_cjk or font_cjk == "auto":
        font_cjk = default_cjk_font()

    fallback = [f for f in _filter_available_fonts(_CJK_FALLBACK)]

    chain: list[str] = []
    if font_latin:
        chain.append(font_latin)
    if font_cjk and font_cjk not in chain:
        chain.append(font_cjk)
    for f in fallback:
        if f not in chain:
            chain.append(f)
    if "sans-serif" not in chain:
        chain.append("sans-serif")
    return chain


def get_academic_style(
    template: str = "default",
    language: str = "zh_CN",
    font_latin: str = "auto",
    font_cjk: str = "auto",
) -> dict:
    """获取学术出图样式配置。

    Args:
        template: 期刊模板名称
        language: 语言 (zh_CN / en_US)
        font_latin: 西文/数字字体；"auto" 自动
        font_cjk: 中文字体；"auto" 自动

    Returns:
        样式参数字典
    """
    if template not in JOURNAL_TEMPLATES:
        template = "default"

    config = JOURNAL_TEMPLATES[template].copy()
    config["font_family"] = font_chain(font_latin, font_cjk, language)
    return config


def apply_style(
    template: str = "default",
    language: str = "zh_CN",
    font_latin: str = "auto",
    font_cjk: str = "auto",
) -> None:
    """应用学术出图样式到 matplotlib 全局设置。

    Args:
        template: 期刊模板名称
        language: 语言
        font_latin: 西文/数字字体（"auto" 自动）
        font_cjk: 中文字体（"auto" 自动）
    """
    style = get_academic_style(template, language, font_latin, font_cjk)

    rcParams["figure.dpi"] = style["dpi"]
    rcParams["font.size"] = style["font_size"]
    rcParams["axes.linewidth"] = style["axis_line_width"]
    rcParams["lines.linewidth"] = style["line_width"]
    rcParams["font.family"] = style.get("font_family", ["sans-serif"])

    # 其他优化
    rcParams["axes.titlesize"] = style["font_size"] + 1
    rcParams["axes.labelsize"] = style["font_size"]
    rcParams["xtick.labelsize"] = style["font_size"] - 1
    rcParams["ytick.labelsize"] = style["font_size"] - 1
    rcParams["legend.fontsize"] = style["font_size"] - 1
    rcParams["figure.titlesize"] = style["font_size"] + 2

    # 分辨率相关
    rcParams["savefig.dpi"] = style["dpi"]
    rcParams["savefig.bbox"] = "tight"
    rcParams["savefig.pad_inches"] = 0.05


def create_figure(
    template: str = "default",
    language: str = "zh_CN",
    font_latin: str = "auto",
    font_cjk: str = "auto",
    width: float | None = None,
    height: float | None = None,
) -> tuple[matplotlib.figure.Figure, matplotlib.axes.Axes]:
    """创建符合学术规范的图表。

    Args:
        template: 期刊模板
        language: 语言
        font_latin: 西文/数字字体（"auto" 自动）
        font_cjk: 中文字体（"auto" 自动）
        width: 自定义宽度（英寸）
        height: 自定义高度（英寸）

    Returns:
        (figure, axes)
    """
    style = get_academic_style(template, language, font_latin, font_cjk)

    w = width if width is not None else style["figure_width"]
    h = height if height is not None else style["figure_height"]

    apply_style(template, language, font_latin, font_cjk)

    fig, ax = plt.subplots(figsize=(w, h))
    return fig, ax
