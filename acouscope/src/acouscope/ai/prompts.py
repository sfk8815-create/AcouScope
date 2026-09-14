# SPDX-License-Identifier: GPL-3.0-only
"""AI 释图的内嵌学术提示词、数据上下文构建与预置追问问题。"""

from __future__ import annotations

ACADEMIC_PROMPT_ZH = """你是一位音乐声学与乐器学研究领域的资深研究员，长期为《Journal of the Acoustical Society of America》《Acta Acustica》等期刊审稿与撰稿。现在给你一张由音频分析软件 AcouScope 生成的分析图表，以及软件同时提供的数值上下文。请进行学术级释读。

要求：
1. 先判定图表类型（波形 / 幅度谱 / 语谱图 / 基频轨迹 / 共振峰轨迹 / MFCC 热图 / 三维时频曲面或瀑布图），并说明坐标轴与标度（线性/对数/dB）。
2. 「主要观察」：用定量语言描述可见结构——谐波列/分音序号、基频估计、峰位频率、共振峰带、起振与衰减过程、颤音或噪声成分等，尽量引用上下文中的数值。
3. 「声学解释」：结合乐器声学/语音声学理论解释这些结构的成因（如弦振动的谐波性、管乐共振峰、弓弦噪声、声带-声道耦合等），指出该对象的发声类型或演奏技法线索。
4. 「论文表述建议」：给出 1–2 句可直接用于论文图注或结果部分的中文表述（严谨、克制、可量化）。
5. 若图像信息不足或上下文缺失，明确说明局限，不得臆造数值。

输出使用中文，采用上述四个小标题的 Markdown 结构，全文 400–800 字。"""

ACADEMIC_PROMPT_EN = """You are a senior researcher in musical acoustics and organology. Given an analysis figure produced by the audio analysis software AcouScope, together with its numeric context, provide an academic-grade interpretation:

1. Identify the figure type (waveform / magnitude spectrum / spectrogram / F0 contour / formant tracks / MFCC heatmap / 3D time-frequency surface or waterfall) and its axes and scales.
2. Observations: describe visible structures quantitatively — harmonic series, fundamental, peak frequencies, formant bands, attack/decay, vibrato or noise components — citing context values where possible.
3. Acoustic interpretation: explain the physical origins (string harmonicity, bore resonances, bowing noise, source-filter coupling, etc.) and infer playing technique or phonation clues.
4. Suggested caption: 1-2 sentences suitable for a journal figure caption.
5. State limitations explicitly if information is insufficient; never fabricate values.

Output in English, Markdown with the four headings, 300-600 words."""


def build_context(
    view_name: str,
    filename: str = "",
    sample_rate: float = 0,
    duration: float = 0,
    peaks: list | None = None,
    f0_stats: dict | None = None,
    formant_medians: list | None = None,
    timbre_stats: dict | None = None,
    segment: tuple | None = None,
    extra: str = "",
) -> str:
    """把软件已计算的数值组装为模型的数值上下文（防臆造）。"""
    lines = ["【数值上下文（由软件精确计算，优先引用）】"]
    if filename:
        lines.append(f"- 音频文件: {filename}")
    if sample_rate:
        lines.append(f"- 采样率: {sample_rate:.0f} Hz; 时长: {duration:.2f} s")
    if segment:
        lines.append(f"- 分析乐段: {segment[0]:.2f}–{segment[1]:.2f} s")
    lines.append(f"- 当前视图: {view_name}")

    if peaks:
        lines.append("- 频谱峰（频率/音名/音分偏差/幅度dB）:")
        for p in peaks[:12]:
            lines.append(
                f"  · {p.get('freq', 0):.1f} Hz {p.get('note', '')} "
                f"{p.get('cents', 0):+.0f}¢ {p.get('db', 0):.1f} dB"
            )
    if f0_stats:
        lines.append(
            f"- 基频 F0: 中位 {f0_stats.get('median', 0):.1f} Hz, "
            f"范围 {f0_stats.get('min', 0):.1f}–{f0_stats.get('max', 0):.1f} Hz"
        )
    if formant_medians:
        fmt_str = ", ".join(
            f"F{i + 1}≈{v:.0f} Hz" for i, v in enumerate(formant_medians) if v > 0
        )
        if fmt_str:
            lines.append(f"- 共振峰中位: {fmt_str}")
    if timbre_stats:
        parts = [f"{k}: {v}" for k, v in timbre_stats.items()]
        lines.append("- 音色特征: " + "; ".join(parts))
    if extra:
        lines.append(extra)
    return "\n".join(lines)


# ----------------------------------------------------------------------
# 预置追问问题（按视图类型，取用户最可能想问的）
# ----------------------------------------------------------------------

PRESET_QUESTIONS: dict[str, list[str]] = {
    "波形": [
        "如何从包络判断起振与衰减特征？",
        "波形周期性与音高如何对应？",
        "幅度调制反映了什么演奏动作？",
        "哪一段适合做频谱分析？",
    ],
    "FFT 频谱": [
        "谐波幅度衰减规律的物理成因？",
        "音分偏差说明音准情况如何？",
        "如何区分谐波与噪声成分？",
        "请给出论文图注表述建议",
    ],
    "语谱图": [
        "如何辨认共振峰带与谐波列？",
        "时变结构对应什么演奏手势？",
        "起音瞬态过程如何读取？",
        "当前窗长设置是否合适？",
    ],
    "音高轨迹": [
        "颤音速率与深度提示何种技法？",
        "音高断裂或八度误差的成因？",
        "如何定量描述音准稳定性？",
        "F0 与频谱能量如何关联？",
    ],
    "共振峰轨迹": [
        "共振峰频率指示何种共振体？",
        "如何区分声源频率与共振峰？",
        "共振峰带对音色的作用？",
        "共振峰数据如何学术报告？",
    ],
    "MFCC 热图": [
        "各 MFCC 维度的声学含义？",
        "热图纹理变化如何解读？",
        "MFCC 相比语谱图的优势？",
        "如何结合音色特征解释？",
    ],
    "3D 频谱图": [
        "如何识别谐波能量脊线？",
        "视角选择对释读的影响？",
        "相比 2D 语谱图的优势？",
        "时频能量如何定量描述？",
    ],
}

DEFAULT_QUESTIONS: list[str] = [
    "最值得关注的声学特征是什么？",
    "数值上下文能解释哪些现象？",
    "还需补充哪些分析支撑结论？",
    "请给出图注表述建议",
]

FOLLOWUP_SYSTEM_NOTE = (
    "（后续追问请基于此前提供的图表与数值上下文回答，保持学术严谨，"
    "不得臆造数值；回答使用中文，一般不超过 300 字。）"
)


def preset_questions_for(view_name: str) -> list[str]:
    """按视图名返回预置追问问题（未知视图返回通用问题）。"""
    return PRESET_QUESTIONS.get(view_name, DEFAULT_QUESTIONS)
