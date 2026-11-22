# SPDX-License-Identifier: GPL-3.0-only
"""合成音高生成器纯函数层判据（判据 1–4，无 Qt、WAV 只写 tmp_path）。"""
from __future__ import annotations

import json
import re
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

import acouscope.dsp.pitch_tone as pt
from acouscope.dsp.pitch_tone import (
    NOTE_NAMES,
    catalog_standards,
    load_standards,
    note_to_midi,
    synthesize_tone,
    tone_frequency,
    write_wave,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REF_DIR = REPO_ROOT / "02_References" / "pitch_standards"
RESOURCE = (
    REPO_ROOT / "acouscope" / "src" / "acouscope" / "resources" / "pitch_standards.json"
)
PT_SRC = Path(pt.__file__)
LOCALES = ("en_US", "zh_CN", "zh_TW", "ko_KR", "ja_JP")


def _zero_crossings(x: np.ndarray) -> int:
    return int(np.sum(np.diff(np.signbit(x))))


# ===========================================================================
# 判据 1 · 纯函数 / 频率换算
# ===========================================================================


def test_note_names_tuple():
    assert NOTE_NAMES == ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    assert isinstance(NOTE_NAMES, tuple)


def test_note_to_midi_known_values():
    assert note_to_midi("C", 4) == 60
    assert note_to_midi("A", 4) == 69
    assert note_to_midi("C", 0) == 12
    assert note_to_midi("A", 0) == 21
    assert note_to_midi("B", 9) == 131


@pytest.mark.parametrize("bad", ["H", "c", "", "C##", "Cb", None])
def test_note_to_midi_invalid_note(bad):
    with pytest.raises(ValueError):
        note_to_midi(bad, 4)


@pytest.mark.parametrize("bad", [-1, 10, 99, 4.0, "4", True])
def test_note_to_midi_invalid_octave(bad):
    with pytest.raises(ValueError):
        note_to_midi("C", bad)


def test_tone_frequency_a4_at_various_references():
    assert tone_frequency("A", 4, 440.0) == 440.0
    assert tone_frequency("A", 4, 435.0) == 435.0
    assert tone_frequency("A", 4, 443.0) == 443.0


def test_tone_frequency_c4_at_440():
    assert tone_frequency("C", 4, 440.0) == pytest.approx(261.6255653, abs=1e-6)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), 399.9, 480.1, None, "abc"])
def test_tone_frequency_invalid_a4(bad):
    with pytest.raises(ValueError):
        tone_frequency("A", 4, bad)


def test_tone_frequency_delegates_to_midi_to_hz(monkeypatch):
    """monkeypatch 自证：tone_frequency 以 ref_freq=a4_hz 调用 midi_to_hz。"""
    calls: dict = {}

    def spy(midi, ref_freq=None):
        calls["midi"], calls["ref_freq"] = midi, ref_freq
        return 999.0

    monkeypatch.setattr(pt, "midi_to_hz", spy)
    assert tone_frequency("A", 4, 443.0) == 999.0
    assert calls == {"midi": 69, "ref_freq": 443.0}


def test_tone_frequency_source_no_power_formula():
    """源码零命中自写 2 的幂公式，并给正对照证明检测有效。"""
    src = PT_SRC.read_text(encoding="utf-8")
    assert "from acouscope.dsp.units import midi_to_hz" in src
    assert "midi_to_hz(note_to_midi(note, octave), ref_freq=a4)" in src
    power = re.compile(r"2\s*\*\*\s*\(")
    assert power.search(src) is None, "源码出现自写 2 的幂公式"
    # 正对照：同一正则对已知自写幂公式样例必须命中
    assert power.search("freq = 440.0 * 2 ** ((m - 69) / 12)") is not None


def test_tone_frequency_does_not_touch_global_reference():
    from acouscope.dsp import units

    before = units.get_reference_hz()
    tone_frequency("A", 4, 435.0)
    tone_frequency("C", 4, 443.0)
    assert units.get_reference_hz() == before
    assert "set_reference_hz" not in PT_SRC.read_text(encoding="utf-8")


# ===========================================================================
# 判据 2 · 波形真实性
# ===========================================================================


def test_synthesize_zero_crossings_440():
    y = synthesize_tone(440.0, 1.0, sample_rate=44100, amplitude=0.8)
    assert len(y) == 44100
    assert y.dtype == np.float64
    zc = _zero_crossings(y)
    assert 879 <= zc <= 881, f"440 Hz / 1 s 零交叉={zc}（期望 880±1）"


def test_synthesize_correlation_with_441_below_099():
    """正对照：440 Hz 输出与 441 Hz 理想正弦归一化相关 < 0.99。"""
    y = synthesize_tone(440.0, 1.0, sample_rate=44100, amplitude=0.8)
    t = np.arange(len(y)) / 44100.0
    ideal_441 = np.sin(2 * np.pi * 441 * t)
    corr = abs(float(np.corrcoef(y, ideal_441)[0, 1]))
    assert corr < 0.99, f"corr={corr}"


def test_synthesize_440_vs_443_differ():
    y440 = synthesize_tone(440.0, 1.0, sample_rate=44100, amplitude=0.8)
    y443 = synthesize_tone(443.0, 1.0, sample_rate=44100, amplitude=0.8)
    assert not np.array_equal(y440, y443)
    assert _zero_crossings(y440) != _zero_crossings(y443)


def test_synthesize_fade_edges_and_peak():
    amp = 0.7
    y = synthesize_tone(440.0, 1.0, amplitude=amp, fade_s=0.01)
    assert abs(float(y[0])) < 1e-9
    assert abs(float(y[-1])) < 1e-9
    assert float(np.max(np.abs(y))) <= amp + 1e-9


def test_synthesize_harmonic_differs_from_sine():
    sine = synthesize_tone(440.0, 0.5, waveform="sine")
    harm = synthesize_tone(440.0, 0.5, waveform="harmonic")
    assert not np.array_equal(sine, harm)
    assert float(np.max(np.abs(harm))) <= 0.8 + 1e-9


def test_synthesize_length_and_dtype_and_range():
    y = synthesize_tone(440.0, 0.5, sample_rate=22050, amplitude=1.0, fade_s=0.0)
    assert len(y) == int(round(0.5 * 22050))
    assert y.dtype == np.float64
    assert float(np.max(y)) <= 1.0 + 1e-9
    assert float(np.min(y)) >= -1.0 - 1e-9


@pytest.mark.parametrize(
    "kwargs",
    [
        {"frequency_hz": 0.0},
        {"frequency_hz": -1.0},
        {"frequency_hz": 44100 / 2},
        {"duration_s": 0.0},
        {"duration_s": -1.0},
        {"sample_rate": 7999},
        {"amplitude": 0.0},
        {"amplitude": 1.5},
        {"waveform": "square"},
        {"waveform": "sawtooth"},
        {"fade_s": -0.001},
        {"fade_s": 0.6, "duration_s": 1.0},
    ],
)
def test_synthesize_invalid_params(kwargs):
    base = {"frequency_hz": 440.0, "duration_s": 1.0}
    base.update(kwargs)
    with pytest.raises(ValueError):
        synthesize_tone(**base)


# ===========================================================================
# 判据 3 · WAV 导出
# ===========================================================================


def test_write_wave_pcm16_header_and_quantization(tmp_path):
    data = synthesize_tone(440.0, 2.0, sample_rate=44100, amplitude=0.8)
    path = write_wave(tmp_path / "tone.wav", data, 44100, depth="pcm16")
    assert path.suffix == ".wav"
    with wave.open(str(path), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 44100
        assert wf.getnframes() == 88200
        frames32 = wf.readframes(32)
        all_frames = wf.readframes(wf.getnframes() - 32)
    got32 = np.frombuffer(frames32, dtype="<i2").astype(int)
    exp32 = (np.clip(data[:32], -1.0, 1.0) * 32767.0).astype(np.int16).astype(int)
    assert int(np.max(np.abs(got32 - exp32))) <= 1
    got_all = np.concatenate([got32, np.frombuffer(all_frames, dtype="<i2").astype(int)])
    exp_all = (np.clip(data, -1.0, 1.0) * 32767.0).astype(np.int16).astype(int)
    assert int(np.max(np.abs(got_all - exp_all))) <= 1


def test_write_wave_float32(tmp_path):
    data = synthesize_tone(440.0, 2.0, sample_rate=44100, amplitude=0.8)
    path = write_wave(tmp_path / "f.wav", data, 44100, depth="float32")
    assert sf.info(str(path)).subtype == "FLOAT"
    got, sr = sf.read(str(path), dtype="float32")
    assert sr == 44100
    assert np.allclose(got, data.astype(np.float32), atol=1e-6)


def test_write_wave_auto_suffix(tmp_path):
    data = synthesize_tone(440.0, 0.1)
    path = write_wave(tmp_path / "noext", data, 44100)
    assert path.name == "noext.wav"
    assert path.is_file()


def test_write_wave_bad_depth(tmp_path):
    with pytest.raises(ValueError):
        write_wave(tmp_path / "x.wav", np.zeros(10), 44100, depth="pcm8")


def test_write_wave_missing_parent(tmp_path):
    with pytest.raises(OSError):
        write_wave(tmp_path / "missing" / "x.wav", np.zeros(10), 44100)


# ===========================================================================
# 判据 4 · 依据文件闭环
# ===========================================================================


def test_load_standards_equals_catalog():
    shipped = load_standards()
    catalog = catalog_standards()
    assert shipped == catalog
    assert len(shipped) == len(catalog) == 13
    for a, b in zip(shipped, catalog):
        assert a == b  # 逐条完整相等（含五语 label / 数值 / caveat / source_refs）


def test_resource_schema_version():
    obj = json.loads(RESOURCE.read_text(encoding="utf-8"))
    assert obj["schema_version"] == 1
    assert obj["standards"] == catalog_standards()


def test_standards_structure():
    standards = load_standards()
    assert len(standards) >= 13
    ids = [s["id"] for s in standards]
    assert len(ids) == len(set(ids))
    for s in standards:
        assert 400.0 <= float(s["a4_hz"]) <= 480.0
        assert s["group"] in ("formal", "historical", "orchestral")
        assert all(s["label"].get(loc) for loc in LOCALES)
        assert s.get("evidence") and s.get("caveat")
        assert s.get("source_refs")


def test_source_refs_exist_and_nontrivial():
    """逐件名单：每条 source_refs 对应文件存在且 >100 bytes。"""
    refs = sorted({r for s in load_standards() for r in s["source_refs"]})
    assert len(refs) >= 10
    print("\n逐件 source_refs 名单:")
    for ref in refs:
        path = REF_DIR / ref
        assert path.is_file(), f"缺失依据件: {ref}"
        size = path.stat().st_size
        assert size > 100, f"依据件过小: {ref} ({size} bytes)"
        print(f"  {ref}: {size} bytes")


def test_verify_manifest_pass():
    """worktree 根运行依据件校验：VERDICT=PASS 且资源表已纳入（无 SKIP）。"""
    proc = subprocess.run(
        ["/usr/bin/python3", str(REF_DIR / "verify_manifest.py")],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = proc.stdout
    assert "VERDICT=PASS" in out, out
    assert "checks_failed=0" in out, out
    assert "SKIP: shipped GUI resource table" not in out, out
    assert proc.returncode == 0


# ===========================================================================
# 判据 7 · 新增 i18n 键五语齐（无 Qt，i18n 不依赖 Qt）
# ===========================================================================


def test_i18n_new_keys_five_locales():
    from acouscope.i18n import _STRINGS

    keys = [
        k for k in _STRINGS
        if k.startswith("pitchgen.") or k == "action.pitch_generator"
    ]
    assert len(keys) >= 34
    for k in keys:
        for loc in LOCALES:
            assert _STRINGS[k].get(loc), f"{k} 缺 {loc}"


# ===========================================================================
# PI-P6-PITCH-02 · 24-bit PCM 导出判据
# ===========================================================================


def test_write_wave_bad_depth_float64(tmp_path):
    with pytest.raises(ValueError):
        write_wave(tmp_path / "y.wav", np.zeros(10), 44100, depth="float64")


def test_write_wave_pcm24_header_and_quantization(tmp_path):
    data = synthesize_tone(440.0, 0.02, sample_rate=44100, amplitude=0.8, fade_s=0.0)
    path = write_wave(tmp_path / "t24.wav", data, 44100, depth="pcm24")
    assert path.suffix == ".wav"
    with wave.open(str(path), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 3
        assert wf.getframerate() == 44100
        assert wf.getnframes() == len(data)
        frames24 = wf.readframes(wf.getnframes())

    # 3 字节小端帧符号扩展成 int32，与 24-bit 量化期望逐样本比较
    b = np.frombuffer(frames24, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
    got = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
    got = np.where(got >= (1 << 23), got - (1 << 24), got)
    exp = np.rint(np.clip(data, -1.0, 1.0) * 8388607.0)
    assert int(np.max(np.abs(got.astype(np.int64) - exp.astype(np.int64)))) <= 1

    # 三档文件体字节数严格递增：pcm16 < pcm24 < float32（三档真实不同）
    p16 = write_wave(tmp_path / "t16.wav", data, 44100, depth="pcm16")
    p32 = write_wave(tmp_path / "tf.wav", data, 44100, depth="float32")
    with wave.open(str(p16), "rb") as wf:
        body16 = wf.getnframes() * wf.getnchannels() * wf.getsampwidth()
    with wave.open(str(path), "rb") as wf:
        body24 = wf.getnframes() * wf.getnchannels() * wf.getsampwidth()
    info32 = sf.info(str(p32))
    assert info32.subtype == "FLOAT"
    body32 = info32.frames * info32.channels * 4  # float32 = 4 字节/样本
    assert body24 > body16
    assert body24 < body32
    # 正对照：文件总体积同样严格递增
    assert p16.stat().st_size < path.stat().st_size < p32.stat().st_size


def test_write_wave_pcm24_roundtrip_soundfile(tmp_path):
    pytest.importorskip("soundfile")
    data = synthesize_tone(440.0, 0.02, sample_rate=44100, amplitude=0.8, fade_s=0.0)
    path = write_wave(tmp_path / "rt24.wav", data, 44100, depth="pcm24")
    assert "PCM_24" in sf.info(str(path)).subtype
    got, sr = sf.read(str(path), dtype="float64")
    assert sr == 44100
    assert np.allclose(got, data, atol=2e-7)
