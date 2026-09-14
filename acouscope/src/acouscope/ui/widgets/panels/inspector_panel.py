# SPDX-License-Identifier: GPL-3.0-only
"""InspectorPanel：视图参数检查器（V099_INSPECTOR_V1）。

填充右 PanelContainer 内容区（标题「检查器 / AI」），为被动只读面板：
- AI 释图按钮（唯一交互件）：clicked → aiRequested 信号；本体释图界面在
  右侧抽屉（T-507a），此处仅入口，面板内不放 AI 界面
- 5 组只读读数（小标题 + 等宽数值 QLabel 两行）：
  当前视图 / 选区 / 分析范围 / 播放位置 / 音频
- 分析范围 = 「分析位置 X.XXXs · 窗口 Y.YYYs」（红针移动/选区变化驱动，
  蓝条已移除——CB-016-3）
- 状态源单一：全部由 main_window 在既有刷新点（选区变化 / 视图切换 /
  invalidate / 播放 tick 与复位 / 加载）驱动 set_* 方法；面板自身不读
  waveform/controller，不发信号（aiRequested 除外）、无轮询
- T-912 档案元数据区（新增，功能化而非向导环节）：由 main_window 把
  file_browser.fileSelected 转接进来（show_file_metadata）；选中支持的
  音频 → 自动登记 ProjectFile（缺时 add_file）+ 自动提取技术元数据 +
  回显已存 metadata（_standard 回显下拉）；保存写该文件 metadata。
  说明：本面板须注入 ProjectManager（set_manager）才可登记/保存。
- 样式走 theme.style_when_theme + TOKENS（数值等宽走 typography.mono），
  严禁硬编码 hex
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from acouscope.audio.io import AudioIO
from acouscope.i18n import tr
from acouscope.ui import theme
from acouscope.ui.widgets.panels.empty_state import EmptyState
from acouscope.ui.widgets.panels.section_header import SectionHeader

# 占位符（与 reset() 口径一致）
_PH_VIEW = "—"
_PH_SELECTION = "无"
_PH_PLAYBACK = "0.000 / 0.000 s"

# ----------------------------------------------------------------------
# T-912 档案元数据编辑区常量
# 字段键 = ProjectFile.metadata 键（同 FIELD_TERMS.key，mapping §三）；
# 控制键 "_standard" 记录所选著录标准（DAT63 / GBT31219.4 / custom）。
# ----------------------------------------------------------------------

# 字段分组（顺序即 UI 行顺序）
_META_AUTO_KEYS = ("SamplingRate", "BitDepth", "Format", "Channels",
                   "Duration", "Date", "Identifier")
_META_MANUAL_KEYS = ("Title", "Creator")
_META_CUSTOM_KEYS = ("Location", "GenreContext", "ActorRole")
_META_FIELD_KEYS = _META_AUTO_KEYS + _META_MANUAL_KEYS + _META_CUSTOM_KEYS

# 每字段 → i18n 行标签 key
_META_LABEL_KEY = {
    "SamplingRate": "inspector.meta.sampling_rate",
    "BitDepth": "inspector.meta.bit_depth",
    "Format": "inspector.meta.format",
    "Channels": "inspector.meta.channels",
    "Duration": "inspector.meta.duration",
    "Date": "inspector.meta.date",
    "Identifier": "inspector.meta.identifier",
    "Title": "inspector.meta.title",
    "Creator": "inspector.meta.creator",
    "Location": "inspector.meta.location",
    "GenreContext": "inspector.meta.genre_context",
    "ActorRole": "inspector.meta.actor_role",
}

# 标准下拉定义：(落盘代码, 下拉文本 i18n key, 说明区 i18n key)；顺序即 UI 顺序。
_META_STANDARDS = (
    ("DAT63", "inspector.meta.std_dat", "inspector.meta.desc_dat"),
    ("GBT31219.4", "inspector.meta.std_gbt", "inspector.meta.desc_gbt"),
    ("custom", "inspector.meta.std_custom", "inspector.meta.desc_custom"),
)
_META_DEFAULT_STD = "custom"


def _fmt_hms(seconds: float) -> str:
    """时长（秒）→ hh:mm:ss 显示口径（DA/T M17；负数截 0）。"""
    total = max(0, int(round(float(seconds))))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _file_stat_mtime(p: Path) -> datetime | None:
    """文件 mtime → 本地 datetime；stat 失败回 None（不抛）。"""
    try:
        return datetime.fromtimestamp(p.stat().st_mtime)
    except OSError:
        return None


def _fmt_file_mtime(p: Path) -> str:
    """摄录时间初值 = 文件时间戳（DA/T M14 系统自动提取口径；可校正）。"""
    dt = _file_stat_mtime(p)
    return dt.strftime("%Y-%m-%d %H:%M") if dt is not None else ""


def _default_identifier(p: Path) -> str:
    """标识符/档号默认生成规则（DA/T M5/M6 自动捕获口径；可校正）。

    规则：`<文件名>-<文件修改日期 YYYYMMDD>`；stat 失败退化为仅文件名。
    """
    dt = _file_stat_mtime(p)
    return f"{p.stem}-{dt:%Y%m%d}" if dt is not None else p.stem


class InspectorPanel(QWidget):
    """视图参数检查器：只读读数 + AI 释图入口（被动同步，无轮询）。"""

    aiRequested = pyqtSignal()  # AI 按钮点击 → main_window 打开释图抽屉
    openRequested = pyqtSignal()  # T-1033：空态主操作按钮 → main_window 打开文件入口

    def __init__(self, parent=None):
        super().__init__(parent)

        sp = theme.TOKENS["spacing"]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(sp["xs"], sp["xs"], sp["xs"], sp["xs"])
        layout.setSpacing(sp["xs"])

        # ---- AI 释图入口（按钮默认样式由主题全局 QSS 提供）----
        self.btn_ai = QPushButton(tr("action.ai_interpret"), self)
        self.btn_ai.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ai.setToolTip(tr("action.ai_interpret"))
        self.btn_ai.clicked.connect(self.aiRequested.emit)
        layout.addWidget(self.btn_ai)

        # ---- 只读读数分组：小标题（sub 色）+ 值（等宽 text 色）两行 ----
        def _divider() -> None:
            line = QFrame(self)
            line.setObjectName("inspectorDivider")
            line.setFrameShape(QFrame.Shape.HLine)
            line.setFixedHeight(sp["xxs"])
            layout.addWidget(line)

        def _group(title_text: str, value_text: str) -> QLabel:
            _divider()
            title = QLabel(title_text, self)
            title.setObjectName("inspectorGroupTitle")
            value = QLabel(value_text, self)
            value.setObjectName("inspectorValue")
            # 数值标签水平策略 Ignored：读数文本随 .3f 跨数字位（9.999→10.000）
            # 宽度变化 → sizeHint 上抛 PanelContainer minimumSizeHint → QSplitter
            # 重排右栏 = 拖红针时检查器抖动。Ignored 让布局忽略其水平 sizeHint，
            # 宽度填满栏宽、不反推面板最小宽（文本左对齐，视觉不变）。
            value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            layout.addWidget(title)
            layout.addWidget(value)
            return value

        # 分组标题文案走 i18n（inspector.view / selection / analysis / playback / audio）
        self.lbl_view = _group(tr("inspector.view"), _PH_VIEW)
        self.lbl_selection = _group(tr("inspector.selection"), _PH_SELECTION)
        self.lbl_analysis = _group(tr("inspector.analysis"), _PH_VIEW)
        self.lbl_playback = _group(tr("inspector.playback"), _PH_PLAYBACK)
        self.lbl_audio = _group(tr("inspector.audio"), _PH_VIEW)

        # ---- T-327 Pε：选区区间统计（只读文本 + 复制；main_window 点击即算后写入）----
        _divider()
        stats_head = QHBoxLayout()
        stats_head.setContentsMargins(0, 0, 0, 0)
        stats_head.setSpacing(sp["xs"])
        title_stats = QLabel(tr("inspector.stats"), self)
        title_stats.setObjectName("inspectorGroupTitle")
        self.btn_copy_stats = QPushButton(tr("region_stats.copy"), self)
        self.btn_copy_stats.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy_stats.setEnabled(False)
        self.btn_copy_stats.clicked.connect(self._copy_stats)
        stats_head.addWidget(title_stats)
        stats_head.addStretch(1)
        stats_head.addWidget(self.btn_copy_stats)
        layout.addLayout(stats_head)
        self.lbl_region_stats = QLabel(_PH_VIEW, self)
        self.lbl_region_stats.setObjectName("inspectorValue")
        self.lbl_region_stats.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self.lbl_region_stats)

        # ---- T-912 档案元数据编辑区（文件管理器选中驱动；空态/编辑区互斥）----
        self._build_metadata_area(layout)

        layout.addStretch(1)

        # 样式注册：随主题刷新（严禁硬编码 hex）
        self._refresh_style = theme.style_when_theme(self, self._build_qss)

    # ------------------------------------------------------------------
    # 样式
    # ------------------------------------------------------------------

    @staticmethod
    def _build_qss(c: dict) -> str:
        """分组标题（sub 色小字）/ 数值（等宽 text 色）/ 分隔线（border 色）。"""
        ty = theme.TOKENS["typography"]
        elev = theme.TOKENS["elevation"]
        rad = theme.TOKENS["radius"]
        sp = theme.TOKENS["spacing"]
        return (
            "QLabel { background: transparent; }"
            "#inspectorGroupTitle {"
            f"  color: {c['sub']}; "
            f"  font-size: {ty['caption']}px;"
            "}"
            "#inspectorValue {"
            f"  color: {c['text']}; "
            f"  font-family: {ty['mono']}; "
            f"  font-size: {ty['caption']}px;"
            "}"
            "QFrame#inspectorDivider {"
            f"  border: none; "
            f"  border-top: {elev['border']}px solid {c['border']};"
            "}"
            # T-912 档案元数据区（区标题与空态自 T-1033 起改走共用构件
            # SectionHeader / EmptyState，其样式由构件自带，不再在此重复）
            "#metaDesc, #metaFieldLabel, #metaStatus {"
            f"  color: {c['sub']}; "
            f"  font-size: {ty['caption']}px;"
            "}"
            "#metaCustomNote {"
            f"  color: {c['sub']}; "
            f"  font-size: {ty['caption']}px;"
            "  font-style: italic;"
            "}"
            "QLineEdit#metaLineEdit, QComboBox#metaStandardCombo {"
            f"  background: transparent; "
            f"  color: {c['text']}; "
            f"  border: 1px solid {c['border']}; "
            f"  border-radius: {rad['sm']}px; "
            f"  padding: {sp['xxs']}px;"
            "}"
        )

    # ------------------------------------------------------------------
    # 同步 API（由 main_window 驱动；仅改标签文本，不发信号、无副作用）
    # ------------------------------------------------------------------

    def set_view_name(self, name: str) -> None:
        self.lbl_view.setText(name or _PH_VIEW)

    def set_selection(self, sel) -> None:
        if sel is None:
            self.lbl_selection.setText(_PH_SELECTION)
        else:
            lo, hi = sel
            self.lbl_selection.setText(f"{lo:.3f} – {hi:.3f} s  ({hi - lo:.3f} s)")

    def set_analysis_scope(self, position: float, frame_size: float) -> None:
        """分析范围数值显示（CB-016-3）：红针位置 + 帧宽（原蓝条区域已移除）。"""
        self.lbl_analysis.setText(
            tr("inspector.analysis_scope").format(
                pos=float(position), win=float(frame_size)
            )
        )

    def set_playback(self, current: float, total: float) -> None:
        self.lbl_playback.setText(f"{current:.3f} / {total:.3f} s")

    def set_audio_info(self, text: str) -> None:
        self.lbl_audio.setText(text or _PH_VIEW)

    def set_region_stats(self, text: str | None) -> None:
        """T-327 Pε：写入选区统计只读文本；None 回占位并禁用复制。"""
        self.lbl_region_stats.setText(text or _PH_VIEW)
        self.btn_copy_stats.setEnabled(bool(text))

    def _copy_stats(self) -> None:
        """把统计文本复制到剪贴板（仅文本存在时可用）。"""
        text = self.lbl_region_stats.text()
        if text and text != _PH_VIEW:
            QApplication.clipboard().setText(text)

    def reset(self) -> None:
        """五个标签全部回占位（invalidate 时调用）。"""
        self.lbl_view.setText(_PH_VIEW)
        self.lbl_selection.setText(_PH_SELECTION)
        self.lbl_analysis.setText(_PH_VIEW)
        self.lbl_playback.setText(_PH_PLAYBACK)
        self.lbl_audio.setText(_PH_VIEW)
        self.set_region_stats(None)

    # ------------------------------------------------------------------
    # T-912 档案元数据编辑区
    # ------------------------------------------------------------------

    def _build_metadata_area(self, layout: QVBoxLayout) -> None:
        """构建"档案元数据"区（空态提示 与 编辑区 互斥显隐）。

        注意：区标题 objectName 用 metaTitle（非 inspectorGroupTitle），
        避免既有 i18n 六组标题计数测试被破坏；样式全走 theme 令牌。
        """
        sp = theme.TOKENS["spacing"]

        # 元数据登记/保存依赖（由 main_window/测试注入；None 时仅展示不落盘）
        self._meta_manager = None

        # 空态：未选中支持音频 / 无音频时显示（不报错）——统一走共用构件
        # EmptyState（ARCH §五-3：说明 + 主操作按钮 + 拖放提示，居中 text_sub）
        self.empty_meta = EmptyState(
            message=tr("inspector.meta.empty"),
            action_text=tr("action.open"),
            drop_hint=tr("empty.drop_hint"),
            parent=self,
        )
        self.empty_meta.actionTriggered.connect(self.openRequested.emit)
        self.empty_meta.hide()
        layout.addWidget(self.empty_meta)

        # 编辑容器（选中文件后才显示）
        self.meta_box = QWidget(self)
        box = QVBoxLayout(self.meta_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(sp["xs"])

        # 区标题（T-1033：改走共用构件 SectionHeader，h3 + 8 上间距，ARCH §五-2）
        box.addWidget(SectionHeader(tr("inspector.metadata"), self.meta_box))

        # 保存状态 + 保存钮
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(sp["xs"])
        self.lbl_meta_status = QLabel("", self.meta_box)
        self.lbl_meta_status.setObjectName("metaStatus")
        self.btn_meta_save = QPushButton(tr("inspector.meta.save"), self.meta_box)
        self.btn_meta_save.setObjectName("metaSaveButton")
        self.btn_meta_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_meta_save.setEnabled(False)
        self.btn_meta_save.clicked.connect(self._on_meta_save)
        head.addWidget(self.lbl_meta_status)
        head.addStretch(1)
        head.addWidget(self.btn_meta_save)
        box.addLayout(head)

        # 标准选择下拉（3 项）+ 说明区（随下拉切换）
        self.meta_standard_combo = QComboBox(self.meta_box)
        self.meta_standard_combo.setObjectName("metaStandardCombo")
        for _code, label_key, _desc_key in _META_STANDARDS:
            self.meta_standard_combo.addItem(tr(label_key), _code)
        self.lbl_meta_desc = QLabel("", self.meta_box)
        self.lbl_meta_desc.setObjectName("metaDesc")
        self.lbl_meta_desc.setWordWrap(True)
        box.addWidget(self.meta_standard_combo)
        box.addWidget(self.lbl_meta_desc)

        # 字段行（自动填报区 → 关键人工字段 → 自定义扩展字段）
        self.meta_edits: dict[str, QLineEdit] = {}
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(sp["xxs"])
        self._meta_append_rows(form, _META_AUTO_KEYS)
        self._meta_append_rows(form, _META_MANUAL_KEYS)
        # 标准外字段显式标注（自定义扩展（非标准元素））
        note = QLabel(tr("inspector.meta.custom_note"), self.meta_box)
        note.setObjectName("metaCustomNote")
        note.setWordWrap(True)
        form.addRow(note)
        self._meta_append_rows(form, _META_CUSTOM_KEYS)
        box.addLayout(form)

        layout.addWidget(self.meta_box)
        self.meta_box.hide()

        self._meta_path: str | None = None
        self.meta_active = False
        self.meta_standard_combo.currentIndexChanged.connect(
            self._on_meta_standard_changed
        )
        # 初值：不指定（自定义）→ 说明区同步
        self.meta_standard_combo.setCurrentIndex(
            self._meta_standard_index(_META_DEFAULT_STD)
        )

    def _meta_append_rows(
        self, form: QFormLayout, keys: tuple[str, ...]
    ) -> None:
        """按字段键追加 QFormLayout 行（标签走 i18n，编辑框入 meta_edits）。"""
        for key in keys:
            lab = QLabel(tr(_META_LABEL_KEY[key]), self.meta_box)
            lab.setObjectName("metaFieldLabel")
            edit = QLineEdit(self.meta_box)
            edit.setObjectName("metaLineEdit")
            self.meta_edits[key] = edit
            form.addRow(lab, edit)

    def _meta_standard_index(self, code: str) -> int:
        """代码 → 下拉下标；未知/缺失回默认（custom）。"""
        for i, (c, _l, _d) in enumerate(_META_STANDARDS):
            if c == code:
                return i
        return self._meta_standard_index(_META_DEFAULT_STD)

    def _meta_standard_code(self) -> str:
        """当前下拉代码（当前数据缺失回默认）。"""
        data = self.meta_standard_combo.currentData()
        if data is not None:
            return str(data)
        return _META_DEFAULT_STD

    def _on_meta_standard_changed(self, index: int) -> None:
        """标准切换 → 说明区随动（§说明区文案照抄 i18n，禁改写）。"""
        if 0 <= index < len(_META_STANDARDS):
            self.lbl_meta_desc.setText(tr(_META_STANDARDS[index][2]))

    def _set_meta_active(self, active: bool) -> None:
        """激活编辑区（active=True 显示编辑框/False 回空态），并复位状态。"""
        self.meta_active = bool(active)
        self.empty_meta.setVisible(not active)
        self.meta_box.setVisible(active)
        self.lbl_meta_status.clear()
        if not active:
            self._meta_path = None
            self.btn_meta_save.setEnabled(False)

    def set_manager(self, manager) -> None:
        """注入 ProjectManager（登记/保存依赖；接线方在项目切换后调用）。"""
        self._meta_manager = manager

    def clear_metadata(self) -> None:
        """清空元数据编辑区回空态（文件管理器选择清空时调用）。"""
        self._set_meta_active(False)

    def show_file_metadata(self, path) -> bool:
        """T-912：加载某文件的档案元数据编辑区。

        对支持的音频：若尚无 ProjectFile 条目则 add_file 登记（自动登记）；
        从文件自动提取技术元数据（复用 audio/io.py 读取能力）预填可校正字段；
        回显该文件已存 metadata（含 _standard 下拉初值，切换不串档）。
        无音频/不支持/读取失败 → 空态不报错。

        Returns:
            本次是否新登记了 ProjectFile（True → 接线方刷新列表"✓"）。
        """
        self.lbl_meta_status.clear()
        p = Path(str(path))
        if p.suffix.lower() not in AudioIO.SUPPORTED_FORMATS:
            self._set_meta_active(False)
            return False

        info = self._meta_read_info(p)
        if info is None:
            # 打不开（损坏/占用等）：不登记、回空态，不报错不崩溃
            self._set_meta_active(False)
            return False

        registered = self._meta_ensure_registered(p)
        stored = self._meta_stored(p)

        # 已存值优先；空字段回退自动提取值（用户可校正后覆盖）
        defaults = {
            "SamplingRate": str(info.sample_rate),
            "BitDepth": str(info.bit_depth),
            "Format": str(info.format),
            "Channels": str(info.channels),
            "Duration": _fmt_hms(info.duration),
            "Date": _fmt_file_mtime(p),
            "Identifier": _default_identifier(p),
        }
        for key, edit in self.meta_edits.items():
            val = stored.get(key, "") or defaults.get(key, "")
            edit.setText(val)

        # _standard 回显下拉（无/未知 → custom 默认）
        code = stored.get("_standard") or _META_DEFAULT_STD
        idx = self._meta_standard_index(code)
        if self.meta_standard_combo.currentIndex() != idx:
            self.meta_standard_combo.setCurrentIndex(idx)
        else:
            self._on_meta_standard_changed(idx)

        self._meta_path = str(p)
        self.meta_active = True
        self.empty_meta.hide()
        self.meta_box.show()
        self.btn_meta_save.setEnabled(self._meta_manager is not None)
        return registered

    def _meta_read_info(self, p: Path):
        """读取文件技术信息（复用 AudioIO.get_info）；失败回 None（不抛）。"""
        try:
            return AudioIO().get_info(p)
        except Exception:
            return None

    def _meta_ensure_registered(self, p: Path) -> bool:
        """缺 ProjectFile 条目则 add_file 登记（自动登记，T-912）。"""
        if self._meta_manager is None:
            return False
        if self._meta_manager.get_file(str(p)) is not None:
            return False
        self._meta_manager.add_file(str(p), label=p.name)
        return True

    def _meta_stored(self, p: Path) -> dict:
        """该文件已存 metadata（无条目/无 manager → 空 dict）。"""
        if self._meta_manager is None:
            return {}
        pf = self._meta_manager.get_file(str(p))
        return dict(pf.metadata) if pf is not None else {}

    def _on_meta_save(self) -> None:
        """保存：写该文件 ProjectFile.metadata + _standard（空值不写入）。"""
        if self._meta_path is None or self._meta_manager is None:
            return
        pf = self._meta_manager.get_file(self._meta_path)
        if pf is None:
            return
        fields = {
            key: edit.text().strip()
            for key, edit in self.meta_edits.items()
            if edit.text().strip()
        }
        merged = {
            k: v
            for k, v in pf.metadata.items()
            if k not in _META_FIELD_KEYS and k != "_standard"
        }
        merged.update(fields)
        merged["_standard"] = self._meta_standard_code()
        pf.metadata = merged
        self.lbl_meta_status.setText(tr("inspector.meta.saved"))
