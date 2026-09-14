# SPDX-License-Identifier: GPL-3.0-only
"""T-1022 §3：模型推荐规则（纯函数表驱动；禁触网、禁真起进程）。

覆盖任务书 Step 6 的必测项：
- 表驱动：RAM 8 / 16 / 32 / 64GB × 磁盘充足/不足 → fit 正确；
- **纯文本条目不出现在任何推荐结果**（含 vision=False 显式断言）；
- `prefer_remote` 分支（可达 / 不可达）；
- 目录适配（GGUF / Ollama → 统一条目）与体积文案。
"""

import sys

sys.path.insert(0, "src")

from acouscope.ai import model_recommend as mr  # noqa: E402


def _entry(mid, *, vision=True, est=1_000_000_000, ram=8.0, tier=3.0,
           source="gguf"):
    return mr.CatalogEntry(model_id=mid, display_name=mid, vision=vision,
                           est_bytes=est, min_ram_gb=ram, tier_gb=tier,
                           source=source)


#: 真实目录形态的简化样本：1.8B / 3B / 7B（含一条纯文本条目做硬门禁反例）
_CATALOG = (
    _entry("tiny-1.8b", est=1_700_000_000, ram=8.0, tier=1.8),
    _entry("vl-3b", est=2_800_000_000, ram=8.0, tier=3.0),
    _entry("vl-7b", est=5_500_000_000, ram=24.0, tier=7.0),
    _entry("text-3b", vision=False, est=2_000_000_000, ram=8.0, tier=3.0),
)

_GB = 1024 ** 3


def _profile(ram_gb, disk_gb):
    from acouscope.ai.hardware import HardwareProfile
    return HardwareProfile(ram_gb=ram_gb, disk_free_gb=disk_gb)


def _fits(recs):
    return {r.model_id: r.fit for r in recs}


# ----------------------------------------------------------------------
# 表驱动：RAM × 磁盘
# ----------------------------------------------------------------------

def test_ram_tiers_with_plenty_of_disk():
    """RAM 8/16/32/64GB × 磁盘充足 → 推荐档位与最高可用档匹配。"""
    table = {
        8.0: ("tiny-1.8b", {"vl-7b": "insufficient_ram"}),
        16.0: ("vl-3b", {"vl-7b": "insufficient_ram"}),
        32.0: ("vl-7b", {}),
        64.0: ("vl-7b", {}),
    }
    for ram, (expected, extra) in table.items():
        recs = mr.recommend_models(_profile(ram, 500.0), _CATALOG)
        fits = _fits(recs)
        recommended = [r.model_id for r in recs if r.fit == "recommended"]
        assert recommended == [expected], f"RAM={ram} → {fits}"
        for mid, fit in extra.items():
            assert fits[mid] == fit, f"RAM={ram} → {fits}"
        assert recs[0].model_id == expected          # 推荐位排在最前


def test_insufficient_disk_marks_every_model():
    """磁盘不足（< 体积×1.2）→ 逐条标 insufficient_disk，且不给推荐位。"""
    recs = mr.recommend_models(_profile(64.0, 1.0), _CATALOG)   # 仅 1GB 可用
    fits = _fits(recs)
    assert set(fits.values()) == {"insufficient_disk"}
    assert all("磁盘" in r.reason for r in recs)


def test_disk_boundary_uses_1_2_margin():
    """边界：略高于体积×1.2 → 通过；略低 → insufficient_disk。"""
    need_gb = 2_800_000_000 * mr.DISK_MARGIN / _GB
    ok_recs = _fits(mr.recommend_models(_profile(16.0, need_gb * 1.01), _CATALOG))
    assert ok_recs["vl-3b"] in ("recommended", "ok")
    low_recs = _fits(mr.recommend_models(_profile(16.0, need_gb * 0.99), _CATALOG))
    assert low_recs["vl-3b"] == "insufficient_disk"
    assert low_recs["tiny-1.8b"] in ("recommended", "ok")   # 体积更小仍可用


def test_ram_none_never_recommends():
    """硬件探测不可得（ram None）→ 不做内存匹配、不给推荐位（诚实口径）。"""
    recs = mr.recommend_models(_profile(None, 500.0), _CATALOG)
    assert "recommended" not in _fits(recs).values()
    assert all(r.fit == "ok" for r in recs)


def test_insufficient_ram_is_soft_hint_not_filtered():
    """内存不足 = 软提示：仍出现在列表里（高级用户可自行承担风险）。"""
    recs = mr.recommend_models(_profile(8.0, 500.0), _CATALOG)
    assert "vl-7b" in _fits(recs)
    assert all("仍可" in r.reason for r in recs if r.fit == "insufficient_ram")


# ----------------------------------------------------------------------
# 硬门禁：vision=False 不出现
# ----------------------------------------------------------------------

def test_text_only_never_appears_in_results():
    """硬约束：`vision=False` 的条目**不得出现在任何推荐结果中**（锁死）。"""
    recs = mr.recommend_models(_profile(64.0, 500.0), _CATALOG)
    assert "text-3b" not in _fits(recs)
    assert all(r.entry.vision is True for r in recs)
    assert "text-3b" not in [e.model_id for e in mr.vision_entries(_CATALOG)]


def test_text_only_filtered_even_when_only_candidate():
    """目录全是纯文本 → 推荐结果为空（绝不退而推荐不可读图的模型）。"""
    only_text = (_entry("a", vision=False), _entry("b", vision=False))
    assert mr.recommend_models(_profile(64.0, 500.0), only_text) == ()


def test_vision_none_or_missing_is_filtered():
    """vision 为 None / 缺失 → 保守过滤（未知能力不进推荐）。"""
    class _Bare:
        model_id = "bare"
        display_name = "bare"
        est_bytes = 1
        min_ram_gb = 1.0
        tier_gb = 1.0
        source = "gguf"

    assert mr.vision_entries((_Bare(),)) == ()


# ----------------------------------------------------------------------
# 外部服务（prefer_remote）
# ----------------------------------------------------------------------

def test_prefer_remote_reachable_and_unreachable():
    """探测可达 → True 并回吐服务根地址；不可达 → None / False（静默）。"""
    assert mr.detect_remote_service(
        endpoints=("http://x/v1/models",),
        probe_fn=lambda url, t: True) == "http://x"
    assert mr.detect_remote_service(
        endpoints=("http://x/v1/models",),
        probe_fn=lambda url, t: False) is None
    assert mr.prefer_remote(remote="http://x") is True
    assert mr.prefer_remote(remote="") is False
    assert mr.prefer_remote(endpoints=("http://x/v1/models",),
                            probe_fn=lambda u, t: True) is True


def test_prefer_remote_probe_never_raises():
    """探测函数抛异常 / 超时 → 静默 False（绝不向上抛、绝不阻塞）。"""
    def _boom(url, timeout):
        raise OSError("refused")

    assert mr.detect_remote_service(endpoints=("http://x/v1/models",),
                                    probe_fn=_boom) is None
    assert mr.prefer_remote(endpoints=("http://x/v1/models",),
                            probe_fn=_boom) is False


def test_service_root_normalisation():
    assert mr._service_root("http://192.168.0.2:8000/v1/models") \
        == "http://192.168.0.2:8000"
    assert mr._service_root("http://a:1/v1/") == "http://a:1"


def test_remote_reachable_hint_in_reason():
    """已探到现成服务 → 推荐理由里提示「免下载可用」。"""
    recs = mr.recommend_models(_profile(16.0, 500.0), _CATALOG,
                               remote_reachable=True)
    top = recs[0]
    assert top.fit == "recommended" and "无需下载" in top.reason


# ----------------------------------------------------------------------
# 目录适配 / 体积文案
# ----------------------------------------------------------------------

def test_size_text_units():
    assert mr.size_text(2_774_658_784) == "2.8 GB"
    assert mr.size_text(844_757_728) == "845 MB"
    assert mr.size_text(0) == "0 MB"


def test_real_catalog_has_only_vision_entries():
    """真实目录适配：内置档条目全部可读图（纯文本已被目录下架 + 出口过滤）。"""
    entries = mr.builtin_catalog()
    assert entries, "内置档视觉目录不得为空"
    assert all(e.vision for e in entries)
    ids = [e.model_id for e in entries]
    assert "qwen2.5-vl-3b-instruct-q4_k_m" in ids      # 受管 GGUF（本机推荐档）
    assert "moondream" in ids                          # 内置 Ollama 官方档
    assert "spark-x2.5-1.7b" not in ids                # 纯文本档已下架
    assert "qwen2.5:3b" not in ids
    gguf = mr.gguf_catalog()
    assert all(e.source == "gguf" and e.est_bytes > 1e9 for e in gguf)


def test_real_catalog_recommends_3b_on_16gb():
    """验收口径：本机 M4/16GB → 推荐 qwen2.5-vl-3b-instruct。"""
    recs = mr.recommend_models(_profile(16.0, 500.0), mr.builtin_catalog())
    assert recs[0].model_id == "qwen2.5-vl-3b-instruct-q4_k_m"
    assert recs[0].fit == "recommended"
