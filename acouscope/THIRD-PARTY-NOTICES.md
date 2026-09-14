# 第三方组件与许可声明（THIRD-PARTY NOTICES）

> 适用范围：AcouScope 源码仓 `acouscope/` 所依赖或随附分发的第三方组件。
> 生成：2026-09-12（T-1049 E1 许可收紧）· 全部条目均**实读**取证（已装分发元数据 / 二进制自述 / 上游原文）。
> 口径：本文件**只作事实陈述**；凡未核实事项一律显式标注，**不作有利推定**（与 `METADATA_standards_audit` 学术诚信口径同源）。

---

## 1. 本项目许可

| 项目 | 许可 | 说明 |
|---|---|---|
| AcouScope | **GPL-3.0-only** | 全文见仓库根 `LICENSE`（GPL-3.0 全文，673 行） |

**为何是 `only` 而非 `or-later`（实读依据）**：`PyQt6 6.11.0` 的分发元数据为
`License-Expression = GPL-3.0-only`（`importlib.metadata` 实读，2026-09-12）。
本项目**无法**对其中 PyQt6 部分授予 GPL「或更高版本」，故全仓声明
（`pyproject.toml` / `README.md` / 源码 SPDX 头）由 `GPL-3.0-or-later` 收紧为 `GPL-3.0-only`。

---

## 2. Python 运行时依赖

版本与「许可」列均为 `importlib.metadata` **实读原文**（本机 `.venv`，2026-09-12）。

| 组件 | 版本 | 许可（元数据原文字段） | 义务要点 | 来源 |
|---|---|---|---|---|
| PyQt6 | 6.11.0 | `GPL-3.0-only` | 见 §3.1 | <https://pypi.org/project/PyQt6/> · <https://www.riverbankcomputing.com/software/pyqt/> |
| PyQt6-Qt6 | 6.11.2 | `LGPL v3` | 见 §3.1（LGPL 义务） | <https://pypi.org/project/PyQt6-Qt6/> · <https://www.qt.io/licensing/open-source-lgpl-obligations> |
| PyQt6-sip | 13.12.0 | `BSD-2-Clause` | 保留版权与许可声明 | <https://pypi.org/project/PyQt6-sip/> |
| pyqtgraph | 0.14.0 | `MIT` | 保留版权与许可声明 | <https://pypi.org/project/pyqtgraph/> |
| matplotlib | 3.10.9 | `License agreement for matplotlib versions 1.3.0 and later`（PSF 式 BSD 兼容） | 保留版权与许可声明 | <https://pypi.org/project/matplotlib/> · <https://matplotlib.org/stable/project/license.html> |
| certifi | 2026.7.22 | `MPL-2.0` | 保留声明；如修改其文件须公开该文件源码 | <https://pypi.org/project/certifi/> · <https://www.mozilla.org/MPL/2.0/> |
| numpy | 2.2.6 | BSD 系（原文首行 `Copyright (c) 2005-2024, NumPy Developers.`） | 保留版权与许可声明 | <https://pypi.org/project/numpy/> · <https://numpy.org/doc/stable/license.html> |
| soundfile | 0.12.1 | `BSD 3-Clause License` | 保留版权与许可声明 | <https://pypi.org/project/soundfile/> |
| Pillow | 12.2.0 | `MIT-CMU` | 保留版权与许可声明 | <https://pypi.org/project/Pillow/> · <https://github.com/python-pillow/Pillow/blob/main/LICENSE> |
| onnxruntime | 1.23.2 | `MIT License` | 保留版权与许可声明 | <https://pypi.org/project/onnxruntime/> · <https://github.com/microsoft/onnxruntime/blob/main/LICENSE> |

> 许可兼容性口径：以上均为 GPL-3.0 兼容许可（MIT / BSD / ISC / MPL-2.0 / PSF 式 / LGPL-3.0），
> 不改变本项目整体以 GPL-3.0-only 分发的事实。

---

## 3. 随包二进制与资产

### 3.1 PyQt6 与 Qt

- **PyQt6 6.11.0** — 许可 `GPL-3.0-only`；发布主体 Riverbank Computing Limited。
  **义务**：以 GPL-3.0 分发时须提供完整对应源码（GPL-3.0 §4/§6，含修改与构建脚本）。
  许可正文**已在仓库根 `LICENSE`**（GPL-3.0 全文），此处仅作指向，不重复粘贴。
- **Qt 6.11.2**（以 `PyQt6-Qt6 6.11.2` 随包分发）— 许可 **LGPL v3**。
  **义务**：① 附 LGPL-3.0 文本 → 见 [`licenses/LGPL-3.0.txt`](licenses/LGPL-3.0.txt)；
  ② 提供**可替换库**条件（LGPL-3.0 §4）。

  **可替换库声明**：AcouScope 通过 PyQt6 以**动态链接**方式使用 Qt 6.11.2 共享库；
  用户可自行以**接口（ABI）兼容**的 Qt 6.11.2 构建（含自行修改后的版本）替换这些共享库，
  无需修改 AcouScope 源码即可重新运行本程序。本仓库未对 Qt 共享库施加额外的技术限制
  （无来源签名锁定、无完整性校验阻断替换）。

### 3.2 FFmpeg（内置解码器）

| 项 | 实读值 |
|---|---|
| 版本 | `ffmpeg version 7.1 Copyright (c) 2000-2024 the FFmpeg developers` |
| 构建 | `built with Apple clang version 13.1.6 (clang-1316.0.21.2.5)` |
| 架构 | Mach-O 64-bit executable **arm64**（仅 arm64；x86_64 平台回退系统 ffmpeg，代码内已注明） |
| 二进制 | `src/acouscope/resources/bin/ffmpeg`，sha256 前缀 `6d175a4743ca50256e89a8cd` |
| 许可 | FFmpeg 官方口径：LGPL v2.1；**启用 `--enable-gpl` 的构建中 GPL 部分为 "GPL version 2 or later"** → 与本项目 GPL-3.0 兼容 |

`ffmpeg -version` 的 configure 行（构建指纹，逐字）：

```
configuration: --prefix=/Volumes/tempdisk/sw --extra-cflags=-fno-stack-check --arch=arm64 --cc=/usr/bin/clang --enable-gpl --enable-libvmaf --enable-libopenjpeg --enable-libopus --enable-libmp3lame --enable-libx264 --enable-libx265 --enable-libvpx --enable-libwebp --enable-libass --enable-libfreetype --enable-fontconfig --enable-libtheora --enable-libvorbis --enable-libsnappy --enable-libaom --enable-libvidstab --enable-libzimg --enable-libsvtav1 --enable-libharfbuzz --enable-libkvazaar --pkg-config-flags=--static --enable-ffplay --enable-postproc --enable-neon --enable-runtime-cpudetect --disable-indev=qtkit --disable-indev=x11grab_xcb
```

**义务与履行**：
- 附 GPL-2.0 许可文本 → 见 [`licenses/GPL-2.0.txt`](licenses/GPL-2.0.txt)。
- **对应源码获取途径**：该二进制为 arm64 **静态构建**（configure 行见上）；**构建来源未记录**，
  本项目未保留该次构建的构建记录、本地补丁或修改信息（取证：无 quarantine 来源、无下载历史、
  无构建目录等痕迹）。对应源码 = 上游官方源码包 **<https://ffmpeg.org/releases/ffmpeg-7.1.tar.xz>**
  （版本与 configure 行一致）。
  ⚠ **未核实项**：本仓未记录该次构建是否引入本地补丁或修改；发布物含此二进制，应由构建方据实
  补齐对应的完整源码（含任何补丁）。因无法溯源具体构建方，发布者宜评估改用自建可复现构建，
  或改用运行时下载 + 上游链接的方式。

### 3.3 llama.cpp / ggml

| 项 | 实读值 |
|---|---|
| 组件 | `llama-server` 及 `libllama*` / `libggml*` / `libmtmd*` 动态库（文件名版本号 `0.23.0`） |
| 许可 | **MIT** |
| 文本位置 | 仓内 `src/acouscope/resources/bin/LICENSE-llama.cpp.txt`；副本 [`licenses/MIT-llama.cpp.txt`](licenses/MIT-llama.cpp.txt) |
| 来源 | <https://github.com/ggml-org/llama.cpp> |

### 3.4 Ollama 随包引擎资产（v0.33.3）

- 版本与来源（实读 `BUNDLE_INFO.txt`）：`ollama v0.33.3`（官方 release，macOS universal2）
  ← <https://github.com/ollama/ollama/releases/tag/v0.33.3>
- **义务履行**：该目录下随上游 tar 原样提供的**许可/声明文本已随仓入库**（`.gitignore` 已放行），路径
  `src/acouscope/resources/bin/ollama/`：

| 文件 | 组件 | 许可（实读首行） |
|---|---|---|
| `GO_LICENSE` | Go 运行时及依赖（文件自述 "Go licenses for Ollama and its dependencies"） | 见文件原文（含 BSD 系条款） |
| `LLAMA_CPP_LICENSE` | llama.cpp | `MIT License` |
| `LLAMA_CPP_VENDORS_LICENSE` | llama.cpp 第三方 vendors（文件自述 "License for llama.cpp"） | 见文件原文 |
| `MLX_LICENSE` | MLX | `MIT License` |
| `MLX_C_LICENSE` | MLX C | `MIT License` |
| `FMT_LICENSE` | {fmt}（Victor Zverovich） | `MIT`（同族） |
| `CPP_HTTPLIB_LICENSE` | cpp-httplib | `The MIT License (MIT)` |
| `DLPACK_LICENSE` | DLPack | `Apache License`（2.0） |
| `PICOJSON_LICENSE` | picojson | 见文件原文 |
| `XGRAMMAR_LICENSE` | XGrammar | `Apache License`（2.0） |
| `XGRAMMAR_NOTICE` | XGrammar NOTICE | 声明文本 |

> 其余引擎二进制本体（~662MB）依 T-317 裁决 B 不入 git，由 `scripts/fetch_ollama.sh` 按官方来源落位；
> 版本与 sha256 登记见该目录 `BUNDLE_INFO.txt`。

### 3.5 图标

| 来源 | 许可 | 文本 | 上游 |
|---|---|---|---|
| Lucide Icons and Contributors | **ISC** | [`licenses/ISC-Lucide.txt`](licenses/ISC-Lucide.txt) | <https://github.com/lucide-icons/lucide> |
| Feather（Cole Bemis，Feather 派生字形） | **MIT** | [`licenses/MIT-Feather.txt`](licenses/MIT-Feather.txt) | <https://github.com/feathericons/feather> |

逐文件来源与许可亦写在每个 SVG 的头部注释（`SPDX-License-Identifier` + `Source` + `License` 三行），
其中 AcouScope 自绘图元（`play` / `stop` / `record` / `sidebar-left` / `sidebar-right`）为
**GPL-3.0-only (c) AcouScope contributors**，由 `scripts/derive_icon_styles.py` 派生 `macos|win|mint` 三风格。

### 3.6 模型权重（★ 事实陈述，未获授权不推定；**T-1051 起改运行时下载，不再随包分发**）

| 资产 | 大小（实测） | 上游来源（实读下载 URL） | 许可状态 | T-1051 处置 |
|---|---|---|---|---|
| `rmvpe.onnx` | **345MB**（361,688,443 字节） | <https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/rmvpe.onnx> | **上游未提供许可声明**（多次探测根目录无许可文件） | 本仓**不再再分发**，首次使用按需下载 |
| `swift_f0.onnx` | **390KB**（399,114 字节） | <https://github.com/mirkolotzek/swift-f0/releases/download/v0.1.0/swift_f0.onnx> | 同上：**上游未提供许可声明** | 同上 |

> **T-1051 处置（供应链 + 合规）**：两权重本仓**不再随发布物再分发**（仅附上游链接），改为**运行时下载**
> 到用户数据目录 `get_data_dir()/models/`；实现见 `analysis/backends/{rmvpe,swift_f0}.py`。
> **完整性校验**：因上游未公布官方 sha256，校验常量取本仓首次下载**实测值**（`rmvpe`
> `5370e71a…3660fd` / `swift_f0` `fa91bb45…8336a5`）——**仅防后续漂移，不能防首次 MITM**；
> 本文件不作「已获授权」或「可自由再分发」的推定。

---

## 4. 许可原文清单与取得途径

本仓 `licenses/` 目录存放本文件所引用的许可正文（**逐字原文，未作改写**）：

| 文件 | 许可 | 取得途径（来源） | 取得日期 | sha256（前 20 位） |
|---|---|---|---|---|
| `licenses/GPL-3.0.txt` | GPL-3.0 | 复制自本仓根 `LICENSE`（既有全文） | 2026-09-12 | `8b1ba204bb69a0ade2bf` |
| `licenses/LGPL-3.0.txt` | LGPL-3.0 | 本机随附逐字副本 `gmp 6.3.0` 的 `COPYING.LESSERv3`（165 行）；规范来源 <https://www.gnu.org/licenses/lgpl-3.0.txt> | 2026-09-12 | `a853c2ffec1705787234` |
| `licenses/GPL-2.0.txt` | GPL-2.0 | 本机随附逐字副本 `xz 5.8.3` 的 `COPYING.GPLv2`（338 行）；规范来源 <https://www.gnu.org/licenses/old-licenses/gpl-2.0.txt> | 2026-09-12 | `edaef632cbb643e4e7a2` |
| `licenses/MIT-llama.cpp.txt` | MIT | 复制自本仓 `src/acouscope/resources/bin/LICENSE-llama.cpp.txt` | 2026-09-12 | `94f29bbed6a22c35b992` |
| `licenses/ISC-Lucide.txt` | ISC | <https://raw.githubusercontent.com/lucide-icons/lucide/main/LICENSE>（HTTP 200） | 2026-09-12 | `b495047bd93a9b069135` |
| `licenses/MIT-Feather.txt` | MIT | <https://raw.githubusercontent.com/feathericons/feather/main/LICENSE>（HTTP 200） | 2026-09-12 | `308028e93fcf84972523` |

---

## 5. 未核实项与已知限制（诚实标注）

1. **gnu.org 直连受限**：本机 `curl https://www.gnu.org/...` 返回 `SSL_ERROR_SYSCALL`（HTTP 000，2026-09-12 实测），
   故 GPL-2.0 / LGPL-3.0 正文取自**本机随附的逐字副本**（sha256 见 §4），并在表中同时记录规范来源 URL。
   如需 FSF 直连原文核验，请在可联网环境按 §4 的规范 URL 复核。
2. **模型权重许可**：`rmvpe.onnx` / `swift_f0.onnx` 上游均未提供许可文件 → 再分发依据未核实（见 §3.6）。
   **T-1051 起本仓不再再分发权重**，改为运行时下载 + 仅附上游链接；校验值为本仓首次下载实测（非上游公布）。
3. **FFmpeg 构建来源与补丁**：`bin/ffmpeg` 构建来源未记录，是否含本地修改/补丁未核实（见 §3.2）。当前发布物
   **仍随包分发**该 arm64 静态二进制（47MB，未超出 GitHub 100MB 硬限），未走运行时下载。
4. **Ollama 个别许可名**：`GO_LICENSE` / `LLAMA_CPP_VENDORS_LICENSE` / `PICOJSON_LICENSE` 为多段原文，
   本文件不臆断其 SPDX 标识，以文件原文为准。
5. 本文件**不构成法律意见**；发布前如需，应由权利人/法务复核。
