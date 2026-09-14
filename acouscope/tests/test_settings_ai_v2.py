# SPDX-License-Identifier: GPL-3.0-only
"""T-320：设置-AI 三档「模型来源」单选（内置 / 本地部署 / 云端服务商）。

覆盖（任务书 Step4）：
- 默认「内置模型」档：零输入（零配置锚点）+ 状态行只读；
- 切「本地部署」→ 地址/模型/密钥三字段显隐 + 保存往返；
- 切「云端服务商」→ 厂商下拉（5+自定义）+ 预置地址/默认模型联动；
- 旧配置迁移：ollama→内置档；external_ollama→本地部署档（字段原样）；
  已删云端厂商→custom 兜底（url/model/key 保留）；
- ai_config()：既有 5 键 + ai_v2 三档新键 + 旧键备份保留（防回滚）；
- 旧 UI 组件负向断言（官方单选组/BYOM/llama 组/厂商下拉不得回潮）；
- 禁词 0（无 oMLX / Mac Studio / llama·GGUF·引擎黑话入用户文案）；
- 纪律：无模态框 / 无 show / 无主窗构造。

构造口径：probe_ollama 打桩（零网络），不弹主窗、不 show。
"""
import sys
from pathlib import Path

sys.path.insert(0, "src")
import pytest
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication, QRadioButton  # noqa: E402

from acouscope.ai.interpreter import PROVIDERS  # noqa: E402
from acouscope.ui.widgets import settings_dialog as sd  # noqa: E402
from acouscope.ui.widgets.settings_dialog import SettingsDialog  # noqa: E402

_SRC = Path(__file__).resolve().parents[1] / "src" / "acouscope"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def _probe_off(monkeypatch):
    """probe_ollama 打桩：引擎未运行（零网络）。"""
    import acouscope.ai.backends.local_registry as lr
    monkeypatch.setattr(lr, "probe_ollama", lambda *a, **k: (False, []))


@pytest.fixture
def dlg(app, monkeypatch):
    _probe_off(monkeypatch)
    return SettingsDialog(ai_config={})


# ---------------------------------------------------------------------------
# 1. 默认内置档：零输入锚点
# ---------------------------------------------------------------------------

def test_default_builtin_no_inputs(dlg):
    """默认构造 → 内置档选中；本地/云端字段组隐藏（零配置开箱即用）。"""
    assert dlg.rbtn_ai_builtin.isChecked() is True
    assert dlg.rbtn_ai_self.isChecked() is False
    assert dlg.rbtn_ai_cloud.isChecked() is False
    assert dlg.grp_ai_self_fields.isHidden() is True
    assert dlg.grp_ai_cloud_fields.isHidden() is True
    # 内置档无任何输入框（状态行只读）
    assert dlg.lbl_ai_builtin_status.isHidden() is False


def test_builtin_status_line(dlg, monkeypatch):
    """状态行只读现有接口：引擎未运行 → 「首次使用」中性文案（禁报错声光）。"""
    text = dlg.lbl_ai_builtin_status.text()
    assert text.strip()
    assert "首次使用" in text


def test_builtin_status_ready(app, monkeypatch):
    """引擎就绪且模型齐备 → 「已就绪」文案（只读，不实现启动/下载）。

    T-1022 归因（非静默）：官方目录纯文本档下架、只留视觉模型，本用例探测到的
    已装模型名随之改用新目录名（等价强度：目录内模型齐备 → 「就绪」）。
    """
    import acouscope.ai.backends.local_registry as lr
    monkeypatch.setattr(lr, "probe_ollama",
                        lambda *a, **k: (True, list(lr.OFFICIAL_MODELS)))
    d = SettingsDialog(ai_config={})
    assert "就绪" in d.lbl_ai_builtin_status.text()
    d.deleteLater()


# ---------------------------------------------------------------------------
# 2. 本地部署档：三字段 + 保存往返
# ---------------------------------------------------------------------------

def test_self_hosted_fields_and_roundtrip(dlg, app, monkeypatch):
    """切「本地部署」→ 地址/模型/密钥三字段可见；保存往返字段不丢。"""
    dlg.rbtn_ai_self.setChecked(True)
    assert dlg.grp_ai_self_fields.isHidden() is False
    assert dlg.grp_ai_cloud_fields.isHidden() is True
    dlg.edit_self_url.setText("http://192.168.1.20:11434")
    dlg.edit_self_model.setText("qwen2.5:3b")
    dlg.edit_self_key.setText("sk-self")
    cfg = dlg.ai_config()
    assert cfg["provider"] == "custom"
    assert cfg["url"] == "http://192.168.1.20:11434"
    assert cfg["model"] == "qwen2.5:3b"
    assert cfg["key"] == "sk-self"
    v2 = cfg["ai_v2"]
    assert v2["source"] == "self_hosted"
    assert v2["external_ollama"] is True
    assert v2["external_ollama_url"] == "http://192.168.1.20:11434"
    # 往返：以保存结果为新配置 → 恢复本地部署档且字段原样
    _probe_off(monkeypatch)
    d2 = SettingsDialog(ai_config=cfg)
    assert d2.rbtn_ai_self.isChecked() is True
    assert d2.edit_self_url.text() == "http://192.168.1.20:11434"
    assert d2.edit_self_model.text() == "qwen2.5:3b"
    assert d2.edit_self_key.text() == "sk-self"
    d2.deleteLater()


# ---------------------------------------------------------------------------
# 3. 云端档：厂商下拉 + 预置联动
# ---------------------------------------------------------------------------

def test_cloud_vendor_combo_preset(dlg):
    """切「云端」→ 厂商下拉 = DeepSeek/通义/OpenAI/智谱/自定义（5 项）。"""
    dlg.rbtn_ai_cloud.setChecked(True)
    assert dlg.grp_ai_cloud_fields.isHidden() is False
    assert dlg.grp_ai_self_fields.isHidden() is True
    ids = [dlg.cmb_cloud_vendor.itemData(i)
           for i in range(dlg.cmb_cloud_vendor.count())]
    assert ids == ["deepseek", "qwen", "openai", "zhipu", "custom"]


def test_cloud_vendor_url_model_autofill(dlg):
    """选命名厂商 → 保存输出预置 base_url；切厂商自动带出默认模型（可改）。"""
    dlg.rbtn_ai_cloud.setChecked(True)
    dlg.cmb_cloud_vendor.setCurrentIndex(0)  # deepseek
    dlg.edit_cloud_model.setText("")  # 模型空 → 切厂商自动带出默认模型
    dlg.cmb_cloud_vendor.setCurrentIndex(1)  # qwen
    assert dlg.edit_cloud_model.text() == PROVIDERS["qwen"].default_model
    dlg.edit_cloud_key.setText("sk-cloud")
    cfg = dlg.ai_config()
    assert cfg["provider"] == "qwen"
    assert cfg["url"] == PROVIDERS["qwen"].base_url
    assert cfg["model"] == PROVIDERS["qwen"].default_model
    assert cfg["key"] == "sk-cloud"
    v2 = cfg["ai_v2"]
    assert v2["source"] == "cloud"
    assert v2["external_ollama"] is False


def test_cloud_custom_vendor_url_field(dlg):
    """「自定义」厂商 → 地址输入可见；手填地址原样入 url。"""
    dlg.rbtn_ai_cloud.setChecked(True)
    idx = [dlg.cmb_cloud_vendor.itemData(i)
           for i in range(dlg.cmb_cloud_vendor.count())].index("custom")
    dlg.cmb_cloud_vendor.setCurrentIndex(idx)
    assert dlg.edit_cloud_url.isVisibleTo(dlg.grp_ai_cloud_fields) is True
    dlg.edit_cloud_url.setText("https://api.mycompany.com/v1")
    cfg = dlg.ai_config()
    assert cfg["provider"] == "custom"
    assert cfg["url"] == "https://api.mycompany.com/v1"


def test_cloud_named_vendor_url_hidden(dlg):
    """命名厂商 → 地址输入隐藏（预置地址，不给用户填）。"""
    dlg.rbtn_ai_cloud.setChecked(True)
    dlg.cmb_cloud_vendor.setCurrentIndex(0)  # deepseek
    assert dlg.edit_cloud_url.isHidden() is True


# ---------------------------------------------------------------------------
# 4. 旧配置迁移（老用户配置不丢、平滑落档）
# ---------------------------------------------------------------------------

def test_migration_ollama_builtin(app, monkeypatch):
    """旧 provider=ollama 且无 external → 内置档。"""
    _probe_off(monkeypatch)
    d = SettingsDialog(ai_config={
        "provider": "ollama", "url": "", "model": "spark-x2.5-1.7b",
        "key": "", "send_image": True})
    assert d.rbtn_ai_builtin.isChecked() is True
    d.deleteLater()


def test_migration_external_ollama_self(app, monkeypatch):
    """旧 external_ollama=True → 本地部署档，url/model/key 原样迁入。"""
    _probe_off(monkeypatch)
    d = SettingsDialog(ai_config={
        "provider": "ollama", "url": "", "model": "llama3.2-vision:11b",
        "key": "k-old",
        "ai_v2": {"external_ollama": True,
                  "external_ollama_url": "http://192.168.1.20:11434"}})
    assert d.rbtn_ai_self.isChecked() is True
    assert d.edit_self_url.text() == "http://192.168.1.20:11434"
    assert d.edit_self_model.text() == "llama3.2-vision:11b"
    assert d.edit_self_key.text() == "k-old"
    d.deleteLater()


def test_migration_local_providers(app, monkeypatch):
    """旧本地类 provider（llama_cpp / lm_studio）→ 本地部署档。"""
    _probe_off(monkeypatch)
    for pid in ("llama_cpp", "lm_studio"):
        d = SettingsDialog(ai_config={"provider": pid})
        assert d.rbtn_ai_self.isChecked() is True, pid
        d.deleteLater()


def test_migration_deleted_cloud_vendor_custom(app, monkeypatch):
    """旧云端厂商（已删，如 anthropic）→ 云端档 custom 兜底，三字段保留。"""
    _probe_off(monkeypatch)
    d = SettingsDialog(ai_config={
        "provider": "anthropic", "url": "https://api.anthropic.com/v1",
        "model": "claude-x", "key": "sk-1"})
    assert d.rbtn_ai_cloud.isChecked() is True
    ids = [d.cmb_cloud_vendor.itemData(i)
           for i in range(d.cmb_cloud_vendor.count())]
    assert d.cmb_cloud_vendor.currentData() == "custom"
    assert "anthropic" not in ids
    assert d.edit_cloud_url.text() == "https://api.anthropic.com/v1"
    assert d.edit_cloud_model.text() == "claude-x"
    assert d.edit_cloud_key.text() == "sk-1"
    cfg = d.ai_config()
    assert cfg["provider"] == "custom"
    assert cfg["url"] == "https://api.anthropic.com/v1"
    assert cfg["model"] == "claude-x"
    d.deleteLater()


def test_migration_unknown_falls_back_builtin(app, monkeypatch):
    """无法判定的旧配置 → 保守回落内置档（不猜）。"""
    _probe_off(monkeypatch)
    d = SettingsDialog(ai_config={"provider": "who-knows"})
    assert d.rbtn_ai_builtin.isChecked() is True
    d.deleteLater()


# ---------------------------------------------------------------------------
# 5. 保存输出：既有 5 键 + ai_v2 旧键备份（防回滚）
# ---------------------------------------------------------------------------

def test_save_preserves_legacy_v2_keys(dlg):
    """ai_config() 保留 ai_v2 旧键（mode/official_model/byom_*）为备份。"""
    legacy_v2 = {"mode": "byom", "official_model": "qwen2.5:3b",
                 "byom_model": "my-model", "byom_prompt": "规范",
                 "llama_model_id": "fake-3b"}
    dlg._ai["ai_v2"] = dict(legacy_v2)
    cfg = dlg.ai_config()
    v2 = cfg["ai_v2"]
    for k, val in legacy_v2.items():
        assert v2[k] == val, f"旧键备份 {k} 丢失"
    assert v2["source"] == "builtin"
    for k in ("provider", "url", "model", "key", "send_image", "ai_v2"):
        assert k in cfg


# ---------------------------------------------------------------------------
# 6. 旧 UI 组件负向断言（防回潮；归并原 test_settings_llama_models 全部对象）
# ---------------------------------------------------------------------------

def test_legacy_ui_removed(dlg):
    """官方单选组/BYOM/llama 组/厂商下拉/下载 worker 不得回潮。"""
    for attr in ("rbtns_official", "grp_official", "btn_download",
                 "lbl_download", "grp_byom", "edit_byom_model",
                 "edit_byom_prompt", "rbtns_llama", "grp_llama",
                 "btn_llama_download", "lbl_llama_download",
                 "cmb_provider", "chk_external", "edit_external_url"):
        assert not hasattr(dlg, attr), f"旧控件回潮: {attr}"
    for mod_attr in ("_ModelPullWorker", "_LlamaPullWorker"):
        assert not hasattr(sd, mod_attr), f"旧 worker 回潮: {mod_attr}"


# ---------------------------------------------------------------------------
# 7. 纪律自断言：三档 radio 互斥 + 禁词 0 + 无模态/无 show
# ---------------------------------------------------------------------------

def test_three_radios_exclusive(dlg):
    """三档 QRadioButton 互斥（autoExclusive 组内单选）。"""
    radios = [dlg.rbtn_ai_builtin, dlg.rbtn_ai_self, dlg.rbtn_ai_cloud]
    assert all(isinstance(r, QRadioButton) for r in radios)
    dlg.rbtn_ai_cloud.setChecked(True)
    assert sum(r.isChecked() for r in radios) == 1
    assert dlg._current_ai_source() == "cloud"


def test_no_banned_terms_in_source():
    """设置界面对象文案禁词 0：oMLX / Mac Studio / 终端黑话（拼接构造防自扫中）。"""
    src = (_SRC / "ui" / "widgets" / "settings_dialog.py").read_text(
        encoding="utf-8")
    for banned in ("o" + "MLX", "Mac " + "Studio", "ollama " + "serve",
                   "ollama " + "pull", "brew " + "install"):
        assert banned not in src, f"禁词命中: {banned!r}"


def test_no_dialog_no_show():
    """本测试文件不得引入模态/主窗 API（拼接构造防自扫中）。"""
    src = Path(__file__).read_text(encoding="utf-8")
    for banned in ("." + "show(", "Q" + "Dialog", "QMessageBox" + "(",
                   "MainWindow" + "("):
        assert banned not in src, f"测试文件出现禁词 {banned!r}"
