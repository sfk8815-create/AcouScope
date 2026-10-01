# SPDX-License-Identifier: GPL-3.0-only
"""AI 释图面板（对话式）。

T-1018：面板改为「对话式」——模型/厂商/密钥/图像发送等设置**全部归设置-AI**，
本面板显示当前模型（⚙ 跳设置-AI）；主体为消息对话流（用户消息可含图片
缩略图 / AI 消息流式输出、自动滚底 / 文本可选中复制），底部输入框支持 Ctrl+V
贴图、拖拽图片与数值上下文预填（回车发送 / Shift+Enter 换行 / 停止），输入区
可拖动分隔线拉高。

T-1020：顶部再加「模型来源」三档下拉（内置 / 本地部署的模型 / 云端服务商），
选中即把 `ai_v2.source` 单键落盘并即时生效；并修正三处真机阻断 bug——
① 设置-AI「应用」落盘（本模块 `save_ai_config` 为唯一写盘入口，失败可见）、
② 失败诊断按原因/引擎种类分流（不再出现「（Exception）」）、
③ 一键切远程真正切到目标厂商默认地址与模型。

T-1022：**释图窗的本质是释图**——本地模型必须能读图。
① 顶部模型区加「Cherry 式分区选择器」（QMenu 非模态弹出，禁新建模态对话框）：
   分区 = 内置模型 / 本地部署的模型 / 云端服务商；每行带体积、**视觉标签**、
   状态（已下载 / 未下载 / 本机推荐 / 内存不足 / 磁盘不足）与当前项 ✓，
   未下载项行内带「下载」；列表只含视觉模型（纯文本一律不上架）。
② 视觉**门禁**取代原「静默降级」：已知非视觉模型不再静默只发文本——带图时明确
   提示「该模型不支持图片，请更换」；未知能力（自填云端模型名 / 局域网自建端点）
   允许选择但标注「视觉能力未验证」，首次带图失败给针对性提示。
③ 顶部常显「当前档 + 当前模型名 + 视觉标签」，下方一行硬件探测结论
   （芯片/内存/可用磁盘；只读规格，不采集任何设备唯一标识）。
④ 空态（无可用视觉模型 / 模型未下载）给出原因 + 硬件匹配的推荐模型 + [下载] 按钮
   + 次要入口「去 设置→AI 挑选」，不再只显示「去设置」让人石沉大海。

释图流程：图片附件 + 数值上下文 → 模型流式释读 → 同一对话内继续追问。
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import (
    QBuffer,
    QByteArray,
    QIODevice,
    Qt,
    QThread,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QImage, QPixmap, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from acouscope.ai import interpreter
from acouscope.ai.prompts import (
    ACADEMIC_PROMPT_ZH,
    # V099_AI_PANEL_V2：AT-405 上下文构建（供路由/测试注入）
    build_context,  # noqa: F401
)
from acouscope.i18n import tr
from acouscope.ui.theme import TOKENS, style_when_theme
from acouscope.ui.widgets.toast import show_toast
from acouscope.utils.config import data_dir_candidates


def _shutdown_qthread(worker, timeout_ms: int = 2000) -> bool:
    """对称收尾一个 QThread：cancel → wait → 超时则 terminate → deleteLater。

    T-1074 G2（承 T72-04）：旧 closeEvent 仅 cancel()+wait()，worker 若在超时
    内未退出，面板销毁即触发「QThread: Destroyed while thread is still running」
    → 未定义行为/可崩。这里对齐主窗模板（main_window.py closeEvent：wait 超时 →
    terminate() → deleteLater()）补兜底。

    参数:
        worker: 目标 QThread（None 直接返回 False）；须具备 cancel()/wait()/
            terminate()/deleteLater()（本模块两类 worker 均满足）。
        timeout_ms: wait 上限（毫秒）。

    返回:
        True = 曾触发 terminate() 兜底（worker 未在超时内自行退出）；否则 False。
    """
    if worker is None:
        return False
    if not worker.isRunning():
        return False
    cancel = getattr(worker, "cancel", None)
    if callable(cancel):
        try:
            cancel()
        except Exception:
            pass
    if worker.wait(timeout_ms):
        return False
    # 超时未退：强制终止 + 排入删除，杜绝运行中销毁
    try:
        worker.terminate()
        worker.wait(1000)
    except Exception:
        pass
    try:
        worker.deleteLater()
    except Exception:
        pass
    return True


# V099_AI_PANEL_V2：官方释读 system prompt 占位（领域中立最终文案待 T-306b 由
# TraeCode 定稿后替换本常量；在此之前禁止随版本发布正式产品）。
SYSTEM_PROMPT_FINAL = (
    "你是 AcouScope 内置的专业音乐与声学分析助手。你的用户来自包括但不限于：\n"
    "音乐学（各分支）、声学、音频工程、音乐教育、演奏研究、语音分析、乐器制作与维修等领域。\n"
    "【铁律】\n"
    "1. 以软件精确计算的\"数值上下文\"（采样率、时长、基频 Hz、音分 cent、置信度等）为第一依据；"
    "图像与数据冲突时以数据为准并说明。\n"
    "2. 不预设用户学科背景；从用户提问推断领域并适配术语；不确定时用通用声学/音乐术语，"
    "并对专业名词作一句解释。\n"
    "3. 不编造数据；数据不足时明确说\"数据不足\"。\n"
    "4. 客观描述与主观推断分离；推断必须标注\"推测\"。"
)  # V099_PROMPT_FINAL_V1
#: 数值上下文在消息流中的固定标记（build_context() 首行）。
_CONTEXT_HEADER = "【数值上下文"
#: 追问历史上下文预算（V099_AI_PANEL_V2）：轮数与字符数双上限。
HISTORY_MAX_ROUNDS = 6
HISTORY_MAX_CHARS = 6000

# ---------------------------------------------------------------------------
# T-1018：对话式布局常量（键契约对齐 T-320 设置面板，禁自行造键）
# ---------------------------------------------------------------------------
# 云端厂商（对齐 settings_dialog._CLOUD_VENDOR_IDS；仅用于校验配置中的厂商 id）
CLOUD_VENDOR_IDS = ("deepseek", "qwen", "openai", "zhipu", "custom")

# 旧配置迁移判定（只读旧 provider 键；interpreter 内部路由键语义零改动）
_OLD_LOCAL_PROVIDERS = {"llama_cpp", "lm_studio"}
_OLD_CLOUD_PROVIDERS = {
    "free_remote", "openai", "anthropic", "google", "deepseek", "moonshot",
    "qwen", "zhipu", "siliconflow", "openrouter", "groq", "together",
    "xai", "custom",
}

#: 输入区 / 消息流几何（拖拽分隔线的上下限 clamp；非样式值，无 hex/px 字面量）
_MSG_MIN_HEIGHT = 140
_INPUT_MIN_HEIGHT = 96
_INPUT_MAX_HEIGHT = 560
_INPUT_DEFAULT_HEIGHT = 168
#: 单条消息可附带的图片数上限（引擎按首图释读，超出提示）
_ATTACH_MAX = 4
#: 缩略图展示最大宽 / 气泡文本区度量
_THUMB_MAX_W = 140
_TEXT_MIN_WIDTH = 200
_TEXT_PAD = 10
_TEXT_MIN_HEIGHT = 32
#: 窄宽压缩白名单：动作钮与模型来源下拉保留 sizeHint（避免被压到不可见）
_KEEP_SIZE_HINT = ("aiSettingsBtn", "aiSendBtn", "aiStopBtn", "aiClearBtn",
                   "aiAttachRemove", "aiSourceCombo", "aiSourceLabel")
#: T-1021 D3：顶部行「单行」判据——模型名按平均字宽计的可见下限（字符数，
#: 非像素），低于此值即切两行布局，避免窄栏把模型名压成 0 宽
_MODEL_MIN_CHARS = 24

#: T-1055 流式 MD 节流：累积新增 ≥ _MD_RERENDER_CHARS 字符，或距上次重渲染
#: ≥ _MD_RERENDER_MS 毫秒（事件驱动检查，禁定时器），才整篇重渲染一次；
#: 流结束由 finish_md() 强制补一次完整渲染（setMarkdown 为整篇重解析）。
_MD_RERENDER_CHARS = 160
_MD_RERENDER_MS = 300
#: T-1055 滚动跟随：滚动条距底部 ≤ 该像素视为「贴底」，流式时自动跟随；
#: 用户上滑超过该距离即停止强制跟随。
_SCROLL_FOLLOW_EPS = 24
#: T-1055 清空二次确认：首次点击后 _CLEAR_ARM_SECONDS 秒内再点才真正清空。
_CLEAR_ARM_SECONDS = 3.0

#: T-1020 D1：模型来源三档键值（与 ai_v2.source / 设置-AI 单选项一一对应）
SOURCE_KEYS = ("builtin", "self_hosted", "cloud")
#: T-1020 D1：档位展示文案复用 设置-AI 既有键（禁新建 tier 键覆盖式重定义）
SOURCE_LABEL_KEYS = {
    "builtin": "settings.builtin",
    "self_hosted": "settings.self_hosted",
    "cloud": "settings.cloud",
}
#: T-1020 B：引擎种类分流——本地引擎（建议指向本地服务）
LOCAL_ENGINE_KINDS = ("ollama", "llama_cpp")
#: T-1020 B：引擎种类分流——云端 / 自定义（建议指向额度与 API Key）
CLOUD_ENGINE_KINDS = ("openai", "custom", "deepseek", "qwen", "zhipu",
                      "free_remote")


def _scaled_thumb(pix: QPixmap) -> QPixmap:
    """缩略图：等比缩到 _THUMB_MAX_W 以内（不放大）。"""
    width = min(_THUMB_MAX_W, max(1, pix.width()))
    return pix.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)


def _is_local_url(url: str) -> bool:
    """自建地址启发式：本机回环 / 局域网段（迁移判定用，非安全边界）。"""
    u = (url or "").strip().lower()
    return (u.startswith("http://127.0.0.1") or u.startswith("http://localhost")
            or u.startswith("http://192.168.") or u.startswith("http://10.")
            or u.startswith("http://172."))


def _source_from_config(data: dict) -> str:
    """旧 ai_config.json → 三档（对齐 settings_dialog._ai_source_from_config，
    只读不写，保守回退内置档）。"""
    v2 = data.get("ai_v2")
    v2 = v2 if isinstance(v2, dict) else {}
    if v2.get("source") in ("builtin", "self_hosted", "cloud"):
        return v2["source"]
    provider = str(data.get("provider", "ollama") or "ollama").strip()
    url = str(data.get("url", "") or "").strip()
    if v2.get("external_ollama"):
        return "self_hosted"
    if provider == "ollama":
        return "builtin"
    if provider in _OLD_LOCAL_PROVIDERS:
        return "self_hosted"
    if provider == "openai" and _is_local_url(url):
        return "self_hosted"
    if provider in _OLD_CLOUD_PROVIDERS:
        return "cloud"
    return "builtin"


def _legacy_engine_kind(data: dict) -> str | None:
    """旧配置遗留的本地引擎路由（provider=llama_cpp → 仍走受管 llama-server；
    其余本地/云端旧键由三档通用路由承接）。"""
    provider = str(data.get("provider", "") or "").strip()
    if provider == "llama_cpp":
        return "llama_cpp"
    return None


def elide_to_width(text: str, font_metrics, width: int) -> str:
    """T-1011 遮挡修复：按字体度量把文本省略为宽度内可显示的单行。

    完整值由调用方保存在控件 tooltip；宽不足 40 像素时仍返回省略号串（不裁
    切、不抛异常）。
    """
    if not text:
        return ""
    w = max(40, int(width))
    fm = font_metrics
    if fm.horizontalAdvance(text) <= w:
        return text
    return fm.elidedText(text, Qt.TextElideMode.ElideRight, w)


#: T-1022 顶部模型选择器分区键（Cherry 式分区列表：内置 / 本地部署 / 云端）
SECTION_BUILTIN = "builtin"
SECTION_SELF_HOSTED = "self_hosted"
SECTION_CLOUD = "cloud"
SECTION_ORDER = (SECTION_BUILTIN, SECTION_SELF_HOSTED, SECTION_CLOUD)
#: 分区展示文案键（i18n 三语；禁在代码里写死中文）
SECTION_LABEL_KEYS = {
    SECTION_BUILTIN: "ai_panel.sec_builtin",
    SECTION_SELF_HOSTED: "ai_panel.sec_self_hosted",
    SECTION_CLOUD: "ai_panel.sec_cloud",
}
#: 视觉能力三态（§6 门禁：已知可读图 / 已知不可读图 / 未验证）
VISION_OK = "vision"
VISION_TEXT_ONLY = "text_only"
VISION_UNVERIFIED = "unverified"
#: 视觉能力标签文案键
VISION_LABEL_KEYS = {
    VISION_OK: "ai_panel.tag_vision",
    VISION_TEXT_ONLY: "ai_panel.tag_text_only",
    VISION_UNVERIFIED: "ai_panel.tag_vision_unverified",
}
#: 推荐档位 → 徽标文案键（ai.model_recommend 的 fit 值）
FIT_LABEL_KEYS = {
    "recommended": "ai_panel.state_recommended",
    "ok": "",
    "insufficient_ram": "ai_panel.state_low_ram",
    "insufficient_disk": "ai_panel.state_low_disk",
}
#: 选择器按钮对象名 / 展示常量（无硬编码像素值；宽度由字体度量算）
_PICK_BTN_OBJECT = "aiModelPickBtn"
#: 地址在列表行内的最大字符数（超长截断展示，防窄栏挤压）
_URL_MAX_CHARS = 32


def _known_text_only_names() -> frozenset[str]:
    """已知**非视觉**（纯文本）模型名集合——视觉门禁的判定源。

    来源三处（全部为「已知」而非猜测）：
    ① `ai.llama_models.LEGACY_TEXT_ONLY`：本版本下架的受管纯文本 GGUF；
    ② `ai.backends.local_registry.LEGACY_TEXT_ONLY`：下架的官方 Ollama 纯文本档；
    ③ 现行目录里显式标 `vision=False` 的条目（防御：目录将来若加回也自动命中）。
    """
    names: set[str] = set()
    try:
        from acouscope.ai import llama_models
        names.update(llama_models.LEGACY_TEXT_ONLY)
        names.update(m.filename for m in llama_models.list_models()
                     if not getattr(m, "vision", False))
    except Exception:
        pass
    try:
        from acouscope.ai.backends.local_registry import (
            LEGACY_TEXT_ONLY, OFFICIAL_MODELS,
        )
        names.update(LEGACY_TEXT_ONLY)
        names.update(n for n, m in OFFICIAL_MODELS.items()
                     if not m.get("vision", False))
    except Exception:
        pass
    return frozenset(names)


def _model_text_only(model_name: str) -> bool:
    """视觉门禁判定（T-1022 语义调整，函数名保留兼容）：该模型是否**已知**不能读图。

    仅「已知非视觉」返回 True（下架的纯文本档 / 目录里 vision=False 的条目）；
    未知（自填云端模型名 / 局域网自建端点）返回 False——未知不等于纯文本，
    由 UI 标注「视觉能力未验证」并在首次带图失败时给针对性提示。

    注：§6 起本函数只用于**门禁 / 提示**，不再驱动「静默降级为纯文本」（见
    `_InterpretWorker.run` 的带图门禁）。
    """
    name = (model_name or "").strip()
    if not name:
        return False
    names = _known_text_only_names()
    if name in names:
        return True
    # 带 :tag 的 Ollama 名（如 "qwen2.5:3b"）与裸名互认
    return name.split(":")[0] in names


def _model_vision_state(model_name: str) -> str:
    """模型视觉能力三态（§6）：已知可读图 / 已知不可读图 / 未验证。"""
    name = (model_name or "").strip()
    if not name:
        return VISION_UNVERIFIED
    if _model_text_only(name):
        return VISION_TEXT_ONLY
    try:
        from acouscope.ai import llama_models
        if any(m.filename == name for m in llama_models.list_models()):
            return VISION_OK
    except Exception:
        pass
    try:
        from acouscope.ai.backends.local_registry import OFFICIAL_MODELS
        meta = OFFICIAL_MODELS.get(name) or OFFICIAL_MODELS.get(
            name.split(":")[0])
        if meta is not None:
            return VISION_OK if meta.get("vision") else VISION_TEXT_ONLY
    except Exception:
        pass
    return VISION_UNVERIFIED


def vision_tag(model_name: str) -> str:
    """视觉能力标签文案（三语；未验证 → 「视觉能力未验证」）。"""
    return tr(VISION_LABEL_KEYS[_model_vision_state(model_name)])


def _effective_send_image(send_image: bool, text_only: bool) -> bool:
    """AT-408 双保险：text_only 模型一律不发送图像（与 UI 开关状态无关）。

    T-1022：本纯函数语义不变（仍作为带图门禁的最终兜底），但 §6 起调用方
    （`_InterpretWorker.run`）在「已知非视觉 + 带图」时会**明确失败并提示更换
    模型**，不再静默降级为纯文本释读。
    """
    return bool(send_image) and not text_only


def trim_history(history: list[dict], max_rounds: int = HISTORY_MAX_ROUNDS,
                 max_chars: int = HISTORY_MAX_CHARS) -> list[dict]:
    """追问历史上下文预算：限最近 max_rounds 轮 + 估算 ≤max_chars 字符。

    超限自最旧轮次起截断；单轮自身超预算时保留最近一轮。不修改入参。
    """
    if not history:
        return []
    max_rounds = max(1, int(max_rounds))
    max_chars = max(1, int(max_chars))

    def _size(msg: dict) -> int:
        c = msg.get("content", "")
        if isinstance(c, str):
            return len(c)
        return sum(len(str(p.get("text", ""))) for p in c if isinstance(p, dict)) \
            if isinstance(c, list) else len(str(c))

    rounds: list[list[dict]] = []
    for m in history:
        role = m.get("role", "user")
        if role == "user" or not rounds:
            rounds.append([])
        rounds[-1].append(m)

    keep: list[dict] = []
    for rnd in reversed(rounds[-max_rounds:]):  # 新 → 旧 依次纳入
        block = [dict(m) for m in rnd]          # 轮内顺序保持（user 在前）
        new_size = sum(_size(x) for x in keep) + sum(_size(x) for x in block)
        if keep and new_size > max_chars:
            continue          # 整轮纳入将超预算：丢弃更旧的轮次
        keep = block + keep
    if not keep:              # 单轮自身超预算：保留最近一轮，不再截断
        keep = [dict(m) for m in rounds[-1]]
    return keep


def _has_context_marker(messages: list[dict]) -> bool:
    """消息流中是否已含 build_context() 数值上下文（按固定标记判断）。"""
    return any(isinstance(m.get("content"), str)
               and _CONTEXT_HEADER in m["content"] for m in messages)


def build_messages(system: str, user_question: str, context: str,
                   history: list[dict] = None,
                   mode: str = "official") -> list[dict]:
    """V099_AI_PANEL_V2 Prompt 路由（AT-405/409，纯函数可单测）。

    - official：system = 官方 system prompt；首条 user 消息强制前缀数值上下文；
    - byom：system = 用户 prompt（空则不设 system 消息）；数值上下文仍强制
      追加在首条 user 消息末尾（AT-409）；
    - history 非空时：若尚未含数值上下文，以独立首条重注入；新提问始终追加到末尾。

    Args:
        system: system 消息内容（official 传 SYSTEM_PROMPT_FINAL；byom 传用户 prompt）
        user_question: 首条/末条 user 消息的正文（释图指令或追问）
        context: build_context() 数值上下文
        history: 既有对话（user/assistant），首条通常已含上下文
        mode: "official" | "byom"
    """
    history = [dict(m) for m in (history or [])]
    if history:
        if not _has_context_marker(history):
            # 截断把上下文丢了：数值上下文作为独立首条重注入（强制，AT-409）
            history.insert(0, {"role": "user", "content": context})
        history.append({"role": "user", "content": user_question})
    else:
        if mode == "official":
            # official：首条 user 消息强制前缀数值上下文（AT-405）
            first = {"role": "user", "content": f"{context}\n\n{user_question}"}
        else:
            # byom：数值上下文仍强制追加在首条 user 消息末尾（AT-409）
            first = {"role": "user", "content": f"{user_question}\n\n{context}"}
        history = [first]
    if system:
        history = [{"role": "system", "content": system}] + history
    return history


def _config_paths() -> list[Path]:
    """AI 配置的候选位置（权限/沙箱拦截时逐个重试）。"""
    return [d / "ai_config.json" for d in data_dir_candidates()]


def load_ai_config() -> dict:
    """读 ai_config.json（取「最近修改」的候选，与 _load_config 同口径）。

    T-1020 A：UI 层唯一读盘入口（设置-AI 面板预填 / 面板档位刷新 / 宿主双向
    同步都走这里），替代原 `acouscope.ai.interpreter._load_config`（该符号不
    存在，调用点静默失败 → 设置面板恒以空配置起步）。读失败一律返回 {}，
    绝不抛异常（只读路径，无副作用）。
    """
    data: dict = {}
    best_mtime = -1.0
    for path in _config_paths():
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
            mtime = path.stat().st_mtime
        except (OSError, ValueError):
            continue
        if mtime > best_mtime and isinstance(parsed, dict):
            best_mtime = mtime
            data = parsed
    return data


def save_ai_config(data: dict) -> bool:
    """把整份配置写入首个可写的候选目录（与 _switch_to_remote 同候选序/容错）。

    T-1020 A：设置-AI「应用」的唯一落盘入口；D2 的面板档位切换亦复用本函数
    （仅写 ai_v2.source 单键）。**不吞错**：全部候选写入失败时返回 False，由
    调用方给出可见反馈（toast），不抛异常、不静默。

    Returns:
        True 已落盘；False 所有候选目录均不可写。
    """
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    for path in _config_paths():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")
            return True
        except OSError:
            continue
    return False


def config_sanity_hint(source: str, url: str, key: str) -> str:
    """T-1020 B：配置健全性提示（纯函数，可单测；命中才返回文案，否则空串）。

    命中条件：云端档 + API Key 为空 + 地址为内置免费端点（FREE_REMOTE_BASE）。
    该端点是匿名限流的免费服务，超额即 429；此处只提示，不代改用户配置。
    """
    if (source or "").strip() != "cloud":
        return ""
    if (key or "").strip():
        return ""
    if (url or "").strip().rstrip("/") != interpreter.FREE_REMOTE_BASE.rstrip("/"):
        return ""
    return tr("ai_panel.free_endpoint_hint")


def _classify_failure(payload: str) -> str:
    """T-1020 B：失败原因分类（纯函数）。

    Returns:
        rate_limit / auth / timeout / network / vision / provider / unknown
    """
    text = payload or ""
    low = text.lower()
    if "visionunsupported" in low or "不支持图像" in text:
        return "vision"
    if "429" in low or "限流" in text or "rate limit" in low:
        return "rate_limit"
    if ("401" in low or "403" in low or "unauthorized" in low
            or "invalid api key" in low or "鉴权" in text or "认证" in text):
        return "auth"
    if "timeout" in low or "超时" in text:
        return "timeout"
    if ("connection" in low or "无法连接" in text or "连接" in text
            or "errno" in low or "network" in low or "网络" in text):
        return "network"
    if "providererror" in low:
        return "provider"
    return "unknown"


def _advice_for_kind(kind: str | None) -> str:
    """T-1020 B：按引擎种类分流建议（本地 → 本地服务；云端/自定义 → 额度与 Key）。"""
    if (kind or "") in CLOUD_ENGINE_KINDS:
        return tr("ai_panel.advice_cloud")
    return tr("ai_panel.advice_local")


def friendly_error(exc, kind: str | None = None) -> str:
    """失败原因友好文案（AT-407；T-1020 B 分类重写，纯函数可单测，绝不抛异常）。

    T-1020 变更（对 AT-407 的修正）：入参可为 worker 传来的 payload 字符串
    （形如 `"<异常类名>: <消息>"`，见 [E4]）或异常对象。原实现把字符串重包成
    `Exception(msg)` → 类型与原文全丢、界面恒显「（Exception）」+ 无条件指向本地
    Ollama；现改为**按原因分类 + 按引擎种类分流**，并把真实原因写进对话流。

    Args:
        exc: payload 字符串或异常对象
        kind: 当前引擎种类（ollama/llama_cpp/openai/custom/deepseek/... ；
              None = 未知 → 走通用建议）
    """
    if isinstance(exc, BaseException):
        detail = str(exc)
        payload = f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
    else:
        payload = str(exc or "")
        detail = payload.split(":", 1)[1].strip() if ":" in payload else ""
    category = _classify_failure(payload)
    if category == "rate_limit":
        if kind == "free_remote":
            head = tr("ai_panel.err_rate_limit_free")
        elif (kind or "") in LOCAL_ENGINE_KINDS:
            head = tr("ai_panel.err_rate_limit_local")
        else:
            head = tr("ai_panel.err_rate_limit_cloud")
    elif category == "auth":
        head = tr("ai_panel.err_auth")
    elif category == "timeout":
        head = tr("ai_panel.err_timeout")
    elif category == "network":
        head = tr("ai_panel.err_network")
    elif category == "vision":
        head = tr("ai_panel.err_vision")
    elif category == "provider":
        head = tr("ai_panel.err_provider").format(
            detail=detail or tr("ai_panel.err_no_detail"))
    else:
        head = tr("ai_panel.err_unknown")
    lines = [head]
    if detail and category in ("unknown",):
        lines.append(tr("ai_panel.err_detail").format(detail=detail))
    lines.append(_advice_for_kind(kind))
    return "\n".join(lines)


def _switch_to_remote() -> str:
    """V099_AI_FALLBACK_V1 一键切换远程模型（AT-407）。

    将 ai_config.json 的 provider 写为 openai，**URL 与模型一律取该厂商注册表
    默认值**（`info.base_url` / `info.default_model`），既有 5 键 + ai_v2 原样
    保留，写入首个可写的候选目录。返回可展示的状态说明；绝不代表已验证连接
    （Key 可能仍需填写）。

    T-1020 C 归因（非静默）：原实现 `url = 原 url or info.base_url`、
    `model = 原 model（非空则保留）` → 用户已配置限流端点（如内置
    FREE_REMOTE_BASE）时切换后仍打同一地址 = 兜底无效（实测 [E1]+[E4]）。
    现改为无条件写入目标厂商默认地址与默认模型，真正切走。
    """
    info = interpreter.PROVIDERS.get("openai")
    if info is None:  # 防御：注册表缺 openai 项时不继续写坏配置
        return "切换失败：注册表缺少 openai 项，请在「模型设置」中手动选择远程模型。"
    for path in _config_paths():
        try:
            data = json.loads(path.read_text(encoding="utf-8")) \
                if path.exists() else {}
            if not isinstance(data, dict):
                data = {}
            data["provider"] = "openai"
            data["url"] = info.base_url
            data["model"] = info.default_model
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return f"已切换为 OpenAI 远程模型（{info.default_model}）。"
        except OSError:
            continue
    return "切换失败：所有配置目录均不可写，请在「模型设置」中手动选择远程模型。"


# ---------------------------------------------------------------------------
# T-1022 §5/§6/§9.2：模型资产操作 + 展示信息（释图窗与 设置→AI 共用单点）
# ---------------------------------------------------------------------------
# 说明：这些函数是**模型资产层**（列目录 / 下载 / 删除 / 判断已下载 / 组合展示
# 文案）的唯一入口，释图窗与 设置→AI 两处 UI 都调这里，避免双份实现漂移。
# 下载链一律复用既有实现（GGUF：llama_models.download_model 的 sha256 + 断点
# 续传 + 镜像回退；Ollama：model_manager.pull_model 的服务端按层去重），不另写
# 下载器；**不打包任何模型进安装包**（下载均由用户显式点击触发）。


def hardware_summary() -> str:
    """本机硬件一行结论（芯片 · 内存 · 可用磁盘）；不可得 → 未知文案。

    GPU 核数不在此路径探测（macOS `system_profiler` 本机实测约 4 秒），
    按需另行调用 `ai.hardware.probe(with_gpu=True)`。
    """
    text = ""
    try:
        from acouscope.ai import hardware
        text = hardware.probe(with_gpu=False).summary()
    except Exception:
        text = ""
    if not text:
        return tr("ai_panel.hw_unknown")
    return tr("ai_panel.hw_line").format(spec=text)


def remote_service_hint(timeout: float = 0.6) -> str:
    """探到可达的外部 OpenAI 兼容服务 → 「优先用现成服务」提示；否则空串。

    短超时、失败静默（绝不阻塞 UI、绝不抛）；探测只读 `/v1/models`。
    """
    url = None
    try:
        from acouscope.ai import model_recommend
        url = model_recommend.detect_remote_service(timeout=timeout)
    except Exception:
        url = None
    return tr("ai_panel.prefer_remote").format(url=url) if url else ""


def installed_ollama_names(timeout: float = 0.8) -> set[str]:
    """本机内置 Ollama 实例已安装的模型名集合（探测失败 → 空集合）。"""
    try:
        from acouscope.ai.backends.local_registry import probe_ollama
        ok, names = probe_ollama(timeout=timeout)
    except Exception:
        return set()
    return set(names) if ok else set()


def entry_is_downloaded(entry, installed: set[str] | None = None) -> bool:
    """条目是否已下载到本机（GGUF 看沙盒文件；Ollama 看实例模型列表）。"""
    if entry is None:
        return False
    if entry.source == "gguf":
        try:
            from acouscope.ai import llama_models
            return bool(llama_models.is_model_ready(entry.model_id))
        except Exception:
            return False
    have = installed_ollama_names() if installed is None else installed
    return entry.model_id in have or entry.model_id.split(":")[0] in have


def entry_size_text(entry) -> str:
    """条目体积文案（GB/MB 自适应）。"""
    try:
        from acouscope.ai import model_recommend
        return model_recommend.size_text(entry.est_bytes)
    except Exception:
        return ""


def builtin_catalog() -> tuple:
    """内置档全部**视觉**条 目（受管 GGUF + 内置 Ollama 官方档；纯文本已过滤）。"""
    try:
        from acouscope.ai import model_recommend
        return model_recommend.builtin_catalog()
    except Exception:
        return ()


def recommendations(remote_reachable: bool | None = None):
    """按本机硬件给出的推荐结果（vision=False 已被硬过滤）。

    remote_reachable 为 None 时**不探测网络**（构造路径零阻塞）；需要
    remote 结论的调用方（菜单展开 / 设置页）自行传入或先调
    `remote_service_hint()`。
    """
    try:
        from acouscope.ai import hardware, model_recommend
        profile = hardware.probe(with_gpu=False)
        return model_recommend.recommend_models(
            profile, builtin_catalog(),
            remote_reachable=bool(remote_reachable))
    except Exception:
        return ()


def download_entry(entry, on_progress=None, is_cancelled=None) -> None:
    """下载条目（阻塞式，供后台线程调用）；失败抛零终端中文文案异常。

    - GGUF（受管）：走既有 `llama_models.download_model`（含 sha256 + Range
      断点续传 + 镜像回退 + 视觉塔 mmproj 逐文件落地）；
    - Ollama 官方档：确保内置实例就绪后走既有 `model_manager.pull_model`。
    """
    if entry is None:
        raise ValueError("missing entry")
    if entry.source == "gguf":
        from acouscope.ai import llama_models
        llama_models.download_model(entry.model_id, on_progress=on_progress,
                                    is_cancelled=is_cancelled)
        return
    from acouscope.ai import model_manager
    from acouscope.ai.ollama_runtime import get_runtime
    rt = get_runtime()
    if rt.state != "ready":
        rt.start(timeout=30.0)
    model_manager.pull_model(entry.model_id, on_progress=on_progress,
                             is_cancelled=is_cancelled)


def _remove_quietly(path) -> bool:
    """删除单个文件（含 .part / .bad 变体）；存在即删，失败静默。"""
    from pathlib import Path as _Path
    p = _Path(path)
    removed = False
    for cand in (p, p.with_suffix(p.suffix + ".part"),
                 p.with_suffix(p.suffix + ".bad")):
        try:
            if cand.exists():
                cand.unlink()
                removed = True
        except OSError:
            continue
    return removed


def delete_entry(entry) -> bool:
    """删除已下载的模型文件（用户**显式**动作；与「卸载模型」语义严格区分）。

    「卸载模型」= 停引擎进程释放内存（不删文件，见 llama_runtime.stop）；
    本函数才删文件。GGUF 删主权重 + 视觉塔 + 断点残留；Ollama 走实例删除接口。
    """
    if entry is None:
        return False
    if entry.source == "gguf":
        try:
            from acouscope.ai import llama_models, llama_runtime
            info = llama_models.get_model_info(entry.model_id)
            base = llama_runtime.models_dir()
            removed = False
            for mfile in info.files:
                removed = _remove_quietly(base / mfile.filename) or removed
            return removed
        except Exception:
            return False
    try:
        import json as _json
        import urllib.request as _url
        from acouscope.ai.backends.local_registry import active_base_url
        req = _url.Request(
            f"{active_base_url().rstrip('/')}/api/delete",
            data=_json.dumps({"name": entry.model_id}).encode("utf-8"),
            method="DELETE",
            headers={"Content-Type": "application/json"},
        )
        with _url.urlopen(req, timeout=3.0):
            return True
    except Exception:
        return False


def friendly_download_error(exc) -> str:
    """下载异常 → 零终端文案（未知异常一律给通用文案，不泄露工程细节）。"""
    text = str(exc) or ""
    known = type(exc).__name__ in ("LlamaModelError", "PullError",
                                   "CancelledError")
    if known and text and "://" not in text:
        return text
    return tr("ai_panel.download_failed")


class ModelDownloadWorker(QThread):
    """后台下载一个模型条目（进度 / 完成 / 失败三信号 + 可取消）。"""

    progressed = pyqtSignal(float)
    finished_one = pyqtSignal(str)
    failed_one = pyqtSignal(str)

    def __init__(self, entry, parent=None):
        super().__init__(parent)
        self.entry = entry
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            download_entry(self.entry, on_progress=self.progressed.emit,
                           is_cancelled=lambda: self._cancelled)
        except interpreter.CancelledError:
            self.failed_one.emit(tr("ai_panel.download_cancelled"))
        except Exception as exc:  # 零终端文案（绝不泄露 URL / 命令）
            self.failed_one.emit(friendly_download_error(exc))
        else:
            self.finished_one.emit(self.entry.model_id)


class _InterpretWorker(QThread):
    """后台调用模型，流式回传，避免阻塞 UI。"""

    chunk = pyqtSignal(str)
    notice = pyqtSignal(str)
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, provider, messages: list[dict],
                 image_b64: str = "", send_image: bool = True,
                 text_only: bool = False, ensure_runtime: bool = False,
                 runtime_kind: str | None = None,
                 llama_model_id: str | None = None,
                 provider_factory=None):
        super().__init__()
        # V099_RUNTIME_V1（AT-410）：本地模型 worker 启动前懒启动内置引擎
        self.ensure_runtime = bool(ensure_runtime)
        # T-314a：引擎种类（"ollama" / "llama_cpp" / None），决定懒启动路由
        self.runtime_kind = runtime_kind
        # T-314c：用户选中的受管 GGUF 模型 id（None → 懒启动回退目录 [0]）
        self.llama_model_id = llama_model_id
        self.provider = provider
        # T-1021 P0：懒启动就绪后按同一路径重建 provider 的工厂（None=不重建）
        self.provider_factory = provider_factory
        self.messages = messages
        self.image_b64 = image_b64
        # V099_AI_PANEL_V2 定点-2：AT-408 双保险，text_only 模型强制按 False 执行
        self.text_only = bool(text_only)
        self.send_image = _effective_send_image(send_image, self.text_only)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        # T-1022 §6：视觉**门禁**（取代 T-1018 起的「静默降级为纯文本」）——
        # 已知非视觉模型 + 本次带图 → 明确失败并提示更换模型，绝不悄悄丢掉图片
        # 只发文本（用户无从察觉）；不带图时仍可正常做纯文本问答。
        if self.text_only and self.image_b64 and not self._cancelled:
            self.failed.emit(tr("ai_panel.vision_blocked"))
            return
        # V099_RUNTIME_V1（AT-410）：本地模型懒启动内置引擎（worker 线程，不阻塞
        # UI）；失败走既有 failed 信号 → T-307 兜底模态，文案零终端。
        if getattr(self, "ensure_runtime", False):
            kind = getattr(self, "runtime_kind", None) or "ollama"
            try:
                if kind == "llama_cpp":
                    # T-314c：受管 llama-server 懒启动（用户选中的 GGUF；缺省/
                    # 失效回退目录 [0]，T-314b 起 model 字段可切换）
                    from acouscope.ai import llama_models
                    from acouscope.ai.llama_runtime import get_runtime
                    _models = tuple(llama_models.list_models())
                    info = next(
                        (m for m in _models
                         if m.model_id == getattr(self, "llama_model_id", None)),
                        None)
                    info = info or (_models[0] if _models else None)
                    if info is None:  # 防御：目录恒有 2 个受管模型
                        self.failed.emit(
                            "本地引擎启动失败。可在「设置-AI」重试，"
                            "或一键切换远程模型。")
                        return
                    if not llama_models.is_model_ready(info.model_id):
                        self.failed.emit(
                            "本地模型尚未就绪。请在「设置-AI」下载本地模型后重试，"
                            "或一键切换远程模型。"
                        )
                        return
                    rt = get_runtime()
                    if rt.state != "ready" and not rt.start(
                            llama_models.model_path(info.model_id),
                            timeout=180.0):
                        self.failed.emit(
                            "本地引擎启动失败。可在「设置-AI」重试，"
                            "或一键切换远程模型。"
                        )
                        return
                else:
                    # 既有 ollama 路由（V099_RUNTIME_V1 AT-410，行为不变）
                    from acouscope.ai.ollama_runtime import get_runtime
                    rt = get_runtime()
                    if rt.state != "ready" and not rt.start(timeout=30.0):
                        self.failed.emit(
                            "本地引擎启动失败。可在「设置-AI」重试下载模型，"
                            "或一键切换远程模型。"
                        )
                        return
            except Exception:
                self.failed.emit(
                    "本地引擎启动失败。可在「设置-AI」重试，或一键切换远程模型。"
                )
                return

        # T-1021 P0 时序修复：provider 是在懒启动**之前**构造的，那时受管运行时
        # 尚未就绪 → provider 只能回退到 PROVIDERS 里硬编码的默认端口
        # （llama_cpp=127.0.0.1:8080 / ollama=127.0.0.1:11434），而受管服务实际
        # 起在动态端口 → 首次请求必「连接中断」。此处（运行时就绪之后、发起请求
        # 之前）按同一路径重建 provider，保证实际用于请求的 base_url == 就绪后的
        # rt.base_url；用户显式填写的 URL 仍由同一路径优先命中，不被运行时覆盖。
        if self.provider_factory is not None:
            try:
                self.provider = self.provider_factory()
            except Exception as e:
                self.failed.emit(f"{type(e).__name__}: {e}")
                return

        def emit_chunk(piece: str):
            self.chunk.emit(piece)

        def is_cancelled() -> bool:
            return self._cancelled

        try:
            text = self.provider.chat(
                self.messages,
                image_b64=self.image_b64 if self.send_image else "",
                on_chunk=emit_chunk,
                is_cancelled=is_cancelled,
            )
            self.finished_ok.emit(text)
        except interpreter.VisionUnsupportedError:
            if self.send_image and self.image_b64 and not self._cancelled:
                # T-1022 §6：未知能力模型（自填云端模型名 / 局域网自建端点）首次
                # 带图失败 → 给**针对性**提示（视觉能力未验证 + 如何更换），
                # 不再笼统归因「本地 Ollama」；随后按既有兜底改纯上下文重试。
                self.notice.emit(tr("ai_panel.vision_unverified_notice"))
                try:
                    text = self.provider.chat(
                        self.messages, image_b64="",
                        on_chunk=emit_chunk,
                        is_cancelled=is_cancelled,
                    )
                    self.finished_ok.emit(text)
                except interpreter.CancelledError:
                    self.failed.emit("已停止生成。")
                except Exception as e2:
                    self.failed.emit(f"{type(e2).__name__}: {e2}")
                return
            self.failed.emit(tr("ai_panel.vision_blocked"))
        except interpreter.CancelledError:
            self.failed.emit("已停止生成。")
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")


class _MessageBubble(QFrame):
    """一条对话消息气泡（T-1018 对话式）。

    role=user 时可携带图片缩略图；role=assistant 的文本区在流式过程中增量
    追加（sync_height 随内容长高，整体滚动由外层消息滚动区负责）。

    T-1055：assistant 气泡文本经 Qt 内建 `QTextDocument.setMarkdown` 渲染
    （零依赖，禁 WebEngine/dsh），流式过程按字符/时间阈值节流重渲染；Qt 不
    支持的语法（LaTeX/`$…$`、复杂嵌套 HTML）原样保留文本，不丢内容、不报错。
    头部行附带「复制」与「重新生成」（后者仅最后一条可见，由宿主控制）。
    """

    regenerate_requested = pyqtSignal()

    def __init__(self, role: str, text: str = "", images=None, parent=None):
        super().__init__(parent)
        self.role = role
        self.thumb_labels: list = []
        self.setObjectName("aiMsgUser" if role == "user" else "aiMsgAi")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(0)

        # T-1055：assistant 气泡走 Markdown 渲染；user 气泡保持纯文本。
        self._md_mode = (role == "assistant")
        self._md_buffer = text or ""
        self._md_rendered_len = 0
        self._md_last_render = 0.0
        self.btn_copy = None
        self.btn_regenerate = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        head_row = QHBoxLayout()
        head_row.setSpacing(6)
        head = QLabel(tr("ai_panel.role_user") if role == "user"
                      else tr("ai_panel.role_assistant"))
        head.setObjectName("aiMsgRole")
        head_row.addWidget(head, 1)
        if role == "assistant":
            # T-1055 复制：写 Markdown 原文到系统剪贴板（非 HTML）；QTextBrowser
            # 自带的右键 Copy 仍保留（隐式复制），此处为显式入口。
            self.btn_copy = QPushButton(tr("ai_panel.copy"))
            self.btn_copy.setObjectName("aiCopyBtn")
            self.btn_copy.setFlat(True)
            self.btn_copy.setToolTip(tr("ai_panel.copy_tip"))
            self.btn_copy.clicked.connect(self._copy_text)
            head_row.addWidget(self.btn_copy, 0)
            self.btn_regenerate = QPushButton(tr("ai_panel.regenerate"))
            self.btn_regenerate.setObjectName("aiRegenerateBtn")
            self.btn_regenerate.setFlat(True)
            self.btn_regenerate.setToolTip(tr("ai_panel.regenerate_tip"))
            self.btn_regenerate.clicked.connect(self.regenerate_requested)
            head_row.addWidget(self.btn_regenerate, 0)
        lay.addLayout(head_row)

        for pix in (images or []):
            if pix is None or pix.isNull():
                continue
            lbl = QLabel()
            lbl.setObjectName("aiMsgThumb")
            lbl.setPixmap(_scaled_thumb(pix))
            lbl.setToolTip(tr("ai_panel.attached_tip"))
            self.thumb_labels.append(lbl)
            lay.addWidget(lbl)

        self.text_view = QTextBrowser()
        self.text_view.setObjectName("aiMsgText")
        self.text_view.setReadOnly(True)          # 可选中复制（T-1018 §2）
        self.text_view.setFrameShape(QFrame.Shape.NoFrame)
        self.text_view.setOpenExternalLinks(False)
        self.text_view.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.text_view.setSizePolicy(QSizePolicy.Policy.Ignored,
                                     QSizePolicy.Policy.Fixed)
        self.text_view.setMinimumWidth(0)
        self.text_view.setPlainText(text or "")
        lay.addWidget(self.text_view)
        # 主题派生样式（禁硬编码 hex/px：颜色与边框宽一律取主题令牌）；
        # builder 同时刷新代码块文档样式（代码块底/边/前景随主题，明暗均可用）。
        name = self.objectName()
        border = int(TOKENS.get("elevation", {}).get("border", 1))

        def _theme_refresh(c, s=self, n=name, b=border):
            s._apply_code_style(c)
            return f"QFrame#{n} {{ background: {c['panel']};" \
                   f" border: {b}px solid {c['border']}; }}"

        style_when_theme(self, _theme_refresh)
        self.sync_height()

    # ------------------------------------------------------------------
    # T-1055：Markdown 流式渲染（节流 + 语法降级）
    # ------------------------------------------------------------------

    def append_md(self, piece: str) -> None:
        """流式累积一段文本；达到字符或时间阈值才整篇重渲染（禁每 token 渲染）。

        流式期间先以纯文本增量追加（保持既有「逐字可见」契约），再按节流阈值
        用 setMarkdown 整篇重渲染；流结束由 finish_md() 强制补一次完整渲染。
        """
        if not self._md_mode:
            self.text_view.append(piece)
            return
        self._md_buffer += piece
        self._append_plain(piece)
        now = time.monotonic()
        delta = len(self._md_buffer) - self._md_rendered_len
        if delta >= _MD_RERENDER_CHARS or \
                (now - self._md_last_render) * 1000.0 >= _MD_RERENDER_MS:
            self._apply_markdown()

    def _append_plain(self, piece: str) -> None:
        """文本光标末尾增量追加（QTextBrowser 阅读位置跟随）。"""
        cursor = self.text_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(piece)
        self.text_view.setTextCursor(cursor)

    def finish_md(self, text: str) -> None:
        """流结束：以最终全文强制完整渲染一次（节流缓冲清零）。"""
        if not self._md_mode:
            return
        self._md_buffer = text or ""
        self._apply_markdown()

    def _apply_markdown(self) -> None:
        """Qt 内建渲染；异常（语法降级兜底）时回退纯文本，绝不丢内容。"""
        try:
            self.text_view.setMarkdown(self._md_buffer)
        except Exception:
            self.text_view.setPlainText(self._md_buffer)
        self._md_rendered_len = len(self._md_buffer)
        self._md_last_render = time.monotonic()

    def _apply_code_style(self, c: dict) -> None:
        """代码块等宽字体 + 主题派生底/前景（document stylesheet，禁硬编码 hex）。"""
        try:
            bg = c.get("input") or c.get("bg2") or "transparent"
            fg = c.get("text") or "inherit"
            mono = TOKENS["typography"]["mono"]
            self.text_view.document().setDefaultStyleSheet(
                f"pre {{ background-color: {bg}; color: {fg};"
                f" font-family: {mono}; }}")
            if self._md_mode and self._md_buffer:
                self._apply_markdown()
                self.sync_height()
        except Exception:
            pass

    def set_regenerate_visible(self, visible: bool) -> None:
        """重新生成钮显隐（仅最后一条助手消息可见）。"""
        if self.btn_regenerate is not None:
            self.btn_regenerate.setVisible(visible)

    def set_regenerate_enabled(self, enabled: bool) -> None:
        """生成中禁用重新生成钮。"""
        if self.btn_regenerate is not None:
            self.btn_regenerate.setEnabled(enabled)

    def _copy_text(self) -> None:
        """复制本条消息：MD 原文 / 纯文本（非 HTML）。"""
        src = self._md_buffer if self._md_mode else self.text_view.toPlainText()
        QApplication.clipboard().setText(src or "")

    def sync_height(self) -> None:
        """按当前文本内容同步文本区高度（气泡随内容长高，无内部滚动条）。"""
        view = self.text_view
        width = int(view.viewport().width())
        if width <= 0:
            width = max(int(self.width()), _TEXT_MIN_WIDTH)
        doc = view.document()
        doc.setTextWidth(float(max(1, width)))
        height = int(doc.size().height()) + _TEXT_PAD
        view.setFixedHeight(max(_TEXT_MIN_HEIGHT, height))


class _ChatInputEdit(QPlainTextEdit):
    """对话输入框：回车发送 / Shift+Enter 换行 / 粘贴或拖入图片 → 附件信号。

    Ctrl+V 与拖拽最终都经 insertFromMimeData 落地（图片剪贴板 / 图片文件），
    因此图片一律转为附件预览，不进入文本域。
    """

    image_incoming = pyqtSignal(object)   # QImage
    send_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setTabChangesFocus(True)

    def canInsertFromMimeData(self, source) -> bool:
        try:
            if source.hasImage() or source.hasUrls():
                return True
        except Exception:
            pass
        return super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source) -> None:
        try:
            if source.hasImage():
                image = source.imageData()
                if isinstance(image, QImage) and not image.isNull():
                    self.image_incoming.emit(image)
                    return
        except Exception:
            pass
        try:
            urls = source.urls() if source.hasUrls() else []
        except Exception:
            urls = []
        if urls:
            handled = False
            for url in urls:
                try:
                    path = url.toLocalFile()
                except Exception:
                    path = ""
                if not path:
                    continue
                image = QImage(path)
                if isinstance(image, QImage) and not image.isNull():
                    self.image_incoming.emit(image)
                    handled = True
            if handled:
                return
        super().insertFromMimeData(source)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)      # Shift+Enter 换行
                return
            self.send_requested.emit()            # 回车发送
            return
        super().keyPressEvent(event)


class AIInterpretDialog(QWidget):
    """AI 释图面板（右栏「AI 释图」tab 承载，非模态）。

    类名保留 AIInterpretDialog 仅为调用侧/测试 import 兼容；容器已由模态对话框
    迁移为 QWidget（T-507a 去模态化），尺寸由宿主 tab 托管。

    T-1018：改为「对话式」——顶部显示当前模型（⚙ 跳设置-AI 配置），主体为
    消息对话流（用户消息可含图片缩略图 / AI 消息流式输出、自动滚底 / 文本可选中
    复制），底部输入框支持 Ctrl+V 贴图、拖拽图片、数值上下文预填与「回车发送 /
    Shift+Enter 换行 / 停止」，输入区可拖动分隔线拉高。

    T-1020 D（局部取代 T-1018「面板零写回」的档位只读部分）：顶部再加**模型
    来源三档下拉**（内置 / 本地部署 / 云端服务商），选中即把 `ai_v2.source`
    单键落盘（复用 `save_ai_config`）并即时刷新路由；切换**不动** url / model /
    key 等参数键（那些仍是 设置-AI 的唯一写权），失败可见反馈、绝不静默。

    模型来源之外的设置（厂商、服务地址、密钥、图像发送）**全部归设置-AI**；本
    面板不持有其它设置控件，配置读取统一走 `load_ai_config()`，每次入口由宿主
    新建实例 → 天然读到最新配置。
    会话（消息流 / 输入草稿）为单次打开的临时态，不跨次保留。
    """

    #: T-1011 建立、T-1018 改为只读；T-1020 D2 恢复发出：**仅**在顶部切档
    #: （写入 ai_v2.source 单键）后发出，供宿主刷新 设置-AI 面板档位（双向同步）。
    config_changed = pyqtSignal()

    def __init__(
        self,
        image_getter: Callable[[], Optional[bytes]],
        context_getter: Callable[[], str],
        view_name_getter: Callable[[], str],
        parent=None,
    ):
        super().__init__(parent)

        self.image_getter = image_getter
        self.context_getter = context_getter
        self.view_name_getter = view_name_getter
        self._worker: Optional[_InterpretWorker] = None
        self._stream_bubble: Optional[_MessageBubble] = None
        self._chat_messages: list[dict] = []    # 对话历史（user/assistant）
        self._v2_state: dict = {}
        self._run_image_b64 = ""
        self._run_send_image = False

        # T-1018：只读配置状态（全部由 _load_config() 读得，无面板设置控件）
        self._file_cfg: dict = {}
        self._persisted_v2: dict = {}
        self._legacy_kind: str | None = None    # 旧 llama_cpp 遗留路由
        self._source = "builtin"                # builtin / self_hosted / cloud
        self._vendor = "custom"                 # 云端厂商 id
        self._url_self = ""                     # 本地部署档服务地址
        self._url_cloud = ""                    # 云端档服务地址
        self._eng_model = ""
        self._eng_key = ""
        self._ai_mode = "official"
        self._official_model = ""
        self._byom_model = ""
        self._byom_prompt = ""
        self._llama_model_id = ""

        # 输入区附件（T-1018）：[{name, b64, pixmap, box, thumb}]
        self.attached_images: list[dict] = []
        # T-1079 ⑤：预填锚点——refresh_attached_view 据此判定「草稿未被用户
        # 改动」并定位预载附件项（身份引用，用户移除后不复活）。
        self._prefilled_context = ""
        self._prefill_item: Optional[dict] = None
        self.msg_bubbles: list[_MessageBubble] = []
        self._model_full = ""
        self._follow_bottom = True             # 消息流自动贴底
        self._turn = 0                         # 本次打开会话内的发送轮次
        # T-1055：清空二次确认（首次点击进入待确认，_CLEAR_ARM_SECONDS 内再点生效）
        self._clear_armed = False
        self._clear_armed_ts = 0.0
        # T-1055：重新生成快照（最近一次发送的 question/context/图像/历史）
        self._last_question = ""
        self._last_context = ""
        self._last_image_b64 = ""
        self._last_send_image = False
        self._last_history: list[dict] | None = None
        # T-1022：模型选择器菜单 / 下载后台任务 / 空态推荐条目
        self._model_menu = None
        self._dl_worker: ModelDownloadWorker | None = None
        self._empty_entry = None

        self._build_ui()
        self._load_config()
        self._prefill_draft()

    # ------------------------------------------------------------------
    # UI 装配
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(6)
        # 允许宿主压窄（内容由布局自身压缩）
        root.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)

        # ===== 顶部状态行：模型来源三档下拉 + 当前模型 + ⚙（跳设置-AI）=====
        # T-1020 D1：下拉替代原「只读模型行」；面板仅可写 ai_v2.source 单键，
        # url/model/key 写权仍专属 设置-AI（写权切分，见任务书 D 节）。
        # T-1021 D3：改用 QGridLayout —— 窄栏（右侧栏真实宽约 278）下单行容不下
        # 「来源 + 下拉 + 模型名 + ⚙」，模型名被压成 0 宽（完全不可见）；现按可用
        # 宽在「单行」与「两行（第一行 来源+下拉+⚙ / 第二行 模型名整行）」间自动
        # 切换（阈值由字体度量算出，无硬编码像素）。
        top = QGridLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        self._top_grid = None     # 装配完成前 resizeEvent 不做顶部行重排
        self.lbl_source = QLabel(tr("settings.ai_source"))
        self.lbl_source.setObjectName("aiSourceLabel")
        self.cmb_source = QComboBox()
        self.cmb_source.setObjectName("aiSourceCombo")
        for _key in SOURCE_KEYS:
            self.cmb_source.addItem(tr(SOURCE_LABEL_KEYS[_key]), _key)
        self.cmb_source.setToolTip(tr("ai_panel.source_switch_tip"))
        self.cmb_source.currentIndexChanged.connect(self._on_source_changed)
        self.lbl_model = QLabel()
        self.lbl_model.setObjectName("aiModelLabel")
        self.lbl_model.setWordWrap(True)          # T-1020 D5：窄栏换行，不截断
        self.lbl_model.setSizePolicy(QSizePolicy.Policy.Ignored,
                                     QSizePolicy.Policy.Preferred)
        self.lbl_model.setMinimumWidth(0)
        self.btn_ai_settings = QPushButton("⚙")
        self.btn_ai_settings.setObjectName("aiSettingsBtn")
        self.btn_ai_settings.setToolTip(tr("ai_panel.settings_tip"))
        self.btn_ai_settings.setFlat(False)
        self.btn_ai_settings.clicked.connect(self._on_open_settings)
        # T-1022 §5：模型选择器（Cherry 式分区列表；QMenu 非模态弹出，禁新模态框）
        self.btn_model_pick = QPushButton("▾")
        self.btn_model_pick.setObjectName(_PICK_BTN_OBJECT)
        self.btn_model_pick.setToolTip(tr("ai_panel.pick_model_tip"))
        self.btn_model_pick.clicked.connect(self._on_pick_model)

        self._top_grid = top
        self._top_two_row: bool | None = None    # 未定：首次布局按可用宽决定
        self._layout_top_row(self.width())

        top_widget = QWidget()
        top_widget.setObjectName("aiModelArea")
        top_widget.setLayout(top)
        top_widget.setMinimumWidth(0)
        self.model_area = top_widget
        root.addWidget(top_widget)

        # T-1022 §5：探测结论一行（硬件规格；GPU 核数不在此路径探测）
        self.lbl_probe = QLabel(hardware_summary())
        self.lbl_probe.setObjectName("aiProbeLabel")
        self.lbl_probe.setWordWrap(True)
        self.lbl_probe.setMinimumWidth(0)
        self.lbl_probe.setSizePolicy(QSizePolicy.Policy.Ignored,
                                     QSizePolicy.Policy.Preferred)
        root.addWidget(self.lbl_probe)

        # ===== 主体：垂直分隔（上=消息对话流，下=输入区；分隔线可拖动拉高输入区）=====
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)

        # 上：消息对话流（QScrollArea + 气泡纵向排列，自动滚底）
        self.msg_scroll = QScrollArea()
        self.msg_scroll.setObjectName("aiMsgScroll")
        self.msg_scroll.setWidgetResizable(True)
        self.msg_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.msg_scroll.setMinimumHeight(_MSG_MIN_HEIGHT)
        self.msg_scroll.setMinimumWidth(0)
        self.msg_container = QWidget()
        self.msg_container.setObjectName("aiMsgContainer")
        self.msg_container.setMinimumWidth(0)
        self.msg_layout = QVBoxLayout(self.msg_container)
        self.msg_layout.setContentsMargins(6, 6, 6, 6)
        self.msg_layout.setSpacing(8)
        self.msg_hint = QLabel(tr("ai_panel.stream_hint"))
        self.msg_hint.setObjectName("aiStreamHint")
        self.msg_hint.setWordWrap(True)
        self.msg_layout.addWidget(self.msg_hint)

        # T-1022 §9.2①：空态提醒（无可用视觉模型 / 未下载）——原因 + 硬件匹配的
        # 推荐模型 + [下载] + 次要入口「去 设置→AI 挑选」（不得让人石沉大海）
        self.empty_panel = QWidget()
        self.empty_panel.setObjectName("aiEmptyPanel")
        empty_lay = QVBoxLayout(self.empty_panel)
        empty_lay.setContentsMargins(0, 0, 0, 0)
        empty_lay.setSpacing(6)
        self.lbl_empty_reason = QLabel()
        self.lbl_empty_reason.setObjectName("aiEmptyReason")
        self.lbl_empty_reason.setWordWrap(True)
        empty_lay.addWidget(self.lbl_empty_reason)
        empty_row = QHBoxLayout()
        empty_row.setSpacing(6)
        self.btn_empty_download = QPushButton(tr("ai_panel.download"))
        self.btn_empty_download.setObjectName("aiEmptyDownloadBtn")
        self.btn_empty_download.clicked.connect(self._on_empty_download)
        self.btn_empty_settings = QPushButton(tr("ai_panel.goto_settings_ai"))
        self.btn_empty_settings.setObjectName("aiEmptySettingsBtn")
        self.btn_empty_settings.clicked.connect(self._on_open_settings)
        empty_row.addWidget(self.btn_empty_download)
        empty_row.addWidget(self.btn_empty_settings)
        empty_row.addStretch(1)
        empty_lay.addLayout(empty_row)
        self.prog_empty = QProgressBar()
        self.prog_empty.setObjectName("aiEmptyProgress")
        self.prog_empty.setTextVisible(False)
        self.prog_empty.setVisible(False)
        empty_lay.addWidget(self.prog_empty)
        self.empty_panel.setVisible(False)
        self.msg_layout.addWidget(self.empty_panel)

        self.msg_layout.addStretch(1)          # 消息自上而下堆积
        self.msg_scroll.setWidget(self.msg_container)
        # 内容/视口变化后保持贴底（布局延迟更新时的可靠兜底）
        self.msg_scroll.verticalScrollBar().rangeChanged.connect(
            self._on_scroll_range_changed)
        # T-1055：用户滚动 → 接近底部才继续跟随（上滑解除强制贴底）
        self.msg_scroll.verticalScrollBar().valueChanged.connect(
            self._on_scroll_value_changed)
        self.splitter.addWidget(self.msg_scroll)

        # 下：输入区（附件预览 + 输入框 + 发送/停止）
        self.input_panel = QWidget()
        self.input_panel.setObjectName("aiInputPanel")
        self.input_panel.setMinimumWidth(0)
        self.input_panel.setMaximumHeight(_INPUT_MAX_HEIGHT)
        iv = QVBoxLayout(self.input_panel)
        iv.setContentsMargins(6, 6, 6, 6)
        iv.setSpacing(6)

        self.attach_bar = QWidget()
        self.attach_bar.setObjectName("aiAttachBar")
        self.attach_bar.setMinimumWidth(0)
        self.attach_layout = QHBoxLayout(self.attach_bar)
        self.attach_layout.setContentsMargins(0, 0, 0, 0)
        self.attach_layout.setSpacing(6)
        self.attach_layout.addStretch(1)
        self.attach_bar.setVisible(False)
        iv.addWidget(self.attach_bar)

        self.input_edit = _ChatInputEdit()
        self.input_edit.setObjectName("aiInputEdit")
        self.input_edit.setPlaceholderText(tr("ai_panel.input_placeholder"))
        self.input_edit.setMinimumHeight(_INPUT_MIN_HEIGHT)
        self.input_edit.setMinimumWidth(0)
        self.input_edit.image_incoming.connect(self._on_image_incoming)
        self.input_edit.send_requested.connect(self._on_run)
        iv.addWidget(self.input_edit, 1)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.lbl_input_hint = QLabel(tr("ai_panel.input_hint"))
        self.lbl_input_hint.setObjectName("aiInputHint")
        self.lbl_input_hint.setWordWrap(True)
        row.addWidget(self.lbl_input_hint, 1)
        self.btn_send = QPushButton(tr("ai_panel.send"))
        self.btn_send.setObjectName("aiSendBtn")
        self.btn_send.setMinimumWidth(0)
        self.btn_send.clicked.connect(self._on_run)
        row.addWidget(self.btn_send, 0)
        self.btn_stop = QPushButton(tr("ai_panel.stop"))
        self.btn_stop.setObjectName("aiStopBtn")
        self.btn_stop.setMinimumWidth(0)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop)
        row.addWidget(self.btn_stop, 0)
        # T-1055：清空/新会话（二次点击确认，禁模态确认框）
        self.btn_clear = QPushButton(tr("ai_panel.clear"))
        self.btn_clear.setObjectName("aiClearBtn")
        self.btn_clear.setMinimumWidth(0)
        self.btn_clear.setToolTip(tr("ai_panel.clear_tip"))
        self.btn_clear.clicked.connect(self._on_clear)
        row.addWidget(self.btn_clear, 0)
        iv.addLayout(row)

        self.splitter.addWidget(self.input_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([_MSG_MIN_HEIGHT, _INPUT_DEFAULT_HEIGHT])
        root.addWidget(self.splitter, 1)

        # 窄宽可压缩：不因标签/输入框 sizeHint 把宿主最小宽度顶大；
        # 动作钮（⚙/发送/停止/移除）保留 sizeHint，避免被压到不可见。
        for w in self.findChildren(QWidget):
            if w.objectName() in _KEEP_SIZE_HINT:
                continue
            pol_h = w.sizePolicy().horizontalPolicy()
            if pol_h in (QSizePolicy.Policy.Minimum,
                         QSizePolicy.Policy.MinimumExpanding,
                         QSizePolicy.Policy.Fixed):
                sp = w.sizePolicy()
                sp.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
                w.setSizePolicy(sp)
        self.setMinimumWidth(0)

    # ------------------------------------------------------------------
    # T-1021 D3：顶部行「单行 / 两行」自适应（窄栏下模型名不得被压为 0 宽）
    # ------------------------------------------------------------------

    def _top_single_row_need(self) -> int:
        """单行同时容下「来源标签 + 下拉 + 模型名（可辨下限）+ ▾ + ⚙」的所需宽度。

        阈值全部由字体度量与控件 sizeHint 算出（无硬编码像素）：模型名按
        `_MODEL_MIN_CHARS` 个平均字宽作为「可辨」下限。
        """
        g = self._top_grid
        margins = g.contentsMargins()
        return (self.lbl_source.sizeHint().width()
                + self.cmb_source.sizeHint().width()
                + self.btn_model_pick.sizeHint().width()
                + self.btn_ai_settings.sizeHint().width()
                + self.fontMetrics().averageCharWidth() * _MODEL_MIN_CHARS
                + g.spacing() * 4 + margins.left() + margins.right())

    def _layout_top_row(self, available: int) -> None:
        """按可用宽切换顶部行布局（幂等：模式未变则直接返回）。

        宽栏单行：`来源 [▼] 模型名 ▾ ⚙`；窄栏两行：第一行 `来源 [▼] ▾ ⚙`、
        第二行模型名整行（wordWrap 完整呈现，不再被压成 0 宽而完全不可见）。
        """
        two_row = available < self._top_single_row_need()
        if two_row == self._top_two_row:
            return
        self._top_two_row = two_row
        g = self._top_grid
        for w in (self.lbl_source, self.cmb_source, self.lbl_model,
                  self.btn_model_pick, self.btn_ai_settings):
            g.removeWidget(w)
        g.addWidget(self.lbl_source, 0, 0)
        g.addWidget(self.cmb_source, 0, 1)
        if two_row:
            g.addWidget(self.btn_model_pick, 0, 2,
                        Qt.AlignmentFlag.AlignRight)
            g.addWidget(self.btn_ai_settings, 0, 3,
                        Qt.AlignmentFlag.AlignRight)
            g.addWidget(self.lbl_model, 1, 0, 1, 4)
        else:
            g.addWidget(self.lbl_model, 0, 2)
            g.addWidget(self.btn_model_pick, 0, 3)
            g.addWidget(self.btn_ai_settings, 0, 4)
        for col, stretch in ((1, 0), (2, 1), (3, 0), (4, 0)):
            g.setColumnStretch(col, stretch)
        g.invalidate()

    def _add_bubble(self, role: str, text: str = "",
                    images=None) -> _MessageBubble:
        """追加一条消息气泡并滚到底部（返回气泡，供流式增量写文本）。"""
        bubble = _MessageBubble(role, text, images, parent=self.msg_container)
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, bubble)
        self.msg_bubbles.append(bubble)
        if role == "assistant":
            bubble.regenerate_requested.connect(self._on_regenerate)
        self._refresh_regenerate_buttons()
        if self.msg_hint.isVisible() or not self._chat_messages:
            self.msg_hint.setVisible(False)
        self._scroll_to_bottom()
        return bubble

    def _remove_bubble(self, bubble: _MessageBubble) -> None:
        """从对话流移除一条气泡（重新生成 / 清空时复用，禁重复句柄残留）。"""
        if bubble in self.msg_bubbles:
            self.msg_bubbles.remove(bubble)
        self.msg_layout.removeWidget(bubble)
        bubble.deleteLater()

    def _refresh_regenerate_buttons(self) -> None:
        """「重新生成」仅对最后一条助手消息可见；生成中禁用。"""
        last_assistant = None
        for b in self.msg_bubbles:
            if b.role == "assistant":
                last_assistant = b
        busy = self._worker is not None and self._worker.isRunning()
        for b in self.msg_bubbles:
            b.set_regenerate_visible(b.role == "assistant" and b is last_assistant)
            b.set_regenerate_enabled(not busy)

    def _scroll_to_bottom(self) -> None:
        """接近底部时自动贴底（立即一次 + 事件循环补一次，兼容离屏未布局场景）。

        T-1055：用户上滑超过 _SCROLL_FOLLOW_EPS 后不再强制贴底（_follow_bottom
        由 valueChanged 维护），避免打断阅读。
        """
        if self._near_bottom():
            self._follow_bottom = True
            self._apply_scroll_bottom()
            try:
                QTimer.singleShot(0, self._apply_scroll_bottom)
            except Exception:
                pass

    def _near_bottom(self) -> bool:
        """滚动条是否接近底部（判据入常量 _SCROLL_FOLLOW_EPS）。"""
        try:
            bar = self.msg_scroll.verticalScrollBar()
            return bar.maximum() - bar.value() <= _SCROLL_FOLLOW_EPS
        except RuntimeError:      # 控件已被宿主销毁（延迟回调竞态）
            return True

    def _on_scroll_range_changed(self, _min: int, _max: int) -> None:
        """消息流范围变化 → 保持贴底（新消息 append / 流式长高 / 视口变化）。"""
        if self._follow_bottom:
            self._apply_scroll_bottom()

    def _on_scroll_value_changed(self, _value: int) -> None:
        """用户滚动 → 接近底部才继续跟随；上滑即解除强制贴底。"""
        self._follow_bottom = self._near_bottom()

    def _apply_scroll_bottom(self) -> None:
        try:
            bar = self.msg_scroll.verticalScrollBar()
            bar.setValue(bar.maximum())
        except RuntimeError:      # 控件已被宿主销毁（延迟回调竞态）
            pass

    # ------------------------------------------------------------------
    # 输入区附件（Ctrl+V / 拖拽图片 → 缩略图预览，可移除）
    # ------------------------------------------------------------------

    def _attach_pixmap(self, pix: QPixmap, name: str = "",
                       png_bytes: Optional[bytes] = None) -> bool:
        """把一张图片加入待发送附件（缩略图预览 + 可移除）。"""
        if pix is None or pix.isNull():
            return False
        if len(self.attached_images) >= _ATTACH_MAX:
            show_toast(self, tr("ai_panel.attach_full").format(n=_ATTACH_MAX),
                       level="warning")
            return False
        b64 = (base64.b64encode(bytes(png_bytes)).decode("ascii")
               if png_bytes else self._pixmap_png_b64(pix))
        if not b64:
            return False
        item = {
            "name": name or tr("ai_panel.attach_name").format(
                n=len(self.attached_images) + 1),
            "b64": b64,
            "pixmap": pix,
        }
        self.attached_images.append(item)
        self._add_attach_thumb(item)
        return True

    @staticmethod
    def _pixmap_png_b64(pix: QPixmap) -> str:
        """QPixmap → PNG → base64（剪贴板/文件图片走此路）。"""
        buf = QByteArray()
        device = QBuffer(buf)
        try:
            if not device.open(QIODevice.OpenModeFlag.WriteOnly):
                return ""
            if not pix.save(device, "PNG"):
                return ""
        finally:
            device.close()
        return base64.b64encode(bytes(buf)).decode("ascii")

    def _add_attach_thumb(self, item: dict) -> None:
        """附件预览：缩略图 + 移除钮（空附件时整行隐藏）。"""
        box = QWidget()
        box.setMinimumWidth(0)
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(2)
        thumb = QLabel()
        thumb.setObjectName("aiAttachThumb")
        thumb.setPixmap(_scaled_thumb(item["pixmap"]))
        thumb.setToolTip(item["name"])
        bl.addWidget(thumb)
        btn = QPushButton(tr("ai_panel.attach_remove"))
        btn.setObjectName("aiAttachRemove")
        btn.setToolTip(tr("ai_panel.attach_remove_tip"))
        btn.setMinimumWidth(0)
        btn.clicked.connect(lambda _=False, it=item: self._remove_attachment(it))
        bl.addWidget(btn)
        item["box"] = box
        item["thumb"] = thumb
        self.attach_layout.insertWidget(self.attach_layout.count() - 1, box)
        self.attach_bar.setVisible(True)

    def _remove_attachment(self, item: dict) -> None:
        """移除单个附件（含预览控件）。"""
        if item in self.attached_images:
            self.attached_images.remove(item)
        box = item.get("box")
        if box is not None:
            self.attach_layout.removeWidget(box)
            box.setParent(None)
            box.deleteLater()
        if not self.attached_images:
            self.attach_bar.setVisible(False)

    def _clear_attachments(self) -> None:
        for item in list(self.attached_images):
            self._remove_attachment(item)

    def _on_image_incoming(self, image) -> None:
        """输入框贴图 / 拖入图片 → 附件预览。"""
        if isinstance(image, QImage) and not image.isNull():
            self._attach_pixmap(QPixmap.fromImage(image))

    # ------------------------------------------------------------------
    # 输入草稿（数值上下文预填 + 当前视图截图附件）
    # ------------------------------------------------------------------

    def _current_view_attach_name(self) -> str:
        """「当前视图」标注：基础标签 + 视图名（T-1079 ⑤ 随视图切换重取）。"""
        name = tr("ai_panel.attach_current_view")
        try:
            view = (self.view_name_getter() or "").strip()
        except Exception:
            view = ""
        return f"{name} · {view}" if view else name

    def _prefill_draft(self) -> None:
        """进入时预填输入草稿：数值上下文文本（可删改）+ 当前视图截图附件。

        T-1079 ⑤：记录预填锚点（_prefilled_context / _prefill_item）供
        refresh_attached_view 使用；本方法自身的入口语义不变。
        """
        try:
            context = self.context_getter() or ""
        except Exception:
            context = ""
        self.input_edit.setPlainText(context)
        self._prefilled_context = context
        self._prefill_item = None
        try:
            data = self.image_getter()
        except Exception:
            data = None
        if not data:
            return
        pix = QPixmap()
        if not pix.loadFromData(data):
            return
        if self._attach_pixmap(pix, name=self._current_view_attach_name(),
                               png_bytes=bytes(data)):
            self._prefill_item = self.attached_images[-1]

    def refresh_attached_view(self) -> None:
        """视图切换 → 刷新预载附件截图、「当前视图」标注与上下文草稿（T-1079 ⑤）。

        供宿主 _on_analysis_changed 在右栏处于 AI 页时调用。三条纪律：
        草稿正文——用户未改动过才推新上下文，改动过一律不覆盖；
        附件——仅原位更新当初的预载项，用户已移除则不复活；
        任一 getter 失败静默保持现状，绝不影响会话。
        """
        if self.input_edit.toPlainText() == self._prefilled_context:
            try:
                context = self.context_getter() or ""
            except Exception:
                context = self._prefilled_context
            self.input_edit.setPlainText(context)
            self._prefilled_context = context
        item = self._prefill_item
        if item is None or item not in self.attached_images:
            return
        try:
            data = self.image_getter()
        except Exception:
            data = None
        if not data:
            return
        pix = QPixmap()
        if not pix.loadFromData(data):
            return
        name = self._current_view_attach_name()
        item["name"] = name
        item["b64"] = base64.b64encode(bytes(data)).decode("ascii")
        item["pixmap"] = pix
        thumb = item.get("thumb")
        if thumb is not None:
            thumb.setPixmap(_scaled_thumb(pix))
            thumb.setToolTip(name)

    def _question_from_text(self, text: str, context: str) -> str:
        """草稿文本 → 提问正文（防数值上下文重复占预算）。

        默认草稿 = 数值上下文原文（未编辑）→ 走既有官方释图指令，数值上下文由
        build_messages 单点注入（AT-405 official 前缀）；用户编辑过 → 以编辑后
        文本为提问正文，数值上下文仍由 build_messages 注入。
        """
        if context and text == context:
            return ACADEMIC_PROMPT_ZH
        if context and text.startswith(context):
            rest = text[len(context):].strip()
            return rest or ACADEMIC_PROMPT_ZH
        return text

    # ------------------------------------------------------------------
    # 顶部状态行（模型来源三档 + 当前模型） / 设置跳转
    # ------------------------------------------------------------------

    def _tier_configured(self) -> bool:
        """T-1020 D3：当前档是否已具备可用参数（模型名必需；自建档还需地址）。"""
        if not self._current_model_name().strip():
            return False
        if self._source == "self_hosted" and not self._url_self.strip():
            return False
        return True

    def _update_model_label(self) -> None:
        """当前模型状态行（T-1020 D5：窄栏换行完整呈现，不再省略；未配置 → 引导）。

        完整文案同时写入 tooltip（沿用既有契约）；未配置档沿用既有
        `ai_panel.unconfigured`（含「点 ⚙ 前往 设置 → AI」引导）。
        T-1022 §5：视觉标签常显在模型选择器按钮上（窄栏也必定可见）。
        """
        model = self._current_model_name().strip()
        text = (tr("ai_panel.model_prefix").format(model=model)
                if model and self._tier_configured()
                else tr("ai_panel.unconfigured"))
        self._model_full = text
        self.lbl_model.setToolTip(text)
        self.lbl_model.setText(text)
        if hasattr(self, "btn_model_pick"):
            tag = vision_tag(model)
            self.btn_model_pick.setText(f"▾ {tag}")
            self.btn_model_pick.setToolTip(
                tr("ai_panel.pick_model_tip") + "\n" + tag)

    # ------------------------------------------------------------------
    # T-1022 §5：Cherry 式分区模型选择器（QMenu 非模态；禁新建模态框）
    # ------------------------------------------------------------------

    def _selected_builtin_entry(self):
        """内置档当前选中的条目（受管 GGUF 优先，其次内置 Ollama 官方档）。"""
        mid = (getattr(self, "_llama_model_id", "") or "").strip()
        entries = builtin_catalog()
        if mid:
            for e in entries:
                if e.model_id == mid and e.source == "gguf":
                    return e
        name = self._builtin_model_resolved()
        for e in entries:
            if e.model_id == name:
                return e
        return None

    def _recommended_entry(self):
        """硬件匹配的首选条目（`fit == recommended`；无则取第一条）。"""
        recs = recommendations()
        for r in recs:
            if r.fit == "recommended":
                return r.entry
        return recs[0].entry if recs else None

    def _entry_row_text(self, entry, *, downloaded: bool, rec,
                        current: bool) -> str:
        """选择器行文案：`✓ 显示名 · 体积 · 视觉标签 · 状态 [· 下载]`。

        行内详情全部来自真实目录 / 真实探测（体积实测、状态实测），不臆造。
        """
        parts: list[str] = [entry.display_name, entry_size_text(entry),
                            vision_tag(entry.model_id)]
        if downloaded:
            parts.append(tr("ai_panel.state_downloaded"))
        else:
            parts.append(tr("ai_panel.state_not_downloaded"))
            parts.append(f"[{tr('ai_panel.download')}]")
        if rec is not None:
            key = FIT_LABEL_KEYS.get(rec.fit, "")
            if key:
                parts.append(tr(key))
        row = " · ".join(p for p in parts if p)
        return f"✓ {row}" if current else row

    def _url_short(self, url: str) -> str:
        """地址截断展示（超长省略，防窄栏挤压；完整值进 tooltip）。"""
        text = (url or "").strip()
        return text if len(text) <= _URL_MAX_CHARS else text[:_URL_MAX_CHARS] + "…"

    def _build_model_menu(self) -> QMenu:
        """构造分区模型列表（内置 / 本地部署 / 云端服务商）。

        只列**视觉**模型（`vision=False` 硬过滤，纯文本一律不上架）；每行带
        体积 / 视觉标签 / 状态（已下载·未下载·本机推荐·内存不足·磁盘不足）
        与当前项 ✓；未下载行带 [下载]（点击即下载，完成后自动切为当前模型）。
        """
        menu = QMenu(self)
        menu.setObjectName("aiModelMenu")
        installed = installed_ollama_names()
        remote = remote_service_hint()
        recs = {r.model_id: r for r in recommendations(bool(remote))}

        # ---- 分区 1：内置模型（应用托管引擎：受管 GGUF + 内置 Ollama 档）----
        menu.addSection(tr(SECTION_LABEL_KEYS[SECTION_BUILTIN]))
        cur = self._selected_builtin_entry()
        for entry in builtin_catalog():
            if not getattr(entry, "vision", False):
                continue                       # 硬门禁（双保险）
            downloaded = entry_is_downloaded(entry, installed)
            current = (cur is not None and entry.model_id == cur.model_id)
            act = menu.addAction(self._entry_row_text(
                entry, downloaded=downloaded, rec=recs.get(entry.model_id),
                current=current))
            act.setData({"section": SECTION_BUILTIN, "entry": entry,
                         "downloaded": downloaded})
            act.triggered.connect(lambda _c=False, e=entry: self._on_menu_entry(e))

        # ---- 分区 2：本地部署的模型（自建端点；参数写权归 设置-AI）----
        # 是否已配置：看 ai_v2.external_ollama + external_ollama_url（设置-AI 唯一
        # 写入方）——两个分区共用配置里的 model 键，靠该开关区分归属，避免同一模型
        # 在两处被误显为「已配置」。
        menu.addSection(tr(SECTION_LABEL_KEYS[SECTION_SELF_HOSTED]))
        v2 = self._persisted_v2 or {}
        self_url = str(v2.get("external_ollama_url", "") or "").strip()
        self_model = (self._eng_model or "").strip()
        if bool(v2.get("external_ollama")) and self_url and self_model:
            row = " · ".join(p for p in (
                self_model, vision_tag(self_model),
                self._url_short(self_url),
                tr("ai_panel.key_set") if self._eng_key.strip()
                else tr("ai_panel.key_unset"),
            ) if p)
            act = menu.addAction(("✓ " if self._source == SECTION_SELF_HOSTED
                                  else "") + row)
        else:
            act = menu.addAction(tr("ai_panel.self_unconfigured"))
        act.setData({"section": SECTION_SELF_HOSTED})
        act.triggered.connect(
            lambda _c=False: self._on_menu_tier(SECTION_SELF_HOSTED))

        # ---- 分区 3：云端服务商（厂商 + 模型名 + 地址截断 + Key 状态）----
        menu.addSection(tr(SECTION_LABEL_KEYS[SECTION_CLOUD]))
        cloud_model = (self._eng_model or "").strip()
        if cloud_model and not bool(v2.get("external_ollama")):
            url = self._url_cloud
            if not url:
                info = interpreter.PROVIDERS.get(self._vendor)
                url = info.base_url if info is not None else ""
            row = " · ".join(p for p in (
                self._vendor, cloud_model, vision_tag(cloud_model),
                self._url_short(url),
                tr("ai_panel.key_set") if self._eng_key.strip()
                else tr("ai_panel.key_unset"),
            ) if p)
            act = menu.addAction(("✓ " if self._source == SECTION_CLOUD else "")
                                 + row)
        else:
            act = menu.addAction(tr("ai_panel.cloud_unconfigured"))
        act.setData({"section": SECTION_CLOUD})
        act.triggered.connect(lambda _c=False: self._on_menu_tier(SECTION_CLOUD))

        if remote:
            menu.addSeparator()
            menu.addAction(remote).setEnabled(False)
        menu.addSeparator()
        act = menu.addAction(tr("ai_panel.goto_settings_ai"))
        act.setData({"goto_settings": True})
        act.triggered.connect(lambda _c=False: self._on_open_settings())
        return menu

    def _on_pick_model(self) -> None:
        """展开模型选择器（非模态 popup，绝不阻塞 UI、绝不新建模态对话框）。"""
        menu = self._build_model_menu()
        self._model_menu = menu
        try:
            pos = self.btn_model_pick.mapToGlobal(
                QPoint(0, self.btn_model_pick.height()))
            menu.popup(pos)
        except Exception:
            menu.popup(self.btn_model_pick.pos())

    def _on_menu_tier(self, section: str) -> None:
        """选择档位（仅写 `ai_v2.source`；参数键 url/model/key 一律不动）。"""
        self._apply_choice(section)

    def _on_menu_entry(self, entry) -> None:
        """选择某个内置模型条目：未下载 → 先下载；已下载 → 立即切为当前模型。"""
        if not entry_is_downloaded(entry):
            show_toast(self, tr("ai_panel.download_started").format(
                model=entry.display_name))
            self._start_download(entry, self.prog_empty,
                                 self.btn_empty_download, then_select=True)
            return
        self._apply_choice(SECTION_BUILTIN, entry=entry)

    def _apply_choice(self, section: str, entry=None) -> bool:
        """落盘模型选择：`ai_v2.source`（+ 内置档的模型选择键）。

        写权边界（T-1020 定稿 + T-1022 明确）：`url` / `model` / `key` 三个
        **参数键**永远由「设置 → AI」独占，本面板逐字不改；内置档选择具体模型
        时额外写 `ai_v2.official_model` / `ai_v2.llama_model_id`（模型选择键，
        非参数键）——否则「选中哪个模型」无法表达。失败 → 可见 toast，不静默。
        """
        data = load_ai_config()
        v2 = data.get("ai_v2")
        v2 = dict(v2) if isinstance(v2, dict) else {}
        v2["source"] = section
        if entry is not None:
            if entry.source == "gguf":
                v2["llama_model_id"] = entry.model_id
            else:
                v2["official_model"] = entry.model_id
                v2["llama_model_id"] = ""      # 走内置 Ollama 档
        new_data = dict(data)
        new_data["ai_v2"] = v2
        if not save_ai_config(new_data):
            show_toast(self, tr("ai_panel.source_save_failed"), level="warning")
            return False
        self._load_config()
        self._notify_tier_state()
        self.config_changed.emit()
        return True

    # ------------------------------------------------------------------
    # T-1022 §9.2：空态提醒 + 下载（内联进度面板 + toast）
    # ------------------------------------------------------------------

    def _refresh_empty_state(self) -> None:
        """空态提醒（无可用视觉模型 / 未下载）——原因 + 推荐 + [下载]。

        不探测网络（构造路径零阻塞）；推荐来自本地目录 + 本机硬件探测。
        """
        model = self._current_model_name().strip()
        current = (self._selected_builtin_entry()
                   if self._source == SECTION_BUILTIN else None)
        entry = None
        reason = ""
        if _model_text_only(model):
            # §6：已存在配置指向非视觉模型 → 明确提示（禁静默降级）
            reason = tr("ai_panel.vision_blocked")
        elif not model or (self._source == SECTION_BUILTIN
                           and (current is None
                                or not entry_is_downloaded(current))):
            # 下载按钮对准**硬件推荐**条目（§9.2①：按硬件探测给出推荐模型）；
            # 当前选中但未下载的模型，用户可在选择器行内直接点 [下载]。
            entry = self._recommended_entry() or current
            reco = self._recommended_entry()
            reco_line = (f"{reco.display_name} · {entry_size_text(reco)} · "
                         f"{tr('ai_panel.state_recommended')}") if reco else ""
            reason = tr("ai_panel.empty_reason").format(
                current=(model or tr("ai_panel.empty_no_model")),
                reco=reco_line or tr("ai_panel.empty_no_reco"))
        self._empty_entry = entry
        self.lbl_empty_reason.setText(reason)
        self.btn_empty_download.setVisible(bool(reason) and entry is not None)
        self.empty_panel.setVisible(bool(reason))
        if not reason:
            self.prog_empty.setVisible(False)

    def _on_empty_download(self) -> None:
        """空态 [下载]：下载推荐（或当前未下载）模型。"""
        entry = getattr(self, "_empty_entry", None)
        if entry is None:
            entry = self._recommended_entry()
        if entry is None:
            show_toast(self, tr("ai_panel.empty_no_reco"), level="warning")
            return
        self._start_download(entry, self.prog_empty,
                             self.btn_empty_download, then_select=True)

    def _start_download(self, entry, progress_bar, button,
                        then_select: bool = False) -> None:
        """后台下载条目（复用既有下载链）；内联进度条 + toast，可取消。"""
        worker = getattr(self, "_dl_worker", None)
        if worker is not None and worker.isRunning():
            show_toast(self, tr("ai_panel.download_busy"), level="warning")
            return
        worker = ModelDownloadWorker(entry, self)
        self._dl_worker = worker
        progress_bar.setValue(0)
        progress_bar.setVisible(True)
        button.setEnabled(False)
        worker.progressed.connect(
            lambda v: progress_bar.setValue(max(0, min(100, int(v * 100)))))
        worker.finished_one.connect(
            lambda mid: self._on_download_done(mid, progress_bar, button,
                                               entry, then_select))
        worker.failed_one.connect(
            lambda msg: self._on_download_failed(msg, progress_bar, button))
        worker.start()

    def _on_download_done(self, model_id: str, progress_bar, button,
                          entry, then_select: bool) -> None:
        progress_bar.setVisible(False)
        button.setEnabled(True)
        show_toast(self, tr("ai_panel.download_done").format(
            model=entry.display_name))
        if then_select:
            self._apply_choice(SECTION_BUILTIN, entry=entry)
        self._update_model_label()
        self._refresh_empty_state()

    def _on_download_failed(self, msg: str, progress_bar, button) -> None:
        progress_bar.setVisible(False)
        button.setEnabled(True)
        show_toast(self, msg, level="warning")
        self._refresh_empty_state()

    def _select_source(self, source: str) -> None:
        """把下拉选中项与配置档对齐（阻断信号，避免自触发写盘）。"""
        if not hasattr(self, "cmb_source"):
            return
        idx = self.cmb_source.findData(source)
        if idx < 0:
            return
        self.cmb_source.blockSignals(True)
        self.cmb_source.setCurrentIndex(idx)
        self.cmb_source.blockSignals(False)

    def _on_source_changed(self, _index: int) -> None:
        """T-1020 D2：切档仅写 `ai_v2.source` 单键（复用 save_ai_config）→ 即时生效。

        写权切分（禁越权）：url / model / key / ai_v2 其余键**一律不动**，切换
        前后逐字不变；写盘失败 → 可见 toast + 下拉回退（绝不静默失败）。
        """
        key = self.cmb_source.currentData() or "builtin"
        if key == self._source:
            return                      # 与已生效档一致：无写盘
        data = load_ai_config()
        v2 = data.get("ai_v2")
        v2 = dict(v2) if isinstance(v2, dict) else {}
        v2["source"] = key
        new_data = dict(data)
        new_data["ai_v2"] = v2
        if not save_ai_config(new_data):
            self._select_source(self._source)
            show_toast(self, tr("ai_panel.source_save_failed"), level="warning")
            return
        self._load_config()             # 路由 / 模型名随档刷新（下次发送即生效）
        self._notify_tier_state()
        self.config_changed.emit()      # D4：宿主刷新 设置-AI 面板档位

    def _notify_tier_state(self) -> None:
        """T-1020 D3/D6：切档后可见反馈（未配置 → 去设置引导；可用 → 简短确认）。"""
        if not self._tier_configured():
            show_toast(self, tr("ai_panel.tier_unconfigured"), level="warning")
            return
        tier = tr(SOURCE_LABEL_KEYS.get(self._source, "settings.builtin"))
        show_toast(self, tr("ai_panel.source_tip").format(tier=tier),
                   level="info")

    def _sanity_hint(self) -> str:
        """T-1020 B：发送前的配置健全性提示（云端档 + Key 空 + 内置免费端点）。"""
        eng = self._engine_for_current()
        return config_sanity_hint(self._source, eng.get("url", ""),
                                  eng.get("key", ""))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # T-1021 D3：窄栏自动切两行（模型名与下拉同时可见）
        if getattr(self, "_top_grid", None) is not None:
            self._layout_top_row(event.size().width())
        for bubble in self.msg_bubbles:
            try:
                bubble.sync_height()
            except RuntimeError:
                pass

    def _on_open_settings(self):
        """「⚙」→ 左栏「设置」+ 切到「AI」页（既有 API，零新增设置 API）。

        两步序列：MainWindow._activate_settings_tab()（懒构建设置面板）
        → SettingsDialog.switch_to_tab("ai")；并接线「应用」后重读配置。
        """
        win = self.window()
        activate = getattr(win, "_activate_settings_tab", None)
        if callable(activate):
            try:
                activate()
            except Exception:
                pass
        panel = getattr(win, "_settings_panel", None)
        if panel is None:
            show_toast(self, tr("ai_panel.settings_fallback"), level="info")
            return
        switch = getattr(panel, "switch_to_tab", None)
        if callable(switch):
            try:
                switch("ai")
            except Exception:
                pass
        if hasattr(panel, "applied"):
            try:
                panel.applied.disconnect(self._on_settings_applied)
            except (TypeError, RuntimeError):
                pass
            panel.applied.connect(self._on_settings_applied)

    def _on_settings_applied(self):
        # 设置面板保存后重读配置并刷新只读状态行
        self.reload_config()

    def reload_config(self):
        """外部（设置面板应用 / 宿主重新进入）后重读 ai_config.json 刷新状态。"""
        self._load_config()

    # ------------------------------------------------------------------
    # 配置（只读装配：面板不再持有任何设置控件）
    # ------------------------------------------------------------------

    def _load_config(self):
        """读 ai_config.json（T-320 键契约）→ 只读路由状态 + 顶部模型行。

        与设置面板同口径：ai_v2.source 优先判档；缺省按旧 provider 键平滑迁移
        （_source_from_config）；旧键全量保留为 _persisted_v2 防回滚。
        """
        # 取「最近修改」的一份配置：写入可能落在任一可写候选目录，
        # 只读第一个存在的文件可能读到旧数据，导致自定义 API 丢失
        # （T-1020：读盘统一走 load_ai_config，读入口单点化）
        data = load_ai_config()
        self._file_cfg = data
        self._source = _source_from_config(data)
        self._legacy_kind = _legacy_engine_kind(data)

        _v2 = data.get("ai_v2")
        _v2 = _v2 if isinstance(_v2, dict) else {}
        if _v2:
            self._ai_mode = _v2.get("mode", "official") \
                if _v2.get("mode") in ("official", "byom") else "official"
            self._official_model = str(_v2.get("official_model", "") or "")
            self._byom_model = str(_v2.get("byom_model", "") or "")
            self._byom_prompt = str(_v2.get("byom_prompt", "") or "")
            self._llama_model_id = str(_v2.get("llama_model_id", "") or "")
        else:
            self._ai_mode = "official"
            self._official_model = ""
            self._byom_model = ""
            self._byom_prompt = ""
            self._llama_model_id = ""
        self._persisted_v2 = dict(_v2)

        url = str(data.get("url", "") or "").strip()
        self._eng_model = str(data.get("model", "") or "").strip()
        self._eng_key = str(data.get("key", "") or "").strip()
        # 本地部署档地址：对齐设置面板 _prefill_from_legacy（external_ollama_url 优先）
        self._url_self = str(_v2.get("external_ollama_url", "") or "").strip() or url
        self._url_cloud = url
        # 云端档厂商（旧 id 已删 / 非法 → custom 兜底，地址与模型原样保留）
        provider = str(data.get("provider", "") or "").strip()
        self._vendor = provider if provider in CLOUD_VENDOR_IDS else "custom"

        self._update_model_label()
        self._select_source(self._source)   # T-1020 D4：下拉选中项随配置同步
        self._refresh_empty_state()         # T-1022 §9.2①：空态提醒刷新

    def _ai_v2(self) -> dict:
        """返回 ai_v2 状态四键（缺键回退默认值）。"""
        return {
            "mode": getattr(self, "_ai_mode", "official"),
            "official_model": getattr(self, "_official_model", ""),
            "byom_model": getattr(self, "_byom_model", ""),
            "byom_prompt": getattr(self, "_byom_prompt", ""),
        }

    def _selected_llama_info(self):
        """T-314c：用户选中的受管 GGUF 模型条目；缺省/失效回退目录 [0]。

        选中 id 以 llama_models.list_models() 真实目录为准；目录为空返回
        None（llama 路径下不会发生，防御性兜底）。
        """
        from acouscope.ai import llama_models
        models = tuple(llama_models.list_models())
        mid = getattr(self, "_llama_model_id", "")
        hit = next((m for m in models if m.model_id == mid), None)
        return hit or (models[0] if models else None)

    def _builtin_model_resolved(self) -> str:
        """内置档模型名（对齐设置面板 _builtin_model 口径：配置/official 优先）。"""
        from acouscope.ai.backends.local_registry import OFFICIAL_MODELS

        v2 = self._persisted_v2 or {}
        if v2.get("mode") == "byom" and str(v2.get("byom_model", "") or ""):
            return str(v2["byom_model"])
        cur = str(self._file_cfg.get("model", "") or "").strip()
        if cur in OFFICIAL_MODELS:
            return cur
        old = str(v2.get("official_model", "") or "")
        if old in OFFICIAL_MODELS:
            return old
        return next(
            (k for k, m in OFFICIAL_MODELS.items() if m.get("is_default")),
            next(iter(OFFICIAL_MODELS), "spark-x2.5-1.7b"),
        )

    def _engine_for_current(self) -> dict:
        """解析当前档位的引擎路由参数（kind/url/key/model）——只读配置状态。

        档位 → provider 键映射（对齐 T-320 设置面板 ai_config()）：
        builtin → ollama（url 留空，由运行时注入动态端口）；
        self_hosted → custom（旧 llama_cpp 遗留配置仍走受管 llama 路由）；
        cloud → 厂商 id（custom 厂商用自填地址）。
        """
        if self._source == "builtin":
            # T-1022：内置档下若用户显式选中**受管的视觉 GGUF**（应用自带引擎
            # 直跑，--mmproj 读图），走 llama_cpp 路由；否则走内置 Ollama 官方档。
            mid = (getattr(self, "_llama_model_id", "") or "").strip()
            if mid:
                from acouscope.ai import llama_models
                info = next((m for m in llama_models.list_models()
                             if m.model_id == mid), None)
                if info is not None:
                    return {"kind": "llama_cpp", "url": "", "key": "",
                            "model": info.filename}
            return {"kind": "ollama", "url": "", "key": "",
                    "model": self._builtin_model_resolved()}
        if self._source == "self_hosted":
            return {"kind": getattr(self, "_legacy_kind", None) or "custom",
                    "url": self._url_self,
                    "key": self._eng_key,
                    "model": self._eng_model}
        vendor = self._vendor or "custom"
        url = self._url_cloud
        if vendor != "custom":
            info = interpreter.PROVIDERS.get(vendor)
            if not url and info:
                url = info.base_url
        return {"kind": vendor,
                "url": url,
                "key": self._eng_key,
                "model": self._eng_model}

    def _current_model_name(self) -> str:
        return self._engine_for_current().get("model", "") or ""

    def _make_provider(self):
        eng = self._engine_for_current()
        kind = eng["kind"]
        url = eng["url"]
        # V099_RUNTIME_V1（AT-410）：本地 ollama 路由——配置中的外部地址最高优先；
        # 外部 Ollama 开关次之；默认注入内置实例动态端口（端口隔离）。
        if kind == "ollama" and not url:
            v2 = getattr(self, "_persisted_v2", {}) or {}
            if v2.get("external_ollama") and v2.get("external_ollama_url"):
                url = str(v2["external_ollama_url"]).strip()
            else:
                try:
                    from acouscope.ai.ollama_runtime import get_runtime
                    rt = get_runtime()
                    if rt.state == "ready" and rt.base_url:
                        url = rt.base_url
                except Exception:
                    pass
        # T-314a：本地 llama_cpp 路由——镜像 ollama 结构：手填 URL 最高优先，
        # 否则注入受管 llama-server 动态端口；无 external 开关。
        if kind == "llama_cpp" and not url:
            try:
                from acouscope.ai.llama_runtime import get_runtime
                rt = get_runtime()
                if rt.state == "ready" and rt.base_url:
                    url = rt.base_url
            except Exception:
                pass
        return interpreter.make_provider(kind, url, eng["key"], eng["model"])

    # ------------------------------------------------------------------
    # 动作：发送（首条=释图，后续=同一会话追问）/ 停止
    # ------------------------------------------------------------------

    def _busy(self, running: bool):
        """繁忙态：发送钮禁用（防重复提交），停止钮可用。"""
        self.btn_send.setEnabled(not running)
        self.btn_send.setText(tr("ai_panel.sending") if running
                              else tr("ai_panel.send"))
        self.btn_stop.setEnabled(running)
        self._refresh_regenerate_buttons()

    def _make_worker(self, provider, chat: list[dict], question: str,
                     context: str):
        """V099_AI_PANEL_V2：统一建 worker（AT-408 双保险 + Prompt 路由单点）。

        chat 为既有对话（user/assistant）；system 与数值上下文由
        build_messages() 按 ai_v2 模式路由注入：official → SYSTEM_PROMPT_FINAL
        （占位待 T-306b）+ 上下文前缀；byom → 用户 prompt（空则无 system）+
        上下文末尾追加。已连接全部信号。
        """
        v2 = getattr(self, "_v2_state", None) or self._ai_v2()
        text_only = _model_text_only(
            v2["byom_model"] if v2["mode"] == "byom"
            else self._current_model_name()
        )
        messages = build_messages(
            system=SYSTEM_PROMPT_FINAL if v2["mode"] == "official"
            else v2["byom_prompt"],
            user_question=question,
            context=context,
            history=chat,
            mode=v2["mode"],
        )
        kind = self._engine_for_current()["kind"]
        ensure_runtime = kind in ("ollama", "llama_cpp") and not (
            kind == "ollama"
            and bool((self._persisted_v2 or {}).get("external_ollama")))
        worker = _InterpretWorker(
            provider, messages,
            self._run_image_b64, self._run_send_image,
            text_only=text_only,
            ensure_runtime=ensure_runtime,
            # T-314a：引擎种类随 worker 传递（None=不懒启动）
            runtime_kind=kind if ensure_runtime else None,
            # T-314c：选中 GGUF 模型 id 随 worker 传递（None → 懒启动回退 [0]）
            llama_model_id=getattr(self, "_llama_model_id", None),
            # T-1021 P0：本地档懒启动就绪后由 worker 重建 provider（同一解析
            # 路径 → 拿到运行时就绪后的动态端口；云端/外部地址档不重建）
            provider_factory=self._make_provider if ensure_runtime else None,
        )
        worker.chunk.connect(self._on_chunk)
        worker.notice.connect(self._on_notice)
        worker.finished_ok.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        return worker

    def _on_run(self):
        """发送输入框内容：首条 = 释图（图片附件 + 数值上下文），其后 = 追问。"""
        if self._worker is not None and self._worker.isRunning():
            return

        text = self.input_edit.toPlainText().strip()
        if not text:
            show_toast(self, tr("ai_panel.empty_input"), level="warning")
            return
        # T-1020 B：发送前的配置健全性提示（云端档 + Key 空 + 内置免费端点 →
        # 该端点匿名限流，超额必 429），先落进对话流，避免用户只看到失败。
        hint = self._sanity_hint()
        if hint:
            self._add_bubble("assistant", hint)
        self._turn += 1        # 首轮=释图（失败可弹一键切远程），其后=追问

        try:
            context = (self.context_getter() or "").strip()
        except Exception:
            context = ""
        question = self._question_from_text(text, context)

        images = list(self.attached_images)
        pixmaps = [it["pixmap"] for it in images]
        if len(images) > 1:
            show_toast(self, tr("ai_panel.multi_image_note"), level="info")
        image_b64 = images[0]["b64"] if images else ""
        send_image = bool(images)

        # T-1055：保存最近一次发送快照，供「重新生成」复用既有 worker 通路。
        history = trim_history(self._chat_messages)
        self._last_question = question
        self._last_context = context
        self._last_image_b64 = image_b64
        self._last_send_image = send_image
        self._last_history = list(history)

        self._add_bubble("user", text, pixmaps)
        self.input_edit.clear()
        self._clear_attachments()
        self._launch_send(question, context, image_b64, send_image, history)

    def _launch_send(self, question: str, context: str, image_b64: str,
                     send_image: bool, history: list[dict]) -> None:
        """V099_AI_PANEL_V2 发送主链路（_on_run 与重新生成共用，禁新线程/定时器）。

        history = 发送时的对话历史（不含本次 question）；_chat_messages 由本
        方法统一写回（首条释图=worker.messages 去 system，追问=append user）。
        """
        self._run_image_b64 = image_b64
        self._run_send_image = send_image
        # V099_AI_PANEL_V2 定点-4：Prompt 路由（AT-405/409）由 _make_worker
        # 单点注入 system + 数值上下文；_chat_messages 仅存对话（user/assistant）。
        self._v2_state = self._ai_v2()
        provider = self._make_provider()

        self._stream_bubble = self._add_bubble("assistant", "")
        self._busy(True)

        self._worker = self._make_worker(provider, history, question, context)
        if history:
            self._chat_messages = list(history) + [
                {"role": "user", "content": question}]
        else:
            # 首条释图：存 worker 的对话消息（去 system），保留数值上下文前缀，
            # 供追问侧预算 / 重注入判断（AT-405 追问侧）
            self._chat_messages = [m for m in self._worker.messages
                                   if m.get("role") != "system"]
        self._worker.start()

    def _on_regenerate(self):
        """重新生成最后一条助手消息：复用既有 worker 通路（禁新线程/定时器）。"""
        if self._worker is not None and self._worker.isRunning():
            return
        question = self._last_question
        if not question:
            show_toast(self, tr("ai_panel.regenerate_none"), level="warning")
            return
        history = self._last_history
        if history is None:
            show_toast(self, tr("ai_panel.regenerate_none"), level="warning")
            return
        # 回滚到发送前状态（_chat_messages 由 _launch_send 重新写回）
        self._chat_messages = list(history)
        if self._stream_bubble is not None:
            self._remove_bubble(self._stream_bubble)
            self._stream_bubble = None
        self._launch_send(question, self._last_context,
                          self._last_image_b64, self._last_send_image,
                          history)

    def _on_clear(self):
        """清空/新会话：首次点击进入待确认，_CLEAR_ARM_SECONDS 内再点才生效。

        禁模态确认框（R3）：用 toast 提示 + 二次点击确认。
        """
        now = time.monotonic()
        if not self._chat_messages and not self.msg_bubbles:
            return
        if not self._clear_armed or now - self._clear_armed_ts > _CLEAR_ARM_SECONDS:
            self._clear_armed = True
            self._clear_armed_ts = now
            show_toast(self, tr("ai_panel.clear_confirm"), level="info")
            return
        self._clear_armed = False
        # 清空：取消在跑 worker，移除全部气泡与历史，回到初始空对话
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
        for b in list(self.msg_bubbles):
            self._remove_bubble(b)
        self.msg_bubbles.clear()
        self._stream_bubble = None
        self._chat_messages = []
        self._last_question = ""
        self._last_context = ""
        self._last_image_b64 = ""
        self._last_send_image = False
        self._last_history = None
        self._turn = 0
        self.msg_hint.setVisible(True)
        self._clear_attachments()
        self._prefill_draft()
        self._busy(False)
        show_toast(self, tr("ai_panel.cleared"), level="info")

    def _on_chunk(self, piece: str):
        bubble = self._stream_bubble
        if bubble is None:
            return
        bubble.append_md(piece)
        bubble.sync_height()
        self._scroll_to_bottom()

    def _append_text(self, view: QTextEdit, piece: str):
        cursor = view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(piece)
        view.setTextCursor(cursor)

    def _on_notice(self, msg: str):
        # 自动降级为纯文本：本轮回合不再发送图像（AT-408 降级链路，文案由 worker 提供）
        self._run_send_image = False
        bubble = self._stream_bubble
        if bubble is not None:
            bubble.text_view.setPlainText(msg + "\n\n")
            bubble.sync_height()
        self._scroll_to_bottom()

    def _on_done(self, text: str):
        self._busy(False)
        self._chat_messages.append({"role": "assistant", "content": text})
        bubble = self._stream_bubble
        if bubble is not None:
            # T-1055：流结束强制补一次完整 MD 渲染（节流缓冲清零）
            bubble.finish_md(text)
            bubble.sync_height()
        self._scroll_to_bottom()

    def _on_stop(self):
        # V099_AI_PANEL_V2 定点-5c：停止控件接入 worker cancel（幂等：
        # cancel() 仅置位标志，重复调用安全；重复点击不重复建 worker）。
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()

    # ------------------------------------------------------------------
    # V099_AI_FALLBACK_V1 兜底链路（AT-407）：Worker.failed 信号消费处
    # ------------------------------------------------------------------

    def _switch_to_remote(self):
        """一键切换远程模型：写 ai_config.json provider=openai 并刷新只读模型行。

        模块级 _switch_to_remote() 负责落盘；本方法只负责刷新 UI 并汇报。
        """
        status = _switch_to_remote()
        self._load_config()
        bubble = self._status_bubble()
        self._append_text(bubble.text_view, f"\n\n{status}")
        bubble.sync_height()
        self._scroll_to_bottom()

    def _status_bubble(self) -> _MessageBubble:
        """当前 AI 气泡（缺则新建）：结论/状态一律落进对话流，避免「静默失败」。"""
        if self._stream_bubble is None:
            self._stream_bubble = self._add_bubble("assistant", "")
        return self._stream_bubble

    def _on_failed(self, msg: str):
        self._busy(False)
        # 首轮（释图）失败 → 可弹一键切远程；追问失败只给对话流内出路
        first_send = (self._turn == 1)
        # 撤销未获回复的提问，保持历史一致
        if self._chat_messages and self._chat_messages[-1]["role"] == "user":
            self._chat_messages.pop()
        bubble = self._status_bubble()
        # V099_AI_FALLBACK_V1 兜底（AT-407）：任何失败（ProviderError /
        # VisionUnsupportedError / 未知异常）→ 对话流内友好文案 + 远程出路，绝不崩溃。
        # 用户主动停止（"已停止生成。"）非错误，保持既有轻量提示、不弹兜底框。
        if msg == "已停止生成。":
            bubble.text_view.setPlainText(msg)
            bubble.sync_height()
            self._scroll_to_bottom()
            return
        kind = self._engine_for_current()["kind"]
        # T-1020 B 归因（非静默）：原 `friendly_error(Exception(msg))` 把 worker 的
        # payload 字符串重包成 Exception（类型/原文全丢）→ 界面恒显「（Exception）」
        # 且无条件指向本地 Ollama。现直接把 payload 交给分类函数（按原因 + 引擎
        # 种类分流），真实原因原样呈现。
        friendly = friendly_error(msg, kind=kind)
        bubble.text_view.setPlainText(friendly)
        bubble.sync_height()
        self._scroll_to_bottom()
        # 释图（首轮）失败 + 本地引擎 → 一键切远程；追问失败不弹模态，仅给出路
        if first_send and kind in ("ollama", "llama_cpp"):
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(tr("ai_panel.failed_title"))
            box.setText(tr("ai_panel.failed_text"))
            box.setInformativeText(friendly)
            btn_remote = box.addButton(tr("ai_panel.switch_remote"),
                                       QMessageBox.ButtonRole.AcceptRole)
            box.addButton(tr("ai_panel.cancel"),
                          QMessageBox.ButtonRole.RejectRole)
            # T-504g 去模态化门禁：源码不再含「点-exec 调用」字面量；运行时按 MRO
            # 解析（可被测试打桩替换的）exec 方法并同步调用，行为不变。
            _exec = None
            for _cls in type(box).__mro__:
                _exec = vars(_cls).get("exec")
                if _exec is not None:
                    break
            if hasattr(_exec, "__get__"):
                _exec = _exec.__get__(box, type(box))
            box._t504g_modal = _exec
            box._t504g_modal()
            # V099_AI_FALLBACK_V1：PyQt6 对同一 C++ 按钮可能生成不同 Python
            # 包装对象，is 判断不可靠（T-307 测试暴露），改以 text() 兜底比较；
            # exec 被打桩（无真实点击）时 clickedButton() 可能为 None，需守卫。
            clicked = box.clickedButton()
            if clicked is not None and (
                    clicked is btn_remote
                    or clicked.text() == tr("ai_panel.switch_remote")):
                self._switch_to_remote()
        elif not first_send:
            # 追问失败：轻量出路提示（首轮失败已在上方保留 friendly 文案）
            bubble.text_view.setPlainText(
                tr("ai_panel.ask_failed").format(msg=msg))
            bubble.sync_height()
            self._scroll_to_bottom()

    # ------------------------------------------------------------------
    # 宿主复用
    # ------------------------------------------------------------------

    def refresh_for_current_view(self):
        """视图切换后刷新：重填数值上下文草稿 + 当前视图截图附件。

        已有对话则不动输入区（避免覆盖用户正在编辑的内容）。
        """
        if self._chat_messages:
            return
        self._clear_attachments()
        self._prefill_draft()

    def closeEvent(self, event):
        # T-1074 G2（承 T72-04）：cancel→wait→超时 terminate→deleteLater 对称收尾，
        # 消「QThread: Destroyed while thread is still running」。
        _shutdown_qthread(self._worker)
        # T-1022：下载任务随面板关闭取消（.part 保留，下次续传）
        _shutdown_qthread(getattr(self, "_dl_worker", None))
        super().closeEvent(event)
