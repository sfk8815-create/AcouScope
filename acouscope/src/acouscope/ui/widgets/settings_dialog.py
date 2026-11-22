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

import json
from PyQt6.QtCore import Qt, QSize, QTimer, QObject, QThread, pyqtSignal, QPoint, QRect
from PyQt6.QtGui import QColor, QKeySequence, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QGridLayout,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QComboBox,
    QCheckBox,
    QFrame,
    QLineEdit,
    QLabel,
    QAbstractScrollArea,
    QScrollArea,
    QListWidget,
    QStackedWidget,
    QWidget,
    QTableWidget,
    QTableWidgetItem,
    QListWidgetItem,
    QHeaderView,
    QLayout,
    QPushButton,
    QProgressBar,
    QRadioButton,
    QSlider,
)

from acouscope.ai.interpreter import PROVIDERS
from acouscope.i18n import tr, available_languages
from acouscope.ui import theme
from acouscope.ui.widgets.param_spin import ParamSpinBox
from acouscope.ui.shortcuts import display_key, unmap_key
from acouscope.ui.widgets.toast import show_toast

# 与 exporters.FigureExporter.SUPPORTED_FORMATS 对齐
FORMATS = [
    ("svg", "svg"),
    ("png", "png"),
    ("pdf", "pdf"),
    ("eps", "eps"),
]

DPI_OPTIONS = [150, 300, 600, 1200]

# T-1047：A4 快捷基准 chip 预设（Hz；数值即载荷 → 无需 i18n 文案）
_A4_PRESETS = (415.0, 432.0, 440.0, 442.0)
# G5：A4 交互滑块的整数刻度倍率（QSlider 只有整数，1 步 = 0.1 Hz，与数值框
# decimals=1 对齐，避免 0.5 步进时的取整漂移）
_A4_SLIDER_SCALE = 10

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


# ----------------------------------------------------------------------
# T-1047 参数控件规范构件（ARCH §五-7 三段式 / §五-8 范围可见性 /
# §五-4 状态点 / §六-11 chip 激活态 / §四 数值等宽与数值层级）。
# 尺寸与透明度唯一源 = theme.TOKENS["param"]；色值一律取 theme.colors() 或
# theme.TOKENS["semantic"]（本文件内 hex / 字面 px = 0）。
# 说明：本单授权面未含新源文件，构件落于本文件（主战场），检视器按同套规范复用。
# ----------------------------------------------------------------------

# 数值与单位之间的窄不换行空格（ARCH §四「单位与数值间」）
NBSP_THIN = "\u202f"


def _param_qss(c: dict) -> str:
    """参数构件样式：名称（text）/ 单位与说明（text_sub）/ 读数框（等宽 text）。"""
    ty = theme.TOKENS["typography"]
    rm = theme.TOKENS["radius"]
    el = theme.TOKENS["elevation"]
    prm = theme.TOKENS["param"]
    return (
        "QLabel#paramName {"
        f"  color: {c['text']};"
        f"  font-size: {ty['body_sm']}px;"
        "}"
        "QLabel#paramUnit, QLabel#paramReadoutName {"
        f"  color: {c['sub']};"
        f"  font-size: {ty['caption']}px;"
        "}"
        "QLabel#paramReadoutValue {"
        f"  color: {c['text']};"
        f"  font-family: {theme.ui_mono_family_qss()};"
        f"  font-size: {ty['caption']}px;"
        f"  background: {c['bg2']};"
        f"  border: {el['border']}px solid {c['border']};"
        f"  border-radius: {rm['sm']}px;"
        f"  padding: {prm['box_pad_y']}px {prm['box_pad_x']}px;"
        "}"
    )


class LedDot(QWidget):
    """状态点（LED 式 · ARCH §五-4）：小圆点 + 令牌色；禁发光/渐变/动画。"""

    _STATE_ROLE = {
        "ready": "success", "on": "success", "warn": "warning",
        "error": "error", "off": "text_faint",
    }

    def __init__(self, state: str = "off", parent=None):
        super().__init__(parent)
        self.setObjectName("paramLedDot")
        dot = theme.TOKENS["param"]["led_dot"]
        self.setFixedSize(dot, dot)
        self._state = state if state in self._STATE_ROLE else "off"
        self._color = ""      # 由首次 style_when_theme 回调按令牌填色
        theme.style_when_theme(self, self._on_theme)

    def state(self) -> str:
        """当前状态名（ready/on/warn/error/off）。"""
        return self._state

    def role(self) -> str:
        """当前状态对应的令牌角色名。"""
        return self._STATE_ROLE[self._state]

    def color(self) -> str:
        """当前状态点色值（取自令牌，非字面量）。"""
        return self._color

    def set_state(self, state: str) -> None:
        self._state = state if state in self._STATE_ROLE else "off"
        self._on_theme(theme.colors())

    def _on_theme(self, c: dict) -> str:
        role = self._STATE_ROLE[self._state]
        self._color = c.get(role) or theme.TOKENS["semantic"][role]
        self.update()
        return ""

    def paintEvent(self, event):  # noqa: N802 (Qt 命名)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._color))
        p.drawEllipse(self.rect())


class ChipButton(QPushButton):
    """状态 chip（ARCH §五-6 / §六-11）：激活 = **底色存在**（accent 低 alpha 底 + accent 字）；
    未激活 = 中性底 + text_sub 字；**禁**描边或纯色文字表达激活。"""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("paramChip")
        self.setCheckable(True)
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # 供像素级判据取期望底色（激活/未激活两态）
        self._qss_active_bg = ""
        self._qss_idle_bg = ""
        self._refresh = theme.style_when_theme(self, self._build_qss)
        self.toggled.connect(lambda _on: self._refresh())

    def active_bg(self) -> str:
        """激活态底色（accent + 低 alpha，微透明 → 与未激活底色必然不同）。"""
        return self._qss_active_bg

    def idle_bg(self) -> str:
        """未激活态底色（中性，无描边）。"""
        return self._qss_idle_bg

    def _build_qss(self, c: dict) -> str:
        ty = theme.TOKENS["typography"]
        rm = theme.TOKENS["radius"]
        prm = theme.TOKENS["param"]
        tint = QColor(c["accent"])
        tint.setAlpha(int(prm["chip_alpha"]))
        self._qss_active_bg = tint.name(QColor.NameFormat.HexArgb)
        self._qss_idle_bg = c["bg2"]
        alpha = tint.alpha()
        return (
            "QPushButton#paramChip {"
            f"  background: {c['bg2']};"
            f"  color: {c['sub']};"
            "  border: none;"
            f"  border-radius: {rm['pill']}px;"
            f"  padding: {prm['chip_pad_y']}px {prm['chip_pad_x']}px;"
            f"  font-size: {ty['body_sm']}px;"
            "}"
            "QPushButton#paramChip:checked {"
            f"  background: rgba({tint.red()}, {tint.green()}, {tint.blue()}, {alpha});"
            f"  color: {c['accent']};"
            "}"
        )


class _FlowLayout(QLayout):
    """换行布局：最小宽 = 单子最小宽，整行 chip 不再顶宽窄栏页最小宽（M4）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list = []
        self._spacing = theme.TOKENS["spacing"]["xs"]

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._place(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        return size + QSize(left + right, top + bottom)

    def _place(self, rect, test_only):
        left, top, right, bottom = self.getContentsMargins()
        x = rect.x() + left
        y = rect.y() + top
        line_h = 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._spacing
            if next_x - self._spacing > rect.right() - right and line_h:
                x = rect.x() + left
                y += line_h + self._spacing
                next_x = x + hint.width() + self._spacing
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(x, y, hint.width(), hint.height()))
            x = next_x
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + bottom


class ChipGroup(QWidget):
    """互斥 chip 组（ARCH §五-6：同一应用内只允许一套激活语义）。

    激活态**唯一**；`chipActivated` 带出该 chip 的载荷（载荷为 None 时组内无激活项）。
    """

    chipActivated = pyqtSignal(object)

    def __init__(self, items, parent=None):
        """items: 序列，元素 = (文案, 载荷)。"""
        super().__init__(parent)
        self.setObjectName("paramChipGroup")
        row = _FlowLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self._payloads: dict[ChipButton, object] = {}
        self.chips: list[ChipButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(False)
        for text, payload in items:
            chip = ChipButton(text, self)
            self._payloads[chip] = payload
            self._group.addButton(chip)
            self.chips.append(chip)
            chip.clicked.connect(lambda _c=False, ch=chip: self._on_click(ch))
            row.addWidget(chip)

    def set_exclusive(self, on: bool = True) -> None:
        """点选排他开关（G5）：交给 QButtonGroup 的排他机制，语义 = 单选。

        默认 `exclusive=False` + 点击后手工取消其余（等效互斥，且保留
        `set_current(None)` 的「全部熄灭」语义）；本轮显式为 A4 快捷基准开启真互斥。
        """
        self._group.setExclusive(bool(on))

    def payload_of(self, chip: ChipButton):
        """某 chip 的载荷。"""
        return self._payloads.get(chip)

    def checked_chip(self) -> ChipButton | None:
        """当前激活 chip（无激活 → None）。"""
        for chip in self.chips:
            if chip.isChecked():
                return chip
        return None

    def current(self):
        """当前激活载荷（无激活 → None）。"""
        chip = self.checked_chip()
        return None if chip is None else self._payloads.get(chip)

    def set_current(self, payload) -> None:
        """按载荷置激活项（载荷不匹配 → 全部取消激活）。"""
        for chip in self.chips:
            chip.setChecked(self._payloads.get(chip) == payload)

    def _on_click(self, chip: ChipButton) -> None:
        for other in self.chips:
            other.setChecked(other is chip)
        self.chipActivated.emit(self._payloads.get(chip))


class RangeHint(QWidget):
    """参数范围线索（ARCH §五-8 / §六-13）：端点数值标签 + 稀疏刻度。

    `ticks` = ((值, 标签或 None), ...)，须含范围两端点；**只标端点 + 少数关键点**
    （标签为 None 的刻度只画线不写数 → 非逐刻度标注）。
    """

    def __init__(self, ticks, parent=None):
        super().__init__(parent)
        self.setObjectName("paramRangeHint")
        prm = theme.TOKENS["param"]
        self.setFixedHeight(prm["range_h"])
        self._ticks = tuple(
            (float(v), "" if lab is None else str(lab)) for v, lab in ticks
        )
        self._line = theme.colors()["border"]
        self._text = theme.colors()["sub"]
        theme.style_when_theme(self, self._on_theme)

    def values(self) -> tuple:
        """全部刻度值（含未标注刻度）。"""
        return tuple(v for v, _lab in self._ticks)

    def labels(self) -> tuple:
        """已标注的刻度文案（稀疏；空串 = 未标注）。"""
        return tuple(lab for _v, lab in self._ticks)

    def endpoints(self) -> tuple:
        """范围两端点值。"""
        return (self._ticks[0][0], self._ticks[-1][0])

    def _on_theme(self, c: dict) -> str:
        self._line = c["border"]
        self._text = c["sub"]
        self.update()
        # 刻度数值等宽（走令牌字链，随主题刷新；禁族名字面量）
        return ("QWidget#paramRangeHint {"
                f"  font-family: {theme.ui_mono_family_qss()};"
                "}")

    def paintEvent(self, event):  # noqa: N802 (Qt 命名)
        if len(self._ticks) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        prm = theme.TOKENS["param"]
        tick = int(prm["tick_len"])
        base_y = h - tick - 1
        lo, hi = self._ticks[0][0], self._ticks[-1][0]
        span = (hi - lo) or 1.0
        p.setPen(QPen(QColor(self._line), theme.TOKENS["elevation"]["border"]))
        p.drawLine(0, base_y, w - 1, base_y)
        p.setFont(self.font())      # 等宽由 QSS 令牌字链给出（见 _on_theme）
        for value, label in self._ticks:
            x = int(round((w - 1) * ((value - lo) / span)))
            p.setPen(QPen(QColor(self._line), theme.TOKENS["elevation"]["border"]))
            p.drawLine(x, base_y, x, h - 1)
            if label:
                tw = p.fontMetrics().horizontalAdvance(label)
                p.setPen(QColor(self._text))
                p.drawText(min(max(x - tw // 2, 0), max(w - tw, 0)),
                           base_y - theme.TOKENS["spacing"]["xxs"], label)


class ReadoutBox(QWidget):
    """读数内嵌框（ARCH §四）：等宽数值（text 色，比说明更亮）+ 说明（text_sub）。"""

    def __init__(self, name: str, value: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("paramReadout")
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.TOKENS["spacing"]["xxs"])
        self.lbl_name = QLabel(name, self)
        self.lbl_name.setObjectName("paramReadoutName")
        self.lbl_value = QLabel(value, self)
        self.lbl_value.setObjectName("paramReadoutValue")
        # 读数等宽（typography.mono）与内嵌框均由 _param_qss 令牌字链给出
        col.addWidget(self.lbl_name)
        col.addWidget(self.lbl_value)
        # 供取值断言（数值层级：数值 text / 说明 text_sub）
        self.name_color = theme.colors()["sub"]
        self.value_color = theme.colors()["text"]
        theme.style_when_theme(self, self._on_theme)

    def set_value(self, text: str) -> None:
        self.lbl_value.setText(text)

    def value(self) -> str:
        return self.lbl_value.text()

    def _on_theme(self, c: dict) -> str:
        self.name_color = c["sub"]
        self.value_color = c["text"]
        return _param_qss(c)


class ParamGroup(QWidget):
    """三段式参数组（ARCH §五-7 名称（上）/ 控件（中）/ 单位（下）+ §五-8 范围线索）。

    同组内每列一个参数，四行由同一 QGridLayout 承载 →「名称列 / 控件列 / 单位列」
    左边界**各自一致**（同列同 x）；可选第 4 行放该参数的范围线索（稀疏刻度）。
    """

    def __init__(self, fields, columns=None, parent=None):
        """fields: 序列，元素 = (名称, 控件, 单位, 范围刻度或 None)。

        `columns` 指定每行块容纳的参数数（默认全部一行；窄面板下换行成多个行块，
        列宽跨行块共享 → 各列左边界仍一致）。
        """
        super().__init__(parent)
        self.setObjectName("paramGroup")
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(theme.TOKENS["param"]["col_gap"])
        grid.setVerticalSpacing(theme.TOKENS["spacing"]["xs"])
        self.fields: list[dict] = []
        cols = max(1, int(columns)) if columns else max(1, len(fields))
        for index, (name, control, unit, ticks) in enumerate(fields):
            block, col = divmod(index, cols)
            row0 = block * 4
            lbl_name = QLabel(name, self)
            lbl_name.setObjectName("paramName")
            lbl_unit = QLabel(unit, self)
            lbl_unit.setObjectName("paramUnit")
            grid.addWidget(lbl_name, row0, col)
            grid.addWidget(control, row0 + 1, col)
            grid.addWidget(lbl_unit, row0 + 2, col)
            hint = None
            if ticks:
                hint = RangeHint(ticks, self)
                grid.addWidget(hint, row0 + 3, col)
            grid.setColumnStretch(col, 1)
            control.setToolTip(name)
            self.fields.append({"name": lbl_name, "control": control,
                                "unit": lbl_unit, "range": hint})
        theme.style_when_theme(self, _param_qss)


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
    """统一设置面板（QWidget，装入右栏内容页；非模态）。"""

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
        backend_selector=None,
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
        # D10a：音高算法后端选择器（主窗构造期暂存；None = 无，测试直构路径不加行）
        self._backend_selector = backend_selector

        # MCP 设置：从 Settings.load() 读取，旧配置缺键时回落默认
        self._mcp_enabled = False
        self._mcp_roots = ""
        self._mcp_out = ""
        try:
            from acouscope.utils.config import Settings

            s = Settings.load()
            self._mcp_enabled = getattr(s, "mcp_enabled", False)
            self._mcp_roots = getattr(s, "mcp_allowed_roots", "")
            self._mcp_out = getattr(s, "mcp_out_dir", "")
        except Exception:
            pass

        self._build_ui()

        # T-1001：图标风格「切换即预览」→ 应用持久化 / 取消回滚（同主题口径）
        self.applied.connect(self._persist_icon_style)
        self.cancelled.connect(self._revert_icon_style)
        # MCP 设置：应用时持久化（best-effort，同图标风格口径）
        self.applied.connect(self._persist_mcp_settings)

    @staticmethod
    def _wrap_page(page: QWidget) -> QScrollArea:
        """H1b：单页装进可缩放滚动区，隔断页最小宽向面板级的传播。

        页内容仍按内容自适应（widgetResizable）：视口够宽时页随视口拉伸，
        视口窄于页的最小宽时由该页自身出横向滚动条（可滚动 ≠ 被裁）。
        """
        area = QScrollArea()
        area.setObjectName("settingsPageScroll")
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        area.setMinimumWidth(0)
        page.setMinimumWidth(0)
        area.setWidget(page)
        return area

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # T-1013：两栏 = 左导航列表（竖排标签，水平可读）+ 右内容页栈。
        # 选型：原生 QTabWidget West 离屏实测 tab 文本被旋转、tab 高度随文本
        # 长度起伏（呈现不满足，触需求说明自绘回退条件）；改用 QListWidget +
        # QStackedWidget，选中态沿用全局 QSS 语义色（theme QListWidget 段）。
        # 六个 tab 页构建顺序/内容零改动（仅承载容器由 QTabWidget 换 stack）。
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("settingsNavList")
        # A1：显式图标尺寸（≤24）——默认 -1 时 20×20 图标与文字互压、行距塌为 0
        self.nav_list.setIconSize(QSize(20, 20))
        self.nav_list.setSizeAdjustPolicy(
            QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents
        )
        # A1：内容超高/超宽时允许滚动，不得裁切（AlwaysOff 会把末项直接切掉）
        self.nav_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.nav_list.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.nav_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.nav_list.setUniformItemSizes(True)
        self.nav_list.currentRowChanged.connect(self._on_nav_row_changed)

        # T-1109 IM-31：导航项字号 +1pt、行高增大（走 QSS 语义色·禁 hex/px）
        nav_font = self.nav_list.font()
        nav_font.setPointSize(nav_font.pointSize() + 1)
        self.nav_list.setFont(nav_font)

        self.stack = QStackedWidget()
        self.stack.setObjectName("settingsPages")
        # H1b：内容栈不再把「最宽页」的最小宽传播到面板级。
        # QStackedLayout 的最小宽 = 各页最小宽的并集（实测音频设备页最高），
        # 窄侧栏下整个面板被顶宽 → 页内容越界被裁（1000×728 实测面板最小宽
        # 远大于侧栏可用宽）。修法：栈自身最小宽归零 + 每页套一层
        # QScrollArea（见 _wrap_page），页过宽时由该页自身出横向滚动条，
        # 属「可滚动」而非「被裁」。
        self.stack.setMinimumWidth(0)
        for title, builder, icon_name in (
            (tr("settings.tab.general"), self._build_general_tab, "settings"),
            (tr("settings.tab.audio_device"), self._build_audio_device_tab, "audio_device"),
            (tr("settings.tab.ai"), self._build_ai_tab, "ai"),
            (tr("settings.tab.interface"), self._build_interface_tab, None),
            (tr("settings.tab.shortcuts"), self._build_shortcuts_tab, None),
            (tr("settings.tab.export"), self._build_export_tab, None),
        ):
            item = QListWidgetItem(title)
            if icon_name:
                item.setIcon(theme.get_icon(icon_name))
            self.nav_list.addItem(item)
            self.stack.addWidget(self._wrap_page(builder()))

        # A1：显式行高（≥28）：默认 delegate 只给 16 像素，20×20 图标会溢出到相邻项
        # （真机「图标与文字互相重叠、行距为 0」）。宽度沿用文本列宽，不额外撑大
        # 导航列；颜色仍走 theme 令牌（此处不写任何色值 / QSS 长度字面量）。
        nav_text_w = self.nav_list.sizeHintForColumn(0)
        for row in range(self.nav_list.count()):
            self.nav_list.item(row).setSizeHint(QSize(nav_text_w, 32))

        # 导航列下限 = 文本列宽 + 图标宽 + 左右边框内边距（原公式漏算图标宽，
        # 图标挤占文本使长标签被省略号截断）；AdjustToContents 只给偏好不给下限。
        self.nav_list.setMinimumWidth(
            self.nav_list.sizeHintForColumn(0)
            + self.nav_list.iconSize().width()
            + 2 * self.nav_list.frameWidth()
        )

        # H9：窄态折叠导航下拉。6 项文案逐字取自 nav_list 的 item(i).text()
        # （禁另写硬编码文案，故参数区无中文字面量）。默认隐藏；由
        # resizeEvent 按面板宽度在「左导航双栏」与「顶部下拉」间切换。
        self.nav_combo = QComboBox()
        self.nav_combo.setObjectName("settingsNavCombo")
        for i in range(self.nav_list.count()):
            self.nav_combo.addItem(self.nav_list.item(i).text())
        self.nav_combo.setVisible(False)
        # 填充完毕再接线：避免构造期首项引发的 currentIndexChanged 回调。
        self.nav_combo.currentIndexChanged[int].connect(
            self._on_nav_combo_changed)

        body.addWidget(self.nav_list)
        body.addWidget(self.stack, 1)
        # 置于 layout 中页头与 body 之间（内容栈上方）：窄态下拉顶替左栏，
        # 隐藏 nav_list 后 body 内只剩 stack，宽度交还内容区。
        layout.addWidget(self.nav_combo)
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

    def resizeEvent(self, event):  # noqa: N802 (Qt 命名)
        """H9：面板宽度变化时重算导航形态（离屏 show / resize 均投递本事件）。"""
        super().resizeEvent(event)
        self._apply_nav_mode()
        self._apply_general_narrow()

    def _apply_nav_mode(self) -> None:
        """H9②：窄态 (<360) 隐藏 nav_list / 显示 nav_combo，并把 stack 交还
        面板全部宽度（连主布局左右边距一并让出，否则两列表格尾部仍被右缘裁掉）；
        宽态 (>=360) 恢复双栏、隐藏 combo 并还原边距。切换瞬间把三者索引对齐，
        与 switch_to_tab 及下拉 / 列表点选路径共用同一份选中态（不分裂）。
        """
        combo = getattr(self, "nav_combo", None)  # 构造期首帧可能尚未就绪
        if combo is None:
            return
        narrow = self.width() < 360
        # 交还全部宽度：只在宽/窄态切换时改边距，避免逐次 resize 抖动。
        # 边距改在 SettingsDialog 主布局，不触碰 stack 结构 / 任何页内控件。
        if getattr(self, "_nav_narrow", None) != narrow:
            self._nav_narrow = narrow
            root = self.layout()
            m = getattr(self, "_nav_root_margins", None)
            if m is None:
                c = root.contentsMargins()
                m = (c.left(), c.top(), c.right(), c.bottom())
                self._nav_root_margins = m
            root.setContentsMargins(
                0 if narrow else m[0], m[1], 0 if narrow else m[2], m[3]
            )
        self.nav_list.setVisible(not narrow)
        combo.setVisible(narrow)
        idx = self.stack.currentIndex()
        if idx >= 0:
            if self.nav_list.currentRow() != idx:
                self.nav_list.setCurrentRow(idx)
            if combo.currentIndex() != idx:
                combo.blockSignals(True)
                combo.setCurrentIndex(idx)
                combo.blockSignals(False)

    def _apply_general_narrow(self) -> None:
        """M4：窄栏释放后端行最小宽下限并缩略其标签，页最小宽不再顶宽视口。"""
        if getattr(self, "_backend_sel_min_w", None) is None:
            return
        narrow = self.width() < 360  # 与 H9 导航窄态同阈值
        if getattr(self, "_general_narrow", None) == narrow:
            return
        self._general_narrow = narrow
        self._backend_selector.setMinimumWidth(
            0 if narrow else self._backend_sel_min_w)
        for lbl in self._backend_sel_labels:
            lbl.setVisible(not narrow)
        caption = " ".join(lbl.text() for lbl in self._backend_sel_labels)
        for combo, tip in zip(self._backend_sel_combos, self._backend_sel_tips):
            combo.setToolTip(caption if narrow else tip)

    def _on_nav_combo_changed(self, index: int) -> None:
        """H9②：顶部下拉选中 → nav_list / stack 同步（三者不分裂）。"""
        if index < 0:
            return
        if self.nav_list.currentRow() != index:
            self.nav_list.setCurrentRow(index)  # 触发 _on_nav_row_changed → stack
        if self.stack.currentIndex() != index:
            self.stack.setCurrentIndex(index)

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

        # F9（真机 GUI 审计）：撤下「启动时自动加载上次文件」「打开文件后
        # 自动播放」两个死开关——全仓无信号连接 / 无取值方法 / 无持久化，
        # 项目本就没有 last_file 机制，勾选后重启仍停在空态，属欺骗性 UI。
        # 选择「消除欺骗性 UI」而非接线（接线 = 新增功能，不属缺陷修复）。

        # 默认分析视图
        form.addRow(QLabel(tr("settings.default_view")))
        self.cmb_default_view = QComboBox()
        self.cmb_default_view.addItem(tr("view.waveform"), "waveform")
        self.cmb_default_view.addItem(tr("view.fft"), "fft")
        self.cmb_default_view.addItem(tr("view.spectrogram"), "spectrogram")
        self.cmb_default_view.addItem(tr("view.pitch"), "pitch")
        self.cmb_default_view.addItem(tr("view.formants"), "formants")
        self.cmb_default_view.addItem(tr("view.timbre"), "timbre")
        self.cmb_default_view.addItem(tr("view.spectrogram3d"), "spectrogram3d")
        form.addRow("", self.cmb_default_view)

        # A4 参考频率（T-921）：音分/音名换算基准，clamp 400–480，可一键恢复 440
        # T-1047：改走三段式（名称/控件/单位）+ 范围线索（稀疏刻度 400/440/480）
        #        + 读数内嵌框（等宽 · 数值亮度高于说明）+ 快捷基准 chip（激活 = 底色）
        # G5 版面修整（离屏实测原状：数值框下方一行孤立「Hz」、一根无单位端点
        # 的静态范围条、以及独立成块的「当前基准 440.0 Hz」重复读数）：
        #   ① 单位并入数值框后缀 → 三段式单位行留空并隐藏，不再有孤立「Hz」行；
        #   ② 数值框 + 交互滑块排成一行（滑块两端标 400 / 480），值与数值框双向联动；
        #   ③ 415/432/440/442 四钮改真互斥（点选后数值框/滑块同步）。
        row_reference = QWidget()
        # G2（真机复核）：A4 行改多行垂直布局——单行 5 控件同排在 162 px
        # 侧栏内把「恢复 440」压成空方框、把端点「480」切成「4」。分行后
        # 每个控件独占可读宽度，不再互抢同一行的水平空间。
        # 数值范围 400–480 / _A4_SLIDER_SCALE / _A4_PRESETS / 信号接线 /
        # _restore_reference_hz() / ParamGroup.fields[0] 结构一字不动。
        row_reference_layout = QVBoxLayout(row_reference)
        row_reference_layout.setContentsMargins(0, 0, 0, 0)
        row_reference_layout.setSpacing(theme.TOKENS["spacing"]["sm"])
        self.spin_reference_hz = ParamSpinBox()
        self.spin_reference_hz.setObjectName("settingsReferenceHz")
        self.spin_reference_hz.setDecimals(1)
        self.spin_reference_hz.setSingleStep(0.5)
        self.spin_reference_hz.setRange(400.0, 480.0)
        self.spin_reference_hz.setValue(float(self._reference_hz))
        # ① 单位贴附数值（后缀），不再单独占一行
        self.spin_reference_hz.setSuffix(f" {tr('param.unit.hz')}")
        self.spin_reference_hz.setToolTip(tr("settings.reference_hz_hint"))
        # ② 滑块的存储刻度 = 0.1 Hz（与 decimals 对齐，避免取整漂移）
        self.slider_reference_hz = QSlider(Qt.Orientation.Horizontal)
        self.slider_reference_hz.setObjectName("settingsReferenceSlider")
        self.slider_reference_hz.setRange(
            int(round(400.0 * _A4_SLIDER_SCALE)), int(round(480.0 * _A4_SLIDER_SCALE))
        )
        self.slider_reference_hz.setSingleStep(int(_A4_SLIDER_SCALE))
        self.slider_reference_hz.setPageStep(int(round(5 * _A4_SLIDER_SCALE)))
        self.slider_reference_hz.setValue(
            int(round(float(self._reference_hz) * _A4_SLIDER_SCALE))
        )
        self.slider_reference_hz.setToolTip(tr("settings.reference_hz_hint"))
        self.slider_reference_hz.setAccessibleName(tr("settings.reference_hz"))
        # 滑块两端端点标注（数值；单位由数值框后缀给出，无需重复）
        self.lbl_reference_min = QLabel("400", row_reference)
        self.lbl_reference_min.setObjectName("paramUnit")
        self.lbl_reference_max = QLabel("480", row_reference)
        self.lbl_reference_max.setObjectName("paramUnit")
        # M4：窄栏裁切/缩略时端点值仍可读（tooltip 全文）
        self.lbl_reference_max.setToolTip(self.lbl_reference_max.text())
        self.btn_reference_restore = QPushButton(tr("settings.reference_hz_restore"))
        self.btn_reference_restore.setObjectName("settingsReferenceRestore")
        self.btn_reference_restore.setToolTip(tr("settings.reference_hz_hint"))
        self.btn_reference_restore.clicked.connect(self._restore_reference_hz)
        # F7（真机 GUI 审计）：约 1000 像素的窄窗下 A4 行被压到「恢复 440」按钮
        # 只剩约 20 像素的空方框、端点标签「480」被切成「4」。给行内固定控件
        # 按自身文本像素需求设最小宽（QScrollArea 可滚动 ≠ 内容被硬裁），
        # 保证按钮实际宽度与两端点标签完整可见。数值范围 400–480 /
        # _A4_SLIDER_SCALE / _A4_PRESETS / _restore_reference_hz 一字不动。
        self.btn_reference_restore.setMinimumWidth(
            self.btn_reference_restore.fontMetrics().horizontalAdvance(
                self.btn_reference_restore.text())
        )
        for _lbl in (self.lbl_reference_min, self.lbl_reference_max):
            _lbl.setMinimumWidth(
                _lbl.fontMetrics().horizontalAdvance(_lbl.text())
            )
        # G2：多行垂直装配——① 数值框独占一行（后缀 Hz 完整）；② 滑块 +
        # 两端点标签一行（滑块 stretch 吸收富余，端点各按文本需求保底）；
        # ③ 「恢复 440」按钮独占一行（被整行拉伸，实宽 ≥ 文本需求）。
        # 单行 5 控件互抢 162 px 是「按钮变空方框 / 480 切成 4」的根因。
        row_reference_layout.addWidget(self.spin_reference_hz)
        row_slider = QHBoxLayout()
        row_slider.setContentsMargins(0, 0, 0, 0)
        row_slider.setSpacing(theme.TOKENS["spacing"]["sm"])
        row_slider.addWidget(self.lbl_reference_min)
        row_slider.addWidget(self.slider_reference_hz, 1)
        row_slider.addWidget(self.lbl_reference_max)
        row_reference_layout.addLayout(row_slider)
        row_reference_layout.addWidget(self.btn_reference_restore)

        self.param_group_general = ParamGroup([
            (tr("settings.reference_hz"), row_reference, "",
             ((400.0, "400"), (440.0, "440"), (480.0, "480"))),
        ])
        form.addRow(self.param_group_general)
        # ① 单位已并入数值框后缀：隐藏三段式的空单位行（防残留空白行）
        self.param_group_general.fields[0]["unit"].setVisible(False)

        # 重复读数块「当前基准 x Hz」：与数值框 + 快捷基准 chip 三处重复同一值，
        # 按 G5 从版面撤下（构件本身保留：取值/主题随动被既有守卫钉住，
        # 仅不再参与排版，故不占用任何可见空间）。
        self.readout_reference = ReadoutBox(tr("param.readout.a4"),
                                            self._reference_readout_text(), tab)
        self.readout_reference.setVisible(False)

        # 快捷基准 chip：激活态靠底色（禁描边 / 纯色文字）
        preset = QWidget()
        preset_col = QVBoxLayout(preset)
        preset_col.setContentsMargins(0, 0, 0, 0)
        preset_col.setSpacing(theme.TOKENS["spacing"]["xxs"])
        lbl_preset = QLabel(tr("param.name.a4_preset"), preset)
        lbl_preset.setObjectName("paramUnit")
        self.chips_a4 = ChipGroup([(f"{hz:g}", hz) for hz in _A4_PRESETS], preset)
        preset_col.addWidget(lbl_preset)
        preset_col.addWidget(self.chips_a4)
        form.addRow(preset)

        # D10a：音高算法（自带 label+combo，跨列行）
        if self._backend_selector is not None:
            # F7 / G2（真机 GUI 审计）：窄窗下该下拉「pYIN (流式)」被 Qt
            # elide 成「pYIN (流…」。仅按纯文本宽设最小宽不够——QComboBox
            # 还要给下拉箭头 + 左右内边距留位，否则文本区窄于当前项文本宽。
            # 留白走排版/控制令牌（同 transport_bar._combo_arrow_reserve
            # 口径），禁硬编码 px；条目/绑定/信号/取值一律不动。
            _affordance = int(theme.TOKENS["spacing"]["sm"] * 2
                              + theme.TOKENS["control"]["gap"])
            for _combo in self._backend_selector.findChildren(QComboBox):
                _need = (_combo.fontMetrics().horizontalAdvance(
                    _combo.currentText()) + _affordance)
                if _combo.minimumWidth() < _need:
                    _combo.setMinimumWidth(_need)
            form.addRow(self._backend_selector)
            self._backend_sel_min_w = self._backend_selector.minimumWidth()
            self._backend_sel_labels = tuple(
                self._backend_selector.findChildren(QLabel))
            self._backend_sel_combos = tuple(
                self._backend_selector.findChildren(QComboBox))
            self._backend_sel_tips = tuple(
                c.toolTip() for c in self._backend_sel_combos)

        # 接线：控件 → chip 激活态（回路） / chip → 控件
        self.spin_reference_hz.valueChanged.connect(self._sync_a4_presets)
        self.slider_reference_hz.valueChanged.connect(self._on_a4_slider)
        self.chips_a4.chipActivated.connect(self._on_a4_preset)
        # ③ 四钮互斥：点选任一即取消其余（QButtonGroup 排他，语义 = 单选）
        self.chips_a4.set_exclusive(True)
        self._sync_a4_presets(self.spin_reference_hz.value())

        # REWORK-4：MCP 集成嵌入「通用」页（分组标题 + 控件块）
        form.addRow(QLabel(tr("settings.tab.mcp")))
        form.addRow("", self._build_mcp_tab())

        return tab

    def _reference_readout_text(self) -> str:
        """A4 读数文案（等宽数值 + 窄空格 + 单位；ARCH §四）。"""
        return f"{self.spin_reference_hz.value():.1f}{NBSP_THIN}{tr('param.unit.hz')}"

    def _sync_a4_presets(self, value: float) -> None:
        """控件 → chip / 滑块 / 读数：仅与预设完全一致时点亮（激活态唯一）。"""
        self.chips_a4.set_current(float(value))
        # ② 数值框 → 滑块（blockSignals 防回环；只在真不同步时写）
        slider_value = int(round(float(value) * _A4_SLIDER_SCALE))
        if self.slider_reference_hz.value() != slider_value:
            self.slider_reference_hz.blockSignals(True)
            self.slider_reference_hz.setValue(slider_value)
            self.slider_reference_hz.blockSignals(False)
        self.readout_reference.set_value(
            f"{float(value):.1f}{NBSP_THIN}{tr('param.unit.hz')}")

    def _on_a4_slider(self, slider_value: int) -> None:
        """② 滑块 → 数值框（0.1 Hz 刻度还原；值相等时 setValue 不再发信号）。"""
        value = float(slider_value) / _A4_SLIDER_SCALE
        if abs(self.spin_reference_hz.value() - value) > 1e-9:
            self.spin_reference_hz.setValue(value)

    def _on_a4_preset(self, payload) -> None:
        """chip → 控件（快捷基准）；激活态/滑块由 valueChanged 回路同步。"""
        if payload is not None:
            self.spin_reference_hz.setValue(float(payload))

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

        # --- 设备选择（输出 / 输入）---
        dev_box = QWidget()
        dev_form = QFormLayout(dev_box)
        dev_form.setContentsMargins(0, 0, 0, 0)
        dev_form.setSpacing(8)

        self.cmb_play_device = QComboBox()
        self._populate_playback_devices()
        dev_form.addRow(tr("param.audio.output_device"), self.cmb_play_device)

        self.cmb_record_device = QComboBox()
        self._populate_recording_devices()
        dev_form.addRow(tr("param.audio.input_device"), self.cmb_record_device)

        layout.addWidget(dev_box)

        # --- 参数区（T-1047 三段式：名称（上）/ 控件（中）/ 单位（下）+ 范围线索）---
        lbl_params = QLabel(tr("param.audio.title"), tab)
        lbl_params.setObjectName("paramName")
        layout.addWidget(lbl_params)

        self.cmb_play_channels = QComboBox()
        self.cmb_play_channels.addItem(f"{tr('param.opt.mono')} (Mono)", 1)
        self.cmb_play_channels.addItem(f"{tr('param.opt.stereo')} (Stereo)", 2)
        self.cmb_play_channels.setCurrentIndex(0)

        self.cmb_record_channels = QComboBox()
        self.cmb_record_channels.addItem(f"{tr('param.opt.mono')} (Mono)", 1)
        self.cmb_record_channels.addItem(f"{tr('param.opt.stereo')} (Stereo)", 2)
        self.cmb_record_channels.setCurrentIndex(0)

        self.cmb_sample_rate = QComboBox()
        rates = [
            ("8000 Hz", 8000),
            ("11025 Hz", 11025),
            ("22050 Hz", 22050),
            ("44100 Hz ({r})".format(r=tr("param.opt.recommended")), 44100),
            ("48000 Hz", 48000),
            ("96000 Hz", 96000),
            ("192000 Hz", 192000),
        ]
        for label, rate in rates:
            self.cmb_sample_rate.addItem(label, rate)
        self.cmb_sample_rate.setCurrentIndex(3)  # 44100

        self.cmb_sample_format = QComboBox()
        self.cmb_sample_format.addItem("16-bit PCM", 16)
        self.cmb_sample_format.addItem("24-bit PCM", 24)
        self.cmb_sample_format.addItem("32-bit Float", 32)
        self.cmb_sample_format.setCurrentIndex(2)  # 32-bit Float

        # 四参数同组（每行块 2 列，窄面板下不溢出）→「名称列 / 控件列 / 单位列」
        # 左边界各自一致（ARCH §五-7）；范围线索稀疏标注（ARCH §五-8）
        self.param_group_audio = ParamGroup([
            (tr("param.name.play_channels"), self.cmb_play_channels,
             tr("param.unit.channels"), ((1.0, "1"), (2.0, "2"))),
            (tr("param.name.record_channels"), self.cmb_record_channels,
             tr("param.unit.channels"), ((1.0, "1"), (2.0, "2"))),
            (tr("param.name.sample_rate"), self.cmb_sample_rate,
             tr("param.unit.hz"),
             ((8000.0, "8k"), (44100.0, None), (96000.0, None),
              (192000.0, "192k"))),
            (tr("param.name.sample_format"), self.cmb_sample_format,
             tr("param.unit.bit"), ((16.0, "16"), (24.0, None), (32.0, "32"))),
        ], columns=2, parent=tab)
        layout.addWidget(self.param_group_audio)

        # --- 刷新按钮 ---
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_refresh_devices = QPushButton(tr("param.audio.refresh"))
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
                self.cmb_play_device.addItem(tr("record.device_none_output"), None)
        except Exception:
            self.cmb_play_device.addItem(tr("record.device_unavailable"), None)

    def _populate_recording_devices(self):
        """填充录音设备列表。"""
        self.cmb_record_device.clear()
        try:
            from PyQt6.QtMultimedia import QMediaDevices
            devices = QMediaDevices.audioInputs()
            for d in devices:
                self.cmb_record_device.addItem(d.description(), d)
            if not devices:
                self.cmb_record_device.addItem(tr("record.device_none"), None)
        except Exception:
            self.cmb_record_device.addItem(tr("record.device_unavailable"), None)

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

        # C·2026-11-06：应用更新检查独立开关（默认关闭，取消首次运行征询；
        # 用户想要就去设置里打开；紧邻上方「本地模型版本」区之后；变更即时落盘
        # app_state.json 的 update_check_enabled）
        from acouscope import state as _app_state

        self.chk_update_check = QCheckBox(tr("settings.update_check_enabled"))
        self.chk_update_check.setObjectName("chkUpdateCheck")
        # 缺键（默认关闭）⇒ 不勾选；此处 setChecked 在 connect 之前，
        # 不触发落盘（只有用户显式切换才写键）。
        self.chk_update_check.setChecked(
            _app_state.is_update_check_enabled() is True)
        self.chk_update_check.toggled.connect(self._on_update_check_toggled)
        root.addWidget(self.chk_update_check)

        # T-1047：状态点（LED 式）+ 只读状态行（§五-4：小圆点令牌色，禁拟物）
        status_text, ready = self._builtin_status()
        self.led_ai_builtin = LedDot("ready" if ready else "off")
        self.led_ai_builtin.setToolTip(
            tr("param.led.ready") if ready else tr("param.led.off"))
        row_builtin = QHBoxLayout()
        row_builtin.setContentsMargins(0, 0, 0, 0)
        row_builtin.setSpacing(theme.TOKENS["spacing"]["xs"])
        row_builtin.addWidget(self.led_ai_builtin, 0,
                              Qt.AlignmentFlag.AlignTop)
        self.lbl_ai_builtin_status = QLabel(status_text)
        self.lbl_ai_builtin_status.setWordWrap(True)
        row_builtin.addWidget(self.lbl_ai_builtin_status, 1)
        root.addLayout(row_builtin)

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
        self.led_ai_builtin.setVisible(source == "builtin")
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

    def _builtin_status(self) -> tuple[str, bool]:
        """内置档状态行（只读现有接口；拿不到状态时显示中性文案）。

        T-1047：同时给出「是否就绪」→ 驱动状态点（LED）。返回 (文案, 就绪)。
        """
        try:
            from acouscope.ai.backends.local_registry import (
                OFFICIAL_MODELS, get_missing_official_models, probe_ollama,
            )
            ok, models = probe_ollama()
            if not ok:
                return "首次使用时将自动启动内置模型服务并准备推荐模型。", False
            missing = get_missing_official_models(models)
            if not missing:
                return "推荐模型已就绪，可直接开始释图。", True
            total = sum(
                int(OFFICIAL_MODELS.get(m, {}).get("est_bytes", 0) or 0)
                for m in missing)
            size = (f"{total / 1_000_000_000:.1f} GB"
                    if total >= 1_000_000_000
                    else f"{round(total / 1_000_000)} MB")
            return f"首次使用时将自动下载推荐模型（约 {size}）。", False
        except Exception:
            return "首次使用时将自动准备推荐模型。", False

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

    def _on_update_check_toggled(self, checked: bool) -> None:
        """UP-2：应用更新检查开关变更 → 即时落盘（键 ``update_check_enabled``）。"""
        from acouscope import state as _app_state

        _app_state.set_update_check_enabled(bool(checked))

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

        # 字体大小（T-1047 三段式 + 范围线索：刻度 11/13/15/17，稀疏标注）
        self.cmb_font_size = QComboBox()
        sizes = [
            (tr("param.opt.font_small"), 11),
            (tr("param.opt.font_default"), 13),
            (tr("param.opt.font_large"), 15),
            (tr("param.opt.font_xlarge"), 17),
        ]
        for label, size in sizes:
            self.cmb_font_size.addItem(label, size)
        self.cmb_font_size.setCurrentIndex(1)  # 默认 13
        self.param_group_interface = ParamGroup([
            (tr("param.name.font_size"), self.cmb_font_size, tr("param.unit.px"),
             ((11.0, "11"), (13.0, None), (15.0, "15"), (17.0, "17"))),
        ])
        form.addRow(self.param_group_interface)

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
    # MCP（模型上下文协议）设置页与持久化
    # ------------------------------------------------------------------

    def _build_mcp_tab(self) -> QWidget:
        """MCP 集成设置页：启用开关、白名单根目录、输出目录、就绪检查、复制 Host 配置。"""
        from PyQt6.QtWidgets import QSizePolicy

        tab = QWidget()
        # REWORK-5: 水平不撑宽，防通用页 minimumSizeHint 被撑到 >310
        tab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        tab.setMinimumWidth(0)
        layout = QVBoxLayout(tab)
        form = QFormLayout()
        form.setSpacing(10)

        self.chk_mcp_enabled = QCheckBox(tr("settings.mcp.enable"))
        self.chk_mcp_enabled.setObjectName("mcpEnabled")
        self.chk_mcp_enabled.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.chk_mcp_enabled.setChecked(self._mcp_enabled)
        form.addRow("", self.chk_mcp_enabled)

        roots_label = QLabel(tr("settings.mcp.roots_hint"))
        roots_label.setWordWrap(True)
        roots_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.edit_mcp_roots = QLineEdit()
        self.edit_mcp_roots.setObjectName("mcpAllowedRoots")
        self.edit_mcp_roots.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.edit_mcp_roots.setMinimumWidth(0)
        self.edit_mcp_roots.setText(self._mcp_roots)
        form.addRow(tr("settings.mcp.title"), self.edit_mcp_roots)
        form.addRow("", roots_label)

        out_label = QLabel(tr("settings.mcp.out_hint"))
        out_label.setWordWrap(True)
        out_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.edit_mcp_out = QLineEdit()
        self.edit_mcp_out.setObjectName("mcpOutDir")
        self.edit_mcp_out.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.edit_mcp_out.setMinimumWidth(0)
        self.edit_mcp_out.setText(self._mcp_out)
        form.addRow(tr("settings.mcp.out_hint"), self.edit_mcp_out)
        form.addRow("", out_label)

        btn_row = QHBoxLayout()
        self.btn_mcp_check = QPushButton(tr("settings.mcp.check"))
        self.btn_mcp_check.setObjectName("mcpCheck")
        self.btn_mcp_check.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.btn_mcp_check.clicked.connect(self._on_mcp_check)
        btn_row.addWidget(self.btn_mcp_check)

        self.btn_mcp_copy = QPushButton(tr("settings.mcp.copy"))
        self.btn_mcp_copy.setObjectName("mcpCopy")
        self.btn_mcp_copy.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.btn_mcp_copy.clicked.connect(self._on_mcp_copy)
        btn_row.addWidget(self.btn_mcp_copy)
        btn_row.addStretch()

        form.addRow("", btn_row)

        self.lbl_mcp_status = QLabel("")
        self.lbl_mcp_status.setObjectName("mcpStatus")
        self.lbl_mcp_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        form.addRow("", self.lbl_mcp_status)

        layout.addLayout(form)
        return tab

    def _on_mcp_check(self):
        """就绪检查：纯计算（无进程/网络），报告 mcp 可导入性、启用状态与目录存在性。"""
        import importlib.util
        import os
        from pathlib import Path

        reasons = []
        if not importlib.util.find_spec("mcp"):
            reasons.append("mcp package not installed")
        if not self.chk_mcp_enabled.isChecked():
            reasons.append("mcp not enabled")

        roots = self.edit_mcp_roots.text().strip()
        if roots:
            for root in roots.split(os.pathsep):
                root = root.strip()
                if root and not Path(root).is_dir():
                    reasons.append(f"root dir missing: {root}")

        out = self.edit_mcp_out.text().strip()
        if out and not Path(out).is_dir():
            reasons.append(f"out dir missing: {out}")

        if not out:
            reasons.append("output directory not set")

        if reasons:
            self.lbl_mcp_status.setText(
                f"{tr('settings.mcp.not_ready')} — " + "; ".join(reasons)
            )
        else:
            self.lbl_mcp_status.setText(tr("settings.mcp.ready"))

    def _on_mcp_copy(self):
        """复制 Host 配置片段到剪贴板（不启动任何进程）。"""
        from acouscope.mcp.service import build_host_config

        config = build_host_config()
        text = json.dumps(config, ensure_ascii=False, indent=2)
        QApplication.clipboard().setText(text)

    def _persist_mcp_settings(self):
        """「应用」：将 MCP 设置写入 settings.json（best-effort）。"""
        try:
            from acouscope.utils.config import Settings

            settings = Settings.load()
            settings.mcp_enabled = self.chk_mcp_enabled.isChecked()
            settings.mcp_allowed_roots = self.edit_mcp_roots.text().strip()
            settings.mcp_out_dir = self.edit_mcp_out.text().strip()
            settings.save()
        except Exception:
            pass

    def mcp_settings(self):
        """返回当前 MCP 控件值（供测试读取）。"""
        return {
            "mcp_enabled": self.chk_mcp_enabled.isChecked(),
            "mcp_allowed_roots": self.edit_mcp_roots.text().strip(),
            "mcp_out_dir": self.edit_mcp_out.text().strip(),
        }

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
        # T-1047 三段式 + 范围线索（刻度 150/300/600/1200，稀疏标注端点+关键点）
        self.param_group_export = ParamGroup([
            (tr("settings.export_dpi"), self.cmb_dpi, tr("param.unit.dpi"),
             ((150.0, "150"), (300.0, None), (600.0, "600"), (1200.0, "1200"))),
        ])
        form.addRow(self.param_group_export)

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
        cat_row.addWidget(QLabel(tr("settings.category_filter")))
        self.cmb_shortcut_category = QComboBox()
        self.cmb_shortcut_category.addItem(tr("settings.category_all"), "all")
        self.cmb_shortcut_category.addItem(tr("settings.category_global"), "global")
        self.cmb_shortcut_category.addItem(tr("settings.category_spectrogram"), "spectrogram")
        self.cmb_shortcut_category.addItem(tr("view.waveform"), "waveform")
        self.cmb_shortcut_category.addItem(tr("view.timbre"), "timbre")
        self.cmb_shortcut_category.addItem(tr("view.pitch"), "pitch")
        self.cmb_shortcut_category.addItem(tr("view.ai_interpret"), "ai_interpret")
        self.cmb_shortcut_category.currentIndexChanged.connect(self._filter_shortcuts)
        cat_row.addWidget(self.cmb_shortcut_category)
        cat_row.addStretch()

        # 重置按钮
        self.btn_reset_shortcut = QPushButton("恢复默认")
        self.btn_reset_shortcut.clicked.connect(self._reset_selected_shortcut)
        cat_row.addWidget(self.btn_reset_shortcut)

        layout.addLayout(cat_row)

        # 快捷键列表（G4：两列「功能 | 快捷键」——分类已由上方筛选器表达，
        # 第三列在 ~430pt 侧栏下会被整列裁掉（「快捷键」只剩 L / Shift / Ctrl-…）。
        # 列宽策略：0 列吃掉余量、1 列按内容收紧；禁横向滚动条（截断靠 tooltip 兜）。
        self.shortcut_table = QTableWidget(0, 2)
        self.shortcut_table.setHorizontalHeaderLabels(["功能", "快捷键"])
        self.shortcut_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.shortcut_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        for _col in range(2):
            _head_item = self.shortcut_table.horizontalHeaderItem(_col)
            if _head_item is not None:
                _head_item.setTextAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
        self.shortcut_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
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
        hint = QLabel(tr("settings_dialog.shortcut_hint"))
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

            # 功能名（G4：分类不再单独成列，改挂 UserRole+1 供筛选器读取）
            item_label = QTableWidgetItem(entry.label)
            item_label.setData(Qt.ItemDataRole.UserRole, entry.action_id)
            item_label.setData(Qt.ItemDataRole.UserRole + 1, entry.category)
            item_label.setFlags(item_label.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.shortcut_table.setItem(row, 0, item_label)

            # 快捷键（显示层走平台文案：macOS 用 ⌘⌃⌥⇧，见 shortcuts.display_key）
            item_key = QTableWidgetItem(display_key(entry.current_key))
            item_key.setData(Qt.ItemDataRole.UserRole, entry.action_id)
            self.shortcut_table.setItem(row, 1, item_key)

            self._set_shortcut_tooltips(row, entry.label, entry.current_key)

        self.shortcut_table.blockSignals(False)
        self._filter_shortcuts()

    def _set_shortcut_tooltips(self, row: int, label: str, raw_key: str) -> None:
        """G4：两列 tooltip 均写全「功能 — 快捷键」，列宽截断时仍可读。"""
        text = f"{label} — {display_key(raw_key)}"
        for col in range(2):
            item = self.shortcut_table.item(row, col)
            if item is not None:
                item.setToolTip(text)

    def _filter_shortcuts(self):
        """按分类过滤快捷键列表（分类取自功能列 UserRole+1）。"""
        cat = self.cmb_shortcut_category.currentData()
        for row in range(self.shortcut_table.rowCount()):
            label_item = self.shortcut_table.item(row, 0)
            entry_cat = (
                label_item.data(Qt.ItemDataRole.UserRole + 1)
                if label_item is not None else None
            )
            show = cat == "all" or entry_cat == cat
            self.shortcut_table.setRowHidden(row, not show)

    def _on_shortcut_edited(self, item: QTableWidgetItem):
        """快捷键编辑完成。"""
        if item.column() != 1:
            return

        action_id = item.data(Qt.ItemDataRole.UserRole)
        # 显示层可能已是平台符号（⌘⌃⌥⇧）→ 先还原成绑定口径再校验/落盘
        new_key = unmap_key(item.text().strip())

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
                        item.setText(display_key(e.current_key))
                        break
            except Exception:
                pass
            return

        # 应用新快捷键
        try:
            from acouscope.ui.shortcuts import ShortcutManager
            mgr = ShortcutManager.instance()
            if mgr.set_key(action_id, new_key):
                # 落盘成功后单元格回显显示层文案 + 重写两列 tooltip（G4）
                self.shortcut_table.blockSignals(True)
                item.setText(display_key(new_key))
                self.shortcut_table.blockSignals(False)
                label_item = self.shortcut_table.item(item.row(), 0)
                self._set_shortcut_tooltips(
                    item.row(),
                    label_item.text() if label_item is not None else "",
                    new_key,
                )
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

        item = self.shortcut_table.item(current_row, 1)
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
                        item.setText(display_key(e.current_key))
                        self.shortcut_table.blockSignals(False)
                        label_item = self.shortcut_table.item(current_row, 0)
                        self._set_shortcut_tooltips(
                            current_row,
                            label_item.text() if label_item is not None else "",
                            e.current_key,
                        )
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
        # 仅覆盖三档新键（source / external_ollama*）——防回滚（需求说明规格 3）。
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
        # H9：顶部下拉同索引（含 nav_list 未变化路径），三者不分裂
        combo = getattr(self, "nav_combo", None)
        if combo is not None and combo.currentIndex() != idx:
            combo.blockSignals(True)
            combo.setCurrentIndex(idx)
            combo.blockSignals(False)

    def _on_nav_row_changed(self, row: int) -> None:
        """左导航选中行 → 右内容页栈切换（T-1013）；H9 同步顶部下拉。"""
        if 0 <= row < self.stack.count():
            self.stack.setCurrentIndex(row)
        combo = getattr(self, "nav_combo", None)  # 构造期本槽先于 combo 就绪
        if combo is not None and 0 <= row < combo.count() \
                and combo.currentIndex() != row:
            combo.blockSignals(True)
            combo.setCurrentIndex(row)
            combo.blockSignals(False)

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
