# SPDX-License-Identifier: GPL-3.0-only
"""律制推断对话框（W-14-08／B6；指挥追加的第 8 项能力）。

**分层纪律**（同 ``cavity_core_dialog``）：

- 推断只走 :func:`acouscope.analysis.tuning_infer_audio.infer_tuning_from_audio`
  （GUI 与 CLI 同一条路、同一组参数），本对话框**不重算、不改写**得分；
- 模板池来自 ``list_templates()``（**八项全列**，含 ``indian_22_shruti``／
  ``arabic_24_tone``）；「论文六模板」只是**预设子集**，不是唯一面；
- 文案纪律：只写「候选／排序／趋近」，**不写「符合某律／该曲属于某律」**。
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
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from acouscope.i18n import tr
from acouscope.ui import theme

__all__ = ["TuningInferenceDialog", "INFER_COLUMNS", "INFER_FILTER"]

#: 导出过滤器（纯 ASCII）
INFER_FILTER = "JSON (*.json);;All files (*)"

#: 结果表列序 → matches 字段
INFER_COLUMNS = (
    ("w14.infer.col_rank", "rank"),
    ("w14.infer.col_template", "template_name"),
    ("w14.infer.col_source", "template_source"),
    ("w14.infer.col_tonic", "tonic_cents"),
    ("w14.infer.col_score", "score"),
    ("w14.infer.col_margin", "margin"),
)


def _fmt(value) -> str:
    """展示用格式化：None → 空串；浮点三位。"""
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


class TuningInferenceDialog(QDialog):
    """律制候选排序（八模板可选／论文六模板预设／结果表＋导出）。"""

    def __init__(
        self,
        parent=None,
        *,
        audio_path=None,
        window_start_s: float = 0.0,
        window_s: float = 30.0,
        top_k: int = 3,
        recording_id: str = "",
    ):
        super().__init__(parent)
        self._audio_path = None if audio_path is None else str(audio_path)
        self._window_start_s = float(window_start_s)
        self._recording_id = str(recording_id)
        #: 最近一次推断结果（GUI 与 CLI 同源）
        self.payload: dict | None = None
        self.last_error: str | None = None

        self.setWindowTitle(tr("w14.infer.title"))
        t = theme.TOKENS
        self.setMinimumWidth(t["spacing"]["xl"] * 26)
        self.setMinimumHeight(t["spacing"]["xl"] * 18)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            t["spacing"]["md"], t["spacing"]["md"],
            t["spacing"]["md"], t["spacing"]["md"],
        )
        layout.setSpacing(t["spacing"]["sm"])

        form = QFormLayout()
        form.setSpacing(t["spacing"]["sm"])

        self.spin_window = QDoubleSpinBox(self)
        self.spin_window.setObjectName("tuningInferWindowS")
        self.spin_window.setDecimals(3)
        self.spin_window.setRange(1.0, 3600.0)
        self.spin_window.setValue(float(window_s))
        self.spin_window.setSuffix(" s")
        form.addRow(QLabel(tr("w14.infer.window")), self.spin_window)

        self.spin_top_k = QSpinBox(self)
        self.spin_top_k.setObjectName("tuningInferTopK")
        self.spin_top_k.setRange(1, 8)
        self.spin_top_k.setValue(int(top_k))
        form.addRow(QLabel(tr("w14.infer.top_k")), self.spin_top_k)
        layout.addLayout(form)

        # ---- 模板多选（八项全列，默认全选）----
        self.list_templates = QListWidget(self)
        self.list_templates.setObjectName("tuningInferTemplateList")
        self.list_templates.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self._fill_templates()
        layout.addWidget(QLabel(tr("w14.infer.col_template")), 0)
        layout.addWidget(self.list_templates, stretch=2)

        row_preset = QHBoxLayout()
        self.btn_paper = QPushButton(tr("w14.infer.preset_paper"), self)
        self.btn_paper.setObjectName("tuningInferPresetPaperBtn")
        self.btn_paper.clicked.connect(self.apply_paper_preset)
        self.btn_all = QPushButton(tr("w14.infer.preset_all"), self)
        self.btn_all.setObjectName("tuningInferPresetAllBtn")
        self.btn_all.clicked.connect(self.apply_all_preset)
        row_preset.addWidget(self.btn_paper)
        row_preset.addWidget(self.btn_all)
        row_preset.addStretch(1)
        layout.addLayout(row_preset)

        self.table = QTableWidget(0, len(INFER_COLUMNS), self)
        self.table.setObjectName("tuningInferTable")
        self.table.setHorizontalHeaderLabels([tr(key) for key, _field in INFER_COLUMNS])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for column in (0, 1, 3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, stretch=3)

        self.lbl_summary = QLabel("", self)
        self.lbl_summary.setObjectName("tuningInferSummary")
        self.lbl_summary.setWordWrap(True)
        layout.addWidget(self.lbl_summary)
        self.lbl_note = QLabel(tr("w14.infer.note"), self)
        self.lbl_note.setObjectName("tuningInferNote")
        self.lbl_note.setWordWrap(True)
        layout.addWidget(self.lbl_note)

        row = QHBoxLayout()
        self.btn_run = QPushButton(tr("w14.infer.run"), self)
        self.btn_run.setObjectName("tuningInferRunBtn")
        self.btn_run.clicked.connect(self._on_run)
        self.btn_export = QPushButton(tr("w14.infer.export"), self)
        self.btn_export.setObjectName("tuningInferExportBtn")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._on_export)
        self.btn_close = QPushButton(tr("w14.cavity_core.close"), self)
        self.btn_close.setObjectName("tuningInferCloseBtn")
        self.btn_close.clicked.connect(self.reject)
        row.addWidget(self.btn_run)
        row.addWidget(self.btn_export)
        row.addStretch(1)
        row.addWidget(self.btn_close)
        layout.addLayout(row)

    # ------------------------------------------------------------------
    # 模板池
    # ------------------------------------------------------------------

    def _fill_templates(self) -> None:
        """八项全列（内置模板表为唯一数据源；不在此写死名录）。"""
        from acouscope.analysis.tunings.templates import get_template, list_templates

        for key in list_templates():
            item = QListWidgetItem(key)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setToolTip(str(get_template(key).source))
            self.list_templates.addItem(item)

    def template_items(self) -> list[str]:
        """清单里的模板键（顺序即内置表顺序）。"""
        return [
            str(self.list_templates.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.list_templates.count())
        ]

    def checked_templates(self) -> list[str]:
        """已勾选的模板键（空 ⇒ 由调用方拦，不静默用全量）。"""
        return [
            str(self.list_templates.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.list_templates.count())
            if self.list_templates.item(index).checkState() == Qt.CheckState.Checked
        ]

    def _set_checked(self, keys) -> None:
        allowed = {str(key) for key in keys}
        for index in range(self.list_templates.count()):
            item = self.list_templates.item(index)
            key = str(item.data(Qt.ItemDataRole.UserRole))
            item.setCheckState(
                Qt.CheckState.Checked if key in allowed else Qt.CheckState.Unchecked
            )

    def apply_paper_preset(self) -> None:
        """预设：论文六模板（子集，不删任何模板）。"""
        from acouscope.analysis.tunings.templates import list_paper_templates

        self._set_checked(list_paper_templates())

    def apply_all_preset(self) -> None:
        """预设：全部八模板（含印度/阿拉伯）。"""
        from acouscope.analysis.tunings.templates import list_templates

        self._set_checked(list_templates())

    # ------------------------------------------------------------------
    # 计算／展示／导出
    # ------------------------------------------------------------------

    def window_s(self) -> float:
        return float(self.spin_window.value())

    def top_k(self) -> int:
        return int(self.spin_top_k.value())

    def compute(self) -> dict:
        """调平台 helper 推断（不在此重算得分）。"""
        from acouscope.analysis.tuning_infer_audio import infer_tuning_from_audio

        if not self._audio_path:
            raise ValueError(tr("w14.infer.need_case"))
        keys = self.checked_templates()
        if not keys:
            raise ValueError(tr("w14.infer.need_case"))
        payload = infer_tuning_from_audio(
            self._audio_path,
            window_start_s=self._window_start_s,
            window_s=self.window_s(),
            template_keys=keys,
            top_k=self.top_k(),
        )
        self.set_payload(payload)
        return payload

    def set_payload(self, payload: dict) -> None:
        """装填结果表（表与 JSON 同源，逐值一致）。"""
        self.payload = payload
        matches = list(payload.get("matches") or ())
        self.table.setRowCount(len(matches))
        for row, match in enumerate(matches):
            for column, (_key, field) in enumerate(INFER_COLUMNS):
                item = QTableWidgetItem(_fmt(match.get(field)))
                item.setData(Qt.ItemDataRole.UserRole, field)
                self.table.setItem(row, column, item)
            self.table.item(row, 2).setToolTip(str(match.get("template_source") or ""))
        self.btn_export.setEnabled(bool(self.payload))
        source = payload.get("source") or {}
        self.lbl_summary.setText(
            tr("w14.infer.summary").format(
                n=len(matches),
                frames=source.get("n_frames", 0),
                window=source.get("window_s", ""),
                templates=len(payload.get("template_pool") or ()),
            )
        )

    def table_rows(self) -> list[dict]:
        """表格内容 → 行字典（供「表与 JSON 逐值一致」核对）。"""
        out: list[dict] = []
        for row in range(self.table.rowCount()):
            out.append(
                {
                    field: self.table.item(row, column).text()
                    for column, (_key, field) in enumerate(INFER_COLUMNS)
                }
            )
        return out

    def export_json(self, path) -> Path:
        if not self.payload:
            raise ValueError(tr("w14.infer.need_case"))
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return target

    # ------------------------------------------------------------------
    # 交互槽（不弹模态错误；状态进摘要行）
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
            self, tr("w14.infer.export"), "tuning_inference.json", INFER_FILTER
        )
        if not path:
            return
        try:
            self.export_json(path)
        except (ValueError, OSError) as exc:
            self.last_error = str(exc)
            self.lbl_summary.setText(str(exc))
