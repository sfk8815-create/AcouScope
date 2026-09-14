# SPDX-License-Identifier: GPL-3.0-only
"""T-929 内存防护与防崩（memguard）回归测试（离屏）。

覆盖：§1 检测两分支 + 全失败静默；§2 阈值判定与 Settings 钳位口径一致；
§3 白名单卸载 + 重建等价；§4 多轨压力序列只读复用 LRU；§5 兜底持续/限频；
UI 侧四类预检挂点 + 非模态提示通道（禁 QDialog）。

纪律：可用内存相关量一律 monkeypatch / 宽松记读，禁对环境相关量写脆断言；
不触真实用户配置（`tests/conftest.py` 已统一隔离）；不调用窗口 show()。
"""

import inspect
import sys
import types

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QDialog

from acouscope.system import memguard
from acouscope.utils.config import Settings

import acouscope.ui.main_window as mw_module
from acouscope.ui.widgets import task_center as tc_module

_SR = 8000


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """构造主窗（不 show）；HOME→tmp 防污染真实用户数据目录。"""

    monkeypatch.setenv("HOME", str(tmp_path))
    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow

    app_controller = AppController()
    win = MainWindow(app_controller)
    yield win
    try:
        win.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# §1 检测（两分支 + 全失败静默）
# ---------------------------------------------------------------------------

def test_available_memory_prefers_psutil(monkeypatch):
    monkeypatch.setattr(memguard, "_available_via_psutil", lambda: 1234.5)
    monkeypatch.setattr(memguard, "_available_native", lambda: 4321.0)
    assert memguard.available_memory_mb() == 1234.5


def test_available_memory_falls_back_to_native(monkeypatch):
    monkeypatch.setattr(memguard, "_available_via_psutil", lambda: None)
    monkeypatch.setattr(memguard, "_available_native", lambda: 640.0)
    assert memguard.available_memory_mb() == 640.0


def test_available_memory_all_probes_fail_returns_none(monkeypatch):
    monkeypatch.setattr(memguard, "_available_via_psutil", lambda: None)
    monkeypatch.setattr(memguard, "_available_native", lambda: None)
    assert memguard.available_memory_mb() is None


def test_detection_failure_is_silent(monkeypatch):
    def boom():
        raise OSError("probe exploded")

    monkeypatch.setattr(memguard, "_available_via_psutil", boom)
    monkeypatch.setattr(memguard, "_available_native", boom)
    assert memguard.available_memory_mb() is None  # 不抛


def test_psutil_branch_absent_is_silent(monkeypatch):
    """未安装 psutil（本机实际命中的分支）→ None，不抛、不新增硬依赖。"""
    monkeypatch.setitem(sys.modules, "psutil", None)
    assert memguard._available_via_psutil() is None


def test_native_macos_probe_is_read_only_or_none():
    """本机（darwin）免依赖分支实测：浮点值或 None，且不得抛（宽松记读，非脆断言）。"""
    if sys.platform != "darwin":
        pytest.skip("macOS 专用分支")
    value = memguard._available_macos()
    assert value is None or (isinstance(value, float) and value > 0.0)


# ---------------------------------------------------------------------------
# §2 阈值 / 预检（与 Settings 钳位同口径）
# ---------------------------------------------------------------------------

def test_module_constants_match_settings_defaults():
    settings = Settings()
    assert settings.memguard_low_threshold_mb == memguard.MEMGUARD_LOW_THRESHOLD_MB
    assert (
        settings.memguard_critical_threshold_mb
        == memguard.MEMGUARD_CRITICAL_THRESHOLD_MB
    )
    assert settings.memguard_model_idle_minutes == memguard.MEMGUARD_MODEL_IDLE_MINUTES
    assert memguard.thresholds_from_settings(settings) == (
        memguard.MEMGUARD_LOW_THRESHOLD_MB,
        memguard.MEMGUARD_CRITICAL_THRESHOLD_MB,
        memguard.MEMGUARD_MODEL_IDLE_MINUTES,
    )


def test_settings_load_clamps_illegal_values(tmp_path):
    settings = Settings()
    settings.memguard_low_threshold_mb = "bad"        # 非法 → 默认
    settings.memguard_critical_threshold_mb = 1       # 越界（<64）→ 默认
    settings.memguard_model_idle_minutes = 9999       # 越界（>240）→ 默认
    settings.reference_hz = 440.0
    path = tmp_path / "settings.json"
    settings.save(path)
    loaded = Settings.load(path)
    assert loaded.memguard_low_threshold_mb == memguard.MEMGUARD_LOW_THRESHOLD_MB
    assert (
        loaded.memguard_critical_threshold_mb
        == memguard.MEMGUARD_CRITICAL_THRESHOLD_MB
    )
    assert loaded.memguard_model_idle_minutes == memguard.MEMGUARD_MODEL_IDLE_MINUTES


def test_memory_status_thresholds():
    assert memguard.memory_status(None) == memguard.STATUS_OK      # 检测失败 → 静默
    assert memguard.memory_status(100) == memguard.STATUS_CRITICAL
    assert memguard.memory_status(300) == memguard.STATUS_LOW
    assert memguard.memory_status(900) == memguard.STATUS_OK
    assert memguard.memory_status(200, critical_mb=200) == memguard.STATUS_LOW


def test_preflight_low_and_ok_decisions():
    low = memguard.preflight(Settings(), available_mb=300)
    assert low.is_low and low.status == memguard.STATUS_LOW
    assert low.low_mb == memguard.MEMGUARD_LOW_THRESHOLD_MB
    ok = memguard.preflight(Settings(), available_mb=4096)
    assert not ok.is_low and ok.status == memguard.STATUS_OK


def test_preflight_silent_when_detection_fails(monkeypatch):
    def boom():
        raise RuntimeError("no memory info")

    monkeypatch.setattr(memguard, "available_memory_mb", boom)
    result = memguard.preflight(Settings())
    assert result.available_mb is None and not result.is_low


# ---------------------------------------------------------------------------
# §3 模型闲置卸载（白名单 + 重建等价）
# ---------------------------------------------------------------------------

def _fake_backend_module(monkeypatch, name="acouscope_t929_fake_backend"):
    """装一个「双重检查懒建」的假后端（同真后端加载路径形态）。"""
    module = types.ModuleType(name)

    class FakeBackend:
        _session = None
        _input_name = None
        _output_name = None
        _mel_extractor = None
        builds = 0

        def __init__(self):
            self._ensure_model()

        def _ensure_model(self):
            if FakeBackend._session is not None:
                return
            FakeBackend.builds += 1
            FakeBackend._session = {"gain": 2.0}
            FakeBackend._input_name = "input"
            FakeBackend._output_name = "output"
            FakeBackend._mel_extractor = object()

        def detect(self, signal):
            self._ensure_model()
            return [value * FakeBackend._session["gain"] for value in signal]

    module.FakeBackend = FakeBackend
    monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(
        memguard,
        "SESSION_WHITELIST",
        (
            (
                "Fake",
                name,
                "FakeBackend",
                ("_session", "_input_name", "_output_name", "_mel_extractor"),
            ),
        ),
    )
    return FakeBackend


def test_session_whitelist_matches_real_backend_attrs():
    """白名单逐名对齐真实后端类属性（只读校验，不改后端文件）。"""
    import importlib

    for name, module_path, class_name, attrs in memguard.SESSION_WHITELIST:
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        assert cls is not None, name
        for attr in attrs:
            assert hasattr(cls, attr), f"{class_name}.{attr}"


def test_free_model_sessions_resets_whitelist(monkeypatch):
    backend = _fake_backend_module(monkeypatch)
    backend()
    assert backend._session is not None and backend._mel_extractor is not None
    assert memguard.loaded_model_names() == ["Fake"]
    assert memguard.free_model_sessions() == ["Fake"]
    assert backend._session is None
    assert backend._input_name is None
    assert backend._output_name is None
    assert backend._mel_extractor is None
    assert memguard.loaded_model_names() == []


def test_unload_then_rebuild_is_equivalent(monkeypatch):
    """卸载后再次构造/detect：重建成功且结果与首次逐值等价（调用次数断言）。"""
    backend = _fake_backend_module(monkeypatch)
    first = backend()
    signal = [1.0, 2.0, 3.0]
    first_result = first.detect(signal)
    assert backend.builds == 1

    assert memguard.free_model_sessions() == ["Fake"]
    rebuilt = backend()
    second_result = rebuilt.detect(signal)
    assert backend.builds == 2                    # 确已重建
    assert second_result == first_result          # 结果等价


def test_free_model_sessions_only_named(monkeypatch):
    backend = _fake_backend_module(monkeypatch)
    backend()
    assert memguard.free_model_sessions(["Other"]) == []   # 白名单外名字 → 不动
    assert backend._session is not None
    assert memguard.free_model_sessions(["Fake"]) == ["Fake"]


def test_model_idle_unloader_waits_full_idle_window(monkeypatch):
    backend = _fake_backend_module(monkeypatch)
    backend()
    unloader = memguard.ModelIdleUnloader(idle_minutes=10)
    assert unloader.poll(at=0.0) == []             # 首次发现 → 起计时，不立即卸载
    assert unloader.poll(at=300.0) == []           # 5 分钟 < 10 分钟
    assert backend._session is not None
    assert unloader.poll(at=601.0) == ["Fake"]     # 满 10 分钟 → 卸载
    assert backend._session is None


def test_model_idle_unloader_skips_while_busy(monkeypatch):
    backend = _fake_backend_module(monkeypatch)
    backend()
    unloader = memguard.ModelIdleUnloader(idle_minutes=10)
    unloader.poll(at=0.0)
    assert unloader.poll(busy=True, at=9999.0) == []
    assert backend._session is not None            # 分析在跑 → 保结果不变


def test_model_idle_unloader_note_restarts_timer(monkeypatch):
    backend = _fake_backend_module(monkeypatch)
    backend()
    unloader = memguard.ModelIdleUnloader(idle_minutes=10)
    unloader.poll(at=0.0)
    unloader.note("Fake", at=590.0)
    assert unloader.poll(at=601.0) == []           # 计时被重置
    assert unloader.poll(at=1200.0) == ["Fake"]


# ---------------------------------------------------------------------------
# §4 多轨协同（只读复用既有 LRU）
# ---------------------------------------------------------------------------

class _FakeSession:
    def __init__(self, released=("t2",)):
        self._released = list(released)
        self.calls = 0

    def unload_inactive(self, keep=()):
        self.calls += 1
        return list(self._released)


def test_release_inactive_tracks_reuses_lru_interface():
    session = _FakeSession()
    assert memguard.release_inactive_tracks(session) == ["t2"]
    assert session.calls == 1
    assert memguard.release_inactive_tracks(None) == []


def test_release_inactive_tracks_silent_on_error():
    class Boom:
        def unload_inactive(self, keep=()):
            raise RuntimeError("boom")

    assert memguard.release_inactive_tracks(Boom()) == []


def test_relieve_pressure_order_tracks_then_models(monkeypatch):
    order = []
    session = _FakeSession()
    monkeypatch.setattr(
        memguard, "free_model_sessions",
        lambda names=None: order.append("models") or ["Fake"],
    )
    monkeypatch.setattr(
        memguard, "release_inactive_tracks",
        lambda s: order.append("tracks") or ["t2"],
    )
    result = memguard.relieve_pressure(session)
    assert order == ["tracks", "models"]           # 先卸轨 buffer，后卸模型 session
    assert result == {"tracks": ["t2"], "models": ["Fake"]}
    assert memguard.relieve_pressure(None, unload_models=False)["models"] == []


# ---------------------------------------------------------------------------
# §5 压力兜底（持续 + 限频 + 静默）
# ---------------------------------------------------------------------------

def test_pressure_monitor_requires_sustained_low_memory():
    monitor = memguard.MemoryPressureMonitor(critical_mb=200, sample_fn=lambda: 100.0)
    assert monitor.poll(at=0.0) is False           # 首次低于阈值 → 起计时
    assert monitor.poll(at=4.0) is False           # 未满 5s
    assert monitor.poll(at=6.0) is True            # 持续 > 5s → 触发一次


def test_pressure_monitor_rate_limited_to_five_minutes():
    monitor = memguard.MemoryPressureMonitor(critical_mb=200, sample_fn=lambda: 100.0)
    assert monitor.poll(at=0.0) is False
    assert monitor.poll(at=6.0) is True
    assert monitor.poll(at=100.0) is False         # < 5 分钟 → 不重复触发
    assert monitor.poll(at=306.0) is True          # 满 5 分钟 → 可再次触发


def test_pressure_monitor_resets_when_recovered():
    samples = iter([100.0, 900.0, 100.0])
    monitor = memguard.MemoryPressureMonitor(critical_mb=200, sample_fn=lambda: next(samples))
    assert monitor.poll(at=0.0) is False
    assert monitor.poll(at=10.0) is False          # 恢复 → 计时清零
    assert monitor.poll(at=11.0) is False          # 重新起计时（未满 5s）


def test_pressure_monitor_silent_on_sample_failure():
    def boom():
        raise OSError("no info")

    monitor = memguard.MemoryPressureMonitor(critical_mb=200, sample_fn=boom)
    assert monitor.poll(at=0.0) is False
    assert monitor.poll(at=100.0) is False


# ---------------------------------------------------------------------------
# 静态纪律：零点 QDialog / 无第二套锁 / 四类预检挂点 / 提示走非模态通道
# ---------------------------------------------------------------------------

def test_memguard_has_no_lock_or_threading():
    """AST 口径：本模块不引入 threading / 不构造任何锁（K8 禁重复造锁）。"""
    import ast

    tree = ast.parse(inspect.getsource(memguard))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not any("threading" in name for name in imported)
    lock_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", "") in {"Lock", "RLock", "Semaphore"}
    ]
    assert lock_calls == []


def test_no_second_scheduler_and_limits_consistent():
    """限流沿用 T-928 并发策略（禁重复造锁/队列）。"""
    assert Settings().task_center_max_concurrency == tc_module.TASK_CENTER_MAX_CONCURRENCY
    assert Settings().task_center_queue_limit == tc_module.TASK_CENTER_QUEUE_LIMIT


def test_main_window_has_four_preflight_hooks():
    source = inspect.getsource(mw_module)
    kinds = ["batch", "analysis", "download", "multitrack"]
    for kind in kinds:
        assert f'self._memguard_preflight("{kind}")' in source, kind
    assert source.count("self._memguard_preflight(") == len(kinds)  # 恰 4 处调用点
    assert "def _memguard_preflight(self, kind: str)" in source


def test_fallback_reuses_autosave_path_without_qdialog():
    source = inspect.getsource(mw_module.MainWindow._memguard_fallback)
    assert "self._on_autosave_tick()" in source     # 只读复用 T-322 写快照路径
    assert "show_toast" in source
    assert "QDialog" not in source


def test_i18n_memguard_keys_three_languages():
    from acouscope.i18n import _STRINGS

    for key in (
        "memguard.low",
        "memguard.continue",
        "memguard.pressure_warning",
        "memguard.prompt_title",
    ):
        entry = _STRINGS[key]
        for lang in ("en_US", "zh_CN", "zh_TW"):
            assert entry[lang].strip(), f"{key}/{lang}"
    assert "{mb}" in _STRINGS["memguard.low"]["zh_CN"]
    assert "{threshold}" in _STRINGS["memguard.low"]["zh_CN"]


# ---------------------------------------------------------------------------
# UI 接线：预检提示走非模态通道 + 零 QDialog + 兜底触发一次 autosave
# ---------------------------------------------------------------------------

def test_preflight_prompt_is_non_modal_and_continues(window, monkeypatch):
    toasts = []
    monkeypatch.setattr(
        mw_module, "show_toast",
        lambda parent, msg, level="info", duration=3500: toasts.append((msg, level)),
    )
    monkeypatch.setattr(
        memguard, "preflight",
        lambda settings=None, available_mb=None: memguard.PreflightResult(
            memguard.STATUS_LOW, 300.0, 512, 200
        ),
    )
    assert window._memguard_preflight("analysis") is True      # 「仍继续」= 默认继续
    assert len(toasts) == 1 and toasts[0][1] == "warning"
    # 「取消」承载于任务中心条目动作（非模态内联；同一时刻至多一条提示条目）
    assert len(window._memguard_prompt_ids) == 1
    entry = window.task_center._entries[window._memguard_prompt_ids[0]]
    assert entry.cancellable is True
    assert not window.findChildren(QDialog)                    # 禁 QDialog/模态


def test_preflight_silent_when_memory_ok(window, monkeypatch):
    toasts = []
    monkeypatch.setattr(
        mw_module, "show_toast",
        lambda parent, msg, level="info", duration=3500: toasts.append(msg),
    )
    monkeypatch.setattr(memguard, "available_memory_mb", lambda: 8192.0)
    before = list(window._memguard_prompt_ids)
    assert window._memguard_preflight("batch") is True
    assert toasts == []
    assert window._memguard_prompt_ids == before


def test_pressure_fallback_triggers_autosave_once_and_warns(window, monkeypatch):
    calls = []
    toasts = []
    monkeypatch.setattr(window, "_on_autosave_tick", lambda: calls.append(1))
    monkeypatch.setattr(
        mw_module, "show_toast",
        lambda parent, msg, level="info", duration=3500: toasts.append(level),
    )
    window._memguard_fallback()
    assert calls == [1]                                        # 触发一次 autosave
    assert toasts == ["warning"]                               # 非模态警告
    assert not window.findChildren(QDialog)


def test_memguard_tick_reports_busy_and_fires_fallback(window, monkeypatch):
    """巡检：分析在跑 → 卸载器收到 busy=True；压力命中 → 走兜底（状态均 mock）。"""
    seen = {"busy": None, "fb": 0}

    def _poll(busy=False, at=None):
        seen["busy"] = busy
        return []

    monkeypatch.setattr(window._memguard_unloader, "poll", _poll)
    monkeypatch.setattr(window._memguard_pressure, "poll", lambda at=None: True)
    monkeypatch.setattr(
        window, "_memguard_fallback", lambda: seen.__setitem__("fb", seen["fb"] + 1)
    )
    monkeypatch.setattr(window.task_center, "is_busy", lambda: True)
    window._on_memguard_tick()
    assert seen["busy"] is True       # 在跑 → 不卸载（保分析结果）
    assert seen["fb"] == 1            # 压力命中 → 兜底一次


# ---------------------------------------------------------------------------
# T-1039 压力兜底内的多轨压力序列接入（先轨后模型；R2 保守口径）
# ---------------------------------------------------------------------------

def _patch_relieve(monkeypatch, calls, *, boom=False):
    """拦截 memguard.relieve_pressure 记录调用实参（可令其抛异常）。"""

    def _relieve(session=None, *, unload_models=True):
        calls.append({"session": session, "unload_models": unload_models})
        if boom:
            raise RuntimeError("relieve boom")
        return {"tracks": [], "models": []}

    monkeypatch.setattr(memguard, "relieve_pressure", _relieve)


def test_fallback_releases_pressure_with_models_when_idle(window, monkeypatch):
    """idle（无任务在跑）→ 完整序列：unload_models=True。"""
    calls = []
    _patch_relieve(monkeypatch, calls)
    monkeypatch.setattr(window.task_center, "is_busy", lambda: False)
    window._memguard_fallback()
    assert len(calls) == 1
    assert calls[0]["session"] is window.multitrack_session
    assert calls[0]["unload_models"] is True


def test_fallback_releases_tracks_only_when_busy(window, monkeypatch):
    """busy（分析在跑）→ 只卸轨：unload_models=False。"""
    calls = []
    _patch_relieve(monkeypatch, calls)
    monkeypatch.setattr(window.task_center, "is_busy", lambda: True)
    window._memguard_fallback()
    assert len(calls) == 1
    assert calls[0]["session"] is window.multitrack_session
    assert calls[0]["unload_models"] is False


def test_fallback_busy_probe_failure_is_conservative(window, monkeypatch):
    """busy 取值失败 → 一律按 True 保守：禁卸模型。"""
    calls = []
    _patch_relieve(monkeypatch, calls)

    def _boom():
        raise RuntimeError("probe boom")

    monkeypatch.setattr(window.task_center, "is_busy", _boom)
    window._memguard_fallback()
    assert len(calls) == 1
    assert calls[0]["unload_models"] is False


def test_fallback_silent_when_relieve_raises(window, monkeypatch):
    """释放序列抛异常 → 全静默，兜底仍完成 autosave 一次 + toast 一次。"""
    calls = []
    _patch_relieve(monkeypatch, calls, boom=True)
    saved = []
    toasts = []
    monkeypatch.setattr(window, "_on_autosave_tick", lambda: saved.append(1))
    monkeypatch.setattr(
        mw_module, "show_toast",
        lambda parent, msg, level="info", duration=3500: toasts.append(level),
    )
    window._memguard_fallback()
    assert len(calls) == 1
    assert saved == [1]
    assert toasts == ["warning"]
    assert not window.findChildren(QDialog)


def test_fallback_pressure_sequence_static_guard():
    """静态守卫：释放序列恰 1 处调用点；禁新增 QTimer/QThread/QDialog。"""
    source = inspect.getsource(mw_module.MainWindow._memguard_fallback)
    assert source.count("relieve_pressure(") == 1
    assert "unload_models=" in source
    for forbidden in ("QTimer(", "QThread(", "QDialog"):
        assert forbidden not in source
