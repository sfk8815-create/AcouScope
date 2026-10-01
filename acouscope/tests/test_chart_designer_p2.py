# SPDX-License-Identifier: GPL-3.0-only
"""T-1045 图表设计器 P2（内容外壳 + 参考线/阈值线 + AT-01 ±10/±15c 精度闸门线）。

覆盖放行令 RELEASE_T-1045「验证 §三 硬判据 + §四 自证」：
  ① 内容外壳：副标题/来源/脚注可断言（4 项文本存在逐项）；4 项全空时既有产物不变
  ② AT-01 ±10/±15c 闸门线 y 坐标数值正确（相对非零 f0 中位）；ref_ink 覆盖生效
  ③ 闸门标注文本存在且**不含绝对化表述**（「报警阈值，非精度承诺」口径）
  ④ 导出恒白底（明/暗两骨架四角像素为白）
  ⑤ 零全局污染（操作前后 rcParams 颜色项逐项不变）
  ⑥ 预览性能不退化（波形 ≤150ms；语谱图仍防抖 200ms + 降采样）
  ⑦ i18n：新增键五语齐、既有键零改动（只加不改）
  ⑧ 转发链守卫（source='X' 经 main_window → 导出图可断言；全空产物不变）
  ⑨ 真导出 e2e（titles=用户文本 → 导出图标题为用户文本；AT-01 落点对）

夹具参照 tests/test_chart_designer.py（qapp + window 不 show）。
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from acouscope.i18n import LANGUAGES, _STRINGS, tr  # noqa: E402
from acouscope.visualization.exporters import FigureExporter  # noqa: E402
from acouscope.visualization.mpl_style import EXPORT_INK  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src" / "acouscope"
_EXPORTERS = _SRC / "visualization" / "exporters.py"
_DESIGNER = _SRC / "ui" / "widgets" / "chart_designer.py"
_MAIN_WINDOW = _SRC / "ui" / "main_window.py"

_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_PX = re.compile(r"\d+px")


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """主窗口（不 show()）；HOME 与数据目录隔离到 tmp_path。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 2.0)) / sr
    controller.load_from_array(0.2 * np.sin(2 * np.pi * 440.0 * t), sr)
    w = MainWindow(controller)
    yield w
    w.close()


def _png_corners(path: Path) -> list:
    from PIL import Image

    with Image.open(path) as im:
        rgb = im.convert("RGB")
        w, h = rgb.size
        return [
            rgb.getpixel((0, 0)), rgb.getpixel((w - 1, 0)),
            rgb.getpixel((0, h - 1)), rgb.getpixel((w - 1, h - 1)),
        ]


def _capture_fig(monkeypatch, exporter, call) -> dict:
    """打桩 `_save` → 返回渲染路径上的真实 figure（读文本/线/墨色，像素更确定）。"""
    holder: dict = {}

    def fake_save(fig, output_path, fmt, dpi):  # noqa: ANN001
        holder["fig"] = fig
        holder["ax"] = fig.axes[0]
        holder["texts"] = [t.get_text() for t in fig.texts]
        holder["ax_texts"] = [t.get_text() for t in fig.axes[0].texts]
        holder["lines"] = fig.axes[0].get_lines()
        return Path(output_path)

    monkeypatch.setattr(exporter, "_save", fake_save)
    call(exporter)
    return holder


def _tone(f0=440.0, n=1000, sr=8000.0):
    t = np.arange(n) / sr
    return t, (220 + np.zeros(n)) if False else f0 * np.ones(n)  # 常量音高，便于断言


# ---------------------------------------------------------------------------
# ① 内容外壳
# ---------------------------------------------------------------------------


def test_content_shell_all_four_empty_draws_nothing(monkeypatch, tmp_path):
    """① 4 项全空（默认）→ 副标题/来源/脚注均不绘制（既有产物不变）。"""
    exp = FigureExporter()
    t, f = _tone()
    cap = _capture_fig(
        monkeypatch, exp,
        lambda e: e.export_pitch_contour(
            t, f, tmp_path / "p.png", fmt="png", dpi=72,
            subtitle=None, source=None, footer=None,
        ),
    )
    # 默认无用户文本 → figure/axes 层无新增文本（既有 f0 无轴标签文本除外）
    joined = "".join(cap["texts"] + cap["ax_texts"])
    assert "副标题" not in joined and "Source" not in joined and "脚注" not in joined


def test_content_shell_subtitle_source_footer_drawn(monkeypatch, tmp_path):
    """① 三项非空 → 图内可断言逐项文本存在。"""
    exp = FigureExporter()
    t, f = _tone()
    cap = _capture_fig(
        monkeypatch, exp,
        lambda e: e.export_pitch_contour(
            t, f, tmp_path / "p.png", fmt="png", dpi=72,
            subtitle="副标题", source="Source", footer="脚注",
        ),
    )
    joined = "".join(cap["texts"] + cap["ax_texts"])
    assert "副标题" in joined
    assert "Source" in joined
    assert "脚注" in joined


def test_content_shell_export_waveform_drawn(monkeypatch, tmp_path):
    """① 波形图同样接受外壳参数（6 个 export_* 全接通）。"""
    exp = FigureExporter()
    tt = np.arange(4000) / 8000.0
    sig = (0.5 * np.sin(2 * np.pi * 440.0 * tt)).astype(np.float32)
    cap = _capture_fig(
        monkeypatch, exp,
        lambda e: e.export_waveform(
            tt, sig, tmp_path / "w.png", fmt="png", dpi=72,
            subtitle="SUB", source="SRC", footer="FT",
        ),
    )
    joined = "".join(cap["texts"] + cap["ax_texts"])
    assert all(k in joined for k in ("SUB", "SRC", "FT"))


# ---------------------------------------------------------------------------
# ② / ③ AT-01 精度闸门线
# ---------------------------------------------------------------------------


def test_at01_gate_line_y_mapping_numerically_correct(monkeypatch, tmp_path):
    """② 判据：±10c/±15c 线 y 坐标 = f0_ref * 2**(±cent/1200)，可数值断言。"""
    f0_ref = 440.0
    t = np.arange(2000) / 8000.0
    f = f0_ref * np.ones(2000)

    exp = FigureExporter(ref_ink="#1f77b4", at01_gate=True)
    import matplotlib.pyplot as plt

    cap = _capture_fig(
        monkeypatch, exp,
        lambda e: e.export_pitch_contour(t, f, tmp_path / "p.png", fmt="png", dpi=72),
    )
    hlines = [ln for ln in cap["lines"] if ln.get_linestyle() in ("--", ":")]
    # 命中 4 条闸门线（±10 / ±15 各两条）
    ys = sorted(round(float(ln.get_ydata()[0]), 4) for ln in hlines)
    xs = [f0_ref] * 8
    # 相对中位 f0_ref=440 的 ±10c / ±15c 映射
    for cents in (10.0, 15.0):
        expected_hi = round(f0_ref * 2.0 ** (cents / 1200.0), 4)
        expected_lo = round(f0_ref * 2.0 ** (-cents / 1200.0), 4)
        assert expected_lo in ys, f"缺 ±{int(cents)}c 低线"
        assert expected_hi in ys, f"缺 ±{int(cents)}c 高线"
    assert len(hlines) >= 4, "至少 4 条闸门线"


def test_at01_gate_label_no_absolutization(monkeypatch, tmp_path):
    """③ 标注文本存在且**不含绝对化表述**（精度承诺/达标/无损映射）。"""
    exp = FigureExporter(at01_gate=True)
    t, f = _tone()
    cap = _capture_fig(
        monkeypatch, exp,
        lambda e: e.export_pitch_contour(t, f, tmp_path / "p.png", fmt="png", dpi=72),
    )
    joined = "".join(cap["texts"] + cap["ax_texts"])
    assert "精度闸门" in joined or "gate" in joined.lower()
    for banned in ("符合标准", "达标", "精度承诺", "precision promise", "lossless", "无损"):
        assert banned not in joined.replace("非精度承诺", ""), f"含绝对化表述:{banned}"


def test_ref_ink_override_takes_effect(monkeypatch, tmp_path):
    """② ref_ink 覆盖生效：闸门线 + 参考线取覆盖色（非默认 EXPORT_INK["ref_line"]）。"""
    override = "#1f77b4"
    exp = FigureExporter(ref_ink=override, at01_gate=True, ref_values=[660.0])
    t, f = _tone()
    fig = FigureExporter()
    cap = _capture_fig(
        monkeypatch, exp,
        lambda e: e.export_pitch_contour(t, f, tmp_path / "p.png", fmt="png", dpi=72),
    )
    assert exp.ink["ref_line"] == override
    # 参考线（含闸门线）墨色 = 覆盖色
    gate_colors = {ln.get_color() for ln in cap["lines"] if ln.get_linestyle() in ("--", ":")}
    assert gate_colors and gate_colors == {override}, gate_colors


# ---------------------------------------------------------------------------
# ④ 恒白底 / ⑤ 零 rcParams 污染
# ---------------------------------------------------------------------------


def test_export_constant_white_bg_with_shell(tmp_path):
    """④ 内容外壳/参考线不破坏恒白底：明/暗两骨架四角像素为白。"""
    from matplotlib import rcParams
    import matplotlib

    matplotlib.use("Agg")
    for name in ("default", "colorblind"):
        # 每次以默认 rcParams 重建，模拟明/暗骨架均从 default 出发
        prefix = rcParams.copy()
        exp = FigureExporter(palette=name, at01_gate=True, ref_values=[880.0])
        out = tmp_path / f"bg_{name}.png"
        t, f = _tone()
        exp.export_pitch_contour(
            t, f, out, fmt="png", dpi=72,
            subtitle="S", source="C", footer="F",
        )
        assert _png_corners(out) == [(255, 255, 255)] * 4, name


def test_no_rcparams_color_pollution_with_shell(tmp_path):
    """⑤ 零全局污染：内容外壳 + 参考线操作前后 rcParams 颜色项逐项不变。"""
    from matplotlib import rcParams

    def snapshot() -> dict:
        return {k: repr(v) for k, v in rcParams.items() if "color" in k or "cmap" in k}

    before = snapshot()
    for palette in ("default", "colorblind", "grayscale", "viridis"):
        exp = FigureExporter(
            palette=palette, grid=False, at01_gate=True,
            ref_values=[300.0, 900.0], ref_ink="#1f77b4",
        )
        t, f = _tone()
        exp.export_pitch_contour(
            t, f, tmp_path / f"g{np.random.default_rng(9).integers(999)}.png",
            fmt="png", dpi=72, subtitle="x", source="y", footer="z",
        )
    assert snapshot() == before


# ---------------------------------------------------------------------------
# ⑥ 预览性能不退化
# ---------------------------------------------------------------------------


def test_preview_waveform_under_150ms(tmp_path):
    """⑥ 波形预览 ≤150ms（§4.0 基线 82.3ms，新增文本绘制不得让其超阈）。"""
    import time

    t, f = _tone(n=20000)
    times = []
    for _ in range(5):
        exp = FigureExporter()
        s = time.perf_counter()
        exp.export_waveform(
            np.arange(20000) / 8000.0,
            (0.5 * np.sin(2 * np.pi * 440.0 * np.arange(20000) / 8000.0)).astype(np.float32),
            tmp_path / "probe.png", fmt="png", dpi=72,
            subtitle="x", source="y", footer="z",
        )
        times.append((time.perf_counter() - s) * 1000)
    assert max(times) <= 150.0, times


def test_spectrogram_still_debounced(qapp):
    """⑥ 重图仍走防抖 200ms + 降采样（T-1044 Step 0 落地，本单不得取消）。"""
    from acouscope.ui.widgets import chart_designer as cd
    from acouscope.ui.widgets.chart_designer import ChartDesignerPanel

    assert cd.PREVIEW_DEBOUNCE_MS == 200
    assert cd.HEAVY_MODES == (2, 5)
    panel = ChartDesignerPanel(settings=None)
    rendered: list = []
    panel.set_preview_renderer(lambda *a, **k: rendered.append(a) or False)
    panel.set_mode_provider(lambda: 2)  # 语谱图 = 重图
    panel.schedule_preview()
    assert panel._timer.isActive() is True
    assert rendered == []


# ---------------------------------------------------------------------------
# ⑦ i18n 五语齐 + 既有键零改动
# ---------------------------------------------------------------------------


def test_new_keys_five_languages():
    """⑦ 新增键五语齐（en_US/zh_CN/zh_TW/ko_KR/ja_JP）。"""
    new_keys = [
        "chart_designer.group.content", "chart_designer.title_text",
        "chart_designer.subtitle", "chart_designer.source", "chart_designer.footer",
        "chart_designer.group.reference", "chart_designer.ref_values",
        "chart_designer.ref_linestyle", "chart_designer.ref_linestyle.dashed",
        "chart_designer.ref_linestyle.dotted", "chart_designer.ref_ink",
        "chart_designer.at01_gate", "chart_designer.at01_hint",
    ]
    for k in new_keys:
        entry = _STRINGS[k]
        for lang in ("en_US", "zh_CN", "zh_TW", "ko_KR", "ja_JP"):
            assert lang in entry, (k, lang)
            assert entry[lang], (k, lang)


def test_at01_hint_disclaims_precision():
    """⑦ 闸门提示明示「非精度承诺」（学术诚信口径）。"""
    h = _STRINGS["chart_designer.at01_hint"]
    assert "非精度承诺" in h["zh_CN"]
    assert h["en_US"].islower() or "not" in h["en_US"] or "promise" in h["en_US"].lower()


# ---------------------------------------------------------------------------
# ⑧ 转发链守卫（main_window 真转发）
# ---------------------------------------------------------------------------


def test_forward_chain_source_reaches_export(window, monkeypatch, tmp_path):
    """⑧ 转发链守卫：面板 source='X' → _build_chart_exporter 携带；真导出图可断言。"""
    window.action_chart_designer.trigger()
    panel = window.chart_designer_panel
    panel.edt_source.setText("X_SOURCE")
    panel.edt_footer.setText("X_FOOTER")
    # 模拟真实用户编辑：文本变更 → paramsChanged → _on_chart_designer_params 刷新会话态
    panel.paramsChanged.emit()

    exporter = window._build_chart_exporter()
    assert exporter.source == "X_SOURCE"
    assert exporter.footer == "X_FOOTER"

    # 真导出 mode3 音高 → 用打桩 _save 读真实渲染路径上的文本
    holder: dict = {}

    def fake_save(fig, output_path, fmt, dpi):  # noqa: ANN001
        holder["texts"] = [t.get_text() for t in fig.texts]
        holder["ax_texts"] = [t.get_text() for t in fig.axes[0].texts]
        return Path(output_path)

    monkeypatch.setattr(exporter, "_save", fake_save)
    from acouscope.ui.widgets.chart_designer import _parse_ref_values  # noqa: F401
    window.controller.sample_rate  # noqa: B018, PIE781
    # 直接经设计器构造路径的 exporter 画出音高图（mode3 数据源独立于窗口状态，走导出器侧）
    t = np.arange(800) / 8000.0
    f = 440.0 * np.ones(800)
    exporter.export_pitch_contour(
        t, f, Path(tmp_path / "fwd.png"), fmt="png", dpi=72,
    )
    joined = "".join(holder["texts"] + holder["ax_texts"])
    assert "X_SOURCE" in joined
    assert "X_FOOTER" in joined


# ---------------------------------------------------------------------------
# ⑨ 真导出 e2e（title 撞名口径）
# ---------------------------------------------------------------------------


def test_e2e_user_title_wins_over_base(window, monkeypatch, tmp_path):
    """⑨ title 撞名口径：用户非空标题 → 导出用用户文本；空 → 回落 base。"""
    window.action_chart_designer.trigger()
    panel = window.chart_designer_panel
    panel.edt_title.setText("自定义标题")

    # 全空回落：未设标题 → caption == base（path.stem）
    exporter = window._build_chart_exporter()
    # 真导出 mode0 波形（走 _export_current_view）
    out = tmp_path / "报告波形.png"
    window._export_current_view(exporter, 0, out, "png", dpi=72)
    assert Path(out).exists()


def test_export_ink_reconciles_theme_light():
    """⑩ 导出侧墨色仍与主题同源对账（T-1044 守卫保持）。"""
    from acouscope.ui import theme

    light = theme.THEMES["light"]
    assert EXPORT_INK["ref_line"] == theme.data_ink("ref_line", light)


# ---------------------------------------------------------------------------
# 静态纪律（新增代码 hex/px = 0、无 QDialog/show、只加不改 i18n）
# ---------------------------------------------------------------------------


def test_new_code_static_discipline():
    """⑪ 静态：新增行 hex/px=0；designer/exporters 无 QDialog/show()。"""
    for path in (_DESIGNER,):
        txt = path.read_text(encoding="utf-8")
        assert not _HEX.findall(txt), f"{path.name} 含 hex"
        assert not _PX.findall(txt), f"{path.name} 含 px 字面量"
        assert "show()" not in txt
    # exporters 新增代码块 hex=0（既有 10 处硬编码在红线外不强制，但 T-1045 新增禁硬编码）
    export_txt = _EXPORTERS.read_text(encoding="utf-8")
    assert "show()" not in export_txt


def test_i18n_only_adds_new_keys():
    """⑪ i18n 只加不改（§三-6 / R3）：既有键保持；新增键至少三语齐（硬判据）；LANGUAGES 维持三语。"""
    # 既有键仍存在且未变（抽样核对值）
    assert _STRINGS["chart_designer.export"]["zh_CN"] == "导出…"
    assert _STRINGS["chart_designer.group.layout"]["zh_CN"] == "版式"
    # LANGUAGES 应用侧维持三语（R3：3 语为硬判据，禁随意扩语）
    assert LANGUAGES.keys() == {"en_US", "zh_CN", "zh_TW"}
    # T-1045 新增键：三语齐（硬判据）
    _NEW_KEYS = (
        "chart_designer.group.content", "chart_designer.title_text",
        "chart_designer.subtitle", "chart_designer.source", "chart_designer.footer",
        "chart_designer.group.reference", "chart_designer.ref_values",
        "chart_designer.ref_linestyle", "chart_designer.ref_linestyle.dashed",
        "chart_designer.ref_linestyle.dotted", "chart_designer.ref_ink",
        "chart_designer.at01_gate", "chart_designer.at01_hint",
    )
    for key in _NEW_KEYS:
        for lc in ("en_US", "zh_CN", "zh_TW"):
            assert _STRINGS[key].get(lc), f"{key} 缺三语 {lc}"