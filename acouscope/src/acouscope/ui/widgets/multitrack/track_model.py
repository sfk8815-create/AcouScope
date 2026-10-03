# SPDX-License-Identifier: GPL-3.0-only
"""T-1004 M1 多轨数据层：轨道模型 / 会话集合 / 懒加载与内存估算。

设计口径（唯一语义源 = `内部记录/knowledge/ARCH_multitrack_interaction.md` D1~D10）：

- 轨道对音频数据只做**引用**（同一缓冲多轨共享，不复制）；全量样本仅在轨道被
  切为当前轨 / 需要分析时载入，非活跃轨可按 LRU 释放（防护接入点留 T-929）。
- 懒加载三级：元数据（采样率/时长/声道，读文件头）→ 粗包络（块式抽稀峰值，
  不保留全量样本）→ 全量样本（按需）。
- 对齐偏移（offset_ms）本任务只存字段与读写接口；**对齐算法归 T-1006**，
  偏移不改音频数据（无损语义）。
- solo/mute 为**播放期解析**语义：任一轨 solo → 仅 solo 且未 mute 的轨可闻。
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Callable, Iterable

import numpy as np

from acouscope.ui import theme

# 懒加载状态（描述**全量样本**的载入状态；粗包络另由 has_envelope 表达）
UNLOADED = "unloaded"
LOADING = "loading"
READY = "ready"

# 粗包络点数（整轨峰值抽稀；载入即算，内存有界）
COARSE_POINTS = 1024
# 块式读取帧数（逐块读，不驻留全量样本）
_BLOCK_FRAMES = 1 << 16
# 每轨固定开销估算（控件/元数据/包络索引等，用于健康提示量级估算）
_TRACK_OVERHEAD_BYTES = 4096


def default_envelope_reader(path, points: int = COARSE_POINTS):
    """块式读取音频并抽稀为峰值包络（不保留全量样本）。

    Returns:
        (times, peaks)：times 为各分桶中心时刻（秒），peaks 为桶内 |样本| 峰值。
    """
    import soundfile as sf

    points = max(1, int(points))
    with sf.SoundFile(str(path)) as f:
        sr = int(f.samplerate)
        frames = int(f.frames)
        if frames <= 0 or sr <= 0:
            return np.zeros(0, dtype=np.float64), np.zeros(0, dtype=np.float32)
        bucket = max(1, frames // points)
        acc = np.zeros(points, dtype=np.float32)
        pos = 0
        while True:
            block = f.read(_BLOCK_FRAMES, dtype="float32", always_2d=True)
            if block is None or len(block) == 0:
                break
            mono = np.abs(block).max(axis=1)
            idx = (np.arange(len(mono), dtype=np.int64) + pos) // bucket
            np.clip(idx, 0, points - 1, out=idx)
            np.maximum.at(acc, idx, mono.astype(np.float32))
            pos += len(mono)
        times = (np.arange(points, dtype=np.float64) + 0.5) * bucket / sr
        return times, acc


def format_seconds(seconds: float) -> str:
    """秒 → "M:SS.mmm"（时间轴/轨道信息显示口径，T-917 绝对时间）。"""
    value = float(seconds or 0.0)
    sign = "-" if value < 0 else ""
    value = abs(value)
    minutes = int(value // 60)
    rest = value - minutes * 60
    return f"{sign}{minutes}:{rest:06.3f}"


def default_metadata_reader(path) -> dict:
    """读音频头信息（不载入样本）：AudioIO.get_info（既有只读复用）。"""
    from acouscope.audio.io import AudioIO

    info = AudioIO().get_info(path)
    return {
        "sample_rate": int(info.sample_rate),
        "channels": int(info.channels),
        "duration": float(info.duration),
    }


def default_loader(path):
    """载入全量样本（既有 AudioIO.load；返回 (data float64, sample_rate)）。"""
    from acouscope.audio.io import AudioIO

    return AudioIO().load(path)


class TrackModel:
    """单条轨道的状态容器（不绘图、不持父控件，可纯逻辑测试）。"""

    def __init__(
        self,
        path,
        *,
        label: str | None = None,
        track_id: str | None = None,
        color_index: int = 0,
        envelope_reader: Callable | None = None,
        metadata_reader: Callable | None = None,
        loader: Callable | None = None,
    ):
        self.track_id = track_id or uuid.uuid4().hex[:12]
        self.path = Path(path)
        self.label = label or self.path.stem
        self.color_index = int(color_index)

        self.state = UNLOADED              # 全量样本载入状态
        self.metadata_ready = False
        self.envelope_ready = False
        self.sample_rate = 0
        self.channels = 0
        self.duration = 0.0

        self.solo = False
        self.mute = False
        self.volume = 1.0                  # D10 方案甲：播放当前轨时的 per-track gain
        self.offset_ms = 0.0               # 对齐偏移（读写接口；算法归 T-1006）

        self.error: str | None = None
        self._data: np.ndarray | None = None
        self._env_times: np.ndarray | None = None
        self._env_peaks: np.ndarray | None = None
        self._peak: float | None = None
        self._envelope_reader = envelope_reader or default_envelope_reader
        self._metadata_reader = metadata_reader or default_metadata_reader
        self._loader = loader or default_loader

    # ------------------------------------------------------------------
    # 懒加载（元数据 → 粗包络 → 全量样本）
    # ------------------------------------------------------------------

    def load_metadata(self) -> bool:
        """读文件头元数据（不载入样本）。失败返回 False 并记录 error。"""
        if self.metadata_ready:
            return True
        try:
            info = self._metadata_reader(self.path)
        except Exception as exc:  # 无 FFmpeg / 文件损坏等：降级为非致命
            self.error = str(exc)
            return False
        self.sample_rate = int(info.get("sample_rate") or 0)
        self.channels = int(info.get("channels") or 0)
        self.duration = float(info.get("duration") or 0.0)
        self.metadata_ready = True
        return True

    def load_envelope(self, points: int = COARSE_POINTS) -> bool:
        """算粗包络（块式读取，不驻留全量样本）。已算则直接返回 True。"""
        if self.envelope_ready:
            return True
        try:
            times, peaks = self._envelope_reader(self.path, points)
        except Exception as exc:
            self.error = str(exc)
            return False
        self._env_times = np.asarray(times, dtype=np.float64)
        self._env_peaks = np.asarray(peaks, dtype=np.float32)
        self._peak = (
            float(self._env_peaks.max()) if self._env_peaks.size else 0.0
        )
        self.envelope_ready = True
        if not self.metadata_ready and self._env_times.size:
            self.duration = float(self._env_times[-1])
        return True

    def load_full(self) -> np.ndarray | None:
        """载入全量样本（切为当前轨 / 需要分析时调用）；已载入则直接返回。"""
        if self._data is not None:
            return self._data
        self.state = LOADING
        try:
            data, sr = self._loader(self.path)
        except Exception as exc:
            self.error = str(exc)
            self.state = UNLOADED
            return None
        self.set_data(data, sample_rate=sr)
        return self._data

    def set_data(self, data, *, sample_rate: int | None = None, copy: bool = False):
        """注入全量样本。默认**引用**传入数组（不复制）；copy=True 时才复制。"""
        if data is None:
            self.release_data()
            return
        arr = np.asarray(data)
        self._data = np.array(arr, copy=True) if copy else arr
        if sample_rate:
            self.sample_rate = int(sample_rate)
        if not self.duration and self.sample_rate:
            self.duration = float(len(self._data)) / float(self.sample_rate)
        self.state = READY

    def release_data(self) -> bool:
        """释放全量样本（保留元数据与粗包络）；返回本次是否确有释放。"""
        had = self._data is not None
        self._data = None
        self.state = UNLOADED
        return had

    # ------------------------------------------------------------------
    # 只读视图与统计
    # ------------------------------------------------------------------

    @property
    def data(self) -> np.ndarray | None:
        """全量样本引用（无复制；未载入为 None）。"""
        return self._data

    @property
    def has_data(self) -> bool:
        return self._data is not None

    def envelope(self):
        """粗包络 (times, peaks) 引用（无复制）。"""
        if self._env_times is None or self._env_peaks is None:
            return np.zeros(0, dtype=np.float64), np.zeros(0, dtype=np.float32)
        return self._env_times, self._env_peaks

    def level_peak(self) -> float:
        """静态电平（读文件峰值，来自粗包络）；未知返回 0.0。"""
        return float(self._peak or 0.0)

    def shifted_duration(self) -> float:
        """含对齐偏移的轨尾时刻（秒）。"""
        return self.offset_ms / 1000.0 + float(self.duration)

    def nbytes(self) -> int:
        """该轨当前驻留内存估算（样本 + 包络）。"""
        total = 0
        if self._data is not None:
            total += int(self._data.nbytes)
        if self._env_times is not None:
            total += int(self._env_times.nbytes)
        if self._env_peaks is not None:
            total += int(self._env_peaks.nbytes)
        return total

    # ------------------------------------------------------------------
    # 可变字段（S/M/音量/偏移/轨名）
    # ------------------------------------------------------------------

    def set_offset_ms(self, value: float) -> float:
        self.offset_ms = float(value)
        return self.offset_ms

    def set_label(self, text: str) -> str:
        self.label = str(text).strip() or self.path.stem
        return self.label


class MultitrackSession:
    """多轨会话：轨列表 + 当前轨 + S/M 解析 + LRU 释放 + 内存估算。

    本类为纯数据/状态对象（无 Qt 依赖）；UI 侧（T-1004 波形区）只读消费它。
    """

    def __init__(
        self,
        *,
        max_loaded: int = 4,
        envelope_reader: Callable | None = None,
        metadata_reader: Callable | None = None,
        loader: Callable | None = None,
        clock: Callable | None = None,
    ):
        self.max_loaded = int(max_loaded)
        self._tracks: list[TrackModel] = []
        self._current_id: str | None = None
        self._pending: tuple[int, TrackModel] | None = None
        self._color_seq = 0
        self._clock = clock or time.monotonic
        self._envelope_reader = envelope_reader or default_envelope_reader
        self._metadata_reader = metadata_reader or default_metadata_reader
        self._loader = loader or default_loader

    # ------------------------------------------------------------------
    # 集合维护
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._tracks)

    def tracks(self) -> list[TrackModel]:
        """当前轨列表（浅拷贝，避免外部增删）。"""
        return list(self._tracks)

    def index_of(self, track_id: str) -> int:
        for i, t in enumerate(self._tracks):
            if t.track_id == track_id:
                return i
        return -1

    def get(self, track_id: str) -> TrackModel | None:
        i = self.index_of(track_id)
        return self._tracks[i] if i >= 0 else None

    def add_path(self, path, *, label: str | None = None) -> TrackModel:
        """由文件路径新建轨道：读元数据 + 算粗包络（懒加载第一/二级）。

        ★ T-1087 M5：拆成 `new_track`（零包络 IO·轨道立即可见）+ `prepare_track`
        （粗包络·整文件块式读，可交 worker）。本方法口径逐字不变（两步就地跑完），
        三级懒加载与 LRU 语义未动。
        """
        track = self.new_track(path, label=label)
        self.prepare_track(track)
        return track

    def new_track(self, path, *, label: str | None = None) -> TrackModel:
        """登记轨道并只读文件头元数据（**不碰粗包络** ⇒ 零整文件 IO）。

        返回已入列的轨道；包络留给 :meth:`prepare_track`（可在 worker 线程调）。
        """
        track = TrackModel(
            path,
            label=label,
            color_index=self._color_seq % len(theme.track_palette()),
            envelope_reader=self._envelope_reader,
            metadata_reader=self._metadata_reader,
            loader=self._loader,
        )
        self._color_seq += 1
        track.load_metadata()
        self._tracks.append(track)
        if self._current_id is None:
            self._current_id = track.track_id
        return track

    def prepare_track(self, track: TrackModel) -> bool:
        """填粗包络（块式读整文件·懒加载第二级）；返回是否就绪。

        纯数据侧动作（不触 UI）⇒ 允许在 worker 线程调用；界面回填由调用方在
        主线程的 done 回调里做（见 ``MultitrackPanel.add_files``）。
        """
        if track is None:
            return False
        return track.load_envelope()

    def add_track(self, track: TrackModel) -> TrackModel:
        """直接登记已有轨道对象（测试/迁移用）。"""
        self._tracks.append(track)
        if self._current_id is None:
            self._current_id = track.track_id
        return track

    def remove(self, track_id: str, *, undoable: bool = True) -> TrackModel | None:
        """移除轨（D9 撤销窗口：进入 pending 槽，可 restore_pending 撤回）。"""
        i = self.index_of(track_id)
        if i < 0:
            return None
        track = self._tracks.pop(i)
        if undoable:
            self._pending = (i, track)
        if self._current_id == track_id:
            self._current_id = (
                self._tracks[min(i, len(self._tracks) - 1)].track_id
                if self._tracks else None
            )
        return track

    @property
    def pending_removal(self) -> TrackModel | None:
        return self._pending[1] if self._pending else None

    def restore_pending(self) -> TrackModel | None:
        """撤回上一次移除（原位回插）。"""
        if self._pending is None:
            return None
        index, track = self._pending
        self._pending = None
        self._tracks.insert(min(index, len(self._tracks)), track)
        if self._current_id is None:
            self._current_id = track.track_id
        return track

    def clear_pending(self) -> None:
        self._pending = None

    def clear(self) -> None:
        """清空会话（退出多轨态/换音频时；未保存的仅视图态）。"""
        for t in self._tracks:
            t.release_data()
        self._tracks.clear()
        self._current_id = None
        self._pending = None
        self._color_seq = 0

    # ------------------------------------------------------------------
    # 当前轨 / S/M / 音量
    # ------------------------------------------------------------------

    @property
    def current_id(self) -> str | None:
        return self._current_id

    @property
    def current(self) -> TrackModel | None:
        return self.get(self._current_id) if self._current_id else None

    def set_current(self, track_id: str) -> bool:
        if self.index_of(track_id) < 0:
            return False
        self._current_id = track_id
        return True

    def audible_ids(self) -> list[str]:
        """可闻轨（D10/solo 语义）：任一轨 solo → 仅 solo 且未 mute 者可闻。"""
        soloed = [t for t in self._tracks if t.solo]
        pool = soloed if soloed else self._tracks
        return [t.track_id for t in pool if not t.mute]

    def set_solo(self, track_id: str, on: bool) -> bool:
        t = self.get(track_id)
        if t is None:
            return False
        t.solo = bool(on)
        return True

    def set_mute(self, track_id: str, on: bool) -> bool:
        t = self.get(track_id)
        if t is None:
            return False
        t.mute = bool(on)
        return True

    def set_volume(self, track_id: str, value: float) -> float | None:
        t = self.get(track_id)
        if t is None:
            return None
        t.volume = max(0.0, min(1.0, float(value)))
        return t.volume

    def set_label(self, track_id: str, text: str) -> str | None:
        t = self.get(track_id)
        return t.set_label(text) if t is not None else None

    def set_offset_ms(self, track_id: str, value: float) -> float | None:
        t = self.get(track_id)
        return t.set_offset_ms(value) if t is not None else None

    # ------------------------------------------------------------------
    # 时间轴与内存
    # ------------------------------------------------------------------

    def total_duration(self) -> float:
        """共享时间轴总长 = 各轨（含偏移）尾时刻最大值。"""
        if not self._tracks:
            return 0.0
        return max(t.shifted_duration() for t in self._tracks)

    def loaded_ids(self) -> list[str]:
        return [t.track_id for t in self._tracks if t.has_data]

    def load_full(self, track_id: str) -> np.ndarray | None:
        """载入指定轨全量样本，并顺带按 LRU 释放非活跃轨（内存有界）。"""
        t = self.get(track_id)
        if t is None:
            return None
        data = t.load_full()
        self.unload_inactive(keep=(track_id,))
        return data

    def unload_inactive(self, keep: Iterable[str] = ()) -> list[str]:
        """LRU 释放：保留当前轨与 keep 名单，其余按载入序释放到 ≤ max_loaded。"""
        keep_set = set(keep)
        if self._current_id:
            keep_set.add(self._current_id)
        loaded = [t for t in self._tracks if t.has_data]
        released: list[str] = []
        for t in sorted(loaded, key=lambda x: self.index_of(x.track_id)):
            if len(loaded) - len(released) <= max(1, self.max_loaded):
                break
            if t.track_id in keep_set:
                continue
            if t.release_data():
                released.append(t.track_id)
        return released

    def estimate_bytes(self) -> int:
        """健康提示口径：各轨驻留（样本 + 包络）+ 每轨固定开销。"""
        return sum(t.nbytes() + _TRACK_OVERHEAD_BYTES for t in self._tracks)

    def estimate_mb(self) -> float:
        return self.estimate_bytes() / (1024.0 * 1024.0)
