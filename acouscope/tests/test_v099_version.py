# SPDX-License-Identifier: GPL-3.0-only
"""T-204: v0.99 版本号冻结测试。"""
import sys
sys.path.insert(0, "src")

import acouscope


class TestVersion:
    """版本号一致性测试。"""

    def test_build_version(self):
        """构建系统版本号（PEP 440 合法）。"""
        assert acouscope.__version__ == "0.99.20261011"

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
        assert 'version = "0.99.20261011"' in src
        assert "0.98" not in src

    def test_build_version_matches_pyproject(self):
        """★ UP-0 同源守卫：构建号必须与 pyproject 真值逐字相同（防两站漂移）。"""
        import pathlib
        import re

        src = pathlib.Path("pyproject.toml").read_text(encoding="utf-8")
        m = re.search(r'^version = "([^"]+)"', src, re.MULTILINE)
        assert m, "pyproject.toml 未找到 version 行"
        assert m.group(1) == acouscope.__version__, (
            f"版本双站漂移：pyproject={m.group(1)} vs __version__={acouscope.__version__}"
        )
        assert "_" not in acouscope.__version__, "构建号不得含下划线（PEP 440）"
