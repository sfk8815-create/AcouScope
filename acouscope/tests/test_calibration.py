# SPDX-License-Identifier: GPL-3.0-only
"""精度标定（对参考真值口径）测试（B2-02 / PI-P5 批次 2）。CALIBRATION_TEST_V1

覆盖（派活令 §判据）：
① 已知偏差对拍：全部 +50 cent → mean_bias≈50 / p95_abs≈50 / dispersion≈0；
   混合 ±（参考真值非零）→ 手算对拍（正负对照，防恒返常量）；
② 确定性：同输入两次调用逐位一致；报告件除 generated_at 单行外逐位一致；
   CLI --synth-demo 两次运行数值面（stdout）逐位一致；
③ metadata 往返：calibration_metadata() 串入 ProjectFile.metadata → 存取往返
   一致；旧文件（无 calibration_ref 键 / 无 metadata 键）零崩溃。

口径：本模块为「对参考真值」；多轨互比口径（p50/p95/bias/shared/remainder）
见 compare_present.py:1136-1164，两套读数分列、不得混称，本测试不涉多轨统计。
"""

import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("numpy")

from acouscope.analysis.calibration import (  # noqa: E402
    CALIBRATION_METADATA_KEY,
    calibrate_against_reference,
    calibration_metadata,
    surface_sha256,
    write_report,
)

_CLI = Path(__file__).resolve().parents[2] / "scripts" / "calib_precision.py"


def _strip_generated_at(text: str) -> str:
    """剥去 generated_at 单行（时间戳单列一键，不参与一致性断言）。"""
    return "\n".join(
        line for line in text.splitlines() if not line.startswith("- generated_at")
    )


def test_known_bias_against_reference():
    """① 已知偏差对拍（含正负对照与零样本边界）。"""
    # 全部 +50 cent（measured = reference + 50）
    stats = calibrate_against_reference([(150.0, 100.0)] * 4)
    assert stats["n"] == 4
    assert stats["mean_bias_cents"] == pytest.approx(50.0)
    assert stats["p95_abs_cents"] == pytest.approx(50.0)
    assert stats["dispersion_cents"] == pytest.approx(0.0, abs=1e-12)

    # 混合 ±（参考真值非零，手算对拍）：
    #   bias = [+50, -30] ⇒ mean = 10；
    #   |bias| = [50, 30] ⇒ p95 = 30 + 0.95 * (50 - 30) = 49；
    #   dispersion = sqrt(((50-10)^2 + (-30-10)^2) / 2) = sqrt(1600) = 40
    mixed = calibrate_against_reference([(170.0, 120.0), (90.0, 120.0)])
    assert mixed["n"] == 2
    assert mixed["mean_bias_cents"] == pytest.approx(10.0)
    assert mixed["p95_abs_cents"] == pytest.approx(49.0)
    assert mixed["dispersion_cents"] == pytest.approx(40.0)

    # 负向系统偏差（符号不丢）：mean 为负、p95/dispersion 非负
    negative = calibrate_against_reference([(-30.0, 0.0), (-30.0, 0.0)])
    assert negative["mean_bias_cents"] == pytest.approx(-30.0)
    assert negative["p95_abs_cents"] == pytest.approx(30.0)
    assert negative["dispersion_cents"] == pytest.approx(0.0, abs=1e-12)

    # 零样本 ⇒ n=0 且统计量 None（不抛、不填 0）
    empty = calibrate_against_reference([])
    assert empty["n"] == 0
    assert empty["mean_bias_cents"] is None
    assert empty["dispersion_cents"] is None
    assert empty["p95_abs_cents"] is None


def test_determinism_calls_and_report_and_cli(tmp_path):
    """② 确定性：同输入两次调用逐位一致；报告件除时间戳外逐位一致；CLI 两次运行一致。"""
    pairs = [(170.0, 120.0), (90.0, 120.0), (130.0, 120.0), (110.0, 120.0)]
    assert calibrate_against_reference(pairs) == calibrate_against_reference(pairs)

    stats = calibrate_against_reference(pairs)
    base = {"dataset": "det_v1", "version": "1.0.0", "stats": stats}
    sha = surface_sha256(base)
    assert sha == surface_sha256(base)  # 数值面 sha256 自身确定
    # generated_at 不进数值面：换时间戳 ⇒ sha 不变
    assert surface_sha256(dict(base, generated_at="2026-01-01T00:00:00+00:00")) == sha

    p1 = dict(base, report_sha256=sha, generated_at="2026-10-23T00:00:00+00:00")
    p2 = dict(base, report_sha256=sha, generated_at="2026-10-24T12:34:56+00:00")
    write_report(p1, tmp_path / "r1.md")
    write_report(p2, tmp_path / "r2.md")
    t1 = (tmp_path / "r1.md").read_text(encoding="utf-8")
    t2 = (tmp_path / "r2.md").read_text(encoding="utf-8")
    assert _strip_generated_at(t1) == _strip_generated_at(t2)
    assert "report_sha256：{0}".format(sha) in t1
    assert t1.count("generated_at") == 1  # 时间戳单列一键

    # CLI --synth-demo 两次运行：退出码均 0、stdout 数值面逐位一致
    cli = _load_cli()
    out = []
    for _ in range(2):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["--synth-demo"])
        assert rc == 0
        out.append(buf.getvalue())
    assert out[0] == out[1]
    assert "generated_at" not in out[0]  # stdout 数值面无时间戳
    assert "PASS=1" in out[0]


def _load_cli():
    """载入 scripts/calib_precision.py——与 CLI 同一份实现（scripts/ 非包 → spec 加载）。"""
    spec = importlib.util.spec_from_file_location("calib_precision_under_test", str(_CLI))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_metadata_roundtrip_and_legacy(tmp_path):
    """③ metadata 往返：calibration_metadata() → ProjectFile.metadata → 存取一致；旧文件零崩溃。"""
    from acouscope.app.project import ProjectFile, ProjectManager

    stats = calibrate_against_reference([(170.0, 120.0), (90.0, 120.0)])
    base = {"dataset": "roundtrip_v1", "version": "2.0.0", "stats": stats}
    payload = dict(
        base,
        report_sha256=surface_sha256(base),
        generated_at="2026-10-23T08:00:00+00:00",
    )
    raw = calibration_metadata(payload)
    assert isinstance(raw, str)  # Dict[str, str] 不变式
    assert "generated_at" not in raw  # 时间戳不入 metadata
    decoded = json.loads(raw)
    assert CALIBRATION_METADATA_KEY in decoded
    assert decoded[CALIBRATION_METADATA_KEY]["report_sha256"] == payload["report_sha256"]
    assert decoded[CALIBRATION_METADATA_KEY]["dataset"] == "roundtrip_v1"
    assert decoded[CALIBRATION_METADATA_KEY]["version"] == "2.0.0"
    assert decoded[CALIBRATION_METADATA_KEY]["n"] == 2

    # 存取往返（用法照 tests/test_analysis_params_snapshot.py 项目文件先例）
    pm = ProjectManager()
    pm.new("calib-test")
    pm.current.files.append(ProjectFile(path="/nonexistent/x.wav", label="x"))
    pm.current.files[0].metadata[CALIBRATION_METADATA_KEY] = raw
    proj_path = tmp_path / "calib.acouproj"
    pm.save(proj_path)
    loaded = ProjectManager().load(str(proj_path))
    back = loaded.files[0].metadata[CALIBRATION_METADATA_KEY]
    assert back == raw

    # 旧文件：metadata 在场但无 calibration_ref 键 ⇒ 零崩溃
    legacy = json.loads(proj_path.read_text(encoding="utf-8"))
    for entry in legacy["files"]:
        entry["metadata"] = {"Title": "旧工程"}
    legacy_path = tmp_path / "legacy.acouproj"
    legacy_path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    project = ProjectManager().load(legacy_path)
    assert CALIBRATION_METADATA_KEY not in project.files[0].metadata
    assert project.files[0].metadata == {"Title": "旧工程"}

    # 更早形态：连 metadata 键都没有 ⇒ 空 dict、零崩溃
    legacy2 = {"name": "old", "version": "0.1", "files": [{"path": "/y.wav", "label": ""}]}
    legacy2_path = tmp_path / "legacy2.acouproj"
    legacy2_path.write_text(json.dumps(legacy2, ensure_ascii=False), encoding="utf-8")
    project2 = ProjectManager().load(legacy2_path)
    assert project2.files[0].metadata == {}
