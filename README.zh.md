<p align="center">
  <img alt="Jinyun SonicAI" src="docs/images/jinyun-logo.png" height="72">
  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  <img alt="AcouScope" src="docs/images/acouscope-icon.png" height="72">
</p>

<h1 align="center">AcouScope · 音析</h1>

<p align="center"><b>面向音乐学与数字人文的声学分析软件</b><br>
从音频导入到学术级出图 —— 全部核心分析算法以纯 NumPy 自主实现。</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-GPL--3.0--only-blue" alt="许可证：GPL-3.0-only">
  <img src="https://img.shields.io/badge/python-3.10%2B-green" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey" alt="平台">
  <img src="https://img.shields.io/badge/version-0.99.20260925_Beta-orange" alt="版本 0.99.20260925（Beta）">
</p>

<p align="center">
  <a href="https://acouscope.vercel.app">官网</a> ·
  <a href="#安装">安装</a> ·
  <a href="#核心特性">核心特性</a> ·
  <a href="#功能模块">功能模块</a> ·
  <a href="#环境要求">环境要求</a> ·
  <a href="#项目结构">项目结构</a> ·
  <a href="#技术栈">技术栈</a> ·
  <a href="#路线图">路线图</a> ·
  <a href="#致谢">致谢</a> ·
  <a href="#许可证">许可证</a>
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <b>简体中文</b> ·
  <a href="README.zh-TW.md">繁體中文</a> ·
  <a href="README.ko.md">한국어</a> ·
  <a href="README.ja.md">日本語</a>
</p>

---

<p align="center">
  <img src="docs/images/screenshot-main-waveform.png" alt="AcouScope —— 主界面：波形与分析" width="820">
</p>

AcouScope（音析）是一款跨平台桌面声学分析软件，面向音乐学、民族音乐学、音乐心理学、声景研究与
乐器声学等研究场景。它覆盖一条连续的工作流：音频导入 → 信号分析 → 学术级出图。

全部核心分析算法 —— FFT / STFT / 音高追踪 / 共振峰提取 / 音色特征 —— 均直接基于 NumPy 自主实现，
不依赖 librosa、scipy 等第三方科学计算库。分析链路因此可逐行审视，并在相同输入的任意机器上
可复现。

## 核心特性

- **纯 NumPy 自研算法**：FFT / STFT / 音高追踪 / 共振峰 / 音色特征等核心分析引擎全部自主实现，
  核心分析链路无第三方算法库依赖。
- **出版级出图**：图表所见即所得导出（跟随当前轴单位、缩放范围与标记），支持 SVG / PDF / PNG
  等格式，DPI 可调。
- **三语界面**：简体中文 / 繁体中文 / English 全量覆盖（含所有右键菜单与对话框）。
- **跨平台**：Windows、macOS、Linux。
- **主题系统**：跟随系统深浅色 + 9 套完整配色，切换即时生效（图表画布保持学术白底）。
- **多维频率轴**：Hz / kHz / MIDI / 钢琴卷帘 / 音分 / Mel 一键切换，钢琴卷帘模式显示竖排
  钢琴键盘标尺。

## 功能模块

### 时域分析
- 波形与包络显示、选区测量、归一化
- 去除开头/结尾静默（RMS 自适应阈值；支持另存新文件，或修改源文件并自动备份）
- 信号特征：RMS 能量、过零率、峰值

### 频域分析
- FFT 频谱（窗函数 / FFT 大小可调）
- 谐波标记：默认标记基频，自动检测前 6 个分音；支持手动增删（±100 音分吸附）
- 峰值保持、预设频段快捷切换

### 时频分析
- STFT 语谱图（纯 NumPy 实现）
- 7 组色板、动态范围 / 对比度调节、对数频率轴
- 峰值追踪曲线、矩形测量工具
- 3D 频谱图（瀑布式三维渲染，14 组学术色板，视角 / 边距参数面板实时调节）

### 音高分析
- 基频（F0）追踪
- A4 参考频率可调、参考线开关
- SOTA 深度后端：RMVPE / SwiftF0（ONNX，离线推理）。**首次使用 RMVPE / SwiftF0 会按需下载权重**
  （RMVPE ≈ 345MB，SwiftF0 ≈ 390KB，下载到用户数据目录；详见 `THIRD-PARTY-NOTICES.md` §3.6）

### 共振峰分析
- LPC 法 F1–F4 共振峰提取与轨迹显示

### 音色特征
- MFCC 系数、谐波噪声比（HNR）
- 频谱质心 / 带宽 / 衰减 / 滚降

### 实时与房间声学
- 实时特征面板：频段能量滚动线、实时对数频谱、频段能量条、场景可视化 —— 四窗口联动
  （● LIVE 录入模式，CSV 导出）
- 房间模态分析：房间共振频率计算

### 辅助能力
- AI 释图：AI 以音乐声学审稿人视角解读分析结果（付费功能）
- 音频编辑：波形窗口选区编辑
- 169 条轮换提示（操作技巧 + 科研幽默）

## 安装

### 从源码运行

```bash
# 方式一：Poetry
git clone https://github.com/sfk8815-create/AcouScope.git
cd AcouScope/acouscope
poetry install
poetry run acouscope

# 方式二：pip（虚拟环境）
python3.10 -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
PYTHONPATH=src python -m acouscope   # Windows: set PYTHONPATH=src
```

支持格式：WAV / MP3 / FLAC / AIFF 等（soundfile 0.12+）。

> **FFmpeg** —— 本仓库**不内置** ffmpeg 二进制（体积原因）。播放或导出 `.mp3` / `.m4a` 等
> 非无损格式需要本地 ffmpeg：运行 `bash scripts/fetch_ffmpeg.sh`（下载 macOS arm64 静态版并做
> sha256 校验），或 `brew install ffmpeg`。

### 安装包

Windows 10 (x64)、macOS 12+ (Intel x86_64)、Linux（Ubuntu AppImage / Arch pacman）的安装包已在
发布流程中；**四平台签名与公证版本**安排在 v0.99 发行（见 [路线图](#路线图)）。在此之前请从源码运行。

### 开发环境

```bash
poetry install --with dev

# 回归测试（pytest）
poetry run pytest --ignore tests/test_realtime_panel.py
```

## 环境要求

- Python 3.10+
- PyQt6 + pyqtgraph
- matplotlib
- soundfile（播放经 QtMultimedia，pyaudio 为可选后备）

可选增强（缺失时自动回退，核心功能不受影响）：pyaudio、pydub、samplerate、scipy。

## 项目结构

```
AcouScope/
├── acouscope/                  # 应用源码树
│   ├── src/acouscope/
│   │   ├── ai/                 # AI 释图（提示词、许可门控）
│   │   ├── analysis/           # 分析服务（音高、共振峰、音色、静默检测等）
│   │   ├── annotation/         # 标注
│   │   ├── app/                # 应用层（控制器、项目、偏好）
│   │   ├── audio/              # 音频 I/O（读写、播放、录音、编辑）
│   │   ├── dsp/                # DSP 引擎（FFT、STFT、窗函数、单位换算）
│   │   ├── i18n/               # 国际化（zh_CN / zh_TW / en_US）
│   │   ├── plugins/            # 插件（预留）
│   │   ├── resources/          # 资源文件（LOGO、图标、内置运行时）
│   │   ├── ui/                 # GUI 层（主窗口、主题、控件、对话框）
│   │   ├── utils/              # 工具函数（配置）
│   │   └── visualization/      # 可视化与出图
│   ├── tests/                  # 回归测试（pytest）
│   ├── scripts/                # 构建脚本
│   └── AcouScope.spec          # PyInstaller 打包配置
├── scripts/                    # 仓库级辅助脚本（如 fetch_ffmpeg.sh）
├── docs/images/                # 本 README 使用的图片
└── THIRD-PARTY-NOTICES.md
```

## 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| GUI | PyQt6 + pyqtgraph |
| 声学分析 | NumPy（纯自研算法） |
| 音频 I/O | soundfile（播放经 QtMultimedia，pyaudio 为可选后备） |
| 出版级出图 | matplotlib |
| 测试 | pytest / pytest-qt |

## 路线图

- **v0.99.20260925（Beta，当前）** —— 九大分析引擎 + 三语界面 + 主题系统 + 出版级导出；四平台安装包正式发行准备中 —— 本内测版**有意未做代码签名/公证**，首启遇阻请按官网「遇到问题怎么办」指引操作
- **v1.0** —— 批处理、插件机制、常 Q 变换 / 小波变换，正式发布

## 致谢

- [PyQt](https://www.qt.io/qt-for-python) —— Python Qt 绑定
- [pyqtgraph](https://pyqtgraph.readthedocs.io/) —— 高性能实时绘图
- [matplotlib](https://matplotlib.org/) —— 出版级出图
- 同类声学可视化软件 —— 设计灵感来源

### 特别鸣谢

谨以此软件特别鸣谢并献予**韩宝强教授**——音乐声学领军学者，中华人民共和国国务院特殊津贴专家。

## 许可证

**GPL-3.0-only**

本项目因依赖 **PyQt6（GPL-3.0-only）**，整体以 **GPL-3.0-only** 分发。第三方组件许可见
[`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md)。

### 版权与作者

© 西南大学·音乐声学实验室 · 西南大学·艺术人类学研究所 · 西南大学·中国音乐心理健康研究所

作者：**石丰恺**（Fengkai Shi）—— sfklc@hotmail.com
