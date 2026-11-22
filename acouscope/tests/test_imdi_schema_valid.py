# SPDX-License-Identifier: GPL-3.0-only
"""M-6b：IMDI XSD 闸——对 PROFILE_IMDI 产物做 XMLSchema.validate 断言。

- lxml 不在 requirements/pyproject（取证件 §一），故 importorskip——闸只在
  lxml 可用的环境跑，不得为跑闸而加依赖（加依赖属另裁）。
- XSD = 仓内 02_References/IMDI_3.0.22_schema.xsd；开跑先钉其 SHA-256，
  不符即红（防有人换 schema 而闸不自知）。
- 四例：两正（全值 / 全空皆 valid=True——锁死「必填件齐、值留空」实现，
  防回归成"有值才出元素"）+ 两破坏反例（根改名 / 删 Session/Name → 必红）。
  反例是闸的存在理由；只写正例 = 空闸。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

lxml = pytest.importorskip("lxml")
from lxml import etree  # noqa: E402

from acouscope.annotation import export  # noqa: E402
from acouscope.annotation.metadata import SessionMetadata  # noqa: E402

# 仓内 XSD 路径（相对本测试文件定位，勿硬编码绝对路径）
_XSD = Path(__file__).resolve().parents[2] / "02_References" / "IMDI_3.0.22_schema.xsd"
# 开跑即钉的 XSD SHA-256（取证件 §九；换 schema 而闸不自知即红）
_XSD_SHA256 = "ec3f3fdcc464fd889cb15c5f3b7afc1585edf8448d3a02f5bb60e8f01b9e4e9c"
_IMDI_NS = "http://www.mpi.nl/IMDI/Schema/IMDI"


@pytest.fixture(scope="module")
def schema():
    """装载 XSD 并校验其 SHA-256（不符即 fail，防 schema 被换）。"""
    raw = _XSD.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == _XSD_SHA256, f"XSD SHA-256 不符（schema 疑被换）: {digest}"
    return etree.XMLSchema(etree.fromstring(raw))


# 全 12 标准键 + 1 自定义键（与 test_export_profiles FIXTURE 同款）
_FULL = {
    "Identifier": "/field/AC-2026-001.wav",
    "Title": "AcouScope 田野录音",
    "Creator": "张三",
    "Date": "2026-08-15",
    "Location": "贵州省黔东南州",
    "GenreContext": "飞歌/山地民歌",
    "ActorRole": "主唱",
    "SamplingRate": 44100,
    "BitDepth": 16,
    "Format": "WAV",
    "Channels": 1,
    "Duration": 12.5,
    "Note": "田野笔记甲",
}


def _full_session() -> SessionMetadata:
    m = SessionMetadata()
    for k, v in _FULL.items():
        m.set(k, v)
    return m


def _validate(schema, path) -> bool:
    return schema.validate(etree.parse(str(path)))


class TestImdiSchemaValid:
    def test_full_values_valid(self, schema, tmp_path):
        """例 1 正：12 字段全值 → XMLSchema.validate 通过。"""
        p = tmp_path / "full.imdi.xml"
        export.export_session_xml(p, _full_session(), export.PROFILE_IMDI)
        assert _validate(schema, p) is True, list(schema.error_log)

    def test_empty_session_valid(self, schema, tmp_path):
        """例 2 正：SessionMetadata() 全空 → 仍通过（必填件齐、值留空亦合法）。

        锁死「必填件落空元素」实现，防回归成"有值才出元素"。
        """
        p = tmp_path / "empty.imdi.xml"
        export.export_session_xml(p, SessionMetadata(), export.PROFILE_IMDI)
        assert _validate(schema, p) is True, list(schema.error_log)

    def test_wrong_root_rejected(self, schema, tmp_path):
        """例 3 反（必红）：根标签改成 IMDI（非 METATRANSCRIPT）→ validate 为 False。"""
        p = tmp_path / "badroot.imdi.xml"
        export.export_session_xml(p, _full_session(), export.PROFILE_IMDI)
        tree = etree.parse(str(p))
        root = tree.getroot()
        root.tag = f"{{{_IMDI_NS}}}IMDI"          # 改名 → 无匹配全局声明
        assert schema.validate(tree) is False

    def test_missing_session_name_rejected(self, schema, tmp_path):
        """例 4 反（必红）：删掉 Session/Name（必填）→ validate 为 False。"""
        p = tmp_path / "noname.imdi.xml"
        export.export_session_xml(p, _full_session(), export.PROFILE_IMDI)
        tree = etree.parse(str(p))
        name = tree.getroot().find(f"{{{_IMDI_NS}}}Session/{{{_IMDI_NS}}}Name")
        assert name is not None                       # 先确认产物里确有 Name
        name.getparent().remove(name)                 # 删必填件
        assert schema.validate(tree) is False
