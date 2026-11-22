# SPDX-License-Identifier: GPL-3.0-only
"""文件源数据常驻信息条：横向紧凑布局，置于分析面板顶部。

将原先占据整个分析面板的元数据视图压缩为单行信息条，
所有分析视图共享，不再随视图切换消失。

PI-G4a-1（D3/D7）：
- 尺寸：三段标签一律 `QSizePolicy.Ignored` + `minimumWidth(0)`，全文另存 `_full_*`，
  按可用宽度 `ElideMiddle` 省略（文件名保留扩展名），不再把 `minimumSizeHint` 顶宽；
- 主题：色值全部取 `theme.colors()` 令牌，并显式开启 `WA_StyledBackground` 让 QSS 底色真绘。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from acouscope.i18n import tr
from acouscope.ui import theme


def _fmt_size(nbytes: int) -> str:
    if nbytes >= 1024**3:
        return f"{nbytes / 1024**3:.2f} GB"
    if nbytes >= 1024**2:
        return f"{nbytes / 1024**2:.2f} MB"
    if nbytes >= 1024:
        return f"{nbytes / 1024:.1f} KB"
    return f"{nbytes} B"


def _build_qss(c: dict[str, str], empty: bool = False) -> str:
    """信息条 QSS：色/圆角/描边/字号一律取主题令牌（本文件零常量色）。

    empty=True（未载入音频，G8）：只输出零观感规则——不画底、不画描边，
    避免「分析」标题下留一个全宽空圆角容器；条本体仍占位（保持分析区版面
    高度恒定，行高恒定性由既有布局守卫钉住）。
    """
    bd = theme.TOKENS["elevation"]["border"]
    rad = theme.TOKENS["radius"]["sm"]
    tp = theme.TOKENS["typography"]
    if empty:
        return "MetadataBar { background: transparent; border: none; }"
    return (
        f"MetadataBar {{ background: {c['bg2']};"
        f" border: {bd}px solid {c['border']}; border-radius: {rad}px; }}"
        f"MetadataBar QLabel {{ color: {c['text_sub']}; background: transparent;"
        f" font-size: {tp['caption']}px; }}"
        f"MetadataBar QLabel#metaFilename {{ color: {c['text']};"
        f" font-size: {tp['body']}px; font-weight: bold; }}"
        f"MetadataBar QFrame[frameShape='6'] {{ color: {c['border']}; }}"
    )


class MetadataBar(QWidget):
    """单行文件信息条：文件名 | 音频参数 | 信号特征。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(46)
        # 自定义 QWidget 子类默认不绘 QSS 背景（D7 根因）：显式开启样式表背景绘制。
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._full_filename = ""
        self._full_params = ""
        self._full_signal = ""
        # G8：未载入音频 → 「无容器观感」（透明、无描边、无文字）。条本体仍占
        # 版面高度：分析区页面的自然最小高由既有布局守卫按精确常量钉住，
        # 整条 hide() 会让该常量漂移 46+4（离屏实测 435 → 385）。
        self._has_data = False

        # 主题切换时重设样式（style_when_theme 建即生效，并登记动态刷新）
        self._refresh_style = theme.style_when_theme(
            self, lambda c: _build_qss(c, not self._has_data)
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(8)

        self.lbl_filename = QLabel(tr("metadata_bar.empty"))
        self.lbl_filename.setObjectName("metaFilename")
        self._fit_label(self.lbl_filename)
        self.lbl_filename.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.lbl_filename, stretch=1)

        self.lbl_params = QLabel("")
        self._fit_label(self.lbl_params)
        self.lbl_params.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.lbl_params, stretch=2)

        self.lbl_signal = QLabel("")
        self._fit_label(self.lbl_signal)
        layout.addWidget(self.lbl_signal, stretch=1)

        # G8 首帧：进入空态（无底/无描边/无文字），不画「全宽空圆角容器」

    # ------------------------------------------------------------------
    # 尺寸：不撑宽 + 按宽省略
    # ------------------------------------------------------------------

    @staticmethod
    def _fit_label(label: QLabel) -> None:
        """标签可缩到 0 宽：尺寸策略 Ignored（sizeHint 不参与最小宽）+ 最小宽 0。"""
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    @staticmethod
    def _elide(label: QLabel, full: str, keep_suffix: bool = False,
               avail: int | None = None) -> None:
        """把 full 按可用宽度省略后写入；keep_suffix 时保留扩展名。

        avail 缺省取标签当前宽度（既有调用口径不变）。
        """
        if not full:
            if label.text():
                label.setText("")
            return
        if avail is None:
            avail = label.width()
        if avail <= 0:
            return
        label.ensurePolished()
        fm = QFontMetrics(label.font())
        if fm.horizontalAdvance(full) <= avail:
            if label.text() != full:
                label.setText(full)
            return
        if keep_suffix:
            path = Path(full)
            suffix = path.suffix
            room = avail - fm.horizontalAdvance(suffix)
            if suffix and room > 0:
                text = fm.elidedText(
                    path.stem, Qt.TextElideMode.ElideMiddle, room
                ) + suffix
            else:
                # 后缀自身即超宽（或无名无后缀）：退回全名省略
                text = fm.elidedText(full, Qt.TextElideMode.ElideMiddle, avail)
        else:
            text = fm.elidedText(full, Qt.TextElideMode.ElideMiddle, avail)
        if text != label.text():
            label.setText(text)

    # 组内字段分隔符（参数组 = 格式 · 体积 · 采样率 · 声道 · 位深 · 时长）
    _FIELD_SEP = " · "
    _MARGIN_X = 10          # 与 layout().setContentsMargins 左/右一致
    _GAP = 8                # 与 layout().setSpacing 一致
    _NAME_MIN_W = 180       # 文件名保底宽（再窄才允许继续让位）
    _NAME_MIN_RATIO = 0.30  # 或条宽的三成，取更小者

    def _drop_fields(self, full: str, limit: int, fm: QFontMetrics) -> str:
        """按整字段从右往左取舍：宁可少一个字段，也不截半个字段。"""
        if not full or limit <= 0:
            return ""
        fields = full.split(self._FIELD_SEP)
        for count in range(len(fields), 0, -1):
            text = self._FIELD_SEP.join(fields[:count])
            if fm.horizontalAdvance(text) <= limit:
                return text
        return ""

    def _apply_elide(self) -> None:
        """按信息组整组取舍重算三段（全文保留在 _full_* 与 tooltip）。

        G7：原实现三段**逐段**省略，窄窗下会把组内单个标签截成 `R…S`
        （RMS）、1000pt 处甚至整段吞掉。现改为：
          ① 次要三元组（峰值 / RMS / 波峰因数）只在全文可容时显示，
             否则**整组隐藏**（禁组内单标签省略形态）；
          ② 参数组按 ` · ` 整字段取舍（从右往左丢整字段，绝不截半个字段）；
          ③ 上述两组让位后仍不够，才省略文件名（保留扩展名）。
        """
        avail = self.width() - self._MARGIN_X * 2 - self._GAP * 2
        if avail <= 0:
            return
        fm_params = QFontMetrics(self.lbl_params.font())
        fm_signal = QFontMetrics(self.lbl_signal.font())
        name_min = min(int(avail * self._NAME_MIN_RATIO), self._NAME_MIN_W)
        rest = max(0, avail - name_min)

        need_params = (
            fm_params.horizontalAdvance(self._full_params)
            if self._full_params else 0
        )
        need_signal = (
            fm_signal.horizontalAdvance(self._full_signal)
            if self._full_signal else 0
        )

        # ① 次要三元组先让位：只有「参数组全文 + 三元组全文」都放得下才显示，
        #    否则**整组隐藏**（禁组内单标签省略成 R…S 形态）
        show_signal = bool(self._full_signal) and need_params + need_signal <= rest
        self.lbl_signal.setText(self._full_signal if show_signal else "")
        self.lbl_signal.setVisible(show_signal)

        # ② 参数组：整字段取舍（三元组让位后仍放不下时才动，绝不截半个字段）
        params_text = self._drop_fields(
            self._full_params, rest if not show_signal else rest - need_signal,
            fm_params)
        params_w = fm_params.horizontalAdvance(params_text) if params_text else 0
        if self.lbl_params.text() != params_text:
            self.lbl_params.setText(params_text)
        self.lbl_params.setVisible(bool(params_text))

        # ③ 文件名最后让位（保留扩展名）
        name_avail = max(0, avail - (params_w if params_text else 0)
                         - (need_signal if show_signal else 0) - self._GAP)
        self._elide(self.lbl_filename, self._full_filename,
                    keep_suffix=True, avail=name_avail)

    def resizeEvent(self, event):  # noqa: N802（Qt 命名）
        super().resizeEvent(event)
        layout = self.layout()
        if layout is not None:
            layout.activate()
        self._apply_elide()

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------

    def set_info(self, info, data: np.ndarray | None, sample_rate: int) -> None:
        """填充文件信息与信号统计（G8：载入文件即恢复容器观感）。"""
        if info is None:
            return
        if not self._has_data:
            self._has_data = True
            self._refresh_style()   # 空态（透明无描边）→ 正常容器
        path = Path(info.filepath)
        self._full_filename = path.name
        self.lbl_filename.setText(self._full_filename)
        self.lbl_filename.setToolTip(str(path))

        channels_text = {1: "单声道", 2: "立体声"}.get(info.channels, f"{info.channels} 声道")
        self._full_params = (
            f"{info.format} · {_fmt_size(info.file_size)} · "
            f"{info.sample_rate:,} Hz · {channels_text} · "
            f"{info.bit_depth} bit · {info.duration_str}"
        )
        self.lbl_params.setText(self._full_params)
        self.lbl_params.setToolTip(self._full_params)

        if data is not None and len(data) > 0:
            x = np.asarray(data, dtype=np.float64)
            peak_db = 20 * np.log10(max(float(np.max(np.abs(x))), 1e-12))
            rms_db = 20 * np.log10(max(float(np.sqrt(np.mean(x**2))), 1e-12))
            self._full_signal = tr("metadata_bar.status.peak_rms").format(
                peak=f"{peak_db:.1f}",
                rms=f"{rms_db:.1f}",
                crest=f"{peak_db - rms_db:.1f}",
            )
        else:
            self._full_signal = ""
        self.lbl_signal.setText(self._full_signal)
        self.lbl_signal.setToolTip(self._full_signal)

        self._apply_elide()
