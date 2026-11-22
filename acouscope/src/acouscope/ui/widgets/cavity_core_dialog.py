# SPDX-License-Identifier: GPL-3.0-only
"""腔核候选对话框（W-14-01 GUI 面；B5 九面之 3）。

**分层纪律**（同 ``batch_readout_dialog``／``paper_figure_dialog``）：

- 本对话框**只做参数传递、展示、导出**；候选一律来自
  :func:`acouscope.analysis.cavity_core_v2.core_candidates_from_audio`（GUI 与 CLI
  同一条路、同一组参数），**不重算、不改写**分析结果；
- 参数与 W-14-01 的 ``params`` **逐项对应**（``max_gap_s`` 必填显式；收缩阈值在本
  GUI 不开放，保持 ``not_applied``，与 CLI 缺省档同值）；
- 表格与导出 JSON **同源**：表里的每一个数都直接取 ``payload["candidates"]``。

口径纪律：只给候选，不给判定；空表 = 如实为空（不伪造行）。
"""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from acouscope.i18n import tr
from acouscope.ui import theme

__all__ = ["CavityCoreDialog", "CAVITY_CORE_COLUMNS", "SCL_FILTER"]

#: 导出过滤器（纯 ASCII，无 i18n 需求）
SCL_FILTER = "JSON (*.json);;All files (*)"

#: 表格列序 → candidate 字段名（导出／核对用；顺序即 UI 顺序）
CAVITY_CORE_COLUMNS = (
    ("w14.cavity_core.col_id", "candidate_id"),
    ("w14.cavity_core.col_range", "range"),
    ("w14.cavity_core.col_degree", "degree_index"),
    ("w14.cavity_core.col_deviation", "degree_deviation_cents"),
    ("w14.cavity_core.col_share", "frame_share"),
    ("w14.cavity_core.col_duration", "duration_s"),
    ("w14.cavity_core.col_ci95", "median_ci95_cents"),
)


def _fmt(value) -> str:
    """展示用格式化：None → 空串（禁 0 冒充缺值）；浮点三位。"""
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


class CavityCoreDialog(QDialog):
    """候选表（起讫/音级/偏离/帧占比/时长/CI）＋导出 JSON。

    用法::

        dlg = CavityCoreDialog(audio_path=..., template="qin_lu")
        dlg.compute()          # 调平台 API，结果存 dlg.payload
        dlg.exec()
    """

    def __init__(
        self,
        parent=None,
        *,
        audio_path=None,
        template: str = "12tet",
        window_start_s: float = 0.0,
        window_s: float = 30.0,
        max_gap_s: float = 0.30,
        recording_id: str = "",
    ):
        super().__init__(parent)
        self._audio_path = None if audio_path is None else str(audio_path)
        self._template = str(template)
        self._recording_id = str(recording_id)
        #: 最近一次计算/装填的候选表（GUI 与 CLI 同源）
        self.payload: dict | None = None
        self.last_error: str | None = None

        self.setWindowTitle(tr("w14.cavity_core.title"))
        t = theme.TOKENS
        self.setMinimumWidth(t["spacing"]["xl"] * 24)
        self.setMinimumHeight(t["spacing"]["xl"] * 14)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            t["spacing"]["md"], t["spacing"]["md"],
            t["spacing"]["md"], t["spacing"]["md"],
        )
        layout.setSpacing(t["spacing"]["sm"])

        form = QFormLayout()
        form.setSpacing(t["spacing"]["sm"])

        self.spin_max_gap = QDoubleSpinBox(self)
        self.spin_max_gap.setObjectName("cavityCoreMaxGapS")
        self.spin_max_gap.setDecimals(3)
        self.spin_max_gap.setRange(0.0, 5.0)
        self.spin_max_gap.setSingleStep(0.05)
        self.spin_max_gap.setValue(float(max_gap_s))
        self.spin_max_gap.setSuffix(" s")
        form.addRow(QLabel(tr("w14.cavity_core.max_gap")), self.spin_max_gap)

        self.spin_window = QDoubleSpinBox(self)
        self.spin_window.setObjectName("cavityCoreWindowS")
        self.spin_window.setDecimals(3)
        self.spin_window.setRange(1.0, 3600.0)
        self.spin_window.setValue(float(window_s))
        self.spin_window.setSuffix(" s")
        form.addRow(QLabel(tr("batch_readout.window_s")), self.spin_window)

        self._window_start_s = float(window_start_s)
        self.lbl_template = QLabel(self._template, self)
        self.lbl_template.setObjectName("cavityCoreTemplate")
        self.lbl_template.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow(QLabel(tr("batch_readout.template")), self.lbl_template)
        layout.addLayout(form)

        self.table = QTableWidget(0, len(CAVITY_CORE_COLUMNS), self)
        self.table.setObjectName("cavityCoreTable")
        self.table.setHorizontalHeaderLabels([tr(key) for key, _field in CAVITY_CORE_COLUMNS])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, stretch=2)

        self.lbl_summary = QLabel("", self)
        self.lbl_summary.setObjectName("cavityCoreSummary")
        self.lbl_summary.setWordWrap(True)
        layout.addWidget(self.lbl_summary)

        row = QHBoxLayout()
        self.btn_run = QPushButton(tr("w14.cavity_core.run"), self)
        self.btn_run.setObjectName("cavityCoreRunBtn")
        self.btn_run.clicked.connect(self._on_run)
        self.btn_export = QPushButton(tr("w14.cavity_core.export"), self)
        self.btn_export.setObjectName("cavityCoreExportBtn")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._on_export)
        self.btn_close = QPushButton(tr("w14.cavity_core.close"), self)
        self.btn_close.setObjectName("cavityCoreCloseBtn")
        self.btn_close.clicked.connect(self.reject)
        row.addWidget(self.btn_run)
        row.addWidget(self.btn_export)
        row.addStretch(1)
        row.addWidget(self.btn_close)
        layout.addLayout(row)

    # ------------------------------------------------------------------
    # 对外面（测试与调用侧同一口径）
    # ------------------------------------------------------------------

    def template_spec(self) -> str:
        """当前模板 spec（内置 key 或 ``.scl`` 路径）。"""
        return self._template

    def max_gap_s(self) -> float:
        """同音级成组最大间隔（显式参数，随 payload 登记）。"""
        return float(self.spin_max_gap.value())

    def window_s(self) -> float:
        return float(self.spin_window.value())

    def params(self) -> dict:
        """与 W-14-01 ``params`` 对齐的当前 GUI 参数面。"""
        return {
            "template": self._template,
            "window_start_s": self._window_start_s,
            "window_s": self.window_s(),
            "max_gap_s": self.max_gap_s(),
            "min_frame_share": None,
            "min_duration_s": None,
            "max_median_mad_cents": None,
        }

    def compute(self) -> dict:
        """调平台 API 计算候选（不在此重算任何口径）。"""
        from acouscope.analysis.cavity_core_v2 import core_candidates_from_audio

        if not self._audio_path:
            raise ValueError(tr("w14.cavity_core.need_case"))
        payload = core_candidates_from_audio(
            self._audio_path,
            template=self._template,
            window_start_s=self._window_start_s,
            window_s=self.window_s(),
            max_gap_s=self.max_gap_s(),
            recording_id=self._recording_id,
        )
        self.set_payload(payload)
        return payload

    def set_payload(self, payload: dict) -> None:
        """装填候选表（表格与 JSON 同源，逐值一致）。"""
        self.payload = payload
        rows = list(payload.get("candidates") or ())
        self.table.setRowCount(len(rows))
        for index, candidate in enumerate(rows):
            cells = {
                "candidate_id": candidate.get("candidate_id"),
                "range": f"{candidate.get('start_s'):.3f}–{candidate.get('end_s'):.3f}",
                "degree_index": candidate.get("degree_index"),
                "degree_deviation_cents": candidate.get("degree_deviation_cents"),
                "frame_share": candidate.get("frame_share"),
                "duration_s": candidate.get("duration_s"),
                "median_ci95_cents": candidate.get("median_ci95_cents"),
            }
            for column, (_key, field) in enumerate(CAVITY_CORE_COLUMNS):
                item = QTableWidgetItem(_fmt(cells.get(field)))
                item.setData(Qt.ItemDataRole.UserRole, field)
                self.table.setItem(index, column, item)
        self.btn_export.setEnabled(bool(self.payload))
        self.lbl_summary.setText(
            tr("w14.cavity_core.summary").format(
                n=len(rows),
                template=payload.get("template", ""),
                max_gap=payload.get("params", {}).get("max_gap_s", ""),
                filter=payload.get("filter_status", ""),
            )
            if rows
            else tr("w14.cavity_core.empty")
        )

    def table_rows(self) -> list[dict]:
        """表格内容 → 行字典（供「表与 JSON 逐值一致」的核对）。"""
        out: list[dict] = []
        for row in range(self.table.rowCount()):
            out.append(
                {
                    "candidate_id": self.table.item(row, 0).text(),
                    "range": self.table.item(row, 1).text(),
                    "degree_index": self.table.item(row, 2).text(),
                    "degree_deviation_cents": self.table.item(row, 3).text(),
                    "frame_share": self.table.item(row, 4).text(),
                    "duration_s": self.table.item(row, 5).text(),
                    "median_ci95_cents": self.table.item(row, 6).text(),
                }
            )
        return out

    def export_json(self, path) -> Path:
        """导出与表格同源的候选 JSON（写盘前要求已有 payload）。"""
        from acouscope.analysis.cavity_core_v2 import export_candidates_json

        if not self.payload:
            raise ValueError(tr("w14.cavity_core.empty"))
        return export_candidates_json(self.payload, path)

    # ------------------------------------------------------------------
    # 交互槽（不弹模态：错误交给调用方/状态行，便于测试）
    # ------------------------------------------------------------------

    def _on_run(self) -> None:
        try:
            self.compute()
            self.last_error = None
        except (ValueError, OSError, KeyError) as exc:
            self.last_error = str(exc)
            self.lbl_summary.setText(str(exc))

    def _on_export(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, tr("w14.cavity_core.export"), "cavity_core_candidates.json", SCL_FILTER
        )
        if not path:
            return
        try:
            self.export_json(path)
        except (ValueError, OSError) as exc:
            self.last_error = str(exc)
            self.lbl_summary.setText(str(exc))

    def payload_json_text(self) -> str:
        """当前 payload 的 JSON 文本（测试用；与导出件同内容）。"""
        return json.dumps(self.payload, ensure_ascii=False, indent=2, default=str)
