# SPDX-License-Identifier: GPL-3.0-only
"""T-205: v0.99 代码净化测试。"""
import sys
sys.path.insert(0, "src")

import subprocess


class TestCleanup:
    """代码净化验证。"""

    def test_no_f401_in_backends(self):
        """backends/ 目录无 F401 未使用 import。"""
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "src/acouscope/analysis/backends/",
             "--select=F401", "--output-format=json"],
            capture_output=True, text=True
        )
        import json
        data = json.loads(result.stdout) if result.stdout.strip() else []
        f401 = [d for d in data if d.get("code") == "F401"]
        assert len(f401) == 0, f"F401 remaining: {len(f401)}"

    def test_swift_f0_imports_clean(self):
        """swift_f0.py 无 PitchBackend import。"""
        src = open("src/acouscope/analysis/backends/swift_f0.py", encoding="utf-8").read()
        assert "from acouscope.analysis.backends.base import PitchBackend" not in src

    def test_rmvpe_imports_clean(self):
        """rmvpe.py 无 PitchBackend import。"""
        src = open("src/acouscope/analysis/backends/rmvpe.py", encoding="utf-8").read()
        assert "from acouscope.analysis.backends.base import PitchBackend" not in src

    def test_backends_still_importable(self):
        """清理后仍可正常导入。"""
        from acouscope.analysis.backends.swift_f0 import SwiftF0Backend
        from acouscope.analysis.backends.rmvpe import RMVPEBackend
        from acouscope.analysis.backends.base import PyinBackend
        assert SwiftF0Backend is not None
        assert RMVPEBackend is not None
        assert PyinBackend is not None
