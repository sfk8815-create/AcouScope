# SPDX-License-Identifier: GPL-3.0-only
"""房间声学工具对话框。

集成：
- Sabine 混响时间计算器
- Farina 指数扫频冲激响应测量
- RT60 分析
"""

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QDoubleSpinBox, QSpinBox, QComboBox, QPushButton,
    QGroupBox, QFormLayout, QGridLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog,
)

from acouscope.analysis.room_acoustics import (
    sabine_rt60,
    calculate_total_absorption,
    MATERIAL_DATABASE,
    OCTAVE_BANDS,
    generate_exponential_sweep,
    generate_inverse_filter,
    compute_impulse_response,
    extract_ir_peak,
    rt60_from_ir,
)
from acouscope.i18n import tr
from acouscope.ui import theme
from acouscope.ui.widgets.toast import show_toast


def _primary_btn_qss(pad_key: str) -> str:
    """主按钮 QSS：交互色 = 主题单强调色（T-1038 M3/M4，令牌插值）。

    `pad_key` 可取自 `TOKENS["spacing"]` 或 `TOKENS["control"]`（内边距档位）。
    """
    c = theme.colors()
    toks = theme.TOKENS
    pad = toks["spacing"][pad_key] if pad_key in toks["spacing"] else toks["control"][pad_key]
    return (
        f"QPushButton{{background:{c['accent']};color:{c['accent_text']};"
        f"padding:{pad}px;font-weight:bold;}}"
        f"QPushButton:hover{{background:{c['bg3']};}}"
    )


def _panel_qss(pad: str, font_key: str) -> str:
    """信息块 QSS：中性阶令牌（T-1038 M4：主题互斥硬编码底块消除）。"""
    c = theme.colors()
    tp = theme.TOKENS["typography"]
    el = theme.TOKENS["elevation"]["border"]
    return (
        f"padding:{pad};background:{c['bg2']};"
        f"border:{el}px solid {c['border']};"
        f"border-radius:{theme.TOKENS['radius']['sm']}px;"
        f"color:{c['text']};font-size:{tp[font_key]}px;"
    )


def _note_qss(role: str, pad: str, font_key: str) -> str:
    """提示块 QSS：语义色低 alpha 派生（T-1038 M4，复用既有派生范式）。"""
    c = theme.colors()
    tone = pg.mkColor(theme.TOKENS["semantic"][role])
    fill, line = pg.mkColor(tone), pg.mkColor(tone)
    fill.setAlpha(28)
    line.setAlpha(120)
    el = theme.TOKENS["elevation"]["border"]
    return (
        f"padding:{pad};"
        f"background:rgba({fill.red()},{fill.green()},{fill.blue()},{fill.alpha()});"
        f"border:{el}px solid rgba({line.red()},{line.green()},{line.blue()},{line.alpha()});"
        f"border-radius:{theme.TOKENS['radius']['sm']}px;"
        f"color:{c['text']};font-size:{theme.TOKENS['typography'][font_key]}px;"
    )


def _tint(role: str, alpha: int = 48):
    """语义反馈色低透明度派生（表格单元格底；T-1038 M4）。"""
    col = pg.mkColor(theme.TOKENS["semantic"][role])
    col.setAlpha(alpha)
    return col


class RoomAcousticsDialog(QWidget):
    """房间声学工具面板（嵌入右抽屉的非模态工具，T-504d 去模态化）。"""

    cancelled = pyqtSignal()   # 关闭按钮触发（抽屉流：关抽屉）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("room_acoustics.title"))
        self.setMinimumSize(0, 480)   # 宽度交抽屉决定，仅保留高度下限

        self._recorded_data = None
        self._recorded_sr = None
        self._ir_data = None
        self._ir_sr = None
        self._sweep_data = None
        self._sweep_sr = None

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        tabs = QTabWidget()

        # ===== Sabine 计算器 =====
        sabine_tab = QWidget()
        self._build_sabine_tab(sabine_tab)
        tabs.addTab(sabine_tab, "Sabine 混响计算器")

        # ===== 冲激响应测量 =====
        ir_tab = QWidget()
        self._build_ir_tab(ir_tab)
        tabs.addTab(ir_tab, "冲激响应测量")

        # ===== RT60 分析 =====
        rt60_tab = QWidget()
        self._build_rt60_tab(rt60_tab)
        tabs.addTab(rt60_tab, "RT60 分析")

        root.addWidget(tabs, stretch=1)

        # 关闭按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.cancelled)
        btn_row.addWidget(self.btn_close)
        root.addLayout(btn_row)

    # ==================================================================
    # Sabine 计算器
    # ==================================================================

    def _build_sabine_tab(self, parent: QWidget):
        layout = QHBoxLayout(parent)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # 左侧：房间参数
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        # 房间尺寸
        size_box = QGroupBox("房间尺寸")
        size_form = QFormLayout(size_box)
        size_form.setSpacing(6)

        self.spin_sab_lx = QDoubleSpinBox()
        self.spin_sab_lx.setRange(1, 100)
        self.spin_sab_lx.setValue(6.0)
        self.spin_sab_lx.setSuffix(" m")
        size_form.addRow("长度 Lx：", self.spin_sab_lx)

        self.spin_sab_ly = QDoubleSpinBox()
        self.spin_sab_ly.setRange(1, 100)
        self.spin_sab_ly.setValue(4.5)
        self.spin_sab_ly.setSuffix(" m")
        size_form.addRow("宽度 Ly：", self.spin_sab_ly)

        self.spin_sab_lz = QDoubleSpinBox()
        self.spin_sab_lz.setRange(1, 50)
        self.spin_sab_lz.setValue(2.8)
        self.spin_sab_lz.setSuffix(" m")
        size_form.addRow("高度 Lz：", self.spin_sab_lz)

        left_layout.addWidget(size_box)

        # 表面材料
        surf_box = QGroupBox("六个表面材料")
        surf_form = QGridLayout(surf_box)
        surf_form.setSpacing(6)

        surfaces = [
            ("天花板 (Lx×Ly)", "lx_ly", "gypsum_board"),
            ("地板 (Lx×Ly)", "floor", "concrete"),
            ("前墙 (Lx×Lz)", "front", "brick"),
            ("后墙 (Lx×Lz)", "back", "brick"),
            ("左墙 (Ly×Lz)", "left", "brick"),
            ("右墙 (Ly×Lz)", "right", "glass"),
        ]

        self._surface_combos = {}
        for i, (name, key, default_mat) in enumerate(surfaces):
            surf_form.addWidget(QLabel(name), i, 0)
            cmb = QComboBox()
            for mat_key, mat in MATERIAL_DATABASE.items():
                cmb.addItem(mat.name, mat_key)
            # 设置默认
            idx = cmb.findData(default_mat)
            if idx >= 0:
                cmb.setCurrentIndex(idx)
            surf_form.addWidget(cmb, i, 1)
            self._surface_combos[key] = cmb

        left_layout.addWidget(surf_box)

        # 人数
        people_box = QGroupBox("其他吸声")
        people_form = QFormLayout(people_box)
        people_form.setSpacing(6)

        self.spin_people = QSpinBox()
        self.spin_people.setRange(0, 100)
        self.spin_people.setValue(2)
        people_form.addRow("人数：", self.spin_people)

        self.spin_speed_sab = QDoubleSpinBox()
        self.spin_speed_sab.setRange(300, 400)
        self.spin_speed_sab.setValue(343)
        self.spin_speed_sab.setSuffix(" m/s")
        people_form.addRow("声速：", self.spin_speed_sab)

        left_layout.addWidget(people_box)

        # 计算按钮
        self.btn_calc_sabine = QPushButton("计算 RT60")
        self.btn_calc_sabine.setStyleSheet(_primary_btn_qss("sm"))
        self.btn_calc_sabine.clicked.connect(self._on_calc_sabine)
        left_layout.addWidget(self.btn_calc_sabine)

        left_layout.addStretch()
        layout.addWidget(left, stretch=0)

        # 右侧：结果
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        # 结果表格
        result_box = QGroupBox("各倍频程 RT60")
        result_layout = QVBoxLayout(result_box)

        self.table_sabine = QTableWidget()
        self.table_sabine.setRowCount(2)
        self.table_sabine.setColumnCount(len(OCTAVE_BANDS))
        self.table_sabine.setHorizontalHeaderLabels([f"{f} Hz" for f in OCTAVE_BANDS])
        self.table_sabine.setVerticalHeaderLabels(["总吸声量 (sabins)", "RT60 (s)"])
        self.table_sabine.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table_sabine.verticalHeader().setFixedWidth(140)
        self.table_sabine.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        result_layout.addWidget(self.table_sabine)

        right_layout.addWidget(result_box)

        # 建议
        self.lbl_sabine_advice = QLabel("")
        self.lbl_sabine_advice.setStyleSheet(
            _note_qss("warning",
                      f"{theme.TOKENS['control']['pad_x']}px", "body_sm")
        )
        self.lbl_sabine_advice.setWordWrap(True)
        right_layout.addWidget(self.lbl_sabine_advice)

        # 体积等信息
        self.lbl_sabine_info = QLabel("")
        self.lbl_sabine_info.setStyleSheet(
            _panel_qss(f"{theme.TOKENS['spacing']['sm']}px", "body_sm")
        )
        self.lbl_sabine_info.setWordWrap(True)
        right_layout.addWidget(self.lbl_sabine_info)

        right_layout.addStretch()
        layout.addWidget(right, stretch=1)

        # 初始计算
        self._on_calc_sabine()

    def _on_calc_sabine(self):
        """计算 Sabine RT60。"""
        lx = self.spin_sab_lx.value()
        ly = self.spin_sab_ly.value()
        lz = self.spin_sab_lz.value()
        speed = self.spin_speed_sab.value()
        people = self.spin_people.value()

        volume = lx * ly * lz

        # 各面面积和材料
        surfaces = [
            (lx * ly, self._surface_combos["lx_ly"].currentData()),    # 天花板
            (lx * ly, self._surface_combos["floor"].currentData()),     # 地板
            (lx * lz, self._surface_combos["front"].currentData()),     # 前墙
            (lx * lz, self._surface_combos["back"].currentData()),      # 后墙
            (ly * lz, self._surface_combos["left"].currentData()),      # 左墙
            (ly * lz, self._surface_combos["right"].currentData()),     # 右墙
        ]

        total_absorption = calculate_total_absorption(surfaces, num_people=people)
        rt60 = sabine_rt60(volume, total_absorption, speed_of_sound=speed)

        # 填充表格
        for i, freq in enumerate(OCTAVE_BANDS):
            abs_item = QTableWidgetItem(f"{total_absorption[freq]:.2f}")
            abs_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_sabine.setItem(0, i, abs_item)

            rt = rt60[freq]
            rt_item = QTableWidgetItem(f"{rt:.2f}" if rt < 10 else "∞")
            rt_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            # 颜色编码（评级 → 语义反馈色低 alpha 派生，随主题骨架）
            if rt < 0.3:
                rt_item.setBackground(_tint("error"))
            elif rt < 0.8:
                rt_item.setBackground(_tint("success"))
            elif rt < 1.5:
                rt_item.setBackground(_tint("warning"))
            else:
                rt_item.setBackground(_tint("error"))
            self.table_sabine.setItem(1, i, rt_item)

        # 信息
        total_surface_area = 2 * (lx * ly + lx * lz + ly * lz)
        info = (
            f"房间体积：{volume:.1f} m³\n"
            f"总表面积：{total_surface_area:.1f} m²\n"
            f"平均吸声系数："
            f"{sum(total_absorption.values()) / len(total_absorption) / total_surface_area:.3f}"
        )
        self.lbl_sabine_info.setText(info)

        # 建议
        mid_rt60 = (rt60[500] + rt60[1000]) / 2
        if volume < 50:
            target = "0.3~0.5"
            use = "小型听音室/录音棚"
        elif volume < 200:
            target = "0.5~0.8"
            use = "中型房间/家庭影院"
        else:
            target = "1.0~2.0"
            use = "大型空间/音乐厅"

        if mid_rt60 < 0.3:
            advice = f"房间偏干（中频 RT60 ≈ {mid_rt60:.2f}s）。\n建议：增加木质表面、扩散体，减少吸声。"
        elif mid_rt60 > 2.0:
            advice = f"房间混响偏重（中频 RT60 ≈ {mid_rt60:.2f}s）。\n建议：增加吸声材料（声学泡沫、地毯、窗帘等）。"
        else:
            advice = f"中频 RT60 ≈ {mid_rt60:.2f}s，处于较合理范围。\n{use}的推荐范围：{target} s。"

        self.lbl_sabine_advice.setText(advice)

    # ==================================================================
    # 冲激响应测量
    # ==================================================================

    def _build_ir_tab(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 扫频参数
        param_box = QGroupBox("扫频信号参数")
        param_form = QFormLayout(param_box)
        param_form.setSpacing(6)

        self.spin_ir_fstart = QDoubleSpinBox()
        self.spin_ir_fstart.setRange(1, 200)
        self.spin_ir_fstart.setValue(20)
        self.spin_ir_fstart.setSuffix(" Hz")
        param_form.addRow("起始频率：", self.spin_ir_fstart)

        self.spin_ir_fend = QDoubleSpinBox()
        self.spin_ir_fend.setRange(1000, 40000)
        self.spin_ir_fend.setValue(20000)
        self.spin_ir_fend.setSuffix(" Hz")
        param_form.addRow("结束频率：", self.spin_ir_fend)

        self.spin_ir_duration = QDoubleSpinBox()
        self.spin_ir_duration.setRange(0.5, 60)
        self.spin_ir_duration.setValue(10)
        self.spin_ir_duration.setSuffix(" s")
        param_form.addRow("扫频时长：", self.spin_ir_duration)

        self.spin_ir_sr = QSpinBox()
        self.spin_ir_sr.setRange(8000, 192000)
        self.spin_ir_sr.setValue(48000)
        self.spin_ir_sr.setSuffix(" Hz")
        param_form.addRow("采样率：", self.spin_ir_sr)

        layout.addWidget(param_box)

        # 操作按钮
        btn_row = QHBoxLayout()

        self.btn_gen_sweep = QPushButton("生成扫频信号并保存")
        self.btn_gen_sweep.clicked.connect(self._on_generate_sweep)
        btn_row.addWidget(self.btn_gen_sweep)

        self.btn_load_recording = QPushButton("加载录制的扫频响应")
        self.btn_load_recording.clicked.connect(self._on_load_recording)
        btn_row.addWidget(self.btn_load_recording)

        self.btn_compute_ir = QPushButton("计算冲激响应")
        self.btn_compute_ir.setStyleSheet(_primary_btn_qss("gap"))
        self.btn_compute_ir.clicked.connect(self._on_compute_ir)
        btn_row.addWidget(self.btn_compute_ir)

        layout.addLayout(btn_row)

        # 状态信息
        self.lbl_ir_status = QLabel(tr("room_acoustics.sweep_hint"))
        self.lbl_ir_status.setStyleSheet(
            _panel_qss(f"{theme.TOKENS['spacing']['sm']}px", "body_sm")
        )
        self.lbl_ir_status.setWordWrap(True)
        layout.addWidget(self.lbl_ir_status)

        layout.addStretch()

    def _on_generate_sweep(self):
        """生成扫频信号并保存为 WAV。"""
        f_start = self.spin_ir_fstart.value()
        f_end = self.spin_ir_fend.value()
        duration = self.spin_ir_duration.value()
        sr = self.spin_ir_sr.value()

        sweep, _ = generate_exponential_sweep(
            f_start=f_start, f_end=f_end,
            duration=duration, sample_rate=sr,
        )

        # 保存为 WAV
        filepath, _ = QFileDialog.getSaveFileName(
            self, "保存扫频信号", "exponential_sweep.wav", "WAV 音频 (*.wav)"
        )
        if not filepath:
            return

        if not filepath.lower().endswith(".wav"):
            filepath += ".wav"

        try:
            import wave
            pcm = np.clip(sweep * 0.9, -1.0, 1.0)
            pcm = (pcm * 32767.0).astype(np.int16)
            with wave.open(filepath, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes(pcm.tobytes())

            self._sweep_data = sweep
            self._sweep_sr = sr
            self.lbl_ir_status.setText(
                tr("room_acoustics.status.sweep_saved").format(filepath=filepath)
            )
        except Exception as e:
            show_toast(self, f"保存扫频信号失败：{e}", level="error")

    def _on_load_recording(self):
        """加载录制的扫频响应。"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "选择录制的扫频响应文件", "", "音频文件 (*.wav *.flac *.ogg)"
        )
        if not filepath:
            return

        try:
            from acouscope.audio.io import AudioIO
            data, sr = AudioIO.load(filepath)
            # 取单声道
            if data.ndim > 1:
                data = data[:, 0]
            self._recorded_data = data
            self._recorded_sr = sr
            self.lbl_ir_status.setText(
                tr("room_acoustics.status.rec_loaded").format(
                    path=filepath,
                    duration=f"{len(data) / sr:.2f}",
                    sample_rate=sr,
                )
            )
        except Exception as e:
            show_toast(self, f"加载音频失败：{e}", level="error")

    def _on_compute_ir(self):
        """计算冲激响应。"""
        if self._recorded_data is None:
            show_toast(self, "请先加载录制的扫频响应文件。", level="warning")
            return

        f_start = self.spin_ir_fstart.value()
        f_end = self.spin_ir_fend.value()
        duration = self.spin_ir_duration.value()
        sr = self.spin_ir_sr.value()

        # 确保采样率匹配
        if self._recorded_sr != sr:
            show_toast(
                self,
                f"录制文件采样率 ({self._recorded_sr} Hz) 与设置 ({sr} Hz) "
                "不匹配，请调整设置后重试。",
                level="warning",
            )
            return

        # 生成逆滤波器
        if self._sweep_data is None or self._sweep_sr != sr:
            sweep, _ = generate_exponential_sweep(
                f_start=f_start, f_end=f_end,
                duration=duration, sample_rate=sr,
            )
            self._sweep_data = sweep
            self._sweep_sr = sr

        inverse_filter = generate_inverse_filter(
            self._sweep_data, f_start=f_start, f_end=f_end, sample_rate=sr
        )

        # 计算 IR
        ir = compute_impulse_response(self._recorded_data, inverse_filter)

        # 提取峰值部分
        ir_peak, peak_idx = extract_ir_peak(ir, pre_peak=0.01, post_peak=2.0, sample_rate=sr)
        self._ir_data = ir_peak
        self._ir_sr = sr

        self.lbl_ir_status.setText(
            tr("room_acoustics.status.ir_done").format(
                length=f"{len(ir_peak) / sr:.3f}",
                peak=f"{peak_idx / sr * 1000:.1f}",
            )
        )

    # ==================================================================
    # RT60 分析
    # ==================================================================

    def _build_rt60_tab(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 控制
        ctrl_row = QHBoxLayout()

        self.btn_load_ir = QPushButton("加载冲激响应音频")
        self.btn_load_ir.clicked.connect(self._on_load_ir_audio)
        ctrl_row.addWidget(self.btn_load_ir)

        ctrl_row.addWidget(QLabel(tr("room_acoustics.method_label")))
        self.cmb_rt60_method = QComboBox()
        self.cmb_rt60_method.addItem("T30 (-5 ~ -35 dB)", "T30")
        self.cmb_rt60_method.addItem("T20 (-5 ~ -25 dB)", "T20")
        self.cmb_rt60_method.addItem("EDT (0 ~ -10 dB)", "EDT")
        self.cmb_rt60_method.setCurrentIndex(0)
        ctrl_row.addWidget(self.cmb_rt60_method)

        self.btn_calc_rt60 = QPushButton("计算 RT60")
        self.btn_calc_rt60.setStyleSheet(_primary_btn_qss("gap"))
        self.btn_calc_rt60.clicked.connect(self._on_calc_rt60)
        ctrl_row.addWidget(self.btn_calc_rt60)

        ctrl_row.addStretch()
        layout.addLayout(ctrl_row)

        # 结果显示
        self.lbl_rt60_result = QLabel(tr("room_acoustics.rt60_hint"))
        self.lbl_rt60_result.setStyleSheet(
            _note_qss("success",
                      f"{theme.TOKENS['spacing']['sm'] + theme.TOKENS['spacing']['xs']}px",
                      "body_lg")
        )
        self.lbl_rt60_result.setWordWrap(True)
        layout.addWidget(self.lbl_rt60_result)

        layout.addStretch()

    def _on_load_ir_audio(self):
        """加载冲激响应音频文件。"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "选择冲激响应文件", "", "音频文件 (*.wav *.flac *.ogg)"
        )
        if not filepath:
            return

        try:
            from acouscope.audio.io import AudioIO
            data, sr = AudioIO.load(filepath)
            if data.ndim > 1:
                data = data[:, 0]
            self._ir_data = data
            self._ir_sr = sr
            self.lbl_rt60_result.setText(
                tr("room_acoustics.status.ir_loaded").format(
                    length=f"{len(data) / sr:.3f}", sample_rate=sr
                )
            )
        except Exception as e:
            show_toast(self, f"加载音频失败：{e}", level="error")

    def _on_calc_rt60(self):
        """计算 RT60。"""
        if self._ir_data is None:
            show_toast(self, "请先加载或计算冲激响应。", level="warning")
            return

        method = self.cmb_rt60_method.currentData()
        result, t, schroeder_db = rt60_from_ir(
            self._ir_data, sample_rate=self._ir_sr, method=method
        )

        if result["valid"]:
            self.lbl_rt60_result.setText(
                tr("room_acoustics.status.rt60_result").format(
                    method=method,
                    rt60=f"{result['rt60']:.3f}",
                    slope=f"{result['slope']:.1f}",
                    db_start=result["db_start"],
                    db_end=result["db_end"],
                )
            )
        else:
            self.lbl_rt60_result.setText(
                tr("room_acoustics.status.rt60_failed").format(method=method)
            )
