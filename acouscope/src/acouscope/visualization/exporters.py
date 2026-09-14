# SPDX-License-Identifier: GPL-3.0-only
"""图表导出模块。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np


class FigureExporter:
    """图表导出器。

    支持多种格式的高质量图表导出。
    """

    SUPPORTED_FORMATS = {
        "svg": {"type": "vector", "description": "SVG 矢量图"},
        "eps": {"type": "vector", "description": "EPS 矢量图 (LaTeX)"},
        "pdf": {"type": "vector", "description": "PDF 矢量图"},
        "png": {"type": "raster", "description": "PNG 位图"},
        "tiff": {"type": "raster", "description": "TIFF 位图 (印刷)"},
        "jpg": {"type": "raster", "description": "JPEG 位图"},
    }

    def __init__(
        self,
        template: str = "default",
        language: str = "zh_CN",
        font_latin: str = "auto",
        font_cjk: str = "auto",
        *,
        palette: str = "default",
        ref_ink: str | None = None,
        line_width: float | None = None,
        width: float | None = None,
        height: float | None = None,
        grid: bool = True,
    ):
        """初始化导出器。

        T-1044：后 6 个参数一律 **keyword-only 且带默认值** → 既有调用零变化
        （`palette="default"` 时序列色与改动前同源）。

        Args:
            template: 期刊模板
            language: 语言
            font_latin: 西文/数字字体
            font_cjk: 中文字体
            palette: 数据序列配色（default / grayscale / colorblind / viridis /
                inferno）；viridis·inferno 无离散序列色 → 序列色回退 default，
                热图色图取该 colormap 名
            ref_ink: 参考线/结构线墨色覆盖（None = 导出侧默认中性墨色 EXPORT_INK）
            line_width: 序列线宽覆盖（None = 各图既有默认值）
            width: 画幅宽（英寸；None = 模板值）
            height: 画幅高（英寸；None = 模板值）
            grid: 是否绘制网格（默认 True = 既有行为）
        """
        self.template = template
        self.language = language
        self.font_latin = font_latin or "auto"
        self.font_cjk = font_cjk or "auto"
        # 惰性导入：mpl_style 在模块加载期即引入 matplotlib（历史上刻意避免）
        from .mpl_style import EXPORT_INK, palette_cycle

        self.palette = palette
        self._cycle = palette_cycle(palette)
        self.ink = dict(EXPORT_INK)
        if ref_ink:
            self.ink["ref_line"] = ref_ink
        self.line_width = line_width
        self.width = width
        self.height = height
        self.grid = bool(grid)
        self._style = None

    # -- T-1044 取色 / 参数解析 ----------------------------------------

    def _series_color(self, index: int = 0) -> str:
        """数据序列色：调色板第 index 色；colormap 类 → 回退 default 调色板。"""
        seq = self._cycle
        if seq is None:
            from .mpl_style import palette_cycle

            seq = palette_cycle("default")
        return seq[index % len(seq)]

    def _cmap(self, cmap: str) -> str:
        """热图色图：palette 为 colormap 类（viridis/inferno）时以 palette 名为准。"""
        return self.palette if self._cycle is None else cmap

    def _linewidth(self, default: float) -> float:
        """序列线宽：None → 既有默认值。"""
        return default if self.line_width is None else float(self.line_width)

    def _apply_grid(self, ax, **kwargs) -> None:
        """网格显隐（grid=False 时不画网格）。"""
        if self.grid:
            ax.grid(True, **kwargs)

    def _new_figure(self):
        """按模板/字体/画幅建图（预览与导出同源：仅 dpi 与 savefig 行为不同）。"""
        from .mpl_style import create_figure

        return create_figure(
            self.template, self.language,
            font_latin=self.font_latin, font_cjk=self.font_cjk,
            width=self.width, height=self.height,
        )

    def export_waveform(
        self,
        times: np.ndarray,
        signal: np.ndarray,
        output_path: str | Path,
        fmt: str = "svg",
        dpi: int = 300,
        title: str = "",
        xlabel: str = "时间 (s)",
        ylabel: str = "幅度",
    ) -> Path:
        """导出波形图。

        Args:
            times: 时间轴
            signal: 信号幅度
            output_path: 输出路径
            fmt: 输出格式
            dpi: 分辨率
            title: 图标题
            xlabel: X 轴标签
            ylabel: Y 轴标签

        Returns:
            输出文件路径
        """
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = self._new_figure()

        ax.plot(times, signal, linewidth=self._linewidth(0.8), color=self._series_color(0))
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        if title:
            ax.set_title(title)

        ax.axhline(0, color=self.ink["axis"], linewidth=0.5, linestyle="-")
        self._apply_grid(ax, alpha=0.3, linewidth=0.5)
        ax.set_xlim(times[0], times[-1])

        return self._save(fig, output_path, fmt, dpi)

    def export_spectrum(
        self,
        freqs: np.ndarray,
        magnitude: np.ndarray,
        output_path: str | Path,
        fmt: str = "svg",
        dpi: int = 300,
        title: str = "",
        xlabel: str = "频率 (Hz)",
        ylabel: str = "幅度 (dB)",
        xscale: str = "linear",
        markers: Optional[list] = None,
        xlim: Optional[tuple] = None,
        ylim: Optional[tuple] = None,
    ) -> Path:
        """导出频谱图。

        Args:
            freqs: 频率轴
            magnitude: 幅度（dB 或线性）
            output_path: 输出路径
            fmt: 输出格式
            dpi: 分辨率
            title: 标题
            xlabel: X 轴标签
            ylabel: Y 轴标签
            xscale: X 轴标度 (linear / log)
            markers: 谐波标记列表 [(频率, 标签), ...]，导出时绘制竖线与标签
            xlim: X 轴显示范围（与窗口视图一致），None 时自动
            ylim: Y 轴显示范围（与窗口视图一致），None 时自动

        Returns:
            输出文件路径
        """
        import matplotlib
        matplotlib.use("Agg")

        fig, ax = self._new_figure()

        ax.plot(freqs, magnitude, linewidth=self._linewidth(0.8), color=self._series_color(0))
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        if title:
            ax.set_title(title)

        ax.set_xscale(xscale)
        self._apply_grid(ax, alpha=0.3, linewidth=0.5, which="both")

        # 与窗口视图一致：显式应用当前显示范围
        if xlim is not None and len(xlim) == 2:
            ax.set_xlim(float(xlim[0]), float(xlim[1]))
        if ylim is not None and len(ylim) == 2:
            ax.set_ylim(float(ylim[0]), float(ylim[1]))

        if markers:
            for freq, label in markers:
                ax.axvline(freq, color=self.ink["ref_line"], linewidth=0.7, linestyle="--", alpha=0.8)
                if label:
                    ax.annotate(
                        label,
                        xy=(freq, 0.97),
                        xycoords=("data", "axes fraction"),
                        fontsize=7,
                        rotation=90,
                        va="top",
                        ha="right",
                        color=self.ink["ref_line"],
                    )

        return self._save(fig, output_path, fmt, dpi)

    def export_spectrogram(
        self,
        freqs: np.ndarray,
        times: np.ndarray,
        data: np.ndarray,
        output_path: str | Path,
        fmt: str = "png",
        dpi: int = 300,
        title: str = "",
        xlabel: str = "时间 (s)",
        ylabel: str = "频率 (Hz)",
        cmap: str = "magma",
        vmin: Optional[float] = None,
        vmax: Optional[float] = None,
    ) -> Path:
        """导出语谱图。

        Args:
            freqs: 频率轴
            times: 时间轴
            data: 语谱图数据矩阵
            output_path: 输出路径
            fmt: 输出格式（建议 png/tiff）
            dpi: 分辨率
            title: 标题
            xlabel: X 轴标签
            ylabel: Y 轴标签
            cmap: 颜色映射
            vmin: 颜色范围最小值
            vmax: 颜色范围最大值

        Returns:
            输出文件路径
        """
        import matplotlib
        matplotlib.use("Agg")

        fig, ax = self._new_figure()

        im = ax.pcolormesh(times, freqs, data, cmap=self._cmap(cmap), vmin=vmin, vmax=vmax, shading="auto")
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        if title:
            ax.set_title(title)

        cbar = fig.colorbar(im, ax=ax)
        cbar.ax.tick_params(labelsize=8)

        return self._save(fig, output_path, fmt, dpi)

    def export_pitch_contour(
        self,
        times: np.ndarray,
        f0: np.ndarray,
        output_path: str | Path,
        fmt: str = "svg",
        dpi: int = 300,
        title: str = "",
        xlabel: str = "时间 (s)",
        ylabel: str = "频率 (Hz)",
    ) -> Path:
        """导出音高轨迹图。

        Args:
            times: 时间轴
            f0: 基频序列
            output_path: 输出路径
            fmt: 输出格式
            dpi: 分辨率
            title: 标题
            xlabel: X 轴标签
            ylabel: Y 轴标签

        Returns:
            输出文件路径
        """
        import matplotlib
        matplotlib.use("Agg")

        fig, ax = self._new_figure()

        # 过滤零值（无声帧）
        valid = f0 > 0
        ax.plot(times[valid], f0[valid], ".", markersize=2, color=self._series_color(0), alpha=0.7)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        if title:
            ax.set_title(title)

        self._apply_grid(ax, alpha=0.3, linewidth=0.5)
        ax.set_xlim(times[0], times[-1])

        return self._save(fig, output_path, fmt, dpi)

    def export_formants(
        self,
        times: np.ndarray,
        formant_freqs: np.ndarray,
        output_path: str | Path,
        fmt: str = "svg",
        dpi: int = 300,
        title: str = "",
        xlabel: str = "时间 (s)",
        ylabel: str = "频率 (Hz)",
    ) -> Path:
        """导出共振峰轨迹图。

        Args:
            times: 时间轴 [n_frames]
            formant_freqs: 共振峰频率 [n_frames, n_formants]（0 表示无效）
            output_path: 输出路径
            fmt: 输出格式
            dpi: 分辨率
            title: 标题
            xlabel: X 轴标签
            ylabel: Y 轴标签

        Returns:
            输出文件路径
        """
        import matplotlib
        matplotlib.use("Agg")

        fig, ax = self._new_figure()

        # 共振峰 F1~F4 四序列：逐序取调色板（colormap 类 palette → 回退 default）
        colors = [self._series_color(k) for k in range(4)]
        n_formants = min(formant_freqs.shape[1], len(colors)) if formant_freqs.ndim == 2 else 0

        for k in range(n_formants):
            freq_k = formant_freqs[:, k]
            valid = freq_k > 0
            if np.any(valid):
                ax.plot(times[valid], freq_k[valid], ".", markersize=2.5,
                        color=colors[k], alpha=0.75, label=f"F{k + 1}")

        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        if title:
            ax.set_title(title)

        if n_formants > 0:
            ax.legend(fontsize=8, frameon=False)
        self._apply_grid(ax, alpha=0.3, linewidth=0.5)
        if len(times) > 0:
            ax.set_xlim(times[0], times[-1])

        return self._save(fig, output_path, fmt, dpi)

    def export_mfcc(
        self,
        times: np.ndarray,
        mfcc: np.ndarray,
        output_path: str | Path,
        fmt: str = "png",
        dpi: int = 300,
        title: str = "",
        xlabel: str = "时间 (s)",
        ylabel: str = "MFCC 系数阶数",
        cmap: str = "viridis",
    ) -> Path:
        """导出 MFCC 热图。

        Args:
            times: 时间轴 [n_frames]
            mfcc: MFCC 矩阵 [n_frames, n_mfcc]
            output_path: 输出路径
            fmt: 输出格式（建议 png/tiff）
            dpi: 分辨率
            title: 标题
            xlabel: X 轴标签
            ylabel: Y 轴标签
            cmap: 颜色映射

        Returns:
            输出文件路径
        """
        import matplotlib
        matplotlib.use("Agg")

        fig, ax = self._new_figure()

        data = mfcc.T  # [n_mfcc, n_frames]
        im = ax.pcolormesh(times, np.arange(data.shape[0]), data,
                           cmap=self._cmap(cmap), shading="nearest")
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        if title:
            ax.set_title(title)

        cbar = fig.colorbar(im, ax=ax)
        cbar.ax.tick_params(labelsize=8)

        return self._save(fig, output_path, fmt, dpi)

    def _save(self, fig, output_path: str | Path, fmt: str, dpi: int) -> Path:
        """保存图表。

        Args:
            fig: matplotlib Figure 对象
            output_path: 输出路径
            fmt: 格式
            dpi: 分辨率

        Returns:
            输出文件路径
        """
        output_path = Path(output_path)

        if fmt == "tiff":
            # matplotlib 不直接支持 tiff，先存为 png 再转换
            import tempfile
            from PIL import Image

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name

            fig.savefig(tmp_path, format="png", dpi=dpi, bbox_inches="tight")
            img = Image.open(tmp_path)
            img.save(output_path, "TIFF", dpi=(dpi, dpi))

            import os
            os.unlink(tmp_path)
        else:
            save_kwargs = {"dpi": dpi, "bbox_inches": "tight"}
            if fmt == "eps":
                save_kwargs["format"] = "eps"
            elif fmt == "pdf":
                save_kwargs["format"] = "pdf"
            elif fmt == "svg":
                save_kwargs["format"] = "svg"
            elif fmt == "png":
                save_kwargs["format"] = "png"
            elif fmt in ("jpg", "jpeg"):
                save_kwargs["format"] = "jpg"

            fig.savefig(output_path, **save_kwargs)

        import matplotlib.pyplot as plt
        plt.close(fig)

        return output_path
