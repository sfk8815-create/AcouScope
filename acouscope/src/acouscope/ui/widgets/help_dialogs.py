# SPDX-License-Identifier: GPL-3.0-only
"""帮助文档对话框：快速入门与用户手册。

内容随界面语言切换（zh_CN / zh_TW / en_US，缺省回退 en_US）。
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTextBrowser,
    QPushButton,
)

from acouscope.i18n import tr, get_language

# ------------------------------------------------------------------
# 快速入门内容（按语言）
# ------------------------------------------------------------------

QUICK_START: dict[str, str] = {
    "zh_CN": """
<h2>快速入门</h2>
<ol>
<li><b>启动与首启</b>：首次使用音高检测的在线引擎（SwiftF0 / RMVPE）时，应用会自动下载模型（含校验）并内置；此后可<b>离线</b>使用。</li>
<li><b>打开音频</b>：文件 → 打开（{sc_open}），支持 WAV / FLAC / MP3 / AIFF / OGG，内置解码，无需外部编码器。</li>
<li><b>三栏认识</b>：左栏导航与页签（文件 / 设置） · 中央画布（上波形、下分析） · 右栏检查器（含 AI 释图）。</li>
<li><b>播放与播放头</b>：空格播放 / 暂停，点击波形任意位置定位播放头。</li>
<li><b>选择区段</b>：波形上左键拖动建立选区；Delete 删除，{sc_undo} 撤销。</li>
<li><b>切换分析视图</b>：F2 频谱 · F3 语谱 · F4 音高 · F5 共振峰 · F6 音色 · F7 3D · F8 房间模态。</li>
<li><b>三套音高引擎</b>：pYIN（流式 / 实时） · SwiftF0（轻量离线） · RMVPE（复音、嘈杂人声），在音高面板选择。</li>
<li><b>音律标尺</b>：工具 → 音律标尺叠加层（F9），把十二平均律以外的律制音级参考线叠到语谱图与音高视图上，读微分音与律制偏差。</li>
<li><b>图表设计器</b>：工具 → 图表设计器（或分析工具栏），实时预览、白底导出，适合论文配图。</li>
<li><b>AI 释图</b>：右栏 → AI 释图（Ctrl+I），读取谱峰 / 泛音 / 共振峰，输出 Markdown 段落草稿。</li>
<li><b>白底导出</b>：图形导出（SVG / PDF / PNG）恒为白底、所见即所得（{sc_export}）。</li>
<li><b>工作区开关组</b>：工具栏右侧「批处理」等全铺页开关互斥、再点收回；左栏打开文件 / 设置。</li>
<li><b>偏好设置</b>：设置 → 偏好设置（{sc_settings}），切换语言（简 / 繁 / EN）、9 套主题、图标风格。</li>
<li><b>快捷键三连</b>：空格 = 播放 / 暂停；Delete = 删除选区；Shift + 拖拽 = 联动分析指针。</li>
<li><b>去哪看更多</b>：帮助 → 用户手册，含 20 节完整说明。</li>
</ol>
<p>完整说明请查看 <b>帮助 → 用户手册</b>。</p>
""",
    "zh_TW": """
<h2>快速入門</h2>
<ol>
<li><b>啟動與首啟</b>：首次使用音高偵測的線上引擎（SwiftF0 / RMVPE）時，應用會自動下載模型（含校驗）並內建；此後可<b>離線</b>使用。</li>
<li><b>開啟音訊</b>：檔案 → 開啟（{sc_open}），支援 WAV / FLAC / MP3 / AIFF / OGG，內建解碼，無需外部編碼器。</li>
<li><b>三欄認識</b>：左欄導覽與頁籤（檔案 / 設定） · 中央畫布（上波形、下分析） · 右欄檢查器（含 AI 釋圖）。</li>
<li><b>播放與播放頭</b>：空白鍵播放 / 暫停，點擊波形任意位置定位播放頭。</li>
<li><b>選擇區段</b>：波形上左鍵拖動建立選區；Delete 刪除，{sc_undo} 復原。</li>
<li><b>切換分析視圖</b>：F2 頻譜 · F3 語譜 · F4 音高 · F5 共振峰 · F6 音色 · F7 3D · F8 房間模態。</li>
<li><b>三套音高引擎</b>：pYIN（串流 / 即時） · SwiftF0（輕量離線） · RMVPE（複音、嘈雜人聲），在音高面板選擇。</li>
<li><b>音律標尺</b>：工具 → 音律標尺疊加層（F9），把十二平均律以外的律制音級參考線疊到語譜圖與音高視圖上，讀微分音與律制偏差。</li>
<li><b>圖表設計器</b>：工具 → 圖表設計器（或分析工具列），即時預覽、白底匯出，適合論文配圖。</li>
<li><b>AI 釋圖</b>：右欄 → AI 釋圖（Ctrl+I），讀取譜峰 / 泛音 / 共振峰，輸出 Markdown 段落草稿。</li>
<li><b>白底匯出</b>：圖形匯出（SVG / PDF / PNG）恆為白底、所見即所得（{sc_export}）。</li>
<li><b>工作區開關組</b>：工具列右側「批次」等全鋪頁開關互斥、再點收回；左欄開啟檔案 / 設定。</li>
<li><b>偏好設定</b>：設定 → 偏好設定（{sc_settings}），切換語言（簡 / 繁 / EN）、9 套主題、圖示風格。</li>
<li><b>快速鍵三連</b>：空白鍵 = 播放 / 暫停；Delete = 刪除選區；Shift + 拖曳 = 聯動分析指標。</li>
<li><b>去哪看更多</b>：說明 → 使用者手冊，含 20 節完整說明。</li>
</ol>
<p>完整說明請參閱 <b>說明 → 使用者手冊</b>。</p>
""",
    "en_US": """
<h2>Quick Start</h2>
<ol>
<li><b>Startup</b>: the first time you use an online pitch engine (SwiftF0 / RMVPE), the model is downloaded and verified automatically and bundled in; afterwards it works <b>offline</b>.</li>
<li><b>Open audio</b>: File → Open ({sc_open}). Supports WAV / FLAC / MP3 / AIFF / OGG with built-in decoding — no system encoder needed.</li>
<li><b>Three panes</b>: left navigation and tabs (Files / Settings) · center canvas (waveform on top, analysis below) · right inspector (including AI Interpretation).</li>
<li><b>Play and playhead</b>: Space toggles play / pause; click anywhere on the waveform to position the playhead.</li>
<li><b>Select a region</b>: drag with the left button on the waveform; Delete removes it, {sc_undo} undoes.</li>
<li><b>Switch analysis views</b>: F2 Spectrum · F3 Spectrogram · F4 Pitch · F5 Formants · F6 Timbre · F7 3D · F8 Room Modes.</li>
<li><b>Three pitch engines</b>: pYIN (streaming / real-time) · SwiftF0 (lightweight offline) · RMVPE (polyphonic, noisy vocals), chosen in the Pitch panel.</li>
<li><b>Tuning ruler</b>: Tools → Tuning Ruler Overlay (F9) overlays the scale-degree reference lines of a selected tuning on the spectrogram and pitch views, for reading microtones and tuning deviations.</li>
<li><b>Chart Designer</b>: Tools → Chart Designer (or the Analysis toolbar); live preview, white-background export, ideal for figures.</li>
<li><b>AI Interpretation</b>: right inspector → AI Interpretation (Ctrl+I); reads spectral peaks / harmonics / formants and drafts Markdown paragraphs.</li>
<li><b>White-background export</b>: chart export (SVG / PDF / PNG) is always on a white background, WYSIWYG ({sc_export}).</li>
<li><b>Workspace switch group</b>: the full-pane toggles on the toolbar (e.g. Batch) are mutually exclusive; clicking again collapses back to the regular workspace.</li>
<li><b>Preferences</b>: Settings → Preferences ({sc_settings}) to switch language (简体 / 繁體 / English), 9 themes and icon style.</li>
<li><b>Three key habits</b>: Space = play / pause; Delete = delete selection; Shift + drag = linked analysis pointer.</li>
<li><b>Learn more</b>: Help → User Manual, a full 20-section guide.</li>
</ol>
<p>See <b>Help → User Manual</b> for the full documentation.</p>
""",
}

# ------------------------------------------------------------------
# 用户手册内容（按语言）
# ------------------------------------------------------------------

MANUAL: dict[str, str] = {
    "zh_CN": """
<h2>用户手册</h2>
<p>AcouScope 是面向音乐与数字人文领域研究的声学分析软件。核心算法纯 NumPy 实现，界面基于 PyQt6。</p>

<h3>1. 界面概览</h3>
<ul>
<li><b>最左 ribbon（全局工具）</b>：网站 / 帮助 / 设置等全局入口；<b>设置固定置底</b>，始终可快速打开。</li>
<li><b>左栏</b>：面板头 + 页签入口（文件 / 设置）；可拖拽调宽，可折叠。</li>
<li><b>中央常规工作区</b>：上方波形、下方分析视图（波形 / FFT / 语谱 / 音高 / 共振峰 / 音色 / 3D）。</li>
<li><b>全铺页</b>：批处理等页面铺满中央、取代常规工作区，经工作区开关组进入。</li>
<li><b>右栏</b>：检查器与 AI 释图；AI 释图也可用固定键 Ctrl+I 呼出。</li>
<li><b>状态栏</b>：位于底部，显示任务状态、提示与选区信息。</li>
<li><b>工作区开关组</b>：工具栏右侧一组全铺页开关（批处理等）互斥；当前页再点即收回常规工作区。</li>
<li><b>三栏分界线</b>：各栏之间悬停浮现 ◁‖▷ 抓手，拖拽改变栏宽，双击收回 / 展开。</li>
</ul>

<h3>2. 加载与播放</h3>
<ul>
<li><b>打开音频</b>：文件 → 打开（{sc_open}），支持 WAV / FLAC / MP3 / AIFF / OGG。</li>
<li><b>内置解码</b>：以上格式均可直接打开，内置 FFmpeg，无需外部编码器（完整包 full 内置；core 小包不含——core 包打开这类格式会提示失败，请改用完整包或自行安装 FFmpeg）。</li>
<li><b>播放 / 暂停 / 停止</b>：空格播放 / 暂停，Shift+空格停止，Esc 停止播放并取消选区。</li>
<li><b>播放头定位</b>：在波形上单击任意处定位播放头，也可用时间码输入。</li>
<li><b>缩放</b>：放大 / 缩小（Ctrl+= / Ctrl+-）、适应窗口（Ctrl+0）、缩放到选区（Shift+Z）。</li>
<li><b>试听选区</b>：建立选区后按 P 试听选区。</li>
<li><b>A/B 循环</b>：按 L 开启 / 关闭选区的循环播放。</li>
<li><b>录音</b>：按 R 开始 / 停止录音（需输入设备），录音结果进入当前工程。</li>
</ul>

<h3>3. 波形编辑（Audacity 风格）</h3>
<ul>
<li><b>建立选区</b>：波形上左键拖动；单击（或在选区外单击）清除选区。</li>
<li><b>剪切 / 复制 / 粘贴</b>：{sc_cut} / {sc_copy} / {sc_paste}；粘贴默认可替换选区。</li>
<li><b>删除选区</b>：Delete（或 Backspace）删除选定内容。</li>
<li><b>静音 / 裁剪</b>：{sc_silence} 静音选区；{sc_trim} 裁剪到选区。</li>
<li><b>撤销 / 重做</b>：{sc_undo} / {sc_redo} 支持多级撤销与重做。</li>
<li><b>全选 / 取消</b>：{sc_sel_all} 全选；Esc 取消选区。</li>
<li><b>分析指针联动</b>：按住 Shift 拖动波形上的分析指针，各分析视图游标同步跟随。</li>
<li><b>适用场景</b>：剪掉咳嗽、静音空隙、片段裁剪等轻量编辑。</li>
</ul>

<h3>4. FFT 频谱</h3>
<ul>
<li><b>视图</b>：分析 → FFT 频谱（F2）。</li>
<li><b>轴单位</b>：频率轴 Hz / kHz / MIDI / 钢琴键 / 音分 / Mel；幅度轴线性 / dB / dBFS / dB(A) / %。</li>
<li><b>谐波自动标注</b>：默认自动标注前 6 个谐波（相对主峰幅度 ≥ −60 dB，即 0.1%）。</li>
<li><b>手动增删标记</b>：左键在谱峰上添加（±100 音分吸附），右键移除。</li>
<li><b>FFT 参数</b>：FFT 大小（512–16384）与窗函数可选；窗口内无滚动条，便于完整截屏。</li>
<li><b>适用场景</b>：稳态音的谐波结构、乐器泛音、律制与微分音分析。</li>
<li><b>限制</b>：瞬态音谱峰较宽，标记吸附以音分为单位。</li>
<li><b>联动</b>：拖动波形区分析指针，频谱随乐段实时更新。</li>
</ul>

<h3>5. 语谱图</h3>
<ul>
<li><b>视图</b>：分析 → 语谱图（F3），时间-频率-能量三轴显示。</li>
<li><b>三轴</b>：横轴时间、纵轴频率、颜色表示能量强度。</li>
<li><b>FFT 参数</b>：FFT 大小（512–16384）、帧移比例、窗函数可调。</li>
<li><b>色板与动态范围</b>：7 种色板；动态范围与对比度可调。</li>
<li><b>频率轴</b>：支持线性 / 对数频率轴。</li>
<li><b>游标联动</b>：时间游标与波形指针双向联动。</li>
<li><b>适用场景</b>：瞬态、语音、音色随时间演变、共振峰走向。</li>
<li><b>提示</b>：要看清低频细节可缩小 FFT 大小提升时间分辨率，或改用对数轴。</li>
</ul>

<h3>6. 音高检测</h3>
<ul>
<li><b>视图</b>：分析 → 音高（F4）。</li>
<li><b>三套引擎</b>：pYIN（流式 / 实时，20 音分 HMM 后处理） · SwiftF0（轻量离线，约 9.5 万参数） · RMVPE（复音、嘈杂人声增强）。</li>
<li><b>怎么选</b>：需要实时跟播看 → pYIN；需要轻量且较精确的离线分析 → SwiftF0；人声 / 复音内容 → RMVPE。</li>
<li><b>反量化连续音高</b>：引擎输出的音分网格经期望值 / 插值还原为连续 Hz，微分音与滑音不被吞掉。</li>
<li><b>离线后端非流式</b>：SwiftF0 / RMVPE 属于整体离线分析，需在独立线程中运行，结果在分析完成后返回。</li>
<li><b>耗时与量级</b>：SwiftF0 轻量（约 9.5 万参数）返回更快；RMVPE 对长音频需等待分析进度。</li>
<li><b>模型首次下载</b>：首次使用会自动下载模型（含校验），此后可离线。</li>
<li><b>钢琴卷帘</b>：音高曲线叠加钢琴键位（C4 标注中央 C），便于对照音符。</li>
<li><b>音分偏差</b>：显示与目标音高的音分偏差，适合律制研究。</li>
</ul>

<h3>7. 共振峰分析</h3>
<ul>
<li><b>视图</b>：分析 → 共振峰（F5）。</li>
<li><b>4 条轨迹</b>：LPC 逐帧提取 F1–F4 共振峰频率与带宽。</li>
<li><b>读法</b>：F1 与开合度相关、F2 与舌位前后相关，可辅助判断元音。</li>
<li><b>适用场景</b>：语音元音分析、歌唱共鸣、音色识别。</li>
<li><b>带宽含义</b>：窄峰 = 稳定共振，宽峰 = 阻尼较大。</li>
<li><b>联动</b>：游标与波形指针联动，可逐帧观察。</li>
<li><b>限制</b>：LPC 阶数与帧内容相关，高噪声下轨迹可能抖动。</li>
<li><b>提示</b>：与语谱图对照观察共振峰能量带更直观。</li>
</ul>

<h3>8. 音色分析</h3>
<ul>
<li><b>视图</b>：分析 → 音色（F6）。</li>
<li><b>MFCC 含义</b>：梅尔倒谱系数刻画频谱包络（音色轮廓），不必深究其数学细节。</li>
<li><b>轨迹比较</b>：同一曲不同演奏、或不同乐器的特征轨迹可叠加比较。</li>
<li><b>频谱特征</b>：质心 / 锐度 / 通量 / 谐噪比（HNR）等。</li>
<li><b>适用场景</b>：同曲不同演奏、不同乐器的音色对比。</li>
<li><b>全局特征</b>：整段汇总的统计指标，可用于归档与检索。</li>
<li><b>限制</b>：音色判断需结合听觉与语境，数值只作参考。</li>
<li><b>提示</b>：先稳定选段、再用轨迹叠图，避免噪声干扰。</li>
</ul>

<h3>9. 3D 频谱图</h3>
<ul>
<li><b>视图</b>：分析 → 3D 频谱（F7）。</li>
<li><b>两种模式</b>：曲面与瀑布（含消隐）两种显示模式。</li>
<li><b>视角操作</b>：鼠标拖拽旋转、滚轮缩放，可复位视角。</li>
<li><b>参数</b>：FFT 大小、帧移、色板、动态范围同语谱图。</li>
<li><b>乐段</b>：默认前 10 秒，上限 60 秒。</li>
<li><b>幅度标尺</b>：线性 / dB / 归一化 %。</li>
<li><b>导出为白底</b>：图形导出恒为白底、所见即所得，与屏幕主题无关。</li>
<li><b>适用场景</b>：直观展示整段频谱结构，论文配图。</li>
</ul>

<h3>10. 实时特征（波形视图）</h3>
<ul>
<li><b>位置</b>：波形视图的实时特征区。</li>
<li><b>播放中实时计算</b>：起音（低 / 中 / 高频段）与 BPM 节拍估计。</li>
<li><b>起音读法</b>：各频段能量跳变即音符起始。</li>
<li><b>BPM</b>：播放中持续估计节拍速度。</li>
<li><b>适用场景</b>：边播边看，快速评估段落节奏与力度。</li>
<li><b>限制</b>：实时估计受噪声影响，仅供观察参考。</li>
<li><b>提示</b>：需要精确数值时用「分析 → 分析选区」。</li>
<li><b>与选区</b>：可先建立选区再在播放中对照。</li>
</ul>

<h3>11. 图表设计器</h3>
<ul>
<li><b>入口</b>：工具 → 图表设计器，或分析工具栏「图表设计器」，在中央全铺页打开。</li>
<li><b>实时预览</b>：增删内容或改样式即时刷新预览。</li>
<li><b>内容外壳</b>：标题、副标题、来源、脚注可分别编辑。</li>
<li><b>参考线 / 阈值线</b>：可按需叠加水平 / 垂直参考线与阈值线。</li>
<li><b>主题预设</b>：多套配色主题可切换。</li>
<li><b>样式 JSON</b>：样式可导入导出为 JSON，便于复用与团队统一。</li>
<li><b>导出恒白底</b>：导出为 SVG / PDF / PNG，恒为白底、所见即所得。</li>
<li><b>DPI 与尺寸</b>：位图导出可调 DPI 与目标尺寸。</li>
<li><b>适用场景</b>：论文配图、答辩、报告、归档。</li>
</ul>

<h3>12. AI 释图</h3>
<ul>
<li><b>入口</b>：右栏 → AI 释图，或菜单分析 → AI 释图（Ctrl+I）。</li>
<li><b>它能做什么</b>：读取谱峰 / 泛音 / 共振峰，生成论文段落草稿与观察描述。</li>
<li><b>Markdown 渲染</b>：结果支持表格 / 列表 / 代码块。</li>
<li><b>流式输出</b>：生成过程逐字显示，可提前查看。</li>
<li><b>操作按钮</b>：复制、重新生成、清空。</li>
<li><b>Provider</b>：可选云端或本地模型；本地模型首次使用自动下载（含校验），此后可离线。</li>
<li><b>引用建议</b>：输出会给出引用建议。</li>
<li><b>人工复核提醒</b>：AI 输出仅供研究者判断，需复核后使用。</li>
<li><b>限制</b>：准确性依赖输入与模型，涉数据结论务必人工核实。</li>
</ul>

<h3>13. 多轨工作台</h3>
<ul>
<li><b>入口</b>：分析 → 多轨对比，或工具栏进入；在中央全铺页并列显示多轨。再按一次 Ctrl+M（或轨道区左上的退出钮）即回到单轨。</li>
<li><b>加入多轨</b>：在左栏文件列表多选后点「加入多轨」；左栏折叠时该按钮先展开列表供你勾选，已展开仍无选中则弹出系统文件框直选。</li>
<li><b>轨头控件</b>：每条轨有名称 / 静音 / 独奏 / 音量 / 逐轨偏移 / 色彩等轨头控件。</li>
<li><b>轨身份色</b>：12 色内容色板与反馈色分家，便于区分轨道。</li>
<li><b>对比呈现</b>：一图（各轨音高曲线叠绘于同一时间轴，参考轨加粗）与多图（每轨一图、共享播放头与缩放）两种模式，另有密度热图开关（时间-频率总览，轨数少于 4 时默认关闭，可手动开启）。</li>
<li><b>差异统计</b>：点工具栏「差异统计」按钮触发，以参考轨为基准逐轨量化音高偏差（需 2 轨以上且非参考轨已有音高结果），结果驱动差异条、悬停读数与差异表 CSV 导出。</li>
<li><b>逐轨分析</b>：对每条轨分别选择分析视图与参数。</li>
<li><b>桥接任务中心</b>：逐轨分析会形成任务进入任务中心，可批量处理。</li>
<li><b>适用场景</b>：同曲不同演奏、不同设备现场录音对比，AB 对照。</li>
<li><b>限制</b>：多轨同时分析较耗资源，建议按需逐轨进行。</li>
<li><b>联动</b>：各轨游标同步，便于逐点对照；播放中共享播放头实时推进，各轨按自己的偏移量对齐显示。</li>
</ul>

<h3>14. 任务中心</h3>
<ul>
<li><b>入口</b>：工作区开关组 → 任务中心，或批处理入口。</li>
<li><b>任务与进度</b>：显示批处理任务列表与实时进度。</li>
<li><b>面板状态记忆</b>：任务中心面板的显隐与折叠状态会被记住。</li>
<li><b>长任务可继续操作</b>：任务在后台执行，界面仍可编辑与查看。</li>
<li><b>失败与重试</b>：失败任务可在列表查看原因并重试。</li>
<li><b>适用场景</b>：批量导出、批量分析。</li>
<li><b>限制</b>：并发增长会占用更多内存，避免一次提交过多。</li>
<li><b>提示</b>：完成 / 失败均有状态标识。</li>
</ul>

<h3>15. 田野元数据</h3>
<ul>
<li><b>用途</b>：语料与采录著录，便于归档、检索。</li>
<li><b>导出格式</b>：JSON / XML / CSV。</li>
<li><b>标识符</b>：Identifier，唯一标识每份采录。</li>
<li><b>题名 / 创作者</b>：Title 题名，Creator-Actor 创作者 / 表演者。</li>
<li><b>日期 / 地点</b>：Date、Location 采录时地。</li>
<li><b>流派 / 情境</b>：Context-Genre 说明语境与体裁。</li>
<li><b>技术信息</b>：采样率、位深、格式等随导出一并写入。</li>
<li><b>字段参考</b>：参考 IASA-TC 04 / IMDI / GB/T 31219.4 / DA/T 63，字段级对照已完成，并有机器校验闸守护。</li>
<li><b>自定义映射</b>：可自定义字段与导出目标字段的映射。</li>
</ul>

<h3>16. 导出</h3>
<ul>
<li><b>图形格式</b>：SVG / PDF（矢量）与 PNG（位图），DPI 可调。</li>
<li><b>恒白底</b>：导出图形恒为白底、所见即所得，与屏幕主题无关。</li>
<li><b>视角保留</b>：导出保留当前视角 / 模式 / 乐段选择。</li>
<li><b>图形入口</b>：文件 → 导出 → 导出图表（{sc_export}）。</li>
<li><b>音频格式</b>：WAV（无损）/ FLAC（无损压缩）/ MP3，内置解码。</li>
<li><b>音频入口</b>：文件 → 导出 → 音频。</li>
<li><b>常见失败原因</b>：未加载音频 / 目标目录无写权限 / 选区为空等。</li>
<li><b>适用场景</b>：论文配图、报告附件、归档。</li>
</ul>

<h3>17. 设置</h3>
<ul>
<li><b>入口</b>：设置 → 偏好设置（{sc_settings}）。</li>
<li><b>主题</b>：9 套主题可切换，涵盖明 / 暗。</li>
<li><b>语言</b>：简体 / 繁體 / English 切换。</li>
<li><b>图标风格</b>：多种图标风格可选。</li>
<li><b>快捷键自定义</b>：设置 → 快捷键可修改条目，并可恢复默认值。</li>
<li><b>图表字体</b>：统一图表字号，3D 图自动匹配界面字号。</li>
<li><b>数据目录</b>：显示数据目录位置（工程、快捷键、日志等）。</li>
<li><b>导出默认</b>：默认图表格式与 DPI 可设置。</li>
</ul>

<h3>18. 常用快捷键</h3>
<p>以下快捷键可由你在 <b>设置 → 快捷键</b> 中修改（此处显示跟随你的改动）：</p>
<table border="1" cellspacing="0" cellpadding="4" width="100%">
<tr><th>操作</th><th>默认键</th></tr>
<tr><td>播放 / 暂停</td><td>Space</td></tr>
<tr><td>停止</td><td>Shift+Space</td></tr>
<tr><td>录音</td><td>R</td></tr>
<tr><td>停止播放</td><td>Esc</td></tr>
<tr><td>打开文件</td><td>{sc_open}</td></tr>
<tr><td>导出图表</td><td>{sc_export}</td></tr>
<tr><td>设置</td><td>{sc_settings}</td></tr>
<tr><td>放大 / 缩小 / 适应窗口</td><td>Ctrl+= / Ctrl+- / Ctrl+0</td></tr>
<tr><td>试听选区</td><td>P</td></tr>
<tr><td>A/B 循环选区（开/关）</td><td>L</td></tr>
<tr><td>打时间点</td><td>T</td></tr>
<tr><td>打文本点</td><td>M</td></tr>
<tr><td>撤销上一打点</td><td>Shift+T</td></tr>
</table>
<p>以下为固定绑定键：</p>
<table border="1" cellspacing="0" cellpadding="4" width="100%">
<tr><th>操作</th><th>按键</th></tr>
<tr><td>视图切换（频谱 / 语谱 / 音高 / 共振峰 / 音色 / 3D / 房间模态）</td><td>F2 · F3 · F4 · F5 · F6 · F7 · F8</td></tr>
<tr><td>音律标尺叠加层（开/关）</td><td>F9</td></tr>
<tr><td>图表设计器</td><td>F10</td></tr>
<tr><td>多轨对比（进/出）</td><td>Ctrl+M</td></tr>
<tr><td>打开项目 / 保存项目 / 新建项目</td><td>Ctrl+Shift+O / Ctrl+S / Ctrl+N</td></tr>
<tr><td>AI 释图</td><td>Ctrl+I</td></tr>
<tr><td>撤销 / 重做</td><td>{sc_undo} / {sc_redo}</td></tr>
<tr><td>剪切 / 复制 / 粘贴</td><td>{sc_cut} / {sc_copy} / {sc_paste}</td></tr>
<tr><td>删除选区</td><td>Delete（或 Backspace）</td></tr>
<tr><td>静音选区 / 裁剪到选区</td><td>{sc_silence} / {sc_trim}</td></tr>
<tr><td>全选</td><td>{sc_sel_all}</td></tr>
<tr><td>缩放到选区</td><td>Shift+Z</td></tr>
<tr><td>分析选区</td><td>Ctrl+Shift+R</td></tr>
<tr><td>区间统计</td><td>Ctrl+Shift+S</td></tr>
<tr><td>导出报告</td><td>Ctrl+Shift+P</td></tr>
<tr><td>退出</td><td>Ctrl+Q（macOS Cmd+Q）</td></tr>
</table>

<h3>19. 开源与许可</h3>
<ul>
<li><b>开源协议</b>：GPL-3.0-only，与 Qt / PyQt6 许可一致。</li>
<li><b>无分级</b>：开源软件，功能无分级、无需注册或激活。</li>
<li><b>第三方许可</b>：第三方许可与来源清单随安装包提供。</li>
<li><b>模型下载</b>：模型首次使用自动下载（含校验），此后可离线。</li>
<li><b>内置 FFmpeg</b>：音频解码内置 FFmpeg，无需外部编码器（仅完整包 full 内置；core 小包需自行安装 FFmpeg）。</li>
<li><b>本地计算</b>：分析在本地进行；除你显式选择云端 AI Provider 外数据不外传。</li>
<li><b>隐私提示</b>：使用云端 AI 前请确认数据脱敏与授权。</li>
<li><b>完整文本</b>：许可证全文见随附 LICENSE 文件。</li>
</ul>

<h3>20. 音律标尺</h3>
<ul>
<li><b>入口</b>：工具 → 音律标尺叠加层（F9），或分析工具栏上的同名按钮；勾选即开、再点即关。</li>
<li><b>它做什么</b>：把所选律制的音级参考线叠绘到语谱图与音高视图上，用来读微分音与律制偏差。</li>
<li><b>音律模板</b>：工具 → 音律模板切换，也可选「不显示」；内置多种律制——十二平均律、纯律大调、五度相生七音、1/4 音差中庸全音、中国三分损益十二律、印度 22 shruti 采样、阿拉伯 24 音划分（等程与非等程皆有，不限于十二平均律）。</li>
<li><b>自定义律制模板</b>：工具 → 管理自定义律制模板…，可新建、编辑、删除、导入与导出；模板保存在用户数据目录，重启后仍出现在「音律模板」子菜单与批量读数下拉；内置八项模板只读。</li>
<li><b>与参考频率联动</b>：刻度线按 设置 → 偏好设置 → 通用 → A4 参考频率 换算，与音分 / 音名显示同一口径。</li>
<li><b>与多轨</b>：开启时，多轨对比的差异量化按当前律制给出逐帧音级归属。</li>
<li><b>限制</b>：只叠加参考线，不改动原始 f0 分析结果；开关与当前模板选择仅在当前会话内保留，不写入工作区；自定义模板本身持久化于用户数据目录。</li>
<li><b>适用场景</b>：律制研究、微分音与民族音乐的音高分析；与 FFT 频谱一节的「律制与微分音分析」互补——看单帧谱峰用那边，看音高随时间的走向用这里。</li>
</ul>
""",
    "zh_TW": """
<h2>使用者手冊</h2>
<p>AcouScope 是面向音樂與數位人文領域研究的聲學分析軟體。核心演算法純 NumPy 實現，介面基於 PyQt6。</p>

<h3>1. 介面概覽</h3>
<ul>
<li><b>最左 ribbon（全域工具）</b>：網站 / 說明 / 設定等全域入口；<b>設定固定置底</b>，隨時可快速開啟。</li>
<li><b>左欄</b>：面板頭 + 頁籤入口（檔案 / 設定）；可拖曳調寬，可摺疊。</li>
<li><b>中央一般工作區</b>：上方波形、下方分析視圖（波形 / FFT / 語譜 / 音高 / 共振峰 / 音色 / 3D）。</li>
<li><b>全鋪頁</b>：批次等頁面鋪滿中央、取代一般工作區，經工作區開關組進入。</li>
<li><b>右欄</b>：檢查器與 AI 釋圖；AI 釋圖也可用固定鍵 Ctrl+I 呼叫。</li>
<li><b>狀態列</b>：位於底部，顯示任務狀態、提示與選區資訊。</li>
<li><b>工作區開關組</b>：工具列右側一組全鋪頁開關（批次等）互斥；目前頁再點即收回一般工作區。</li>
<li><b>三欄分界線</b>：各欄之間懸停浮現 ◁‖▷ 抓手，拖曳改變欄寬，雙擊收回 / 展開。</li>
</ul>

<h3>2. 載入與播放</h3>
<ul>
<li><b>開啟音訊</b>：檔案 → 開啟（{sc_open}），支援 WAV / FLAC / MP3 / AIFF / OGG。</li>
<li><b>內建解碼</b>：以上格式均可直接開啟，內建 FFmpeg，無需外部編碼器（完整套件 full 內建；core 輕量套件不含——core 套件開啟這類格式會提示失敗，請改用完整套件或自行安裝 FFmpeg）。</li>
<li><b>播放 / 暫停 / 停止</b>：空白鍵播放 / 暫停，Shift+空白鍵停止，Esc 停止播放並取消選區。</li>
<li><b>播放頭定位</b>：在波形上單擊任意處定位播放頭，也可用時間碼輸入。</li>
<li><b>縮放</b>：放大 / 縮小（Ctrl+= / Ctrl+-）、適應視窗（Ctrl+0）、縮放到選區（Shift+Z）。</li>
<li><b>試聽選區</b>：建立選區後按 P 試聽選區。</li>
<li><b>A/B 循環</b>：按 L 開啟 / 關閉選區的循環播放。</li>
<li><b>錄音</b>：按 R 開始 / 停止錄音（需輸入裝置），錄音結果進入目前專案。</li>
</ul>

<h3>3. 波形編輯（Audacity 風格）</h3>
<ul>
<li><b>建立選區</b>：波形上左鍵拖動；單擊（或在選區外單擊）清除選區。</li>
<li><b>剪下 / 複製 / 貼上</b>：{sc_cut} / {sc_copy} / {sc_paste}；貼上預設可取代選區。</li>
<li><b>刪除選區</b>：Delete（或 Backspace）刪除選定內容。</li>
<li><b>靜音 / 裁剪</b>：{sc_silence} 靜音選區；{sc_trim} 裁剪到選區。</li>
<li><b>復原 / 重做</b>：{sc_undo} / {sc_redo} 支援多階復原與重做。</li>
<li><b>全選 / 取消</b>：{sc_sel_all} 全選；Esc 取消選區。</li>
<li><b>分析指標聯動</b>：按住 Shift 拖動波形上的分析指標，各分析視圖游標同步跟隨。</li>
<li><b>適用場景</b>：剪掉咳嗽、靜音空隙、片段裁剪等輕量編輯。</li>
</ul>

<h3>4. FFT 頻譜</h3>
<ul>
<li><b>視圖</b>：分析 → FFT 頻譜（F2）。</li>
<li><b>軸單位</b>：頻率軸 Hz / kHz / MIDI / 鋼琴鍵 / 音分 / Mel；振幅軸線性 / dB / dBFS / dB(A) / %。</li>
<li><b>諧波自動標註</b>：預設自動標註前 6 個諧波（相對主峰振幅 ≥ −60 dB，即 0.1%）。</li>
<li><b>手動增刪標記</b>：左鍵在譜峰上加入（±100 音分吸附），右鍵移除。</li>
<li><b>FFT 參數</b>：FFT 大小（512–16384）與窗函數可選；視窗內無捲軸，便於完整擷圖。</li>
<li><b>適用場景</b>：穩態音的諧波結構、樂器泛音、律制與微分音分析。</li>
<li><b>限制</b>：瞬態音譜峰較寬，標記吸附以音分為單位。</li>
<li><b>聯動</b>：拖動波形區分析指標，頻譜隨樂段即時更新。</li>
</ul>

<h3>5. 語譜圖</h3>
<ul>
<li><b>視圖</b>：分析 → 語譜圖（F3），時間-頻率-能量三軸顯示。</li>
<li><b>三軸</b>：橫軸時間、縱軸頻率、顏色表示能量強度。</li>
<li><b>FFT 參數</b>：FFT 大小（512–16384）、幀移比例、窗函數可調。</li>
<li><b>色板與動態範圍</b>：7 種色板；動態範圍與對比可調。</li>
<li><b>頻率軸</b>：支援線性 / 對數頻率軸。</li>
<li><b>游標聯動</b>：時間游標與波形指標雙向聯動。</li>
<li><b>適用場景</b>：瞬態、語音、音色隨時間演變、共振峰走向。</li>
<li><b>提示</b>：要看清楚低頻細節可縮小 FFT 大小提升時間解析度，或改用對數軸。</li>
</ul>

<h3>6. 音高偵測</h3>
<ul>
<li><b>視圖</b>：分析 → 音高（F4）。</li>
<li><b>三套引擎</b>：pYIN（串流 / 即時，20 音分 HMM 後處理） · SwiftF0（輕量離線，約 9.5 萬參數） · RMVPE（複音、嘈雜人聲增強）。</li>
<li><b>怎麼選</b>：需要即時跟播看 → pYIN；需要輕量且較精確的離線分析 → SwiftF0；人聲 / 複音內容 → RMVPE。</li>
<li><b>反量化連續音高</b>：引擎輸出的音分網格經期望值 / 插值還原為連續 Hz，微分音與滑音不會被吞掉。</li>
<li><b>離線後端非串流</b>：SwiftF0 / RMVPE 屬於整體離線分析，需在獨立執行緒中執行，結果在分析完成後返回。</li>
<li><b>耗時與量級</b>：SwiftF0 輕量（約 9.5 萬參數）返回較快；RMVPE 對長音訊需等待分析進度。</li>
<li><b>模型首次下載</b>：首次使用會自動下載模型（含校驗），此後可離線。</li>
<li><b>鋼琴卷簾</b>：音高曲線疊加鋼琴鍵位（C4 標註中央C），便於對照音符。</li>
<li><b>音分偏差</b>：顯示與目標音高的音分偏差，適合律制研究。</li>
</ul>

<h3>7. 共振峰分析</h3>
<ul>
<li><b>視圖</b>：分析 → 共振峰（F5）。</li>
<li><b>4 條軌跡</b>：LPC 逐幀提取 F1–F4 共振峰頻率與頻寬。</li>
<li><b>讀法</b>：F1 與開合度相關、F2 與舌位前後相關，可輔助判斷元音。</li>
<li><b>適用場景</b>：語音元音分析、歌唱共鳴、音色辨識。</li>
<li><b>頻寬含義</b>：窄峰 = 穩定共振，寬峰 = 阻尼較大。</li>
<li><b>聯動</b>：游標與波形指標聯動，可逐幀觀察。</li>
<li><b>限制</b>：LPC 階數與幀內容相關，高雜訊下軌跡可能抖動。</li>
<li><b>提示</b>：與語譜圖對照觀察共振峰能量帶更直觀。</li>
</ul>

<h3>8. 音色分析</h3>
<ul>
<li><b>視圖</b>：分析 → 音色（F6）。</li>
<li><b>MFCC 含義</b>：梅爾倒譜係數刻畫頻譜包絡（音色輪廓），不必深究其數學細節。</li>
<li><b>軌跡比較</b>：同一曲不同演奏、或不同樂器的特徵軌跡可疊加比較。</li>
<li><b>頻譜特徵</b>：質心 / 銳度 / 通量 / 諧噪比（HNR）等。</li>
<li><b>適用場景</b>：同曲不同演奏、不同樂器的音色對比。</li>
<li><b>全域特徵</b>：整段彙總的統計指標，可用於歸檔與檢索。</li>
<li><b>限制</b>：音色判斷需結合聽覺與語境，數值僅供參考。</li>
<li><b>提示</b>：先穩定選段、再用軌跡疊圖，避免雜訊干擾。</li>
</ul>

<h3>9. 3D 頻譜圖</h3>
<ul>
<li><b>視圖</b>：分析 → 3D 頻譜（F7）。</li>
<li><b>兩種模式</b>：曲面與瀑布（含消隱）兩種顯示模式。</li>
<li><b>視角操作</b>：滑鼠拖曳旋轉、滾輪縮放，可重設視角。</li>
<li><b>參數</b>：FFT 大小、幀移、色板、動態範圍同語譜圖。</li>
<li><b>樂段</b>：預設前 10 秒，上限 60 秒。</li>
<li><b>振幅標尺</b>：線性 / dB / 歸一化 %。</li>
<li><b>匯出為白底</b>：圖形匯出恆為白底、所見即所得，與螢幕主題無關。</li>
<li><b>適用場景</b>：直觀展示整段頻譜結構，論文配圖。</li>
</ul>

<h3>10. 即時特徵（波形視圖）</h3>
<ul>
<li><b>位置</b>：波形視圖的即時特徵區。</li>
<li><b>播放中即時計算</b>：起音（低 / 中 / 高頻段）與 BPM 節拍估計。</li>
<li><b>起音讀法</b>：各頻段能量跳變即音符起始。</li>
<li><b>BPM</b>：播放中持續估計節拍速度。</li>
<li><b>適用場景</b>：邊播邊看，快速評估段落節奏與力度。</li>
<li><b>限制</b>：即時估計受雜訊影響，僅供觀察參考。</li>
<li><b>提示</b>：需要精確數值時用「分析 → 分析選區」。</li>
<li><b>與選區</b>：可先建立選區再在播放中對照。</li>
</ul>

<h3>11. 圖表設計器</h3>
<ul>
<li><b>入口</b>：工具 → 圖表設計器，或分析工具列「圖表設計器」，在中央全鋪頁開啟。</li>
<li><b>即時預覽</b>：增刪內容或改樣式即時刷新預覽。</li>
<li><b>內容外殼</b>：標題、副標題、來源、註腳可分別編輯。</li>
<li><b>參考線 / 閾值線</b>：可按需疊加水平 / 垂直參考線與閾值線。</li>
<li><b>主題預設</b>：多套配色主題可切換。</li>
<li><b>樣式 JSON</b>：樣式可匯入匯出為 JSON，便於重用與團隊統一。</li>
<li><b>匯出恆白底</b>：匯出為 SVG / PDF / PNG，恆為白底、所見即所得。</li>
<li><b>DPI 與尺寸</b>：點陣圖匯出可調 DPI 與目標尺寸。</li>
<li><b>適用場景</b>：論文配圖、答辯、報告、歸檔。</li>
</ul>

<h3>12. AI 釋圖</h3>
<ul>
<li><b>入口</b>：右欄 → AI 釋圖，或選單分析 → AI 釋圖（Ctrl+I）。</li>
<li><b>它能做什麼</b>：讀取譜峰 / 泛音 / 共振峰，生成論文段落草稿與觀察描述。</li>
<li><b>Markdown 渲染</b>：結果支援表格 / 列表 / 程式碼區塊。</li>
<li><b>串流輸出</b>：生成過程逐字顯示，可提前查看。</li>
<li><b>操作按鈕</b>：複製、重新產生、清空。</li>
<li><b>Provider</b>：可選雲端或本機模型；本機模型首次使用自動下載（含校驗），此後可離線。</li>
<li><b>引用建議</b>：輸出會給出引用建議。</li>
<li><b>人工複核提醒</b>：AI 輸出僅供研究者判斷，需複核後使用。</li>
<li><b>限制</b>：準確性依賴輸入與模型，涉資料結論務必人工核實。</li>
</ul>

<h3>13. 多軌工作台</h3>
<ul>
<li><b>入口</b>：分析 → 多軌對比，或工具列進入；在中央全鋪頁並列顯示多軌。再按一次 Ctrl+M（或軌道區左上的退出鈕）即回到單軌。</li>
<li><b>加入多軌</b>：在左欄檔案清單多選後點「加入多軌」；左欄摺疊時該按鈕先展開清單供你勾選，已展開仍無選取則跳出系統檔案框直選。</li>
<li><b>軌頭控制項</b>：每條軌有名稱 / 靜音 / 獨奏 / 音量 / 逐軌偏移 / 色彩等軌頭控制項。</li>
<li><b>軌身分色</b>：12 色內容色板與回饋色分家，便於區分軌道。</li>
<li><b>對比呈現</b>：單圖（各軌音高曲線疊繪於同一時間軸，參考軌加粗）與多圖（每軌一圖、共享播放頭與縮放）兩種模式，另有密度熱圖開關（時間-頻率總覽，軌數少於 4 時預設關閉，可手動開啟）。</li>
<li><b>差異統計</b>：點工具列「差異統計」按鈕觸發，以參考軌為基準逐軌量化音高偏差（需 2 軌以上且非參考軌已有音高結果），結果驅動差異條、懸停讀數與差異表 CSV 匯出。</li>
<li><b>逐軌分析</b>：對每條軌分別選擇分析視圖與參數。</li>
<li><b>橋接任務中心</b>：逐軌分析會形成任務進入任務中心，可批次處理。</li>
<li><b>適用場景</b>：同曲不同演奏、不同設備現場錄音對比，AB 對照。</li>
<li><b>限制</b>：多軌同時分析較耗資源，建議按需逐軌進行。</li>
<li><b>聯動</b>：各軌游標同步，便於逐點對照；播放中共享播放頭即時推進，各軌按自己的偏移量對齊顯示。</li>
</ul>

<h3>14. 任務中心</h3>
<ul>
<li><b>入口</b>：工作區開關組 → 任務中心，或批次入口。</li>
<li><b>任務與進度</b>：顯示批次任務列表與即時進度。</li>
<li><b>面板狀態記憶</b>：任務中心面板的顯隱與摺疊狀態會被記住。</li>
<li><b>長任務可繼續操作</b>：任務在背景執行，介面仍可編輯與檢視。</li>
<li><b>失敗與重試</b>：失敗任務可在列表檢視原因並重試。</li>
<li><b>適用場景</b>：批次匯出、批次分析。</li>
<li><b>限制</b>：併發成長會佔用更多記憶體，避免一次提交過多。</li>
<li><b>提示</b>：完成 / 失敗均有狀態標識。</li>
</ul>

<h3>15. 田野中繼資料</h3>
<ul>
<li><b>用途</b>：語料與採錄著錄，便於歸檔、檢索。</li>
<li><b>匯出格式</b>：JSON / XML / CSV。</li>
<li><b>識別碼</b>：Identifier，唯一識別每份採錄。</li>
<li><b>題名 / 創作者</b>：Title 題名，Creator-Actor 創作者 / 演出者。</li>
<li><b>日期 / 地點</b>：Date、Location 採錄時地。</li>
<li><b>流派 / 情境</b>：Context-Genre 說明語境與體裁。</li>
<li><b>技術資訊</b>：取樣率、位元深度、格式等隨匯出一併寫入。</li>
<li><b>欄位參考</b>：參考 IASA-TC 04 / IMDI / GB/T 31219.4 / DA/T 63，欄位級對照已完成，並有機器校驗閘守護。</li>
<li><b>自訂對應</b>：可自訂欄位與匯出目標欄位的對應。</li>
</ul>

<h3>16. 匯出</h3>
<ul>
<li><b>圖形格式</b>：SVG / PDF（向量）與 PNG（點陣圖），DPI 可調。</li>
<li><b>恆白底</b>：匯出圖形恆為白底、所見即所得，與螢幕主題無關。</li>
<li><b>視角保留</b>：匯出保留目前視角 / 模式 / 樂段選擇。</li>
<li><b>圖形入口</b>：檔案 → 匯出 → 匯出圖表（{sc_export}）。</li>
<li><b>音訊格式</b>：WAV（無損）/ FLAC（無損壓縮）/ MP3，內建解碼。</li>
<li><b>音訊入口</b>：檔案 → 匯出 → 音訊。</li>
<li><b>常見失敗原因</b>：未載入音訊 / 目標目錄無寫入權限 / 選區為空等。</li>
<li><b>適用場景</b>：論文配圖、報告附件、歸檔。</li>
</ul>

<h3>17. 設定</h3>
<ul>
<li><b>入口</b>：設定 → 偏好設定（{sc_settings}）。</li>
<li><b>主題</b>：9 套主題可切換，涵蓋明 / 暗。</li>
<li><b>語言</b>：簡體 / 繁體 / English 切換。</li>
<li><b>圖示風格</b>：多種圖示風格可選。</li>
<li><b>快速鍵自訂</b>：設定 → 快速鍵可修改條目，並可恢復預設值。</li>
<li><b>圖表字型</b>：統一圖表字號，3D 圖自動匹配介面字號。</li>
<li><b>資料目錄</b>：顯示資料目錄位置（專案、快速鍵、日誌等）。</li>
<li><b>匯出預設</b>：預設圖表格式與 DPI 可設定。</li>
</ul>

<h3>18. 常用快速鍵</h3>
<p>以下快速鍵可由你在 <b>設定 → 快速鍵</b> 中修改（此處顯示跟隨你的改動）：</p>
<table border="1" cellspacing="0" cellpadding="4" width="100%">
<tr><th>操作</th><th>預設鍵</th></tr>
<tr><td>播放 / 暫停</td><td>Space</td></tr>
<tr><td>停止</td><td>Shift+Space</td></tr>
<tr><td>錄音</td><td>R</td></tr>
<tr><td>停止播放</td><td>Esc</td></tr>
<tr><td>開啟檔案</td><td>{sc_open}</td></tr>
<tr><td>匯出圖表</td><td>{sc_export}</td></tr>
<tr><td>設定</td><td>{sc_settings}</td></tr>
<tr><td>放大 / 縮小 / 適應視窗</td><td>Ctrl+= / Ctrl+- / Ctrl+0</td></tr>
<tr><td>試聽選區</td><td>P</td></tr>
<tr><td>A/B 循環選區（開/關）</td><td>L</td></tr>
<tr><td>打時間點</td><td>T</td></tr>
<tr><td>打文本點</td><td>M</td></tr>
<tr><td>撤銷上一打點</td><td>Shift+T</td></tr>
</table>
<p>以下為固定綁定鍵：</p>
<table border="1" cellspacing="0" cellpadding="4" width="100%">
<tr><th>操作</th><th>按鍵</th></tr>
<tr><td>視圖切換（頻譜 / 語譜 / 音高 / 共振峰 / 音色 / 3D / 房間模態）</td><td>F2 · F3 · F4 · F5 · F6 · F7 · F8</td></tr>
<tr><td>音律標尺疊加層（開/關）</td><td>F9</td></tr>
<tr><td>圖表設計器</td><td>F10</td></tr>
<tr><td>多軌對比（進/出）</td><td>Ctrl+M</td></tr>
<tr><td>開啟專案 / 儲存專案 / 新建專案</td><td>Ctrl+Shift+O / Ctrl+S / Ctrl+N</td></tr>
<tr><td>AI 釋圖</td><td>Ctrl+I</td></tr>
<tr><td>復原 / 重做</td><td>{sc_undo} / {sc_redo}</td></tr>
<tr><td>剪下 / 複製 / 貼上</td><td>{sc_cut} / {sc_copy} / {sc_paste}</td></tr>
<tr><td>刪除選區</td><td>Delete（或 Backspace）</td></tr>
<tr><td>靜音選區 / 裁剪到選區</td><td>{sc_silence} / {sc_trim}</td></tr>
<tr><td>全選</td><td>{sc_sel_all}</td></tr>
<tr><td>縮放到選區</td><td>Shift+Z</td></tr>
<tr><td>分析選區</td><td>Ctrl+Shift+R</td></tr>
<tr><td>區間統計</td><td>Ctrl+Shift+S</td></tr>
<tr><td>匯出報告</td><td>Ctrl+Shift+P</td></tr>
<tr><td>結束</td><td>Ctrl+Q（macOS Cmd+Q）</td></tr>
</table>

<h3>19. 開源與授權</h3>
<ul>
<li><b>開源協定</b>：GPL-3.0-only，與 Qt / PyQt6 授權一致。</li>
<li><b>無分級</b>：開源軟體，功能無分級、無需註冊或啟動。</li>
<li><b>第三方授權</b>：第三方授權與來源清單隨安裝套件提供。</li>
<li><b>模型下載</b>：模型首次使用自動下載（含校驗），此後可離線。</li>
<li><b>內建 FFmpeg</b>：音訊解碼內建 FFmpeg，無需外部編碼器（僅完整套件 full 內建；core 輕量套件需自行安裝 FFmpeg）。</li>
<li><b>本機計算</b>：分析在本機進行；除你明確選擇雲端 AI Provider 外資料不外傳。</li>
<li><b>隱私提示</b>：使用雲端 AI 前請確認資料去識別與授權。</li>
<li><b>完整文字</b>：授權證全文見隨附 LICENSE 檔案。</li>
</ul>

<h3>20. 音律標尺</h3>
<ul>
<li><b>入口</b>：工具 → 音律標尺疊加層（F9），或分析工具列上的同名按鈕；勾選即開、再點即關。</li>
<li><b>它做什麼</b>：把所選律制的音級參考線疊繪到語譜圖與音高視圖上，用來讀微分音與律制偏差。</li>
<li><b>音律模板</b>：工具 → 音律模板切換，也可選「不顯示」；內建多種律制——十二平均律、純律大調、五度相生七音、1/4 音差中庸全音、中國三分損益十二律、印度 22 shruti 採樣、阿拉伯 24 音劃分（等程與非等程皆有，不限於十二平均律）。</li>
<li><b>自訂律制範本</b>：工具 → 管理自訂律制範本…，可新增、編輯、刪除、匯入與匯出；範本保存在使用者資料目錄，重啟後仍出現在「音律範本」子選單與批量讀數下拉；內建八項範本唯讀。</li>
<li><b>與參考頻率聯動</b>：刻度線按 設定 → 偏好設定 → 一般 → A4 參考頻率 換算，與音分 / 音名顯示同一口徑。</li>
<li><b>與多軌</b>：開啟時，多軌對比的差異量化按當前律制給出逐幀音級歸屬。</li>
<li><b>限制</b>：只疊加參考線，不改動原始 f0 分析結果；開關與目前範本選擇僅在目前工作階段內保留，不寫入工作區；自訂範本本身持久化於使用者資料目錄。</li>
<li><b>適用場景</b>：律制研究、微分音與民族音樂的音高分析；與 FFT 頻譜一節的「律制與微分音分析」互補——看單幀譜峰用那邊，看音高隨時間的走向用這裡。</li>
</ul>
""",
    "en_US": """
<h2>User Manual</h2>
<p>AcouScope is an acoustic analysis application for music and digital humanities research. Core algorithms are implemented in pure NumPy; the UI is built with PyQt6.</p>

<h3>1. Interface Overview</h3>
<ul>
<li><b>Leftmost ribbon (global tools)</b>: website / help / settings; <b>Settings is pinned to the bottom</b> for quick access.</li>
<li><b>Left pane</b>: panel header plus tab entries (Files / Settings); draggable to resize and collapsible.</li>
<li><b>Center regular workspace</b>: waveform on top, analysis views below (Waveform / FFT / Spectrogram / Pitch / Formants / Timbre / 3D).</li>
<li><b>Full-pane pages</b>: pages such as Batch fill the center and replace the regular workspace, entered via the workspace switch group.</li>
<li><b>Right pane</b>: inspector and AI Interpretation; AI Interpretation can also be opened with the fixed key Ctrl+I.</li>
<li><b>Status bar</b>: at the bottom, showing task status, tips and selection info.</li>
<li><b>Workspace switch group</b>: a group of mutually exclusive full-pane toggles (e.g. Batch) on the right side of the toolbar; clicking the active one collapses back to the regular workspace.</li>
<li><b>Three-pane dividers</b>: hovering over a divider shows a ◁‖▷ handle; drag to resize the pane, double-click to collapse / expand.</li>
</ul>

<h3>2. Loading and Playback</h3>
<ul>
<li><b>Open audio</b>: File → Open ({sc_open}). Supports WAV / FLAC / MP3 / AIFF / OGG.</li>
<li><b>Built-in decoding</b>: all these formats open directly with the built-in FFmpeg — no system encoder needed (the full package bundles FFmpeg; the core package does not — on the core package these formats report a decode failure, so use the full package or install FFmpeg yourself).</li>
<li><b>Play / Pause / Stop</b>: Space toggles play / pause, Shift+Space stops, Esc stops playback and clears the selection.</li>
<li><b>Position the playhead</b>: click anywhere on the waveform to position the playhead, or type a timecode.</li>
<li><b>Zoom</b>: Zoom in / out (Ctrl+= / Ctrl+-), Fit to Window (Ctrl+0), Zoom to Selection (Shift+Z).</li>
<li><b>Preview selection</b>: press P to audition the selected region.</li>
<li><b>A/B loop</b>: press L to toggle looped playback of the selection.</li>
<li><b>Record</b>: press R to start / stop recording (requires an input device); the result enters the current project.</li>
</ul>

<h3>3. Waveform Editing (Audacity-style)</h3>
<ul>
<li><b>Make a selection</b>: drag with the left button on the waveform; click (or click outside the selection) to clear it.</li>
<li><b>Cut / Copy / Paste</b>: {sc_cut} / {sc_copy} / {sc_paste}; paste can replace the selection.</li>
<li><b>Delete selection</b>: Delete (or Backspace) removes the selected content.</li>
<li><b>Silence / Trim</b>: {sc_silence} silences the selection; {sc_trim} trims to the selection.</li>
<li><b>Undo / Redo</b>: {sc_undo} / {sc_redo} support multi-level undo and redo.</li>
<li><b>Select all / Clear</b>: {sc_sel_all} selects all; Esc clears the selection.</li>
<li><b>Linked analysis pointer</b>: hold Shift and drag the analysis pointer on the waveform; cursors in all analysis views follow it.</li>
<li><b>Use cases</b>: light edits such as removing a cough, silence gaps, or trimming a segment.</li>
</ul>

<h3>4. FFT Spectrum</h3>
<ul>
<li><b>View</b>: Analysis → FFT Spectrum (F2).</li>
<li><b>Axis units</b>: frequency in Hz / kHz / MIDI / piano key / cents / Mel; amplitude in linear / dB / dBFS / dB(A) / %.</li>
<li><b>Automatic harmonics</b>: the top 6 harmonics (relative amplitude ≥ −60 dB, i.e. 0.1%) are marked by default.</li>
<li><b>Manual markers</b>: left-click on a peak to add (±100-cent snap), right-click to remove.</li>
<li><b>FFT parameters</b>: FFT size (512–16384) and window function are selectable; the window has no scroll bars for clean full-view screenshots.</li>
<li><b>Use cases</b>: harmonic structure of steady tones, instrument overtones, tuning and microtonal analysis.</li>
<li><b>Limits</b>: transient peaks are broad, and markers snap in cents.</li>
<li><b>Linkage</b>: drag the analysis pointer on the waveform and the spectrum updates live.</li>
</ul>

<h3>5. Spectrogram</h3>
<ul>
<li><b>View</b>: Analysis → Spectrogram (F3); a time–frequency–energy three-axis display.</li>
<li><b>Three axes</b>: time on the horizontal, frequency on the vertical, energy shown in color.</li>
<li><b>FFT parameters</b>: adjustable FFT size (512–16384), hop ratio and window function.</li>
<li><b>Colormap and range</b>: 7 colormaps; adjustable dynamic range and contrast.</li>
<li><b>Frequency axis</b>: linear or logarithmic.</li>
<li><b>Cursor linkage</b>: time cursor and waveform pointer are bidirectionally linked.</li>
<li><b>Use cases</b>: transients, speech, timbre evolution over time, formant tracks.</li>
<li><b>Tips</b>: to see low-frequency detail, lower the FFT size for better time resolution or use the logarithmic axis.</li>
</ul>

<h3>6. Pitch Detection</h3>
<ul>
<li><b>View</b>: Analysis → Pitch (F4).</li>
<li><b>Three engines</b>: pYIN (streaming / real-time, 20-cent HMM post-processing) · SwiftF0 (lightweight offline, ~95k parameters) · RMVPE (polyphonic, noisy-vocal enhanced).</li>
<li><b>How to choose</b>: live follow-along → pYIN; light but accurate offline analysis → SwiftF0; vocals / polyphonic content → RMVPE.</li>
<li><b>Continuous dequantized pitch</b>: the engine's cent grid is restored to continuous Hz via expectation / interpolation, so microtones and glides are not discarded.</li>
<li><b>Offline backends are not streaming</b>: SwiftF0 / RMVPE run global offline analysis in a separate thread; results are returned when analysis completes.</li>
<li><b>Cost and scale</b>: SwiftF0 is lightweight (~95k parameters) and returns faster; RMVPE requires waiting on the progress for long audio.</li>
<li><b>First-use model download</b>: the model is downloaded and verified automatically on first use; afterwards it works offline.</li>
<li><b>Piano roll</b>: the pitch contour is overlaid on piano keys (C4 marked as middle C) for note comparison.</li>
<li><b>Cent deviation</b>: shows the cent offset from the target pitch, suitable for tuning research.</li>
</ul>

<h3>7. Formant Analysis</h3>
<ul>
<li><b>View</b>: Analysis → Formants (F5).</li>
<li><b>Four tracks</b>: frame-wise LPC extraction of F1–F4 formant frequencies and bandwidths.</li>
<li><b>Reading</b>: F1 relates to jaw opening and F2 to tongue front/back, useful for vowel identification.</li>
<li><b>Use cases</b>: vowel analysis in speech, singing resonance, timbre identification.</li>
<li><b>Bandwidth meaning</b>: a narrow peak means a stable resonance; a wide one means greater damping.</li>
<li><b>Linkage</b>: cursor and waveform pointer are linked for frame-by-frame inspection.</li>
<li><b>Limits</b>: LPC order depends on frame content; tracks may jitter under heavy noise.</li>
<li><b>Tips</b>: comparing with the spectrogram makes the formant bands easier to read.</li>
</ul>

<h3>8. Timbre Analysis</h3>
<ul>
<li><b>View</b>: Analysis → Timbre (F6).</li>
<li><b>What MFCC means</b>: Mel-frequency cepstral coefficients describe the spectral envelope (timbre shape); you do not need the math.</li>
<li><b>Track comparison</b>: feature tracks from different performances of the same piece, or from different instruments, can be overlaid.</li>
<li><b>Spectral features</b>: centroid / sharpness / flux / harmonics-to-noise ratio (HNR), etc.</li>
<li><b>Use cases</b>: comparing timbre across takes or instruments.</li>
<li><b>Global features</b>: per-segment summary statistics, useful for archiving and retrieval.</li>
<li><b>Limits</b>: timbre judgment should combine listening and context; numbers are only a reference.</li>
<li><b>Tips</b>: fix the segment first, then overlay tracks to avoid noise interference.</li>
</ul>

<h3>9. 3D Spectrogram</h3>
<ul>
<li><b>View</b>: Analysis → 3D Spectrogram (F7).</li>
<li><b>Two modes</b>: surface and waterfall (with hidden-line removal).</li>
<li><b>View manipulation</b>: drag to rotate, scroll to zoom, and reset the view.</li>
<li><b>Parameters</b>: FFT size, hop, colormap and dynamic range, same as the spectrogram.</li>
<li><b>Segment</b>: first 10 seconds by default, up to 60 seconds.</li>
<li><b>Amplitude scale</b>: linear / dB / normalized %.</li>
<li><b>White-background export</b>: exported charts are always on a white background, regardless of the screen theme.</li>
<li><b>Use cases</b>: presenting the spectrum structure of a whole segment, e.g. in a paper figure.</li>
</ul>

<h3>10. Real-time Features (Waveform View)</h3>
<ul>
<li><b>Location</b>: the real-time feature area of the waveform view.</li>
<li><b>Live during playback</b>: onsets (low / mid / high bands) and BPM estimation.</li>
<li><b>Reading onsets</b>: an energy jump in a band marks a note onset.</li>
<li><b>BPM</b>: the tempo is estimated continuously during playback.</li>
<li><b>Use cases</b>: watching while playing to quickly judge a segment's rhythm and dynamics.</li>
<li><b>Limits</b>: real-time estimates are affected by noise and are for observation only.</li>
<li><b>Tips</b>: use Analysis → Analyze Region for precise numbers.</li>
<li><b>With selections</b>: make a selection first, then compare during playback.</li>
</ul>

<h3>11. Chart Designer</h3>
<ul>
<li><b>Entry</b>: Tools → Chart Designer, or the "Chart Designer" button on the Analysis toolbar; opens as a full-pane page.</li>
<li><b>Live preview</b>: adding content or changing styles refreshes the preview instantly.</li>
<li><b>Content shell</b>: title, subtitle, source and footnote can be edited separately.</li>
<li><b>Reference / threshold lines</b>: add horizontal / vertical reference lines and threshold lines as needed.</li>
<li><b>Theme presets</b>: several color themes are available.</li>
<li><b>Style JSON</b>: styles can be imported and exported as JSON for reuse and team consistency.</li>
<li><b>White-background export</b>: exports to SVG / PDF / PNG on a white background, WYSIWYG.</li>
<li><b>DPI and size</b>: bitmap export lets you adjust DPI and target dimensions.</li>
<li><b>Use cases</b>: paper figures, defenses, reports and archives.</li>
</ul>

<h3>12. AI Interpretation</h3>
<ul>
<li><b>Entry</b>: right pane → AI Interpretation, or menu Analysis → AI Interpretation (Ctrl+I).</li>
<li><b>What it does</b>: reads spectral peaks / harmonics / formants and drafts paper paragraph text and observation notes.</li>
<li><b>Markdown rendering</b>: results support tables / lists / code blocks.</li>
<li><b>Streaming output</b>: text streams in as it is generated so you can preview early.</li>
<li><b>Actions</b>: copy, regenerate and clear.</li>
<li><b>Provider</b>: choose a cloud or local model; the local model is downloaded and verified on first use, then works offline.</li>
<li><b>Citation suggestion</b>: the output includes citation guidance.</li>
<li><b>Human review reminder</b>: AI output is for the researcher to judge; verify before use.</li>
<li><b>Limits</b>: accuracy depends on input and model; always manually verify any data-related conclusions.</li>
</ul>

<h3>13. Multitrack Workbench</h3>
<ul>
<li><b>Entry</b>: Analysis → Multitrack Compare, or via the toolbar; multiple tracks are shown side by side in a full-pane page. Pressing Ctrl+M again (or the exit button at the top of the track area) returns you to the single-track workspace.</li>
<li><b>Adding tracks</b>: select files in the left file list and use "add to multitrack"; if the left pane is collapsed the button expands the list first so you can pick, and with the pane open but nothing selected a system file dialog opens instead.</li>
<li><b>Track-header controls</b>: each track has name / mute / solo / volume / per-track offset / color controls at its header.</li>
<li><b>Track identity colors</b>: a 12-color content palette kept separate from feedback colors, so tracks are easy to tell apart.</li>
<li><b>Comparison views</b>: single chart (all pitch curves overlaid on one shared time axis, the reference track drawn thicker) or multiple charts (one per track with a shared playhead and zoom), plus a density heatmap switch (a time–frequency overview, off by default below 4 tracks and switchable on).</li>
<li><b>Difference statistics</b>: started by clicking the "Difference statistics" button, which quantifies every track against the reference track (needs at least two tracks and a pitch result on a non-reference track); the result drives the difference bar, the hover readout and the CSV export of the difference table.</li>
<li><b>Per-track analysis</b>: choose the analysis view and parameters for each track independently.</li>
<li><b>Bridges to Task Center</b>: per-track analysis creates tasks in the Task Center that can be handled in batch.</li>
<li><b>Use cases</b>: comparing different takes of the same piece, or field or concert recordings from different devices (A/B).</li>
<li><b>Limits</b>: analyzing many tracks at once is resource-heavy; process them one at a time when possible.</li>
<li><b>Linkage</b>: cursors are synchronized across tracks for point-by-point comparison; during playback the shared playhead advances live, each track aligned by its own offset.</li>
</ul>

<h3>14. Task Center</h3>
<ul>
<li><b>Entry</b>: workspace switch group → Task Center, or the Batch entry.</li>
<li><b>Tasks and progress</b>: shows the list of batch tasks and their progress in real time.</li>
<li><b>Panel state memory</b>: whether the Task Center panel is shown or collapsed is remembered.</li>
<li><b>Keep working during long tasks</b>: tasks run in the background while you keep editing and viewing.</li>
<li><b>Failure and retry</b>: failed tasks can be inspected and retried from the list.</li>
<li><b>Use cases</b>: batch export, batch analysis.</li>
<li><b>Limits</b>: more concurrency uses more memory; avoid submitting too much at once.</li>
<li><b>Tips</b>: completed and failed tasks are clearly flagged.</li>
</ul>

<h3>15. Field Metadata</h3>
<ul>
<li><b>Purpose</b>: documenting field recordings and corpora for archiving and retrieval.</li>
<li><b>Export formats</b>: JSON / XML / CSV.</li>
<li><b>Identifier</b>: a unique identifier for each recording.</li>
<li><b>Title / Creator</b>: Title; Creator-Actor for the creator / performer.</li>
<li><b>Date / Location</b>: where and when the recording was made.</li>
<li><b>Context / Genre</b>: Context-Genre describes the context and genre.</li>
<li><b>Technical info</b>: sample rate, bit depth and format are written alongside on export.</li>
<li><b>Field references</b>: fields are mapped item by item to IASA-TC 04 / IMDI / GB/T 31219.4 / DA/T 63, with machine-verified gates guarding the mapping.</li>
<li><b>Custom mapping</b>: you can map your fields to the export target fields.</li>
</ul>

<h3>16. Export</h3>
<ul>
<li><b>Chart formats</b>: SVG / PDF (vector) and PNG (bitmap), with adjustable DPI.</li>
<li><b>White background</b>: exported charts are always on a white background, WYSIWYG and independent of the screen theme.</li>
<li><b>View preserved</b>: exports keep the current view angle, mode and segment selection.</li>
<li><b>Chart entry</b>: File → Export → Export Chart ({sc_export}).</li>
<li><b>Audio formats</b>: WAV (lossless) / FLAC (lossless compression) / MP3, with built-in decoding.</li>
<li><b>Audio entry</b>: File → Export → Audio.</li>
<li><b>Common failure causes</b>: no audio loaded / target directory not writable / empty selection.</li>
<li><b>Use cases</b>: paper figures, reports and archives.</li>
</ul>

<h3>17. Settings</h3>
<ul>
<li><b>Entry</b>: Settings → Preferences ({sc_settings}).</li>
<li><b>Themes</b>: 9 themes covering light and dark.</li>
<li><b>Language</b>: 简体 / 繁體 / English.</li>
<li><b>Icon style</b>: several icon styles are available.</li>
<li><b>Custom shortcuts</b>: Settings → Shortcuts to edit entries, with the option to restore defaults.</li>
<li><b>Chart font</b>: set chart font sizes globally; 3D charts follow the interface font size.</li>
<li><b>Data directory</b>: shows the data directory (projects, shortcuts, logs, etc.).</li>
<li><b>Export defaults</b>: default chart format and DPI are configurable.</li>
</ul>

<h3>18. Keyboard Shortcuts</h3>
<p>The following shortcuts can be modified by you in <b>Settings → Shortcuts</b> (shown here following your changes):</p>
<table border="1" cellspacing="0" cellpadding="4" width="100%">
<tr><th>Action</th><th>Default key</th></tr>
<tr><td>Play / Pause</td><td>Space</td></tr>
<tr><td>Stop</td><td>Shift+Space</td></tr>
<tr><td>Record</td><td>R</td></tr>
<tr><td>Stop playback</td><td>Esc</td></tr>
<tr><td>Open file</td><td>{sc_open}</td></tr>
<tr><td>Export chart</td><td>{sc_export}</td></tr>
<tr><td>Settings</td><td>{sc_settings}</td></tr>
<tr><td>Zoom in / out / fit</td><td>Ctrl+= / Ctrl+- / Ctrl+0</td></tr>
<tr><td>Preview selection</td><td>P</td></tr>
<tr><td>A/B loop selection (toggle)</td><td>L</td></tr>
<tr><td>Add time mark</td><td>T</td></tr>
<tr><td>Add text mark</td><td>M</td></tr>
<tr><td>Undo last mark</td><td>Shift+T</td></tr>
</table>
<p>The following are fixed bindings:</p>
<table border="1" cellspacing="0" cellpadding="4" width="100%">
<tr><th>Action</th><th>Key</th></tr>
<tr><td>Switch view (Spectrum / Spectrogram / Pitch / Formants / Timbre / 3D / Room Modes)</td><td>F2 · F3 · F4 · F5 · F6 · F7 · F8</td></tr>
<tr><td>Tuning ruler overlay (on/off)</td><td>F9</td></tr>
<tr><td>Chart Designer</td><td>F10</td></tr>
<tr><td>Multitrack compare (enter / exit)</td><td>Ctrl+M</td></tr>
<tr><td>Open / Save / New project</td><td>Ctrl+Shift+O / Ctrl+S / Ctrl+N</td></tr>
<tr><td>AI Interpretation</td><td>Ctrl+I</td></tr>
<tr><td>Undo / Redo</td><td>{sc_undo} / {sc_redo}</td></tr>
<tr><td>Cut / Copy / Paste</td><td>{sc_cut} / {sc_copy} / {sc_paste}</td></tr>
<tr><td>Delete selection</td><td>Delete (or Backspace)</td></tr>
<tr><td>Silence selection / Trim to selection</td><td>{sc_silence} / {sc_trim}</td></tr>
<tr><td>Select all</td><td>{sc_sel_all}</td></tr>
<tr><td>Zoom to selection</td><td>Shift+Z</td></tr>
<tr><td>Analyze region</td><td>Ctrl+Shift+R</td></tr>
<tr><td>Region statistics</td><td>Ctrl+Shift+S</td></tr>
<tr><td>Export report</td><td>Ctrl+Shift+P</td></tr>
<tr><td>Quit</td><td>Ctrl+Q (Cmd+Q on macOS)</td></tr>
</table>

<h3>19. Open Source and License</h3>
<ul>
<li><b>License</b>: GPL-3.0-only, consistent with Qt / PyQt6.</li>
<li><b>No tiers</b>: open-source software with no feature tiers; no registration or activation required.</li>
<li><b>Third-party licenses</b>: a list of third-party licenses and sources is bundled with the installer.</li>
<li><b>Model download</b>: models are downloaded and verified automatically on first use; afterwards they work offline.</li>
<li><b>Bundled FFmpeg</b>: audio decoding uses a bundled FFmpeg — no system encoder needed (bundled in the full package only; the core package requires a self-installed FFmpeg).</li>
<li><b>Local computation</b>: analysis runs locally; data is not sent out unless you explicitly pick a cloud AI provider.</li>
<li><b>Privacy note</b>: before using a cloud AI, confirm anonymization and authorization of your data.</li>
<li><b>Full text</b>: the full license text is in the bundled LICENSE file.</li>
</ul>

<h3>20. Tuning Ruler</h3>
<ul>
<li><b>Entry</b>: Tools → Tuning Ruler Overlay (F9), or the button of the same name on the Analysis toolbar; check it to switch the overlay on, click again to switch it off.</li>
<li><b>What it does</b>: overlays the scale-degree reference lines of the chosen tuning on the spectrogram and pitch views, so you can read microtones and tuning deviations.</li>
<li><b>Tuning templates</b>: Tools → Tuning Template offers 12-tone equal temperament, 5-limit just major, the 3/2 fifth-chain diatonic, 1/4-comma meantone, the Chinese twelve-lü (sanfen sunyi) set, 22-shruti and 24-tone equal divisions, plus "Do not show" — equal and unequal divisions alike, not just 12-TET.</li>
<li><b>Custom tuning templates</b>: Tools → Manage Custom Tuning Templates… to add, edit, delete, import and export; templates are stored in the user data directory and reappear in the Tuning Template submenu and the batch-readout dropdown after restart; the eight built-in templates remain read-only.</li>
<li><b>Follows the reference pitch</b>: the lines are computed from Settings → Preferences → General → A4 reference (Hz), the same basis used for cents and note-name readouts.</li>
<li><b>With multitrack</b>: while the overlay is on, multitrack difference statistics attribute each frame to a degree of the current tuning.</li>
<li><b>Limits</b>: the overlay only draws reference lines and never changes the raw f0 results; the switch and the current template choice live in the current session only and are not written to the workspace; custom templates themselves persist in the user data directory.</li>
<li><b>Use cases</b>: tuning research and pitch analysis of microtonal or traditional musics; complements the "tuning and microtonal analysis" note in the FFT Spectrum section — use that one for the peaks of a single frame, this one for how pitch moves over time.</li>
</ul>
""",
}


def _format_shortcuts(text: str) -> str:
    """将手册中的 {sc_*} 占位符替换为平台快捷键。

    G12：macOS 用户面一律用符号（Ctrl→⌘ / Meta→⌃ / Alt→⌥ / Shift→⇧，Qt 的
    macOS 语义），其它平台保持原样；正文里的字面键位串同样在渲染期过一遍
    `display_key`（源文案不动，故既有内容守卫按源码钉的行一律不变）。
    """
    from acouscope.ui.shortcuts import display_key, is_macos

    def d(key: str) -> str:
        # 与设置页快捷键表同口径：entry.current_key 是绑定口径原串（Ctrl+O），
        # display_key 直接把 Ctrl→⌘。若先过 sc()，macOS 会把 Ctrl 翻成 Meta，
        # 再显示成 ⌃O（手册 ⌃O / 设置表 ⌘O 的口径分裂）。
        return display_key(key)

    # {sc_redo}：action_redo 使用 QKeySequence.StandardKey.Redo，macOS 实际为 Cmd+Shift+Z，
    # 而 Windows/Linux 为 Ctrl+Y。此前固定映射 Ctrl+Y（macOS 显示 Cmd+Y）与真实值不一致，
    # 此处按平台真实值输出（T-1057 授权修补）。
    redo = "⌘⇧Z" if is_macos() else "Ctrl+Y"

    out = text.format(
        sc_open=d("Ctrl+O"),
        sc_undo=d("Ctrl+Z"),
        sc_redo=redo,
        sc_cut=d("Ctrl+X"),
        sc_copy=d("Ctrl+C"),
        sc_paste=d("Ctrl+V"),
        sc_silence=d("Ctrl+L"),
        sc_trim=d("Ctrl+T"),
        sc_sel_all=d("Ctrl+A"),
        sc_export=d("Ctrl+E"),
        sc_settings=d("Ctrl+,"),
    )
    # 正文里的字面键位（"Ctrl+M" / "Shift+Space" / "Cmd+Q" …）同样转成平台
    # 显示符号：display_key 覆盖绑定口径修饰词，Cmd+ 是手册里的口语写法，
    # 单独归一到 ⌘，避免同一篇手册 ⌃/⌘/Cmd+ 三种写法混排。
    out = display_key(out)
    if is_macos():
        out = out.replace("Cmd+", "⌘")
    return out


class _HelpDialog(QWidget):
    """帮助内容面板基类：滚动文本浏览器 + 关闭按钮（非模态，T-504e 抽屉宿主）。"""

    cancelled = pyqtSignal()  # “关闭”按钮点击 → 宿主关闭抽屉

    def __init__(self, content_map: dict[str, str], title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(0, 480)  # 宽度交给抽屉决定

        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        lang = get_language()
        html = content_map.get(lang) or content_map.get("en_US", "")
        browser.setHtml(_format_shortcuts(html))
        layout.addWidget(browser)

        self.btn_close = QPushButton(tr("btn.close"))
        self.btn_close.clicked.connect(self.cancelled)
        layout.addWidget(self.btn_close)


class QuickStartDialog(_HelpDialog):
    """快速入门对话框。"""

    def __init__(self, parent=None):
        super().__init__(QUICK_START, tr("help.quickstart.title"), parent)


class ManualDialog(_HelpDialog):
    """用户手册对话框。"""

    def __init__(self, parent=None):
        super().__init__(MANUAL, tr("help.manual.title"), parent)
