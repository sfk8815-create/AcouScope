# SPDX-License-Identifier: GPL-3.0-only
"""T-1022 §5/§6：释图窗模型选择器详情化 + 视觉门禁（离屏；禁触网 / 禁真起进程）。

覆盖任务书 Step 6 的必测项：
- 选择器分区列表只含**视觉**模型（纯文本不可选且不在列表）；
- 行内详情：体积 / 视觉标签 / 状态（已下载·未下载·本机推荐）/ 当前项 ✓；
- 未知能力（自填云端模型名 / 自建端点）→ 标注「视觉能力未验证」，允许选择；
- 写权：选择器只写 `ai_v2.source`（+ 内置档模型选择键）；`url`/`model`/`key`
  三个参数键切档前后**逐字不变**；
- `_serve_args` 含 `--mmproj`（纯函数）；
- 静态纪律（禁词 / hex-px / 无 QDialog / 无主窗 show）。

可见性口径：面板为**未 show() 的离屏 QWidget**，故一律用 `isHidden()`
（显式隐藏状态）判定，不用 `isVisible()`（父级未显示时恒 False）。
硬件探测一律打桩为固定档（本机 M4 / 16GB / 200GB 可用），用例不随真机漂移。
"""

import json
import pathlib
import re
import sys

import pytest

sys.path.insert(0, "src")
pytest.importorskip("PyQt6")

from PyQt6.QtGui import QAction  # noqa: E402
from PyQt6.QtWidgets import QMenu  # noqa: E402

from acouscope.ai import hardware, llama_models  # noqa: E402
from acouscope.ai.llama_runtime import _serve_args  # noqa: E402
from acouscope.i18n import tr  # noqa: E402
from acouscope.ui.widgets import ai_interpret as ai  # noqa: E402

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SRC = (_REPO_ROOT / "src" / "acouscope" / "ui" / "widgets" / "ai_interpret.py")
_BANNED = "Mel" + "odyne"
_CONTEXT = "【数值上下文】测试上下文"
#: 固定探测档（确定性用例；真机数值由 test_hardware_probe 覆盖）
_FIXED_RAM_GB = 16.0


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------

def _cfg_file(tmp_path, data: dict) -> pathlib.Path:
    path = tmp_path / "ai_config.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _panel(monkeypatch, paths=(), *, installed=(), downloaded=(), remote=""):
    """离屏面板 + 全部外部探测打桩（零网络 / 零真实模型文件 / 固定硬件档）。"""
    monkeypatch.setattr(ai, "_config_paths", lambda: list(paths))
    monkeypatch.setattr(ai, "installed_ollama_names",
                        lambda timeout=0.8: set(installed))
    monkeypatch.setattr(ai, "remote_service_hint", lambda timeout=0.6: remote)
    monkeypatch.setattr(
        hardware, "probe",
        lambda refresh=False, with_gpu=True: hardware.HardwareProfile(
            ram_gb=_FIXED_RAM_GB, chip="Apple M4", is_apple_silicon=True,
            disk_free_gb=200.0, unified_memory=True))
    monkeypatch.setattr(llama_models, "is_model_ready",
                        lambda mid: mid in set(downloaded))
    return ai.AIInterpretDialog(
        image_getter=lambda: None,
        context_getter=lambda: _CONTEXT,
        view_name_getter=lambda: "FFT 频谱",
    )


def _rows(panel) -> list[QAction]:
    """菜单里的可点行（排除分区标题 / 分隔线 / 无载荷项）。"""
    menu = panel._build_model_menu()
    return [a for a in menu.actions() if not a.isSeparator() and a.data()]


def _row_texts(panel) -> list[str]:
    return [a.text() for a in _rows(panel)]


# ----------------------------------------------------------------------
# §5 分区列表 + 行内详情
# ----------------------------------------------------------------------

def test_menu_is_sectioned_and_vision_only(qapp, monkeypatch, tmp_path):
    """分区列表只含视觉模型；纯文本模型（含下架档）一律不出现。"""
    p = _panel(monkeypatch, [])
    try:
        menu = p._build_model_menu()
        all_text = [a.text() for a in menu.actions()]
        assert tr("ai_panel.sec_builtin") in all_text     # 分区标题
        assert tr("ai_panel.sec_self_hosted") in all_text
        assert tr("ai_panel.sec_cloud") in all_text
        texts = _row_texts(p)
        assert texts, "选择器不得为空（视觉目录非空）"
        for banned in ("spark-x2.5-1.7b", "qwen2.5:3b",
                       "qwen2.5-1.5b-instruct", "qwen2.5-3b-instruct"):
            assert all(banned not in t for t in texts), \
                f"纯文本模型不得上架：{banned}"
        assert any("Qwen2.5-VL 3B" in t for t in texts)
        assert any(tr("ai_panel.tag_vision") in t for t in texts)
    finally:
        p.deleteLater()


def test_rows_show_size_state_and_download_affordance(qapp, monkeypatch,
                                                      tmp_path):
    """行内详情：体积 + 状态（已下载 / 未下载 + [下载]）+ 本机推荐徽标。"""
    p = _panel(monkeypatch, [],
               downloaded=("qwen2.5-vl-3b-instruct-q4_k_m",))
    try:
        texts = _row_texts(p)
        row_3b = next(t for t in texts if "Qwen2.5-VL 3B" in t)
        row_7b = next(t for t in texts if "Qwen2.5-VL 7B" in t)
        assert "GB" in row_3b                       # 体积实测（双文件合计）
        assert tr("ai_panel.state_downloaded") in row_3b
        assert tr("ai_panel.state_not_downloaded") in row_7b
        assert f"[{tr('ai_panel.download')}]" in row_7b
        assert tr("ai_panel.state_recommended") in row_3b
        assert tr("ai_panel.state_low_ram") in row_7b    # 7B 需 24GB（软提示）
    finally:
        p.deleteLater()


def test_current_model_row_carries_check_mark(qapp, monkeypatch, tmp_path):
    """当前项带 ✓；内置档选中受管 GGUF → 走 llama_cpp 路由（应用自带引擎直跑）。"""
    cfg = _cfg_file(tmp_path, {
        "provider": "ollama", "url": "", "model": "", "key": "",
        "ai_v2": {"source": "builtin",
                  "llama_model_id": "qwen2.5-vl-3b-instruct-q4_k_m"},
    })
    p = _panel(monkeypatch, [cfg],
               downloaded=("qwen2.5-vl-3b-instruct-q4_k_m",))
    try:
        assert p._current_model_name() == "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"
        assert p._engine_for_current()["kind"] == "llama_cpp"
        checked = [t for t in _row_texts(p) if t.startswith("✓")]
        assert len(checked) == 1 and "Qwen2.5-VL 3B" in checked[0]
    finally:
        p.deleteLater()


def test_cloud_row_shows_vendor_model_url_and_key_state(qapp, monkeypatch,
                                                        tmp_path):
    """云端行：厂商 + 模型名 + 地址（截断）+ Key 已填 + 视觉未验证标注。"""
    long_url = "https://api.example.com/" + "very-long-path/" * 6
    cfg = _cfg_file(tmp_path, {
        "provider": "custom", "url": long_url,
        "model": "demo-vision-model", "key": "PLACEHOLDER-NOT-A-REAL-KEY",
        "ai_v2": {"source": "cloud"},
    })
    p = _panel(monkeypatch, [cfg])
    try:
        row = next(t for t in _row_texts(p) if "demo-vision-model" in t)
        assert "custom" in row
        assert tr("ai_panel.key_set") in row
        assert "…" in row
        assert tr("ai_panel.tag_vision_unverified") in row
    finally:
        p.deleteLater()


def test_cloud_row_key_unset_and_current_mark(qapp, monkeypatch, tmp_path):
    cfg = _cfg_file(tmp_path, {
        "provider": "openai", "url": "https://api.openai.com/v1",
        "model": "gpt-4o", "key": "", "ai_v2": {"source": "cloud"},
    })
    p = _panel(monkeypatch, [cfg])
    try:
        row = next(t for t in _row_texts(p) if "gpt-4o" in t)
        assert tr("ai_panel.key_unset") in row
        assert row.startswith("✓")                   # 当前档
    finally:
        p.deleteLater()


def test_unconfigured_tiers_row_routes_to_settings(qapp, monkeypatch, tmp_path):
    """未配置的本地 / 云端档 → 行文「未配置…去 设置→AI」；点击仍可切档
    （切档后由既有 `_notify_tier_state` 给出去设置的可见引导）。"""
    p = _panel(monkeypatch, [])
    switched = []
    monkeypatch.setattr(p, "_on_menu_tier", lambda s: switched.append(s))
    try:
        acts = _rows(p)
        self_row = next(a for a in acts
                        if a.data().get("section") == "self_hosted")
        cloud_row = next(a for a in acts if a.data().get("section") == "cloud")
        assert self_row.text() == tr("ai_panel.self_unconfigured")
        assert cloud_row.text() == tr("ai_panel.cloud_unconfigured")
        self_row.trigger()
        cloud_row.trigger()
        assert switched == ["self_hosted", "cloud"]
        goto = [a for a in acts if a.data().get("goto_settings")]
        assert goto and goto[0].text() == tr("ai_panel.goto_settings_ai")
    finally:
        p.deleteLater()


def test_unknown_capability_allows_selection_but_is_labelled(qapp, monkeypatch,
                                                             tmp_path):
    """未知能力（自填云端 model 名 / 自建端点）→ 允许选择，标注「未验证」。"""
    cfg = _cfg_file(tmp_path, {
        "provider": "custom", "url": "http://192.168.0.9:8000/v1",
        "model": "my-private-vl", "key": "PLACEHOLDER-NOT-A-REAL-KEY",
        "ai_v2": {"source": "cloud"},
    })
    p = _panel(monkeypatch, [cfg])
    try:
        assert ai._model_vision_state("my-private-vl") == ai.VISION_UNVERIFIED
        assert ai._model_text_only("my-private-vl") is False
        assert ai.vision_tag("my-private-vl") == \
            tr("ai_panel.tag_vision_unverified")
        row = next(t for t in _row_texts(p) if "my-private-vl" in t)
        assert tr("ai_panel.tag_vision_unverified") in row
        assert p._tier_configured() is True          # 允许选择
    finally:
        p.deleteLater()


# ----------------------------------------------------------------------
# §6 视觉门禁（取代静默降级）
# ----------------------------------------------------------------------

def test_known_text_only_model_marked_and_blocked(qapp, monkeypatch, tmp_path):
    """已存在配置指向非视觉模型 → 顶部标签「不支持图片」+ 空态明确提示更换。"""
    cfg = _cfg_file(tmp_path, {
        "provider": "custom", "url": "http://127.0.0.1:11434",
        "model": "spark-x2.5-1.7b", "key": "",
        "ai_v2": {"source": "self_hosted"},
    })
    p = _panel(monkeypatch, [cfg])
    try:
        assert ai._model_vision_state("spark-x2.5-1.7b") == ai.VISION_TEXT_ONLY
        assert tr("ai_panel.tag_text_only") in p.btn_model_pick.text()
        assert p.empty_panel.isHidden() is False
        assert p.lbl_empty_reason.text() == tr("ai_panel.vision_blocked")
        assert p.btn_empty_download.isHidden() is True   # 需更换模型，无下载项
    finally:
        p.deleteLater()


def test_empty_state_shows_reason_and_download(qapp, monkeypatch, tmp_path):
    """空态：未下载 → 原因 + 本机推荐 + [下载] + 次要入口（不得石沉大海）。"""
    p = _panel(monkeypatch, [])
    try:
        assert p.empty_panel.isHidden() is False
        reason = p.lbl_empty_reason.text()
        assert tr("ai_panel.state_recommended") in reason
        assert "Qwen2.5-VL 3B" in reason             # 16GB 档 → 推荐 3B
        assert p.btn_empty_download.isHidden() is False
        assert p.btn_empty_download.text() == tr("ai_panel.download")
        assert p.btn_empty_settings.text() == tr("ai_panel.goto_settings_ai")
        assert p._empty_entry.model_id == "qwen2.5-vl-3b-instruct-q4_k_m"
    finally:
        p.deleteLater()


def test_empty_state_hidden_when_model_downloaded(qapp, monkeypatch, tmp_path):
    """当前模型已下载 → 空态隐藏（不再提示下载）。"""
    cfg = _cfg_file(tmp_path, {
        "provider": "ollama", "url": "", "model": "", "key": "",
        "ai_v2": {"source": "builtin",
                  "llama_model_id": "qwen2.5-vl-3b-instruct-q4_k_m"},
    })
    p = _panel(monkeypatch, [cfg],
               downloaded=("qwen2.5-vl-3b-instruct-q4_k_m",))
    try:
        assert p.empty_panel.isHidden() is True
        assert p.lbl_empty_reason.text() == ""
    finally:
        p.deleteLater()


def test_download_from_unloaded_row_selects_after_done(qapp, monkeypatch,
                                                       tmp_path):
    """未下载行点击 → 启动下载（worker 打桩，零网络）+ 内联进度；完成后切为当前。"""
    cfg = _cfg_file(tmp_path, {
        "provider": "ollama", "url": "", "model": "", "key": "",
        "ai_v2": {"source": "builtin"},
    })
    p = _panel(monkeypatch, [cfg])
    started = []
    monkeypatch.setattr(ai.ModelDownloadWorker, "start",
                        lambda self: started.append(self.entry.model_id))
    try:
        entry = next(e for e in ai.builtin_catalog()
                     if e.model_id == "qwen2.5-vl-3b-instruct-q4_k_m")
        p._on_menu_entry(entry)
        assert started == ["qwen2.5-vl-3b-instruct-q4_k_m"]
        assert p.prog_empty.isHidden() is False      # 内联进度面板可见
        assert p.btn_empty_download.isEnabled() is False

        monkeypatch.setattr(ai, "entry_is_downloaded", lambda e, i=None: True)
        p._on_download_done(entry.model_id, p.prog_empty,
                            p.btn_empty_download, entry, True)
        data = json.loads(cfg.read_text(encoding="utf-8"))
        assert data["ai_v2"]["llama_model_id"] == entry.model_id
        assert data["ai_v2"]["source"] == "builtin"
        assert p.prog_empty.isHidden() is True
        assert p.btn_empty_download.isEnabled() is True
    finally:
        p.deleteLater()


# ----------------------------------------------------------------------
# 写权：只写 ai_v2.source（参数键 url/model/key 逐字不变）
# ----------------------------------------------------------------------

def test_choice_writes_source_only_and_keeps_parameter_keys(qapp, monkeypatch,
                                                            tmp_path):
    """切档（本地 / 云端行）只写 `ai_v2.source`；url/model/key 逐字不变。"""
    key = "PLACEHOLDER-NOT-A-REAL-KEY"
    cfg = _cfg_file(tmp_path, {
        "provider": "openai", "url": "https://api.example.com/v1",
        "model": "demo-vision-model", "key": key, "send_image": True,
        "ai_v2": {"source": "cloud", "mode": "official",
                  "llama_model_id": "keep-me"},
    })
    p = _panel(monkeypatch, [cfg])
    try:
        self_row = next(a for a in _rows(p)
                        if a.data().get("section") == "self_hosted")
        self_row.trigger()
        data = json.loads(cfg.read_text(encoding="utf-8"))
        assert data["ai_v2"]["source"] == "self_hosted"
        assert data["provider"] == "openai"
        assert data["url"] == "https://api.example.com/v1"
        assert data["model"] == "demo-vision-model"
        assert data["key"] == key
        assert data["send_image"] is True
        assert data["ai_v2"]["mode"] == "official"
        assert data["ai_v2"]["llama_model_id"] == "keep-me"   # 未选具体模型 → 不动
    finally:
        p.deleteLater()


def test_managed_gguf_selection_writes_model_keys_only(qapp, monkeypatch,
                                                       tmp_path):
    """内置档选中受管 GGUF：额外写模型选择键，url/model/key 仍逐字不变。"""
    key = "PLACEHOLDER-NOT-A-REAL-KEY"
    cfg = _cfg_file(tmp_path, {
        "provider": "custom", "url": "https://api.example.com/v1",
        "model": "demo-vision-model", "key": key,
        "ai_v2": {"source": "cloud", "mode": "official"},
    })
    p = _panel(monkeypatch, [cfg],
               downloaded=("qwen2.5-vl-3b-instruct-q4_k_m",))
    try:
        entry = next(e for e in ai.builtin_catalog()
                     if e.model_id == "qwen2.5-vl-3b-instruct-q4_k_m")
        p._on_menu_entry(entry)
        data = json.loads(cfg.read_text(encoding="utf-8"))
        assert data["ai_v2"]["source"] == "builtin"
        assert data["ai_v2"]["llama_model_id"] == entry.model_id
        assert data["provider"] == "custom"
        assert data["url"] == "https://api.example.com/v1"
        assert data["model"] == "demo-vision-model"
        assert data["key"] == key
        assert p._engine_for_current()["kind"] == "llama_cpp"
    finally:
        p.deleteLater()


def test_builtin_ollama_selection_clears_gguf_pointer(qapp, monkeypatch,
                                                      tmp_path):
    """内置档选中 Ollama 官方档 → 记 official_model 并清 GGUF 指针（路由正确）。"""
    cfg = _cfg_file(tmp_path, {
        "provider": "ollama", "url": "", "model": "", "key": "",
        "ai_v2": {"source": "builtin",
                  "llama_model_id": "qwen2.5-vl-3b-instruct-q4_k_m"},
    })
    p = _panel(monkeypatch, [cfg], installed=("moondream",))
    try:
        entry = next(e for e in ai.builtin_catalog() if e.model_id == "moondream")
        p._on_menu_entry(entry)
        data = json.loads(cfg.read_text(encoding="utf-8"))
        assert data["ai_v2"]["official_model"] == "moondream"
        assert data["ai_v2"]["llama_model_id"] == ""
        assert p._engine_for_current()["kind"] == "ollama"
    finally:
        p.deleteLater()


def test_choice_write_failure_is_visible(qapp, monkeypatch, tmp_path):
    """写盘失败 → 可见 toast 且不抛（绝不静默）。"""
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    monkeypatch.setattr(ai, "_config_paths", lambda: [ro / "ai_config.json"])
    monkeypatch.setattr(ai, "installed_ollama_names", lambda timeout=0.8: set())
    monkeypatch.setattr(ai, "remote_service_hint", lambda timeout=0.6: "")
    toasts = []
    monkeypatch.setattr(ai, "show_toast",
                        lambda parent, msg, level="info": toasts.append(msg))
    p = ai.AIInterpretDialog(image_getter=lambda: None,
                             context_getter=lambda: _CONTEXT,
                             view_name_getter=lambda: "FFT 频谱")
    try:
        assert p._apply_choice("cloud") is False
        assert tr("ai_panel.source_save_failed") in toasts
    finally:
        ro.chmod(0o700)
        p.deleteLater()


# ----------------------------------------------------------------------
# §4 --mmproj（argv 纯函数）
# ----------------------------------------------------------------------

def test_serve_args_without_and_with_mmproj():
    base = _serve_args("bin", "m.gguf", 5000, 4096)
    assert base == ["bin", "-m", "m.gguf", "--host", "127.0.0.1",
                    "--port", "5000", "--ctx-size", "4096"]
    argv = _serve_args("bin", "m.gguf", 5000, 4096, "/m/mmproj.gguf")
    assert argv[:len(base)] == base
    assert argv[-2:] == ["--mmproj", "/m/mmproj.gguf"]


def test_catalog_vision_models_carry_mmproj():
    """目录层：视觉模型必须带 mmproj（视觉塔），否则引擎读不了图。"""
    for info in llama_models.GGUF_MODELS:
        assert info.vision is True
        assert info.mmproj is not None
        assert [f.role for f in info.files] == ["weights", "mmproj"]


# ----------------------------------------------------------------------
# 顶部常显信息 + 静态纪律
# ----------------------------------------------------------------------

def test_top_line_always_shows_vision_tag_and_probe(qapp, monkeypatch, tmp_path):
    """顶部常显：视觉标签（按钮）+ 探测结论一行（芯片 / 内存 / 磁盘）。"""
    p = _panel(monkeypatch, [])
    try:
        assert "▾" in p.btn_model_pick.text()
        assert tr("ai_panel.tag_vision") in p.btn_model_pick.text()
        assert p.lbl_probe.text().strip()
        assert "Apple M4" in p.lbl_probe.text()
        assert "16GB" in p.lbl_probe.text()
    finally:
        p.deleteLater()


def test_static_discipline_ai_interpret():
    src = _SRC.read_text(encoding="utf-8")
    assert _BANNED not in src
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", src), "禁硬编码 hex 颜色"
    assert not re.search(r"\d+px", src), "禁硬编码像素字面量"
    assert "QDialog" not in src, "禁新建模态对话框"
    assert ".exec(" not in src, "禁模态调用字面量"
    assert "MainWindow" + ".show()" not in src
    assert "setHandleWidth(" not in src


def test_selector_uses_non_modal_popup(qapp, monkeypatch, tmp_path):
    """选择器 = QMenu 非模态 popup（绝不阻塞）；每次展开重建（状态最新）。"""
    p = _panel(monkeypatch, [])
    try:
        menu = p._build_model_menu()
        assert isinstance(menu, QMenu)
        assert menu.objectName() == "aiModelMenu"
        p._on_pick_model()
        assert isinstance(p._model_menu, QMenu)
        assert p._model_menu is not menu
    finally:
        p.deleteLater()
