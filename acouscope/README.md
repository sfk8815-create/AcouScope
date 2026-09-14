# AcouScope · 音析

**版本：0.98_20160830 (Beta)**

面向音乐与数字人文领域研究的跨平台音频分析软件。

## 项目简介

AcouScope（音析）是一款专业的音频分析桌面软件，专为音乐与数字人文领域研究设计，覆盖音乐学、民族音乐学、音乐心理学、声景研究与乐器声学等方向。它提供从音频导入、信号分析到学术级出图的一站式工作流。全部核心分析算法以纯 numpy 自主实现，不依赖 librosa / scipy 等第三方科学计算库，从底层保障研究结果的自主可控与可复现性。

## 核心特性

- **纯 numpy 自研算法**：FFT / STFT / 音高追踪 / 共振峰 / 音色特征等核心分析引擎全部自主实现，无第三方算法库依赖
- **出版级出图**：图表所见即所得导出（跟随当前轴单位、缩放范围与标记），支持 SVG / PDF / PNG 等格式，DPI 可调
- **三语界面**：简体中文 / 繁体中文 / English 全量覆盖（含所有右键菜单与对话框）
- **跨平台**：Windows、macOS、Linux
- **主题系统**：跟随系统深浅色 + 9 套完整配色，切换即时生效（图表画布保持学术白底）
- **多维频率轴**：Hz / kHz / MIDI / 钢琴卷帘 / 音分 / Mel 一键切换，钢琴卷帘模式显示竖排钢琴键盘标尺

## 功能模块

### 时域分析
- 波形与包络显示、选区测量、归一化
- 去除开头静默（RMS 自适应阈值，支持另存新文件或修改源文件+自动备份）
- RMS 能量、过零率、峰值等信号特征

### 频域分析
- FFT 频谱（窗函数 / FFT 大小可调）
- 谐波标记：默认标记基频，自动检测前 6 个分音；支持手动增删（±100 音分吸附）
- 峰值保持、预设频段快捷切换

### 时频分析
- STFT 语谱图（纯 numpy 实现）
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
- 实时特征面板：频段能量滚动线、实时对数频谱、频段能量条、场景可视化四窗口联动（● LIVE 录入模式，CSV 导出）
- 房间模态分析：房间共振频率计算

### 辅助能力
- AI 释图：AI 以音乐声学审稿人视角解读分析结果（付费功能）
- 音频编辑：波形窗口选区编辑
- 169 条轮换提示（操作技巧 + 科研幽默）

## 安装

### 从源码运行

```bash
# 方式一：poetry
git clone <repository-url>
cd acouscope
poetry install
poetry run acouscope

# 方式二：pip（构建包方式）
python3.10 -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
PYTHONPATH=src python -m acouscope   # Windows: set PYTHONPATH=src
```

支持格式：WAV / MP3 / FLAC / AIFF 等（soundfile 0.12+）。

### 安装包

- **Windows 10 (x64)**：`AcouScope-0.98.20160830-setup-x64.exe`（Inno Setup 安装程序，支持简中/英文安装界面与文件关联）——需 VC++ 2015–2022 运行库
- **macOS 12+ (Intel x86_64)**：`AcouScope-0.98.20160830-macOS-x86_64.dmg`（Apple Silicon 需 Rosetta）——首次打开若提示"已损坏"，执行 `xattr -dr com.apple.quarantine /Applications/AcouScope.app`
- **Linux**：Ubuntu AppImage / Arch 系 pacman 包（构建向导见各构建包文件夹）

### 开发环境

```bash
poetry install --with dev

# 运行测试（403 项回归）
poetry run pytest
```

## 项目结构

```
acouscope/
├── src/acouscope/          # 主包
│   ├── ai/                 # AI 释图（提示词、许可门控）
│   ├── analysis/           # 分析服务（音高、共振峰、音色、静默检测等）
│   ├── annotation/         # 标注
│   ├── app/                # 应用层（控制器、项目、偏好）
│   ├── audio/              # 音频 I/O（读写、播放、录音、编辑）
│   ├── dsp/                # DSP 引擎（FFT、STFT、窗函数、单位换算）
│   ├── i18n/               # 国际化（zh_CN / zh_TW / en_US）
│   ├── plugins/            # 插件（预留）
│   ├── resources/          # 资源文件（LOGO 等）
│   ├── ui/                 # GUI 层（主窗口、主题、控件、对话框）
│   ├── utils/              # 工具函数（配置）
│   └── visualization/      # 可视化与出图
├── tests/                  # 单元测试（24 个文件，403 项）
├── scripts/                # 构建脚本
└── AcouScope.spec          # PyInstaller 打包配置
```

## 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| GUI | PyQt6 + pyqtgraph |
| 音频分析 | numpy（纯自研算法） |
| 音频 I/O | soundfile（播放经 QtMultimedia，pyaudio 为可选后备） |
| 出版级出图 | matplotlib |
| 测试 | pytest / pytest-qt |

可选增强（缺失时自动回退，核心功能不受影响）：pyaudio、pydub、samplerate、scipy。

## 路线图

- **v0.98 (Beta，当前)**：九大分析引擎 + 三语界面 + 主题系统 + 出版级导出
- **v0.99**：四平台安装包正式发行、代码签名（Windows Authenticode / Apple 公证）
- **v1.0**：批处理、插件机制、常 Q 变换 / 小波变换，正式发布

## 许可证

GPL-3.0-only

本项目因依赖 **PyQt6（GPL-3.0-only）**，整体以 **GPL-3.0-only** 分发；第三方组件许可见 `THIRD-PARTY-NOTICES.md`。

## 致谢

- [PyQt](https://www.qt.io/qt-for-python) - Python Qt 绑定
- [pyqtgraph](https://pyqtgraph.readthedocs.io/) - 高性能实时绘图
- [matplotlib](https://matplotlib.org/) - 出版级出图
- [Sonic Visualiser](https://www.sonicvisualiser.org/) - 设计灵感来源

## 特别鸣谢

谨以此软件特别鸣谢并献予**韩宝强教授**——音乐声学领军学者，中华人民共和国国务院特殊津贴专家。
