# SPDX-License-Identifier: GPL-3.0-only
"""应用层模块。

包含应用控制器、项目管理、偏好设置等。
"""

from .controller import AppController
from .project import ProjectManager
from .preferences import Preferences

__all__ = ["AppController", "ProjectManager", "Preferences"]
