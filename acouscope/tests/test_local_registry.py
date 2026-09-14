# SPDX-License-Identifier: GPL-3.0-only
"""T-303: 官方模型注册表 + Ollama 环境自检（monkeypatch mock，禁真实网络）。"""
import sys
sys.path.insert(0, "src")
from acouscope.ai.backends import local_registry as lr  # noqa: E402


def test_registry_shape():
    """T-1022 归因（非静默）：官方目录整体替换——纯文本档（spark-x2.5-1.7b /
    qwen2.5:3b）全部下架（释图窗的本质是释图，本地档必须能读图），现目录只保留
    **视觉**模型。原「is_default 必须是 spark / 全部 text_only=True」的断言已失效，
    改写为等价强度的新契约：目录非空、每条 vision=True 且 text_only=False、
    带 est_bytes（实测）与 min_ram_gb、恰有一条默认推荐、下架名进 LEGACY_TEXT_ONLY。
    """
    assert lr.OFFICIAL_MODELS, "视觉目录不得为空"
    defaults = [n for n, m in lr.OFFICIAL_MODELS.items() if m.get("is_default")]
    assert len(defaults) == 1
    for name, m in lr.OFFICIAL_MODELS.items():
        assert m["vision"] is True, f"{name} 非视觉却上架（硬门禁）"
        assert m["text_only"] is False, f"{name} text_only 应为 False"
        assert m["est_bytes"] > 1e8
        assert m["min_ram_gb"] > 0
        assert m.get("tier_gb", 0) > 0
    # 纯文本档已下架：既不进目录，也不得再作为可选项
    assert "spark-x2.5-1.7b" not in lr.OFFICIAL_MODELS
    assert "qwen2.5:3b" not in lr.OFFICIAL_MODELS
    assert {"spark-x2.5-1.7b", "qwen2.5:3b"} <= set(lr.LEGACY_TEXT_ONLY)


def test_probe_down(monkeypatch):
    def boom(*a, **k):
        raise OSError("refused")
    monkeypatch.setattr(lr.urllib.request, "urlopen", boom)
    ok, models = lr.probe_ollama()
    assert ok is False and models == []


def test_probe_up(monkeypatch):
    class R:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return b'{"models":[{"name":"spark-x2.5-1.7b:latest"}]}'
    monkeypatch.setattr(lr.urllib.request, "urlopen", lambda *a, **k: R())
    ok, models = lr.probe_ollama()
    assert ok and models == ["spark-x2.5-1.7b:latest"]


def test_missing_calc():
    """T-1022 归因（非静默）：缺失计算按**新视觉目录**（原用例引用的
    spark-x2.5-1.7b / qwen2.5:3b 纯文本档已整体下架）。契约不变：带 :tag 与
    裸名互认、Ollama 不可用视为全部缺失。"""
    names = list(lr.OFFICIAL_MODELS)
    assert len(names) >= 2
    assert lr.get_missing_official_models([names[0] + ":latest"]) == names[1:]
    assert lr.get_missing_official_models(list(names)) == []
    assert len(lr.get_missing_official_models([])) == len(names)


def test_guidance_branches(monkeypatch):
    # V099_RUNTIME_V1（AT-410 零终端）：文案改为本地引擎状态，不再含任何终端/URL 指引
    monkeypatch.setattr(lr, "probe_ollama", lambda timeout=0.8, base_url=None: (False, []))
    assert "本地引擎未就绪" in lr.guidance_text()
    monkeypatch.setattr(lr, "probe_ollama", lambda timeout=0.8, base_url=None: (True, []))
    monkeypatch.setattr(lr, "get_missing_official_models",
                        lambda available=None: ["spark-x2.5-1.7b"])
    txt = lr.guidance_text()
    assert "模型尚未下载" in txt
    assert "设置-AI" in txt


_BANNED = ["终端", "ollama serve", "ollama pull", "ollama.com", "http", "请安装", "brew"]


def test_guidance_zero_terminal(monkeypatch):
    """AT-410 零终端铁律：两分支文案均不含任何命令行/URL/安装指引。"""
    monkeypatch.setattr(lr, "probe_ollama", lambda timeout=0.8, base_url=None: (False, []))
    for w in _BANNED:
        assert w not in lr.guidance_text()
    monkeypatch.setattr(lr, "probe_ollama", lambda timeout=0.8, base_url=None: (True, []))
    for w in _BANNED:
        assert w not in lr.guidance_text()


def test_probe_base_url_param(monkeypatch):
    """base_url 参数直连指定地址（V099_RUNTIME_V1 路由入口）。"""
    seen = []

    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"models":[]}'

    def fake_urlopen(req, timeout=None):
        seen.append(req.full_url)
        return R()

    monkeypatch.setattr(lr.urllib.request, "urlopen", fake_urlopen)
    ok, models = lr.probe_ollama(base_url="http://127.0.0.1:9999")
    assert ok is True and models == []
    assert seen == ["http://127.0.0.1:9999/api/tags"]
