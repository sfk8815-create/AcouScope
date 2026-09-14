# SPDX-License-Identifier: GPL-3.0-only
"""峰值标记内嵌面板（CB-002 F-3）：非模态 QWidget，列峰值并支持多选标记/取消。

UI 宪法条 3（对话框最小化）：本体为内嵌 QWidget，由频谱工具栏「标记面板」勾选
展开/收起，零 QDialog、零 .exec(。标记逻辑零重复——面板只发信号
（marksRequested / unmarkRequested），真正的增删落在 spectrum 既有
_add_peak_mark / _remove_mark / _find_marked_peak_near 上。
"""

from __future__ import annotations

import math

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from acouscope.ui import theme


class PeakMarksPanel(QWidget):
    """峰值列表面板：频率/音名/幅度/已标记态，多选标记与取消。"""

    marksRequested = pyqtSignal(list)    # 待标记峰值 dict 列表
    unmarkRequested = pyqtSignal(list)  # 待取消标记频率列表

    def __init__(self, parent=None):
        super().__init__(parent)
        self._peaks: list[dict] = []

        sp = theme.TOKENS["spacing"]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(sp["sm"], sp["sm"], sp["sm"], sp["sm"])
        layout.setSpacing(sp["sm"])

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["#", "频率 (Hz)", "音名", "幅度 (dB)", "已标记"]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.MultiSelection
        )
        hv = self.table.horizontalHeader()
        hv.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for c in range(1, 5):
            hv.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, stretch=1)

        btn_row = QHBoxLayout()
        self.btn_mark = QPushButton("标记选中")
        self.btn_unmark = QPushButton("取消标记")
        self.lbl_info = QLabel("")
        self.lbl_info.setStyleSheet(
            f"color: {theme.colors()['sub']}; font-size: 10px;"
        )
        btn_row.addWidget(self.btn_mark)
        btn_row.addWidget(self.btn_unmark)
        btn_row.addStretch(1)
        btn_row.addWidget(self.lbl_info)
        layout.addLayout(btn_row)

        self.btn_mark.clicked.connect(self._emit_mark)
        self.btn_unmark.clicked.connect(self._emit_unmark)

        # 主题令牌化：QSS 跟随主题（V099_TOKENS_V1）
        self._refresh_style = theme.style_when_theme(self, self._build_qss)

    @staticmethod
    def _build_qss(c: dict) -> str:
        return (
            "QPushButton{font-size:11px;padding:2px 8px;"
            f"color:{c['text']};border:1px solid {c['border']};"
            f"border-radius:3px;background:{c['btn']};}}"
            f"QPushButton:hover{{background:{c['btn_hover']};}}"
            f"QPushButton:pressed{{background:{c['accent']};color:{c['accent_text']};}}"
        )

    # ------------------------------------------------------------------
    # 数据接口
    # ------------------------------------------------------------------

    def set_peaks(self, peaks: list[dict]) -> None:
        """由 spectrum 注入最近一次检测结果，仅刷新显示。"""
        self._peaks = list(peaks)
        self.table.setRowCount(len(self._peaks))
        for i, p in enumerate(self._peaks):
            freq = float(p.get("freq", 0.0))
            note = str(p.get("note", ""))
            mag = float(p.get("magnitude", 0.0))
            db = 20.0 * math.log10(mag) if mag > 0 else -120.0
            self.table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.table.setItem(i, 1, QTableWidgetItem(f"{freq:.1f}"))
            self.table.setItem(i, 2, QTableWidgetItem(note))
            self.table.setItem(i, 3, QTableWidgetItem(f"{db:.1f}"))
            self.table.setItem(i, 4, QTableWidgetItem("—"))
        self.table.resizeRowsToContents()

    def set_mark_flags(self, flags) -> None:
        """更新「已标记」列（True=✓）。"""
        for i, marked in enumerate(flags):
            if 0 <= i < self.table.rowCount():
                self.table.setItem(
                    i, 4, QTableWidgetItem("✓" if marked else "—")
                )

    def selected_peaks(self) -> list[dict]:
        """当前选中行对应的峰值 dict 列表。"""
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        return [self._peaks[r] for r in rows if 0 <= r < len(self._peaks)]

    def set_info(self, text: str) -> None:
        self.lbl_info.setText(text)

    # ------------------------------------------------------------------
    # 信号
    # ------------------------------------------------------------------

    def _emit_mark(self):
        sel = self.selected_peaks()
        if sel:
            self.marksRequested.emit(sel)

    def _emit_unmark(self):
        sel = self.selected_peaks()
        if sel:
            self.unmarkRequested.emit([p.get("freq") for p in sel])
