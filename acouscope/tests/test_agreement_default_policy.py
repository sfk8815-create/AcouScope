# SPDX-License-Identifier: GPL-3.0-only
"""丙-1 一致率口径判据：默认＝「未分类」剔除，``--include-unclassified`` 才计入分母。

锁的是 ``agreement.py`` 的默认接线（``resolve_exclude_unclassified``），不是一致率算法：
该口径两轮核验中出现过两种说法，故用判据钉死，避免文档与行为再次分叉。
"""

import csv
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "03_Docs_and_Assets" / "paper_support_20261025" / "agreement.py"

MACHINE = {("r1", "1.000-2.000"): "上趋", ("r1", "2.000-3.000"): "平直"}


@pytest.fixture()
def mod(monkeypatch):
    assert SCRIPT.is_file(), f"未找到 {SCRIPT}"
    spec = importlib.util.spec_from_file_location("agreement_under_test", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, "load_machine", lambda: dict(MACHINE))
    return m


def _responses(tmp_path) -> str:
    """两条专家行：一同一异；「异」那条专家标未分类（主口径应被剔除）。"""
    path = tmp_path / "expert.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["recording_id", "segment_id", "label"])
        w.writeheader()
        w.writerow({"recording_id": "r1", "segment_id": "1.000-2.000", "label": "上趋"})
        w.writerow({"recording_id": "r1", "segment_id": "2.000-3.000", "label": "未分类"})
    return str(tmp_path)


def test_default_excludes_unclassified(mod, tmp_path):
    """默认（命令行不传开关）⇒ 未分类不计分母，单列剔除数。"""
    args = mod.build_parser().parse_args([])
    r = mod.run(_responses(tmp_path), mod.resolve_exclude_unclassified(args))
    assert r["excluded_unclassified"] == 1
    assert r["unclassified_in_denominator"] is False
    assert r["n_matched"] == 1
    assert r["agree"] == 1
    assert r["rate"] == 1.0


def test_sensitivity_flag_counts_unclassified(mod, tmp_path):
    """``--include-unclassified`` ⇒ 敏感性档：未分类计入分母，一致率随之变化。"""
    args = mod.build_parser().parse_args(["--include-unclassified"])
    r = mod.run(_responses(tmp_path), mod.resolve_exclude_unclassified(args))
    assert r["excluded_unclassified"] == 0
    assert r["unclassified_in_denominator"] is True
    assert r["n_matched"] == 2
    assert r["agree"] == 1
    assert r["rate"] == 0.5
