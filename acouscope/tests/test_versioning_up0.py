# SPDX-License-Identifier: GPL-3.0-only
"""UP-0：语义化版本比较器公共模块（acouscope.utils.versioning）三例。"""
import sys
sys.path.insert(0, "src")

from acouscope.ai import ollama_engines as oe
from acouscope.utils import versioning
from acouscope.utils.versioning import is_newer, ver_tuple


def test_boundary_matrix():
    """例 1：边界矩阵（跨版本对；旧版操作数避开旧发布号残留字面，见报告 N-项）。"""
    assert is_newer("0.99.20260925", "0.99.20260920") is True
    assert is_newer("0.99.20260920", "0.99.20260925") is False
    assert is_newer("0.99.20260925", "0.99.20260925") is False
    assert is_newer("v0.99.20260925", "0.99.20260920") is True
    assert is_newer("0.99.20260925.1", "0.99.20260925") is True
    assert is_newer("0.99.20261001", "0.99.20260925") is True


def test_dirty_input_no_raise():
    """例 2：降级不抛（网络侧脏数据防御）。"""
    assert is_newer("", "0.99.20260925") is False
    assert is_newer("abc", "0.99.20260925") is False
    ver_tuple("0.99.20260925-beta")  # 不抛异常


def test_thin_import_same_object():
    """例 3：旧入口零破（薄引 = 同一对象，非复制两份实现）。"""
    assert oe.is_newer("0.99.20260925", "0.99.20260920") is True
    assert oe.is_newer is versioning.is_newer
