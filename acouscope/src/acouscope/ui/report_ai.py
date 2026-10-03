# SPDX-License-Identifier: GPL-3.0-only
"""报告 AI 解读段（T-1104 · C-2/C-3 里程碑 M-C′·MC-1 · L-3 破例）。

职责：给报告提供「点一下 → 后台生成 → 回填面板」的 AI 技术解读——
``build_report_ai_messages`` 纯函数组装消息（元数据 / 技术信息 / 图题摘要），
``ReportAiWorker`` 在后台线程经**公共 AI API**（``interpreter.make_provider``
+ ``provider.chat``，流式与取消内建）取全文，以信号回主线程；本地档可选
懒启动内置引擎（T-1107 MC-3：仅 ``import`` 公共 ``get_runtime()`` /
``llama_models.*``，阻塞只发生在 worker 线程，不改其源码）。

纪律（需求说明 T-1104 §一/§三）：
- 禁自动外发：本模块不主动发起任何调用，仅由主窗槽在用户点按后建 worker；
- 降级不静默：失败 / 取消 / 不可用各有独立信号（``failed`` / ``cancelled``），
  由宿主转 toast，``run()`` 绝不裸抛崩线程；
- 零复用面板私有件（``_InterpretWorker`` / ``_make_provider`` 不 import），
  不触碰 ``ai_interpret.py`` / ``ai/interpreter.py`` / ``ai/prompts.py``；
- 消息模板零第三方产品名 / 零 URL / 零隐私外发路径；
- 本模块零 QDialog / 零 QTimer（QThread 子类唯一），线程收尾归宿主 closeEvent。
"""

from __future__ import annotations

from typing import Iterable, Mapping

from PyQt6.QtCore import QThread, pyqtSignal

from acouscope.ai import interpreter

# 用户消息尾部的固定指令（令书 M-2 给定措辞·纯静态文本）
_INSTRUCTION = "请就上述声学分析结果给出简明技术解读。"

_SYSTEM_PROMPT = (
    "你是声学分析助手。请基于用户提供的分析结果摘要，"
    "给出简明、客观的技术解读；只依据所给信息，不要编造数据。"
)


def _mapping_lines(data: Mapping[str, object] | None) -> list[str]:
    """{键: 值} → "- 键: 值" 行（控制键 "_…" 与空值丢弃·值转 str）。"""
    lines: list[str] = []
    for key, value in dict(data or {}).items():
        name = str(key)
        if name.startswith("_"):
            continue
        text = str(value or "").strip()
        if not text:
            continue
        lines.append(f"- {name}: {text}")
    return lines


def build_report_ai_messages(
    *,
    metadata: Mapping[str, object] | None = None,
    tech_info: Mapping[str, object] | None = None,
    figure_captions: Iterable[str] = (),
) -> list[dict]:
    """组装报告 AI 解读消息（纯函数·零网络·返回 system+user 两条）。

    user 内容 = 元数据行 + 技术信息行 + 图题摘要行 + 固定指令；
    零第三方产品名 / 零 URL（判据 §二-3 静态扫描）。
    """
    blocks: list[str] = ["【声学分析报告摘要】"]

    rows = _mapping_lines(metadata)
    if rows:
        blocks.append("元数据：\n" + "\n".join(rows))

    rows = _mapping_lines(tech_info)
    if rows:
        blocks.append("技术信息：\n" + "\n".join(rows))

    caption_lines = [
        f"- {str(caption).strip()}" for caption in figure_captions if str(caption or "").strip()
    ]
    if caption_lines:
        blocks.append("插图图题：\n" + "\n".join(caption_lines))

    blocks.append(_INSTRUCTION)
    user_content = "\n\n".join(blocks)
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


class ReportAiWorker(QThread):
    """报告 AI 解读后台线程（本模块 QThread 子类唯一·主窗零线程字面量）。

    信号契约（令书 M-2）：``chunk`` 逐段（str）· ``finished_ok`` 全文（str）·
    ``failed`` 可读摘要（str）· ``cancelled`` 取消。四者互斥收尾且至多一发终态，
    ``run()`` 吞掉一切异常转信号，绝不裸抛崩线程。
    """

    chunk = pyqtSignal(str)
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, provider, messages: list[dict], parent=None, *,
                 ensure_runtime: bool = False,
                 runtime_kind: str | None = None,
                 llama_model_id: str | None = None,
                 provider_factory=None) -> None:
        super().__init__(parent)
        self._provider = provider
        self._messages = list(messages)
        self._cancelled = False
        # T-1107 MC-3：本地档懒启动入参（默认值保证 MC-1/MC-2 既有调用零破）
        self._ensure_runtime = bool(ensure_runtime)
        self._runtime_kind = runtime_kind
        self._llama_model_id = llama_model_id
        self._provider_factory = provider_factory

    def cancel(self) -> None:
        """请求取消（置位后 provider 内的 ``is_cancelled`` 轮询生效）。"""
        self._cancelled = True

    def run(self) -> None:  # noqa: D102
        collected: list[str] = []

        def _on_chunk(piece: object) -> None:
            text = str(piece or "")
            if not text:
                return
            collected.append(text)
            self.chunk.emit(text)

        try:
            if self._ensure_runtime:
                # T-1107 MC-3：本地档懒启动内置引擎（镜像 ai_interpret 已验证
                # 路径；阻塞只发生在本 worker 线程，绝不触碰 UI 线程）。
                kind = self._runtime_kind or "ollama"
                try:
                    if kind == "llama_cpp":
                        from acouscope.ai import llama_models
                        from acouscope.ai.llama_runtime import get_runtime
                        models = tuple(llama_models.list_models())
                        info = next(
                            (m for m in models
                             if m.model_id == self._llama_model_id),
                            None)
                        info = info or (models[0] if models else None)
                        if info is None:
                            self.failed.emit(
                                "本地模型尚未就绪。可在「设置-AI」下载本地"
                                "模型后重试，或一键切换远程模型。")
                            return
                        if not llama_models.is_model_ready(info.model_id):
                            self.failed.emit(
                                "本地模型尚未下载。请在「设置-AI」下载本地"
                                "模型后重试，或一键切换远程模型。")
                            return
                        rt = get_runtime()
                        if rt.state != "ready" and not rt.start(
                                llama_models.model_path(info.model_id),
                                timeout=180.0):
                            self.failed.emit(
                                "本地引擎启动失败。可在「设置-AI」重试，"
                                "或一键切换远程模型。")
                            return
                    else:
                        from acouscope.ai.ollama_runtime import get_runtime
                        rt = get_runtime()
                        if rt.state != "ready" and not rt.start(
                                timeout=30.0):
                            self.failed.emit(
                                "本地引擎启动失败。可在「设置-AI」重试下载"
                                "模型，或一键切换远程模型。")
                            return
                except Exception:
                    self.failed.emit(
                        "本地引擎启动失败。可在「设置-AI」重试，"
                        "或一键切换远程模型。")
                    return

            # T-1021 时序：provider 构造早于懒启动，届时运行时未就绪只能落到
            # 默认端口；就绪后（此刻、chat 前）经同一工厂重建，拿到动态端口。
            if self._provider_factory is not None:
                try:
                    self._provider = self._provider_factory()
                except Exception as exc:  # noqa: BLE001
                    self.failed.emit(f"{type(exc).__name__}: {exc}"[:300])
                    return

            text = self._provider.chat(
                self._messages,
                image_b64="",
                on_chunk=_on_chunk,
                is_cancelled=lambda: self._cancelled,
            )
        except interpreter.CancelledError:
            self.cancelled.emit()
            return
        except (
            interpreter.ProviderError,
            interpreter.VisionUnsupportedError,
            interpreter.ConnectionInterruptedError,
        ) as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}"[:300])
            return
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}"[:300])
            return
        full = str(text or "").strip() or "".join(collected)
        self.finished_ok.emit(full)
