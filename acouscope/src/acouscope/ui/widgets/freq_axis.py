# SPDX-License-Identifier: GPL-3.0-only
"""Y 轴频率单位切换工具（音高/语谱图/共振峰共用）。

单位集与 FFT 频谱窗口的 X 轴一致（Hz/kHz/MIDI/钢琴卷帘/音分/Mel）：
- 散点/折线：freq_to_display() 直接变换数值
- 图像（语谱图）：resample_rows() 把 (n_freq, n_time) 矩阵重采样到
  目标单位空间的均匀网格（pyqtgraph ImageItem 只支持线性坐标，
  非线性映射必须在数据层完成）
- 刻度：midi/piano 模式用音名刻度（note_name_ticks），
  其余单位用 pyqtgraph 自动数值刻度
- 钢琴卷帘模式：PianoKeyboardStrip 在宿主图左侧显示竖排钢琴键盘
  （Y=MIDI 坐标联动，与 FFT 频谱窗口的横排键盘同款样式）
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox

from acouscope.dsp.units import (
    FREQ_UNITS,
    cents_to_hz,
    convert_freq_axis,
    hz_to_cents,
    hz_to_mel,
    hz_to_midi,
    mel_to_hz,
    midi_to_hz,
)
from acouscope.ui import theme


def _apply_canvas_theme(plot_widget, bg_role: str = "bg1") -> None:
    """画布并入主题（T-1032）：底色取中性阶，轴/刻度/网格随主题着色。

    pyqtgraph 的 ``setBackground`` 与轴笔不走 QSS，故主题变化时须显式重设。
    网格线沿用轴笔颜色（`showGrid` 的 alpha 不变）→ 随之着色。
    """
    c = theme.colors()
    plot_widget.setBackground(c[bg_role])
    for side in ("left", "bottom", "right", "top"):
        axis = plot_widget.getAxis(side)
        axis.setPen(c["text_sub"])
        axis.setTextPen(c["text_sub"])
        axis.setLabel(
            axis.labelText, units=axis.labelUnits,
            **{**axis.labelStyle, "color": c["text"]},
        )

# 各单位的左轴标签：(标签文本, 单位后缀)；后缀 None 表示不带 units
FREQ_AXIS_LABELS = {
    "hz": ("频率", "Hz"),
    "khz": ("频率", "kHz"),
    "midi": ("MIDI 音高", None),
    "piano": ("音高（钢琴卷帘）", None),
    "cents": ("音分（相对 A4=440Hz）", None),
    "mel": ("Mel 频率", None),
}


def freq_to_display(freq_hz, unit: str):
    """频率(Hz) → 当前单位坐标值。支持标量与数组。"""
    arr = np.asarray(freq_hz, dtype=float)
    out = convert_freq_axis(arr, unit)
    if arr.ndim == 0:
        return float(out)
    return out


def display_to_freq(val, unit: str):
    """当前单位坐标值 → 频率(Hz)。支持标量与数组。"""
    arr = np.asarray(val, dtype=float)
    if unit == "khz":
        out = arr * 1000.0
    elif unit in ("midi", "piano"):
        out = midi_to_hz(arr)
    elif unit == "cents":
        out = cents_to_hz(arr)
    elif unit == "mel":
        out = mel_to_hz(arr)
    else:
        out = arr
    if arr.ndim == 0:
        return float(out)
    return out


def set_freq_axis_label(plot_widget, unit: str, side: str = "left") -> None:
    """按单位设置频率轴标签。"""
    text, units = FREQ_AXIS_LABELS.get(unit, ("频率", "Hz"))
    plot_widget.setLabel(side, text, units=units)


def note_name_ticks(lo: float, hi: float) -> list[tuple[float, str]]:
    """MIDI 坐标区间的八度 C 音名刻度（C2、C3...，C4 另注中央C）。"""
    from acouscope.dsp.units import midi_note_name

    ticks = []
    start = max(int(np.ceil(lo / 12.0)) * 12, 0)
    end = min(int(np.floor(hi)), 127)
    for m in range(start, end + 1):
        if m % 12 == 0:
            label = midi_note_name(m)
            if m == 60:
                label = "C4(中央C)"
            ticks.append((float(m), label))
    return ticks


def resample_rows(
    freqs_hz: np.ndarray,
    matrix: np.ndarray,
    unit: str,
    n_out: int = 256,
    min_hz: float = 20.0,
):
    """把 (n_freq, n_time) 矩阵重采样到目标单位空间的均匀网格。

    Args:
        freqs_hz: 频率轴 (n_freq,)，必须单调递增且 > 0
        matrix: 数据矩阵 (n_freq, n_time)
        unit: 目标单位
        n_out: 输出网格点数
        min_hz: 低频截断（极低频在音分/Mel 单位下会压缩到负无穷远处）

    Returns:
        (grid, new_matrix)：grid 为目标单位下的均匀坐标 (n_out,)
    """
    x_hz = np.asarray(freqs_hz, dtype=float)
    x_hz = x_hz[x_hz >= min_hz]
    rows = matrix[-len(x_hz):, :] if len(x_hz) < len(freqs_hz) else matrix

    x_unit = np.asarray(convert_freq_axis(x_hz, unit), dtype=float)
    grid = np.linspace(float(x_unit[0]), float(x_unit[-1]), n_out)
    out = np.empty((n_out, matrix.shape[1]), dtype=float)
    for j in range(matrix.shape[1]):
        out[:, j] = np.interp(grid, x_unit, rows[:, j])
    return grid, out


def format_freq_readout(freq_hz: float, unit: str) -> str:
    """按单位格式化频率读数（信息栏用）。"""
    if freq_hz <= 0 or not np.isfinite(freq_hz):
        return "--"
    if unit == "khz":
        return f"{freq_hz / 1000.0:.2f} kHz"
    if unit in ("midi", "piano"):
        from acouscope.dsp.units import midi_note_name

        midi = hz_to_midi(freq_hz)
        return f"MIDI {float(midi):.2f} ({midi_note_name(int(round(midi)))})"
    if unit == "cents":
        return f"{float(hz_to_cents(freq_hz)):+,.0f} 音分"
    if unit == "mel":
        return f"{float(hz_to_mel(freq_hz)):.0f} mel"
    return f"{freq_hz:.1f} Hz"


def fit_combo_width(combo: QComboBox) -> None:
    """下拉框宽度自适应最长条目（含下拉箭头与边距），避免文字截断。"""
    from PyQt6.QtGui import QFontMetrics

    fm = QFontMetrics(combo.font())
    text_w = max(
        (fm.horizontalAdvance(combo.itemText(i)) for i in range(combo.count())),
        default=0,
    )
    width = text_w + 48
    combo.setMinimumWidth(width)
    combo.setMaximumWidth(width)


def build_freq_unit_combo(parent=None) -> QComboBox:
    """构建频率单位下拉框（单位集与 FFT 频谱窗口一致）。"""
    combo = QComboBox(parent)
    for label, key, tip in FREQ_UNITS:
        combo.addItem(label, key)
        combo.setItemData(combo.count() - 1, tip, Qt.ItemDataRole.ToolTipRole)
    fit_combo_width(combo)
    return combo


class PianoKeyboardStrip(pg.PlotWidget):
    """竖排钢琴键盘条（Y=MIDI 坐标，供 Y 轴频率窗口的钢琴卷帘模式显示）。

    与 FFT 频谱窗口的横排键盘同款样式（白键全宽、黑键居中偏左、
    C4 中央 C 音名文字加粗、左轴 C 音名刻度），键位静态绘制全音域
    (MIDI 0~127)，由 Y 轴联动裁剪到当前视图。
    """

    WHITE_W = 4.0   # 白键横向宽度（本条内部 X 坐标）
    # T-1042：黑键宽 2.36 = WHITE_W × 0.59（真实钢琴黑键宽 ∈ [0.58, 0.60] 白键宽）
    BLACK_W = 2.36  # 黑键横向宽度
    # T-1042：黑键居中偏左 —— (WHITE_W − BLACK_W)/2 = 0.82 为居中位，再略左移 0.12
    # 表达真实钢琴黑键偏左（ARCH §五c-3：约 5–10%）；原 1.7 贴右侧是「歪」因。
    BLACK_X0 = 0.70  # 黑键起点（居中偏左）
    BLACK_H = 0.58   # 黑键纵向高（半音 × 0.58 ∈ [0.58, 0.62]）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._key_items: list = []
        self.setMouseEnabled(x=False, y=False)
        self.getPlotItem().setMenuEnabled(False)
        self.setMinimumWidth(46)
        self.setMaximumWidth(62)
        self.hideAxis("right")
        self.hideAxis("top")
        self.setContentsMargins(0, 0, 0, 0)
        self.getAxis("left").setStyle(tickTextOffset=2, tickLength=4)
        self.enableAutoRange(x=False, y=False)
        self.setXRange(0, self.WHITE_W, padding=0)
        # 注：底部轴保留（不 hideAxis）——隐藏底轴会触发 pyqtgraph
        # 视图联动机制的几何偏差；改为空刻度 + 不显示数值即可视觉隐形
        self.getAxis("bottom").setStyle(showValues=False)
        self.getAxis("bottom").setTicks([])

        from acouscope.dsp.units import midi_note_name

        # 左轴 C 音名刻度（静态全音域，超出视图自动裁剪）
        ticks = []
        for midi in range(0, 128, 12):
            label = midi_note_name(midi)
            if midi == 60:
                label = "C4(中央C)"
            ticks.append((float(midi), label))
        self.getAxis("left").setTicks([ticks])

        # 中央 C 文字强调（T-1042）：原「金色描边框」已废除（违 §2.1-3 反馈色当装饰），
        # 改为在中央 C 键上叠一个**加粗**音名标签（复用 note_name_ticks 文案），不用任何语义色。
        from PyQt6.QtGui import QFont

        cfont = QFont()
        cfont.setBold(True)
        self._center_c_label = pg.TextItem(
            "C4(中央C)", color=theme.colors()["text_sub"],
            anchor=(1.0, 0.5), border=None, fill=None,
        )
        self._center_c_label.textItem.setFont(cfont)
        self._center_c_label.setPos(self.WHITE_W, 60.0)
        self.addItem(self._center_c_label)

        theme.on_theme_change(self._on_canvas_theme)
        self._on_canvas_theme()

    def _on_canvas_theme(self) -> None:
        """主题切换：重设键盘带底色/轴色并重建键面（键色随主题令牌）。"""
        _apply_canvas_theme(self, "bg2")
        self._center_c_label.setColor(theme.colors()["text_sub"])
        self._build_keys()

    def _build_keys(self) -> None:
        """按当前主题令牌重建 128 键键面（T-1042：分层明度 + 去强描边 + 去金色 + 黑键圆角）。

        分层顺序：先铺整条键带底（keys.strip，比黑键更暗让键「浮」出），
        再叠白键面（keys.white + keys.white_seam 极细分隔，禁亮于键面的描边），
        再叠黑键（keys.black，圆角、无描边）。中央 C 与其它白键同色（去金色）。
        """
        from acouscope.dsp.units import midi_is_black_key, midi_is_white_key

        for item in self._key_items:
            self.removeItem(item)
        self._key_items = []

        faces = theme.key_faces()
        strip_brush = pg.mkBrush(faces["strip"])
        white_brush = pg.mkBrush(faces["white"])
        # 白键间分隔：用 keys.white_seam（比白键暗），禁 border（壳色，会亮于键面 → 「格子纸」）
        seam_pen = pg.mkPen(faces["white_seam"], width=0.15)
        black_brush = pg.mkBrush(faces["black"])
        no_pen = pg.mkPen(None)

        # ① 键带底：铺满整条的底（gutter），比黑键更暗
        strip = pg.QtWidgets.QGraphicsRectItem(0, -0.5, self.WHITE_W, 128.0)
        strip.setBrush(strip_brush)
        strip.setPen(no_pen)
        strip.setZValue(-20)
        self.addItem(strip)
        self._key_items.append(strip)

        # ② 白键（全宽、直角；真实白键为直角不加圆角）
        for midi in range(128):
            if midi_is_white_key(midi):
                rect = pg.QtWidgets.QGraphicsRectItem(0, midi - 0.5, self.WHITE_W, 1.0)
                rect.setBrush(white_brush)
                rect.setPen(seam_pen)
                self.addItem(rect)
                self._key_items.append(rect)

        # ③ 黑键（居中偏左、较窄、顶层、圆角、无描边）
        radius = self.BLACK_W * 0.17  # 圆角 ≈ 黑键宽 17%（ARCH §五c 建议 15–20%）
        for midi in range(128):
            if midi_is_black_key(midi):
                path = pg.QtGui.QPainterPath()
                half = self.BLACK_H / 2.0
                path.addRoundedRect(
                    self.BLACK_X0, midi - half, self.BLACK_W, self.BLACK_H,
                    radius, radius,
                )
                item = pg.QtWidgets.QGraphicsPathItem(path)
                item.setBrush(black_brush)
                item.setPen(no_pen)
                item.setZValue(20)
                self.addItem(item)
                self._key_items.append(item)

    def follow(self, host_plot_widget) -> None:
        """让键盘条精确跟随宿主图的 Y 轴范围。

        不用 ViewBox.setYLink：pyqtgraph 的联动机制在底轴隐藏/空白时
        存在几何性偏差（实测低端偏移 ~0.5 半音）；改为监听宿主
        sigYRangeChanged 手动同步，逐次精确。
        """
        host_vb = host_plot_widget.getPlotItem().vb
        host_vb.sigYRangeChanged.connect(self._on_host_y_range)
        y0, y1 = host_vb.viewRange()[1]
        self._on_host_y_range(host_vb, (y0, y1))

    def _on_host_y_range(self, _vb, y_range) -> None:
        lo, hi = float(min(y_range)), float(max(y_range))
        if np.isfinite(lo) and np.isfinite(hi) and hi > lo:
            self.plotItem.vb.setYRange(lo, hi, padding=0)
