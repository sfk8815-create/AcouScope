# SPDX-License-Identifier: GPL-3.0-only
"""单位转换工具。

音乐声学研究中常用的频率和幅度单位转换。
"""

from __future__ import annotations

import math

import numpy as np

# 标准音高参考
A4_FREQ = 440.0
A4_MIDI = 69
NOTES_PER_OCTAVE = 12
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# 满刻度参考（0 dBFS = 1.0 幅度）
DBFS_REF = 1.0

# A4 参考频率的可注入当前值（T-921）：默认 A4_FREQ（440.0），
# 未显式传 ref_freq= 时各换算函数改用它；显式传入者优先。
REFERENCE_HZ_MIN = 400.0
REFERENCE_HZ_MAX = 480.0
_reference_hz = A4_FREQ


def get_reference_hz() -> float:
    """当前 A4 参考频率（Hz），默认 440.0。"""
    return _reference_hz


def set_reference_hz(freq: float) -> bool:
    """设置 A4 参考频率（Hz）。

    入参非法（非数值/非有限/≤0/超出 ``REFERENCE_HZ_MIN``–``REFERENCE_HZ_MAX``）时
    **保持原值且不抛异常**。

    Args:
        freq: 目标 A4 参考频率（Hz）

    Returns:
        True 表示已生效；False 表示入参被拒（当前参考未改动）
    """
    try:
        value = float(freq)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(value) or value <= 0.0:
        return False
    if not (REFERENCE_HZ_MIN <= value <= REFERENCE_HZ_MAX):
        return False
    global _reference_hz
    _reference_hz = value
    return True


def _resolve_reference(ref_freq: float | None) -> float:
    """显式 ref_freq 优先；未显式传入时取当前 A4 参考。"""
    return get_reference_hz() if ref_freq is None else float(ref_freq)


# ============================================================
# 频率单位转换
# ============================================================

def hz_to_khz(freq_hz: np.ndarray | float) -> np.ndarray | float:
    """Hz → kHz"""
    return freq_hz / 1000.0


def hz_to_midi(freq_hz: np.ndarray | float, ref_freq: float | None = None) -> np.ndarray | float:
    """Hz → MIDI 音高编号。

    MIDI 编号 69 = A4 = 参考频率（默认 440 Hz），每半音差 1 个 MIDI 数。
    ref_freq 省略时使用当前 A4 参考（``get_reference_hz()``）。
    """
    reference = _resolve_reference(ref_freq)
    freq_hz = np.asarray(freq_hz, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        midi = A4_MIDI + NOTES_PER_OCTAVE * np.log2(freq_hz / reference)
    return midi


def midi_to_hz(midi: np.ndarray | float, ref_freq: float | None = None) -> np.ndarray | float:
    """MIDI 音高编号 → Hz（ref_freq 省略时使用当前 A4 参考）。"""
    reference = _resolve_reference(ref_freq)
    midi = np.asarray(midi, dtype=float)
    return reference * (2 ** ((midi - A4_MIDI) / NOTES_PER_OCTAVE))


def hz_to_cents(freq_hz: np.ndarray | float, ref_freq: float | None = None) -> np.ndarray | float:
    """Hz → 音分（相对于参考频率；省略时用当前 A4 参考）。

    1 半音 = 100 音分，1 八度 = 1200 音分。
    """
    reference = _resolve_reference(ref_freq)
    freq_hz = np.asarray(freq_hz, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        cents = 1200.0 * np.log2(freq_hz / reference)
    return cents


def cents_to_hz(cents: np.ndarray | float, ref_freq: float | None = None) -> np.ndarray | float:
    """音分 → Hz（ref_freq 省略时使用当前 A4 参考）。"""
    reference = _resolve_reference(ref_freq)
    cents = np.asarray(cents, dtype=float)
    return reference * (2 ** (cents / 1200.0))


def hz_to_mel(freq_hz: np.ndarray | float) -> np.ndarray | float:
    """Hz → Mel（心理声学音高标度）。

    采用常见的 mel 折算式 m = 2595 * log10(1 + f/700)。
    ★ 码内旧注自称 O'Shaughnessy (1975)，本轮外部取证未取到可核条目 ⇒ 出处待核，
    见 02_References/BIBLIOGRAPHY.md §十二 E-12（对外正文不得写「依据 O'Shaughnessy」）
    """
    freq_hz = np.asarray(freq_hz, dtype=float)
    return 2595.0 * np.log10(1.0 + freq_hz / 700.0)


def mel_to_hz(mel: np.ndarray | float) -> np.ndarray | float:
    """Mel → Hz"""
    mel = np.asarray(mel, dtype=float)
    return 700.0 * (10 ** (mel / 2595.0) - 1.0)


def hz_to_note_name(freq_hz: float) -> str:
    """单频率 → 音名（如 C4、A#5）。"""
    if freq_hz <= 0 or not np.isfinite(freq_hz):
        return "--"
    midi = round(hz_to_midi(freq_hz))
    if midi < 0 or midi > 127:
        return "--"
    octave = midi // 12 - 1
    note_idx = midi % 12
    return f"{NOTE_NAMES[note_idx]}{octave}"


# ============================================================
# 幅度单位转换
# ============================================================

def linear_to_db(magnitude: np.ndarray | float, ref: float = 1.0) -> np.ndarray | float:
    """线性幅度 → dB（相对分贝）。

    20 * log10(magnitude / ref)
    """
    magnitude = np.asarray(magnitude, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        db = 20.0 * np.log10(np.maximum(magnitude, 1e-12) / ref)
    return db


def linear_to_dbfs(magnitude: np.ndarray | float) -> np.ndarray | float:
    """线性幅度 → dBFS（满刻度分贝）。

    0 dBFS = 满刻度（幅度 = 1.0），所有实际值 ≤ 0 dBFS。
    数字音频的标准幅度单位。
    """
    return linear_to_db(magnitude, ref=DBFS_REF)


def linear_to_normalized(magnitude: np.ndarray | float) -> np.ndarray | float:
    """线性幅度 → 归一化百分比（0-100%）。

    以当前最大值为 100%。
    """
    magnitude = np.asarray(magnitude, dtype=float)
    max_val = float(np.max(magnitude))
    if max_val <= 0:
        return np.zeros_like(magnitude)
    return magnitude / max_val * 100.0


# ============================================================
# 单位配置
# ============================================================

# X 轴（频率）单位选项
FREQ_UNITS = [
    ("Hz", "hz", "赫兹（线性）"),
    ("kHz", "khz", "千赫兹"),
    ("MIDI", "midi", "MIDI 音高编号（半音刻度）"),
    ("钢琴卷帘", "piano", "钢琴卷帘视图（左侧显示键盘，C4=中央C）"),
    ("音分", "cents", "音分（相对于当前 A4 参考）"),
    ("Mel", "mel", "Mel 标度（心理声学）"),
]

# Y 轴（幅度）单位选项
MAG_UNITS = [
    ("线性", "linear", "线性幅度"),
    ("dB", "db", "相对分贝（dB）"),
    ("dBFS", "dbfs", "满刻度分贝（数字音频标准）"),
    ("dB(A)", "dba", "A 计权声级（模拟人耳听感）"),
    ("归一化 %", "norm", "归一化百分比（0-100%）"),
]


def convert_freq_axis(
    freqs_hz: np.ndarray,
    target_unit: str,
    ref_freq: float | None = None,
) -> np.ndarray:
    """将频率轴从 Hz 转换为目标单位。

    Args:
        freqs_hz: 频率轴（Hz）
        target_unit: 目标单位 (hz, khz, midi, cents, mel)
        ref_freq: 参考频率（用于音分）；省略时用当前 A4 参考

    Returns:
        转换后的频率轴
    """
    if target_unit == "hz":
        return freqs_hz.copy()
    elif target_unit == "khz":
        return hz_to_khz(freqs_hz)
    elif target_unit == "midi":
        return hz_to_midi(freqs_hz, ref_freq)
    elif target_unit == "piano":
        # 钢琴卷帘模式：X 坐标用 MIDI（与 MIDI 单位相同，只是额外显示键盘）
        return hz_to_midi(freqs_hz, ref_freq)
    elif target_unit == "cents":
        return hz_to_cents(freqs_hz, ref_freq)
    elif target_unit == "mel":
        return hz_to_mel(freqs_hz)
    else:
        raise ValueError(f"未知频率单位: {target_unit}")


def convert_mag_axis(
    magnitude_linear: np.ndarray,
    target_unit: str,
    freqs_hz: np.ndarray | None = None,
) -> np.ndarray:
    """将幅度从线性转换为目标单位。

    Args:
        magnitude_linear: 线性幅度
        target_unit: 目标单位 (linear, db, dbfs, dba, norm)
        freqs_hz: 频率轴（dB(A) 计权需要）

    Returns:
        转换后的幅度
    """
    if target_unit == "linear":
        return magnitude_linear.copy()
    elif target_unit == "db":
        return linear_to_db(magnitude_linear)
    elif target_unit == "dbfs":
        return linear_to_dbfs(magnitude_linear)
    elif target_unit == "dba":
        return linear_to_dba(magnitude_linear, freqs_hz)
    elif target_unit == "norm":
        return linear_to_normalized(magnitude_linear)
    else:
        raise ValueError(f"未知幅度单位: {target_unit}")


# ============================================================
# A 计权声级 (A-weighting)
# ============================================================

def a_weighting(freqs_hz: np.ndarray | float) -> np.ndarray | float:
    """计算 A 计权频率响应曲线（dB）。

    使用 ANSI S1.42-2001 标准的 A 计权公式：
    A(f) = 20log10( (12194^2 * f^4) / ((f^2+20.6^2) * (f^2+12194^2) *
            sqrt((f^2+107.7^2)*(f^2+737.9^2))) )

    Args:
        freqs_hz: 频率 Hz

    Returns:
        A 计权增益（dB），0 dB 约在 2.5 kHz 左右
    """
    f = np.asarray(freqs_hz, dtype=float)

    # ANSI 标准公式
    f1 = 20.598997
    f2 = 107.65265
    f3 = 737.86223
    f4 = 12194.217

    # 避免除零
    f_safe = np.maximum(f, 1e-10)

    raf = (
        (f4 ** 2) * (f_safe ** 4)
        / (
            (f_safe ** 2 + f1 ** 2)
            * np.sqrt((f_safe ** 2 + f2 ** 2) * (f_safe ** 2 + f3 ** 2))
            * (f_safe ** 2 + f4 ** 2)
        )
    )

    # 归一化：让 1 kHz 处为 0 dB（A 计权的参考点）
    # 先计算 1 kHz 处的值
    f_1k = 1000.0
    raf_1k = (
        (f4 ** 2) * (f_1k ** 4)
        / (
            (f_1k ** 2 + f1 ** 2)
            * np.sqrt((f_1k ** 2 + f2 ** 2) * (f_1k ** 2 + f3 ** 2))
            * (f_1k ** 2 + f4 ** 2)
        )
    )

    a_db = 20.0 * np.log10(raf / raf_1k)

    # 0 Hz 处设为 -inf
    if np.isscalar(freqs_hz):
        return float(a_db) if freqs_hz > 0 else -np.inf

    a_db[f == 0] = -np.inf
    return a_db


def linear_to_dba(
    magnitude_linear: np.ndarray,
    freqs_hz: np.ndarray | None = None,
) -> np.ndarray:
    """线性幅度 → dB(A) A 计权声级。

    先对幅度谱应用 A 计权频率响应，再转为 dB。

    Args:
        magnitude_linear: 线性幅度
        freqs_hz: 对应的频率轴 Hz（必须提供）

    Returns:
        A 计权后的 dB 值
    """
    if freqs_hz is None:
        raise ValueError("dB(A) 计算需要提供频率轴 freqs_hz")

    magnitude_linear = np.asarray(magnitude_linear, dtype=float)
    freqs_hz = np.asarray(freqs_hz, dtype=float)

    # A 计权增益（线性域）
    aw_db = a_weighting(freqs_hz)
    aw_linear = 10 ** (aw_db / 20.0)

    # 应用计权
    weighted = magnitude_linear * aw_linear

    # 转为 dB
    return linear_to_db(weighted)


# ============================================================
# 钢琴键盘相关
# ============================================================

# 白键和黑键模式（每个八度内）
# C=白, C#=黑, D=白, D#=黑, E=白, F=白, F#=黑, G=白, G#=黑, A=白, A#=黑, B=白
_WHITE_KEYS = [0, 2, 4, 5, 7, 9, 11]  # C D E F G A B
_BLACK_KEYS = [1, 3, 6, 8, 10]        # C# D# F# G# A#


def midi_is_white_key(midi: int) -> bool:
    """MIDI 编号是否为白键。"""
    return (midi % 12) in _WHITE_KEYS


def midi_is_black_key(midi: int) -> bool:
    """MIDI 编号是否为黑键。"""
    return (midi % 12) in _BLACK_KEYS


def midi_note_name(midi: int) -> str:
    """MIDI 编号 → 音名（如 C4、A#3）。"""
    if midi < 0 or midi > 127:
        return "--"
    octave = midi // 12 - 1
    note_idx = midi % 12
    return f"{NOTE_NAMES[note_idx]}{octave}"


def freq_unit_label(unit: str) -> str:
    """获取频率单位的标签文本。"""
    for label, key, _ in FREQ_UNITS:
        if key == unit:
            return label
    return "Hz"


def mag_unit_label(unit: str) -> str:
    """获取幅度单位的标签文本。"""
    for label, key, _ in MAG_UNITS:
        if key == unit:
            return label
    return "线性"
