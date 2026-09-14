# SPDX-License-Identifier: GPL-3.0-only
"""状态栏数据段宿主（CB-013 D-2）。

段注册体系：段 key 注册表（默认五段）→ 每个段自动拥有一个 QLabel 承载控件
与一个 QMenu checkable 菜单项；勾选即切该段显隐。右键菜单由宿主按注册表
动态生成（新段只需注册，菜单/显隐/持久化逻辑零分支）。

显隐配置持久化到 ``<get_data_dir()>/ui_statusbar_segments.json``：
- 变更即存（json，``{"segments": {key: bool}}``）；
- 启动加载；文件缺失/损坏回落默认五段全显。

注意：本文件只提供「段显隐 + 文本读写」机制，数据来源由 main_window 在
既有更新点喂入（播放位置/录音计时/缩放/文件信息）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMenu, QWidget

from acouscope.i18n import tr


@dataclass(frozen=True)
class SegmentSpec:
    """段规格：key（注册表主键） + 菜单/前缀 i18n label key。"""

    key: str
    label_key: str


# 默认五段（注册顺序即状态栏显示顺序）
DEFAULT_SEGMENTS: tuple[SegmentSpec, ...] = (
    SegmentSpec("file", "status.seg.file"),
    SegmentSpec("sample_rate", "status.seg.sample_rate"),
    SegmentSpec("play_position", "status.seg.play_position"),
    SegmentSpec("record_timer", "status.seg.record_timer"),
    SegmentSpec("zoom", "status.seg.zoom"),
)


class StatusBarSegments(QWidget):
    """状态栏数据段容器：注册 → QLabel；右键勾选显隐；配置持久化。"""

    def __init__(
        self,
        specs: tuple[SegmentSpec, ...] = DEFAULT_SEGMENTS,
        config_path: Path | str | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._specs: dict[str, SegmentSpec] = {}
        self._labels: dict[str, QLabel] = {}
        self._visible: dict[str, bool] = {}
        self._config_path = Path(config_path) if config_path is not None else None

        # 与 QStatusBar 同底色（panel），避免全局 QSS 的 QWidget 底与之断层
        from acouscope.ui.theme import style_when_theme

        style_when_theme(self, lambda c: f"background: {c['panel']};")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(10)

        for spec in specs:
            self._register(spec)

        self._load()

    # ------------------------------------------------------------------
    # 注册表（新增段只在此注册，其余逻辑零分支）
    # ------------------------------------------------------------------

    def _register(self, spec: SegmentSpec) -> None:
        key = spec.key
        label = QLabel("", self)
        label.setObjectName(f"seg_{key}")
        from acouscope.ui.theme import style_when_theme

        style_when_theme(label, lambda c: f"color: {c['sub']};")
        self._labels[key] = label
        self._visible[key] = True
        self._specs[key] = spec
        self.layout().addWidget(label)

    def set_temporary_text(self, text: str | None) -> None:
        """临时读数段（T-326 Pδ）：显示在段区最右，不入注册表/菜单/持久化。

        传 None 清空隐藏；文本未变则不重写（避免高频刷新触发重排）。
        """
        self._ensure_temp_label()
        label = self._temp_label
        if text:
            if label.text() != text:
                label.setText(text)
            label.show()
        else:
            label.clear()
            label.hide()

    def clear_temporary(self) -> None:
        """隐藏并清空临时读数段。"""
        self.set_temporary_text(None)

    # ------------------------------------------------------------------
    # 临时读数段（内部动态控件，不进 _specs/_visible，故右键/持久化零影响）
    # ------------------------------------------------------------------

    def _ensure_temp_label(self) -> None:
        if getattr(self, "_temp_label", None) is not None:
            return
        label = QLabel("", self)
        label.setObjectName("seg_temp_readout")
        from acouscope.ui.theme import style_when_theme

        style_when_theme(label, lambda c: f"color: {c['sub']};")
        label.hide()
        self._temp_label = label
        self.layout().addWidget(label)

    def keys(self) -> tuple[str, ...]:
        """已注册段 key（顺序 = 显示顺序）。"""
        return tuple(self._specs)

    def label(self, key: str) -> QLabel | None:
        """段承载控件。"""
        return self._labels.get(key)

    def labels(self) -> dict[str, QLabel]:
        return dict(self._labels)

    def set_text(self, key: str, text: str) -> None:
        """写段文本（文本未变则跳过，避免高频刷新触发重排）。"""
        label = self._labels.get(key)
        if label is not None and label.text() != text:
            label.setText(text)

    def text(self, key: str) -> str:
        label = self._labels.get(key)
        return label.text() if label is not None else ""

    def is_segment_visible(self, key: str) -> bool:
        return bool(self._visible.get(key, True))

    def set_segment_visible(self, key: str, visible: bool) -> None:
        """勾选/取消勾选 → 段承载控件显隐 + 立即持久化。"""
        if key not in self._labels:
            return
        visible = bool(visible)
        self._visible[key] = visible
        self._labels[key].setVisible(visible)
        self._save()

    # ------------------------------------------------------------------
    # 右键菜单（每次现场构建，随菜单销毁自动回收，无悬挂引用）
    # ------------------------------------------------------------------

    def build_menu(self) -> QMenu:
        """构建段勾选菜单：每注册段一个 checkable 项（文本双语）。"""
        menu = QMenu(self)
        for spec in self._specs.values():
            action = QAction(tr(spec.label_key), menu)
            action.setCheckable(True)
            action.setChecked(bool(self._visible[spec.key]))
            action.setData(spec.key)
            action.toggled.connect(
                lambda on, key=spec.key: self.set_segment_visible(key, on)
            )
            menu.addAction(action)
        return menu

    def popup(self, global_pos) -> None:
        """在全局坐标弹出勾选菜单（状态栏右键调用点）。"""
        self.build_menu().exec(global_pos)

    # ------------------------------------------------------------------
    # 持久化（读写模式对齐 main_window._save_view_index / _load_view_index）
    # ------------------------------------------------------------------

    def _save(self) -> None:
        if self._config_path is None:
            return
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._config_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {"segments": dict(self._visible)},
                    fh, ensure_ascii=False, indent=2,
                )
        except Exception:  # noqa: BLE001 — 段显隐配置写盘永不抛
            pass

    def _load(self) -> None:
        if self._config_path is None:
            return
        data = {}
        try:
            with open(self._config_path, encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict) and isinstance(raw.get("segments"), dict):
                data = raw["segments"]
        except Exception:  # noqa: BLE001 — 缺失/损坏 → 默认全显
            data = {}
        for key in self._specs:
            vis = data.get(key, True)
            if not isinstance(vis, bool):
                vis = True
            self._visible[key] = vis
            self._labels[key].setVisible(vis)
