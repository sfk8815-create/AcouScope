# SPDX-License-Identifier: GPL-3.0-only
"""视觉语言模型调用层（纯 urllib，零新增依赖）。

Providers（T-320 三档制：内置 / 本地部署 / 云端服务商）：
- 路由保留键：free_remote（免费远程）、ollama、llama_cpp（本地引擎接线）
- 云端厂商：DeepSeek、通义 Qwen、OpenAI、智谱GLM
- 自定义：任意 OpenAI 兼容 API

针对本地服务的健壮性设计：
- 自动补全 /v1 前缀（LM Studio 仅监听 /v1/chat/completions，
  用户只填 http://ip:1234 时直接请求根路径会 404 → 表现为"无输出"）
- SSE 流式输出：本地大模型生成慢，逐块显示避免"无输出"错觉与整体超时
- 纯文本模型（如 mlx 文本模型）收到图像会报错或返回空：
  抛 VisionUnsupportedError，由上层自动改纯文本重试
- 连接中断时保留已生成的部分输出而不是整体丢弃
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import re
import ssl
import urllib.error
import urllib.request

FREE_REMOTE_BASE = "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1"
FREE_REMOTE_MODEL = "Qwen2.5-VL-72B-Instruct"
OLLAMA_DEFAULT = "http://127.0.0.1:11434"
OLLAMA_DEFAULT_MODEL = "moondream"


# ---------------------------------------------------------------------------
# 服务商定义（Cherry Studio 风格，分组展示）
# ---------------------------------------------------------------------------

@dataclass
class ProviderInfo:
    """服务商信息。"""
    id: str
    name: str           # 显示名
    category: str       # 分类：free / local / cloud / custom
    base_url: str       # 默认 API 地址
    default_model: str  # 默认模型名
    api_key_required: bool = True   # 是否需要 API Key
    docs_url: str = ""  # 文档链接
    description: str = ""


PROVIDERS = {
    # ---- 路由保留键（T-320 三档制下设置 UI 不以下拉呈现；释图面板与
    #      引擎接线仍消费这些 provider id，语义保持兼容）----
    "free_remote": ProviderInfo(
        id="free_remote",
        name="免费远程模型（OVHcloud）",
        category="free",
        base_url=FREE_REMOTE_BASE,
        default_model=FREE_REMOTE_MODEL,
        api_key_required=False,
        description="匿名 2 RPM，无需密钥，稳定性不保证",
    ),
    "ollama": ProviderInfo(
        id="ollama",
        name="Ollama（本地）",
        category="local",
        base_url=OLLAMA_DEFAULT,
        default_model=OLLAMA_DEFAULT_MODEL,
        api_key_required=False,
        description="跨平台本地推理，支持 Metal/CUDA 加速",
    ),
    "llama_cpp": ProviderInfo(
        id="llama_cpp",
        name="llama.cpp server（本地）",
        category="local",
        base_url="http://127.0.0.1:8080/v1",
        default_model="",
        api_key_required=False,
        description="llama.cpp 官方 server，轻量高效",
    ),

    # ---- 云端厂商（T-320 收口：DeepSeek / 通义 Qwen / OpenAI / 智谱GLM /
    #      自定义 OpenAI 兼容，对齐 Cherry Studio「模型服务商」范式）----
    "deepseek": ProviderInfo(
        id="deepseek",
        name="DeepSeek",
        category="cloud",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        description="DeepSeek-V3 / DeepSeek-R1",
    ),
    "qwen": ProviderInfo(
        id="qwen",
        name="通义 Qwen",
        category="cloud",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen-vl-max",
        description="Qwen-VL / Qwen2.5 系列",
    ),
    "openai": ProviderInfo(
        id="openai",
        name="OpenAI",
        category="cloud",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o",
        description="GPT-4o / GPT-4o mini 等",
    ),
    "zhipu": ProviderInfo(
        id="zhipu",
        name="智谱GLM",
        category="cloud",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-4v-flash",
        description="GLM-4V / GLM-4 系列",
    ),

    # 自定义
    "custom": ProviderInfo(
        id="custom",
        name="自定义（OpenAI 兼容）",
        category="custom",
        base_url="",
        default_model="",
        description="兼容任何 OpenAI 格式的 API 端点",
    ),
}

# T-320 收口注记：lm_studio / anthropic / google / moonshot / siliconflow /
# openrouter / groq / together / xai 预设已从 PROVIDERS 删除（设置 UI 三档制
# 不再引用；旧配置在设置对话框读取时迁移，详见 settings_dialog._ai_source_from_config）。
# PROVIDERS 完整物理删除与全仓审计留 T-321。

# 分类标签
PROVIDER_CATEGORIES = [
    ("free", "免费"),
    ("local", "本地模型"),
    ("cloud", "云端 API"),
    ("custom", "自定义"),
]

# 兼容旧接口：(id, label) 列表
PROVIDER_LABELS = [(p.id, p.name) for p in PROVIDERS.values()]

# 本地 27B 级模型逐 token 生成很慢：这是"相邻数据块"的读超时，
# 流式下只要模型持续产出 token 就不会触发
CHAT_TIMEOUT = 600
MAX_TOKENS = 4096

# 纯文本模型收到图像输入时的典型报错关键词
_VISION_ERROR_RE = re.compile(
    r"image|vision|multimodal|base64|data:image|invalid.*content|content.*invalid"
    r"|not support|unsupported",
    re.IGNORECASE,
)


class ProviderError(Exception):
    """模型调用失败。"""


class VisionUnsupportedError(ProviderError):
    """模型不支持图像输入（上层应改纯文本重试）。"""


class ConnectionInterruptedError(ProviderError):
    """连接中途断开（可能已有部分输出）。"""


class CancelledError(Exception):
    """用户主动停止生成。"""


def _ssl_context():
    """构造可用的 SSL 上下文（macOS 官方 Python 缺根证书时用 certifi 兜底）。"""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _http_json(url: str, payload: dict | None = None,
               headers: dict | None = None, timeout: float = 30) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST" if data else "GET",
    )
    ctx = _ssl_context() if url.lower().startswith("https") else None
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        if e.code == 429:
            raise ProviderError(
                "免费远程模型限流（匿名约 2 次/分钟），请稍候 1 分钟重试，"
                "或改用本地 Ollama / 自定义 API。"
            ) from e
        raise ProviderError(f"服务返回 {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise ProviderError(f"无法连接服务: {e.reason}") from e
    except TimeoutError as e:
        raise ProviderError("请求超时（模型推理可能较慢，请重试）") from e


# ----------------------------------------------------------------------
# 流式解析（纯函数，便于离线测试）
# ----------------------------------------------------------------------

def parse_sse_stream(lines, on_chunk, is_cancelled=None) -> dict:
    """解析 OpenAI 兼容 SSE 流（'data: {...}' 行），逐块回调。

    Returns:
        {"finish_reason": str, "empty": bool}
    """
    meta = {"finish_reason": "", "empty": True}
    for raw in lines:
        if is_cancelled is not None and is_cancelled():
            raise CancelledError("已停止生成")
        line = raw.strip() if isinstance(raw, str) else raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        data_str = line[5:].strip()
        if data_str == "[DONE]":
            break
        try:
            obj = json.loads(data_str)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("error"):
            raise ProviderError(str(obj["error"])[:300])
        try:
            choice = obj["choices"][0]
        except (KeyError, IndexError, TypeError):
            continue
        delta = choice.get("delta") or {}
        piece = delta.get("content") or choice.get("text") or ""
        if piece:
            meta["empty"] = False
            on_chunk(piece)
        if choice.get("finish_reason"):
            meta["finish_reason"] = choice["finish_reason"]
    return meta


def parse_ndjson_stream(lines, on_chunk, is_cancelled=None) -> dict:
    """解析 Ollama NDJSON 流（每行一个 JSON 对象），逐块回调。"""
    meta = {"finish_reason": "", "empty": True}
    for raw in lines:
        if is_cancelled is not None and is_cancelled():
            raise CancelledError("已停止生成")
        line = raw.strip() if isinstance(raw, str) else raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if obj.get("error"):
            raise ProviderError(str(obj["error"])[:300])
        piece = (obj.get("message") or {}).get("content") or ""
        if piece:
            meta["empty"] = False
            on_chunk(piece)
        if obj.get("done"):
            break
    return meta


def _extract_completion(obj: dict) -> tuple[str, str]:
    """从非流式 chat/completions 响应提取正文与结束原因。"""
    try:
        choice = obj["choices"][0]
        content = choice["message"]["content"] or ""
        return content, choice.get("finish_reason") or ""
    except (KeyError, IndexError, TypeError) as e:
        raise ProviderError(f"服务响应格式异常: {str(obj)[:200]}") from e


def _http_stream(url: str, payload: dict, headers: dict, timeout: float,
                 on_chunk, is_cancelled=None,
                 parser=parse_sse_stream) -> dict:
    """POST（stream=True）并把响应行流式交给 parser；
    兼容服务器忽略 stream 参数直接返回整包 JSON 的情况。"""
    import http.client

    payload = {**payload, "stream": True}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", **headers},
    )
    ctx = _ssl_context() if url.lower().startswith("https") else None
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            lines = iter(resp)
            first = next(lines, None)
            if first is None:
                return {"finish_reason": "", "empty": True}
            if first.lstrip().startswith(b"{"):
                # 服务器未走流式：整体解析
                body = first + b"".join(lines)
                obj = json.loads(body.decode("utf-8", "replace"))
                if isinstance(obj, dict) and obj.get("error"):
                    raise ProviderError(str(obj["error"])[:300])
                content, finish = _extract_completion(obj)
                if content:
                    on_chunk(content)
                return {"finish_reason": finish, "empty": not content}

            def _gen():
                yield first
                yield from lines

            return parser(_gen(), on_chunk, is_cancelled)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        if e.code == 429:
            raise ProviderError(
                "免费远程模型限流（匿名约 2 次/分钟），请稍候 1 分钟重试，"
                "或改用本地模型。"
            ) from e
        raise ProviderError(f"服务返回 {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise ProviderError(f"无法连接服务: {e.reason}") from e
    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError,
            TimeoutError, http.client.HTTPException) as e:
        raise ConnectionInterruptedError(f"连接中断: {e}") from e


def _attach_image(messages: list[dict], image_b64: str) -> list[dict]:
    """把图像挂到第一条 user 消息（OpenAI 多模态格式）。"""
    out = []
    attached = False
    for m in messages:
        if image_b64 and not attached and m.get("role") == "user":
            out.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": m.get("content", "")},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_b64}"
                        },
                    },
                ],
            })
            attached = True
        else:
            out.append(dict(m))
    return out


class OpenAICompatProvider:
    """OpenAI 兼容 chat/completions（SSE 流式；支持纯文本模型回退）。"""

    def __init__(self, base_url: str, api_key: str = "", model: str = ""):
        self.base_url = (base_url or "").strip().rstrip("/")
        self.api_key = api_key or ""
        self.model = model or ""
        self._base_resolved = False

    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _ensure_base(self) -> None:
        """自动补全 /v1 前缀（LM Studio 等只监听 /v1 路径）。"""
        if self._base_resolved or not self.base_url:
            return
        self._base_resolved = True
        if re.search(r"/v\d+$", self.base_url):
            return
        try:
            _http_json(f"{self.base_url}/models",
                       headers=self._auth(), timeout=10)
            return
        except ProviderError:
            pass
        try:
            _http_json(f"{self.base_url}/v1/models",
                       headers=self._auth(), timeout=10)
            self.base_url += "/v1"
        except ProviderError:
            pass  # 保持原地址，让后续调用报真实错误

    def check(self) -> tuple[bool, str]:
        self._ensure_base()
        try:
            result = _http_json(f"{self.base_url}/models",
                                headers=self._auth(), timeout=15)
        except ProviderError as e:
            return False, str(e)
        ids = [m.get("id", "") for m in result.get("data", [])
               if isinstance(m, dict)]
        if self.model and ids and self.model not in ids:
            shown = ", ".join(ids[:5]) + ("…" if len(ids) > 5 else "")
            return True, (
                f"连接正常，但模型列表中未找到 “{self.model}”。"
                f"可用模型: {shown}。请核对模型名（区分大小写）。"
            )
        return True, "连接正常" + (f"，模型 {self.model} 就绪" if self.model else "")

    def chat(self, messages: list[dict], image_b64: str = "",
             on_chunk=None, is_cancelled=None,
             timeout: float = CHAT_TIMEOUT) -> str:
        """按 messages 对话；image_b64 非空时挂到第一条 user 消息。

        Raises:
            VisionUnsupportedError: 带图调用失败/返回空，疑似模型不支持图像
            ProviderError / ConnectionInterruptedError / CancelledError
        """
        self._ensure_base()
        payload = {
            "model": self.model,
            "messages": _attach_image(messages, image_b64),
            "max_tokens": MAX_TOKENS,
        }
        chunks: list[str] = []

        def collect(piece: str):
            chunks.append(piece)
            if on_chunk is not None:
                on_chunk(piece)

        try:
            meta = _http_stream(
                f"{self.base_url}/chat/completions", payload, self._auth(),
                timeout, collect, is_cancelled,
            )
        except ConnectionInterruptedError:
            if chunks:
                return (
                    "".join(chunks).strip()
                    + "\n\n> 提示：与模型的连接中断，以上为已生成的部分。"
                )
            raise
        except ProviderError as e:
            if (
                image_b64
                and not isinstance(e, ConnectionInterruptedError)
                and _VISION_ERROR_RE.search(str(e))
            ):
                raise VisionUnsupportedError(str(e)) from e
            raise

        text = "".join(chunks).strip()
        if not text:
            if image_b64:
                raise VisionUnsupportedError(
                    "模型未返回任何内容（可能不支持图像输入）"
                )
            raise ProviderError(
                "模型返回空内容：请检查模型名是否正确、上下文是否过长，"
                "或换一个模型重试。"
            )
        if meta.get("finish_reason") == "length":
            text += "\n\n> 提示：输出达到长度上限被截断，可追问“请继续”。"
        return text


class OllamaProvider:
    """本地 Ollama /api/chat（NDJSON 流式；images 字段传 base64）。"""

    def __init__(self, base_url: str = OLLAMA_DEFAULT,
                 model: str = OLLAMA_DEFAULT_MODEL):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def check(self) -> tuple[bool, str]:
        try:
            result = _http_json(f"{self.base_url}/api/tags", timeout=10)
        except ProviderError as e:
            return False, f"{e}（本地引擎未就绪；首次释图会自动启动内置引擎，或在「设置-AI」切换远程模型）"
        names = [m.get("name", "") for m in result.get("models", [])]
        if any(n.startswith(self.model) for n in names):
            return True, f"本地模型 {self.model} 就绪"
        return False, (
            f"本地模型 {self.model} 尚未下载。请到「设置-AI」点击「下载选中模型」，"
            f"或切换远程模型（引擎内已检测到: {', '.join(names[:5]) or '无'}）"
        )

    def chat(self, messages: list[dict], image_b64: str = "",
             on_chunk=None, is_cancelled=None,
             timeout: float = CHAT_TIMEOUT) -> str:
        msgs = []
        attached = False
        for m in messages:
            item = {"role": m["role"], "content": m.get("content", "")}
            if image_b64 and not attached and m["role"] == "user":
                item["images"] = [image_b64]
                attached = True
            msgs.append(item)
        payload = {"model": self.model, "messages": msgs}

        chunks: list[str] = []

        def collect(piece: str):
            chunks.append(piece)
            if on_chunk is not None:
                on_chunk(piece)

        payload = {**payload, "stream": True}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat", data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                meta = parse_ndjson_stream(
                    (raw.decode("utf-8", "replace") for raw in resp),
                    collect, is_cancelled,
                )
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            if image_b64 and _VISION_ERROR_RE.search(body):
                raise VisionUnsupportedError(body) from e
            raise ProviderError(f"服务返回 {e.code}: {body}") from e
        except urllib.error.URLError as e:
            raise ProviderError(f"无法连接 Ollama: {e.reason}") from e
        except (ConnectionResetError, ConnectionAbortedError,
                BrokenPipeError, TimeoutError) as e:
            if chunks:
                return (
                    "".join(chunks).strip()
                    + "\n\n> 提示：与 Ollama 的连接中断，以上为已生成的部分。"
                )
            raise ConnectionInterruptedError(f"连接中断: {e}") from e

        text = "".join(chunks).strip()
        if not text:
            if image_b64:
                raise VisionUnsupportedError(
                    "模型未返回任何内容（可能不支持图像输入）"
                )
            raise ProviderError("模型返回空内容：请检查模型名或换模型重试。")
        if meta.get("finish_reason") == "length":
            text += "\n\n> 提示：输出达到长度上限被截断，可追问“请继续”。"
        return text


def make_provider(kind: str, base_url: str = "", api_key: str = "",
                  model: str = ""):
    """按类型构造 provider。

    Args:
        kind: 服务商 ID（参见 PROVIDERS 字典）
        base_url: API 地址（为空时使用服务商默认地址）
        api_key: API 密钥
        model: 模型名（为空时使用服务商默认模型）
    """
    info = PROVIDERS.get(kind)

    # Ollama 走专用 provider
    if kind == "ollama":
        return OllamaProvider(
            base_url or (info.base_url if info else OLLAMA_DEFAULT),
            model or (info.default_model if info else OLLAMA_DEFAULT_MODEL),
        )

    # 免费远程
    if kind == "free_remote":
        return OpenAICompatProvider(FREE_REMOTE_BASE, "", FREE_REMOTE_MODEL)

    # 其他全部走 OpenAI 兼容协议
    if info:
        return OpenAICompatProvider(
            base_url or info.base_url,
            api_key,
            model or info.default_model,
        )

    # 兜底：自定义
    return OpenAICompatProvider(base_url, api_key, model)


def encode_png(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")
