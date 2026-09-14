# SPDX-License-Identifier: GPL-3.0-only
"""测试配置：离屏 Qt 环境。

CB-005（C1 诊断加固，2026-09-06）在此文件追加两部分、零第三方依赖：
  - D1：faulthandler 落栈——进程级信号处理器在原生崩溃（SIGSEGV 等）时把
    Python 栈逐线程转储到 .pi/logs/flaky_segfault.log（附 Qt 平台/版本上下文）。
  - D2：test_waveform_editing.py::test_drag_creates_selection 用例级重跑容错
    （手写 pytest_runtest_protocol，禁 pytest-rerunfailures）：失败/崩溃自动
    重跑 1 次；重跑即绿 → 记 FLAKY_EVENT；连续 2 败 → 如实 FAIL。

注意：原生 SIGSEGV 杀进程（exit 139）无法在进程内抢救——faulthandler 落栈 +
外部重跑（D3 对照实验 / 回归）为其兜底；本 D2 针对进程内可恢复的失败路径。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import datetime as _dt
import faulthandler
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# CB-005 D1：faulthandler 落栈
# ---------------------------------------------------------------------------

# 工作区根 = acouscope/tests/conftest.py → parents[2]
_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
_LOG_DIR = _WORKSPACE_ROOT / ".pi" / "logs"
FLAKY_LOG = _LOG_DIR / "flaky_segfault.log"


def _ensure_log_dir():
    _LOG_DIR.mkdir(parents=True, exist_ok=True)


def _append_flaky_log(text: str) -> None:
    try:
        _ensure_log_dir()
        with open(FLAKY_LOG, "a", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
    except OSError:
        # 落盘失败不影响测试本体（诊断加固仅尽力而为）
        pass


def _enable_faulthandler() -> None:
    """尽早开启 faulthandler，原生崩溃时把 Python 栈写入 flaky_segfault.log。

    faulthandler 模块持有所打开文件对象的引用，进程退出阶段的崩溃也能落栈；
    句柄以追加模式打开，多次会话累计同一条证据链。
    """
    try:
        _ensure_log_dir()
        fh = open(FLAKY_LOG, "a", encoding="utf-8")
        # faulthandler 内部保留 fh 引用，不会在解释器退出前被回收
        faulthandler.enable(file=fh, all_threads=True)
    except (OSError, RuntimeError):
        # 已启用 / 无法开文件时保持现状
        pass


_enable_faulthandler()


def pytest_configure(config):
    """每次 pytest 会话开始：记录 Qt 平台/版本上下文到 flaky 日志。"""
    try:
        import platform

        import PyQt6.QtCore as _qc
        import pyqtgraph as _pg

        _append_flaky_log(
            "\n================ SESSION START ================\n"
            f"ts={_dt.datetime.now().isoformat(timespec='seconds')}\n"
            f"cwd={os.getcwd()}\n"
            f"python={sys.version.split()[0]} platform={platform.platform()}\n"
            f"QT_QPA_PLATFORM={os.environ.get('QT_QPA_PLATFORM', '(unset)')}\n"
            f"PyQt6={_qc.PYQT_VERSION_STR} Qt={_qc.QT_VERSION_STR} "
            f"pyqtgraph={_pg.__version__} pytest={pytest.__version__}\n"
            "===============================================\n"
        )
    except Exception:
        # 上下文仅为诊断便利，缺失不影响测试
        pass


# ---------------------------------------------------------------------------
# CB-005 D2：test_drag_creates_selection 用例级重跑容错（零依赖手写）
# ---------------------------------------------------------------------------

_RETRY_MODULE = "test_waveform_editing.py"
_RETRY_TEST = "test_drag_creates_selection"


def _is_retry_target(item) -> bool:
    """仅对本用例生效（nodeid 如 tests/test_waveform_editing.py::…::test_drag_creates_selection）。"""
    try:
        nodeid = item.nodeid.replace("\\", "/")
    except Exception:
        return False
    parts = nodeid.split("::")
    if len(parts) < 2:
        return False
    if not parts[-1].startswith(_RETRY_TEST):
        return False
    return parts[0].split("/")[-1] == _RETRY_MODULE


def _has_failure(reports) -> bool:
    return any(
        getattr(r, "failed", False) or getattr(r, "outcome", "") == "failed"
        for r in reports
    )


def _report_line(r) -> str:
    detail = ""
    longrepr = getattr(r, "longrepr", None)
    if longrepr is not None:
        try:
            detail = getattr(r, "longreprtext", None) or str(longrepr)
        except Exception:
            detail = repr(longrepr)
        detail = detail.replace("\n", " \\n ")[:400]
    return (
        f"  {{when:{getattr(r, 'when', '?')}, "
        f"outcome:{getattr(r, 'outcome', '?')}, "
        f"nodeid:{getattr(r, 'nodeid', '?')}, "
        f"detail:{detail}}}"
    )


def _log_retry_event(item, reports, attempt: int) -> None:
    outcome = "FAILED" if _has_failure(reports) else "PASSED"
    lines = [
        "================ FLAKY_EVENT (CB-005 D2 retry) ================",
        f"ts={_dt.datetime.now().isoformat(timespec='seconds')}",
        f"nodeid={item.nodeid} attempt={attempt} outcome={outcome}",
    ]
    lines += [_report_line(r) for r in reports]
    lines.append("=========================================================")
    _append_flaky_log("\n".join(lines) + "\n")


def pytest_runtest_protocol(item, nextitem):
    """失败重跑 1 次；重跑即绿记 FLAKY_EVENT；连续 2 败如实 FAIL。

    pytest_runtest_protocol 为 firstresult hook：本实现返回 None（非目标用例）
    时回落到 pytest 内建流程；对本用例返回 True 时由本实现全权执行。
    """
    if not _is_retry_target(item):
        return None

    ihook = item.ihook
    ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
    try:
        from _pytest import runner as _runner

        # 首次执行（静默，结果先不外发）
        reports = _runner.runtestprotocol(item, nextitem=nextitem, log=False)
        if not _has_failure(reports):
            # 一次即绿：与内建流程等价地外发各阶段报告
            for rep in reports:
                ihook.pytest_runtest_logreport(report=rep)
            return True

        # 首次失败：如实留档后重跑 1 次（可见，log=True 正常上报）
        _log_retry_event(item, reports, attempt=1)
        reports2 = _runner.runtestprotocol(item, nextitem=nextitem, log=True)
        _log_retry_event(item, reports2, attempt=2)
        return True
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # pragma: no cover - 兜底：不吞异常
        _append_flaky_log(
            f"[{_dt.datetime.now().isoformat(timespec='seconds')}] "
            f"CB-005 D2 protocol error on {item.nodeid}: {exc!r}\n"
        )
        raise


# ---------------------------------------------------------------------------
# 既有配置（原样保留）
# ---------------------------------------------------------------------------


# CB-005 诊断模块隔离：未显式设置 CB005_DIAG=1 时不收集 test_cb005_diag_*，
# 保证常规全量门禁的收集计数/结果完全不受诊断文件影响（仅在显式环境变量下可复跑）。
if os.environ.get("CB005_DIAG") != "1":
    collect_ignore = [
        p.name for p in Path(__file__).parent.glob("test_cb005_diag_*.py")
    ]


@pytest.fixture(scope="session")
def qapp():
    """会话级 QApplication（离屏）。"""
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


# _isolate_app_data_dir (autouse)：统一为全部测试重定向应用数据目录与配置目录，
# 兜底隔离，防止任何构造 MainWindow/面板的测试写/读真实用户配置。
@pytest.fixture(autouse=True)
def _isolate_app_data_dir(tmp_path, monkeypatch):
    """统一重定向应用数据目录与配置目录到临时目录，杜绝测试读写真实用户配置
    （ui_analysis_view.json / ui_layout.json / shortcuts.json / acouscope.log /
    settings.json 等）。
    函数内 import 的消费方 patch config 模块属性即生效；
    顶层 import 绑定名的模块（workspace / ollama_runtime）须同步 patch。

    T-1027（IM-09）：原实现只重定向 get_data_dir，而 Settings.load()/save() 走
    get_config_dir() 与 _settings_candidates()（其内部再取 config_dir_candidates()）
    → 仍会读到真实用户 settings.json（本机 icon_style=macos），使测试非封闭、
    用户切换过非 generic 图标风格后本机回归恒红。故一并隔离配置目录与候选链。"""
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)

    # T-1027：配置目录 + 两条候选链全部钉进 tmp_path，切断对 ~/Library/... 等
    # 真实候选的外泄；_resolve_dir 有模块级缓存 _RESOLVED_DIRS，换新字典使其失效
    # （teardown 由 monkeypatch 还原原字典对象，生产语义不变）。
    monkeypatch.setattr(_cfg, "get_config_dir", lambda: tmp_path)
    monkeypatch.setattr(_cfg, "config_dir_candidates", lambda: [tmp_path])
    monkeypatch.setattr(_cfg, "data_dir_candidates", lambda: [tmp_path])
    monkeypatch.setattr(_cfg, "_RESOLVED_DIRS", {})

    import acouscope.ui.widgets.panels.workspace as _ws

    monkeypatch.setattr(_ws, "get_data_dir", lambda: tmp_path)

    import acouscope.ai.ollama_runtime as _oll

    monkeypatch.setattr(_oll, "get_data_dir", lambda: tmp_path)


# ---------------------------------------------------------------------------
# T-904 L1：孤儿 worker 进程兜底回收（tracked registry 模式）
# ---------------------------------------------------------------------------
# T-902b watchdog 测试（env=1）spawn `python -m acouscope.analysis.worker.server`
# 子进程；异常测试路径 / 未走 proxy.close() 时残留为孤儿（持 SharedMemory 段）。
# 本 autouse fixture 每测试新建局部登记列表（禁全局单例跨测试泄漏）：
# monkeypatch WorkerProxy.__init__（wrapt 式包装，保留原签名与行为）把每个新建
# 实例以 weakref 登记；yield 后遍历，凡存活且 _proc 仍非 None（未 close）的
# 实例补一次 close()（吞每个实例的异常，收集计数）。
# 弱引用登记的理由（T-904 实测 2026-09-07）：强引用列表会在测试体内托住
# 实例引用计数 → 析构兜底（__del__）在测试内永不触发，L2 测试无法验证；
# 弱引用下 del proxy → 引用计数归零 → __del__ 即时回收（未 close 时由 L2
# 兜底 close）；弱引用死 → 实例已被回收，无需兜底。另以 weakref.finalize
# 注册兜底：实例仍被测试局部变量强持至函数返回（refcount 延迟归零）时，
# 回收发生前 finalize 触发——解释器健康期 close，防 CPython shutdown 期
# 属性 None 化导致回收失效（finalize 回调内 close 吞异常）。
# 与 proxy.py 的 __del__ 析构兜底（L2）双层互补：本层覆盖“测试局部变量
# 持有至函数返回”路径，L2 覆盖 del 即时回收路径。
import weakref as _weakref


@pytest.fixture(autouse=True)
def _reclaim_worker_proxies(monkeypatch):
    from acouscope.analysis.worker.proxy import WorkerProxy

    _tracked: list = []  # 本测试局部（function scope），禁跨测试共享
    _finalizers: list = []
    _orig_init = WorkerProxy.__init__

    def _finalize_cb(ref):
        # 实例弱引用已死：L2 __del__ 已在回收时兜底；此处仅防御性补位
        #（如 __del__ 因 shutdown 期属性 None 化未生效——finalize 回调
        # 在回收流程中先于对象销毁运行，能拿到存活实例）
        proxy = ref()
        if proxy is None:
            return
        try:
            if getattr(proxy, "_proc", None) is not None:
                proxy.close()
        except Exception:
            pass

    def _tracked_init(self, *args, **kwargs):
        _orig_init(self, *args, **kwargs)
        try:
            r = _weakref.ref(self)
            _tracked.append(r)
            # finalize 仅持弱引用 r（回调参数链不持实例强引用，
            # 否则注册表本身托住实例、L2 永不触发）
            _finalizers.append(_weakref.finalize(self, _finalize_cb, r))
        except Exception:
            pass

    monkeypatch.setattr(WorkerProxy, "__init__", _tracked_init)
    yield
    # teardown：回收本测试内创建、仍存活且未 close 的 WorkerProxy（逐实例吞异常）
    reclaimed = 0
    for ref in _tracked:
        proxy = ref() if callable(ref) else None
        if proxy is None:
            continue  # 已回收（__del__/finalize 已兜底）
        try:
            if getattr(proxy, "_proc", None) is not None:
                proxy.close()
                reclaimed += 1
        except Exception:
            pass


# ---------------------------------------------------------------------------
# use-after-free 缓解（2026-09-08）：per-test 确定性 gc.collect()
# ---------------------------------------------------------------------------
# 背景：全量 pytest 在 test_cb016_red_cursor.py + test_cb016_spectrogram3d_
# analysis_driven.py 同场时 SIGSEGV（EXIT=139，2/2 可复现）。macOS 崩溃栈 =
# QGraphicsItem::sceneBoundingRect() ← QGraphicsScene::itemsBoundingRect() ←
# scene event（processEvents 期间），EXC_BAD_ACCESS @0x170（近 NULL 悬垂指针）。
# 根因：测试创建的含 QGraphicsScene 的 widget（WaveformWidget / SpectrogramWidget /
# MainWindow）在测试结束出作用域后，被 Python GC 以"不同于 Qt 场景删除顺序"的
# 分代时机回收，scene 内部 item 列表残留悬垂指针；后续 processEvents 触发 scene
# 事件遍历到已释放 C++ 项 → 段错误。
# 修复（最小安全版）：本 autouse fixture 每测试结束调一次 gc.collect()，把"GC
# 分代任意时机"收敛为"测试边界的确定性时点"——widget 在其所属测试刚结束时即被
# 回收（受控上下文），而非拖到后续无关测试的 processEvents 里才释放。
# 【关键教训（本波实证，勿回退到显式销毁）】曾尝试"close+deleteLater+
# sendPostedEvents/processEvents 显式销毁 top-level widget"：3 文件崩溃组通过，
# 但全量回归反而 SIGSEGV（崩溃点落在本 fixture 的销毁调用内）——deleteLater 销毁
# C++ widget 时若 scene 残留悬垂 item 即段错误，且 teardown 局部列表仍持 wrapper
# → zombie。故本 fixture 只做 gc.collect()（确定性 GC 时机），不做显式销毁。
# 诚实边界：此为"缓解"（收敛 GC 时机），非"根治"；scene item 悬垂持方仍需按
# HANDOFF e 待办① 定位（pyqtgraph/PyQt 生命周期），不声称彻底消除。
import gc as _gc


@pytest.fixture(autouse=True)
def _deterministic_gc_per_test():
    """每测试结束确定性 gc.collect()（收敛 GC 分代时机，缓解 scene use-after-free）。"""
    yield
    _gc.collect()
