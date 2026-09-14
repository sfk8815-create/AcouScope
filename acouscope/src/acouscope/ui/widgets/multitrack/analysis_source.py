# SPDX-License-Identifier: GPL-3.0-only
"""T-1008 M3 分析源抽象 + 逐轨分析调度（多轨对比包第 3 项）。

口径与红线（细则见任务书 `.pi/tasks/T-1008.txt` 与放行令 `RELEASE_T-1008.md`）：

- **只做「取数层」抽象**：算法函数（`analysis/**`、`dsp/**`）一律不动，仍以
  `(data, sample_rate)` 为参；本模块只决定「把哪条音频喂给算法」。
- **默认源与现状完全等价**：默认解析结果 `data` 与 `controller.audio_data`
  **同一对象**、采样率同值、对齐偏移 0 → 单轨既有分析路径结果逐位不变
  （等价性硬门槛）。
- **不复制 buffer**：`AnalysisSource` 持 ndarray 引用（同 dtype ndarray 经
  `np.asarray` 零复制）；逐轨调度与缓存均只持引用。
- **对齐后时间映射**：复用 T-1006 的 `align.shifted_times`；偏移为 0 时
  **原样返回入参**（保 dtype 与对象身份），保证单轨路径零扰动。
- **两域隔离禁串**（ARCH §五）：多轨逐轨结果缓存键 `(track_id, kind, 参数指纹)`，
  与单轨域 `(kind, fp[, t0, t1])` 形态与语义均不共用、各为独立容器；
  单轨缓存键形态与命中语义零改动。
- **逐轨调度默认并发 1**（与 T-929 限流口径一致，防内存峰值）。
- T-928 任务中心（逐轨进度队列）未合入 → 本模块**同步执行**并在报告注明
  「待 T-928 合入后改走队列」（放行令裁定 C：禁自造队列/进度中心）。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from acouscope.ui.widgets.multitrack.align import shifted_times

# 逐轨调度默认并发（防内存峰值；与 T-929 限流口径一致）
DEFAULT_MAX_CONCURRENCY = 1
# 多轨逐轨结果缓存域标记（与单轨域隔离的自我标识）
CACHE_DOMAIN = "multitrack"
# 逐轨结果缓存默认上限（条目数，超限按插入序淘汰最旧）
DEFAULT_CACHE_LIMIT = 24


def _freeze(value):
    """把参数值转为可哈希指纹片段（dict/list 递归；其余退化为 repr）。"""
    if isinstance(value, dict):
        return tuple(sorted((str(k), _freeze(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def params_fingerprint(params) -> tuple:
    """分析参数指纹（键序不敏感；None/空 → 空元组）。"""
    if not params:
        return ()
    return _freeze(dict(params))


class AnalysisSource:
    """一次分析的只读数据源（**持引用，不复制 buffer**）。

    - `data`：样本数组**引用**（与 `controller.audio_data` 或
      `TrackModel.data` 同一对象；无音频时为 None，与既有取数口径一致）；
    - `sample_rate`：采样率（原样透传，不强制转换）；
    - `align_offset_ms`：对齐偏移（T-1006；默认源 0 = 单轨主态）；
    - `track_id`：多轨轨标识（默认源为 None）；
    - `name`：来源名（文件名/轨名；报告与状态提示用，非界面文案）。
    """

    def __init__(
        self,
        name,
        data,
        sample_rate,
        align_offset_ms=0.0,
        track_id=None,
    ):
        self.name = str(name)
        # 仅做「同 dtype ndarray 零复制」的规整；无音频时为 None（语义同 controller）
        self.data = data if data is None else np.asarray(data)
        self.sample_rate = sample_rate
        self.align_offset_ms = float(align_offset_ms or 0.0)
        self.track_id = track_id

    # ------------------------------------------------------------------
    # 对齐后时间映射（T-1006 偏移）
    # ------------------------------------------------------------------

    @property
    def offset_seconds(self) -> float:
        """对齐偏移（秒）。"""
        return self.align_offset_ms / 1000.0

    def to_timeline(self, times):
        """把源内时间轴映射到对比时间基线。

        偏移为 0（单轨主态）时**原样返回入参**（含 dtype/对象身份），
        保证既有单轨结果逐位不变。
        """
        if not self.align_offset_ms:
            return times
        return shifted_times(times, self.align_offset_ms)

    def fingerprint(self) -> tuple:
        """内容指纹（采样率/长度/幅度和；换音频后逐轨缓存自动失效）。"""
        if self.data is None or len(self.data) == 0:
            return (self.sample_rate, 0, 0.0)
        return (
            self.sample_rate,
            len(self.data),
            float(np.sum(self.data)),
        )

    def __len__(self) -> int:
        return len(self.data) if self.data is not None else 0


def _default_source(controller) -> AnalysisSource:
    """controller 当前文件源（默认源：与改造前取数逐字等价）。"""
    data = getattr(controller, "audio_data", None)
    path = getattr(controller, "current_file", None)
    name = Path(path).stem if path else "current"
    return AnalysisSource(name, data, getattr(controller, "sample_rate", None))


def resolve_source(controller, *, session=None, track_id=None) -> AnalysisSource:
    """解析分析数据源。

    - 默认（`track_id is None`）→ controller 当前文件源：`data` 与
      `controller.audio_data` **同一对象**、采样率同值、偏移 0（与现状等价）。
    - 多轨（显式 `track_id` + `session`）→ 指定轨源：懒加载全量样本，
      携带 T-1006 对齐偏移与 track_id；轨不存在/未载入成功 → 回落默认源。
    """
    if track_id is not None and session is not None:
        track = session.get(track_id) if hasattr(session, "get") else None
        if track is not None:
            data = track.data
            if data is None:
                data = track.load_full()
            if data is not None and len(data):
                return AnalysisSource(
                    getattr(track, "label", None) or str(track_id),
                    data,
                    getattr(track, "sample_rate", None),
                    align_offset_ms=getattr(track, "offset_ms", 0.0),
                    track_id=getattr(track, "track_id", track_id),
                )
    return _default_source(controller)


class TrackResultCache:
    """多轨逐轨结果缓存（**独立域**）。

    键 = `(track_id, kind, 参数指纹)`；与单轨域 `(kind, fp[, t0, t1])` 形态与
    语义均不共用（ARCH §五「两域隔离禁串」）——两个域各自独立存储，轨道键
    不会与单轨键混存，单轨缓存的键形态与命中语义零改动。
    """

    DOMAIN = CACHE_DOMAIN

    def __init__(self, limit: int = DEFAULT_CACHE_LIMIT):
        self.limit = int(limit)
        self._items: dict = {}

    @staticmethod
    def key(track_id, kind, params=None) -> tuple:
        """多轨缓存键：`(track_id, kind, 参数指纹)`。"""
        return (track_id, str(kind), params_fingerprint(params))

    def get(self, key):
        """读取（命中移到末尾＝LRU 序）；未命中返回 None。"""
        if key not in self._items:
            return None
        value = self._items.pop(key)
        self._items[key] = value
        return value

    def put(self, key, result):
        """写入并按上限淘汰最旧条目；返回结果本身（引用透传）。"""
        self._items.pop(key, None)
        self._items[key] = result
        while len(self._items) > self.limit:
            del self._items[next(iter(self._items))]
        return result

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, key) -> bool:
        return key in self._items

    def clear(self) -> None:
        self._items.clear()


class AnalysisHandle:
    """逐轨分析结果句柄（结果**按引用**持有，不复制大数组）。"""

    def __init__(self, track_id, kind, cache_key: tuple):
        self.track_id = track_id
        self.kind = kind
        self.cache_key = cache_key
        self.result = None                 # 分析结果（引用）
        self.error: str | None = None
        self.status = "pending"            # pending|cached|done|error|cancelled
        self.seq = -1                      # 完成序（-1 = 未完成）

    @property
    def ok(self) -> bool:
        return self.status in ("cached", "done")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return (
            f"AnalysisHandle(track_id={self.track_id!r}, kind={self.kind!r}, "
            f"status={self.status!r}, seq={self.seq})"
        )


# ----------------------------------------------------------------------
# 内置逐轨分析 runner（kind → fn(source, params) -> result）
# ----------------------------------------------------------------------

_RUNNERS: dict = {}


def register_runner(kind: str, fn) -> None:
    """登记 kind → 计算函数（`fn(source, params) -> result`）。"""
    _RUNNERS[str(kind)] = fn


def _pitch_runner(source: AnalysisSource, params):
    """音高（pYIN 既定路径；算法本身零改动）。"""
    from acouscope.analysis.pitch import detect_pyin

    return detect_pyin(source.data, source.sample_rate)


def _spectrogram_runner(source: AnalysisSource, params):
    """语谱图 STFT（复用 `dsp/stft.py` 引擎）。"""
    from acouscope.dsp.stft import STFTEngine

    options = dict(params or {})
    engine = STFTEngine(
        n_fft=int(options.get("n_fft", 2048)),
        hop_length=int(options.get("hop_length", 512)),
        window=options.get("window", "hann"),
    )
    return engine.magnitude(source.data, source.sample_rate, db_scale=True)


register_runner("pitch", _pitch_runner)
register_runner("spectrogram", _spectrogram_runner)


def run_analysis_on_tracks(
    sources,
    kind,
    params=None,
    *,
    runner=None,
    cache: TrackResultCache | None = None,
    cancel=None,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
):
    """对多轨逐轨跑同一 kind 分析，返回**输入序**句柄列表。

    - `runner(source, params) -> result`；缺省按 kind 走内置登记表，
      未登记的 kind → 该轨句柄 `status="error"`（不抛）。
    - **默认并发 1**（串行逐轨，防内存峰值）；`max_concurrency > 1` 时走
      线程池（完成序由 `handle.seq` 记录，输入序不变）。
    - 结果按 `(track_id, kind, 参数指纹)` 入多轨缓存（**另域**）；句柄持引用。
    - `cancel`：可调用对象（如 `threading.Event.is_set`）为真 → 不再启动新轨，
      未跑的轨置 `cancelled`；已入缓存者仍走命中（`status="cached"`）。
    - 单轨失败互不影响（异常落在该轨句柄的 `error`）。
    - T-928 未合入：**同步执行**（待合入后改走任务队列）。
    """
    fn = runner or _RUNNERS.get(str(kind))
    cache = cache if cache is not None else TrackResultCache()
    items = list(sources)
    handles = [
        AnalysisHandle(
            getattr(src, "track_id", None),
            str(kind),
            TrackResultCache.key(getattr(src, "track_id", None), kind, params),
        )
        for src in items
    ]

    def _is_cancelled() -> bool:
        return bool(cancel()) if cancel is not None else False

    completed: list[AnalysisHandle] = []

    def _run(handle: AnalysisHandle, src) -> None:
        if fn is None:
            handle.status = "error"
            handle.error = f"unknown analysis kind: {kind}"
        else:
            try:
                result = fn(src, params)
            except Exception as exc:  # noqa: BLE001 - 单轨失败不影响其余轨
                handle.status = "error"
                handle.error = f"{type(exc).__name__}: {exc}"
            else:
                handle.result = result
                cache.put(handle.cache_key, result)
                handle.status = "done"
        completed.append(handle)

    todo: list[tuple[AnalysisHandle, object]] = []
    for handle, src in zip(handles, items):
        cached = cache.get(handle.cache_key)
        if cached is not None:
            handle.result = cached
            handle.status = "cached"
            completed.append(handle)
        else:
            todo.append((handle, src))

    cancelled = False
    if int(max_concurrency) > 1 and len(todo) > 1:
        with ThreadPoolExecutor(max_workers=int(max_concurrency)) as pool:
            futures = []
            for handle, src in todo:
                if _is_cancelled():
                    cancelled = True
                    break
                futures.append(pool.submit(_run, handle, src))
            for future in futures:
                future.result()
    else:
        for handle, src in todo:
            if _is_cancelled():
                cancelled = True
                break
            _run(handle, src)

    for index, handle in enumerate(completed):
        handle.seq = index
    if cancelled or _is_cancelled():
        for handle in handles:
            if handle.seq < 0:
                handle.status = "cancelled"
    return handles
