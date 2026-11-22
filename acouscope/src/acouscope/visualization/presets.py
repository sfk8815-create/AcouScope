# SPDX-License-Identifier: GPL-3.0-only
"""绘图预设层：只放裁剪／轴／图注等**呈现参数**，不含图形逻辑与数据。

**分工**（2026-10-25 返工）：通用图形在 :mod:`acouscope.visualization.figures`
（``segment_curve``／``type_oscillation``／``reference_comparison``）；本层只声明
「论文图 A 用哪个通用图形、怎么裁、轴怎么写」。论文仍是调用方之一，平台核心不
依赖论文：删掉本文件，通用绘图与数据层不受影响。

图注（caption）字段留空槽位：文字由写作侧给，平台不写结论句。
"""

from __future__ import annotations

from ..analysis.tunings.templates import list_paper_templates

__all__ = ["PAPER_PRESETS", "PRESETS", "get_preset", "list_presets"]

#: 论文图 A：段曲线（论文 §四 图 A 的呈现参数）
_PAPER_A = {
    "figure": "segment_curve",
    "dpi": 300,
    "formats": ("png", "pdf"),
    # 26.09–27.19 s：沿用 2026-10-25 图 A 裁切约定（左界再往左进段前滑音 −92 音分，
    # 右界再往右进下一音），避免曲线撞轴成竖直线的误读
    "pad_left": 0.05,
    "pad_right": 0.04,
    "window_s": 30.0,
    "segmenter": "hmm",
    "tuning_template": "12tet",
    "annotate_segment": True,
    "labels": {"waveform": "波形", "cents": "相对段中位音分", "time": "时间 s"},
    "caption": None,  # 图注归写作侧
}

#: 论文图 B：形态×往复度分面
_PAPER_B = {
    "figure": "type_oscillation",
    "dpi": 300,
    "formats": ("png", "pdf"),
    # 图面文案不含字段名：`turns` 只是内部 key／CSV 列名，不得进正文图面
    # （01i 返工；与 01g 把图 C 的 `12tet`／`absolute` 改中文同一判据）
    "labels": {"x": "往复度（分档）", "count": "段数"},
    "caption": None,
}

#: 论文图 C：参照系对比（**要求锚定偏移**；中位偏离只作描述量）
_PAPER_C = {
    "figure": "reference_comparison",
    "dpi": 300,
    "formats": ("png", "pdf"),
    "window_s": 30.0,
    "segmenter": "hmm",
    "tuning_template": "12tet",
    # 论文模板集（2026-10-31 约定「律制参照系整体修正」后定格）：含琴律与纯律；
    # 印度二十二律／阿拉伯二十四律移出论文——二者仍保留在平台模板表内（可载、可对照），
    # 但本预设不取、不出图、论文不引用。
    "templates": list_paper_templates(),
    "limit": 60,
    "require_anchor": True,
    "labels": {
        "y": "律制模板",
        "x": "段序号",
        "colorbar": "音级序号",  # 画的是音级归属，不是音分；禁改「音分」
        "anchor_pending": "未提供锚定偏移：本图不作参照系切换的「整体偏移」论断",
        "no_shift_note": "绝对口径不施加移调",
        # 模板刻度中文名（仅图面；内部 key 与 JSON／API 一律不变）
        "template_labels": {
            "12tet": "十二平均律",
            "just_major": "纯律（大调）",
            "pythagorean_diatonic": "毕达哥拉斯律（七声）",
            "quarter_comma_meantone": "四分之一音差中庸律",
            "chinese_sanfen_sunyi_12": "三分损益十二律",
            "qin_lu": "琴律（复合律制）",
            "indian_22_shruti": "印度二十二律",
            "arabic_24_tone": "阿拉伯二十四律",
        },
    },
    "caption": None,
}

PAPER_PRESETS = {"paper_A": _PAPER_A, "paper_B": _PAPER_B, "paper_C": _PAPER_C}

#: 全部预设（当前只有论文三图；通用调用可直接用 figures 里的函数，无需预设）
PRESETS = {**PAPER_PRESETS}


def list_presets() -> list[str]:
    """预设名清单（CLI ``--preset`` 的候选）。"""
    return sorted(PRESETS)


def get_preset(name: str) -> dict:
    """取预设（返回副本，调用方可就地改，不污染全局）。"""
    try:
        return dict(PRESETS[name])
    except KeyError as exc:  # pragma: no cover - 由 CLI choices 先拦
        raise KeyError(f"未知预设：{name!r}（可用：{', '.join(list_presets())}）") from exc
