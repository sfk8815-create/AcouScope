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
    get_reference_hz,
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
    "cents": (f"音分（相对 A4={get_reference_hz():.0f}Hz）", None),
    "mel": ("Mel 频率", None),
}


def rounded_end_rect(x: float, y: float, w: float, h: float, r: float,
                     end: str = "right") -> pg.QtGui.QPainterPath:
    """矩形**一端两角圆角**路径（对端直角）：`end` ∈ {"right","left","top","bottom"}。

    T-1042b：参考图黑键「自左缘起算」/白键右端小圆角——`addRoundedRect` 会四角同圆角，
    圆角端的对端也会被掏空（破坏贴左/贴边/贴缝），故手绘路径。竖横两键盘共用（同一取值来源）。
    """
    r = min(float(r), w / 2.0, h / 2.0)
    path = pg.QtGui.QPainterPath()
    if end == "right":
        path.moveTo(x, y)
        path.lineTo(x + w - r, y)
        path.quadTo(x + w, y, x + w, y + r)
        path.lineTo(x + w, y + h - r)
        path.quadTo(x + w, y + h, x + w - r, y + h)
        path.lineTo(x, y + h)
    elif end == "left":
        path.moveTo(x + w, y)
        path.lineTo(x + r, y)
        path.quadTo(x, y, x, y + r)
        path.lineTo(x, y + h - r)
        path.quadTo(x, y + h, x + r, y + h)
        path.lineTo(x + w, y + h)
    elif end == "top":
        path.moveTo(x, y + h)
        path.lineTo(x, y + r)
        path.quadTo(x, y, x + r, y)
        path.lineTo(x + w - r, y)
        path.quadTo(x + w, y, x + w, y + r)
        path.lineTo(x + w, y + h)
    else:  # bottom
        path.moveTo(x, y)
        path.lineTo(x + w, y)
        path.lineTo(x + w, y + h - r)
        path.quadTo(x + w, y + h, x + w - r, y + h)
        path.lineTo(x + r, y + h)
        path.quadTo(x, y + h, x, y + h - r)
        path.lineTo(x, y)
    path.closeSubpath()
    return path


def make_seam_pen(pen):
    """白键缝笔 → cosmetic（线宽按设备像素计、不随 ViewBox 缩放）。

    T-1079 ①：0.15 场景单位线宽在缩小视图下不足一个设备像素、被抗锯齿吞没
    → 白键间几乎无缝。cosmetic 后恒一设备像素，任意缩放缝可见；色值仍取
    keys.white_seam，不在此派生暗色/回写 theme。竖横两键盘带共用。
    """
    pen.setCosmetic(True)
    pen.setWidth(1)
    return pen


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

    与 FFT 频谱窗口的横排键盘同款样式（T-1042b v2 定形：黑键**贴左** + 白键右端
    **小圆角** + 键面**单套物理色**明暗同款 + 缩放只变键距键长不变）。
    T-1042c v3：**能渲染**（隐藏音名轴 → ViewBox 占满条宽，键像素 > 0）、
    **键床连续**（keys.white 连续铺满整条，除 1–2 像素细缝外无背景色像素）、
    **音名落位键床内**（§2.1-②，文案沿用现有音名形态，色 keys.label）。
    键位静态绘制全音域 (MIDI 0~127)，由 Y 轴联动裁剪到当前视图。
    """

    WHITE_W = 4.0   # 白键横向满宽（本条内部 X 坐标；参考图 74 像素）
    # T-1042b v2 定形（按最高指挥参考图）：
    # 黑键**贴左**（BLACK_X0=0 零内缩）、长 = 白键满宽 × 0.46（参考图 34/74，旧 0.59 作废）、
    # 高 = 半音 × 0.55（参考图 28/52）、上缘贴所属半音的**键缝**一侧（不再上下留半缝居中）。
    BLACK_W = WHITE_W * 0.46   # 黑键横向长度（长比 0.46）
    BLACK_X0 = 0.0             # 黑键起点（贴左，零内缩）
    BLACK_H = 0.55             # 黑键纵向高（半音 × 0.55）
    # 圆角（ARCH §五c v1.5）：白键右端 r ≈ 半音高 6–10%（取 8%）；
    # 黑键右端 r ≈ 黑键高 15–20%（取 17%）。竖横两键盘共用此常量。
    WHITE_KEY_R = 0.08
    BLACK_KEY_R = BLACK_H * 0.17
    # T-1042c：音名内嵌键床时的自由端留白（占键床宽/高的比例，竖横同源）
    LABEL_INSET = 0.03

    def __init__(self, parent=None):
        super().__init__(parent)
        self._key_items: list = []
        self._name_labels: list = []
        self._center_c_label = None
        self.setMouseEnabled(x=False, y=False)
        self.getPlotItem().setMenuEnabled(False)
        self.setMinimumWidth(46)
        self.setMaximumWidth(62)
        self.hideAxis("right")
        self.hideAxis("top")
        # ★ T-1042c 缺陷 A：音名轴（自然宽 ≈65 像素）此前把 62 像素条宽的 ViewBox 挤成 8 像素
        # → 键面被裁到部件外，一个键像素都画不出来。现隐藏音名轴，音名改画进键床内
        # （§2.1-②，与参考图一致）→ ViewBox 占满条宽，键面真被绘制（实测见报告）。
        self.hideAxis("left")
        self.setContentsMargins(0, 0, 0, 0)
        self.getAxis("left").setStyle(tickTextOffset=2, tickLength=4)
        self.enableAutoRange(x=False, y=False)
        self.setXRange(0, self.WHITE_W, padding=0)
        # 注：底部轴保留（不 hideAxis）——隐藏底轴会触发 pyqtgraph
        # 视图联动机制的几何偏差；改为空刻度 + 不显示数值即可视觉隐形
        self.getAxis("bottom").setStyle(showValues=False)
        self.getAxis("bottom").setTicks([])

        theme.on_theme_change(self._on_canvas_theme)
        self._on_canvas_theme()

    def _on_canvas_theme(self) -> None:
        """主题切换：重设键盘带底色/轴色并重建键面（键色单套物理色，不随骨架变）。"""
        _apply_canvas_theme(self, "bg2")
        self._build_keys()

    @staticmethod
    def _name_fonts() -> tuple:
        """键床内音名文字字体（字号取 typography 令牌，唯一源在 theme.py）。"""
        from PyQt6.QtGui import QFont

        base = QFont()
        base.setPixelSize(theme.TOKENS["typography"]["caption_sm"])
        bold = QFont(base)
        bold.setBold(True)
        return base, bold

    @staticmethod
    def note_label(midi: int) -> str:
        """音名文案（沿用现有音名形态；中央 C 仍为「C4(中央C)」）。"""
        from acouscope.dsp.units import midi_note_name

        return "C4(中央C)" if midi == 60 else midi_note_name(midi)

    def _build_keys(self) -> None:
        """重建 128 键键面（T-1042c v3：键床连续 + 音名落位键床内）。

        分层顺序（自下而上）：
        ① 键带底（随骨架 bg2，仅作底板，z=-20）；
        ② ★ 键床底 keys.white **连续铺满整条**（ARCH §五c v1.6 §3-ter-1，z=-10）
           ——除白键细缝外键床内不得出现任何背景色像素；
        ③ 白键面（keys.white + keys.white_seam 1–2 像素细缝，右端小圆角，z=0）；
        ④ 黑键（keys.black，贴左 x=0、长 0.46、半音向 0.55、右端圆角，无描边，z=20）；
        ⑤ 音名（keys.label，画进键床内，z=30）：中央 C「C4(中央C)」加粗。
        """
        from acouscope.dsp.units import midi_is_black_key, midi_is_white_key

        for item in self._key_items:
            self.removeItem(item)
        self._key_items = []

        faces = theme.key_faces()
        # 键带底/gutter 随骨架 bg2（ARCH §五c v1.5：仅作底板，不参与视觉分层）
        strip_brush = pg.mkBrush(theme.colors()["bg2"])
        white_brush = pg.mkBrush(faces["white"])
        # 白键间分隔：用 keys.white_seam（比白键暗），禁 border（壳色，会亮于键面 → 「格子纸」）
        # T-1079 ①：cosmetic 设备像素宽，任意缩放缝可见（0.15 场景单位缩小下被 AA 吞没）
        seam_pen = make_seam_pen(pg.mkPen(faces["white_seam"], width=0.15))
        black_brush = pg.mkBrush(faces["black"])
        no_pen = pg.mkPen(None)

        # ① 键带底：铺满整条的底（gutter），随骨架 bg2
        strip = pg.QtWidgets.QGraphicsRectItem(0, -0.5, self.WHITE_W, 128.0)
        strip.setBrush(strip_brush)
        strip.setPen(no_pen)
        strip.setZValue(-20)
        self.addItem(strip)
        self._key_items.append(strip)

        # ② 键床底：keys.white 连续铺满整条（T-1042c §3-ter-1）——白键不再画成互不接触的块
        bed = pg.QtWidgets.QGraphicsRectItem(0, -0.5, self.WHITE_W, 128.0)
        bed.setBrush(white_brush)
        bed.setPen(no_pen)
        bed.setZValue(-10)
        self.addItem(bed)
        self._key_items.append(bed)

        # ③ 白键（全宽、右端小圆角 r ≈ 半音高 8%；左端直角贴边；描边即白键间细缝）
        for midi in range(128):
            if midi_is_white_key(midi):
                path = rounded_end_rect(
                    0, midi - 0.5, self.WHITE_W, 1.0, self.WHITE_KEY_R, end="right",
                )
                item = pg.QtWidgets.QGraphicsPathItem(path)
                item.setBrush(white_brush)
                item.setPen(seam_pen)
                self.addItem(item)
                self._key_items.append(item)

        # ④ 黑键（贴左、上缘贴缝、右端圆角、顶层、无描边）
        for midi in range(128):
            if midi_is_black_key(midi):
                path = rounded_end_rect(
                    self.BLACK_X0, midi + 0.5 - self.BLACK_H,
                    self.BLACK_W, self.BLACK_H, self.BLACK_KEY_R, end="right",
                )
                item = pg.QtWidgets.QGraphicsPathItem(path)
                item.setBrush(black_brush)
                item.setPen(no_pen)
                item.setZValue(20)
                self.addItem(item)
                self._key_items.append(item)

        # ⑤ 音名画进键床内（T-1042c §2.1-②）：右端对齐键床自由端，色取 keys.label
        base_font, bold_font = self._name_fonts()
        self._name_labels = []
        self._center_c_label = None
        for midi in range(0, 128, 12):
            is_center = midi == 60
            txt = pg.TextItem(
                self.note_label(midi), color=faces["label"],
                anchor=(1.0, 0.5), border=None, fill=None,
            )
            txt.textItem.setFont(bold_font if is_center else base_font)
            txt.setPos(self.WHITE_W - self.LABEL_INSET * self.WHITE_W, float(midi))
            txt.setZValue(30)
            self.addItem(txt)
            self._name_labels.append(txt)
            if is_center:
                self._center_c_label = txt

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
