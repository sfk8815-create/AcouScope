# SPDX-License-Identifier: GPL-3.0-only
"""轻量国际化模块。

支持三种语言：English (en_US)、简体中文 (zh_CN)、繁体中文 (zh_TW)。
基于字典查表，不依赖 Qt 的 .ts/.qm 编译流程。
切换语言后调用方需重新构建 UI（retranslate_ui）。
"""

from __future__ import annotations

from typing import Dict

# ---------------------------------------------------------------------------
# 语言定义
# ---------------------------------------------------------------------------

LANGUAGES = {
    "en_US": "English",
    "zh_CN": "简体中文",
    "zh_TW": "繁體中文",
}

DEFAULT_LANG = "en_US"

_current_lang = DEFAULT_LANG

# ---------------------------------------------------------------------------
# 翻译字典（按 key 组织，每个 key 下有三种语言的文本）
# ---------------------------------------------------------------------------

_STRINGS: Dict[str, Dict[str, str]] = {
    # --- 菜单 ---
    "menu.file":      {"en_US": "&File",       "zh_CN": "文件(&F)",       "zh_TW": "檔案(&F)"},
    "menu.analysis":  {"en_US": "&Analysis",   "zh_CN": "分析(&A)",       "zh_TW": "分析(&A)"},
    "menu.settings":  {"en_US": "&Settings",   "zh_CN": "设置(&S)",       "zh_TW": "設定(&S)"},
    "menu.help":      {"en_US": "&Help",       "zh_CN": "帮助(&H)",       "zh_TW": "說明(&H)"},
    # --- T-1002 菜单信息架构：新增「视图」「工具」两菜单 ---
    "menu.view":      {"en_US": "&View",       "zh_CN": "视图(&V)",       "zh_TW": "檢視(&V)"},
    "menu.tools":     {"en_US": "&Tools",      "zh_CN": "工具(&T)",       "zh_TW": "工具(&T)"},
    # --- T-1002 新增动作（视图/工具/分析/文件；留位项见 report） ---
    "action.new_project": {
        "en_US": "New Project…", "zh_CN": "新建项目…", "zh_TW": "新建專案…",
    },
    "action.export_report": {
        "en_US": "Export Report…", "zh_CN": "导出报告…", "zh_TW": "匯出報告…",
    },
    # T-1102 M-B′-β1：报告 PDF 导出菜单项（文件 ▸ 导出 ▸ …）
    "action.export_report_pdf": {
        "en_US": "Export Report PDF…", "zh_CN": "导出报告 PDF…", "zh_TW": "匯出報告 PDF…",
    },
    # --- T-1003 分析报告（入口/流程/报告文案）· T-1100 主产物改自包含 HTML ---
    "report.dialog_title": {
        "en_US": "Export Report", "zh_CN": "导出报告", "zh_TW": "匯出報告",
    },
    "report.pdf_dialog_title": {
        "en_US": "Export Report PDF", "zh_CN": "导出报告 PDF", "zh_TW": "匯出報告 PDF",
    },
    "report.filter_html": {
        "en_US": "HTML report (*.html)", "zh_CN": "HTML 报告 (*.html)", "zh_TW": "HTML 報告 (*.html)",
    },
    "report.filter_pdf": {
        "en_US": "PDF report (*.pdf)", "zh_CN": "PDF 报告 (*.pdf)", "zh_TW": "PDF 報告 (*.pdf)",
    },
    "report.exporting": {
        "en_US": "Generating report…", "zh_CN": "正在生成报告…", "zh_TW": "正在產生報告…",
    },
    "report.exported": {
        "en_US": "Report exported:\n{path}",
        "zh_CN": "报告已导出：\n{path}",
        "zh_TW": "報告已匯出：\n{path}",
    },
    "report.failed": {
        "en_US": "Report export failed:\n{error}",
        "zh_CN": "报告导出失败：\n{error}",
        "zh_TW": "報告匯出失敗：\n{error}",
    },
    "report.relocated": {
        "en_US": "The original folder is not writable (macOS privacy protection).\n"
                  "The report was saved to another folder instead.",
        "zh_CN": "原目标目录无写入权限（macOS 系统隐私权限限制）。\n报告已改存到其他目录。",
        "zh_TW": "原目標目錄無寫入權限（macOS 系統隱私權限限制）。\n報告已改存到其他目錄。",
    },
    "report.metadata": {
        "en_US": "Metadata", "zh_CN": "元数据", "zh_TW": "中繼資料",
    },
    "report.tech_info": {
        "en_US": "Technical Information", "zh_CN": "技术信息", "zh_TW": "技術資訊",
    },
    "report.filename": {
        "en_US": "File Name", "zh_CN": "文件名", "zh_TW": "檔名",
    },
    "report.degraded": {
        "en_US": "Metadata unavailable — degraded report: title and technical information only.",
        "zh_CN": "元数据缺失 — 降级报告：仅含题名与技术信息。",
        "zh_TW": "中繼資料缺失 — 降級報告：僅含題名與技術資訊。",
    },
    "report.untitled": {
        "en_US": "Untitled", "zh_CN": "未命名", "zh_TW": "未命名",
    },
    "report.figure_missing": {
        "en_US": "(figure unavailable)", "zh_CN": "（图不可用）", "zh_TW": "（圖不可用）",
    },
    "report.caption_range": {
        "en_US": "Time range: {t0} – {t1} s",
        "zh_CN": "时间范围：{t0} – {t1} s",
        "zh_TW": "時間範圍：{t0} – {t1} s",
    },
    # --- T-1103 M-B′-β2 报告预览面板（index5 页入口 + 顶栏控件） ---
    "action.report_preview": {
        "en_US": "Report Preview…", "zh_CN": "报告预览…", "zh_TW": "報告預覽…",
    },
    "report.preview_title": {
        "en_US": "Report preview", "zh_CN": "报告预览", "zh_TW": "報告預覽",
    },
    "report.orientation_portrait": {
        "en_US": "Portrait", "zh_CN": "纵向", "zh_TW": "縱向",
    },
    "report.orientation_landscape": {
        "en_US": "Landscape", "zh_CN": "横向", "zh_TW": "橫向",
    },
    "report.dpi_label": {
        "en_US": "Resolution (DPI)", "zh_CN": "分辨率（DPI）", "zh_TW": "解析度（DPI）",
    },
    "report.margin_label": {
        "en_US": "Margin (mm)", "zh_CN": "边距（毫米）", "zh_TW": "邊距（毫米）",
    },
    "report.preview_refresh": {
        "en_US": "Refresh", "zh_CN": "刷新", "zh_TW": "重新整理",
    },
    "report.preview_export_btn": {
        "en_US": "Export PDF", "zh_CN": "导出 PDF", "zh_TW": "匯出 PDF",
    },
    # T-1109 IM-32：预览页「导出报告(HTML)」按钮 + 关闭按钮
    "report.preview_export_html_btn": {
        "en_US": "Export Report (HTML)…", "zh_CN": "导出报告(HTML)…", "zh_TW": "匯出報告(HTML)…",
    },
    "report.preview_close_btn": {
        "en_US": "Close", "zh_CN": "关闭", "zh_TW": "關閉",
    },
    # --- T-1104 M-C′·MC-1 报告 AI 解读段（预览顶栏入口 + 生成流程文案） ---
    "action.report_ai": {
        "en_US": "Generate AI Interpretation",
        "zh_CN": "生成 AI 解读",
        "zh_TW": "產生 AI 解讀",
    },
    "report.ai_section_title": {
        "en_US": "AI Interpretation", "zh_CN": "AI 解读", "zh_TW": "AI 解讀",
    },
    "report.ai_unavailable": {
        "en_US": "No AI provider is configured yet. Set one up in Settings → AI first.",
        "zh_CN": "尚未配置可用的 AI 服务商，请先在设置 → AI 中完成配置。",
        "zh_TW": "尚未配置可用的 AI 服務商，請先在設定 → AI 中完成配置。",
    },
    "report.ai_generating": {
        "en_US": "Generating AI interpretation…",
        "zh_CN": "正在生成 AI 解读…",
        "zh_TW": "正在產生 AI 解讀…",
    },
    "report.ai_done": {
        "en_US": "AI interpretation added — preview/export will include it.",
        "zh_CN": "AI 解读已生成，预览与导出将随报告包含该段。",
        "zh_TW": "AI 解讀已產生，預覽與匯出將隨報告包含該段。",
    },
    "report.ai_failed": {
        "en_US": "AI interpretation failed:\n{error}",
        "zh_CN": "AI 解读生成失败：\n{error}",
        "zh_TW": "AI 解讀產生失敗：\n{error}",
    },
    "report.ai_cancelled": {
        "en_US": "AI interpretation cancelled.",
        "zh_CN": "AI 解读已取消。",
        "zh_TW": "AI 解讀已取消。",
    },
    "report.ai_placeholder": {
        "en_US": "AI interpretation will appear here after generation.",
        "zh_CN": "生成后，AI 解读将显示于此。",
        "zh_TW": "產生後，AI 解讀將顯示於此。",
    },
    "action.analyze_region": {
        "en_US": "Analyze Selection", "zh_CN": "分析此区域", "zh_TW": "分析此區域",
    },
    "action.multitrack_compare": {
        "en_US": "Compare Tracks…", "zh_CN": "多轨对比…", "zh_TW": "多軌對比…",
    },
    # --- T-1004 多轨态（轨道区；D9 区域命名 / D10 音量与电平）---
    "multitrack.area_title": {
        "en_US": "Track Area", "zh_CN": "轨道区", "zh_TW": "軌道區",
    },
    "multitrack.waveform_area": {
        "en_US": "Waveform Area", "zh_CN": "波形区", "zh_TW": "波形區",
    },
    "multitrack.action_tip": {
        "en_US": "Enter or leave the track area (multi-track); leaving returns to the single-track waveform area",
        "zh_CN": "进入/退出轨道区（多轨态）；退出后回到单轨波形区",
        "zh_TW": "進入/離開軌道區（多軌態）；離開後回到單軌波形區",
    },
    "multitrack.readonly": {
        "en_US": "Read-only compare — edit or record in single-track mode",
        "zh_CN": "只读对比 — 编辑/录音请回单轨模式",
        "zh_TW": "唯讀對比 — 編輯/錄音請回單軌模式",
    },
    "multitrack.empty": {
        "en_US": "Drop audio files here to add tracks",
        "zh_CN": "拖入音频文件以添加轨道",
        "zh_TW": "拖入音訊檔案以新增軌道",
    },
    "multitrack.info": {
        "en_US": "{duration} · {rate}", "zh_CN": "{duration} · {rate}",
        "zh_TW": "{duration} · {rate}",
    },
    "multitrack.status": {
        "en_US": "Track {index}/{total} · {name}",
        "zh_CN": "轨 {index}/{total} · 当前轨 {name}",
        "zh_TW": "軌 {index}/{total} · 當前軌 {name}",
    },
    "multitrack.health": {
        "en_US": "{n} tracks loaded · about {mb} MB",
        "zh_CN": "已加载 {n} 轨 · 占用约 {mb} MB",
        "zh_TW": "已載入 {n} 軌 · 佔用約 {mb} MB",
    },
    "multitrack.unsupported_drop": {
        "en_US": "Unsupported file format: {name}",
        "zh_CN": "不支持的文件格式：{name}",
        "zh_TW": "不支援的檔案格式：{name}",
    },
    "multitrack.removed_toast": {
        "en_US": "Removed track “{name}”",
        "zh_CN": "已移除轨「{name}」",
        "zh_TW": "已移除軌「{name}」",
    },
    "multitrack.undo": {
        "en_US": "Undo", "zh_CN": "撤销移除", "zh_TW": "復原移除",
    },
    "multitrack.add_tip": {
        "en_US": "Add the files selected in the file list as tracks",
        "zh_CN": "把文件列表中选中的文件加入多轨",
        "zh_TW": "把檔案清單中選取的檔案加入多軌",
    },
    "multitrack.add_action": {
        "en_US": "Add as tracks", "zh_CN": "加入多轨", "zh_TW": "加入多軌",
    },
    "multitrack.no_selection": {
        "en_US": "Select one or more audio files in the file list first",
        "zh_CN": "请先在文件列表中选择一个或多个音频文件",
        "zh_TW": "請先在檔案清單中選擇一個或多個音訊檔案",
    },
    # T-1087 M1（真机目测 #7）：轨道区无退出钮 → 工具栏补退出 + Ctrl+M 键位
    "multitrack.exit.tip": {
        "en_US": "Exit multitrack compare (Ctrl+M)",
        "zh_CN": "退出多轨对比（Ctrl+M）",
        "zh_TW": "退出多軌對比（Ctrl+M）",
    },
    "shortcut.multitrack_mode": {
        "en_US": "Toggle Multitrack Compare",
        "zh_CN": "切换多轨对比",
        "zh_TW": "切換多軌對比",
    },
    # T-1087 M2（真机目测 #5）：无选中兜底第二级 = 系统文件框直选
    "multitrack.add_dialog_title": {
        "en_US": "Add audio files as tracks",
        "zh_CN": "选择要加入多轨的音频文件",
        "zh_TW": "選擇要加入多軌的音訊檔案",
    },
    # T-1087 M2（真机目测 #5）：无选中时的兜底入口（展开左栏 + 系统文件框直选）
    "multitrack.tt.name": {
        "en_US": "Track", "zh_CN": "轨道", "zh_TW": "軌道",
    },
    "multitrack.tt.rename": {
        "en_US": "Edit track name", "zh_CN": "编辑轨名", "zh_TW": "編輯軌名",
    },
    "multitrack.tt.solo": {
        "en_US": "Solo (any solo mutes the others)",
        "zh_CN": "独奏（任一轨独奏则其余静音）",
        "zh_TW": "獨奏（任一軌獨奏則其餘靜音）",
    },
    "multitrack.tt.mute": {
        "en_US": "Mute", "zh_CN": "静音", "zh_TW": "靜音",
    },
    "multitrack.tt.volume": {
        "en_US": "Track volume (applies when this track plays)",
        "zh_CN": "轨道音量（播放当前轨时生效）",
        "zh_TW": "軌道音量（播放當前軌時生效）",
    },
    "multitrack.tt.level": {
        "en_US": "Level (file peak when idle, live while playing)",
        "zh_CN": "电平（空闲为读文件峰值，播放时动态）",
        "zh_TW": "電平（閒置為讀檔案峰值，播放時動態）",
    },
    "multitrack.tt.offset": {
        "en_US": "Alignment offset", "zh_CN": "对齐偏移", "zh_TW": "對齊偏移",
    },
    "multitrack.tt.play": {
        "en_US": "Play this track", "zh_CN": "播放该轨", "zh_TW": "播放該軌",
    },
    "multitrack.tt.stop": {
        "en_US": "Stop", "zh_CN": "停止", "zh_TW": "停止",
    },
    "multitrack.tt.remove": {
        "en_US": "Remove track (undoable)", "zh_CN": "移除该轨（可撤销）",
        "zh_TW": "移除該軌（可復原）",
    },
    # --- T-1006 M2 多轨开头对齐（自动对齐 + 逐轨微调）---
    "multitrack.align.tip": {
        "en_US": "Detect each track's first sounding point and align them to one start baseline (offset metadata only; audio files are never modified)",
        "zh_CN": "检测各轨首个发声起点并统一到同一基线（只写偏移元数据，不修改音频文件）",
        "zh_TW": "偵測各軌首個發聲起點並統一至同一基線（只寫偏移中繼資料，不修改音訊檔案）",
    },
    "multitrack.align.done": {
        "en_US": "Aligned {n} tracks · reference: {ref}",
        "zh_CN": "已对齐 {n} 轨 · 参考轨：{ref}",
        "zh_TW": "已對齊 {n} 軌 · 參考軌：{ref}",
    },
    "multitrack.align.skipped": {
        "en_US": "{n} track(s) without a detected onset",
        "zh_CN": "{n} 轨未检测到起点",
        "zh_TW": "{n} 軌未偵測到起點",
    },
    "multitrack.align.all_none": {
        "en_US": "No onset detected in any track — offsets unchanged",
        "zh_CN": "未检测到任何轨道起点，偏移保持不变",
        "zh_TW": "未偵測到任何軌道起點，偏移保持不變",
    },
    "multitrack.align.no_tracks": {
        "en_US": "Add tracks before aligning",
        "zh_CN": "请先添加轨道再对齐",
        "zh_TW": "請先新增軌道再對齊",
    },
    "multitrack.align.none": {
        "en_US": "No onset detected", "zh_CN": "未检测到起点",
        "zh_TW": "未偵測到起點",
    },
    "multitrack.align.onset": {
        "en_US": "Onset {ms} ms", "zh_CN": "起点 {ms} ms", "zh_TW": "起點 {ms} ms",
    },
    "multitrack.tt.offset_coarse": {
        "en_US": "Nudge by {step} ms (the value box steps by 1 ms)",
        "zh_CN": "按 {step} ms 粗调（数值框步进为 1 ms）",
        "zh_TW": "按 {step} ms 粗調（數值框步進為 1 ms）",
    },
    "multitrack.tt.align": {
        "en_US": "Alignment state (onset detected by Auto Align)",
        "zh_CN": "对齐状态（自动对齐检测到的起点）",
        "zh_TW": "對齊狀態（自動對齊偵測到的起點）",
    },
    # --- T-1009 M4 多轨对比呈现（一图 / 多图 / 密度热图）---
    "multitrack.compare.title": {
        "en_US": "Comparison view", "zh_CN": "对比呈现", "zh_TW": "對比呈現",
    },
    "multitrack.compare.mode_single": {
        "en_US": "Single chart", "zh_CN": "一图", "zh_TW": "單圖",
    },
    "multitrack.compare.mode_single_tip": {
        "en_US": "Overlay every track's pitch curve on one shared time axis (reference track drawn thicker and dashed)",
        "zh_CN": "全部轨音高曲线叠绘于同一共享时间轴（参考轨加粗虚线）",
        "zh_TW": "全部軌音高曲線疊繪於同一共享時間軸（參考軌加粗虛線）",
    },
    "multitrack.compare.mode_grid": {
        "en_US": "Multiple charts", "zh_CN": "多图", "zh_TW": "多圖",
    },
    "multitrack.compare.mode_grid_tip": {
        "en_US": "One chart per track with a shared playhead and shared zoom",
        "zh_CN": "每轨一图，共享播放头与缩放",
        "zh_TW": "每軌一圖，共享播放頭與縮放",
    },
    "multitrack.compare.heatmap": {
        "en_US": "Density heatmap", "zh_CN": "密度热图", "zh_TW": "密度熱圖",
    },
    "multitrack.compare.heatmap_tip": {
        "en_US": "Time-frequency density overview of the pitch curves (off by default with fewer than 4 tracks)",
        "zh_CN": "音高曲线的时间-频率密度总览（轨数少于 4 时默认关闭）",
        "zh_TW": "音高曲線的時間-頻率密度總覽（軌數少於 4 時預設關閉）",
    },
    "multitrack.compare.analyze": {
        "en_US": "Analyze tracks", "zh_CN": "运行逐轨分析", "zh_TW": "執行逐軌分析",
    },
    "multitrack.compare.analyze_tip": {
        "en_US": "Run pitch analysis for every track and show the results here",
        "zh_CN": "对全部轨运行音高分析，结果呈现在此视图",
        "zh_TW": "對全部軌執行音高分析，結果呈現在此檢視",
    },
    "multitrack.compare.analyzed": {
        "en_US": "Pitch analysis finished for {n} track(s)",
        "zh_CN": "已完成 {n} 轨音高分析", "zh_TW": "已完成 {n} 軌音高分析",
    },
    "multitrack.compare.analyze_failed": {
        "en_US": "No pitch result produced — check that the audio of each track is available",
        "zh_CN": "未产生音高结果，请确认各轨音频可用",
        "zh_TW": "未產生音高結果，請確認各軌音訊可用",
    },
    "multitrack.compare.no_tracks": {
        "en_US": "Add tracks before comparing", "zh_CN": "请先添加轨道再对比",
        "zh_TW": "請先新增軌道再對比",
    },
    "multitrack.compare.no_result": {
        "en_US": "No pitch result yet — run track-by-track analysis first",
        "zh_CN": "暂无音高结果，请先运行逐轨分析",
        "zh_TW": "尚無音高結果，請先執行逐軌分析",
    },
    "multitrack.compare.reference": {
        "en_US": "Reference track", "zh_CN": "参考轨", "zh_TW": "參考軌",
    },
    "multitrack.compare.reference_tip": {
        "en_US": "Track used as the comparison baseline (drawn thicker and dashed)",
        "zh_CN": "作为对比基准的轨（加粗虚线绘制）",
        "zh_TW": "作為對比基準的軌（加粗虛線繪製）",
    },
    "multitrack.compare.diff_stats": {
        "en_US": "Difference statistics", "zh_CN": "差异统计", "zh_TW": "差異統計",
    },
    "multitrack.compare.diff_tip": {
        "en_US": "Compare every track against the reference track (alarm threshold, not an accuracy claim); results drive the difference bar, hover readout and CSV export",
        "zh_CN": "逐轨与参考轨对比（报警阈值，非精度承诺）；结果为差异条、悬停读数与 CSV 导出",
        "zh_TW": "逐軌與參考軌對比（報警閾值，非精度承諾）；結果為差異條、懸停讀數與 CSV 匯出",
    },
    "multitrack.compare.diff_unit_cents": {
        "en_US": "cents (12TET)", "zh_CN": "音分 (cents)", "zh_TW": "音分 (cents)",
    },
    "multitrack.compare.diff_unit_tip": {
        "en_US": "Difference unit: cents by default (12TET reference grid); differences are objective cent values independent of any tuning system",
        "zh_CN": "差异单位：默认音分（12TET 参考网格）；差异为客观音分差，与律制无关",
        "zh_TW": "差異單位：預設音分（12TET 參考網格）；差異為客觀音分差，與律制無關",
    },
    "multitrack.compare.diff_threshold_note": {
        "en_US": "Alarm threshold, not an accuracy claim",
        "zh_CN": "报警阈值，非精度承诺",
        "zh_TW": "報警閾值，非精度承諾",
    },
    "multitrack.compare.diff_summary": {
        "en_US": "Alarm threshold {threshold} cents; tracks compared {tracks}; largest over-threshold ratio {ratio}",
        "zh_CN": "报警阈值 {threshold} cents；比较轨数 {tracks}；最大超阈占比 {ratio}",
        "zh_TW": "報警閾值 {threshold} cents；比較軌數 {tracks}；最大超閾佔比 {ratio}",
    },
    "multitrack.compare.diff_no_pair": {
        "en_US": "(no comparable frame)", "zh_CN": "（无可比帧）", "zh_TW": "（無可比幀）",
    },
    "multitrack.compare.diff_pairing_note": {
        "en_US": "Frame rates differ: intersection timeline used (no interpolation)",
        "zh_CN": "帧率不一致：取交集时间轴（不插值）",
        "zh_TW": "幀率不一致：取交集時間軸（不插值）",
    },
    "multitrack.compare.diff_export": {
        "en_US": "Export difference CSV…", "zh_CN": "导出差异表 CSV…", "zh_TW": "匯出差異表 CSV…",
    },
    "multitrack.compare.diff_export_tip": {
        "en_US": "Export the per-frame difference table (track / time / ΔHz / Δcent / over-threshold flag / reference track)",
        "zh_CN": "导出逐帧差异表（轨 / 时间 / ΔHz / Δcent / 超阈标记 / 参考轨名）",
        "zh_TW": "匯出逐幀差異表（軌 / 時間 / ΔHz / Δcent / 超閾標記 / 參考軌名）",
    },
    "multitrack.compare.diff_export_title": {
        "en_US": "Export Multitrack Difference Table",
        "zh_CN": "导出多轨差异表", "zh_TW": "匯出多軌差異表",
    },
    "multitrack.compare.diff_export_done": {
        "en_US": "Difference table exported", "zh_CN": "差异表已导出", "zh_TW": "差異表已匯出",
    },
    "multitrack.compare.diff_export_failed": {
        "en_US": "Difference table export failed",
        "zh_CN": "差异表导出失败", "zh_TW": "差異表匯出失敗",
    },
    "multitrack.compare.diff_export_empty": {
        "en_US": "No comparable difference data yet; run per-track analysis and compute differences first",
        "zh_CN": "暂无可导出的差异数据，请先执行逐轨分析并计算差异",
        "zh_TW": "暫無可匯出的差異資料，請先執行逐軌分析並計算差異",
    },
    # --- T-1089 N-B：差异可见化（逐轨量化 + 全轨一致性 + 截断告知）---
    "multitrack.compare.diff_overview_stats": {
        "en_US": "overall mean |delta| {mean_abs}, max {max_abs}; {over_tracks} track(s) over alarm (worst: {worst})",
        "zh_CN": "全轨平均|Δ| {mean_abs} · 最大 {max_abs} · {over_tracks} 轨存在超阈（最高：{worst}）",
        "zh_TW": "全軌平均|Δ| {mean_abs} · 最大 {max_abs} · {over_tracks} 軌存在超閾（最高：{worst}）",
    },
    "multitrack.compare.diff_track_stats": {
        "en_US": "{label}: mean |delta| {mean_abs}, over {over}, max {max_abs}",
        "zh_CN": "{label}：平均|Δ| {mean_abs} · 超阈 {over} · 最大 {max_abs}",
        "zh_TW": "{label}：平均|Δ| {mean_abs} · 超閾 {over} · 最大 {max_abs}",
    },
    "multitrack.compare.diff_more_tracks": {
        "en_US": "+{n} track(s) not listed",
        "zh_CN": "＋{n} 轨未列",
        "zh_TW": "＋{n} 軌未列",
    },
    "multitrack.compare.diff_bar_more": {
        "en_US": "+{n} track(s) not drawn",
        "zh_CN": "＋{n} 轨未画",
        "zh_TW": "＋{n} 軌未畫",
    },
    # --- T-1089 N-C：坐标轴标注（单位与时间轴·语言中立文本仍走 tr 保持三语一致口径）---
    "multitrack.compare.axis_hz": {
        "en_US": "Hz", "zh_CN": "Hz", "zh_TW": "Hz",
    },
    "multitrack.compare.axis_time": {
        "en_US": "Time", "zh_CN": "时间", "zh_TW": "時間",
    },
    # --- T-1089 N-E：可解释指标（呈现层只读派生·量化层零改）---
    "multitrack.compare.diff_analysis_stats": {
        "en_US": "analysis: |delta| p50 {p50} / p95 {p95}, bias {bias}, shared degrees {shared}, tuning remainder {remainder}",
        "zh_CN": "分析指标：|Δ| p50 {p50} · p95 {p95} · 系统偏差 {bias} · 共同音级 {shared} · 律制余差 {remainder}",
        "zh_TW": "分析指標：|Δ| p50 {p50} · p95 {p95} · 系統偏差 {bias} · 共同音級 {shared} · 律製餘差 {remainder}",
    },
    # --- T-1089 N-F：热图色标量纲（绝对计数）---
    "multitrack.compare.heatmap_colorbar_unit": {
        "en_US": "frames/bin", "zh_CN": "帧/格", "zh_TW": "幀/格",
    },
    # --- 多轨测量结果表格界面键（M3）---
    "multitrack.measure.col_file": {
        "en_US": "File", "zh_CN": "文件", "zh_TW": "檔案",
        "ko_KR": "파일", "ja_JP": "ファイル",
    },
    "multitrack.measure.col_duration_s": {
        "en_US": "Duration (s)", "zh_CN": "时长（秒）", "zh_TW": "時長（秒）",
        "ko_KR": "길이(초)", "ja_JP": "長さ(秒)",
    },
    "multitrack.measure.col_sample_rate": {
        "en_US": "Sample Rate", "zh_CN": "采样率", "zh_TW": "取樣率",
        "ko_KR": "샘플레이트", "ja_JP": "サンプリングレート",
    },
    "multitrack.measure.col_channels": {
        "en_US": "Channels", "zh_CN": "声道", "zh_TW": "聲道",
        "ko_KR": "채널", "ja_JP": "チャネル",
    },
    "multitrack.measure.col_rms_db": {
        "en_US": "RMS (dB)", "zh_CN": "有效值（dB）", "zh_TW": "有效值（dB）",
        "ko_KR": "RMS(dB)", "ja_JP": "RMS(dB)",
    },
    "multitrack.measure.col_peak_db": {
        "en_US": "Peak (dB)", "zh_CN": "峰值（dB）", "zh_TW": "峰值（dB）",
        "ko_KR": "피크(dB)", "ja_JP": "ピーク(dB)",
    },
    "multitrack.measure.col_f0_median_hz": {
        "en_US": "F0 Median (Hz)", "zh_CN": "基频中位值（Hz）", "zh_TW": "基頻中位值（Hz）",
        "ko_KR": "F0 중앙값(Hz)", "ja_JP": "F0中央値(Hz)",
    },
    "multitrack.measure.col_status": {
        "en_US": "Status", "zh_CN": "状态", "zh_TW": "狀態",
        "ko_KR": "상태", "ja_JP": "状態",
    },
    "multitrack.measure.tab": {
        "en_US": "Measurements", "zh_CN": "测量结果", "zh_TW": "測量結果",
        "ko_KR": "측정 결과", "ja_JP": "測定結果",
    },
    "multitrack.measure.measure": {
        "en_US": "Measure All", "zh_CN": "测量全部", "zh_TW": "測量全部",
        "ko_KR": "전체 측정", "ja_JP": "全測定",
    },
    "multitrack.measure.export": {
        "en_US": "Export CSV", "zh_CN": "导出 CSV", "zh_TW": "匯出 CSV",
        "ko_KR": "CSV 내보내기", "ja_JP": "CSVエクスポート",
    },
    "multitrack.measure.empty": {
        "en_US": "No measurement results yet. Click \"Measure All\" to start.",
        "zh_CN": "尚无测量结果。点击「测量全部」开始。",
        "zh_TW": "尚無測量結果。點擊「測量全部」開始。",
        "ko_KR": "측정 결과가 없습니다. \"전체 측정\"을 클릭하십시오.",
        "ja_JP": "測定結果がありません。「全測定」をクリックしてください。",
    },
    "multitrack.measure.done": {
        "en_US": "Measured {n} files", "zh_CN": "已测量 {n} 个文件",
        "zh_TW": "已測量 {n} 個檔案",
        "ko_KR": "{n}개 파일 측정 완료", "ja_JP": "{n}ファイル測定完了",
    },
    "multitrack.measure.status_measured": {
        "en_US": "Measured", "zh_CN": "已测量", "zh_TW": "已測量",
        "ko_KR": "측정됨", "ja_JP": "測定済み",
    },
    "multitrack.measure.status_partial": {
        "en_US": "Partial", "zh_CN": "部分", "zh_TW": "部分",
        "ko_KR": "일부", "ja_JP": "一部",
    },
    "multitrack.measure.status_missing": {
        "en_US": "Missing", "zh_CN": "缺失", "zh_TW": "缺失",
        "ko_KR": "누락", "ja_JP": "欠落",
    },
    "action.batch": {
        "en_US": "Batch Processing…", "zh_CN": "批处理…", "zh_TW": "批次處理…",
    },
    "action.annotation_mode": {
        "en_US": "Annotation Mode", "zh_CN": "标注模式", "zh_TW": "標註模式",
    },
    "action.restore_layout": {
        "en_US": "Restore Default Layout", "zh_CN": "恢复默认布局", "zh_TW": "恢復預設佈局",
    },
    "action.shortcuts_overview": {
        "en_US": "Shortcut Overview", "zh_CN": "快捷键总览", "zh_TW": "快捷鍵總覽",
    },
    "action.shortcuts_empty": {
        "en_US": "(no shortcut)", "zh_CN": "（无快捷键）", "zh_TW": "（無快捷鍵）",
    },
    # --- 文件菜单 ---
    "action.open":        {"en_US": "Open File…",      "zh_CN": "打开文件…",       "zh_TW": "開啟檔案…"},
    "action.open_project":{"en_US": "Open Project…",   "zh_CN": "打开项目…",       "zh_TW": "開啟專案…"},
    "action.save_project":{"en_US": "Save Project",     "zh_CN": "保存项目",         "zh_TW": "儲存專案"},
    "action.save_as":     {"en_US": "Save Project As…","zh_CN": "项目另存为…",     "zh_TW": "專案另存…"},
    "autosave.restore_title": {"en_US": "Restore Autosaved Project", "zh_CN": "恢复自动保存的项目", "zh_TW": "還原自動儲存的專案"},
    "autosave.restore_body": {"en_US": "The previous session ended unexpectedly. An autosaved project snapshot was found. Restore it now?", "zh_CN": "检测到上次未正常退出，并发现自动保存的项目快照。是否立即恢复？", "zh_TW": "偵測到上次未正常結束，並發現自動儲存的專案快照。是否立即還原？"},
    "autosave.fail_once": {"en_US": "Autosave failed. Please save manually.", "zh_CN": "自动保存失败，请手动保存项目。", "zh_TW": "自動儲存失敗，請手動儲存專案。"},
    "action.export":      {"en_US": "Export Figure…",  "zh_CN": "导出图表…",       "zh_TW": "匯出圖表…"},
    "action.quit":        {"en_US": "Quit",             "zh_CN": "退出",             "zh_TW": "結束"},
    # --- 分析菜单 ---
    "action.fft":         {"en_US": "FFT Spectrum",    "zh_CN": "FFT 频谱",         "zh_TW": "FFT 頻譜"},
    "action.spectrogram": {"en_US": "Spectrogram",     "zh_CN": "语谱图",           "zh_TW": "語譜圖"},
    "action.pitch":       {"en_US": "Pitch Detection", "zh_CN": "音高检测",         "zh_TW": "音高偵測"},
    "action.formants":    {"en_US": "Formant Analysis","zh_CN": "共振峰分析",       "zh_TW": "共振峰分析"},
    "action.timbre":      {"en_US": "Timbre Analysis", "zh_CN": "音色分析",         "zh_TW": "音色分析"},
    "action.spectrogram3d":{"en_US": "3D Spectrogram","zh_CN": "3D 频谱图",        "zh_TW": "3D 頻譜圖"},
    "action.ai_interpret":{"en_US": "AI Interpret…",   "zh_CN": "AI 释图…",        "zh_TW": "AI 釋圖…"},
    # --- 设置菜单 ---
    "action.chart_font":  {"en_US": "Chart Font…",      "zh_CN": "图表字体…",       "zh_TW": "圖表字體…"},
    # --- 图表设计器（T-1044 P1：导出前设计交互）---
    "action.chart_designer": {"en_US": "Chart Designer…", "zh_CN": "图表设计器…", "zh_TW": "圖表設計器…"},
    "chart_designer.title": {"en_US": "Chart Designer", "zh_CN": "图表设计器", "zh_TW": "圖表設計器"},
    "chart_designer.preview_placeholder": {"en_US": "Open audio to preview the export here.", "zh_CN": "打开音频后在此预览导出效果。", "zh_TW": "開啟音訊後在此預覽匯出效果。"},
    "chart_designer.group.layout": {"en_US": "Layout", "zh_CN": "版式", "zh_TW": "版式"},
    "chart_designer.group.palette": {"en_US": "Colors", "zh_CN": "配色", "zh_TW": "配色"},
    "chart_designer.group.font": {"en_US": "Fonts", "zh_CN": "字体", "zh_TW": "字體"},
    "chart_designer.group.export": {"en_US": "Export", "zh_CN": "导出", "zh_TW": "匯出"},
    "chart_designer.template": {"en_US": "Journal Template", "zh_CN": "期刊模板", "zh_TW": "期刊範本"},
    "chart_designer.template_default": {"en_US": "Default", "zh_CN": "默认", "zh_TW": "預設"},
    "chart_designer.width": {"en_US": "Figure Width", "zh_CN": "画幅宽", "zh_TW": "畫幅寬"},
    "chart_designer.height": {"en_US": "Figure Height", "zh_CN": "画幅高", "zh_TW": "畫幅高"},
    "chart_designer.grid": {"en_US": "Show Grid", "zh_CN": "显示网格", "zh_TW": "顯示網格"},
    "chart_designer.palette": {"en_US": "Palette", "zh_CN": "配色方案", "zh_TW": "配色方案"},
    "chart_designer.palette.default": {"en_US": "Default (color)", "zh_CN": "默认（彩色）", "zh_TW": "預設（彩色）"},
    "chart_designer.palette.grayscale": {"en_US": "Grayscale", "zh_CN": "灰度", "zh_TW": "灰階"},
    "chart_designer.palette.colorblind": {"en_US": "Colorblind Safe", "zh_CN": "色盲友好", "zh_TW": "色盲友善"},
    "chart_designer.palette.viridis": {"en_US": "viridis (colormap)", "zh_CN": "viridis（色图）", "zh_TW": "viridis（色圖）"},
    "chart_designer.font_latin": {"en_US": "Latin / Digits", "zh_CN": "西文 / 数字", "zh_TW": "西文 / 數字"},
    "chart_designer.font_cjk": {"en_US": "CJK", "zh_CN": "中文", "zh_TW": "中文"},
    "chart_designer.font_auto": {"en_US": "Auto", "zh_CN": "自动", "zh_TW": "自動"},
    "chart_designer.font_jump": {"en_US": "Font Settings…", "zh_CN": "字体设置…", "zh_TW": "字體設定…"},
    "chart_designer.format": {"en_US": "Format", "zh_CN": "导出格式", "zh_TW": "匯出格式"},
    "chart_designer.dpi": {"en_US": "DPI", "zh_CN": "分辨率（DPI）", "zh_TW": "解析度（DPI）"},
    "chart_designer.export": {"en_US": "Export…", "zh_CN": "导出…", "zh_TW": "匯出…"},
    # --- T-1045 P2：内容外壳 + 参考线/阈值线（新增键一律五语齐）---
    "chart_designer.group.content": {
        "en_US": "Content", "zh_CN": "内容", "zh_TW": "內容",
        "ko_KR": "콘텐츠", "ja_JP": "コンテンツ",
    },
    "chart_designer.title_text": {
        "en_US": "Title", "zh_CN": "标题", "zh_TW": "標題",
        "ko_KR": "제목", "ja_JP": "タイトル",
    },
    "chart_designer.subtitle": {
        "en_US": "Subtitle", "zh_CN": "副标题", "zh_TW": "副標題",
        "ko_KR": "부제목", "ja_JP": "サブタイトル",
    },
    "chart_designer.source": {
        "en_US": "Source", "zh_CN": "来源", "zh_TW": "來源",
        "ko_KR": "출처", "ja_JP": "出典",
    },
    "chart_designer.footer": {
        "en_US": "Footer", "zh_CN": "脚注", "zh_TW": "腳註",
        "ko_KR": "바닥글", "ja_JP": "フッター",
    },
    "chart_designer.group.reference": {
        "en_US": "Reference", "zh_CN": "参考线", "zh_TW": "參考線",
        "ko_KR": "기준선", "ja_JP": "基準線",
    },
    "chart_designer.ref_values": {
        "en_US": "Reference values (Hz)", "zh_CN": "参考线数值 (Hz)", "zh_TW": "參考線數值 (Hz)",
        "ko_KR": "기준선 값 (Hz)", "ja_JP": "基準線の値 (Hz)",
    },
    "chart_designer.ref_linestyle": {
        "en_US": "Line style", "zh_CN": "线型", "zh_TW": "線型",
        "ko_KR": "선 스타일", "ja_JP": "線種",
    },
    "chart_designer.ref_linestyle.dashed": {
        "en_US": "Dashed", "zh_CN": "虚线", "zh_TW": "虛線",
        "ko_KR": "점선", "ja_JP": "破線",
    },
    "chart_designer.ref_linestyle.dotted": {
        "en_US": "Dotted", "zh_CN": "点线", "zh_TW": "點線",
        "ko_KR": "점선", "ja_JP": "点線",
    },
    "chart_designer.ref_ink": {
        "en_US": "Reference ink", "zh_CN": "参考线墨色", "zh_TW": "參考線墨色",
        "ko_KR": "기준선 잉크", "ja_JP": "基準線の色",
    },
    "chart_designer.at01_gate": {
        "en_US": "AT-01 gate (±10/±15c)", "zh_CN": "AT-01 精度闸门（±10/±15c）", "zh_TW": "AT-01 精度閘門（±10/±15c）",
        "ko_KR": "AT-01 게이트 (±10/±15c)", "ja_JP": "AT-01 ゲート (±10/±15c)",
    },
    "chart_designer.at01_hint": {
        "en_US": "Measurement accuracy gate — warning threshold, not a precision promise",
        "zh_CN": "测量精度闸门 — 报警阈值，非精度承诺",
        "zh_TW": "測量精度閘門 — 警報閾值，非精度承諾",
        "ko_KR": "측정 정밀도 게이트 — 경보 임계값, 정밀도 약속이 아님",
        "ja_JP": "測定精度ゲート — 警報しきい値であり、精度の約束ではない",
    },
    # --- T-1046 P3：主题预设（会话/项目/全局三层）+ 样式 JSON 导入/导出（新增键五语齐）---
    "chart_designer.preset.name": {
        "en_US": "Preset", "zh_CN": "预设", "zh_TW": "預設",
        "ko_KR": "프리셋", "ja_JP": "プリセット",
    },
    "chart_designer.preset.name_hint": {
        "en_US": "Preset name", "zh_CN": "预设名称", "zh_TW": "預設名稱",
        "ko_KR": "프리셋 이름", "ja_JP": "プリセット名",
    },
    "chart_designer.preset.save": {
        "en_US": "Save", "zh_CN": "保存", "zh_TW": "儲存",
        "ko_KR": "저장", "ja_JP": "保存",
    },
    "chart_designer.preset.overwrite": {
        "en_US": "Save (overwrite)?", "zh_CN": "保存（覆盖）？", "zh_TW": "儲存（覆寫）？",
        "ko_KR": "저장 (덮어쓰기)?", "ja_JP": "保存（上書き）？",
    },
    "chart_designer.preset.load": {
        "en_US": "Load", "zh_CN": "加载", "zh_TW": "載入",
        "ko_KR": "불러오기", "ja_JP": "読み込み",
    },
    "chart_designer.preset.delete": {
        "en_US": "Delete", "zh_CN": "删除", "zh_TW": "刪除",
        "ko_KR": "삭제", "ja_JP": "削除",
    },
    "chart_designer.preset.delete_confirm": {
        "en_US": "Delete?", "zh_CN": "确认删除？", "zh_TW": "確認刪除？",
        "ko_KR": "삭제?", "ja_JP": "削除？",
    },
    "chart_designer.preset.import": {
        "en_US": "Import…", "zh_CN": "导入…", "zh_TW": "匯入…",
        "ko_KR": "가져오기…", "ja_JP": "インポート…",
    },
    "chart_designer.preset.export": {
        "en_US": "Export…", "zh_CN": "导出…", "zh_TW": "匯出…",
        "ko_KR": "내보내기…", "ja_JP": "エクスポート…",
    },
    "chart_designer.preset.name_required": {
        "en_US": "Enter a preset name first.", "zh_CN": "请先输入预设名称。", "zh_TW": "請先輸入預設名稱。",
        "ko_KR": "먼저 프리셋 이름을 입력하세요.", "ja_JP": "プリセット名を入力してください。",
    },
    "chart_designer.preset.saved": {
        "en_US": "Preset saved.", "zh_CN": "预设已保存。", "zh_TW": "預設已儲存。",
        "ko_KR": "프리셋이 저장되었습니다.", "ja_JP": "プリセットを保存しました。",
    },
    "chart_designer.preset.deleted": {
        "en_US": "Preset deleted.", "zh_CN": "预设已删除。", "zh_TW": "預設已刪除。",
        "ko_KR": "프리셋이 삭제되었습니다.", "ja_JP": "プリセットを削除しました。",
    },
    "chart_designer.preset.import_ok": {
        "en_US": "Style imported.", "zh_CN": "样式已导入。", "zh_TW": "樣式已匯入。",
        "ko_KR": "스타일을 가져왔습니다.", "ja_JP": "スタイルをインポートしました。",
    },
    "chart_designer.preset.import_warning": {
        "en_US": "Style imported; {n} unknown key(s) ignored.",
        "zh_CN": "样式已导入；已忽略 {n} 个未知键。",
        "zh_TW": "樣式已匯入；已忽略 {n} 個未知鍵。",
        "ko_KR": "스타일을 가져왔습니다. 알 수 없는 키 {n}개를 무시했습니다.",
        "ja_JP": "スタイルをインポートしました。不明なキー {n} 個を無視しました。",
    },
    "chart_designer.preset.import_reject": {
        "en_US": "Not an AcouScope chart-style file: {fmt}",
        "zh_CN": "非 AcouScope 图表样式文件：{fmt}",
        "zh_TW": "非 AcouScope 圖表樣式檔案：{fmt}",
        "ko_KR": "AcouScope 차트 스타일 파일이 아닙니다: {fmt}",
        "ja_JP": "AcouScope チャートスタイルファイルではありません: {fmt}",
    },
    "chart_designer.preset.import_version": {
        "en_US": "Unsupported style version: {v}",
        "zh_CN": "不支持的样式版本：{v}",
        "zh_TW": "不支援的樣式版本：{v}",
        "ko_KR": "지원하지 않는 스타일 버전: {v}",
        "ja_JP": "未対応のスタイルバージョン: {v}",
    },
    "chart_designer.preset.import_bad_json": {
        "en_US": "Invalid style JSON.",
        "zh_CN": "样式 JSON 无效。",
        "zh_TW": "樣式 JSON 無效。",
        "ko_KR": "스타일 JSON이 유효하지 않습니다.",
        "ja_JP": "スタイル JSON が無効です。",
    },
    "chart_designer.preset.import_missing_params": {
        "en_US": "Style file has no parameters.",
        "zh_CN": "样式文件缺少参数体。",
        "zh_TW": "樣式檔案缺少參數體。",
        "ko_KR": "스타일 파일에 매개변수가 없습니다.",
        "ja_JP": "スタイルファイルにパラメータがありません。",
    },
    "chart_designer.preset.export_ok": {
        "en_US": "Style exported.", "zh_CN": "样式已导出。", "zh_TW": "樣式已匯出。",
        "ko_KR": "스타일을 내보냈습니다.", "ja_JP": "スタイルをエクスポートしました。",
    },
    # --- 帮助菜单 ---
    "action.about":       {"en_US": "About AcouScope","zh_CN": "关于 AcouScope",  "zh_TW": "關於 AcouScope"},
    "action.quickstart":  {"en_US": "Quick Start",    "zh_CN": "快速入门",         "zh_TW": "快速入門"},
    "action.manual":      {"en_US": "User Manual",    "zh_CN": "用户手册",         "zh_TW": "使用者手冊"},
    "action.visit_site":  {"en_US": "Visit Website",  "zh_CN": "访问网站",         "zh_TW": "訪問網站"},
    "action.sponsor":     {"en_US": "Support AcouScope", "zh_CN": "支持 AcouScope", "zh_TW": "支持 AcouScope"},
    "help.quickstart.title": {"en_US": "Quick Start", "zh_CN": "快速入门",         "zh_TW": "快速入門"},
    "help.manual.title":  {"en_US": "User Manual",    "zh_CN": "用户手册",         "zh_TW": "使用者手冊"},
    # --- 工具栏 ---
    "toolbar.file":       {"en_US": "File",            "zh_CN": "文件",             "zh_TW": "檔案"},
    "toolbar.analysis":   {"en_US": "Analysis",        "zh_CN": "分析",             "zh_TW": "分析"},
    "toolbar.ai":         {"en_US": "AI Interpret",    "zh_CN": "AI 释图",          "zh_TW": "AI 釋圖"},
    "toolbar.font":       {"en_US": "Chart Font",      "zh_CN": "图表字体",         "zh_TW": "圖表字體"},
    "toolbar.toggle_ribbon": {"en_US": "Toggle Left Bar", "zh_CN": "左侧图标栏", "zh_TW": "左側圖示欄"},
    "toolbar.toggle_right_panel": {"en_US": "Toggle Right Panel", "zh_CN": "右栏展开/折叠", "zh_TW": "右欄展開/摺疊"},
    # T-1048：工具栏左栏面板开关（纯可见性；与右栏开关成对）
    "toolbar.toggle_left_panel": {"en_US": "Toggle Left Panel", "zh_CN": "左栏展开/折叠", "zh_TW": "左欄展開/摺疊"},
    # T-1054 批0/批3：主工具栏「工作区开关组」全铺页（批3 后房间两开关已启用，
    # tooltip 去「待启用」；图表设计器仍为禁用占位，值保留待启用标记）
    "toolbar.room_modal": {"en_US": "Room Modal", "zh_CN": "房间模态", "zh_TW": "房間模態"},
    "toolbar.room_acoustic": {"en_US": "Room Acoustics", "zh_CN": "房间声学", "zh_TW": "房間聲學"},
    "toolbar.chart_designer": {"en_US": "Chart Designer", "zh_CN": "图表设计器", "zh_TW": "圖表設計器"},
    # G10：溢出菜单「图表设计器」撞名消歧——工作区页入口加「（工作区）」限定，
    # 对话框入口沿用 action.chart_designer（「图表设计器…」带省略号）。
    "overflow.chart_designer_workspace": {
        "en_US": "Chart Designer (Workspace)",
        "zh_CN": "图表设计器（工作区）",
        "zh_TW": "圖表設計器（工作區）",
        "ko_KR": "차트 디자이너 (작업 공간)",
        "ja_JP": "チャートデザイナー（ワークスペース）",
    },
    # G11：图标型开关按钮的无障碍名（AX 树里原为 name 为空的 button）
    "toolbar.overflow_more": {
        "en_US": "More tools", "zh_CN": "更多工具", "zh_TW": "更多工具",
        "ko_KR": "추가 도구", "ja_JP": "その他のツール",
    },
    # 溢出钮**标签**（短词；tooltip/AX 另用 toolbar.overflow_more）
    "toolbar.more": {
        "en_US": "More", "zh_CN": "更多", "zh_TW": "更多",
        "ko_KR": "더 보기", "ja_JP": "その他",
    },
    # --- 命令面板（T-1120）---
    "command_palette.title": {
        "en_US": "Command Palette", "zh_CN": "命令面板", "zh_TW": "命令面板",
        "ko_KR": "명령 팔레트", "ja_JP": "コマンドパレット",
    },
    "command_palette.placeholder": {
        "en_US": "Type a command\u2026", "zh_CN": "输入命令\u2026", "zh_TW": "輸入指令\u2026",
        "ko_KR": "명령 입력\u2026", "ja_JP": "コマンドを入力\u2026",
    },
    "command_palette.empty": {
        "en_US": "No matching command", "zh_CN": "没有匹配的命令", "zh_TW": "沒有符合的指令",
        "ko_KR": "일치하는 명령 없음", "ja_JP": "一致するコマンドなし",
    },
    "command_palette.hint": {
        "en_US": "Enter to run \u00b7 Esc to close", "zh_CN": "Enter 执行 \u00b7 Esc 关闭",
        "zh_TW": "Enter 執行 \u00b7 Esc 關閉",
        "ko_KR": "Enter 실행 \u00b7 Esc 닫기", "ja_JP": "Enter 実行 \u00b7 Esc 閉じる",
    },
    # --- 左右栏 tab 标题（T-1010 侧栏信息架构统一；每类内容唯一宿主）---
    "sidebar.tab.files":    {"en_US": "Files",           "zh_CN": "文件",             "zh_TW": "檔案"},
    "sidebar.tab.settings": {"en_US": "Settings",        "zh_CN": "设置",             "zh_TW": "設定"},
    "sidebar.tab.inspector":{"en_US": "Inspector",       "zh_CN": "检查器",           "zh_TW": "檢查器"},
    "sidebar.tab.ai":       {"en_US": "AI Interpret",    "zh_CN": "AI 释图",          "zh_TW": "AI 釋圖"},
    "sidebar.tab.quickstart":{"en_US": "Quick Start",    "zh_CN": "快速入门",         "zh_TW": "快速入門"},
    "sidebar.tab.manual":   {"en_US": "Manual",           "zh_CN": "手册",           "zh_TW": "手冊"},
    "sidebar.tab.record":   {"en_US": "Record Settings",  "zh_CN": "录音设置",        "zh_TW": "錄音設定"},
    # --- 下拉框选项 ---
    "cmb.waveform":       {"en_US": "Waveform",        "zh_CN": "波形",             "zh_TW": "波形"},
    "cmb.fft":            {"en_US": "FFT Spectrum",    "zh_CN": "FFT 频谱",         "zh_TW": "FFT 頻譜"},
    "cmb.spectrogram":    {"en_US": "Spectrogram",     "zh_CN": "语谱图",           "zh_TW": "語譜圖"},
    "cmb.pitch":          {"en_US": "Pitch",           "zh_CN": "音高",             "zh_TW": "音高"},
    "cmb.formants":       {"en_US": "Formants",        "zh_CN": "共振峰",           "zh_TW": "共振峰"},
    "cmb.timbre":         {"en_US": "Timbre",          "zh_CN": "音色",             "zh_TW": "音色"},
    "cmb.spectrogram3d":  {"en_US": "3D Spectrogram",  "zh_CN": "3D 频谱图",        "zh_TW": "3D 頻譜圖"},
    # --- 左图标栏（CB-011 B-2，Obsidian 风格 ribbon 工具提示）---
    "ribbon.help":        {"en_US": "Help",             "zh_CN": "帮助",             "zh_TW": "說明"},
    "ribbon.settings":    {"en_US": "Settings",         "zh_CN": "设置",             "zh_TW": "設定"},
    # --- 状态栏 / 提示 ---
    "status.ready":       {"en_US": "Ready",           "zh_CN": "就绪",             "zh_TW": "就緒"},
    "status.open_audio":  {"en_US": "Please open an audio file and select an analysis type",
                           "zh_CN": "请打开音频文件并选择分析类型",
                           "zh_TW": "請開啟音訊檔案並選擇分析類型"},
    "msg.no_audio":       {"en_US": "Please open an audio file first",
                           "zh_CN": "请先打开音频文件",
                           "zh_TW": "請先開啟音訊檔案"},
    "msg.hint":           {"en_US": "Hint",            "zh_CN": "提示",             "zh_TW": "提示"},
    "msg.analysis_failed":{"en_US": "Analysis Failed", "zh_CN": "分析失败",         "zh_TW": "分析失敗"},
    "msg.export_failed":  {"en_US": "Export Failed",   "zh_CN": "导出失败",         "zh_TW": "匯出失敗"},
    "msg.export_figure":  {"en_US": "Export Figure",   "zh_CN": "导出图表",         "zh_TW": "匯出圖表"},
    "msg.exported":        {"en_US": "Figure exported:","zh_CN": "图表已导出：",     "zh_TW": "圖表已匯出："},
    "msg.export_relocated":{"en_US": "Export Location Changed",
                           "zh_CN": "导出位置调整",
                           "zh_TW": "匯出位置調整"},
    # --- 状态栏数据段（CB-013 D-2）---
    "status.seg.menu":    {"en_US": "Status Bar Segments", "zh_CN": "状态栏数据段",   "zh_TW": "狀態欄資料段"},
    "status.seg.file":    {"en_US": "File",                "zh_CN": "文件名",         "zh_TW": "檔名"},
    "status.seg.sample_rate":{"en_US": "Sample Rate",      "zh_CN": "采样率",         "zh_TW": "取樣率"},
    "status.seg.play_position":{"en_US": "Play Position",  "zh_CN": "播放位置",       "zh_TW": "播放位置"},
    "status.seg.record_timer":{"en_US": "Record Timer",    "zh_CN": "录音计时",       "zh_TW": "錄音計時"},
    "status.seg.zoom":    {"en_US": "Zoom",                "zh_CN": "缩放",           "zh_TW": "縮放"},
    # --- G-2a：main_window.py Qt 汇点硬编码清零（32 键，三语齐、ko/ja 随批后补）---
    "update.downloading_model": {"en_US": "Downloading {backend} model…",
                                 "zh_CN": "下载 {backend} 模型…",
                                 "zh_TW": "下載 {backend} 模型…"},
    "status.autosave_restored": {"en_US": "Project restored from autosave snapshot",
                                 "zh_CN": "已从自动保存快照恢复项目",
                                 "zh_TW": "已從自動儲存快照復原專案"},
    "status.loading":     {"en_US": "Loading: {name}...",
                           "zh_CN": "正在加载: {name}...",
                           "zh_TW": "正在載入: {name}..."},
    "status.loaded":      {"en_US": "Loaded: {name}",
                           "zh_CN": "已加载: {name}",
                           "zh_TW": "已載入: {name}"},
    "status.play_rate":   {"en_US": "Playback rate: {rate}x",
                           "zh_CN": "播放速率: {rate}x",
                           "zh_TW": "播放速率: {rate}x"},
    "status.computing_fft": {"en_US": "Computing FFT spectrum...",
                             "zh_CN": "计算 FFT 频谱...",
                             "zh_TW": "計算 FFT 頻譜..."},
    "status.fft_info_pos": {"en_US": "FFT spectrum ({n}-point FFT, position: {pos}s)",
                            "zh_CN": "FFT 频谱 ({n} 点 FFT, 位置: {pos}s)",
                            "zh_TW": "FFT 頻譜 ({n} 點 FFT, 位置: {pos}s)"},
    "status.fft_info_window": {"en_US": "FFT spectrum ({n}-point FFT, {window} window)",
                               "zh_CN": "FFT 频谱 ({n} 点 FFT, {window}窗)",
                               "zh_TW": "FFT 頻譜 ({n} 點 FFT, {window} 窗)"},
    "status.fft_info_hint": {"en_US": "FFT spectrum ({n}-point FFT = internal zero-padding FFT size; window length set by the drop-down; drag the red cursor to inspect positions)",
                             "zh_CN": "FFT 频谱 ({n} 点 FFT 为内部补零/零填充后的 FFT 点数，窗长由下拉设置；拖动红色指针查看不同位置)",
                             "zh_TW": "FFT 頻譜 ({n} 點 FFT 為內部補零/零填充後的 FFT 點數，窗長由下拉設定；拖曳紅色指標查看不同位置)"},
    "status.computing_spectrogram": {"en_US": "Computing spectrogram...",
                                     "zh_CN": "计算语谱图...",
                                     "zh_TW": "計算語譜圖..."},
    "status.recomputing_spectrogram": {"en_US": "Recomputing spectrogram...",
                                       "zh_CN": "重新计算语谱图...",
                                       "zh_TW": "重新計算語譜圖..."},
    "status.computing_3d": {"en_US": "Computing 3D spectrogram...",
                            "zh_CN": "计算 3D 频谱图...",
                            "zh_TW": "計算 3D 頻譜圖..."},
    "status.project_created": {"en_US": "Project created: {path}",
                               "zh_CN": "项目已创建: {path}",
                               "zh_TW": "專案已建立: {path}"},
    "status.project_loading": {"en_US": "Loading project: {name}...",
                               "zh_CN": "正在加载项目: {name}...",
                               "zh_TW": "正在載入專案: {name}..."},
    "status.project_loaded": {"en_US": "Project loaded: {name}",
                              "zh_CN": "项目已加载: {name}",
                              "zh_TW": "專案已載入: {name}"},
    "status.project_saved": {"en_US": "Project saved: {path}",
                             "zh_CN": "项目已保存: {path}",
                             "zh_TW": "專案已儲存: {path}"},
    "status.exporting_audio": {"en_US": "Exporting {fmt} audio...",
                               "zh_CN": "导出 {fmt} 音频...",
                               "zh_TW": "匯出 {fmt} 音訊..."},
    "status.audio_exported": {"en_US": "Audio exported: {path}",
                              "zh_CN": "音频已导出: {path}",
                              "zh_TW": "音訊已匯出: {path}"},
    "status.exporting_chart": {"en_US": "Exporting chart...",
                               "zh_CN": "导出图表...",
                               "zh_TW": "匯出圖表..."},
    "status.chart_exported": {"en_US": "Chart exported: {path}",
                              "zh_CN": "图表已导出: {path}",
                              "zh_TW": "圖表已匯出: {path}"},
    "app.window_title_project": {"en_US": "{name} - AcouScope",
                                 "zh_CN": "{name} - AcouScope 音析",
                                 "zh_TW": "{name} - AcouScope 音析"},
    "record.device_none": {"en_US": "(no input device)",
                           "zh_CN": "（无输入设备）",
                           "zh_TW": "（無輸入裝置）"},
    "record.device_unavailable": {"en_US": "(unavailable)",
                                  "zh_CN": "（不可用）",
                                  "zh_TW": "（不可用）"},
    "record.finished_title": {"en_US": "Recording Complete",
                              "zh_CN": "录音完成",
                              "zh_TW": "錄音完成"},
    "record.recorded_seconds": {"en_US": "Recorded {seconds} s.",
                                "zh_CN": "已录制 {seconds} 秒。",
                                "zh_TW": "已錄製 {seconds} 秒。"},
    "record.load_question": {"en_US": "Load it into the waveform for analysis?",
                             "zh_CN": "是否加载到波形中进行分析？",
                             "zh_TW": "是否載入波形中進行分析？"},
    "pitch.backend_label": {"en_US": "Pitch algorithm:",
                            "zh_CN": "音高算法:",
                            "zh_TW": "音高演算法:"},
    "pitch.backend_pyin": {"en_US": "pYIN (streaming)",
                           "zh_CN": "pYIN (流式)",
                           "zh_TW": "pYIN (串流)"},
    "pitch.backend_swiftf0": {"en_US": "SwiftF0 (deep)",
                              "zh_CN": "SwiftF0 (深度)",
                              "zh_TW": "SwiftF0 (深度)"},
    "pitch.backend_rmvpe": {"en_US": "RMVPE (vocal)",
                            "zh_CN": "RMVPE (人声)",
                            "zh_TW": "RMVPE (人聲)"},
    "pitch.model_missing_title": {"en_US": "Model Not Installed",
                                  "zh_CN": "模型未安装",
                                  "zh_TW": "模型未安裝"},
    "pitch.model_missing_text": {"en_US": "The {backend} model has not been downloaded yet. Download it now?\n(Network connection required; download in advance before fieldwork.)",
                                 "zh_CN": "{backend} 模型尚未下载。是否现在下载？\n（需要网络连接，田野调查前请预下载）",
                                 "zh_TW": "{backend} 模型尚未下載。是否現在下載？\n（需要網路連線，田野調查前請預先下載）"},
    # --- 传输条（CB-013 D-1）---
    "transport.speed_readout":{"en_US": "Playback Rate",   "zh_CN": "播放速率",       "zh_TW": "播放速率"},
    # G13：速率读数前缀（与相邻倍速下拉的裸 1.0x 区分，避免两个裸 x 值并排）
    "transport.rate_label": {
        "en_US": "Rate", "zh_CN": "速率", "zh_TW": "速率",
        "ko_KR": "재생 속도", "ja_JP": "再生速度",
    },
    # --- 全局快捷键（CB-013 D-1）---
    "shortcut.record":    {"en_US": "Record",              "zh_CN": "录音",           "zh_TW": "錄音"},
    "shortcut.stop_playback":{"en_US": "Stop Playback",    "zh_CN": "停止播放",       "zh_TW": "停止播放"},
    # T-324 选区快速试听与 A/B 循环（Pβ）
    "shortcut.preview_selection": {"en_US": "Preview Selection", "zh_CN": "试听选区", "zh_TW": "試聽選區"},
    "shortcut.loop_selection": {"en_US": "A/B Loop Selection",   "zh_CN": "A/B 循环选区", "zh_TW": "A/B 循環選區"},
    # T-325 播放中打点标注（Pγ）
    "shortcut.annotate_instant": {"en_US": "Add Time Mark",       "zh_CN": "打时间点",     "zh_TW": "打時間點"},
    "shortcut.annotate_instant_text": {"en_US": "Add Text Mark",  "zh_CN": "打文本点",     "zh_TW": "打文本點"},
    "shortcut.undo_last_marker": {"en_US": "Undo Last Mark",      "zh_CN": "撤销上一打点", "zh_TW": "撤銷上一打點"},
    "annotate.need_audio": {"en_US": "Load audio before placing marks",
                            "zh_CN": "请先加载音频再打点",
                            "zh_TW": "請先載入音訊再打點"},
    # --- 检查器面板（右面板只读读数分组小标题）---
    "inspector.view":     {"en_US": "Current View",      "zh_CN": "当前视图",         "zh_TW": "目前視圖"},
    "inspector.selection":{"en_US": "Selection",         "zh_CN": "选区",             "zh_TW": "選區"},
    "inspector.analysis": {"en_US": "Analysis Scope",    "zh_CN": "分析范围",         "zh_TW": "分析範圍"},
    "inspector.playback": {"en_US": "Playback Position", "zh_CN": "播放位置",         "zh_TW": "播放位置"},
    "inspector.audio":    {"en_US": "Audio",             "zh_CN": "音频",             "zh_TW": "音訊"},
    # CB-016-3：检查器分析范围数值模板（.format 占位，数值格式保留）
    "inspector.analysis_scope": {
        "en_US": "Analysis Pos {pos:.3f}s · Window {win:.3f}s",
        "zh_CN": "分析位置 {pos:.3f}s · 窗口 {win:.3f}s",
        "zh_TW": "分析位置 {pos:.3f}s · 視窗 {win:.3f}s",
    },
    # CB-016-2：红针 Label 文案（i18n）
    "wave.analysis_cursor": {
        "en_US": "Analysis Position", "zh_CN": "分析位置", "zh_TW": "分析位置",
    },
    # --- 付费功能 ---
    "feature.spectrogram": {"en_US": "Spectrogram",      "zh_CN": "语谱图",           "zh_TW": "語譜圖"},
    "feature.pitch":       {"en_US": "Pitch Detection",  "zh_CN": "音高检测",         "zh_TW": "音高偵測"},
    "feature.formants":    {"en_US": "Formant Analysis", "zh_CN": "共振峰分析",       "zh_TW": "共振峰分析"},
    "feature.timbre":      {"en_US": "Timbre Analysis",  "zh_CN": "音色分析",         "zh_TW": "音色分析"},
    "feature.spectrogram3d":{"en_US": "3D Spectrogram", "zh_CN": "3D 频谱图",        "zh_TW": "3D 頻譜圖"},
    "feature.export":      {"en_US": "Chart Export",     "zh_CN": "图表导出",         "zh_TW": "圖表匯出"},
    "feature.ai_interpret":{"en_US": "AI Interpretation","zh_CN": "AI 释图",        "zh_TW": "AI 釋圖"},
    # --- 设置对话框 ---
    "settings.title":     {"en_US": "Settings",         "zh_CN": "设置",             "zh_TW": "設定"},
    "settings.tab.general":{"en_US": "General",         "zh_CN": "通用",             "zh_TW": "一般"},
    # T-1109 IM-31：音频设备标签 tr() 化（原硬编码「音频设备」）
    "settings.tab.audio_device":{"en_US": "Audio Device","zh_CN": "音频设备",         "zh_TW": "音訊裝置"},
    "settings.tab.ai":    {"en_US": "AI",                "zh_CN": "AI",              "zh_TW": "AI"},
    "settings.tab.interface":{"en_US": "Interface",     "zh_CN": "界面",             "zh_TW": "介面"},
    "settings.tab.export":{"en_US": "Export",           "zh_CN": "导出",             "zh_TW": "匯出"},
    # IM-41：快捷键标签 tr() 化（原 settings_dialog 硬编码「快捷键」，英文界面中英混排）
    "settings.tab.shortcuts":{"en_US": "Shortcuts",     "zh_CN": "快捷键",           "zh_TW": "快捷鍵"},
    # MCP（模型上下文协议）设置页 — 9 键 × 5 语齐
    "settings.tab.mcp": {"en_US": "MCP", "zh_CN": "MCP", "zh_TW": "MCP", "ko_KR": "MCP", "ja_JP": "MCP"},
    "settings.mcp.title": {"en_US": "Allowed Root Directories", "zh_CN": "允许访问的根目录", "zh_TW": "允許訪問的根目錄", "ko_KR": "허용된 루트 디렉토리", "ja_JP": "許可されたルートディレクトリ"},
    "settings.mcp.enable": {"en_US": "Enable MCP integration", "zh_CN": "启用 MCP 集成", "zh_TW": "啟用 MCP 整合", "ko_KR": "MCP 통합 활성화", "ja_JP": "MCP 統合を有効化"},
    "settings.mcp.roots_hint": {"en_US": "Separate multiple absolute paths with the system path separator", "zh_CN": "多个绝对路径请用系统路径分隔符号隔开", "zh_TW": "多個絕對路徑請用系統路徑分隔符號隔開", "ko_KR": "여러 절대 경로는 시스템 경로 구분자로 분리하십시오", "ja_JP": "複数の絶対パスはシステムパス区切り文字で区切ってください"},
    "settings.mcp.out_hint": {"en_US": "Output directory for MCP artifacts (leave empty for default)", "zh_CN": "MCP 输出工作目录（留空使用默认）", "zh_TW": "MCP 輸出工作目錄（留空使用預設）", "ko_KR": "MCP 산출물 출력 디렉토리(비우면 기본값)", "ja_JP": "MCP アーティファクト出力ディレクトリ（空はデフォルト）"},
    "settings.mcp.check": {"en_US": "Check Readiness", "zh_CN": "就绪检查", "zh_TW": "就緒檢查", "ko_KR": "준비 상태 확인", "ja_JP": "準備状況を確認"},
    "settings.mcp.copy": {"en_US": "Copy Host Config", "zh_CN": "复制 Host 配置", "zh_TW": "複製 Host 設定", "ko_KR": "호스트 구성 복사", "ja_JP": "ホスト設定をコピー"},
    "settings.mcp.ready": {"en_US": "MCP ready", "zh_CN": "MCP 就绪", "zh_TW": "MCP 就緒", "ko_KR": "MCP 준비 완료", "ja_JP": "MCP 準備完了"},
    "settings.mcp.not_ready": {"en_US": "MCP not ready", "zh_CN": "MCP 未就绪", "zh_TW": "MCP 未就緒", "ko_KR": "MCP 준비 안 됨", "ja_JP": "MCP 準備未完了"},
    "settings.language":  {"en_US": "Language:",        "zh_CN": "语言：",           "zh_TW": "語言："},
    "settings.lang_hint": {"en_US": "Restart required after changing language",
                           "zh_CN": "更改语言后需重启应用生效",
                           "zh_TW": "更改語言後需重啟應用生效"},
    "settings.ai_provider":{"en_US": "Model Source:",   "zh_CN": "模型来源：",       "zh_TW": "模型來源："},
    # --- T-320：模型来源三档（内置 / 本地部署 / 云端服务商） ---
    "settings.ai_source": {"en_US": "Model Source",     "zh_CN": "模型来源",         "zh_TW": "模型來源"},
    "settings.builtin":  {"en_US": "Built-in Model",    "zh_CN": "内置模型",         "zh_TW": "內建模型"},
    "settings.builtin_reco": {"en_US": " (Recommended)", "zh_CN": "（推荐）",         "zh_TW": "（推薦）"},
    "settings.builtin_hint": {"en_US": "Bundled with the app; no setup needed",
                              "zh_CN": "随软件自带，无需任何设置",
                              "zh_TW": "隨軟體自帶，無需任何設定"},
    "settings.self_hosted": {"en_US": "Self-hosted Model", "zh_CN": "本地部署的模型", "zh_TW": "本地部署的模型"},
    "settings.self_hosted_hint": {
        "en_US": "Use a model service you run yourself, e.g. on your own computer or an institution server",
        "zh_CN": "使用你自己运行的模型服务（你自己电脑或机构服务器上部署的 Ollama 等兼容服务）",
        "zh_TW": "使用你自己執行的模型服務（你自己的電腦或機構伺服器上部署的 Ollama 等相容服務）"},
    "settings.cloud":    {"en_US": "Cloud Provider",    "zh_CN": "云端服务商",        "zh_TW": "雲端服務商"},
    "settings.cloud_hint": {"en_US": "Use an online API; an API key is required",
                            "zh_CN": "使用在线 API，需填写密钥",
                            "zh_TW": "使用線上 API，需填寫金鑰"},
    "settings.ai_service_url": {"en_US": "Service Address:", "zh_CN": "服务地址：",   "zh_TW": "服務位址："},
    "settings.ai_vendor": {"en_US": "Vendor:",          "zh_CN": "厂商：",           "zh_TW": "廠商："},
    "settings.ai_url":    {"en_US": "API Address:",     "zh_CN": "API 地址：",       "zh_TW": "API 位址："},
    "settings.ai_model":  {"en_US": "Model Name:",      "zh_CN": "模型名称：",       "zh_TW": "模型名稱："},
    "settings.ai_key":    {"en_US": "API Key:",         "zh_CN": "API 密钥：",       "zh_TW": "API 金鑰："},
    "settings.ai_image":  {"en_US": "Send chart image to model",
                           "zh_CN": "向模型发送图表图像",
                           "zh_TW": "向模型發送圖表影像"},
    "settings.ai_test":   {"en_US": "Test Connection",  "zh_CN": "测试连接",         "zh_TW": "測試連線"},
    # --- T-319：内置档「本地模型版本」检查更新 / 恢复默认（零黑话） ---
    "settings.engine_bundled": {"en_US": "Bundled with the app",
                                "zh_CN": "随软件自带",
                                "zh_TW": "隨軟體自帶"},
    "settings.engine_updated_to": {"en_US": "Updated to version {version}",
                                   "zh_CN": "已更新至版本 {version}",
                                   "zh_TW": "已更新至版本 {version}"},
    "settings.engine_check_updates": {"en_US": "Check for Updates",
                                      "zh_CN": "检查更新",
                                      "zh_TW": "檢查更新"},
    "settings.engine_restore_default": {"en_US": "Restore Default",
                                        "zh_CN": "恢复默认",
                                        "zh_TW": "恢復預設"},
    "settings.engine_cancel": {"en_US": "Cancel Update",
                               "zh_CN": "取消更新",
                               "zh_TW": "取消更新"},
    "settings.engine_checking": {"en_US": "Checking for updates…",
                                 "zh_CN": "正在检查更新…",
                                 "zh_TW": "正在檢查更新…"},
    "settings.engine_downloading": {"en_US": "Downloading update…",
                                    "zh_CN": "正在下载更新…",
                                    "zh_TW": "正在下載更新…"},
    "settings.engine_toast_ok": {"en_US": "Local model updated to version {version}",
                                 "zh_CN": "本地模型已更新至版本 {version}",
                                 "zh_TW": "本地模型已更新至版本 {version}"},
    "settings.engine_toast_latest": {"en_US": "You already have the latest version",
                                     "zh_CN": "当前已是最新版本",
                                     "zh_TW": "目前已是最新版本"},
    "settings.engine_toast_netfail": {
        "en_US": "Cannot reach the update service. Please try again later.",
        "zh_CN": "无法连接更新服务，请稍后重试",
        "zh_TW": "無法連線更新服務，請稍後再試"},
    "settings.engine_toast_failed": {
        "en_US": "Update failed. The current working version is kept.",
        "zh_CN": "更新失败，已保留当前可用的版本",
        "zh_TW": "更新失敗，已保留目前可用的版本"},
    "settings.engine_toast_cancelled": {"en_US": "Update cancelled.",
                                        "zh_CN": "已取消更新",
                                        "zh_TW": "已取消更新"},
    "settings.engine_toast_unsupported": {
        "en_US": "Automatic updates are not available on this platform yet; the bundled version remains available.",
        "zh_CN": "当前平台暂不支持自动更新，随软件自带版本始终可用",
        "zh_TW": "目前平台暫不支援自動更新，隨軟體自帶版本始終可用"},
    "settings.engine_toast_reset": {
        "en_US": "Restored to the version bundled with the app.",
        "zh_CN": "已恢复随软件自带的版本",
        "zh_TW": "已恢復隨軟體自帶的版本"},
    "settings.engine_cancelled": {"en_US": "Update cancelled",
                                  "zh_CN": "已取消更新",
                                  "zh_TW": "已取消更新"},
    # --- UP-2：应用更新检查（只通知；帮助菜单 + 结果提示 + 设置开关 + 首次征询）---
    "action.check_updates": {"en_US": "Check for Updates…",
                             "zh_CN": "检查更新…",
                             "zh_TW": "檢查更新…"},
    "update.status_ok": {"en_US": "Version {version} is available — get it from the download page:",
                         "zh_CN": "发现新版本 {version}，请到下载页获取：",
                         "zh_TW": "發現新版本 {version}，請到下載頁取得："},
    "update.up_to_date": {"en_US": "You already have the latest version.",
                          "zh_CN": "当前已是最新版本。",
                          "zh_TW": "目前已是最新版本。"},
    "update.no_network": {"en_US": "Cannot reach the update service right now.",
                          "zh_CN": "暂时无法连接更新服务。",
                          "zh_TW": "暫時無法連線更新服務。"},
    "update.malformed": {"en_US": "Update information is temporarily unavailable.",
                         "zh_CN": "暂时无法获取更新信息。",
                         "zh_TW": "暫時無法取得更新資訊。"},
    "update.disabled": {"en_US": "Update checks are turned off — you can enable them in Settings → AI.",
                        "zh_CN": "更新检查已关闭，可在「设置 → AI」中开启。",
                        "zh_TW": "更新檢查已關閉，可在「設定 → AI」中開啟。"},
    "settings.update_check_enabled": {"en_US": "Check for updates automatically",
                                      "zh_CN": "自动检查更新",
                                      "zh_TW": "自動檢查更新"},
    "update.ask_title": {"en_US": "Stay up to date?",
                         "zh_CN": "是否启用更新检查？",
                         "zh_TW": "是否啟用更新檢查？"},
    "update.ask_body": {"en_US": "Allow AcouScope to check for new versions automatically? "
                                 "No personal data is sent, and you can change this anytime in Settings.",
                         "zh_CN": "是否允许 AcouScope 自动检查新版本？"
                                  "不会发送任何个人数据，随时可在设置中更改。",
                         "zh_TW": "是否允許 AcouScope 自動檢查新版本？"
                                  "不會傳送任何個人資料，隨時可在設定中變更。"},
    "settings.theme":     {"en_US": "Theme:",           "zh_CN": "主题：",           "zh_TW": "主題："},
    # T-1031 曝光收敛：主题标签中性化（去「日落暖橙/薰衣草紫」等轻佻命名，只留色相描述）
    "settings.theme.group.basic":{"en_US": "Basic",     "zh_CN": "基础配色",         "zh_TW": "基礎配色"},
    "settings.theme.group.more":{"en_US": "More Colors", "zh_CN": "更多配色",         "zh_TW": "更多配色"},
    "settings.theme.default":{"en_US": "Default",       "zh_CN": "默认",             "zh_TW": "預設"},
    "settings.theme.dark":{"en_US": "Dark",            "zh_CN": "深色",             "zh_TW": "深色"},
    "settings.theme.light":{"en_US": "Light",          "zh_CN": "浅色",             "zh_TW": "淺色"},
    "settings.theme.system":{"en_US": "Follow System", "zh_CN": "跟随系统",         "zh_TW": "跟隨系統"},
    "settings.theme.ocean":{"en_US": "Blue",           "zh_CN": "蓝调",             "zh_TW": "藍調"},
    "settings.theme.forest":{"en_US": "Green",         "zh_CN": "绿调",             "zh_TW": "綠調"},
    "settings.theme.sunset":{"en_US": "Amber",         "zh_CN": "橙调",             "zh_TW": "橙調"},
    "settings.theme.lavender":{"en_US": "Violet",      "zh_CN": "紫调",             "zh_TW": "紫調"},
    "settings.theme.graphite":{"en_US": "Gray",        "zh_CN": "灰调",             "zh_TW": "灰調"},
    "settings.theme.sepia":{"en_US": "Brown",          "zh_CN": "棕调",             "zh_TW": "棕調"},
    # --- T-1001 图标风格 ---
    "settings.icon_style":     {"en_US": "Icon Style:",  "zh_CN": "图标风格：",       "zh_TW": "圖示風格："},
    "settings.icon_style.macos":{"en_US": "macOS (rounded)", "zh_CN": "macOS（圆润）", "zh_TW": "macOS（圓潤）"},
    "settings.icon_style.win": {"en_US": "Windows (sharp)", "zh_CN": "Windows（方直）", "zh_TW": "Windows（方直）"},
    "settings.icon_style.mint":{"en_US": "Mint (balanced)", "zh_CN": "Mint（均衡）",  "zh_TW": "Mint（均衡）"},
    "settings.icon_style.generic":{"en_US": "Generic",    "zh_CN": "通用（默认）",     "zh_TW": "通用（預設）"},
    "settings.icon_style.hint": {"en_US": "Icons come from the built-in set and refresh across the window when switched",
                                 "zh_CN": "图标取自内置集合，切换后全窗即时刷新",
                                 "zh_TW": "圖示取自內建集合，切換後全視窗即時更新"},
    "settings.export_format":{"en_US":"Default Format:","zh_CN": "默认导出格式：",   "zh_TW": "預設匯出格式："},
    "settings.export_dpi":{"en_US": "Default DPI:",    "zh_CN": "默认导出 DPI：",    "zh_TW": "預設匯出 DPI："},
    "settings.dpi.150":   {"en_US": "150 dpi (Screen)", "zh_CN": "150 dpi（屏幕/预览）","zh_TW": "150 dpi（螢幕/預覽）"},
    "settings.dpi.300":   {"en_US": "300 dpi (Recommended)","zh_CN": "300 dpi（推荐，印刷级）","zh_TW": "300 dpi（推薦，印刷級）"},
    "settings.dpi.600":   {"en_US": "600 dpi (High)",  "zh_CN": "600 dpi（高清）",   "zh_TW": "600 dpi（高畫質）"},
    "settings.dpi.1200":  {"en_US": "1200 dpi (Ultra)","zh_CN": "1200 dpi（超高）", "zh_TW": "1200 dpi（超高）"},
    # --- 关于对话框 ---
    "about.title":        {"en_US": "About AcouScope", "zh_CN": "关于 AcouScope",  "zh_TW": "關於 AcouScope"},
    "about.desc":         {"en_US": "Cross-platform acoustic analysis software for music and digital humanities research",
                           "zh_CN": "面向音乐与数字人文领域研究的跨平台声学分析软件",
                           "zh_TW": "面向音樂與數位人文領域研究的跨平台聲學分析軟體"},
    "about.tech":         {"en_US": "Built with Python + PyQt6 + pyqtgraph; core algorithms in pure NumPy",
                           "zh_CN": "基于 Python + PyQt6 + pyqtgraph 开发，核心算法纯 numpy 实现",
                           "zh_TW": "基於 Python + PyQt6 + pyqtgraph 開發，核心演算法純 numpy 實現"},
    "about.license":      {"en_US": "Open source software released under the GPL-3.0-only license.",
                           "zh_CN": "开源软件，基于 GPL-3.0-only 许可协议发布。",
                           "zh_TW": "開源軟體，基於 GPL-3.0-only 許可協議發佈。"},
    "about.version":      {"en_US": "Version",         "zh_CN": "版本",             "zh_TW": "版本"},
    "about.website":      {"en_US": "Website",         "zh_CN": "网站",             "zh_TW": "網站"},
    "about.author_label": {"en_US": "Author",          "zh_CN": "作者",             "zh_TW": "作者"},
    "about.author_name":  {"en_US": "Fengkai Shi (sfklc@hotmail.com)",
                           "zh_CN": "石丰恺（sfklc@hotmail.com）",
                           "zh_TW": "石豐愷（sfklc@hotmail.com）"},
    "about.copyright":    {"en_US": "Copyright © 2026 Jinyun SonicAI · Institute of Art Anthropology, Southwest University · Institute of Chinese Music & Mental Health, Southwest University",
                           "zh_CN": "Copyright © 2026 缙云声智（Jinyun SonicAI）· 西南大学艺术人类学研究所 · 西南大学中国音乐心理健康研究所",
                           "zh_TW": "Copyright © 2026 縉雲聲智（Jinyun SonicAI）· 西南大學藝術人類學研究所 · 西南大學中國音樂心理健康研究所"},
    "about.rights":       {"en_US": "All rights reserved.",
                           "zh_CN": "保留所有权利。",
                           "zh_TW": "版權所有。"},
    "about.ack_title":    {"en_US": "Acknowledgements", "zh_CN": "致谢",            "zh_TW": "致謝"},
    "about.ack_body":     {"en_US": "Built on outstanding open-source projects: NumPy, Qt / PyQt6, pyqtgraph, matplotlib, python-soundfile (libsndfile), certifi and pytest.",
                           "zh_CN": "本软件的构建得益于以下优秀开源项目：NumPy、Qt / PyQt6、pyqtgraph、matplotlib、python-soundfile（libsndfile）、certifi 与 pytest。",
                           "zh_TW": "本軟體的建構得益於以下優秀開源專案：NumPy、Qt / PyQt6、pyqtgraph、matplotlib、python-soundfile（libsndfile）、certifi 與 pytest。"},
    "about.ded_title":    {"en_US": "With Special Acknowledgement and Dedication to",
                           "zh_CN": "特别鸣谢并献予",
                           "zh_TW": "特別鳴謝並獻予"},
    "about.ded_name":     {"en_US": "Prof. Han Baoqiang",
                           "zh_CN": "韩宝强 教授",
                           "zh_TW": "韓寶強 教授"},
    "about.ded_desc":     {"en_US": "Leading scholar in music acoustics; Expert receiving the Special Allowance of the State Council of the People's Republic of China",
                           "zh_CN": "音乐声学领军学者；中华人民共和国国务院特殊津贴专家",
                           "zh_TW": "音樂聲學領軍學者；中華人民共和國國務院特殊津貼專家"},
    "app.name_cn":        {"en_US": "AcouScope",       "zh_CN": "音析",             "zh_TW": "音析"},
    # --- 实时特征面板 ---
    "rt.title":           {"en_US": "Real-time Features", "zh_CN": "实时特征",      "zh_TW": "即時特徵"},
    "rt.static":          {"en_US": "Static",          "zh_CN": "静态",             "zh_TW": "靜態"},
    "rt.live_rec":        {"en_US": "● LIVE · Recording", "zh_CN": "● LIVE · 录入中", "zh_TW": "● LIVE · 錄入中"},
    "rt.onset_lmh":       {"en_US": "Onset L{low} M{mid} H{high}", "zh_CN": "起音 L{low} M{mid} H{high}", "zh_TW": "起音 L{low} M{mid} H{high}"},
    "rt.live_play":       {"en_US": "● LIVE",           "zh_CN": "● LIVE",           "zh_TW": "● LIVE"},
    "rt.menu_peaks":      {"en_US": "Toggle Peak Hold", "zh_CN": "峰值保持 开/关",    "zh_TW": "峰值保持 開/關"},
    # --- 音高模块右键菜单 ---
    "pitch.menu_refline": {"en_US": "Toggle A4 Reference", "zh_CN": "A4 参考线 开/关", "zh_TW": "A4 參考線 開/關"},
    # --- 主工具栏 LOGO ---
    "toolbar.logo_tip":   {"en_US": "Jinyun Acoustic Studio", "zh_CN": "金韵声学工作室", "zh_TW": "金韻聲學工作室"},
    # --- 3D 频谱图右侧参数面板 ---
    "s3d.panel_view":     {"en_US": "View",            "zh_CN": "视角参数",          "zh_TW": "視角參數"},
    "s3d.elev":           {"en_US": "Elevation (°)",   "zh_CN": "仰角 (°)",          "zh_TW": "仰角 (°)"},
    "s3d.azim":           {"en_US": "Azimuth (°)",     "zh_CN": "方位角 (°)",        "zh_TW": "方位角 (°)"},
    "s3d.reset_view":     {"en_US": "Reset View",      "zh_CN": "复位视角",          "zh_TW": "復位視角"},
    "s3d.panel_margin":   {"en_US": "Margins",         "zh_CN": "边距参数",          "zh_TW": "邊距參數"},
    "s3d.m_top":          {"en_US": "Top",             "zh_CN": "上边界",            "zh_TW": "上邊界"},
    "s3d.m_bottom":       {"en_US": "Bottom",          "zh_CN": "下边界",            "zh_TW": "下邊界"},
    "s3d.m_left":         {"en_US": "Left",            "zh_CN": "左边界",            "zh_TW": "左邊界"},
    "s3d.m_right":        {"en_US": "Right",           "zh_CN": "右边界",            "zh_TW": "右邊界"},
    "s3d.reset_margin":   {"en_US": "Reset Margins",   "zh_CN": "复位边距",          "zh_TW": "復位邊距"},
    "s3d.save":           {"en_US": "Save Image…",     "zh_CN": "保存图片…",         "zh_TW": "儲存圖片…"},
    "rt.plot_bands":      {"en_US": "Band Energy · Rolling", "zh_CN": "频段能量 · 滚动", "zh_TW": "頻段能量 · 捲動"},
    "rt.plot_spectrum":   {"en_US": "Real-time Spectrum · Log", "zh_CN": "实时频谱 · 对数", "zh_TW": "即時頻譜 · 對數"},
    "rt.plot_bars":       {"en_US": "Band Energy Bars", "zh_CN": "频段能量条",      "zh_TW": "頻段能量條"},
    "rt.axis_time":       {"en_US": "Time",            "zh_CN": "时间",             "zh_TW": "時間"},
    "rt.axis_freq":       {"en_US": "Frequency",       "zh_CN": "频率",             "zh_TW": "頻率"},
    # H4：左下「场景可视化」块的标题与 X/Y 轴标（en/zh_CN/zh_TW 三语齐；ko/ja 随批补齐，
    # 保持 parity 守卫的 ko_ja 缺口单调不增）
    "rt.plot_scene":      {"en_US": "Scene Visualization", "zh_CN": "场景可视化",
                           "zh_TW": "場景視覺化", "ko_KR": "장면 시각화", "ja_JP": "シーン可視化"},
    "rt.axis_scene_x":    {"en_US": "Horizontal",      "zh_CN": "横向",
                           "zh_TW": "橫向", "ko_KR": "가로", "ja_JP": "横方向"},
    "rt.axis_scene_y":    {"en_US": "Vertical",        "zh_CN": "纵向",
                           "zh_TW": "縱向", "ko_KR": "세로", "ja_JP": "縦方向"},
    "rt.band_low":        {"en_US": "Low",             "zh_CN": "低",               "zh_TW": "低"},
    "rt.band_mid":        {"en_US": "Mid",             "zh_CN": "中",               "zh_TW": "中"},
    "rt.band_high":       {"en_US": "High",            "zh_CN": "高",               "zh_TW": "高"},
    "rt.leg_low":         {"en_US": "Low 40–250 Hz",   "zh_CN": "低频 40–250 Hz",   "zh_TW": "低頻 40–250 Hz"},
    "rt.leg_mid":         {"en_US": "Mid 250–2k Hz",   "zh_CN": "中频 250–2k Hz",   "zh_TW": "中頻 250–2k Hz"},
    "rt.leg_high":        {"en_US": "High 2k–16k Hz",  "zh_CN": "高频 2k–16k Hz",   "zh_TW": "高頻 2k–16k Hz"},
    "rt.btn_csv":         {"en_US": "CSV",             "zh_CN": "CSV",              "zh_TW": "CSV"},
    "rt.tip_csv":         {"en_US": "Export real-time features as CSV", "zh_CN": "导出实时特征 CSV", "zh_TW": "匯出即時特徵 CSV"},
    "rt.dlg_export":      {"en_US": "Export Real-time Features CSV", "zh_CN": "导出实时特征 CSV", "zh_TW": "匯出即時特徵 CSV"},
    "rt.file_filter":     {"en_US": "CSV Files (*.csv)", "zh_CN": "CSV 文件 (*.csv)", "zh_TW": "CSV 檔案 (*.csv)"},
    "rt.band_legend":     {"en_US": "{label}",         "zh_CN": "{label}",          "zh_TW": "{label}"},
    # --- 图表右键菜单（自定义，替代 pyqtgraph 内置英文菜单） ---
    "menu.view_all":      {"en_US": "Fit to View",     "zh_CN": "适应窗口",         "zh_TW": "適應視窗"},
    "menu.reset_x":       {"en_US": "Reset X Axis",    "zh_CN": "复位 X 轴",        "zh_TW": "復位 X 軸"},
    "menu.reset_view":    {"en_US": "Reset View",      "zh_CN": "复位视图",         "zh_TW": "復位視圖"},
    # --- 对话框按钮 ---
    "btn.ok":             {"en_US": "OK",              "zh_CN": "确定",             "zh_TW": "確定"},
    "btn.cancel":         {"en_US": "Cancel",          "zh_CN": "取消",             "zh_TW": "取消"},
    "btn.close":          {"en_US": "Close",           "zh_CN": "关闭",             "zh_TW": "關閉"},
    "btn.save":           {"en_US": "Save",            "zh_CN": "保存",             "zh_TW": "儲存"},
    "btn.apply":         {"en_US": "Apply",           "zh_CN": "应用",             "zh_TW": "套用"},
    # --- 导出格式 ---
    "fmt.svg":           {"en_US": "SVG Vector (*.svg)", "zh_CN": "SVG 矢量图 (*.svg)", "zh_TW": "SVG 向量圖 (*.svg)"},
    "fmt.png":           {"en_US": "PNG Raster (*.png)", "zh_CN": "PNG 位图 (*.png)",   "zh_TW": "PNG 點陣圖 (*.png)"},
    "fmt.pdf":           {"en_US": "PDF Vector (*.pdf)", "zh_CN": "PDF 矢量图 (*.pdf)", "zh_TW": "PDF 向量圖 (*.pdf)"},
    "fmt.eps":           {"en_US": "EPS Vector (*.eps)", "zh_CN": "EPS 矢量图 (*.eps)", "zh_TW": "EPS 向量圖 (*.eps)"},
    # --- Tips 条（主工具栏提示区） ---
    "menu.export":      {"en_US": "Export",           "zh_CN": "导出",             "zh_TW": "匯出"},
    "toolbar.tips":      {"en_US": "Tips",             "zh_CN": "提示",             "zh_TW": "提示"},
    "tip.prefix":        {"en_US": "Tip",              "zh_CN": "提示",             "zh_TW": "提示"},
    # G14：提示条右侧 × 关闭钮（只隐藏本条，不落盘）
    "tip.close":         {
        "en_US": "Dismiss this tip", "zh_CN": "关闭本条提示", "zh_TW": "關閉本條提示",
        "ko_KR": "이 팁 닫기", "ja_JP": "このヒントを閉じる",
    },
    "tip.1":             {"en_US": "Drag & drop an audio file onto the window to open it.",
                           "zh_CN": "把音频文件拖放到窗口即可打开。",
                           "zh_TW": "將音訊檔案拖放到視窗即可開啟。"},
    "tip.2":             {"en_US": "New project: Cmd/Ctrl+N.",
                           "zh_CN": "新建项目：Cmd/Ctrl+N。",
                           "zh_TW": "新建專案：Cmd/Ctrl+N。"},
    "tip.3":             {"en_US": "Open project: Cmd/Ctrl+Shift+O.",
                           "zh_CN": "打开项目：Cmd/Ctrl+Shift+O。",
                           "zh_TW": "開啟專案：Cmd/Ctrl+Shift+O。"},
    "tip.4":             {"en_US": "AcouScope auto-saves project snapshots so an unexpected quit can be recovered.",
                           "zh_CN": "AcouScope 会定期自动保存工程快照，异常退出后可恢复。",
                           "zh_TW": "AcouScope 會定期自動儲存工程快照，異常結束後可回復。"},
    "tip.5":             {"en_US": "Export the current view: Cmd/Ctrl+E.",
                           "zh_CN": "导出当前视图：Cmd/Ctrl+E。",
                           "zh_TW": "匯出目前檢視：Cmd/Ctrl+E。"},
    "tip.6":             {"en_US": "Click on the empty waveform to move the playhead.",
                           "zh_CN": "在波形空白处单击即可移动播放头。",
                           "zh_TW": "在波形空白處單擊即可移動播放頭。"},
    "tip.7":             {"en_US": "Drag across the waveform to create a selection region.",
                           "zh_CN": "在波形上按住拖动可创建选区。",
                           "zh_TW": "在波形上按住拖動可建立選區。"},
    "tip.8":             {"en_US": "Double-click the waveform to select the whole clip.",
                           "zh_CN": "双击波形可全选整段音频。",
                           "zh_TW": "雙擊波形可全選整段音訊。"},
    "tip.9":             {"en_US": "Hold Shift to drag the analysis position line independently of the region.",
                           "zh_CN": "按住 Shift 可独立拖动分析位置线（默认与选区咬合）。",
                           "zh_TW": "按住 Shift 可獨立拖動分析位置線（預設與選區咬合）。"},
    "tip.10":            {"en_US": "Edit keys: Cmd/Ctrl+X/C/V cut·copy·paste, Delete, and standard Undo/Redo.",
                           "zh_CN": "编辑键：Cmd/Ctrl+X/C/V 剪切·复制·粘贴、Delete，及标准撤销/重做。",
                           "zh_TW": "編輯鍵：Cmd/Ctrl+X/C/V 剪下·複製·貼上、Delete，及標準復原/重做。"},
    "tip.11":            {"en_US": "F2–F7 switch analysis views: FFT·spectrogram·pitch·formants·timbre·3D.",
                           "zh_CN": "F2–F7 切换分析视图：FFT·语谱图·音高·共振峰·音色·3D。",
                           "zh_TW": "F2–F7 切換分析檢視：FFT·語譜圖·音高·共振峰·音色·3D。"},
    "tip.12":            {"en_US": "Use the bottom tab bar to move among the seven views.",
                           "zh_CN": "用底部标签卡在七个视图间切换。",
                           "zh_TW": "用底部標籤卡在七個檢視間切換。"},
    "tip.13":            {"en_US": "In the 3D spectrogram, drag to orbit the view (elevation / azimuth).",
                           "zh_CN": "3D 频谱图中可拖动旋转视角（俯仰/方位）。",
                           "zh_TW": "3D 頻譜圖中可拖動旋轉視角（俯仰/方位）。"},
    "tip.14":            {"en_US": "The frequency axis unit is switchable: Hz · cents · MIDI · piano.",
                           "zh_CN": "频率轴单位可切换：Hz·音分·MIDI·钢琴。",
                           "zh_TW": "頻率軸單位可切換：Hz·音分·MIDI·鋼琴。"},
    "tip.15":            {"en_US": '"Analyze region" runs analysis only on the current selection.',
                           "zh_CN": "「分析区域」只对当前选区做分析。",
                           "zh_TW": "「分析區域」只對目前選區做分析。"},
    "tip.16":            {"en_US": "Annotation mode lets you drop labeled markers on the timeline.",
                           "zh_CN": "标注模式可在时间轴上放置带标签的标记。",
                           "zh_TW": "標註模式可在時間軸上放置帶標籤的標記。"},
    "tip.17":            {"en_US": "The pitch view offers pYIN and neural backends (SwiftF0 / RMVPE).",
                           "zh_CN": "音高视图提供 pYIN 与神经后端（SwiftF0 / RMVPE）。",
                           "zh_TW": "音高檢視提供 pYIN 與神經後端（SwiftF0 / RMVPE）。"},
    "tip.18":            {"en_US": "Overlay a tuning ruler to compare pitches against a custom scale.",
                           "zh_CN": "叠加音律标尺，对照自定义音律查看音高偏差。",
                           "zh_TW": "疊加音律標尺，對照自訂音律檢視音高偏差。"},
    "tip.19":            {"en_US": "Add the current audio as a track to start a multitrack session.",
                           "zh_CN": "将当前音频加入轨道，即可开始多轨会话。",
                           "zh_TW": "將目前音訊加入軌道，即可開始多軌工作。"},
    "tip.20":            {"en_US": "Each track has solo, mute and volume controls in its header.",
                           "zh_CN": "每条轨的轨头都有独奏、静音与音量控制。",
                           "zh_TW": "每條軌的軌頭都有獨奏、靜音與音量控制。"},
    "tip.21":            {"en_US": "Multitrack compare renders multiple charts (grid / heatmap / single).",
                           "zh_CN": "多轨对比可出多图（网格 / 热图 / 单图）。",
                           "zh_TW": "多軌對比可出多圖（網格 / 熱圖 / 單圖）。"},
    "tip.22":            {"en_US": "Align tracks by offsetting them against a reference track.",
                           "zh_CN": "以参考轨为基准对齐各轨（无损偏移元数据）。",
                           "zh_TW": "以參考軌為基準對齊各軌（無損偏移中繼資料）。"},
    "tip.23":            {"en_US": "Analyze tracks one by one to compare per-track results.",
                           "zh_CN": "逐轨分析以对比各轨结果。",
                           "zh_TW": "逐軌分析以對比各軌結果。"},
    "tip.24":            {"en_US": "The Chart Designer restyles the current view for publication.",
                           "zh_CN": "图表设计器可为当前视图套用出版级样式。",
                           "zh_TW": "圖表設計器可為目前檢視套用出版級樣式。"},
    "tip.25":            {"en_US": "Apply a journal template to match a target publication in one click.",
                           "zh_CN": "一键套用期刊模板，匹配目标出版风格。",
                           "zh_TW": "一鍵套用期刊範本，匹配目標出版風格。"},
    "tip.26":            {"en_US": "Palettes: default · grayscale · colorblind · viridis.",
                           "zh_CN": "配色板：默认·灰度·色盲友好·viridis。",
                           "zh_TW": "配色板：預設·灰度·色盲友善·viridis。"},
    "tip.27":            {"en_US": "Export figures as SVG · PNG · PDF at 72–1200 DPI.",
                           "zh_CN": "图可导出为 SVG·PNG·PDF，DPI 72–1200。",
                           "zh_TW": "圖可匯出為 SVG·PNG·PDF，DPI 72–1200。"},
    "tip.28":            {"en_US": "Set Latin and CJK chart fonts separately.",
                           "zh_CN": "图表的拉丁与中日韩字体可分别设置。",
                           "zh_TW": "圖表的拉丁與中日韓字型可分別設定。"},
    "tip.29":            {"en_US": "Save/load chart styles as JSON presets.",
                           "zh_CN": "图表样式可存/载为 JSON 预设。",
                           "zh_TW": "圖表樣式可存/載為 JSON 預設。"},
    "tip.30":            {"en_US": "Open AI Interpretation in the right panel: Cmd/Ctrl+I.",
                           "zh_CN": "在右栏打开 AI 释图：Cmd/Ctrl+I。",
                           "zh_TW": "在右欄開啟 AI 釋圖：Cmd/Ctrl+I。"},
    "tip.31":            {"en_US": "AI Interpretation preloads the current view's screenshot and numeric context, and follows view switches.",
                           "zh_CN": "AI 释图会预载当前视图截图与数值上下文，并随视图切换更新。",
                           "zh_TW": "AI 釋圖會預載目前檢視截圖與數值上下文，並隨檢視切換更新。"},
    "tip.32":            {"en_US": "The AI model can run from a local deployment (offline).",
                           "zh_CN": "AI 模型可用本地部署（离线）运行。",
                           "zh_TW": "AI 模型可用本地部署（離線）執行。"},
    "tip.33":            {"en_US": "Record from the toolbar record action.",
                           "zh_CN": "用工具栏录音动作开始录音。",
                           "zh_TW": "用工具欄錄音動作開始錄音。"},
    "tip.34":            {"en_US": "Choose device and input settings in the Recording Setup page (left panel).",
                           "zh_CN": "在录音设置页（左栏）选设备与输入参数。",
                           "zh_TW": "在錄音設定頁（左欄）選裝置與輸入參數。"},
    "tip.35":            {"en_US": "Real-time features stream live analysis.",
                           "zh_CN": "实时特征面板做即时分析。",
                           "zh_TW": "即時特徵面板做即時分析。"},
    "tip.36":            {"en_US": "F8 opens Room Mode analysis.",
                           "zh_CN": "F8 打开房间模态分析。",
                           "zh_TW": "F8 開啟房間模態分析。"},
    "tip.37":            {"en_US": "The formants view traces vowel formant trajectories.",
                           "zh_CN": "共振峰视图追踪元音共振峰轨迹。",
                           "zh_TW": "共振峰檢視追蹤母音共振峰軌跡。"},
    "tip.38":            {"en_US": "The timbre (MFCC) view shows MFCC heatmaps and features.",
                           "zh_CN": "音色（MFCC）视图显示 MFCC 热图与特征。",
                           "zh_TW": "音色（MFCC）檢視顯示 MFCC 熱圖與特徵。"},
    "tip.39":            {"en_US": "Restore the default window layout from the View menu.",
                           "zh_CN": "在视图菜单恢复默认窗口布局。",
                           "zh_TW": "在檢視選單回復預設視窗佈局。"},
    "tip.40":            {"en_US": "Switch light / dark theme in Settings.",
                           "zh_CN": "在设置里切换明亮 / 暗色主题。",
                           "zh_TW": "在設定裡切換明亮 / 暗色主題。"},
    "tip.41":            {"en_US": "Icon style is switchable: macOS · Windows · Mint · generic.",
                           "zh_CN": "图标风格可切换：macOS·Windows·Mint·通用。",
                           "zh_TW": "圖示風格可切換：macOS·Windows·Mint·通用。"},
    "tip.42":            {"en_US": "Collapse a side panel via its header or the ◁ ‖ ▷ handle on the divider.",
                           "zh_CN": "用面板头或分界处的 ◁ ‖ ▷ 手柄折叠侧栏。",
                           "zh_TW": "用面板頭或分界處的 ◁ ‖ ▷ 手柄摺疊側欄。"},
    "tip.43":            {"en_US": "The left panel has four pages: Files · Quick Start · Manual · Recording Setup.",
                           "zh_CN": "左栏四页：文件·快速入门·用户手册·录音设置。",
                           "zh_TW": "左欄四頁：檔案·快速入門·使用者手冊·錄音設定。"},
    "tip.44":            {"en_US": "Quick Start and User Manual are built-in help pages.",
                           "zh_CN": "内置快速入门与用户手册页。",
                           "zh_TW": "內建快速入門與使用者手冊頁。"},
    "tip.45":            {"en_US": "A Shortcuts overview lists all key bindings.",
                           "zh_CN": "快捷键总览列出全部键位。",
                           "zh_TW": "捷徑總覽列出全部鍵位。"},
    "tip.46":            {"en_US": "Batch mode analyzes multiple files at once.",
                           "zh_CN": "批处理可一次分析多个文件。",
                           "zh_TW": "批次處理可一次分析多個檔案。"},
    "tip.47":            {"en_US": "Export a full analysis report (not just a single figure).",
                           "zh_CN": "可导出完整分析报告（不止单张图）。",
                           "zh_TW": "可匯出完整分析報告（不止單張圖）。"},
    "tip.48":            {"en_US": "Drag/scroll to zoom the spectrogram in time and frequency.",
                           "zh_CN": "语谱图可拖动/滚轮按时间与频率缩放。",
                           "zh_TW": "語譜圖可拖動/滾輪依時間與頻率縮放。"},
    "tip.49":            {"en_US": "The FFT view lets you change the window function.",
                           "zh_CN": "FFT 视图可切换窗函数。",
                           "zh_TW": "FFT 檢視可切換窗函式。"},
    "tip.50":            {"en_US": "The status bar shows file name, sample rate, playback position and duration.",
                           "zh_CN": "状态栏显示文件名、采样率、播放位置与时长。",
                           "zh_TW": "狀態列顯示檔名、取樣率、播放位置與時長。"},
    "tip.51":            {"en_US": "Exported figures always use a white background, publication-ready.",
                           "zh_CN": "导出的图恒为白底，适合论文/出版。",
                           "zh_TW": "匯出的圖恆為白底，適合論文/出版。"},
    "tip.52":            {"en_US": "Analysis results are cached so re-running the same parameters is instant.",
                           "zh_CN": "分析结果有缓存，相同参数再跑即时返回。",
                           "zh_TW": "分析結果有快取，相同參數再跑即時返回。"},
    "tip.53":            {"en_US": "Scroll or drag to zoom the waveform.",
                           "zh_CN": "波形可滚动/拖拽缩放。",
                           "zh_TW": "波形可滾動/拖拽縮放。"},
    "tip.54":            {"en_US": "Loop playback covers the current selection region.",
                           "zh_CN": "循环播放覆盖当前选区。",
                           "zh_TW": "迴圈播放覆蓋目前選區。"},
    "tip.55":            {"en_US": "Multiple audio formats are supported for import.",
                           "zh_CN": "支持导入多种音频格式。",
                           "zh_TW": "支援匯入多種音訊格式。"},
    "tip.56":            {"en_US": "Annotations can be exported alongside your analysis.",
                           "zh_CN": "标注可随分析结果一并导出。",
                           "zh_TW": "標註可隨分析結果一併匯出。"},
    "tip.57":            {"en_US": "The undo stack covers your edit operations.",
                           "zh_CN": "撤销栈覆盖你的编辑操作。",
                           "zh_TW": "復原堆疊覆蓋你的編輯操作。"},
    "tip.58":            {"en_US": "Visit the official site and About from the Help menu.",
                           "zh_CN": "帮助菜单可访问官网与关于。",
                           "zh_TW": "說明選單可造訪官網與關於。"},
    "tip.59":            {"en_US": "Shortcuts auto-map Cmd on macOS and Ctrl on Windows/Linux.",
                           "zh_CN": "快捷键在 macOS 用 Cmd、Windows/Linux 用 Ctrl，自动适配。",
                           "zh_TW": "捷徑在 macOS 用 Cmd、Windows/Linux 用 Ctrl，自動適配。"},
    "tip.60":            {"en_US": "Switch pitch algorithms to compare a fast and a high-accuracy result.",
                           "zh_CN": "切换音高算法，对比快速与高精度结果。",
                           "zh_TW": "切換音高演算法，對比快速與高精度結果。"},
    "tip.shift_drag":    {"en_US": "Hold Shift to drag the analysis cursor",
                           "zh_CN": "按住 Shift 才能拖动分析位置线",
                           "zh_TW": "按住 Shift 才能拖動分析位置線"},
    "tip.cursor_unlocked":{"en_US": "Analysis cursor unlocked from region (double-click to re-lock)",
                           "zh_CN": "分析位置已与区域解除咬合（双击位置线可恢复）",
                           "zh_TW": "分析位置已與區域解除咬合（雙擊位置線可恢復）"},
    "tip.cursor_locked": {"en_US": "Analysis cursor re-locked to region center",
                           "zh_CN": "分析位置已恢复与区域咬合",
                           "zh_TW": "分析位置已恢復與區域咬合"},
    "tip.selection":     {"en_US": "Selection created: drag its edges to adjust; right-click for edit actions",
                           "zh_CN": "已创建选区：拖动边缘可微调，右键菜单可编辑",
                           "zh_TW": "已建立選區：拖動邊緣可微調，右鍵選單可編輯"},
    "tip.dbl_select_all": {"en_US": "Selected entire waveform (double-click)",
                           "zh_CN": "已全选整个波形（双击）",
                           "zh_TW": "已全選整個波形（雙擊）"},
    "tip.playhead_set":  {"en_US": "Playhead positioned",
                           "zh_CN": "已定位播放头",
                           "zh_TW": "已定位播放頭"},
    # --- 编辑菜单 / 波形编辑工具条 ---
    "menu.edit":         {"en_US": "&Edit",            "zh_CN": "编辑(&E)",         "zh_TW": "編輯(&E)"},
    "edit.undo":         {"en_US": "Undo",             "zh_CN": "撤销",             "zh_TW": "復原"},
    "edit.redo":         {"en_US": "Redo",             "zh_CN": "重做",             "zh_TW": "重做"},
    "edit.cut":          {"en_US": "Cut",              "zh_CN": "剪切",             "zh_TW": "剪下"},
    "edit.copy":         {"en_US": "Copy",             "zh_CN": "复制",             "zh_TW": "複製"},
    "edit.paste":        {"en_US": "Paste",            "zh_CN": "粘贴",             "zh_TW": "貼上"},
    "edit.delete":       {"en_US": "Delete",           "zh_CN": "删除",             "zh_TW": "刪除"},
    "edit.silence":      {"en_US": "Silence",          "zh_CN": "静音",             "zh_TW": "靜音"},
    "edit.trim":         {"en_US": "Trim (keep selection)", "zh_CN": "裁剪（仅保留选区）", "zh_TW": "裁剪（僅保留選區）"},
    "edit.select_all":   {"en_US": "Select All",       "zh_CN": "全选",             "zh_TW": "全選"},
    "edit.select_none":  {"en_US": "Clear Selection",  "zh_CN": "取消选区",         "zh_TW": "取消選區"},
    "edit.zoom_sel":     {"en_US": "Zoom to Selection","zh_CN": "缩放到选区",       "zh_TW": "縮放到選區"},
    "edit.zoom_in":      {"en_US": "Zoom In",          "zh_CN": "放大",             "zh_TW": "放大"},
    "edit.zoom_out":     {"en_US": "Zoom Out",         "zh_CN": "缩小",             "zh_TW": "縮小"},
    "edit.zoom_fit":     {"en_US": "Fit to Window",    "zh_CN": "适应窗口",         "zh_TW": "適應視窗"},
    "edit.need_selection":{"en_US": "This action needs a selection",
                           "zh_CN": "该操作需要先创建选区",
                           "zh_TW": "該操作需要先建立選區"},
    "edit.need_audio":   {"en_US": "No audio loaded",  "zh_CN": "未加载音频",       "zh_TW": "未載入音訊"},
    "edit.clipboard_empty":{"en_US": "Clipboard is empty",
                           "zh_CN": "剪贴板为空",       "zh_TW": "剪貼簿為空"},
    "edit.sel_label":    {"en_US": "Selection",        "zh_CN": "选区",             "zh_TW": "選區"},
    "edit.no_selection": {"en_US": "No selection",     "zh_CN": "无选区",           "zh_TW": "無選區"},
    # --- 去除开头静默 ---
    "wave.trim_silence_btn":  {"en_US": "Trim Silence", "zh_CN": "去静默",           "zh_TW": "去靜音"},
    "wave.trim_silence_tip":  {"en_US": "Detect and remove leading silence",
                               "zh_CN": "检测并去除开头静默",
                               "zh_TW": "偵測並去除開頭靜音"},
    "trim.title":        {"en_US": "Remove Leading Silence",
                          "zh_CN": "去除开头静默",
                          "zh_TW": "去除開頭靜音"},
    "trim.detected":     {"en_US": "Detected {sec} seconds of leading silence ({pct}% of the file).\nHow would you like to proceed?",
                          "zh_CN": "检测到开头静默 {sec} 秒（占全长的 {pct}%）。\n请选择处理方式：",
                          "zh_TW": "偵測到開頭靜音 {sec} 秒（佔全長的 {pct}%）。\n請選擇處理方式："},
    "trim.save_as":      {"en_US": "Save As New File && Import",
                          "zh_CN": "另存为新文件并导入",
                          "zh_TW": "另存為新檔案並匯入"},
    "trim.modify_src":   {"en_US": "Modify Source File (Dangerous)",
                          "zh_CN": "修改源文件（危险）",
                          "zh_TW": "修改原始檔案（危險）"},
    "trim.cancel":       {"en_US": "Cancel",           "zh_CN": "取消",             "zh_TW": "取消"},
    "trim.warn_title":   {"en_US": "Warning: Source File Will Be Overwritten",
                          "zh_CN": "警示：源文件将被覆盖",
                          "zh_TW": "警示：原始檔案將被覆寫"},
    "trim.warn_text":    {"en_US": "You are about to OVERWRITE the original audio file:\n{path}\n\nThis cannot be undone. A backup copy will be created next to it,\nbut please make sure you have your own backup.\n\nContinue?",
                          "zh_CN": "即将直接覆盖原始音频文件：\n{path}\n\n此操作不可撤销。系统会自动在旁边创建一份备份，\n但仍请确认您已自行妥善保存原文件。\n\n确定继续？",
                          "zh_TW": "即將直接覆寫原始音訊檔案：\n{path}\n\n此操作無法復原。系統會自動在旁邊建立一份備份，\n但仍請確認您已自行妥善保存原始檔案。\n\n確定繼續？"},
    "trim.no_silence":   {"en_US": "No leading silence detected",
                          "zh_CN": "未检测到开头静默",
                          "zh_TW": "未偵測到開頭靜音"},
    "trim.need_audio":   {"en_US": "No audio loaded",  "zh_CN": "未加载音频",       "zh_TW": "未載入音訊"},
    "trim.done_save":    {"en_US": "Saved and imported: {path}",
                          "zh_CN": "已保存并导入：{path}",
                          "zh_TW": "已儲存並匯入：{path}"},
    "trim.done_src":     {"en_US": "Source file updated (backup: {path})",
                          "zh_CN": "源文件已更新（备份：{path}）",
                          "zh_TW": "原始檔案已更新（備份：{path}）"},
    "trim.failed":       {"en_US": "Operation failed: {err}",
                          "zh_CN": "操作失败：{err}",
                          "zh_TW": "操作失敗：{err}"},
    # --- 项目新建弹窗（T-908）---
    "project_new.title":       {"en_US": "New Project",             "zh_CN": "新建项目",         "zh_TW": "新建專案"},
    "project_new.name":        {"en_US": "Project Name",            "zh_CN": "项目名称",         "zh_TW": "專案名稱"},
    "project_new.name_ph":     {"en_US": "e.g. My Research Project","zh_CN": "例如：我的研究项目", "zh_TW": "例如：我的研究專案"},
    "project_new.dir":         {"en_US": "Storage Path",            "zh_CN": "项目存储路径",     "zh_TW": "專案儲存路徑"},
    "project_new.browse_dir":  {"en_US": "Browse…",                 "zh_CN": "浏览…",            "zh_TW": "瀏覽…"},
    "project_new.import":      {"en_US": "Import Audio (Optional)", "zh_CN": "音频导入（可选）", "zh_TW": "音訊匯入（可選）"},
    "project_new.browse_files":{"en_US": "Select Files…",           "zh_CN": "选择文件…",        "zh_TW": "選擇檔案…"},
    "project_new.create":      {"en_US": "Create",                  "zh_CN": "创建",             "zh_TW": "創建"},
    "project_new.cancel":      {"en_US": "Cancel",                  "zh_CN": "取消",             "zh_TW": "取消"},
    "project_new.err_name":    {"en_US": "Project name is required.","zh_CN": "请输入项目名称。",  "zh_TW": "請輸入專案名稱。"},
    "project_new.err_dir":     {"en_US": "Cannot create directory: {err}",
                                "zh_CN": "无法创建目录：{err}",
                                "zh_TW": "無法建立目錄：{err}"},
    "project_new.err_save":    {"en_US": "Project created, but saving failed: {err}",
                                "zh_CN": "项目已创建，但保存失败：{err}",
                                "zh_TW": "專案已建立，但儲存失敗：{err}"},
    # --- 文件管理器（T-910）---
    "file_browser.empty":      {"en_US": "No project or open files",  "zh_CN": "无项目或未打开文件", "zh_TW": "無專案或未開啟檔案"},
    # --- 空态共用构件（T-1033 §五-3：说明 + 主操作按钮 + 拖放提示）---
    "empty.drop_hint":         {"en_US": "or drag an audio file into the window",
                                "zh_CN": "或将音频文件拖入窗口",
                                "zh_TW": "或將音訊檔案拖入視窗"},
    "file_browser.open":       {"en_US": "Open",                      "zh_CN": "打开",               "zh_TW": "開啟"},
    "file_browser.reveal":     {"en_US": "Show in Finder",            "zh_CN": "在 Finder 中显示",   "zh_TW": "在 Finder 中顯示"},
    "file_browser.remove":     {"en_US": "Remove from Project",       "zh_CN": "从项目移除",         "zh_TW": "從專案移除"},
    "file_browser.batch":      {"en_US": "Batch Process…",            "zh_CN": "批处理…",            "zh_TW": "批次處理…"},
    # --- 批处理工作区（T-913）---
    "batch.title":             {"en_US": "Batch Workspace",            "zh_CN": "批处理工作区",        "zh_TW": "批次處理工作區"},
    "batch.exit":              {"en_US": "Exit",                       "zh_CN": "退出",               "zh_TW": "離開"},
    "batch.nav_title":         {"en_US": "Task Type",                  "zh_CN": "任务类型",           "zh_TW": "任務類型"},
    "batch.nav_empty":         {"en_US": "No batch functions available", "zh_CN": "暂无批处理功能",   "zh_TW": "暫無批次處理功能"},
    "batch.files_title":       {"en_US": "Files to Process",           "zh_CN": "待处理文件",         "zh_TW": "待處理檔案"},
    "batch.files_empty":       {"en_US": "No files yet. Add files or enter from the file manager.", "zh_CN": "尚无文件，请添加或从文件管理器进入", "zh_TW": "尚無檔案，請新增或從檔案管理員進入"},
    "batch.files_add":         {"en_US": "Add Files…",                 "zh_CN": "添加文件…",          "zh_TW": "新增檔案…"},
    "batch.files_remove":      {"en_US": "Remove Selected",            "zh_CN": "移除所选",           "zh_TW": "移除所選"},
    "batch.files_check_all":   {"en_US": "Check All",                  "zh_CN": "全选",               "zh_TW": "全選"},
    "batch.status_archived":   {"en_US": "Archived",                   "zh_CN": "已入档",             "zh_TW": "已入檔"},
    "batch.status_new":        {"en_US": "New",                        "zh_CN": "新登记",             "zh_TW": "新登記"},
    "batch.param_title":       {"en_US": "Parameters & Editing",       "zh_CN": "参数与编辑",         "zh_TW": "參數與編輯"},
    "batch.param_empty":       {"en_US": "Select a task type above to configure", "zh_CN": "选择模块后在此配置参数", "zh_TW": "選擇模組後在此設定參數"},
    "batch.progress_title":    {"en_US": "Progress & Results",         "zh_CN": "进度与结果",         "zh_TW": "進度與結果"},
    "batch.run":               {"en_US": "Run",                        "zh_CN": "执行",               "zh_TW": "執行"},
    "batch.run_done":          {"en_US": "Finished processing {n} file(s)", "zh_CN": "处理完成：{n} 个文件", "zh_TW": "處理完成：{n} 個檔案"},
    "batch.run_error":         {"en_US": "Error",                      "zh_CN": "错误",               "zh_TW": "錯誤"},
    "batch.result_ok":         {"en_US": "OK",                         "zh_CN": "完成",               "zh_TW": "完成"},
    "batch.result_fail":       {"en_US": "Failed",                     "zh_CN": "失败",               "zh_TW": "失敗"},

    # T-914 批量元数据模块（Batch Workspace 首个业务模块）
    "batch.meta.module_name": {
        "en_US": "Batch Edit Metadata",
        "zh_CN": "批量更改元数据",
        "zh_TW": "批次變更元資料",
    },
    "batch.meta.action": {
        "en_US": "Batch Edit Metadata…",
        "zh_CN": "批量更改元数据…",
        "zh_TW": "批次變更元資料…",
    },
    "batch.meta.step1": {
        "en_US": "1. Scope & Standard",
        "zh_CN": "1. 范围与标准",
        "zh_TW": "1. 範圍與標準",
    },
    "batch.meta.step2": {
        "en_US": "2. Batch Fields",
        "zh_CN": "2. 批量字段",
        "zh_TW": "2. 批次欄位",
    },
    "batch.meta.step3": {
        "en_US": "3. Review & Apply",
        "zh_CN": "3. 核对与应用",
        "zh_TW": "3. 核對與套用",
    },
    "batch.meta.prev": {
        "en_US": "Previous",
        "zh_CN": "上一步",
        "zh_TW": "上一步",
    },
    "batch.meta.next": {
        "en_US": "Next",
        "zh_CN": "下一步",
        "zh_TW": "下一步",
    },
    "batch.meta.apply": {
        "en_US": "Apply & Finish",
        "zh_CN": "应用并完成",
        "zh_TW": "套用並完成",
    },
    "batch.meta.cancel": {
        "en_US": "Cancel & Exit",
        "zh_CN": "取消并退出",
        "zh_TW": "取消並離開",
    },
    "batch.meta.scope_standard": {
        "en_US": "Cataloging standard (for reference/correspondence only)",
        "zh_CN": "著录标准（仅供参考/对应）",
        "zh_TW": "著錄標準（僅供參考/對應）",
    },
    "batch.meta.scope_summary": {
        "en_US": "This run will process {n} file(s): {new} to be registered / {archived} already archived",
        "zh_CN": "本次将处理 {n} 个文件：新登记 {new} 个 / 已入档 {archived} 个",
        "zh_TW": "本次將處理 {n} 個檔案：新登記 {new} 個 / 已入檔 {archived} 個",
    },
    "batch.meta.scope_note": {
        "en_US": "Files already archived keep their other fields; only the fields filled here are overwritten.",
        "zh_CN": "已入档文件保留其余字段，仅覆盖本页填写的字段。",
        "zh_TW": "已入檔檔案保留其餘欄位，僅覆寫本頁填寫的欄位。",
    },
    "batch.meta.common_title": {
        "en_US": "Common fields (filled once, applied to all files)",
        "zh_CN": "共同字段（一次填写，应用全部文件）",
        "zh_TW": "共同欄位（一次填寫，套用全部檔案）",
    },
    "batch.meta.recorder": {
        "en_US": "Recorder",
        "zh_CN": "摄录者",
        "zh_TW": "攝錄者",
    },
    "batch.meta.date_placeholder": {
        "en_US": "Leave blank = each file's own timestamp",
        "zh_CN": "留空＝按各文件时间戳",
        "zh_TW": "留空＝依各檔案時間戳",
    },
    "batch.meta.date_range": {
        "en_US": "Detected file timestamp range: {rng}",
        "zh_CN": "检测到文件时间戳范围：{rng}",
        "zh_TW": "偵測到檔案時間戳範圍：{rng}",
    },
    "batch.meta.title_mode": {
        "en_US": "Title mode",
        "zh_CN": "题名方式",
        "zh_TW": "題名方式",
    },
    "batch.meta.title_mode_file": {
        "en_US": "1) Default = file name (no extension)",
        "zh_CN": "① 默认＝文件名（去扩展名）",
        "zh_TW": "① 預設＝檔名（去副檔名）",
    },
    "batch.meta.title_mode_prefix": {
        "en_US": "2) Common prefix + file name",
        "zh_CN": "② 统一前缀＋文件名",
        "zh_TW": "② 統一前綴＋檔名",
    },
    "batch.meta.title_mode_manual": {
        "en_US": "3) Edit per row (in the review step)",
        "zh_CN": "③ 逐条编辑（在第 3 步逐行修改）",
        "zh_TW": "③ 逐條編輯（在第 3 步逐列修改）",
    },
    "batch.meta.prefix": {
        "en_US": "Common prefix",
        "zh_CN": "统一前缀",
        "zh_TW": "統一前綴",
    },
    "batch.meta.identifier_prefix": {
        "en_US": "Identifier / archive code prefix",
        "zh_CN": "标识符/档号前缀",
        "zh_TW": "識別符/檔號前綴",
    },
    "batch.meta.id_prefix_placeholder": {
        "en_US": "Default: ID",
        "zh_CN": "默认：ID",
        "zh_TW": "預設：ID",
    },
    "batch.meta.identifier_hint": {
        "en_US": "Auto rule: <prefix>-<3-digit index>; each row can be corrected in the review step.",
        "zh_CN": "自动生成规则：<前缀>-<三位序号>；可在第 3 步逐行校正。",
        "zh_TW": "自動產生規則：<前綴>-<三位序號>；可在第 3 步逐列校正。",
    },
    "batch.meta.tech_title": {
        "en_US": "Technical metadata (auto-extracted per file, read-only)",
        "zh_CN": "技术元数据（逐文件自动提取，只读）",
        "zh_TW": "技術元資料（逐檔案自動擷取，唯讀）",
    },
    "batch.meta.tech_note": {
        "en_US": "Sampling rate / bit depth / format / channels / duration are extracted from each audio file and never typed by hand.",
        "zh_CN": "采样率/位深/格式/声道/时长由各音频文件自动提取，不手工填写。",
        "zh_TW": "取樣率/位元深度/格式/聲道/時長由各音訊檔案自動擷取，不手動填寫。",
    },
    "batch.meta.step3_hint": {
        "en_US": "Review each file's final summary; a missing required field blocks the run.",
        "zh_CN": "逐行核对每文件最终摘要；必填缺失将阻止执行。",
        "zh_TW": "逐列核對每個檔案的最終摘要；必填缺失將阻止執行。",
    },
    "batch.meta.col_file": {
        "en_US": "File",
        "zh_CN": "文件名",
        "zh_TW": "檔名",
    },
    "batch.meta.col_title": {
        "en_US": "Title",
        "zh_CN": "题名",
        "zh_TW": "題名",
    },
    "batch.meta.col_tech": {
        "en_US": "Technical (read-only)",
        "zh_CN": "技术元数据（只读）",
        "zh_TW": "技術元資料（唯讀）",
    },
    "batch.meta.col_summary": {
        "en_US": "Metadata to write",
        "zh_CN": "将写入的元数据",
        "zh_TW": "將寫入的元資料",
    },
    "batch.meta.col_warn": {
        "en_US": "Empty-field warning",
        "zh_CN": "空字段警告",
        "zh_TW": "空欄位警告",
    },
    "batch.meta.standard_label": {
        "en_US": "Standard",
        "zh_CN": "标准",
        "zh_TW": "標準",
    },
    "batch.meta.warn_creator": {
        "en_US": "Missing required: Creator / Inheritor",
        "zh_CN": "缺少必填：责任者/传承人",
        "zh_TW": "缺少必填：責任者/傳承人",
    },
    "batch.meta.blocked": {
        "en_US": "Creator / Inheritor is required — please fill it in step 2.",
        "zh_CN": "责任者/传承人为必填，请在第 2 步填写。",
        "zh_TW": "責任者/傳承人為必填，請在第 2 步填寫。",
    },
    "batch.meta.err_creator_required": {
        "en_US": "Creator / Inheritor is required",
        "zh_CN": "责任者/传承人为必填",
        "zh_TW": "責任者/傳承人為必填",
    },
    "batch.meta.err_no_manager": {
        "en_US": "No project manager available",
        "zh_CN": "无可用项目管理器",
        "zh_TW": "無可用的專案管理器",
    },
    "batch.meta.warn_missing_fields": {
        "en_US": "Missing required: {fields}",
        "zh_CN": "必填缺失：{fields}",
        "zh_TW": "必填缺失：{fields}",
    },
    "batch.meta.err_fields_missing": {
        "en_US": "Missing required fields: {fields}",
        "zh_CN": "必填字段缺失：{fields}",
        "zh_TW": "必填欄位缺失：{fields}",
    },
    "batch.meta.applied": {
        "en_US": "Done: {ok} succeeded / {fail} failed",
        "zh_CN": "已完成：{ok} 成功 / {fail} 失败",
        "zh_TW": "已完成：{ok} 成功 / {fail} 失敗",
    },
    "batch.meta.progress": {
        "en_US": "Writing metadata {i}/{n}: {name}",
        "zh_CN": "写入元数据 {i}/{n}：{name}",
        "zh_TW": "寫入元資料 {i}/{n}：{name}",
    },

    # --- 波形右键菜单（T-915）---
    "ctx.analyze_region":      {"en_US": "Analyze This Region",       "zh_CN": "分析此区域",         "zh_TW": "分析此區域"},
    # --- 选区区间分析（T-916）---
    "analyze_region.invalid":  {"en_US": "Invalid analysis region",   "zh_CN": "无效的分析区间",     "zh_TW": "無效的分析區間"},
    "analyze_region.no_offline": {"en_US": "No offline analysis for the current view; switch to an analysis view",
                                 "zh_CN": "当前视图无离线分析，请切换到分析视图", "zh_TW": "目前視圖無離線分析，請切換到分析視圖"},
    "analyze_region.fft_unsupported": {"en_US": "FFT view does not support region analysis yet",
                                 "zh_CN": "FFT 视图暂不支持区域分析", "zh_TW": "FFT 視圖暫不支援區域分析"},
    "analyze_region.status":   {"en_US": "Analyzing region {t0}–{t1} s",
                                 "zh_CN": "分析区域 {t0}–{t1} s",    "zh_TW": "分析區域 {t0}–{t1} s"},
    # --- 选区测量（T-326 Pδ：悬停读数 + 两点测量）---
    "measure_selection":      {"en_US": "Measure Selection", "zh_CN": "测量选区", "zh_TW": "測量選區"},
    "measure_clear":          {"en_US": "Clear Measurement", "zh_CN": "清除测量", "zh_TW": "清除測量"},
    "measure_result.full":    {"en_US": "Δt {dt} s | ΔHz {df} | Δcent {dc} | ratio {ratio}",
                               "zh_CN": "Δt {dt} s | ΔHz {df} | Δ音分 {dc} | 频率比 {ratio}",
                               "zh_TW": "Δt {dt} s | ΔHz {df} | Δ音分 {dc} | 頻率比 {ratio}"},
    "measure_result.dt_only": {"en_US": "Δt {dt} s", "zh_CN": "Δt {dt} s", "zh_TW": "Δt {dt} s"},
    # --- 选区区间统计（T-327 Pε）---
    "region_stats":        {"en_US": "Region Statistics…", "zh_CN": "区间统计…", "zh_TW": "區間統計…"},
    "region_stats.copy":   {"en_US": "Copy", "zh_CN": "复制", "zh_TW": "複製"},
    "region_stats.no_cache": {"en_US": "No analysis result for this region — run analysis for it first",
                              "zh_CN": "该区间无分析结果，请先分析此区域",
                              "zh_TW": "該區間無分析結果，請先分析此區域"},
    "inspector.stats":     {"en_US": "Region Statistics", "zh_CN": "选区统计", "zh_TW": "選區統計"},
    "region_stats.r_time": {"en_US": "Selection {t0}–{t1} s · duration {dt} s",
                            "zh_CN": "选区 {t0}–{t1} s · 时长 {dt} s",
                            "zh_TW": "選區 {t0}–{t1} s · 時長 {dt} s"},
    "region_stats.r_rms":  {"en_US": "Energy RMS {rms} dB (lin {lin}) · peak {peak} dB",
                            "zh_CN": "能量 RMS {rms} dB（线性 {lin}）· 峰值 {peak} dB",
                            "zh_TW": "能量 RMS {rms} dB（線性 {lin}）· 峰值 {peak} dB"},
    "region_stats.r_pitch": {"en_US": "Pitch voiced {v}/{n} ({pct})\nf0 mean {mean} · med {median} · {fmin}–{fmax} Hz · range {rng} Hz\ncent(A4) mean {cent}",
                             "zh_CN": "音高 浊音 {v}/{n}（{pct}）\n基频 均值 {mean} · 中位 {median} · {fmin}–{fmax} Hz · 范围 {rng} Hz\n音分(A4) 均值 {cent}",
                             "zh_TW": "音高 濁音 {v}/{n}（{pct}）\n基頻 均值 {mean} · 中位 {median} · {fmin}–{fmax} Hz · 範圍 {rng} Hz\n音分(A4) 均值 {cent}"},
    "region_stats.r_pitch_na": {"en_US": "Pitch — no voiced frame in region",
                                "zh_CN": "音高 — 选区内无浊音帧",
                                "zh_TW": "音高 — 選區內無濁音幀"},
    # --- 档案元数据编辑区（T-912；说明区文案照抄需求说明 §说明区文案，禁改写）---
    "inspector.metadata": {
        "en_US": "Archive Metadata",
        "zh_CN": "档案元数据",
        "zh_TW": "檔案元資料",
    },
    "inspector.meta.save": {"en_US": "Save", "zh_CN": "保存", "zh_TW": "儲存"},
    "inspector.meta.saved": {
        "en_US": "✓ Saved",
        "zh_CN": "✓ 已保存",
        "zh_TW": "✓ 已儲存",
    },
    "inspector.meta.missing_required": {
        "en_US": "Missing required fields for {standard}: {fields}. Nothing was saved.",
        "zh_CN": "该标准（{standard}）必填项未填：{fields}，已阻止保存。",
        "zh_TW": "該標準（{standard}）必填項未填：{fields}，已阻止儲存。",
    },
    "inspector.meta.format_warn": {
        "en_US": "Value format warning: {fields} should use YYYY-MM-DD.",
        "zh_CN": "值域提示：{fields} 应为 YYYY-MM-DD 格式（已保存，请核对）。",
        "zh_TW": "值域提示：{fields} 應為 YYYY-MM-DD 格式（已儲存，請核對）。",
    },
    "inspector.meta.empty": {
        "en_US": "Select an audio file in the File panel to view or edit its archive metadata.",
        "zh_CN": "在文件管理器中选择一个音频文件，以查看/编辑其档案元数据。",
        "zh_TW": "在檔案管理器中選擇一個音訊檔案，以檢視/編輯其檔案元資料。",
    },
    "inspector.meta.custom_note": {
        "en_US": "Custom extension (non-standard elements)",
        "zh_CN": "自定义扩展（非标准元素）",
        "zh_TW": "自訂擴充（非標準元素）",
    },
    "inspector.meta.std_dat": {
        "en_US": "DA/T 63-2017 Metadata Scheme for Audio and Video Electronic Records",
        "zh_CN": "DA/T 63-2017 录音录像类电子档案元数据方案",
        "zh_TW": "DA/T 63-2017 錄音錄影類電子檔案元資料方案",
    },
    "inspector.meta.std_gbt": {
        "en_US": "GB/T 31219.4-2014 Digitization Processing Specifications for Library Collection Resources — Part 4: Audio Resources",
        "zh_CN": "GB/T 31219.4-2014 图书馆馆藏资源数字化加工规范 第4部分：音频资源",
        "zh_TW": "GB/T 31219.4-2014 圖書館館藏資源數位化加工規範 第4部分：音訊資源",
    },
    "inspector.meta.std_custom": {
        "en_US": "Not specified (custom)",
        "zh_CN": "不指定（自定义）",
        "zh_TW": "不指定（自訂）",
    },
    "inspector.meta.desc_dat": {
        "en_US": "· Nature: industry standard of the National Archives Administration, “Metadata Scheme for Audio and Video Electronic Records” (final released edition, verified).\n"
                 "· Scope: audio/video electronic records of archives at all levels, organizations, and enterprises.\n"
                 "· Features: four-entity model (records/business/agents/authorization; records entity mandatory); some elements are auto-extracted by system (recording time, audio parameters).\n"
                 "· Note: this software supports a subset mapping of its records entity (Table 2; M76-M96 not covered), not the full scheme; archive code/title/creator/time are mandatory items.",
        "zh_CN": "· 性质：国家档案局档案行业标准《录音录像类电子档案元数据方案》（正式发布版，已核对）。\n"
                 "· 适用范围：各级机关/团体/企事业单位和国家档案馆的录音、录像类电子档案。\n"
                 "· 特点：四实体模式（档案实体/业务/机构人员/授权；档案实体必选）；部分元素由系统自动提取（如摄录时间、音频参数）。\n"
                 "· 注意：本软件支持其档案实体的子集映射（表2，不含 M76-M96 三个业务实体），不等同于完整方案；档号/题名/责任者/时间等为标准必选。",
        "zh_TW": "· 性質：國家檔案局檔案行業標準《錄音錄影類電子檔案元資料方案》（正式發布版，已核對）。\n"
                 "· 適用範圍：各級機關/團體/企事業單位和國家檔案館的錄音、錄影類電子檔案。\n"
                 "· 特點：四實體模式（檔案實體/業務/機構人員/授權；檔案實體必選）；部分元素由系統自動提取（如攝錄時間、音訊參數）。\n"
                 "· 注意：本軟體支援其檔案實體的子集對映（表2，不含 M76-M96 三個業務實體），不等同於完整方案；檔號/題名/責任者/時間等為標準必選。",
    },
    "inspector.meta.desc_gbt": {
        "en_US": "· Nature: national standard “Digitization Processing Specifications for Library Collection Resources — Part 4: Audio Resources” (digitization processing specification).\n"
                 "· Scope: digitization processing of library audio resources; other documentation institutions may reference.\n"
                 "· Features: focuses on processing grade/technical parameters/process; metadata is technical and managerial (Table 1 content items, Table 2 packaging info).\n"
                 "· Note: it has no humanistic fields such as creator/location/genre; this software only corresponds to its technical/managerial metadata subset.",
        "zh_CN": "· 性质：国家标准《图书馆馆藏资源数字化加工规范 第4部分：音频资源》（数字化加工规范）。\n"
                 "· 适用范围：图书馆音频资源数字化加工，其他文献信息机构可参照。\n"
                 "· 特点：侧重加工级别/技术参数/加工流程；元数据偏技术与管理（表1 应标记内容项、表2 封装信息）。\n"
                 "· 注意：不含创作者/地理位置/流派等人文描述字段；本软件仅对应其技术/管理元数据子集。",
        "zh_TW": "· 性質：國家標準《圖書館館藏資源數位化加工規範 第4部分：音訊資源》（數位化加工規範）。\n"
                 "· 適用範圍：圖書館音訊資源數位化加工，其他文獻資訊機構可參照。\n"
                 "· 特點：側重加工級別/技術參數/加工流程；元資料偏技術與管理（表1 應標記內容項、表2 封裝資訊）。\n"
                 "· 注意：不含創作者/地理位置/流派等人文描述欄位；本軟體僅對應其技術/管理元資料子集。",
    },
    "inspector.meta.desc_custom": {
        "en_US": "Use the custom cataloging fields of this software (for field-research scenarios such as intangible cultural heritage and ethnomusicology).",
        "zh_CN": "使用本软件自定义著录字段（面向非遗/民族音乐学等田野研究场景）。",
        "zh_TW": "使用本軟體自訂著錄欄位（面向非遺/民族音樂學等田野研究場景）。",
    },
    "inspector.meta.std_imdi": {
        "en_US": "IMDI 3.0.22 (ISLE Meta Data Initiative)",
        "zh_CN": "IMDI 3.0.22（ISLE 元数据计划）",
        "zh_TW": "IMDI 3.0.22（ISLE 元資料計畫）",
    },
    "inspector.meta.desc_imdi": {
        "en_US": "· Nature: IMDI (ISLE Meta Data Initiative) session metadata schema, official XSD 3.0.22 (2015-08-26).\n"
                 "· Status: succeeded by CLARIN CMDI (ISO 24648:2012); field-level mapping follows the 3.0.22 XSD.\n"
                 "· Features: Session structure (Title/Date/MDGroup/Resources…); Identifier uses the short-name slot Session/Name; technical parameters are carried in MediaFile/Keys.\n"
                 "· Validation: the output is a METATRANSCRIPT document-level structure which passes structural validation against the official IMDI 3.0.22 XSD; closed-vocabulary conformance is outside that check.",
        "zh_CN": "· 性质：IMDI（ISLE Meta Data Initiative）会话元数据模式，官方 XSD 3.0.22（2015-08-26）。\n"
                 "· 状态：已由 CLARIN CMDI（ISO 24648:2012）承接；字段级映射以 3.0.22 XSD 为准。\n"
                 "· 特点：Session 结构（Title/Date/MDGroup/Resources…）；Identifier 挂短名槽 Session/Name；技术参数挂 MediaFile/Keys。\n"
                 "· 校验：输出为 METATRANSCRIPT 文档级结构，已通过官方 IMDI 3.0.22 XSD 的结构校验；闭集受控词表合规不在该校验范围内。",
        "zh_TW": "· 性質：IMDI（ISLE Meta Data Initiative）會話元資料模式，官方 XSD 3.0.22（2015-08-26）。\n"
                 "· 狀態：已由 CLARIN CMDI（ISO 24648:2012）承接；欄位級對映以 3.0.22 XSD 為準。\n"
                 "· 特點：Session 結構（Title/Date/MDGroup/Resources…）；Identifier 掛短名槽 Session/Name；技術參數掛 MediaFile/Keys。\n"
                 "· 校驗：輸出為 METATRANSCRIPT 文件級結構，已通過官方 IMDI 3.0.22 XSD 的結構校驗；閉集受控詞表合規不在該校驗範圍內。",
    },
    "inspector.meta.sampling_rate": {
        "en_US": "Sampling Rate (Hz)",
        "zh_CN": "采样率(Hz)",
        "zh_TW": "取樣率(Hz)",
    },
    "inspector.meta.bit_depth": {
        "en_US": "Bit Depth (bit)",
        "zh_CN": "位深(bit)",
        "zh_TW": "位元深度(bit)",
    },
    "inspector.meta.format": {"en_US": "Format", "zh_CN": "格式", "zh_TW": "格式"},
    "inspector.meta.channels": {
        "en_US": "Channels",
        "zh_CN": "声道",
        "zh_TW": "聲道",
    },
    "inspector.meta.duration": {
        "en_US": "Duration",
        "zh_CN": "时长",
        "zh_TW": "時長",
    },
    # M-8a：DA/T 四项自动/预设值的报告/检查器共用标签（三语齐；ko/ja 随批后补）
    "inspector.meta.file_name": {
        "en_US": "File name",
        "zh_CN": "文件名",
        "zh_TW": "檔名",
    },
    "inspector.meta.file_size": {
        "en_US": "File size",
        "zh_CN": "文件大小",
        "zh_TW": "檔案大小",
    },
    "inspector.meta.aggregation_level": {
        "en_US": "Aggregation level",
        "zh_CN": "聚合层次",
        "zh_TW": "聚合層次",
    },
    "inspector.meta.retention_period": {
        "en_US": "Retention period",
        "zh_CN": "保管期限",
        "zh_TW": "保管期限",
    },
    "inspector.meta.date": {
        "en_US": "Recording Date",
        "zh_CN": "摄录时间",
        "zh_TW": "攝錄時間",
    },
    "inspector.meta.identifier": {
        "en_US": "Identifier / Ref No.",
        "zh_CN": "标识符/档号",
        "zh_TW": "識別符/檔號",
    },
    "inspector.meta.title": {"en_US": "Title", "zh_CN": "题名", "zh_TW": "題名"},
    "inspector.meta.creator": {
        "en_US": "Creator / Inheritor",
        "zh_CN": "责任者/传承人",
        "zh_TW": "責任者/傳承人",
    },
    "inspector.meta.location": {
        "en_US": "Location",
        "zh_CN": "地理位置",
        "zh_TW": "地理位置",
    },
    "inspector.meta.genre_context": {
        "en_US": "Genre / Context",
        "zh_CN": "文化语境/流派",
        "zh_TW": "文化語境/流派",
    },
    "inspector.meta.actor_role": {
        "en_US": "Actor Role",
        "zh_CN": "表演者角色",
        "zh_TW": "表演者角色",
    },
    # --- 音高后端切换即时生效（T-1014）---
    "pitch_backend.switched_reanalyze": {
        "en_US": "Pitch algorithm switched to {backend}; re-analyzing…",
        "zh_CN": "音高算法已切换为 {backend}，正在重新分析…",
        "zh_TW": "音高演算法已切換為 {backend}，正在重新分析…",
    },
    "pitch_backend.switched_next": {
        "en_US": "Pitch algorithm switched to {backend}; takes effect on next analysis",
        "zh_CN": "已切换为 {backend}，下次分析生效",
        "zh_TW": "已切換為 {backend}，下次分析生效",
    },
    # --- 赞助致谢框（T-1017；正文为用户定稿中文原文，禁改字）---
    "sponsor.window_title": {
        "en_US": "Support AcouScope",
        "zh_CN": "支持 AcouScope",
        "zh_TW": "支持 AcouScope",
    },
    "sponsor.heading": {
        "en_US": "Thank you for supporting AcouScope.",
        "zh_CN": "感谢您支持 AcouScope·音析。",
        "zh_TW": "感謝您支持 AcouScope·音析。",
    },
    "sponsor.body": {
        "en_US": (
            "AcouScope is free and open-source software. All features are "
            "permanently free to use.\n"
            "If it has ever helped your work, you are sincerely welcome to "
            "support it voluntarily.\n"
            "The amount and method are entirely up to you (a reference of 12 CNY "
            "is suggested, with no upper limit). It is completely voluntary and "
            "does not affect any feature.\n"
            "\n"
            "Every bit of your support goes toward advancing AcouScope!"
        ),
        "zh_CN": (
            "AcouScope 为开源自由软件，所有功能永久免费可用。\n"
            "若它曾助益您的工作，我们诚挚欢迎您自愿予以支持。\n"
            "赞助金额与方式皆由您酌定（建议参考 12 元，无上限），完全自愿，不影响任何功能。\n"
            "\n"
            "您的每一份支持，都将用于推进 AcouScope 的持续进步！"
        ),
        "zh_TW": (
            "AcouScope 為開源自由軟體，所有功能永久免費可用。\n"
            "若它曾助益您的工作，我們誠摯歡迎您自願予以支持。\n"
            "贊助金額與方式皆由您酌定（建議參考 12 元，無上限），完全自願，不影響任何功能。\n"
            "\n"
            "您的每一份支持，都將用於推進 AcouScope 的持續進步！"
        ),
    },
    "sponsor.qr_zhifubao": {
        "en_US": "Alipay",
        "zh_CN": "支付宝",
        "zh_TW": "支付寶",
    },
    "sponsor.qr_weixin": {
        "en_US": "WeChat",
        "zh_CN": "微信",
        "zh_TW": "微信",
    },
    "sponsor.qr_missing": {
        "en_US": "QR code unavailable",
        "zh_CN": "二维码暂缺",
        "zh_TW": "二維碼暫缺",
    },
    "sponsor.continue": {
        "en_US": "Continue",
        "zh_CN": "继续使用",
        "zh_TW": "繼續使用",
    },
    "sponsor.dismiss": {
        "en_US": "I've supported it — don't remind me again",
        "zh_CN": "已支持，不再提醒",
        "zh_TW": "已支持，不再提醒",
    },
    # --- T-1111 主窗常驻「支持一下」心跳按钮（纯追加键；既有 sponsor.* 逐字零动）---
    "encourage.label": {
        "en_US": "Encourage us",
        "zh_CN": "支持一下",
        "zh_TW": "支持一下",
    },
    "encourage.tip": {
        "en_US": "Enjoying AcouScope? Your support keeps it moving.",
        "zh_CN": "若 AcouScope 曾助益您的工作，欢迎自愿支持我们。",
        "zh_TW": "若 AcouScope 曾助益您的工作，歡迎自願支持我們。",
    },
    # --- T-1112 主窗常驻「微信群」入口与二维码窗（纯追加键；既有 sponsor.*/encourage.* 逐字零动）---
    "weixin_group.label": {
        "en_US": "WeChat group",
        "zh_CN": "微信群",
        "zh_TW": "微信群",
    },
    "weixin_group.tip": {
        "en_US": "Join the official AcouScope WeChat group — questions, bug reports and early previews.",
        "zh_CN": "加入 AcouScope 官方微信群 · 提问 / 反馈 / 新特性预告",
        "zh_TW": "加入 AcouScope 官方微信群 · 提問 / 回饋 / 新特性預告",
    },
    "weixin_group.window_title": {
        "en_US": "Official WeChat group",
        "zh_CN": "官方微信群",
        "zh_TW": "官方微信群",
    },
    "weixin_group.heading": {
        "en_US": "Join the AcouScope community group.",
        "zh_CN": "加入 AcouScope 官方微信群。",
        "zh_TW": "加入 AcouScope 官方微信群。",
    },
    "weixin_group.body": {
        "en_US": (
            "AcouScope is still evolving, and your voice is what moves it forward.\n"
            "In the group you can ask questions, report bugs, and share a recording "
            "that puzzles you; get new releases and feature previews ahead of time; "
            "and trade answers with other researchers in musicology, acoustics and "
            "digital humanities.\n"
            "Just scan the code to join. Please keep the room civil: no advertising, "
            "no flooding, and give some context when you start a topic.\n"
            "\n"
            "If the code shows as expired or the group is full, please get the latest "
            "one from the download page on our website, or write to the author by email."
        ),
        "zh_CN": (
            "AcouScope 仍在持续演进，你的声音就是它前进的方向。\n"
            "在群里你可以：提问题、报缺陷，贴一段让你困惑的录音；拿到新版本与功能预告；"
            "与其他音乐学、声学和数字人文方向的研究者互相答疑。\n"
            "扫码入群即可。群内请守基本礼仪：不广告、不刷屏，讨论请带上上下文。\n"
            "\n"
            "若二维码提示已过期或群已满员，请到官网下载页获取最新二维码，或邮件联系作者。"
        ),
        "zh_TW": (
            "AcouScope 仍在持續演進，你的聲音就是它前進的方向。\n"
            "在群裡你可以：提問題、報缺陷，貼一段讓你困惑的錄音；拿到新版本與功能預告；"
            "與其他音樂學、聲學和數位人文方向的研究者互相答疑。\n"
            "掃碼入群即可。群內請守基本禮儀：不廣告、不刷屏，討論請带上上下文。\n"
            "\n"
            "若二維碼提示已過期或群已滿員，請到官網下載頁取得最新二維碼，或郵件聯繫作者。"
        ),
    },
    "weixin_group.qr_caption": {
        "en_US": "Group QR code — scan with WeChat",
        "zh_CN": "微信群二维码 · 微信扫一扫",
        "zh_TW": "微信群二維碼 · 微信掃一掃",
    },
    "weixin_group.qr_missing": {
        "en_US": "QR code unavailable — please get the latest one from our website.",
        "zh_CN": "二维码暂缺 · 请到官网下载页获取最新二维码。",
        "zh_TW": "二維碼暫缺 · 請到官網下載頁取得最新二維碼。",
    },
    "weixin_group.close": {
        "en_US": "Close",
        "zh_CN": "关闭",
        "zh_TW": "關閉",
    },
    # --- AI 释图面板：对话式（T-1018；全部为追加键，不改既有键）---
    "ai_panel.model_prefix": {
        "en_US": "Current model: {model}",
        "zh_CN": "当前模型：{model}",
        "zh_TW": "目前模型：{model}",
    },
    "ai_panel.unconfigured": {
        "en_US": "No model configured — click ⚙ to open Settings → AI",
        "zh_CN": "尚未配置模型 —— 点击 ⚙ 前往「设置 → AI 配置」",
        "zh_TW": "尚未設定模型 —— 點擊 ⚙ 前往「設定 → AI 設定」",
    },
    "ai_panel.settings_tip": {
        "en_US": "Model settings (Settings → AI)",
        "zh_CN": "模型设置（前往 设置 → AI）",
        "zh_TW": "模型設定（前往 設定 → AI）",
    },
    "ai_panel.settings_fallback": {
        "en_US": "Adjust the model in the AI tab of the Settings panel on the left.",
        "zh_CN": "请在左侧「设置」面板的 AI 选项卡中调整模型。",
        "zh_TW": "請在左側「設定」面板的 AI 分頁中調整模型。",
    },
    "ai_panel.role_user": {
        "en_US": "Me",
        "zh_CN": "我",
        "zh_TW": "我",
    },
    "ai_panel.role_assistant": {
        "en_US": "AI",
        "zh_CN": "AI",
        "zh_TW": "AI",
    },
    "ai_panel.stream_hint": {
        "en_US": ("The conversation has not started yet. The numeric context and "
                  "the current view screenshot are pre-filled below — send "
                  "directly or edit first."),
        "zh_CN": ("对话尚未开始。下方已预填当前视图的数值上下文与截图，"
                  "可直接发送，或编辑后再发送。"),
        "zh_TW": ("對話尚未開始。下方已預填目前檢視的數值上下文與截圖，"
                  "可直接傳送，或編輯後再傳送。"),
    },
    "ai_panel.input_placeholder": {
        "en_US": ("Type a message… (Ctrl+V to paste an image, or drag one in; "
                  "Enter to send, Shift+Enter for a new line)"),
        "zh_CN": ("输入消息…（Ctrl+V 贴图，或直接拖入图片；"
                  "回车发送，Shift+Enter 换行）"),
        "zh_TW": ("輸入訊息…（Ctrl+V 貼圖，或直接拖入圖片；"
                  "Enter 傳送，Shift+Enter 換行）"),
    },
    "ai_panel.input_hint": {
        "en_US": "Enter to send · Shift+Enter for a new line · drop or paste images",
        "zh_CN": "回车发送 · Shift+Enter 换行 · 可拖入或粘贴图片",
        "zh_TW": "Enter 傳送 · Shift+Enter 換行 · 可拖入或貼上圖片",
    },
    "ai_panel.send": {
        "en_US": "Send",
        "zh_CN": "发送",
        "zh_TW": "傳送",
    },
    "ai_panel.sending": {
        "en_US": "Interpreting…",
        "zh_CN": "释图中…",
        "zh_TW": "釋圖中…",
    },
    "ai_panel.stop": {
        "en_US": "Stop",
        "zh_CN": "停止",
        "zh_TW": "停止",
    },
    "ai_panel.empty_input": {
        "en_US": "Please type something before sending.",
        "zh_CN": "请先输入内容再发送。",
        "zh_TW": "請先輸入內容再傳送。",
    },
    "ai_panel.attach_current_view": {
        "en_US": "Current view",
        "zh_CN": "当前视图",
        "zh_TW": "目前檢視",
    },
    "ai_panel.attach_name": {
        "en_US": "Image {n}",
        "zh_CN": "图片 {n}",
        "zh_TW": "圖片 {n}",
    },
    "ai_panel.attach_remove": {
        "en_US": "Remove",
        "zh_CN": "移除",
        "zh_TW": "移除",
    },
    "ai_panel.attach_remove_tip": {
        "en_US": "Remove this image from the message",
        "zh_CN": "从本条消息中移除该图片",
        "zh_TW": "從本則訊息中移除該圖片",
    },
    "ai_panel.attach_full": {
        "en_US": "At most {n} images can be attached.",
        "zh_CN": "最多可附带 {n} 张图片。",
        "zh_TW": "最多可附加 {n} 張圖片。",
    },
    "ai_panel.attached_tip": {
        "en_US": "Image attached to this message",
        "zh_CN": "本条消息附带的图片",
        "zh_TW": "本則訊息附加的圖片",
    },
    "ai_panel.multi_image_note": {
        "en_US": ("The current engine interprets a single image; only the first "
                  "one will be sent."),
        "zh_CN": "当前引擎按单张图片释读，本次将只发送第一张图片。",
        "zh_TW": "目前引擎以單張圖片釋讀，本次將只傳送第一張圖片。",
    },
    "ai_panel.ask_failed": {
        "en_US": ("Follow-up failed: {msg}. You can switch to a remote model "
                  "in Settings → AI and retry."),
        "zh_CN": "追问失败：{msg}。可在「设置 → AI」中切换远程模型后重试。",
        "zh_TW": "追問失敗：{msg}。可在「設定 → AI」中切換遠端模型後重試。",
    },
    "ai_panel.failed_title": {
        "en_US": "Interpretation failed",
        "zh_CN": "释图失败",
        "zh_TW": "釋圖失敗",
    },
    "ai_panel.failed_text": {
        "en_US": "The interpretation could not be completed",
        "zh_CN": "释图未能完成",
        "zh_TW": "釋圖未能完成",
    },
    "ai_panel.switch_remote": {
        "en_US": "Switch to remote model",
        "zh_CN": "切换远程模型",
        "zh_TW": "切換遠端模型",
    },
    "ai_panel.cancel": {
        "en_US": "Cancel",
        "zh_CN": "取消",
        "zh_TW": "取消",
    },
    # --- T-1055：MD 渲染配套（气泡复制 / 重新生成 / 清空二次确认）三语齐 ---
    "ai_panel.copy": {
        "en_US": "Copy",
        "zh_CN": "复制",
        "zh_TW": "複製",
    },
    "ai_panel.copy_tip": {
        "en_US": "Copy this message (Markdown source)",
        "zh_CN": "复制本条消息（Markdown 原文）",
        "zh_TW": "複製此則訊息（Markdown 原文）",
    },
    "ai_panel.regenerate": {
        "en_US": "Regenerate",
        "zh_CN": "重新生成",
        "zh_TW": "重新生成",
    },
    "ai_panel.regenerate_tip": {
        "en_US": "Regenerate the last AI response",
        "zh_CN": "重新生成最后一条 AI 回复",
        "zh_TW": "重新生成最後一則 AI 回覆",
    },
    "ai_panel.regenerate_none": {
        "en_US": "Nothing to regenerate yet.",
        "zh_CN": "还没有可重新生成的内容。",
        "zh_TW": "還沒有可重新生成的內容。",
    },
    "ai_panel.clear": {
        "en_US": "Clear",
        "zh_CN": "清空",
        "zh_TW": "清空",
    },
    "ai_panel.clear_tip": {
        "en_US": "Clear this conversation and start a new one",
        "zh_CN": "清空当前对话，开始新对话",
        "zh_TW": "清空目前對話，開始新對話",
    },
    "ai_panel.clear_confirm": {
        "en_US": "Click Clear again to confirm clearing this conversation",
        "zh_CN": "再次点击「清空」确认清空当前对话",
        "zh_TW": "再次點擊「清空」確認清空目前對話",
    },
    "ai_panel.cleared": {
        "en_US": "Conversation cleared. Start a new one.",
        "zh_CN": "对话已清空，开始新对话。",
        "zh_TW": "對話已清空，開始新對話。",
    },
    # --- T-1020：设置落盘反馈 / 顶部三档下拉 / 失败诊断分类（全部为追加键，
    #     不改既有键；档位标签与「模型来源」复用 settings.* 既有键）---
    "ai_panel.config_save_failed": {
        "en_US": ("Failed to save the AI settings — no writable config "
                  "directory. Please check permissions and try again."),
        "zh_CN": "AI 设置保存失败：所有配置目录均不可写，请检查权限后重试。",
        "zh_TW": "AI 設定儲存失敗：所有設定目錄皆不可寫入，請檢查權限後重試。",
    },
    "ai_panel.source_switch_tip": {
        "en_US": "Model source (saved immediately; other parameters unchanged)",
        "zh_CN": "模型来源（选中即保存，其它参数不变）",
        "zh_TW": "模型來源（選取即儲存，其它參數不變）",
    },
    "ai_panel.source_tip": {
        "en_US": "Model source switched to {tier}; it takes effect on the next send.",
        "zh_CN": "已切换模型来源：{tier}，下次发送即生效。",
        "zh_TW": "已切換模型來源：{tier}，下次傳送即生效。",
    },
    "ai_panel.source_save_failed": {
        "en_US": ("Failed to save the model source — no writable config "
                  "directory. Please retry in Settings → AI."),
        "zh_CN": "模型来源保存失败：配置目录不可写，请在「设置 → AI」中重试。",
        "zh_TW": "模型來源儲存失敗：設定目錄不可寫入，請在「設定 → AI」中重試。",
    },
    "ai_panel.tier_unconfigured": {
        "en_US": "This source is not configured yet — click ⚙ to open Settings → AI",
        "zh_CN": "该档尚未配置 —— 点击 ⚙ 前往「设置 → AI」填写参数",
        "zh_TW": "此檔位尚未設定 —— 點擊 ⚙ 前往「設定 → AI」填寫參數",
    },
    "ai_panel.free_endpoint_hint": {
        "en_US": ("Heads-up: the current cloud endpoint is the built-in free "
                  "service (anonymous quota, rate-limited) and no API key is "
                  "filled in — it returns HTTP 429 once the quota runs out. "
                  "Use a local model, or fill in your own API key in "
                  "Settings → AI."),
        "zh_CN": ("提示：当前云端地址是内置免费端点（匿名额度、有限流），且未填写 "
                  "API Key —— 额度用尽会返回 429。建议改用本地模型，或在"
                  "「设置 → AI」中填写自备 API Key。"),
        "zh_TW": ("提示：目前雲端位址是內建免費端點（匿名額度、有限流），且未填寫 "
                  "API Key —— 額度用盡會回傳 429。建議改用本地模型，或在"
                  "「設定 → AI」中填寫自備 API Key。"),
    },
    "ai_panel.err_rate_limit_cloud": {
        "en_US": ("Model call failed: the service is rate-limiting or the quota "
                  "is used up (HTTP 429). Check your quota/API key, or try "
                  "again later."),
        "zh_CN": ("模型调用失败：服务端限流或额度用尽（HTTP 429），"
                  "请检查额度/API Key，或稍后重试。"),
        "zh_TW": ("模型呼叫失敗：伺服端限流或額度用盡（HTTP 429），"
                  "請檢查額度/API Key，或稍後重試。"),
    },
    "ai_panel.err_rate_limit_local": {
        "en_US": ("Model call failed: the local model service is busy or "
                  "rate-limited. Try again later, or switch to a smaller model."),
        "zh_CN": "模型调用失败：本地模型服务繁忙或限流，请稍后重试或换用更小的模型。",
        "zh_TW": "模型呼叫失敗：本地模型服務繁忙或限流，請稍後重試或換用更小的模型。",
    },
    "ai_panel.err_rate_limit_free": {
        "en_US": ("Model call failed: the free remote model is rate-limited "
                  "(anonymous quota, about 2 requests per minute). Please wait, "
                  "or switch to a local model / use your own API key."),
        "zh_CN": ("模型调用失败：免费远程模型限流（匿名额度约 2 次/分钟），"
                  "请稍候重试，或改用本地模型/自备 API Key。"),
        "zh_TW": ("模型呼叫失敗：免費遠端模型限流（匿名額度約 2 次/分鐘），"
                  "請稍候重試，或改用本地模型/自備 API Key。"),
    },
    "ai_panel.err_auth": {
        "en_US": ("Model call failed: authentication failed (HTTP 401/403). "
                  "Check that your API key is valid and not expired."),
        "zh_CN": "模型调用失败：鉴权失败（HTTP 401/403），请检查 API Key 是否有效或已过期。",
        "zh_TW": "模型呼叫失敗：鑑權失敗（HTTP 401/403），請檢查 API Key 是否有效或已過期。",
    },
    "ai_panel.err_timeout": {
        "en_US": ("Timed out while contacting the model service (inference may "
                  "be slow). Retry, or switch to a faster model."),
        "zh_CN": "与模型服务的连接超时（模型推理可能较慢），请重试或改用更快的模型。",
        "zh_TW": "與模型服務的連線逾時（模型推理可能較慢），請重試或改用更快的模型。",
    },
    "ai_panel.err_network": {
        "en_US": ("The connection to the model service was interrupted (the "
                  "result may be partial). Check the service address and your "
                  "network, then retry."),
        "zh_CN": "与模型服务的连接中断（可能仅生成了部分结果），请检查服务地址与网络后重试。",
        "zh_TW": "與模型服務的連線中斷（可能僅產生部分結果），請檢查服務位址與網路後重試。",
    },
    "ai_panel.err_vision": {
        "en_US": "This model does not support image input.",
        "zh_CN": "该模型不支持图像输入。",
        "zh_TW": "此模型不支援圖像輸入。",
    },
    "ai_panel.err_provider": {
        "en_US": "Model call failed: {detail}",
        "zh_CN": "模型调用失败：{detail}",
        "zh_TW": "模型呼叫失敗：{detail}",
    },
    "ai_panel.err_no_detail": {
        "en_US": "no valid response received",
        "zh_CN": "未获取到有效响应",
        "zh_TW": "未取得有效回應",
    },
    "ai_panel.err_unknown": {
        "en_US": "This interpretation could not be completed.",
        "zh_CN": "本次释读未能完成。",
        "zh_TW": "本次釋讀未能完成。",
    },
    "ai_panel.err_detail": {
        "en_US": "Reason: {detail}",
        "zh_CN": "原因：{detail}",
        "zh_TW": "原因：{detail}",
    },
    "ai_panel.advice_local": {
        "en_US": ("Tip: check that local Ollama is running with the model "
                  "ready, or click “Switch to remote model” to use a cloud API."),
        "zh_CN": ("建议：检查本地 Ollama 是否已启动且模型已就绪，"
                  "或点击「切换远程模型」改用云端 API 重试。"),
        "zh_TW": ("建議：檢查本地 Ollama 是否已啟動且模型已就緒，"
                  "或點擊「切換遠端模型」改用雲端 API 重試。"),
    },
    "ai_panel.advice_cloud": {
        "en_US": ("Tip: check the service address, model name and API "
                  "key/quota in Settings → AI, then retry. You can also switch "
                  "to another remote service."),
        "zh_CN": ("建议：核对「设置 → AI」中的服务地址、模型名与 API Key/账户额度"
                  "后重试；也可改用其它远程服务。"),
        "zh_TW": ("建議：核對「設定 → AI」中的服務位址、模型名稱與 API Key/帳戶額度"
                  "後重試；也可改用其它遠端服務。"),
    },
    # --- T-1022：模型选择器 / 视觉门禁 / 硬件探测（全部为追加键，不改既有键）---
    "ai_panel.pick_model_tip": {
        "en_US": "Choose a model (size, vision support and status shown per row)",
        "zh_CN": "选择模型（每行显示体积、视觉支持与状态）",
        "zh_TW": "選擇模型（每列顯示體積、視覺支援與狀態）",
    },
    "ai_panel.sec_builtin": {
        "en_US": "Built-in models",
        "zh_CN": "内置模型",
        "zh_TW": "內建模型",
    },
    "ai_panel.sec_self_hosted": {
        "en_US": "My local service",
        "zh_CN": "本地部署的模型",
        "zh_TW": "本地部署的模型",
    },
    "ai_panel.sec_cloud": {
        "en_US": "Cloud providers",
        "zh_CN": "云端服务商",
        "zh_TW": "雲端服務商",
    },
    "ai_panel.tag_vision": {
        "en_US": "Vision",
        "zh_CN": "视觉",
        "zh_TW": "視覺",
    },
    "ai_panel.tag_text_only": {
        "en_US": "No image support",
        "zh_CN": "不支持图片",
        "zh_TW": "不支援圖片",
    },
    "ai_panel.tag_vision_unverified": {
        "en_US": "Vision unverified",
        "zh_CN": "视觉能力未验证",
        "zh_TW": "視覺能力未驗證",
    },
    "ai_panel.state_downloaded": {
        "en_US": "Downloaded",
        "zh_CN": "已下载",
        "zh_TW": "已下載",
    },
    "ai_panel.state_not_downloaded": {
        "en_US": "Not downloaded",
        "zh_CN": "未下载",
        "zh_TW": "未下載",
    },
    "ai_panel.state_recommended": {
        "en_US": "Recommended for this Mac",
        "zh_CN": "本机推荐",
        "zh_TW": "本機推薦",
    },
    "ai_panel.state_low_ram": {
        "en_US": "Not enough memory (may still work)",
        "zh_CN": "内存不足（仍可试用）",
        "zh_TW": "記憶體不足（仍可試用）",
    },
    "ai_panel.state_low_disk": {
        "en_US": "Not enough disk space",
        "zh_CN": "磁盘不足",
        "zh_TW": "磁碟不足",
    },
    "ai_panel.download": {
        "en_US": "Download",
        "zh_CN": "下载",
        "zh_TW": "下載",
    },
    "ai_panel.hw_line": {
        "en_US": "This Mac: {spec}",
        "zh_CN": "本机：{spec}",
        "zh_TW": "本機：{spec}",
    },
    "ai_panel.hw_unknown": {
        "en_US": "Hardware details unavailable",
        "zh_CN": "硬件信息不可用",
        "zh_TW": "硬體資訊不可用",
    },
    "ai_panel.prefer_remote": {
        "en_US": "A ready-to-use service was found at {url} — use it first, no download needed",
        "zh_CN": "检测到现成服务 {url} —— 可直接使用，无需下载",
        "zh_TW": "偵測到現成服務 {url} —— 可直接使用，無需下載",
    },
    "ai_panel.key_set": {
        "en_US": "Key set",
        "zh_CN": "Key 已填",
        "zh_TW": "Key 已填",
    },
    "ai_panel.key_unset": {
        "en_US": "Key not set",
        "zh_CN": "Key 未填",
        "zh_TW": "Key 未填",
    },
    "ai_panel.vision_blocked": {
        "en_US": ("This model cannot read images. Please choose a model tagged "
                  "“Vision” in the model list, or do text-only analysis."),
        "zh_CN": ("该模型不支持图片，请更换为模型列表中带「视觉」标签的模型"
                  "（也可仅做文字分析）。"),
        "zh_TW": ("此模型不支援圖片，請更換為模型列表中帶「視覺」標籤的模型"
                  "（也可僅做文字分析）。"),
    },
    "ai_panel.vision_unverified_notice": {
        "en_US": ("This model's image support has not been verified and the "
                  "image call failed; the answer below uses the numeric "
                  "context only. Pick a model tagged “Vision” for image reading."),
        "zh_CN": ("该模型的视觉能力未经验证，带图调用未成功；下方改用「数值上下文」"
                  "作答。若需读图，请在模型列表中选择带「视觉」标签的模型。"),
        "zh_TW": ("此模型的視覺能力未經驗證，帶圖呼叫未成功；下方改用「數值上下文」"
                  "作答。若需讀圖，請在模型列表中選擇帶「視覺」標籤的模型。"),
    },
    "ai_panel.empty_reason": {
        "en_US": ("No vision model is ready for image reading yet.\n"
                  "Current: {current}\nRecommended for this Mac: {reco}"),
        "zh_CN": ("尚无可用于释图的视觉模型。\n"
                  "当前：{current}\n本机推荐：{reco}"),
        "zh_TW": ("尚無可用於釋圖的視覺模型。\n"
                  "目前：{current}\n本機推薦：{reco}"),
    },
    "ai_panel.empty_no_model": {
        "en_US": "no model configured",
        "zh_CN": "未配置模型",
        "zh_TW": "未設定模型",
    },
    "ai_panel.empty_no_reco": {
        "en_US": "see the model list in Settings → AI",
        "zh_CN": "请见「设置 → AI」的模型列表",
        "zh_TW": "請見「設定 → AI」的模型列表",
    },
    "ai_panel.goto_settings_ai": {
        "en_US": "Pick one in Settings → AI",
        "zh_CN": "去 设置→AI 挑选",
        "zh_TW": "去 設定→AI 挑選",
    },
    "ai_panel.self_unconfigured": {
        "en_US": "No local service configured — set the address and model in Settings → AI",
        "zh_CN": "尚未配置本地服务 —— 请在「设置 → AI」填写服务地址与模型名",
        "zh_TW": "尚未設定本地服務 —— 請在「設定 → AI」填寫服務位址與模型名稱",
    },
    "ai_panel.cloud_unconfigured": {
        "en_US": "No cloud provider configured — fill in the key and model in Settings → AI",
        "zh_CN": "尚未配置云端服务商 —— 请在「设置 → AI」填写密钥与模型名",
        "zh_TW": "尚未設定雲端服務商 —— 請在「設定 → AI」填寫金鑰與模型名稱",
    },
    "ai_panel.download_started": {
        "en_US": "Downloading {model}…",
        "zh_CN": "正在下载 {model}…",
        "zh_TW": "正在下載 {model}…",
    },
    "ai_panel.download_done": {
        "en_US": "{model} is ready.",
        "zh_CN": "{model} 已就绪。",
        "zh_TW": "{model} 已就緒。",
    },
    "ai_panel.download_failed": {
        "en_US": "The model could not be downloaded. Please check your network and retry.",
        "zh_CN": "模型下载失败，请检查网络后重试。",
        "zh_TW": "模型下載失敗，請檢查網路後重試。",
    },
    "ai_panel.download_cancelled": {
        "en_US": "Download cancelled.",
        "zh_CN": "已取消下载。",
        "zh_TW": "已取消下載。",
    },
    "ai_panel.download_busy": {
        "en_US": "A download is already in progress.",
        "zh_CN": "已有下载任务正在进行。",
        "zh_TW": "已有下載任務正在進行。",
    },
    # --- T-1022：设置 → AI 的探测结论与推荐下载项 ---
    "settings.ai_probe_line": {
        "en_US": "This Mac: {spec} — models below are ordered by fit",
        "zh_CN": "本机：{spec} —— 下方模型按匹配度排序",
        "zh_TW": "本機：{spec} —— 下方模型按匹配度排序",
    },
    "settings.ai_models_title": {
        "en_US": "Recommended vision models (image reading)",
        "zh_CN": "推荐视觉模型（可读图）",
        "zh_TW": "推薦視覺模型（可讀圖）",
    },
    "settings.ai_download": {
        "en_US": "Download",
        "zh_CN": "下载",
        "zh_TW": "下載",
    },
    "settings.ai_delete": {
        "en_US": "Delete model files",
        "zh_CN": "删除模型文件",
        "zh_TW": "刪除模型檔案",
    },
    "settings.ai_delete_done": {
        "en_US": "Model files deleted.",
        "zh_CN": "已删除模型文件。",
        "zh_TW": "已刪除模型檔案。",
    },
    "settings.ai_delete_failed": {
        "en_US": "Nothing was deleted (no local files or the service is not running).",
        "zh_CN": "未删除任何文件（本地无该模型或服务未运行）。",
        "zh_TW": "未刪除任何檔案（本地無此模型或服務未執行）。",
    },
    "settings.ai_fit_recommended": {
        "en_US": "Recommended",
        "zh_CN": "本机推荐",
        "zh_TW": "本機推薦",
    },
    "settings.ai_fit_ok": {
        "en_US": "Compatible",
        "zh_CN": "可用",
        "zh_TW": "可用",
    },
    "settings.ai_fit_low_ram": {
        "en_US": "Memory may be insufficient",
        "zh_CN": "内存可能不足",
        "zh_TW": "記憶體可能不足",
    },
    "settings.ai_fit_low_disk": {
        "en_US": "Disk space insufficient",
        "zh_CN": "磁盘空间不足",
        "zh_TW": "磁碟空間不足",
    },
    "settings.ai_no_text_only": {
        "en_US": "Text-only models are not listed (they cannot read images).",
        "zh_CN": "纯文本模型不在列表中（无法读图）。",
        "zh_TW": "純文字模型不在清單中（無法讀圖）。",
    },
    # --- T-921：设置 → 通用 · A4 参考频率 ---
    "settings.reference_hz": {
        "en_US": "A4 reference (Hz)",
        "zh_CN": "A4 参考频率（Hz）",
        "zh_TW": "A4 參考頻率（Hz）",
    },
    "settings.reference_hz_hint": {
        "en_US": "Affects cents and note-name display only; f0 analysis results are unchanged.",
        "zh_CN": "仅影响音分与音名显示，不改变原始 f0 分析结果。",
        "zh_TW": "僅影響音分與音名顯示，不改變原始 f0 分析結果。",
    },
    "settings.reference_hz_restore": {
        "en_US": "Restore 440",
        "zh_CN": "恢复 440",
        "zh_TW": "還原 440",
    },
    # --- T-922：音律标尺叠加层（分析菜单开关 + 音律模板子菜单） ---
    "action.tuning_ruler": {
        "en_US": "Tuning Ruler Overlay",
        "zh_CN": "音律标尺叠加层",
        "zh_TW": "音律標尺疊加層",
    },
    "menu.tuning_template": {
        "en_US": "Tuning Template",
        "zh_CN": "音律模板",
        "zh_TW": "音律模板",
    },
    "tuning.none": {
        "en_US": "Do not show",
        "zh_CN": "不显示",
        "zh_TW": "不顯示",
    },
    # --- T-928：非模态任务进度中心（状态栏 toggle + 非模态面板；进度中心状态文案） ---
    "task_center.toggle": {
        "en_US": "Tasks",
        "zh_CN": "任务中心",
        "zh_TW": "任務中心",
    },
    "task_center.title": {
        "en_US": "Task Center",
        "zh_CN": "任务进度中心",
        "zh_TW": "任務進度中心",
    },
    "task_center.empty": {
        "en_US": "No active tasks",
        "zh_CN": "无进行中任务",
        "zh_TW": "無進行中任務",
    },
    "task_center.empty_hint": {
        "en_US": "Analyses, model downloads and batch runs show their progress here.",
        "zh_CN": "分析、模型下载与批处理任务会在此显示进度。",
        "zh_TW": "分析、模型下載與批次處理任務會在此顯示進度。",
    },
    "task_center.group.running": {
        "en_US": "Running",
        "zh_CN": "进行中",
        "zh_TW": "進行中",
    },
    "task_center.group.queued": {
        "en_US": "Queued",
        "zh_CN": "排队",
        "zh_TW": "排隊",
    },
    "task_center.group.history": {
        "en_US": "Recent results",
        "zh_CN": "完成历史",
        "zh_TW": "完成歷史",
    },
    "task_center.state.queued": {
        "en_US": "Queued",
        "zh_CN": "排队中",
        "zh_TW": "排隊中",
    },
    "task_center.state.running": {
        "en_US": "Running",
        "zh_CN": "进行中",
        "zh_TW": "進行中",
    },
    "task_center.state.done": {
        "en_US": "Done",
        "zh_CN": "完成",
        "zh_TW": "完成",
    },
    "task_center.state.failed": {
        "en_US": "Failed",
        "zh_CN": "失败",
        "zh_TW": "失敗",
    },
    "task_center.state.cancelled": {
        "en_US": "Cancelled",
        "zh_CN": "已取消",
        "zh_TW": "已取消",
    },
    "task_center.cancel": {
        "en_US": "Cancel",
        "zh_CN": "取消",
        "zh_TW": "取消",
    },
    "task_center.cancelling": {
        "en_US": "Cancelling…",
        "zh_CN": "取消中…",
        "zh_TW": "取消中…",
    },
    "task_center.collapse": {
        "en_US": "Collapse",
        "zh_CN": "折叠",
        "zh_TW": "折疊",
    },
    "task_center.expand": {
        "en_US": "Expand",
        "zh_CN": "展开",
        "zh_TW": "展開",
    },
    "task_center.clear_history": {
        "en_US": "Clear history",
        "zh_CN": "清空历史",
        "zh_TW": "清空歷史",
    },
    "task_center.elapsed": {
        "en_US": "Elapsed",
        "zh_CN": "耗时",
        "zh_TW": "耗時",
    },
    "task_center.queue_full": {
        "en_US": "Task queue is full (limit {n}); wait for the running task to finish.",
        "zh_CN": "任务队列已满（上限 {n}），请等待当前任务完成。",
        "zh_TW": "任務佇列已滿（上限 {n}），請等待目前任務完成。",
    },
    "task_center.no_runner": {
        "en_US": "Task runner missing",
        "zh_CN": "任务执行体缺失",
        "zh_TW": "任務執行體缺失",
    },
    "task_center.title.download": {
        "en_US": "{name} model download",
        "zh_CN": "{name} 模型下载",
        "zh_TW": "{name} 模型下載",
    },
    "task_center.title.batch": {
        "en_US": "Batch run ({n} files)",
        "zh_CN": "批处理（{n} 个文件）",
        "zh_TW": "批次處理（{n} 個檔案）",
    },
    "task_center.title.multitrack": {
        "en_US": "Pitch analysis of {n} track(s)",
        "zh_CN": "{n} 轨音高分析", "zh_TW": "{n} 軌音高分析",
    },
    # T-1087 M6：开头对齐经任务中心后台化（逐轨取数 + 帧能量循环不再堵主线程）
    "task_center.title.multitrack_align": {
        "en_US": "Auto-align {n} track(s)",
        "zh_CN": "{n} 轨开头对齐", "zh_TW": "{n} 軌開頭對齊",
    },
    # T-1087 M7：差异量化经任务中心后台化（逐轨全样本帧循环 / 律制推送不再阻塞）
    "task_center.title.multitrack_diff": {
        "en_US": "Track difference quantification ({n} track(s))",
        "zh_CN": "{n} 轨差异量化", "zh_TW": "{n} 軌差異量化",
    },
    # T-1087 M5：加轨粗包络（每轨整文件块式读）经任务中心后台化
    "task_center.title.multitrack_add": {
        "en_US": "Loading {n} new track(s)",
        "zh_CN": "载入 {n} 条新轨", "zh_TW": "載入 {n} 條新軌",
    },
    "task_center.download_progress": {
        "en_US": "{name} model download {pct}%",
        "zh_CN": "{name} 模型下载 {pct}%",
        "zh_TW": "{name} 模型下載 {pct}%",
    },
    "task_center.submitted": {
        "en_US": "Added to task center: {title}",
        "zh_CN": "已加入任务中心：{title}",
        "zh_TW": "已加入任務中心：{title}",
    },
    "memguard.prompt_title": {
        "en_US": "Low memory ({mb} MB)",
        "zh_CN": "内存不足（{mb} MB）",
        "zh_TW": "記憶體不足（{mb} MB）",
    },
    "memguard.low": {
        "en_US": "Only {mb} MB memory available (below {threshold} MB). Close analysis views or reduce the batch job count.",
        "zh_CN": "可用内存不足 {mb} MB（低于阈值 {threshold} MB），建议关闭分析视图 / 减少批处理任务数。",
        "zh_TW": "可用記憶體不足 {mb} MB（低於閾值 {threshold} MB），建議關閉分析視圖 / 減少批次處理任務數。",
    },
    "memguard.continue": {
        "en_US": "The task will still run (at your own risk); you can cancel it in the task center.",
        "zh_CN": "任务仍将继续执行（风险自担），可在任务中心取消。",
        "zh_TW": "任務仍將繼續執行（風險自擔），可在任務中心取消。",
    },
    "memguard.pressure_warning": {
        "en_US": "Memory is critically low. Please save your work and consider restarting the app.",
        "zh_CN": "内存偏低，请保存并考虑重启应用。",
        "zh_TW": "記憶體偏低，請儲存並考慮重新啟動應用程式。",
    },
    # --- T-1047：参数控件规范（三段式名称/单位 · 读数 · 状态点 · chip 快捷基准）---
    # 新增键一律五语齐（en/简/繁/韩/日），禁硬编码中文
    "param.unit.hz": {
        "en_US": "Hz", "zh_CN": "Hz", "zh_TW": "Hz",
        "ko_KR": "Hz", "ja_JP": "Hz",
    },
    "param.unit.px": {
        "en_US": "px", "zh_CN": "px", "zh_TW": "px",
        "ko_KR": "px", "ja_JP": "px",
    },
    "param.unit.dpi": {
        "en_US": "dpi", "zh_CN": "dpi", "zh_TW": "dpi",
        "ko_KR": "dpi", "ja_JP": "dpi",
    },
    "param.unit.channels": {
        "en_US": "ch", "zh_CN": "声道", "zh_TW": "聲道",
        "ko_KR": "채널", "ja_JP": "ch",
    },
    "param.unit.bit": {
        "en_US": "bit", "zh_CN": "bit", "zh_TW": "bit",
        "ko_KR": "bit", "ja_JP": "bit",
    },
    "param.name.a4_preset": {
        "en_US": "Quick A4 presets", "zh_CN": "快捷基准",
        "zh_TW": "快捷基準", "ko_KR": "빠른 기준", "ja_JP": "クイック基準",
    },
    "param.readout.a4": {
        "en_US": "Current reference", "zh_CN": "当前基准",
        "zh_TW": "當前基準", "ko_KR": "현재 기준", "ja_JP": "現在の基準",
    },
    "param.name.font_size": {
        "en_US": "Interface font size", "zh_CN": "界面字体大小",
        "zh_TW": "介面字型大小", "ko_KR": "인터페이스 글꼴 크기",
        "ja_JP": "インターフェース文字サイズ",
    },
    "param.opt.font_small": {
        "en_US": "Small", "zh_CN": "小", "zh_TW": "小",
        "ko_KR": "작게", "ja_JP": "小",
    },
    "param.opt.font_default": {
        "en_US": "Default", "zh_CN": "默认", "zh_TW": "預設",
        "ko_KR": "기본", "ja_JP": "標準",
    },
    "param.opt.font_large": {
        "en_US": "Large", "zh_CN": "大", "zh_TW": "大",
        "ko_KR": "크게", "ja_JP": "大",
    },
    "param.opt.font_xlarge": {
        "en_US": "Extra large", "zh_CN": "特大", "zh_TW": "特大",
        "ko_KR": "아주 크게", "ja_JP": "特大",
    },
    "param.name.play_channels": {
        "en_US": "Playback channels", "zh_CN": "播放声道数",
        "zh_TW": "播放聲道數", "ko_KR": "재생 채널 수",
        "ja_JP": "再生チャンネル数",
    },
    "param.name.record_channels": {
        "en_US": "Recording channels", "zh_CN": "录音声道数",
        "zh_TW": "錄音聲道數", "ko_KR": "녹음 채널 수",
        "ja_JP": "録音チャンネル数",
    },
    "param.name.sample_rate": {
        "en_US": "Default sample rate", "zh_CN": "默认采样率",
        "zh_TW": "預設取樣率", "ko_KR": "기본 샘플 레이트",
        "ja_JP": "既定サンプルレート",
    },
    "param.name.sample_format": {
        "en_US": "Sample format", "zh_CN": "采样格式",
        "zh_TW": "取樣格式", "ko_KR": "샘플 형식",
        "ja_JP": "サンプル形式",
    },
    "param.audio.output_device": {
        "en_US": "Output device", "zh_CN": "输出设备",
        "zh_TW": "輸出裝置", "ko_KR": "출력 장치",
        "ja_JP": "出力デバイス",
    },
    "param.audio.input_device": {
        "en_US": "Input device", "zh_CN": "输入设备",
        "zh_TW": "輸入裝置", "ko_KR": "입력 장치",
        "ja_JP": "入力デバイス",
    },
    "param.audio.title": {
        "en_US": "Parameters", "zh_CN": "参数", "zh_TW": "參數",
        "ko_KR": "파라미터", "ja_JP": "パラメーター",
    },
    "param.audio.refresh": {
        "en_US": "Refresh device list", "zh_CN": "刷新设备列表",
        "zh_TW": "重新整理裝置清單", "ko_KR": "장치 목록 새로 고침",
        "ja_JP": "デバイス一覧を更新",
    },
    "param.opt.mono": {
        "en_US": "Mono", "zh_CN": "单声道", "zh_TW": "單聲道",
        "ko_KR": "모노", "ja_JP": "モノラル",
    },
    "param.opt.stereo": {
        "en_US": "Stereo", "zh_CN": "立体声", "zh_TW": "立體聲",
        "ko_KR": "스테레오", "ja_JP": "ステレオ",
    },
    "param.opt.recommended": {
        "en_US": "Recommended", "zh_CN": "推荐", "zh_TW": "推薦",
        "ko_KR": "권장", "ja_JP": "推奨",
    },
    "param.led.ready": {
        "en_US": "Ready", "zh_CN": "就绪", "zh_TW": "就緒",
        "ko_KR": "준비됨", "ja_JP": "準備完了",
    },
    "param.led.off": {
        "en_US": "Not available", "zh_CN": "不可用", "zh_TW": "不可用",
        "ko_KR": "사용 불가", "ja_JP": "利用不可",
    },
    # --- G-2b：设置/录音设置/房间声学/房间模态/图表字体五面汇点清零 ---
    # （43 键，三语齐、ko/ja 随批后补；「频谱图」settings.category_spectrogram
    #   与「语谱图」view.spectrogram 为两条既有文案，禁合并）
    # 通用：默认分析视图下拉（settings_dialog:603-611 / 1655-1657 复用）
    "settings.default_view": {
        "en_US": "Default analysis view:", "zh_CN": "默认分析视图：", "zh_TW": "預設分析檢視：",
    },
    "view.waveform": {
        "en_US": "Waveform", "zh_CN": "波形", "zh_TW": "波形",
    },
    "view.fft": {
        "en_US": "FFT Spectrum", "zh_CN": "FFT 频谱", "zh_TW": "FFT 頻譜",
    },
    "view.spectrogram": {
        "en_US": "Spectrogram", "zh_CN": "语谱图", "zh_TW": "語譜圖",
    },
    "view.pitch": {
        "en_US": "Pitch", "zh_CN": "音高", "zh_TW": "音高",
    },
    "view.formants": {
        "en_US": "Formants", "zh_CN": "共振峰", "zh_TW": "共振峰",
    },
    "view.timbre": {
        "en_US": "Timbre", "zh_CN": "音色", "zh_TW": "音色",
    },
    "view.spectrogram3d": {
        "en_US": "3D Spectrogram", "zh_CN": "3D 频谱图", "zh_TW": "3D 頻譜圖",
    },
    "view.ai_interpret": {
        "en_US": "AI Interpret", "zh_CN": "AI 释图", "zh_TW": "AI 釋圖",
    },
    # 通用：音频设备占位（复用 record.device_none / device_unavailable 之外的新键）
    "record.device_none_output": {
        "en_US": "(no output device)", "zh_CN": "（无输出设备）", "zh_TW": "（無輸出裝置）",
    },
    # 通用：快捷键分类下拉（1654「频谱图」≠ 607「语谱图」）
    "settings.category_filter": {
        "en_US": "Category:", "zh_CN": "分类：", "zh_TW": "分類：",
    },
    "settings.category_all": {
        "en_US": "All", "zh_CN": "全部", "zh_TW": "全部",
    },
    "settings.category_global": {
        "en_US": "General", "zh_CN": "通用", "zh_TW": "一般",
    },
    "settings.category_spectrogram": {
        "en_US": "Spectrogram", "zh_CN": "频谱图", "zh_TW": "頻譜圖",
    },
    # 录音设置面板
    "record_settings.title": {
        "en_US": "Recording Settings", "zh_CN": "录音设置", "zh_TW": "錄音設定",
    },
    "record_settings.output_location": {
        "en_US": "Output location", "zh_CN": "输出位置", "zh_TW": "輸出位置",
    },
    "record_settings.filename_placeholder": {
        "en_US": "File name (without extension)",
        "zh_CN": "文件名（不含扩展名）",
        "zh_TW": "檔案名稱（不含副檔名）",
    },
    "record_settings.compress_auto": {
        "en_US": "Compressed (auto quality)",
        "zh_CN": "压缩格式（自动质量）",
        "zh_TW": "壓縮格式（自動品質）",
    },
    "record_settings.autosave_path": {
        "en_US": "Auto-saved to after recording stops:\n{path}",
        "zh_CN": "停止录音后将自动保存到：\n{path}",
        "zh_TW": "停止錄音後將自動儲存至：\n{path}",
    },
    "record_settings.err_need_dir_and_name": {
        "en_US": "Please set both directory and file name.",
        "zh_CN": "请填写目录与文件名。",
        "zh_TW": "請填寫目錄與檔案名稱。",
    },
    "record_settings.err_need_name": {
        "en_US": "Please enter a file name.",
        "zh_CN": "请填写文件名。",
        "zh_TW": "請填寫檔案名稱。",
    },
    "record_settings.err_dir_missing": {
        "en_US": "Directory does not exist; please choose again.",
        "zh_CN": "目录不存在，请重新选择。",
        "zh_TW": "目錄不存在，請重新選擇。",
    },
    "record_settings.overwrite_title": {
        "en_US": "File already exists", "zh_CN": "文件已存在", "zh_TW": "檔案已存在",
    },
    "record_settings.overwrite_question": {
        "en_US": "{path}\nAlready exists. Overwrite?",
        "zh_CN": "{path}\n已存在，是否覆盖？",
        "zh_TW": "{path}\n已存在，是否覆寫？",
    },
    # 房间声学工具
    "room_acoustics.title": {
        "en_US": "Room Acoustics Tool", "zh_CN": "房间声学工具", "zh_TW": "房間聲學工具",
    },
    "room_acoustics.sweep_hint": {
        "en_US": "Generate a sweep, play and record the room response, then load the recording.",
        "zh_CN": "请先生成扫频信号，播放并录制房间响应，然后加载录制文件。",
        "zh_TW": "請先產生掃頻信號，播放並錄製房間響應，然後載入錄製檔案。",
    },
    "room_acoustics.method_label": {
        "en_US": "Method:", "zh_CN": "方法：", "zh_TW": "方法：",
    },
    "room_acoustics.rt60_hint": {
        "en_US": "Load an impulse response to compute RT60.",
        "zh_CN": "请加载冲激响应并计算 RT60。",
        "zh_TW": "請載入衝激響應並計算 RT60。",
    },
    # 房间模态分析（预设显示串保留尺寸；itemData 数值元组不动）
    "room_modes.length_lx": {
        "en_US": "Length Lx:", "zh_CN": "长度 Lx：", "zh_TW": "長度 Lx：",
    },
    "room_modes.width_ly": {
        "en_US": "Width Ly:", "zh_CN": "宽度 Ly：", "zh_TW": "寬度 Ly：",
    },
    "room_modes.height_lz": {
        "en_US": "Height Lz:", "zh_CN": "高度 Lz：", "zh_TW": "高度 Lz：",
    },
    "room_modes.max_order": {
        "en_US": "Max order:", "zh_CN": "最大阶数：", "zh_TW": "最大階數：",
    },
    "room_modes.max_freq": {
        "en_US": "Max frequency:", "zh_CN": "最高频率：", "zh_TW": "最高頻率：",
    },
    "room_modes.speed_of_sound": {
        "en_US": "Speed of sound:", "zh_CN": "声速：", "zh_TW": "聲速：",
    },
    "room_modes.modal_q": {
        "en_US": "Modal Q:", "zh_CN": "模态 Q 值：", "zh_TW": "模態 Q 值：",
    },
    "room_modes.preset_custom": {
        "en_US": "Custom", "zh_CN": "自定义", "zh_TW": "自訂",
    },
    "room_modes.preset_small_room": {
        "en_US": "Small listening room (4×3×2.5m)",
        "zh_CN": "小型听音室 (4×3×2.5m)",
        "zh_TW": "小型試聽室 (4×3×2.5m)",
    },
    "room_modes.preset_medium_studio": {
        "en_US": "Medium studio (6×4.5×3m)",
        "zh_CN": "中型录音室 (6×4.5×3m)",
        "zh_TW": "中型錄音室 (6×4.5×3m)",
    },
    "room_modes.preset_large_studio": {
        "en_US": "Large studio (10×8×4m)",
        "zh_CN": "大型演播室 (10×8×4m)",
        "zh_TW": "大型演播室 (10×8×4m)",
    },
    "room_modes.preset_living_room": {
        "en_US": "Living room (5×4×2.7m)",
        "zh_CN": "起居室 (5×4×2.7m)",
        "zh_TW": "客廳 (5×4×2.7m)",
    },
    "room_modes.preset_bedroom": {
        "en_US": "Bedroom (3.5×3×2.6m)",
        "zh_CN": "卧室 (3.5×3×2.6m)",
        "zh_TW": "臥室 (3.5×3×2.6m)",
    },
    "room_modes.preset_concert_hall": {
        "en_US": "Concert hall (30×20×12m)",
        "zh_CN": "音乐厅 (30×20×12m)",
        "zh_TW": "音樂廳 (30×20×12m)",
    },
    # 图表字体（预览样例，仅文案；预览控件逻辑不动）
    "chart_font.preview_sample": {
        "en_US": "Aa 440 Hz · Harmonics · Harmonic series · Spectrogram",
        "zh_CN": "Aa 440 Hz · Harmonics · 谐波列 · 语谱图",
        "zh_TW": "Aa 440 Hz · Harmonics · 諧波列 · 語譜圖",
    },
    # --- G-2c 笔 1：口径升级（括号配平）新捕获 26 处补漏 ---
    # main_window（状态栏 / 信息条 / toast）
    "main_window.info.summary": {
        "en_US": "{sample_rate} Hz · {channels} ch · {duration} · {format}",
        "zh_CN": "{sample_rate} Hz · {channels} 声道 · {duration} · {format}",
        "zh_TW": "{sample_rate} Hz · {channels} 聲道 · {duration} · {format}",
    },
    "main_window.realtime.title": {
        "en_US": "Waveform · Real-time features ({bpm}, onsets low {low}/mid {mid}/high {high})",
        "zh_CN": "波形 · 实时特征 ({bpm}, 起音 低 {low}/中 {mid}/高 {high})",
        "zh_TW": "波形 · 即時特徵 ({bpm}, 起音 低 {low}/中 {mid}/高 {high})",
    },
    "main_window.realtime.no_beat": {
        "en_US": "no stable beat",
        "zh_CN": "无稳定节拍",
        "zh_TW": "無穩定節拍",
    },
    "main_window.chart.region_avg": {
        "en_US": "Region average spectrum ({t0}–{t1}s, {fft_size}-point FFT)",
        "zh_CN": "区域平均谱 ({t0}–{t1}s, {fft_size} 点 FFT)",
        "zh_TW": "區域平均譜 ({t0}–{t1}s, {fft_size} 點 FFT)",
    },
    "main_window.chart.spectrogram_title": {
        "en_US": "Spectrogram ({n_fft}-point FFT, hop {hop} samples, {window} window)",
        "zh_CN": "语谱图 ({n_fft} 点 FFT, 帧移 {hop} 样点, {window}窗)",
        "zh_TW": "語譜圖 ({n_fft} 點 FFT, 幀移 {hop} 樣點, {window}窗)",
    },
    "main_window.chart.spectrum3d_title": {
        "en_US": "3D spectrum (segment {t0}–{t1} s, {mode})",
        "zh_CN": "3D 频谱图 (乐段 {t0}–{t1} s, {mode})",
        "zh_TW": "3D 頻譜圖 (樂段 {t0}–{t1} s, {mode})",
    },
    "main_window.status.formants_done": {
        "en_US": "Formant analysis complete ({frames} frames, {valid} valid formants)",
        "zh_CN": "共振峰分析完成 ({frames} 帧, {valid} 个有效共振峰)",
        "zh_TW": "共振峰分析完成 ({frames} 幀, {valid} 個有效共振峰)",
    },
    "main_window.status.timbre_done": {
        "en_US": "Timbre analysis complete ({frames} frames, mean HNR {hnr} dB)",
        "zh_CN": "音色分析完成 ({frames} 帧, HNR 均值 {hnr} dB)",
        "zh_TW": "音色分析完成 ({frames} 幀, HNR 均值 {hnr} dB)",
    },
    "main_window.toast.chart_font_updated": {
        "en_US": "Chart fonts updated: Latin {latin} / CJK {cjk}",
        "zh_CN": "图表字体已更新：西文 {latin} / 中文 {cjk}",
        "zh_TW": "圖表字體已更新：西文 {latin} / 中文 {cjk}",
    },
    "main_window.toast.font_auto": {
        "en_US": "Auto",
        "zh_CN": "自动",
        "zh_TW": "自動",
    },
    # 图表字体（G-2b 遗留的多行说明，G-2c 笔 1 补清）
    "chart_font.hint_scope": {
        "en_US": "Latin/numeric and CJK fonts are set separately and apply to "
                 "all exported charts and 3D views.\nWith \"Auto\", the recommended "
                 "font is chosen from the UI language.",
        "zh_CN": "西文/数字字体与中文字体分开设置，应用于全部导出图表与 3D 视图。\n"
                 "「自动」时按界面语言选择推荐字体。",
        "zh_TW": "西文/數字字體與中文字體分開設定，套用於全部匯出圖表與 3D 檢視。\n"
                 "「自動」時依介面語言選擇推薦字體。",
    },
    "chart_font.hint_academic": {
        "en_US": "Tip: academic charts commonly use Times New Roman (Latin) + "
                 "Songti/PingFang (CJK); settings persist across restarts.",
        "zh_CN": "提示：学术图表常用 Times New Roman（西文）+ 宋体/苹方（中文）；"
                 "设置会持久化，重启后保留。",
        "zh_TW": "提示：學術圖表常用 Times New Roman（西文）+ 宋體/蘋方（中文）；"
                 "設定會持久化，重啟後保留。",
    },
    # 文件信息条（信号特征）
    "metadata_bar.status.peak_rms": {
        "en_US": "Peak {peak} dBFS · RMS {rms} dBFS · Crest {crest} dB",
        "zh_CN": "峰值 {peak} dBFS · RMS {rms} dBFS · 波峰因数 {crest} dB",
        "zh_TW": "峰值 {peak} dBFS · RMS {rms} dBFS · 波峰因數 {crest} dB",
    },
    # 录音设置（有损格式说明）
    "record_settings.compress_lossy": {
        "en_US": "{fmt} is a lossy format, so no bit depth applies; "
                 "encoding uses the default quality.",
        "zh_CN": "{fmt} 为有损压缩格式，不设采样深度；以默认质量编码。",
        "zh_TW": "{fmt} 為有損壓縮格式，不設取樣深度；以預設品質編碼。",
    },
    # 房间声学（状态面板多行提示）
    "room_acoustics.status.sweep_saved": {
        "en_US": "Sweep signal generated and saved: {filepath}\n"
                 "Play this signal in the room under test and record the response.",
        "zh_CN": "扫频信号已生成并保存：{filepath}\n请在被测房间中播放此信号并录制响应。",
        "zh_TW": "掃頻訊號已產生並儲存：{filepath}\n請在被測房間中播放此訊號並錄製響應。",
    },
    "room_acoustics.status.rec_loaded": {
        "en_US": "Recording loaded: {path}\n"
                 "Duration: {duration} s, sample rate: {sample_rate} Hz\n"
                 "Click \"Compute impulse response\" to start the analysis.",
        "zh_CN": "已加载录制文件：{path}\n时长：{duration} s，采样率：{sample_rate} Hz\n"
                 "点击「计算冲激响应」开始分析。",
        "zh_TW": "已載入錄製檔案：{path}\n時長：{duration} s，取樣率：{sample_rate} Hz\n"
                 "點擊「計算衝擊響應」開始分析。",
    },
    "room_acoustics.status.ir_done": {
        "en_US": "Impulse response computed.\n"
                 "IR length: {length} s\nPeak position: {peak} ms\n\n"
                 "Switch to the \"RT60 analysis\" tab for reverberation time analysis.",
        "zh_CN": "冲激响应计算完成！\nIR 长度：{length} s\n峰值位置：{peak} ms\n\n"
                 "切换到「RT60 分析」选项卡进行混响时间分析。",
        "zh_TW": "衝擊響應計算完成！\nIR 長度：{length} s\n峰值位置：{peak} ms\n\n"
                 "切換到「RT60 分析」索引標籤進行殘響時間分析。",
    },
    "room_acoustics.status.ir_loaded": {
        "en_US": "IR loaded: {length} s, {sample_rate} Hz\n"
                 "Click \"Compute RT60\" to analyse.",
        "zh_CN": "已加载 IR：{length} s，{sample_rate} Hz\n点击「计算 RT60」进行分析。",
        "zh_TW": "已載入 IR：{length} s，{sample_rate} Hz\n點擊「計算 RT60」進行分析。",
    },
    "room_acoustics.status.rt60_result": {
        "en_US": "RT60 ({method}) = {rt60} s\nDecay slope: {slope} dB/s\n"
                 "Fit range: {db_start} ~ {db_end} dB",
        "zh_CN": "RT60 ({method}) = {rt60} 秒\n衰减斜率：{slope} dB/s\n"
                 "拟合区间：{db_start} ~ {db_end} dB",
        "zh_TW": "RT60 ({method}) = {rt60} 秒\n衰減斜率：{slope} dB/s\n"
                 "擬合區間：{db_start} ~ {db_end} dB",
    },
    "room_acoustics.status.rt60_failed": {
        "en_US": "RT60 computation failed: not enough data points in the "
                 "{method} range.\nCheck that the impulse response is valid.",
        "zh_CN": "RT60 计算失败：无法在 {method} 区间找到足够数据点。\n"
                 "请检查冲激响应是否有效。",
        "zh_TW": "RT60 計算失敗：無法在 {method} 區間找到足夠資料點。\n"
                 "請檢查衝擊響應是否有效。",
    },
    # 设置（快捷键表说明）
    "settings_dialog.shortcut_hint": {
        "en_US": "Double-click the \"Shortcut\" column to change a key. "
                 "Press Esc to cancel, Enter to confirm.",
        "zh_CN": "双击「快捷键」列可修改按键。按 Esc 取消，按 Enter 确认。",
        "zh_TW": "雙擊「快速鍵」欄可修改按鍵。按 Esc 取消，按 Enter 確認。",
    },
    # 语谱图（游标读数）
    "spectrogram.cursor_readout": {
        "en_US": "Time: {time} s | Freq: {freq} | Level: {db} dB",
        "zh_CN": "时间: {time} s | 频率: {freq} | 强度: {db} dB",
        "zh_TW": "時間: {time} s | 頻率: {freq} | 強度: {db} dB",
    },
    # 3D 频谱图（字体按钮提示）
    "spectrogram3d.font_tooltip": {
        "en_US": "Set the Latin/CJK fonts for 3D charts (shared with exported "
                 "charts; applies to exported images too)",
        "zh_CN": "设置 3D 图表的西文/中文字体（与导出图表共用，导出图片同样生效）",
        "zh_TW": "設定 3D 圖表的西文/中文字體（與匯出圖表共用，匯出圖片同樣生效）",
    },
    # 频谱（Y 轴跟随提示 / 标记操作说明）
    "spectrum.y_follow_tooltip": {
        "en_US": "Y axis follows visible data automatically (default)\n"
                 "Shift+wheel zoom locks Y manually\n"
                 "Click this button to return to auto",
        "zh_CN": "Y 轴自动跟随可见数据（默认）\n"
                 "Shift+滚轮手动缩放 Y 后自动锁定\n点击此按钮恢复自动",
        "zh_TW": "Y 軸自動跟隨可見資料（預設）\n"
                 "Shift+滾輪手動縮放 Y 後自動鎖定\n點擊此按鈕恢復自動",
    },
    "spectrum.peak_mark_hint": {
        "en_US": "Click a peak: toggle mark · Right-click: menu · Drag: pan · "
                 "Wheel: zoom frequency axis · Shift+wheel: zoom amplitude axis · "
                 "Double-click: reset · Delete: remove selected mark",
        "zh_CN": "单击峰：添加/取消标记 · 右键：菜单 · 拖动：平移 · 滚轮：缩放频率轴 · "
                 "Shift+滚轮：缩放幅度轴 · 双击：重置 · Delete：删除选中标记",
        "zh_TW": "單擊峰：新增/取消標記 · 右鍵：選單 · 拖曳：平移 · 滾輪：縮放頻率軸 · "
                 "Shift+滾輪：縮放幅度軸 · 雙擊：重設 · Delete：刪除選取標記",
    },
    # 音色（MFCC 概要）
    "timbre.status.mfcc_summary": {
        "en_US": "{order}-order MFCC · {frames} frames · mean HNR {hnr} dB",
        "zh_CN": "{order} 阶 MFCC · {frames} 帧 · HNR 均值 {hnr} dB",
        "zh_TW": "{order} 階 MFCC · {frames} 幀 · HNR 均值 {hnr} dB",
    },
    # --- G-2c 笔 2：新口径守护下余 86 处大清零 ---
    # 频谱（工具栏标签 / 提示 / 读数；38 处 → 34 键，同串复用 4 组）
    "spectrum.title": {
        "en_US": "Spectrum",
        "zh_CN": "频谱",
        "zh_TW": "頻譜",
    },
    "spectrum.single_tone_none": {
        "en_US": "Single note: --",
        "zh_CN": "单音: --",
        "zh_TW": "單音: --",
    },
    "spectrum.single_tone": {
        "en_US": "Single note: {name}",
        "zh_CN": "单音: {name}",
        "zh_TW": "單音: {name}",
    },
    "spectrum.chord": {
        "en_US": "Chord: {name} ({conf}%)",
        "zh_CN": "和弦: {name} ({conf}%)",
        "zh_TW": "和弦: {name} ({conf}%)",
    },
    "spectrum.notes_count": {
        "en_US": "{n} notes",
        "zh_CN": "{n} 个音",
        "zh_TW": "{n} 個音",
    },
    "spectrum.marks_notes": {
        "en_US": "Marks: {n} notes",
        "zh_CN": "标记: {n} 个音",
        "zh_TW": "標記: {n} 個音",
    },
    "spectrum.axis_x": {
        "en_US": "X axis:",
        "zh_CN": "X轴:",
        "zh_TW": "X 軸:",
    },
    "spectrum.axis_y": {
        "en_US": "Y axis:",
        "zh_CN": "Y轴:",
        "zh_TW": "Y 軸:",
    },
    "spectrum.window": {
        "en_US": "Window:",
        "zh_CN": "窗:",
        "zh_TW": "窗:",
    },
    "spectrum.range": {
        "en_US": "Range:",
        "zh_CN": "范围:",
        "zh_TW": "範圍:",
    },
    "spectrum.harmonic_marks": {
        "en_US": "Harmonic marks ({n})",
        "zh_CN": "谐波标记 ({n})",
        "zh_TW": "諧波標記 ({n})",
    },
    "spectrum.resolution_info": {
        "en_US": "Resolution: {res} Hz | Zero-padded FFT: {n} points",
        "zh_CN": "分辨率: {res} Hz | 补零后 FFT: {n} 点",
        "zh_TW": "解析度: {res} Hz | 補零後 FFT: {n} 點",
    },
    "spectrum.y_locked": {
        "en_US": "Y locked",
        "zh_CN": "Y锁定",
        "zh_TW": "Y 鎖定",
    },
    "spectrum.y_auto": {
        "en_US": "Y auto",
        "zh_CN": "Y自动",
        "zh_TW": "Y 自動",
    },
    "spectrum.freq_none": {
        "en_US": "Freq: -- Hz",
        "zh_CN": "频率: -- Hz",
        "zh_TW": "頻率: -- Hz",
    },
    "spectrum.amp_none": {
        "en_US": "Amp: --",
        "zh_CN": "幅度: --",
        "zh_TW": "幅度: --",
    },
    "spectrum.note_none": {
        "en_US": "Note: --",
        "zh_CN": "音符: --",
        "zh_TW": "音符: --",
    },
    "spectrum.freq_unit": {
        "en_US": "Freq: {value} {unit}",
        "zh_CN": "频率: {value} {unit}",
        "zh_TW": "頻率: {value} {unit}",
    },
    "spectrum.freq_hz": {
        "en_US": "Freq: {value} Hz",
        "zh_CN": "频率: {value} Hz",
        "zh_TW": "頻率: {value} Hz",
    },
    "spectrum.freq_value": {
        "en_US": "Freq: {value}",
        "zh_CN": "频率: {value}",
        "zh_TW": "頻率: {value}",
    },
    "spectrum.cents": {
        "en_US": "Cents: {value} cents",
        "zh_CN": "音分: {value} cents",
        "zh_TW": "音分: {value} cents",
    },
    "spectrum.amp_unit": {
        "en_US": "Amp: {value} {unit}",
        "zh_CN": "幅度: {value} {unit}",
        "zh_TW": "幅度: {value} {unit}",
    },
    "spectrum.amp_pct": {
        "en_US": "Amp: {value}%",
        "zh_CN": "幅度: {value}%",
        "zh_TW": "幅度: {value}%",
    },
    "spectrum.amp_value": {
        "en_US": "Amp: {value}",
        "zh_CN": "幅度: {value}",
        "zh_TW": "幅度: {value}",
    },
    "spectrum.note_cents": {
        "en_US": "Note: {name} ({cents} cents)",
        "zh_CN": "音符: {name} ({cents} 音分)",
        "zh_TW": "音符: {name} ({cents} 音分)",
    },
    "spectrum.tip_peak_detect": {
        "en_US": "Detect spectral peaks and list their frequency and amplitude",
        "zh_CN": "自动检测频谱峰值并列出频率和幅度",
        "zh_TW": "自動偵測頻譜峰值並列出頻率與幅度",
    },
    "spectrum.tip_toggle_marks": {
        "en_US": "Expand/collapse the peak marker panel",
        "zh_CN": "展开/收起峰值标记面板",
        "zh_TW": "展開/收合峰值標記面板",
    },
    "spectrum.tip_peak_hold": {
        "en_US": "Peak hold",
        "zh_CN": "峰值保持 (Peak Hold)",
        "zh_TW": "峰值保持 (Peak Hold)",
    },
    "spectrum.tip_auto_mark": {
        "en_US": "Auto-mark the 6 strongest partials "
                 "(amplitude ≥ 0.1% of the strongest peak)",
        "zh_CN": "自动标记最强的前 6 个分音（幅度 ≥ 最大峰的 0.1%）",
        "zh_TW": "自動標記最強的前 6 個分音（幅度 ≥ 最大峰的 0.1%）",
    },
    "spectrum.tip_clear_marks": {
        "en_US": "Clear all harmonic marks",
        "zh_CN": "清除全部谐波标记",
        "zh_TW": "清除全部諧波標記",
    },
    "spectrum.tip_copy_table": {
        "en_US": "Copy the marker table (tab-separated; paste into Excel)",
        "zh_CN": "复制标记数值表（制表符分隔，可粘贴到 Excel）",
        "zh_TW": "複製標記數值表（定位字元分隔，可貼上到 Excel）",
    },
    "spectrum.tip_zoom_in": {
        "en_US": "Zoom in (Ctrl+=)",
        "zh_CN": "放大 (Ctrl+=)",
        "zh_TW": "放大 (Ctrl+=)",
    },
    "spectrum.tip_zoom_out": {
        "en_US": "Zoom out (Ctrl+-)",
        "zh_CN": "缩小 (Ctrl+-)",
        "zh_TW": "縮小 (Ctrl+-)",
    },
    "spectrum.tip_fit": {
        "en_US": "Fit to window / reset zoom (Ctrl+0 or double-click)",
        "zh_CN": "适应窗口 / 重置缩放 (Ctrl+0 或双击)",
        "zh_TW": "適應視窗 / 重設縮放 (Ctrl+0 或雙擊)",
    },
    # 播放条（12 处 → 11 键，录音提示复用）
    "transport.tip_rewind": {
        "en_US": "Go to start (Home)",
        "zh_CN": "跳到开头 (Home)",
        "zh_TW": "跳到開頭 (Home)",
    },
    "transport.tip_play": {
        "en_US": "Play / Pause (Space)",
        "zh_CN": "播放 / 暂停 (Space)",
        "zh_TW": "播放 / 暫停 (Space)",
    },
    "transport.tip_stop": {
        "en_US": "Stop (Esc)",
        "zh_CN": "停止 (Esc)",
        "zh_TW": "停止 (Esc)",
    },
    "transport.tip_end": {
        "en_US": "Go to end (End)",
        "zh_CN": "跳到结尾 (End)",
        "zh_TW": "跳到結尾 (End)",
    },
    "transport.tip_record": {
        "en_US": "Record (R)",
        "zh_CN": "录音 (R)",
        "zh_TW": "錄音 (R)",
    },
    "transport.tip_stop_record": {
        "en_US": "Stop recording (R)",
        "zh_CN": "停止录音 (R)",
        "zh_TW": "停止錄音 (R)",
    },
    "transport.tip_input_device": {
        "en_US": "Select the recording input device",
        "zh_CN": "选择录音输入设备",
        "zh_TW": "選擇錄音輸入裝置",
    },
    "transport.tip_sample_rate": {
        "en_US": "Recording sample rate",
        "zh_CN": "录音采样率",
        "zh_TW": "錄音取樣率",
    },
    "transport.tip_loop": {
        "en_US": "Loop the selected region (no effect without a selection) (L)",
        "zh_CN": "循环播放选中区域（未选区域则无效）(L)",
        "zh_TW": "循環播放選取區域（未選取區域則無效）(L)",
    },
    "transport.tip_rate": {
        "en_US": "Playback rate (changes speed and pitch)",
        "zh_CN": "播放速率（变速变调）",
        "zh_TW": "播放速率（變速變調）",
    },
    "transport.tip_position": {
        "en_US": "Playback position",
        "zh_CN": "播放位置",
        "zh_TW": "播放位置",
    },
    # 语谱图（9 处 → 8 键，标题复用 view.spectrogram）
    "spectrogram.range": {
        "en_US": "Range:",
        "zh_CN": "范围:",
        "zh_TW": "範圍:",
    },
    "spectrogram.axis_y": {
        "en_US": "Y axis:",
        "zh_CN": "Y轴:",
        "zh_TW": "Y 軸:",
    },
    "spectrogram.colormap": {
        "en_US": "Colormap:",
        "zh_CN": "色板:",
        "zh_TW": "色板:",
    },
    "spectrogram.readout_none": {
        "en_US": "Time: -- s | Freq: -- Hz | Level: -- dB",
        "zh_CN": "时间: -- s | 频率: -- Hz | 强度: -- dB",
        "zh_TW": "時間: -- s | 頻率: -- Hz | 強度: -- dB",
    },
    "spectrogram.tip_measure": {
        "en_US": "Measure tool (drag to measure time/frequency difference)",
        "zh_CN": "测量工具（拖动测量时间差/频率差）",
        "zh_TW": "測量工具（拖曳測量時間差/頻率差）",
    },
    "spectrogram.tip_peak_track": {
        "en_US": "Peak frequency tracking (strongest frequency per frame)",
        "zh_CN": "峰值频率追踪（显示每帧最强频率曲线）",
        "zh_TW": "峰值頻率追蹤（顯示每幀最強頻率曲線）",
    },
    "spectrogram.tip_pitch_overlay": {
        "en_US": "Pitch contour overlay (pYIN track)",
        "zh_CN": "音高曲线叠加（pYIN 轨迹）",
        "zh_TW": "音高曲線疊加（pYIN 軌跡）",
    },
    "spectrogram.tip_advanced": {
        "en_US": "Advanced settings",
        "zh_CN": "高级设置",
        "zh_TW": "進階設定",
    },
    # 音高（8 处 → 8 键）
    "pitch.title": {
        "en_US": "Pitch contour",
        "zh_CN": "音高轨迹",
        "zh_TW": "音高軌跡",
    },
    "pitch.axis_y": {
        "en_US": "Y axis:",
        "zh_CN": "Y轴:",
        "zh_TW": "Y 軸:",
    },
    "pitch.time_none": {
        "en_US": "Time: -- s",
        "zh_CN": "时间: -- s",
        "zh_TW": "時間: -- s",
    },
    "pitch.freq_none": {
        "en_US": "Freq: -- Hz",
        "zh_CN": "频率: -- Hz",
        "zh_TW": "頻率: -- Hz",
    },
    "pitch.cents_none": {
        "en_US": "Cents (rel. A4): -- cents",
        "zh_CN": "相对 A4 音分: -- cents",
        "zh_TW": "相對 A4 音分: -- cents",
    },
    "pitch.time": {
        "en_US": "Time: {time} s",
        "zh_CN": "时间: {time} s",
        "zh_TW": "時間: {time} s",
    },
    "pitch.freq_hz": {
        "en_US": "Freq: {value} Hz",
        "zh_CN": "频率: {value} Hz",
        "zh_TW": "頻率: {value} Hz",
    },
    "pitch.cents": {
        "en_US": "Cents (rel. A4): {value} cents",
        "zh_CN": "相对 A4 音分: {value} cents",
        "zh_TW": "相對 A4 音分: {value} cents",
    },
    # 3D 频谱图（7 处 → 6 键，标题复用 view.spectrogram3d）
    "spectrogram3d.segment": {
        "en_US": "Segment:",
        "zh_CN": "乐段:",
        "zh_TW": "樂段:",
    },
    "spectrogram3d.tip_segment": {
        "en_US": "Centre on the waveform playhead and take ±2 s",
        "zh_CN": "以波形分析指针为中心，取前后各 2 秒的乐段",
        "zh_TW": "以波形分析指標為中心，取前後各 2 秒的樂段",
    },
    "spectrogram3d.mode": {
        "en_US": "Mode:",
        "zh_CN": "模式:",
        "zh_TW": "模式:",
    },
    "spectrogram3d.scale": {
        "en_US": "Scale:",
        "zh_CN": "标度:",
        "zh_TW": "標度:",
    },
    "spectrogram3d.freq": {
        "en_US": "Frequency:",
        "zh_CN": "频率:",
        "zh_TW": "頻率:",
    },
    "spectrogram3d.colormap": {
        "en_US": "Colormap:",
        "zh_CN": "色板:",
        "zh_TW": "色板:",
    },
    # 波形（6 处 → 6 键，均 setToolTip）
    "waveform.tip_zoom_in": {
        "en_US": "Zoom in (Ctrl+=)",
        "zh_CN": "放大 (Ctrl+=)",
        "zh_TW": "放大 (Ctrl+=)",
    },
    "waveform.tip_zoom_out": {
        "en_US": "Zoom out (Ctrl+-)",
        "zh_CN": "缩小 (Ctrl+-)",
        "zh_TW": "縮小 (Ctrl+-)",
    },
    "waveform.tip_fit": {
        "en_US": "Fit to window",
        "zh_CN": "适应窗口",
        "zh_TW": "適應視窗",
    },
    "waveform.tip_scrub": {
        "en_US": "Scrub mode: hold and drag to play (Ctrl+drag also works)",
        "zh_CN": "Scrub 模式：按住鼠标拖动播放（Ctrl+拖动也可触发）",
        "zh_TW": "Scrub 模式：按住滑鼠拖曳播放（Ctrl+拖曳也可觸發）",
    },
    "waveform.tip_normalize": {
        "en_US": "Toggle waveform normalization (N)",
        "zh_CN": "切换波形归一化显示 (N)",
        "zh_TW": "切換波形正規化顯示 (N)",
    },
    "waveform.tip_level": {
        "en_US": "Output level",
        "zh_CN": "输出电平",
        "zh_TW": "輸出電平",
    },
    # 共振峰（4 处 → 4 键）
    "formants.title": {
        "en_US": "Formant contour (LPC)",
        "zh_CN": "共振峰轨迹 (LPC)",
        "zh_TW": "共振峰軌跡 (LPC)",
    },
    "formants.axis_y": {
        "en_US": "Y axis:",
        "zh_CN": "Y轴:",
        "zh_TW": "Y 軸:",
    },
    "formants.time_none": {
        "en_US": "Time: -- s",
        "zh_CN": "时间: -- s",
        "zh_TW": "時間: -- s",
    },
    "formants.time": {
        "en_US": "Time: {time} s",
        "zh_CN": "时间: {time} s",
        "zh_TW": "時間: {time} s",
    },
    # 文件信息条（空态）
    "metadata_bar.empty": {
        "en_US": "No file loaded",
        "zh_CN": "未加载文件",
        "zh_TW": "未載入檔案",
    },
    # 音色（标题）
    "timbre.title": {
        "en_US": "Timbre feature analysis",
        "zh_CN": "音色特征分析",
        "zh_TW": "音色特徵分析",
    },
    # H5b：MFCC 色标轴标签——系数不是分贝，标签即「系数值」（非 dB；三语齐，
    # ko/ja 同批补齐，保持既有 parity 计数不减）
    "timbre.colorbar.unit": {
        "en_US": "Coefficient",
        "zh_CN": "系数值",
        "zh_TW": "係數值",
        "ko_KR": "계수 값",
        "ja_JP": "係数値",
    },
    # --- PI-P5-B3-01i 论文图导出入口（菜单项 + 对话框；三语齐，ko/ja 随批已给） ---
    "action.export_paper_figure": {
        "en_US": "Export Paper Figure…",
        "zh_CN": "论文图导出…",
        "zh_TW": "論文圖匯出…",
        "ko_KR": "논문 그림 내보내기…",
        "ja_JP": "論文図の書き出し…",
    },
    "figure_export.title": {
        "en_US": "Export Paper Figure",
        "zh_CN": "论文图导出",
        "zh_TW": "論文圖匯出",
        "ko_KR": "논문 그림 내보내기",
        "ja_JP": "論文図の書き出し",
    },
    "figure_export.figure": {
        "en_US": "Figure",
        "zh_CN": "图型",
        "zh_TW": "圖型",
        "ko_KR": "그림 유형",
        "ja_JP": "図の種類",
    },
    "figure_export.preset_a": {
        "en_US": "Figure A · Segment curve",
        "zh_CN": "图 A · 段曲线",
        "zh_TW": "圖 A · 段曲線",
        "ko_KR": "그림 A · 구간 곡선",
        "ja_JP": "図 A · 区間カーブ",
    },
    "figure_export.preset_b": {
        "en_US": "Figure B · Type × oscillation",
        "zh_CN": "图 B · 形态 × 往复度",
        "zh_TW": "圖 B · 形態 × 往復度",
        "ko_KR": "그림 B · 형태 × 왕복도",
        "ja_JP": "図 B · 形態 × 往復度",
    },
    "figure_export.preset_c": {
        "en_US": "Figure C · Reference comparison",
        "zh_CN": "图 C · 参照系对比",
        "zh_TW": "圖 C · 參照系對比",
        "ko_KR": "그림 C · 기준계 비교",
        "ja_JP": "図 C · 参照系比較",
    },
    "figure_export.output_dir": {
        "en_US": "Output folder",
        "zh_CN": "输出目录",
        "zh_TW": "輸出目錄",
        "ko_KR": "출력 폴더",
        "ja_JP": "出力フォルダー",
    },
    "figure_export.browse": {
        "en_US": "Browse…",
        "zh_CN": "浏览…",
        "zh_TW": "瀏覽…",
        "ko_KR": "찾아보기…",
        "ja_JP": "参照…",
    },
    "figure_export.start_s": {
        "en_US": "Segment start (s)",
        "zh_CN": "段起点（秒）",
        "zh_TW": "段起點（秒）",
        "ko_KR": "구간 시작(초)",
        "ja_JP": "区間開始（秒）",
    },
    "figure_export.end_s": {
        "en_US": "Segment end (s)",
        "zh_CN": "段终点（秒）",
        "zh_TW": "段終點（秒）",
        "ko_KR": "구간 끝(초)",
        "ja_JP": "区間終了（秒）",
    },
    "figure_export.window_start": {
        "en_US": "Window start (s)",
        "zh_CN": "窗起点（秒）",
        "zh_TW": "窗起點（秒）",
        "ko_KR": "창 시작(초)",
        "ja_JP": "ウィンドウ開始（秒）",
    },
    "figure_export.anchor_cents": {
        "en_US": "Anchor offset (cents)",
        "zh_CN": "锚定偏移（音分）",
        "zh_TW": "錨定偏移（音分）",
        "ko_KR": "앵커 오프셋(센트)",
        "ja_JP": "アンカーオフセット（セント）",
    },
    "figure_export.anchor_source": {
        "en_US": "Anchor source",
        "zh_CN": "锚来源（实践／文献）",
        "zh_TW": "錨來源（實踐／文獻）",
        "ko_KR": "앵커 출처(실연/문헌)",
        "ja_JP": "アンカー出典（実践／文献）",
    },
    "figure_export.anchor_pending": {
        "en_US": "Not provided",
        "zh_CN": "未提供（不填）",
        "zh_TW": "未提供（不填）",
        "ko_KR": "미제공(미입력)",
        "ja_JP": "未提供（入力しない）",
    },
    "figure_export.anchor_note": {
        "en_US": "The anchor offset comes from performance practice or the literature; "
                 "the platform does not guess. Without an anchor this preset cannot be exported.",
        "zh_CN": "锚定偏移由演奏实践／文献给，平台不猜；缺锚则该预设不出图（导出按钮禁用）。",
        "zh_TW": "錨定偏移由演奏實踐／文獻給，平台不猜；缺錨則該預設不出圖（匯出按鈕停用）。",
        "ko_KR": "앵커 오프셋은 연주 실천이나 문헌이 주는 값이며 플랫폼은 추측하지 않습니다. "
                 "앵커가 없으면 이 프리셋은 내보낼 수 없습니다.",
        "ja_JP": "アンカーオフセットは演奏実践や文献が与える値で、プラットフォームは推測しません。"
                 "アンカーが無い場合、このプリセットは書き出せません。",
    },
    "figure_export.panels_file": {
        "en_US": "Panel data file (JSON/CSV)",
        "zh_CN": "分面数据文件（JSON/CSV）",
        "zh_TW": "分面資料檔（JSON/CSV）",
        "ko_KR": "분면 데이터 파일(JSON/CSV)",
        "ja_JP": "パネルデータファイル（JSON/CSV）",
    },
    "figure_export.export": {
        "en_US": "Export",
        "zh_CN": "导出",
        "zh_TW": "匯出",
        "ko_KR": "내보내기",
        "ja_JP": "書き出し",
    },
    "figure_export.cancel": {
        "en_US": "Cancel",
        "zh_CN": "取消",
        "zh_TW": "取消",
        "ko_KR": "취소",
        "ja_JP": "キャンセル",
    },
    "figure_export.done": {
        "en_US": "Paper figure exported to {path}",
        "zh_CN": "论文图已导出至 {path}",
        "zh_TW": "論文圖已匯出至 {path}",
        "ko_KR": "논문 그림을 {path}에 내보냈습니다",
        "ja_JP": "論文図を {path} に書き出しました",
    },
    "figure_export.failed": {
        "en_US": "Paper figure export failed",
        "zh_CN": "论文图导出失败",
        "zh_TW": "論文圖匯出失敗",
        "ko_KR": "논문 그림 내보내기 실패",
        "ja_JP": "論文図の書き出しに失敗しました",
    },
    "figure_export.publication_note": {
        "en_US": "300 dpi · PNG + PDF",
        "zh_CN": "300 dpi · PNG + PDF",
        "zh_TW": "300 dpi · PNG + PDF",
        "ko_KR": "300 dpi · PNG + PDF",
        "ja_JP": "300 dpi · PNG + PDF",
    },
    "figure_export.need_audio": {
        "en_US": "Open an audio file first",
        "zh_CN": "请先加载音频文件",
        "zh_TW": "請先載入音訊檔案",
        "ko_KR": "먼저 오디오 파일을 여십시오",
        "ja_JP": "先に音声ファイルを開いてください",
    },
    "figure_export.need_panels": {
        "en_US": "Choose a panel data file (JSON/CSV) first",
        "zh_CN": "请先选择分面数据文件（JSON/CSV）",
        "zh_TW": "請先選擇分面資料檔（JSON/CSV）",
        "ko_KR": "먼저 분면 데이터 파일(JSON/CSV)을 선택하십시오",
        "ja_JP": "先にパネルデータファイル（JSON/CSV）を選んでください",
    },
    "action.batch_readout": {
        "en_US": "Batch Readout Run…",
        "zh_CN": "批量读数运行…",
        "zh_TW": "批次讀數執行…",
        "ko_KR": "배치 판독 실행…",
        "ja_JP": "バッチ読み出し実行…",
    },
    "batch_readout.title": {
        "en_US": "Batch Readout Run",
        "zh_CN": "批量读数运行",
        "zh_TW": "批次讀數執行",
        "ko_KR": "배치 판독 실행",
        "ja_JP": "バッチ読み出し実行",
    },
    "batch_readout.cases": {
        "en_US": "Recordings",
        "zh_CN": "录音清单",
        "zh_TW": "錄音清單",
        "ko_KR": "녹음 목록",
        "ja_JP": "録音リスト",
    },
    "batch_readout.col_file": {
        "en_US": "File",
        "zh_CN": "文件",
        "zh_TW": "檔案",
        "ko_KR": "파일",
        "ja_JP": "ファイル",
    },
    "batch_readout.col_label": {
        "en_US": "Display name",
        "zh_CN": "呈现名",
        "zh_TW": "呈現名",
        "ko_KR": "표시 이름",
        "ja_JP": "表示名",
    },
    "batch_readout.col_anchor": {
        "en_US": "Anchor (cents)",
        "zh_CN": "锚偏移（音分）",
        "zh_TW": "錨偏移（音分）",
        "ko_KR": "앵커 오프셋(음분)",
        "ja_JP": "アンカー（セント）",
    },
    "batch_readout.col_source": {
        "en_US": "Anchor source",
        "zh_CN": "锚来源",
        "zh_TW": "錨來源",
        "ko_KR": "앵커 출처",
        "ja_JP": "アンカーの出典",
    },
    "batch_readout.add": {
        "en_US": "Add…",
        "zh_CN": "添加…",
        "zh_TW": "新增…",
        "ko_KR": "추가…",
        "ja_JP": "追加…",
    },
    "batch_readout.remove": {
        "en_US": "Remove",
        "zh_CN": "移除",
        "zh_TW": "移除",
        "ko_KR": "제거",
        "ja_JP": "削除",
    },
    "batch_readout.add_title": {
        "en_US": "Select recordings",
        "zh_CN": "选择录音文件",
        "zh_TW": "選擇錄音檔案",
        "ko_KR": "녹음 파일 선택",
        "ja_JP": "録音ファイルを選択",
    },
    "batch_readout.browse": {
        "en_US": "Browse…",
        "zh_CN": "浏览…",
        "zh_TW": "瀏覽…",
        "ko_KR": "찾아보기…",
        "ja_JP": "参照…",
    },
    "batch_readout.output_dir": {
        "en_US": "Output folder",
        "zh_CN": "输出目录",
        "zh_TW": "輸出目錄",
        "ko_KR": "출력 폴더",
        "ja_JP": "出力フォルダ",
    },
    "batch_readout.figure_out": {
        "en_US": "Also render the figure (same run, same τ)",
        "zh_CN": "同时出图（同源同 τ）",
        "zh_TW": "同時出圖（同源同 τ）",
        "ko_KR": "같은 실행에서 그림도 출력(동일 τ)",
        "ja_JP": "同時に図も出力（同一実行・同一 τ）",
    },
    "batch_readout.figure_dir": {
        "en_US": "Figure folder",
        "zh_CN": "图件输出目录",
        "zh_TW": "圖件輸出目錄",
        "ko_KR": "그림 출력 폴더",
        "ja_JP": "図の出力フォルダ",
    },
    "batch_readout.params_group": {
        "en_US": "Acquisition parameters (any change changes the numbers)",
        "zh_CN": "取数参数（换任一即换数）",
        "zh_TW": "取數參數（換任一即換數）",
        "ko_KR": "취수 파라미터(하나만 바뀌어도 값이 바뀝니다)",
        "ja_JP": "取得パラメータ（1 つ変えると数値も変わる）",
    },
    "batch_readout.window_s": {
        "en_US": "Window length",
        "zh_CN": "分析窗长",
        "zh_TW": "分析窗長",
        "ko_KR": "분석 창 길이",
        "ja_JP": "分析窓長",
    },
    "batch_readout.min_window_s": {
        "en_US": "Minimum tail window",
        "zh_CN": "最短尾窗",
        "zh_TW": "最短尾窗",
        "ko_KR": "최소 꼬리 창",
        "ja_JP": "最小末尾窓",
    },
    "batch_readout.fmin": {
        "en_US": "Lower pitch bound",
        "zh_CN": "音高下限",
        "zh_TW": "音高下限",
        "ko_KR": "음역 하한",
        "ja_JP": "ピッチ下限",
    },
    "batch_readout.fmax": {
        "en_US": "Upper pitch bound",
        "zh_CN": "音高上限",
        "zh_TW": "音高上限",
        "ko_KR": "음역 상한",
        "ja_JP": "ピッチ上限",
    },
    "batch_readout.tonic_window_s": {
        "en_US": "Tonic fitting window",
        "zh_CN": "主音拟合窗",
        "zh_TW": "主音擬合窗",
        "ko_KR": "주음 피팅 창",
        "ja_JP": "主音フィット窓",
    },
    "batch_readout.overlap_ratio": {
        "en_US": "Pairing overlap ratio",
        "zh_CN": "配对重叠比",
        "zh_TW": "配對重疊比",
        "ko_KR": "쌍 매칭 겹침 비율",
        "ja_JP": "ペア重なり率",
    },
    "batch_readout.smooth_k": {
        "en_US": "Turn smoothing window",
        "zh_CN": "往复度平滑窗",
        "zh_TW": "往復度平滑窗",
        "ko_KR": "왕복도 평활 창",
        "ja_JP": "往復度平滑窓",
    },
    "batch_readout.min_thr": {
        "en_US": "Valid-frame threshold",
        "zh_CN": "有效帧阈值",
        "zh_TW": "有效幀閾值",
        "ko_KR": "유효 프레임 임계값",
        "ja_JP": "有効フレーム閾値",
    },
    "batch_readout.taus": {
        "en_US": "τ scan steps (none = uncalibrated)",
        "zh_CN": "τ 扫描档位（none = 未标定）",
        "zh_TW": "τ 掃描檔位（none = 未標定）",
        "ko_KR": "τ 주사 단계(none = 미표정)",
        "ja_JP": "τ 走査ステップ（none = 未校正）",
    },
    "batch_readout.tau_analysis": {
        "en_US": "Main τ (run-config declared)",
        "zh_CN": "主分析 τ（运行口径声明）",
        "zh_TW": "主分析 τ（執行口徑宣告）",
        "ko_KR": "주 분석 τ(실행 기준 선언)",
        "ja_JP": "主分析 τ（実行口径の宣言）",
    },
    "batch_readout.tau_analysis_hint": {
        "en_US": "cents; leave blank to emit the sign-based control band only",
        "zh_CN": "音分；留空则只出按符号判对照档",
        "zh_TW": "音分；留空則只出按符號判對照檔",
        "ko_KR": "센트; 비우면 부호 판정 대조군만 산출",
        "ja_JP": "セント；空欄なら符号判定の対照のみ出力",
    },
    "batch_readout.err_bad_tau_analysis": {
        "en_US": "Main τ must be a positive number (or left blank).",
        "zh_CN": "主分析 τ 须为正数（或留空）。",
        "zh_TW": "主分析 τ 須為正數（或留空）。",
        "ko_KR": "주 분석 τ는 양수여야 합니다(또는 비워 두십시오).",
        "ja_JP": "主分析 τ は正の数値（または空欄）にしてください。",
    },
    "batch_readout.segmenter": {
        "en_US": "Segmenter",
        "zh_CN": "分段器",
        "zh_TW": "分段器",
        "ko_KR": "분할기",
        "ja_JP": "セグメンタ",
    },
    "batch_readout.seg_hmm": {
        "en_US": "Note HMM (three-state)",
        "zh_CN": "Note HMM 三态分段",
        "zh_TW": "Note HMM 三態分段",
        "ko_KR": "Note HMM 3상 분할",
        "ja_JP": "Note HMM 3 状態分割",
    },
    "batch_readout.seg_simple": {
        "en_US": "Simple contour",
        "zh_CN": "简易轮廓分段",
        "zh_TW": "簡易輪廓分段",
        "ko_KR": "단순 윤곽 분할",
        "ja_JP": "単純輪廓分割",
    },
    "batch_readout.template": {
        "en_US": "Tuning template",
        "zh_CN": "律制模板",
        "zh_TW": "律制模板",
        "ko_KR": "율제 템플릿",
        "ja_JP": "音律テンプレート",
    },
    "batch_readout.ref_absolute": {
        "en_US": "Absolute",
        "zh_CN": "绝对口径",
        "zh_TW": "絕對口徑",
        "ko_KR": "절대 기준",
        "ja_JP": "絶対基準",
    },
    "batch_readout.ref_main_tone": {
        "en_US": "Main-tone relative",
        "zh_CN": "主音相对口径",
        "zh_TW": "主音相對口徑",
        "ko_KR": "주음 상대 기준",
        "ja_JP": "主音相対基準",
    },
    "batch_readout.cancel": {
        "en_US": "Cancel",
        "zh_CN": "取消",
        "zh_TW": "取消",
        "ko_KR": "취소",
        "ja_JP": "キャンセル",
    },
    "batch_readout.run": {
        "en_US": "Run",
        "zh_CN": "运行",
        "zh_TW": "執行",
        "ko_KR": "실행",
        "ja_JP": "実行",
    },
    "batch_readout.err_no_case": {
        "en_US": "Add at least one recording",
        "zh_CN": "请至少添加一条录音",
        "zh_TW": "請至少新增一筆錄音",
        "ko_KR": "녹음을 하나 이상 추가하십시오",
        "ja_JP": "録音を 1 件以上追加してください",
    },
    "batch_readout.err_no_dir": {
        "en_US": "Choose an output folder",
        "zh_CN": "请选择输出目录",
        "zh_TW": "請選擇輸出目錄",
        "ko_KR": "출력 폴더를 선택하십시오",
        "ja_JP": "出力フォルダを選んでください",
    },
    "batch_readout.err_no_figure_dir": {
        "en_US": "Choose a figure folder (or turn the figure off)",
        "zh_CN": "请选择图件输出目录（或取消出图）",
        "zh_TW": "請選擇圖件輸出目錄（或取消出圖）",
        "ko_KR": "그림 출력 폴더를 선택하십시오(또는 그림 출력을 끄십시오)",
        "ja_JP": "図の出力フォルダを選ぶ（または図出力をオフに）",
    },
    "batch_readout.err_no_mode": {
        "en_US": "Keep at least one reference mode",
        "zh_CN": "请至少保留一个口径",
        "zh_TW": "請至少保留一個口徑",
        "ko_KR": "기준을 하나 이상 남겨 두십시오",
        "ja_JP": "基準を 1 つ以上残してください",
    },
    "batch_readout.err_bad_taus": {
        "en_US": "τ steps must be numbers or 'none'",
        "zh_CN": "τ 档位须为数字或 none",
        "zh_TW": "τ 檔位須為數字或 none",
        "ko_KR": "τ 단계는 숫자 또는 none 이어야 합니다",
        "ja_JP": "τ ステップは数値または none",
    },
    "batch_readout.done": {
        "en_US": "Batch readout done · run_id {rid}",
        "zh_CN": "批量读数完成 · run_id {rid}",
        "zh_TW": "批次讀數完成 · run_id {rid}",
        "ko_KR": "배치 판독 완료 · run_id {rid}",
        "ja_JP": "バッチ読み出し完了 · run_id {rid}",
    },
    "batch_readout.failed": {
        "en_US": "Batch readout failed",
        "zh_CN": "批量读数失败",
        "zh_TW": "批次讀數失敗",
        "ko_KR": "배치 판독 실패",
        "ja_JP": "バッチ読み出し失敗",
    },
    "batch_readout.cancelled": {
        "en_US": "Batch readout cancelled",
        "zh_CN": "批量读数已取消",
        "zh_TW": "批次讀數已取消",
        "ko_KR": "배치 판독 취소됨",
        "ja_JP": "バッチ読み出しは取り消されました",
    },
    "task_center.title.readout": {
        "en_US": "Batch readout · {n} recordings",
        "zh_CN": "批量读数 · {n} 条",
        "zh_TW": "批次讀數 · {n} 筆",
        "ko_KR": "배치 판독 · {n}건",
        "ja_JP": "バッチ読み出し · {n} 件",
    },
    "figure_export.same_run": {
        "en_US": "Require same run as the tables (T-3)",
        "zh_CN": "要求与表格同源（T-3）",
        "zh_TW": "要求與表格同源（T-3）",
        "ko_KR": "표와 동일 실행일 것(T-3)",
        "ja_JP": "表と同一実行を要求（T-3）",
    },
    "figure_export.same_run_note": {
        "en_US": "Panel data and the table must come from one run (same run_id, same τ). Without a companion distribution file this cannot be checked.",
        "zh_CN": "图件与表格须出自同一次运行（同一 run_id、同一 τ）；缺配套分布件时无法核验，将如实登记为未核验。",
        "zh_TW": "圖件與表格須出自同一次執行（同一 run_id、同一 τ）；缺配套分佈檔時無法核驗，將如實登記為未核驗。",
        "ko_KR": "그림과 표는 같은 실행(동일 run_id·동일 τ)이어야 합니다. 분포 파일이 없으면 검증할 수 없으며 미검증으로 기록됩니다.",
        "ja_JP": "図と表は同一実行（同じ run_id・同じ τ）でなければなりません。分布ファイルが無い場合は検証できず、未検証として記録されます。",
    },
    "figure_export.error_same_run": {
        "en_US": "Refusing to render: panel data run_id {panels} does not match the table run_id {table}. They are not from the same run.",
        "zh_CN": "拒绝出图：图件 run_id {panels} 与表格 run_id {table} 不一致，二者非同一次运行。",
        "zh_TW": "拒絕出圖：圖件 run_id {panels} 與表格 run_id {table} 不一致，二者非同一次執行。",
        "ko_KR": "그림 출력을 거부합니다: 그림 run_id {panels} 와 표 run_id {table} 가 다릅니다. 같은 실행이 아닙니다.",
        "ja_JP": "図の出力を拒否します：図の run_id {panels} と表の run_id {table} が一致しません。同一実行ではありません。",
    },
    "batch_readout.load_json": {
        "en_US": "Load list…",
        "zh_CN": "载入清单…",
        "zh_TW": "載入清單…",
        "ko_KR": "목록 불러오기…",
        "ja_JP": "リスト読込…",
    },
    "batch_readout.load_title": {
        "en_US": "Select a case list (cases.json)",
        "zh_CN": "选择清单文件（cases.json）",
        "zh_TW": "選擇清單檔（cases.json）",
        "ko_KR": "케이스 목록 파일 선택(cases.json)",
        "ja_JP": "ケース一覧ファイル選択（cases.json）",
    },
    "batch_readout.load_json_tip": {
        "en_US": "Load the same cases.json used by the CLI — then GUI and CLI reproduce the very same run_id.",
        "zh_CN": "载入与命令行同一份 cases.json ⇒ GUI 与命令行可复现同一个 run_id。",
        "zh_TW": "載入與命令列同一份 cases.json ⇒ GUI 與命令列可重現同一個 run_id。",
        "ko_KR": "CLI 와 같은 cases.json 을 불러오면 GUI 와 CLI 가 동일한 run_id 를 재현합니다.",
        "ja_JP": "CLI と同じ cases.json を読み込むと、GUI と CLI が同じ run_id を再現します。",
    },
    # --- W-14（2026-11-01）平台公共能力补齐：GUI 文案（五语齐） ---
    "w14.template.custom_item": {
        "en_US": "Custom (.scl)…",
        "zh_CN": "自定义 (.scl)…",
        "zh_TW": "自訂 (.scl)…",
        "ko_KR": "사용자 정의(.scl)…",
        "ja_JP": "カスタム(.scl)…",
    },
    "w14.template.custom_filter": {
        "en_US": "Scala scale (*.scl);;All files (*)",
        "zh_CN": "Scala 音阶 (*.scl);;所有文件 (*)",
        "zh_TW": "Scala 音階 (*.scl);;所有檔案 (*)",
        "ko_KR": "Scala 음계 (*.scl);;모든 파일 (*)",
        "ja_JP": "Scala 音階 (*.scl);;すべてのファイル (*)",
    },
    "w14.template.custom_bound": {
        "en_US": "Custom scale: {name}",
        "zh_CN": "自定义音阶：{name}",
        "zh_TW": "自訂音階：{name}",
        "ko_KR": "사용자 정의 음계: {name}",
        "ja_JP": "カスタム音階：{name}",
    },
    "w14.template.custom_failed": {
        "en_US": "Cannot load the .scl file: {error}",
        "zh_CN": "无法载入 .scl 文件：{error}",
        "zh_TW": "無法載入 .scl 檔案：{error}",
        "ko_KR": ".scl 파일을 불러올 수 없습니다: {error}",
        "ja_JP": ".scl ファイルを読み込めません: {error}",
    },
    "w14.template.save_scl": {
        "en_US": "Save as .scl",
        "zh_CN": "另存为 .scl",
        "zh_TW": "另存為 .scl",
        "ko_KR": ".scl 로 저장",
        "ja_JP": ".scl として保存",
    },
    "w14.template.save_scl_done": {
        "en_US": "Scale written: {path}",
        "zh_CN": "音阶已写出：{path}",
        "zh_TW": "音階已寫出：{path}",
        "ko_KR": "음계를 저장했습니다: {path}",
        "ja_JP": "音階を書き出しました: {path}",
    },
    "w14.template.info": {
        "en_US": "Template: {name}｜source: {source}｜fingerprint: {fingerprint}",
        "zh_CN": "模板：{name}｜来源：{source}｜指纹：{fingerprint}",
        "zh_TW": "模板：{name}｜來源：{source}｜指紋：{fingerprint}",
        "ko_KR": "템플릿: {name}｜출처: {source}｜지문: {fingerprint}",
        "ja_JP": "テンプレート：{name}｜出典：{source}｜指紋：{fingerprint}",
    },
    "w14.template.info_label": {
        "en_US": "Template name / source / fingerprint",
        "zh_CN": "模板名称／来源／指纹",
        "zh_TW": "模板名稱／來源／指紋",
        "ko_KR": "템플릿 이름／출처／지문",
        "ja_JP": "テンプレート名／出典／指紋",
    },
    "tuning.user.manage": {
        "en_US": "Manage Custom Tuning Templates…",
        "zh_CN": "管理自定义律制模板…",
        "zh_TW": "管理自訂律制範本…",
        "ko_KR": "사용자 정의 율제 템플릿 관리…",
        "ja_JP": "カスタム律制テンプレートの管理…",
    },
    "tuning.user.group": {
        "en_US": "My Templates",
        "zh_CN": "我的模板",
        "zh_TW": "我的範本",
        "ko_KR": "내 템플릿",
        "ja_JP": "マイテンプレート",
    },
    "tuning.user.title": {
        "en_US": "Custom Tuning Templates",
        "zh_CN": "自定义律制模板",
        "zh_TW": "自訂律制範本",
        "ko_KR": "사용자 정의 율제 템플릿",
        "ja_JP": "カスタム律制テンプレート",
    },
    "tuning.user.name": {
        "en_US": "Name",
        "zh_CN": "名称",
        "zh_TW": "名稱",
        "ko_KR": "이름",
        "ja_JP": "名前",
    },
    "tuning.user.source": {
        "en_US": "Source (required)",
        "zh_CN": "来源（必填）",
        "zh_TW": "來源（必填）",
        "ko_KR": "출처 (필수)",
        "ja_JP": "出典（必須）",
    },
    "tuning.user.degrees": {
        "en_US": "Degrees (one cent value or n/d ratio per line)",
        "zh_CN": "音级（每行一个音分值或 n/d 比值）",
        "zh_TW": "音級（每行一個音分值或 n/d 比值）",
        "ko_KR": "음급 (줄마다 음분값 또는 n/d 비율)",
        "ja_JP": "音級（1行に音分値または n/d 比）",
    },
    "tuning.user.new": {
        "en_US": "New",
        "zh_CN": "新建",
        "zh_TW": "新增",
        "ko_KR": "새로 만들기",
        "ja_JP": "新規",
    },
    "tuning.user.save": {
        "en_US": "Save",
        "zh_CN": "保存",
        "zh_TW": "儲存",
        "ko_KR": "저장",
        "ja_JP": "保存",
    },
    "tuning.user.delete": {
        "en_US": "Delete",
        "zh_CN": "删除",
        "zh_TW": "刪除",
        "ko_KR": "삭제",
        "ja_JP": "削除",
    },
    "tuning.user.delete_arm": {
        "en_US": "Click again to confirm",
        "zh_CN": "再点一次确认删除",
        "zh_TW": "再點一次確認刪除",
        "ko_KR": "한 번 더 눌러 삭제",
        "ja_JP": "もう一度クリックで削除",
    },
    "tuning.user.import": {
        "en_US": "Import .scl",
        "zh_CN": "导入 .scl",
        "zh_TW": "匯入 .scl",
        "ko_KR": ".scl 가져오기",
        "ja_JP": ".scl を読み込む",
    },
    "tuning.user.export": {
        "en_US": "Export .scl",
        "zh_CN": "导出 .scl",
        "zh_TW": "匯出 .scl",
        "ko_KR": ".scl 내보내기",
        "ja_JP": ".scl を書き出す",
    },
    "tuning.user.close": {
        "en_US": "Close",
        "zh_CN": "关闭",
        "zh_TW": "關閉",
        "ko_KR": "닫기",
        "ja_JP": "閉じる",
    },
    "tuning.user.err_bad": {
        "en_US": "Cannot parse degrees: {error}",
        "zh_CN": "无法解析音级：{error}",
        "zh_TW": "無法解析音級：{error}",
        "ko_KR": "음급을 해석할 수 없습니다: {error}",
        "ja_JP": "音級を解析できません: {error}",
    },
    "tuning.user.err_empty": {
        "en_US": "Name, source and degrees are all required",
        "zh_CN": "名称、来源与音级均不可为空",
        "zh_TW": "名稱、來源與音級均不可為空",
        "ko_KR": "이름, 출처, 음급은 모두 필수입니다",
        "ja_JP": "名前・出典・音級はすべて必須です",
    },
    "tuning.user.empty_hint": {
        "en_US": "(no custom templates yet)",
        "zh_CN": "（尚无自定义模板）",
        "zh_TW": "（尚無自訂範本）",
        "ko_KR": "(사용자 정의 템플릿 없음)",
        "ja_JP": "（カスタムテンプレートはまだありません）",
    },
    "tuning.user.saved": {
        "en_US": "Saved: {name}",
        "zh_CN": "已保存：{name}",
        "zh_TW": "已儲存：{name}",
        "ko_KR": "저장됨: {name}",
        "ja_JP": "保存しました: {name}",
    },
    "tuning.user.deleted": {
        "en_US": "Deleted: {name}",
        "zh_CN": "已删除：{name}",
        "zh_TW": "已刪除：{name}",
        "ko_KR": "삭제됨: {name}",
        "ja_JP": "削除しました: {name}",
    },
    "w14.cavity_core.button": {
        "en_US": "Cavity-core candidates…",
        "zh_CN": "腔核候选…",
        "zh_TW": "腔核候選…",
        "ko_KR": "공진 핵 후보…",
        "ja_JP": "腔核候補…",
    },
    "w14.cavity_core.title": {
        "en_US": "Cavity-core candidates (candidates only, not a verdict)",
        "zh_CN": "腔核候选（只给候选，不给判定）",
        "zh_TW": "腔核候選（只給候選，不給判定）",
        "ko_KR": "공진 핵 후보(후보만 제공, 판정 아님)",
        "ja_JP": "腔核候補（候補のみ・判定ではない）",
    },
    "w14.cavity_core.need_case": {
        "en_US": "Select one case in the list first.",
        "zh_CN": "请先在清单里选中一条案例。",
        "zh_TW": "請先在清單裡選中一條案例。",
        "ko_KR": "먼저 목록에서 사례를 하나 선택하세요.",
        "ja_JP": "先に一覧からケースを 1 件選択してください。",
    },
    "w14.cavity_core.col_id": {
        "en_US": "Candidate ID",
        "zh_CN": "候选 ID",
        "zh_TW": "候選 ID",
        "ko_KR": "후보 ID",
        "ja_JP": "候補 ID",
    },
    "w14.cavity_core.col_range": {
        "en_US": "Start–end (s)",
        "zh_CN": "起讫（秒）",
        "zh_TW": "起訖（秒）",
        "ko_KR": "시작–끝(초)",
        "ja_JP": "開始–終了(秒)",
    },
    "w14.cavity_core.col_degree": {
        "en_US": "Scale step",
        "zh_CN": "音级",
        "zh_TW": "音級",
        "ko_KR": "음계 단계",
        "ja_JP": "音階段",
    },
    "w14.cavity_core.col_deviation": {
        "en_US": "Deviation (cents)",
        "zh_CN": "偏离（音分）",
        "zh_TW": "偏離（音分）",
        "ko_KR": "편차(센트)",
        "ja_JP": "偏差（セント）",
    },
    "w14.cavity_core.col_share": {
        "en_US": "Stable frame share",
        "zh_CN": "稳定帧占比",
        "zh_TW": "穩定幀佔比",
        "ko_KR": "안정 프레임 비율",
        "ja_JP": "安定フレーム比率",
    },
    "w14.cavity_core.col_duration": {
        "en_US": "Duration (s)",
        "zh_CN": "时长（秒）",
        "zh_TW": "時長（秒）",
        "ko_KR": "길이(초)",
        "ja_JP": "長さ(秒)",
    },
    "w14.cavity_core.col_ci95": {
        "en_US": "Median CI95 (±cents)",
        "zh_CN": "中位 CI95（±音分）",
        "zh_TW": "中位 CI95（±音分）",
        "ko_KR": "중앙값 CI95(±센트)",
        "ja_JP": "中央値 CI95（±セント）",
    },
    "w14.cavity_core.run": {
        "en_US": "Compute",
        "zh_CN": "计算",
        "zh_TW": "計算",
        "ko_KR": "계산",
        "ja_JP": "計算",
    },
    "w14.cavity_core.export": {
        "en_US": "Export JSON…",
        "zh_CN": "导出 JSON…",
        "zh_TW": "匯出 JSON…",
        "ko_KR": "JSON 내보내기…",
        "ja_JP": "JSON 書き出し…",
    },
    "w14.cavity_core.close": {
        "en_US": "Close",
        "zh_CN": "关闭",
        "zh_TW": "關閉",
        "ko_KR": "닫기",
        "ja_JP": "閉じる",
    },
    "w14.cavity_core.max_gap": {
        "en_US": "Max gap for grouping (s)",
        "zh_CN": "同音级成组最大间隔（秒）",
        "zh_TW": "同音級成組最大間隔（秒）",
        "ko_KR": "동일 음계 그룹 최대 간격(초)",
        "ja_JP": "同音級グループ最大間隔(秒)",
    },
    "w14.cavity_core.summary": {
        "en_US": "{n} candidates｜template {template}｜params max_gap={max_gap}s｜filter {filter}",
        "zh_CN": "{n} 个候选｜模板 {template}｜参数 max_gap={max_gap}s｜过滤 {filter}",
        "zh_TW": "{n} 個候選｜模板 {template}｜參數 max_gap={max_gap}s｜過濾 {filter}",
        "ko_KR": "후보 {n}개｜템플릿 {template}｜매개변수 max_gap={max_gap}s｜필터 {filter}",
        "ja_JP": "候補 {n} 件｜テンプレート {template}｜パラメータ max_gap={max_gap}s｜フィルタ {filter}",
    },
    "w14.cavity_core.empty": {
        "en_US": "No candidate under current parameters (honest empty result).",
        "zh_CN": "当前参数下无候选（如实为空）。",
        "zh_TW": "目前參數下無候選（如實為空）。",
        "ko_KR": "현재 매개변수에서 후보가 없습니다(사실대로 비어 있음).",
        "ja_JP": "現在のパラメータでは候補がありません（正直に空）。",
    },
    "w14.figure.note_name": {
        "en_US": "Add note-name calibre (cross-template comparison)",
        "zh_CN": "增出音名口径（跨模板比较以此为准）",
        "zh_TW": "增出音名口徑（跨模板比較以此為準）",
        "ko_KR": "음이름 기준 추가(템플릿 간 비교 기준)",
        "ja_JP": "音名基準を追加（テンプレート間比較の基準）",
    },
    "w14.figure.note_name_tip": {
        "en_US": "The note-name calibre is a display convention (nearest semitone), not a tuning claim.",
        "zh_CN": "音名口径为显示/索引约定（最近半音），不是律学断言。",
        "zh_TW": "音名口徑為顯示/索引約定（最近半音），不是律學斷言。",
        "ko_KR": "음이름 기준은 표시·색인 규약(최근 반음)이며 율학적 단정이 아닙니다.",
        "ja_JP": "音名基準は表示・索引の約定（最近半音）であり、律学的な断定ではありません。",
    },
    "w14.figure.denominator": {
        "en_US": "Denominator",
        "zh_CN": "分母口径",
        "zh_TW": "分母口徑",
        "ko_KR": "분모 기준",
        "ja_JP": "分母基準",
    },
    "w14.figure.denominator_all": {
        "en_US": "all (current behaviour)",
        "zh_CN": "all（现行为）",
        "zh_TW": "all（現行為）",
        "ko_KR": "all(현재 동작)",
        "ja_JP": "all（現行の動作）",
    },
    "w14.figure.denominator_judgable": {
        "en_US": "judgable (valid segments only)",
        "zh_CN": "judgable（仅可判段）",
        "zh_TW": "judgable（僅可判段）",
        "ko_KR": "judgable(판정 가능 구간만)",
        "ja_JP": "judgable（判定可能区間のみ）",
    },
    "w14.figure.denominator_body": {
        "en_US": "body (main-text baseline, low-frequency excluded)",
        "zh_CN": "body（正文基准，剔低频不可靠）",
        "zh_TW": "body（正文基準，剔低頻不可靠）",
        "ko_KR": "body(본문 기준, 저주파 제외)",
        "ja_JP": "body（本文基準・低域除外）",
    },
    "w14.morph.group": {
        "en_US": "Chinese music morphology (project extension)",
        "zh_CN": "中国音乐形态学（项目扩展词汇）",
        "zh_TW": "中國音樂形態學（專案擴展詞彙）",
        "ko_KR": "중국 음악 형태학(프로젝트 확장 어휘)",
        "ja_JP": "中国音楽形態学（プロジェクト拡張語彙）",
    },
    "w14.morph.note": {
        "en_US": "Project extension vocabulary — not a core element of DA/T 63, GB/T 31219.4 or IMDI.",
        "zh_CN": "项目扩展词汇——不属 DA/T 63、GB/T 31219.4、IMDI 核心元素。",
        "zh_TW": "專案擴展詞彙——不屬 DA/T 63、GB/T 31219.4、IMDI 核心元素。",
        "ko_KR": "프로젝트 확장 어휘 — DA/T 63, GB/T 31219.4, IMDI 핵심 요소가 아닙니다.",
        "ja_JP": "プロジェクト拡張語彙 — DA/T 63、GB/T 31219.4、IMDI の中核要素ではありません。",
    },
    "w14.morph.cavity_position": {
        "en_US": "Cavity position",
        "zh_CN": "腔位",
        "zh_TW": "腔位",
        "ko_KR": "강 위치",
        "ja_JP": "腔位",
    },
    "w14.morph.cavity_type": {
        "en_US": "Cavity type",
        "zh_CN": "腔格",
        "zh_TW": "腔格",
        "ko_KR": "강 유형",
        "ja_JP": "腔格",
    },
    "w14.morph.note_position": {
        "en_US": "Note position",
        "zh_CN": "乐位",
        "zh_TW": "樂位",
        "ko_KR": "음 위치",
        "ja_JP": "楽位",
    },
    "w14.morph.cavity_core_annotation": {
        "en_US": "Cavity-core annotation",
        "zh_CN": "腔核标注",
        "zh_TW": "腔核標註",
        "ko_KR": "공진 핵 주석",
        "ja_JP": "腔核注記",
    },
    "w14.morph.annotator": {
        "en_US": "Annotator",
        "zh_CN": "标注者",
        "zh_TW": "標註者",
        "ko_KR": "주석자",
        "ja_JP": "注記者",
    },
    "w14.morph.method": {
        "en_US": "Method",
        "zh_CN": "方法",
        "zh_TW": "方法",
        "ko_KR": "방법",
        "ja_JP": "方法",
    },
    "w14.morph.template": {
        "en_US": "Reference template",
        "zh_CN": "参照模板",
        "zh_TW": "參照模板",
        "ko_KR": "참조 템플릿",
        "ja_JP": "参照テンプレート",
    },
    "w14.morph.confidence": {
        "en_US": "Confidence (0–1, blank = not given)",
        "zh_CN": "置信度（0–1，留空＝未给）",
        "zh_TW": "置信度（0–1，留空＝未給）",
        "ko_KR": "신뢰도(0–1, 공백=미기재)",
        "ja_JP": "信頼度（0–1、空欄＝未記入）",
    },
    "w14.morph.invalid": {
        "en_US": "Morphology field check failed: {problems}",
        "zh_CN": "形态学字段校验未通过：{problems}",
        "zh_TW": "形態學欄位校驗未通過：{problems}",
        "ko_KR": "형태학 필드 검증 실패: {problems}",
        "ja_JP": "形態学フィールド検証に失敗：{problems}",
    },
    "w14.morph.saved": {
        "en_US": "Morphology fields saved.",
        "zh_CN": "形态学字段已保存。",
        "zh_TW": "形態學欄位已儲存。",
        "ko_KR": "형태학 필드를 저장했습니다.",
        "ja_JP": "形態学フィールドを保存しました。",
    },
    "w14.morph.empty_enum": {
        "en_US": "(not set)",
        "zh_CN": "（未标注）",
        "zh_TW": "（未標註）",
        "ko_KR": "(미기재)",
        "ja_JP": "（未記入）",
    },
    "w14.infer.button": {
        "en_US": "Tuning inference…",
        "zh_CN": "律制推断…",
        "zh_TW": "律制推斷…",
        "ko_KR": "율제 추론…",
        "ja_JP": "律制推論…",
    },
    "w14.infer.title": {
        "en_US": "Tuning candidates (ranking only, not a claim of conformity)",
        "zh_CN": "律制候选（仅排序，不作「符合某律」断言）",
        "zh_TW": "律制候選（僅排序，不作「符合某律」斷言）",
        "ko_KR": "율제 후보(순위만, 특정 율 준수 주장 아님)",
        "ja_JP": "律制候補（順位のみ、「ある律に適合」とは主張しない）",
    },
    "w14.infer.preset_paper": {
        "en_US": "Paper six templates",
        "zh_CN": "论文六模板",
        "zh_TW": "論文六模板",
        "ko_KR": "논문 6개 템플릿",
        "ja_JP": "論文 6 テンプレート",
    },
    "w14.infer.preset_all": {
        "en_US": "All eight templates",
        "zh_CN": "全部八模板",
        "zh_TW": "全部八模板",
        "ko_KR": "전체 8개 템플릿",
        "ja_JP": "全 8 テンプレート",
    },
    "w14.infer.top_k": {
        "en_US": "Results (top k)",
        "zh_CN": "结果条数（top k）",
        "zh_TW": "結果條數（top k）",
        "ko_KR": "결과 개수(top k)",
        "ja_JP": "結果件数（top k）",
    },
    "w14.infer.window": {
        "en_US": "Analysis window (s)",
        "zh_CN": "分析窗（秒）",
        "zh_TW": "分析窗（秒）",
        "ko_KR": "분석 창(초)",
        "ja_JP": "分析窓(秒)",
    },
    "w14.infer.run": {
        "en_US": "Infer",
        "zh_CN": "推断",
        "zh_TW": "推斷",
        "ko_KR": "추론",
        "ja_JP": "推論",
    },
    "w14.infer.export": {
        "en_US": "Export JSON…",
        "zh_CN": "导出 JSON…",
        "zh_TW": "匯出 JSON…",
        "ko_KR": "JSON 내보내기…",
        "ja_JP": "JSON 書き出し…",
    },
    "w14.infer.col_rank": {
        "en_US": "Rank",
        "zh_CN": "序",
        "zh_TW": "序",
        "ko_KR": "순위",
        "ja_JP": "順位",
    },
    "w14.infer.col_template": {
        "en_US": "Template",
        "zh_CN": "模板",
        "zh_TW": "模板",
        "ko_KR": "템플릿",
        "ja_JP": "テンプレート",
    },
    "w14.infer.col_source": {
        "en_US": "Source",
        "zh_CN": "来源",
        "zh_TW": "來源",
        "ko_KR": "출처",
        "ja_JP": "出典",
    },
    "w14.infer.col_tonic": {
        "en_US": "Tonic (cents)",
        "zh_CN": "主音（音分）",
        "zh_TW": "主音（音分）",
        "ko_KR": "주음(센트)",
        "ja_JP": "主音（セント）",
    },
    "w14.infer.col_score": {
        "en_US": "Score",
        "zh_CN": "得分",
        "zh_TW": "得分",
        "ko_KR": "점수",
        "ja_JP": "スコア",
    },
    "w14.infer.col_margin": {
        "en_US": "Margin",
        "zh_CN": "领先幅度",
        "zh_TW": "領先幅度",
        "ko_KR": "격차",
        "ja_JP": "差",
    },
    "w14.infer.need_case": {
        "en_US": "Select one case in the list first.",
        "zh_CN": "请先在清单里选中一条案例。",
        "zh_TW": "請先在清單裡選中一條案例。",
        "ko_KR": "먼저 목록에서 사례를 하나 선택하세요.",
        "ja_JP": "先に一覧からケースを 1 件選択してください。",
    },
    "w14.infer.summary": {
        "en_US": "{n} candidates｜{frames} frames｜window {window}s｜templates {templates}",
        "zh_CN": "{n} 个候选｜{frames} 帧｜窗 {window}s｜模板 {templates}",
        "zh_TW": "{n} 個候選｜{frames} 幀｜窗 {window}s｜模板 {templates}",
        "ko_KR": "후보 {n}개｜{frames} 프레임｜창 {window}s｜템플릿 {templates}",
        "ja_JP": "候補 {n} 件｜{frames} フレーム｜窓 {window}s｜テンプレート {templates}",
    },
    "w14.infer.note": {
        "en_US": "Candidates ranked by score; the platform makes no 'conforms to' claim.",
        "zh_CN": "候选按得分排序；平台不作「符合某律」断言。",
        "zh_TW": "候選按得分排序；平台不作「符合某律」斷言。",
        "ko_KR": "후보는 점수순이며 플랫폼은 '준수'를 주장하지 않습니다.",
        "ja_JP": "候補はスコア順であり、プラットフォームは「適合」を主張しません。",
    },
    # --- PI-P6-PITCH-01 合成音高生成器（新增键一律五语齐）---
    "action.pitch_generator": {
        "en_US": "Pitch Generator…", "zh_CN": "合成音高生成器…", "zh_TW": "合成音高產生器…",
        "ko_KR": "합성 음높이 생성기…", "ja_JP": "合成音高ジェネレーター…",
    },
    "pitchgen.title": {
        "en_US": "Pitch Generator", "zh_CN": "合成音高生成器", "zh_TW": "合成音高產生器",
        "ko_KR": "합성 음높이 생성기", "ja_JP": "合成音高ジェネレーター",
    },
    "pitchgen.group.formal": {
        "en_US": "Formal standards (ISO / official)", "zh_CN": "正式标准（ISO / 官方）", "zh_TW": "正式標準（ISO／官方）",
        "ko_KR": "공식 표준(ISO / 공식)", "ja_JP": "正式規格（ISO／公式）",
    },
    "pitchgen.group.historical": {
        "en_US": "Historical pitches — NOT ISO standards", "zh_CN": "历史音高（非 ISO 标准）", "zh_TW": "歷史音高（非 ISO 標準）",
        "ko_KR": "역사적 음높이(ISO 표준 아님)", "ja_JP": "歴史的音高（ISO 規格ではない）",
    },
    "pitchgen.group.orchestral": {
        "en_US": "Orchestral conventions — NOT ISO standards", "zh_CN": "乐团惯例（非 ISO 标准）", "zh_TW": "樂團慣例（非 ISO 標準）",
        "ko_KR": "오케스트라 관습(ISO 표준 아님)", "ja_JP": "オーケストラ慣例（ISO 規格ではない）",
    },
    "pitchgen.box.standard": {
        "en_US": "Pitch standard", "zh_CN": "音高标准", "zh_TW": "音高標準",
        "ko_KR": "음높이 표준", "ja_JP": "音高規格",
    },
    "pitchgen.box.tone": {
        "en_US": "Note & parameters", "zh_CN": "音符与参数", "zh_TW": "音符與參數",
        "ko_KR": "음표 및 매개변수", "ja_JP": "音符とパラメータ",
    },
    "pitchgen.box.readout": {
        "en_US": "Live readout", "zh_CN": "实时读数", "zh_TW": "即時讀數",
        "ko_KR": "실시간 판독값", "ja_JP": "リアルタイム読取値",
    },
    "pitchgen.standard": {
        "en_US": "Standard", "zh_CN": "标准", "zh_TW": "標準",
        "ko_KR": "표준", "ja_JP": "規格",
    },
    "pitchgen.note": {
        "en_US": "Note", "zh_CN": "音名", "zh_TW": "音名",
        "ko_KR": "음명", "ja_JP": "音名",
    },
    "pitchgen.octave": {
        "en_US": "Octave", "zh_CN": "八度", "zh_TW": "八度",
        "ko_KR": "옥타브", "ja_JP": "オクターブ",
    },
    "pitchgen.duration": {
        "en_US": "Duration (s)", "zh_CN": "时长 (s)", "zh_TW": "時長 (s)",
        "ko_KR": "지속 시간 (s)", "ja_JP": "長さ (s)",
    },
    "pitchgen.sample_rate": {
        "en_US": "Sample rate (Hz)", "zh_CN": "采样率 (Hz)", "zh_TW": "取樣率 (Hz)",
        "ko_KR": "샘플링 레이트 (Hz)", "ja_JP": "サンプリング周波数 (Hz)",
    },
    "pitchgen.amplitude": {
        "en_US": "Amplitude", "zh_CN": "音量", "zh_TW": "音量",
        "ko_KR": "음량", "ja_JP": "音量",
    },
    "pitchgen.waveform": {
        "en_US": "Waveform", "zh_CN": "波形", "zh_TW": "波形",
        "ko_KR": "파형", "ja_JP": "波形",
    },
    "pitchgen.waveform.sine": {
        "en_US": "Sine", "zh_CN": "正弦", "zh_TW": "正弦",
        "ko_KR": "사인파", "ja_JP": "正弦波",
    },
    "pitchgen.waveform.harmonic": {
        "en_US": "Harmonic", "zh_CN": "谐波", "zh_TW": "諧波",
        "ko_KR": "고조파", "ja_JP": "倍音",
    },
    "pitchgen.depth": {
        "en_US": "Bit depth", "zh_CN": "位深", "zh_TW": "位元深度",
        "ko_KR": "비트 심도", "ja_JP": "ビット深度",
    },
    "pitchgen.depth.pcm16": {
        "en_US": "16-bit PCM", "zh_CN": "16 位 PCM", "zh_TW": "16 位元 PCM",
        "ko_KR": "16비트 PCM", "ja_JP": "16-bit PCM",
    },
    "pitchgen.depth.pcm24": {
        "en_US": "24-bit PCM", "zh_CN": "24 位 PCM", "zh_TW": "24 位元 PCM",
        "ko_KR": "24비트 PCM", "ja_JP": "24ビット PCM",
    },
    "pitchgen.depth.float32": {
        "en_US": "32-bit float", "zh_CN": "32 位浮点", "zh_TW": "32 位元浮點",
        "ko_KR": "32비트 부동소수점", "ja_JP": "32-bit float",
    },
    "pitchgen.fade": {
        "en_US": "Fade in/out (s)", "zh_CN": "淡入淡出 (s)", "zh_TW": "淡入淡出 (s)",
        "ko_KR": "페이드 인/아웃 (s)", "ja_JP": "フェードイン／アウト (s)",
    },
    "pitchgen.frequency": {
        "en_US": "Frequency", "zh_CN": "频率", "zh_TW": "頻率",
        "ko_KR": "주파수", "ja_JP": "周波数",
    },
    "pitchgen.cents": {
        "en_US": "Cents vs A440", "zh_CN": "相对 A440 音分", "zh_TW": "相對 A440 音分",
        "ko_KR": "A440 대비 음분", "ja_JP": "A440 との音分差",
    },
    "pitchgen.source": {
        "en_US": "Sources", "zh_CN": "依据来源", "zh_TW": "依據來源",
        "ko_KR": "출처", "ja_JP": "出典",
    },
    "pitchgen.caveat": {
        "en_US": "Caveat", "zh_CN": "注意事项", "zh_TW": "注意事項",
        "ko_KR": "주의 사항", "ja_JP": "注意事項",
    },
    "pitchgen.preview": {
        "en_US": "Waveform preview (first 20 ms)", "zh_CN": "波形预览（前 20 ms）", "zh_TW": "波形預覽（前 20 ms）",
        "ko_KR": "파형 미리보기(처음 20 ms)", "ja_JP": "波形プレビュー（先頭 20 ms）",
    },
    "pitchgen.btn.export": {
        "en_US": "Export WAV", "zh_CN": "导出 WAV", "zh_TW": "匯出 WAV",
        "ko_KR": "WAV 내보내기", "ja_JP": "WAV 書き出し",
    },
    "pitchgen.btn.load": {
        "en_US": "Load into workspace", "zh_CN": "载入工作区", "zh_TW": "載入工作區",
        "ko_KR": "작업 공간에 불러오기", "ja_JP": "ワークスペースに読み込む",
    },
    "pitchgen.btn.close": {
        "en_US": "Close", "zh_CN": "关闭", "zh_TW": "關閉",
        "ko_KR": "닫기", "ja_JP": "閉じる",
    },
    "pitchgen.saved": {
        "en_US": "WAV saved: {path}", "zh_CN": "已导出 WAV：{path}", "zh_TW": "已匯出 WAV：{path}",
        "ko_KR": "WAV 저장됨: {path}", "ja_JP": "WAV を保存しました: {path}",
    },
    "pitchgen.loaded": {
        "en_US": "Loaded into workspace: {name}", "zh_CN": "已载入工作区：{name}", "zh_TW": "已載入工作區：{name}",
        "ko_KR": "작업 공간에 불러옴: {name}", "ja_JP": "ワークスペースに読み込みました: {name}",
    },
    "pitchgen.err.export": {
        "en_US": "Export failed: {error}", "zh_CN": "导出失败：{error}", "zh_TW": "匯出失敗：{error}",
        "ko_KR": "내보내기 실패: {error}", "ja_JP": "書き出し失敗: {error}",
    },
    "pitchgen.err.load": {
        "en_US": "Load failed: {error}", "zh_CN": "载入失败：{error}", "zh_TW": "載入失敗：{error}",
        "ko_KR": "불러오기 실패: {error}", "ja_JP": "読み込み失敗: {error}",
    },
    "pitchgen.filter": {
        "en_US": "WAV (*.wav)", "zh_CN": "WAV (*.wav)", "zh_TW": "WAV (*.wav)",
        "ko_KR": "WAV (*.wav)", "ja_JP": "WAV (*.wav)",
    },
    # --- PI-P7-PREC-A T02/T03：不确定度显示（三语齐；ko/ja 同步补齐以守 parity 单调闸）---
    "region_stats.r_uncertainty": {
        "en_US": "Pitch uncertainty ±{u} cent (effective n {n})",
        "zh_CN": "音高不确定度 ±{u} 音分（有效帧数 {n}）",
        "zh_TW": "音高不確定度 ±{u} 音分（有效幀數 {n}）",
        "ko_KR": "음고 불확실도 ±{u} 센트 (유효 프레임 {n})",
        "ja_JP": "音高不確かさ ±{u} セント（有効フレーム {n}）",
    },
    "measure_result.full_u": {
        "en_US": "Δt {dt} s | ΔHz {df} | Δcent {dc} ± {u} | ratio {ratio}",
        "zh_CN": "Δt {dt} s | ΔHz {df} | Δ音分 {dc} ± {u} | 频率比 {ratio}",
        "zh_TW": "Δt {dt} s | ΔHz {df} | Δ音分 {dc} ± {u} | 頻率比 {ratio}",
        "ko_KR": "Δt {dt} s | ΔHz {df} | Δcent {dc} ± {u} | 비율 {ratio}",
        "ja_JP": "Δt {dt} s | ΔHz {df} | Δcent {dc} ± {u} | 比率 {ratio}",
    },
    # --- PI-P7-PREC-B T05：区间统计测量记录导出（三语齐；ko/ja 同步补齐
    #     以守 test_i18n_parity_guard_up3.py 单调闸：新增键若缺 ko/ja 会把
    #     gap 从 930 抬到 932 > 基线，与批 A T02/T03 追加键同款口径）---
    "region_stats.export": {
        "en_US": "Export Measurement…", "zh_CN": "导出测量记录…", "zh_TW": "匯出測量記錄…",
        "ko_KR": "측정 기록 내보내기…", "ja_JP": "測定記録の書き出し…",
    },
    "region_stats.exported": {
        "en_US": "Measurement exported: {name}", "zh_CN": "测量记录已导出：{name}", "zh_TW": "測量記錄已匯出：{name}",
        "ko_KR": "측정 기록 내보냄: {name}", "ja_JP": "測定記録を書き出しました: {name}",
    },
}


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------

def set_language(lang: str) -> None:
    """设置当前语言。"""
    global _current_lang
    if lang in LANGUAGES:
        _current_lang = lang


def get_language() -> str:
    """获取当前语言代码。"""
    return _current_lang


def tr(key: str, default: str | None = None) -> str:
    """翻译一个 key 到当前语言。

    Args:
        key: 翻译键（如 "menu.file"）
        default: 找不到时的回退文本，None 时返回 key 本身

    Returns:
        翻译后的字符串
    """
    entry = _STRINGS.get(key)
    if entry is None:
        return default if default is not None else key
    text = entry.get(_current_lang)
    if text:
        return text
    # 回退到英文
    text = entry.get(DEFAULT_LANG)
    return text if text else (default if default is not None else key)


def tr_list(*keys: str) -> list[str]:
    """批量翻译多个 key，返回列表。"""
    return [tr(k) for k in keys]


def available_languages() -> dict[str, str]:
    """返回可用语言字典 {code: display_name}。"""
    return dict(LANGUAGES)
