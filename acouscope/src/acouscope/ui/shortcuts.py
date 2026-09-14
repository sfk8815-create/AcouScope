# SPDX-License-Identifier: GPL-3.0-only
"""全局快捷键管理。

提供统一的快捷键注册与分发：
- 全局快捷键（播放/暂停、停止、打开文件等）
- 用户可在设置中自定义
- 平台适配（macOS 用 Cmd，Windows/Linux 用 Ctrl）
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Callable, Optional

from PyQt6.QtCore import QObject
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QWidget


def is_macos() -> bool:
    """判断当前是否为 macOS。"""
    return platform.system() == "Darwin"


def sc(key: str) -> str:
    """平台适配的快捷键字符串。

    将 "Ctrl" 自动替换为 macOS 上的 "Meta"（即 Cmd 键），
    其他平台保持 "Ctrl" 不变。

    用法：sc("Ctrl+O") → macOS 下返回 "Meta+O"，其他平台返回 "Ctrl+O"
    """
    if is_macos():
        return key.replace("Ctrl+", "Meta+")
    return key


@dataclass
class ShortcutEntry:
    """快捷键条目。"""
    action_id: str
    label: str
    default_key: str
    current_key: str
    callback: Optional[Callable] = None
    shortcut_obj: Optional[QShortcut] = None
    category: str = "global"


class ShortcutManager(QObject):
    """全局快捷键管理器。

    使用单例模式，所有视图共享同一个管理器。
    """

    _instance: Optional["ShortcutManager"] = None

    @classmethod
    def instance(cls) -> "ShortcutManager":
        if cls._instance is None:
            cls._instance = ShortcutManager()
        return cls._instance

    def __init__(self):
        super().__init__()
        self._entries: dict[str, ShortcutEntry] = {}

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------

    def register_global(
        self,
        action_id: str,
        label: str,
        default_key: str,
        callback: Callable,
        parent: QWidget,
    ) -> QShortcut:
        """注册全局快捷键。

        Args:
            action_id: 唯一标识
            label: 显示名称
            default_key: 默认按键
            callback: 触发回调
            parent: 父控件（快捷键绑定在此控件上）

        Returns:
            QShortcut 对象
        """
        key = self._load_key(action_id, default_key)
        sc = QShortcut(QKeySequence(key), parent)
        sc.activated.connect(callback)

        entry = ShortcutEntry(
            action_id=action_id,
            label=label,
            default_key=default_key,
            current_key=key,
            callback=callback,
            shortcut_obj=sc,
            category="global",
        )
        self._entries[action_id] = entry
        return sc

    # ------------------------------------------------------------------
    # 自定义修改
    # ------------------------------------------------------------------

    def set_key(self, action_id: str, key: str) -> bool:
        """修改快捷键。"""
        entry = self._entries.get(action_id)
        if not entry or not entry.shortcut_obj:
            return False

        entry.shortcut_obj.setKey(QKeySequence(key))
        entry.current_key = key
        self._save_key(action_id, key)
        return True

    def reset_key(self, action_id: str) -> bool:
        """恢复默认快捷键。"""
        entry = self._entries.get(action_id)
        if not entry:
            return False
        return self.set_key(action_id, entry.default_key)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def all_entries(self) -> list[ShortcutEntry]:
        """获取所有快捷键条目（按显示名排序）。"""
        result = list(self._entries.values())
        result.sort(key=lambda e: e.label)
        return result

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _load_key(self, action_id: str, default: str) -> str:
        try:
            from acouscope.utils.config import get_data_dir
            path = get_data_dir() / "shortcuts.json"
            if path.exists():
                import json
                data = json.loads(path.read_text(encoding="utf-8"))
                return data.get(action_id, default)
        except Exception:
            pass
        return default

    def _save_key(self, action_id: str, key: str):
        try:
            from acouscope.utils.config import get_data_dir
            path = get_data_dir() / "shortcuts.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            import json
            data = {}
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except ValueError:
                    data = {}
            data[action_id] = key
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
