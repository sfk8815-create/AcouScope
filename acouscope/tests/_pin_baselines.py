# SPDX-License-Identifier: GPL-3.0-only
"""测侧冻结计数基线（T-1095 集中化）。

本档是**测试侧**「计数冻结 pin」的唯一数值源：各守卫测一律 `==` 本档常量。
集中前，每次图标扩容或新增定时器都要逐档追改 N 处硬编码（T-1086 漏改→T-1088 补、
T-1093 险破）；集中后扩容器只需 ①先取授权 ②改本档一处常量并在此登记扩容史。

★ 守卫语义红线：`==` 不得放宽为 `>=`——放宽即失去「防擅自扩容 / 防 chrome 段滥用」意图。

ICONS 逻辑名扩容史（集中自原散在 8 处守卫档的注释）：
  - 基线 21 名（T-1025 之前）。
  - T-1025 授权扩容 21→30：新增 9 名 —— track / add_track / solo / mute /
    align / volume / room_modal / room_acoustic / chart_designer。
  - T-1084 授权扩容 30→31：新增 tuning_ruler（音律标尺）。
  - T-1098 授权扩容 31→33：新增 mode_single / mode_grid（呈现模式「一图 / 多图」图标）。
  - T-1109 授权扩容 33→34：新增 audio_device（设置·音频设备标签图标）。
  - T-1111 授权扩容 34→35：新增 encourage（主窗常驻「支持一下」入口）。
  - T-1112 授权扩容 35→36：新增 weixin_group（主窗常驻「微信群」入口）。
  - 再扩容须先获授权，随后 +1 本档常量并在此登记。

main_window.py 全文静态计数（原钉于 test_chrome_panel_toggles）：
  - MAINWINDOW_QDIALOG_COUNT = 0：禁绝模态对话框（`==0` 经常量仍表禁绝）。
  - MAINWINDOW_QTHREAD_COUNT = 0：禁绝裸线程（同上）。
  - MAINWINDOW_QTIMER_COUNT = 8：定时器白名单基数（T-1048 开工实读基线，
    T-1086 多轨播放定时器 +1 ⇒ 7→8，T-1088 同步）。
"""

ICONS_LOGICAL_NAME_COUNT = 36
MAINWINDOW_QTIMER_COUNT = 8
MAINWINDOW_QDIALOG_COUNT = 0
MAINWINDOW_QTHREAD_COUNT = 0

# ---------------------------------------------------------------------------
# T-1096 追加：非图标类「真·双站」冻结计数（集中自散落 pin）
# ---------------------------------------------------------------------------

# 每语 MANUAL 帮助节数（<h3> 计数·T-1091 §20 音律标尺新节之后）。
# 两站同源：test_help_content_t1091 断三语各 == 本值；test_menu_chart_designer_t1094
# 断全文 <h3> == 本值 × len(LANGS)。加节只需改本常量一处。
# 前提：QUICK_START 及两 dict 之外 <h3> 恒为 0（现盘全文 60 = 20 × 3）；
# 若将来 QUICK_START 引入 <h3>，两站计数必不一致 → 判据自动红（耦合自校），无须放宽。
HELP_SECTIONS_PER_LANG = 20

# multitrack_view.py 内 analyzeRequested.connect 恰 1 处（防追加连接式双触发）。
# 两站同数同文件：test_multitrack_analysis_task 与 test_multitrack_view。
MULTITRACK_ANALYZE_REQUEST_CONNECTS = 1

# main_window.py 内**确认框类**（破坏性/确认 `QMessageBox.question(`）白名单余数 = 2
# （录音完成 + 模型未安装）。注意非 `QMessageBox.` 泛用总数（同文件现盘 21 处·
# 含 information/warning/StandardButton 等）。迁移每减一处改此一处；
# `test_toast_migration_a` 与 `test_record_settings_drawer` 两站随动。
MAINWINDOW_QMESSAGEBOX_CONFIRM_COUNT = 2