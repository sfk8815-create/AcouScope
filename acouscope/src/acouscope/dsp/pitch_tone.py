# SPDX-License-Identifier: GPL-3.0-only
"""合成音高生成器 —— 纯函数层（无 Qt、无第三方 DSP 依赖）。

按已落盘的国际/历史/乐团音高标准合成参考音或指定音名，并导出 WAV。
频率换算一律复用 :func:`acouscope.dsp.units.midi_to_hz`（显式 ``ref_freq``），
绝不改动全局 A4 参考。
"""
from __future__ import annotations

import json
import math
import wave
from pathlib import Path

import numpy as np

from acouscope.dsp.units import midi_to_hz

NOTE_NAMES: tuple[str, ...] = (
    "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
)

_REFERENCE_MIN = 400.0
_REFERENCE_MAX = 480.0


def note_to_midi(note: str, octave: int) -> int:
    """音名 + 八度 → MIDI 编号（``C4 = 60`` / ``A4 = 69``）。

    非法音名或八度越界（0..9）抛 :class:`ValueError`。
    """
    if not isinstance(note, str) or note not in NOTE_NAMES:
        raise ValueError(f"非法音名: {note!r}")
    if isinstance(octave, bool) or not isinstance(octave, int) or not (0 <= octave <= 9):
        raise ValueError(f"八度越界(0..9): {octave!r}")
    return 12 * (octave + 1) + NOTE_NAMES.index(note)


def tone_frequency(note: str, octave: int, a4_hz: float) -> float:
    """指定音名在给定 A4 参考下的频率（Hz）。

    频率换算完全委托 :func:`midi_to_hz`（显式 ``ref_freq=a4_hz``），
    不写自用的 2 的幂公式，也不改全局 A4 参考。非法 ``a4_hz``
    （非有限或不在 ``[400, 480]``）抛 :class:`ValueError`。
    """
    try:
        a4 = float(a4_hz)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"非法 A4 参考: {a4_hz!r}") from exc
    if not math.isfinite(a4) or not (_REFERENCE_MIN <= a4 <= _REFERENCE_MAX):
        raise ValueError(f"A4 参考须在 [400, 480]: {a4_hz!r}")
    return float(midi_to_hz(note_to_midi(note, octave), ref_freq=a4))


def synthesize_tone(
    frequency_hz: float,
    duration_s: float,
    sample_rate: int = 44100,
    amplitude: float = 0.8,
    waveform: str = "sine",
    fade_s: float = 0.01,
) -> np.ndarray:
    """合成单声道 ``float64`` 波形，取值 ``[-1, 1]``。

    ``waveform="sine"`` 为纯正弦；``"harmonic"`` 为 1..5 次谐波按 ``1/k``
    叠加后归一化到峰值 1。首尾各 ``fade_s`` 秒 raised-cosine 淡入淡出；
    长度为 ``int(round(duration_s * sample_rate))``。参数越界抛
    :class:`ValueError`。
    """
    f = float(frequency_hz)
    dur = float(duration_s)
    amp = float(amplitude)
    fade = float(fade_s)
    if not math.isfinite(f) or f <= 0.0 or f >= float(sample_rate) / 2.0:
        raise ValueError(f"频率越界: {frequency_hz!r}")
    if not math.isfinite(dur) or dur <= 0.0:
        raise ValueError(f"时长越界: {duration_s!r}")
    if sample_rate < 8000:
        raise ValueError(f"采样率过低: {sample_rate!r}")
    if not math.isfinite(amp) or not (0.0 < amp <= 1.0):
        raise ValueError(f"音量越界: {amplitude!r}")
    if waveform not in ("sine", "harmonic"):
        raise ValueError(f"未知波形: {waveform!r}")
    if fade < 0.0 or fade >= dur / 2.0:
        raise ValueError(f"淡入淡出越界: {fade_s!r}")

    n = int(round(dur * sample_rate))
    t = np.arange(n, dtype=np.float64) / float(sample_rate)
    if waveform == "sine":
        tone = np.sin(2.0 * np.pi * f * t)
    else:
        tone = np.zeros(n, dtype=np.float64)
        for k in range(1, 6):
            tone += np.sin(2.0 * np.pi * (f * k) * t) / k
        peak = float(np.max(np.abs(tone))) if n else 0.0
        if peak > 0.0:
            tone = tone / peak

    fade_n = int(round(fade * sample_rate))
    if fade_n > 0:
        ramp = 0.5 - 0.5 * np.cos(
            np.pi * np.arange(fade_n, dtype=np.float64) / fade_n
        )
        env = np.ones(n, dtype=np.float64)
        env[:fade_n] = ramp
        env[-fade_n:] = ramp[::-1]
        tone = tone * env

    return np.clip(tone * amp, -1.0, 1.0).astype(np.float64)


def write_wave(
    path: str | Path,
    data: np.ndarray,
    sample_rate: int,
    depth: str = "pcm16",
) -> Path:
    """把单声道波形写为 WAV 文件并返回实际路径。

    ``depth="pcm16"`` 用标准库 :mod:`wave` 写 16-bit PCM；
    ``depth="pcm24"`` 用标准库 :mod:`wave` 写 24-bit PCM；
    ``depth="float32"`` 用 :func:`soundfile.write` 写 ``subtype="FLOAT"``。
    自动补 ``.wav`` 后缀；父目录不存在抛 :class:`OSError`；坏 ``depth``
    抛 :class:`ValueError`。
    """
    if depth not in ("pcm16", "pcm24", "float32"):
        raise ValueError(f"未知位深: {depth!r}")
    p = Path(path)
    if p.suffix.lower() != ".wav":
        p = Path(str(p) + ".wav")
    if not p.parent.exists():
        raise OSError(f"父目录不存在: {p.parent}")

    arr = np.asarray(data)
    if depth == "pcm16":
        pcm = (np.clip(arr.astype(np.float64), -1.0, 1.0) * 32767.0).astype("<i2")
        with wave.open(str(p), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(int(sample_rate))
            wf.writeframes(pcm.tobytes())
    elif depth == "pcm24":
        q = np.rint(
            np.clip(arr.astype(np.float64), -1.0, 1.0) * 8388607.0
        ).astype("<i4")
        raw = q.tobytes()
        pcm24 = np.frombuffer(raw, np.uint8).reshape(-1, 4)[:, :3].tobytes()
        with wave.open(str(p), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(3)
            wf.setframerate(int(sample_rate))
            wf.writeframes(pcm24)
    else:
        import soundfile as sf

        sf.write(str(p), arr.astype(np.float32), int(sample_rate), subtype="FLOAT")
    return p


def load_standards() -> list[dict]:
    """读随包的 ``resources/pitch_standards.json``，原样返回 ``standards``。

    缺文件 / JSON 坏 / 空表抛 :class:`ValueError`。
    """
    path = Path(__file__).resolve().parents[1] / "resources" / "pitch_standards.json"
    if not path.is_file():
        raise ValueError(f"资源表缺失: {path}")
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"资源表 JSON 损坏: {path}") from exc
    standards = obj.get("standards") if isinstance(obj, dict) else None
    if not isinstance(standards, list) or not standards:
        raise ValueError("资源表 standards 为空或结构错误")
    return standards


def catalog_standards() -> list[dict]:
    """测试辅助：从本文件上溯到仓根，读 catalog 的 ``standards``。

    找不到抛 :class:`FileNotFoundError`。
    """
    for base in Path(__file__).resolve().parents:
        candidate = (
            base / "02_References" / "pitch_standards" / "pitch_standards_catalog.json"
        )
        if candidate.is_file():
            obj = json.loads(candidate.read_text(encoding="utf-8"))
            return obj["standards"]
    raise FileNotFoundError("未找到音高标准 catalog 依据件")
