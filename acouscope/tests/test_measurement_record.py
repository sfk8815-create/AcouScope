# SPDX-License-Identifier: GPL-3.0-only
"""PI-P7-PREC-B T05：测量元数据记录（纯标准库，零 Qt）。

覆盖（设计约定 §判据-2 / §范围-2）：
  ① ``MEASUREMENT_FIELDS`` 17 项齐、顺序固定（逐字对照）；
  ② ``build_measurement_record``：format_version=1 / generated_at UTC ISO8601 /
     缺项填 None 不臆造 / 未知键忽略；
  ③ ``input_sha256`` 非 64 hex 抛 ``ValueError``（合法 hex / None 通过）；
  ④ JSON 写→读往返一致（dict/None/数值无损）；
  ⑤ CSV 单行 17 列、``resample_quality``/``extra`` 为 JSON 字符串、
     读回结构一致（缺项 None）；
  ⑥ GUI/重采样链路字段可查（resample_quality 结构原样保留）。
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone

import pytest

from acouscope.analysis.measurement_record import (
    MEASUREMENT_FIELDS,
    build_measurement_record,
    read_measurement_csv,
    read_measurement_json,
    write_measurement_csv,
    write_measurement_json,
)

EXPECTED_FIELDS = (
    "format_version", "generated_at", "sample_rate", "frame_size",
    "hop_length", "window", "zero_pad", "backend", "backend_version",
    "a4_reference_hz", "n_eff", "snr_db", "input_sha256",
    "calibration_status", "resample_quality", "uncertainty_cent", "extra",
)
VALID_SHA = hashlib.sha256(b"acouscope-pi-p7-prec-b").hexdigest()


def _full_record(**overrides) -> dict:
    kwargs = dict(
        sample_rate=44100,
        frame_size=2048,
        hop_length=512,
        window="hann",
        zero_pad=16,
        backend="pyin",
        backend_version="0.99",
        a4_reference_hz=440.0,
        n_eff=12.5,
        snr_db=20.0,
        input_sha256=VALID_SHA,
        calibration_status="pending",
        resample_quality={
            "method": "linear_fallback", "anti_alias": False,
            "uncertainty_cent": 21.05,
        },
        uncertainty_cent=2.55,
        extra={"region": [0.5, 0.9], "note": "P7"},
    )
    kwargs.update(overrides)
    return build_measurement_record(**kwargs)


# ----------------------------------------------------------------------
# ① 17 字段 / 顺序固定
# ----------------------------------------------------------------------
def test_measurement_fields_exactly_17_in_order():
    print("MEASUREMENT_FIELDS len=%d %s" % (len(MEASUREMENT_FIELDS),
                                            list(MEASUREMENT_FIELDS)))
    assert len(MEASUREMENT_FIELDS) == 17
    assert tuple(MEASUREMENT_FIELDS) == EXPECTED_FIELDS
    assert len(set(MEASUREMENT_FIELDS)) == 17


def test_record_keys_follow_fields_order():
    rec = build_measurement_record()
    assert tuple(rec.keys()) == MEASUREMENT_FIELDS
    print("record keys=%s" % list(rec.keys()))


# ----------------------------------------------------------------------
# ② build 语义
# ----------------------------------------------------------------------
def test_build_defaults_format_version_and_utc_iso8601():
    rec = build_measurement_record()
    assert rec["format_version"] == 1
    gen = rec["generated_at"]
    dt = datetime.fromisoformat(gen)
    print("generated_at=%s parsed_utcoffset=%s" % (gen, dt.utcoffset()))
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0.0  # UTC
    assert "+00:00" in gen  # ISO8601 UTC 后缀


def test_build_missing_fields_are_none_no_fabrication():
    rec = build_measurement_record(sample_rate=44100)
    for field in MEASUREMENT_FIELDS:
        if field in ("format_version", "generated_at", "sample_rate"):
            continue
        assert rec[field] is None, field
    assert rec["sample_rate"] == 44100
    print("missing-filled-None fields=%d" % 14)


def test_build_format_version_cannot_be_overridden():
    """format_version 恒 1、generated_at 自动生成，防止臆造。"""
    rec = build_measurement_record(format_version=999, generated_at="fake")
    print("format_version=%s generated_at=%s" % (rec["format_version"],
                                                  rec["generated_at"]))
    assert rec["format_version"] == 1
    assert rec["generated_at"] != "fake"
    datetime.fromisoformat(rec["generated_at"])


def test_build_unknown_kwargs_ignored():
    rec = build_measurement_record(totally_unknown_key="x")
    assert "totally_unknown_key" not in rec
    assert tuple(rec.keys()) == MEASUREMENT_FIELDS
    print("unknown kwarg ignored; keys=%d" % len(rec))


# ----------------------------------------------------------------------
# ③ input_sha256 校验
# ----------------------------------------------------------------------
def test_input_sha256_valid_64_hex_ok():
    for sha in (VALID_SHA, "A" * 64, "0" * 64, "0123456789abcdef" * 4):
        rec = build_measurement_record(input_sha256=sha)
        assert rec["input_sha256"] == sha
    print("valid sha256 accepted (lower/upper/digit-mix)")


def test_input_sha256_none_allowed():
    assert build_measurement_record(input_sha256=None)["input_sha256"] is None
    assert build_measurement_record()["input_sha256"] is None
    print("input_sha256 None / missing allowed (unknown, not fabricated)")


@pytest.mark.parametrize("bad", [
    "", "abc", "z" * 64, "g" * 64, "a" * 63, "a" * 65,
    "a" * 64 + " ", 12345, ["a" * 64], "0x" + "a" * 62,
])
def test_input_sha256_not_64_hex_raises_value_error(bad):
    with pytest.raises(ValueError):
        build_measurement_record(input_sha256=bad)
    print("rejected input_sha256=%r" % (bad,))


# ----------------------------------------------------------------------
# ④ JSON 往返一致
# ----------------------------------------------------------------------
def test_json_roundtrip_identical(tmp_path):
    rec = _full_record()
    path = tmp_path / "measurement.json"
    write_measurement_json(path, rec)
    assert path.exists() and path.stat().st_size > 0
    back = read_measurement_json(path)
    print("JSON roundtrip equal=%s bytes=%d" % (back == rec,
                                                path.stat().st_size))
    assert back == rec
    assert tuple(back.keys()) == MEASUREMENT_FIELDS


def test_json_roundtrip_with_all_none_minimal(tmp_path):
    rec = build_measurement_record()
    path = tmp_path / "minimal.json"
    write_measurement_json(path, rec)
    back = read_measurement_json(path)
    assert back == rec
    assert back["resample_quality"] is None and back["extra"] is None
    print("JSON minimal roundtrip keys=%d" % len(back))


def test_json_is_utf8_readable_with_resample_quality_dict(tmp_path):
    rec = _full_record(extra={"中文": "测量"})
    path = tmp_path / "utf8.json"
    write_measurement_json(path, rec)
    text = path.read_text(encoding="utf-8")
    assert "测量" in text  # ensure_ascii=False
    assert read_measurement_json(path)["extra"] == {"中文": "测量"}
    print("JSON utf-8 extra preserved")


# ----------------------------------------------------------------------
# ⑤ CSV 单行 17 列 / JSON 字符串 / 结构一致
# ----------------------------------------------------------------------
def test_csv_single_row_17_columns(tmp_path):
    rec = _full_record()
    path = tmp_path / "measurement.csv"
    write_measurement_csv(path, rec)
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    print("CSV rows=%d columns=%d" % (len(rows), len(rows[0])))
    assert len(rows) == 1            # 单行（无表头）
    assert len(rows[0]) == 17        # 17 列


def test_csv_resample_quality_and_extra_are_json_strings(tmp_path):
    rec = _full_record()
    path = tmp_path / "measurement.csv"
    write_measurement_csv(path, rec)
    with path.open(encoding="utf-8", newline="") as fh:
        row = next(csv.reader(fh))
    by_field = dict(zip(MEASUREMENT_FIELDS, row))
    print("CSV resample_quality cell=%s" % by_field["resample_quality"])
    print("CSV extra cell=%s" % by_field["extra"])
    assert json.loads(by_field["resample_quality"]) == rec["resample_quality"]
    assert json.loads(by_field["extra"]) == rec["extra"]
    assert by_field["input_sha256"] == VALID_SHA
    assert by_field["format_version"] == "1"


def test_csv_roundtrip_structure(tmp_path):
    rec = _full_record()
    path = tmp_path / "measurement.csv"
    write_measurement_csv(path, rec)
    back = read_measurement_csv(path)
    print("CSV roundtrip resample_quality=%s extra=%s"
          % (back["resample_quality"], back["extra"]))
    assert tuple(back.keys()) == MEASUREMENT_FIELDS
    assert back["resample_quality"] == rec["resample_quality"]
    assert back["extra"] == rec["extra"]
    assert back["input_sha256"] == rec["input_sha256"]
    assert back["format_version"] == str(rec["format_version"])
    assert set(back.keys()) == set(MEASUREMENT_FIELDS)  # 无多余/缺漏字段


def test_csv_roundtrip_none_fields_become_empty_then_none(tmp_path):
    rec = build_measurement_record()
    path = tmp_path / "minimal.csv"
    write_measurement_csv(path, rec)
    with path.open(encoding="utf-8", newline="") as fh:
        row = next(csv.reader(fh))
    by_field = dict(zip(MEASUREMENT_FIELDS, row))
    print("CSV minimal None-cells=%d" % sum(1 for v in row if v == ""))
    assert by_field["sample_rate"] == ""
    assert by_field["resample_quality"] == ""
    assert by_field["extra"] == ""
    back = read_measurement_csv(path)
    assert back["sample_rate"] is None
    assert back["resample_quality"] is None
    assert back["extra"] is None


def test_csv_bad_shape_raises(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_measurement_csv(path)
    path.write_text(",".join(["x"] * 17) + "\n" + ",".join(["y"] * 17) + "\n",
                    encoding="utf-8")
    with pytest.raises(ValueError):
        read_measurement_csv(path)
    print("CSV bad shape guarded")


# ----------------------------------------------------------------------
# ⑥ resample_quality 链路字段可查
# ----------------------------------------------------------------------
def test_record_preserves_resample_quality_anti_alias_link():
    q = {"method": "linear_fallback", "anti_alias": False,
         "uncertainty_cent": 21.05}
    rec = build_measurement_record(resample_quality=q)
    assert rec["resample_quality"] is q
    assert rec["resample_quality"]["anti_alias"] is False
    print("LINK record.resample_quality.anti_alias=%r"
          % rec["resample_quality"]["anti_alias"])


def test_generated_at_is_recent_utc(tmp_path):
    before = datetime.now(timezone.utc)
    rec = build_measurement_record()
    after = datetime.now(timezone.utc)
    dt = datetime.fromisoformat(rec["generated_at"])
    print("generated_at in [before, after]=%s"
          % (before <= dt <= after))
    assert before <= dt <= after
