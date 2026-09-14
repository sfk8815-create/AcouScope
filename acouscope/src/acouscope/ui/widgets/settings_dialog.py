# SPDX-License-Identifier: GPL-3.0-only
"""统一设置面板（选项卡式，非模态，可嵌入抽屉；T-504g 去模态化）。

四个选项卡：
- 通用：语言选择
- AI：模型来源、API 地址、模型名称、API 密钥、发送图像开关
- 界面：主题
- 导出：默认导出格式、默认导出 DPI

信号：
- applied：点击「应用」时发出，调用方随后读取 language()/ai_config()/theme() 等
- cancelled：未应用即关闭时发出（调用方用于回滚预览过的主题等）
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, QObject, QThread, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QComboBox,
    QCheckBox,
    QDoubleSpinBox,
    QLineEdit,
    QLabel,
    QAbstractScrollArea,
    QListWidget,
    QStackedWidget,
    QWidget,
    QTableWidget,
    QTableWidgetItem,
    QListWidgetItem,
    QHeaderView,
    QPushButton,
    QProgressBar,
    QRadioButton,
)

from acouscope.ai.interpreter import PROVIDERS
from acouscope.i18n import tr, available_languages
from acouscope.ui.widgets.toast import show_toast

# 与 exporters.FigureExporter.SUPPORTED_FORMATS 对齐
FORMATS = [
    ("svg", "svg"),
    ("png", "png"),
    ("pdf", "pdf"),
    ("eps", "eps"),
]

DPI_OPTIONS = [150, 300, 600, 1200]

# T-320：云端档厂商（Cherry Studio「模型服务商」范式：预置厂商 + OpenAI 兼容兜底）
_CLOUD_VENDOR_IDS = ("deepseek", "qwen", "openai", "zhipu", "custom")

# T-1022 §7：推荐模型列表的最小可见行数（高度由字体度量换算，非硬编码像素）
_AI_MODEL_LIST_ROWS = 5

# T-1022 §7：推荐档位（ai.model_recommend 的 fit 值）→ 徽标文案键
_AI_FIT_KEYS = {
    "recommended": "settings.ai_fit_recommended",
    "ok": "settings.ai_fit_ok",
    "insufficient_ram": "settings.ai_fit_low_ram",
    "insufficient_disk": "settings.ai_fit_low_disk",
}

# 旧配置迁移映射（已删预设的归属判定；详见 SettingsDialog._ai_source_from_config）
_OLD_LOCAL_PROVIDERS = {"llama_cpp", "lm_studio"}
_OLD_CLOUD_PROVIDERS = {
    "free_remote", "openai", "anthropic", "google", "deepseek", "moonshot",
    "qwen", "zhipu", "siliconflow", "openrouter", "groq", "together",
    "xai", "custom",
}


def _is_local_url(url: str) -> bool:
    """自建地址启发式：本机回环 / 局域网段（迁移判定用，非安全边界）。"""
    u = (url or "").strip().lower()
    return (u.startswith("http://127.0.0.1") or u.startswith("http://localhost")
            or u.startswith("http://192.168.") or u.startswith("http://10.")
            or u.startswith("http://172."))


class _EngineUpdateWorker(QObject):
    """后台执行本地模型引擎「检查更新」全流程（非模态；禁真网络进测试）。

    工作线程执行 acouscope.ai.ollama_engines.perform_upgrade，进度经
    progress(0..1) 上报、结果经 done(code, version) 交回 UI 线程。
    """

    progress = pyqtSignal(float)
    done = pyqtSignal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.cancel_requested = False

    def run(self) -> None:
        from acouscope.ai import ollama_engines as oe
        try:
            code, version = oe.perform_upgrade(
                self.progress.emit, lambda: self.cancel_requested)
        except Exception:
            code, version = "failed", ""
        self.done.emit(code, version or "")


class SettingsDialog(QWidget):
    """统一设置面板（QWidget，可嵌入 DrawerWidget；非模态）。"""

    applied = pyqtSignal()    # 点击「应用」：调用方读取取值方法并持久化
    cancelled = pyqtSignal()  # 未应用即关闭：调用方回滚预览（如主题）

    # T-1001：图标风格缩略预览（下拉项与预览行共用的代表图标名 / 位图边长）
    _ICON_PREVIEW_NAMES = ("play", "stop", "record", "settings")
    _ICON_PREVIEW_SIZE = 20

    def __init__(
        self,
        parent=None,
        language: str = "en_US",
        ai_config: dict | None = None,
        theme: str = "default",
        default_format: str = "svg",
        default_dpi: int = 300,
        reference_hz: float = 440.0,
    ):
        super().__init__(parent)
        self._applied = False
        self._lang = language if language in available_languages() else "en_US"
        self._ai = ai_config or {}
        self._theme = theme
        self._fmt = default_format if default_format in dict(FORMATS) else "svg"
        self._dpi = default_dpi if default_dpi in DPI_OPTIONS else 300
        # T-921：A4 参考频率初值（越界回退 440.0，与 Settings.load 同口径）
        try:
            reference = float(reference_hz)
        except (TypeError, ValueError):
            reference = 440.0
        self._reference_hz = reference if 400.0 <= reference <= 480.0 else 440.0
        # T-319：引擎升级后台任务状态（防重复点击 / 供取消）
        self._engine_thread: QThread | None = None
        self._engine_worker_ref: _EngineUpdateWorker | None = None
        self._engine_busy = False
        self._engine_cancel = False
        # T-1022：模型下载后台任务（推荐列表的 [下载]/[删除]）
        self._model_worker = None

        self._build_ui()

        # T-1001：图标风格「切换即预览」→ 应用持久化 / 取消回滚（同主题口径）
        self.applied.connect(self._persist_icon_style)
        self.cancelled.connect(self._revert_icon_style)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # T-1013：两栏 = 左导航列表（竖排标签，水平可读）+ 右内容页栈。
        # 选型：原生 QTabWidget West 离屏实测 tab 文本被旋转、tab 高度随文本
        # 长度起伏（呈现不满足，触任务书自绘回退条件）；改用 QListWidget +
        # QStackedWidget，选中态沿用全局 QSS 语义色（theme QListWidget 段）。
        # 六个 tab 页构建顺序/内容零改动（仅承载容器由 QTabWidget 换 stack）。
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("settingsNavList")
        self.nav_list.setSizeAdjustPolicy(
            QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents
        )
        self.nav_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.nav_list.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.nav_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.nav_list.setUniformItemSizes(True)
        self.nav_list.currentRowChanged.connect(self._on_nav_row_changed)

        self.stack = QStackedWidget()
        self.stack.setObjectName("settingsPages")
        for title, builder in (
            (tr("settings.tab.general"), self._build_general_tab),
            ("音频设备", self._build_audio_device_tab),
            (tr("settings.tab.ai"), self._build_ai_tab),
            (tr("settings.tab.interface"), self._build_interface_tab),
            ("快捷键", self._build_shortcuts_tab),
            (tr("settings.tab.export"), self._build_export_tab),
        ):
            self.nav_list.addItem(title)
            self.stack.addWidget(builder())

        body.addWidget(self.nav_list)
        body.addWidget(self.stack, 1)
        layout.addLayout(body)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_apply = QPushButton(tr("btn.apply"))
        self.btn_apply.clicked.connect(self._on_apply_clicked)
        btn_row.addWidget(self.btn_apply)
        self.btn_close = QPushButton(tr("btn.close"))
        self.btn_close.clicked.connect(self.close)
        btn_row.addWidget(self.btn_close)
        layout.addLayout(btn_row)

    def _on_apply_clicked(self):
        self._applied = True
        self.applied.emit()

    def closeEvent(self, event):  # noqa: N802 (Qt 命名)
        if not self._applied:
            self.cancelled.emit()
        # 关闭时若有升级后台任务：请求取消并短等收尾（防 QThread 销毁告警）
        th = self._engine_thread
        if th is not None and th.isRunning():
            ref = getattr(self, "_engine_worker_ref", None)
            if ref is not None:
                ref.cancel_requested = True
            th.wait(3000)
        # T-1022：模型下载任务同样随面板关闭取消（.part 保留，下次续传）
        mw = getattr(self, "_model_worker", None)
        if mw is not None and mw.isRunning():
            mw.cancel()
            mw.wait(3000)
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # 选项卡：通用
    # ------------------------------------------------------------------

    def _build_general_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setSpacing(10)

        # 启动时自动加载上次文件
        self.chk_auto_load_last = QCheckBox("启动时自动加载上次文件")
        self.chk_auto_load_last.setChecked(True)
        form.addRow("", self.chk_auto_load_last)

        # 自动播放
        self.chk_auto_play = QCheckBox("打开文件后自动播放")
        self.chk_auto_play.setChecked(False)
        form.addRow("", self.chk_auto_play)

        # 默认分析视图
        form.addRow(QLabel("默认分析视图："))
        self.cmb_default_view = QComboBox()
        self.cmb_default_view.addItem("波形", "waveform")
        self.cmb_default_view.addItem("FFT 频谱", "fft")
        self.cmb_default_view.addItem("语谱图", "spectrogram")
        self.cmb_default_view.addItem("音高", "pitch")
        self.cmb_default_view.addItem("共振峰", "formants")
        self.cmb_default_view.addItem("音色", "timbre")
        self.cmb_default_view.addItem("3D 频谱图", "spectrogram3d")
        form.addRow("", self.cmb_default_view)

        # A4 参考频率（T-921）：音分/音名换算基准，clamp 400–480，可一键恢复 440
        row_reference = QWidget()
        row_reference_layout = QHBoxLayout(row_reference)
        row_reference_layout.setContentsMargins(0, 0, 0, 0)
        row_reference_layout.setSpacing(8)
        self.spin_reference_hz = QDoubleSpinBox()
        self.spin_reference_hz.setObjectName("settingsReferenceHz")
        self.spin_reference_hz.setDecimals(1)
        self.spin_reference_hz.setSingleStep(0.5)
        self.spin_reference_hz.setRange(400.0, 480.0)
        self.spin_reference_hz.setValue(float(self._reference_hz))
        self.spin_reference_hz.setToolTip(tr("settings.reference_hz_hint"))
        self.btn_reference_restore = QPushButton(tr("settings.reference_hz_restore"))
        self.btn_reference_restore.setObjectName("settingsReferenceRestore")
        self.btn_reference_restore.setToolTip(tr("settings.reference_hz_hint"))
        self.btn_reference_restore.clicked.connect(self._restore_reference_hz)
        row_reference_layout.addWidget(self.spin_reference_hz)
        row_reference_layout.addWidget(self.btn_reference_restore)
        row_reference_layout.addStretch(1)
        form.addRow(tr("settings.reference_hz"), row_reference)

        return tab

    def _restore_reference_hz(self) -> None:
        """「恢复 440」：把 A4 参考频率置回 440.0 Hz（T-921）。"""
        self.spin_reference_hz.setValue(440.0)

    # ------------------------------------------------------------------
    # 选项卡：音频设备（参考 Audacity DevicePrefs）
    # ------------------------------------------------------------------

    def _build_audio_device_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        # --- 播放设备 ---
        play_box = QWidget()
        play_form = QFormLayout(play_box)
        play_form.setContentsMargins(0, 0, 0, 0)
        play_form.setSpacing(8)

        play_form.addRow(QLabel("<b>播放</b>"))

        self.cmb_play_device = QComboBox()
        self._populate_playback_devices()
        play_form.addRow("输出设备：", self.cmb_play_device)

        self.cmb_play_channels = QComboBox()
        self.cmb_play_channels.addItem("单声道 (Mono)", 1)
        self.cmb_play_channels.addItem("立体声 (Stereo)", 2)
        self.cmb_play_channels.setCurrentIndex(0)
        play_form.addRow("声道数：", self.cmb_play_channels)

        layout.addWidget(play_box)

        # --- 录音设备 ---
        rec_box = QWidget()
        rec_form = QFormLayout(rec_box)
        rec_form.setContentsMargins(0, 0, 0, 0)
        rec_form.setSpacing(8)

        rec_form.addRow(QLabel("<b>录音</b>"))

        self.cmb_record_device = QComboBox()
        self._populate_recording_devices()
        rec_form.addRow("输入设备：", self.cmb_record_device)

        self.cmb_record_channels = QComboBox()
        self.cmb_record_channels.addItem("单声道 (Mono)", 1)
        self.cmb_record_channels.addItem("立体声 (Stereo)", 2)
        self.cmb_record_channels.setCurrentIndex(0)
        rec_form.addRow("声道数：", self.cmb_record_channels)

        layout.addWidget(rec_box)

        # --- 质量 ---
        qual_box = QWidget()
        qual_form = QFormLayout(qual_box)
        qual_form.setContentsMargins(0, 0, 0, 0)
        qual_form.setSpacing(8)

        qual_form.addRow(QLabel("<b>采样率与质量</b>"))

        self.cmb_sample_rate = QComboBox()
        rates = [
            ("8000 Hz", 8000),
            ("11025 Hz", 11025),
            ("22050 Hz", 22050),
            ("44100 Hz (推荐)", 44100),
            ("48000 Hz", 48000),
            ("96000 Hz", 96000),
            ("192000 Hz", 192000),
        ]
        for label, rate in rates:
            self.cmb_sample_rate.addItem(label, rate)
        self.cmb_sample_rate.setCurrentIndex(3)  # 44100
        qual_form.addRow("默认采样率：", self.cmb_sample_rate)

        self.cmb_sample_format = QComboBox()
        self.cmb_sample_format.addItem("16-bit PCM", 16)
        self.cmb_sample_format.addItem("24-bit PCM", 24)
        self.cmb_sample_format.addItem("32-bit Float", 32)
        self.cmb_sample_format.setCurrentIndex(2)  # 32-bit Float
        qual_form.addRow("采样格式：", self.cmb_sample_format)

        layout.addWidget(qual_box)

        # --- 刷新按钮 ---
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_refresh_devices = QPushButton("刷新设备列表")
        self.btn_refresh_devices.clicked.connect(self._refresh_audio_devices)
        btn_row.addWidget(self.btn_refresh_devices)
        layout.addLayout(btn_row)

        layout.addStretch()
        return tab

    def _populate_playback_devices(self):
        """填充播放设备列表。"""
        self.cmb_play_device.clear()
        try:
            from PyQt6.QtMultimedia import QMediaDevices
            devices = QMediaDevices.audioOutputs()
            for d in devices:
                self.cmb_play_device.addItem(d.description(), d)
            if not devices:
                self.cmb_play_device.addItem("（无输出设备）", None)
        except Exception:
            self.cmb_play_device.addItem("（不可用）", None)

    def _populate_recording_devices(self):
        """填充录音设备列表。"""
        self.cmb_record_device.clear()
        try:
            from PyQt6.QtMultimedia import QMediaDevices
            devices = QMediaDevices.audioInputs()
            for d in devices:
                self.cmb_record_device.addItem(d.description(), d)
            if not devices:
                self.cmb_record_device.addItem("（无输入设备）", None)
        except Exception:
            self.cmb_record_device.addItem("（不可用）", None)

    def _refresh_audio_devices(self):
        """刷新音频设备列表。"""
        self._populate_playback_devices()
        self._populate_recording_devices()

    # ------------------------------------------------------------------
    # 选项卡：AI 设置
    # ------------------------------------------------------------------

    def _build_ai_tab(self) -> QWidget:
        """T-320：AI 设置 =「模型来源」三档单选。

        1. 内置模型（推荐）——零输入，仅一行只读状态（读现有 runtime/
           模型注册表接口；启动/下载属 T-316~T-319 链，不在本层实现）；
        2. 本地部署的模型——服务地址 / 模型名称 / 密钥三字段；
        3. 云端服务商——厂商下拉（预置地址与默认模型）+ 密钥 + 模型名
           + 自定义地址（仅「自定义」厂商显示地址输入）。

        旧配置构造时经 _ai_source_from_config() 平滑迁移到三档之一，
        ai_v2 旧键（mode/official_model/byom_*/llama_model_id）原样保留
        为备份，防回滚。
        """
        tab = QWidget()
        root = QVBoxLayout(tab)
        root.setSpacing(4)
        root.setContentsMargins(8, 8, 8, 8)

        source = self._ai_source_from_config()

        # ---- T-1022 §7：硬件探测结论（芯片 / 内存 / 磁盘可用；只读规格）----
        self.lbl_ai_probe = QLabel()
        self.lbl_ai_probe.setObjectName("aiProbeLine")
        self.lbl_ai_probe.setWordWrap(True)
        root.addWidget(self.lbl_ai_probe)
        self._refresh_ai_probe_line()

        # T-1033 P3：分组标题改走共用构件 SectionHeader（h3 + 8 上间距，ARCH §五-2）
        from acouscope.ui.widgets.panels.section_header import SectionHeader

        root.addWidget(SectionHeader(tr("settings.ai_source")))

        # ---- 档 1：内置模型（推荐）----
        self.rbtn_ai_builtin = QRadioButton(
            tr("settings.builtin") + tr("settings.builtin_reco"))
        self.rbtn_ai_builtin.setChecked(source == "builtin")
        self.rbtn_ai_builtin.toggled.connect(self._on_ai_source_changed)
        root.addWidget(self.rbtn_ai_builtin)
        lbl_builtin_hint = QLabel(tr("settings.builtin_hint"))
        root.addWidget(lbl_builtin_hint)

        # ---- T-319：内置档「本地模型版本」检查更新 / 恢复默认（零黑话）----
        self.grp_engine_state = QWidget()
        lay_eng = QVBoxLayout(self.grp_engine_state)
        lay_eng.setContentsMargins(18, 2, 0, 2)
        lay_eng.setSpacing(3)
        row_eng = QHBoxLayout()
        row_eng.setSpacing(8)
        self.lbl_engine_version = QLabel(self._engine_version_text())
        self.lbl_engine_version.setWordWrap(True)
        row_eng.addWidget(self.lbl_engine_version, 1)
        self.btn_engine_update = QPushButton(tr("settings.engine_check_updates"))
        self.btn_engine_update.clicked.connect(self._on_engine_update_clicked)
        if not self._engine_ops_supported():
            self.btn_engine_update.setEnabled(False)
        self.btn_engine_reset = QPushButton(tr("settings.engine_restore_default"))
        self.btn_engine_reset.clicked.connect(self._on_engine_reset_clicked)
        row_eng.addWidget(self.btn_engine_update)
        row_eng.addWidget(self.btn_engine_reset)
        lay_eng.addLayout(row_eng)
        self.lbl_engine_work = QLabel(tr("settings.engine_checking"))
        self.lbl_engine_work.setWordWrap(True)
        self.lbl_engine_work.setVisible(False)
        lay_eng.addWidget(self.lbl_engine_work)
        self.prog_engine = QProgressBar()
        self.prog_engine.setVisible(False)
        self.prog_engine.setTextVisible(False)
        lay_eng.addWidget(self.prog_engine)
        root.addWidget(self.grp_engine_state)

        self.lbl_ai_builtin_status = QLabel(self._builtin_status_text())
        self.lbl_ai_builtin_status.setWordWrap(True)
        root.addWidget(self.lbl_ai_builtin_status)

        # ---- T-1022 §7/§9.2③：推荐下载项（按硬件排序；纯文本模型不出现）----
        root.addWidget(SectionHeader(tr("settings.ai_models_title")))
        self.lst_ai_models = QListWidget()
        self.lst_ai_models.setObjectName("aiModelList")
        self.lst_ai_models.setMinimumHeight(
            self.fontMetrics().height() * _AI_MODEL_LIST_ROWS)
        self.lst_ai_models.currentRowChanged.connect(
            self._on_ai_model_selected)
        root.addWidget(self.lst_ai_models)
        row_model_btns = QHBoxLayout()
        row_model_btns.setSpacing(8)
        self.btn_ai_download = QPushButton(tr("settings.ai_download"))
        self.btn_ai_download.clicked.connect(self._on_ai_download_clicked)
        self.btn_ai_delete = QPushButton(tr("settings.ai_delete"))
        self.btn_ai_delete.clicked.connect(self._on_ai_delete_clicked)
        row_model_btns.addWidget(self.btn_ai_download)
        row_model_btns.addWidget(self.btn_ai_delete)
        row_model_btns.addStretch(1)
        root.addLayout(row_model_btns)
        self.prog_ai_model = QProgressBar()
        self.prog_ai_model.setObjectName("aiModelProgress")
        self.prog_ai_model.setTextVisible(False)
        self.prog_ai_model.setVisible(False)
        root.addWidget(self.prog_ai_model)
        self.lbl_ai_model_note = QLabel(tr("settings.ai_no_text_only"))
        self.lbl_ai_model_note.setWordWrap(True)
        root.addWidget(self.lbl_ai_model_note)
        self._refresh_ai_models()

        # ---- 档 2：本地部署的模型 ----
        self.rbtn_ai_self = QRadioButton(tr("settings.self_hosted"))
        self.rbtn_ai_self.setChecked(source == "self_hosted")
        self.rbtn_ai_self.toggled.connect(self._on_ai_source_changed)
        root.addWidget(self.rbtn_ai_self)
        lbl_self_hint = QLabel(tr("settings.self_hosted_hint"))
        lbl_self_hint.setWordWrap(True)
        root.addWidget(lbl_self_hint)
        self.grp_ai_self_fields = QWidget()
        form_self = QFormLayout(self.grp_ai_self_fields)
        form_self.setContentsMargins(18, 0, 0, 0)
        form_self.setSpacing(6)
        self.edit_self_url = QLineEdit()
        self.edit_self_url.setPlaceholderText("http://127.0.0.1:11434")
        self.edit_self_model = QLineEdit()
        self.edit_self_key = QLineEdit()
        self.edit_self_key.setEchoMode(QLineEdit.EchoMode.Password)
        form_self.addRow(tr("settings.ai_service_url"), self.edit_self_url)
        form_self.addRow(tr("settings.ai_model"), self.edit_self_model)
        form_self.addRow(tr("settings.ai_key"), self.edit_self_key)
        root.addWidget(self.grp_ai_self_fields)

        # ---- 档 3：云端服务商 ----
        self.rbtn_ai_cloud = QRadioButton(tr("settings.cloud"))
        self.rbtn_ai_cloud.setChecked(source == "cloud")
        self.rbtn_ai_cloud.toggled.connect(self._on_ai_source_changed)
        root.addWidget(self.rbtn_ai_cloud)
        lbl_cloud_hint = QLabel(tr("settings.cloud_hint"))
        root.addWidget(lbl_cloud_hint)
        self.grp_ai_cloud_fields = QWidget()
        form_cloud = QFormLayout(self.grp_ai_cloud_fields)
        form_cloud.setContentsMargins(18, 0, 0, 0)
        form_cloud.setSpacing(6)
        self.cmb_cloud_vendor = QComboBox()
        for pid in _CLOUD_VENDOR_IDS:
            info = PROVIDERS.get(pid)
            self.cmb_cloud_vendor.addItem(info.name if info else pid, pid)
        self.cmb_cloud_vendor.currentIndexChanged.connect(
            self._on_cloud_vendor_changed)
        self.edit_cloud_key = QLineEdit()
        self.edit_cloud_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_cloud_model = QLineEdit()
        self.edit_cloud_url = QLineEdit()
        self.edit_cloud_url.setPlaceholderText("https://api.example.com/v1")
        self._lbl_cloud_url = QLabel(tr("settings.ai_url"))
        form_cloud.addRow(tr("settings.ai_vendor"), self.cmb_cloud_vendor)
        form_cloud.addRow(tr("settings.ai_key"), self.edit_cloud_key)
        form_cloud.addRow(tr("settings.ai_model"), self.edit_cloud_model)
        form_cloud.addRow(self._lbl_cloud_url, self.edit_cloud_url)
        root.addWidget(self.grp_ai_cloud_fields)

        # 迁移预填：旧配置 → 对应档字段（仅预填，保存时才写回）
        self._prefill_from_legacy()

        # 发送图像开关（既有键 send_image，语义不变）
        self.chk_image = QCheckBox(tr("settings.ai_image"))
        self.chk_image.setChecked(bool(self._ai.get("send_image", True)))
        root.addWidget(self.chk_image)

        root.addStretch(1)
        self._update_source_fields_visibility()
        return tab

    # ------------------------------------------------------------------
    # T-320：三档状态 / 迁移 / 显隐
    # ------------------------------------------------------------------

    def _current_ai_source(self) -> str:
        """当前选中的模型来源档。"""
        if self.rbtn_ai_cloud.isChecked():
            return "cloud"
        if self.rbtn_ai_self.isChecked():
            return "self_hosted"
        return "builtin"

    def _on_ai_source_changed(self, checked: bool):
        """档间切换：互斥显隐 + 即时同步 ai_v2 新键 source。"""
        if not checked:
            return
        self._update_source_fields_visibility()
        self._ai.setdefault("ai_v2", {})["source"] = self._current_ai_source()

    def _update_source_fields_visibility(self):
        """仅显示当前档所需字段；不相关控件整体隐藏（禁残留干扰布局）。"""
        source = self._current_ai_source()
        self.lbl_ai_builtin_status.setVisible(source == "builtin")
        self.grp_engine_state.setVisible(source == "builtin")
        self.grp_ai_self_fields.setVisible(source == "self_hosted")
        self.grp_ai_cloud_fields.setVisible(source == "cloud")
        # 云端档内部：地址输入仅「自定义」厂商显示（命名厂商地址预置）
        pid = self.cmb_cloud_vendor.currentData() or "custom"
        self._lbl_cloud_url.setVisible(pid == "custom")
        self.edit_cloud_url.setVisible(pid == "custom")

    def _on_cloud_vendor_changed(self):
        """厂商切换：地址行显隐 + 模型名自动带出（可改，非默认值不覆盖）。"""
        pid = self.cmb_cloud_vendor.currentData() or "custom"
        info = PROVIDERS.get(pid)
        self._lbl_cloud_url.setVisible(pid == "custom")
        self.edit_cloud_url.setVisible(pid == "custom")
        prev = PROVIDERS.get(getattr(self, "_cloud_prev_vendor", "") or "")
        prev_default = prev.default_model if prev else ""
        cur = self.edit_cloud_model.text().strip()
        if info and info.default_model and (not cur or cur == prev_default):
            self.edit_cloud_model.setText(info.default_model)
        self._cloud_prev_vendor = pid

    def _ai_source_from_config(self) -> str:
        """旧配置 → 三档映射（T-320 迁移；只读不写，保守回退内置档）。

        - ai_v2.source 已就位（新结构）→ 直接采用；
        - 旧 external_ollama 开关 / 旧本地类 provider / openai+自建地址
          → 本地部署档；
        - 旧云端厂商 id → 云端档（已删厂商在预填时落 custom 兜底）；
        - 无法判定 → 内置档（保守不猜）。
        """
        v2 = self._ai.get("ai_v2")
        v2 = v2 if isinstance(v2, dict) else {}
        if v2.get("source") in ("builtin", "self_hosted", "cloud"):
            return v2["source"]
        provider = str(self._ai.get("provider", "ollama") or "ollama").strip()
        url = str(self._ai.get("url", "") or "").strip()
        if v2.get("external_ollama"):
            return "self_hosted"
        if provider == "ollama":
            return "builtin"
        if provider in _OLD_LOCAL_PROVIDERS:
            return "self_hosted"
        if provider == "openai" and _is_local_url(url):
            return "self_hosted"
        if provider in _OLD_CLOUD_PROVIDERS:
            return "cloud"
        return "builtin"

    def _prefill_from_legacy(self):
        """迁移预填：按旧配置填充对应档字段（自定义厂商保留旧地址）。"""
        v2 = self._ai.get("ai_v2")
        v2 = v2 if isinstance(v2, dict) else {}
        url = str(self._ai.get("url", "") or "").strip()
        model = str(self._ai.get("model", "") or "").strip()
        key = str(self._ai.get("key", "") or "").strip()
        provider = str(self._ai.get("provider", "ollama") or "ollama").strip()

        # 本地部署档：外部地址键优先，其次旧 url（自建地址场景）
        self.edit_self_url.setText(
            str(v2.get("external_ollama_url", "") or "").strip() or url)
        self.edit_self_model.setText(model)
        self.edit_self_key.setText(key)

        # 云端档：厂商（旧 id 已删 → custom 兜底，url/key/model 原样保留）
        self._cloud_prev_vendor = None
        vendor = provider if provider in _CLOUD_VENDOR_IDS else "custom"
        for i in range(self.cmb_cloud_vendor.count()):
            if self.cmb_cloud_vendor.itemData(i) == vendor:
                self.cmb_cloud_vendor.setCurrentIndex(i)
                break
        self.edit_cloud_key.setText(key)
        if vendor == "custom":
            self.edit_cloud_model.setText(model)
            self.edit_cloud_url.setText(url)
        else:
            self.edit_cloud_model.setText(model)

    def reload_ai_config(self, cfg=None):
        """T-1011：外部写回后刷新 AI 三档字段（释图面板 config_changed 联动）。

        按传入配置字典或重新读取 ai_config.json，重建三档单选项与字段内容，
        保留未保存的其它设置页状态不变。禁抛异常（联动副作用安全）。
        """
        if cfg is None:
            cfg = {}
            try:
                from acouscope.ai.interpreter import _load_config
                cfg = _load_config() or {}
            except Exception:
                pass
        if not isinstance(cfg, dict):
            cfg = {}
        self._ai = dict(cfg)
        source = self._ai_source_from_config()
        for s, rb in (("builtin", self.rbtn_ai_builtin),
                      ("self_hosted", self.rbtn_ai_self),
                      ("cloud", self.rbtn_ai_cloud)):
            rb.blockSignals(True)
            rb.setChecked(s == source)
            rb.blockSignals(False)
        self._prefill_from_legacy()
        self.chk_image.setChecked(bool(cfg.get("send_image", True)))
        v2 = self._ai.setdefault("ai_v2", {})
        if not isinstance(v2, dict):
            v2 = {}
            self._ai["ai_v2"] = v2
        v2["source"] = source
        self._update_source_fields_visibility()
        # T-1022 §7：探测结论 + 推荐列表随外部写回刷新
        if hasattr(self, "lbl_ai_probe"):
            self._refresh_ai_probe_line()
            self._refresh_ai_models()

    def _builtin_status_text(self) -> str:
        """内置档状态行（只读现有接口；拿不到状态时显示中性文案）。"""
        try:
            from acouscope.ai.backends.local_registry import (
                OFFICIAL_MODELS, get_missing_official_models, probe_ollama,
            )
            ok, models = probe_ollama()
            if not ok:
                return "首次使用时将自动启动内置模型服务并准备推荐模型。"
            missing = get_missing_official_models(models)
            if not missing:
                return "推荐模型已就绪，可直接开始释图。"
            total = sum(
                int(OFFICIAL_MODELS.get(m, {}).get("est_bytes", 0) or 0)
                for m in missing)
            size = (f"{total / 1_000_000_000:.1f} GB"
                    if total >= 1_000_000_000
                    else f"{round(total / 1_000_000)} MB")
            return f"首次使用时将自动下载推荐模型（约 {size}）。"
        except Exception:
            return "首次使用时将自动准备推荐模型。"

    # ------------------------------------------------------------------
    # T-319：内置档「本地模型版本」检查更新 / 恢复默认（零黑话）
    # ------------------------------------------------------------------

    def _engine_ops_supported(self) -> bool:
        """当前平台是否支持自动更新（macOS 通道；其余平台禁用更新按钮）。"""
        import sys as _sys
        return _sys.platform == "darwin"

    def _engine_version_text(self) -> str:
        """「本地模型版本」状态行（bundled → 随软件自带；用户级 → 版本号）。"""
        try:
            from acouscope.ai import ollama_engines as oe
            is_user, ver = oe.engine_state()
        except Exception:
            return tr("settings.engine_bundled")
        if is_user and ver:
            return tr("settings.engine_updated_to").format(version=ver)
        return tr("settings.engine_bundled")

    def _on_engine_update_clicked(self):
        """「检查更新」：后台线程全流程（检查→下载→校验→切换），非模态。"""
        if self._engine_busy or (
                self._engine_thread is not None
                and self._engine_thread.isRunning()):
            return
        self._engine_cancel = False
        worker = _EngineUpdateWorker()
        thread = QThread(self)
        worker.moveToThread(thread)
        self._engine_thread = thread
        self._engine_worker_ref = worker
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_engine_progress)
        worker.done.connect(self._on_engine_update_done)
        worker.done.connect(thread.quit)
        worker.done.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._engine_start_busy(tr("settings.engine_checking"))
        thread.start()

    def _on_engine_reset_clicked(self):
        """「恢复默认」：清指针回 bundled（保留已下载版本目录，可再切回）。"""
        if self._engine_busy:
            return
        from acouscope.ai import ollama_engines as oe
        try:
            oe.restore_default()
        except Exception:
            show_toast(self, tr("settings.engine_toast_failed"),
                       level="warning")
            return
        self.lbl_engine_version.setText(self._engine_version_text())
        show_toast(self, tr("settings.engine_toast_reset"))

    def _engine_start_busy(self, status: str):
        """进入忙碌态：更新按钮变「取消更新」，显示进行中文案 + 忙碌进度条。"""
        self._engine_busy = True
        try:
            self.btn_engine_update.clicked.disconnect(self._on_engine_update_clicked)
        except TypeError:
            pass
        self.btn_engine_update.setText(tr("settings.engine_cancel"))
        self.btn_engine_update.setEnabled(True)
        self.btn_engine_update.clicked.connect(self._engine_request_cancel)
        self.btn_engine_reset.setEnabled(False)
        self.lbl_engine_work.setText(status)
        self.lbl_engine_work.setVisible(True)
        self.prog_engine.setRange(0, 0)
        self.prog_engine.setVisible(True)

    def _engine_end_busy(self):
        """结束忙碌态：还原按钮文案/连接/可用态，隐藏进度区。"""
        self._engine_busy = False
        self._engine_thread = None
        self._engine_worker_ref = None
        try:
            self.btn_engine_update.clicked.disconnect(self._engine_request_cancel)
        except TypeError:
            pass
        self.btn_engine_update.setText(tr("settings.engine_check_updates"))
        self.btn_engine_update.setEnabled(self._engine_ops_supported())
        self.btn_engine_update.clicked.connect(self._on_engine_update_clicked)
        self.btn_engine_reset.setEnabled(True)
        self.lbl_engine_work.setVisible(False)
        self.prog_engine.setVisible(False)

    def _engine_request_cancel(self):
        """用户点「取消更新」：置取消位（下载链下个分块响应即中止）。"""
        self._engine_cancel = True
        ref = getattr(self, "_engine_worker_ref", None)
        if ref is not None:
            ref.cancel_requested = True
        self.btn_engine_update.setEnabled(False)
        self.lbl_engine_work.setText(tr("settings.engine_cancelled"))

    def _on_engine_progress(self, value: float):
        """进度回调（工作线程 → UI 队列）。有进度则切确定性进度条。"""
        if value is None:
            return
        self.prog_engine.setRange(0, 100)
        self.prog_engine.setValue(max(0, min(100, int(value * 100))))

    def _on_engine_update_done(self, code: str, version: str):
        """升级后台任务收尾：还原按钮 / 状态行刷新 / 温和提示（不弹模态）。"""
        self._engine_end_busy()
        self.lbl_engine_version.setText(self._engine_version_text())
        mapping = {
            "ok": ("settings.engine_toast_ok", "info"),
            "up_to_date": ("settings.engine_toast_latest", "info"),
            "no_network": ("settings.engine_toast_netfail", "warning"),
            "failed": ("settings.engine_toast_failed", "warning"),
            "cancelled": ("settings.engine_toast_cancelled", "info"),
            "unsupported": ("settings.engine_toast_unsupported", "info"),
        }
        key, level = mapping.get(code, ("settings.engine_toast_failed",
                                        "warning"))
        text = tr(key)
        if "{version}" in text and version:
            text = text.format(version=version)
        show_toast(self, text, level=level)

    # ------------------------------------------------------------------
    # T-1022 §7：硬件探测结论 + 推荐下载项（[下载]/[删除]）
    # ------------------------------------------------------------------

    def _refresh_ai_probe_line(self) -> None:
        """探测结论一行（芯片 / 内存 / 磁盘可用）；不可得 → 中性文案。"""
        spec = ""
        try:
            from acouscope.ai import hardware
            spec = hardware.probe(with_gpu=False).summary()
        except Exception:
            spec = ""
        self.lbl_ai_probe.setText(
            tr("settings.ai_probe_line").format(spec=spec)
            if spec else tr("ai_panel.hw_unknown"))

    def _refresh_ai_models(self) -> None:
        """重建推荐模型列表（按推荐排序 + 体积 + 已下载状态 + fit 徽标）。

        纯文本模型（`vision=False`）由 `ai.model_recommend` 硬过滤，
        **不会**出现在本列表（测试锁死）；下载链复用既有实现，不另写下载器。
        """
        if not hasattr(self, "lst_ai_models"):
            return
        try:
            from acouscope.ui.widgets import ai_interpret as aip
            recs = aip.recommendations(bool(aip.remote_service_hint()))
            installed = aip.installed_ollama_names()
        except Exception:
            recs, installed = (), set()
        self.lst_ai_models.blockSignals(True)
        self.lst_ai_models.clear()
        for rec in recs:
            entry = rec.entry
            downloaded = aip.entry_is_downloaded(entry, installed)
            parts = [entry.display_name, aip.entry_size_text(entry),
                     tr("ai_panel.tag_vision"),
                     tr("ai_panel.state_downloaded") if downloaded
                     else tr("ai_panel.state_not_downloaded")]
            fit_key = _AI_FIT_KEYS.get(rec.fit, "")
            if fit_key:
                parts.append(tr(fit_key))
            item = QListWidgetItem(" · ".join(p for p in parts if p))
            item.setData(Qt.ItemDataRole.UserRole,
                         {"entry": entry, "downloaded": downloaded})
            self.lst_ai_models.addItem(item)
        self.lst_ai_models.blockSignals(False)
        self._on_ai_model_selected(self.lst_ai_models.currentRow())

    def _selected_ai_model(self) -> dict | None:
        """当前选中条目的载荷（{entry, downloaded}）；无选中 → None。"""
        if not hasattr(self, "lst_ai_models"):
            return None
        item = self.lst_ai_models.currentItem()
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, dict) else None

    def _on_ai_model_selected(self, _row: int) -> None:
        """选中态 → 按钮可用性（未下载可下载；已下载可删除）。"""
        if not hasattr(self, "btn_ai_download"):
            return
        info = self._selected_ai_model()
        busy = (self._model_worker is not None
                and self._model_worker.isRunning())
        self.btn_ai_download.setEnabled(
            info is not None and not info["downloaded"] and not busy)
        self.btn_ai_delete.setEnabled(
            info is not None and bool(info["downloaded"]) and not busy)

    def _on_ai_download_clicked(self) -> None:
        """[下载] 选中模型（后台线程 + 内联进度 + toast；复用既有下载链）。"""
        info = self._selected_ai_model()
        if info is None:
            return
        entry = info["entry"]
        if self._model_worker is not None and self._model_worker.isRunning():
            show_toast(self, tr("ai_panel.download_busy"), level="warning")
            return
        try:
            from acouscope.ui.widgets.ai_interpret import ModelDownloadWorker
        except Exception:
            return
        worker = ModelDownloadWorker(entry, self)
        self._model_worker = worker
        self.prog_ai_model.setValue(0)
        self.prog_ai_model.setVisible(True)
        self.btn_ai_download.setEnabled(False)
        show_toast(self, tr("ai_panel.download_started").format(
            model=entry.display_name))
        worker.progressed.connect(
            lambda v: self.prog_ai_model.setValue(max(0, min(100, int(v * 100)))))
        worker.finished_one.connect(self._on_ai_download_done)
        worker.failed_one.connect(self._on_ai_download_failed)
        worker.start()

    def _on_ai_download_done(self, _model_id: str) -> None:
        self.prog_ai_model.setVisible(False)
        entry = getattr(self._model_worker, "entry", None)
        show_toast(self, tr("ai_panel.download_done").format(
            model=getattr(entry, "display_name", "")))
        self._refresh_ai_models()

    def _on_ai_download_failed(self, msg: str) -> None:
        self.prog_ai_model.setVisible(False)
        show_toast(self, msg, level="warning")
        self._refresh_ai_models()

    def _on_ai_delete_clicked(self) -> None:
        """[删除模型文件] 用户**显式**删除（与「卸载模型」＝停进程释放内存区分）。"""
        info = self._selected_ai_model()
        if info is None:
            return
        try:
            from acouscope.ui.widgets import ai_interpret as aip
            ok = aip.delete_entry(info["entry"])
        except Exception:
            ok = False
        show_toast(self, tr("settings.ai_delete_done") if ok
                   else tr("settings.ai_delete_failed"),
                   level="info" if ok else "warning")
        self._refresh_ai_models()

    def _builtin_model(self) -> str:
        """内置档自动模型：官方严选注册表内优先（byom 旧键其次）。"""
        from acouscope.ai.backends.local_registry import OFFICIAL_MODELS
        v2 = self._ai.get("ai_v2")
        v2 = v2 if isinstance(v2, dict) else {}
        if v2.get("mode") == "byom" and str(v2.get("byom_model", "") or ""):
            return str(v2["byom_model"])
        cur = str(self._ai.get("model", "") or "").strip()
        if cur in OFFICIAL_MODELS:
            return cur
        old = str(v2.get("official_model", "") or "")
        if old in OFFICIAL_MODELS:
            return old
        return next((k for k, m in OFFICIAL_MODELS.items() if m.get("is_default")),
                    next(iter(OFFICIAL_MODELS), "spark-x2.5-1.7b"))

    # ------------------------------------------------------------------
    # 选项卡：界面
    # ------------------------------------------------------------------

    def _build_interface_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setSpacing(10)

        # 语言选择
        self.cmb_language = QComboBox()
        for code, name in available_languages().items():
            self.cmb_language.addItem(name, code)
            if code == self._lang:
                self.cmb_language.setCurrentIndex(self.cmb_language.count() - 1)
        form.addRow(tr("settings.language"), self.cmb_language)

        # 主题（跟随系统 + 9 套配色；切换即时预览生效，确定后持久化）
        # T-1031 曝光收敛：展示分组——主区 3 项（跟随系统/深色/浅色）+ 次级区「更多配色」；
        #   选中行为 / 持久化键 / apply_theme 调用路径零变化（仅展示分组，条目一个不少）。
        from PyQt6.QtGui import QStandardItem, QStandardItemModel

        from acouscope.ui.theme import THEME_ORDER, apply_theme, theme_swatch

        _primary_ids = ("system", "dark", "light")
        _primary = [t for t in _primary_ids if t in THEME_ORDER]
        _secondary = [t for t in THEME_ORDER if t not in _primary_ids]
        self.cmb_theme = QComboBox()
        _model = QStandardItemModel(self.cmb_theme)
        for _group_key, _ids in (("settings.theme.group.basic", _primary),
                                 ("settings.theme.group.more", _secondary)):
            _head = QStandardItem(tr(_group_key))
            _head.setFlags(Qt.ItemFlag.NoItemFlags)  # 分组标题：不可选/不可聚焦
            _model.appendRow(_head)
            for _tid in _ids:
                _item = QStandardItem(theme_swatch(_tid), tr(f"settings.theme.{_tid}"))
                _item.setData(_tid, Qt.ItemDataRole.UserRole)
                _model.appendRow(_item)
        self.cmb_theme.setModel(_model)
        idx = self.cmb_theme.findData(self._theme)
        if idx >= 0:
            self.cmb_theme.setCurrentIndex(idx)
        self.cmb_theme.currentIndexChanged.connect(
            lambda i: apply_theme(self.cmb_theme.itemData(i)))
        form.addRow(tr("settings.theme"), self.cmb_theme)

        # T-1001：图标风格（三套脚本派生 + generic 兜底；切换即预览，应用才持久化）
        from acouscope.ui.theme import (
            ICON_STYLES,
            icon_style,
            style_icon,
            style_when_theme,
        )

        self._icon_style_at_open = icon_style()
        self.cmb_icon_style = QComboBox()
        for sid in ICON_STYLES:
            # 下拉项自带该风格代表图标（theme_swatch 同款：图标 + i18n 文案）
            self.cmb_icon_style.addItem(
                style_icon(sid, self._ICON_PREVIEW_NAMES[0]),
                tr(f"settings.icon_style.{sid}"),
                sid,
            )
        idx_icon = self.cmb_icon_style.findData(self._icon_style_at_open)
        if idx_icon >= 0:
            self.cmb_icon_style.setCurrentIndex(idx_icon)
        form.addRow(tr("settings.icon_style"), self.cmb_icon_style)
        form.addRow("", self._build_icon_preview())
        # 接线在填充/选中之后（避免构造期把实时风格改掉，同 cmb_theme 口径）
        self.cmb_icon_style.currentIndexChanged.connect(self._on_icon_style_changed)

        hint_icon = QLabel(tr("settings.icon_style.hint"))
        hint_icon.setWordWrap(True)
        style_when_theme(hint_icon, lambda c: f"color: {c['sub']};")
        form.addRow("", hint_icon)

        # 字体大小
        form.addRow(QLabel("界面字体大小："))
        self.cmb_font_size = QComboBox()
        sizes = [("小", 11), ("默认", 13), ("大", 15), ("特大", 17)]
        for label, size in sizes:
            self.cmb_font_size.addItem(label, size)
        self.cmb_font_size.setCurrentIndex(1)  # 默认 13
        form.addRow("", self.cmb_font_size)

        # 显示网格
        self.chk_show_grid = QCheckBox("显示图表网格")
        self.chk_show_grid.setChecked(True)
        form.addRow("", self.chk_show_grid)

        # 动画效果
        self.chk_animations = QCheckBox("启用界面动画")
        self.chk_animations.setChecked(True)
        form.addRow("", self.chk_animations)

        hint = QLabel(tr("settings.lang_hint"))
        from acouscope.ui.theme import TOKENS, style_when_theme

        # T-1033 P6：字号改走 TOKENS.typography.body_sm（禁字面 px）
        style_when_theme(
            hint,
            lambda c: (
                f"color: {c['sub']}; "
                f"font-size: {TOKENS['typography']['body_sm']}px;"
            ),
        )
        hint.setWordWrap(True)
        form.addRow("", hint)

        return tab

    # ------------------------------------------------------------------
    # T-1001：图标风格（缩略预览 / 应用持久化 / 取消回滚）
    # ------------------------------------------------------------------

    def _build_icon_preview(self) -> QWidget:
        """当前风格代表图标缩略预览行（4 枚，与下拉项同款渲染）。"""
        from acouscope.ui.theme import TOKENS

        row = QWidget(self)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(TOKENS["spacing"]["xs"])
        self._icon_preview_labels = []
        for _name in self._ICON_PREVIEW_NAMES:
            lbl = QLabel(row)
            self._icon_preview_labels.append(lbl)
            lay.addWidget(lbl)
        lay.addStretch(1)
        self._refresh_icon_preview()
        return row

    def _refresh_icon_preview(self) -> None:
        """按当前选中风格重绘缩略预览（色值取当前主题语义色）。"""
        from acouscope.ui.theme import style_icon

        labels = getattr(self, "_icon_preview_labels", [])
        style = self.icon_style()
        size = self._ICON_PREVIEW_SIZE
        for lbl, name in zip(labels, self._ICON_PREVIEW_NAMES):
            lbl.setPixmap(style_icon(style, name, size).pixmap(size, size))

    def _on_icon_style_changed(self, _index: int = 0) -> None:
        """下拉切换即预览：立即换风格（含全窗刷新）并同步缩略预览。"""
        from acouscope.ui.theme import set_icon_style

        set_icon_style(self.icon_style())
        self._refresh_icon_preview()

    def _persist_icon_style(self) -> None:
        """「应用」：当前风格写入 settings.json（best-effort，同 main_window 持久化口径）。"""
        from acouscope.ui.theme import set_icon_style

        style = self.icon_style()
        set_icon_style(style)
        try:
            from acouscope.utils.config import Settings

            settings = Settings.load()
            settings.icon_style = style
            settings.save()
        except Exception:
            pass  # 落盘失败（如目录只读）：会话内风格已生效，仅不持久化

    def _revert_icon_style(self) -> None:
        """未应用即关闭：回滚到打开时的风格（撤销会话内预览）。"""
        if self.icon_style() == self._icon_style_at_open:
            return
        idx = self.cmb_icon_style.findData(self._icon_style_at_open)
        if idx >= 0:
            self.cmb_icon_style.setCurrentIndex(idx)  # → 切换槽内回滚全窗图标

    # ------------------------------------------------------------------
    # 选项卡：导出
    # ------------------------------------------------------------------

    def _build_export_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setSpacing(10)

        self.cmb_format = QComboBox()
        for key, _ in FORMATS:
            self.cmb_format.addItem(tr(f"fmt.{key}"), key)
        idx = self.cmb_format.findData(self._fmt)
        if idx >= 0:
            self.cmb_format.setCurrentIndex(idx)
        form.addRow(tr("settings.export_format"), self.cmb_format)

        self.cmb_dpi = QComboBox()
        for dpi in DPI_OPTIONS:
            self.cmb_dpi.addItem(tr(f"settings.dpi.{dpi}"), dpi)
        idx = self.cmb_dpi.findData(self._dpi)
        if idx >= 0:
            self.cmb_dpi.setCurrentIndex(idx)
        form.addRow(tr("settings.export_dpi"), self.cmb_dpi)

        return tab

    # ------------------------------------------------------------------
    # 选项卡：快捷键
    # ------------------------------------------------------------------

    def _build_shortcuts_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(8)

        # 分类选择
        cat_row = QHBoxLayout()
        cat_row.addWidget(QLabel("分类："))
        self.cmb_shortcut_category = QComboBox()
        self.cmb_shortcut_category.addItem("全部", "all")
        self.cmb_shortcut_category.addItem("通用", "global")
        self.cmb_shortcut_category.addItem("频谱图", "spectrogram")
        self.cmb_shortcut_category.addItem("波形", "waveform")
        self.cmb_shortcut_category.addItem("音色", "timbre")
        self.cmb_shortcut_category.addItem("音高", "pitch")
        self.cmb_shortcut_category.addItem("AI 释图", "ai_interpret")
        self.cmb_shortcut_category.currentIndexChanged.connect(self._filter_shortcuts)
        cat_row.addWidget(self.cmb_shortcut_category)
        cat_row.addStretch()

        # 重置按钮
        self.btn_reset_shortcut = QPushButton("恢复默认")
        self.btn_reset_shortcut.clicked.connect(self._reset_selected_shortcut)
        cat_row.addWidget(self.btn_reset_shortcut)

        layout.addLayout(cat_row)

        # 快捷键列表
        self.shortcut_table = QTableWidget(0, 3)
        self.shortcut_table.setHorizontalHeaderLabels(["功能", "分类", "快捷键"])
        self.shortcut_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.shortcut_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.shortcut_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.shortcut_table.verticalHeader().setVisible(False)
        self.shortcut_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.shortcut_table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.SelectedClicked
        )
        self.shortcut_table.itemChanged.connect(self._on_shortcut_edited)
        layout.addWidget(self.shortcut_table, stretch=1)

        # 提示
        hint = QLabel(
            "双击「快捷键」列可修改按键。按 Esc 取消，按 Enter 确认。"
        )
        # T-1033 P6：色改 colors()['text_sub']、字号走令牌，且必须经
        # style_when_theme（禁绕过主题的裸样式表调用，ARCH §八）
        from acouscope.ui.theme import TOKENS, style_when_theme

        style_when_theme(
            hint,
            lambda c: (
                f"color: {c['sub']}; "
                f"font-size: {TOKENS['typography']['body_sm']}px;"
            ),
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # 延迟加载（等主窗口注册完快捷键）
        QTimer.singleShot(0, self._load_shortcuts)

        return tab

    def _load_shortcuts(self):
        """从 ShortcutManager 加载快捷键列表。"""
        try:
            from acouscope.ui.shortcuts import ShortcutManager
            mgr = ShortcutManager.instance()
            entries = mgr.all_entries()
        except Exception:
            entries = []

        self.shortcut_table.blockSignals(True)
        self.shortcut_table.setRowCount(0)

        for entry in entries:
            row = self.shortcut_table.rowCount()
            self.shortcut_table.insertRow(row)

            # 功能名
            item_label = QTableWidgetItem(entry.label)
            item_label.setData(Qt.ItemDataRole.UserRole, entry.action_id)
            item_label.setFlags(item_label.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.shortcut_table.setItem(row, 0, item_label)

            # 分类
            cat_text = "通用"
            item_cat = QTableWidgetItem(cat_text)
            item_cat.setData(Qt.ItemDataRole.UserRole, entry.category)
            item_cat.setFlags(item_cat.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.shortcut_table.setItem(row, 1, item_cat)

            # 快捷键
            item_key = QTableWidgetItem(entry.current_key)
            item_key.setData(Qt.ItemDataRole.UserRole, entry.action_id)
            self.shortcut_table.setItem(row, 2, item_key)

        self.shortcut_table.blockSignals(False)
        self._filter_shortcuts()

    def _filter_shortcuts(self):
        """按分类过滤快捷键列表。"""
        cat = self.cmb_shortcut_category.currentData()
        for row in range(self.shortcut_table.rowCount()):
            cat_item = self.shortcut_table.item(row, 1)
            entry_cat = cat_item.data(Qt.ItemDataRole.UserRole)
            entry_feature = cat_item.text()

            if cat == "all":
                show = True
            elif cat == "global":
                show = entry_cat == "global"
            else:
                show = entry_feature == cat

            self.shortcut_table.setRowHidden(row, not show)

    def _on_shortcut_edited(self, item: QTableWidgetItem):
        """快捷键编辑完成。"""
        if item.column() != 2:
            return

        action_id = item.data(Qt.ItemDataRole.UserRole)
        new_key = item.text().strip()

        if not new_key:
            item.setText(item.text())  # 保持原值
            return

        # 验证按键合法性
        try:
            seq = QKeySequence(new_key)
            if seq.isEmpty():
                raise ValueError("empty")
        except Exception:
            show_toast(self, f"「{new_key}」不是有效的快捷键。", level="warning")
            # 恢复原值
            try:
                from acouscope.ui.shortcuts import ShortcutManager
                mgr = ShortcutManager.instance()
                entries = mgr.all_entries()
                for e in entries:
                    if e.action_id == action_id:
                        item.setText(e.current_key)
                        break
            except Exception:
                pass
            return

        # 应用新快捷键
        try:
            from acouscope.ui.shortcuts import ShortcutManager
            mgr = ShortcutManager.instance()
            if mgr.set_key(action_id, new_key):
                show_toast(self, f"快捷键已更新为：{new_key}", level="success")
            else:
                show_toast(self, "无法修改该快捷键。", level="warning")
        except Exception as e:
            show_toast(self, str(e), level="warning")

    def _reset_selected_shortcut(self):
        """恢复选中快捷键为默认值。"""
        current_row = self.shortcut_table.currentRow()
        if current_row < 0:
            return

        item = self.shortcut_table.item(current_row, 2)
        if not item:
            return

        action_id = item.data(Qt.ItemDataRole.UserRole)
        try:
            from acouscope.ui.shortcuts import ShortcutManager
            mgr = ShortcutManager.instance()
            if mgr.reset_key(action_id):
                entries = mgr.all_entries()
                for e in entries:
                    if e.action_id == action_id:
                        self.shortcut_table.blockSignals(True)
                        item.setText(e.current_key)
                        self.shortcut_table.blockSignals(False)
                        break
                show_toast(self, "快捷键已恢复为默认值。", level="success")
        except Exception as e:
            show_toast(self, str(e), level="warning")

    # ------------------------------------------------------------------
    # 取值方法
    # ------------------------------------------------------------------

    def language(self) -> str:
        return self.cmb_language.currentData() or "en_US"

    def ai_config(self) -> dict:
        """T-320：按当前档输出既有 5 键 + ai_v2（旧键全量保留为备份）。

        - builtin：provider=ollama + url 空（释图面板注入内置实例动态端口）；
        - self_hosted：provider=custom + 服务地址（任意 OpenAI 兼容自建地址；
          external_ollama* 旧键同步，供旧链路与回滚使用）；
        - cloud：provider=厂商 id + 预置地址（custom 档用用户手填地址）。
        """
        source = self._current_ai_source()
        # ai_v2 旧键（mode/official_model/byom_*/llama_model_id 等）原样保留，
        # 仅覆盖三档新键（source / external_ollama*）——防回滚（任务书规格 3）。
        v2 = dict(self._ai.get("ai_v2") or {})
        if source == "self_hosted":
            provider = "custom"
            url = self.edit_self_url.text().strip()
            model = self.edit_self_model.text().strip()
            key = self.edit_self_key.text().strip()
            v2.update({"source": "self_hosted",
                       "external_ollama": True,
                       "external_ollama_url": url})
        elif source == "cloud":
            provider = self.cmb_cloud_vendor.currentData() or "custom"
            info = PROVIDERS.get(provider)
            key = self.edit_cloud_key.text().strip()
            model = self.edit_cloud_model.text().strip()
            if provider == "custom":
                url = self.edit_cloud_url.text().strip()
            else:
                url = info.base_url if info else ""
            v2.update({"source": "cloud",
                       "external_ollama": False,
                       "external_ollama_url": ""})
        else:  # builtin
            provider, url, key = "ollama", "", ""
            model = self._builtin_model()
            v2.update({"source": "builtin",
                       "external_ollama": False,
                       "external_ollama_url": ""})
        return {
            "provider": provider,
            "url": url,
            "model": model,
            "key": key,
            "send_image": self.chk_image.isChecked(),
            "ai_v2": v2,
        }

    def switch_to_tab(self, tab_name: str):
        """切换到指定设置页（T-1013 两栏：左导航选中 + 右内容栈同步）。

        Args:
            tab_name: "general", "audio", "ai", "interface", "shortcuts", "export"
        """
        tab_map = {
            "general": 0,
            "audio": 1,
            "ai": 2,
            "interface": 3,
            "shortcuts": 4,
            "export": 5,
        }
        idx = tab_map.get(tab_name, 0)
        if idx != self.nav_list.currentRow():
            self.nav_list.setCurrentRow(idx)  # 触发 _on_nav_row_changed 同步
        self.stack.setCurrentIndex(idx)

    def _on_nav_row_changed(self, row: int) -> None:
        """左导航选中行 → 右内容页栈切换（T-1013）。"""
        if 0 <= row < self.stack.count():
            self.stack.setCurrentIndex(row)

    def theme(self) -> str:
        return self.cmb_theme.currentData() or "default"

    def icon_style(self) -> str:
        """T-1001：图标风格取值（下拉 data；缺省 generic 兜底）。"""
        return self.cmb_icon_style.currentData() or "generic"

    def default_format(self) -> str:
        return self.cmb_format.currentData() or "svg"

    def default_dpi(self) -> int:
        return int(self.cmb_dpi.currentData() or 300)

    def reference_hz(self) -> float:
        """A4 参考频率（Hz）；取值由控件 clamp 在 400–480（T-921）。"""
        return float(self.spin_reference_hz.value())
