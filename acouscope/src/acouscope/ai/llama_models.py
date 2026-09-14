# SPDX-License-Identifier: GPL-3.0-only
"""llama.cpp 模型（GGUF）下载管理器（T-313）。GGUF_MODELS_V1

与 Ollama /api/pull 路线（model_manager.py）的本质差异：llama.cpp 用
直文件 GGUF，服务端无 /api/pull 去重，断点必须由客户端自己做——
下载写 <file>.part 临时文件，重发请求带 `Range: bytes=<已下字节数>-`：
服务端 206 → 追加续传；200 → 忽略 .part 从头全量重写。

下载完成后三重校验：GGUF 魔数（文件头 b"GGUF"，Experience 454351 教训：
未校验会把 HTML 鉴权/404 错误页当模型，llama-server 报 "GGUF magic
invalid"）+ 文件大小 + sha256（目录条目有值时，哈希取自 HF API 的 LFS
oid，见 Step 0 记录）。校验失败 .part 改名 <file>.bad 保留供排查，
不直接删除。

用户可见文案铁律（零终端）：LlamaModelError 消息只描述状态与下一步
动作，绝不出现命令行、URL（"://"）、curl / wget / pip 或安装指引。
URL 只存在于本文件顶部的目录常量中。

T-1023 加固：流被**中途截断**（服务器提前关流 → 短读）时，仅靠「下载完
→ sha256 失败 → 改名 .bad」会把可续传的半成品浪费掉。现改为：流式写入
结束后比对「本次实收字节 vs 期望长度」（有 Content-Length 时；无长度即
分块传输 → 以 sha256 兜底，不误判），短读 / 流内 I/O 异常 → 保留 .part，
按既有 `Range` 语义自动续传（上限 3 次 + 指数退避 1/2/4s，可取消），
耗尽仍未完成才抛 LlamaModelError（.part 保留，用户重试可继续续传）。
"""
# V1_GGUF_DOWNLOAD_V1：模型目录 / 磁盘预检 / Range 断点续传 / 镜像回退 /
# 魔数+sha256 校验 / .part 原子改名
# T-1023：短读检测 / 有限次自动续传（指数退避 + 可取消）/ 进度单调
from __future__ import annotations

import hashlib
import http.client
import os
import shutil
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# 依赖 T-312：llama.cpp 模型沙盒目录（get_data_dir()/"llama_models"，自动
# mkdir）。import 失败即 [DEP_MISSING] T-312——不允许 try 吞掉。
from acouscope.ai.interpreter import CancelledError
from acouscope.ai.llama_runtime import models_dir

try:
    import certifi
except ImportError:  # 缺 certifi 时回退默认 urlopen 行为（向后兼容）
    certifi = None

#: GGUF 文件格式魔数（文件头 4 字节，0x47475546 小端 = "GGUF"）。
GGUF_MAGIC = b"GGUF"

#: 流式读 / 哈希块大小：64KB。
_CHUNK = 1 << 16

#: 证书校验失败的用户可见短文案（零终端：不出现命令 / 路径 / 库名细节）。
_ERR_CERT_STALE = "本地证书库过旧，建议升级应用后重试"

#: T-1023：单文件「短读 / 流内 I/O 异常」自动续传的最大重试次数。
_MAX_RESUME_RETRIES = 3

#: T-1023：自动续传退避秒数（指数退避；索引超出即取末项）。
_RESUME_BACKOFF_S: tuple[float, ...] = (1.0, 2.0, 4.0)

#: T-1023：退避分片睡眠粒度（秒）——用于「取消即时生效」。
_BACKOFF_STEP_S = 0.05


class _InterruptedStream(Exception):
    """T-1023：流被中途截断（短读 / 流内 I/O 异常）的内部信号。

    绝不作 user-visible 文案：只由 `_download_one` 捕获 → 保留 .part，
    按既有 Range 语义自动续传；耗尽仍未完成才转成 LlamaModelError。
    """


def _build_opener() -> urllib.request.OpenerDirector:
    """构造下载用 opener（HTTPS 带 certifi CA 证书库）。

    根因：Python 运行时默认证书库可能缺少企业/新根证书，HTTPS 下载报
    证书验证失败（CERTIFICATE_VERIFY_FAILED）；certifi 随包发布，证书库
    持续更新。certifi 缺失或证书上下文构造失败 → 回退默认行为。
    """
    if certifi is None:
        return urllib.request.build_opener()
    try:
        ctx = ssl.create_default_context(cafile=certifi.where())
        return urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ctx))
    except Exception:  # 构造失败不阻断下载：保持默认证书行为
        return urllib.request.build_opener()


def _is_ssl_cert_error(exc: BaseException) -> bool:
    """是否 SSL 证书验证失败（区别于普通网络错误 / 镜像不可用）。

    覆盖 urlopen 直抛 ssl.SSLCertVerificationError，及被 URLError 包裹
    （reason 为 ssl.SSLCertVerificationError / reason 文本含
    CERTIFICATE_VERIFY_FAILED）两种形态。
    """
    if isinstance(exc, ssl.SSLCertVerificationError):
        return True
    if isinstance(exc, urllib.error.URLError):
        r = exc.reason
        if isinstance(r, ssl.SSLCertVerificationError):
            return True
        text = str(r)
        return ("CERTIFICATE_VERIFY_FAILED" in text
                or "certificate verify failed" in text)
    return False


class LlamaModelError(Exception):
    """GGUF 下载/校验失败（用户可见中文文案，零终端：不含命令 / URL / 安装指引）。"""


class _CertStaleError(Exception):
    """内部标记：所有镜像均因本地证书库过旧失败（零终端文案，不进 UI 直抛）。"""


@dataclass(frozen=True)
class ModelFile:
    """模型条目下的单个文件（T-1022：视觉模型为「权重 + 视觉塔」双文件）。

    role="weights" = 语言/主干权重；role="mmproj" = 多模态投影（视觉塔），
    经 llama-server `--mmproj` 挂载。size / sha256 取自目录实测（见 GGUF_MODELS
    上方注释的查询日期），禁编造。
    """

    filename: str
    urls: tuple[str, ...]
    size: int
    sha256: str | None
    role: str = "weights"


@dataclass(frozen=True)
class ModelInfo:
    """单个可下载 GGUF 模型条目。

    urls：主站在前、镜像在后；est_bytes：**该模型全部文件合计**体积
    （含视觉塔，用于磁盘预检与总体进度）；sha256：主权重文件的 LFS oid
    （64 位十六进制），下载完成后比对，None 表示未录入。

    T-1022 扩展（向后兼容：既有构造点/读点语义不变）：
    - `mmproj`：视觉塔文件（None = 纯文本模型）；
    - `vision`：视觉能力（False 一律不进任何模型列表/推荐，硬门禁依据）；
    - `min_ram_gb`：建议最小内存（软提示）；`tier_gb`：参数量档位。
    派生只读属性 `files`（weights → mmproj 顺序）供下载器逐个落地。
    """

    model_id: str
    display_name: str
    filename: str
    urls: tuple[str, ...]
    est_bytes: int
    sha256: str | None
    vision: bool = False
    min_ram_gb: float = 0.0
    tier_gb: float = 0.0
    mmproj: ModelFile | None = None

    @property
    def files(self) -> tuple[ModelFile, ...]:
        """需落地的全部文件（主权重在前，视觉塔在后）。"""
        weights = ModelFile(
            filename=self.filename,
            urls=tuple(self.urls),
            size=int(self.est_bytes) - (int(self.mmproj.size)
                                        if self.mmproj is not None else 0),
            sha256=self.sha256,
            role="weights",
        )
        return (weights,) if self.mmproj is None else (weights, self.mmproj)

    @property
    def weights(self) -> ModelFile:
        """主权重文件（`model_path()` 的落地目标）。"""
        return self.files[0]


def _hf_urls(repo: str, filename: str) -> tuple[str, str]:
    """主站 + hf-mirror 镜像两条直链（仅用于目录常量，不进异常文案）。"""
    base = f"{repo}/resolve/main/{filename}"
    return (
        f"https://huggingface.co/{base}",
        f"https://hf-mirror.com/{base}",
    )


#: GGUF 模型目录（T-1022 目录替换：纯文本 Instruct 全部下架，只上视觉模型）。
#: est_bytes / sha256 / 各文件 size 均取自 2026-09-11 对 HF 公开 API
#: （/api/models/<repo>/tree/main 的 size 字段与 LFS oid）的真实查询，禁编造：
#:   ggml-org/Qwen2.5-VL-3B-Instruct-GGUF:
#:     Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf  1929901056
#:     mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf  844757728
#:   ggml-org/Qwen2.5-VL-7B-Instruct-GGUF:
#:     Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf  4683072032
#:     mmproj-Qwen2.5-VL-7B-Instruct-Q8_0.gguf  853119712
GGUF_MODELS: tuple[ModelInfo, ...] = (
    ModelInfo(
        model_id="qwen2.5-vl-3b-instruct-q4_k_m",
        display_name="Qwen2.5-VL 3B Instruct (Q4_K_M)",
        filename="Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf",
        urls=_hf_urls("ggml-org/Qwen2.5-VL-3B-Instruct-GGUF",
                      "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"),
        # est_bytes = 1929901056 + 844757728（HF API size 实测，含视觉塔）
        est_bytes=2774658784,
        sha256="d02fe9b69ad8cadbbd228e387667af66612c44bed29ffc8eb1e7caf9ac486c12",
        vision=True,
        min_ram_gb=8.0,
        tier_gb=3.0,
        mmproj=ModelFile(
            filename="mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf",
            urls=_hf_urls("ggml-org/Qwen2.5-VL-3B-Instruct-GGUF",
                          "mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf"),
            # size = 844757728（HF API 实测）
            size=844757728,
            sha256="980c9b2f78c04e6cff93d277ada09e768394f112d75db3b4e9dea8a69f9fb904",
            role="mmproj",
        ),
    ),
    ModelInfo(
        model_id="qwen2.5-vl-7b-instruct-q4_k_m",
        display_name="Qwen2.5-VL 7B Instruct (Q4_K_M)",
        filename="Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf",
        urls=_hf_urls("ggml-org/Qwen2.5-VL-7B-Instruct-GGUF",
                      "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf"),
        # est_bytes = 4683072032 + 853119712（HF API size 实测，含视觉塔）
        est_bytes=5536191744,
        sha256="9258bf05b12686d097ff3b6b18d968ab393649780aa2b3cd67fec43d50554392",
        vision=True,
        # 7B 档建议内存高于 16GB：本机 16GB 档只推荐 3B（见 ai/model_recommend.py）
        min_ram_gb=24.0,
        tier_gb=7.0,
        mmproj=ModelFile(
            filename="mmproj-Qwen2.5-VL-7B-Instruct-Q8_0.gguf",
            urls=_hf_urls("ggml-org/Qwen2.5-VL-7B-Instruct-GGUF",
                          "mmproj-Qwen2.5-VL-7B-Instruct-Q8_0.gguf"),
            # size = 853119712（HF API 实测）
            size=853119712,
            sha256="2ddb555391bae966e412deab9e07b58afa18bcc06930ba0f1c78a3695ab9e506",
            role="mmproj",
        ),
    ),
)

#: 已知纯文本（非视觉）模型的模型名集合——T-1022 前上架过、现已下架；
#: 供视觉门禁识别「已存在配置指向非视觉模型」的历史配置（禁静默降级）。
LEGACY_TEXT_ONLY: frozenset[str] = frozenset({
    "qwen2.5-1.5b-instruct-q4_k_m",
    "qwen2.5-3b-instruct-q4_k_m",
    "qwen2.5-1.5b-instruct-q4_k_m.gguf",
    "qwen2.5-3b-instruct-q4_k_m.gguf",
})


def list_models() -> tuple[ModelInfo, ...]:
    """全部可下载 GGUF 模型（目录按展示顺序）。"""
    return GGUF_MODELS


def get_model_info(model_id: str) -> ModelInfo:
    """按 id 取模型条目；未知 id 抛 LlamaModelError（中文文案，零终端）。"""
    for m in GGUF_MODELS:
        if m.model_id == model_id:
            return m
    raise LlamaModelError(f"未知模型：{model_id}")


def model_path(model_id: str) -> Path:
    """模型落地路径：模型沙盒目录 / 主权重 filename。"""
    return models_dir() / get_model_info(model_id).filename


def mmproj_path(model_id: str) -> Path | None:
    """视觉塔（mmproj）落地路径；纯文本条目 → None（T-1022 §4）。"""
    info = get_model_info(model_id)
    return None if info.mmproj is None else models_dir() / info.mmproj.filename


def _magic_ok(path: Path) -> bool:
    """文件头 4 字节是否为 GGUF 魔数（缺字节/读失败均视为不通过）。"""
    try:
        with open(path, "rb") as f:
            return f.read(4) == GGUF_MAGIC
    except OSError:
        return False


def is_model_ready(model_id: str) -> bool:
    """模型**全部文件**已存在且魔数正确（含视觉塔；轻量就绪判定，不做 sha256）。"""
    info = get_model_info(model_id)
    return all(_magic_ok(models_dir() / f.filename) for f in info.files)


def precheck_disk(info: ModelInfo) -> tuple[bool, str]:
    """磁盘空间预检：est_bytes * 1.2 余量，对准模型沙盒目录。

    口径对齐 model_manager.precheck_disk（T-304b）：不足返回
    (False, 中文文案)。
    """
    free = shutil.disk_usage(str(models_dir())).free
    need = int(info.est_bytes * 1.2)
    if free < need:
        return (False,
                f"磁盘剩余 {free / 1e9:.1f}GB 不足以容纳"
                f"{info.display_name}（预估需 {need / 1e9:.1f}GB）")
    return True, "ok"


def verify_file(path: Path, expected_sha256: str | None) -> tuple[bool, str]:
    """三重校验：GGUF 魔数 → 文件大小（>=4）→ sha256（有值时流式比对）。

    返回 (是否通过, 消息)。任一失败消息为零终端中文文案；全过返回
    (True, "ok")。
    """
    size = path.stat().st_size
    if size < 4:
        return False, "模型文件已损坏或不是有效的 GGUF 文件"
    hasher = hashlib.sha256() if expected_sha256 else None
    with open(path, "rb") as f:
        head = f.read(4)
        if head != GGUF_MAGIC:
            return False, "模型文件已损坏或不是有效的 GGUF 文件"
        if hasher is not None:
            hasher.update(head)
        while chunk := f.read(_CHUNK):
            if hasher is not None:
                hasher.update(chunk)
    if hasher is not None \
            and hasher.hexdigest().lower() != expected_sha256.lower():
        return False, "模型文件校验失败（文件不完整或已损坏），请重试下载"
    return True, "ok"


def _write_stream(
    resp,
    part: Path,
    resume_pos: int,
    total: int,
    is_cancelled: Callable[[], bool] | None,
    on_progress: Callable[[float], None] | None,
) -> int:
    """流式写入 .part（append），返回本次新写入字节数；取消抛 CancelledError。"""
    mode = "ab" if resume_pos else "wb"
    with open(part, mode) as out:
        while True:
            if is_cancelled is not None and is_cancelled():
                resp.close()
                raise CancelledError("download cancelled")
            chunk = resp.read(_CHUNK)
            if not chunk:
                break
            out.write(chunk)
            resume_pos += len(chunk)
            if on_progress is not None and total > 0:
                # 进度单调夹 0..1
                on_progress(max(0.0, min(1.0, resume_pos / total)))
    return resume_pos


def _backoff_sleep(retry_index: int, is_cancelled: Callable[[], bool] | None) -> None:
    """T-1023：续传前退避等待（指数退避，分片睡眠以便取消即时生效）。

    取消 → 抛 CancelledError（.part 已保留，交由上层语义处理）。
    """
    if is_cancelled is not None and is_cancelled():
        raise CancelledError("download cancelled")
    if not _RESUME_BACKOFF_S:
        return
    total = _RESUME_BACKOFF_S[min(retry_index, len(_RESUME_BACKOFF_S) - 1)]
    waited = 0.0
    while waited < total:
        if is_cancelled is not None and is_cancelled():
            raise CancelledError("download cancelled")
        time.sleep(min(_BACKOFF_STEP_S, total - waited))
        waited += _BACKOFF_STEP_S


def _download_from_url(
    url: str,
    part: Path,
    resume_pos: int,
    est_bytes: int,
    is_cancelled: Callable[[], bool] | None,
    on_progress: Callable[[float], None] | None,
) -> bool:
    """从单个 URL 下载（支持 Range 续传）。成功返回 True。

    - 206 Partial Content → 追加续传（保留 .part）；200 OK → 删 .part 从头全量重写；
    - 416 Range Not Satisfiable 且 resume_pos >= est_bytes（.part 已达目录登记
      的完整大小，100% 前一刻中断后重试）→ 返回 True 视为下载完成，由调用方
      走 verify_file 正常校验 / 改名；其余 416 → 返回 False 换镜像；
    - 其他 HTTP 状态码（404 / 403 HTML 错误页等）或**连接层**网络异常 → 返回
      False，由调用方换下一个镜像；
    - **流已建立后**被截断（短读：实收 < Content-Length；或流内 I/O 异常）
      → 抛 _InterruptedStream（T-1023），由调用方保留 .part 自动续传；
      无 Content-Length（分块传输）→ 不做短读判定，以 sha256 兜底，不误判；
    - 取消 → CancelledError 直接上抛（.part 已保留）；
    - 证书验证失败 → 抛 _CertStaleError（零终端短文案），由调用方汇总透出。
    """
    headers = {}
    if resume_pos:
        headers["Range"] = f"bytes={resume_pos}-"
    req = urllib.request.Request(url, headers=headers)
    try:
        with _build_opener().open(req, timeout=60) as resp:
            code = resp.getcode()
            if code == 200 and resume_pos:
                # 服务端忽略 Range 全量重发 → 删 .part 从头重写
                part.unlink(missing_ok=True)
                resume_pos = 0
            elif code != 200 and code != 206:
                # 其他状态码（404 / 416 等）→ 换下一个镜像
                return False
            cr = resp.headers.get("Content-Length")
            if cr:
                # 206：本次响应剩余长度；200：本次全量长度（T-1023 短读比对基数）
                remaining = int(cr)
                has_length = True
            else:
                # 服务端未给 Content-Length（如分块传输）：按目录经验值
                # est_bytes 估算进度分母（注释注明：估算，可能偏差）；
                # 无长度即无法判定短读，以 sha256 校验为最后一道闸（不误判）。
                remaining = max(est_bytes - resume_pos, 1)
                has_length = False
            total = resume_pos + remaining
            base = resume_pos
            try:
                end = _write_stream(resp, part, base, total,
                                    is_cancelled, on_progress)
            except CancelledError:
                raise
            except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
                # 流读取中途重置 / 分块读取不完整 → 可续传（T-1023）
                raise _InterruptedStream("下载流被中断") from exc
            if has_length and (end - base) < remaining:
                # 短读：服务器提前关流（本任务根因场景）→ 不得视为下载完成
                raise _InterruptedStream(
                    f"下载中断：本次期望 {remaining} 字节，实收 {end - base} 字节")
            return True
    except CancelledError:
        raise
    except _InterruptedStream:
        raise
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and resume_pos >= est_bytes:
            # .part 已达完整大小（100% 前一刻中断后重试）：Range: bytes=<总大小>-
            # 服务端必返 416（Range Not Satisfiable），文件实际已完整 → 视为
            # 下载完成，交给上层 verify_file 校验（魔数 + sha256）后原子改名。
            return True
        # 其余 416（.part 未完成却收到 Range 不可满足）或 404 等 → 换下一镜像
        return False
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        # 证书验证失败：带 reason 上抛，供上层与“镜像不可用”区分（零终端）
        if _is_ssl_cert_error(exc):
            raise _CertStaleError(_ERR_CERT_STALE) from exc
        # 连接失败（源不可达）/ 镜像 404、403 等：交给上层回退下一镜像
        # （T-1023：连接层失败沿用镜像回退语义，不占用续传重试预算）
        return False
    return False


def _download_one(
    mfile: ModelFile,
    on_progress: Callable[[float], None] | None,
    is_cancelled: Callable[[], bool] | None,
    base_done: int,
    total: int,
) -> Path:
    """下载单个文件（Range 续传 + 镜像回退 + 三重校验 + 原子改名）。

    T-1022：从原单文件 `download_model` 抽出，供「权重 + 视觉塔」逐文件复用；
    进度按 `(base_done + 本文件已下字节) / total` 折算为整模型进度。
    T-1023：流被截断（短读 / 流内 I/O 异常）→ **保留 .part**，按既有 Range
    语义自动续传（上限 `_MAX_RESUME_RETRIES` 次 + 指数退避 1/2/4s，可取消）；
    预算耗尽仍未完成 → 抛 LlamaModelError（.part 保留，用户重试可继续续传；
    坏文件绝不入档）。进度回调单调不回退。

    镜像回退顺序不变：连接层失败（源不可达 / 404）仍立即换下一镜像。
    """
    target = models_dir() / mfile.filename
    part = target.with_suffix(target.suffix + ".part")
    if target.exists() and _magic_ok(target):
        if on_progress is not None and total > 0:
            on_progress(max(0.0, min(1.0, (base_done + mfile.size) / total)))
        return target

    high_water = 0.0

    def _progress(fraction: float) -> None:
        nonlocal high_water
        if on_progress is None or total <= 0:
            return
        value = max(0.0, min(1.0, (base_done + fraction * mfile.size) / total))
        # T-1023：续传重发（200 重写导致分母回退）不得把进度回调拉回去
        if value < high_water:
            value = high_water
        high_water = value
        on_progress(value)

    retries = 0          # 已消耗的自动续传次数（整文件共享预算，含跨镜像）
    interrupted = False  # 是否出现过「流被截断」（决定终态文案）
    last_err = ""
    finished = False
    for url in mfile.urls:
        while True:
            resume_pos = part.stat().st_size if part.exists() else 0
            try:
                if _download_from_url(url, part, resume_pos, mfile.size,
                                      is_cancelled, _progress):
                    finished = True
                    break
                last_err = "模型源暂时不可用"
                break  # 连接层失败 / 其他状态码 → 换下一个镜像
            except CancelledError:
                raise
            except _CertStaleError as exc:
                last_err = str(exc)
                break
            except _InterruptedStream:
                # 短读 / 流内 I/O 异常：保留 .part，同源按 Range 语义自动续传
                interrupted = True
                if retries >= _MAX_RESUME_RETRIES:
                    break
                _backoff_sleep(retries, is_cancelled)  # 指数退避，可取消
                retries += 1
                continue
        if finished:
            break
    if not finished:
        if interrupted and retries >= _MAX_RESUME_RETRIES:
            raise LlamaModelError(
                f"下载中断（网络不稳定），已自动重试 {retries} 次仍未完成，"
                "请稍后重试"
            )
        # 全部镜像均失败：零终端文案，不泄露 URL / 命令；证书类失败
        # 的短 reason 透出在末尾括号内，与普通“镜像不可用”区分。
        raise LlamaModelError(
            "模型下载失败：网络连接中断或模型源暂不可用，请稍后重试"
            f"（{last_err}）"
        )
    ok, msg = verify_file(part, mfile.sha256)
    if not ok:
        bad = target.with_suffix(target.suffix + ".bad")
        if bad.exists():
            bad.unlink()
        os.replace(part, bad)
        raise LlamaModelError(msg)
    os.replace(part, target)  # 原子改名
    _progress(1.0)
    return target


def download_model(
    model_id: str,
    on_progress: Callable[[float], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> Path:
    """阻塞式下载模型**全部文件**到沙盒目录，返回主权重落地路径。

    幂等：目标已存在且魔数正确 → 直接返回，零网络（逐文件判定）。取消抛
    CancelledError（.part 保留，重发即续传）；其余失败抛 LlamaModelError
    （零终端中文文案）。进度经 on_progress(0..1) 单调回调（含视觉塔）。
    """
    info = get_model_info(model_id)
    ok, msg = precheck_disk(info)
    if not ok:
        raise LlamaModelError(msg)
    files = info.files
    total = sum(int(f.size) for f in files) or int(info.est_bytes)
    done = 0
    # 返回值恒为**主权重**落地路径（多文件时不得被视觉塔覆盖，T-1022 Step 8 实测）
    weights = models_dir() / info.filename
    for mfile in files:
        _download_one(mfile, on_progress, is_cancelled, done, total)
        done += int(mfile.size)
    if on_progress is not None:
        on_progress(1.0)
    return weights
