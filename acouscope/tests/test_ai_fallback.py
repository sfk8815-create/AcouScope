# SPDX-License-Identifier: GPL-3.0-only
"""T-307: 兜底链路（AT-407，全 mock，绝不触网）。

覆盖 Worker.error（failed 信号）消费处 _on_failed 的异常路径：
- ProviderError / VisionUnsupportedError / 未知异常 → 友好文案，绝不崩溃；
- 本地/免费远程失败 → QMessageBox [切换远程模型][取消]；
- 一键切换 → ai_config.json provider=openai 且 lbl_provider 刷新。

T-1020 归因（非静默）：本轮把 `friendly_error` 的用户可见文案迁到 i18n 三语
（原为硬编码中文，违反「用户可见文案 i18n 三语」口径），并改为**按原因 + 按
引擎种类分流**。因此下列用例中「断言硬编码中文『远程』/『本地』」改为断言
i18n 键文案本身（等价且更严：直接锁到具体文案键，不依赖当前界面语言）。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")
import pytest
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QMessageBox

from acouscope.ai.interpreter import ProviderError, VisionUnsupportedError
from acouscope.i18n import tr
from acouscope.ui.widgets import ai_interpret as ai


# ----------------------------------------------------------------------
# 纯函数：friendly_error（绝不抛异常 + 给出路）
# T-1020 归因（非静默）：断言由「硬编码中文关键词」改为「i18n 键文案 + 真实原因」
# 双重锁（等价且更严：文案键即契约，且额外要求 fail 原因不被抹平）。
# ----------------------------------------------------------------------

def test_fallback_message_text():
    msg = ai.friendly_error(ProviderError("boom"))
    assert "boom" in msg                       # T-1020：真实原因原样呈现
    assert tr("ai_panel.advice_local") in msg  # 提供出路
    assert tr("ai_panel.advice_cloud") not in msg


def test_fallback_never_raises():
    class Weird(Exception):
        pass
    msg = ai.friendly_error(Weird("x"))
    assert tr("ai_panel.err_unknown") in msg
    assert tr("ai_panel.advice_local") in msg


def test_fallback_vision_specific():
    msg = ai.friendly_error(VisionUnsupportedError("no vision"))
    assert tr("ai_panel.err_vision") in msg and tr("ai_panel.advice_local") in msg


def test_fallback_empty_detail():
    # 无 detail 的异常也不崩、仍有出路
    assert tr("ai_panel.advice_local") in ai.friendly_error(ProviderError())


# ----------------------------------------------------------------------
# 一键切换：模块级 _switch_to_remote（mock 配置路径，真落盘 tmp）
# ----------------------------------------------------------------------

def test_switch_to_remote_writes_openai(tmp_path, monkeypatch):
    cfg = tmp_path / "ai_config.json"
    cfg.write_text(json.dumps({
        "provider": "ollama", "url": "http://127.0.0.1:11434",
        "model": "spark-x2.5-1.7b", "key": "", "send_image": False,
        "ai_v2": {"mode": "official", "official_model": "",
                  "byom_model": "", "byom_prompt": ""},
    }), encoding="utf-8")
    monkeypatch.setattr(ai, "_config_paths", lambda: [cfg])
    status = ai._switch_to_remote()
    assert "OpenAI" in status
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["provider"] == "openai"
    # 既有键原样保留（HARD-RULES-2：写 provider=openai，不破坏其余配置）
    assert data["send_image"] is False
    assert data["ai_v2"]["mode"] == "official"
    assert data["url"].strip()  # 空则取 openai 默认 base_url
    assert data["model"].strip()


def test_switch_to_remote_no_config_file(tmp_path, monkeypatch):
    cfg = tmp_path / "ai_config.json"  # 不存在
    monkeypatch.setattr(ai, "_config_paths", lambda: [cfg])
    status = ai._switch_to_remote()
    assert "OpenAI" in status
    assert json.loads(cfg.read_text(encoding="utf-8"))["provider"] == "openai"


def test_switch_to_remote_unwritable(tmp_path, monkeypatch):
    monkeypatch.setattr(ai, "_config_paths", lambda: [Path("/proc/forbidden/x")])
    assert "失败" in ai._switch_to_remote()  # 不抛异常


# ----------------------------------------------------------------------
# 对话框级：_on_failed 异常路径（mock QMessageBox.exec，不弹真框）
# ----------------------------------------------------------------------

@pytest.fixture()
def dlg(qapp, monkeypatch, tmp_path):
    """真实对话框；_config_paths 打桩到 tmp，避免污染真实用户配置。"""
    mp = pytest.MonkeyPatch()
    mp.setattr(ai, "_config_paths", lambda: [tmp_path / "ai_config.json"])
    d = ai.AIInterpretDialog(
        image_getter=lambda: b"fake-png",
        context_getter=lambda: "【数值上下文】测试上下文",
        view_name_getter=lambda: "FFT 频谱",
    )
    yield d
    mp.undo()
    d.deleteLater()


def _last_reply(dlg) -> str:
    """对话流内最后一条 AI 气泡文本。

    T-1018 归因（非静默）：原「结果区 result_view / 追问区 chat_view」已随对话式
    重做合流为消息流气泡，读取点改此函数。
    """
    for b in reversed(dlg.msg_bubbles):
        if b.role == "assistant":
            return b.text_view.toPlainText()
    return ""


def _use_cfg(dlg, monkeypatch, tmp_path, data: dict):
    """T-1018 归因（非静默）：档位改由 ai_config.json 只读驱动（面板三档下拉已删）。"""
    cfg = tmp_path / "ai_config.json"
    cfg.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ai, "_config_paths", lambda: [cfg])
    dlg.reload_config()
    return cfg


def _builtin_first_send(dlg, monkeypatch, tmp_path):
    """内置档（ollama）+ 首轮（释图）状态：失败应给「一键切远程」出路。

    「首轮 / 追问」由 _turn 表达（原 _mode 已随合流入口删除）。
    配置不含 ai_v2.source：走既有 provider=ollama → 内置档迁移判定（同 T-1011
    之前的旧配置口径），使 _switch_to_remote 写入后可解析为云端档。
    """
    _use_cfg(dlg, monkeypatch, tmp_path, {
        "provider": "ollama", "url": "", "model": "", "key": "",
    })
    dlg._turn = 1
    dlg._chat_messages = [{"role": "user", "content": "q"}]


def _cloud_openai_first_send(dlg, monkeypatch, tmp_path):
    """云端档 + OpenAI 厂商：云端失败语义（不弹模态）。"""
    _use_cfg(dlg, monkeypatch, tmp_path, {
        "provider": "openai", "url": "https://api.openai.com/v1",
        "model": "gpt-4o", "key": "sk-x",
        "ai_v2": {"source": "cloud", "external_ollama": False,
                  "external_ollama_url": ""},
    })
    dlg._turn = 1


def test_on_failed_run_ollama_shows_remote_button(dlg, monkeypatch, tmp_path):
    """首轮（释图）+ 内置档失败 → 对话流友好文案 + [切换远程模型][取消]，不崩溃。

    T-1018 归因（非静默）：原「run 模式 + result_view」口径改为「首轮 + 消息流气泡」
    （释图与追问已合流为同一输入框发送，_mode 删除）。
    """
    from PyQt6.QtWidgets import QPushButton
    seen = {}

    def fake_exec(self):
        labels = [b.text() for b in self.findChildren(QPushButton)
                  if not b.isDefault()]
        seen["buttons"] = labels
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    _builtin_first_send(dlg, monkeypatch, tmp_path)

    dlg._on_failed("ProviderError: 无法连接 Ollama: [Errno 61] refused")

    text = _last_reply(dlg)
    # T-1020 归因（非静默）：原断言硬编码中文「远程」；文案迁 i18n 后改为断言
    # 本地档建议键（语义等价：本地引擎失败仍给出「切远程」出路）。
    assert tr("ai_panel.advice_local") in text          # 对话流友好文案含出路
    assert tr("ai_panel.switch_remote") in seen["buttons"]   # 一键切换按钮
    assert tr("ai_panel.cancel") in seen["buttons"]
    assert dlg._chat_messages == []                     # 未获回复的提问已撤销
    assert dlg.btn_send.isEnabled() is True             # _busy(False) 已复位


def test_on_failed_click_switch_writes_openai(dlg, monkeypatch, tmp_path):
    """点击 [切换远程模型] → ai_config.json provider=openai + 只读模型行刷新。"""
    from PyQt6.QtWidgets import QPushButton
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)

    _builtin_first_send(dlg, monkeypatch, tmp_path)

    def fake_exec(self):
        for b in self.findChildren(QPushButton):
            if b.text() == tr("ai_panel.switch_remote"):
                # 默认参数提前绑定：否则 lambda 晚绑定捕获循环末值「取消」
                monkeypatch.setattr(self, "clickedButton", lambda b=b: b)
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    dlg._on_failed("ProviderError: 无法连接 Ollama")

    cfgs = [p for p in ai._config_paths() if p.exists()]
    assert cfgs, "切换后应存在 ai_config.json"
    # _load_config 取最近修改者；这里只有一个 tmp 候选
    data = json.loads(cfgs[-1].read_text(encoding="utf-8"))
    assert data["provider"] == "openai"
    # T-1018 归因：只读模型行只显示「当前模型：{模型名}」，厂商由档位/引擎解析
    assert "gpt-4o" in dlg.lbl_model.toolTip()
    assert dlg._source == "cloud"
    assert dlg._engine_for_current()["kind"] == "openai"
    assert "OpenAI" in _last_reply(dlg)                # 状态汇报入对话流


def test_on_failed_stop_is_lightweight(dlg, monkeypatch, tmp_path):
    """用户主动停止（CancelledError 路径）→ 轻量提示，不弹兜底框、不判失败。"""
    monkeypatch.setattr(QMessageBox, "exec",
                        lambda self: pytest.fail("停止不应弹模态框"))
    _builtin_first_send(dlg, monkeypatch, tmp_path)
    dlg._on_failed("已停止生成。")  # 绝不抛异常
    assert "已停止" in _last_reply(dlg)


def test_on_failed_followup_no_modal(dlg, monkeypatch, tmp_path):
    """追问（非首轮）+ 未知异常 → 对话流内出路提示，绝不弹模态。

    T-1018 归因（非静默）：原 ask 模式 → 现以 _turn>=2 表达「非首轮」。
    """
    monkeypatch.setattr(QMessageBox, "exec",
                        lambda self: pytest.fail("追问失败不应弹模态框"))
    _builtin_first_send(dlg, monkeypatch, tmp_path)
    dlg._turn = 2                                     # 非首轮（追问）
    dlg._chat_messages = [{"role": "user", "content": "追问"}]
    dlg._on_failed("ValueError: 完全没见过的错误")
    reply = _last_reply(dlg)
    assert reply == tr("ai_panel.ask_failed").format(
        msg="ValueError: 完全没见过的错误")
    assert "远程" in reply or "remote" in reply.lower()   # 给出路


def test_on_failed_cloud_provider_no_modal(dlg, monkeypatch, tmp_path):
    """云端 API（openai）失败 → 友好文案在对话流，不弹模态（非本地故障语义）。

    T-1020 归因（非静默）：原断言硬编码中文「远程」；文案迁 i18n 后改为断言
    云端档专属文案键，并**加严**——断言不再出现本地 Ollama 指向（B 项要求）。
    """
    monkeypatch.setattr(QMessageBox, "exec",
                        lambda self: pytest.fail("云端失败不应弹模态框"))
    _cloud_openai_first_send(dlg, monkeypatch, tmp_path)
    dlg._on_failed("ProviderError: 服务返回 401")
    reply = _last_reply(dlg)
    assert tr("ai_panel.err_auth") in reply
    assert tr("ai_panel.advice_cloud") in reply
    assert "Ollama" not in reply                        # 不再无条件指向本地服务
    assert dlg.btn_send.isEnabled() is True
