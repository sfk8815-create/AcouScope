# SPDX-License-Identifier: GPL-3.0-only
"""波形编辑核心（Audacity 风格，纯 numpy 实现）。

操作对象为单声道 float 数组，选区以 (start_s, end_s) 秒传入，
内部换算采样索引。撤销/重做采用快照栈（限制深度，防长录音内存失控）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


class EditError(Exception):
    """编辑操作失败（如缺少选区、剪贴板为空）。"""


@dataclass
class Clipboard:
    """跨控件共享的音频剪贴板（模块级单例语义）。"""

    data: Optional[np.ndarray] = None
    sample_rate: int = 0

    def put(self, data: np.ndarray, sample_rate: int) -> None:
        self.data = np.asarray(data, dtype=np.float32).copy()
        self.sample_rate = int(sample_rate)

    def get(self, sample_rate: int) -> np.ndarray:
        if self.data is None or len(self.data) == 0:
            raise EditError("clipboard_empty")
        if int(sample_rate) != self.sample_rate and self.sample_rate > 0:
            # 采样率不同：线性重采样（纯 numpy）
            return _resample_linear(self.data, self.sample_rate, int(sample_rate))
        return self.data.copy()

    def has(self) -> bool:
        return self.data is not None and len(self.data) > 0


def _resample_linear(x: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    if sr_from == sr_to or len(x) == 0:
        return x.copy()
    n_out = max(1, int(round(len(x) * sr_to / sr_from)))
    pos = np.arange(n_out, dtype=np.float64) * sr_from / sr_to
    i0 = np.floor(pos).astype(np.int64)
    i0 = np.clip(i0, 0, len(x) - 1)
    i1 = np.clip(i0 + 1, 0, len(x) - 1)
    frac = (pos - i0).astype(np.float32)
    return (x[i0] * (1.0 - frac) + x[i1] * frac).astype(np.float32)


def _sel_indices(sel: Optional[tuple[float, float]], sr: int, n: int,
                 required: bool) -> tuple[int, int]:
    if sel is None or sel[1] <= sel[0]:
        if required:
            raise EditError("need_selection")
        return 0, n
    i0 = max(0, min(int(round(sel[0] * sr)), n))
    i1 = max(i0, min(int(round(sel[1] * sr)), n))
    if required and i1 - i0 < 2:
        raise EditError("need_selection")
    return i0, i1


@dataclass
class _Snapshot:
    data: np.ndarray
    label: str


class EditingController:
    """编辑操作 + 撤销/重做。所有方法返回新的数组（或抛 EditError）。"""

    def __init__(self, history_limit: int = 6):
        self._undo: list[_Snapshot] = []
        self._redo: list[_Snapshot] = []
        self._limit = history_limit
        self.clipboard = Clipboard()

    # -- 状态 --
    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def last_label(self) -> str:
        return self._undo[-1].label if self._undo else ""

    def _push(self, before: np.ndarray, label: str) -> None:
        self._undo.append(_Snapshot(np.asarray(before, dtype=np.float32), label))
        if len(self._undo) > self._limit:
            self._undo.pop(0)
        self._redo.clear()

    def reset(self) -> None:
        self._undo.clear()
        self._redo.clear()

    # -- 操作 --
    def copy(self, data: np.ndarray, sr: int,
             sel: Optional[tuple[float, float]]) -> None:
        x = np.asarray(data, dtype=np.float32)
        i0, i1 = _sel_indices(sel, sr, len(x), required=True)
        self.clipboard.put(x[i0:i1], sr)

    def cut(self, data: np.ndarray, sr: int,
            sel: Optional[tuple[float, float]]) -> np.ndarray:
        x = np.asarray(data, dtype=np.float32)
        i0, i1 = _sel_indices(sel, sr, len(x), required=True)
        self.clipboard.put(x[i0:i1], sr)
        new = np.delete(x, np.s_[i0:i1])
        self._push(x, "cut")
        return new

    def delete(self, data: np.ndarray, sr: int,
               sel: Optional[tuple[float, float]]) -> np.ndarray:
        x = np.asarray(data, dtype=np.float32)
        i0, i1 = _sel_indices(sel, sr, len(x), required=True)
        new = np.delete(x, np.s_[i0:i1])
        self._push(x, "delete")
        return new

    def paste(self, data: np.ndarray, sr: int,
              insert_t: float) -> np.ndarray:
        x = np.asarray(data, dtype=np.float32)
        clip = self.clipboard.get(sr)
        at = int(np.clip(round(insert_t * sr), 0, len(x)))
        new = np.concatenate([x[:at], clip, x[at:]])
        self._push(x, "paste")
        return new

    def silence(self, data: np.ndarray, sr: int,
                sel: Optional[tuple[float, float]]) -> np.ndarray:
        x = np.asarray(data, dtype=np.float32)
        i0, i1 = _sel_indices(sel, sr, len(x), required=True)
        new = x.copy()
        new[i0:i1] = 0.0
        self._push(x, "silence")
        return new

    def trim(self, data: np.ndarray, sr: int,
             sel: Optional[tuple[float, float]]) -> np.ndarray:
        x = np.asarray(data, dtype=np.float32)
        i0, i1 = _sel_indices(sel, sr, len(x), required=True)
        new = x[i0:i1].copy()
        self._push(x, "trim")
        return new

    # -- 撤销/重做 --
    def undo(self, data: np.ndarray, sr: int) -> np.ndarray:
        if not self._undo:
            raise EditError("nothing_to_undo")
        snap = self._undo.pop()
        self._redo.append(_Snapshot(np.asarray(data, dtype=np.float32), snap.label))
        return snap.data.copy()

    def redo(self, data: np.ndarray, sr: int) -> np.ndarray:
        if not self._redo:
            raise EditError("nothing_to_redo")
        snap = self._redo.pop()
        self._undo.append(_Snapshot(np.asarray(data, dtype=np.float32), snap.label))
        return snap.data.copy()
