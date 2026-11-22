# SPDX-License-Identifier: GPL-3.0-only
"""多轨测量结果表格界面（M3）：每文件一行展示测量读数，带测量/导出动作。"""

from __future__ import annotations

from acouscope.i18n import tr
from acouscope.ui.widgets.multitrack.measure_summary import (
    MEASUREMENT_COLUMNS,
    write_measurements_csv,
)

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

MEASURE_TAB_KEY = "multitrack.measure.tab"

# 表格展示列（MEASUREMENT_COLUMNS 的 8 列子集，顺序固定）
DISPLAY_COLUMNS = (
    "file",
    "duration_s",
    "sample_rate",
    "channels",
    "rms_db",
    "peak_db",
    "f0_median_hz",
    "status",
)

# 列名 → i18n 键映射
HEADER_KEYS: dict[str, str] = {
    col: f"multitrack.measure.col_{col}" for col in DISPLAY_COLUMNS
}


class MeasureTableWidget(QWidget):
    """测量结果表格：只读展示、两按钮（测量全部/导出 CSV）发信号。"""

    measureRequested = pyqtSignal()
    exportRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("multitrackMeasureTable")
        self._rows: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 顶部按钮栏
        btn_row = QHBoxLayout()
        self.btn_measure = QPushButton(tr("multitrack.measure.measure"))
        self.btn_measure.setObjectName("measureAllButton")
        self.btn_measure.clicked.connect(self.measureRequested)

        self.btn_export = QPushButton(tr("multitrack.measure.export"))
        self.btn_export.setObjectName("measureExportButton")
        self.btn_export.setText(tr("multitrack.measure.export"))
        self.btn_export.clicked.connect(self.exportRequested)

        btn_row.addWidget(self.btn_measure)
        btn_row.addWidget(self.btn_export)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        # 表格
        self.table = QTableWidget()
        self.table.setObjectName("measureResultTable")
        self.table.setColumnCount(len(DISPLAY_COLUMNS))
        self.table.setRowCount(0)
        self.table.verticalHeader().setVisible(False)
        self._set_headers()
        layout.addWidget(self.table, 1)

        # 空状态提示
        self.lbl_empty = QLabel(tr("multitrack.measure.empty"))
        self.lbl_empty.setObjectName("measureEmptyHint")
        layout.addWidget(self.lbl_empty)

        # 初始空态显示提示
        self.set_rows([])

    def _set_headers(self) -> None:
        """设置表头文本（i18n）。"""
        for i, col in enumerate(DISPLAY_COLUMNS):
            key = HEADER_KEYS[col]
            self.table.setHorizontalHeaderItem(i, QTableWidgetItem(tr(key)))

    def set_rows(self, rows: list[dict]) -> None:
        """填充表格行数据。rows 为空时显示空状态提示。"""
        self._rows = rows
        self.table.setRowCount(len(rows))
        self.lbl_empty.setHidden(bool(rows))
        for r, row in enumerate(rows):
            for c, col in enumerate(DISPLAY_COLUMNS):
                val = row.get(col)
                display_val = self._map_status_for_display(val, col)
                item = QTableWidgetItem(self._format_cell(display_val))
                flags = item.flags() & ~Qt.ItemFlag.ItemIsEditable
                item.setFlags(flags)
                self.table.setItem(r, c, item)

    @staticmethod
    def _map_status_for_display(val, col: str):
        """status 列表现层映射：measured/partial/missing → i18n 译文；未知值原样。"""
        if col != "status" or val is None:
            return val
        status_map = {
            "measured": tr("multitrack.measure.status_measured"),
            "partial": tr("multitrack.measure.status_partial"),
            "missing": tr("multitrack.measure.status_missing"),
        }
        return status_map.get(val, val)

    def rows(self) -> list[dict]:
        """返回当前行数据（同一对象引用）。"""
        return self._rows

    def export_csv(self, path: str) -> int:
        """导出当前行数据为 CSV，返回行数。"""
        return write_measurements_csv(path, self._rows)

    @staticmethod
    def _format_cell(val):
        """单元格显示格式：None→空串、float→3 位小数、其余 str()。"""
        if val is None:
            return ""
        if isinstance(val, float):
            return f"{val:.3f}"
        return str(val)
