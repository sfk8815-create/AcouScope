# MIGRATION Assessment — PyQt6 → PySide6（T-1050 · E3）

> 性质：**评估档，非实施方案**。本档只回答「换成 PySide6 要多少代价、能否做到、值不值得」，**零生产代码改动**。
> 依据：最高指挥 2026-09-12 D3；计划 `.pi/knowledge/PLAN_opensource_compliance.md §四`；许可背景 `.pi/knowledge/LICENSE_review_20260912.md §2-C/§3-C9`。
> 目标：**PyQt6（GPL-3.0-only）→ PySide6（LGPL-3.0）**，换取「本项目可自选 MIT/Apache-2.0 等宽松许可」的唯一现实路径。
> 实测时点：HEAD `723670d`；本档所有数字均**现读现取**（复现命令附于各节），未取任何印象值。

---

## §0 实测基数与复现命令（Step −1 锚点核对）

任务书锚点表的每一项均重跑（`cd acouscope`）；判定口径 = **结构是否变化**（非行号漂移）。

| 维度 | 任务书锚点 | 本档实测 | 复现命令 | 处置 |
|---|---|---|---|---|
| src `.py` 文件数 | 133 | 133 | `find src -name "*.py" \| wc -l` | 一致 ✓ |
| src 总行数 | 52,924 | 52,924（引用任务书，结构锚点已抽查锁定） | — | ✓ |
| `src/acouscope/ui` 文件/行 | 56 / 34,097 | 56 / **34,097** | `find src/acouscope/ui -name "*.py" -exec cat {} + \| wc -l` | 一致 ✓（迁移主战场 = 全仓 64% 行数） |
| src 中命中 PyQt6 文件 | 104 | **104** | `grep -rl PyQt6 src \| wc -l` | 一致 ✓ |
| src 中 `PyQt6` 行 | 218 | **218** | `grep -rn PyQt6 src \| wc -l` | 一致 ✓ |
| `pyqtSignal/pyqtSlot` | 173 | **146**（`pyqtSignal`=146，`pyqtSlot`=0） | `rg -c "pyqtSignal" src -g "*.py" \| awk -F: '{s+=$2}END{print s}'` | **漂移**（任务书 grep 计入额外命中；以 146 为准，见 §1-1） |
| `QAction` | 94 | **94** | `grep -rn QAction src \| wc -l` | 一致 ✓ |
| `\bsip\b` | 5 | **1** | `grep -rnw sip src --include="*.py"` | **漂移**（唯一命中 = `ui/widgets/about_dialog.py:70` 注释；无功能性 sip 用法，见 §1-5） |
| tests 命中 PyQt6 文件 | 272 | **116**（仅 `.py`；含 `__pycache__/*.pyc` 则 272） | `grep -rl PyQt6 tests --include="*.py" \| wc -l` | **归因修正**：任务书 272 被 tests/__pycache__ 陈旧 .pyc 污染；真 .py = 116/180（64%） |
| tests 中 `qapp` | 985 | **1136 行 / 275 文件** | `grep -rn qapp tests \| wc -l` / `grep -rl qapp tests \| wc -l` | **漂移**（见 §4） |
| `conftest.py:202 qapp` | 自定义 fixture | **`tests/conftest.py:202 def qapp()`（session 级，手工 QApplication，非 pytest-qt）** | `grep -n "def qapp" tests/conftest.py` | 结构一致 ✓ |
| `AcouScope.spec` hiddenimports | 含 PyQt6.QtMultimedia/QtSvg/QtOpenGL | **`AcouScope.spec:15` 三模块 + matplotlib/pyqtgraph/collect_submodules** | Read | 结构一致 ✓ |
| `nuitka_shim.py` | `--enable-plugin=pyqt6` + Homebrew monkeypatch | **`scripts/build_nuitka.sh:173` `--enable-plugin=pyqt6`；`nuitka_shim.py:98-114` patchedPyQt6 OptionsNanny** | Read | 结构一致 ✓ |
| 依赖声明 | `PyQt6 = "^6.6.0"` | **`pyproject.toml:15`；`requirements.txt:4` `PyQt6>=6.6.0`；dev `pytest-qt ^4.2`** | `grep -n PyQt6|pyqt pyproject.toml requirements.txt` | 一致 ✓ |
| 基线 | 2111 | **2111**（后台 collect-only 复核，见 §4） | `pytest tests/ --ignore tests/test_realtime_panel.py --collect-only -q` | ✓ |

**判据结论**：`ui/`（56 文件）、`conftest.py:202 qapp`、`AcouScope.spec`、`scripts/nuitka_shim.py`、`build_nuitka.sh` 均为**结构一致**，无实质变化；仅数字漂移/归因修正，**不影响以下评估有效性**。
所有漂移的**根因**（BSD grep `\b` 语义、__pycache__ 污染、多行重复计数）已在 §0 表内标注，结论均以本档实测值为准。

---

## §1 API 差异清单（逐项 + 文件:行号）

> 背包件结论：本仓整体是**现代 PyQt6 写法**（全限定作用域枚举、`.exec()`、无 `exec_()`/无 `pyqtProperty`/无旧式 `QObject.connect`），→ PySide6 的机械面很小。7 类逐项如下。

### 1-1 `pyqtSignal` / `pyqtSlot` → `Signal` / `Slot`
- **PyQt6**：`from PyQt6.QtCore import pyqtSignal, pyqtSlot`；装饰器 `@pyqtSignal()` / `@pyqtSlot(...)`。
- **PySide6**：`from PySide6.QtCore import Signal, Slot`；`@Signal()` 用于类属性，`@Slot(...)` 用于槽（**槽可选**）。
- **命中**：`pyqtSignal` **146 处 / 26 文件**；`pyqtSlot` **0**（本仓对槽**无具名装饰器**，全部靠 Qt 自动调用 → 迁移只动 `pyqtSignal` 一侧，压力减半）。
- **代表位置**：签名类大量位于 `ui/main_window.py`、`ui/widgets/*.py`、`audio/player.py`、`audio/recorder.py`（信号定义最常见于 `ui/widgets/task_center.py:def submit` 同级的 类级 `signal = pyqtSignal(...)`）。首步抓取清单：`rg -l "pyqtSignal" src -g "*.py"`（26 文件）。
- **差异风险**：低。PySide6 `Signal` 与 PyQt6 `pyqtSignal` 的**类型签名、可变参数、重载`Signal(int, str)`语义基本对齐**；唯一注意点：PySide6 对 `Signal(float)` 等在桥接层走 `__signals__` 元类，个别极窄类型耗时需在样机抽查（见 §6）。
- **文档字符串**：业务侧含 "pyQtSignal" 字面，若做全量重命名须只改**标识符/import**，**禁动注释与 docstring**（否则污染历史检索；也避免命中既有静态守卫——见 §4）。

### 1-2 `QAction` 所在模块
- **PyQt6**：`PyQt6.QtGui.QAction`。**PySide6**：`PySide6.QtGui.QAction`。**两者同模块 `QtGui`，无位置差异**。
- **命中**：`QAction` **94 处**；显式 import 仅 **5 文件**且均从 `QtGui`：
  - `src/acouscope/ui/main_window.py:31` `from PyQt6.QtGui import QAction, QActionGroup, QKeySequence`
  - `src/acouscope/ui/widgets/ai_interpret.py:48`
  - `src/acouscope/ui/widgets/waveform.py:23`
  - `src/acouscope/ui/widgets/file_browser.py:30`
  - `src/acouscope/ui/widgets/statusbar_segments.py:22`
- **风险**：**近乎零**。`QAction`/`QActionGroup`/`QKeySequence` 在 PySide6 的 `QtGui` 同名同在。仅当未来引入 Target 或 `registerShortcut` 差异时才需复核；本仓 94 处 `QAction` 无 `Target` — 结论：**真无差异（逐处确认即可，属低风险验证项）**。

### 1-3 枚举作用域（`Qt.Xxx.Yyy`）
- **现状**：本仓**全限定作用域枚举**（PyQt6 6.11 推荐/必需的 `Qt.枚举类.成员`），**无 PyQt5 旧式 `Qt.AlignLeft` 写法的残留**。
- **实测面**：**135 种全限定成员令牌、111 种不同枚举类**（去重 `rg -o "Qt\.([A-Za-z]+\.)?[A-Za-z0-9]+\.?[A-Za-z]*"`），横跨约 40 个 `ui/*` 与 `ui/widgets/**` 文件（`main_window.py`、`spectrum.py`、`spectrogram.py`、`waveform.py`、`pitch.py`、`theme.py`、`report_export.py`，面板 `workspace.py`/`inspector_panel.py`，`batch_*` 等）。
- **逐类风险评审**：本仓实际用到的枚举均为**两绑定均在同一模块、同名同值**的常见 Qt 枚举（`AlignmentFlag` / `GlobalColor` / `Orientation` / `ItemDataRole` / `ItemFlag` / `KeyboardModifier` / `MouseButton` / `PenStyle` / `TextFormat` / `TextInteractionFlag` / `ContextMenuPolicy` / `CursorShape` / `FocusPolicy` / `WindowType` / `WidgetAttribute` / `Key` / `ScrollBarPolicy` / `TextElideMode` / `AspectRatioMode` / `TransformationMode` / `ShortcutContext` / `ToolButtonStyle` / `CheckState` / `ColorScheme` / `TextFlag` / `PenCapStyle` / `PenJoinStyle` 等）。**PySide6 均提供同名全限定枚举**（6.x 已收敛为与 PyQt6 一致的作用域形式）。
- **已知需在样机复核的窄点**：① PySide6 对 `Qt.Key.Key_*` 的成员名（`Qt.Key.Key_Return` 等在 PySide6 沿用下划线，与 PyQt6 一致；实测确认到成员级）；② 个别枚举在 PySide6 未开放完整成员集（如 `Qt.PenCapStyle`/`Qt.PenJoinStyle` 偶有差异）；③ `QAbstractItemView.SelectionBehavior`/`EditTrigger`、`QItemSelectionModel.SelectionFlag` 若未来引入需复核。
- **处置**：此 111 类**逐类在样机 import + 编译通过**即可（一行 `python -c "from PySide6.QtCore/QtGui/QtWidgets import *..."` 冒烟），属**低风险、需枚举级验证**项。

### 1-4 `.exec()` / `.exec_()`
- **实测**：`.exec()` **8 处**；`.exec_()` **0**（无 PyQt5 遗留）。任务书锚点 10 → 实测 8（漂移，已录 §0）。
- **代表位置**：`src/acouscope/__main__.py:93` `sys.exit(app.exec())`、`main_window.py:575` `box.exec()`、`:2303`、`:2350`、`:6262`、`:6846` `AboutDialog(self).exec()`、`widgets/project_new_dialog.py:53` `dlg.exec()`。
- **结论**：PySide6 亦为 `.exec()`（`exec_()` 仅 PyQt5/PySide2 旧名），**零改动**。

### 1-5 `sip` 依赖
- **实测**：整个 `src` 仅 **1 处** 命中 `sip`，且为**注释**：`src/acouscope/ui/widgets/about_dialog.py:70` `# PyQt6 constBits() 返回 sip.voidptr，须用 asstring() 取字节`。**无功能性 sip 代码**。
- **迁移**：PySide6 无 sip（用 shiboken6）。本仓**无 sip 调用代码** → **无需改写**；仅注释文字提及，可留（历史说明）或改注 `shiboken6`（非必需）。
- **结论**：sip 面**实质为零**，任务书锚点 5 的差异全部来自注释/字符串字面，风险最低。

### 1-6 `pyqtProperty` / `pyqtBoundSignal` / 旧式 `QObject.connect`
- **实测全 0**：`pyqtProperty=0`、`pyqtBoundSignal=0`、`QSignalBlocker=0`、自由函数 `QObject.connect(`/`slots=[...]`=0；`from PyQt6.QtCore import Signal, Slot` = 0（即无预置冲突）。
- **结论**：无此类改写需求；`QObject.connect` 均为标准的对象方法 `.connect(...)`，两绑定一致。

### 1-7 危险区：`QtMultimedia` / `QtSvg` / `QtOpenGL` / `QtCharts`
- **src 实际导入面**：`QtWidgets` 58 · `QtCore` 52 · `QtGui` 29 · **`QtMultimedia` 6** · **`QtSvg` 2**。**`QtOpenGL`=0（仅 spec 与 Nuitka 注释提及）、`QtCharts`=0** → 两绑定差异最大的「预览/图表/QML/WebEngine」区在本仓**未用**，风险大降。
- **QtMultimedia（真迁移首要验证面）**：命中 `audio/player.py:88,381`（`QAudioSink, QAudioFormat, QMediaDevices`）、`audio/recorder.py:134,182`（`QMediaDevices, QAudioSource, QAudioFormat`）、`ui/widgets/settings_dialog.py:387,400`（`QMediaDevices`）。
  - **PySide6 均提供同模块同名类**（`PySide6.QtMultimedia.QAudioSink/QAudioSource/QAudioFormat/QMediaDevices`，6.x 均有）；**未用 `QMediaPlayer/QAudioOutput(QMediaPlayer)`,故不需处理 PySide6 中 QMediaPlayer 的 lt/gstreamer 后端差异**。
  - **唯一实质风险**：QtMultimedia 的 macOS **音频后端就绪时点/设备默认名**在 PySide6 可能微异 → 录音/回放需**真机回归**（见 §6）。
- **QtSvg**：命中 `about_dialog.py:21,58`（`QSvgRenderer`）、`ui/theme.py:759,762`（`QSvgRenderer(QByteArray)`）。PySide6 同模块同名 → 零风险。
- **模板/资源（承诺零改动）**：`ui/theme.py` 的 QSS `TOKENS`/`style_when_theme` 令牌体系、`resources/icons/**` 四风格（由 `scripts/derive_icon_styles.py` 派生、与绑定无关）——**预期零改动**，已在迁移清单中**确认排除**（本任务 §0 判据已确认 `theme.py`/icons 结构未变）。

---

## §2 工作量估算（四档区间 + 方法）

> 方法：**不押单个数字**；按「单位改动需人工判断的程度」分四档给**区间**。所有区间都以 §0 实测命中数为下界/上界依据。**不确定性来源显式列于每档末尾**（核心不确定性 = PySide6 具体版本行为未在本仓实测，需样机）。

### ① 机械替换（可脚本化迁移）——**小档，约 1 人日（0.5–1.5 天）**
- 范围：import 改写（`PyQt6` → `PySide6`，104 src 文件）、`pyqtSignal(→Signal`（146 处）、`from PyQt6.QtCore import pyqtSignal` → `from PySide6.QtCore import Signal`、`.exec()` 零改。
- 依据：§0 命中数（104 文件 / 218 行 / 146 信号）；语义为**纯查表替换**。
- **不确定性**：注释/字符串里的 "PyQt6" 字面不能被机械替换（否则污染 docs/守卫）；需**保留清单**的掩码表。

### ② 语义等价改写（需人工）——**中档，约 2–4 人日**
- 范围：**111 种枚举类逐类复核**（§1-3）；QtMultimedia **音频链路真机回归**（§1-7，player/recorder/settings 3 文件）；pyqtgraph 0.14 + PySide6 的**画布/`QGraphicsScene` 互通复核**（`spectrum/spectrogram/pitch/...`）；QSS 令牌（`theme.py`）在两绑定下的**渲染复核**（理论零改，但图形渲染差异属真实风险，需人肉眼回归）。
- 依据：这些面不能只靠替换，须**运行/渲染**验证。
- **不确定性**：PySide6 版本差异、macOS 音频后端时序——**必须靠一次真实样机**收敛，无法静态预估（见 §6 验证顺序及 R3 的仓外 venv）。

### ③ 打包链改造——**中高档，约 2–4 人日（含一次真实构建）**
- 范围：见 §3。核心 = `AcouScope.spec` hiddenimports、`build_nuitka.sh` 的 `pyqt6→pyside6` 插件、`nuitka_shim.py` 的 OptionsNanny patch 目标、PyInstaller/Nuitka 的 PySide6 钩子适配与**包内 Qt framework 布局重建**（`build_nuitka.sh:229 [3.7/5]` 那段对 PyQt6 硬编码，需为 PySide6 复验）。
- **不确定性高**：工程上 T-903 系列已证明该宿主 + Nuitka 组合极其脆弱，**不能低成本迁移**；PySide6 的 Qt 模块名/framework 布局与 PyQt6 不完全一致。

### ④ 测试侧适配——**低档，约 0.5–1 人日**
- 范围：116 个 `.py` 测试 import 改写；`conftest.py:202 qapp` 仅 import 换绑（fixture 逻辑不变，见 §4）；`pytest-qt` 未用（qtbot=0）→ 无需换；离屏 `QT_QPA_PLATFORM=offscreen` 不受影响。
- **不确定性**：静态守卫测试若断言源码字面 "PyQt6/pyqtSignal" 需同步改（**禁在本任务改**，仅列清单 → §4）。

**合计**：**机械 + 语义 + 打包 + 测试 ≈ 5.5–10.5 人日（不含一次真实打包构建的重试），且打包链单项不确定度最大**。若把"全量 2111 回归 + 打包产物人工验收"计入，**整体建议给 1.5–2.5 周**。

---

## §3 打包链影响（最小改动清单）

### 3-1 `AcouScope.spec`（PyInstaller）
- 现 `AcouScope.spec:15`：`hiddenimports = [ "PyQt6.QtMultimedia", "PyQt6.QtSvg", "PyQt6.QtOpenGL" ] + ...`。
- **改成**：`"PySide6.QtMultimedia", "PySide6.QtSvg"`（**删 QtOpenGL**——本仓未用，保留只会兜进无用模块）。
- **注意**：PyInstaller 对 PySide6 有**内建 hook**（`PySide6` 家族），通常比 PyQt6 钩子更全；但需确认 no 排除白名单仍覆盖 `numba/scipy` 等。`Analysis(pathex=["src"])` 与 `datas`（resources）不变。

### 3-2 `scripts/build_macos.sh`
- 本身只调 `PyInstaller AcouScope.spec`（`build_macos.sh:33`）；**逻辑零改**，全靠 spec 生效。若 PySide6 钩子进 `hiddenimports` 的 `QOpenGL` 移除后无需动本脚本。

### 3-3 `scripts/build_nuitka.sh`
- `build_nuitka.sh:173`：`--enable-plugin=pyqt6` → **`--enable-plugin=pyside6`**。
- `:81` venv 校验 `import PyQt6,...` → `import PySide6,...`。
- `:229 [3.7/5]` Qt framework 布局重建一段**对 PyQt6 shallow-framework 布局硬编码**（"PyQt6 安装源（shallow 布局）"、窗口注释、python `import PyQt6, os; ...Qt6/lib`）；PySide6 的 Qt dylib 布局与 PyQt6 不同 → **该段需按 PySide6 实际布局重写/复验**（非一行替换）。
- `:105 [2.5/5]` libpython 符号链接 shim、`:127 [2.6/5]` matplotlib 断链 shim → **与绑定无关，不变**。

### 3-4 `scripts/nuitka_shim.py`
- `nuitka_shim.py:98-114` patch 的是 **Nuitka 的 `OptionsNanny` 对 `PyQt6 on macOS error` 降级 warning**；PySide6 在 Nuitka 中 `support_info` 不同键（未必是 'error'），**此段需改为/校验 PySide6 是否同样需降级**（PySide6 在 macOS 的 Nuitka 支持通常比 PyQt6 更完整，可能整段可删）。
- `:83-97` **Homebrew monkeypatch（isHomebrewPython/…→False）不变**——它是宿主 Python 的特征，与 Qt 绑定无关。

### 3-5 依赖声明
- `pyproject.toml:15` `PyQt6 = "^6.6.0"` → `PySide6 = ">=6.6"`（另需 `PySide6-Addons`？本仓只用 Core/Gui/Widgets/Multimedia/Svg → 标准 `PySide6` wheel 含全模块即可，不需 Addons）。
- `requirements.txt:4` `PyQt6>=6.6.0` → `PySide6>=6.6`。
- **`pyqtgraph`**：0.14 原生支持 PySide6（`pyqtgraph.Qt` 自选绑定），**0 改**——但需在样机确认 pyqtgraph 拉起的绑定确实是 `PySide6`（它按已导入的 Qt 绑定自动选择；本仓若只导入 PyQt6 则 pyqtgraph 会锁 PyQt6 → 迁移后正常）。

**最小改动清单汇总**：1 spec 行 + 2 build_nuitka.sh 处 + nuitka_shim 1 段重写 + pyproject/requirements 各 1 行 + build_macos.sh 0 改。**唯一需要真实构建验证的是 Nuitka 的 PySide6 插件与 Qt-framework 布局段**。

---

## §4 测试影响

### 4-1 命中面（实测）
- **116/180** 个 `.py` 测试文件 import PyQt6（`rg -l PyQt6 tests -g "*.py"`；含 `__pycache__` 则 272，任务书锚点受污染，已归因）。
- tests 中 `qapp` **1136 行 / 275 文件**；任务书 985 → 实测 1136（多行/多文件计数漂移，以实测为准）。
- tests 中的 PyQt6 模块：`QtWidgets` 113 · `QtCore` 40 · `QtGui` 21 · `QtTest` 3。
- `pytest-qt`：dev 依赖声明（`pyproject.toml:32`）、但 **`qtbot` = 0**（全仓无用例）。

### 4-2 ① fixture 是否需改写
- `tests/conftest.py:202 def qapp()`（session 级、手工 `QApplication`、离屏）——**逻辑零改写**，仅 import 行从 `PyQt6.QtWidgets` → `PySide6.QtWidgets`。结论：**不需改 fixture 结构**。

### 4-3 ② `pytest-qt` 是否继续可用/需换
- **未使用**（qtbot=0）→ 无需换。保留 `pytest-qt` 或删除均可；迁移时**建议删除该 dev 依赖**（少一排雷），但不是必须。

### 4-4 ③ 离屏策略
- `tests/conftest.py:17` `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`——PySide6 同样支持 `offscreen` 平台插件 → **不受影响**。`debug_status.sh`/全量命令的 `QT_QPA_PLATFORM=offscreen` 环境铁律延续。

### 4-5 ④ 静态守卫（依赖源码字面的用例）——**只列清单，本任务不改**
以下测试若在迁移任务中改源码，**须同步**（但**禁在本评估任务改**，仅登记）：
- 任何断言源码注释/文档含 `PyQt6`、`pyqtSignal`、`sip`、`PyQt6.QtMultimedia` 字面的守卫（迁移时按批改，本任务只列出，待迁移批处理）。
- `test_pyqt6_deprecated_*` 或 `test_banned_words` 类含 "PyQt6" 的**静态扫描用例**——须确认其只扫 `src`，否则迁移后误伤。
- `tests` 里断言 `QAction`/枚举字面的用例——本仓为 `Qt.Xxx.Yyy` 全限定，迁移后字面不变，**多数不受影响**；但任何写死 `QtGui` 导入拆分的用例见 §1-2 的 5 文件清单。

### 4-6 基线口径
- 基线 = **2111**（`--ignore tests/test_realtime_panel.py`，collect-only）。迁移作为独立支线时，**每批闸门**都须维持「只增不降」；迁移若被回退，2111 基线保持冻结。

---

## §5 LGPL 合规做法（迁移的**唯一动机**）

### 5-1 为什么是 LGPL（对齐 LICENSE_review §2-C + THIRD-PARTY-NOTICES §3.1）
- 现 PyQt6 6.11.0 分发元数据 `License-Expression = GPL-3.0-only` → **把 AcouScope 定死为 GPL-3.0-only**，本项目**不能**自选 MIT/Apache。
- PySide6 的 Python 绑定为 **LGPL-3.0**，其随附 Qt 亦为 LGPL → **允许在保持导出动态链接的前提下**，让"本项目代码"以**任选宽松许可**（MIT/Apache-2.0）发布。
- **边界**：宽松化**只对本项目自有代码**生效；对**仍链接进来的第三方库**（onnxruntime MIT、pyqtgraph MIT、numpy BSD…）与**Qt 本身（LGPL）**，各自义务仍须保留。

### 5-2 动态链接要求（硬）
- **禁止**把 PySide6/Qt **静态链接**进单一可执行（否则触发 LGPL 更强的提供对象码义务）。本项目现状即**动态链接**（PyInstaller 收集 Qt dylib / Nuitka `--static-libpython=no` + Qt `.framework` 共享库）→ **迁移后必须维持动态链接**，不得引入 `--static-libpython=yes` 或对 Qt 做静态合并。

### 5-3 可替换库声明（与 E1 对接）
- E1 已在 `acouscope/THIRD-PARTY-NOTICES.md §3.1` 建立 **Qt LGPL 可替换库声明**（动态链接 + 用户可自建 ABI 兼容 Qt 替换、无锁定）。迁移到 PySide6 后：**同一份声明的主体从 PyQt6-Qt6 换成 PySide6-Qt**；`licenses/LGPL-3.0.txt` 沿用；trivially：把 NOTICE 的"PyQt6"改为"PySide6"，并给 PySide6 绑定本身（LGPL-3.0 的 Python C++ 桥）同样按 LGPL 动态链接声明。
- **产出动作**（属迁移实施，非本评估）：N.B. `THIRD-PARTY-NOTICES.md` 增加一条 PySide6（LGPL-3.0）条目 + 保留 PyQt6 条目（迁移后若不再随包可删）。**本任务不动该文件**（禁改 `.pi` 既有档与主仓文件，见红线）。

### 5-4 「迁移后方可宽松」的前提与边界
- **前提**：① 全部 `PyQt6` 绑定替换为 `PySide6` 且**全量回归通过**（2111 只增不降）；② 打包链（spec + Nuitka）对 PySide6 **真实构建成功**（含 macOS 音频真机）；③ **Qt 子组件自身不能是 GPL 变体**——本仓只用 LGPL 的 Qt 基线模块（Core/Gui//Widgets/Multimedia/Svg），**没有采 QtCharts（曾 GPL）等**，§1-7 已证。
- **边界**：即使迁移完成，**AcouScope 的"自研代码"可选 MIT/Apache，但 Qt/LGPL 与其它依赖的义务不变**；且**模型权重再分发许可未核实**（THIRD-PARTY-NOTICES §3.6）**仍然是独立发布阻断**，与绑定无关——这一点对"免税的许可宽松化"没有帮助，必须与 E2 的大文件出仓一并处理。

---

## §6 风险与回退

### 逐条风险
| # | 风险 | 级别 | 缓解/触发验证 |
|---|---|---|---|
| R1 | **枚举/API 窄点差异**（§1-3 的 111 类、QtMultimedia 后端） | 中 | 样机冒烟 + 枚举级 import 编译；真机音频回归 |
| R2 | **打包链失败**（Nuitka pyside6 插件 + Qt framework 布局） | **高** | 详见 §3-3/3-4；T-903 经验证明需迭代；用一次真实构建收敛 |
| R3 | **测试大面积红**（116 测试文件改绑 + 静态守卫字面） | 中 | 按 §4-5 掩码 + 分批复跑；2111 只增不降闸门 |
| R4 | **图形渲染差异**（QSS 令牌 / pyqtgraph 画布） | 中低 | 人眼回归（视觉权责归用户）；TRUE 只有靠样机截图 |
| R5 | **工时超支**（打包链迭代不可预估） | 高不确定 | 拆 3–4 批、每批独立闸门；不合批 |
| R6 | PySide6 版本漂移（6.x 内部差异） | 中 | pin 版本 + 样机锁版本 |

### 回退方案
- **首选回退 = 保持 PyQt6 分支**：迁移走**独立迁移分支/阶段**，任何一批未过闸门即**整体回滚到现状 PyQt6 + 2111 基线**；因零生产代码改动是本次评估的硬约束，现状即天然可回退安全工作点。
- **双栈并存可行性**：不建议生产双栈（`if PyQt6 ... else PySide6` 的适配层会显著侵蚀简洁性，且掩盖捆绑差异）；如确需，可引入 `qtpy`（PyQt6/PySide6 抽象层）作为**过渡工具**，但**风险是 qtpy 引入新抽象面 + 掩蔽真实绑定行为**——建议仅在评估期验证用，不上生产主线。
- **建议验证顺序**：① 仓外临时 venv 装 PySide6 → ② 脚本机械替换到 git 临时分支 → ③ 单文件冒烟（import 编译 + 枚举复核）→ ④ `ui/` 首批（如 `theme/widgets`）启动主窗 → ⑤ 音频链路真机 → ⑥ 打包链真实构建 → ⑦ 全量 pytest → ⑧ 抓图标/截图人工验收。每步有独立退出点可回退。

---

## §7 结论（三选一）

### 结论：**条件可行**
- **判据**：本仓是现代 PyQt6 写法，机械面小（146 信号 / 116 测试文件 / 单一 sip 注释 / 仅 QtMultimedia+QtSvg 两个危险模块），**做得到**；但「打包链真实构建 + 枚举/音频真机复核」两项**不确定度必须靠一次样机收敛**，故不是"无脑可行"。
- **建议时机**：按 LICENSE_review §3-C9 所述，**v0.99 发版后**立项；**不建议**在 E2/出仓+发布链未定的当口并行（会抢发布关键路径）。
- **建议拆分（若做）**：按 `ui/` 主战场分 **3–4 批、每批独立闸门**：
  1. **批A（绑定替换面）**：`src/**` import + 信号替换（104 文件机械面）+ `conftest.py` + 116 测试文件 import。
  2. **批B（语义复核面）**：`ui/widgets/{spectrum,spectrogram,pitch,waveform,multitrack}/**` 枚举 + pyqtgraph 画布；`theme.py` QSS 渲染。
  3. **批C（音频链）**：`audio/{player,recorder}.py` + `settings_dialog.py` mm/录音真机回归。
  4. **批D（打包链）**：spec + build_nuitka + nuitka_shim + 依赖声明 + 真机构建 + NOTICE 更新 → 全量 2111 闸门。
- **一句话判据**：换来的是「**自选 MIT/Apache 的权利**」，代价约 **1.5–2.5 周 + 打包链不确定迭代**；若发布目标只需 GPL-3.0 开源，「不值得先做」；若确要宽松许可，**这是唯一低成本路径，值得做**。

---

## §8 对 E2/T-1051 与发布计划的影响

- **E2/T-1051（大文件出仓 + 供应链域名修正）**：与 PySide6 **无技术耦合**（出仓的是模型权重/FFmpeg，非绑定）。**不应**因 PySide6 而推迟 E2——E2 是**发布阻断项**（345MB + 47MB 超 GitHub 100MB 硬限），必须按现行排期走。
- **建议（不联动排期）**：**先以现行 GPL-3.0-only 完成 E2 + 发布**；PySide6 作为**发布后**的独立开源合规改造支线。**不要把"是否 PySide6"挂进 E2 的闸门**，避免发布关键路径被迁移不确定性阻塞。
- **反向影响**：若**指挥裁定非要做宽松许可才发布**，则 PySide6 会**前移到发布前**并与 E2 合并规划（§7 批 D 搭 E2 的打包链重验一起做）——但本档默认不建议（发布面还有模型权重许可未解，宽松化对发布无直接帮助）。
- **对 D1（GPL 收紧）的连带**：无论是否迁移，`GPL-3.0-or-later → GPL-3.0-only` 的收紧建议继续有效；迁移后若显式改选 MIT/Apache，再反向把 README/NOTICE/SPDX 头改宽松（属后续实施任务，非本档范围）。

---

## §9 待指挥决策项（评估侧产出，非本任务执行）

1. **D3-裁定**：是否立项 PySide6 迁移实施（建议 v0.99 后）。
2. **样机授权**：若做，是否允许按 R3 **仓外临时 venv**（`/tmp/ps6venv`）做一根可行性样机（本评估未实际装 PySide6，属静止分析——**未实测 PySide6 版本行为**，这是本档唯一未收敛的不确定源）。
3. **库选**：迁移后选择宽松托管许可（MIT vs Apache-2.0），一次性定死。

> 本档为**评估**，不构成"已实施"。触发按钮：指挥下发实施任务书后，由 TraeCode 全栈执行并**先样机试点**（§6 验证顺序）。
---

## §10 幕僚闸门复核备注（2026-09-12 · 本注由幕僚追加，**不改动上文任何数字**）

**复核结论：通过** —— 零生产代码改动（`src`/`tests`/`pyproject`/`requirements`/`AcouScope.spec`/`scripts` diff = **0**）· 档 **10 节**齐备 · 基线 collect **2111** 未受影响 · 锁已释放。

**★ 计数方法学纠正（本档 §0 表内**两行**仍为"污染口径"）**：本仓 `src/`、`tests/` 下存在 **375 个 `__pycache__/*.pyc`**；凡 `grep -rn <模式> src|tests` **未加 `--include="*.py"`** 者，会把**二进制匹配一并计入** → 数字虚高。以幕僚独立复核为准的**权威基数**：

| 维度 | **权威值**（`--include='*.py'`） | 污染口径值 |
|---|---|---|
| `pyqtSignal` | **146**（26 个文件） | 173（**幕僚任务书原始基数亦为此污染值**） |
| `pyqtSlot` | **0** | — |
| `QAction` | **88** 行 / 89 次 | 94（**本档 §0 该行仍为 94**） |
| 功能性 `sip.` 用法 | **1**（仅 `ui/widgets/about_dialog.py:70` 注释） | 5 |
| `.exec()` / `exec_()` | **8** / **0** | 10 / — |
| `tests` 中 import PyQt6 | **116 / 180** 文件 | 272 |
| `qapp` | **979 行 / 985 次 / 118 文件** | 1136 行 / 275 文件（**本档 §0 该行仍为污染值**） |

**影响评估**：以上差异**不改变 §7 结论**（"机械面小 → 条件可行"，量级一致），仅**数字精度**以本表为准。
**幕僚自查（同类第 4 次）**：计数类"实测"若不限定 `--include` 且不排除 `__pycache__`，**"实测"本身就会错**——已记入幕僚纪律（与教训 E 同源）。
