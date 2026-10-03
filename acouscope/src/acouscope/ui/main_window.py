# SPDX-License-Identifier: GPL-3.0-only
"""主窗口模块。"""

from __future__ import annotations

import json

from pathlib import Path

import numpy as np

from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QTextBrowser,
    QHBoxLayout,
    QSplitter,
    QToolBar,
    QStatusBar,
    QFileDialog,
    QMessageBox,
    QLabel,
    QPushButton,
    QProgressBar,
    QApplication,
    QStackedWidget,
    QTabBar,
    QToolButton,
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QKeySequence

from acouscope.app.controller import AppController
from acouscope.audio.editing import EditingController, EditError
from acouscope.utils.log import get_logger
from acouscope.i18n import tr, tr_list, set_language, get_language, available_languages
from acouscope.ui.shortcuts import sc
from acouscope.ui.theme import get_icon
from acouscope.ui.widgets.encourage_button import EncourageButton
from acouscope.ui.widgets.weixin_group_button import WeixinGroupButton
from acouscope.ui.widgets.help_dialogs import MANUAL, QUICK_START, _format_shortcuts
from acouscope.ui.widgets.multitrack.analysis_source import (
    TrackResultCache, resolve_source,
)
from acouscope.ui.widgets.toast import show_toast
from acouscope.ui.widgets.task_center import (
    KIND_ANALYSIS,
    KIND_BATCH,
    KIND_DOWNLOAD,
    PROGRESS_INDETERMINATE,
    PROGRESS_TEXT,
    TASK_CENTER_PANEL_WIDTH,
    TaskCenter,
    TaskCenterPanel,
)
from acouscope.state import (
    bump_launch_count,
    ensure_first_run,
    should_show_sponsor_reminder,
)
from acouscope.ui.widgets.transport_bar import format_transport_clock

_log = get_logger("ui.main_window")


# CB-011 B-2：左图标栏宽度（Obsidian 风格窄条 44px，几何尺寸字面值；
# 颜色一律 theme 派生，禁硬编码 hex）
_RIBBON_WIDTH = 44

# T-1017：赞助致谢框延后拍数（毫秒）。正延迟 + 恢复确认 singleShot(0) 保证
# 二者错峰，不同帧抢焦点；恢复确认若为模态 exec，本拍数须待其关闭后才触发。
_SPONSOR_PROMPT_DELAY_MS = 800

# UP-2b：启动自动更新检查拍数（毫秒）。两条例由：
# ⒜ 晚于赞助框拍数（800ms）——保证首次运行征询模态框不被压在非模态赞助框
#    之后，源序与时间序一致；⒝ 5s 正延迟——使测试套在「show 主窗后无 ≥5s
#    事件循环」时不会触发真网络（该前提由 UP-2b 判据③-4 现场取证）。
_UPDATE_CHECK_DELAY_MS = 5000

# T-1044：图表设计器「全局默认」落盘去抖（毫秒）——参数拖动时避免每拍刷盘
_CHART_DESIGNER_SAVE_DELAY_MS = 500


def _panel_toggle_button(
    parent, icon_name: str, tooltip: str, object_name: str
) -> QPushButton:
    """T-1048：主工具栏「左栏 / 右栏」面板开关（成对；icon-only + tooltip）。

    纯可见性语义（不切页）；激活态遵 ARCH §五-6「内凹」——checked 底色取
    ``colors()['bg0']``（比工具栏常态更暗），不铺 accent 实心。
    """
    from acouscope.ui.theme import style_when_theme

    b = QPushButton(parent)
    b.setObjectName(object_name)
    b.setCheckable(True)
    b.setIcon(get_icon(icon_name))
    b.setText("")  # icon-only：可发现性由 tooltip 承担（面板头另有关闭/动作出口）
    b.setToolTip(tooltip)
    b.setAutoDefault(False)
    style_when_theme(
        b,
        lambda c: f"QPushButton#{object_name}:checked {{ background: {c['bg0']}; }}",
    )
    return b


def _header_icon_button(parent, icon_name: str, tooltip: str, object_name: str) -> QToolButton:
    """T-1048：面板头右操作区图标钮（本面板自己的动作；icon-only + tooltip）。

    几何走 ``TOKENS.control.h_sm``；激活态遵 §五-6「内凹」（与面板内开关同口径）。
    """
    from PyQt6.QtCore import QSize

    from acouscope.ui.theme import TOKENS, style_when_theme

    side = TOKENS["control"]["h_sm"]
    b = QToolButton(parent)
    b.setObjectName(object_name)
    b.setIcon(get_icon(icon_name))
    b.setIconSize(QSize(side - TOKENS["spacing"]["sm"], side - TOKENS["spacing"]["sm"]))
    b.setFixedSize(QSize(side, side))
    b.setToolTip(tooltip)
    b.setAutoRaise(True)
    style_when_theme(
        b,
        lambda c: (
            f"QToolButton#{object_name} {{ background: transparent; "
            f"border: none; border-radius: {TOKENS['radius']['sm']}px; padding: 0; }}"
            f"QToolButton#{object_name}:hover {{ background: {c['btn_hover']}; }}"
            f"QToolButton#{object_name}:checked {{ background: {c['bg0']}; }}"
        ),
    )
    return b


# T-1002：视图菜单 7 项文案 key（顺序 = analysis_tab_bar 逻辑索引 0..6；
# 复用 cmb.* 键 → 菜单项文案与标签卡逐字一致，不新增第二份视图名）
_VIEW_MENU_KEYS = (
    "cmb.waveform", "cmb.fft", "cmb.spectrogram", "cmb.pitch",
    "cmb.formants", "cmb.timbre", "cmb.spectrogram3d",
)


def _normalize_region(region):
    """T-1019：分析区间 region 的类型守卫（防「region 类型污染」同类再犯）。

    契约（与波形 getter 一一对应，两者解耦）：
    - 分析区间 region：``tuple[float, float] | None``，即 ``[t0, t1]``
      （来源 ``WaveformWidget.get_selection()``）；
    - 标注区域对象：带 ``.start_time/.end_time`` 的对象（来源
      ``WaveformWidget.selected_region()``），**不得**作为 region 传入分析槽，
      仅供试听/循环/打点使用。

    守卫语义：非「长度为 2 的可转 float 序列」一律按 None 兜底（含 QAction
    直连误传的 bool、标注区域对象、长度异常者），使分析槽退化为全文件路径
    而不是抛 ``cannot unpack non-iterable bool object``。根因修复见
    ``_create_actions`` 中 QAction.triggered 的 λ 包装；本守卫是第二道防线。
    """
    if region is None:
        return None
    if isinstance(region, (tuple, list)) and len(region) == 2:
        try:
            return (float(region[0]), float(region[1]))
        except (TypeError, ValueError):
            return None
    return None


class _DownloadProgressPanel(QWidget):
    """SOTA 模型下载的内联进度面板（CB-003 G-2，D10 去模态化）。

    状态栏内联容器（QWidget，非模态、不阻塞调用方）：
    [状态文本 | QProgressBar | 取消按钮]。外观全部走全局 QSS/主题
    （QProgressBar/按钮样式由主题驱动），无硬编码 hex/px。
    取消语义保留：btn_cancel 点击 → canceled 信号，由宿主终止下载线程。
    """

    canceled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lbl_message = QLabel(self)
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.btn_cancel = QPushButton("取消", self)
        self.btn_cancel.clicked.connect(self.canceled)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.lbl_message)
        layout.addWidget(self.progress)
        layout.addWidget(self.btn_cancel)

    def set_backend(self, backend_name: str) -> None:
        """切换下载目标（复用面板时更新提示文本）。"""
        self.lbl_message.setText(f"下载 {backend_name} 模型…")


class MainWindow(QMainWindow):
    """AcouScope 主窗口。"""

    fileOpened = pyqtSignal(str)

    # T-1074 G1（承 T72-01）：播放 daemon 线程的错误回调不得直接建 QWidget。
    # 回调改为 emit 本信号；连接建立在主线程、接收者(self)属主线程 ⇒ Qt 自动
    # 走 QueuedConnection，show_toast 恒在主线程执行，消跨线程建 widget 的 UB。
    _mt_player_error = pyqtSignal(str)

    def __init__(self, controller: AppController):
        super().__init__()
        self.controller = controller

        # 初始化语言
        lang = getattr(controller.settings, "language", "en_US")
        set_language(lang if lang in available_languages() else "en_US")
        self._init_lang = get_language()

        # T-921：应用 A4 参考频率（默认 440.0 时各换算函数输出与改动前逐位一致）
        from acouscope.dsp.units import set_reference_hz

        set_reference_hz(getattr(controller.settings, "reference_hz", 440.0))

        self.setWindowTitle(f"AcouScope - {tr('app.name_cn')}" if get_language() == "zh_CN" else "AcouScope")
        self.setMinimumSize(1000, 700)

        # 恢复窗口大小
        settings = controller.settings
        self.resize(settings.window_width, settings.window_height)

        # UI 组件
        self._create_actions()
        self._create_menu_bar()
        self._create_toolbar()
        self._create_central_widget()
        self._create_status_bar()
        self._setup_editing()
        self._update_edit_actions()

        # 播放定时器
        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._update_playback_position)
        self._play_timer.setInterval(33)  # ~30 FPS 播放头平滑

        # T-323 播放联动：播放跟随滚动状态（默认开；用户手动平移后置 False，
        # 播放头再次越过可视右缘才恢复）与 scrub 节流记录
        self._follow_enabled = True
        self._scrub_last_at = 0.0
        # T-326 Pδ：两点测量结果状态（复用选区；A/B 标记 + 状态栏临时段）
        self._measure_active = False
        self._measure_status_text = None
        # T-324 试听选区：一次播完即停的选区尾时刻（None=无试听会话）
        self._preview_end: float | None = None
        # T-325 播放打点：连击去重单调钟（None=无）与最近打点时刻（撤销定位用）
        self._last_annotate_mono: float | None = None
        self._last_annotate_time: float | None = None

        # 分析异步执行：代数计数防陈旧回调，结果缓存避免重复重算
        self._analysis_gen = 0
        self._analysis_workers: list = []
        # T-928：任务进度中心（调度层常驻；面板与状态栏 toggle 懒建）
        # 并发/排队上限取自设置（越界已由 Settings.load 钳位回默认）
        self.task_center = TaskCenter(
            self,
            max_concurrency=getattr(controller.settings, "task_center_max_concurrency", 1),
            queue_limit=getattr(controller.settings, "task_center_queue_limit", 32),
        )
        self.task_center.taskRejected.connect(self._on_task_center_rejected)
        self.task_center.queueChanged.connect(self._refresh_task_center_toggle)
        self._task_center_panel: TaskCenterPanel | None = None
        self._restore_task_center_state = self._load_task_center_state()
        # T-1040：恢复任务中心显隐（只读档不建面板；走既有 _toggle_task_center 懒建路径）
        if self._restore_task_center_state is not None \
                and self._restore_task_center_state.get("visible") is True:
            self.btn_task_center.setChecked(True)
        self._download_task_id: str | None = None
        self._batch_task_id: str | None = None
        self._result_cache: dict = {}
        # T-321: 结果缓存分级治理——区间结果 ≤ 10、全文件结果 ≤ 12（全文件常驻优先）
        self._cache_region_limit = 10
        self._cache_full_limit = 12

        # 录音器
        self._recorder = None
        # T-1054 批4c：record_settings_panel 由 _build_record_settings_page 构建期置位
        # （其后不得再赋 None，否则面板属性被清空 → accepted 启动录音失效）
        self._record_timer = QTimer(self)
        self._record_timer.timeout.connect(self._update_record_ui)
        self._record_timer.setInterval(33)  # ~30 FPS 平滑滚动

        # 全局快捷键
        self._setup_shortcuts()

        # T-322: 项目自动保存与异常恢复（脏标记 + 周期 autosave + 恢复探测）
        self._setup_project_autosave()

        # T-929: 内存防护与防崩（预检 / 模型闲置卸载 / 压力兜底；检测失败静默跳过）
        self._setup_memguard()

    # ------------------------------------------------------------------
    # T-929: 内存防护与防崩（memguard；检测仅"读"，异常一律静默跳过）
    # ------------------------------------------------------------------

    def _setup_memguard(self) -> None:
        """启动期接线：阈值取自设置（K2 钳位后），周期巡检（闲置卸载 + 压力兜底）。"""
        from acouscope.system import memguard

        self._memguard_mod = memguard
        low, critical, idle_minutes = memguard.thresholds_from_settings(
            getattr(self.controller, "settings", None)
        )
        self._memguard_low_mb = low
        self._memguard_critical_mb = critical
        self._memguard_unloader = memguard.ModelIdleUnloader(idle_minutes=idle_minutes)
        self._memguard_pressure = memguard.MemoryPressureMonitor(critical_mb=critical)
        self._memguard_last_preflight = None
        self._memguard_prompt_ids: list[str] = []
        self._last_analysis_task_id: str | None = None
        self._memguard_timer = QTimer(self)
        self._memguard_timer.setInterval(2000)  # 巡检周期：压力"持续 >5s"判定精度
        self._memguard_timer.timeout.connect(self._on_memguard_tick)
        self._memguard_timer.start()

    def _on_memguard_tick(self) -> None:
        """周期巡检：模型闲置卸载（分析在跑时跳过）+ 压力兜底（限频，见 memguard §5）。"""
        unloader = getattr(self, "_memguard_unloader", None)
        if unloader is None:
            return
        try:
            busy = bool(self.task_center.is_busy())
        except Exception:  # noqa: BLE001
            busy = False
        try:
            unloader.poll(busy=busy)
        except Exception:  # noqa: BLE001
            pass
        monitor = getattr(self, "_memguard_pressure", None)
        if monitor is None:
            return
        try:
            fire = bool(monitor.poll())
        except Exception:  # noqa: BLE001
            fire = False
        if fire:
            self._memguard_fallback()

    def _memguard_fallback(self) -> None:
        """兜底（§5）：先释放压力序列（先轨后模型），再复用 T-322 写快照路径 + 非模态警告。"""
        guard = getattr(self, "_memguard_mod", None)
        if guard is not None:
            try:
                try:
                    busy = bool(self.task_center.is_busy())
                except Exception:  # noqa: BLE001
                    busy = True  # 取 busy 失败：保守口径，只卸轨、禁卸模型
                guard.relieve_pressure(
                    getattr(self, "multitrack_session", None),
                    unload_models=not busy,
                )
            except Exception:  # noqa: BLE001
                pass
        try:
            self._on_autosave_tick()  # 只读复用（脏标记 + 已命名/未命名两路径语义不变）
        except Exception:  # noqa: BLE001
            self._autosave_failure_once()
        try:
            show_toast(
                self, tr("memguard.pressure_warning"), level="warning", duration=8000
            )
        except Exception:  # noqa: BLE001
            pass

    def _memguard_preflight(self, kind: str) -> bool:
        """长任务启动前内存预检（§2）。返回 True = 默认继续（「仍继续」，风险自担）。

        检测失败 / 内存充足 → **静默** True（永不阻塞用户操作）；低内存 → 非模态
        提示（K6）：toast 文案 + 任务中心条目动作承载「取消」，零 QDialog/模态。
        """
        guard = getattr(self, "_memguard_mod", None)
        if guard is None:
            return True
        try:
            result = guard.preflight(getattr(self.controller, "settings", None))
        except Exception:  # noqa: BLE001
            return True
        if not result.is_low:
            return True
        self._memguard_last_preflight = result
        self._show_memguard_prompt(result, kind)
        return True

    def _show_memguard_prompt(self, result, kind: str) -> None:
        """低内存非模态提示：toast（文案）+ 任务中心条目（「取消」动作，非模态内联）。"""
        mb = int(result.available_mb or 0)
        try:
            msg = tr("memguard.low").format(mb=mb, threshold=result.low_mb)
            show_toast(
                self, f"{msg} {tr('memguard.continue')}", level="warning", duration=8000
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            # 同一时刻至多保留一条低内存提示条目（防重复触发堆积）
            for stale in list(self._memguard_prompt_ids):
                try:
                    self.task_center.finish(stale, ok=True)
                except Exception:  # noqa: BLE001
                    pass
            self._memguard_prompt_ids.clear()
            entry = self.task_center.register(
                tr("memguard.prompt_title").format(mb=mb),
                kind=KIND_ANALYSIS,
                progress_mode=PROGRESS_TEXT,
                cancellable=True,
                cancel_action=lambda: self._on_memguard_cancel(kind),
            )
            self._memguard_prompt_ids.append(entry.task_id)
        except Exception:  # noqa: BLE001
            pass

    def _on_memguard_cancel(self, kind: str) -> None:
        """「取消」：经既有取消通道中止本次长任务（K8 不另立锁/队列）。

        分析类任务走 `task_center.cancel` 既有语义；批处理为**同步执行、无中断
        通道**（T-928 既定语义）→ 仅关闭提示（已在报告 deviations 登记）。
        """
        if kind != "analysis":
            return
        task_id = getattr(self, "_last_analysis_task_id", None)
        if not task_id:
            return
        try:
            self.task_center.cancel(task_id)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # T-322: 项目自动保存与异常恢复（两级轻量数据保护，不自动保存音频数据）
    # ------------------------------------------------------------------

    def _setup_project_autosave(self) -> None:
        """初始化自动保存：脏标记 + 周期定时器 + 标注变更接线 + 恢复探测。"""
        self._project_dirty = False
        self._autosave_warned = False
        self._autosave_interval_s = 120  # 周期自动保存间隔（秒，可调常量）
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._on_autosave_tick)
        self._autosave_timer.setInterval(self._autosave_interval_s * 1000)
        self._autosave_restore = self._detect_restorable_snapshot()
        self._bind_annotation_dirty()

    def _bind_annotation_dirty(self) -> None:
        """标注变更 → 置脏（统一入口：共享 AnnotationModel 变更回调，勿散点手置）。"""
        try:
            model = self.waveform_widget.annotations
        except AttributeError:
            return
        if model is not None:
            model.add_listener(self._mark_project_dirty)

    def _mark_project_dirty(self) -> None:
        """置脏：标注/项目结构等需落盘的变更（选区/播放位置不经此入口）。"""
        self._project_dirty = True

    def _autosave_dir(self) -> Path:
        """autosave 快照目录（用户数据目录下，不入项目 git 跟踪）。"""
        from acouscope.utils.config import get_data_dir

        return get_data_dir() / "autosave"

    def _latest_autosave_snapshot(self, max_age_s=86400.0):
        """最近一份快照路径；无快照或超龄（默认 24h）返回 None。"""
        import time as _time

        d = self._autosave_dir()
        if not d.is_dir():
            return None
        snaps = sorted(
            d.glob("autosave_*.acouproj"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not snaps:
            return None
        if max_age_s is not None and (
            _time.time() - snaps[0].stat().st_mtime
        ) > max_age_s:
            return None
        return snaps[0]

    def _detect_restorable_snapshot(self):
        """启动探测：有 clean 标志视为正常退出 → 不提示；否则返回可恢复快照。"""
        d = self._autosave_dir()
        if (d / "clean.flag").exists():
            return None
        return self._latest_autosave_snapshot()

    def _on_autosave_tick(self) -> None:
        """周期自动保存：有未保存变更且存在可保存项目时才落盘。"""
        if not getattr(self, "_project_dirty", False):
            return
        if not self.controller.has_audio() and self.controller.project.filepath is None:
            return
        try:
            if self.controller.project.filepath is not None:
                self._save_project_to(self.controller.project.filepath)
            else:
                self._write_autosave_snapshot()
            self._project_dirty = False
        except Exception:
            self._autosave_failure_once()

    def _autosave_failure_once(self) -> None:
        """自动保存失败：仅一次温和提示（禁反复弹窗、零终端）。"""
        if self._autosave_warned:
            return
        self._autosave_warned = True
        try:
            show_toast(self, tr("autosave.fail_once"), level="warning")
        except Exception:
            pass

    def _save_project_to(self, filepath) -> None:
        """核心保存（无 UI 副作用；手动/自动共用，成功后由调用方清脏）。"""
        marks = self._collect_harmonic_marks()
        self.controller.save_project(
            filepath,
            annotations=marks,
            grid_model=getattr(self, "_pitch_grid_model", None),
        )

    def _write_autosave_snapshot(self) -> None:
        """未命名项目写 autosave 快照（as_snapshot：不改变项目命名路径），保留最近 1 份。"""
        from datetime import datetime

        d = self._autosave_dir()
        d.mkdir(parents=True, exist_ok=True)
        target = d / f"autosave_{datetime.now().strftime('%Y%m%d_%H%M%S')}.acouproj"
        marks = self._collect_harmonic_marks()
        self.controller.save_project(
            target,
            annotations=marks,
            grid_model=getattr(self, "_pitch_grid_model", None),
            as_snapshot=True,
        )
        for snap in d.glob("autosave_*.acouproj"):
            if snap != target:
                try:
                    snap.unlink()
                except OSError:
                    pass

    def _clean_exit_autosave(self) -> None:
        """正常退出闭环：清理快照 + 写干净标志（防止下次启动误提示恢复）。

        仅在本会话确实用过 autosave 目录时落盘；无关场景零文件副作用。
        """
        from datetime import datetime

        d = self._autosave_dir()
        if not d.is_dir():
            return
        for snap in d.glob("autosave_*.acouproj"):
            try:
                snap.unlink()
            except OSError:
                pass
        try:
            (d / "clean.flag").write_text(
                datetime.now().isoformat(timespec="seconds"), encoding="utf-8"
            )
        except OSError:
            pass

    def _prompt_restore_autosave(self) -> None:
        """异常退出恢复确认（仅启动探测命中且窗口可见时）。

        用既有白名单组件 QMessageBox（显式构造 + exec）；不复用 question
        工厂函数——T-504f 计数守卫要求该用法保持既有 2 处。
        """
        snap = getattr(self, "_autosave_restore", None)
        if snap is None or not self.isVisible():
            return
        if (self._autosave_dir() / "clean.flag").exists():
            return
        from PyQt6.QtWidgets import QMessageBox

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("autosave.restore_title"))
        box.setText(tr("autosave.restore_body"))
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Discard
        )
        ret = box.exec()
        if ret == QMessageBox.StandardButton.Yes:
            self._restore_from_snapshot(snap)
        else:
            try:
                snap.unlink()
            except OSError:
                pass

    def _restore_from_snapshot(self, snap: Path) -> None:
        """从 autosave 快照恢复项目（音频缺失时 info=None，由用户手动打开）。"""
        try:
            project, info = self.controller.load_project(snap)
            if info is not None:
                self._sync_after_open(info)
            self._update_window_title(project.name)
            self.lbl_status.setText("已从自动保存快照恢复项目")
            self._project_dirty = False
        except Exception as e:
            show_toast(self, f"恢复自动保存失败:\n{str(e)}", level="error")

    def showEvent(self, event) -> None:
        """首次显示时：启动周期自动保存；恢复提示延后一拍，不打断首次打开。"""
        super().showEvent(event)
        if getattr(self, "_first_show_done", False):
            return
        self._first_show_done = True
        # T-322: 窗口可见才启动周期定时器；恢复提示延后一拍，不打断首次打开
        timer = getattr(self, "_autosave_timer", None)
        if timer is not None and not timer.isActive():
            timer.start()
        QTimer.singleShot(0, self._prompt_restore_autosave)
        # T-1017/T-1110：首次运行时间落盘（纯装机记录；已存在则不覆盖），
        # 启动计数 +1（第 5 次启动起每次均弹）；再以正延迟排入赞助致谢框判定
        # ——与恢复确认错峰，禁同帧抢焦点
        ensure_first_run()
        bump_launch_count()
        QTimer.singleShot(_SPONSOR_PROMPT_DELAY_MS, self._maybe_show_sponsor_dialog)
        # UP-2b：AD-12 自动路径挂载点·每启动至多排一次（`_first_show_done` 闸门
        # :616-618）·每日至多一次由 `state.should_run_update_check()` 裁决
        QTimer.singleShot(_UPDATE_CHECK_DELAY_MS,
                          lambda: self._on_check_updates(manual=False))

    def _maybe_show_sponsor_dialog(self) -> None:
        """启动后自动弹赞助致谢框——**第 5 次启动起、此后每次启动均弹**（T-1110 反转 #3）。

        - 判定闸在 :func:`acouscope.state.should_show_sponsor_reminder`：
          仅「已支持，不再提醒」永久停弹；否则启动次数达标（≥5）即弹；
        - 进程内闸门 ``self._sponsor_prompt_shown`` 防同一启动内重复弹（不落盘）；
        - 非模态（``setModal(False)`` + ``show()``），不阻塞主界面；
        - 触发点由 showEvent 以正延迟 singleShot 排入事件循环，恢复确认
          （singleShot(0) 或模态 exec）必然先行，二者不同帧抢焦点。
        """
        if getattr(self, "_sponsor_prompt_shown", False):
            return
        if not should_show_sponsor_reminder():
            return
        self._sponsor_prompt_shown = True
        from acouscope.ui.widgets.sponsor_dialog import SponsorDialog

        self._sponsor_dialog = SponsorDialog(self)
        self._sponsor_dialog.show()

    def _on_show_sponsor(self) -> None:
        """帮助菜单常驻入口：打开/复用非模态赞助致谢框（主动打开不消耗自动弹名额）。"""
        dlg = getattr(self, "_sponsor_dialog", None)
        if dlg is None or not dlg.isVisible():
            from acouscope.ui.widgets.sponsor_dialog import SponsorDialog

            dlg = SponsorDialog(self)
            self._sponsor_dialog = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _on_show_weixin_group(self) -> None:
        """打开/复用非模态微信群二维码窗（T-1112）。"""
        dlg = getattr(self, "_weixin_dialog", None)
        if dlg is None or not dlg.isVisible():
            from acouscope.ui.widgets.weixin_group_dialog import WeixinGroupDialog

            dlg = WeixinGroupDialog(self)
            self._weixin_dialog = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _on_check_updates(self, manual: bool = True) -> None:
        """帮助菜单「检查更新」入口（只通知·零下载·零替换）。

        三条语义（逐字）：

        - **节流只约束自动路径**：``manual=True``（菜单点击）绕过节流；
          ``manual=False``（自动路径）受 :func:`state.should_run_update_check` 每日一次约束。
        - **开关对两条路径一律生效**：开关为 ``False``（或首次征询答「否」）时，
          手动入口也**不**发起请求，并给 ``disabled`` 文案（不静默吞掉点击）。
        - **在飞闸门先于每日节流**（UP-2b）：线程在飞时重入点击**静默 return**
          （零反馈）；★ 必须排在 :func:`state.should_run_update_check` **之前**——
          该函数会为自动路径写盘今日日期、消费「当日一次」名额，闸门若在其后，
          重入点击会白吃掉当日配额（当日再也不会自动检查）。

        未决策（开关键缺失）时先走首次征询；**未答复前不发任何网络请求**。
        """
        from acouscope import state
        from acouscope import update_checker

        # 在飞闸门（UP-2b）：取线程对象的在飞判定（而非「标志位 + 槽内清零」）——
        # run() 异常退出未 emit 时标志位会永挂（本会话再不发检查）；线程结束后
        # 该判定自动放行。
        running = getattr(self, "_update_worker", None)
        if running is not None and running.isRunning():
            return
        if not manual and not state.should_run_update_check():
            return  # 自动路径：开关关 / 同日已查 ⇒ 静默返回（零 fetch）
        enabled = state.is_update_check_enabled()
        if enabled is None:
            enabled = self._ask_update_check_optin()
        if enabled is not True:
            self.statusBar().showMessage(tr("update.disabled"), 8000)
            return
        worker = update_checker.UpdateCheckWorker(self)
        worker.finished_with.connect(self._on_update_checked)
        self._update_worker = worker
        worker.start()

    def _ask_update_check_optin(self) -> bool:
        """首次运行征询（AD-12：默认开 + 只问一次）；答复落盘后返回是否开启。

        ★ 用现盘既有白名单形 ``QMessageBox(self)``（**非**静态 ``.question(``），
        不破 ``MAINWINDOW_QMESSAGEBOX_CONFIRM_COUNT`` 常量钉。
        """
        from acouscope import state

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("update.ask_title"))
        box.setText(tr("update.ask_body"))
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        accepted = box.exec() == QMessageBox.StandardButton.Yes
        state.set_update_check_enabled(accepted)
        return accepted

    def _on_update_checked(self, code: str, new_version: str) -> None:
        """更新检查结果 → **非模态**提示（statusBar；零新对话框）。

        ``ok`` 时文案含新版本号与 ``notes_url``，并把链接复制到剪贴板（只给链接与
        复制，**禁自动打开浏览器**）；失败两态用温和文案（禁「更新失败/重试」字样）。
        """
        from acouscope import update_checker

        if code == update_checker.CODE_OK:
            notes_url = getattr(self._update_worker, "notes_url", "") or ""
            message = tr("update.status_ok").format(version=new_version)
            if notes_url:
                message = f"{message}  {notes_url}"
                QApplication.clipboard().setText(notes_url)
            self.statusBar().showMessage(message, 15000)
        elif code == update_checker.CODE_UP_TO_DATE:
            self.statusBar().showMessage(tr("update.up_to_date"), 8000)
        elif code == update_checker.CODE_NO_NETWORK:
            self.statusBar().showMessage(tr("update.no_network"), 8000)
        elif code == update_checker.CODE_MALFORMED:
            self.statusBar().showMessage(tr("update.malformed"), 8000)
        elif code == update_checker.CODE_DISABLED:
            self.statusBar().showMessage(tr("update.disabled"), 8000)

    # ------------------------------------------------------------------
    # UI 创建
    # ------------------------------------------------------------------

    def _create_actions(self):
        """创建动作。"""

        # 文件
        self.action_open = QAction(tr("action.open"), self)
        self.action_open.setShortcut(QKeySequence.StandardKey.Open)
        self.action_open.setIcon(get_icon("open"))
        self.action_open.triggered.connect(self._on_open_file)

        self.action_quit = QAction(tr("action.quit"), self)
        self.action_quit.setShortcut(QKeySequence.StandardKey.Quit)
        self.action_quit.triggered.connect(self.close)

        # 分析
        # T-1019：QAction.triggered(bool checked) 若直连分析槽，checked(False) 会成为
        # region 的位置实参 → 槽内 `t0, _t1 = region` 抛 cannot unpack non-iterable
        # bool object（六个分析入口全中，菜单/快捷键进入即失败）。故统一经 λ 吞掉
        # checked，恒以「region 缺省 = None（全文件）」调用。
        self.action_fft = QAction(tr("action.fft"), self)
        self.action_fft.setShortcut("F2")
        self.action_fft.triggered.connect(lambda _checked=False: self._on_fft_analysis())

        self.action_spectrogram = QAction(tr("action.spectrogram"), self)
        self.action_spectrogram.setShortcut("F3")
        self.action_spectrogram.triggered.connect(
            lambda _checked=False: self._on_spectrogram_analysis()
        )

        self.action_pitch = QAction(tr("action.pitch"), self)
        self.action_pitch.setShortcut("F4")
        self.action_pitch.triggered.connect(lambda _checked=False: self._on_pitch_analysis())

        self.action_formants = QAction(tr("action.formants"), self)
        self.action_formants.setShortcut("F5")
        self.action_formants.triggered.connect(
            lambda _checked=False: self._on_formant_analysis()
        )

        self.action_timbre = QAction(tr("action.timbre"), self)
        self.action_timbre.setShortcut("F6")
        self.action_timbre.triggered.connect(lambda _checked=False: self._on_timbre_analysis())

        self.action_spectrogram3d = QAction(tr("action.spectrogram3d"), self)
        self.action_spectrogram3d.setShortcut("F7")
        self.action_spectrogram3d.triggered.connect(
            lambda _checked=False: self._on_spectrogram3d_analysis()
        )

        # T-326 Pδ：两点测量（复用选区；无快捷键，避免与既有键位冲突）
        self.action_measure_selection = QAction(tr("measure_selection"), self)
        self.action_measure_selection.setObjectName("measure_selection")
        self.action_measure_selection.triggered.connect(self._on_measure_selection)

        self.action_measure_clear = QAction(tr("measure_clear"), self)
        self.action_measure_clear.setObjectName("measure_clear")
        self.action_measure_clear.triggered.connect(self._on_measure_clear)

        # T-327 Pε：选区区间统计；T-1090 增量补键 Ctrl+Shift+S（⌘S 已被保存占用）
        self.action_region_stats = QAction(tr("region_stats"), self)
        self.action_region_stats.setObjectName("region_stats")
        self.action_region_stats.setShortcut("Ctrl+Shift+S")
        self.action_region_stats.triggered.connect(self._on_region_stats)

        # T-922：音律标尺叠加层（可勾选；模板经子菜单切换，状态只在会话内）
        self.tuning_ruler_template_key: str | None = None  # None = 未选模板
        self.action_tuning_ruler = QAction(tr("action.tuning_ruler"), self)
        self.action_tuning_ruler.setObjectName("tuning_ruler")
        self.action_tuning_ruler.setShortcut("F9")
        self.action_tuning_ruler.setCheckable(True)
        self.action_tuning_ruler.setIcon(get_icon("tuning_ruler"))
        self.action_tuning_ruler.toggled.connect(self._on_tuning_ruler_toggled)

        # 房间声学工具（T-1043：持续态抽屉入口 → 开关语义，§五b）
        self.action_room_modes = QAction("房间模态分析…", self)
        self.action_room_modes.setShortcut("F8")
        self.action_room_modes.setCheckable(True)
        self.action_room_modes.toggled.connect(self._on_room_modes)

        self.action_room_acoustics = QAction("房间声学工具（Sabine/IR/RT60）…", self)
        self.action_room_acoustics.setCheckable(True)
        self.action_room_acoustics.toggled.connect(self._on_room_acoustics)

        # 项目
        self.action_open_project = QAction(tr("action.open_project"), self)
        self.action_open_project.setShortcut("Ctrl+Shift+O")
        self.action_open_project.triggered.connect(self._on_open_project)

        self.action_save_project = QAction(tr("action.save_project"), self)
        self.action_save_project.setShortcut(QKeySequence.StandardKey.Save)
        self.action_save_project.triggered.connect(self._on_save_project)

        self.action_save_project_as = QAction(tr("action.save_as"), self)
        self.action_save_project_as.triggered.connect(self._on_save_project_as)

        # 导出
        self.action_export = QAction(tr("action.export"), self)
        self.action_export.setShortcut("Ctrl+E")
        self.action_export.triggered.connect(self._on_export_figure)

        self.action_export_audio = QAction("导出音频文件…", self)
        self.action_export_audio.triggered.connect(self._on_export_audio)

        # AI
        self.action_ai_interpret = QAction(tr("action.ai_interpret"), self)
        self.action_ai_interpret.setShortcut("Ctrl+I")
        self.action_ai_interpret.triggered.connect(self._on_ai_interpret)

        # 设置（T-1043：产生持续态界面（左栏设置页）→ 开关语义，参 N5 切页口径）
        self.action_settings = QAction(tr("settings.title"), self)
        self.action_settings.setShortcut("Ctrl+,")
        self.action_settings.setCheckable(True)
        self.action_settings.toggled.connect(self._on_settings)

        self.action_chart_font = QAction(tr("action.chart_font"), self)
        self.action_chart_font.setToolTip(
            tr("action.chart_font")
        )
        self.action_chart_font.setCheckable(True)
        # T-1054 批2 单宿主：action_chart_font 不再开抽屉，改走泛化槽切右栏「图表字体」页
        #（不再登记为抽屉入口；抽屉基础设施保留待批4）
        self.action_chart_font.toggled.connect(self._on_chart_font_settings)

        # T-1044：图表设计器（导出前设计交互）→ 非模态抽屉 = 持续态界面 → 开关语义
        # （ARCH_ui_visual_language §五b）；菜单与工具栏**共用同一 QAction 实例**
        # → 勾选态天然一致，禁写第二套同步逻辑。
        self.action_chart_designer = QAction(tr("action.chart_designer"), self)
        self.action_chart_designer.setShortcut("F10")
        self.action_chart_designer.setIcon(get_icon("chart_designer"))
        self.action_chart_designer.setToolTip(tr("action.chart_designer"))
        self.action_chart_designer.setCheckable(True)
        self.action_chart_designer.toggled.connect(self._on_chart_designer)

        # 帮助族入口（T-1054 批4b：快速入门/用户手册 → 左栏页 index1/2，与页签钮同组互斥）
        self.action_quickstart = QAction(tr("action.quickstart"), self)
        self.action_quickstart.setCheckable(True)
        self.action_quickstart.toggled.connect(
            lambda c: self._on_left_page_toggled(c, 1)
        )

        self.action_manual = QAction(tr("action.manual"), self)
        self.action_manual.setCheckable(True)
        self.action_manual.toggled.connect(
            lambda c: self._on_left_page_toggled(c, 2)
        )

        self.action_about = QAction(tr("action.about"), self)
        self.action_about.triggered.connect(self._on_about)

        # T-1015：访问网站（帮助菜单 / 工具栏 LOGO / 左图标栏网站入口共用）
        self.action_visit_site = QAction(tr("action.visit_site"), self)
        self.action_visit_site.triggered.connect(self._on_visit_site)

        # UP-2：检查更新（帮助菜单；只通知·零下载）。★ 菜单点击 = 手动入口，
        # 绕过节流但**不绕过开关**（故显式 manual=True，不直接接 triggered 的 bool）。
        self.action_check_updates = QAction(tr("action.check_updates"), self)
        self.action_check_updates.setObjectName("actionCheckUpdates")
        self.action_check_updates.triggered.connect(
            lambda: self._on_check_updates(manual=True)
        )

        # ------- 波形编辑（Audacity 风格） -------
        self.action_undo = QAction(tr("edit.undo"), self)
        self.action_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.action_undo.triggered.connect(self._on_edit_undo)

        self.action_redo = QAction(tr("edit.redo"), self)
        self.action_redo.setShortcut(QKeySequence.StandardKey.Redo)
        self.action_redo.triggered.connect(self._on_edit_redo)

        self.action_cut = QAction(tr("edit.cut"), self)
        self.action_cut.setShortcut(QKeySequence.StandardKey.Cut)
        self.action_cut.triggered.connect(self._on_edit_cut)

        self.action_copy = QAction(tr("edit.copy"), self)
        self.action_copy.setShortcut(QKeySequence.StandardKey.Copy)
        self.action_copy.triggered.connect(self._on_edit_copy)

        self.action_paste = QAction(tr("edit.paste"), self)
        self.action_paste.setShortcut(QKeySequence.StandardKey.Paste)
        self.action_paste.triggered.connect(self._on_edit_paste)

        self.action_delete = QAction(tr("edit.delete"), self)
        # Mac 键盘的 delete 键发送 Backspace，两种键值都绑定
        self.action_delete.setShortcuts([
            QKeySequence(Qt.Key.Key_Delete),
            QKeySequence(Qt.Key.Key_Backspace),
        ])
        self.action_delete.triggered.connect(self._on_edit_delete)

        self.action_silence = QAction(tr("edit.silence"), self)
        self.action_silence.setShortcut(sc("Ctrl+L"))
        self.action_silence.triggered.connect(self._on_edit_silence)

        self.action_trim = QAction(tr("edit.trim"), self)
        self.action_trim.setShortcut(sc("Ctrl+T"))
        self.action_trim.triggered.connect(self._on_edit_trim)

        self.action_select_all = QAction(tr("edit.select_all"), self)
        self.action_select_all.setShortcut(QKeySequence.StandardKey.SelectAll)
        self.action_select_all.triggered.connect(self._on_edit_select_all)

        self.action_select_none = QAction(tr("edit.select_none"), self)
        # CB-013 D-1：Esc 从本 action 解绑 → 统一由 ShortcutManager 的 "escape"
        # 全局快捷键处理（有选区先取消选区，无选区停止播放，见 _on_escape）。
        self.action_select_none.triggered.connect(self._on_edit_select_none)

        self.action_zoom_sel = QAction(tr("edit.zoom_sel"), self)
        self.action_zoom_sel.setShortcut("Shift+Z")
        self.action_zoom_sel.triggered.connect(self._on_edit_zoom_sel)

        # ------- T-1002：菜单信息架构新增动作 -------
        # 文件
        self.action_new_project = QAction(tr("action.new_project"), self)
        self.action_new_project.setShortcut("Ctrl+N")
        self.action_new_project.triggered.connect(self._on_new_project)

        # 文件·导出▸报告 HTML（T-1003 接线：槽 = _on_export_report；
        # T-1109 IM-32：菜单入口收敛至预览页按钮，action 保留供预览页调用）
        self.action_export_report = QAction(tr("action.export_report"), self)
        self.action_export_report.setObjectName("export_report")
        self.action_export_report.triggered.connect(
            lambda _checked=False: self._on_export_report()
        )
        self.action_export_report.setEnabled(False)

        # 文件·导出▸报告 PDF（T-1102 M-B′-β1 接线：槽 = _on_export_report_pdf，
        # T-1109 IM-32：菜单入口收敛至预览页按钮，action 保留供预览页调用）
        self.action_export_report_pdf = QAction(tr("action.export_report_pdf"), self)
        self.action_export_report_pdf.setObjectName("export_report_pdf")
        self.action_export_report_pdf.triggered.connect(
            lambda _checked=False: self._on_export_report_pdf()
        )
        self.action_export_report_pdf.setEnabled(False)

        # 文件·导出▸报告预览（T-1103 M-B′-β2 + T-1109 IM-32 整合：唯一报告菜单入口，
        # Ctrl+Shift+P 改挂此处；进 index5 预览页，HTML/PDF/关闭皆从预览页出）
        self.action_report_preview = QAction(tr("action.report_preview"), self)
        self.action_report_preview.setObjectName("report_preview")
        self.action_report_preview.setShortcut("Ctrl+Shift+P")
        self.action_report_preview.triggered.connect(
            lambda _checked=False: self._show_report_preview()
        )
        self.action_report_preview.setEnabled(False)

        # 视图：7 项 checkable 单选（radio 组）——只镜像 analysis_tab_bar 切换路径
        self.view_action_group = QActionGroup(self)
        self.view_action_group.setExclusive(True)
        self._view_actions: list[QAction] = []
        for _idx, _key in enumerate(_VIEW_MENU_KEYS):
            _act = QAction(tr(_key), self)
            _act.setObjectName(f"view_menu_{_idx}")
            _act.setCheckable(True)
            _act.triggered.connect(
                lambda _checked=False, _i=_idx: self._on_view_menu_selected(_i)
            )
            self.view_action_group.addAction(_act)
            self._view_actions.append(_act)

        # 视图·绘图导航：适应窗口复用既有 _on_zoom_fit；复位两键委派视图既有实现
        self.action_view_fit = QAction(tr("menu.view_all"), self)
        self.action_view_fit.setObjectName("view_menu_fit")
        self.action_view_fit.triggered.connect(lambda _checked=False: self._on_zoom_fit())

        self.action_view_reset_x = QAction(tr("menu.reset_x"), self)
        self.action_view_reset_x.setObjectName("view_menu_reset_x")
        self.action_view_reset_x.triggered.connect(
            lambda _checked=False: self._on_view_reset_axis()
        )

        self.action_view_reset_view = QAction(tr("menu.reset_view"), self)
        self.action_view_reset_view.setObjectName("view_menu_reset_view")
        self.action_view_reset_view.triggered.connect(
            lambda _checked=False: self._on_view_reset_view()
        )

        # 分析
        # T-1002：菜单项「分析此区域」（T-915 波形右键信号同槽；无选区时 enable=False）
        self.action_analyze_region = QAction(tr("action.analyze_region"), self)
        self.action_analyze_region.setObjectName("analyze_region")
        self.action_analyze_region.setShortcut("Ctrl+Shift+R")
        self.action_analyze_region.triggered.connect(self._on_menu_analyze_region)

        # 分析·多轨对比（T-1004 批 8B M1：可勾选入口——勾选=进入轨道区（多轨只读
        # 对比态），取消=退出回单轨主态；文本沿用「多轨对比…」。零快捷键，避免
        # 与既有键位冲突（快捷键唯一性扫描）。）
        self.action_multitrack_compare = QAction(tr("action.multitrack_compare"), self)
        self.action_multitrack_compare.setObjectName("multitrack_compare")
        self.action_multitrack_compare.setCheckable(True)
        self.action_multitrack_compare.setToolTip(tr("multitrack.action_tip"))
        self.action_multitrack_compare.toggled.connect(self._on_multitrack_toggled)

        # 工具
        # T-1002：批处理入口（enable 由 BatchWorkspace 注册表非空驱动，见
        # _update_menu_actions；T-913/914 已注册元数据模块 → 可用）
        self.action_batch = QAction(tr("action.batch"), self)
        self.action_batch.setObjectName("batch")
        self.action_batch.triggered.connect(
            lambda _checked=False: self._open_batch_workspace()
        )

        # 工具·标注模式（T-924/925 留位：禁用占位，零槽函数）
        self.action_annotation_mode = QAction(tr("action.annotation_mode"), self)
        self.action_annotation_mode.setObjectName("annotation_mode")
        self.action_annotation_mode.setEnabled(False)

        # 工具·恢复默认布局（需 workspace/PanelContainer 侧 reset API，本任务
        # 改动面不含该模块 → 留位：禁用占位，零槽函数）
        self.action_restore_layout = QAction(tr("action.restore_layout"), self)
        self.action_restore_layout.setObjectName("restore_layout")
        self.action_restore_layout.setEnabled(False)

    def _create_menu_bar(self):
        """创建菜单栏（T-1002：7 菜单 = 文件 / 编辑 / 视图 / 分析 / 工具 / 设置 / 帮助）。"""
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu(tr("menu.file"))
        file_menu.addAction(self.action_open)
        file_menu.addAction(self.action_new_project)
        file_menu.addAction(self.action_open_project)
        # 「最近打开」（可选）：需 recent-files 持久化，不在本任务改动面 → 未列项（report 注记）
        file_menu.addAction(self.action_save_project)
        file_menu.addAction(self.action_save_project_as)
        file_menu.addSeparator()

        # 导出子菜单：图表 / 音频 / 田野元数据 / 报告预览（T-1109 IM-32 整合）
        export_menu = file_menu.addMenu(tr("menu.export"))
        export_menu.addAction(self.action_export)
        export_menu.addSeparator()
        export_menu.addAction(self.action_export_audio)
        export_menu.addSeparator()

        # V099_EXPORT_UI_V1: 田野元数据导出
        export_metadata_act = export_menu.addAction("导出田野元数据 (IMDI/CSV)")
        export_metadata_act.triggered.connect(self._export_field_metadata)
        # T-1109 IM-32：报告三入口收敛为一条「报告预览…」
        export_menu.addAction(self.action_report_preview)

        file_menu.addSeparator()
        file_menu.addAction(self.action_quit)

        # 编辑菜单（Audacity 风格波形编辑）
        edit_menu = menubar.addMenu(tr("menu.edit"))
        edit_menu.addAction(self.action_undo)
        edit_menu.addAction(self.action_redo)
        edit_menu.addSeparator()
        edit_menu.addAction(self.action_cut)
        edit_menu.addAction(self.action_copy)
        edit_menu.addAction(self.action_paste)
        edit_menu.addAction(self.action_delete)
        edit_menu.addSeparator()
        edit_menu.addAction(self.action_silence)
        edit_menu.addAction(self.action_trim)
        edit_menu.addSeparator()
        edit_menu.addAction(self.action_select_all)
        edit_menu.addAction(self.action_select_none)
        edit_menu.addAction(self.action_zoom_sel)

        # 视图菜单（T-1002 新）：7 项单选只镜像 analysis_tab_bar 切换路径（零第二套状态机）
        view_menu = menubar.addMenu(tr("menu.view"))
        for view_act in self._view_actions:
            view_menu.addAction(view_act)
        view_menu.addSeparator()
        # T-1002：适应窗口复用既有 _on_zoom_fit；复位两键委派当前视图既有实现
        view_menu.addAction(self.action_view_fit)
        view_menu.addAction(self.action_view_reset_x)
        view_menu.addAction(self.action_view_reset_view)
        self._sync_view_menu(0)  # 初值（标签卡未建 → 默认 0，建卡后由切换路径回勾）

        # 分析菜单
        analysis_menu = menubar.addMenu(tr("menu.analysis"))
        # T-1002：命令式入口（分析此区域 = T-915 同槽）；区间统计 = T-327 既有
        analysis_menu.addAction(self.action_analyze_region)
        analysis_menu.addAction(self.action_region_stats)
        analysis_menu.addAction(self.action_measure_selection)
        analysis_menu.addAction(self.action_measure_clear)
        # T-1004 留位：多轨对比（禁用占位）
        analysis_menu.addAction(self.action_multitrack_compare)
        analysis_menu.addSeparator()
        # 模块分析命令（FFT/语谱图/音高/共振峰/音色/3D）
        analysis_menu.addAction(self.action_fft)
        analysis_menu.addAction(self.action_spectrogram)
        analysis_menu.addAction(self.action_pitch)
        analysis_menu.addAction(self.action_formants)
        analysis_menu.addAction(self.action_timbre)
        analysis_menu.addAction(self.action_spectrogram3d)
        analysis_menu.addSeparator()
        analysis_menu.addAction(self.action_room_modes)
        analysis_menu.addAction(self.action_room_acoustics)
        analysis_menu.addSeparator()
        # AI 释图：既有槽 → 右栏 AI tab（ARCH_sidebar_ai_panel T-1010 路由，零新逻辑）
        analysis_menu.addAction(self.action_ai_interpret)

        # 工具菜单（T-1002 新）
        tools_menu = menubar.addMenu(tr("menu.tools"))
        tools_menu.addAction(self.action_batch)          # enable 由注册表非空驱动
        # T-922：音律标尺叠加层开关 + 音律模板子菜单（默认 12TET，会话内状态）
        tools_menu.addAction(self.action_tuning_ruler)
        self.menu_tuning_template = tools_menu.addMenu(tr("menu.tuning_template"))
        self.menu_tuning_template.setObjectName("tuningTemplateMenu")
        self._rebuild_tuning_template_menu()
        # T-1044 入口①：图表设计器（T-1094 由「文件▸导出」归入本菜单·紧随音律标尺一族后
        # =律/图工具相邻；置于模板子菜单之后以免拆散标尺↔模板配对）。工具栏入口②不变。
        tools_menu.addAction(self.action_chart_designer)
        tools_menu.addAction(self.action_annotation_mode)  # T-924/925 留位
        tools_menu.addSeparator()
        tools_menu.addAction(self.action_restore_layout)   # 留位（见动作定义处注记）

        # 设置菜单：全局性设置统一收纳
        # （T-1001「外观>图标风格」已在设置面板「界面」tab 内实现，此处不重复入口；
        #   菜单项「设置」经 _on_settings → 左栏「设置」tab（T-1010））
        settings_menu = menubar.addMenu(tr("menu.settings"))
        settings_menu.addAction(self.action_settings)
        settings_menu.addAction(self.action_chart_font)

        # 帮助菜单
        help_menu = menubar.addMenu(tr("menu.help"))
        help_menu.addAction(self.action_quickstart)
        help_menu.addAction(self.action_manual)
        # T-1002：快捷键总览（子菜单，展开时实时重建；不用第二份快捷键清单）
        self.menu_shortcuts_overview = help_menu.addMenu(tr("action.shortcuts_overview"))
        self.menu_shortcuts_overview.setObjectName("shortcutsOverviewMenu")
        self.menu_shortcuts_overview.aboutToShow.connect(self._rebuild_shortcuts_overview)
        help_menu.addSeparator()
        # T-1015：访问网站（快速入门/用户手册之后、关于之前）
        help_menu.addAction(self.action_visit_site)
        # UP-2：检查更新（访问网站之后、关于之前；顺序写死）
        help_menu.addAction(self.action_check_updates)
        help_menu.addAction(self.action_about)
        # T-1082：常驻支持入口（紧邻「关于」之后；复用既有非模态 SponsorDialog）
        self.action_sponsor = QAction(tr("action.sponsor"), self)
        self.action_sponsor.setObjectName("actionSponsor")
        self.action_sponsor.triggered.connect(self._on_show_sponsor)
        help_menu.addAction(self.action_sponsor)

    def _create_toolbar(self):
        """创建工具栏。"""
        # 文件工具栏（主工具栏：新建/打开项目 + 打开音频 + 撤销/重做/导出 + 批处理
        # + 右栏展开折叠；T-1002 增补项目三按钮与批处理入口）
        file_toolbar = QToolBar(tr("toolbar.file"), self)
        file_toolbar.setMovable(False)
        # T-1002：按钮风格统一（主/分析工具栏同为 TextBesideIcon，禁混合）
        file_toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.action_new_project.setIcon(get_icon("files"))
        self.action_open_project.setIcon(get_icon("open"))
        self.action_save_project.setIcon(get_icon("save"))
        self.action_batch.setIcon(get_icon("layers"))
        self.action_undo.setIcon(get_icon("undo"))
        self.action_redo.setIcon(get_icon("redo"))
        self.action_export.setIcon(get_icon("export"))
        file_toolbar.addAction(self.action_new_project)
        file_toolbar.addAction(self.action_open_project)
        file_toolbar.addAction(self.action_save_project)
        file_toolbar.addSeparator()
        file_toolbar.addAction(self.action_open)
        file_toolbar.addSeparator()
        file_toolbar.addAction(self.action_undo)
        file_toolbar.addAction(self.action_redo)
        file_toolbar.addSeparator()
        file_toolbar.addAction(self.action_export)
        file_toolbar.addSeparator()
        # T-1054 批0：批处理从工具栏撤下，改为主工具栏「工作区开关组」的可见
        # checkable 开关（见下）；action_batch 本体/图标/菜单项/_update_menu_actions
        # 的 enable 绑定保持不动，此处仅移除工具栏 addAction。
        file_toolbar.addSeparator()

        # T-1048：主工具栏成对「左栏 / 右栏」面板开关（纯可见性，不切页）。
        # 左栏开关（btn_toggle_left_panel）≠ T-1012 已删的 ribbon 开关（旧名不再出现）：
        # ribbon 仍常驻不可关，本开关只折叠/展开左栏 PanelContainer。
        self.btn_toggle_left_panel = _panel_toggle_button(
            file_toolbar, "sidebar_left", tr("toolbar.toggle_left_panel"), "toggleLeftPanelBtn"
        )
        self.btn_toggle_left_panel.setChecked(False)  # 左栏默认折叠（workspace 缺省态）
        self.btn_toggle_left_panel.toggled.connect(self._on_toggle_left_panel)
        file_toolbar.addWidget(self.btn_toggle_left_panel)

        # T-1012：右侧图标栏（ribbon）常驻不可关；右栏 toggle（checkable，与右栏
        # PanelContainer 折叠态联动；图标 get_icon + i18n tooltip）。
        # T-1048：图标 inspect（放大镜，语义错配）→ sidebar_right（面板图元）
        self.btn_toggle_right_panel = _panel_toggle_button(
            file_toolbar, "sidebar_right", tr("toolbar.toggle_right_panel"), "toggleRightPanelBtn"
        )
        self.btn_toggle_right_panel.setChecked(True)  # 右栏默认展开
        self.btn_toggle_right_panel.toggled.connect(self._on_toggle_right_panel)
        file_toolbar.addWidget(self.btn_toggle_right_panel)

        # T-1054 批0：主工具栏「工作区开关组」——中央全铺页切换（紧接左右栏开关，
        # 前置分隔符与「面板可见性」两钮分区）。唯一状态源 _set_workspace_page 统管
        # 开关与右键入口（R1），禁出现"右键进批处理后工具栏开关没亮"的分裂状态。
        # 四钮全部启用（点→对应全铺页，再点→回 index0，R2）：批处理 index1 /
        # 房间模态 index2 / 房间声学 index3 / 图表设计器 index4（T-1054 批4a 收口，
        # 原「禁用占位」已清零）。
        file_toolbar.addSeparator()
        self.btn_toggle_batch_workspace = _panel_toggle_button(
            file_toolbar, "layers", tr("action.batch"), "toggleBatchWorkspaceBtn"
        )
        self.btn_toggle_batch_workspace.clicked.connect(
            lambda _checked=False: self._on_workspace_toggle("batch")
        )
        file_toolbar.addWidget(self.btn_toggle_batch_workspace)

        self.btn_toggle_room_modal = _panel_toggle_button(
            file_toolbar, "room_modal", tr("toolbar.room_modal"), "toggleRoomModalBtn"
        )
        self.btn_toggle_room_modal.clicked.connect(
            lambda _checked=False: self._on_workspace_toggle("room_modal")
        )
        file_toolbar.addWidget(self.btn_toggle_room_modal)

        self.btn_toggle_room_acoustic = _panel_toggle_button(
            file_toolbar, "room_acoustic", tr("toolbar.room_acoustic"), "toggleRoomAcousticBtn"
        )
        self.btn_toggle_room_acoustic.clicked.connect(
            lambda _checked=False: self._on_workspace_toggle("room_acoustic")
        )
        file_toolbar.addWidget(self.btn_toggle_room_acoustic)

        self.btn_toggle_chart_designer = _panel_toggle_button(
            file_toolbar, "chart_designer", tr("toolbar.chart_designer"), "toggleChartDesignerBtn"
        )
        self.btn_toggle_chart_designer.clicked.connect(
            lambda _checked=False: self._on_workspace_toggle("chart_designer")
        )
        file_toolbar.addWidget(self.btn_toggle_chart_designer)

        # T-1033 P5：图标优先（逐按钮判据，见报告「改/不改表」）——
        # ① 高频且图标语义无歧义 → 纯图标 + tooltip（可发现性靠 tooltip 保持）；
        # ② 命名入口 / 低频 / 语义可能歧义 → 保留文字（项目三按钮与批处理）。
        # 口径：工具栏级 style 维持既有统一值（既有守卫
        # tests/test_menu_restructure.py::test_toolbar_button_style_unified 未改动），
        # 逐按钮显式覆盖 ToolButtonIconOnly。
        for _act, _tip_key in (
            (self.action_open, "action.open"),
            (self.action_undo, "edit.undo"),
            (self.action_redo, "edit.redo"),
            (self.action_export, "action.export"),
        ):
            _act.setToolTip(tr(_tip_key))
            _btn = file_toolbar.widgetForAction(_act)
            if _btn is not None:
                _btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        self.addToolBar(file_toolbar)

        # 分析工具栏（CB-011 B-1：功能区下拉已移除，改由 analysis_panel
        # 内容区左下方的横向标签卡 analysis_tab_bar 承载视图切换；
        # T-1002：布局决策 = 保留第二工具栏，AI 释图/后端选择器/音律标尺
        #   与文件编辑类高频钮分离，避免主工具栏过度拥挤）
        analysis_toolbar = QToolBar(tr("toolbar.analysis"), self)
        analysis_toolbar.setMovable(False)
        analysis_toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        self.btn_ai_interpret = QPushButton(tr("toolbar.ai"))
        self.btn_ai_interpret.setIcon(get_icon("ai"))
        self.btn_ai_interpret.setToolTip(tr("action.ai_interpret"))
        self.btn_ai_interpret.clicked.connect(self._on_ai_interpret)
        analysis_toolbar.addWidget(self.btn_ai_interpret)

        # V099_SOTA_UI_V1: 音高算法后端选择器
        try:
            backend_widget = self._create_backend_selector()
            analysis_toolbar.addWidget(backend_widget)
            _log.debug("[SOTA] backend selector added to toolbar")
        except Exception as _e:
            # T-1074 G3①（承 T72-05）：裸 print+traceback.print_exc 纳管日志；
            # exc_info=True 已含回溯，无需再 import traceback。
            _log.error("[SOTA][ERROR] backend selector failed: %s", _e, exc_info=True)

        # T-922：音律标尺叠加层开关（与分析菜单同 Action，勾选状态共享）
        analysis_toolbar.addAction(self.action_tuning_ruler)

        # T-1044 入口②：同一 QAction 实例挂到分析工具栏（当前视图可直接设计）
        # 范围护栏：只增一个 action，**不碰**工具栏样式与既有按钮。
        analysis_toolbar.addAction(self.action_chart_designer)

        self.addToolBar(analysis_toolbar)

        # Tips 条形区（主工具栏下方，定宽 24 汉字，超宽跑马灯）
        from acouscope.ui.widgets.tip_bar import TipBar

        tip_toolbar = QToolBar(tr("toolbar.tips"), self)
        tip_toolbar.setMovable(False)

        # 单一容器收纳 [提示条 | 弹簧 | LOGO]：QToolBar 布局只整体压缩
        # 该容器，不会把提示条单独丢进溢出菜单——提示条正常显示，
        # 窗口缩小时先压缩弹簧、再压缩提示条至没有，LOGO 永远可见
        tip_row = QWidget()
        row_layout = QHBoxLayout(tip_row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        self.tip_bar = TipBar()
        row_layout.addWidget(self.tip_bar)
        row_layout.addStretch(1)

        # T-1112：常驻「微信群」闪耀按钮（心跳图标左侧·点击开二维码窗·非模态）
        self.btn_weixin = WeixinGroupButton(self)
        self.btn_weixin.weixinRequested.connect(self._on_show_weixin_group)
        row_layout.addWidget(self.btn_weixin)

        # T-1111：常驻「支持一下」心跳按钮（LOGO 左侧·点击开赞助框·非模态）
        self.btn_encourage = EncourageButton(self)
        self.btn_encourage.encourageRequested.connect(self._on_show_sponsor)
        row_layout.addWidget(self.btn_encourage)

        # 工作室 LOGO 常驻本行最右：等比缩放、固定尺寸（20px 高，低于
        # 行高 28px 不抬升工具栏）；T-1015：可点击 → 主站
        from acouscope.ui.widgets.about_dialog import ClickableLabel, render_logo

        dpr = self.devicePixelRatioF()
        logo_pm = render_logo(int(20 * dpr))
        if logo_pm is not None:
            logo_pm.setDevicePixelRatio(dpr)
            self.lbl_logo = ClickableLabel()
            self.lbl_logo.setObjectName("mainLogo")
            self.lbl_logo.setPixmap(logo_pm)
            self.lbl_logo.setFixedSize(
                round(logo_pm.width() / dpr), round(logo_pm.height() / dpr)
            )
            self.lbl_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.lbl_logo.setToolTip(
                f"{tr('toolbar.logo_tip')} — {tr('action.visit_site')}"
            )
            self.lbl_logo.clicked.connect(self._on_visit_site)
            row_layout.addWidget(self.lbl_logo)

        tip_toolbar.addWidget(tip_row)

        self.addToolBar(tip_toolbar)

        # 轮换 8s；上下文提示临时接管 5s 后恢复轮换
        # tip.1~10 操作提示；tip.11~30 功能提示；tip.31~169 科研轻幽默
        self._tip_keys = [f"tip.{i}" for i in range(1, 61)]
        self._tip_index = 0
        self._tip_timer = QTimer(self)
        self._tip_timer.setInterval(8000)
        self._tip_timer.timeout.connect(self._rotate_tip)
        self._tip_resume = QTimer(self)
        self._tip_resume.setSingleShot(True)
        self._tip_resume.setInterval(5000)
        self._tip_resume.timeout.connect(self._tip_timer.start)
        self._rotate_tip()
        self._tip_timer.start()

    def _create_central_widget(self):
        """创建中央部件。"""
        central = QWidget()

        # CB-011 B-2：中央区外层由垂直布局改为 QHBoxLayout——
        # [left_ribbon（最左窄图标栏）| 右侧原水平三栏工作区（含中央垂直 splitter）]
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 4, 4, 4)
        layout.setSpacing(4)

        self.left_ribbon = self._create_left_ribbon()
        layout.addWidget(self.left_ribbon)

        # 分割器：上方波形，下方分析面板
        splitter = QSplitter(Qt.Orientation.Vertical)

        # 波形显示区域
        from acouscope.ui.widgets.waveform import WaveformWidget

        self.waveform_widget = WaveformWidget()

        self.waveform_widget.positionChanged.connect(self._on_wave_position_changed)
        self.waveform_widget.selectionChanged.connect(self._on_selection_changed)
        # T-916：波形右键「分析此区域」→ 当前激活分析视图对区间重算并重绘
        self.waveform_widget.analyzeRegionRequested.connect(self._on_analyze_region)
        self.waveform_widget.playheadSeek.connect(self._on_wave_playhead_seek)
        self.waveform_widget.tipRequested.connect(
            lambda key: self.show_tip(key, contextual=True)
        )
        self.waveform_widget.trimSilenceRequested.connect(
            self._on_trim_leading_silence
        )
        # CB-016-3：红针移动 → 检查器分析范围读数（独立于 positionChanged，
        # 后者连的是播放位置语义，复用会误跳播放头）
        self.waveform_widget.analysisPositionChanged.connect(
            self._on_analysis_position_changed_for_inspector
        )

        # 传输条（独立控件；先实例化供设备列表填充）
        from acouscope.ui.widgets.transport_bar import TransportBar

        self.transport_bar = TransportBar()

        # 填充录音输入设备列表
        self._populate_input_devices()

        # CB-010 P0-3：波形视图容器（与 waveform 同容器，顶部一行 TransportBar、
        # 下方 Waveform——仿 DAW 内嵌传输条；从 analysis_panel 底部迁出）。
        # 传输条随波形视图显隐的接线见 _sync_transport_visibility；TransportBar
        # 内部逻辑与信号连接保持不动。
        self.waveform_view = QWidget()
        wave_view_lay = QVBoxLayout(self.waveform_view)
        wave_view_lay.setContentsMargins(0, 0, 0, 0)
        wave_view_lay.setSpacing(0)
        wave_view_lay.addWidget(self.transport_bar)
        wave_view_lay.addWidget(self.waveform_widget, stretch=1)

        # T-1004：多轨态容器（第二态）挂载于波形区层级内部——保持
        # splitter.widget(0) is waveform_view / waveform_widget 父级不变
        # 的既有结构断言（单轨主态零变化）；默认隐藏，进入多轨态才显示
        # （见 _enter_multitrack_mode）。会话为视图态，不碰 controller 单文件语义。
        from acouscope.ui.widgets.multitrack.multitrack_view import MultitrackPanel
        from acouscope.ui.widgets.multitrack.track_model import MultitrackSession

        self.multitrack_session = MultitrackSession()
        self._multitrack_mode = False
        self._multitrack_player = None       # 懒建（只读复用 AudioPlayer）
        self._mt_play_timer = QTimer(self)
        self._mt_play_timer.setInterval(33)
        self._mt_play_timer.timeout.connect(self._update_multitrack_playhead)
        self._multitrack_sources_cache: list = []
        self.multitrack_panel = MultitrackPanel(self.multitrack_session)
        self.multitrack_panel.hide()
        self._multitrack_analysis_task_id: str | None = None
        # T-1009：多轨结果缓存域由主窗持有（跨呈现模式切换保留）；呈现带在面板内
        self.multitrack_result_cache = TrackResultCache()
        self.multitrack_panel.set_result_cache(self.multitrack_result_cache)
        self.multitrack_panel.set_analysis_deliver(self._deliver_multitrack_analysis)
        # T-1087 M6/M7/M5：对齐 / 差异量化 / 加轨包络 IO 走任务中心（共用投递适配器）
        self.multitrack_panel.set_align_deliver(self._deliver_multitrack_task)
        self.multitrack_panel.set_track_prepare_deliver(
            self._deliver_multitrack_task
        )
        self.multitrack_panel.compare_view.set_diff_deliver(
            self._deliver_multitrack_task
        )
        self.multitrack_panel.playRequested.connect(self._on_multitrack_play)
        self.multitrack_panel.stopRequested.connect(self._on_multitrack_stop)
        self.multitrack_panel.tracksChanged.connect(self._update_multitrack_status)
        self.multitrack_panel.currentTrackChanged.connect(
            self._on_multitrack_current_changed
        )
        self.multitrack_panel.playheadMoved.connect(self._on_multitrack_playhead)
        self.multitrack_panel.selectionChanged.connect(
            self._on_multitrack_selection
        )
        self.multitrack_panel.addFromBrowserRequested.connect(
            self._on_multitrack_add_from_browser
        )
        # T-1087 M1：轨道区退出钮 → 回单轨主态（复用既有 _exit_multitrack_mode 单点）
        self.multitrack_panel.exitRequested.connect(self._exit_multitrack_mode)
        # T-1087 M3（N4 hover）：多轨呈现带的悬停读数上抛状态栏临时段（同单轨 Pδ
        # 注入器·同一消费槽）。★ 只注 compare_view——波形区 MultitrackView.mouseMove
        # 无 hover 产出源（PI-T78 R-2），造读数属新增功能（越 `L-3`）。
        self._inject_hover_readout(self.multitrack_panel.compare_view)
        wave_view_lay.addWidget(self.multitrack_panel, stretch=1)
        # D9：主态拖入 = 打开该文件（多轨态拖入由轨道区容器自行消费）
        self.setAcceptDrops(True)

        splitter.addWidget(self.waveform_view)

        # 分析面板：常驻文件信息条 + 视图切换区
        from acouscope.ui.widgets.metadata_bar import MetadataBar

        self.analysis_panel = QWidget()
        analysis_layout = QVBoxLayout(self.analysis_panel)
        analysis_layout.setContentsMargins(0, 0, 0, 0)
        analysis_layout.setSpacing(4)

        # T-1033 P2：分析区面板头（共用构件 PanelHeader，ARCH §五-1）
        from acouscope.ui.widgets.panels.panel_header import attach_panel_header

        self.analysis_panel_header = attach_panel_header(
            self.analysis_panel, tr("toolbar.analysis")
        )

        self.metadata_bar = MetadataBar()
        analysis_layout.addWidget(self.metadata_bar)

        # 视图切换区（QStackedWidget：懒构建 + 常驻，切换零销毁、视图状态跨切换保留）
        self.view_container = QStackedWidget()
        self._view_widgets: dict[int, QWidget] = {}
        self._pending_view_index: int = 0
        self._restore_view_index = self._load_view_index()

        hint_page = QWidget()
        hint_layout = QVBoxLayout(hint_page)
        hint_layout.setContentsMargins(0, 0, 0, 0)

        # T-1033 P4：空态规范（ARCH §五-3）= 说明 + 主操作按钮 + 拖放提示，
        # 统一由共用构件 EmptyState 承载（居中、text_sub）
        from acouscope.ui.widgets.panels.empty_state import EmptyState

        self.analysis_empty_state = EmptyState(
            message=tr("status.open_audio"),
            action_text=tr("action.open"),
            drop_hint=tr("empty.drop_hint"),
        )
        self.analysis_empty_state.actionTriggered.connect(self._on_empty_state_open)
        hint_layout.addWidget(self.analysis_empty_state)
        self.view_container.addWidget(hint_page)  # 第 0 页：提示页（常驻）

        analysis_layout.addWidget(self.view_container, stretch=1)

        # CB-011 B-1：功能区横向标签卡（内容区左下方，替代原分析工具栏下拉）。
        # 7 标签顺序与逻辑视图索引一致：波形(0)/FFT(1)/语谱图(2)/音高(3)/
        # 共振峰(4)/音色(5)/3D(6)，标签文案沿用 cmb.* i18n key；
        # currentChanged → _on_analysis_changed 保持唯一切换入口
        # （切换仍触发 _sync_transport_visibility；蓝条叠加层同步已随
        # CB-016-1 移除）。
        # 先加满标签再接信号：避免 QTabBar 自动选中首标签时提前触发回调。
        self.analysis_tab_bar = QTabBar()
        self.analysis_tab_bar.setObjectName("analysisTabBar")
        for text in tr_list(
            "cmb.waveform", "cmb.fft", "cmb.spectrogram", "cmb.pitch",
            "cmb.formants", "cmb.timbre", "cmb.spectrogram3d",
        ):
            self.analysis_tab_bar.addTab(text)
        self.analysis_tab_bar.setExpanding(False)
        self.analysis_tab_bar.currentChanged.connect(self._on_analysis_changed)

        # 标签卡左对齐（左下方）：QHBox 收纳 + 右侧弹性留白
        tab_row = QHBoxLayout()
        tab_row.setContentsMargins(0, 0, 0, 0)
        tab_row.setSpacing(0)
        tab_row.addWidget(self.analysis_tab_bar)
        tab_row.addStretch(1)
        analysis_layout.addLayout(tab_row)

        # 连接传输条 Transport 信号（与原波形控件同名信号，槽函数签名不变）
        self.transport_bar.playToggled.connect(self._on_wave_play_toggled)
        self.transport_bar.playStop.connect(self._on_wave_play_stop)
        self.transport_bar.skipToStart.connect(self._on_wave_skip_start)
        self.transport_bar.skipToEnd.connect(self._on_wave_skip_end)
        self.transport_bar.recordToggled.connect(self._on_wave_record_toggled)
        self.transport_bar.loopToggled.connect(self._on_toggle_loop)
        self.transport_bar.speedChanged.connect(self._on_speed_changed)
        self.transport_bar.seekPreview.connect(self._on_slider_moved)
        self.transport_bar.seekCommit.connect(self._on_slider_released)

        splitter.addWidget(self.analysis_panel)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([200, 400])
        splitter.setHandleWidth(6)  # 加宽手柄便于拖动调整波形/分析区比例
        # T-1093 M-D：中央分隔条画成可辨识色带。**不碰 theme 全局 `QSplitter::handle`
        # 色值（§十二 R-1）**，改用本控件局部 QSS 覆盖；★ PI-T84 N-7：QSS 设在 handle
        # 自身不生效，落点＝splitter 本体 + objectName 选择器。色值经 theme.colors()
        # 运行时插值、由 style_when_theme 随主题切换重设（禁 hex 字面量）。
        splitter.setObjectName("centralVerticalSplitter")
        from acouscope.ui.theme import style_when_theme

        style_when_theme(
            splitter,
            lambda c: (
                "QSplitter#centralVerticalSplitter::handle"
                f" {{ background: {c['border_strong']}; }}"
            ),
        )

        # T-913：中央批处理模式——原垂直 splitter 外包 central_stack（双页）：
        #   index0 = 现有垂直 splitter（常规模式，行为零变化：波形上/分析面板下）；
        #   index1 = BatchWorkspace（波形随整页隐藏、中间全区批处理工作区）。
        # 进批处理/退出 仅切 index（见 _open/_exit_batch_workspace）；ws 返回结构
        # 保持兼容（restore/save_workspace 与 ws["left"/"right"] 均不受影响）。
        from acouscope.ui.widgets.batch_metadata_module import MetadataBatchModule
        from acouscope.ui.widgets.batch_workspace import BatchWorkspace, register_module
        from acouscope.ui.widgets.chart_designer import ChartDesignerPanel
        from acouscope.ui.widgets.panels.workspace import (
            build_workspace_splitter, make_layout_save_timer,
            restore_workspace, save_workspace,
        )

        self.central_stack = QStackedWidget()
        self.central_stack.setObjectName("centralStack")
        # T-1093 B-2：全铺页（index1-4）最小高封顶，口径同 _add_analysis_widget
        # （宽 0=不限，只压地板）。QStackedLayout 的 minimumSizeHint 恒取**全页并集
        # 最大**（实测 836×578），未封顶时任一页的自然 min 高都会顶住中央 splitter
        # 的可用高 ⇒ 切页把波形/分析区分界整体抬上去 = 窗体抖动。封顶后 stack 级
        # min 由 index0 自然值决定，切页恒定。
        _full_page_min_h = 200
        self.central_stack.addWidget(splitter)  # index0 常规模式
        self.batch_workspace = BatchWorkspace()
        self.batch_workspace.exitRequested.connect(self._exit_batch_workspace)
        self.batch_workspace.setMinimumSize(0, _full_page_min_h)  # index1 同口径封顶
        # T-928：批处理 → 任务进度中心聚合桥接（内联进度区保留为批处理专属
        # 明细；聚合条目只呈现阶段文本与终态，不重复进度条）
        self.batch_workspace.set_task_observer(self._on_batch_task_event)
        # T-914：批处理首个业务模块「批量更改元数据」——
        # 注册须发生在 ws.refresh_modules() 之前（同名覆盖为框架既定语义）；
        # 模块实例持有本次 ws（文件集/manager 来源），接线处保留引用供入口激活用。
        self.batch_metadata_module = MetadataBatchModule(self.batch_workspace)
        register_module(self.batch_metadata_module)
        self.batch_workspace.refresh_modules()
        self.central_stack.addWidget(self.batch_workspace)  # index1 批处理页

        # T-1054 批3：房间模态 / 房间声学 → 中央全铺页（index2/3）。
        # R3 页面零改造：外层容器 + 边距直接嵌入既有 widget（内部一行不改）。
        from acouscope.ui.widgets.room_modes import RoomModesWidget
        from acouscope.ui.widgets.room_acoustics_dialog import RoomAcousticsDialog

        def _wrap_room_page(widget: QWidget) -> QWidget:
            page = QWidget()
            lay = QVBoxLayout(page)
            lay.setContentsMargins(12, 12, 12, 12)
            lay.addWidget(widget)
            # T-1093 B-2：外层包壳侧封顶（R3 页面零改造 + R-5 room_modes 本体零改动
            # 同时成立）；lbl_stats 的 setWordWrap 宽高耦合由此被封死在页内。
            page.setMinimumSize(0, _full_page_min_h)
            return page

        self.room_modes_page = _wrap_room_page(RoomModesWidget())
        self.central_stack.addWidget(self.room_modes_page)      # index2 房间模态页
        # T-1054b3 补正（审计闸门第1轮）：批3 删抽屉通路后全仓再无 cancelled 消费者
        # （房间声学页内「关闭」成死键）→ 保留内嵌 dialog 引用并接线回 index0；R3 不破。
        _dlg = RoomAcousticsDialog()
        _dlg.cancelled.connect(lambda: self._set_workspace_page(0))
        self.room_acoustics_page = _wrap_room_page(_dlg)
        self.central_stack.addWidget(self.room_acoustics_page)  # index3 房间声学页

        # T-1054 批4a：图表设计器 → 中央 index4 全铺页（零抽屉口径）。
        # 面板**常驻单实例**（构建期一次性，禁每次切页 new）；接线逐字沿用原抽屉
        # 构造点七项（父对象仍为主窗，_project() 父链上溯不受宿主迁移影响）。
        self.chart_designer_panel = ChartDesignerPanel(
            settings=self.controller.settings, parent=self
        )
        # 渲染由宿主注入 → 预览与导出走**同一条** _export_current_view 路径
        self.chart_designer_panel.set_preview_renderer(self._render_chart_designer_preview)
        self.chart_designer_panel.set_mode_provider(
            lambda: self.analysis_tab_bar.currentIndex()
        )
        self.chart_designer_panel.paramsChanged.connect(self._on_chart_designer_params)
        self.chart_designer_panel.exportRequested.connect(self._on_chart_designer_export)
        self.chart_designer_panel.fontSettingsRequested.connect(
            self._on_chart_designer_font_settings
        )
        self.chart_designer_page = _wrap_room_page(self.chart_designer_panel)
        self.central_stack.addWidget(self.chart_designer_page)  # index4 图表设计器页

        # T-1103 M-B′-β2：报告预览 → 中央 index5 全铺页（常驻单实例，构建期一次性）。
        # 预览与导出同源：html 走同一 _collect_report_figures + build_report_html；
        # 版面参数经 options() 透传给 β1 导出侧（_on_export_report_pdf）。
        from acouscope.ui.report_preview import ReportPreviewPanel

        self.report_preview_panel = ReportPreviewPanel(parent=self)
        self.report_preview_panel.set_html_provider(self._build_report_preview_html)
        self.report_preview_panel.exportRequested.connect(self._on_export_report_pdf)
        # T-1109 IM-32：预览页 HTML 导出 + 关闭按钮接线
        self.report_preview_panel.exportHtmlRequested.connect(self._on_export_report)
        self.report_preview_panel.closeRequested.connect(
            lambda: self._set_workspace_page(0)
        )
        # T-1104 M-C′·MC-1：AI 解读入口接线（worker 构造点在 report_ai 模块，
        # 主窗仅实例化——守三计数 0/0/8）；captions 由预览取数路顺带缓存，
        # 生成时零重渲染。
        self.report_preview_panel.aiRequested.connect(self._on_report_ai_requested)
        self._report_ai_worker = None
        self._report_preview_captions: tuple[str, ...] = ()
        self.report_preview_page = _wrap_room_page(self.report_preview_panel)
        self.central_stack.addWidget(self.report_preview_page)  # index5 报告预览页

        ws = build_workspace_splitter(self.central_stack)
        self.ws_splitter = ws["splitter"]
        self.left_panel = ws["left"]
        self.right_panel = ws["right"]

        # T-1013：分析导航器已删除（ARCH §6.1 覆盖 GUI_backlog #18 裁决 A）；
        # 视图切换镜像由中间 analysis_tab_bar（T-1010 前后一致）承担，无功能损失。
        self._build_side_tabs()

        restore_workspace(ws)
        self._ws_state = ws
        # T-1093 B-2 次要项：opaque 拖拽逐像素发 splitterMoved → 旧实现每像素一次
        # json.dump（GUI 线程磁盘 IO = 拖拽卡顿）。改为尾部合并：一次拖拽停手只落盘
        # 一次。★ PI-T84 N-6：节流只在接线层做，**禁沉入 workspace.save_workspace
        # 本体**（未授权档 test_workspace.py 同步 save→立刻读档，节流会让它红）。
        # 定时器构造点在 workspace.make_layout_save_timer（本布局模块内聚·父=本窗），
        # 定时器构造计数现由 tests/_pin_baselines.MAINWINDOW_QTIMER_COUNT（值 8）钉死
        # （T-1093 工厂移 workspace·保本文件 8 枚·冻结测见 test_chrome_panel_toggles）。
        self._ws_layout_save_timer = make_layout_save_timer(
            self, self._save_workspace_layout
        )
        ws["splitter"].splitterMoved.connect(
            lambda *_: self._ws_layout_save_timer.start()
        )
        ws["left"].collapsedChanged.connect(lambda *_: save_workspace(ws))
        ws["right"].collapsedChanged.connect(lambda *_: save_workspace(ws))
        # T-1010：右栏折叠态 → 工具栏 btn_toggle_right_panel 反同步
        ws["right"].collapsedChanged.connect(self._sync_right_panel_toggle)
        ws["right"].collapsedChanged.connect(self._sync_right_page_toggle)
        # T-1048：左栏折叠态 → 工具栏 btn_toggle_left_panel 反同步（两控件并存：
        # 本槽管工具栏面板开关，_sync_left_ribbon_toggle 管 ribbon 页签入口）
        ws["left"].collapsedChanged.connect(self._sync_left_panel_toggle)
        # T-1043：左栏折叠态 → ribbon 切页按钮 / 设置 action 反同步（§五b 双向同步）
        ws["left"].collapsedChanged.connect(self._sync_left_ribbon_toggle)
        self._sync_left_ribbon_toggle()
        self._sync_left_panel_toggle()
        layout.addWidget(ws["splitter"], 1)

        self.setCentralWidget(central)

    # ------------------------------------------------------------------
    # T-913：批处理工作区中央接线（central_stack 双页：index0 常规 / index1 批处理）
    # ------------------------------------------------------------------

    def _set_workspace_page(self, index: int) -> None:
        """T-1054 批0/批3：中央全铺页切换唯一状态源（R1）。

        切页 + 同步工作区开关组 checked（互斥：至多一个 checked，且与当前页一致；
        index1=批处理 / index2=房间模态 / index3=房间声学 / index4=图表设计器，
        其余开关恒未勾选）。
        菜单 action（action_room_modes / action_room_acoustics / action_chart_designer）
        勾选态一并同源同步，杜绝"右键进批处理后工具栏开关没亮 / 菜单与工具栏分裂"的分裂状态。
        所有进出路径（工具栏开关 / 菜单 action / _open_batch_workspace /
        _exit_batch_workspace / _on_room_modes / _on_room_acoustics /
        _on_chart_designer）必须都走本方法。
        """
        stack = getattr(self, "central_stack", None)
        if stack is None:
            return
        stack.setCurrentIndex(index)
        active_key = {
            1: "batch_workspace",
            2: "room_modal",
            3: "room_acoustic",
            4: "chart_designer",
        }.get(index)
        for name in ("batch_workspace", "room_modal", "room_acoustic", "chart_designer"):
            btn = getattr(self, "btn_toggle_" + name, None)
            if btn is not None:
                btn.setChecked(name == active_key)
        # 菜单 action 同源同步（禁分裂态）。blockSignals 防回环：setChecked 会触发
        # toggled → _on_room_* / _on_chart_designer 再次进入本方法并覆盖目标页；
        # 阻断后由本方法唯一裁决。
        for name, idx in (
            ("action_room_modes", 2),
            ("action_room_acoustics", 3),
            ("action_chart_designer", 4),
        ):
            act = getattr(self, name, None)
            if act is not None:
                act.blockSignals(True)
                act.setChecked(index == idx)
                act.blockSignals(False)
        # T-1054 批4a（M7）：设计器页两条入口（工具栏开关 / 菜单+分析工具栏 action）
        # 同槽 → 出图统一在本方法内触发，避免"菜单进页不出图"的半成品态。
        if index == 4:
            panel = getattr(self, "chart_designer_panel", None)
            if panel is not None:
                panel.render_now()

    def _on_workspace_toggle(self, workspace: str) -> None:
        """工作区开关组点击（R2：再点收回——点击已激活开关回常规页 index0）。

        _panel_toggle_button 默认 checkable，这里不依赖其自动翻转，目标页由本槽
        按当前栈索引判定，翻转后由 _set_workspace_page 统一回写 checked。
        """
        stack = getattr(self, "central_stack", None)
        if stack is None:
            return
        target = {
            "batch": 1,
            "room_modal": 2,
            "room_acoustic": 3,
            "chart_designer": 4,
        }[workspace]
        # 已在目标页 → 收回 index0；否则进入对应全铺页
        self._set_workspace_page(0 if stack.currentIndex() == target else target)

    def _open_batch_workspace(self, paths=None, module_name=None) -> None:
        """框架级入口：进入批处理页（index1）并预载文件集。

        由 FileBrowser.batchRequested（右键「批处理…」）驱动；paths 为待处理
        文件绝对路径列表。进入前同步当前 ProjectManager（入档状态判定用）。
        module_name（T-914 新增，可选）：进入后激活该已注册业务模块。
        """
        stack = getattr(self, "central_stack", None)
        ws = getattr(self, "batch_workspace", None)
        if stack is None or ws is None:
            return
        ws.set_manager(self.controller.project)
        ws.set_files(list(paths) if paths else [])
        self._set_workspace_page(1)  # 统一状态源（T-1054 批0）；波形随整页隐藏
        if module_name:
            ws.activate(module_name)

    def _open_batch_metadata_workspace(self) -> None:
        """右键「批量更改元数据…」入口（T-914）。

        addContextAction 语义为**无参**回调（框架已吞掉 Qt checked 入参，见
        T-1019 教训）→ 本槽**不得声明形参**；作用对象经 selected_paths() 自取。
        """
        fb = getattr(self, "file_browser", None)
        module = getattr(self, "batch_metadata_module", None)
        if fb is None or module is None:
            return
        self._open_batch_workspace(fb.selected_paths(), module.name)

    def _exit_batch_workspace(self) -> None:
        """退出批处理页 → 回常规模式 index0（波形恢复；经唯一状态源，开关同步反勾）。"""
        self._set_workspace_page(0)

    # ------------------------------------------------------------------
    # T-1012：侧栏内容宿主（无 tab 条：图标切换同一内容区）+ 入口路由
    # ------------------------------------------------------------------

    def _build_side_tabs(self) -> None:
        """T-1012：左右栏内容宿主（无 tab 条；见 ARCH_sidebar_ai_panel §六）。

        左栏内容 = QStackedWidget（QStackedWidget 自身无可见 tab 条）：
          页0「文件」= FileBrowser（T-910，默认内容）；页1「设置」= SettingsDialog
          （T-320，懒构建，打开前为占位页）。
        右栏内容 = QStackedWidget：页0「检查器」= InspectorPanel（默认内容）；
          页1「AI 释图」= 常驻宿主 _ai_host（每次入口以全新 AIInterpretDialog
          实例替换宿主内容，见 _activate_ai_tab）。
        PanelContainer 无标题栏/边缘三角/宽度自适应由 workspace.py 负责。
        """
        from PyQt6.QtWidgets import QWidget

        from acouscope.ui.widgets.file_browser import FileBrowser
        from acouscope.ui.widgets.panels import InspectorPanel

        # ---- 左栏：文件（默认） + 设置 ----
        self.left_content = QStackedWidget()
        self.left_content.setObjectName("leftSidebarContent")
        self.file_browser = FileBrowser(
            manager=self.controller.project,
            current_file=self.controller.current_file,
        )
        self.file_browser.fileActivated.connect(self._load_file)
        # T-912：点选单个文件 → 检查器档案元数据区；选中集清空 → 回空态
        self.file_browser.fileSelected.connect(self._on_file_selected_metadata)
        self.file_browser.selectionChanged.connect(
            self._on_file_selection_changed_metadata
        )
        # T-913：右键「批处理…」→ 批处理工作区（index1）并预载右键文件集
        self.file_browser.batchRequested.connect(self._open_batch_workspace)
        # T-914：右键「批量更改元数据…」→ 进入批处理页并激活本模块（业务入口）
        self.file_browser.addContextAction(
            tr("batch.meta.action"), self._open_batch_metadata_workspace
        )
        # T-1026：右键「加入多轨」→ D7 多选入口（语义 = 已选中文件）
        self.file_browser.addContextAction(
            tr("multitrack.add_action"), self._on_multitrack_add_from_browser
        )
        self.left_content.addWidget(self.file_browser)
        # T-1054 批1b：左栏页签条（4 页签）——index1 快速入门 / index2 手册 /
        # index3 录音设置（页承载按钮）复用 help_dialogs 既有内容源，零复制（R4/R5）。
        self._quickstart_page = self._build_help_page("quickstart", QUICK_START)
        self.left_content.addWidget(self._quickstart_page)
        self._manual_page = self._build_help_page("manual", MANUAL)
        self.left_content.addWidget(self._manual_page)
        self._record_settings_page = self._build_record_settings_page()
        self.left_content.addWidget(self._record_settings_page)
        # 「设置」页懒构建（先占位）：设置面板含音频设备枚举等重 UI，
        # 每次主窗构造 eager 构建会在 UI 长进程测试中放大 Qt 原生对象 churn
        # （回归：全量长进程 SIGSEGV）。首次入口激活时以 SettingsDialog 实例
        # 替换占位页（_activate_settings_tab）。
        self._settings_panel = None
        self._settings_placeholder = QWidget()
        self._settings_placeholder.setObjectName("settingsPlaceholder")
        self.left_content.addWidget(self._settings_placeholder)
        self.left_panel.set_content(self.left_content)

        # T-1033 P2：左栏面板头（共用构件 PanelHeader，ARCH §五-1）；
        # 标题随左栏页签（文件 / 设置）切换
        from acouscope.ui.widgets.panels.panel_header import attach_panel_header

        self.left_panel_header = attach_panel_header(
            self.left_panel, tr("sidebar.tab.files")
        )
        # T-1048 D3：左栏面板头右操作区 = 本面板自己的动作（文件页 / 设置页）；
        # checkable + 纳入 _left_page_entries() → 与 ribbon 页签入口同组互斥同步
        # （复用 T-1043 机制，零第二套同步逻辑；激活态 §五-6 内凹）。
        self.btn_header_files = _header_icon_button(
            self.left_panel_header, "files", tr("sidebar.tab.files"), "leftHeaderFilesBtn"
        )
        self.btn_header_files.setCheckable(True)
        # T-1054 批1a 裁决扩面：切页型入口 = 开关 → toggled 接泛化槽（index 0）
        self.btn_header_files.toggled.connect(
            lambda c: self._on_left_page_toggled(c, 0)
        )
        self.left_panel_header.add_action(self.btn_header_files)

        # T-1054 批1b：左栏页签条（4 页签，顺序 文件→快速入门→手册→录音设置）——
        # 设置页不再有面板头钮，入口仅余 ribbon 置底 ⚙ 与菜单 action_settings。
        self.btn_header_quickstart = _header_icon_button(
            self.left_panel_header, "help-circle", tr("sidebar.tab.quickstart"), "leftHeaderQuickstartBtn"
        )
        self.btn_header_quickstart.setCheckable(True)
        self.btn_header_quickstart.toggled.connect(
            lambda c: self._on_left_page_toggled(c, 1)
        )
        self.left_panel_header.add_action(self.btn_header_quickstart)

        self.btn_header_manual = _header_icon_button(
            self.left_panel_header, "info", tr("sidebar.tab.manual"), "leftHeaderManualBtn"
        )
        self.btn_header_manual.setCheckable(True)
        self.btn_header_manual.toggled.connect(
            lambda c: self._on_left_page_toggled(c, 2)
        )
        self.left_panel_header.add_action(self.btn_header_manual)

        self.btn_header_record = _header_icon_button(
            self.left_panel_header, "record", tr("sidebar.tab.record"), "leftHeaderRecordBtn"
        )
        self.btn_header_record.setCheckable(True)
        self.btn_header_record.toggled.connect(
            lambda c: self._on_left_page_toggled(c, 3)
        )
        self.left_panel_header.add_action(self.btn_header_record)
        self.left_content.currentChanged.connect(self._on_left_page_changed)

        # ---- 右栏：检查器（默认） + AI 释图 ----
        # AI 页 = 常驻宿主 _ai_host：每次入口以全新 AIInterpretDialog 实例替换
        # 宿主内容（原抽屉 set_content 同构，避免动态增删内容的 Qt 原生 churn）；
        # AI 面板生命周期由 _ai_panel 跟踪。
        self.right_content = QStackedWidget()
        self.right_content.setObjectName("rightSidebarContent")
        self.inspector_panel = InspectorPanel()
        self.inspector_panel.aiRequested.connect(self._on_ai_interpret)
        # T-1033 P4：检查器空态主操作按钮 → 既有「打开文件」入口
        self.inspector_panel.openRequested.connect(self._on_empty_state_open)
        # T-912：档案元数据区登记/保存依赖 ProjectManager
        self.inspector_panel.set_manager(self.controller.project)
        self.right_content.addWidget(self.inspector_panel)
        self._ai_host = QWidget()
        self._ai_host_layout = QVBoxLayout(self._ai_host)
        self._ai_host_layout.setContentsMargins(0, 0, 0, 0)
        self._ai_host_layout.setSpacing(0)
        self.right_content.addWidget(self._ai_host)
        self._ai_panel = None
        # T-1054 批2：图表字体页 = 内嵌既有 ChartFontDialog（单宿主；选择即 fontChanged → 既有
        # _apply_chart_fonts 持久化 + 同步 3D；零复制、零新控件）。
        from acouscope.ui.widgets.chart_font_dialog import ChartFontDialog

        latin, cjk = self._current_chart_fonts()
        self._chart_font_page = ChartFontDialog(latin=latin, cjk=cjk, parent=self)
        self._chart_font_page.fontChanged.connect(self._apply_chart_fonts)
        self.right_content.addWidget(self._chart_font_page)
        self.right_panel.set_content(self.right_content)

        # T-1033 P2：右栏面板头（共用构件，与左栏/分析区同一套）；标题随页签
        # （检查器 / AI 释图）切换
        self.right_panel_header = attach_panel_header(
            self.right_panel, tr("sidebar.tab.inspector")
        )
        # T-1054 批2：右栏面板头右操作区 = 3 个页签钮（检查器 / AI 释图 / 图表字体）
        # → right_content index0/1/2；全部 checkable + toggled 接泛化槽 _on_right_page_toggled
        #（照左栏范式唯一总表 + 泛化开关槽，异 index 互斥）。
        self.btn_header_inspect = _header_icon_button(
            self.right_panel_header, "inspect", tr("sidebar.tab.inspector"), "rightHeaderInspectBtn"
        )
        self.btn_header_inspect.setCheckable(True)
        self.btn_header_inspect.toggled.connect(
            lambda c: self._on_right_page_toggled(c, 0)
        )
        self.right_panel_header.add_action(self.btn_header_inspect)

        self.btn_header_ai = _header_icon_button(
            self.right_panel_header, "ai", tr("action.ai_interpret"), "rightHeaderAiBtn"
        )
        self.btn_header_ai.setCheckable(True)
        self.btn_header_ai.toggled.connect(
            lambda c: self._on_right_page_toggled(c, 1)
        )
        self.right_panel_header.add_action(self.btn_header_ai)

        self.btn_header_chart_font = _header_icon_button(
            self.right_panel_header, "chart_designer", tr("action.chart_font"), "rightHeaderChartFontBtn"
        )
        self.btn_header_chart_font.setCheckable(True)
        self.btn_header_chart_font.toggled.connect(
            lambda c: self._on_right_page_toggled(c, 2)
        )
        self.right_panel_header.add_action(self.btn_header_chart_font)
        self.right_content.currentChanged.connect(self._on_right_page_changed)
        # T-1054 批2：初始勾选态收敛（默认页 = 检查器；照左栏 _sync_left_ribbon_toggle 范式）
        self._sync_right_page_toggle()

    # ------------------------------------------------------------------
    # T-1033 P2：面板头标题随页签同步
    # ------------------------------------------------------------------

    def _on_left_page_changed(self, index: int) -> None:
        """左栏页签切换 → 面板头标题随动（文件 / 快速入门 / 手册 / 录音设置 / 设置）。"""
        header = getattr(self, "left_panel_header", None)
        if header is None:
            return
        keys = {
            0: "sidebar.tab.files",
            1: "sidebar.tab.quickstart",
            2: "sidebar.tab.manual",
            3: "sidebar.tab.record",
            4: "sidebar.tab.settings",
        }
        header.set_title(tr(keys.get(int(index), "sidebar.tab.files")))
        # T-1054 批4c（R3 M5）：离开 index3（切页 / setCurrentIndex(0)）→ 录音页收回清账
        if int(index) != 3:
            self._on_record_page_retracted()

    def _on_right_page_changed(self, index: int) -> None:
        """右栏页签切换 → 面板头标题随动（检查器 / AI 释图 / 图表字体）。"""
        header = getattr(self, "right_panel_header", None)
        if header is None:
            return
        keys = {
            0: "sidebar.tab.inspector",
            1: "sidebar.tab.ai",
            2: "action.chart_font",
        }
        header.set_title(tr(keys.get(int(index), "sidebar.tab.inspector")))

    def _build_settings_panel(self) -> QWidget:
        """左栏「设置」tab 内容：SettingsDialog 单实例（常驻 tab，T-504g 语义）。

        应用/取消接线为 _on_settings_applied/_on_settings_cancelled；构造失败
        返回空占位页（不阻断主窗启动）。
        """
        try:
            from acouscope.ui.widgets.settings_dialog import SettingsDialog

            s = self.controller.settings
            # T-1020 A 归因（非静默）：原 `from acouscope.ai.interpreter import
            # _load_config` 同样是不存在的符号 → 设置面板恒以空配置起步（回到
            # 内置档）。现统一走 UI 层读盘函数 load_ai_config（同候选序、取最近
            # 修改者），保证「打开设置」看到的就是磁盘上的真实配置。
            from acouscope.ui.widgets.ai_interpret import load_ai_config

            ai_config = load_ai_config()

            panel = SettingsDialog(
                parent=self,
                language=get_language(),
                ai_config=ai_config,
                theme=getattr(s, "theme", "default"),
                default_format=getattr(s, "default_format", "svg"),
                default_dpi=getattr(s, "default_dpi", 300),
                reference_hz=getattr(s, "reference_hz", 440.0),
            )
            panel.applied.connect(self._on_settings_applied)
            panel.cancelled.connect(self._on_settings_cancelled)
            self._settings_panel = panel
            return panel
        except Exception:
            import traceback

            traceback.print_exc()
            # 失败降级为空白占位页（不阻断主窗启动；无信号接线故安全）
            self._settings_panel = QWidget()
            return self._settings_panel

    def _build_help_page(self, kind: str, content_map: dict) -> QWidget:
        """左栏帮助页（快速入门/手册）：复用 help_dialogs 同一内容源零复制（R4）。

        渲染文本 == `_format_shortcuts(QUICK_START[lang])` / `_format_shortcuts(MANUAL[lang])`
        ——直接抽走 help_dialogs._HelpDialog 的同源渲染（QTextBrowser + _format_shortcuts），
        禁复制 HTML 字符串、禁改 help_dialogs 内容。kind 仅作 objectName 区分。
        """
        page = QWidget()
        page.setObjectName(f"helpPage_{kind}")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        lang = get_language()
        html = content_map.get(lang) or content_map.get("en_US", "")
        browser.setHtml(_format_shortcuts(html))
        layout.addWidget(browser)
        return page

    def _build_record_settings_page(self) -> QWidget:
        """左栏「录音设置」页（index3）：内嵌常驻 RecordSettingsDialog（批4c R1）。

        面板构建期一次性（切页不重建）；accepted/cancelled 沿用既有槽。
        本页不改 `transport_bar.btn_record` 勾选语义（录音运行状态源，T-1043 d5）。
        """
        from acouscope.ui.widgets.record_settings_dialog import RecordSettingsDialog

        page = QWidget()
        page.setObjectName("recordSettingsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        hint = QLabel(tr("sidebar.tab.record"))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        tool_rate = self.transport_bar.cmb_record_rate.currentData()
        panel = RecordSettingsDialog(
            self, current_rate=int(tool_rate) if tool_rate else 44100
        )
        panel.accepted.connect(self._begin_recording_from_settings)
        panel.cancelled.connect(self._on_recording_settings_cancelled)
        self.record_settings_panel = panel
        layout.addWidget(panel, stretch=1)
        return page

    def _record_page_is_current(self) -> bool:
        """左栏当前页是否=录音设置页（且左栏展开）：录音入口第二态判据。"""
        content = getattr(self, "left_content", None)
        page = getattr(self, "_record_settings_page", None)
        left = getattr(self, "left_panel", None)
        if content is None or page is None or left is None:
            return False
        return (not left.is_collapsed()) and content.currentWidget() is page

    def _show_left_content(self, widget) -> None:
        """切左栏当前内容并展开左栏；展开态下宽度随新内容自适应（非手动宽度）。"""
        content = getattr(self, "left_content", None)
        if content is None or widget is None:
            return
        content.setCurrentWidget(widget)
        left_panel = getattr(self, "left_panel", None)
        if left_panel is None:
            return
        if left_panel.is_collapsed():
            left_panel.set_collapsed(False)  # 触发 workspace._expand_slot 自适应
        else:
            self._fit_left_width()
        # T-1043：左栏页签入口勾选态 = 展开 + 当前页（单点收敛，任何路径都同步）
        self._sync_left_ribbon_toggle()

    def _save_workspace_layout(self) -> None:
        """三栏布局落盘唯一出口（splitterMoved debounce 尾触发 + 退出前补存）。

        save_workspace 自身全程静默（不可写/损坏均不抛），本方法不加第二层吞异常。
        """
        ws = getattr(self, "_ws_state", None)
        if ws is None:
            return
        from acouscope.ui.widgets.panels.workspace import save_workspace

        save_workspace(ws)

    def _fit_left_width(self) -> None:
        """左栏展开态按内容自适应宽度（用户手动拖拽值优先，不覆盖）。"""
        left_panel = getattr(self, "left_panel", None)
        if left_panel is None:
            return
        try:
            from acouscope.ui.widgets.panels.workspace import fit_panel_width

            fit_panel_width(left_panel)
            ws = getattr(self, "_ws_state", None)
            if ws is not None:
                from acouscope.ui.widgets.panels.workspace import save_workspace

                save_workspace(ws)
        except Exception:  # noqa: BLE001 — 布局自适应永不抛
            pass

    def _activate_settings_tab(self) -> None:
        """切左栏「设置」内容并展开左栏（菜单/ribbon ⚙/快捷键共同入口）。

        SettingsDialog 懒构建：首次入口以实例替换占位页（页1），此后单实例
        常驻；占位页只存在于从未打开设置之前（_settings_panel is None）。
        """
        content = getattr(self, "left_content", None)
        if content is None:
            return
        panel = getattr(self, "_settings_panel", None)
        if panel is None:
            # 移除占位页，构建并追加真实 SettingsDialog 实例
            ph = getattr(self, "_settings_placeholder", None)
            if ph is not None:
                content.removeWidget(ph)
                ph.deleteLater()
                self._settings_placeholder = None
            panel = self._build_settings_panel()
            content.addWidget(panel)
        # 面板内「关闭」曾把自身隐藏：重入时恢复可见
        if panel.isHidden():
            panel.show()
        self._show_left_content(panel)

    def _activate_files_tab(self) -> None:
        """ribbon「文件」图标入口：切回左栏文件浏览器并展开左栏。"""
        fb = getattr(self, "file_browser", None)
        if fb is not None:
            self._show_left_content(fb)

    def _on_file_selected_metadata(self, path: str) -> None:
        """T-912：文件管理器点选 → 检查器加载单文件档案元数据。

        面板内部对尚无 ProjectFile 条目的文件自动 add_file 登记；
        show_file_metadata 返回 True（本次新增登记）时刷新文件浏览器，
        让列表随即显示"✓"入档标识（registered=False 不触发重列）。
        """
        ins = getattr(self, "inspector_panel", None)
        if ins is None:
            return
        registered = ins.show_file_metadata(path)
        fb = getattr(self, "file_browser", None)
        if registered and fb is not None:
            fb.refresh()

    def _on_file_selection_changed_metadata(self, paths: list) -> None:
        """T-912：选择清空（点空白/取消选中）→ 检查器元数据区回空态。

        单选点选已由 fileSelected（itemClicked）驱动加载；这里仅处理
        选中集变为空的情形，多选状态不触发加载（避免连点反复读盘）。
        """
        if paths:
            return
        ins = getattr(self, "inspector_panel", None)
        if ins is not None:
            ins.clear_metadata()

    def _on_settings_applied(self) -> None:
        """左栏设置 tab「应用」：语言/AI/主题/导出持久化（原 _on_settings 内嵌逻辑）。"""
        panel = getattr(self, "_settings_panel", None)
        if panel is None:
            return
        s = self.controller.settings

        new_lang = panel.language()
        s.language = new_lang
        set_language(new_lang)

        new_ai = panel.ai_config()
        # T-1020 A 归因（非静默）：原 `from acouscope.ai.interpreter import _save_config`
        # 的死 import —— 该符号全仓不存在 → ImportError 被 `except Exception: pass`
        # 静默吞掉 → 设置-AI「应用」**从不写 ai_config.json**（实测零文件生成），
        # 即「不管设置什么都一样」的直接原因。现改调 UI 层真实写盘函数（复用
        # _config_paths() 候选序）；写失败必须可见（toast），不再静默吞。
        from acouscope.ui.widgets.ai_interpret import save_ai_config

        if not save_ai_config(new_ai):
            show_toast(self, tr("ai_panel.config_save_failed"), level="warning")

        from acouscope.ui.theme import apply_theme

        new_theme = panel.theme()
        s.theme = new_theme
        apply_theme(new_theme)

        fmt, dpi = panel.default_format(), panel.default_dpi()
        s.default_format = fmt
        s.default_dpi = dpi

        # T-921：A4 参考频率（未显式传 ref_freq= 的音分/MIDI 换算改用它；
        # 入参非法时 set_reference_hz 返回 False 并保持原值，不写入持久化）
        from acouscope.dsp.units import set_reference_hz

        new_reference = panel.reference_hz()
        reference_applied = set_reference_hz(new_reference)
        if reference_applied:
            s.reference_hz = new_reference

        try:
            from acouscope.utils.config import Settings

            settings = Settings.load()
            settings.language = new_lang
            settings.theme = new_theme
            settings.default_format = fmt
            settings.default_dpi = dpi
            if reference_applied:
                settings.reference_hz = new_reference
            settings.save()
        except Exception as e:
            # T-1074 G3③（承 T72-08）：偏好落盘失败不再静默——补日志痕（含回溯）
            _log.warning("语言/主题/格式/DPI 偏好保存失败: %s", e, exc_info=True)

        self.statusBar().showMessage(
            f"{tr('settings.title')} → {new_lang} / {fmt.upper()} / {dpi} dpi", 5000
        )

        if new_lang != self._init_lang:
            show_toast(self, tr("settings.lang_hint"), level="info")

        # T-1011：设置应用后刷新已存在的 AI 释图面板（同会话双向同步）
        # T-1020：收窄原 `except Exception: pass`（静默吞）——reload_config 读取
        # 路径永不抛；仅吸收「面板 C++ 对象已销毁」这一无意义刷新的 RuntimeError。
        panel_ai = getattr(self, "_ai_panel", None)
        if panel_ai is not None and hasattr(panel_ai, "reload_config"):
            try:
                panel_ai.reload_config()
            except RuntimeError:
                pass

    def _on_ai_config_changed(self) -> None:
        """AI 释图面板切档写盘 ai_v2.source → 刷新左栏设置面板 AI 三档字段。

        T-1020 D4：显式把磁盘配置传给 reload_ai_config（其 cfg=None 分支内部
        引用的 `ai.interpreter._load_config` 不存在，会静默退回空配置 → 档位
        被错误重置为内置档）；load_ai_config 永不抛，故此处无需吞异常。
        """
        sp = getattr(self, "_settings_panel", None)
        if sp is None:
            return
        if not hasattr(sp, "reload_ai_config"):
            return
        from acouscope.ui.widgets.ai_interpret import load_ai_config

        sp.reload_ai_config(load_ai_config())

    def _on_settings_cancelled(self) -> None:
        """左栏设置 tab 关闭（未应用）：回滚主题即时预览（原 _on_settings 内嵌逻辑）。"""
        from acouscope.ui.theme import apply_theme

        apply_theme(getattr(self.controller.settings, "theme", "dark"))

    def _make_ai_panel(self):
        """构造 AI 释图面板（每次打开新建实例，配置由 __init__ 的 _load_config 恢复）。"""
        from acouscope.ui.widgets.ai_interpret import AIInterpretDialog

        return AIInterpretDialog(
            image_getter=self._capture_current_view_png,
            context_getter=self._build_ai_context,
            view_name_getter=self._current_view_name,
            parent=self,
        )

    def _activate_ai_tab(self) -> None:
        """AI 释图入口（菜单/工具栏/检查器钮）：右栏切「AI 释图」内容并展开右栏。

        每次入口新建 AIInterpretDialog 实例：旧实例先 close（触发其 closeEvent
        取消并等待后台 worker），再从常驻宿主 _ai_host 移除；新实例装入宿主。
        对话历史为单次打开会话临时态，不保留。
        """
        content = getattr(self, "right_content", None)
        host = getattr(self, "_ai_host", None)
        host_layout = getattr(self, "_ai_host_layout", None)
        if content is None or host is None or host_layout is None:
            return

        # 既有 AI 面板 → 先 close（worker 取消收尾）再移出宿主
        old = getattr(self, "_ai_panel", None)
        if old is not None:
            try:
                old.close()
            except RuntimeError:
                pass
            host_layout.removeWidget(old)
            old.setParent(None)
            old.deleteLater()

        panel = self._make_ai_panel()
        self._ai_panel = panel
        # T-1011：面板写回 ai_config.json → 同会话刷新左栏设置面板三档字段
        panel.config_changed.connect(self._on_ai_config_changed)
        host_layout.addWidget(panel)
        content.setCurrentWidget(host)

        right_panel = getattr(self, "right_panel", None)
        if right_panel is not None and right_panel.is_collapsed():
            right_panel.set_collapsed(False)

    def _create_left_ribbon(self) -> QWidget:
        """T-1012：主窗最左窄图标栏（ribbon，参考 Obsidian ribbon，常驻不可关）。

        自上而下：中部弹性留白位；底部 网站 → 帮助 → 设置（设置置底固定，T-1054 批1a）。
        文件页入口交由面板头 btn_header_files 承担；图标 get_icon + i18n tooltip；
        clicked → 对应槽；颜色一律 theme 派生（style_when_theme / TOKENS，禁硬编码 hex）。
        """
        from PyQt6.QtCore import QSize
        from PyQt6.QtWidgets import QPushButton

        from acouscope.ui.theme import TOKENS, style_when_theme

        ribbon = QWidget(self)
        ribbon.setObjectName("leftRibbon")
        ribbon.setFixedWidth(_RIBBON_WIDTH)
        style_when_theme(
            ribbon,
            lambda c: (
                f"QWidget#leftRibbon {{ background: {c['panel']}; "
                f"border-right: 1px solid {c['border']}; }}"
            ),
        )

        sp = TOKENS["spacing"]
        lay = QVBoxLayout(ribbon)
        lay.setContentsMargins(0, sp["xs"], 0, sp["xs"])
        lay.setSpacing(sp["sm"])

        def _icon_btn(icon_name: str, tooltip: str) -> QPushButton:
            b = QPushButton(ribbon)
            b.setObjectName("ribbonIconBtn")
            b.setIcon(get_icon(icon_name))
            b.setIconSize(QSize(20, 20))
            b.setFixedSize(QSize(32, 32))
            b.setToolTip(tooltip)
            b.setAutoDefault(False)
            style_when_theme(
                b,
                lambda c: (
                    f"QPushButton#ribbonIconBtn {{ background: transparent; "
                    f"border: none; padding: 0; "
                    f"border-radius: {TOKENS['radius']['sm']}px; }}"
                    f"QPushButton#ribbonIconBtn:hover {{ "
                    f"background: {c['btn_hover']}; }}"
                    f"QPushButton#ribbonIconBtn:pressed {{ "
                    f"background: {c['accent']}; }}"
                    # T-1043 §五-6：激活 = 内凹（比周围更暗的底，明暗两骨架同向）
                    f"QPushButton#ribbonIconBtn:checked {{ "
                    f"background: {c['bg0']}; }}"
                ),
            )
            return b

        # T-1054 批1a：顶部「文件/设置」入口撤下。文件页入口由面板头 btn_header_files
        # （T-1048 D3）承担；设置钮移至底部最末（置底固定）。中部仅留弹性留白位。
        lay.addStretch(1)

        # 底部上移：网站入口（T-1015：位于帮助图标上方，点击 → 主站）
        self.ribbon_btn_site = _icon_btn("info", tr("action.visit_site"))
        self.ribbon_btn_site.clicked.connect(self._on_visit_site)
        lay.addWidget(
            self.ribbon_btn_site, 0, Qt.AlignmentFlag.AlignHCenter
        )

        # 底部：帮助?（T-1054 批4b：与 ribbon_btn_settings 对称改 toggled，走左栏页 index1）
        # 勾选 → 展开左栏切快速入门页；再点 → 折叠左栏（唯一槽 _on_left_page_toggled）
        self.ribbon_btn_help = _icon_btn("help-circle", tr("action.quickstart"))
        self.ribbon_btn_help.setCheckable(True)
        self.ribbon_btn_help.toggled.connect(
            lambda c: self._on_left_page_toggled(c, 1)
        )
        lay.addWidget(
            self.ribbon_btn_help, 0, Qt.AlignmentFlag.AlignHCenter
        )

        # 底部最末：设置（T-1054 批1a 自顶部置底固定；同 checkable/同槽）
        # 裁决扩面：与面板头页签钮统一接泛化开关槽（index 4）
        self.ribbon_btn_settings = _icon_btn("settings", tr("sidebar.tab.settings"))
        self.ribbon_btn_settings.setCheckable(True)
        self.ribbon_btn_settings.toggled.connect(
            lambda c: self._on_left_page_toggled(c, 4)
        )
        lay.addWidget(
            self.ribbon_btn_settings, 0, Qt.AlignmentFlag.AlignHCenter
        )

        return ribbon

    def _create_status_bar(self):
        """创建状态栏（CB-013 D-2：lbl_status 消息 + 数据段宿主 + lbl_audio_info）。"""
        status = QStatusBar()
        self.setStatusBar(status)

        self.lbl_status = QLabel(tr("status.ready"))
        status.addWidget(self.lbl_status)

        # CB-013 D-2：状态栏数据段宿主（默认五段注册表 + 右键勾选 + 持久化）。
        # lbl_status/lbl_audio_info 两既有控件原样保留（lbl_status 为通用消息区；
        # lbl_audio_info 为常驻完整音频信息）；file/sample_rate 段与后者同源
        # 抽取对应信息，口径说明见 CB-013 报告。
        from acouscope.ui.widgets.statusbar_segments import StatusBarSegments
        from acouscope.utils.config import get_data_dir

        self.status_segments = StatusBarSegments(
            config_path=get_data_dir() / "ui_statusbar_segments.json",
            parent=self,
        )
        status.addWidget(self.status_segments)

        status.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        status.customContextMenuRequested.connect(self._show_status_segments_menu)

        # 段初始占位：文件/采样率未知 → "—"；位置/录音计时归零
        seg = self.status_segments
        seg.set_text("file", f"{tr('status.seg.file')}: —")
        seg.set_text("sample_rate", f"{tr('status.seg.sample_rate')}: —")
        seg.set_text(
            "play_position",
            f"{tr('status.seg.play_position')}: "
            f"{format_transport_clock(0.0)} / {format_transport_clock(0.0)}",
        )
        seg.set_text("record_timer", f"{tr('status.seg.record_timer')}: 00:00")
        seg.set_text("zoom", f"{tr('status.seg.zoom')}: —")

        # 缩放段数据源：波形视图可见时间窗（vb 范围变化即刷新；waveform 内部
        # 工具栏/滚轮缩放同样经此路径，无需改 waveform.py）
        self.waveform_widget.plot_widget.plotItem.vb.sigRangeChanged.connect(
            lambda *_: self._refresh_status_zoom_segment()
        )

        self.lbl_audio_info = QLabel("")
        status.addPermanentWidget(self.lbl_audio_info)

        # T-928：任务进度中心 toggle（状态栏右侧、与 lbl_audio_info 同区；
        # 面板为非模态 QWidget，跟进态按钮展开/收起，不进侧栏）
        from PyQt6.QtWidgets import QToolButton

        self.btn_task_center = QToolButton()
        self.btn_task_center.setObjectName("taskCenterToggle")
        self.btn_task_center.setText(tr("task_center.toggle"))
        self.btn_task_center.setIcon(get_icon("layers"))
        self.btn_task_center.setCheckable(True)
        self.btn_task_center.setAutoRaise(True)
        self.btn_task_center.setToolTip(tr("task_center.title"))
        self.btn_task_center.toggled.connect(self._toggle_task_center)
        status.addPermanentWidget(self.btn_task_center)

    # ------------------------------------------------------------------
    # T-928：任务进度中心（状态栏 toggle + 非模态面板；调度层见 task_center.py）
    # ------------------------------------------------------------------

    def _on_task_center_rejected(self, title: str) -> None:
        """排队超上限 → 拒绝并提示（不静默丢弃）。"""
        show_toast(
            self,
            tr("task_center.queue_full").format(n=self.task_center.queue_limit),
            level="error",
        )

    def _deliver_multitrack_analysis(self, plan, kind, cache):
        """多轨分析 → 任务中心投递（T-1041a 轮 B；轮 A 投递缝的宿主侧）。

        投递同步返回、句柄待 worker 结束才存在 ⇒ 恒返回 ``[]``（句柄不可补；
        唯一树内调用方 multitrack_view:540 的 λ 忽略返回值，不构成缺公开面）。

        ★ T-1087 M4（path_A）：``plan`` 是**零 IO 取数计划**，``plan.resolve()``
        （→ ``resolve_source`` → ``track.load_full()``·整文件同步读）挪进 worker
        的 ``run`` 内——修前它发生在 ``analyze_all`` 里、submit **之前**（主线程），
        异步收益被逐轨 IO 吃掉。LRU 驱逐 ``unload_inactive`` 相应**延后**到
        ``on_done`` 主线程回填之后：worker 期间主线程不再与并发改 ``_data``/``state``
        的驱逐动作重叠（详见 report「M4 线程安全处置说明」）。
        """
        from acouscope.ui.widgets.multitrack.analysis_source import (
            run_analysis_on_tracks,
        )

        pending = self._multitrack_analysis_task_id
        if pending is not None:
            entry = self.task_center.entry(pending)
            if entry is not None and not entry.is_terminal():
                return []                 # 在跑：连点不重复投递（IM-26 双触发）

        def _release_io() -> None:
            """M4：worker 结束后在主线程做 LRU 驱逐（驻留样本有界）。

            驱逐对象取 ``plan.session``——那才是 worker 真正载入样本的会话（宿主
            ``self.multitrack_session`` 在回填前可能已被换音频/重开项目替换）。
            """
            plan.session.unload_inactive()

        def on_done(handles) -> None:
            done = sum(1 for h in handles if h.ok)
            if done:
                show_toast(self, tr("multitrack.compare.analyzed").format(n=done))
            else:
                show_toast(
                    self, tr("multitrack.compare.analyze_failed"), level="warning"
                )
            self._multitrack_analysis_task_id = None
            _release_io()
            self.multitrack_panel.refresh_presentation()

        def on_fail(_error) -> None:
            self._multitrack_analysis_task_id = None
            _release_io()

        def on_cancelled() -> None:
            self._multitrack_analysis_task_id = None
            _release_io()
            self.multitrack_panel.refresh_presentation()  # 收口「末刻取消」竞态

        def work(reporter):
            # ★ 本函数在 worker 线程执行（task_center._TaskThread）：取数 IO 与
            # 逐轨分析全在此，主线程只负责排期与回填。
            sources = plan.resolve()
            return run_analysis_on_tracks(
                sources, kind, cache=cache, cancel=lambda: reporter.cancelled
            )

        title = tr("task_center.title.multitrack").format(n=len(plan))
        entry = self.task_center.submit(
            title,
            work,
            on_done=on_done,
            on_fail=on_fail,
            on_cancelled=on_cancelled,
        )
        if entry is None:
            return []   # 队列超限/关停：taskRejected 已弹 toast（:2305）⇒ 禁双弹
        self._multitrack_analysis_task_id = entry.task_id
        return []

    def _deliver_multitrack_task(self, title, work, on_done, on_settle):
        """多轨后台任务的通用投递（T-1087 M6/M7/M5 同构包裹）。

        只调 ``task_center.submit`` 公开 API（内核零改）；``work(reporter)`` 在
        worker 线程跑，终态一律先 ``on_settle()``（解在途门闩）再 ``on_done(result)``
        主线程回填。队列超限/关停 → 返回 None（``taskRejected`` 已弹 toast ⇒ 禁双弹）。

        面板侧三个入口共用本适配器：``set_align_deliver``（M6 开头对齐）、
        ``ComparePresentWidget.set_diff_deliver``（M7 差异量化）、
        ``set_track_prepare_deliver``（M5 加轨包络 IO）。
        """
        def done(result) -> None:
            on_settle()
            on_done(result)

        def settle_only(_error=None) -> None:
            on_settle()

        return self.task_center.submit(
            title,
            work,
            on_done=done,
            on_fail=settle_only,
            on_cancelled=settle_only,
        )

    def _on_batch_task_event(self, event: str, payload: dict) -> None:
        """批处理 → 任务中心聚合条目（外部驱动任务；无可靠数值进度 → 仅文本）。

        口径（定案）：批处理的 `progress_cb` 只给文本、无数值分数，故聚合条目
        按「不定式 + 阶段文本」呈现（模块级 `PROGRESS_TEXT` = 不重复进度条）；
        批处理专属明细仍由 BatchWorkspace 内联进度区承载。
        """
        if event == "start":
            # T-929 预检挂点①：批处理启动（模块 apply 之前；低内存 → 非模态提示）
            self._memguard_preflight("batch")
            entry = self.task_center.register(
                tr("task_center.title.batch").format(n=payload.get("n", 0)),
                kind=KIND_BATCH,
                progress_mode=PROGRESS_TEXT,
                cancellable=False,  # 同步执行、无中断通道 → 不给无效取消按钮
            )
            self._batch_task_id = entry.task_id
        elif event == "stage":
            if self._batch_task_id:
                self.task_center.set_stage(
                    self._batch_task_id, str(payload.get("text", ""))
                )
        elif event == "finish":
            task_id = self._batch_task_id
            if task_id:
                self._batch_task_id = None
                self.task_center.finish(
                    task_id,
                    ok=bool(payload.get("ok")),
                    error=str(payload.get("error", "")),
                )

    def _refresh_task_center_toggle(self) -> None:
        """toggle 文案随「进行中 + 排队」计数更新（0 时不显示计数）。"""
        btn = getattr(self, "btn_task_center", None)
        if btn is None:
            return
        base = tr("task_center.toggle")
        count = self.task_center.active_count()
        btn.setText(f"{base} ({count})" if count else base)

    def _toggle_task_center(self, checked: bool) -> None:
        """状态栏 toggle → 显示/隐藏非模态任务面板（幂等）。"""
        panel = self._ensure_task_center_panel()
        if checked:
            self._position_task_center_panel()
            panel.show()
            panel.raise_()
        else:
            panel.hide()
        self._save_task_center_state()  # T-1040：显隐变化落盘

    def _ensure_task_center_panel(self) -> TaskCenterPanel:
        """取（懒建）任务面板：宿主为 MainWindow，非模态、可折叠。"""
        panel = self._task_center_panel
        if panel is None:
            panel = TaskCenterPanel(self.task_center, self)
            panel.hide()
            self._task_center_panel = panel
            # T-1040：折叠态变化 → 落盘（保存时机走既有 set_collapsed 通路）
            panel.collapsedChanged.connect(self._save_task_center_state)
            # T-1040：首次创建后应用上次折叠态（仅恢复，不改既有显隐语义）
            saved = getattr(self, "_restore_task_center_state", None)
            if isinstance(saved, dict) and isinstance(saved.get("collapsed"), bool):
                panel.set_collapsed(saved["collapsed"])
        return panel

    def _position_task_center_panel(self) -> None:
        """面板定位：状态栏之上、右侧对齐（悬浮内联，不进侧栏）。"""
        panel = self._task_center_panel
        if panel is None:
            return
        from acouscope.ui.theme import TOKENS

        margin = TOKENS["spacing"]["sm"]
        bar_height = self.statusBar().height()
        height = min(panel.sizeHint().height(), max(margin, self.height() // 2))
        panel.resize(TASK_CENTER_PANEL_WIDTH, height)
        x = max(margin, self.width() - TASK_CENTER_PANEL_WIDTH - margin)
        y = max(margin, self.height() - bar_height - height - margin)
        panel.move(x, y)

    def resizeEvent(self, event):
        """窗口尺寸变化：面板可见时重新贴靠状态栏。"""
        super().resizeEvent(event)
        panel = self._task_center_panel
        if panel is not None and not panel.isHidden():
            self._position_task_center_panel()

    # ------------------------------------------------------------------
    # CB-013 D-2：状态栏数据段辅助
    # ------------------------------------------------------------------

    def _show_status_segments_menu(self, pos):
        """状态栏右键 → 数据段勾选菜单（QMenu checkable，合法非模态）。"""
        seg = getattr(self, "status_segments", None)
        if seg is None:
            return
        seg.popup(self.statusBar().mapToGlobal(pos))

    def _refresh_status_zoom_segment(self) -> None:
        """缩放段刷新：可见时间窗占全轨时长百分比（波形视图为数据源）。"""
        seg = getattr(self, "status_segments", None)
        if seg is None:
            return
        info = self.controller.audio_info
        total = float(info.duration) if info is not None else 0.0
        try:
            x0, x1 = self.waveform_widget.plot_widget.plotItem.vb.viewRange()[0]
        except Exception:
            x0, x1 = 0.0, 0.0
        span = max(0.0, float(x1) - float(x0))
        if total > 0 and span > 0:
            pct = min(999.9, span / total * 100.0)
            text = f"{tr('status.seg.zoom')}: {pct:.1f}%"
        else:
            text = f"{tr('status.seg.zoom')}: —"
        seg.set_text("zoom", text)

    def _update_status_play_position(self, pos: float, duration: float) -> None:
        """播放位置段：与传输条同数据源（HH:MM:SS.mmm）。"""
        seg = getattr(self, "status_segments", None)
        if seg is None:
            return
        seg.set_text(
            "play_position",
            f"{tr('status.seg.play_position')}: "
            f"{format_transport_clock(pos)} / {format_transport_clock(duration)}",
        )

    def _set_status_record_timer(self, duration: float) -> None:
        """录音计时段：录音中 mm:ss；空闲归零（始终可见，由右键菜单隐藏）。"""
        seg = getattr(self, "status_segments", None)
        if seg is None:
            return
        d = max(0, int(duration))
        seg.set_text(
            "record_timer",
            f"{tr('status.seg.record_timer')}: {d // 60:02d}:{d % 60:02d}",
        )

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------

    def _on_empty_state_open(self) -> None:
        """空态主操作按钮 → 既有「打开文件」入口（T-1033 P4，零第二套路径）。"""
        self.action_open.trigger()

    def _on_open_file(self):
        """打开文件。"""
        filters = (
            "音频文件 (*.wav *.mp3 *.flac *.ogg *.aiff *.aif);;"
            "所有文件 (*.*)"
        )
        filepath, _ = QFileDialog.getOpenFileName(
            self, "打开音频文件", "", filters
        )
        if filepath:
            self._load_file(filepath)

    def _load_file(self, filepath: str):
        """加载音频文件。"""
        try:
            self.lbl_status.setText(f"正在加载: {Path(filepath).name}...")
            self.lbl_status.repaint()

            info = self.controller.open_file(filepath)
            self._sync_after_open(info)

            self.fileOpened.emit(filepath)

        except Exception as e:
            show_toast(self, f"无法打开文件:\n{str(e)}", level="error")
            self.lbl_status.setText("就绪")

    def _sync_after_open(self, info):
        """音频打开后的 UI 同步。"""
        # 更新波形
        times, data = self.controller.get_waveform()
        self.waveform_widget.set_data(times, data, sample_rate=info.sample_rate)

        # 设置播放电平回调（VU 表）
        self.controller.audio_player.set_level_callback(self._on_play_level)

        # 更新状态
        name = Path(info.filepath).name if info.filepath else ""
        self.lbl_status.setText(f"已加载: {name}")
        self.lbl_audio_info.setText(
            f"{info.sample_rate} Hz · {info.channels} 声道 · "
            f"{info.duration_str} · {info.format}"
        )

        # CB-013 D-2：数据段同步（file/sample_rate 与上方 lbl_audio_info 同源）
        seg = getattr(self, "status_segments", None)
        if seg is not None:
            seg.set_text("file", f"{tr('status.seg.file')}: {name or '—'}")
            seg.set_text(
                "sample_rate",
                f"{tr('status.seg.sample_rate')}: {info.sample_rate} Hz",
            )

        # 重置进度条
        self.transport_bar.set_seek_percent(0)
        self.transport_bar.set_time_label(0.0, info.duration)
        self._update_status_play_position(0.0, info.duration)
        # T-507b：检查器播放位置复位 + 音频信息（与状态栏 lbl_audio_info 同口径）
        ins = getattr(self, "inspector_panel", None)
        if ins is not None:
            ins.set_playback(0.0, info.duration)
            ins.set_audio_info(
                f"{info.sample_rate} Hz · {info.channels} 声道 · "
                f"{info.duration_str} · {info.format}"
            )
        self.waveform_widget.set_playhead(0.0)

        # 常驻文件信息条
        self.metadata_bar.set_info(info, self.controller.audio_data, info.sample_rate)
        self._update_edit_actions()

        # T-805：还原工程已存音高网格模型（GUI_backlog #16；仅还原模型，不重建音高控件；
        # 损坏数据反序列化后残留非法 dict，此处仅接受 PitchGridModel，非模型不覆盖）
        from acouscope.analysis.pitch_grid import PitchGridModel

        grid = self.controller.get_saved_pitch_grid()
        if isinstance(grid, PitchGridModel):
            self._pitch_grid_model = grid

        # 波形视图下的实时特征面板（视图堆叠常驻化：
        # 新音频使旧视图失效，懒重建当前视图；启动时恢复持久化的上次视图）
        self._invalidate_analysis_views()
        idx = self._restore_view_index if self._restore_view_index is not None else self.analysis_tab_bar.currentIndex()
        self._restore_view_index = None
        self._on_analysis_changed(idx)
        self._set_analysis_view(idx)  # 标签卡与恢复的视图保持同步

        # CB-013 D-2：缩放段初始读数（加载后默认全窗 = 适应窗口）
        self._refresh_status_zoom_segment()

        # T-1010：文件浏览器（左栏 tab①）跟随最近打开音频刷新目录
        fb = getattr(self, "file_browser", None)
        if fb is not None:
            fb.set_current_file(info.filepath)

    # ------------------------------------------------------------------
    # 去除开头静默（波形工具栏按钮）
    # ------------------------------------------------------------------

    def _on_trim_leading_silence(self):
        """检测开头静默并按用户选择处理（另存导入 / 修改源文件）。"""
        from acouscope.analysis.silence import detect_leading_silence
        from acouscope.i18n import tr

        if not self.controller.has_audio():
            show_toast(self, tr("trim.need_audio"), level="info")
            return

        data = self.controller.audio_data
        sr = self.controller.sample_rate
        cut = detect_leading_silence(data, sr)
        if cut <= 0:
            show_toast(self, tr("trim.no_silence"), level="info")
            return

        total = len(data)
        sec = cut / sr
        pct = cut / total * 100.0
        msg = QMessageBox(self)
        msg.setWindowTitle(tr("trim.title"))
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText(tr("trim.detected").format(sec=f"{sec:.3f}", pct=f"{pct:.1f}"))
        btn_save = msg.addButton(
            tr("trim.save_as"), QMessageBox.ButtonRole.YesRole
        )
        btn_src = msg.addButton(
            tr("trim.modify_src"), QMessageBox.ButtonRole.DestructiveRole
        )
        msg.addButton(tr("trim.cancel"), QMessageBox.ButtonRole.RejectRole)
        msg.exec()

        if msg.clickedButton() is btn_save:
            self._trim_silence_save_as(data, sr, cut)
        elif msg.clickedButton() is btn_src:
            self._trim_silence_modify_source(data, sr, cut)

    def _trim_silence_save_as(self, data: np.ndarray, sr: int, cut: int):
        """另存为新文件（去除静默后）并导入。"""
        from acouscope.i18n import tr

        src = self.controller.current_file
        default_name = (
            f"{Path(src).stem}_trimmed{Path(src).suffix}" if src else "trimmed.wav"
        )
        default_dir = str(Path(src).parent) if src else ""
        filepath, _ = QFileDialog.getSaveFileName(
            self, tr("trim.save_as"), str(Path(default_dir) / default_name),
            "WAV 音频 (*.wav);;FLAC (*.flac);;AIFF (*.aiff *.aif)"
        )
        if not filepath:
            return
        try:
            self.controller.audio_io.save(data[cut:], sr, filepath)
            self._load_file(filepath)
            self.show_tip_text(tr("trim.done_save").format(path=Path(filepath).name))
        except Exception as e:
            show_toast(self, tr("trim.failed").format(err=e), level="error")

    def _trim_silence_modify_source(self, data: np.ndarray, sr: int, cut: int):
        """修改源文件（覆盖前自动备份 + 二次警示）。"""
        import shutil

        from acouscope.i18n import tr

        src = self.controller.current_file
        if src is None:
            show_toast(self, tr("trim.need_audio"), level="warning")
            return

        # 二次警示：覆盖不可撤销
        warn = QMessageBox(self)
        warn.setWindowTitle(tr("trim.warn_title"))
        warn.setIcon(QMessageBox.Icon.Warning)
        warn.setText(tr("trim.warn_text").format(path=str(src)))
        btn_yes = warn.addButton(tr("trim.modify_src"), QMessageBox.ButtonRole.YesRole)
        warn.addButton(tr("trim.cancel"), QMessageBox.ButtonRole.RejectRole)
        warn.exec()
        if warn.clickedButton() is not btn_yes:
            return

        backup = src.with_name(f"{src.stem}_backup{src.suffix}")
        try:
            shutil.copy2(src, backup)
            self.controller.audio_io.save(data[cut:], sr, src)
            self._load_file(str(src))
            self.show_tip_text(
                tr("trim.done_src").format(path=Path(backup).name)
            )
        except Exception as e:
            show_toast(self, tr("trim.failed").format(err=e), level="error")

    # ------------------------------------------------------------------
    # 全局快捷键
    # ------------------------------------------------------------------

    def _setup_shortcuts(self):
        """注册全局快捷键。"""
        from acouscope.ui.shortcuts import ShortcutManager
        mgr = ShortcutManager.instance()

        # 播放/暂停（空格）
        mgr.register_global(
            "play_pause", "播放/暂停", "Space",
            self._on_play_pause, self,
        )
        # 停止（Shift+Space）
        mgr.register_global(
            "stop", "停止", "Shift+Space",
            self._on_stop, self,
        )
        # CB-013 D-1：录音（R，与 ● 按钮同入口）；Esc 统一停止（有选区先取消）
        mgr.register_global(
            "record", tr("shortcut.record"), "R",
            self._on_record_shortcut, self,
        )
        mgr.register_global(
            "escape", tr("shortcut.stop_playback"), "Esc",
            self._on_escape, self,
        )
        # 打开文件
        mgr.register_global(
            "open_file", "打开文件", "Ctrl+O",
            self._on_open_file, self,
        )
        # 导出
        mgr.register_global(
            "export", "导出图表", "Ctrl+E",
            self._on_export_figure, self,
        )
        # 设置
        mgr.register_global(
            "settings", "设置", "Ctrl+,",
            self._on_settings, self,
        )
        # 放大
        mgr.register_global(
            "zoom_in", "放大", "Ctrl+=",
            self._on_zoom_in, self,
        )
        # 缩小
        mgr.register_global(
            "zoom_out", "缩小", "Ctrl+-",
            self._on_zoom_out, self,
        )
        # 适应窗口
        mgr.register_global(
            "zoom_fit", "适应窗口", "Ctrl+0",
            self._on_zoom_fit, self,
        )
        # T-324 选区快速试听与 A/B 循环（Pβ）
        mgr.register_global(
            "preview_selection", tr("shortcut.preview_selection"), "P",
            self._on_preview_selection, self,
        )
        mgr.register_global(
            "loop_selection", tr("shortcut.loop_selection"), "L",
            self._on_loop_shortcut, self,
        )
        # T-325 播放中打点标注（Pγ）：T=纯时间点 / M=带文本点 / Shift+T=撤销上一打点
        # context=WidgetWithChildrenShortcut：焦点在独立 Popup（如标注输入框）时不误触发，
        # 保证 M 弹输入期间可正常输入 t/m 字母、播放不被快捷键打断。
        for _aid, _label, _key, _cb in (
            ("annotate_instant", tr("shortcut.annotate_instant"), "T",
             self._on_annotate_playhead),
            ("annotate_instant_text", tr("shortcut.annotate_instant_text"), "M",
             self._on_annotate_playhead_text),
            ("undo_last_marker", tr("shortcut.undo_last_marker"), "Shift+T",
             self._on_undo_playhead_annotate),
        ):
            _sc = mgr.register_global(_aid, _label, _key, _cb, self)
            _sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

        # T-1087 M1（真机目测 #7）：多轨态进出键位。★ 不走 QAction.setShortcut——
        # test_menu_restructure:149 冻结 action_multitrack_compare 键位为空（该档
        # 不在本件授权面）⇒ 按 2753 起同族口径以 QShortcut 注册，触发一次
        # action.toggle()，态源仍是该可勾选动作（_on_multitrack_toggled 单入口）。
        mgr.register_global(
            "multitrack_mode", tr("shortcut.multitrack_mode"), "Ctrl+M",
            lambda: self.action_multitrack_compare.toggle(), self,
        )

    def _on_record_shortcut(self):
        """录音全局快捷键（R）入口：等价于点击传输条录音按钮（●/■）。

        CB-013 D-1：以 transport_bar.btn_record 当前勾选态为唯一状态源，取反后
        走既有 _on_record_toggle（与 ● 按钮同一入口，含录音设置抽屉/停止保存既有
        流程），再经 set_record_button_state 同步按钮显示态。无音频/无输入设备等
        前置条件与 ● 按钮行为保持一致，不另设逻辑。
        """
        new_checked = not self.transport_bar.btn_record.isChecked()
        self._on_record_toggle(new_checked)
        self.transport_bar.set_record_button_state(new_checked)

    def _on_escape(self):
        """Esc 全局快捷键：有选区先取消选区，无选区则停止播放。

        CB-013 D-1：Esc 不再直接等同 stop，而是「有选区先清选区、无选区才停止」
        （语义见 action_select_none 上方注释），与编辑取消选区习惯一致。
        """
        if self.waveform_widget.get_selection() is not None:
            self._on_edit_select_none()
        else:
            self._on_stop()

    def _current_analysis_widget(self):
        """获取当前激活的分析控件。"""
        mode = self.analysis_tab_bar.currentIndex()
        attr_map = {
            1: "_spectrogram_widget",
            2: "_pitch_widget",
            3: "_formant_widget",
            4: "_timbre_widget",
            5: "_spectrogram3d_widget",
        }
        attr = attr_map.get(mode)
        if attr:
            return self._live_widget(attr)
        return None

    def _on_zoom_in(self):
        """放大当前视图。"""
        w = self._current_analysis_widget()
        if w and hasattr(w, "zoom_in"):
            w.zoom_in()
        elif hasattr(self.waveform_widget, "zoom_in"):
            self.waveform_widget.zoom_in()

    def _on_zoom_out(self):
        """缩小当前视图。"""
        w = self._current_analysis_widget()
        if w and hasattr(w, "zoom_out"):
            w.zoom_out()
        elif hasattr(self.waveform_widget, "zoom_out"):
            self.waveform_widget.zoom_out()

    def _on_zoom_fit(self):
        """适应窗口。"""
        w = self._current_analysis_widget()
        if w and hasattr(w, "zoom_fit"):
            w.zoom_fit()
        elif hasattr(self.waveform_widget, "zoom_fit"):
            self.waveform_widget.zoom_fit()

    # ------------------------------------------------------------------
    # T-1002 视图菜单绘图导航（委派当前视图既有实现，不新建缩放状态机）
    # ------------------------------------------------------------------

    def _view_plot_targets(self) -> list:
        """当前激活分析控件 + 波形控件（与 _on_zoom_fit 同口径，去重后有序）。"""
        targets = []
        w = self._current_analysis_widget()
        if w is not None:
            targets.append(w)
        targets.append(self.waveform_widget)
        return targets

    def _dispatch_view_command(self, *method_names: str) -> bool:
        """依次委派既有方法（duck-typed，同 _on_zoom_fit 口径）；命中即返回。

        全部未命中时回落当前控件 plot_widget.autoRange()（pyqtgraph 既有能力）。
        """
        for target in self._view_plot_targets():
            for name in method_names:
                fn = getattr(target, name, None)
                if callable(fn):
                    fn()
                    return True
        for target in self._view_plot_targets():
            plot = getattr(target, "plot_widget", None)
            if plot is not None and hasattr(plot, "autoRange"):
                plot.autoRange()
                return True
        return False

    def _on_view_reset_axis(self) -> None:
        """视图·复位 X 轴：委派视图既有 _reset_x（音高控件已实现），否则回落 autoRange。"""
        self._dispatch_view_command("_reset_x")

    def _on_view_reset_view(self) -> None:
        """视图·复位视图：委派视图既有 _reset_view（3D 默认视角），否则回落 autoRange。"""
        self._dispatch_view_command("_reset_view")

    # ------------------------------------------------------------------
    # Tips 条
    # ------------------------------------------------------------------

    def _rotate_tip(self):
        """轮换到下一条提示。"""
        self._tip_index = (self._tip_index + 1) % len(self._tip_keys)
        self.show_tip(self._tip_keys[self._tip_index], contextual=False)

    def show_tip(self, key: str, contextual: bool = True):
        """显示提示；上下文提示临时接管 5 秒后恢复轮换。"""
        text = tr(key)
        if not text or text == key:
            return
        self.tip_bar.show_text(tr("tip.prefix"), text)
        if contextual:
            self._tip_timer.stop()
            self._tip_resume.start()

    def show_tip_text(self, text: str):
        """显示自定义文本提示（临时接管 5 秒后恢复轮换）。"""
        self.tip_bar.show_text(tr("tip.prefix"), text)
        self._tip_timer.stop()
        self._tip_resume.start()

    # ------------------------------------------------------------------
    # 波形编辑（Audacity 风格）
    # ------------------------------------------------------------------

    _EDIT_LABEL_KEYS = {
        "cut": "edit.cut", "copy": "edit.copy", "paste": "edit.paste",
        "delete": "edit.delete", "silence": "edit.silence",
        "trim": "edit.trim", "effect": "edit.trim",
    }

    def _setup_editing(self):
        self.editor = EditingController()

    def _edit_error_text(self, e: EditError) -> str:
        key = {"need_selection": "edit.need_selection",
               "clipboard_empty": "edit.clipboard_empty"}.get(str(e))
        return tr(key) if key else str(e)

    def _update_edit_actions(self):
        """按当前状态刷新编辑动作的可用性与撤销文案。"""
        has_audio = self.controller.has_audio()
        has_sel = self.waveform_widget.get_selection() is not None
        can_edit = has_audio and not self._recording_active()

        for act in (self.action_cut, self.action_copy, self.action_delete,
                    self.action_silence, self.action_trim,
                    self.action_select_all, self.action_zoom_sel):
            act.setEnabled(can_edit)
        self.action_paste.setEnabled(
            can_edit and self.editor.clipboard.has()
        )
        self.action_select_none.setEnabled(has_sel)
        self.action_zoom_sel.setEnabled(has_sel)

        self.action_undo.setEnabled(self.editor.can_undo())
        self.action_redo.setEnabled(self.editor.can_redo())
        label = self.editor.last_label()
        key = self._EDIT_LABEL_KEYS.get(label)
        suffix = f" {tr(key)}" if key else ""
        self.action_undo.setText(tr("edit.undo") + suffix)
        self.action_redo.setText(tr("edit.redo"))
        # T-326 Pδ：测量动作 enable 随选区/激活视图刷新（既有刷新点统一收敛于此）
        self._update_measure_actions()

    # ------------------------------------------------------------------
    # T-326 Pδ：悬停读数上抛 + 两点测量（复用选区；A/B 标记 + 状态栏临时段）
    # ------------------------------------------------------------------

    def _current_measure_widget(self):
        """当前激活的时间类分析视图（Pδ 读数源：语谱图/音高/共振峰/音色）。"""
        idx = self.analysis_tab_bar.currentIndex()
        attr = {
            2: "_spectrogram_widget",
            3: "_pitch_widget",
            4: "_formant_widget",
            5: "_timbre_widget",
        }.get(idx)
        return self._live_widget(attr) if attr else None

    def _inject_hover_readout(self, w) -> None:
        """给分析视图注入 Pδ 悬停读数上抛回调（属性注入，仿 _wave_link_callback 模式）。"""
        w._on_hover_readout = self._on_view_hover_readout

    def _on_view_hover_readout(self, text: str | None) -> None:
        """视图悬停读数上抛 → 状态栏临时段（离开 None；测量结果存在时悬停仅临时接管）。"""
        seg = getattr(self, "status_segments", None)
        if seg is None:
            return
        if text:
            seg.set_temporary_text(text)
        elif getattr(self, "_measure_active", False) and self._measure_status_text:
            seg.set_temporary_text(self._measure_status_text)
        elif getattr(self, "_multitrack_mode", False):
            # T-1087 M3：多轨态鼠标离开呈现带 ⇒ 临时段回到 D4「轨 N/M · 健康提示」，
            # 不清空（清空后只有切轨/加轨才再出现，状态栏看起来像坏了）。
            self._update_multitrack_status()
        else:
            seg.clear_temporary()

    def _update_measure_actions(self) -> None:
        """T-326 Pδ 动作 enable：测量选区=有选区且激活时间类分析视图；清除测量=有标记。"""
        sel = self.waveform_widget.get_selection()
        self.action_measure_selection.setEnabled(
            sel is not None and self._current_measure_widget() is not None
        )
        self.action_measure_clear.setEnabled(
            bool(getattr(self, "_measure_active", False))
        )
        # T-327 Pε：区间统计 enable = 有音频且有选区（无选区 → 触发时 toast 防御）
        # 注：__init__ 早期(建菜单动作前)也调此方法 → hasattr 守卫
        stats_action = getattr(self, "action_region_stats", None)
        if stats_action is not None:
            stats_action.setEnabled(
                bool(self.controller.has_audio()) and sel is not None
            )
        # T-1002：「分析此区域」enable 沿用同一数据源（有音频且有选区，只读）；
        # 「批处理」enable = BatchWorkspace 注册表非空（T-913/914 已注册模块 → 可用）
        analyze_action = getattr(self, "action_analyze_region", None)
        if analyze_action is not None:
            analyze_action.setEnabled(
                bool(self.controller.has_audio()) and sel is not None
            )
        batch_action = getattr(self, "action_batch", None)
        if batch_action is not None:
            from acouscope.ui.widgets.batch_workspace import registered_modules

            batch_action.setEnabled(bool(registered_modules()))
        # T-1003：「导出报告…」enable = 有音频（无音频触发时 toast info 防御）
        report_action = getattr(self, "action_export_report", None)
        if report_action is not None:
            report_action.setEnabled(bool(self.controller.has_audio()))
        # T-1102：「导出报告 PDF…」enable = 有音频（与 HTML 快导同源）
        pdf_action = getattr(self, "action_export_report_pdf", None)
        if pdf_action is not None:
            pdf_action.setEnabled(bool(self.controller.has_audio()))
        # T-1103：「报告预览…」enable = 有音频（与导出 PDF 同闸同源）
        preview_action = getattr(self, "action_report_preview", None)
        if preview_action is not None:
            preview_action.setEnabled(bool(self.controller.has_audio()))
        # T-1004：「多轨对比…」enable = 有音频或会话已有轨（进入轨道区的前提）
        multitrack_action = getattr(self, "action_multitrack_compare", None)
        if multitrack_action is not None:
            multitrack_action.setEnabled(self._can_enter_multitrack())
        # T-1004 D6：多轨态只读动作灰化（本方法为 enable 汇聚点，需每轮重施）
        self._apply_multitrack_action_states()

    def _on_measure_selection(self) -> None:
        """「测量选区」：波形选区两端 = A(t0)/B(t1)，在当前激活视图读频并计算 Δ。"""
        sel = self.waveform_widget.get_selection()
        if sel is None:
            show_toast(self, tr("edit.no_selection"), level="info")
            return
        w = self._current_measure_widget()
        if w is None:
            return  # enable 已禁（菜单不可达），静默防御
        lo, hi = (float(sel[0]), float(sel[1]))
        t0, t1 = (lo, hi) if hi >= lo else (hi, lo)
        dt = abs(t1 - t0)
        freq_at = getattr(w, "freq_at", None)
        f0 = freq_at(t0) if freq_at is not None else None
        f1 = freq_at(t1) if freq_at is not None else None
        if f0 is not None and f1 is not None and f0 > 0 and f1 > 0:
            import math

            df = abs(f1 - f0)
            dc = 1200.0 * math.log2(f1 / f0)
            ratio = f1 / f0
            text = tr("measure_result.full").format(
                dt=f"{dt:.3f}", df=f"{df:.1f}",
                dc=f"{dc:.1f}", ratio=f"{ratio:.3f}",
            )
        else:
            # 任一频率 None/≤0（无声/无数据/不支持视图）：只留 Δt（禁臆造插值）
            text = tr("measure_result.dt_only").format(dt=f"{dt:.3f}")
        seg = getattr(self, "status_segments", None)
        if seg is not None:
            seg.set_temporary_text(text)
        self._measure_active = True
        self._measure_status_text = text
        show = getattr(w, "measure_markers_show", None)
        if show is not None:
            show(t0, t1, f0, f1)
        ov = getattr(w, "set_readout_overlay", None)
        if ov is not None:
            ov(text)
        self._update_measure_actions()

    def _on_measure_clear(self) -> None:
        """「清除测量」：清除分析视图 A/B 标记 + 状态栏临时段（不动选区）。"""
        for attr in ("_spectrogram_widget", "_pitch_widget", "_formant_widget"):
            w = self._live_widget(attr)
            if w is None:
                continue
            clear = getattr(w, "measure_markers_clear", None)
            if clear is not None:
                clear()
            ov = getattr(w, "set_readout_overlay", None)
            if ov is not None:
                ov(None)
        self._measure_active = False
        self._measure_status_text = None
        seg = getattr(self, "status_segments", None)
        if seg is not None:
            seg.clear_temporary()
        self._update_measure_actions()

    # ------------------------------------------------------------------
    # T-327 Pε：选区区间统计（时长/RMS·峰值/音高统计；数据源=既有缓存与控件
    # 结果，禁重算分析——路径零 _on_*_analysis 调用）
    # ------------------------------------------------------------------

    def _pitch_arrays_for_stats(self, t0: float, t1: float):
        """取现有音高结果 (times, f0)：区间缓存命中 > 控件显示 > 全文件缓存。

        区间缓存键为 T-321 产物（含 round(t0,3)/round(t1,3)），与「分析此区域」
        的落键口径一致；任一来源缺失或区间无重叠 → None（调用方 toast 引导）。
        """
        if not self.controller.has_audio():
            return None
        fp = self._audio_fingerprint()
        cached = self._cache_get(self._cache_key("pitch", fp, (t0, t1)))
        if cached is not None and len(cached) >= 2:
            times, f0 = cached[0], cached[1]
            if times.size and float(times[-1]) >= t0 and float(times[0]) <= t1:
                return (times, f0)
        w = self._live_widget("_pitch_widget")
        getter = getattr(w, "result_arrays", None) if w is not None else None
        if getter is not None:
            times, f0 = getter()
            if times.size and float(times[-1]) >= t0 and float(times[0]) <= t1:
                return (times, f0)
        cached_full = self._cache_get(self._cache_key("pitch", fp))
        if cached_full is not None and len(cached_full) >= 2:
            times, f0 = cached_full[0], cached_full[1]
            if times.size and float(times[-1]) >= t0 and float(times[0]) <= t1:
                return (times, f0)
        return None

    def _on_region_stats(self) -> None:
        """「分析>区间统计」：波形选区 → 时长/能量(RMS·峰值 dB+线性)/音高摘要。

        结果写入检查器只读区（InspectorPanel.set_region_stats，非模态、可复制）；
        无选区/无音频/无分析结果 → toast 引导（禁触发分析）。
        """
        sel = self.waveform_widget.get_selection()
        if sel is None:
            show_toast(self, tr("edit.no_selection"), level="info")
            return
        if not self.controller.has_audio():
            show_toast(self, tr("msg.no_audio"), level="info")
            return
        lo, hi = (float(sel[0]), float(sel[1]))
        t0, t1 = (lo, hi) if hi >= lo else (hi, lo)
        pitch = self._pitch_arrays_for_stats(t0, t1)
        if pitch is None:
            show_toast(self, tr("region_stats.no_cache"), level="info")
            return

        from acouscope.ui.region_stats import pitch_stats, region_peak, region_rms

        data = self.controller.audio_data
        if data is None or len(data) == 0:
            show_toast(self, tr("msg.no_audio"), level="info")
            return
        if data.ndim > 1:
            data = data.mean(axis=1)
        sr = float(self.controller.sample_rate or 1.0)
        i0 = max(0, int(round(t0 * sr)))
        i1 = min(int(len(data)), int(round(t1 * sr)))
        seg = data[i0:i1] if i1 > i0 else data[:0]

        lin = None
        rms_db = None
        peak_db = None
        if seg.size:
            lin, rms_db = region_rms(seg)
            _pk_lin, peak_db = region_peak(seg)
        fmt_db = "--" if rms_db is None else f"{rms_db:.1f}"
        fmt_lin = "--" if lin is None else f"{lin:.4f}"
        fmt_pk = "--" if peak_db is None else f"{peak_db:.1f}"

        rows = [
            tr("region_stats.r_time").format(
                t0=f"{t0:.3f}", t1=f"{t1:.3f}", dt=f"{t1 - t0:.3f}"
            ),
            tr("region_stats.r_rms").format(
                rms=fmt_db, lin=fmt_lin, peak=fmt_pk
            ),
        ]

        def _hz(val) -> str:
            return "--" if val is None else f"{val:.1f}"

        stats = pitch_stats(pitch[0], pitch[1], t0, t1)
        if stats is not None and stats["voiced"]:
            ratio = stats["voiced_ratio"]
            rows.append(
                tr("region_stats.r_pitch").format(
                    v=stats["voiced"], n=stats["frames"],
                    pct="--" if ratio is None else f"{ratio:.0%}",
                    mean=_hz(stats["f0_mean"]),
                    median=_hz(stats["f0_median"]),
                    fmin=_hz(stats["f0_min"]),
                    fmax=_hz(stats["f0_max"]),
                    rng=_hz(stats["f0_range"]),
                    cent=("--" if stats["cent_mean"] is None
                          else f"{stats['cent_mean']:+.1f}"),
                )
            )
        else:
            rows.append(tr("region_stats.r_pitch_na"))

        ins = getattr(self, "inspector_panel", None)
        if ins is not None:
            ins.set_region_stats("\n".join(rows))

    def _recording_active(self) -> bool:
        rec = getattr(self, "_recorder", None)
        return bool(rec is not None and getattr(rec, "_is_recording", False))

    def _current_audio(self) -> np.ndarray:
        data = self.controller.audio_data
        if data is None or len(data) == 0:
            raise EditError("need_audio")
        return data

    def _edit_sel(self):
        return self.waveform_widget.get_selection()

    def _apply_edited_audio(self, new_data: np.ndarray) -> None:
        """把编辑结果写回控制器/波形/元数据。"""
        sr = self.controller.sample_rate
        new32 = np.asarray(new_data, dtype=np.float32)
        if self.controller.is_playing():
            self._on_stop()

        self.controller.load_from_array(new32, sr, "edited.wav")
        times = np.arange(len(new32), dtype=np.float32) / np.float32(sr)
        self.waveform_widget.set_data(times, new32, sample_rate=sr)

        info = self.controller.audio_info
        if info is not None:
            self.metadata_bar.set_info(
                info, self.controller.audio_data, info.sample_rate
            )
        self._update_edit_actions()

    def _on_edit_undo(self):
        try:
            new = self.editor.undo(self._current_audio(), self.controller.sample_rate)
        except EditError as e:
            self.lbl_status.setText(self._edit_error_text(e))
            return
        self._apply_edited_audio(new)

    def _on_edit_redo(self):
        try:
            new = self.editor.redo(self._current_audio(), self.controller.sample_rate)
        except EditError as e:
            self.lbl_status.setText(self._edit_error_text(e))
            return
        self._apply_edited_audio(new)

    def _on_edit_copy(self):
        try:
            data = self._current_audio()
            self.editor.copy(data, self.controller.sample_rate, self._edit_sel())
        except EditError as e:
            self.lbl_status.setText(self._edit_error_text(e))
            return
        self._update_edit_actions()

    def _on_edit_cut(self):
        try:
            data = self._current_audio()
            new = self.editor.cut(data, self.controller.sample_rate, self._edit_sel())
        except EditError as e:
            self.lbl_status.setText(self._edit_error_text(e))
            return
        self._apply_edited_audio(new)

    def _on_edit_delete(self):
        try:
            data = self._current_audio()
            new = self.editor.delete(data, self.controller.sample_rate, self._edit_sel())
        except EditError as e:
            self.lbl_status.setText(self._edit_error_text(e))
            return
        self._apply_edited_audio(new)

    def _on_edit_paste(self):
        try:
            data = self._current_audio()
            sr = self.controller.sample_rate
            sel = self._edit_sel()
            # 有选区：粘贴替换选区（Audacity 行为）
            if sel is not None:
                new = self.editor.delete(data, sr, sel)
                new = self.editor.paste(new, sr, sel[0])
                # 合并为一步可撤销操作：重做栈已清空，无需合并处理
            else:
                new = self.editor.paste(data, sr, self.waveform_widget.get_playhead_time())
        except EditError as e:
            self.lbl_status.setText(self._edit_error_text(e))
            return
        self._apply_edited_audio(new)

    def _on_edit_silence(self):
        try:
            data = self._current_audio()
            new = self.editor.silence(data, self.controller.sample_rate, self._edit_sel())
        except EditError as e:
            self.lbl_status.setText(self._edit_error_text(e))
            return
        self._apply_edited_audio(new)

    def _on_edit_trim(self):
        try:
            data = self._current_audio()
            new = self.editor.trim(data, self.controller.sample_rate, self._edit_sel())
        except EditError as e:
            self.lbl_status.setText(self._edit_error_text(e))
            return
        self._apply_edited_audio(new)
        self.waveform_widget.zoom_fit()

    def _on_edit_select_all(self):
        info = self.controller.audio_info
        if info and info.duration > 0:
            self.waveform_widget.set_selection(0.0, info.duration)

    def _on_edit_select_none(self):
        self.waveform_widget.clear_selection()

    def _on_edit_zoom_sel(self):
        self.waveform_widget.zoom_to_selection()

    def _on_selection_changed(self, sel):
        # T-326 Pδ：选区清除（含 Esc 既有语义「有选区先清选区」）→ 测量 A/B 标记随之清除
        if sel is None and getattr(self, "_measure_active", False):
            self._on_measure_clear()
        if sel is None:
            self.lbl_status.setText(tr("edit.no_selection"))
        else:
            lo, hi = sel
            self.lbl_status.setText(
                f"{tr('edit.sel_label')}: {lo:.3f} s – {hi:.3f} s  ({hi - lo:.3f} s)"
            )
        self._update_edit_actions()

        # T-507b：检查器选区刷新
        ins = getattr(self, "inspector_panel", None)
        if ins is not None:
            ins.set_selection(sel)

        # CB-016-3：检查器分析范围数值刷新（选区变化刷新点之一；蓝条已移除，
        # 显示「分析位置 X.XXXs · 窗口 Y.YYYs」）
        if ins is not None:
            fs = getattr(self.waveform_widget, "get_frame_size", lambda: 1.0)()
            ins.set_analysis_scope(self.waveform_widget.get_analysis_position(), fs)

    def _on_wave_playhead_seek(self, t: float):
        if self.controller.has_audio():
            self.controller.set_position(t)
        self.waveform_widget.set_playhead(t)

    # ------------------------------------------------------------------
    # T-323 播放联动：分析视图时间交互分发 / 跨视图同步 / 播放跟随滚动
    # （各分析视图只上抛信号，本窗口为唯一分发者，禁视图直连 controller）
    # ------------------------------------------------------------------

    def _link_time_view_signals(self, w) -> None:
        """连接分析视图 T-323 时间交互信号（懒构建各分支构建完成后调用）。"""
        w.timeClicked.connect(self._on_time_clicked)
        w.timeDoubleClicked.connect(self._on_time_double_clicked)
        w.timeScrubbed.connect(self._on_time_scrubbed)
        w.xRangeShifted.connect(
            lambda lo, hi, _w=w: self._on_time_xrange_shifted(_w, lo, hi)
        )

    def _time_views(self) -> list:
        """现存时间类分析视图（语谱图/音高/共振峰/音色，已销毁者跳过）。"""
        out = []
        for attr in ("_spectrogram_widget", "_pitch_widget",
                     "_formant_widget", "_timbre_widget"):
            w = getattr(self, attr, None)
            if w is None:
                continue
            try:
                w.parent()
            except RuntimeError:
                continue
            out.append(w)
        return out

    def _on_time_clicked(self, t: float) -> None:
        """单击：定位播放头（播放中=跳播继续，停止态=定位待播）。"""
        if not self.controller.has_audio():
            return
        self._reset_preview_guard()  # T-324：用户单击接管 → 退出试听守卫
        self.controller.set_position(float(t))
        self.waveform_widget.set_playhead(float(t))

    def _on_time_double_clicked(self, t: float) -> None:
        """双击：从此处播放。"""
        if not self.controller.has_audio():
            return
        self._reset_preview_guard()  # T-324：双击起播接管 → 退出试听守卫
        self.controller.set_position(float(t))
        self.waveform_widget.set_playhead(float(t))
        if not self.controller.is_playing():
            self.controller.play()
            self._play_timer.start()
            self.transport_bar.set_play_button_state(True)
            panel = self._live_widget("_realtime_panel")
            if panel is not None:
                panel.set_position(float(t))
                panel.set_playing(True)

    def _on_time_scrubbed(self, t: float) -> None:
        """Alt+拖 scrub：节流 ~30Hz 实时 set_position（连续试听定位）。"""
        import time as _time

        if not self.controller.has_audio():
            return
        self._reset_preview_guard()  # T-324：scrub 浏览接管 → 退出试听守卫
        now = _time.monotonic()
        if now - self._scrub_last_at < 0.033:
            return
        self._scrub_last_at = now
        self.controller.set_position(float(t))
        self.waveform_widget.set_playhead(float(t))

    def _set_view_time_range(self, w, lo: float, hi: float) -> None:
        """给单个时间视图套用 X 时间窗（分析视图经 set_time_range 防自激上抛；
        波形视图无上抛通道，直接 setXRange，其滚动条由内部 sigRangeChanged 跟随）。"""
        setter = getattr(w, "set_time_range", None)
        if setter is not None:
            setter(lo, hi)
        else:
            w.plot_widget.setXRange(lo, hi, padding=0)

    def _broadcast_time_range(self, lo: float, hi: float, source=None) -> None:
        """跨视图平移同步：广播时间窗给波形 + 其余时间类视图（跳过 source 防回环）。"""
        for w in self._time_views():
            if w is source:
                continue
            self._set_view_time_range(w, float(lo), float(hi))
        if self.waveform_widget is not source:
            self.waveform_widget.plot_widget.setXRange(float(lo), float(hi), padding=0)

    def _on_time_xrange_shifted(self, source, lo: float, hi: float) -> None:
        """任一视图用户平移：解除播放跟随，并把同一时间窗同步到其余时间视图。"""
        self._follow_enabled = False
        self._broadcast_time_range(float(lo), float(hi), source=source)

    def _update_follow_scroll(self, pos: float) -> None:
        """播放 tick：播放头越过可视右缘 → 平移时间视图使播放头位于约 1/3 处。

        用户手动平移后 follow 置 False；播放头再次越过右缘才恢复（需求说明规格 3）。
        """
        try:
            vlo, vhi = self.waveform_widget.plot_widget.plotItem.vb.viewRange()[0]
        except Exception:
            return
        if pos <= vhi:
            return
        if not self._follow_enabled:
            self._follow_enabled = True  # 再次到右缘恢复跟随
        width = max(vhi - vlo, 1e-6)
        new_lo = pos - width / 3.0
        self._broadcast_time_range(new_lo, new_lo + width)

    # ------------------------------------------------------------------
    # 录音功能（Audacity 风格）
    # ------------------------------------------------------------------

    def _populate_input_devices(self):
        """填充输入设备下拉框。"""
        combo = self.transport_bar.cmb_input_device
        try:
            from acouscope.audio.recorder import AudioRecorder
            devices = AudioRecorder.list_devices()
            for desc, dev in devices:
                combo.addItem(desc, dev)
            if not devices:
                combo.addItem("（无输入设备）", None)
        except Exception:
            combo.addItem("（不可用）", None)

    def _get_recorder(self):
        """获取或创建录音器实例。"""
        if self._recorder is None:
            from acouscope.audio.recorder import AudioRecorder
            self._recorder = AudioRecorder()
            self._recorder.set_level_callback(self._on_record_level)
            self._recorder.set_data_callback(self._on_record_chunk)
        return self._recorder

    def _on_record_chunk(self, chunk):
        """录音数据块回调：驱动波形与实时面板的实时显示。"""
        self.waveform_widget.append_live_chunk(chunk)
        panel = self._live_widget("_realtime_panel")
        if panel is not None and hasattr(panel, "push_live_chunk"):
            panel.push_live_chunk(chunk)

    def _on_record_toggle(self, checked: bool):
        """开始/停止录音。"""
        # T-1004 D6：多轨态只读——录音仅单轨模式可用（拦下并复位按钮 + 引导提示；
        # 多轨态新状态下生效，单轨主态路径零变化）
        if checked and getattr(self, "_multitrack_mode", False):
            btn = getattr(getattr(self, "transport_bar", None), "btn_record", None)
            if btn is not None:
                btn.blockSignals(True)
                btn.setChecked(False)
                btn.blockSignals(False)
            show_toast(self, tr("multitrack.readonly"), level="info")
            return
        # T-1054 批4c（R2）：录音设置页常驻左栏 index3；再点同入口 = 收回左栏页
        # （不进入停止/保存路径；录音运行态本分支不成立 → 录音中再点仍为停止）
        if not checked:
            if self._record_page_is_current() and not self._record_timer.isActive():
                self._on_left_page_toggled(False, 3)
                self.transport_bar.set_record_button_state(False)
                return
        recorder = self._get_recorder()

        if checked:
            self._on_left_page_toggled(True, 3)
        else:
            # 停止录音并保存
            self.waveform_widget.end_live_capture()
            panel = self._live_widget("_realtime_panel")
            if panel is not None and hasattr(panel, "end_live_capture"):
                panel.end_live_capture()

            data = recorder.stop()
            self._record_timer.stop()
            self.transport_bar.set_record_button_state(False)
            self._set_status_record_timer(0)
            self.waveform_widget.vu_meter.reset()
            self._update_edit_actions()

            if data is not None and len(data) > 0:
                duration = recorder.get_duration()

                # 自动保存到用户设定的文件
                save_msg = ""
                pending = getattr(self, "_pending_recording", None)
                if pending:
                    from acouscope.audio.recorder import save_audio_file

                    ok, info = save_audio_file(
                        data, recorder.get_sample_rate(),
                        pending["path"], pending["fmt"], pending["depth"],
                    )
                    save_msg = (
                        f"已保存到：{info}" if ok
                        else f"保存失败：{info}"
                    )
                    self._pending_recording = None

                # T-504c 条件化（UI 宪法条 3 对话框最小化）：
                # 工作区无已加载音频 → 自动加载 + toast（免询问）；
                # 仅当已有音频时保留 question（模态白名单：防覆盖当前
                # 分析中的音频，破坏性确认）
                sr = recorder.get_sample_rate()
                if self.controller.audio_data is None:
                    # 无已加载音频：直接执行原 Yes 分支 + 成功 toast
                    self.controller.load_from_array(data, sr, "recording.wav")
                    rec_times = np.arange(len(data), dtype=np.float32) / np.float32(sr)
                    self.waveform_widget.set_data(rec_times, data, sample_rate=sr)
                    if self.controller.audio_info is not None:
                        self.metadata_bar.set_info(
                            self.controller.audio_info,
                            self.controller.audio_data,
                            self.controller.sample_rate,
                        )
                    self._update_edit_actions()
                    self._on_analysis_changed(self.analysis_tab_bar.currentIndex())
                    show_toast(
                        self, f"已录制 {duration:.1f} 秒。{save_msg}".strip(),
                        level="success",
                    )
                else:
                    # 已有音频：保留模态 question（防覆盖白名单）
                    question_text = (
                        f"已录制 {duration:.1f} 秒。"
                        + (f"\n{save_msg}" if save_msg else "")
                        + "\n是否加载到波形中进行分析？"
                    )
                    reply = QMessageBox.question(
                        self, "录音完成",
                        question_text,
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.Yes,
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        self.controller.load_from_array(data, sr, "recording.wav")
                        rec_times = np.arange(len(data), dtype=np.float32) / np.float32(sr)
                        self.waveform_widget.set_data(rec_times, data, sample_rate=sr)
                        if self.controller.audio_info is not None:
                            self.metadata_bar.set_info(
                                self.controller.audio_info,
                                self.controller.audio_data,
                                self.controller.sample_rate,
                            )
                        self._update_edit_actions()
                        self._on_analysis_changed(self.analysis_tab_bar.currentIndex())
            else:
                show_toast(self, "没有录制到音频数据。", level="info")
                self._pending_recording = None

    def _begin_recording_from_settings(self):
        """录音设置面板 accepted：收回左栏页（R4-F）并启动录音。

        收回经唯一槽 `_on_left_page_toggled(False, 3)`（= 原 `close_drawer()` 等价）；
        承载原模态流 accepted 分支的启动逻辑；recorder.start 失败回滚
        与原一致：toast + 按钮复位 + pending 清空。
        """
        self._on_left_page_toggled(False, 3)
        panel = self.record_settings_panel
        if panel is None:
            self.transport_bar.set_record_button_state(False)
            return

        recorder = self._get_recorder()

        self._pending_recording = {
            "path": panel.file_path(),
            "fmt": panel.format_name(),
            "depth": panel.depth(),
        }

        device = self.transport_bar.cmb_input_device.currentData()
        if device is not None:
            recorder.set_device(device)

        recorder.set_sample_rate(panel.sample_rate())
        recorder.set_channels(panel.channels())

        # 停止当前播放
        self._on_stop()

        ok = recorder.start()
        if not ok:
            show_toast(self, "无法启动录音，请检查输入设备。", level="warning")
            self.transport_bar.set_record_button_state(False)
            self._pending_recording = None
            return

        # 实时显示：波形滚动 + 实时面板 LIVE
        sr = recorder.get_sample_rate()
        self.waveform_widget.begin_live_capture(sr)
        panel_rt = self._live_widget("_realtime_panel")
        if panel_rt is not None and hasattr(panel_rt, "begin_live_capture"):
            panel_rt.begin_live_capture(sr)

        self._record_timer.start()
        self.transport_bar.set_record_button_state(True)
        self._update_edit_actions()

    def _on_recording_settings_cancelled(self):
        """录音设置面板取消（点取消按钮）：未录音 → 按钮复位；录音中 → 走停止流程。

        M6：页常驻后取消按钮在**录音运行态**仍可达（原抽屉流程不可达）⇒ 若只
        复位按钮会留下「按钮灭着但录音在跑」分裂态；此处改为经既有停止/保存
        流程（`_on_record_toggle(False)`）停录 + 复位，运行状态源仍为 btn_record。
        """
        if self._record_timer.isActive() or self._recording_active():
            self._on_record_toggle(False)
            self.transport_bar.set_record_button_state(
                self._recording_active()
            )
            return
        self.transport_bar.set_record_button_state(False)

    def _on_record_page_retracted(self) -> None:
        """左栏录音页被外部路径收回/切走 → 未在录音则复位 ● 。

        原 `_on_recording_drawer_closed` 的页语义等价（R3 M5）：面板头录音钮再点、
        工具栏左栏开关、切换左栏页、`left_content.setCurrentIndex(0)` 等外部路径
        不再有抽屉 closed 兜底，故在既有唯一同步槽收敛（禁四处重复贴代码）。
        """
        timer = getattr(self, "_record_timer", None)
        if self._record_page_is_current() or (timer is not None and timer.isActive()):
            return
        tb = getattr(self, "transport_bar", None)
        if tb is None or not tb.btn_record.isChecked():
            return
        self.transport_bar.set_record_button_state(False)

    def _on_record_level(self, level: float):
        """录音电平回调（波形 VU 表显示）。"""
        self.waveform_widget.set_level(level)

    def _on_play_level(self, level: float):
        """播放电平回调（VU 表）。"""
        self.waveform_widget.set_level(level)

    def _update_record_ui(self):
        """更新录音 UI：波形滚动重绘 + 状态栏 + 实时面板跟随。"""
        recorder = self._get_recorder()
        dur = recorder.get_duration()
        mins = int(dur) // 60
        secs = dur - mins * 60
        text = f"录音中 {mins:02d}:{secs:04.1f}"
        if self.lbl_status.text() != text:
            self.lbl_status.setText(text)
        # CB-013 D-2：录音计时段（mm:ss）
        self._set_status_record_timer(dur)
        self.waveform_widget.refresh_live()

        # 实时特征面板跟随录音进度
        panel = self._live_widget("_realtime_panel")
        if panel is not None:
            panel.set_position(dur)
            panel.set_playing(True)

    def _on_play_pause(self):
        """播放/暂停切换。"""
        if not self.controller.has_audio():
            return
        # T-324：空格手动接管播放 → 取消试听选区的一次播完即停守卫
        self._reset_preview_guard()

        if self.controller.is_playing():
            self.controller.pause()
            self._play_timer.stop()
            self.transport_bar.set_play_button_state(False)
        else:
            self.controller.play()
            self._play_timer.start()
            self.transport_bar.set_play_button_state(True)

        panel = self._live_widget("_realtime_panel")
        if panel is not None:
            panel.set_position(self.controller.get_position())
            panel.set_playing(self.controller.is_playing())

    def _on_stop(self):
        """停止播放。"""
        if not self.controller.has_audio():
            return
        self._reset_preview_guard()  # T-324：停止同样退出试听会话

        self.controller.stop()
        self._play_timer.stop()
        self.transport_bar.set_seek_percent(0)
        self.transport_bar.set_time_label(0.0, self.controller.audio_info.duration)
        self._update_status_play_position(0.0, self.controller.audio_info.duration)
        # T-507b：检查器播放位置复位
        ins = getattr(self, "inspector_panel", None)
        if ins is not None:
            ins.set_playback(0.0, self.controller.audio_info.duration)
        self.transport_bar.set_play_button_state(False)
        self.waveform_widget.set_playhead(0.0)
        self.waveform_widget.vu_meter.reset()

        panel = self._live_widget("_realtime_panel")
        if panel is not None:
            panel.set_position(0.0)
            panel.set_playing(False)

    # ------------------------------------------------------------------
    # 波形控件 Transport 处理
    # ------------------------------------------------------------------

    def _on_wave_play_toggled(self, playing: bool):
        """波形播放按钮切换。"""
        if not self.controller.has_audio():
            self.transport_bar.set_play_button_state(False)
            return
        if playing:
            self.controller.play()
            self._play_timer.start()
            self.transport_bar.set_play_button_state(True)
        else:
            self.controller.pause()
            self._play_timer.stop()
            self.transport_bar.set_play_button_state(False)

        panel = self._live_widget("_realtime_panel")
        if panel is not None:
            panel.set_position(self.controller.get_position())
            panel.set_playing(playing)

    def _on_wave_play_stop(self):
        """波形停止。"""
        self._on_stop()

    def _on_wave_skip_start(self):
        """跳到开头。"""
        if not self.controller.has_audio():
            return
        self.controller.set_position(0.0)
        self._update_playback_position()

    def _on_wave_skip_end(self):
        """跳到结尾。"""
        if not self.controller.has_audio() or not self.controller.audio_info:
            return
        duration = self.controller.audio_info.duration
        self.controller.set_position(duration)
        self._update_playback_position()

    def _on_wave_record_toggled(self, recording: bool):
        """波形录音切换。"""
        self._on_record_toggle(recording)

    def _on_wave_position_changed(self, position: float):
        """波形位置变化。"""
        if self.controller.has_audio():
            self.controller.set_position(position)

    def _on_analysis_position_changed_for_inspector(self, position: float):
        """红针移动 → 检查器分析范围读数刷新（CB-016-3 接线）。

        禁复用 positionChanged / position_changed_callback：前者是播放位置
        语义（set_position 会跳播放头），后者是单槽回调且被视图切换覆写。
        """
        ins = getattr(self, "inspector_panel", None)
        if ins is None:
            return
        fs = getattr(self.waveform_widget, "get_frame_size", lambda: 1.0)()
        ins.set_analysis_scope(position, fs)

    def _on_toggle_loop(self, checked: bool):
        """切换循环播放。"""
        # T-324：进入/退出循环都是用户接管播放语义 → 退出试听守卫
        self._reset_preview_guard()
        if not self.controller.has_audio():
            self.transport_bar.set_loop_state(False)
            return

        # 优先用标注区域；否则用波形选区
        region = self.waveform_widget.selected_region()
        loop_range = (region.start_time, region.end_time) if region else None
        if loop_range is None:
            sel = self.waveform_widget.get_selection()
            if sel is not None:
                loop_range = sel

        if checked and loop_range is None:
            show_toast(
                self,
                f"{tr('edit.need_selection')}\n"
                f"{tr('tip.2')}",
                level="info",
            )
            self.transport_bar.set_loop_state(False)
            return

        if checked and loop_range is not None:
            self.controller.set_loop(loop_range[0], loop_range[1])
            self.controller.set_loop_enabled(True)
            # 如果未在播放，自动开始播放
            if not self.controller.is_playing():
                self.controller.set_position(loop_range[0])
                self.controller.play()
                self._play_timer.start()
                self.transport_bar.set_play_button_state(True)
        else:
            self.controller.set_loop_enabled(False)

    # ------------------------------------------------------------------
    # T-324 选区快速试听与 A/B 循环（Pβ）：快捷键一键闭环，零新 UI 形态
    # ------------------------------------------------------------------

    def _reset_preview_guard(self) -> None:
        """退出试听选区的一次播完即停守卫（None=无守卫）。"""
        self._preview_end = None

    def _on_preview_selection(self) -> None:
        """P：试听选区——从选区头播到选区尾自动暂停（一次播完即停，非循环）。

        - 无选区：温和 toast 提示（不播全曲，保持原状态）；
        - 播放中按：先停再从 t0 起播；循环中按：先取消循环再单次播放；
        - 到 t1 自动暂停（容差 20ms，位置停在 t1 附近），后续由用户手动接管。
        """
        if not self.controller.has_audio():
            return
        sel = self.waveform_widget.get_selection()
        if sel is None:
            show_toast(
                self,
                f"{tr('edit.need_selection')}\n"
                f"{tr('tip.2')}",
                level="info",
            )
            return
        t0, t1 = float(sel[0]), float(sel[1])
        if t1 - t0 <= 0:
            return
        self._reset_preview_guard()
        # 循环中按试听：先取消循环，避免被循环接管
        if self.transport_bar.btn_loop.isChecked():
            self.transport_bar.set_loop_state(False)
            self.controller.set_loop_enabled(False)
        # 播放中按试听：先停，再从 t0 干净开播
        if self.controller.is_playing():
            self.controller.pause()
            self._play_timer.stop()
            self.transport_bar.set_play_button_state(False)
        self.controller.set_position(t0)
        self.controller.play()
        self._play_timer.start()
        self.transport_bar.set_play_button_state(True)
        self._preview_end = t1
        panel = self._live_widget("_realtime_panel")
        if panel is not None:
            panel.set_position(t0)
            panel.set_playing(True)

    def _on_loop_shortcut(self) -> None:
        """L：A/B 循环选区开关——等价点击传输条 ⟳ 按钮（复用现链路）。

        复用 transport_bar.btn_loop → loopToggled → _on_toggle_loop 完整语义：
        有选区进入 A/B 循环并起播；再按一次取消循环；无选区由 _on_toggle_loop
        温和提示且不误播全曲。不另建第二个循环开关。
        """
        if not self.controller.has_audio():
            return
        self.transport_bar.btn_loop.click()

    # ------------------------------------------------------------------
    # T-325 播放中打点标注（Pγ）：T/M 打点（光标不停顿）+ Shift+T 撤销上一打点
    # ------------------------------------------------------------------

    def _on_annotate_playhead(self) -> None:
        """T：在播放头打一个纯时间点（播放/停止态均可，光标不停顿）。"""
        self._annotate_at_playhead(with_text=False)

    def _on_annotate_playhead_text(self) -> None:
        """M：播放头打点 + 弹标签输入 popover（非模态、不打断播放）。

        先落纯点（防丢）→ 回车更新文本；Esc/取消 = 保留纯点。
        """
        self._annotate_at_playhead(with_text=True)

    def _annotate_at_playhead(self, with_text: bool) -> None:
        """播放头打点共用入口（T/M）。"""
        if not self.controller.has_audio():
            show_toast(self, tr("annotate.need_audio"), level="info")
            return
        # 连击去重：同一时刻（<50ms）重复触发只落一点（防抖动连击）
        import time as _time
        now = _time.monotonic()
        if (self._last_annotate_mono is not None
                and now - self._last_annotate_mono < 0.05):
            return
        pos = float(self.controller.get_position())
        inst = self.waveform_widget.add_instant(pos, "")
        self._last_annotate_mono = now
        self._last_annotate_time = pos
        if with_text:
            self.waveform_widget.prompt_instant_label(inst)

    def _on_undo_playhead_annotate(self) -> None:
        """Shift+T：撤销最近一次播放打点（时间与最近打点时刻匹配才删）。"""
        self._last_annotate_mono = None
        last_time = self._last_annotate_time
        self._last_annotate_time = None
        if last_time is None:
            return
        instants = self.waveform_widget.annotations.instants
        if not instants:
            return
        last = instants[-1]  # 模型内按时间排序
        if abs(float(last.time) - last_time) < 1e-6:
            self.waveform_widget.delete_instant(last)

    def _on_speed_changed(self, rate: float):
        """播放速率变化。"""
        self.controller.set_playback_rate(rate)
        self.lbl_status.setText(f"播放速率: {rate}x")

    def _on_slider_moved(self, value: int):
        """拖动进度条预览。"""
        if self.controller.audio_info:
            pos = value / 1000.0 * self.controller.audio_info.duration
            self.waveform_widget.set_playhead(pos)

    def _on_slider_released(self):
        """释放进度条定位。"""
        if self.controller.audio_info:
            pos = (
                self.transport_bar.slider_position.value()
                / 1000.0 * self.controller.audio_info.duration
            )
            self.controller.set_position(pos)

    def _update_playback_position(self):
        """更新播放位置显示。"""
        pos = self.controller.get_position()

        if self.controller.audio_info:
            duration = self.controller.audio_info.duration
            if duration > 0:
                self.transport_bar.set_seek_percent(int(pos / duration * 1000))
                self.transport_bar.set_time_label(pos, duration)
                self._update_status_play_position(pos, duration)
                # T-507b：检查器播放位置跟随
                ins = getattr(self, "inspector_panel", None)
                if ins is not None:
                    ins.set_playback(pos, duration)

        # 同步波形播放头与时间显示（Audacity 风格实时跟随）
        self.waveform_widget.set_playhead(pos)

        # T-324：试听选区——播放头到达选区尾 t1（容差 20ms）自动暂停，一次播完即停
        if self._preview_end is not None and self.controller.is_playing():
            if pos >= self._preview_end - 0.02:
                self.controller.pause()
                self._play_timer.stop()
                self.transport_bar.set_play_button_state(False)
                self._preview_end = None
                panel = self._live_widget("_realtime_panel")
                if panel is not None:
                    panel.set_playing(False)

        # T-323：播放跟随滚动——播放头越过可视右缘时平移时间视图
        if self.controller.is_playing():
            self._update_follow_scroll(pos)

        # 实时特征面板跟随（波形视图下）——位置与播放状态统一在此同步，
        # 任何播放入口（空格、按钮、菜单）都会驱动面板进入 LIVE
        panel = self._live_widget("_realtime_panel")
        if panel is not None:
            panel.set_position(pos)
            panel.set_playing(self.controller.is_playing())

        # 如果播放结束
        if self.controller.audio_info and pos >= self.controller.audio_info.duration - 0.05:
            if not self.controller.is_playing():
                self._play_timer.stop()
                self.transport_bar.set_play_button_state(False)
                if panel is not None:
                    panel.set_playing(False)

    def _set_analysis_view(self, index: int):
        """同步分析视图标签卡索引（阻塞信号避免递归触发）。"""
        tabs = getattr(self, "analysis_tab_bar", None)
        if tabs is not None and tabs.currentIndex() != index:
            tabs.blockSignals(True)
            tabs.setCurrentIndex(index)
            tabs.blockSignals(False)
        # CB-016-1：蓝条叠加层显隐同步随蓝条一并移除；
        # T-906：传输条全局化，调用点保留（恒可见语义，见 _sync_transport_visibility）
        self._sync_transport_visibility(index)
        # T-1002：视图菜单勾选态同步（与标签卡同源）
        self._sync_view_menu(index)

    def _sync_transport_visibility(self, index: int) -> None:
        """CB-015-1/T-906 语义变更：传输条全局化，不再随视图显隐。

        方法保留防调用点断链（:1858/:1972/:2132 仍触发，仅不再改变可见性）；
        父容器 waveform_view 常驻于垂直 splitter 顶部（从不被隐藏），
        show() 即保证跨视图常驻。不动 TransportBar 内部逻辑与信号连接。
        """
        tb = getattr(self, "transport_bar", None)
        if tb is None:
            return
        tb.show()  # 恒可见；不再按 index 门控显隐

    def _add_analysis_widget(self, widget, min_h: int = 200):
        """分析控件统一入口：封顶最小高度，保证主分隔条可自由拖动。

        部分控件（FFT 谐波表 / 3D 画布）的自然 minimumSizeHint 可达
        400–700px，会把波形与分析区之间的 QSplitter 卡死；显式设置
        较小的最小尺寸（宽 0 = 不限）后分隔条恢复可拖动。

        注意：必须用 setMinimumSize 同时设置宽高——仅 setMinimumHeight
        时 minimumSize 宽度仍为 -1（invalid），QLayout 会整体回退到
        minimumSizeHint，设置不生效。

        视图堆叠常驻化：控件加入 QStackedWidget（幂等防御），
        并以当前 pending 视图索引登记，随后切为当前页。
        """
        widget.setMinimumSize(0, min_h)
        index = int(getattr(self, "_pending_view_index", self.analysis_tab_bar.currentIndex()))
        if self.view_container.indexOf(widget) == -1:
            self.view_container.addWidget(widget)  # 幂等防御
        self._view_widgets[index] = widget
        self.view_container.setCurrentWidget(widget)

    def _build_analysis_view(self, index: int):
        """按视图索引构建分析视图（懒构建入口，分发到 7 个构建路径）。"""
        if index == 0:  # 波形 → 下方窗口显示实时特征面板（免费功能）
            from acouscope.ui.widgets.realtime_features import RealtimePanel

            panel = RealtimePanel()
            self._populate_realtime_panel(panel)
            self._add_analysis_widget(panel)
            self._realtime_panel = panel
            # 正在播放时直接进 LIVE
            if self.controller.is_playing():
                panel.set_position(self.controller.get_position())
                panel.set_playing(True)
        elif index == 1:  # FFT
            self._on_fft_analysis()
        elif index == 2:  # 语谱图
            self._on_spectrogram_analysis()
        elif index == 3:  # 音高
            self._on_pitch_analysis()
        elif index == 4:  # 共振峰
            self._on_formant_analysis()
        elif index == 5:  # 音色
            self._on_timbre_analysis()
        elif index == 6:  # 3D 频谱图
            self._on_spectrogram3d_analysis()

    def _show_or_build_view(self, index: int):
        """常驻视图切换：已构建且存活 → 直接切页零重建；否则懒构建。"""
        w = self._view_widgets.get(index)
        if w is not None:
            try:
                w.parent()
            except RuntimeError:
                w = None  # 已销毁则重建
        if w is not None:
            self.view_container.setCurrentWidget(w)
            # 常驻切回：重挂构建时 stash 在控件上的波形指针联动
            cb = getattr(w, "_wave_link_callback", None)
            wf = getattr(self, "waveform_widget", None)
            if cb is not None and wf is not None:
                wf.position_changed_callback = cb
            return
        self._pending_view_index = index
        self._build_analysis_view(index)

    # T-1060 件2：常驻分析视图子控件属性名（销毁 / 关窗收尾遍历的唯一来源）
    _ANALYSIS_VIEW_ATTRS = (
        "_spectrum_widget", "_spectrogram_widget", "_pitch_widget",
        "_formant_widget", "_timbre_widget",
        "_spectrogram3d_widget", "_realtime_panel",
    )

    @staticmethod
    def _detach_view_widget(w) -> None:
        """调用画布控件的统一收尾入口 `_detach_scene_items()`（幂等、不绝外抛）。

        未实现该协议的控件直接跳过（第二段 T-1060b 覆盖其余 5 个画布控件）。
        """
        fn = getattr(w, "_detach_scene_items", None)
        if not callable(fn):
            return
        try:
            fn()
        except Exception:
            pass  # 收尾路径绝不外抛

    def _finalize_analysis_view_widgets(self) -> None:
        """关窗收尾：遍历常驻分析视图子控件（含主波形），断开场景 item / 信号 /
        事件过滤器，并停掉其子控件定时器等投递源。

        ★ 必须在任何事件泵（task_center drain / 裸 processEvents）**之前**执行：
        否则悬垂投递会先被派发 → SIGSEGV（T-1060 / PI-T7 实测路径）。
        幂等；对未实现收尾协议的控件跳过，不改任何可见行为。
        """
        targets: list = []
        seen: set = set()
        wf = getattr(self, "waveform_widget", None)
        if wf is not None:
            seen.add(id(wf))
            targets.append(wf)
        for attr in self._ANALYSIS_VIEW_ATTRS:
            w = getattr(self, attr, None)
            if w is not None and id(w) not in seen:
                seen.add(id(w))
                targets.append(w)
        for w in self._view_widgets.values():
            if id(w) not in seen:
                seen.add(id(w))
                targets.append(w)
        for w in targets:
            self._detach_view_widget(w)

    def _invalidate_analysis_views(self):
        """销毁全部常驻分析视图（换音频/关闭时调用），回提示页。"""
        self._analysis_gen += 1
        # T-1004：换音频/项目 → 多轨会话清空并退出多轨态（轨源与 controller
        # 当前文件语义脱节时不再保留；退出为零残留视图态回退）。
        self._reset_multitrack_state()

        # T-1060 件2：销毁顺序 = 先 detach（断场景/信号/事件过滤器 + 停子定时器）
        # → 再 drop Python 引用 → 最后 deleteLater()。旧序（先 delattr 后
        # deleteLater）会留下「Python 包装已丢、C++ 对象仍在投递」的悬垂窗口。
        stale: list = []
        seen: set = set()
        for attr in self._ANALYSIS_VIEW_ATTRS:
            w = getattr(self, attr, None)
            if w is not None and id(w) not in seen:
                seen.add(id(w))
                stale.append(w)
        for w in self._view_widgets.values():
            if id(w) not in seen:
                seen.add(id(w))
                stale.append(w)
        for w in stale:
            self._detach_view_widget(w)

        for attr in self._ANALYSIS_VIEW_ATTRS:
            if hasattr(self, attr):
                delattr(self, attr)

        for w in list(self._view_widgets.values()):
            self.view_container.removeWidget(w)
            w.deleteLater()
        self._view_widgets.clear()
        self.view_container.setCurrentIndex(0)  # 回 hint 页

        # T-507b：检查器读数复位
        ins = getattr(self, "inspector_panel", None)
        if ins is not None:
            ins.reset()

        # CB-016-1：蓝条叠加层同步已移除；T-906：传输条恒可见，调用点保留
        self._sync_transport_visibility(0)
        # T-326 Pδ：视图全销毁 → 测量标记/临时段一并复位
        self._measure_active = False
        self._measure_status_text = None
        seg = getattr(self, "status_segments", None)
        if seg is not None:
            seg.clear_temporary()
        self._update_measure_actions()

    # ------------------------------------------------------------------
    # T-1004：多轨态（第二态）——入口 / 生命周期 / 播放 / 状态栏
    # ------------------------------------------------------------------

    # D6：多轨态只读——下列编辑/导出/选区类动作进入灰化（退出按原态恢复）
    _MULTITRACK_READONLY_ACTIONS = (
        "action_undo", "action_redo", "action_cut", "action_copy", "action_paste",
        "action_delete", "action_silence", "action_trim", "action_zoom_sel",
        "action_export", "action_export_audio", "action_export_wav",
        "action_export_flac", "action_export_mp3",
    )

    def _multitrack_action(self):
        return getattr(self, "action_multitrack_compare", None)

    def _can_enter_multitrack(self) -> bool:
        session = getattr(self, "multitrack_session", None)
        return bool(self.controller.has_audio()) or bool(session and len(session))

    def _on_multitrack_toggled(self, checked: bool) -> None:
        """入口：勾选=进入轨道区（多轨只读态），取消=退出回单轨主态。"""
        if not checked:
            self._exit_multitrack_mode()
            return
        if not self._can_enter_multitrack():
            act = self._multitrack_action()
            if act is not None:
                act.blockSignals(True)
                act.setChecked(False)
                act.blockSignals(False)
            show_toast(self, tr("status.open_audio"), level="info")
            return
        self._enter_multitrack_mode()

    def _multitrack_sources(self) -> list[str]:
        """轨源（D7）：文件浏览器多选（≥2）优先，否则当前音频文件（须实际存在）。"""
        fb = getattr(self, "file_browser", None)
        paths = [p for p in (fb.selected_paths() if fb is not None else []) if p]
        if len(paths) > 1:
            return paths
        cur = self.controller.current_file
        if cur and Path(cur).exists():
            return [str(cur)]
        return paths

    def _enter_multitrack_mode(self) -> None:
        """进入多轨态：波形区切轨道区（只读对比）；空会话由轨源注入首轨。"""
        panel = getattr(self, "multitrack_panel", None)
        if panel is None:
            return
        # T-929 预检挂点④：多轨加载（进态注入首轨）/ 逐轨分析前（低内存 → 提示）
        self._memguard_preflight("multitrack")
        if not self._multitrack_mode:
            if len(self.multitrack_session) == 0:
                paths = self._multitrack_sources()
                if paths:
                    panel.add_files(paths)
            self._multitrack_prev_enabled = {
                name: getattr(self, name).isEnabled()
                for name in self._MULTITRACK_READONLY_ACTIONS
                if hasattr(self, name)
            }
            self._multitrack_mode = True
            self.waveform_widget.hide()
            panel.show()
        panel.refresh_presentation()      # T-1009：进态即按会话 + 缓存重建对比呈现
        self._apply_multitrack_action_states()
        self._update_multitrack_status()
        act = self._multitrack_action()
        if act is not None and not act.isChecked():
            act.blockSignals(True)
            act.setChecked(True)
            act.blockSignals(False)

    def _exit_multitrack_mode(self) -> None:
        """退出多轨态：回单轨主态零残留（仅释放驻留样本，不碰 controller）。"""
        panel = getattr(self, "multitrack_panel", None)
        if panel is None:
            return
        self._on_multitrack_stop()
        panel.undo_bar.stop()
        self.multitrack_session.clear_pending()
        for track in self.multitrack_session.tracks():
            track.release_data()          # 视图态退出：释放全量样本，保留轨列表
        for name, was in getattr(self, "_multitrack_prev_enabled", {}).items():
            act = getattr(self, name, None)
            if act is not None:
                act.setEnabled(was)
        self._multitrack_prev_enabled = {}
        self._multitrack_mode = False
        panel.hide()
        self.waveform_widget.show()
        act = self._multitrack_action()
        if act is not None and act.isChecked():
            act.blockSignals(True)
            act.setChecked(False)
            act.blockSignals(False)
        seg = getattr(self, "status_segments", None)
        if seg is not None:
            seg.clear_temporary()
        self._update_measure_actions()

    def _reset_multitrack_state(self) -> None:
        """换音频/项目/关闭：清空多轨会话并退出多轨态（幂等，早期无会话时跳过）。"""
        panel = getattr(self, "multitrack_panel", None)
        if panel is None:
            return
        if getattr(self, "_multitrack_mode", False):
            self._exit_multitrack_mode()
        self._on_multitrack_stop()
        self.multitrack_session.clear()

    def _apply_multitrack_action_states(self) -> None:
        """D6：多轨态灰化编辑/导出/选区类动作（引导见轨道区「只读对比」提示）。"""
        if not getattr(self, "_multitrack_mode", False):
            return
        for name in self._MULTITRACK_READONLY_ACTIONS:
            act = getattr(self, name, None)
            if act is not None:
                act.setEnabled(False)
        # 多轨态内分析命令面向「当前轨」（D8 后续 T-1008 接线）：本任务保持
        # 既有 enable 语义不变，仅保证只读类动作灰化。
        self._update_multitrack_status()

    # ---- 播放（单轨一次播放，非混音；复用既有 AudioPlayer，只读复用） ----

    def _multitrack_player_instance(self):
        if self._multitrack_player is None:
            from acouscope.audio.player import AudioPlayer

            self._multitrack_player = AudioPlayer()
            self._multitrack_player.set_level_callback(
                self._on_multitrack_level
            )
            # T-1074 G1（承 T72-01）：回调在播放 daemon 线程触发；改 emit 信号，
            # 由主线程 QueuedConnection 收到后再建 toast，杜绝跨线程建 QWidget。
            # 连接在本 getter 内建立（受 is None 守卫，仅一次，无重复 emit）。
            self._mt_player_error.connect(self._on_mt_player_error)
            self._multitrack_player.set_error_callback(self._mt_player_error.emit)
        return self._multitrack_player

    def _on_mt_player_error(self, msg: str) -> None:
        """主线程侧接收多轨播放错误（T-1074 G1）：在此建 toast 恒安全。"""
        show_toast(self, str(msg), level="error")

    def _on_multitrack_play(self, track_id: str) -> None:
        """播放当前轨：懒加载全量样本 → 复用播放器；音量按需临时缩放（D10）。"""
        session = self.multitrack_session
        track = session.get(track_id)
        data = session.load_full(track_id)      # 懒加载第三级 + LRU 释放
        if track is None or data is None or len(data) == 0:
            self.multitrack_panel.set_playing(None)
            show_toast(self, tr("multitrack.tt.play"), level="warning")
            return
        payload = data if track.volume >= 1.0 else data * float(track.volume)
        player = self._multitrack_player_instance()
        player.load(payload, track.sample_rate or 44100)
        player.play()
        self.multitrack_panel.set_playing(track_id)
        self._mt_play_timer.start()

    def _on_multitrack_stop(self) -> None:
        self._mt_play_timer.stop()
        if self._multitrack_player is not None:
            self._multitrack_player.stop()
        panel = getattr(self, "multitrack_panel", None)
        if panel is not None:
            panel.set_playing(None)

    def _on_multitrack_level(self, level: float) -> None:
        """播放中动态电平（D10）：仅当前轨的轨道头电平条。"""
        panel = getattr(self, "multitrack_panel", None)
        if panel is None or panel.playing_id() is None:
            return
        panel.set_level(panel.playing_id(), float(level or 0.0))

    # ---- 当前轨 / 共享播放头 / 状态栏 ----

    def _on_multitrack_current_changed(self, track_id: str) -> None:
        """D4：lbl_audio_info = 当前轨信息（切轨即更）。"""
        track = self.multitrack_session.get(track_id)
        if track is None:
            return
        rate = f"{track.sample_rate / 1000.0:.1f} kHz" if track.sample_rate else "—"
        self.lbl_audio_info.setText(
            f"{track.label} · {track.duration:.2f} s · {rate}"
        )
        self._update_multitrack_status()

    def _on_multitrack_playhead(self, value: float) -> None:
        """D2：共享播放头（对齐基线时间）；读数归当前轨（本任务只同步状态栏）。"""
        panel = getattr(self, "multitrack_panel", None)
        if panel is not None and hasattr(panel, "view"):
            panel.view.set_playhead(value)

    def _update_multitrack_playhead(self) -> None:
        p = self._multitrack_player
        if p is None or not p.is_playing():
            self._mt_play_timer.stop()
            return
        panel = getattr(self, "multitrack_panel", None)
        if panel is None:
            return
        tid = panel.playing_id()
        track = self.multitrack_session.get(tid) if tid else None
        if track is None:
            self._mt_play_timer.stop()
            return
        offset_s = float(getattr(track, "offset_ms", 0.0) or 0.0) / 1000.0
        shared = p.get_position() + offset_s
        panel.view.set_playhead(shared)
        if hasattr(panel, "compare_view") and panel.compare_view is not None:
            panel.compare_view.set_playhead(shared)
        if not p.is_playing():
            self._mt_play_timer.stop()

    def _on_multitrack_selection(self, value) -> None:
        """D1：共享时间选区；两态选区源互不迁移（域隔离），本任务只记录视图态。"""
        self._multitrack_selection = value

    def _on_multitrack_add_from_browser(self) -> None:
        """文件列表多选 → 加入多轨（D7 多选入口；白名单过滤在容器内）。"""
        fb = getattr(self, "file_browser", None)
        paths = [p for p in (fb.selected_paths() if fb is not None else []) if p]
        if not paths:
            paths = self._multitrack_add_fallback()
        if not paths:
            show_toast(self, tr("multitrack.no_selection"), level="info")
            return
        added, rejected = self.multitrack_panel.add_files(paths)
        if rejected:
            names = ", ".join(str(p).rsplit("/", 1)[-1] for p in rejected)
            show_toast(
                self,
                tr("multitrack.unsupported_drop").format(name=names),
                level="warning",
            )
        if not added:
            return
        if not self._multitrack_mode:
            self._enter_multitrack_mode()

    def _multitrack_add_fallback(self) -> list[str]:
        """「加入多轨」无选中时的两级兜底（T-1087 M2·真机目测 #5）。

        #5 根因：入口读的是**折叠左栏**里的 FileBrowser 选中项，用户看不见列表，
        点按钮只得到一句 toast。故按可见性升级：

        1. 左栏折叠 ⇒ 先展开文件列表（`_show_left_content` 单点：切页 + 展开 +
           宽度自适应 + 页签勾选同步），本次点击不改轨集（列表即刻可选）；
        2. 左栏已展开仍无选中 ⇒ 列表这一路已帮不上忙 ⇒ 开系统文件框直选。

        折叠态**不**弹框：那是 #5 的常态，弹框反而绕过项目列表（与 D7 多选口径
        相左），且会让既有「无选中仅提示」契约（test_multitrack_mode）改道进模态。
        """
        left = getattr(self, "left_panel", None)
        fb = getattr(self, "file_browser", None)
        if left is not None and fb is not None and left.is_collapsed():
            self._show_left_content(fb)
            return []
        from PyQt6.QtWidgets import QFileDialog

        from acouscope.audio.io import AudioIO

        globs = " ".join(f"*{ext}" for ext in sorted(AudioIO.SUPPORTED_FORMATS))
        paths, _selected = QFileDialog.getOpenFileNames(
            self, tr("multitrack.add_dialog_title"), "", f"Audio ({globs})",
        )
        return [str(p) for p in (paths or []) if p]

    def _update_multitrack_status(self) -> None:
        """状态栏（D4）：轨 N/M · 当前轨名 + 健康提示（已加载 N 轨 · 约 X MB）。"""
        if not getattr(self, "_multitrack_mode", False):
            return
        seg = getattr(self, "status_segments", None)
        if seg is None:
            return
        session = self.multitrack_session
        total = len(session)
        current = session.current
        index = session.index_of(current.track_id) + 1 if current is not None else 0
        name = current.label if current is not None else "—"
        text = tr("multitrack.status").format(index=index, total=total, name=name)
        health = tr("multitrack.health").format(
            n=len(session.loaded_ids()), mb=f"{session.estimate_mb():.1f}"
        )
        seg.set_temporary_text(f"{text} · {health}")

    # ---- D9：主态拖入 = 打开该文件；多轨态拖入由轨道区容器自行消费 ----

    def _dropped_audio_paths(self, mime) -> list[str]:
        """从拖放数据取白名单（AudioIO.SUPPORTED_FORMATS）内的本地音频路径。"""
        from acouscope.audio.io import AudioIO

        if mime is None or not mime.hasUrls():
            return []
        paths = []
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            ext = path.lower().rsplit(".", 1)[-1]
            if f".{ext}" in AudioIO.SUPPORTED_FORMATS:
                paths.append(path)
        return paths

    def dragEnterEvent(self, event):  # noqa: N802（Qt 命名）
        if self._dropped_audio_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):  # noqa: N802（Qt 命名）
        if getattr(self, "_multitrack_mode", False):
            event.ignore()          # 多轨态由轨道区容器处理追加轨
            return
        paths = self._dropped_audio_paths(event.mimeData())
        if not paths:
            return
        event.acceptProposedAction()
        self._load_file(paths[0])

    def _save_view_index(self, index: int) -> None:
        """持久化上次分析视图索引（全静默，风格对齐 workspace.py）。"""
        try:
            from acouscope.utils.config import get_data_dir

            target = get_data_dir() / "ui_analysis_view.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                json.dump({"index": int(index)}, f)
        except OSError:
            pass
        except Exception:  # noqa: BLE001 — 视图索引保存永不抛
            pass

    def _load_view_index(self) -> int | None:
        """读取上次分析视图索引；缺失/损坏/越界（含 bool）均返回 None。"""
        try:
            from acouscope.utils.config import get_data_dir

            target = get_data_dir() / "ui_analysis_view.json"
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return None
            idx = data.get("index")
            if isinstance(idx, int) and not isinstance(idx, bool) and 0 <= idx <= 6:
                return idx
            return None
        except OSError:
            return None
        except Exception:  # noqa: BLE001 — 视图索引读取永不抛
            return None

    def _load_task_center_state(self) -> dict | None:
        """读取上次任务中心两态（显隐/折叠）；缺失/损坏/非法类型均静默返回 None。"""
        try:
            from acouscope.utils.config import get_data_dir

            target = get_data_dir() / "ui_task_center.json"
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return None
            out = {}
            for key in ("visible", "collapsed"):
                val = data.get(key)
                if isinstance(val, bool):
                    out[key] = val
            return out or None
        except OSError:
            return None
        except Exception:  # noqa: BLE001 — 任务中心两态读取永不抛
            return None

    def _save_task_center_state(self) -> None:
        """持久化任务中心两态（显隐/折叠；全静默）。"""
        try:
            from acouscope.utils.config import get_data_dir

            target = get_data_dir() / "ui_task_center.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            btn = getattr(self, "btn_task_center", None)
            panel = self._task_center_panel
            state = {
                "visible": bool(btn is not None and btn.isChecked()),
                "collapsed": bool(panel is not None and panel.is_collapsed()),
            }
            with open(target, "w", encoding="utf-8") as f:
                json.dump(state, f)
        except OSError:
            pass
        except Exception:  # noqa: BLE001 — 任务中心两态保存永不抛
            pass

    def _live_widget(self, attr_name: str):
        """获取存活的分析控件（已删除的 Qt 对象返回 None）。"""
        widget = getattr(self, attr_name, None)
        if widget is None:
            return None
        try:
            widget.parent()
        except RuntimeError:
            return None
        return widget

    # ------------------------------------------------------------------
    # 分析异步执行（重计算移出主线程，播放/界面保持响应）
    # ------------------------------------------------------------------

    def _audio_fingerprint(self) -> tuple:
        """当前音频内容指纹（编辑/换文件后自动失效结果缓存）。"""
        data = self.controller.audio_data
        sr = self.controller.sample_rate
        if data is None or len(data) == 0:
            return (sr, 0, 0.0)
        return (sr, len(data), float(np.sum(data)))

    # ------------------------------------------------------------------
    # T-321: 结果缓存统一读写封装——分级上限 LRU（区间 ≤10 / 全文件 ≤12）
    # 键形态与 T-916 一致：全文件 (kind, fp)；区间 (kind, fp, t0, t1)。
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_is_region_key(key: tuple) -> bool:
        """判定缓存键是否为区间键（含 t0/t1）。"""
        return isinstance(key, tuple) and len(key) >= 3

    def _cache_key(self, kind: str, fp: tuple, region: tuple | None = None) -> tuple:
        """规范化结果缓存键（区间键含 round(t0,3)/round(t1,3)，T-916 语义不变）。"""
        if region is None:
            return (kind, fp)
        t0, t1 = region
        return (kind, fp, round(t0, 3), round(t1, 3))

    def _cache_get(self, key: tuple):
        """读取结果缓存并刷新使用序（最近使用在末尾）；未命中返回 None。

        注：显式删后重插实现"移到末尾"，兼容缺失 dict.move_to_end 的环境。
        """
        result = self._result_cache.pop(key, None)
        if result is not None:
            self._result_cache[key] = result
        return result

    def _cache_put(self, key: tuple, result) -> None:
        """写入结果缓存并按分级上限淘汰最旧项，任一新增都不会无限增长。

        区间档超限 → 仅淘汰最旧区间结果；全文件档超限 → 仅淘汰最旧全文件
        结果（区间全淘汰后仍超限才轮到全文件兜底）＝保全文件常驻语义。
        """
        self._result_cache.pop(key, None)  # 删后重插＝移到末尾（插序即 LRU 序）
        self._result_cache[key] = result
        while self._cache_count(self._cache_is_region_key) > self._cache_region_limit:
            self._cache_evict_oldest(self._cache_is_region_key)
        while self._cache_count(lambda k: not self._cache_is_region_key(k)) > self._cache_full_limit:
            self._cache_evict_oldest(lambda k: not self._cache_is_region_key(k))

    def _cache_count(self, predicate) -> int:
        """统计满足谓词的缓存条目数（按类档位限额）。"""
        return sum(1 for k in self._result_cache if predicate(k))

    def _cache_evict_oldest(self, predicate) -> bool:
        """淘汰满足谓词的类内最旧条目（插入序最前）；无可淘汰返回 False。"""
        for k in self._result_cache:
            if predicate(k):
                del self._result_cache[k]
                return True
        return False

    def _run_analysis_async(self, status_text, compute_fn, on_done, error_prefix):
        """后台线程执行重计算，完成后回主线程构建控件。

        T-928：本入口统一经任务进度中心提交（排队 / 并发上限 / 取消 / 呈现收口）；
        `compute_fn` 仍在**工作线程**执行（纯计算，禁止触碰 UI），`on_done` 仍在
        主线程回调；陈旧守卫（`self._analysis_gen`）语义不变。

        分析任务**无真实进度上报**（`compute_fn` 无进度回调）→ 面板按「不定式
        busy + 阶段文本」呈现，禁伪造百分比。

        compute_fn: () -> result，工作线程执行（纯计算，禁止触碰 UI）
        on_done:    (result) -> None，主线程执行
        """
        gen = self._analysis_gen
        # T-929 预检挂点②：全量分析（音高/共振峰/音色三入口共用本入口；含后端切换）
        self._memguard_preflight("analysis")
        self.lbl_status.setText(status_text)
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)

        def _restore_cursor():
            QApplication.restoreOverrideCursor()

        def _compute(reporter):
            reporter.stage(status_text)
            return compute_fn()

        def _finish(result):
            _restore_cursor()
            if gen != self._analysis_gen:
                return  # 用户已切换视图，丢弃陈旧结果
            try:
                on_done(result)
            except Exception as e:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                show_toast(self, f"{error_prefix}:\n{e}", level="warning")
                self.lbl_status.setText("就绪")

        def _fail(msg):
            _restore_cursor()
            if gen != self._analysis_gen:
                return
            show_toast(self, f"{error_prefix}:\n{msg}", level="error")
            self.lbl_status.setText("就绪")

        def _cancelled():
            _restore_cursor()
            if gen != self._analysis_gen:
                return
            self.lbl_status.setText("就绪")

        entry = self.task_center.submit(
            status_text,
            _compute,
            kind=KIND_ANALYSIS,
            progress_mode=PROGRESS_INDETERMINATE,
            on_done=_finish,
            on_fail=_fail,
            on_cancelled=_cancelled,
        )
        if entry is not None:
            # T-929：记录最近一次分析任务 id（低内存提示的「取消」走此既有通道）
            self._last_analysis_task_id = entry.task_id

    def _analysis_source(self, track_id: str | None = None):
        """T-1008：分析取数统一入口（抽象层，默认单轨主态）。

        `track_id` 为空（默认）时必须与改造前 `controller.audio_data` /
        `controller.sample_rate` **完全等价**（同一对象、同采样率、偏移 0）
        → 单轨既有分析结果逐位不变；多轨态传 `track_id` 即得该轨数据源
        （懒加载全量样本 + T-1006 对齐偏移）。
        """
        return resolve_source(
            self.controller,
            session=getattr(self, "multitrack_session", None),
            track_id=track_id,
        )

    def _populate_realtime_panel(self, panel) -> None:
        """填充实时面板：命中缓存则零计算恢复，否则重算并写缓存。"""
        data = self.controller.audio_data
        sr = self.controller.sample_rate
        cache = getattr(self, "_rt_cache", None)
        if (cache is not None and cache[0] == sr
                and cache[1] == len(data) and cache[2] is data):
            panel.set_cached(cache[3])
        else:
            panel.set_audio(data, sr)
            self._rt_cache = (sr, len(data), data, panel.get_cache())

        # 任务信息与波形模块一致（覆盖上一个视图残留的状态文本）
        r = panel._result
        if r is not None:
            counts = {n: len(r["onsets"][n].times) for n in ("low", "mid", "high")}
            bpm = r["bpm"]
            bpm_txt = f"BPM {bpm:.0f}" if bpm > 0 else "无稳定节拍"
            self.lbl_status.setText(
                f"波形 · 实时特征 ({bpm_txt}, 起音 "
                f"低 {counts['low']}/中 {counts['mid']}/高 {counts['high']})"
            )

    def _on_analysis_changed(self, index: int):
        """分析类型切换（功能区标签卡）：常驻堆叠切换，零销毁零重建。

        唯一切换入口：analysis_tab_bar.currentChanged / 导航器重入 /
        恢复视图路径均汇于此；切换仍触发 CB-009 叠加层与传输条显隐。
        """
        if not self.controller.has_audio():
            return

        # 断开波形指针联动（如果有的话）
        if hasattr(self, 'waveform_widget') and self.waveform_widget:
            self.waveform_widget.position_changed_callback = None

        # 切换即失效旧异步回调（常驻视图不销毁）
        self._analysis_gen += 1

        self._show_or_build_view(index)
        self._save_view_index(index)
        # T-922：音律标尺叠加层随视图切换推给当前可见视图（不激活其它视图）
        self._apply_tuning_overlay()

        # T-507b：检查器当前视图名刷新
        ins = getattr(self, "inspector_panel", None)
        if ins is not None:
            ins.set_view_name(self._current_view_name())

        # T-1079 ⑤：右栏在 AI 页 → 面板预载截图/标注/未改动草稿随视图切换刷新
        # （镜像上方 set_view_name 范式；RuntimeError 吞「面板已销毁」，同 T-1011
        # reload_config 收尾语义）。
        panel_ai = getattr(self, "_ai_panel", None)
        if (panel_ai is not None
                and self.right_content.currentWidget() is self._ai_host):
            try:
                panel_ai.refresh_attached_view()
            except RuntimeError:
                pass

        # T-906：传输条全局化，同一视图切换路径调用点保留（恒可见语义；
        # CB-016-1 蓝条移除，CB-009 叠加层同步方法已整删）
        self._sync_transport_visibility(index)
        # T-326 Pδ：激活视图变化 → 测量动作 enable 刷新
        self._update_measure_actions()
        # T-1002：视图菜单勾选态镜像本切换路径（唯一状态源 = 标签卡索引）
        self._sync_view_menu(index)

    # ------------------------------------------------------------------
    # T-1002 视图菜单（只镜像 analysis_tab_bar 切换路径，零第二套状态机）
    # ------------------------------------------------------------------

    def _sync_view_menu(self, index: int | None = None) -> None:
        """把当前视图索引回勾到视图菜单 7 项（None → 取标签卡当前索引）。

        菜单为「显示侧」，勾选态唯一来源是 analysis_tab_bar.currentIndex；
        标签卡尚未构建（菜单较早构建）时按 index=0 出初值。
        """
        if index is None:
            tabs = getattr(self, "analysis_tab_bar", None)
            index = tabs.currentIndex() if tabs is not None else 0
        for i, act in enumerate(getattr(self, "_view_actions", ())):
            act.setChecked(i == index)

    def _on_view_menu_selected(self, index: int) -> None:
        """视图菜单项触发 → 切 analysis_tab_bar（与标签卡同一切换路径）。"""
        tabs = getattr(self, "analysis_tab_bar", None)
        if tabs is None:
            return
        if tabs.currentIndex() != index:
            tabs.setCurrentIndex(index)  # → currentChanged → _on_analysis_changed
        # 无音频时切换被 _on_analysis_changed 早退拦截 → 回勾真实索引，菜单不做假状态
        self._sync_view_menu(tabs.currentIndex())

    # ------------------------------------------------------------------
    # T-922 音律标尺叠加层（会话内状态；只推给当前可见视图）
    # ------------------------------------------------------------------

    def _rebuild_tuning_template_menu(self) -> None:
        """重建音律模板子菜单：「不显示」+ 内置模板名（list_templates()）。"""
        from acouscope.analysis.tunings import templates as tuning_templates

        menu = getattr(self, "menu_tuning_template", None)
        if menu is None:
            return
        menu.clear()
        action_map: dict = {}
        act_none = QAction(tr("tuning.none"), self)
        act_none.setCheckable(True)
        act_none.triggered.connect(
            lambda _checked=False: self._on_tuning_template_selected(None)
        )
        menu.addAction(act_none)
        action_map[None] = act_none
        for key in tuning_templates.list_templates():
            action = QAction(tuning_templates.get_template(key).name, self)
            action.setCheckable(True)
            action.triggered.connect(
                lambda _checked=False, template_key=key: self._on_tuning_template_selected(
                    template_key
                )
            )
            menu.addAction(action)
            action_map[key] = action
        self._tuning_template_actions = action_map
        self._sync_tuning_template_checks()

    def _sync_tuning_template_checks(self) -> None:
        """菜单勾选与当前模板状态对齐（信号阻断，防回环）。"""
        current_key = getattr(self, "tuning_ruler_template_key", None)
        for key, action in getattr(self, "_tuning_template_actions", {}).items():
            action.blockSignals(True)
            action.setChecked(key == current_key)
            action.blockSignals(False)

    def _on_tuning_ruler_toggled(self, checked: bool) -> None:
        """勾选启用/关闭音律标尺；首次启用且未选模板 → 默认 12TET。"""
        if checked and getattr(self, "tuning_ruler_template_key", None) is None:
            self.tuning_ruler_template_key = "12tet"
            self._sync_tuning_template_checks()
        self._apply_tuning_overlay()

    def _on_tuning_template_selected(self, key) -> None:
        """模板选择（会话内状态，不持久化）；标尺开启时立即推给当前可见视图。"""
        self.tuning_ruler_template_key = key
        self._sync_tuning_template_checks()
        self._apply_tuning_overlay()

    def _build_tuning_overlay_lines(self):
        """按开关 + 当前模板 + A4 参考频率构建叠加线（关闭/无模板 → None）。"""
        if not self.action_tuning_ruler.isChecked():
            return None
        key = getattr(self, "tuning_ruler_template_key", None)
        if key is None:
            return None
        from acouscope.analysis.tunings.overlay import build_overlay_lines
        from acouscope.analysis.tunings.templates import get_template
        from acouscope.dsp.units import get_reference_hz

        try:
            tuning = get_template(key)
        except KeyError:
            return None
        # 参考频率与音分/音名显示同一口径（dsp.units 只读消费）
        return build_overlay_lines(tuning, ref_hz=get_reference_hz())

    def _current_tuning(self):
        """当前生效律制（T-1034a 轮 B 唯一取用点）：关闭/未选模板 → None。

        模板恒为 440（templates 不传 reference_freq）⇒ 取用点统一注入当前 A4
        （只读 dsp.units，不写参考频率）；未选模板禁回退 12TET（律制语义
        不得在用户未选择时凭空出现）。
        """
        if not self.action_tuning_ruler.isChecked():
            return None
        key = getattr(self, "tuning_ruler_template_key", None)
        if key is None:
            return None
        import dataclasses

        from acouscope.analysis.tunings.templates import get_template
        from acouscope.dsp.units import get_reference_hz

        try:
            tuning = get_template(key)
        except KeyError:
            return None
        return dataclasses.replace(tuning, reference_freq=float(get_reference_hz()))

    def _apply_tuning_overlay(self) -> None:
        """推给视图：开启 → 仅当前可见视图；关闭 → 清空全部已建视图（零残留）。

        不激活任何其它视图，也不触发分析结果重算。
        """
        lines = self._build_tuning_overlay_lines()
        tuning = self._current_tuning()
        targets = []
        if lines is None:
            targets.extend(getattr(self, "_view_widgets", {}).values())
        container = getattr(self, "view_container", None)
        current = container.currentWidget() if container is not None else None
        if current is not None:
            targets.append(current)
        for widget in targets:
            setter = getattr(widget, "set_tuning_overlay", None)
            if callable(setter):
                setter(None if lines is None else list(lines))
        # T-1034a 轮 B：当前生效律制推给对比呈现（compare 视图不在上述 fan-out 内）
        panel = getattr(self, "multitrack_panel", None)
        presentation = getattr(panel, "presentation", None)
        if callable(presentation):
            presentation().set_tuning(tuning)

    def _on_menu_analyze_region(self):
        """T-1002 菜单项「分析此区域」→ 取当前波形选区，交 T-915 同一槽。

        数据源只读（波形 get_selection）；无选区 → toast 防御（enable 已禁，菜单不可达）。
        """
        sel = self.waveform_widget.get_selection()
        if sel is None:
            show_toast(self, tr("edit.no_selection"), level="info")
            return
        lo, hi = float(sel[0]), float(sel[1])
        t0, t1 = (lo, hi) if hi >= lo else (hi, lo)
        self._on_analyze_region(t0, t1)

    def _on_analyze_region(self, t0: float, t1: float):
        """T-916：波形选区「分析此区域」→ 当前激活分析视图对 [t0, t1] 重算并重绘。

        7 视图分派（索引 = analysis_tab_bar）：
        0 波形 → 无离线分析，toast 提示；1 FFT → 区域平均谱；
        2/3/4/5 语谱图/音高/共振峰/音色 → 区间裁剪重算 + times += t0；
        6 3D → 全量数据 + set_time_range（控件内部按乐段裁剪）。
        """
        if not self.controller.has_audio():
            show_toast(self, tr("msg.no_audio"), level="info")
            return
        if not (t1 > t0):
            show_toast(self, tr("analyze_region.invalid"), level="warning")
            return

        index = self.analysis_tab_bar.currentIndex()
        self.lbl_status.setText(
            tr("analyze_region.status").format(t0=f"{t0:.3f}", t1=f"{t1:.3f}")
        )

        if index == 0:
            show_toast(self, tr("analyze_region.no_offline"), level="info")
            return

        region = (t0, t1)
        if index == 1:
            self._on_fft_analysis(region=region)
        elif index == 2:
            self._on_spectrogram_analysis(region=region)
        elif index == 3:
            self._on_pitch_analysis(region=region)
        elif index == 4:
            self._on_formant_analysis(region=region)
        elif index == 5:
            self._on_timbre_analysis(region=region)
        elif index == 6:
            self._on_spectrogram3d_analysis(region=region)

    def _on_fft_analysis(self, region: tuple[float, float] | None = None):
        """FFT 频谱分析（与波形指针联动）。

        T-916：region=(t0, t1) 时显示区域平均谱（区间 STFT 沿时间轴均值），
        并断开波形指针联动（平均谱与指针位置无关）；region=None 行为零改变。
        """
        region = _normalize_region(region)  # T-1019：类型守卫（非元组/None → 全文件）
        if not self.controller.has_audio():
            show_toast(self, "请先打开音频文件", level="info")
            return

        self._set_analysis_view(1)

        self.lbl_status.setText("计算 FFT 频谱...")
        self.lbl_status.repaint()

        try:
            from acouscope.analysis import SpectralAnalyzer
            from acouscope.ui.widgets.spectrum import SpectrumWidget

            # T-1008：取数经分析源抽象（默认源 = controller 当前音频，逐字等价）
            _src = self._analysis_source()
            data = _src.data
            sr = _src.sample_rate

            # FFT 帧大小（秒）
            frame_seconds = 2.0
            frame_samples = int(sr * frame_seconds)

            # FFT 大小取大于帧长的最小 2 的幂，至少 8192 点
            fft_size = 1
            while fft_size < frame_samples:
                fft_size *= 2
            fft_size = max(fft_size, 8192)

            analyzer = SpectralAnalyzer(sr)

            # 更新波形上的分析窗口大小
            self.waveform_widget.set_frame_size(frame_seconds)

            def get_frame_at_position(position: float) -> np.ndarray:
                """获取指定位置的一帧数据。"""
                center_idx = int(position * sr)
                half = frame_samples // 2
                start = max(0, center_idx - half)
                end = min(len(data), center_idx + half)
                frame = np.zeros(frame_samples)
                offset = half - (center_idx - start)
                frame[offset : offset + (end - start)] = data[start:end]
                return frame

            def compute_fft(position: float, window_type: str = "hann"):
                """计算指定位置的 FFT。"""
                frame = get_frame_at_position(position)
                f, m = analyzer.fft_spectrum(frame, fft_size=fft_size, window=window_type, db_scale=False)
                return f, m

            # 用当前波形指针位置计算初始 FFT
            pos = self.waveform_widget.get_analysis_position()
            freqs, mag = compute_fft(pos, "hann")

            spectrum_widget = SpectrumWidget()

            # T-916 区域平均谱：对区间求 STFT 后沿时间轴取均值 → 1D 谱；
            # 平均谱与波形指针位置无关，故断开指针联动（region=None 时不执行）
            if region is not None:
                t0, t1 = region
                i0 = max(0, int(t0 * sr))
                i1 = min(len(data), int(t1 * sr))
                seg = data[i0:i1]
                from acouscope.dsp.stft import STFTEngine

                stft_engine = STFTEngine(n_fft=fft_size, hop_length=max(1, fft_size // 4),
                                         window="hann")
                f_stft, _times, mag_matrix = stft_engine.magnitude(seg, sr, db_scale=False)
                if mag_matrix.size == 0:
                    # 区域过短（不足一帧）→ 显式降级提示，不得静默失败
                    show_toast(self, tr("analyze_region.fft_unsupported"), level="warning")
                    return
                mean_mag = np.mean(mag_matrix, axis=1)
                spectrum_widget.set_data(
                    f_stft, mean_mag,
                    title=f"区域平均谱 {t0:.3f}–{t1:.3f}s",
                    db_scale=False,
                    sample_rate=sr,
                )
                self._add_analysis_widget(spectrum_widget)
                self._spectrum_widget = spectrum_widget
                # 平均谱与波形指针位置无关 → 清除联动（防旧回调覆写）
                self.waveform_widget.position_changed_callback = None
                spectrum_widget._wave_link_callback = None
                self.lbl_status.setText(
                    f"区域平均谱 ({t0:.3f}–{t1:.3f}s, {fft_size} 点 FFT)"
                )
                return

            # 性能优化：拖动时防抖（只在释放后更新，避免卡顿）
            self._fft_update_pending = False
            self._fft_last_position = pos

            def on_position_changed(position: float):
                """波形指针位置变化时更新 FFT（带防抖）。"""
                self._fft_last_position = position
                if not self._fft_update_pending:
                    self._fft_update_pending = True
                    # 使用 QTimer.singleShot 做防抖，200ms 延迟
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(30, self._update_fft_from_position)

            def _update_fft_from_position():
                """真正执行 FFT 更新。"""
                try:
                    self._fft_update_pending = False
                    pos = self._fft_last_position
                    win_type = spectrum_widget._window_type
                    f, m = compute_fft(pos, win_type)
                    spectrum_widget.set_data(
                        f, m,
                        title=f"FFT 频谱 ({pos:.3f}s)",
                        db_scale=False,
                        sample_rate=sr,
                        signal_data=get_frame_at_position(pos),
                    )
                    self.lbl_status.setText(f"FFT 频谱 ({fft_size} 点 FFT, 位置: {pos:.3f}s)")
                except Exception as e:
                    # T-1074 G3②（承 T72-07）：指针联动高频路径，补 _log.warning
                    # 消静默吞；此路径不宜弹 toast（会随指针移动刷屏），与姊妹
                    # on_window_changed 的 toast 分工：高频联动记日志、显式切换弹提示。
                    _log.warning("FFT 频谱联动更新失败: %s", e)

            # 绑定到主窗口实例
            self._update_fft_from_position = _update_fft_from_position

            # 窗函数切换回调
            def on_window_changed(window_type):
                try:
                    pos = self.waveform_widget.get_analysis_position()
                    f, m = compute_fft(pos, window_type)
                    spectrum_widget.set_data(
                        f, m,
                        title=f"FFT 频谱 ({pos:.3f}s)",
                        db_scale=False,
                        sample_rate=sr,
                        signal_data=get_frame_at_position(pos),
                    )
                    self.lbl_status.setText(f"FFT 频谱 ({fft_size} 点 FFT, {window_type}窗)")
                except Exception as e:
                    show_toast(self, f"FFT 分析失败:\n{str(e)}", level="warning")

            spectrum_widget.window_changed_callback = on_window_changed

            # 设置初始数据
            spectrum_widget.set_data(
                freqs, mag,
                title=f"FFT 频谱 ({pos:.3f}s)",
                db_scale=False,
                sample_rate=sr,
                signal_data=get_frame_at_position(pos),
            )
            # 默认线性幅度 + 1 kHz 范围
            spectrum_widget.cmb_y_unit.setCurrentIndex(0)  # 线性
            spectrum_widget.cmb_range.setCurrentIndex(1)   # 1 kHz

            # 恢复项目中保存的谐波标记
            saved_marks = self.controller.get_saved_annotations()
            if saved_marks:
                spectrum_widget.restore_marks(saved_marks)

            self._add_analysis_widget(spectrum_widget)

            # 保存引用，便于切换分析模式时断开
            self._spectrum_widget = spectrum_widget

            # 建立波形指针联动
            self.waveform_widget.position_changed_callback = on_position_changed
            spectrum_widget._wave_link_callback = on_position_changed

            self.lbl_status.setText(f"FFT 频谱 ({fft_size} 点 FFT, 拖动红色指针查看不同位置)")

        except Exception as e:
            import traceback
            traceback.print_exc()
            show_toast(self, f"FFT 分析失败:\n{str(e)}", level="warning")
            self.lbl_status.setText("就绪")

    def _on_spectrogram_analysis(self, region: tuple[float, float] | None = None):
        """语谱图分析（与波形指针双向联动）。

        T-916：region=(t0, t1) 时对区间数据重算 STFT，且结果 times += t0
        （横轴绝对时间，与波形/标注/游标对齐）；region=None 行为零改变。
        """
        region = _normalize_region(region)  # T-1019：类型守卫（非元组/None → 全文件）
        if not self.controller.has_audio():
            show_toast(self, tr("msg.no_audio"), level="info")
            return

        self._set_analysis_view(2)

        self.lbl_status.setText("计算语谱图...")
        self.lbl_status.repaint()

        try:
            from acouscope.ui.widgets.spectrogram import SpectrogramWidget

            # T-1008：取数经分析源抽象（默认源逐字等价）
            _src = self._analysis_source()
            data = _src.data
            sr = _src.sample_rate
            fp = self._audio_fingerprint()  # T-321: 全文件指纹（裁剪前取，失效口径不变）

            # T-916：区间模式——裁剪 [t0, t1]，时间轴偏移 +t0
            t0 = 0.0
            if region is not None:
                t0, _t1 = region
                i0 = max(0, int(t0 * sr))
                i1 = min(len(data), int(_t1 * sr))
                data = data[i0:i1]

            # 默认参数
            n_fft = 2048
            hop_length = 512
            window = "hann"

            def compute_stft(n_fft=n_fft, hop_length=hop_length, window=window):
                """计算 STFT 语谱图（使用缓存引擎）。"""
                from acouscope.dsp.stft import STFTEngine
                engine = self.controller.analysis_cache.get_or_create(
                    "stft",
                    {"n_fft": n_fft, "hop_length": hop_length, "window": window},
                    lambda: STFTEngine(n_fft=n_fft, hop_length=hop_length, window=window),
                )
                freqs, times, mag_db = engine.magnitude(data, sr, db_scale=True)
                if t0:
                    times = times + t0  # T-916：区间模式横轴绝对化
                return freqs, times, mag_db

            # T-321: 语谱图结果入统一结果缓存——同音频/同区间二次进入命中即免重算；
            # 命中仍走下方完整视图构建链路（控件重建/参数/游标/叠加/标注接线），仅跳过 STFT compute。
            cache_key = self._cache_key("spectrogram", fp, region)
            cached = self._cache_get(cache_key)
            if cached is not None:
                freqs, times, mag_db = cached
            else:
                freqs, times, mag_db = compute_stft()
                self._cache_put(cache_key, (freqs, times, mag_db))

            spec_widget = SpectrogramWidget()
            spec_widget.set_data(freqs, times, mag_db, sample_rate=sr)
            # 设置默认 FFT 大小匹配
            fft_idx = spec_widget.cmb_fft.findData(n_fft)
            if fft_idx >= 0:
                spec_widget.cmb_fft.setCurrentIndex(fft_idx)

            self._add_analysis_widget(spec_widget)

            # 保存引用
            self._spectrogram_widget = spec_widget
            # T-326 Pδ：注入悬停读数上抛回调（悬停 overlay 就近显示 + 状态栏同步）
            self._inject_hover_readout(spec_widget)
            # T-922：语谱图构建完成后补推音律标尺叠加层（会话内状态）
            self._apply_tuning_overlay()

            # 音高轨迹缓存存在时立即叠加（PITCH_OVERLAY_V1）
            # T-321: 读取走统一封装（键语义不变：全文件 pitch）
            pitch_cached = self._cache_get(
                self._cache_key("pitch", self._audio_fingerprint())
            )
            if pitch_cached is not None and hasattr(spec_widget, "set_pitch_track"):
                # T-802: 缓存为 (times, f0, grid_model) 三元组，叠加只取前两元
                spec_widget.set_pitch_track(pitch_cached[0], pitch_cached[1])

            # ===== 波形指针联动（双向） =====

            # 波形 → 语谱图：拖动波形指针，语谱图游标跟随
            def on_wave_position_changed(position: float):
                spec_widget.set_cursor(position)

            self.waveform_widget.position_changed_callback = on_wave_position_changed
            spec_widget._wave_link_callback = on_wave_position_changed

            # 语谱图 → 波形：拖动语谱图游标，波形指针跟随
            def on_spec_cursor_moved(time_sec: float):
                self.waveform_widget.set_analysis_position(time_sec)

            spec_widget.cursor_changed = on_spec_cursor_moved

            # 初始化游标位置
            init_pos = self.waveform_widget.get_analysis_position()
            spec_widget.set_cursor(init_pos)

            # ===== 标注同步（波形 → 语谱图） =====
            ann_model = self.waveform_widget.annotations
            spec_widget.set_annotation_model(ann_model)

            # 波形中区域被拖动时刷新语谱图标注
            def on_region_selected(region):
                spec_widget.refresh_annotations()

            self.waveform_widget.region_selected_callback = on_region_selected

            # 循环播放请求
            def on_loop_request(enabled, region):
                if enabled and region is not None:
                    self.transport_bar.set_loop_state(True)
                    self._on_toggle_loop(True)

            self.waveform_widget.loop_request_callback = on_loop_request

            # ===== 参数变化时重算 =====
            import traceback

            def recompute():
                """参数变化时重新计算 STFT。"""
                try:
                    self.lbl_status.setText("重新计算语谱图...")
                    n = spec_widget.fft_size
                    hop = spec_widget.hop_length
                    win = spec_widget.window_name
                    f, t, m = compute_stft(n_fft=n, hop_length=hop, window=win)
                    spec_widget.set_data(f, t, m, sample_rate=sr)
                    # 保持游标位置
                    spec_widget.set_cursor(self.waveform_widget.get_analysis_position())
                    self.lbl_status.setText(
                        f"语谱图 ({n} 点 FFT, 帧移 {hop} 样点, {win}窗)"
                    )
                except Exception:
                    traceback.print_exc()
                    show_toast(self, "语谱图重算失败", level="warning")

            # FFT 大小变化
            def on_fft_changed(idx):
                recompute()
            spec_widget.cmb_fft.currentIndexChanged.connect(on_fft_changed)

            # 帧移变化（在设置面板里）
            def on_hop_changed(idx):
                recompute()
            spec_widget.cmb_hop.currentIndexChanged.connect(on_hop_changed)

            # 窗函数变化
            def on_window_changed(idx):
                recompute()
            spec_widget.cmb_window.currentIndexChanged.connect(on_window_changed)

            # 对数频率轴切换
            def on_log_freq_toggled():
                spec_widget._update_image()
            spec_widget.chk_log_freq.stateChanged.connect(on_log_freq_toggled)

            # 自动对比度切换
            def on_contrast_toggled():
                spec_widget._update_image()
            spec_widget.chk_contrast.stateChanged.connect(on_contrast_toggled)

            self.lbl_status.setText(
                f"语谱图 ({n_fft} 点 FFT, 帧移 {hop_length} 样点, {window}窗)"
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            show_toast(self, f"语谱图分析失败:\n{str(e)}", level="warning")
            self.lbl_status.setText("就绪")

    def _on_pitch_analysis(self, region: tuple[float, float] | None = None):
        """音高检测（后台线程计算，界面保持响应）。

        T-916：region=(t0, t1) 时对区间数据重算 pYIN/SOTA，结果 times += t0
        （横轴绝对时间）；缓存键含区间（防串档），全文件键语义不变。
        """
        region = _normalize_region(region)  # T-1019：类型守卫（非元组/None → 全文件）
        if not self.controller.has_audio():
            show_toast(self, tr("msg.no_audio"), level="info")
            return

        self._set_analysis_view(3)

        # T-1008：取数经分析源抽象（默认源逐字等价）
        _src = self._analysis_source()
        data = _src.data
        sr = _src.sample_rate
        fp = self._audio_fingerprint()

        # T-916：区间模式——裁剪 [t0, t1]，缓存键含区间（防串档）
        t0 = 0.0
        if region is not None:
            t0, _t1 = region
            i0 = max(0, int(t0 * sr))
            i1 = min(len(data), int(_t1 * sr))
            data = data[i0:i1]
            # T-321: 区间键经统一封装构造（键含 round(t0,3)/round(t1,3)，语义不变）
            cache_key = self._cache_key("pitch", fp, region)
        else:
            cache_key = ("pitch", fp)

        cached = self._cache_get(cache_key)
        if cached is not None:
            self._build_pitch_widget(cached)
            return

        def compute():
            # V099_SOTA_UI_V1: 多后端选择
            backend_name = getattr(self, "_pitch_backend", "pYIN")
            if backend_name == "pYIN":
                from acouscope.analysis.pitch import detect_pyin
                tr = detect_pyin(data, sr)
            else:
                tr = self._detect_with_sota(backend_name, data, sr)
            # T-802: 返回 (times, f0, grid_model) 三元组；网格为表现层增值数据，
            # 原始连续 f0 不受吸附影响（反量化铁律）
            from acouscope.analysis.pitch_grid import build_pitch_grid
            snap_mode = getattr(self.controller.settings, "pitch_snap_mode", "off")
            times = tr.times + t0 if t0 else tr.times  # T-916：区间模式横轴绝对化
            grid = build_pitch_grid(times, tr.f0_hz, tr.confidence, snap_mode)
            return times, tr.f0_hz, grid

        def done(result):
            self._cache_put(cache_key, result)
            self._build_pitch_widget(result)

        self._run_analysis_async("检测音高...", compute, done, "音高检测失败")

    def _build_pitch_widget(self, result):
        """主线程构建音高曲线控件。"""
        times, f0, grid_model = result
        # T-802: 网格模型挂主窗，供后续吸附 UI / 导出消费；原始 f0 已原样传入控件
        self._pitch_grid_model = grid_model
        from acouscope.ui.widgets.pitch import PitchContourWidget

        pitch_widget = PitchContourWidget()
        pitch_widget.set_data(times, f0)
        self._add_analysis_widget(pitch_widget)
        self._pitch_widget = pitch_widget
        # T-326 Pδ：注入悬停读数上抛回调（悬停 overlay 就近显示 + 状态栏同步）
        self._inject_hover_readout(pitch_widget)
        # T-922：异步构建完成后补推音律标尺叠加层（会话内状态）
        self._apply_tuning_overlay()


    def _export_field_metadata(self):
        """V099_EXPORT_UI_V1: 导出田野元数据（JSON/IMDI XML/CSV）。"""
        from PyQt6.QtWidgets import QFileDialog
        # T-1035b：当前音频路径的真实来源 = AppController（原 `_current_audio_path`
        # 属性全仓无任何赋值点，旧守卫 `hasattr(self, ...)` 恒为真 → 本功能长期不可达）。
        current = self.controller.current_file if self.controller.has_audio() else None
        if not current:
            show_toast(self, "请先加载音频文件", level="warning")
            return
        default_name = "field_metadata"
        path, fmt = QFileDialog.getSaveFileName(
            self, "导出田野元数据", default_name,
            "JSON (*.json);;IMDI XML (*.xml);;CSV (*.csv)"
        )
        if not path:
            return
        try:
            from acouscope.annotation import export
            from acouscope.annotation.metadata import SessionMetadata

            # 构建元数据：只填应用内确实拿得到的值（不臆造）。
            #   Identifier  ← 控制器当前文件路径
            #   技术字段    ← 控制器已加载的 AudioInfo（采样率/位深/格式/声道/时长）
            #   Creator / Date / Location / GenreContext 应用内无来源 → 留空
            info = self.controller.audio_info
            meta = SessionMetadata()
            meta.set("Identifier", str(current))
            meta.set("Title", "AcouScope 田野录音")
            if info is not None:
                meta.set("SamplingRate", info.sample_rate)
                meta.set("BitDepth", info.bit_depth)
                meta.set("Format", info.format)
                meta.set("Channels", info.channels)
                meta.set("Duration", round(float(info.duration), 3))
            if path.endswith(".json"):
                export.export_session_json(path, meta)
            elif path.endswith(".xml"):
                export.export_session_xml(path, meta)
            elif path.endswith(".csv"):
                export.export_session_csv(path, meta)
            show_toast(self, f"元数据已导出至:\n{path}", level="success")
        except Exception as e:
            show_toast(self, str(e), level="error")

    # ------------------------------------------------------------------
    # T-1003/T-1100：分析报告 HTML 导出（文件 ▸ 导出 ▸ 导出报告…）
    # 非模态：QFileDialog 系统保存框（既有导出同款豁免）→ 后台线程拼装 → toast。
    # 禁新建对话框类 / 禁模态进度窗。
    # ------------------------------------------------------------------

    def _report_metadata(self) -> dict:
        """当前文件著录元数据（T-912 数据源 ProjectFile.metadata，只读）。

        无当前文件 / 无项目条目 → 空 dict（报告走降级路径，禁臆造默认值）。
        """
        path = self.controller.current_file
        project = getattr(self.controller, "project", None)
        if path is None or project is None:
            return {}
        try:
            entry = project.get_file(str(path))
        except Exception:  # noqa: BLE001
            return {}
        return dict(entry.metadata) if entry is not None else {}

    def _report_tech_info(self) -> dict:
        """降级模式技术信息（文件名/时长/采样率）；零分析计算，只读现有数据。"""
        data = self.controller.audio_data
        sample_rate = int(self.controller.sample_rate or 0)
        duration = len(data) / sample_rate if data is not None and sample_rate else 0.0
        info = {
            "Filename": Path(self.controller.current_file).name
            if self.controller.current_file is not None
            else "",
            "Duration": f"{duration:.3f} s",
            "SamplingRate": f"{sample_rate} Hz",
        }
        return {k: v for k, v in info.items() if v}

    def _collect_report_figures(self) -> list:
        """报告插图：波形（主）+ 当前分析视图，均走既有渲染管线。

        主线程执行：``_export_current_view`` 需读取活动控件状态（控件缺失时
        还会补算 + sendPostedEvents），不可下放工作线程；只有 HTML 生成落盘在后台。
        选区存在时当前视图即选区渲染结果 → 图题按选区时间范围标注。
        """
        import tempfile

        from acouscope.ui.report_export import ReportFigure
        from acouscope.visualization.exporters import FigureExporter

        data = self.controller.audio_data
        sample_rate = int(self.controller.sample_rate or 0)
        duration = len(data) / sample_rate if data is not None and sample_rate else 0.0

        selection = self.waveform_widget.get_selection()
        if selection is not None:
            lo, hi = float(selection[0]), float(selection[1])
            t0, t1 = (lo, hi) if hi >= lo else (hi, lo)
        else:
            t0, t1 = 0.0, duration

        latin, cjk = self._current_chart_fonts()
        exporter = FigureExporter(font_latin=latin, font_cjk=cjk)

        workdir = tempfile.TemporaryDirectory(prefix="acouscope_report_")
        self._report_tmp = workdir
        root = Path(workdir.name)

        figures = [
            ReportFigure(
                image=self._export_current_view(exporter, 0, root / "waveform.png", "png"),
                caption="{}  |  {}".format(
                    tr("cmb.waveform"),
                    tr("report.caption_range").format(t0=f"{0.0:.3f}", t1=f"{duration:.3f}"),
                ),
            )
        ]
        mode = int(self.analysis_tab_bar.currentIndex())
        if mode > 0:
            figures.append(
                ReportFigure(
                    image=self._export_current_view(
                        exporter, mode, root / f"view_{mode}.png", "png"
                    ),
                    caption="{}  |  {}".format(
                        tr(_VIEW_MENU_KEYS[mode]),
                        tr("report.caption_range").format(t0=f"{t0:.3f}", t1=f"{t1:.3f}"),
                    ),
                )
            )
        return figures

    def _cleanup_report_tmp(self) -> None:
        """释放报告渲染临时目录（幂等）。"""
        workdir = getattr(self, "_report_tmp", None)
        if workdir is None:
            return
        self._report_tmp = None
        try:
            workdir.cleanup()
        except OSError:
            pass

    def _on_export_report(self):
        """导出分析报告（自包含 HTML）：题名 + 元数据/降级技术信息 + 波形 + 当前分析视图。"""
        from acouscope.ui import report_export

        if not self.controller.has_audio():
            show_toast(self, tr("msg.no_audio"), level="info")
            return

        current = self.controller.current_file
        stem = Path(current).stem if current is not None else "audio"
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            tr("report.dialog_title"),
            report_export.default_report_name(stem),
            tr("report.filter_html"),
        )
        if not filepath:
            return

        target = Path(filepath)
        if target.suffix.lower() != ".html":
            target = target.with_suffix(".html")

        relocated = False
        if not self._dir_writable(target.parent):
            # macOS TCC 可能拒绝进程写入桌面/下载等目录：自动改存（同既有导出）
            target = self._fallback_export_path(target)
            relocated = True

        try:
            figures = self._collect_report_figures()
        except Exception as e:  # noqa: BLE001
            self._cleanup_report_tmp()
            show_toast(
                self,
                tr("report.failed").format(error=f"{type(e).__name__}: {e}"),
                level="error",
            )
            self.lbl_status.setText(tr("status.ready"))
            return

        metadata = self._report_metadata()
        tech_info = self._report_tech_info()
        _latin, cjk = self._current_chart_fonts()  # 报告正文字族（CJK 可用字族）
        self.lbl_status.setText(tr("report.exporting"))
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)

        class _ReportWorker(QThread):
            done = pyqtSignal(object)
            fail = pyqtSignal(str)

            def run(self_):
                try:
                    self_.done.emit(
                        report_export.export_report_html(
                            target,
                            title=stem,
                            metadata=metadata,
                            figures=figures,
                            tech_info=tech_info,
                            font_family=cjk,
                        )
                    )
                except Exception as e:  # noqa: BLE001
                    import traceback

                    self_.fail.emit(f"{e}\n{traceback.format_exc(limit=3)}")

        worker = _ReportWorker(self)
        workers = getattr(self, "_report_workers", None)
        if workers is None:
            workers = self._report_workers = []

        def _drop(w=worker):
            if w in workers:
                workers.remove(w)

        worker.done.connect(lambda saved: self._on_report_done(saved, relocated))
        worker.fail.connect(self._on_report_failed)
        worker.finished.connect(_drop)
        worker.finished.connect(self._cleanup_report_tmp)
        workers.append(worker)
        worker.start()

    def _on_report_done(self, saved, relocated: bool = False):
        """后台 HTML 生成完成：状态栏 + 成功 toast（改存路径时附说明）。"""
        QApplication.restoreOverrideCursor()
        self.lbl_status.setText(tr("report.exported").format(path=saved).replace("\n", " "))
        message = tr("report.exported").format(path=saved)
        if relocated:
            message = f"{message}\n\n{tr('report.relocated')}"
        show_toast(self, message, level="success")

    def _on_report_failed(self, message: str):
        """后台 HTML 生成失败：状态栏复位 + 失败 toast（error）。"""
        QApplication.restoreOverrideCursor()
        show_toast(self, tr("report.failed").format(error=message), level="error")
        self.lbl_status.setText(tr("status.ready"))

    def _on_export_report_pdf(self):
        """导出分析报告 PDF（T-1102 M-B′-β1）：与 HTML 快导同源——同一取数 +
        同一 ``build_report_html``，产物交 ``report_pdf.render_report_pdf`` 同步
        渲染（默认 A4 纵向·边距 16·dpi 300）。不引线程（禁自行开线程绕 pin）。"""
        from acouscope.ui import report_export, report_pdf

        if not self.controller.has_audio():
            show_toast(self, tr("msg.no_audio"), level="info")
            return

        current = self.controller.current_file
        stem = Path(current).stem if current is not None else "audio"
        initial = Path(report_export.default_report_name(stem)).with_suffix(".pdf")
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            tr("report.pdf_dialog_title"),
            str(initial),
            tr("report.filter_pdf"),
        )
        if not filepath:
            return

        target = Path(filepath)
        if target.suffix.lower() != ".pdf":
            target = target.with_suffix(".pdf")

        if not self._dir_writable(target.parent):
            # macOS TCC 可能拒绝进程写入桌面/下载等目录：自动改存（同 HTML 路）
            target = self._fallback_export_path(target)

        try:
            figures = self._collect_report_figures()
        except Exception as e:  # noqa: BLE001
            self._cleanup_report_tmp()
            show_toast(
                self,
                tr("report.failed").format(error=f"{type(e).__name__}: {e}"),
                level="error",
            )
            self.lbl_status.setText(tr("status.ready"))
            return

        try:
            metadata = self._report_metadata()
            tech_info = self._report_tech_info()
            _latin, cjk = self._current_chart_fonts()  # 报告正文字族（同 HTML 路）
            self.lbl_status.setText(tr("report.exporting"))
            # T-1103 M-B′-β2：版面参数取预览面板透传（预览导出同源）；
            # 面板缺席时 {} / "" 回落 α 默认（A4 纵 / 16 毫米 / dpi 300）——β1 兼容。
            panel = getattr(self, "report_preview_panel", None)
            opt = panel.options() if panel is not None else {}
            # T-1104 M-C′·MC-1：AI 段与预览同源透传（面板缺席回落 ""=零 AI 节）
            ai_text = panel.ai_text() if panel is not None else ""
            html = report_export.build_report_html(
                title=stem,
                metadata=metadata,
                figures=figures,
                tech_info=tech_info,
                degraded_reason="",
                font_family=cjk,
                ai_text=ai_text,
            )
            saved = report_pdf.render_report_pdf(html, target, **opt)
        except Exception as e:  # noqa: BLE001
            show_toast(
                self,
                tr("report.failed").format(error=f"{type(e).__name__}: {e}"),
                level="error",
            )
            self.lbl_status.setText(tr("status.ready"))
            return
        finally:
            self._cleanup_report_tmp()

        show_toast(
            self, tr("report.exported").format(path=saved).replace("\n", " "),
            level="success",
        )
        self.lbl_status.setText(tr("status.ready"))

    def _build_report_preview_html(self) -> str:
        """报告预览 HTML 产串（T-1103 M-B′-β2·面板 provider 回调）。

        与导出同一条取数 + 同一 ``build_report_html``；异常上抛由面板 catch
        （预览失败不动宿主）。图已 base64 内嵌进串，临时目录建串后即释放。
        """
        from acouscope.ui import report_export

        figures = self._collect_report_figures()
        # T-1104：顺带缓存图题（AI 消息取数用·零重渲染既有管线）
        self._report_preview_captions = tuple(
            str(f.caption or "") for f in figures
        )
        try:
            current = self.controller.current_file
            stem = Path(current).stem if current is not None else "audio"
            _latin, cjk = self._current_chart_fonts()  # 报告正文字族（同导出路）
            panel = getattr(self, "report_preview_panel", None)
            return report_export.build_report_html(
                title=stem,
                metadata=self._report_metadata(),
                figures=figures,
                tech_info=self._report_tech_info(),
                degraded_reason="",
                font_family=cjk,
                # T-1104 M-C′·MC-1：AI 段与导出同源透传（面板缺席回落 ""）
                ai_text=panel.ai_text() if panel is not None else "",
            )
        finally:
            self._cleanup_report_tmp()

    def _on_report_ai_requested(self) -> None:
        """生成报告 AI 解读（T-1104 M-C′·MC-1）。

        禁自动外发：仅用户点按触发；无音频 / 无 provider 配置 → toast 即止。
        只经公共 API（``load_ai_config`` / ``interpreter.make_provider`` /
        ``provider.chat``）消费 AI 域，零复用释图面板私有件。T-1107 MC-3：
        本地档（ollama/llama_cpp）传懒启动入参与 provider 工厂，引擎经公共
        ``get_runtime()`` 在 worker 线程内起，就绪后按动态端口重建 provider。
        幂等防重：已有 worker 在跑直接 return。三终态（done/failed/cancelled）
        各有 toast——降级不静默；worker 收尾在 closeEvent。
        """
        from acouscope.ai import interpreter
        from acouscope.ui.report_ai import ReportAiWorker, build_report_ai_messages
        from acouscope.ui.widgets.ai_interpret import load_ai_config

        if not self.controller.has_audio():
            show_toast(self, tr("msg.no_audio"), level="info")
            return
        worker = getattr(self, "_report_ai_worker", None)
        if worker is not None and worker.isRunning():
            return

        cfg = load_ai_config()
        # 三档路由最小镜像（只读公共键）：provider 缺省且为内置档 → 内置 ollama；
        # 其余档缺 provider/地址 → 视为无可用配置，止于 toast（禁自动外发）。
        v2 = cfg.get("ai_v2") if isinstance(cfg.get("ai_v2"), dict) else {}
        kind = str(cfg.get("provider", "") or "").strip()
        if not kind and v2.get("source") in (None, "", "builtin"):
            kind = "ollama"
        if not cfg or not kind:
            show_toast(self, tr("report.ai_unavailable"), level="info")
            return
        url = str(cfg.get("url", "") or "").strip()
        if kind in ("custom",) and not url:
            show_toast(self, tr("report.ai_unavailable"), level="info")
            return
        key = str(cfg.get("key", "") or "").strip()
        model = str(cfg.get("model", "") or "").strip()

        def _make_provider():
            # 镜像 ai_interpret._make_provider 的动态端口注入：本地档未手填
            # URL 时，仅当运行时就绪才注入其 base_url（except 忽略回落默认）。
            provider_url = url
            if kind in ("ollama", "llama_cpp") and not provider_url:
                try:
                    if kind == "llama_cpp":
                        from acouscope.ai.llama_runtime import get_runtime
                    else:
                        from acouscope.ai.ollama_runtime import get_runtime
                    rt = get_runtime()
                    if rt.state == "ready" and rt.base_url:
                        provider_url = rt.base_url
                except Exception:
                    pass
            return interpreter.make_provider(kind, provider_url, key, model)

        provider = _make_provider()
        # T-1107 MC-3：本地档懒启动开关（镜像 ai_interpret 决策规则；外部
        # Ollama 开关打开时不启内置引擎）。阻塞只发生在 worker 线程。
        ensure_runtime = kind in ("ollama", "llama_cpp") and not (
            kind == "ollama" and bool(v2.get("external_ollama")))
        llama_model_id = str(v2.get("llama_model_id", "") or "") or None
        messages = build_report_ai_messages(
            metadata=self._report_metadata(),
            tech_info=self._report_tech_info(),
            figure_captions=getattr(self, "_report_preview_captions", ()),
        )
        panel = self.report_preview_panel
        w = self._report_ai_worker = ReportAiWorker(
            provider,
            messages,
            parent=self,
            ensure_runtime=ensure_runtime,
            runtime_kind=kind if ensure_runtime else None,
            llama_model_id=llama_model_id,
            provider_factory=_make_provider if ensure_runtime else None,
        )
        chunks: list[str] = []

        # T-1106 M-C′·MC-2：重生成前清旧文 + 置灰按钮 + 「生成中」占位回填展示位
        panel.set_ai_text("")
        panel.set_ai_busy(True)
        panel.set_ai_text(tr("report.ai_generating"))

        def _on_chunk(piece):
            chunks.append(piece)
            panel.set_ai_text("".join(chunks))  # 逐段回填（非等全文）

        def _finished(full):
            panel.set_ai_busy(False)
            panel.set_ai_text(full or "".join(chunks))
            show_toast(self, tr("report.ai_done"), level="success")

        def _failed(error):
            panel.set_ai_busy(False)
            panel.set_ai_text("")
            show_toast(
                self, tr("report.ai_failed").format(error=error), level="error"
            )

        def _cancelled():
            panel.set_ai_busy(False)
            show_toast(self, tr("report.ai_cancelled"), level="info")

        def _clear():
            if self._report_ai_worker is w:
                self._report_ai_worker = None

        w.chunk.connect(_on_chunk)
        w.finished_ok.connect(_finished)
        w.failed.connect(_failed)
        w.cancelled.connect(_cancelled)
        w.finished.connect(_clear)
        show_toast(self, tr("report.ai_generating"), level="info")
        w.start()

    def _show_report_preview(self) -> None:
        """进报告预览页（index5）并刷新（T-1103 M-B′-β2）。"""
        self._set_workspace_page(5)
        self.report_preview_panel.refresh()


# ============================================================
# SOTA 深度分析后端集成（T-202）V099_SOTA_UI_V1
# 防缩进陷阱：textwrap.dedent 处理 + re 正则定位
# ============================================================

    def _detect_with_sota(self, backend_name, data, sr):
        """SOTA 后端检测（SwiftF0/RMVPE），离线全局分析。"""
        if backend_name == "SwiftF0":
            from acouscope.analysis.backends.swift_f0 import SwiftF0Backend
            backend = SwiftF0Backend()
        elif backend_name == "RMVPE":
            from acouscope.analysis.backends.rmvpe import RMVPEBackend
            backend = RMVPEBackend()
        else:
            raise ValueError(f"Unknown backend: {backend_name}")
        return backend.detect(data, sr)

    def _create_backend_selector(self):
        """创建算法后端下拉菜单（挂载到 analysis_toolbar）。

        返回一个尺寸稳定的 QWidget（QLabel + QComboBox）。
        不使用 addStretch——QToolBar 中会导致控件被压缩至不可见。
        """
        from PyQt6.QtWidgets import QComboBox, QLabel, QWidget, QHBoxLayout, QSizePolicy
        widget = QWidget()
        # T-1083 M-2：Fixed→Preferred 让右簇随窗宽收缩，minimumWidth 保底防压至 0 宽
        widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        widget.setMinimumWidth(180)  # T207_FIX_V1: 防 QToolBar 压缩容器为 0 宽
        layout = QHBoxLayout()
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(4)
        label = QLabel("音高算法:")
        combo = QComboBox()
        combo.setMinimumWidth(140)
        combo.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        combo.addItem("pYIN (流式)", "pYIN")
        combo.addItem("SwiftF0 (深度)", "SwiftF0")
        combo.addItem("RMVPE (人声)", "RMVPE")
        combo.currentIndexChanged.connect(self._on_backend_changed)
        self._pitch_backend = "pYIN"
        self._backend_combo = combo
        layout.addWidget(label)
        layout.addWidget(combo)
        widget.setLayout(layout)
        return widget

    def _on_backend_changed(self):
        """后端切换处理：不可用提示下载；切换成功即时生效（T-1014）。

        成功分支：更新 _pitch_backend 后交由 _apply_backend_switch 完成
        「失效音高结果 + 按需重算 + toast」；模型不可用 → 既有下载询问
        分支不动；下载中/回退 pYIN 分支语义保持。
        """
        backend = self._backend_combo.currentData()
        prev = self._pitch_backend  # T-1014：记录切换前有效后端（判定真变化）
        if backend == "pYIN":
            self._pitch_backend = "pYIN"
            self._apply_backend_switch("pYIN", prev)
            return
        # 检查 SOTA 后端是否可用
        try:
            if backend == "SwiftF0":
                from acouscope.analysis.backends.swift_f0 import SwiftF0Backend
                if SwiftF0Backend().is_available():
                    self._pitch_backend = "SwiftF0"
                    self._apply_backend_switch("SwiftF0", prev)
                    return
            elif backend == "RMVPE":
                from acouscope.analysis.backends.rmvpe import RMVPEBackend
                if RMVPEBackend().is_available():
                    self._pitch_backend = "RMVPE"
                    self._apply_backend_switch("RMVPE", prev)
                    return
        except Exception:
            pass
        # 模型不可用，提示下载
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "模型未安装",
            f"{backend} 模型尚未下载。是否现在下载？\n（需要网络连接，田野调查前请预下载）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._download_sota_model(backend)
        else:
            # 回退到 pYIN
            self._backend_combo.setCurrentIndex(0)
            self._pitch_backend = "pYIN"

    def _apply_backend_switch(self, backend: str, prev: str) -> None:
        """T-1014：切换成功即时生效——失效旧音高结果并按新后端重算。

        失效口径选型＝仅清音高相关缓存键 + 仅销毁音高控件（不动 FFT/语谱图
        等其他分析结果与常驻视图，避免无谓重算）。重算按需：
          · 当前激活视图恰为音高（含首次分析在途、尚无结果）→ 立即走常驻
            懒构建路径重算（_run_analysis_async 后台线程，非阻塞）；
          · 音高视图已构建但非当前 → 控件销毁 + 缓存清空，下次进入自动按
            新后端重算（标记待重算）；
          · 无音高结果且不在音高视图 → 仅 toast「下次分析生效」。
        backend == prev（如不可用下载被拒绝、回退回原后端）→ 无有效变化，
        不打扰用户。
        """
        if backend == prev:
            return
        has_view = self._live_widget("_pitch_widget") is not None
        has_result = has_view or self._has_pitch_cache()
        active_pitch = (
            self.controller.has_audio()
            and self.analysis_tab_bar.currentIndex() == 3
        )
        if not (has_result or active_pitch):
            show_toast(
                self,
                tr("pitch_backend.switched_next").format(backend=backend),
                level="success",
            )
            return
        self._drop_pitch_results()  # 仅清 pitch 缓存键（其他结果保留）
        if has_view:
            self._drop_pitch_view()  # 仅销毁音高控件（其他常驻视图保留）
        if active_pitch:
            # 当前即音高视图 → 立即重建重算（async 后台路径，不阻塞 UI）
            self._on_analysis_changed(3)
        show_toast(
            self,
            tr("pitch_backend.switched_reanalyze").format(backend=backend),
            level="success",
        )

    def _has_pitch_cache(self) -> bool:
        """结果缓存是否存在任一音高键（kind == 'pitch'）。"""
        return any(
            isinstance(k, tuple) and len(k) >= 2 and k[0] == "pitch"
            for k in self._result_cache
        )

    def _drop_pitch_results(self) -> None:
        """仅清除音高相关结果缓存键（不触及其他分析结果）。"""
        for k in [
            key for key in self._result_cache
            if isinstance(key, tuple) and len(key) >= 2 and key[0] == "pitch"
        ]:
            del self._result_cache[k]

    def _drop_pitch_view(self) -> None:
        """仅销毁音高控件与网格模型，其余常驻分析视图不受影响。

        从常驻堆叠按对象摘除（登记索引可能非 3：SOTA 深度完成回调晚于
        视图切换的竞态下可能落到其他索引）；Pδ 测量态复位口径与
        _invalidate_analysis_views 一致。
        """
        w = getattr(self, "_pitch_widget", None)
        for attr in ("_pitch_widget", "_pitch_grid_model"):
            if hasattr(self, attr):
                delattr(self, attr)
        entries = [idx for idx, cand in self._view_widgets.items() if cand is w]
        for idx in entries:
            self._view_widgets.pop(idx, None)
        if w is not None:
            try:
                w.parent()  # 存活检查（C++ 侧已销毁则跳过）
            except RuntimeError:
                w = None
        if w is not None and self.view_container.indexOf(w) != -1:
            self.view_container.removeWidget(w)
            w.deleteLater()
        self._measure_active = False
        self._measure_status_text = None
        seg = getattr(self, "status_segments", None)
        if seg is not None:
            seg.clear_temporary()
        self._update_measure_actions()

    def _download_sota_model(self, backend_name):
        """在后台线程下载 SOTA 模型（非模态，CB-003 G-2 去模态化）。

        原模态进度对话框（D10）已替换：开始下载走 show_toast
        提示；进度改状态栏内联进度面板（_DownloadProgressPanel，QWidget
        容器，非模态不阻塞，复用 T-305b/T-314b 进度先例）；取消按钮
        语义保留（进度区可取消 → 终止下载线程并回退 pYIN）；下载完成/失败
        仍走 _on_download_done toast。
        """
        if getattr(self, "_download_worker", None) is not None and \
                self._download_worker.isRunning():
            return  # 已有下载在途：忽略重复触发，避免进度面板叠加

        # T-929 预检挂点③：模型下载前（低内存 → 非模态提示；默认继续）
        self._memguard_preflight("download")

        from PyQt6.QtCore import QThread, pyqtSignal

        class DownloadWorker(QThread):
            progress = pyqtSignal(int, int)  # downloaded, total
            finished_signal = pyqtSignal(bool, str)

            def __init__(self, name):
                super().__init__()
                self._name = name
                self._finished = False  # 取消竞态守卫：先置位再 emit

            def run(self):
                try:
                    if self._name == "SwiftF0":
                        from acouscope.analysis.backends.swift_f0 import SwiftF0Backend
                        ok = SwiftF0Backend.download_model(
                            lambda d, t: self.progress.emit(d, t)
                        )
                    elif self._name == "RMVPE":
                        from acouscope.analysis.backends.rmvpe import RMVPEBackend
                        ok = RMVPEBackend.download_model(
                            lambda d, t: self.progress.emit(d, t)
                        )
                    else:
                        self._finished = True
                        self.finished_signal.emit(False, "未知后端")
                        return
                    self._finished = True
                    if ok:
                        self.finished_signal.emit(True, f"{self._name} 模型下载成功")
                    else:
                        self.finished_signal.emit(False, f"{self._name} 模型下载失败")
                except Exception as e:
                    self._finished = True
                    self.finished_signal.emit(False, str(e))

        worker = DownloadWorker(backend_name)
        panel = self._ensure_download_panel()
        panel.set_backend(backend_name)
        panel.progress.setValue(0)
        self.statusBar().addWidget(panel)
        panel.show()

        # T-928：下载任务登记进任务进度中心（聚合条目：阶段文本 + 终态 + 取消）。
        # 真实字节进度仍由状态栏内联面板（下载专属明细）承载 → 同一任务只有
        # 一条进度条（禁双进度显示）；取消动作仍走 T-304b/T-305b 原链路。
        d_title = tr("task_center.title.download").format(name=backend_name)
        dl_entry = self.task_center.register(
            d_title,
            kind=KIND_DOWNLOAD,
            progress_mode=PROGRESS_TEXT,
            cancel_action=lambda w=worker: self._cancel_sota_download(w),
        )
        self._download_task_id = dl_entry.task_id

        worker.progress.connect(
            lambda d, t: self._on_download_progress(d, t, backend_name)
        )
        worker.finished_signal.connect(
            lambda ok, msg: (self._hide_download_progress(),
                             self._on_download_done(ok, msg, backend_name))
        )
        panel.canceled.connect(lambda: self._cancel_sota_download(worker))
        worker.start()
        self._download_worker = worker
        # T-928 定案 D1″：提交默认不 toast（面板可见即达）；面板不可见时提示，
        # 保证用户仍可感知已提交。
        if not self._task_center_panel_visible():
            show_toast(
                self,
                tr("task_center.submitted").format(title=d_title),
                level="info",
            )

    def _task_center_panel_visible(self) -> bool:
        """任务面板当前是否可见（提交提示的降噪判据）。"""
        panel = self._task_center_panel
        return panel is not None and not panel.isHidden()

    def _on_download_progress(self, downloaded, total, backend_name) -> None:
        """下载进度 → 状态栏内联面板（真实字节）+ 任务中心聚合阶段文本。"""
        panel = getattr(self, "_download_panel", None)
        pct = int(downloaded * 100 / total) if total else 0
        if panel is not None:
            panel.progress.setValue(pct)
        task_id = self._download_task_id
        if task_id:
            self.task_center.set_stage(
                task_id,
                tr("task_center.download_progress").format(
                    name=backend_name, pct=pct
                ),
            )

    def _ensure_download_panel(self) -> _DownloadProgressPanel:
        """取（懒建）复用的下载进度面板，挂 MainWindow 作宿主。"""
        panel = getattr(self, "_download_panel", None)
        if panel is None:
            panel = _DownloadProgressPanel(self)
            self._download_panel = panel
        return panel

    def _hide_download_progress(self) -> None:
        """下载完成/失败/取消后从状态栏移除进度面板（幂等）。"""
        panel = getattr(self, "_download_panel", None)
        if panel is None:
            return
        self.statusBar().removeWidget(panel)
        panel.hide()

    def _cancel_sota_download(self, worker) -> None:
        """取消下载（进度区“取消”按钮，语义与旧模态进度取消一致）。

        仅当下载确未完成时终止线程并回退 pYIN；若线程已置 _finished
        （完成信号在途），只收起面板，不重复 toast/复位，避免双路竞态。
        T-928：同时把任务中心聚合条目收敛为「已取消」（幂等）。
        """
        if not getattr(worker, "_finished", False) and worker.isRunning():
            worker.terminate()
            show_toast(self, "已取消下载，音高后端回退到 pYIN。", level="info")
            self._backend_combo.setCurrentIndex(0)
            self._pitch_backend = "pYIN"
        self._hide_download_progress()
        task_id = self._download_task_id
        if task_id:
            # 先落 id 再取消：cancel 会回调 cancel_action → 重入本方法时
            # id 已清空，避免二次收敛（TaskCenter 侧终态幂等兜底）。
            self._download_task_id = None
            self.task_center.cancel(task_id)

    def _on_download_done(self, ok, msg, backend_name):
        """下载完成后提示；T-928：任务中心聚合条目同步收敛为终态。"""
        task_id = self._download_task_id
        if task_id:
            self._download_task_id = None
            self.task_center.finish(task_id, ok=bool(ok), error="" if ok else str(msg))
        if ok:
            show_toast(self, msg, level="success")
        else:
            show_toast(self, msg, level="error")
            self._backend_combo.setCurrentIndex(0)
            self._pitch_backend = "pYIN"

    def _run_sota_analysis(self, data, sr, backend_name):
        """SOTA 深度分析（独立 QThread，不阻塞 UI）。"""
        from PyQt6.QtCore import QThread, pyqtSignal

        class SotaWorker(QThread):
            progress = pyqtSignal(float)
            finished_signal = pyqtSignal(object)
            error = pyqtSignal(str)

            def __init__(self, backend_name, data, sr):
                super().__init__()
                self._backend_name = backend_name
                self._data = data
                self._sr = sr

            def run(self):
                try:
                    if self._backend_name == "SwiftF0":
                        from acouscope.analysis.backends.swift_f0 import SwiftF0Backend
                        backend = SwiftF0Backend()
                    elif self._backend_name == "RMVPE":
                        from acouscope.analysis.backends.rmvpe import RMVPEBackend
                        backend = RMVPEBackend()
                    else:
                        self.error.emit(f"Unknown: {self._backend_name}")
                        return
                    tr = backend.detect(
                        self._data, self._sr,
                        progress_cb=lambda p: self.progress.emit(p),
                    )
                    self.finished_signal.emit(tr)
                except Exception as e:
                    self.error.emit(str(e))

        worker = SotaWorker(backend_name, data, sr)
        worker.progress.connect(lambda p: self.statusBar().showMessage(
            f"深度分析中... {p*100:.0f}%"))
        def _on_pitch_finished(tr):
            # T-802: 深度分析路径同步构建网格模型（三元组契约）
            from acouscope.analysis.pitch_grid import build_pitch_grid
            snap_mode = getattr(self.controller.settings, "pitch_snap_mode", "off")
            grid = build_pitch_grid(tr.times, tr.f0_hz, tr.confidence, snap_mode)
            self._build_pitch_widget((tr.times, tr.f0_hz, grid))
            # 音高曲线同步叠加到语谱图（若该视图已存在，PITCH_OVERLAY_V1）
            spec = getattr(self, "_spectrogram_widget", None)
            if spec is not None and hasattr(spec, "set_pitch_track"):
                spec.set_pitch_track(tr.times, tr.f0_hz)
                spec.btn_pitch.setChecked(True)
            self.lbl_status.setText("音高检测完成")

        worker.finished_signal.connect(_on_pitch_finished)
        worker.error.connect(lambda e: self.statusBar().showMessage(
            f"分析失败: {e}"))
        worker.start()
        self._sota_worker = worker

    def _on_formant_analysis(self, region: tuple[float, float] | None = None):
        """共振峰分析（LPC 法，后台线程计算）。

        T-916：region=(t0, t1) 时对区间数据重算 LPC，结果 times += t0
        （横轴绝对时间）；缓存键含区间（防串档），全文件键语义不变。
        """
        region = _normalize_region(region)  # T-1019：类型守卫（非元组/None → 全文件）
        if not self.controller.has_audio():
            show_toast(self, tr("msg.no_audio"), level="info")
            return
        self._set_analysis_view(4)

        # T-1008：取数经分析源抽象（默认源逐字等价）
        _src = self._analysis_source()
        data = _src.data
        sr = _src.sample_rate
        fp = self._audio_fingerprint()

        # T-916：区间模式——裁剪 [t0, t1]，缓存键含区间（防串档）
        t0 = 0.0
        if region is not None:
            t0, _t1 = region
            i0 = max(0, int(t0 * sr))
            i1 = min(len(data), int(_t1 * sr))
            data = data[i0:i1]
            # T-321: 区间键经统一封装构造（键含 round(t0,3)/round(t1,3)，语义不变）
            cache_key = self._cache_key("formant", fp, region)
        else:
            cache_key = ("formant", fp)

        cached = self._cache_get(cache_key)
        if cached is not None:
            self._build_formant_widget(cached)
            return

        def compute():
            from acouscope.analysis import FormantAnalyzer

            analyzer = self.controller.analysis_cache.get_or_create(
                "formant",
                {"sr": sr},
                lambda: FormantAnalyzer(sr),
            )
            times, freqs, bws = analyzer.extract_lpc(
                data, frame_size=1024, hop_length=512
            )
            if t0:
                times = times + t0  # T-916：区间模式横轴绝对化
            return times, freqs, bws

        def done(result):
            self._cache_put(cache_key, result)
            self._build_formant_widget(result)

        self._run_analysis_async("共振峰分析中...", compute, done, "共振峰分析失败")

    def _build_formant_widget(self, result):
        """主线程构建共振峰控件。"""
        times, freqs, bws = result
        from acouscope.ui.widgets.formants import FormantWidget

        formant_widget = FormantWidget()
        formant_widget.set_data(times, freqs, bws)
        self._add_analysis_widget(formant_widget)
        self._formant_widget = formant_widget
        # T-326 Pδ：注入悬停读数上抛回调（悬停 overlay 就近显示 + 状态栏同步）
        self._inject_hover_readout(formant_widget)
        self._link_time_view_signals(formant_widget)

        n_valid = int(np.sum(freqs > 0))
        self.lbl_status.setText(
            f"共振峰分析完成 ({len(times)} 帧, {n_valid} 个有效共振峰)"
        )

    def _on_timbre_analysis(self, region: tuple[float, float] | None = None):
        """音色特征分析（MFCC / HNR / 频谱特征 / 全局特征，后台线程计算）。

        T-916：region=(t0, t1) 时对区间数据重算，times/hnr_times += t0
        （横轴绝对时间）；缓存键含区间（防串档），全文件键语义不变。
        """
        region = _normalize_region(region)  # T-1019：类型守卫（非元组/None → 全文件）
        if not self.controller.has_audio():
            show_toast(self, tr("msg.no_audio"), level="info")
            return

        self._set_analysis_view(5)

        # T-1008：取数经分析源抽象（默认源逐字等价）
        _src = self._analysis_source()
        data = _src.data
        sr = _src.sample_rate
        fp = self._audio_fingerprint()

        # T-916：区间模式——裁剪 [t0, t1]，缓存键含区间（防串档）
        t0 = 0.0
        if region is not None:
            t0, _t1 = region
            i0 = max(0, int(t0 * sr))
            i1 = min(len(data), int(_t1 * sr))
            data = data[i0:i1]
            # T-321: 区间键经统一封装构造（键含 round(t0,3)/round(t1,3)，语义不变）
            cache_key = self._cache_key("timbre", fp, region)
        else:
            cache_key = ("timbre", fp)

        cached = self._cache_get(cache_key)
        if cached is not None:
            self._build_timbre_widget(cached)
            return

        def compute():
            from acouscope.analysis import TimbreAnalyzer

            analyzer = self.controller.analysis_cache.get_or_create(
                "timbre",
                {"sr": sr},
                lambda: TimbreAnalyzer(sr),
            )
            times, mfcc = analyzer.mfcc(data, n_mfcc=13, n_fft=2048, hop_length=512)
            hnr_times, hnr = analyzer.hnr(data, frame_size=2048, hop_length=512)
            if t0:  # T-916：区间模式横轴绝对化
                times = times + t0
                hnr_times = hnr_times + t0
            features = analyzer.spectral_features(data)
            global_feats = analyzer.global_features(data)
            return (times, mfcc, hnr_times, hnr, features, global_feats)

        def done(result):
            self._cache_put(cache_key, result)
            self._build_timbre_widget(result)

        self._run_analysis_async("音色分析中...", compute, done, "音色分析失败")

    def _build_timbre_widget(self, result):
        """主线程构建音色控件。"""
        times, mfcc, hnr_times, hnr, features, global_feats = result
        from acouscope.ui.widgets.timbre import TimbreWidget

        timbre_widget = TimbreWidget()
        timbre_widget.set_data(times, mfcc, hnr_times, hnr, features, global_feats)
        self._add_analysis_widget(timbre_widget)
        self._timbre_widget = timbre_widget

        hnr_mean = float(np.mean(hnr)) if len(hnr) else 0.0
        self.lbl_status.setText(
            f"音色分析完成 ({len(times)} 帧, HNR 均值 {hnr_mean:.1f} dB)"
        )

    def _on_spectrogram3d_analysis(self, region: tuple[float, float] | None = None):
        """3D 频谱图 / 瀑布图（延迟一拍构建，让面板切换先完成绘制）。

        T-916：region=(t0, t1) 时乐段直接取选区（全量数据 + set_time_range，
        控件内部按乐段裁剪计算）；region=None 行为零改变。
        """
        region = _normalize_region(region)  # T-1019：类型守卫（非元组/None → 全文件）
        if not self.controller.has_audio():
            show_toast(self, tr("msg.no_audio"), level="info")
            return
        self._set_analysis_view(6)
        self.lbl_status.setText("计算 3D 频谱图...")

        gen = self._analysis_gen
        QTimer.singleShot(0, lambda: self._build_spectrogram3d(gen, region))

    def _build_spectrogram3d(self, gen: int, region: tuple[float, float] | None = None):
        """构建 3D 频谱图控件（matplotlib 渲染须在主线程）。"""
        if gen != self._analysis_gen:
            return  # 排队期间用户已切换视图

        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        try:
            from acouscope.ui.widgets.spectrogram3d import Spectrogram3DWidget

            # T-1008：取数经分析源抽象（默认源逐字等价）
            _src = self._analysis_source()
            data = _src.data
            sr = _src.sample_rate

            widget = Spectrogram3DWidget()
            widget.pointer_getter = self.waveform_widget.get_analysis_position
            widget.set_audio(data, sr)

            if region is not None:
                # T-916：选区分析——乐段直接取用户选区（全量数据 + set_time_range）
                widget.set_time_range(region[0], region[1])
            else:
                # CB-016-4：3D 乐段以分析位置为中心（与分析帧宽语义一致，±half）；
                # 帧宽不可得时回退 ±2.0s（沿用 3D 侧 _on_pointer_centered 的 ±2s 惯例）
                try:
                    fs = self.waveform_widget.get_frame_size()
                    half = fs / 2.0 if fs > 0 else 2.0
                except Exception:
                    half = 2.0
                pos = self.waveform_widget.get_analysis_position()
                widget.set_time_range(pos - half, pos + half)

            self._add_analysis_widget(widget)
            self._spectrogram3d_widget = widget
            # T-1054 批2：3D 内「字体设置…」上抛信号 → 切右栏「图表字体」页（单宿主；
            # 3D 控件唯一创建/装配点 connect，只连一次）
            widget.chartFontRequested.connect(
                lambda: self._on_right_page_toggled(True, 2)
            )

            t0, t1 = widget.segment
            self.lbl_status.setText(
                f"3D 频谱图 (乐段 {t0:.2f}–{t1:.2f} s, "
                f"{widget.cmb_mode.currentText()})"
            )

        except Exception as e:
            show_toast(self, f"3D 频谱图分析失败:\n{str(e)}", level="warning")
            self.lbl_status.setText("就绪")
        finally:
            QApplication.restoreOverrideCursor()

    # ------------------------------------------------------------------
    # AI 释图
    # ------------------------------------------------------------------

    def _on_room_modes(self, checked: bool = True):
        """菜单 action 入口：切中央全铺页 index2（页面内嵌 RoomModesWidget，R3 零改动）。

        T-1054 批3：房间模态由抽屉改为中央全铺页（单宿主，不再开抽屉）；
        勾选 → 进 index2，取消 → 收回 index0；切页/勾选态统一收敛于
        _set_workspace_page（唯一状态源，工具栏同钮同步，禁分裂态）。
        """
        self._set_workspace_page(2 if checked else 0)

    def _on_room_acoustics(self, checked: bool = True):
        """菜单 action 入口：切中央全铺页 index3（页面内嵌 RoomAcousticsDialog）。

        T-1054 批3：房间声学由抽屉改为中央全铺页（单宿主，不再开抽屉）；
        勾选 → 进 index3，取消 → 收回 index0；切页/勾选态统一收敛于
        _set_workspace_page（唯一状态源，工具栏同钮同步，禁分裂态）。
        """
        self._set_workspace_page(3 if checked else 0)

    def _on_ai_interpret(self):
        """AI 释图（菜单/工具栏/检查器入口）：右栏切「AI 释图」tab（T-1010）。

        右抽屉对 AI 的承载已取消（ARCH_sidebar_ai_panel §二）；每次打开新建
        面板实例，配置持久化由面板 __init__ 的 _load_config 恢复（对话历史
        为单次打开会话临时态，不保留）。
        """
        if not self.controller.has_audio():
            show_toast(self, "请先打开音频文件", level="info")
            return

        try:
            self._activate_ai_tab()
        except Exception:
            import traceback

            traceback.print_exc()
            show_toast(
                self,
                "无法打开 AI 释图面板",
                level="error",
            )

    def _current_view_name(self) -> str:
        names = ["波形", "FFT 频谱", "语谱图", "音高轨迹", "共振峰轨迹",
                 "MFCC 热图", "3D 频谱图"]
        mode = self.analysis_tab_bar.currentIndex()
        return names[mode] if mode < len(names) else "图表"

    def _capture_current_view_png(self) -> bytes | None:
        """把当前分析视图渲染为 PNG 字节（供视觉模型释读）。"""
        try:
            mode = self.analysis_tab_bar.currentIndex()

            # 3D 视图：直接从 matplotlib 画布渲染（清晰且保留当前视角）
            # T-1052：改走导出等效白底入口（与 _export_current_view mode==6 同源）
            if mode == 6:
                widget = self._live_widget("_spectrogram3d_widget")
                if widget is None:
                    return None
                import io
                buf = io.BytesIO()
                widget.export_current_view(buf, fmt="png", dpi=150)
                return buf.getvalue() or None

            widget_map = {
                0: getattr(self, "waveform_widget", None),
                1: self._live_widget("_spectrum_widget"),
                2: self._live_widget("_spectrogram_widget"),
                3: self._live_widget("_pitch_widget"),
                4: self._live_widget("_formant_widget"),
                5: self._live_widget("_timbre_widget"),
            }
            widget = widget_map.get(mode)
            if widget is None:
                return None

            pixmap = widget.grab()
            if pixmap.width() <= 0 or pixmap.height() <= 0:
                return None

            from PyQt6.QtCore import QBuffer, QIODevice
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            pixmap.save(buffer, "PNG")
            data = bytes(buffer.data())
            buffer.close()
            return data or None
        except Exception:
            return None

    def _build_ai_context(self) -> str:
        """汇总当前视图的数值上下文（随图提供给模型，防止臆造）。"""
        try:
            from acouscope.ai.prompts import build_context

            mode = self.analysis_tab_bar.currentIndex()
            info = self.controller.audio_info
            filename = ""
            if info is not None and getattr(info, "filepath", None):
                filename = Path(info.filepath).name
            sr = float(self.controller.sample_rate or 0)
            duration = float(info.duration) if info is not None else 0.0

            kwargs: dict = {}

            if mode == 1:  # FFT 频谱：谐波标记峰
                widget = self._live_widget("_spectrum_widget")
                marks = getattr(widget, "_manual_peaks", None) if widget else None
                if widget is not None and marks:
                    mag_db = 20 * np.log10(
                        np.maximum(widget._magnitude_linear, 1e-12)
                    )
                    peaks = []
                    for p in marks:
                        freq = float(p["freq"])
                        db = 0.0
                        if len(widget._freqs_hz):
                            idx = int(np.argmin(np.abs(widget._freqs_hz - freq)))
                            db = float(mag_db[idx])
                        peaks.append({
                            "freq": freq,
                            "note": str(p.get("note", "")),
                            "cents": float(p.get("cents", 0.0)),
                            "db": db,
                        })
                    kwargs["peaks"] = peaks

            elif mode == 2:  # 语谱图：STFT 参数
                widget = self._live_widget("_spectrogram_widget")
                if widget is not None:
                    kwargs["extra"] = (
                        f"- STFT 参数: {widget.fft_size} 点 FFT, "
                        f"帧移 {widget.hop_length} 样点, {widget.window_name} 窗"
                    )

            elif mode == 3:  # 音高：F0 统计
                widget = self._live_widget("_pitch_widget")
                if widget is not None and len(widget._f0):
                    voiced = widget._f0[widget._f0 > 0]
                    if len(voiced):
                        kwargs["f0_stats"] = {
                            "median": float(np.median(voiced)),
                            "min": float(np.min(voiced)),
                            "max": float(np.max(voiced)),
                        }

            elif mode == 4:  # 共振峰：各阶中位频率
                widget = self._live_widget("_formant_widget")
                if widget is not None and np.size(widget._freqs):
                    arr = np.asarray(widget._freqs)
                    if arr.ndim == 1:
                        arr = arr.reshape(-1, 1)
                    medians = []
                    for col in range(arr.shape[1]):
                        v = arr[:, col]
                        v = v[np.isfinite(v) & (v > 0)]
                        medians.append(float(np.median(v)) if len(v) else 0.0)
                    kwargs["formant_medians"] = medians

            elif mode == 5:  # 音色：HNR 与频谱特征统计
                widget = self._live_widget("_timbre_widget")
                if widget is not None:
                    stats = {}
                    if len(widget._hnr):
                        stats["HNR均值(dB)"] = f"{float(np.mean(widget._hnr)):.1f}"
                    feats = getattr(widget, "_features", {}) or {}
                    for key, label in (
                        ("spectral_flatness", "频谱平坦度均值"),
                        ("spectral_flux", "频谱通量均值"),
                        ("spectral_centroid", "频谱质心均值(Hz)"),
                    ):
                        vals = np.atleast_1d(feats.get(key, np.array([])))
                        vals = vals[np.isfinite(vals)] if vals.size else vals
                        if vals.size:
                            stats[label] = f"{float(np.mean(vals)):.4g}"
                    if stats:
                        kwargs["timbre_stats"] = stats

            elif mode == 6:  # 3D 频谱图：乐段与显示模式
                widget = self._live_widget("_spectrogram3d_widget")
                if widget is not None:
                    kwargs["segment"] = tuple(float(t) for t in widget.segment)
                    kwargs["extra"] = (
                        f"- 显示模式: {widget.cmb_mode.currentText()}"
                    )

            return build_context(
                self._current_view_name(),
                filename=filename,
                sample_rate=sr,
                duration=duration,
                **kwargs,
            )
        except Exception:
            return "【数值上下文不可用】"

    # ------------------------------------------------------------------
    # 图表字体
    # ------------------------------------------------------------------

    def _current_chart_fonts(self) -> tuple[str, str]:
        """读取当前图表字体设置 (西文, 中文)，以设置文件为准，失败回退 auto。"""
        try:
            from acouscope.utils.config import Settings

            s = Settings.load()
            latin = getattr(s, "chart_font_latin", "auto") or "auto"
            cjk = getattr(s, "chart_font_cjk", "auto") or "auto"
            return latin, cjk
        except Exception:
            s = self.controller.settings
            return (
                getattr(s, "chart_font_latin", "auto") or "auto",
                getattr(s, "chart_font_cjk", "auto") or "auto",
            )

    def _apply_chart_fonts(self, latin: str, cjk: str):
        """持久化图表字体并同步已打开的 3D 视图（抽屉即时生效路径）。"""
        self.controller.settings.chart_font_latin = latin
        self.controller.settings.chart_font_cjk = cjk
        try:
            from acouscope.utils.config import Settings

            settings = Settings.load()
            settings.chart_font_latin = latin
            settings.chart_font_cjk = cjk
            settings.save()
        except Exception as e:
            # T-1074 G3③（承 T72-08）：图表字体偏好落盘失败补日志痕
            _log.warning("图表字体偏好保存失败: %s", e, exc_info=True)

        # 同步已打开的 3D 视图
        widget = self._live_widget("_spectrogram3d_widget")
        if widget is not None:
            try:
                widget.set_chart_font(latin, cjk)
            except Exception:
                pass

        def _label(v: str) -> str:
            return "自动" if v == "auto" else v

        self.statusBar().showMessage(
            f"图表字体已更新：西文 {_label(latin)} / 中文 {_label(cjk)}", 5000
        )

    def _on_chart_font_settings(self, checked: bool = True):
        """图表字体入口（菜单 action）：切右栏「图表字体」页（T-1054 批2 单宿主改造）。

        不再开抽屉（去抽屉通路）；checked → 展开右栏并切 index2，未勾选 → 折叠右栏；
        均走泛化槽 _on_right_page_toggled（与 3D 内按钮/面板头图表字体钮同一宿主）。
        UI 宪法条 3 语义保留：仍是「非模态、禁 exec」。
        """
        self._on_right_page_toggled(bool(checked), 2)

    # ------------------------------------------------------------------
    # T-1044：图表设计器（导出前设计交互：中央 index4 全铺页 + 实时预览 + 四组参数）
    # T-1054 批4a：抽屉通路退役（零抽屉口径），入口 = 工作区开关组 / 菜单 action。
    # ------------------------------------------------------------------

    def _on_chart_designer(self, checked: bool = True) -> None:
        """图表设计器入口（T-1054a：改中央全铺页 index4；抽屉通路已退役）。"""
        if checked:
            self._set_workspace_page(4)
        else:
            stack = getattr(self, "central_stack", None)
            if stack is not None and stack.currentIndex() == 4:
                self._set_workspace_page(0)

    def _chart_designer_panel(self):
        """图表设计器面板（T-1054 批4a：常驻单实例；未构建返回 None）。"""
        return getattr(self, "chart_designer_panel", None)

    def _current_chart_designer_params(self) -> dict:
        """会话态参数（持久化第①层；未打开过设计器则为空 dict = 既有行为）。"""
        return getattr(self, "_chart_designer_params", None) or {}

    def _on_chart_designer_params(self) -> None:
        """参数变化 → ① 更新会话态 ② 排程写全局默认（去抖，避免拖动刷盘）。"""
        panel = self._chart_designer_panel()
        if panel is None:
            return
        self._chart_designer_params = panel.params()
        timer = getattr(self, "_chart_designer_save_timer", None)
        if timer is None:
            timer = self._chart_designer_save_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._persist_chart_designer_defaults)
        timer.start(_CHART_DESIGNER_SAVE_DELAY_MS)

    def _persist_chart_designer_defaults(self) -> None:
        """写全局默认（持久化第②层：Settings，照 default_journal_template /
        chart_font_* 范式）；失败静默（不影响预览与导出）。"""
        settings = getattr(self.controller, "settings", None)
        params = self._current_chart_designer_params()
        if settings is None or not params:
            return
        try:
            settings.chart_designer_palette = str(params.get("palette") or "default")
            settings.chart_designer_grid = bool(params.get("grid", True))
            settings.chart_designer_figsize_w = float(params.get("width") or 0.0)
            settings.chart_designer_figsize_h = float(params.get("height") or 0.0)
            settings.default_journal_template = str(params.get("template") or "default")
            if params.get("format"):
                settings.default_format = str(params["format"])
            if params.get("dpi"):
                settings.default_dpi = int(params["dpi"])
            settings.save()
        except Exception as e:
            # T-1074 G3③（承 T72-08）：图表设计器参数落盘失败补日志痕
            _log.warning("图表设计器参数保存失败: %s", e, exc_info=True)

    def _on_chart_designer_export(self) -> None:
        """设计器「导出…」→ 既有导出单路径（选择保存位置）。"""
        self._on_export_figure()

    def _on_chart_designer_font_settings(self) -> None:
        """字体组「字体设置…」→ 跳转既有字体入口（字体值保持单一来源）。"""
        self._set_entry_checked(self.action_chart_font, True)

    def _build_chart_exporter(self):
        """按会话参数建 `FigureExporter`（预览与导出**同一条构造路径**）。

        T-1045（裁决最小豁免）：仅本函数 + `_export_current_view` 允许转发内容外壳/
        参考线/AT-01 新参（ref_ink/子标题/来源/脚注/闸门）；其余 main_window 禁碰。
        """
        from acouscope.visualization.exporters import FigureExporter

        latin, cjk = self._current_chart_fonts()
        params = self._current_chart_designer_params()
        return FigureExporter(
            font_latin=latin,
            font_cjk=cjk,
            palette=params.get("palette", "default"),
            width=params.get("width"),
            height=params.get("height"),
            grid=params.get("grid", True),
            ref_ink=params.get("ref_ink"),
            subtitle=params.get("subtitle"),
            source=params.get("source"),
            footer=params.get("footer"),
            at01_gate=bool(params.get("at01_gate")),
            ref_values=params.get("ref_values"),
            ref_linestyle=params.get("ref_linestyle", "--"),
        )

    def _chart_designer_dpi(self) -> int:
        """会话层 DPI（设计器 ⑥ 组）；无会话参数 → 既有全局默认读数。"""
        try:
            dpi = int(self._current_chart_designer_params().get("dpi"))
        except (TypeError, ValueError):
            return self._export_dpi()
        return dpi if 72 <= dpi <= 1200 else self._export_dpi()

    def _render_chart_designer_preview(self, path, dpi: int, preview: bool = True) -> bool:
        """设计器预览渲染（宿主侧注入给面板）。

        与导出同源：同一条 `_export_current_view` + 同一 `_build_chart_exporter`，
        仅 DPI（72）与「是否预览」（重图降采样）不同 → 所见即所得。
        """
        if not self.controller.has_audio():
            return False
        exporter = self._build_chart_exporter()
        mode = self.analysis_tab_bar.currentIndex()
        try:
            self._export_current_view(
                exporter, mode, Path(path), "png", dpi=int(dpi), preview=bool(preview)
            )
        except Exception:
            return False
        return True

    @staticmethod
    def _preview_stride(length: int, limit: int) -> int:
        """预览降采样步长（Step 0 实测：语谱图 72dpi ≈535ms > 400ms 档 → 重图降采样）。"""
        return max(1, (int(length) + int(limit) - 1) // int(limit))

    def _on_settings(self, checked: bool = True):
        """统一设置入口（菜单/左 ribbon ⚙/快捷键）：切左栏「设置」tab（T-1010）。

        右抽屉对设置的承载已取消；设置面板为左栏常驻 tab 单实例，应用/取消
        分别走 _on_settings_applied/_on_settings_cancelled（语义与 T-504g 一致）。
        T-1043（§五b/N5）：本入口产生持续态界面（左栏设置页）→ 开关语义：
        取消勾选（再点同入口 / 左栏折叠反同步）→ 折叠左栏。
        """
        if not checked:
            self._collapse_left_panel()
            return
        try:
            self._activate_settings_tab()
        except Exception as e:
            import traceback

            traceback.print_exc()
            # 打开失败 → 入口不留虚假勾选态（T-1043）
            self._set_entry_checked(self.action_settings, False)
            show_toast(
                self,
                f"{tr('settings.title')}: {type(e).__name__}: {e}",
                level="error",
            )

    # ------------------------------------------------------------------
    # 项目管理
    # ------------------------------------------------------------------

    def _on_new_project(self):
        """T-1002：新建项目（复用既有 ProjectNewDialog，禁新建对话框类）。

        项目经对话框写入 controller.project 管理器本体 → 创建成功后按打开项目
        同口径同步窗口标题 / 文件浏览器 / 检查器档案区（零新状态）。
        """
        from acouscope.ui.widgets.project_new_dialog import ProjectNewDialog

        dlg = ProjectNewDialog(self.controller.project, parent=self)
        dlg.exec()
        if not dlg.was_created():
            return
        proj = self.controller.project
        self._update_window_title(proj.current.name)
        self.lbl_status.setText(f"项目已创建: {proj.filepath}")
        self._project_dirty = False
        fb = getattr(self, "file_browser", None)
        if fb is not None:
            fb.set_manager(proj)
        ins = getattr(self, "inspector_panel", None)
        if ins is not None:
            ins.set_manager(proj)

    def _on_open_project(self):
        """打开项目。"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "打开项目", "", "AcouScope 项目 (*.acouproj)"
        )
        if not filepath:
            return

        try:
            self.lbl_status.setText(f"正在加载项目: {Path(filepath).name}...")
            self.lbl_status.repaint()

            project, info = self.controller.load_project(filepath)

            if info is not None:
                self._sync_after_open(info)
            else:
                show_toast(
                    self,
                    "项目已加载，但其中的音频文件均不存在，\n请手动打开音频文件。",
                    level="warning",
                )

            self._update_window_title(project.name)
            self.lbl_status.setText(f"项目已加载: {project.name}")
            self._project_dirty = False  # T-322: 加载即干净（新内容变更再置脏）

            # T-1010：文件浏览器（左栏 tab①）切换到项目目录（音频缺省时仍列目录）
            fb = getattr(self, "file_browser", None)
            if fb is not None:
                fb.set_manager(self.controller.project)
            # T-912：检查器档案元数据区同步项目管理器（登记/保存依赖）
            ins = getattr(self, "inspector_panel", None)
            if ins is not None:
                ins.set_manager(self.controller.project)

        except Exception as e:
            show_toast(self, f"无法打开项目:\n{str(e)}", level="error")
            self.lbl_status.setText("就绪")

    def _on_save_project(self):
        """保存项目（无路径时转为另存为）。"""
        if self.controller.project.filepath is None:
            self._on_save_project_as()
            return
        self._do_save_project(self.controller.project.filepath)

    def _on_save_project_as(self):
        """项目另存为。"""
        default_name = ""
        if self.controller.current_file is not None:
            default_name = self.controller.current_file.stem + ".acouproj"

        filepath, _ = QFileDialog.getSaveFileName(
            self, "项目另存为", default_name, "AcouScope 项目 (*.acouproj)"
        )
        if not filepath:
            return
        if not filepath.endswith(".acouproj"):
            filepath += ".acouproj"
        self._do_save_project(filepath)

    def _do_save_project(self, filepath):
        """执行项目保存（手动/另存为；成功后清脏标记）。"""
        try:
            self._save_project_to(filepath)
            self._project_dirty = False
            self._update_window_title(self.controller.project.current.name)
            self.lbl_status.setText(f"项目已保存: {self.controller.project.filepath}")
        except Exception as e:
            show_toast(self, f"无法保存项目:\n{str(e)}", level="error")

    def _collect_harmonic_marks(self):
        """收集频谱控件的谐波标记（转为可 JSON 序列化的数据）。"""
        widget = self._live_widget("_spectrum_widget")
        if widget is None or not hasattr(widget, "_manual_peaks"):
            return None

        return [
            {
                "freq": float(p["freq"]),
                "note": str(p.get("note", "")),
                "cents": float(p.get("cents", 0.0)),
                "midi": float(p.get("midi", 0.0)),
            }
            for p in widget._manual_peaks
        ]

    def _update_window_title(self, project_name: str):
        """更新窗口标题（含项目名）。"""
        self.setWindowTitle(f"{project_name} - AcouScope 音析")

    # ------------------------------------------------------------------
    # 图表导出
    # ------------------------------------------------------------------

    def _export_format_default(self) -> str:
        """读取全局默认导出格式（偏好设置），非法值回退 svg。"""
        fmt = getattr(self.controller.settings, "default_format", "svg")
        return fmt if fmt in ("svg", "png", "pdf", "eps") else "svg"

    def _export_dpi(self) -> int:
        """读取全局默认导出 DPI（偏好设置），非法值回退 300。"""
        try:
            dpi = int(getattr(self.controller.settings, "default_dpi", 300))
        except Exception:
            dpi = 300
        return dpi if dpi in (150, 300, 600, 1200) else 300

    def _on_export_audio(self, fmt: str = ""):
        """导出当前音频为文件（WAV/FLAC/MP3 等）。

        Args:
            fmt: 指定格式（空字符串则弹出对话框选择）
        """
        if not self.controller.has_audio():
            show_toast(self, tr("msg.no_audio"), level="info")
            return

        data = self.controller.audio_data
        sr = self.controller.sample_rate
        current_file = self.controller.current_file

        # 确定文件名
        if current_file is not None:
            default_stem = current_file.stem
        else:
            default_stem = "audio"

        if not fmt:
            # 弹出选择对话框
            filter_map = {
                "wav": "WAV 音频 (*.wav)",
                "flac": "FLAC 无损 (*.flac)",
                "mp3": "MP3 音频 (*.mp3)",
                "ogg": "OGG Vorbis (*.ogg)",
            }
            filters = ";;".join(filter_map.values())
            filepath, selected_filter = QFileDialog.getSaveFileName(
                self, "导出音频", default_stem + ".wav", filters
            )
            if not filepath:
                return
            # 从选中的过滤器推断格式
            for key, f in filter_map.items():
                if f == selected_filter:
                    fmt = key
                    break
            if not fmt:
                fmt = Path(filepath).suffix.lower().lstrip(".") or "wav"
        else:
            filepath = default_stem + "." + fmt

        # 确保后缀正确
        if not filepath.lower().endswith("." + fmt):
            filepath += "." + fmt

        target = Path(filepath)

        # 检查写入权限
        if not self._dir_writable(target.parent):
            target = self._fallback_export_path(target)

        try:
            self.lbl_status.setText(f"导出 {fmt.upper()} 音频...")
            self.lbl_status.repaint()

            self._save_audio_file(data, sr, str(target), fmt)

            self.lbl_status.setText(f"音频已导出: {target}")
            show_toast(
                self,
                f"音频已导出为 {fmt.upper()} 格式：\n{target.name}",
                level="success",
            )
        except Exception as e:
            import traceback
            detail = traceback.format_exc().strip().splitlines()
            hint = "\n".join(detail[-3:])
            show_toast(
                self,
                f"音频导出失败:\n{type(e).__name__}: {e}\n\n{hint}",
                level="error",
            )
            self.lbl_status.setText("就绪")

    def _save_audio_file(self, data: np.ndarray, sample_rate: int,
                         path: str, fmt: str):
        """保存音频数据到文件。

        Args:
            data: 单声道 float64 数据
            sample_rate: 采样率
            path: 输出路径
            fmt: 格式 (wav / flac / mp3 / ogg)
        """
        fmt = fmt.lower()

        if fmt == "wav":
            # 使用标准库 wave 模块，零依赖
            import wave
            pcm = np.clip(data, -1.0, 1.0)
            pcm = (pcm * 32767.0).astype(np.int16)
            with wave.open(path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm.tobytes())

        elif fmt in ("flac", "mp3", "ogg"):
            # 优先使用 soundfile（支持多格式）
            try:
                import soundfile as sf
                sf.write(path, data, sample_rate, format=fmt.upper())
                return
            except ImportError:
                pass

            # 改以 pydub + ffmpeg
            try:
                from pydub import AudioSegment
                # 先存为 wav 再转换
                import tempfile, os
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp_path = tmp.name
                self._save_audio_file(data, sample_rate, tmp_path, "wav")
                audio = AudioSegment.from_wav(tmp_path)
                audio.export(path, format=fmt)
                os.unlink(tmp_path)
                return
            except ImportError:
                pass

            raise RuntimeError(
                f"导出 {fmt.upper()} 需要安装 soundfile 或 pydub 库。\n"
                f"请运行: pip install soundfile  (推荐，支持 FLAC/OGG)\n"
                f"或: pip install pydub  (需要系统安装 ffmpeg，支持 MP3)"
            )
        else:
            raise ValueError(f"不支持的音频格式: {fmt}")

    def _on_export_figure(self):
        """导出当前分析视图为学术图表。"""
        if not self.controller.has_audio():
            show_toast(self, tr("msg.no_audio"), level="info")
            return
        mode = self.analysis_tab_bar.currentIndex()
        default_fmt = self._export_format_default()
        filter_map = {
            "svg": "SVG 矢量图 (*.svg)",
            "png": "PNG 位图 (*.png)",
            "pdf": "PDF 矢量图 (*.pdf)",
            "eps": "EPS 矢量图 (*.eps)",
        }
        # T-1044：设计器会话选择（⑥ 导出组）优先，仍限既有四格式
        session_fmt = self._current_chart_designer_params().get("format")
        if session_fmt in filter_map:
            default_fmt = session_fmt
        filters = ";;".join(filter_map[k] for k in ("svg", "png", "pdf", "eps"))
        initial_filter = filter_map[default_fmt]

        mode_names = ["波形", "频谱", "语谱图", "音高", "共振峰", "MFCC", "3D频谱图"]
        mode_name = mode_names[mode] if mode < len(mode_names) else "图表"
        default_name = ""
        if self.controller.current_file is not None:
            default_name = (
                self.controller.current_file.stem + "_" + mode_name + "." + default_fmt
            )

        filepath, _ = QFileDialog.getSaveFileName(
            self, "导出图表", default_name, filters, initial_filter
        )
        if not filepath:
            return

        suffix = Path(filepath).suffix.lower().lstrip(".")
        if suffix not in ("svg", "png", "pdf", "eps"):
            suffix = default_fmt
            filepath += "." + default_fmt

        target = Path(filepath)
        relocated = False
        if not self._dir_writable(target.parent):
            # macOS TCC 可能拒绝进程写入桌面/下载等目录：自动改存
            target = self._fallback_export_path(target)
            relocated = True

        try:
            self.lbl_status.setText("导出图表...")
            self.lbl_status.repaint()

            # T-1044：与预览同源——同一 _build_chart_exporter（会话参数）+ 同一
            # _export_current_view 路径；仅 DPI（导出 DPI）与是否降采样不同。
            exporter = self._build_chart_exporter()
            dpi = self._chart_designer_dpi()
            try:
                saved = self._export_current_view(
                    exporter, mode, target, suffix, dpi=dpi
                )
            except PermissionError:
                target = self._fallback_export_path(target)
                saved = self._export_current_view(
                    exporter, mode, target, suffix, dpi=dpi
                )
                relocated = True

            self.lbl_status.setText(f"图表已导出: {saved}")
            if relocated:
                show_toast(
                    self,
                    "原目标目录无写入权限（macOS 系统隐私权限限制）。\n"
                    f"图表已改存到：\n{saved}\n\n"
                    "如需直接写入桌面，请在 系统设置 → 隐私与安全性 → "
                    "完全磁盘访问权限 中允许本应用。",
                    level="info",
                )

        except Exception as e:
            import traceback
            detail = traceback.format_exc().strip().splitlines()
            hint = "\n".join(detail[-3:])
            show_toast(
                self,
                f"图表导出失败:\n{type(e).__name__}: {e}\n\n{hint}",
                level="error",
            )
            self.lbl_status.setText("就绪")

    @staticmethod
    def _dir_writable(directory: Path) -> bool:
        """探测目录是否可写（TCC 拒绝时 open 会抛 PermissionError）。"""
        try:
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / ".acouscope_write_probe"
            probe.write_text("probe", encoding="utf-8")
            probe.unlink()
            return True
        except OSError:
            return False

    def _fallback_export_path(self, original: Path) -> Path:
        """返回尽可能可写的备用导出路径。

        依次尝试：~/Documents/AcouScope导出 → 当前音频所在目录 → 用户主目录。
        """
        candidates = [Path.home() / "Documents" / "AcouScope导出"]
        current = getattr(self.controller, "current_file", None)
        if current is not None:
            candidates.append(Path(current).parent)
        candidates.append(Path.home())

        for cand in candidates:
            if self._dir_writable(cand):
                return cand / original.name
        return candidates[-1] / original.name

    def _export_current_view(
        self, exporter, mode: int, path: Path, fmt: str,
        *, dpi: int | None = None, preview: bool = False,
    ) -> Path:
        """按当前分析模式导出对应图表。

        控件已失效（被面板替换删除）时自动重算分析，保证导出总能成功。

        T-1044：`dpi` / `preview` 为 keyword-only（默认 = 既有行为）。
        设计器预览即走本方法（同源），仅 `dpi=72` + `preview=True`（重图降采样）。
        """
        # T-1046（件3）：报告/预览/导出同源 —— 会话参数覆写传入 exporter 的内容外壳/
        # 参考线。报告侧 exporter 自建（_collect_report_figures，不经 _build_chart_exporter），
        # 故在此统一覆写；直接导出路径为幂等（值与本函数同一参数源）。
        params = self._current_chart_designer_params()
        if params:
            exporter.subtitle = params.get("subtitle")
            exporter.source = params.get("source")
            exporter.footer = params.get("footer")
            exporter.at01_gate = bool(params.get("at01_gate"))
            exporter.ref_values = (
                list(params["ref_values"]) if params.get("ref_values") else None
            )
            exporter.ref_linestyle = params.get("ref_linestyle", "--")
            if params.get("ref_ink"):
                exporter.ink["ref_line"] = params["ref_ink"]

        data = self.controller.audio_data
        sr = self.controller.sample_rate
        base = path.stem
        dpi = self._export_dpi() if dpi is None else int(dpi)

        # T-1045（裁决撞名口径）：用户设了标题 → 用用户文本；否则回落 base（产物不变）
        user_title = (self._current_chart_designer_params().get("title") or "").strip()
        caption = user_title or base

        if mode == 0:  # 波形
            times = np.arange(len(data), dtype=np.float32) / np.float32(sr)
            return exporter.export_waveform(times, data, path, fmt=fmt, dpi=dpi, title=caption)

        if mode == 1:  # FFT 频谱
            widget = self._live_widget("_spectrum_widget")
            if widget is None:
                self._on_fft_analysis()
                QApplication.sendPostedEvents()
                widget = self._live_widget("_spectrum_widget")
            if widget is None or len(widget._freqs_hz) == 0:
                raise ValueError("频谱计算失败，无法导出")

            # 跟随当前窗口显示：单位（Hz/kHz/MIDI/…、线性/dB/dBFS/…）、
            # 可见范围（缩放/平移/预设频段）与标记全部与窗口一致，
            # 否则无论窗口如何设置，导出永远是同一张全频段 dB 图
            view = widget.get_view_export()
            return exporter.export_spectrum(
                view["x"], view["y"], path, fmt=fmt, dpi=dpi, title=caption,
                xlabel=view["xlabel"], ylabel=view["ylabel"],
                markers=view["markers"],
                xlim=view["xlim"], ylim=view["ylim"],
            )

        if mode == 2:  # 语谱图
            widget = self._live_widget("_spectrogram_widget")
            if widget is None:
                self._on_spectrogram_analysis()
                QApplication.sendPostedEvents()
                widget = self._live_widget("_spectrogram_widget")
            if widget is None or widget._magnitude_db.size == 0:
                raise ValueError("语谱图计算失败，无法导出")

            try:
                db_range = float(widget.spn_dr.value())
            except RuntimeError:
                db_range = 60.0
            freqs, times, matrix = widget._freqs, widget._times, widget._magnitude_db
            vmax = float(np.max(matrix))
            vmin = vmax - db_range
            if preview:
                # 重图预览降采样（Step 0：语谱图 72dpi ≈535ms > 400ms 档）；导出仍全量
                step = self._preview_stride(max(matrix.shape), 500)
                freqs, times = freqs[::step], times[::step]
                matrix = matrix[::step, ::step]
            return exporter.export_spectrogram(
                freqs, times, matrix,
                path, fmt=fmt, dpi=dpi,
                title=caption, vmin=vmin, vmax=vmax,
            )

        if mode == 3:  # 音高
            widget = self._live_widget("_pitch_widget")
            if widget is None:
                self._on_pitch_analysis()
                QApplication.sendPostedEvents()
                widget = self._live_widget("_pitch_widget")
            if widget is None or len(widget._times) == 0:
                raise ValueError("音高检测失败，无法导出")

            return exporter.export_pitch_contour(
                widget._times, widget._f0, path, fmt=fmt, dpi=dpi, title=caption
            )

        if mode == 4:  # 共振峰
            widget = self._live_widget("_formant_widget")
            if widget is None:
                self._on_formant_analysis()
                QApplication.sendPostedEvents()
                widget = self._live_widget("_formant_widget")
            if widget is None or len(widget._times) == 0:
                raise ValueError("共振峰分析失败，无法导出")

            return exporter.export_formants(
                widget._times, widget._freqs, path, fmt=fmt, dpi=dpi, title=caption
            )

        if mode == 5:  # 音色（MFCC 热图）
            widget = self._live_widget("_timbre_widget")
            if widget is None:
                self._on_timbre_analysis()
                QApplication.sendPostedEvents()
                widget = self._live_widget("_timbre_widget")
            if widget is None or widget._mfcc.size == 0:
                raise ValueError("音色分析失败，无法导出")

            times, mfcc = widget._times, widget._mfcc
            if preview:
                # 重图预览降采样（同上）；导出仍全量
                step = self._preview_stride(len(times), 1500)
                times, mfcc = times[::step], mfcc[::step]
            return exporter.export_mfcc(
                times, mfcc, path,
                fmt="png", dpi=dpi, title=caption,
            )

        if mode == 6:  # 3D 频谱图 / 瀑布图
            widget = self._live_widget("_spectrogram3d_widget")
            if widget is None:
                self._on_spectrogram3d_analysis()
                QApplication.sendPostedEvents()
                widget = self._live_widget("_spectrogram3d_widget")
            if widget is None or len(widget._stft_times) == 0:
                raise ValueError("3D 频谱图计算失败，无法导出")

            # 直接导出当前渲染的画布（保留用户的视角、模式与乐段选择）
            # T-1052：改走导出等效白底入口，与 3D 自带导出同源（EXPORT_FACE 白底）
            widget.export_current_view(path, fmt=fmt, dpi=dpi)
            return path

        raise ValueError("未知分析模式")

    def _on_visit_site(self):
        """访问网站（T-1015）：打开主站（QDesktopServices.openUrl，仅用户点击触发）。"""
        from acouscope.ui.constants import SITE_MAIN_URL, open_site

        open_site(SITE_MAIN_URL)

    def _rebuild_shortcuts_overview(self) -> None:
        """T-1002：快捷键总览子菜单（展开时实时重建，零第二份快捷键清单）。

        条目来源 = 窗口内全部 QAction 的快捷键（含菜单/工具栏/子菜单），按键位
        排序；无快捷键的动作不入列（总览只列「可键盘直达」命令）。
        """
        menu = getattr(self, "menu_shortcuts_overview", None)
        if menu is None:
            return
        menu.clear()
        entries = []
        for act in self.findChildren(QAction):
            shortcut = act.shortcut().toString()
            label = act.text().replace("&", "").strip()
            if shortcut and label:
                entries.append((shortcut, label))
        if not entries:
            menu.addAction(tr("action.shortcuts_empty"))
            return
        for shortcut, label in sorted(set(entries)):
            menu.addAction(f"{label}  ({shortcut})")

    def _on_about(self):
        """打开关于对话框（模态 QDialog，CB-010 用户特批「关于」回归模态）。

        快速入门/用户手册仍走非模态抽屉；「关于」例外：AboutDialog(self).exec()
        模态弹出（内容/样式与抽屉版本一致，见 about_dialog.py），关闭后返回主窗。
        """
        from acouscope.ui.widgets.about_dialog import AboutDialog

        AboutDialog(self).exec()

    # ------------------------------------------------------------------
    # T-1012：工具栏右栏展开/折叠 toggle（原左侧图标栏开关已删除，ribbon 常驻）
    # ------------------------------------------------------------------

    def _sync_right_panel_toggle(self, collapsed: bool = False) -> None:
        """右栏折叠态 → 工具栏 btn_toggle_right_panel 反同步（blockSignals 防回环）。"""
        btn = getattr(self, "btn_toggle_right_panel", None)
        if btn is None:
            return
        checked = not bool(collapsed)
        if btn.isChecked() != checked:
            btn.blockSignals(True)
            btn.setChecked(checked)
            btn.blockSignals(False)

    def _on_toggle_right_panel(self, checked: bool) -> None:
        """工具栏右栏 toggle：checked=右栏展开；未勾选 → 右栏折叠为窄条。

        外部（标题栏折叠钮/恢复布局）折叠 → collapsedChanged →
        _sync_right_panel_toggle 反同步按钮状态。
        """
        panel = getattr(self, "right_panel", None)
        if panel is not None:
            panel.set_collapsed(not checked)

    # ------------------------------------------------------------------
    # T-1048：工具栏左栏面板开关（与右栏同构；≠ ribbon 页签开关，两者并存）
    # ------------------------------------------------------------------

    def _sync_left_panel_toggle(self, collapsed: bool | None = None) -> None:
        """左栏折叠态 → 工具栏 btn_toggle_left_panel 反同步（blockSignals 防回环）。

        collapsed 缺省（None）时实读左栏当前态 —— 初始同步与 collapsedChanged
        汇入同一出口（对照 _sync_left_ribbon_toggle 口径）。
        """
        btn = getattr(self, "btn_toggle_left_panel", None)
        if btn is None:
            return
        panel = getattr(self, "left_panel", None)
        if collapsed is None:
            if panel is None:
                return
            collapsed = panel.is_collapsed()
        checked = not bool(collapsed)
        if btn.isChecked() != checked:
            btn.blockSignals(True)
            btn.setChecked(checked)
            btn.blockSignals(False)

    def _on_toggle_left_panel(self, checked: bool) -> None:
        """工具栏左栏 toggle：checked=左栏展开；未勾选 → 左栏折叠为窄条。

        纯可见性（不切左栏页签）；ribbon 页签按钮语义由 T-1043 独立维护。
        """
        panel = getattr(self, "left_panel", None)
        if panel is not None:
            panel.set_collapsed(not checked)

    # ------------------------------------------------------------------
    # T-1043：交互语义（开关 vs 命令）——持续态界面入口开关化 + 双向同步
    # 语义源：ARCH_ui_visual_language §五b（判据 N1）/ §五-6（激活态）
    # ------------------------------------------------------------------

    @staticmethod
    def _set_entry_checked(entry, checked: bool) -> None:
        """写入口勾选态（blockSignals 防回环；值相同则不动，杜绝信号风暴）。"""
        if entry is not None and entry.isChecked() != bool(checked):
            entry.blockSignals(True)
            entry.setChecked(bool(checked))
            entry.blockSignals(False)

    def _left_page_entries(self) -> tuple:
        """左栏页签入口 → 页索引（files=0 / quickstart=1 / manual=2 / record=3 / settings=4）。

        T-1054 批1b：面板头 4 页签钮 + ribbon 置底设置钮 + 菜单设置 action 同组；
        同 index 的两个设置入口同勾选属设计，异 index 互斥（批1a 口径）。
        """
        return (
            (getattr(self, "btn_header_files", None), 0),
            (getattr(self, "btn_header_quickstart", None), 1),
            (getattr(self, "btn_header_manual", None), 2),
            (getattr(self, "btn_header_record", None), 3),
            (getattr(self, "ribbon_btn_settings", None), 4),
            (getattr(self, "action_settings", None), 4),
            # T-1054 批4b 帮助族：快速入门/用户手册/帮助? 并入同组（同 index 同勾选、异 index 互斥）
            (getattr(self, "action_quickstart", None), 1),
            (getattr(self, "action_manual", None), 2),
            (getattr(self, "ribbon_btn_help", None), 1),
        )

    def _sync_left_ribbon_toggle(self, collapsed: bool | None = None) -> None:
        """左栏（展开态 + 当前页）→ 页签入口勾选态反同步（blockSignals 防回环）。

        对照 _sync_right_panel_toggle；左栏自带折叠钮 / 恢复布局等外部路径经
        collapsedChanged 汇入同一出口（§五b 状态与可见性双向同步）。
        """
        left = getattr(self, "left_panel", None)
        content = getattr(self, "left_content", None)
        if left is None or content is None:
            return
        is_collapsed = left.is_collapsed() if collapsed is None else bool(collapsed)
        current = content.currentIndex()
        for entry, index in self._left_page_entries():
            self._set_entry_checked(entry, (not is_collapsed) and current == index)
        # T-1054 批4c（R3 M5）：左栏折叠 / 当前页非 index3 → 录音页收回清账
        # （面板头录音钮再点、工具栏左栏开关等外部路径均汇入本出口）
        if is_collapsed or current != 3:
            self._on_record_page_retracted()

    def _collapse_left_panel(self) -> None:
        """左栏折叠为窄条（页签入口「再点收回」路径，与右栏折叠语义对称）。"""
        left = getattr(self, "left_panel", None)
        if left is not None:
            left.set_collapsed(True)

    def _on_left_page_toggled(self, checked: bool, index: int) -> None:
        """页签型入口开关槽（T-1054 批1a/b 泛化·合并原 ribbon/面板头槽）。

        面板头 4 页签钮（files/quickstart/manual/record）与 ribbon 置底设置钮全部
        接本槽，禁两套逻辑。checked → 展开左栏并切对应页（0=文件/1=快速入门/
        2=手册/3=录音设置/4=设置）；not checked → 折叠左栏
        （T-1043 §5b-9/-11「切页型入口 = 开关」）。
        """
        if checked:
            if index == 0:
                self._activate_files_tab()
            elif index == 4:
                self._activate_settings_tab()
            elif index == 1:
                self._show_left_content(getattr(self, "_quickstart_page", None))
            elif index == 2:
                self._show_left_content(getattr(self, "_manual_page", None))
            elif index == 3:
                self._show_left_content(getattr(self, "_record_settings_page", None))
        else:
            self._collapse_left_panel()

    # ------------------------------------------------------------------
    # T-1054 批2：右栏页签条（检查器 / AI 释图 / 图表字体）——照左栏范式唯一总表 + 泛化开关槽
    # ------------------------------------------------------------------

    def _right_page_entries(self) -> tuple:
        """右栏页签入口 → 页索引（inspector=0 / ai=1 / chart_font=2）。

        T-1054 批2：面板头 3 页签钮 + 菜单 action_chart_font；同 index 的
        action_chart_font 与面板头图表字体钮同勾选属设计，异 index 互斥（照左栏范式）。
        """
        return (
            (getattr(self, "btn_header_inspect", None), 0),
            (getattr(self, "btn_header_ai", None), 1),
            (getattr(self, "btn_header_chart_font", None), 2),
            (getattr(self, "action_chart_font", None), 2),
        )

    def _show_right_content(self, widget) -> None:
        """切右栏当前内容并展开右栏（0=检查器 / 2=图表字体页；AI 页见 _activate_ai_tab）。"""
        content = getattr(self, "right_content", None)
        if content is None or widget is None:
            return
        content.setCurrentWidget(widget)
        right_panel = getattr(self, "right_panel", None)
        if right_panel is not None and right_panel.is_collapsed():
            right_panel.set_collapsed(False)
        # 展开 + 当前页 → 页签入口勾选态单点收敛（异 index 互斥）
        self._sync_right_page_toggle()

    def _collapse_right_panel(self) -> None:
        """右栏折叠为窄条（页签入口「再点收回」路径，与左栏折叠语义对称）。"""
        right_panel = getattr(self, "right_panel", None)
        if right_panel is not None:
            right_panel.set_collapsed(True)

    def _sync_right_page_toggle(self) -> None:
        """右栏（展开态 + 当前页）→ 页签入口勾选态反同步（blockSignals 防回环）。

        对照 _sync_left_ribbon_toggle；右栏自带折叠钮 / 恢复布局等外部路径经
        collapsedChanged 汇入 _sync_right_panel_toggle（工具栏开关），页签钮勾选态
        在到达本函数或泛化槽时收敛（异 index 互斥）。
        """
        right = getattr(self, "right_panel", None)
        content = getattr(self, "right_content", None)
        if right is None or content is None:
            return
        is_collapsed = right.is_collapsed()
        current = content.currentIndex()
        for entry, index in self._right_page_entries():
            self._set_entry_checked(entry, (not is_collapsed) and current == index)

    def _on_right_page_toggled(self, checked: bool, index: int) -> None:
        """右栏页签入口开关槽（T-1054 批2 泛化）。

        面板头 3 页签钮（inspector/ai/chart_font）与菜单 action_chart_font 全部接本槽，
        禁两套逻辑。checked → 展开右栏并切对应页（0=检查器/1=AI 释图/2=图表字体）；
        not checked → 折叠右栏（「切页型入口 = 开关」）。
        """
        if checked:
            if index == 1:
                self._activate_ai_tab()
            elif index == 2:
                self._show_right_content(getattr(self, "_chart_font_page", None))
            else:
                self._show_right_content(getattr(self, "inspector_panel", None))
            self._sync_right_page_toggle()
        else:
            self._collapse_right_panel()

    # ------------------------------------------------------------------
    # 关闭事件
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        """关闭窗口事件。"""
        # T-1093 M-C：splitterMoved 落盘已改为尾部合并 → 退出前补存一次，
        # 防「拖完立刻退出」丢末次布局（定时器未及触发）。
        _save_timer = getattr(self, "_ws_layout_save_timer", None)
        if _save_timer is not None:
            _save_timer.stop()
            self._save_workspace_layout()
        # T-1004：多轨态退出（停播放器 + 释放驻留样本；幂等，早期无会话时跳过）
        self._reset_multitrack_state()
        # 保存窗口大小（设置写入失败不得阻断退出——macOS 权限拒绝时曾崩溃）
        self.controller.settings.window_width = self.width()
        self.controller.settings.window_height = self.height()
        try:
            self.controller.save_settings()
        except Exception:
            pass

        # T-1040：任务中心两态补写（末次状态留盘；静默不阻断退出）
        self._save_task_center_state()

        # 停止录音（录音中关窗：停止并落盘临时 WAV，防止数据丢失与设备泄漏）
        try:
            rec = self.controller.recorder
            if rec is not None and (rec.is_recording() or rec.is_paused()):
                merged = rec.stop()
                if merged is not None and len(merged) > 0:
                    import tempfile
                    import time as _time

                    from acouscope.audio.recorder import save_audio_file

                    tmp_path = Path(tempfile.gettempdir()) / (
                        f"acouscope_recording_{_time.strftime('%Y%m%d_%H%M%S')}.wav"
                    )
                    ok, msg = save_audio_file(merged, rec.get_sample_rate(), tmp_path)
                    if ok:
                        # T-1074 G3①（承 T72-06）：退出录音自动保存纳管日志（GUI stdout 不可达）
                        _log.info("退出时检测到录音未停止，已自动保存: %s", msg)
                    else:
                        _log.error("退出时录音自动保存失败: %s", msg)
        except Exception:
            pass

        # 停止播放
        try:
            self.controller.stop()
        except Exception:
            pass

        # 等待后台分析线程结束（QThread 运行中被销毁会崩溃）
        self._analysis_gen += 1  # 令所有待处理回调失效
        for worker in list(self._analysis_workers):
            if not worker.wait(3000):
                worker.terminate()
                worker.deleteLater()

        # T-1060 件2：常驻分析视图子控件统一收尾（断场景/信号/事件过滤器 +
        # 停子定时器）——**必须先于任何事件泵**（下方 task_center drain 会
        # 消费挂起投递，若子控件计时器仍在册派发即命中悬垂 slot → SIGSEGV）。
        # 幂等、绝不外抛、不改可见行为（仅收尾路径触发）。
        try:
            self._finalize_analysis_view_widgets()
        except Exception:
            pass

        # T-928：任务进度中心收尾（取消排队 + 等待/终止在跑线程）
        try:
            self.task_center.shutdown()
        except Exception:
            pass

        # T-929：内存防护巡检停止（防关窗后残留定时回调）
        try:
            timer = getattr(self, "_memguard_timer", None)
            if timer is not None:
                timer.stop()
        except Exception:
            pass

        # SOTA 模型下载线程（CB-003 G-2 非模态进度）：关窗时终止防销毁崩溃
        dl = getattr(self, "_download_worker", None)
        if dl is not None and dl.isRunning():
            dl.terminate()
            dl.wait(3000)
            dl.deleteLater()

        # T-1104 M-C′·MC-1：报告 AI 解读线程收尾（仿既有线程先例：先礼貌
        # cancel 让 provider 内 is_cancelled 收敛，wait 超时才 terminate——
        # QThread 运行中被销毁会崩溃）。
        _aiw = getattr(self, "_report_ai_worker", None)
        if _aiw is not None and _aiw.isRunning():
            _aiw.cancel()
            if not _aiw.wait(2000):
                _aiw.terminate()
                _aiw.deleteLater()

        # T-1010：右栏 AI 释图面板（右栏 tab②，每次入口新建实例）close →
        # 触发面板 closeEvent（cancel + wait worker）；左栏设置面板同理
        # （引擎升级线程收尾）。getattr 守卫：未打开过时安全无操作。
        _ai = getattr(self, "_ai_panel", None)
        if _ai is not None:
            try:
                _ai.close()
            except RuntimeError:
                pass
        _sp = getattr(self, "_settings_panel", None)
        if _sp is not None:
            try:
                _sp.close()
            except RuntimeError:
                pass

        # T-1022 §9.1「关闭即停」：显式停止两个受管 AI 引擎（内置 llama-server /
        # 内置 Ollama），确保退出后无残余子进程、无监听端口、内存释放。
        # stop() 本身幂等且绝不抛（atexit 双保险仍在，见两个 runtime 模块）。
        # 语义边界：「卸载模型」= 停进程释放内存，**不删除**已下载的模型文件
        # （删除是用户在 设置→AI 里显式点「删除模型文件」的另一个动作）。
        for _kind in ("llama", "ollama"):
            try:
                if _kind == "llama":
                    from acouscope.ai.llama_runtime import (
                        get_runtime as _get_llama,
                    )
                    _rt = _get_llama()
                else:
                    from acouscope.ai.ollama_runtime import (
                        get_runtime as _get_ollama,
                    )
                    _rt = _get_ollama()
                _rt.stop()
            except Exception:
                pass

        # T-322: 正常退出 → 清理 autosave 快照 + 写干净标志（异常恢复闭环）
        try:
            self._clean_exit_autosave()
        except Exception:
            pass

        super().closeEvent(event)
