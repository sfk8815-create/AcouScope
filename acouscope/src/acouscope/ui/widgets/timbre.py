# SPDX-License-Identifier: GPL-3.0-only
"""音色特征分析显示控件。"""

from __future__ import annotations

import csv
import os
import time

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QFileDialog,
)

from acouscope.ui import theme
from acouscope.ui.widgets.time_axis import apply_time_axis
from acouscope.ui.widgets.toast import show_toast


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


# 全局特征中文名映射（顺序即显示顺序）
GLOBAL_FEATURE_LABELS = {
    "peak_dbfs": ("峰值电平 (dBFS)", "{:.1f} dBFS"),
    "rms_db": ("RMS 电平 (dB)", "{:.1f} dB"),
    "crest_factor": ("波峰因数 (dB)", "{:.1f} dB"),
    "dc_offset": ("DC 偏移 (%)", "{:+.4f} %"),
    "attack_time": ("起振时间 10%→90%", "{:.0f} ms"),
    "decay_time": ("衰减时间 −20 dB", "{:.0f} ms"),
    "zcr": ("过零率 (Hz)", "{:.1f} Hz"),
    "spectral_centroid": ("频谱质心 (Hz)", "{:.1f} Hz"),
    "spectral_bandwidth": ("频谱带宽 (Hz)", "{:.1f} Hz"),
    "spectral_rolloff": ("频谱滚降 85% (Hz)", "{:.1f} Hz"),
    "spectral_flatness": ("频谱平坦度 (0–1)", "{:.4f}"),
    "spectral_skewness": ("频谱偏度", "{:.2f}"),
    "spectral_kurtosis": ("频谱峭度（超额）", "{:.2f}"),
}

FEATURE_COUNT = 5


def feature_colors() -> dict[str, str]:
    """特征曲线多序列取色：T-1036 内容色板前 5 色（T-1038 M2，禁另造第二套分类色）。"""
    palette = theme.track_palette()
    return {
        "centroid": palette[0],
        "bandwidth": palette[1],
        "rolloff": palette[2],
        "flatness": palette[3],
        "flux": palette[4 % len(palette)],
    }


def _meta_qss(extra: str = "") -> str:
    """次级读数标签 QSS（T-1038 M3：令牌插值，禁字面 hex/px）。"""
    return (f"color: {theme.colors()['text_sub']};"
            f" font-size: {theme.TOKENS['typography']['body_sm']}px;{extra}")


class TimbreWidget(QWidget):
    """音色特征分析控件。

    四个页签：
    - MFCC 热图（时间 × 系数）
    - 谐波噪声比 (HNR) 曲线
    - 频谱特征曲线（质心/带宽/滚降 + 平坦度/通量子图）
    - 全局特征统计表（电平/包络/频谱形状三类描述符）
    """

    # T-323 播放联动信号：时间交互事件出口上抛，由 main_window 统一分发。
    # feature_plot（含 XLink 的 dim_plot）作为 xRange 代表；mfcc/hnr 各自独立。
    timeClicked = pyqtSignal(float)
    timeDoubleClicked = pyqtSignal(float)
    timeScrubbed = pyqtSignal(float)
    xRangeShifted = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._times = np.array([])
        self._mfcc = np.zeros((0, 0))
        self._hnr_times = np.array([])
        self._hnr = np.array([])
        self._features: dict = {}
        self._global_features: dict = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 信息栏
        info_bar = QHBoxLayout()
        info_bar.setContentsMargins(6, 4, 6, 4)
        self.lbl_title = QLabel("音色特征分析")
        self.lbl_title.setStyleSheet(
            f"font-weight: bold; font-size: {theme.TOKENS['typography']['body']}px;")
        info_bar.addWidget(self.lbl_title)
        info_bar.addStretch()
        self.lbl_info = QLabel("")
        self.lbl_info.setStyleSheet(_meta_qss())
        info_bar.addWidget(self.lbl_info)
        self.btn_export = QPushButton("导出 CSV")
        self.btn_export.setStyleSheet(
            f"font-size: {theme.TOKENS['typography']['body_sm']}px;"
            f" padding: {theme.TOKENS['spacing']['xxs']}px"
            f" {theme.TOKENS['control']['pad_x']}px;")
        self.btn_export.clicked.connect(self._on_export_csv)
        info_bar.addWidget(self.btn_export)
        layout.addLayout(info_bar)

        # 页签
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self._build_mfcc_tab()
        self._build_hnr_tab()
        self._build_features_tab()
        self._build_global_tab()

        # T-323 导航手势状态（feature_plot 为 xRange 代表；dim 已 XLink 跟随）
        self._scrubbing = False
        self._nav_press_view_t = None
        self._nav_plot = None  # 按下/scrub 所在 plot
        self._last_nav_click_at = -1.0
        self._last_nav_click_t = None
        self._xrange_blocked = False
        self._prev_view_x = None
        self._nav_scene_to_plot = {}
        for plot in (self.mfcc_plot, self.hnr_plot,
                     self.feature_plot, self.dim_plot):
            plot.scene().installEventFilter(self)
            plot.setMouseTracking(True)
            self._nav_scene_to_plot[plot.scene()] = plot
        self.feature_plot.plotItem.vb.sigRangeChanged.connect(
            self._on_view_range_changed
        )
        theme.on_theme_change(self._on_canvas_theme)

    def _apply_ink(self) -> None:
        """数据墨色（T-1038 M1/M6）：HNR 主轨迹 + 五条特征曲线随主题骨架取色。"""
        ink = feature_colors()
        self.hnr_curve.setPen(pg.mkPen(color=theme.data_ink("trace"), width=2.7))
        for curve, key in (
            (self.centroid_curve, "centroid"),
            (self.bandwidth_curve, "bandwidth"),
            (self.rolloff_curve, "rolloff"),
            (self.flatness_curve, "flatness"),
            (self.flux_curve, "flux"),
        ):
            curve.setPen(pg.mkPen(color=ink[key], width=2.7))

    def _on_canvas_theme(self):
        """主题切换：重设五个音色画布底色/轴色 + 数据墨色（pyqtgraph 不走 QSS）。"""
        _apply_canvas_theme(self.mfcc_plot)
        _apply_canvas_theme(self.mfcc_colorbar, "bg2")
        _apply_canvas_theme(self.hnr_plot)
        _apply_canvas_theme(self.feature_plot)
        _apply_canvas_theme(self.dim_plot)
        self._apply_ink()
        self.lbl_info.setStyleSheet(_meta_qss())
        for plot in (self.mfcc_plot, self.hnr_plot, self.feature_plot, self.dim_plot):
            plot.update()

    def _nav_plot_of(self, obj):
        """事件源 scene → 对应时间 plot（无则 None）。"""
        return self._nav_scene_to_plot.get(obj)

    def _nav_time_at(self, scene_pos, plot) -> float:
        """场景坐标 → 时间（秒），夹取到数据时间范围。"""
        vb = plot.plotItem.vb
        t = float(vb.mapSceneToView(scene_pos).x())
        if self._times.size:
            t = float(np.clip(t, float(self._times[0]), float(self._times[-1])))
        return t

    def _emit_nav_click(self, t: float, plot) -> None:
        """微拖抬起：0.35s + 1% 视宽口径区分单击/双击（与波形判定一致）。"""
        lo, hi = plot.viewRange()[0]
        span = max(hi - lo, 1e-9)
        now = time.monotonic()
        if (self._last_nav_click_t is not None
                and now - self._last_nav_click_at < 0.35
                and abs(t - self._last_nav_click_t) < span * 0.01):
            self._last_nav_click_at = -1.0
            self._last_nav_click_t = None
            self.timeDoubleClicked.emit(t)
        else:
            self.timeClicked.emit(t)
            self._last_nav_click_at = now
            self._last_nav_click_t = t

    def _on_view_range_changed(self):
        """feature_plot X 范围变化：仅"用户平移"上抛 xRangeShifted。"""
        vb = self.feature_plot.plotItem.vb
        lo, hi = float(vb.viewRange()[0][0]), float(vb.viewRange()[0][1])
        if self._xrange_blocked:
            self._prev_view_x = (lo, hi)
            return
        prev = self._prev_view_x
        self._prev_view_x = (lo, hi)
        if prev is None:
            return
        if abs(lo - prev[0]) < 1e-12 and abs(hi - prev[1]) < 1e-12:
            return
        prev_span = prev[1] - prev[0]
        if prev_span <= 0 or abs((hi - lo) - prev_span) > prev_span * 1e-3:
            return  # 缩放：不同步
        self.xRangeShifted.emit(lo, hi)

    def set_time_range(self, lo: float, hi: float) -> None:
        """程序性同步 X 时间窗（跨视图平移/播放跟随入口，防自激上抛）。

        dim_plot 已 XLink 跟随 feature_plot；mfcc/hnr 一并同步。
        """
        self._xrange_blocked = True
        try:
            self.feature_plot.setXRange(lo, hi, padding=0)
            self.mfcc_plot.setXRange(lo, hi, padding=0)
            self.hnr_plot.setXRange(lo, hi, padding=0)
        finally:
            self._xrange_blocked = False

    def eventFilter(self, obj, event):
        """默认导航态手势出口：单击定位 / 双击播放 / Alt+拖 scrub（其余放行）。"""
        plot = self._nav_plot_of(obj)
        if plot is None:
            return super().eventFilter(obj, event)
        etype = event.type()
        if (etype in (event.Type.GraphicsSceneMousePress,
                      event.Type.GraphicsSceneMouseDoubleClick)
                and event.button() == Qt.MouseButton.LeftButton):
            if (etype == event.Type.GraphicsSceneMousePress
                    and event.modifiers() & Qt.KeyboardModifier.AltModifier):
                self._scrubbing = True
                self._nav_plot = plot
                self.timeScrubbed.emit(self._nav_time_at(event.scenePos(), plot))
                return True
            self._nav_plot = plot
            self._nav_press_view_t = self._nav_time_at(event.scenePos(), plot)

        elif etype == event.Type.GraphicsSceneMouseMove and self._scrubbing:
            if self._nav_plot is not None:
                self.timeScrubbed.emit(
                    self._nav_time_at(event.scenePos(), self._nav_plot)
                )
            return True

        elif (etype == event.Type.GraphicsSceneMouseRelease
                and event.button() == Qt.MouseButton.LeftButton):
            if self._scrubbing:
                self._scrubbing = False
                if self._nav_plot is not None:
                    self.timeScrubbed.emit(
                        self._nav_time_at(event.scenePos(), self._nav_plot)
                    )
                self._nav_plot = None
                return True
            if self._nav_press_view_t is not None and self._nav_plot is not None:
                press_t = self._nav_press_view_t
                cur_plot = self._nav_plot
                t = self._nav_time_at(event.scenePos(), cur_plot)
                self._nav_press_view_t = None
                self._nav_plot = None
                lo, hi = cur_plot.viewRange()[0]
                if abs(t - press_t) <= (hi - lo) * 0.004:
                    self._emit_nav_click(t, cur_plot)
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _build_mfcc_tab(self):
        """MFCC 热图页签。"""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.mfcc_plot = pg.PlotWidget()
        self.mfcc_plot.showGrid(x=True, y=True, alpha=0.15)
        self.mfcc_plot.setLabel("bottom", "时间", units="s")
        apply_time_axis(self.mfcc_plot)
        self.mfcc_plot.setLabel("left", "MFCC 系数阶数")
        self.mfcc_plot.getPlotItem().setMenuEnabled(False)
        _apply_canvas_theme(self.mfcc_plot)
        layout.addWidget(self.mfcc_plot, stretch=1)

        # 色条
        self.mfcc_colorbar = pg.PlotWidget()
        self.mfcc_colorbar.setMaximumWidth(30)
        self.mfcc_colorbar.hideAxis("bottom")
        self.mfcc_colorbar.getAxis("left").setWidth(30)
        self.mfcc_colorbar.getAxis("left").setStyle(tickTextOffset=5)
        _apply_canvas_theme(self.mfcc_colorbar, "bg2")
        layout.addWidget(self.mfcc_colorbar, stretch=0)

        self.mfcc_img = pg.ImageItem()
        self.mfcc_plot.addItem(self.mfcc_img)

        self.mfcc_bar_img = pg.ImageItem()
        self.mfcc_colorbar.addItem(self.mfcc_bar_img)

        self.tabs.addTab(container, "MFCC 热图")

    def _build_hnr_tab(self):
        """HNR 曲线页签。"""
        self.hnr_plot = pg.PlotWidget()
        self.hnr_plot.showGrid(x=True, y=True, alpha=0.2)
        self.hnr_plot.setLabel("bottom", "时间", units="s")
        apply_time_axis(self.hnr_plot)
        self.hnr_plot.setLabel("left", "HNR", units="dB")
        self.hnr_plot.getPlotItem().setMenuEnabled(False)
        _apply_canvas_theme(self.hnr_plot)
        self.hnr_curve = self.hnr_plot.plot(
            pen=pg.mkPen(color=theme.data_ink("trace"), width=2.7)
        )
        self.tabs.addTab(self.hnr_plot, "谐波噪声比 (HNR)")

    def _build_features_tab(self):
        """频谱特征曲线页签（上：频率量纲；下：平坦度/通量，X 轴联动）。"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 上：频率量纲特征（Hz）
        self.feature_plot = pg.PlotWidget()
        self.feature_plot.showGrid(x=True, y=True, alpha=0.2)
        self.feature_plot.setLabel("bottom", "时间", units="s")
        apply_time_axis(self.feature_plot)
        self.feature_plot.setLabel("left", "频率", units="Hz")
        self.feature_plot.getPlotItem().setMenuEnabled(False)
        _apply_canvas_theme(self.feature_plot)
        self.feature_plot.addLegend(offset=(10, 10))

        self.centroid_curve = self.feature_plot.plot(
            pen=pg.mkPen(color=feature_colors()["centroid"], width=2.7), name="质心"
        )
        self.bandwidth_curve = self.feature_plot.plot(
            pen=pg.mkPen(color=feature_colors()["bandwidth"], width=2.7), name="带宽"
        )
        self.rolloff_curve = self.feature_plot.plot(
            pen=pg.mkPen(color=feature_colors()["rolloff"], width=2.7), name="滚降 85%"
        )
        layout.addWidget(self.feature_plot, stretch=3)

        # 下：无量纲特征（平坦度 0–1 / 通量归一化）
        self.dim_plot = pg.PlotWidget()
        self.dim_plot.showGrid(x=True, y=True, alpha=0.2)
        self.dim_plot.setLabel("bottom", "时间", units="s")
        apply_time_axis(self.dim_plot)
        self.dim_plot.setLabel("left", "平坦度 / 通量（归一化）")
        self.dim_plot.getPlotItem().setMenuEnabled(False)
        _apply_canvas_theme(self.dim_plot)
        self.dim_plot.addLegend(offset=(10, 10))
        self.dim_plot.setYRange(0, 1.05, padding=0)

        self.flatness_curve = self.dim_plot.plot(
            pen=pg.mkPen(color=feature_colors()["flatness"], width=2.7), name="平坦度"
        )
        self.flux_curve = self.dim_plot.plot(
            pen=pg.mkPen(color=feature_colors()["flux"], width=2.7), name="通量"
        )
        layout.addWidget(self.dim_plot, stretch=2)

        self.dim_plot.setXLink(self.feature_plot)

        self.tabs.addTab(container, "频谱特征")

    def _build_global_tab(self):
        """全局特征表页签。"""
        self.global_table = QTableWidget(0, 2)
        self.global_table.setHorizontalHeaderLabels(["特征", "数值"])
        self.global_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.global_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.global_table.verticalHeader().setVisible(False)
        self.global_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabs.addTab(self.global_table, "全局特征")

    # ------------------------------------------------------------------
    # 数据设置
    # ------------------------------------------------------------------

    def set_data(
        self,
        times: np.ndarray,
        mfcc: np.ndarray,
        hnr_times: np.ndarray,
        hnr: np.ndarray,
        features: dict,
        global_features: dict,
    ):
        """设置音色分析数据。

        Args:
            times: MFCC 时间轴 [n_frames]
            mfcc: MFCC 矩阵 [n_frames, n_mfcc]
            hnr_times: HNR 时间轴
            hnr: HNR dB 值
            features: spectral_features() 返回的字典
            global_features: global_features() 返回的字典
        """
        self._times = times
        self._mfcc = mfcc
        self._hnr_times = hnr_times
        self._hnr = hnr
        self._features = features
        self._global_features = global_features

        self._update_mfcc()
        self._update_hnr()
        self._update_features()
        self._update_global_table(global_features)

        self.lbl_info.setText(
            f"{mfcc.shape[1]} 阶 MFCC · {len(times)} 帧 · "
            f"HNR 均值 {np.mean(hnr) if len(hnr) else 0:.1f} dB"
        )

    def _update_mfcc(self):
        """更新 MFCC 热图。"""
        if self._mfcc.size == 0 or len(self._times) == 0:
            self.mfcc_img.clear()
            return

        data = self._mfcc.T  # [n_mfcc, n_frames]
        t_lo = float(self._times[0])
        t_hi = float(self._times[-1])
        n_coef = data.shape[0]

        self.mfcc_img.setImage(data, autoLevels=False)
        self.mfcc_img.setRect(t_lo, 0, max(t_hi - t_lo, 1e-6), n_coef)
        self.mfcc_plot.setYRange(0, n_coef, padding=0.02)

        # 色阶：按 2%~98% 分位避免离群值压缩对比度
        lo, hi = np.percentile(data, [2, 98])
        if hi <= lo:
            hi = lo + 1.0
        self.mfcc_img.setLevels((float(lo), float(hi)))

        # 色条（垂直渐变）
        bar = np.linspace(hi, lo, 256).reshape(-1, 1)
        self.mfcc_bar_img.setImage(bar)
        self.mfcc_bar_img.setLevels((lo, hi))
        self.mfcc_bar_img.setRect(0, lo, 1, hi - lo)
        self.mfcc_colorbar.setYRange(lo, hi, padding=0)

        try:
            cmap = pg.colormap.get("viridis")
        except Exception:
            cmap = pg.colormap.getFromMatplotlib("viridis")
        lut = cmap.getLookupTable(0.0, 1.0, 256)
        self.mfcc_img.setLookupTable(lut)
        self.mfcc_bar_img.setLookupTable(lut)

    def _update_hnr(self):
        """更新 HNR 曲线。"""
        if len(self._hnr_times) == 0:
            self.hnr_curve.setData([], [])
            return
        self.hnr_curve.setData(self._hnr_times, self._hnr)
        if len(self._hnr) > 0:
            margin = max(abs(np.max(self._hnr)), abs(np.min(self._hnr)), 1.0) * 0.1
            self.hnr_plot.setYRange(
                float(np.min(self._hnr) - margin),
                float(np.max(self._hnr) + margin),
                padding=0,
            )

    def _update_features(self):
        """更新频谱特征曲线。"""
        times = self._features.get("times", np.array([]))
        if len(times) == 0:
            for curve in (self.centroid_curve, self.bandwidth_curve,
                          self.rolloff_curve, self.flatness_curve, self.flux_curve):
                curve.setData([], [])
            return

        self.centroid_curve.setData(times, self._features.get("spectral_centroid", []))
        self.bandwidth_curve.setData(times, self._features.get("spectral_bandwidth", []))
        self.rolloff_curve.setData(times, self._features.get("spectral_rolloff", []))

        all_vals = np.concatenate([
            np.atleast_1d(self._features.get(k, np.array([])))
            for k in ("spectral_centroid", "spectral_bandwidth", "spectral_rolloff")
            if len(np.atleast_1d(self._features.get(k, np.array([])))) > 0
        ])
        if len(all_vals) > 0:
            self.feature_plot.setYRange(0, float(np.max(all_vals)) * 1.05, padding=0)

        # 平坦度（0–1）与通量（按峰值归一化到 0–1）
        flatness = np.atleast_1d(self._features.get("spectral_flatness", np.array([])))
        flux = np.atleast_1d(self._features.get("spectral_flux", np.array([])))
        if len(flux) > 0:
            fmax = float(np.max(flux))
            flux = flux / fmax if fmax > 0 else np.zeros_like(flux)
        else:
            flux = np.array([])
        self.flatness_curve.setData(times, flatness)
        self.flux_curve.setData(times, flux)

    def _update_global_table(self, global_features: dict):
        """更新全局特征表。"""
        self.global_table.setRowCount(0)
        for key, (label, fmt) in GLOBAL_FEATURE_LABELS.items():
            if key not in global_features:
                continue
            value = global_features[key]
            text = "—" if value is None else fmt.format(value)
            row = self.global_table.rowCount()
            self.global_table.insertRow(row)
            self.global_table.setItem(row, 0, QTableWidgetItem(label))
            self.global_table.setItem(row, 1, QTableWidgetItem(text))

    # ------------------------------------------------------------------
    # CSV 导出
    # ------------------------------------------------------------------

    def _on_export_csv(self):
        """导出音色特征数据为 CSV 文件。"""
        if not self._times.size:
            show_toast(self, "暂无数据可导出。", level="info")
            return

        default_name = "timbre_features.csv"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出音色特征为 CSV",
            default_name,
            "CSV 文件 (*.csv)",
        )
        if not path:
            return

        try:
            self._export_csv(path)
            show_toast(
                self, f"导出成功，数据已导出到：{os.path.basename(path)}",
                level="success",
            )
        except Exception as e:
            show_toast(self, f"导出失败，导出 CSV 时出错：{e}", level="error")

    def _export_csv(self, path: str):
        """将所有音色特征数据写入 CSV 文件。

        文件包含三部分：
        1. 逐帧特征（MFCC + 频谱特征 + HNR）— 以时间对齐
        2. 全局特征（标量）— 以键值对形式追加在末尾
        """

        times = self._times
        n_frames = len(times)

        # ---- 收集逐帧特征列 ----
        columns = [("time_s", times)]

        # MFCC 系数
        if self._mfcc.size and self._mfcc.shape[0] == n_frames:
            n_mfcc = self._mfcc.shape[1]
            for i in range(n_mfcc):
                columns.append((f"mfcc_{i}", self._mfcc[:, i]))

        # 频谱特征
        for key, arr in self._features.items():
            arr = np.asarray(arr)
            if arr.ndim == 1 and len(arr) == n_frames:
                columns.append((f"spectral_{key}", arr))

        # HNR（可能帧数不同，单独插值对齐）
        if len(self._hnr_times) > 1:
            hnr_interp = np.interp(times, self._hnr_times, self._hnr)
            columns.append(("hnr_db", hnr_interp))

        # ---- 写入逐帧数据 ----
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)

            # 表头
            headers = [col[0] for col in columns]
            writer.writerow(headers)

            # 数据行
            for i in range(n_frames):
                row = [f"{col[1][i]:.6f}" for col in columns]
                writer.writerow(row)

            # ---- 全局特征（追加在末尾，带分隔行）----
            writer.writerow([])
            writer.writerow(["=== Global Features ==="])
            writer.writerow(["feature_key", "feature_name", "value"])
            for key, (label, _fmt) in GLOBAL_FEATURE_LABELS.items():
                val = self._global_features.get(key)
                if val is not None:
                    writer.writerow([key, label, f"{val:.6f}"])
