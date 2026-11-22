# SPDX-License-Identifier: GPL-3.0-only
"""传输条：播放/录音传输控制（独立控件，置于中央画布底部横贯全宽）。

信号与原 WaveformWidget 的 Transport 信号同名，主窗口槽函数签名不变。

PI-G4a-2（D1 附带）收口：
- `minimumSizeHint().width() <= 620`：窄态（< 760px）收起速率读数位，
  时间读数用 `elidedText` 中部省略收口（最小宽 150；极窄态降到 96 让位）；
- H6：录音输入设备选择器**任何宽度下都在位**（最小宽按「（无输入设备）」实测），
  窄态优先压缩时间读数/速率段，不再整体隐藏设备源；
- 倍速下拉 + 只读读数位（P3b 恢复 CB-013 D-1 的 `lbl_speed_readout`，af35900 曾删）；
- 按钮样式全部改 `theme.colors()` 令牌（原 13 处字面 hex 清零）。
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider, QWidget,
)

from acouscope.i18n import tr
from acouscope.ui.theme import TOKENS, style_when_theme, ui_mono_family_qss

_UNKNOWN_TIME = "--:--:--.---"
# 窄态阈值：条宽低于此值收起「速率读数位」（时间读数改省略号收口）。
# H6：输入设备选择器**不再**随窄态折叠——录音按钮常在而选不到输入源
# 等于「能录但不知录哪」，故该控件恒在位，改为优先压缩时间读数/速率段。
_COMPACT_W = 760
# 时间读数最小宽：窄态可压到此宽，全量文本以中部省略显示
_CLOCK_MIN_W = 150
# 极窄态（条宽 < _TIGHT_W）下 F8：不再把时间读数压到 72px 让位，而是抬到
# 「无损紧凑短格式（小时 00 → mm:ss.mmm；小时非 00 → 保留 HH:MM:SS.mmm）」
# 可读的下限（真机 1000px 窗口曾被 ElideMiddle 挖成 00:…000、AX 读数不可辨）。
_TIGHT_W = 620
_CLOCK_MIN_W_TIGHT = 180
# 构造期最小宽预算基线：_ClockLabel 未布局时的 minimumSizeHint 口径。
# tight 档提高的下限只在 _apply_compact 运行时施加，不抬高 TransportBar
# 的 minimumSizeHint（既有 620 宽度预算判据锁死，不可顶破）。
_CLOCK_MIN_W_BUDGET = 72
# 窄态时间读数上限：钳住它的「想要宽」（sizeHint 按全量文本报），把宽度让给
# 设备选择器等不可省控件（H6：先压时间读数/速率段）。宽态恢复不限。
_CLOCK_MAX_W_NARROW = 150
_CLOCK_MAX_W_TIGHT = 260
_CLOCK_MAX_W = 16777215
# 设备下拉最小宽：按「当前显示文本」整句实测（括号也算），空表时退回到文案前 2 字
# 的桩宽——既保证「（无输入设备）」整句可读，也不把传输条自身最小宽顶破 620 预算。


def format_transport_clock(sec) -> str:
    """秒数 → HH:MM:SS.mmm（毫秒精度，CB-013 D-1 DAW 大号读数）。

    None / NaN / 负数视为总时长未知，显示 ``--:--:--.---``。
    """
    if sec is None:
        return _UNKNOWN_TIME
    try:
        f = float(sec)
    except (TypeError, ValueError):
        return _UNKNOWN_TIME
    if math.isnan(f) or f < 0:
        return _UNKNOWN_TIME
    ms = int(round(f * 1000.0))
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def _compact_transport_clock(full: str) -> str:
    """F8：HH:MM:SS.mmm / HH:MM:SS.mmm → 无损紧凑读数（tight 档用）。

    tight 档（条宽 < _TIGHT_W）改用更短但信息无损的格式，两个读数分别
    处理：仅当小时段为 ``00`` 时去掉该段（真机读数多在 1h 内），得
    ``MM:SS.mmm``；小时段非 ``00``（含未知态 ``--``）时保留完整
    ``HH:MM:SS.mmm``，绝不静默丢掉 1h/2h 等小时信息（R3-1）。
    非双读数 / 未知态 / 非三段格式一律原样返回（既有语义不变）。
    """
    parts = full.split(" / ")
    if len(parts) != 2:
        return full
    out = []
    for part in parts:
        seg = part.split(":")
        out.append(":".join(seg[1:])
                   if len(seg) == 3 and seg[0] == "00" else part)
    return " / ".join(out)


def _button_qss(record: bool = False):
    """传输钮 QSS 构造器（随主题重设；色值一律取令牌，禁字面 hex）。

    record=True 为录音钮变体：选中底取 `semantic.error`（红色语义，非主题强调色）。
    """
    def build(c) -> str:
        accent = TOKENS["semantic"]["error"] if record else c["accent"]
        accent_text = (
            TOKENS["semantic"]["error_text"] if record else c["accent_text"]
        )
        return (
            f"QPushButton{{font-size:11px;padding:2px 6px;min-width:22px;"
            f"color:{c['text_sub']};border:1px solid {c['border']};"
            f"border-radius:3px;background:{c['bg2']};}}"
            f"QPushButton:hover{{background:{c['bg3']};color:{c['text']};"
            f"border-color:{c['border_strong']};}}"
            f"QPushButton:checked{{background:{accent};color:{accent_text};"
            f"border-color:{accent};}}"
            f"QPushButton:disabled{{color:{c['text_faint']};"
            f"background:{c['bg2']};}}"
        )

    return build


class _ClockLabel(QLabel):
    """时间读数：宽裕时显示全量，窄态以中部省略收口（最小宽 `_CLOCK_MIN_W`）。

    `sizeHint` 恒按全量文本报宽（宽裕时不被省略号钉死），`minimumSizeHint`
    封顶 150（不把传输条顶宽）；实际文本在 resizeEvent 里按当前宽 elide。
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._full_text = text
        # 构造期按最小宽预算基线（运行时由 _apply_compact 抬到 tight/wide 档）
        self._min_width = _CLOCK_MIN_W_BUDGET
        # F8：默认宽态全量口径；tight 档由 set_compact(True) 切到无损紧凑短格式。
        self._compact = False

    def set_min_width(self, width: int) -> None:
        """窄态让位：可压到的下限（H6：优先压缩时间读数而非隐藏设备选择器）。"""
        width = max(0, int(width))
        if width == self._min_width:
            return
        self._min_width = width
        self.updateGeometry()
        self._apply_elide()

    def set_compact(self, on: bool) -> None:
        """F8：tight 档切到无损紧凑短格式（信息完整，不再中部省略挖空）。"""
        on = bool(on)
        if on == self._compact:
            return
        self._compact = on
        self.updateGeometry()
        self._apply_elide()

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self._apply_elide()

    def sizeHint(self) -> QSize:  # noqa: N802 (override)
        text = (_compact_transport_clock(self._full_text) if self._compact
                else self._full_text)
        width = self.fontMetrics().horizontalAdvance(text) + 20
        return QSize(width, super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (override)
        base = super().minimumSizeHint()
        return QSize(min(base.width(), self._min_width), base.height())

    def resizeEvent(self, event) -> None:  # noqa: N802 (override)
        super().resizeEvent(event)
        self._apply_elide()

    def _apply_elide(self) -> None:
        """L2：任何档位都不以省略号挖空时钟；宽度不足退到无损紧凑格式。

        F8 的 tight 档已用紧凑格式；中间档此前走 ElideMiddle，真机会把读数
        挖成「00:00:0…:08.000」，两端读数不可辨。改为「放得下用全量、放不下
        用紧凑」，省略号路径整体移除。
        """
        if self._compact:
            text = _compact_transport_clock(self._full_text)
        else:
            avail = max(40, self.width() - 4)
            if self.fontMetrics().horizontalAdvance(self._full_text) <= avail:
                text = self._full_text
            else:
                text = _compact_transport_clock(self._full_text)
        if super().text() != text:
            super().setText(text)


class TransportBar(QWidget):
    """独立传输条。

    控件顺序：⏮ / ▶ / ■ / ⏭ / 分隔 / ●录音 / 输入设备 / 录音采样率 /
    ⟳循环 / 速率 / 当前时间 / 进度滑条（stretch=1）。
    """

    # Transport 信号（与原 waveform 同名，保持 main_window 槽函数签名不变）
    playToggled = pyqtSignal(bool)       # 播放切换
    playStop = pyqtSignal()              # 停止
    skipToStart = pyqtSignal()           # 跳到开头
    skipToEnd = pyqtSignal()             # 跳到结尾
    recordToggled = pyqtSignal(bool)     # 录音切换
    loopToggled = pyqtSignal(bool)       # 循环播放切换
    speedChanged = pyqtSignal(float)     # 播放速率变化
    seekPreview = pyqtSignal(int)        # 拖动进度条预览（0-1000）
    seekCommit = pyqtSignal()            # 释放进度条定位

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 0)
        layout.setSpacing(2)
        self.layout = layout

        # --- 按钮样式（令牌化；录音钮为红色语义变体）---
        # 跳到开头
        self.btn_skip_start = QPushButton("⏮")
        self.btn_skip_start.setToolTip(tr("transport.tip_rewind"))
        style_when_theme(self.btn_skip_start, _button_qss())
        self.btn_skip_start.clicked.connect(lambda: self.skipToStart.emit())
        layout.addWidget(self.btn_skip_start)

        # 播放/暂停
        self.btn_play = QPushButton("▶")
        self.btn_play.setToolTip(tr("transport.tip_play"))
        self.btn_play.setCheckable(True)
        style_when_theme(self.btn_play, _button_qss())
        self.btn_play.toggled.connect(lambda v: self.playToggled.emit(v))
        layout.addWidget(self.btn_play)

        # 停止
        self.btn_stop = QPushButton("■")
        self.btn_stop.setToolTip(tr("transport.tip_stop"))
        style_when_theme(self.btn_stop, _button_qss())
        self.btn_stop.clicked.connect(lambda: self.playStop.emit())
        layout.addWidget(self.btn_stop)

        # 跳到结尾
        self.btn_skip_end = QPushButton("⏭")
        self.btn_skip_end.setToolTip(tr("transport.tip_end"))
        style_when_theme(self.btn_skip_end, _button_qss())
        self.btn_skip_end.clicked.connect(lambda: self.skipToEnd.emit())
        layout.addWidget(self.btn_skip_end)

        # 分隔线
        sep = QLabel("|")
        style_when_theme(sep, lambda c: f"color: {c['sub']}; padding: 0 2px;")
        layout.addWidget(sep)

        # 录音（红色变体）
        self.btn_record = QPushButton("●")
        self.btn_record.setToolTip(tr("transport.tip_record"))
        self.btn_record.setCheckable(True)
        style_when_theme(self.btn_record, _button_qss(record=True))
        self.btn_record.toggled.connect(lambda v: self.recordToggled.emit(v))
        layout.addWidget(self.btn_record)

        # 录音输入设备（H6：恒在位——窄态只压缩其它可省元素，禁整体隐藏）
        self.cmb_input_device = QComboBox()
        self.cmb_input_device.setToolTip(tr("transport.tip_input_device"))
        self.cmb_input_device.setMaximumWidth(140)
        # 宽度意图（H6）：最小宽跟随「当前显示文本」（空表 → 桩宽；填入
        # 「（无输入设备）」→ 该句整句可读宽），控件恒在位、永不隐藏；
        # 时间读数/速率段才是窄态先让位的元素。
        self.cmb_input_device.setMinimumWidth(self._device_combo_stub_width())
        self.cmb_input_device.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        # 条目/选中项变化 → 最小宽跟随（不新增控件、不改显示行为）
        self.cmb_input_device.currentIndexChanged.connect(
            lambda _i: self._sync_device_min_width()
        )
        layout.addWidget(self.cmb_input_device)

        # 设备选择器优先：显式登记为不可拉伸（不抢富余宽），压缩顺序靠
        # minimumWidth 分级（时间读数/速率段先让位）。
        layout.setStretchFactor(self.cmb_input_device, 0)

        # 录音采样率
        self.cmb_record_rate = QComboBox()
        self.cmb_record_rate.setToolTip(tr("transport.tip_sample_rate"))
        self.cmb_record_rate.setMaximumWidth(80)
        for rate in [8000, 16000, 22050, 44100, 48000, 96000]:
            self.cmb_record_rate.addItem(f"{rate//1000}k" if rate >= 1000 else str(rate), rate)
        self.cmb_record_rate.setCurrentIndex(3)  # 44100
        # H6 让位序：采样率段是可省元素（最小宽收到「条目本身够读」，不改显示）
        self.cmb_record_rate.setMinimumWidth(
            self._combo_tight_width(
                self.cmb_record_rate,
                [self.cmb_record_rate.itemText(i)
                 for i in range(self.cmb_record_rate.count())],
            )
        )
        layout.addWidget(self.cmb_record_rate)

        # 循环播放
        self.btn_loop = QPushButton("⟳")
        self.btn_loop.setToolTip(tr("transport.tip_loop"))
        self.btn_loop.setCheckable(True)
        style_when_theme(self.btn_loop, _button_qss())
        self.btn_loop.toggled.connect(lambda v: self.loopToggled.emit(v))
        layout.addWidget(self.btn_loop)

        # 播放速率
        self.cmb_speed = QComboBox()
        for label, val in [
            ("0.5x", 0.5), ("0.75x", 0.75), ("1.0x", 1.0),
            ("1.25x", 1.25), ("1.5x", 1.5), ("2.0x", 2.0),
        ]:
            self.cmb_speed.addItem(label, val)
        self.cmb_speed.setCurrentIndex(2)  # 1.0x
        self.cmb_speed.setToolTip(tr("transport.tip_rate"))
        self.cmb_speed.setMaximumWidth(70)
        # H6 让位序：速率段是可省元素（最小宽收到「0.75x 本身够读」）
        self.cmb_speed.setMinimumWidth(
            self._combo_tight_width(
                self.cmb_speed,
                [self.cmb_speed.itemText(i) for i in range(self.cmb_speed.count())],
            )
        )
        self.cmb_speed.currentIndexChanged.connect(
            lambda _: self.speedChanged.emit(float(self.cmb_speed.currentData()))
        )
        layout.addWidget(self.cmb_speed)

        # G13：速率读数前缀——左侧倍速下拉本身是裸「1.0x」，右侧读数裸「1.00x」，
        # 两个裸 x 值并排会被读成「播放速率 / 缩放」两套单位。加「速率」前缀后
        # 读数语义自明；读数文本本身保持两位小数（既有读数判据逐字不变）。
        self.lbl_speed_label = QLabel(tr("transport.rate_label"))
        self.lbl_speed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_speed_label.setToolTip(tr("transport.speed_readout"))
        style_when_theme(
            self.lbl_speed_label,
            lambda c: (
                f" color: {c['sub']};"
                f" font-size: {TOKENS['typography']['caption']}px;"
            ),
        )
        self.lbl_speed_label.hide()  # 与读数同位展开（窄态一并收起）
        layout.addWidget(self.lbl_speed_label)

        # CB-013 D-1：显式速度读数（只读，随 cmb_speed 更新；颜色/字号走令牌派生）
        self.lbl_speed_readout = QLabel("1.00x")
        self.lbl_speed_readout.setToolTip(tr("transport.speed_readout"))
        self.lbl_speed_readout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        style_when_theme(
            self.lbl_speed_readout,
            lambda c: (
                f"font-family: {ui_mono_family_qss()};"
                f" font-size: {TOKENS['typography']['body']}px;"
                f" color: {c['sub']};"
            ),
        )
        self.cmb_speed.currentIndexChanged.connect(self._sync_speed_readout)
        self.lbl_speed_readout.hide()  # 初始窄态；宽裕时由 resizeEvent 展开
        layout.addWidget(self.lbl_speed_readout)

        layout.addSpacing(6)

        # CB-013 D-1：当前时间/总时长大号读数（HH:MM:SS.mmm 毫秒级，随主题派生色）
        self.lbl_current_time = _ClockLabel("00:00:00.000 / 00:00:00.000")
        self.lbl_current_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        style_when_theme(
            self.lbl_current_time,
            lambda c: (
                f"font-family: {ui_mono_family_qss()};"
                f" font-size: {TOKENS['typography']['h3']}px;"
                f" color: {c['text']}; background: {c['input']};"
                f" padding: 1px 8px;"
                f" border-radius: {TOKENS['radius']['sm']}px;"
            ),
        )
        layout.addWidget(self.lbl_current_time)

        layout.addSpacing(6)

        # 播放进度条（占弹性空间）
        self.slider_position = QSlider(Qt.Orientation.Horizontal)
        self.slider_position.setRange(0, 1000)
        self.slider_position.setValue(0)
        self.slider_position.setToolTip(tr("transport.tip_position"))
        self.slider_position.setStyleSheet(
            "QSlider{max-height:18px;}"
        )
        self.slider_position.sliderMoved.connect(self.seekPreview.emit)
        self.slider_position.sliderReleased.connect(self.seekCommit.emit)
        layout.addWidget(self.slider_position, stretch=1)

        # 与原 toolbar 一致的高度上限
        self.setMaximumHeight(30)

    # ------------------------------------------------------------------
    # 窄态折叠（D1 附带：条宽 < 760 时收起输入设备名）
    # ------------------------------------------------------------------

    def _combo_arrow_reserve(self) -> int:
        """下拉箭头 + 文字左右内边距的预留宽（走 TOKENS，禁字面像素）。

        实测：再收 6px 就会把「44k」压成空框（下拉内部另吃边框内边距），故保留
        两个 sm——极端窄态下宁可让「速率段」先省略，也不让设备名少字（H6 优先序）。
        """
        return int(TOKENS["spacing"]["sm"] * 2 + TOKENS["control"]["gap"])

    def _combo_tight_width(self, combo, texts) -> int:
        """下拉「可辨下限」：最宽条目文本 + 箭头预留。

        H6 的让位优先序里，速率/采样率段是**可省元素**——它们的最小宽收到
        「文本本身就够读」，富余宽照旧由 sizeHint 提供（宽态显示不受影响）。
        """
        fm = combo.fontMetrics()
        widest = max((fm.horizontalAdvance(t) for t in texts), default=0)
        return int(widest + self._combo_arrow_reserve())

    def _device_combo_stub_width(self) -> int:
        """设备下拉「桩宽」：空表/极窄窗时的下限（前 2 字 + 箭头预留），恒在位。"""
        fm = self.cmb_input_device.fontMetrics()
        head = (tr("record.device_none") or "")[:2]
        return int(fm.horizontalAdvance(head) + self._combo_arrow_reserve())

    def _device_combo_min_width(self) -> int:
        """设备下拉最小宽（H6 口径）：**当前显示文本**整句可读 + 箭头预留。

        取当前项文本而非最坏文案：空表时回落到桩宽（不撑条），条目填入后由
        `_sync_device_min_width`（currentIndexChanged）自动抬到「（无输入设备）」
        整句可读宽；用户切设备时同样跟随，故不会退化成空框/省略号。
        """
        fm = self.cmb_input_device.fontMetrics()
        text = (self.cmb_input_device.currentText() or "").strip()
        stub = self._device_combo_stub_width()
        if not text:
            return stub
        return max(stub, int(fm.horizontalAdvance(text) + self._combo_arrow_reserve()))

    def _sync_device_min_width(self) -> None:
        """设备条目/选中项变化 → 重算设备下拉最小宽（最小宽随内容自适应）。"""
        try:
            self.cmb_input_device.setMinimumWidth(self._device_combo_min_width())
        except Exception:  # noqa: BLE001 — 宽度自适应永不抛
            pass

    def resizeEvent(self, event) -> None:  # noqa: N802 (override)
        super().resizeEvent(event)
        self._apply_compact(self.width())

    def _apply_compact(self, width: int) -> None:
        """窄态折叠：只收「速率读数/前缀」与时间读数下限，设备选择器恒在位（H6）。

        优先级：设备选择器 > 播放/录音按钮 > 时间读数 > 速率读数。
        窗口极窄时时间读数以中部省略显示，控件本身仍在位。
        """
        want_wide = width >= _COMPACT_W
        for widget in (self.lbl_speed_label, self.lbl_speed_readout):
            if want_wide and widget.isHidden():
                widget.show()
            elif not want_wide and not widget.isHidden():
                widget.hide()
        # 时间读数让位（H6 的第一顺位可省元素）：窄态下限与上限同时收口，
        # 富余宽改由设备选择器等不可省控件吸收；宽态恢复原口径。
        tight = width < _TIGHT_W
        # G1（真机复核）：tight 档同排 9 类控件总需求远超条宽，Qt 把无损
        # 时钟读数压到文本需求以下（真机 AX 只露「/ 00」）。收起一组次要
        # 控件（跳转/循环/采样率/速率下拉）给 lbl_current_time 让位，使其
        # 至少拿到自身 sizeHint；非 tight 档（含宽态）一律恢复显示，杜绝
        # 状态泄漏。收起清单不含输入设备下拉（H6 恒在位）与播放/录音/停止
        # 核心按钮。让位结果由 lbl 的 sizeHint/horizontalAdvance 决定，
        # 不引入任何硬编码尺寸。
        omit_secondary = tight
        for widget in (self.btn_skip_start, self.btn_skip_end, self.btn_loop,
                       self.cmb_record_rate, self.cmb_speed):
            if omit_secondary and not widget.isHidden():
                widget.hide()
            elif not omit_secondary and widget.isHidden():
                widget.show()
        self.lbl_current_time.set_compact(tight)
        self.lbl_current_time.set_min_width(
            _CLOCK_MIN_W_TIGHT if tight else _CLOCK_MIN_W
        )
        if want_wide:
            self.lbl_current_time.setMaximumWidth(_CLOCK_MAX_W)
        else:
            self.lbl_current_time.setMaximumWidth(
                _CLOCK_MAX_W_TIGHT if tight else _CLOCK_MAX_W_NARROW
            )
        self._sync_device_min_width()
        # 输入设备选择器：任何宽度下都必须可见（显式收口，防外部误隐藏）
        if self.cmb_input_device.isHidden():
            self.cmb_input_device.show()

    # ------------------------------------------------------------------
    # 按钮状态同步（与原 waveform 同名同行为，blockSignals 不触发信号）
    # ------------------------------------------------------------------

    def set_play_button_state(self, playing: bool):
        """设置播放按钮状态。"""
        self.btn_play.blockSignals(True)
        self.btn_play.setChecked(playing)
        self.btn_play.setText("⏸" if playing else "▶")
        self.btn_play.blockSignals(False)

    def set_record_button_state(self, recording: bool):
        """设置录音按钮状态（录音中变身「■ 停止」，空闲恢复「● 录音」）。"""
        self.btn_record.blockSignals(True)
        self.btn_record.setChecked(recording)
        if recording:
            self.btn_record.setText("■")
            self.btn_record.setToolTip(tr("transport.tip_stop_record"))
        else:
            self.btn_record.setText("●")
            self.btn_record.setToolTip(tr("transport.tip_record"))
        self.btn_record.blockSignals(False)

    def set_loop_state(self, checked: bool):
        """设置循环播放按钮状态（不触发信号）。"""
        self.btn_loop.blockSignals(True)
        self.btn_loop.setChecked(checked)
        self.btn_loop.blockSignals(False)

    # ------------------------------------------------------------------
    # 进度/时间显示
    # ------------------------------------------------------------------

    def set_seek_percent(self, permille: int):
        """设置进度滑条（0-1000 千分比，不触发信号）。"""
        self.slider_position.blockSignals(True)
        self.slider_position.setValue(int(permille))
        self.slider_position.blockSignals(False)

    def _sync_speed_readout(self):
        """速率下拉变化 → 只读读数刷新（如 1.00x / 0.50x）。"""
        data = self.cmb_speed.currentData()
        text = f"{float(data):.2f}x" if data is not None else "1.00x"
        if self.lbl_speed_readout.text() != text:
            self.lbl_speed_readout.setText(text)

    def set_time_label(self, current_sec: float, total_sec: float):
        """显示 当前时间/总时长（HH:MM:SS.mmm 毫秒级，DAW 大号读数）。

        无音频时显示 00:00:00.000 / 00:00:00.000（控件初始文本）；
        总时长未知（None/NaN/负数）显示 ``--:--:--.---``。
        全量文本由控件持有，窄态自动以中部省略显示（不撑条）。
        """
        self.lbl_current_time.set_full_text(
            f"{format_transport_clock(current_sec)} / "
            f"{format_transport_clock(total_sec)}"
        )
