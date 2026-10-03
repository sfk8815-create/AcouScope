# SPDX-License-Identifier: GPL-3.0-only
"""T-1020：AI 释图链路真机阻断修复 + 顶部三档下拉（离屏；临时 HOME，禁触网）。

覆盖需求说明 Step 6 必测六项：
① 端到端落盘：设置-AI 改字段 → `_on_settings_applied()` → ai_config.json 真的
   生成且**逐键等于** 面板 `ai_config()` → 重入面板读回一致（修前：死 import
   `interpreter._save_config` + `except Exception: pass` → 零文件生成）；
② 写失败路径：全候选不可写 → 返回 False / 可见反馈且**不抛异常**（禁静默）；
③ 诊断分类：429 → 文案含「限流」且**不含「（Exception）」**；本地/云端建议分流；
④ 兜底：`_switch_to_remote()` 写入 `info.base_url` + `info.default_model`；
⑤ 【D】切档：仅落盘 `ai_v2.source`（url/model/key 逐字不变）、路由随档变化、
   未配置档给「设置 → AI」引导、双向同步、窄栏模型名不截断；
⑥ 静态纪律（禁词 / hex-px / QDialog / 无主窗 show 调用）。

语言口径：断言中文文案前先切 zh_CN（i18n 默认 en_US），测试结束还原。
凭据口径：测试内 API Key 一律为占位串（禁写入任何真实 Key）。
"""

import ast
import json
import pathlib
import re
import sys

import numpy as np
import pytest

sys.path.insert(0, "src")
pytest.importorskip("PyQt6")

from acouscope.ai import interpreter
from acouscope.i18n import get_language, set_language, tr
from acouscope.ui.widgets import ai_interpret as ai

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_BANNED = "Mel" + "odyne"
_CONTEXT = "【数值上下文】测试上下文"
_PLACEHOLDER_KEY = "PLACEHOLDER-NOT-A-REAL-KEY"


@pytest.fixture(autouse=True)
def _zh_cn_language():
    """中文文案断言前置：临时切 zh_CN，用例结束还原。"""
    prev = get_language()
    set_language("zh_CN")
    yield
    set_language(prev)


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------

def _home(tmp_path) -> pathlib.Path:
    """临时 HOME（用户配置写入此下的标准位置，绝不碰真实用户配置）。"""
    return tmp_path / "home"


def _expected_cfg_path(home: pathlib.Path) -> pathlib.Path:
    """临时 HOME 下 ai_config.json 的首选候选（= data_dir_candidates()[0]）。"""
    return (home / "Library" / "Application Support" / "AcouScope"
            / "ai_config.json")


def _write_cfg(path: pathlib.Path, data: dict) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def _panel(monkeypatch, paths=None):
    """离屏面板；paths 非 None 时打桩 _config_paths（隔离真实用户配置）。"""
    if paths is not None:
        monkeypatch.setattr(ai, "_config_paths", lambda: list(paths))
    return ai.AIInterpretDialog(
        image_getter=lambda: None,
        context_getter=lambda: _CONTEXT,
        view_name_getter=lambda: "FFT 频谱",
    )


def _main_window(monkeypatch, tmp_path):
    """主窗（不 show()）；HOME / 数据目录 / 配置目录全部临时重定向。"""
    import acouscope.utils.config as _cfg

    monkeypatch.setenv("HOME", str(_home(tmp_path)))
    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(_cfg, "get_config_dir", lambda: tmp_path / "cfg")

    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 2.0)) / sr
    controller.load_from_array(0.5 * np.sin(2 * np.pi * (200 + 300 * t) * t),
                               sr)
    return MainWindow(controller)


def _toast_spy(monkeypatch):
    """收集可见反馈（show_toast 打桩；模块内为全局名查找，打桩即生效）。"""
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(ai, "show_toast",
                        lambda parent, msg, level="info": seen.append((msg, level)))
    return seen


class _StubWorker:
    """_on_run 的 worker 替身（**绝不触网**）：只需 start/messages/isRunning。"""

    def __init__(self, messages=None):
        self.messages = messages or []

    def start(self):
        pass

    def isRunning(self):
        return False

    def cancel(self):
        pass


# ----------------------------------------------------------------------
# ① 端到端落盘（设置-AI「应用」→ ai_config.json → 重入读回）
# ----------------------------------------------------------------------

def test_settings_apply_writes_ai_config_end_to_end(qapp, monkeypatch, tmp_path):
    """修前证据：应用后零文件生成（死 import + except 静默吞）；修后：真落盘。"""
    home = _home(tmp_path)
    cfg = _expected_cfg_path(home)
    win = _main_window(monkeypatch, tmp_path)
    try:
        win._activate_settings_tab()
        sp = win._settings_panel
        assert sp is not None

        sp.cmb_cloud_vendor.setCurrentIndex(
            sp.cmb_cloud_vendor.findData("custom"))
        sp.rbtn_ai_cloud.setChecked(True)
        sp.edit_cloud_url.setText("https://api.example.com/v1")
        sp.edit_cloud_model.setText("demo-vision-model")
        sp.edit_cloud_key.setText(_PLACEHOLDER_KEY)
        expected = sp.ai_config()
        assert expected["ai_v2"]["source"] == "cloud"

        assert not cfg.exists()            # 应用前：无文件
        win._on_settings_applied()         # 设置-AI「应用」

        assert cfg.exists(), "设置-AI「应用」必须真正写盘 ai_config.json"
        on_disk = json.loads(cfg.read_text(encoding="utf-8"))
        assert on_disk == expected         # 逐键等于面板 ai_config()
        assert on_disk["url"] == "https://api.example.com/v1"
        assert on_disk["model"] == "demo-vision-model"
        assert on_disk["ai_v2"]["source"] == "cloud"

        # 重入面板（新实例 = 重新读盘）→ 读回一致
        again = ai.AIInterpretDialog(
            image_getter=lambda: None,
            context_getter=lambda: _CONTEXT,
            view_name_getter=lambda: "FFT 频谱",
        )
        try:
            assert again._source == "cloud"
            assert again._current_model_name() == "demo-vision-model"
            assert again.lbl_model.toolTip() == tr(
                "ai_panel.model_prefix").format(model="demo-vision-model")
            assert again.cmb_source.currentData() == "cloud"
        finally:
            again.deleteLater()
    finally:
        win.close()


def test_settings_apply_toxic_report_when_unwritable(qapp, monkeypatch,
                                                     tmp_path):
    """写失败必须可见（toast）且不抛；主窗与设置面板保持可用。"""
    from acouscope.ui import main_window as mw

    ro = tmp_path / "readonly"
    ro.mkdir()
    ro.chmod(0o500)                        # 只读目录：写盘必失败
    win = _main_window(monkeypatch, tmp_path)
    # 落盘候选全部指向只读目录（ai_interpret 顶层绑定的名字须就地打桩）
    monkeypatch.setattr(ai, "data_dir_candidates", lambda: [ro])
    mw_toasts: list[str] = []
    monkeypatch.setattr(mw, "show_toast",
                        lambda parent, msg, level="info": mw_toasts.append(msg))
    try:
        win._activate_settings_tab()
        sp = win._settings_panel
        sp.rbtn_ai_cloud.setChecked(True)
        sp.edit_cloud_model.setText("demo-vision-model")

        win._on_settings_applied()         # 绝不抛

        assert not (ro / "ai_config.json").exists()
        assert tr("ai_panel.config_save_failed") in mw_toasts, \
            "落盘失败必须给出可见反馈（禁静默 except）"
        assert win.isEnabled() is True     # 主窗仍可用
    finally:
        ro.chmod(0o700)
        win.close()


def test_save_ai_config_returns_false_without_raising(tmp_path, monkeypatch):
    """模块级写盘函数：全候选不可写 → False（不抛），可写 → True 且内容一致。"""
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    monkeypatch.setattr(ai, "_config_paths", lambda: [ro / "ai_config.json"])
    try:
        assert ai.save_ai_config({"provider": "ollama"}) is False
    finally:
        ro.chmod(0o700)

    ok = tmp_path / "ok" / "ai_config.json"
    monkeypatch.setattr(ai, "_config_paths", lambda: [ok])
    assert ai.save_ai_config({"provider": "ollama", "model": "m"}) is True
    assert json.loads(ok.read_text(encoding="utf-8"))["model"] == "m"
    assert ai.load_ai_config() == {"provider": "ollama", "model": "m"}


# ----------------------------------------------------------------------
# ③ 诊断分类（429 / 鉴权 / 超时 / 网络；不得再出现「（Exception）」）
# ----------------------------------------------------------------------

def test_429_diagnostic_says_rate_limit_not_exception():
    msg = ai.friendly_error(
        "ProviderError: 服务返回 429: {\"message\":\"API rate limit exceeded\"}",
        kind="openai")
    assert "限流" in msg
    assert "（Exception）" not in msg
    assert "免费远程" not in msg           # 云端/自定义档不得套用免费远程文案
    assert "Ollama" not in msg             # 不得无条件指向本地 Ollama


def test_diagnostic_split_by_engine_kind():
    local = ai.friendly_error("ProviderError: 无法连接 Ollama: [Errno 61] refused",
                              kind="ollama")
    assert "本地" in local and "远程" in local       # 本地档保留本地出路
    cloud = ai.friendly_error("ProviderError: 无法连接服务: [Errno 61] refused",
                              kind="openai")
    assert "本地" not in cloud                       # 云端档不再指向本地服务
    assert "远程" in cloud
    free = ai.friendly_error("ProviderError: 免费远程模型限流（匿名约 2 次/分钟）",
                             kind="free_remote")
    assert "免费远程" in free                        # 仅 free_remote 档保留该口径


def test_diagnostic_auth_timeout_network_unknown():
    assert "鉴权" in ai.friendly_error("ProviderError: 服务返回 401: Unauthorized",
                                       kind="openai")
    assert "超时" in ai.friendly_error(
        "TimeoutError: 请求超时（模型推理可能较慢，请重试）", kind="ollama")
    assert "连接中断" in ai.friendly_error(
        "ConnectionInterruptedError: 连接中断", kind="openai")
    unknown = ai.friendly_error("ValueError: 完全没见过的错误", kind="openai")
    assert "完全没见过的错误" in unknown              # 真实原因不被抹平
    assert "（Exception）" not in unknown
    # 纯函数契约：异常对象入参同样不泄露类型名（原实现恒显「（Exception）」）
    assert "（Exception）" not in ai.friendly_error(Exception("x"))


def test_free_endpoint_sanity_hint():
    hint = ai.config_sanity_hint("cloud", interpreter.FREE_REMOTE_BASE, "")
    assert hint and "429" in hint
    assert ai.config_sanity_hint("cloud", interpreter.FREE_REMOTE_BASE,
                                 _PLACEHOLDER_KEY) == ""
    assert ai.config_sanity_hint("builtin", interpreter.FREE_REMOTE_BASE,
                                 "") == ""
    assert ai.config_sanity_hint("cloud", "https://api.openai.com/v1", "") == ""


def test_run_shows_free_endpoint_hint(qapp, monkeypatch, tmp_path):
    """发送前落一条指引气泡（云端档 + Key 空 + 内置免费端点）；worker 打桩零触网。"""
    cfg = _write_cfg(tmp_path / "ai_config.json", {
        "provider": "custom", "url": interpreter.FREE_REMOTE_BASE,
        "model": interpreter.FREE_REMOTE_MODEL, "key": "",
        "send_image": False, "ai_v2": {"source": "cloud"},
    })
    p = _panel(monkeypatch, [cfg])
    monkeypatch.setattr(ai.AIInterpretDialog, "_make_worker",
                        lambda self, *a, **k: _StubWorker())
    try:
        p.input_edit.setPlainText("请释读当前视图")
        p._on_run()
        texts = [b.text_view.toPlainText() for b in p.msg_bubbles]
        assert any("429" in t for t in texts), "应给出免费端点限流提示"
    finally:
        p.deleteLater()


# ----------------------------------------------------------------------
# ④ 一键切远程：写入目标厂商默认地址与模型（不再保留原 URL）
# ----------------------------------------------------------------------

def test_switch_remote_writes_provider_defaults(tmp_path, monkeypatch):
    cfg = _write_cfg(tmp_path / "ai_config.json", {
        "provider": "custom", "url": interpreter.FREE_REMOTE_BASE,
        "model": interpreter.FREE_REMOTE_MODEL, "key": "",
        "send_image": False, "ai_v2": {"source": "cloud", "mode": "official"},
    })
    monkeypatch.setattr(ai, "_config_paths", lambda: [cfg])
    status = ai._switch_to_remote()
    info = interpreter.PROVIDERS["openai"]
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["url"] == info.base_url            # 真正切走（原 URL 不再保留）
    assert data["model"] == info.default_model     # 原模型不兼容 → 取目标默认
    assert data["provider"] == "openai"
    assert data["send_image"] is False             # 其余键原样保留
    assert data["ai_v2"]["mode"] == "official"
    assert "OpenAI" in status


# ----------------------------------------------------------------------
# ⑤【D】顶部三档下拉
# ----------------------------------------------------------------------

def test_source_combo_has_three_tiers(qapp, monkeypatch, tmp_path):
    p = _panel(monkeypatch, [])
    try:
        assert p.cmb_source.count() == 3
        assert [p.cmb_source.itemData(i) for i in range(3)] == list(ai.SOURCE_KEYS)
        assert p.cmb_source.objectName() == "aiSourceCombo"
        # 档位文案复用 设置-AI 既有键（禁另造一套）
        assert p.cmb_source.itemText(0) == tr("settings.builtin")
        assert p.cmb_source.itemText(1) == tr("settings.self_hosted")
        assert p.cmb_source.itemText(2) == tr("settings.cloud")
    finally:
        p.deleteLater()


def test_tier_switch_persists_source_only(qapp, monkeypatch, tmp_path):
    """切档只写 ai_v2.source；url/model/key 与 ai_v2 其余键逐字不变。"""
    home = _home(tmp_path)
    cfg = _write_cfg(_expected_cfg_path(home), {
        "provider": "openai", "url": "https://api.example.com/v1",
        "model": "demo-vision-model", "key": _PLACEHOLDER_KEY,
        "send_image": True,
        "ai_v2": {"source": "cloud", "mode": "official",
                  "llama_model_id": "keep-me"},
    })
    monkeypatch.setenv("HOME", str(home))
    p = ai.AIInterpretDialog(
        image_getter=lambda: None,
        context_getter=lambda: _CONTEXT,
        view_name_getter=lambda: "FFT 频谱",
    )
    toasts = _toast_spy(monkeypatch)
    try:
        assert p.cmb_source.currentData() == "cloud"
        p.cmb_source.setCurrentIndex(p.cmb_source.findData("self_hosted"))

        data = json.loads(cfg.read_text(encoding="utf-8"))
        assert data["ai_v2"]["source"] == "self_hosted"      # 落盘（复用写盘函数）
        assert data["provider"] == "openai"                  # 参数键零改动
        assert data["url"] == "https://api.example.com/v1"
        assert data["model"] == "demo-vision-model"
        assert data["key"] == _PLACEHOLDER_KEY
        assert data["send_image"] is True
        assert data["ai_v2"]["mode"] == "official"
        assert data["ai_v2"]["llama_model_id"] == "keep-me"
        # 路由随档变化（下次发送即生效，无需重建面板）
        assert p._source == "self_hosted"
        assert p._engine_for_current()["kind"] == "custom"
        # 可见反馈（可用档 → 简短确认）
        assert any(tr("settings.self_hosted") in m for m, _ in toasts)
    finally:
        p.deleteLater()


def test_tier_switch_route_follows_each_tier(qapp, monkeypatch, tmp_path):
    """三档切换 → 路由 kind 与模型名随档解析（builtin=ollama / cloud / self）。"""
    home = _home(tmp_path)
    cfg = _write_cfg(_expected_cfg_path(home), {
        "provider": "ollama", "url": "", "model": "", "key": "",
        "ai_v2": {"source": "builtin"},
    })
    monkeypatch.setenv("HOME", str(home))
    p = ai.AIInterpretDialog(
        image_getter=lambda: None,
        context_getter=lambda: _CONTEXT,
        view_name_getter=lambda: "FFT 频谱",
    )
    _toast_spy(monkeypatch)
    try:
        assert p.cmb_source.currentData() == "builtin"
        assert p._engine_for_current()["kind"] == "ollama"
        assert p._current_model_name().strip()               # 内置档恒有默认模型

        p.cmb_source.setCurrentIndex(p.cmb_source.findData("cloud"))
        assert json.loads(cfg.read_text(encoding="utf-8"))["ai_v2"]["source"] \
            == "cloud"
        assert p._source == "cloud"
    finally:
        p.deleteLater()


def test_tier_switch_unconfigured_guides_to_settings(qapp, monkeypatch, tmp_path):
    """未配置档：档位仍可选并落盘，但给出「去 设置 → AI」引导（不静默失败）。"""
    cfg = _write_cfg(tmp_path / "ai_config.json", {
        "provider": "ollama", "url": "", "model": "", "key": "",
        "ai_v2": {"source": "builtin"},
    })
    p = _panel(monkeypatch, [cfg])
    toasts = _toast_spy(monkeypatch)
    try:
        p.cmb_source.setCurrentIndex(p.cmb_source.findData("cloud"))   # model 空
        assert json.loads(cfg.read_text(encoding="utf-8"))["ai_v2"]["source"] \
            == "cloud"
        assert p._tier_configured() is False
        assert p.lbl_model.toolTip() == tr("ai_panel.unconfigured")
        assert any("设置 → AI" in m for m, _ in toasts), "未配置档必须给出设置引导"

        p.cmb_source.setCurrentIndex(p.cmb_source.findData("self_hosted"))
        assert p._tier_configured() is False                  # 地址也为空
    finally:
        p.deleteLater()


def test_tier_switch_write_failure_visible_and_reverts(qapp, monkeypatch,
                                                       tmp_path):
    """切档写盘失败 → 可见 toast + 下拉回退（绝不静默失败）。"""
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    monkeypatch.setattr(ai, "_config_paths", lambda: [ro / "ai_config.json"])
    toasts = _toast_spy(monkeypatch)
    p = ai.AIInterpretDialog(
        image_getter=lambda: None,
        context_getter=lambda: _CONTEXT,
        view_name_getter=lambda: "FFT 频谱",
    )
    try:
        assert p.cmb_source.currentData() == "builtin"
        p.cmb_source.setCurrentIndex(p.cmb_source.findData("cloud"))
        assert p._source == "builtin"                          # 未生效
        assert p.cmb_source.currentData() == "builtin"         # 下拉回退
        assert any(tr("ai_panel.source_save_failed") == m for m, _ in toasts)
    finally:
        ro.chmod(0o700)
        p.deleteLater()


def test_two_way_sync_panel_combo_and_settings(qapp, monkeypatch, tmp_path):
    """双向同步：面板切档 → 设置面板档位刷新；设置「应用」→ 面板下拉同步。"""
    win = _main_window(monkeypatch, tmp_path)
    try:
        win._activate_settings_tab()
        sp = win._settings_panel
        win._activate_ai_tab()
        panel = win._ai_panel
        assert panel is not None and sp is not None

        # 面板 → 设置：config_changed → _on_ai_config_changed → reload_ai_config
        panel.cmb_source.setCurrentIndex(panel.cmb_source.findData("cloud"))
        assert sp.rbtn_ai_cloud.isChecked()
        assert sp._current_ai_source() == "cloud"

        # 设置 → 面板：应用 → panel.reload_config() → 下拉选中项同步
        sp.rbtn_ai_self.setChecked(True)
        sp.edit_self_url.setText("http://203.0.113.9:11434")
        sp.edit_self_model.setText("demo-selfhost-model")
        assert sp.ai_config()["ai_v2"]["source"] == "self_hosted"
        win._on_settings_applied()
        assert panel.cmb_source.currentData() == "self_hosted"
        assert panel._source == "self_hosted"
        assert panel._current_model_name() == "demo-selfhost-model"
    finally:
        win.close()


def test_long_model_name_not_truncated_in_narrow_pane(qapp, monkeypatch,
                                                      tmp_path):
    """D5：窄栏模型名不截断（无省略号，完整文本 + 全文 tooltip）。"""
    long_name = "Qwen2.5-VL-72B-Instruct-一个非常长的模型名用于窄栏验证"
    cfg = _write_cfg(tmp_path / "ai_config.json", {
        "provider": "custom", "url": "https://api.example.com/v1",
        "model": long_name, "key": _PLACEHOLDER_KEY,
        "ai_v2": {"source": "cloud"},
    })
    p = _panel(monkeypatch, [cfg])
    try:
        p.resize(240, 480)
        qapp.processEvents()
        assert p.lbl_model.text() == tr("ai_panel.model_prefix").format(
            model=long_name)
        assert "…" not in p.lbl_model.text()
        assert p.lbl_model.toolTip() == p.lbl_model.text()
        assert p.lbl_model.wordWrap() is True
    finally:
        p.deleteLater()


# ----------------------------------------------------------------------
# ⑥ 静态纪律（禁词 / hex-px / QDialog 0 / 无主窗 show 调用 / 死 import 清）
# ----------------------------------------------------------------------

def _interpreter_imports(src: str) -> set:
    """源码里 `from acouscope.ai.interpreter import X` 的符号集合（AST 口径）。"""
    found = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith(
                "ai.interpreter"):
            found.update(alias.name for alias in node.names)
    return found


def test_static_discipline():
    panel_src = (_REPO_ROOT / "src" / "acouscope" / "ui" / "widgets"
                 / "ai_interpret.py").read_text(encoding="utf-8")
    win_src = (_REPO_ROOT / "src" / "acouscope" / "ui"
               / "main_window.py").read_text(encoding="utf-8")
    i18n_src = (_REPO_ROOT / "src" / "acouscope" / "i18n"
                / "__init__.py").read_text(encoding="utf-8")

    for src in (panel_src, win_src, i18n_src):
        assert _BANNED not in src, "禁词零容忍"
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", panel_src), "禁硬编码 hex 颜色"
    assert "QDialog" not in panel_src
    assert "MainWindow" + ".show()" not in panel_src
    assert "MainWindow" + ".show()" not in win_src
    # 死 import 清零（AST 口径：注释中的归因叙述不算）：主窗不得再从 engine 层
    # 导入不存在的 _save_config / _load_config；引擎面零改动由「无 ui→ai 写盘调用」保证
    imported = _interpreter_imports(win_src)
    assert "_save_config" not in imported
    assert "_load_config" not in imported
