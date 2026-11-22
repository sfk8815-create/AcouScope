# SPDX-License-Identifier: GPL-3.0-only
"""论文图导出对话框（PI-P5-B3-01i）：预设 → 平台通用绘图层 → 300 dpi PNG+PDF。

**分层纪律**（2026-10-25 通用化返工口径，本模块只接线不造轮子）：

- 图形与读数一律来自 :mod:`acouscope.visualization.figures`（``*_data`` ＋ 同名
  绘图函数），本模块**不含任何绘图逻辑、不碰数据口径**；
- 呈现参数（裁剪／轴／图注槽位）一律来自
  :mod:`acouscope.visualization.presets` 的 ``get_preset``；
- 出版硬要求固定：``dpi=300``、``formats=("png", "pdf")``——不做可选降级。

**锚定偏移**（paper_C）：由演奏实践／文献给，平台不猜；界面用可空复选框表达
「未提供」，缺锚时该预设导出按钮禁用（``reference_comparison(require_anchor=True)``
另有硬闸兜底）。

合规：本对话框为模态 QDialog（与项目新建／关于同列），经派活令 PI-P5-B3-01i 授权。
"""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from acouscope.i18n import tr
from acouscope.ui.widgets.param_spin import ParamSpinBox
from acouscope.ui import theme
from acouscope.ui.widgets.toast import show_toast
from acouscope.visualization.presets import get_preset, list_presets

#: 出版硬要求（不做可选降级；判据 test_paper_figure_export_ui 逐值锁定）
DPI = 300
FORMATS = ("png", "pdf")

#: 分面数据文件过滤器（纯 ASCII，无 i18n 需求）
PANELS_FILTER = "JSON (*.json);;CSV (*.csv);;All files (*)"

__all__ = ["DPI", "FORMATS", "PANELS_FILTER", "PaperFigureDialog"]


def _default_output_dir() -> Path:
    """默认输出目录：``~/Documents``（存在与否不改写，交由导出侧 mkdir）。"""
    return Path.home() / "Documents"


class PaperFigureDialog(QDialog):
    """论文图导出：三预设（paper_A／paper_B／paper_C）→ 平台 API → PNG+PDF。

    用法::

        dlg = PaperFigureDialog(audio_path, parent=self)
        dlg.exec()          # 点「导出」即按预设分支调 figures 出图

    也可在测试中构造后直接调 :meth:`export`（不需要 exec 事件循环）。
    """

    def __init__(self, audio_path=None, parent=None):
        super().__init__(parent)
        self._audio_path = None if audio_path is None else str(audio_path)
        self._presets = tuple(list_presets())

        #: 最近一次成功导出的返回值（figures.* 的 result dict）
        self.last_result: dict | None = None
        #: 最近一次失败的错误文本（None = 未失败）
        self.last_error: str | None = None
        #: 最近一次同源核验结果（T-3；None = 尚未核验）
        self.last_same_run_check: dict | None = None

        self.setWindowTitle(tr("figure_export.title"))
        t = theme.TOKENS
        self.setMinimumWidth(t["spacing"]["xl"] * 14)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            t["spacing"]["md"], t["spacing"]["md"],
            t["spacing"]["md"], t["spacing"]["md"],
        )
        layout.setSpacing(t["spacing"]["sm"])

        # ----- 图型 + 输出目录 -----
        form = QFormLayout()
        form.setSpacing(t["spacing"]["sm"])

        self.cmb_preset = QComboBox()
        self.cmb_preset.setObjectName("paperFigurePreset")
        for name in self._presets:
            self.cmb_preset.addItem(self._preset_label(name), name)
        self.cmb_preset.currentIndexChanged.connect(self._refresh_state)
        form.addRow(QLabel(tr("figure_export.figure")), self.cmb_preset)

        self.edit_dir = QLineEdit()
        self.edit_dir.setObjectName("paperFigureOutputDir")
        self.edit_dir.setReadOnly(True)
        self.edit_dir.setText(str(_default_output_dir()))
        row_dir = QHBoxLayout()
        row_dir.addWidget(self.edit_dir, stretch=1)
        self.btn_browse_dir = QPushButton(tr("figure_export.browse"))
        self.btn_browse_dir.setObjectName("paperFigureBrowseDir")
        self.btn_browse_dir.clicked.connect(self._on_browse_dir)
        row_dir.addWidget(self.btn_browse_dir)
        form.addRow(QLabel(tr("figure_export.output_dir")), row_dir)

        layout.addLayout(form)

        # ----- paper_A 专用：段起止 -----
        self.section_a = QWidget(self)
        self.section_a.setObjectName("paperFigureSectionA")
        form_a = QFormLayout(self.section_a)
        form_a.setContentsMargins(0, 0, 0, 0)
        form_a.setSpacing(t["spacing"]["sm"])

        self.spin_start = ParamSpinBox()
        self.spin_start.setObjectName("paperFigureStartS")
        self.spin_start.setDecimals(3)
        self.spin_start.setRange(0.0, 60000.0)
        self.spin_start.setSingleStep(0.1)
        self.spin_start.setSuffix(" s")
        form_a.addRow(QLabel(tr("figure_export.start_s")), self.spin_start)

        self.spin_end = ParamSpinBox()
        self.spin_end.setObjectName("paperFigureEndS")
        self.spin_end.setDecimals(3)
        self.spin_end.setRange(0.0, 60000.0)
        self.spin_end.setSingleStep(0.1)
        self.spin_end.setSuffix(" s")
        form_a.addRow(QLabel(tr("figure_export.end_s")), self.spin_end)
        layout.addWidget(self.section_a)

        # ----- paper_C 专用：锚定偏移 / 锚来源 -----
        self.section_c = QWidget(self)
        self.section_c.setObjectName("paperFigureSectionC")
        form_c = QFormLayout(self.section_c)
        form_c.setContentsMargins(0, 0, 0, 0)
        form_c.setSpacing(t["spacing"]["sm"])

        # 窗起点：**取数参数**（换窗即换数），故与锚定偏移同列在 paper_C 区内
        self.spin_window_start = ParamSpinBox()
        self.spin_window_start.setObjectName("paperFigureWindowStartS")
        self.spin_window_start.setDecimals(3)
        self.spin_window_start.setRange(0.0, 3600.0)
        self.spin_window_start.setSingleStep(1.0)
        self.spin_window_start.setSuffix(" s")
        self.spin_window_start.setValue(0.0)
        form_c.addRow(QLabel(tr("figure_export.window_start")), self.spin_window_start)

        row_anchor = QHBoxLayout()
        self.spin_anchor = ParamSpinBox()
        self.spin_anchor.setObjectName("paperFigureAnchorCents")
        self.spin_anchor.setDecimals(2)
        self.spin_anchor.setRange(-1200.0, 1200.0)
        self.spin_anchor.setSingleStep(1.0)
        self.spin_anchor.setValue(0.0)
        row_anchor.addWidget(self.spin_anchor, stretch=1)
        self.chk_anchor_pending = QCheckBox(tr("figure_export.anchor_pending"))
        self.chk_anchor_pending.setObjectName("paperFigureAnchorPending")
        self.chk_anchor_pending.setChecked(True)  # 默认「未提供」：不替用户猜锚
        self.chk_anchor_pending.toggled.connect(self._refresh_state)
        row_anchor.addWidget(self.chk_anchor_pending)
        form_c.addRow(QLabel(tr("figure_export.anchor_cents")), row_anchor)

        self.edit_anchor_source = QLineEdit()
        self.edit_anchor_source.setObjectName("paperFigureAnchorSource")
        form_c.addRow(QLabel(tr("figure_export.anchor_source")), self.edit_anchor_source)

        # W-14-03 GUI 面 6：音名口径（与 degree 口径并陈；不改 preset 默认值）
        self.chk_note_name = QCheckBox(tr("w14.figure.note_name"))
        self.chk_note_name.setObjectName("paperFigureNoteName")
        self.chk_note_name.setToolTip(tr("w14.figure.note_name_tip"))
        form_c.addRow(self.chk_note_name)

        self.lbl_anchor_note = QLabel(tr("figure_export.anchor_note"))
        self.lbl_anchor_note.setObjectName("paperFigureAnchorNote")
        self.lbl_anchor_note.setWordWrap(True)
        form_c.addRow(self.lbl_anchor_note)
        layout.addWidget(self.section_c)

        # ----- paper_B 专用：分面数据文件 -----
        self.section_b = QWidget(self)
        self.section_b.setObjectName("paperFigureSectionB")
        form_b = QFormLayout(self.section_b)
        form_b.setContentsMargins(0, 0, 0, 0)
        form_b.setSpacing(t["spacing"]["sm"])

        self.edit_panels = QLineEdit()
        self.edit_panels.setObjectName("paperFigurePanelsFile")
        self.edit_panels.setReadOnly(True)
        row_panels = QHBoxLayout()
        row_panels.addWidget(self.edit_panels, stretch=1)
        self.btn_browse_panels = QPushButton(tr("figure_export.browse"))
        self.btn_browse_panels.setObjectName("paperFigureBrowsePanels")
        self.btn_browse_panels.clicked.connect(self._on_browse_panels)
        row_panels.addWidget(self.btn_browse_panels)
        form_b.addRow(QLabel(tr("figure_export.panels_file")), row_panels)

        # T-3 同源闸：图与表须出自同一次运行（同一 run_id）
        self.chk_same_run = QCheckBox(tr("figure_export.same_run"))
        self.chk_same_run.setObjectName("paperFigureSameRun")
        self.chk_same_run.setChecked(True)
        form_b.addRow(self.chk_same_run)
        self.lbl_same_run = QLabel(tr("figure_export.same_run_note"))
        self.lbl_same_run.setObjectName("paperFigureSameRunNote")
        self.lbl_same_run.setWordWrap(True)
        form_b.addRow(self.lbl_same_run)

        # W-14-04 GUI 面 7：分母口径（all／judgable／body）；只改本次导出参数
        self.cmb_denominator = QComboBox()
        self.cmb_denominator.setObjectName("paperFigureDenominator")
        for value, label_key in (
            ("all", "w14.figure.denominator_all"),
            ("judgable", "w14.figure.denominator_judgable"),
            ("body", "w14.figure.denominator_body"),
        ):
            self.cmb_denominator.addItem(tr(label_key, value), value)
        form_b.addRow(QLabel(tr("w14.figure.denominator")), self.cmb_denominator)
        layout.addWidget(self.section_b)

        # ----- 出版参数（只读文字：不做可选降级）-----
        self.lbl_publication = QLabel(tr("figure_export.publication_note"))
        self.lbl_publication.setObjectName("paperFigurePublicationNote")
        layout.addWidget(self.lbl_publication)

        layout.addStretch(1)

        # ----- 按钮行 -----
        row_btns = QHBoxLayout()
        row_btns.addStretch(1)
        self.btn_cancel = QPushButton(tr("figure_export.cancel"))
        self.btn_cancel.setObjectName("paperFigureCancelBtn")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_export = QPushButton(tr("figure_export.export"))
        self.btn_export.setObjectName("paperFigureExportBtn")
        self.btn_export.setDefault(True)
        self.btn_export.clicked.connect(self._on_export_clicked)
        row_btns.addWidget(self.btn_cancel)
        row_btns.addWidget(self.btn_export)
        layout.addLayout(row_btns)

        self._refresh_state()

    # ------------------------------------------------------------------
    # 对外读取面（测试与调用侧复用同一口径）
    # ------------------------------------------------------------------

    @staticmethod
    def _preset_label(name: str) -> str:
        """预设显示名：``paper_A`` → ``figure_export.preset_a``（内部值仍是原名）。"""
        suffix = name.rsplit("_", 1)[-1].lower()
        return tr(f"figure_export.preset_{suffix}", name)

    def preset_names(self) -> list[str]:
        """下拉里的预设内部值顺序（paper_A／paper_B／paper_C）。"""
        return list(self._presets)

    def selected_preset(self) -> str:
        """当前预设内部名（如 ``paper_C``）。"""
        return str(self.cmb_preset.currentData())

    def current_figure(self) -> str:
        """当前预设在通用绘图层的图形名（segment_curve 等）。"""
        return str(get_preset(self.selected_preset())["figure"])

    def output_dir(self) -> str:
        """输出目录（只读行现值）。"""
        return self.edit_dir.text().strip()

    def window_start_s(self) -> float:
        """取数窗起点（秒）：取数参数，非呈现参数（换窗即换数，须登记）。"""
        return float(self.spin_window_start.value())

    def anchor_offset_cents(self) -> float | None:
        """锚定偏移（音分）；「未提供」勾选时返回 None（不替用户猜 0）。"""
        return None if self.chk_anchor_pending.isChecked() else float(self.spin_anchor.value())

    def anchor_source(self) -> str | None:
        """锚来源（可空）。"""
        text = self.edit_anchor_source.text().strip()
        return text or None

    def panels_file(self) -> str | None:
        """分面数据文件路径（可空）。"""
        text = self.edit_panels.text().strip()
        return text or None

    def require_same_run(self) -> bool:
        """是否要求「图与表同源」硬闸（默认 True，T-3）。"""
        return bool(self.chk_same_run.isChecked())

    def note_name(self) -> bool:
        """是否增出音名口径（W-14-03；缺省 False ＝ 旧行为，不改 preset 默认）。"""
        return bool(self.chk_note_name.isChecked())

    def denominator(self) -> str:
        """图件分母口径（W-14-04）：``all``／``judgable``／``body``。"""
        return str(self.cmb_denominator.currentData() or "all")

    def same_run_check(self) -> dict:
        """** T-3 同源核验**：panels 的 ``run_id`` 与配套分布件是否一致。

        在 panels 所在目录找 ``type_distribution.absolute.json``：两者都带
        ``run_id`` ⇒ 逐位比对。返回
        ``{"checked", "panels_run_id", "table_run_id", "consistent"}``；
        ``checked=False`` = 无配套件可校 —— **如实登记为未核验**，不得当作通过。
        """
        info = {"checked": False, "panels_run_id": None,
                "table_run_id": None, "consistent": None}
        panels_path = self.panels_file()
        if not panels_path:
            return info
        try:
            panels = json.loads(Path(panels_path).read_text(encoding="utf-8"))
            if isinstance(panels, list):   # 纯 list 形态（无 run_id 信封）
                info["panels_run_id"] = None
            else:
                info["panels_run_id"] = panels.get("run_id")
        except (OSError, ValueError):
            return info
        tables = Path(panels_path).parent / "type_distribution.absolute.json"
        if not tables.is_file():
            return info          # 无配套分布件 ⇒ 未核验（不假装通过）
        try:
            rows = json.loads(tables.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return info
        table_run = rows[0].get("run_id") if isinstance(rows, list) and rows else None
        info["table_run_id"] = table_run
        info["checked"] = bool(info["panels_run_id"]) and bool(table_run)
        info["consistent"] = bool(
            info["checked"] and info["panels_run_id"] == table_run
        )
        return info

    def _enforce_same_run(self) -> dict:
        """T-3 硬闸：要求同源却不一致 ⇒ 抛错（不出图）；一致 ⇒ 顺手出对账件。"""
        info = self.same_run_check()
        if not self.require_same_run() or not info["checked"]:
            return info
        if not info["consistent"]:
            raise ValueError(
                tr("figure_export.error_same_run").format(
                    panels=info["panels_run_id"], table=info["table_run_id"]
                )
            )
        # 同源成立 ⇒ 出「图—表逐格对账」件（T-3 验收口径）
        from acouscope.analysis.readout import verify_figure_table

        note = verify_figure_table(
            Path(self.panels_file()).parent,
            panels_path=self.panels_file(),
            tables_path=str(Path(self.panels_file()).parent
                            / "type_distribution.absolute.json"),
        )
        info["figure_table_check"] = note.get("pass")
        return info

    # ------------------------------------------------------------------
    # 状态联动
    # ------------------------------------------------------------------

    def _refresh_state(self, *_args) -> None:
        """按预设显示对应参数区；缺锚（paper_C）则禁用导出。"""
        kind = self.current_figure()
        self.section_a.setVisible(kind == "segment_curve")
        self.section_b.setVisible(kind == "type_oscillation")
        self.section_c.setVisible(kind == "reference_comparison")
        anchor_given = not self.chk_anchor_pending.isChecked()
        self.spin_anchor.setEnabled(anchor_given)
        self.edit_anchor_source.setEnabled(anchor_given)
        self.btn_export.setEnabled(self.export_allowed())

    def export_allowed(self) -> bool:
        """导出按钮可用性：paper_C 必须已给锚（0 与「不填」是两件事）。"""
        if self.current_figure() == "reference_comparison":
            return not self.chk_anchor_pending.isChecked()
        return True

    # ------------------------------------------------------------------
    # 交互槽
    # ------------------------------------------------------------------

    def _on_browse_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, tr("figure_export.output_dir"), self.output_dir()
        )
        if path:
            self.edit_dir.setText(path)

    def _on_browse_panels(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, tr("figure_export.panels_file"), self.panels_file() or "", PANELS_FILTER
        )
        if path:
            self.edit_panels.setText(path)

    def _on_export_clicked(self) -> None:
        self.export()

    # ------------------------------------------------------------------
    # 导出：按预设分支调平台 API（本模块不含绘图逻辑）
    # ------------------------------------------------------------------

    def _common_kwargs(self) -> dict:
        """出版参数（固定）＋ 预设呈现参数（labels／style）＋ 文件名主干。"""
        preset = get_preset(self.selected_preset())
        return {
            "stem": self.selected_preset().lower(),
            "dpi": DPI,
            "formats": FORMATS,
            "labels": preset.get("labels"),
            "style": tuple(preset.get("style", ("default", "zh_CN"))),
        }

    def export(self) -> dict | None:
        """按预设分支导出（300 dpi PNG+PDF）。

        成功返回 figures 的 result dict 并 toast；``ValueError``／``OSError``
        → :meth:`QMessageBox.warning` 显式报错（不静默吞），返回 None。
        """
        from acouscope.visualization import figures

        preset = get_preset(self.selected_preset())
        kind = str(preset["figure"])
        out_dir = self.output_dir()
        common = self._common_kwargs()

        try:
            if kind == "segment_curve":
                if not self._audio_path:
                    raise ValueError(tr("figure_export.need_audio"))
                data = figures.segment_curve_data(
                    self._audio_path,
                    float(self.spin_start.value()),
                    float(self.spin_end.value()),
                    window_s=float(preset.get("window_s", 30.0)),
                    template=preset.get("tuning_template", "12tet"),
                    segmenter=preset.get("segmenter", "hmm"),
                )
                result = figures.segment_curve(
                    data,
                    out_dir,
                    pad_left=float(preset.get("pad_left", 0.30)),
                    pad_right=float(preset.get("pad_right", 0.30)),
                    annotate_segment=bool(preset.get("annotate_segment", True)),
                    **common,
                )
            elif kind == "type_oscillation":
                panels_path = self.panels_file()
                if not panels_path:
                    raise ValueError(tr("figure_export.need_panels"))
                check = self._enforce_same_run()
                # W-14-04：分母口径只改本次导出参数（preset 默认值不动）
                data = figures.type_oscillation_data(
                    figures.load_panels(panels_path), denominator=self.denominator()
                )
                result = figures.type_oscillation(data, out_dir, **common)
                # 同源核验结果**不并入** result（那是绘图层产物），另存在 dialog 上
                self.last_same_run_check = check
            else:
                if not self._audio_path:
                    raise ValueError(tr("figure_export.need_audio"))
                # 一站式公开入口（读窗 → 分析 → 读数 → 出图）：口径全在 figures 层，
                # 本模块只用公开名；窗起点是取数参数，随结果登记
                result = figures.reference_comparison_from_audio(
                    self._audio_path,
                    out_dir,
                    window_start_s=self.window_start_s(),
                    window_s=float(preset.get("window_s", 30.0)),
                    anchor_offset_cents=self.anchor_offset_cents(),
                    anchor_source=self.anchor_source(),
                    templates=preset.get("templates"),
                    limit=int(preset.get("limit", 60)),
                    require_anchor=bool(preset.get("require_anchor", False)),
                    tuning_template=preset.get("tuning_template", "12tet"),
                    note_name=self.note_name(),
                    **common,
                )
        except (ValueError, OSError) as exc:
            self.last_error = str(exc)
            QMessageBox.warning(self, tr("figure_export.failed"), str(exc))
            return None

        self.last_error = None
        self.last_result = result
        show_toast(self, tr("figure_export.done").format(path=out_dir), level="success")
        return result
