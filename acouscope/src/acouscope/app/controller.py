# SPDX-License-Identifier: GPL-3.0-only
"""应用控制器。

负责协调各个模块，是 UI 和业务逻辑之间的桥梁。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

from acouscope.audio import AudioIO, AudioInfo, AudioPlayer
from acouscope.analysis.params_snapshot import (
    ANALYSIS_PARAMS_METADATA_KEY,
    params_snapshot_to_metadata,
)
from acouscope.analysis.pitch_grid import PitchGridModel
from acouscope.app.project import ProjectManager
from acouscope.dsp.cache import AnalysisCache
from acouscope.utils import Settings


class AppController:
    """应用主控制器。

    采用 MVC 模式，协调各模块间的交互。
    """

    def __init__(self):
        self.settings = Settings.load()
        self.audio_io = AudioIO()
        self.audio_player = AudioPlayer()
        self.project = ProjectManager()

        # 分析引擎缓存（避免重复创建）
        self.analysis_cache = AnalysisCache(max_size=12)

        # 当前状态
        self._current_file: Optional[Path] = None
        self._audio_data: Optional[np.ndarray] = None
        self._sample_rate: int = 0
        self._audio_info: Optional[AudioInfo] = None

        # 分析结果缓存
        self._analysis_cache: dict = {}

    # ------------------------------------------------------------------
    # 文件操作
    # ------------------------------------------------------------------

    def open_file(self, filepath: str | Path) -> AudioInfo:
        """打开音频文件。

        Args:
            filepath: 音频文件路径

        Returns:
            音频信息对象

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 不支持的格式
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"文件不存在: {filepath}")

        data, sample_rate = self.audio_io.load(filepath)
        info = self.audio_io.get_info(filepath)

        # 保存旧状态，播放器加载失败时回滚
        old_state = (
            self._current_file, self._audio_data,
            self._sample_rate, self._audio_info,
        )

        self._current_file = filepath
        self._audio_data = data
        self._sample_rate = sample_rate
        self._audio_info = info
        self._analysis_cache.clear()

        # 加载到播放器（失败则回滚状态并抛出）
        try:
            self.audio_player.load(data, sample_rate)
        except Exception:
            (
                self._current_file,
                self._audio_data,
                self._sample_rate,
                self._audio_info,
            ) = old_state
            raise

        return info

    def load_from_array(self, data: np.ndarray, sample_rate: int, name: str = "recording") -> None:
        """从 numpy 数组加载音频（用于录音等场景）。

        Args:
            data: 音频数据（单声道，float32/float64 均可）
            sample_rate: 采样率
            name: 显示名称
        """
        self._current_file = Path(name)
        # 零复制引用（不做 float64 整体转换：10 分钟录音可省数百 MB）
        self._audio_data = np.asarray(data)
        self._sample_rate = sample_rate
        from acouscope.audio.io import AudioInfo
        bits = 32 if self._audio_data.dtype == np.float32 else 64
        self._audio_info = AudioInfo(
            filepath=str(name),
            sample_rate=sample_rate,
            channels=1,
            duration=len(data) / sample_rate if sample_rate > 0 else 0,
            samples=len(data),
            bit_depth=bits,
            format=f"float{bits}",
            file_size=0,
        )
        self._analysis_cache.clear()
        self.audio_player.load(data, sample_rate)

    @property
    def current_file(self) -> Optional[Path]:
        """当前打开的文件路径。"""
        return self._current_file

    @property
    def audio_data(self) -> Optional[np.ndarray]:
        """当前音频数据（numpy 数组）。"""
        return self._audio_data

    @property
    def sample_rate(self) -> int:
        """当前采样率。"""
        return self._sample_rate

    @property
    def audio_info(self) -> Optional[AudioInfo]:
        """当前音频文件信息。"""
        return self._audio_info

    def has_audio(self) -> bool:
        """是否已加载音频。"""
        return self._audio_data is not None

    # ------------------------------------------------------------------
    # 播放控制
    # ------------------------------------------------------------------

    def play(self) -> None:
        """开始播放。"""
        self.audio_player.play()

    def pause(self) -> None:
        """暂停播放。"""
        self.audio_player.pause()

    def stop(self) -> None:
        """停止播放。"""
        self.audio_player.stop()

    def is_playing(self) -> bool:
        """是否正在播放。"""
        return self.audio_player.is_playing()

    def set_position(self, seconds: float) -> None:
        """设置播放位置。

        Args:
            seconds: 目标位置（秒）
        """
        self.audio_player.set_position(seconds)

    def get_position(self) -> float:
        """获取当前播放位置（秒）。"""
        return self.audio_player.get_position()

    def set_loop(self, start_sec, end_sec):
        """设置循环播放区域。"""
        self.audio_player.set_loop(start_sec, end_sec)

    def set_loop_enabled(self, enabled: bool):
        self.audio_player.set_loop_enabled(enabled)

    def is_loop_enabled(self) -> bool:
        return self.audio_player.is_loop_enabled()

    def get_loop_region(self):
        return self.audio_player.get_loop_region()

    def set_playback_rate(self, rate: float):
        """设置播放速率（0.25 ~ 4.0）。"""
        self.audio_player.set_rate(rate)

    # ------------------------------------------------------------------
    # 分析功能（占位，后续逐步实现）
    # ------------------------------------------------------------------

    def get_waveform(self, max_points: int = 10000) -> tuple[np.ndarray, np.ndarray]:
        """获取波形数据（降采样用于显示）。

        Args:
            max_points: 最大返回点数

        Returns:
            (时间数组, 幅度数组)
        """
        if self._audio_data is None:
            return np.array([]), np.array([])

        data = self._audio_data
        n = len(data)

        if n <= max_points:
            times = np.arange(n) / self._sample_rate
            return times, data

        # 降采样：取每个区间的峰值
        step = n // max_points
        n_out = n // step
        reshaped = data[: n_out * step].reshape(n_out, step)
        peaks = np.max(np.abs(reshaped), axis=1) * np.sign(
            reshaped[np.arange(n_out), np.argmax(np.abs(reshaped), axis=1)]
        )
        times = np.arange(n_out) * step / self._sample_rate

        return times, peaks

    # ------------------------------------------------------------------
    # 项目管理
    # ------------------------------------------------------------------

    def save_project(
        self,
        filepath: str | Path,
        annotations: list | None = None,
        grid_model: PitchGridModel | None = None,
        as_snapshot: bool = False,
    ) -> Path:
        """保存项目。

        将当前打开的音频文件作为条目写入项目（同路径条目更新，不同则追加），
        保留项目中的其他文件条目。

        Args:
            filepath: 项目文件路径
            annotations: 用户标注（如频谱谐波标记）
            grid_model: 音高网格模型（T-804，None 时零行为变更）
            as_snapshot: T-322 autosave 快照模式——写盘但不把项目"命名"到快照
                路径（未命名项目手动保存仍走另存为，语义不被快照污染）

        Returns:
            项目文件路径
        """
        if self._current_file is not None:
            # 未命名项目时用音频文件名作项目名
            if self.project.current.name == "未命名项目":
                self.project.current.name = self._current_file.stem

            path_str = str(self._current_file)
            entry = next(
                (f for f in self.project.current.files if f.path == path_str), None
            )
            if entry is None:
                entry = self.project.add_file(path_str, label=self._current_file.name)
            else:
                entry.label = self._current_file.name

            if annotations is not None:
                entry.analysis_results["harmonic_marks"] = annotations
            if grid_model is not None:
                entry.analysis_results["pitch_grid"] = grid_model
                # B1-03：参数快照绑定（保存时点即本次分析时点；参数面为全局单源
                # + 静态参数表）。值为 JSON 字符串，合 Dict[str, str] 不变式。
                entry.metadata[ANALYSIS_PARAMS_METADATA_KEY] = (
                    params_snapshot_to_metadata()
                )

        if as_snapshot:
            self.project.save_to(filepath)
            return Path(filepath)
        self.project.save(filepath)
        return self.project.filepath

    def load_project(self, filepath: str | Path) -> tuple:
        """加载项目。

        若项目含音频文件条目，自动打开第一个存在的文件。

        Args:
            filepath: 项目文件路径

        Returns:
            (Project, AudioInfo 或 None)
        """
        project = self.project.load(filepath)

        audio_info = None
        for entry in project.files:
            if Path(entry.path).exists():
                audio_info = self.open_file(entry.path)
                break

        return project, audio_info

    def get_saved_annotations(self) -> list:
        """获取当前文件在项目中已保存的标注。"""
        if self._current_file is None:
            return []
        path_str = str(self._current_file)
        entry = next(
            (f for f in self.project.current.files if f.path == path_str), None
        )
        if entry is None:
            return []
        return entry.analysis_results.get("harmonic_marks", [])

    def get_saved_pitch_grid(self) -> PitchGridModel | None:
        """获取当前文件在项目中已保存的音高网格模型（T-804）。

        无当前文件/无条目/无键 → None。
        """
        if self._current_file is None:
            return None
        path_str = str(self._current_file)
        entry = next(
            (f for f in self.project.current.files if f.path == path_str), None
        )
        if entry is None:
            return None
        return entry.analysis_results.get("pitch_grid")

    # ------------------------------------------------------------------
    # 设置管理
    # ------------------------------------------------------------------

    def save_settings(self) -> None:
        """保存当前设置。"""
        self.settings.save()
