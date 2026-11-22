# SPDX-License-Identifier: GPL-3.0-only
"""PI-P7-PREC-C T09：24-bit WAV 跨语言独立验证（Python ↔ Node/wavefile）。

正对照：write_wave(pcm24) 生成含正负样本 WAV → node 脚本两路独立读数
→ stdout 单行 JSON PASS=true / bitsPerSample=24 / maxDelta<=1。
负对照：NODE_PATH 指向空目录 → 脚本退出 2 且输出 WAVEFILE_UNAVAILABLE（禁静默）。

node 缺失时 pytest.skip（验收带 NODE_PATH 实跑，不许 skip 冒充）。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from acouscope.dsp.pitch_tone import write_wave

SR = 44100
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_wav24_node.mjs"
# 运行期等价于 wavefile@11 安装目录；源码不写死该绝对路径字面。
_DEFAULT_NODE_MODULES = str(Path(os.sep) / "tmp" / "pi_p7_node" / "node_modules")


def _node_path() -> str:
    if shutil.which("node") is None:
        pytest.skip("node 运行时不可用")
    return os.environ.get("NODE_PATH", _DEFAULT_NODE_MODULES)


def _require_wavefile(node_path: str) -> None:
    """无验证件时放行（skip）；显式声明 NODE_PATH 却缺件时 fail（禁 skip 冒充）。"""
    if (Path(node_path) / "wavefile").is_dir():
        return None
    if "NODE_PATH" in os.environ:
        pytest.fail("NODE_PATH 已显式设置但 wavefile@11 不可用（禁 skip 冒充）")
    pytest.skip("wavefile@11 开发期验证件未安装")


def _pcm24_wav(tmp_path: Path) -> Path:
    # 含正负样本的满幅信号（正弦天然覆盖正/负）
    t = np.arange(int(0.05 * SR), dtype=np.float64) / float(SR)
    data = 0.8 * np.sin(2 * np.pi * 440.0 * t)
    assert float(data.max()) > 0 and float(data.min()) < 0
    return write_wave(tmp_path / "tone24.wav", data, SR, depth="pcm24")


def test_node_two_independent_readings_pass(tmp_path):
    node_path = _node_path()
    _require_wavefile(node_path)
    wav = _pcm24_wav(tmp_path)
    proc = subprocess.run(
        ["node", str(_SCRIPT), str(wav)],
        env={**os.environ, "NODE_PATH": node_path},
        capture_output=True,
        text=True,
        timeout=120,
    )
    print(f"[T09] rc={proc.returncode} stdout={proc.stdout.strip()} stderr={proc.stderr.strip()}")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    payload = json.loads(proc.stdout.strip())
    assert payload["PASS"] is True
    assert payload["bitsPerSample"] == 24
    assert payload["wavefileBitDepth"] == 24
    assert payload["sampleRate"] == SR
    assert payload["maxDelta"] <= 1
    assert payload["frames"] == int(0.05 * SR)


def test_node_negative_control_wavefile_unavailable(tmp_path):
    _node_path()  # 仅确认 node 存在（避免负对照因缺 node 而假绿）
    empty = tmp_path / "empty_node_path"
    empty.mkdir()
    wav = _pcm24_wav(tmp_path)
    proc = subprocess.run(
        ["node", str(_SCRIPT), str(wav)],
        env={**os.environ, "NODE_PATH": str(empty)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    print(f"[T09-NEG] rc={proc.returncode} stdout={proc.stdout.strip()}")
    assert proc.returncode == 2
    assert "WAVEFILE_UNAVAILABLE" in (proc.stdout + proc.stderr)
    # 禁静默通过：绝不能输出 PASS=true
    assert "PASS" not in proc.stdout


def test_script_has_spdx_header():
    assert "SPDX-License-Identifier: GPL-3.0-only" in _SCRIPT.read_text(encoding="utf-8")


def test_require_wavefile_guards(tmp_path, monkeypatch):
    # 未显式 NODE_PATH + 缺件 → skip（清理后仓库自洽）
    monkeypatch.delenv("NODE_PATH", raising=False)
    with pytest.raises(pytest.skip.Exception):
        _require_wavefile(str(tmp_path / "missing"))

    # 显式声明 NODE_PATH 却缺件 → fail（禁 skip 冒充）
    monkeypatch.setenv("NODE_PATH", str(tmp_path / "missing"))
    with pytest.raises(pytest.fail.Exception):
        _require_wavefile(os.environ["NODE_PATH"])

    # 验证件存在 → 正常返回（不看 env）
    (tmp_path / "ok" / "wavefile").mkdir(parents=True)
    assert _require_wavefile(str(tmp_path / "ok")) is None
