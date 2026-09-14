<p align="center">
  <img alt="Jinyun SonicAI" src="docs/images/jinyun-logo.png" height="72">
  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  <img alt="AcouScope" src="docs/images/acouscope-icon.png" height="72">
</p>

<h1 align="center">AcouScope · 音析</h1>

<p align="center"><b>面向音樂學與數位人文的音訊分析軟體</b><br>
從音訊匯入到學術級出圖 —— 全部核心分析演算法以純 NumPy 自主實作。</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-GPL--3.0--only-blue" alt="授權條款：GPL-3.0-only">
  <img src="https://img.shields.io/badge/python-3.10%2B-green" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey" alt="平台">
  <img src="https://img.shields.io/badge/status-beta-orange" alt="Beta">
</p>

<p align="center">
  <a href="https://acouscope.vercel.app">官方網站</a> ·
  <a href="#安裝">安裝</a> ·
  <a href="#核心特性">核心特性</a> ·
  <a href="#功能模組">功能模組</a> ·
  <a href="#環境需求">環境需求</a> ·
  <a href="#專案結構">專案結構</a> ·
  <a href="#技術棧">技術棧</a> ·
  <a href="#路線圖">路線圖</a> ·
  <a href="#致謝">致謝</a> ·
  <a href="#授權條款">授權條款</a>
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <a href="README.zh.md">简体中文</a> ·
  <b>繁體中文</b> ·
  <a href="README.ko.md">한국어</a> ·
  <a href="README.ja.md">日本語</a>
</p>

---

<p align="center">
  <img src="docs/images/screenshot-fft-spectrum.png" alt="AcouScope —— FFT 頻譜與諧波標記" width="820">
</p>

AcouScope（音析）是一款跨平台桌面音訊分析軟體，面向音樂學、民族音樂學、音樂心理學、聲景研究與
樂器聲學等研究場景。它涵蓋一條連續的工作流程：音訊匯入 → 訊號分析 → 學術級出圖。

全部核心分析演算法 —— FFT / STFT / 音高追蹤 / 共振峰擷取 / 音色特徵 —— 均直接基於 NumPy 自主
實作，不依賴 librosa、scipy 等第三方科學運算函式庫。分析鏈因此可逐行檢視，並在相同輸入的任意
機器上可重現。

## 核心特性

- **純 NumPy 自研演算法**：FFT / STFT / 音高追蹤 / 共振峰 / 音色特徵等核心分析引擎全部自主實作，
  核心分析鏈無第三方演算法函式庫依賴。
- **出版級出圖**：圖表所見即所得匯出（跟隨當前軸單位、縮放範圍與標記），支援 SVG / PDF / PNG
  等格式，DPI 可調。
- **三語介面**：簡體中文 / 繁體中文 / English 全量涵蓋（含所有右鍵選單與對話框）。
- **跨平台**：Windows、macOS、Linux。
- **主題系統**：跟隨系統深淺色 + 9 套完整配色，切換即時生效（圖表畫布保持學術白底）。
- **多維頻率軸**：Hz / kHz / MIDI / 鋼琴捲簾 / 音分 / Mel 一鍵切換，鋼琴捲簾模式顯示直排
  鋼琴鍵盤標尺。

## 功能模組

### 時域分析
- 波形與包絡顯示、選區量測、正規化
- 去除開頭／結尾靜音（RMS 自適應閾值；支援另存新檔，或修改來源檔並自動備份）
- 訊號特徵：RMS 能量、過零率、峰值

### 頻域分析
- FFT 頻譜（窗函式 / FFT 大小可調）
- 諧波標記：預設標記基頻，自動偵測前 6 個分音；支援手動增刪（±100 音分吸附）
- 峰值保持、預設頻段快捷切換

### 時頻分析
- STFT 頻譜圖（純 NumPy 實作）
- 7 組色盤、動態範圍 / 對比度調節、對數頻率軸
- 峰值追蹤曲線、矩形量測工具
- 3D 頻譜圖（瀑布式三維算繪，14 組學術色盤，視角 / 邊距參數面板即時調節）

### 音高分析
- 基頻（F0）追蹤
- A4 參考頻率可調、參考線開關
- SOTA 深度後端：RMVPE / SwiftF0（ONNX，離線推論）。**首次使用 RMVPE / SwiftF0 會按需下載權重**
  （RMVPE ≈ 345MB，SwiftF0 ≈ 390KB，下載至使用者資料目錄；詳見 `THIRD-PARTY-NOTICES.md` §3.6）

### 共振峰分析
- LPC 法 F1–F4 共振峰擷取與軌跡顯示

### 音色特徵
- MFCC 係數、諧波雜訊比（HNR）
- 頻譜質心 / 頻寬 / 衰減 / 滾降

### 即時與室內聲學
- 即時特徵面板：頻段能量滾動線、即時對數頻譜、頻段能量條、場景視覺化 —— 四視窗聯動
  （● LIVE 錄入模式，CSV 匯出）
- 室內模態分析：室內共振頻率計算

### 輔助能力
- AI 釋圖：AI 以音樂聲學審稿人視角解讀分析結果（付費功能）
- 音訊編輯：波形視窗選區編輯
- 169 條輪換提示（操作技巧 + 研究幽默）

## 安裝

### 從原始碼執行

```bash
# 方式一：Poetry
git clone https://github.com/sfk8815-create/AcouScope.git
cd AcouScope/acouscope
poetry install
poetry run acouscope

# 方式二：pip（虛擬環境）
python3.10 -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
PYTHONPATH=src python -m acouscope   # Windows: set PYTHONPATH=src
```

支援格式：WAV / MP3 / FLAC / AIFF 等（soundfile 0.12+）。

> **FFmpeg** —— 本倉庫**不內建** ffmpeg 二進位檔（體積考量）。播放或匯出 `.mp3` / `.m4a` 等
> 非無損格式需要本機 ffmpeg：執行 `bash scripts/fetch_ffmpeg.sh`（下載 macOS arm64 靜態版並做
> sha256 校驗），或 `brew install ffmpeg`。

### 安裝套件

Windows 10 (x64)、macOS 12+ (Intel x86_64)、Linux（Ubuntu AppImage / Arch pacman）的安裝套件已在
發布流程中；**四平台簽章與公證版本**安排在 v0.99 發行（見 [路線圖](#路線圖)）。在此之前請從原始碼執行。

### 開發環境

```bash
poetry install --with dev

# 回歸測試（pytest）
poetry run pytest --ignore tests/test_realtime_panel.py
```

## 環境需求

- Python 3.10+
- PyQt6 + pyqtgraph
- matplotlib
- soundfile（播放經 QtMultimedia，pyaudio 為可選後備）

可選增強（缺少時自動回退，核心功能不受影響）：pyaudio、pydub、samplerate、scipy。

## 專案結構

```
AcouScope/
├── acouscope/                  # 應用程式原始碼樹
│   ├── src/acouscope/
│   │   ├── ai/                 # AI 釋圖（提示詞、授權閘控）
│   │   ├── analysis/           # 分析服務（音高、共振峰、音色、靜音偵測等）
│   │   ├── annotation/         # 標註
│   │   ├── app/                # 應用層（控制器、專案、偏好）
│   │   ├── audio/              # 音訊 I/O（讀寫、播放、錄音、編輯）
│   │   ├── dsp/                # DSP 引擎（FFT、STFT、窗函式、單位換算）
│   │   ├── i18n/               # 國際化（zh_CN / zh_TW / en_US）
│   │   ├── plugins/            # 外掛（預留）
│   │   ├── resources/          # 資源檔（LOGO、圖示、內建執行環境）
│   │   ├── ui/                 # GUI 層（主視窗、主題、控制項、對話框）
│   │   ├── utils/              # 工具函式（設定）
│   │   └── visualization/      # 視覺化與出圖
│   ├── tests/                  # 回歸測試（pytest）
│   ├── scripts/                # 建置腳本
│   └── AcouScope.spec          # PyInstaller 打包設定
├── scripts/                    # 倉庫層級輔助腳本（如 fetch_ffmpeg.sh）
├── docs/images/                # 本 README 使用的圖片
└── THIRD-PARTY-NOTICES.md
```

## 技術棧

| 類別 | 技術 |
|------|------|
| 語言 | Python 3.10+ |
| GUI | PyQt6 + pyqtgraph |
| 音訊分析 | NumPy（純自研演算法） |
| 音訊 I/O | soundfile（播放經 QtMultimedia，pyaudio 為可選後備） |
| 出版級出圖 | matplotlib |
| 測試 | pytest / pytest-qt |

## 路線圖

- **v0.98（Beta，當前）** —— 九大分析引擎 + 三語介面 + 主題系統 + 出版級匯出
- **v0.99** —— 四平台安裝套件正式發行、程式碼簽章（Windows Authenticode / Apple 公證）
- **v1.0** —— 批次處理、外掛機制、常 Q 變換 / 小波變換，正式發布

## 致謝

- [PyQt](https://www.qt.io/qt-for-python) —— Python Qt 綁定
- [pyqtgraph](https://pyqtgraph.readthedocs.io/) —— 高效能即時繪圖
- [matplotlib](https://matplotlib.org/) —— 出版級出圖
- [Sonic Visualiser](https://www.sonicvisualiser.org/) —— 設計靈感來源

### 特別鳴謝

謹以此軟體特別鳴謝並獻予**韓寶強教授**——音樂聲學領軍學者，中華人民共和國國務院特殊津貼專家。

## 授權條款

**GPL-3.0-only**

本專案因依賴 **PyQt6（GPL-3.0-only）**，整體以 **GPL-3.0-only** 散布。第三方元件授權條款見
[`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md)。

### 版權與作者

© 西南大學·音樂聲學實驗室 · 西南大學·藝術人類學研究所 · 西南大學·中國音樂心理健康研究所

作者：**石豐愷**（Fengkai Shi）—— sfklc@hotmail.com
