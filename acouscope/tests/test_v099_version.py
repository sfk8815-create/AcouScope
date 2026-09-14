# SPDX-License-Identifier: GPL-3.0-only
"""T-204: v0.99 版本号冻结测试。"""
import sys
sys.path.insert(0, "src")

import acouscope


class TestVersion:
    """版本号一致性测试。"""

    def test_build_version(self):
        """构建系统版本号（PEP 440 合法）。"""
        assert acouscope.__version__ == "0.99.20260904"

    def test_display_version(self):
        """UI 显示版本号。"""
        assert hasattr(acouscope, "__version_display__")
        assert "0.99" in acouscope.__version_display__
        assert "beta" in acouscope.__version_display__.lower()

    def test_no_beta_in_build_version(self):
        """构建版本号中不含括号/下划线（PEP 440）。"""
        assert "(" not in acouscope.__version__
        assert ")" not in acouscope.__version__
        assert "_" not in acouscope.__version__.split(".")

    def test_pyproject_toml_version(self):
        """pyproject.toml 版本号。"""
        src = open("pyproject.toml", encoding="utf-8").read()
        assert 'version = "0.99.20260904"' in src
        assert "0.98" not in src
