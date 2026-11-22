# SPDX-License-Identifier: GPL-3.0-only
"""批量读数运行对话框（任务件-20261026 · GUI 化）。

**分层纪律**（同 ``paper_figure_dialog``，本模块只接线不造轮子）：

- 本对话框**只采集参数**并返回纯 dict 的 ``spec``；跑批、落盘、出图全在
  :mod:`acouscope.analysis.readout` 里面（GUI 与脚本共用同一条路）；
- 计算在 worker 线程跑（``MainWindow`` 投递到 ``TaskCenter``），这里**不阻塞**；
- 所有界面文字走 :func:`acouscope.i18n.tr`，对象名稳定（``batchReadout*``）供测试。

**取数参数一律显式登记**（窗长／重叠／τ 档位等）：换任一参数即换数，故不予
「高级选项」折叠隐藏，也不给平台默认值以外的隐式兜底。

**锚值来自调用方**：锚偏移留空即 ``None``（未提供），平台不猜（与 paper_C 同一口径）。
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from acouscope.i18n import tr
from acouscope.ui import theme

#: τ 扫描档位默认文本（第一档 none = 平台未标定、按符号判）
DEFAULT_TAU_TEXT = "none,10,20,30"

#: 音频过滤器（用于多选打开对话框）
AUDIO_FILTER = "Audio (*.wav *.flac *.ogg *.mp3 *.m4a);;All files (*)"

#: 模板下拉里「自定义 .scl」项的 data 标记（不是合法模板 spec，仅 UI 用）
CUSTOM_ITEM = "__custom__"

__all__ = ["DEFAULT_TAU_TEXT", "AUDIO_FILTER", "CUSTOM_ITEM", "BatchReadoutDialog"]


def _unique_id(stem: str, used: set[str]) -> str:
    """由文件名生成不重复的 recording_id（同名文件加序号后缀）。"""
    base = stem or "rec"
    candidate, index = base, 1
    while candidate in used:
        index += 1
        candidate = f"{base}_{index}"
    used.add(candidate)
    return candidate


class BatchReadoutDialog(QDialog):
    """批量读数运行：多选录音 → 填锚与取数参数 → 产出纯 dict 的 ``spec``。

    用法::

        dlg = BatchReadoutDialog(parent=self)
        if dlg.exec():
            spec = dlg.spec()          # 交给 TaskCenter 投递，不在本线程跑

    :meth:`spec` 是唯一对外数据出口；校验失败时 :meth:`validate` 返回错误文本
    （调用侧负责提示，对话框自身不弹 MessageBox —— 便于测试）。
    """

    # 表格列序（列标题为 i18n 文案，索引稳定）
    COL_PATH, COL_LABEL, COL_ANCHOR, COL_SOURCE = range(4)

    # 附加数据角色：文件列并存「全路径」与「读取自清单的 recording_id」
    _ROLE_PATH = Qt.ItemDataRole.UserRole
    _ROLE_ID = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("batch_readout.title"))
        t = theme.TOKENS
        self.setMinimumWidth(t["spacing"]["xl"] * 22)
        self.setMinimumHeight(t["spacing"]["xl"] * 16)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            t["spacing"]["md"], t["spacing"]["md"],
            t["spacing"]["md"], t["spacing"]["md"],
        )
        layout.setSpacing(t["spacing"]["sm"])

        # ----- 录音清单 -----
        layout.addWidget(QLabel(tr("batch_readout.cases")))
        self.table = QTableWidget(0, 4, self)
        self.table.setObjectName("batchReadoutTable")
        self.table.setHorizontalHeaderLabels([
            tr("batch_readout.col_file"),
            tr("batch_readout.col_label"),
            tr("batch_readout.col_anchor"),
            tr("batch_readout.col_source"),
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(self.COL_PATH, QHeaderView.ResizeMode.Stretch)
        for col in (self.COL_LABEL, self.COL_ANCHOR, self.COL_SOURCE):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table, stretch=2)

        row_cases = QHBoxLayout()
        self.btn_add = QPushButton(tr("batch_readout.add"))
        self.btn_add.setObjectName("batchReadoutAdd")
        self.btn_add.clicked.connect(self._on_add)
        self.btn_remove = QPushButton(tr("batch_readout.remove"))
        self.btn_remove.setObjectName("batchReadoutRemove")
        self.btn_remove.clicked.connect(self._on_remove)
        row_cases.addWidget(self.btn_add)
        row_cases.addWidget(self.btn_remove)
        self.btn_load = QPushButton(tr("batch_readout.load_json"))
        self.btn_load.setObjectName("batchReadoutLoadJson")
        self.btn_load.setToolTip(tr("batch_readout.load_json_tip"))
        self.btn_load.clicked.connect(self._on_load_json)
        row_cases.addWidget(self.btn_load)
        row_cases.addStretch(1)
        layout.addLayout(row_cases)

        # ----- 输出 -----
        form_out = QFormLayout()
        form_out.setSpacing(t["spacing"]["sm"])

        self.edit_dir = QLineEdit(self)
        self.edit_dir.setObjectName("batchReadoutOutputDir")
        self.edit_dir.setReadOnly(True)
        row_dir = QHBoxLayout()
        row_dir.addWidget(self.edit_dir, stretch=1)
        self.btn_browse_dir = QPushButton(tr("batch_readout.browse"))
        self.btn_browse_dir.setObjectName("batchReadoutBrowseDir")
        self.btn_browse_dir.clicked.connect(self._on_browse_dir)
        row_dir.addWidget(self.btn_browse_dir)
        form_out.addRow(QLabel(tr("batch_readout.output_dir")), row_dir)

        self.chk_figure = QCheckBox(tr("batch_readout.figure_out"))
        self.chk_figure.setObjectName("batchReadoutFigureEnabled")
        self.chk_figure.setChecked(True)
        self.chk_figure.toggled.connect(self._refresh_state)
        form_out.addRow(self.chk_figure)

        self.edit_figure_dir = QLineEdit(self)
        self.edit_figure_dir.setObjectName("batchReadoutFigureDir")
        self.edit_figure_dir.setReadOnly(True)
        row_fig = QHBoxLayout()
        row_fig.addWidget(self.edit_figure_dir, stretch=1)
        self.btn_browse_figure = QPushButton(tr("batch_readout.browse"))
        self.btn_browse_figure.setObjectName("batchReadoutBrowseFigure")
        self.btn_browse_figure.clicked.connect(self._on_browse_figure)
        row_fig.addWidget(self.btn_browse_figure)
        form_out.addRow(QLabel(tr("batch_readout.figure_dir")), row_fig)
        layout.addLayout(form_out)

        # ----- 取数参数（换任一即换数，故显式登记）-----
        box = QGroupBox(tr("batch_readout.params_group"), self)
        box.setObjectName("batchReadoutParams")
        params = QFormLayout(box)
        params.setSpacing(t["spacing"]["sm"])

        self.spin_window = self._spin(5.0, 3600.0, 30.0, 1.0, "batchReadoutWindowS", " s")
        params.addRow(QLabel(tr("batch_readout.window_s")), self.spin_window)

        self.spin_min_window = self._spin(0.0, 3600.0, 5.0, 0.5, "batchReadoutMinWindowS", " s")
        params.addRow(QLabel(tr("batch_readout.min_window_s")), self.spin_min_window)

        self.spin_fmin = self._spin(10.0, 4000.0, 60.0, 5.0, "batchReadoutFmin", " Hz")
        params.addRow(QLabel(tr("batch_readout.fmin")), self.spin_fmin)

        self.spin_fmax = self._spin(100.0, 20000.0, 1500.0, 50.0, "batchReadoutFmax", " Hz")
        params.addRow(QLabel(tr("batch_readout.fmax")), self.spin_fmax)

        self.spin_tonic = self._spin(1.0, 3600.0, 30.0, 1.0, "batchReadoutTonicWindowS", " s")
        params.addRow(QLabel(tr("batch_readout.tonic_window_s")), self.spin_tonic)

        self.spin_overlap = self._spin(0.0, 1.0, 0.5, 0.05, "batchReadoutOverlap", "")
        params.addRow(QLabel(tr("batch_readout.overlap_ratio")), self.spin_overlap)

        self.spin_smooth = QSpinBox(self)
        self.spin_smooth.setObjectName("batchReadoutSmoothK")
        self.spin_smooth.setRange(1, 99)
        self.spin_smooth.setValue(5)
        params.addRow(QLabel(tr("batch_readout.smooth_k")), self.spin_smooth)

        self.spin_min_thr = self._spin(0.0, 100.0, 10.0, 1.0, "batchReadoutMinThr", "")
        params.addRow(QLabel(tr("batch_readout.min_thr")), self.spin_min_thr)

        self.edit_taus = QLineEdit(DEFAULT_TAU_TEXT, self)
        self.edit_taus.setObjectName("batchReadoutTaus")
        params.addRow(QLabel(tr("batch_readout.taus")), self.edit_taus)

        # 主分析 τ 的**运行口径声明**（与扫描档分离；留空 ⇒ 只出按符号判对照档）
        self.edit_tau_analysis = QLineEdit("", self)
        self.edit_tau_analysis.setObjectName("batchReadoutTauAnalysis")
        self.edit_tau_analysis.setPlaceholderText(tr("batch_readout.tau_analysis_hint"))
        params.addRow(QLabel(tr("batch_readout.tau_analysis")), self.edit_tau_analysis)

        self.cmb_segmenter = QComboBox(self)
        self.cmb_segmenter.setObjectName("batchReadoutSegmenter")
        for value, name in (("hmm", "batch_readout.seg_hmm"),
                            ("simple", "batch_readout.seg_simple")):
            self.cmb_segmenter.addItem(tr(name, value), value)
        params.addRow(QLabel(tr("batch_readout.segmenter")), self.cmb_segmenter)

        self.cmb_template = QComboBox(self)
        self.cmb_template.setObjectName("batchReadoutTemplate")
        params.addRow(QLabel(tr("batch_readout.template")), self.cmb_template)

        # W-14-01 GUI 面 3 的成组参数：**显式**给值，随候选 params 原样登记
        self.spin_max_gap = self._spin(0.0, 5.0, 0.30, 0.05, "batchReadoutMaxGapS", " s")
        params.addRow(QLabel(tr("w14.cavity_core.max_gap")), self.spin_max_gap)

        # W-14-05 GUI 面 5：模板名称／来源／指纹（与 run_descriptor 同一函数取数）
        # 超长来源（URL）+ 64 位指纹只单行省略，全文进 tooltip；禁无限换行把
        # 下方「另存为 .scl／腔核候选／律制推断」按钮行挤出可视区。
        from PyQt6.QtWidgets import QSizePolicy
        from acouscope.ui.widgets.statusbar_segments import ElidedLabel

        self.lbl_template_info = ElidedLabel("", self)
        self.lbl_template_info.setObjectName("batchReadoutTemplateInfo")
        self.lbl_template_info.setWordWrap(False)
        self.lbl_template_info.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self.lbl_template_info.setMinimumWidth(0)
        self.lbl_template_info.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        params.addRow(QLabel(tr("w14.template.info_label")), self.lbl_template_info)

        row_scl = QHBoxLayout()
        self.btn_save_scl = QPushButton(tr("w14.template.save_scl"), self)
        self.btn_save_scl.setObjectName("batchReadoutSaveSclBtn")
        self.btn_save_scl.clicked.connect(self._on_save_scl)
        row_scl.addWidget(self.btn_save_scl)
        self.btn_cavity = QPushButton(tr("w14.cavity_core.button"), self)
        self.btn_cavity.setObjectName("batchReadoutCavityCoreBtn")
        self.btn_cavity.setEnabled(False)
        self.btn_cavity.clicked.connect(self._on_cavity_core)
        row_scl.addWidget(self.btn_cavity)
        # W-14-08（B6）：律制推断入口（同样随选中行启用；不改 main_window）
        self.btn_tuning_infer = QPushButton(tr("w14.infer.button"), self)
        self.btn_tuning_infer.setObjectName("batchReadoutTuningInferBtn")
        self.btn_tuning_infer.setEnabled(False)
        self.btn_tuning_infer.clicked.connect(self._on_tuning_infer)
        row_scl.addWidget(self.btn_tuning_infer)
        self.btn_manage_templates = QPushButton(tr("tuning.user.manage"), self)
        self.btn_manage_templates.setObjectName("batchReadoutManageTemplatesBtn")
        self.btn_manage_templates.clicked.connect(self._on_manage_templates)
        row_scl.addWidget(self.btn_manage_templates)
        row_scl.addStretch(1)
        params.addRow(row_scl)

        row_modes = QHBoxLayout()
        self.chk_absolute = QCheckBox(tr("batch_readout.ref_absolute"))
        self.chk_absolute.setObjectName("batchReadoutRefAbsolute")
        self.chk_absolute.setChecked(True)
        self.chk_main_tone = QCheckBox(tr("batch_readout.ref_main_tone"))
        self.chk_main_tone.setObjectName("batchReadoutRefMainTone")
        self.chk_main_tone.setChecked(True)
        row_modes.addWidget(self.chk_absolute)
        row_modes.addWidget(self.chk_main_tone)
        row_modes.addStretch(1)
        params.addRow(row_modes)
        layout.addWidget(box)

        #: 最近一次打开的腔核候选对话框（测试与接线复核用；未开过 ⇒ None）
        self.last_cavity_dialog = None
        #: 最近一次打开的律制推断对话框（同上）
        self.last_infer_dialog = None
        self._fill_templates()
        self._refresh_state()

        # ----- 按钮行 -----
        row_btns = QHBoxLayout()
        row_btns.addStretch(1)
        self.btn_cancel = QPushButton(tr("batch_readout.cancel"))
        self.btn_cancel.setObjectName("batchReadoutCancelBtn")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_run = QPushButton(tr("batch_readout.run"))
        self.btn_run.setObjectName("batchReadoutRunBtn")
        self.btn_run.setDefault(True)
        self.btn_run.clicked.connect(self._on_run)
        row_btns.addWidget(self.btn_cancel)
        row_btns.addWidget(self.btn_run)
        layout.addLayout(row_btns)

    # ------------------------------------------------------------------
    # 小工具
    # ------------------------------------------------------------------

    @staticmethod
    def _spin(low: float, high: float, value: float, step: float,
              object_name: str, suffix: str) -> QDoubleSpinBox:
        """带单位后缀的数值输入构造（统一 decimals=3）。"""
        spin = QDoubleSpinBox()
        spin.setObjectName(object_name)
        spin.setDecimals(3)
        spin.setRange(low, high)
        spin.setSingleStep(step)
        spin.setValue(value)
        if suffix:
            spin.setSuffix(suffix)
        return spin

    def _fill_templates(self) -> None:
        """律制模板下拉：读 platform ``list_templates()``（对话框不内置名录）。

        W-14-06：末尾追加「自定义 (.scl)…」项（选中即弹文件选择，**不是**死按钮）；
        内置八项照旧全列（印度／阿拉伯模板不得从下拉里消失）。
        P3：用户自定义模板项插于 CUSTOM_ITEM 之前（仅当库非空）。
        """
        # P3：幂等断连 + 清空重建，使刷新可重复调用
        try:
            self.cmb_template.currentIndexChanged.disconnect(self._on_template_changed)
        except (TypeError, RuntimeError):
            pass
        self.cmb_template.clear()
        #: 已绑定的自定义音阶路径（空 = 未绑定）
        self._custom_scl_path = ""
        try:
            from acouscope.analysis.tunings.templates import list_templates

            names = list(list_templates())
        except Exception:  # noqa: BLE001 — 模板不可得不阻断对话框
            names = ["12tet"]
        for name in names:
            self.cmb_template.addItem(str(name), str(name))
        # P3：用户自定义模板（仅当库非空时出现）
        from acouscope.analysis.tunings import user_templates as _ut

        user_items = _ut.list_user_templates()
        if user_items:
            self.cmb_template.insertSeparator(self.cmb_template.count())
            for entry in user_items:
                self.cmb_template.addItem(entry["name"], entry["spec"])
        self.cmb_template.addItem(tr("w14.template.custom_item"), CUSTOM_ITEM)
        index = self.cmb_template.findData("12tet")
        if index >= 0:
            self.cmb_template.setCurrentIndex(index)
        self.cmb_template.currentIndexChanged.connect(self._on_template_changed)
        self._refresh_template_info()

    def template_spec(self) -> str:
        """当前模板 spec：内置 key，或已绑定的 ``.scl`` 路径（未绑定 ⇒ 空串）。"""
        data = str(self.cmb_template.currentData() or "")
        if data == CUSTOM_ITEM:
            return str(self._custom_scl_path or "")
        return data

    def _on_manage_templates(self) -> None:
        """打开自定义律制模板编辑器；关闭后刷新下拉。"""
        from acouscope.ui.widgets.tuning_template_editor import TuningTemplateEditorDialog

        dlg = TuningTemplateEditorDialog(self)
        dlg.exec()
        self.refresh_user_templates()

    def refresh_user_templates(self) -> None:
        """编辑器关闭后刷新下拉：重填模板并恢复原选择（幂等，不重复弹框）。

        恢复选择全程抑制信号：若原选择是外部 ``.scl``（CUSTOM_ITEM），
        ``setCurrentIndex`` 会触发 ``_on_template_changed`` 再次弹出文件框。
        """
        current = self.template_spec()
        self.cmb_template.blockSignals(True)
        try:
            self._fill_templates()
            idx = self.cmb_template.findData(current)
            if idx >= 0:
                self.cmb_template.setCurrentIndex(idx)
            elif current and not current.startswith("custom:") and current != CUSTOM_ITEM:
                # 裸 .scl 路径：若无法找到对应项，选 CUSTOM_ITEM 并保留路径
                self._custom_scl_path = current
                idx = self.cmb_template.findData(CUSTOM_ITEM)
                if idx >= 0:
                    self.cmb_template.setCurrentIndex(idx)
            else:
                # 回退到 12tet
                idx = self.cmb_template.findData("12tet")
                if idx >= 0:
                    self.cmb_template.setCurrentIndex(idx)
        finally:
            self.cmb_template.blockSignals(False)
        self._refresh_template_info()

    def _on_template_changed(self, *_args) -> None:
        """选中「自定义 (.scl)…」⇒ 弹文件选择；取消 ⇒ 回退到上一个可用项。"""
        data = str(self.cmb_template.currentData() or "")
        if data != CUSTOM_ITEM:
            self._refresh_template_info()
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, tr("w14.template.custom_item"), "", tr("w14.template.custom_filter")
        )
        if not path:
            index = self.cmb_template.findData("12tet")
            self.cmb_template.blockSignals(True)
            self.cmb_template.setCurrentIndex(index if index >= 0 else 0)
            self.cmb_template.blockSignals(False)
            self._refresh_template_info()
            return
        self.bind_custom_scl(path)

    def bind_custom_scl(self, path) -> None:
        """绑定自定义 ``.scl``（测试与批处理可绕过文件对话框）；坏文件显式报错。"""
        from acouscope.analysis.tunings.templates import get_tuning

        spec = str(path)
        try:
            get_tuning(spec)  # 解析即校验：坏 .scl 在此报错，**不静默回退 12TET**
        except (ValueError, OSError, KeyError) as exc:
            self._custom_scl_path = ""
            self.lbl_template_info.setText(
                tr("w14.template.custom_failed").format(error=exc)
            )
            raise
        self._custom_scl_path = spec
        index = self.cmb_template.findData(CUSTOM_ITEM)
        if index >= 0:
            self.cmb_template.blockSignals(True)
            self.cmb_template.setCurrentIndex(index)
            self.cmb_template.blockSignals(False)
        self._refresh_template_info()

    def template_info(self) -> dict:
        """当前模板的记录块（W-14-05 五字段；与 ``run_descriptor`` 同源函数）。"""
        from acouscope.analysis.readout import template_record

        spec = self.template_spec()
        if not spec:
            return {}
        return template_record(spec)

    def _refresh_template_info(self) -> None:
        """模板名称／来源／指纹行（换模板即刷新；坏 spec 显示错误文本）。"""
        block = self.template_info()
        if not block:
            info = tr("w14.template.info_label")
        else:
            info = tr("w14.template.info").format(
                name=block.get("template_name", ""),
                source=block.get("template_source", ""),
                fingerprint=block.get("template_fingerprint", ""),
            )
        self._set_template_info_text(info)

    def _set_template_info_text(self, info: str) -> None:
        """单行省略显示 + tooltip 全文（超长 URL／指纹不再撑高表单）。"""
        self.lbl_template_info.setText(info)
        self.lbl_template_info.setToolTip(info)

    def set_template_info(self, name: str = "", source: str = "",
                          fingerprint: str = "") -> None:
        """显式注入模板信息（离线断言/外部取数用；与自动刷新同一渲染口径）。"""
        self._set_template_info_text(
            tr("w14.template.info").format(
                name=name, source=source, fingerprint=fingerprint
            )
        )

    # ------------------------------------------------------------------
    # 对外读取面（测试与调用侧复用同一口径）
    # ------------------------------------------------------------------

    def _row_text(self, row: int, col: int) -> str:
        item = self.table.item(row, col)
        return "" if item is None else item.text().strip()

    def cases(self) -> list[dict]:
        """表格 → cases 列表（``recording_id`` 由文件名生成且去重）。"""
        used: set[str] = set()
        rows: list[dict] = []
        for row in range(self.table.rowCount()):
            path = self._cell_data(row, self.COL_PATH)
            if not path:
                continue
            anchor = self._row_text(row, self.COL_ANCHOR)
            try:
                anchor_value = float(anchor) if anchor else None
            except ValueError:
                anchor_value = None
            item = self.table.item(row, self.COL_PATH)
            preset_id = ""
            if item is not None:
                preset_id = str(item.data(self._ROLE_ID) or "")
            rows.append(
                {
                    # 载入清单时沿用清单里的 recording_id ⇒ 与 CLI 跑出同一 run_id
                    "recording_id": preset_id or _unique_id(Path(path).stem, used),
                    "audio_path": path,
                    "label": self._row_text(row, self.COL_LABEL) or None,
                    "anchor_offset_cents": anchor_value,
                    "anchor_source": self._row_text(row, self.COL_SOURCE),
                }
            )
        return rows

    def _cell_data(self, row: int, col: int) -> str:
        item = self.table.item(row, col)
        if item is None:
            return ""
        return str(item.data(self._ROLE_PATH) or "")

    def ref_modes(self) -> list[str]:
        """勾选的口径（至少须留一个，由 :meth:`validate` 拦)。"""
        modes = []
        if self.chk_absolute.isChecked():
            modes.append("absolute")
        if self.chk_main_tone.isChecked():
            modes.append("main_tone")
        return modes

    def spec(self) -> dict:
        """纯 dict 运行契约（可直接喂 :func:`analysis.readout.run_batch_from_spec`）。"""
        figure_dir = self.edit_figure_dir.text().strip()
        return {
            "cases": self.cases(),
            "out_dir": self.edit_dir.text().strip(),
            "figure_out": figure_dir if self.chk_figure.isChecked() and figure_dir else None,
            "figure_stem": "figure_b",
            "tau_values": self._tau_values(),
            "tau_analysis": self.tau_analysis(),
            "tau_provenance": (
                "gui:batch_readout.tau_analysis"
                if self.tau_analysis() is not None
                else ""
            ),
            "ref_modes": self.ref_modes(),
            "params": {
                "window_s": float(self.spin_window.value()),
                "min_window_s": float(self.spin_min_window.value()),
                "fmin": float(self.spin_fmin.value()),
                "fmax": float(self.spin_fmax.value()),
                "segmenter": str(self.cmb_segmenter.currentData()),
                # W-14-06：内置 key 或 .scl 路径（同一字段；空 ⇒ 由 validate 拦）
                "template": self.template_spec(),
                "overlap_ratio": float(self.spin_overlap.value()),
                "smooth_k": int(self.spin_smooth.value()),
                "min_thr": float(self.spin_min_thr.value()),
                "tonic_window_s": float(self.spin_tonic.value()),
            },
        }

    def _tau_values(self) -> list[float | None]:
        """τ 档位文本 → 列表；解析失败返回空 T 面（由 validate 拦）前原样给回。"""
        try:
            from acouscope.analysis.readout import parse_tau_values

            return parse_tau_values(self.edit_taus.text())
        except Exception:  # noqa: BLE001 — 非法文本交由 validate 统一报错
            return []

    def tau_analysis(self) -> float | None:
        """主分析 τ 的运行口径声明 → 浮点；留空 = ``None``（只出对照档）。"""
        raw = self.edit_tau_analysis.text().strip()
        if not raw:
            return None
        return float(raw)

    def validate(self) -> str | None:
        """校验：返回**面向用户的错误文本**；``None`` = 通过。"""
        if not self.cases():
            return tr("batch_readout.err_no_case")
        if not self.template_spec():
            # 选了「自定义 (.scl)…」却没绑定文件 ⇒ 明确报错（禁回退 12TET）
            return tr("w14.template.custom_failed").format(
                error=tr("w14.template.custom_item")
            )
        if not self.edit_dir.text().strip():
            return tr("batch_readout.err_no_dir")
        if self.chk_figure.isChecked() and not self.edit_figure_dir.text().strip():
            return tr("batch_readout.err_no_figure_dir")
        if not self.ref_modes():
            return tr("batch_readout.err_no_mode")
        try:
            values = self._tau_values()
        except Exception:  # noqa: BLE001
            values = None
        if values is None or not values:
            return tr("batch_readout.err_bad_taus")
        raw_tau_analysis = self.edit_tau_analysis.text().strip()
        if raw_tau_analysis:
            try:
                if float(raw_tau_analysis) <= 0:
                    return tr("batch_readout.err_bad_tau_analysis")
            except ValueError:
                return tr("batch_readout.err_bad_tau_analysis")
        return None

    # ------------------------------------------------------------------
    # 交互槽
    # ------------------------------------------------------------------

    def _refresh_state(self, *_args) -> None:
        """图件目录随勾选启用/禁用；腔核候选按钮随选中行启用/禁用（无死按钮）。"""
        enabled = self.chk_figure.isChecked()
        self.edit_figure_dir.setEnabled(enabled)
        self.btn_browse_figure.setEnabled(enabled)
        has_case = bool(self.selected_case_path())
        if hasattr(self, "btn_cavity"):
            self.btn_cavity.setEnabled(has_case)
        if hasattr(self, "btn_tuning_infer"):
            self.btn_tuning_infer.setEnabled(has_case)

    def _on_selection_changed(self) -> None:
        self._refresh_state()

    def selected_case_path(self) -> str:
        """当前选中行（第一列有全路径者）的音频路径；未选中 ⇒ 空串。"""
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        if not rows:
            return ""
        return self._cell_data(rows[0], self.COL_PATH)

    def _on_save_scl(self) -> None:
        """把当前模板写成 ``.scl``（内置模板可导出、自定义可另存）。"""
        from acouscope.analysis.tunings.scl import save_scl
        from acouscope.analysis.tunings.templates import get_tuning

        spec = self.template_spec()
        if not spec:
            self.lbl_template_info.setText(
                tr("w14.template.custom_failed").format(error=tr("w14.template.custom_item"))
            )
            return
        path, _filter = QFileDialog.getSaveFileName(
            self, tr("w14.template.save_scl"), "custom.scl", tr("w14.template.custom_filter")
        )
        if not path:
            return
        try:
            save_scl(get_tuning(spec), path)
        except (ValueError, OSError, KeyError) as exc:
            self.lbl_template_info.setText(
                tr("w14.template.custom_failed").format(error=exc)
            )
            return
        self.lbl_template_info.setText(tr("w14.template.save_scl_done").format(path=path))

    def _on_cavity_core(self) -> None:
        """打开腔核候选对话框（作用于当前选中案例＋当前模板＋当前窗）。"""
        path = self.selected_case_path()
        if not path:
            self.lbl_template_info.setText(tr("w14.cavity_core.need_case"))
            return
        from acouscope.ui.widgets.cavity_core_dialog import CavityCoreDialog

        dialog = CavityCoreDialog(
            self,
            audio_path=path,
            template=self.template_spec(),
            window_s=float(self.spin_window.value()),
            max_gap_s=float(self.spin_max_gap.value()),
            recording_id=Path(path).stem,
        )
        dialog.setObjectName("batchCavityCoreDialog")
        self.last_cavity_dialog = dialog
        dialog.exec()

    def _on_tuning_infer(self) -> None:
        """打开律制推断对话框（作用于当前选中案例；无选中不可点）。"""
        path = self.selected_case_path()
        if not path:
            self.lbl_template_info.setText(tr("w14.infer.need_case"))
            return
        from acouscope.ui.widgets.tuning_inference_dialog import TuningInferenceDialog

        dialog = TuningInferenceDialog(
            self,
            audio_path=path,
            window_s=float(self.spin_window.value()),
            recording_id=Path(path).stem,
        )
        dialog.setObjectName("batchTuningInferDialog")
        self.last_infer_dialog = dialog
        dialog.exec()

    def _on_browse_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, tr("batch_readout.output_dir"), self.edit_dir.text().strip()
        )
        if path:
            self.edit_dir.setText(path)
            if not self.edit_figure_dir.text().strip():
                self.edit_figure_dir.setText(path)  # 图件默认随读数件同目录

    def _on_browse_figure(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, tr("batch_readout.figure_dir"), self.edit_figure_dir.text().strip()
        )
        if path:
            self.edit_figure_dir.setText(path)

    def _on_add(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(
            self, tr("batch_readout.add_title"), "", AUDIO_FILTER
        )
        for path in paths:
            self._append_row(path)

    def _append_row(self, path: str, recording_id: str = "") -> None:
        """追加一行（文件列存全路径与 recording_id 于 UserRole、显示文件名）。"""
        if any(self._cell_data(r, self.COL_PATH) == path
               for r in range(self.table.rowCount())):
            return  # 同一路径不重复添加
        row = self.table.rowCount()
        self.table.insertRow(row)
        item = QTableWidgetItem(Path(path).name)
        item.setData(self._ROLE_PATH, path)
        if recording_id:
            item.setData(self._ROLE_ID, recording_id)
        item.setToolTip(path)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, self.COL_PATH, item)
        self.table.setItem(row, self.COL_LABEL, QTableWidgetItem(""))
        self.table.setItem(row, self.COL_ANCHOR, QTableWidgetItem(""))
        self.table.setItem(row, self.COL_SOURCE, QTableWidgetItem(""))

    def _on_load_json(self) -> None:
        """载入 ``cases.json``：沿用其 recording_id，使 GUI 与 CLI 跑出同一 run_id。"""
        path, _filter = QFileDialog.getOpenFileName(
            self, tr("batch_readout.load_title"), "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            self.load_cases_json(path)
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.warning(self, tr("batch_readout.title"), str(exc))

    def load_cases_json(self, path) -> int:
        """按清单 JSON 装填（返回装填条数）；清单格式与 CLI 的 ``--cases`` 同一份。

        **为什么有这条路**：``run_id`` 是内容定址的，输入清单（含 recording_id）
        进了哈希面。GUI 若只按文件名生成标识，与 CLI 跑出的 run_id 会不同 —— 载入
        同一份清单即可让两条路**逐位复现同一个 run_id**。
        """
        from acouscope.analysis.readout import cases_from_json

        cases = cases_from_json(path)
        for case in cases:
            self._append_row(str(case.audio_path), str(case.recording_id))
            row = self.table.rowCount() - 1
            self.table.item(row, self.COL_LABEL).setText(
                "" if case.label is None else str(case.label)
            )
            self.table.item(row, self.COL_ANCHOR).setText(
                "" if case.anchor_offset_cents is None else f"{case.anchor_offset_cents:g}"
            )
            self.table.item(row, self.COL_SOURCE).setText(str(case.anchor_source or ""))
        return len(cases)

    def _on_remove(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()},
                      reverse=True)
        for row in rows:
            self.table.removeRow(row)

    def _on_run(self) -> None:
        error = self.validate()
        if error:
            QMessageBox.warning(self, tr("batch_readout.title"), error)
            return
        self.accept()

    # -- 测试友好：不经文件对话框即可装填 -------------------------------

    def set_cases_from_paths(self, paths) -> None:
        """直接按路径装填清单（供测试与批处理复用，绕过 QFileDialog）。"""
        for path in paths:
            self._append_row(str(path))
