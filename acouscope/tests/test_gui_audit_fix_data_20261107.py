# SPDX-License-Identifier: GPL-3.0-only
"""真机 GUI 审计「数据读数 / 呈现」层 4 项缺陷守卫（F2/F3/F4/F6，2026-11-07）。

全部离屏（conftest 已设 QT_QPA_PLATFORM=offscreen）：不构造 MainWindow、
不跑事件循环、不 exec 模态框、不留长驻进程。4 个用例各自对应一处修复，
并在交付时逐条做过「改回旧态 → 断言翻红 → 反向替换撤销 → 回绿」变异自检：

- F2：pitch.cents 读数明确标注「相对 A4 参考频率」基准。i18n 三语 value
  （仓库真值：LANGUAGES 仅注册 en_US/zh_CN/zh_TW，ko_KR/ja_JP 是 backlog，
  见 IM45_parity_baseline.json「ko/ja 随批后补」）同步标注 A4；lbl_cents
  挂 tooltip + accessibleDescription 说明口径；hz_to_cents 数值口径不变。
- F3：FormantWidget 构造期轴标签走 freq_axis.set_freq_axis_label 单一数据源，
  不再硬写 Hz；下拉切换 kHz/Hz/MIDI/钢琴/音分/Mel 后轴标题/单位与所选一致。
- F4：谱波标记表第 5 列表头「相对幅度 (dBr)」+ 表头/单元格口径 tooltip；
  mag_db 归一化公式不变（最强峰恒 0.0）。
- F6：MFCC 稳健动态范围 lo<median<hi、256 级 LUT 去重索引 ≥8（打印实测数字），
  且 mfcc_img / mfcc_bar_img / mfcc_colorbar 共用同一组 lo,hi。

各用例的「变异点」在实现侧，实现记录逐条记录三段（变异前 / 红文 / 撤销后）。
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PyQt6")

import pyqtgraph as pg  # noqa: E402

# 仓库真值：i18n 仅三语齐备（ko_KR/ja_JP 为 backlog 单调闸，见 parity guard）
_I18N_LOCALES = ("en_US", "zh_CN", "zh_TW")


# ---------------------------------------------------------------------------
# F2：pitch.cents 读数 A4 基准消歧
# ---------------------------------------------------------------------------


def test_F2_pitch_cents_marks_A4_basis(qapp):
    """三语 value 标注 A4、结构/占位符零改动、数值口径不变、tooltip/a11y 齐备。"""
    import acouscope.i18n as i18n
    from acouscope.dsp.units import hz_to_cents
    from acouscope.ui.widgets.pitch import PitchContourWidget

    # ① 两个 key 的三语 value 同步标注 A4 基准；key 集合 / 结构零改动
    for key in ("pitch.cents", "pitch.cents_none"):
        entry = i18n._STRINGS[key]
        assert set(entry) == set(_I18N_LOCALES), (key, sorted(entry))
        for lang in _I18N_LOCALES:
            assert "A4" in entry[lang], (key, lang, entry[lang])
    # 占位符保留（既有 .format(value=...) 契约 / hover 反对照守卫）
    assert "{value}" in i18n._STRINGS["pitch.cents"]["en_US"]
    assert "A4" in i18n.tr("pitch.cents").format(value="+0")

    # ② 数值计算不得改：260.4 Hz 相对 A4=440 约 -908 音分（绝对音分口径）
    assert float(hz_to_cents(260.4)) == pytest.approx(-908.0, abs=1.0)

    # ③ lbl_cents 的 tooltip + 读屏描述说明口径（区分谱波表的「音分偏差」）
    w = PitchContourWidget()
    try:
        tip = w.lbl_cents.toolTip()
        desc = w.lbl_cents.accessibleDescription()
        assert tip and desc, (tip, desc)
        assert "A4" in tip and "A4" in desc, (tip, desc)
        assert "相对" in tip and "音分偏差" in tip, tip
        assert tip == desc, "tooltip 与 accessibleDescription 应同源"
    finally:
        w.close()
        w.deleteLater()


# ---------------------------------------------------------------------------
# F3：FormantWidget 构造期轴标签单一数据源
# ---------------------------------------------------------------------------


def test_F3_formants_axis_label_single_source(qapp, monkeypatch):
    """哨兵注入 FREQ_AXIS_LABELS["hz"]：构造期轴标签必须取自该字典（非硬写）。"""
    from acouscope.ui.widgets import freq_axis
    from acouscope.ui.widgets.formants import FormantWidget

    sentinel_text, sentinel_units = "SENT-FREQ-LABEL", "SENT-U"
    monkeypatch.setitem(freq_axis.FREQ_AXIS_LABELS, "hz",
                        (sentinel_text, sentinel_units))

    w = FormantWidget()
    try:
        ax = w.plot_widget.getAxis("left")
        # 构造期单一数据源：哨兵能从 FREQ_AXIS_LABELS 流到轴标签 → 证明非硬写
        assert ax.labelText == sentinel_text, ax.labelText
        assert ax.labelUnits == sentinel_units, ax.labelUnits

        # 下拉切换后轴标题/单位与所选一致（含 kHz/Hz/MIDI/钢琴/音分/Mel）。
        # 对照法：同一函数作用于 ref widget 的读回值即期望值，规避 pyqtgraph
        # 对 units=None 读回 '' 的语义差异。
        times = np.linspace(0.0, 1.0, 40)
        fw = np.tile([500.0, 1500.0, 2500.0], (40, 1))
        w.set_data(times, fw, fw * 0.1)
        ref = pg.PlotWidget()
        for i in range(w.cmb_y_unit.count()):
            key = w.cmb_y_unit.itemData(i)
            w.cmb_y_unit.setCurrentIndex(i)
            freq_axis.set_freq_axis_label(ref, key)
            cur = w.plot_widget.getAxis("left")
            ref_ax = ref.getAxis("left")
            assert cur.labelText == ref_ax.labelText, (
                key, cur.labelText, ref_ax.labelText)
            assert cur.labelUnits == ref_ax.labelUnits, (
                key, cur.labelUnits, ref_ax.labelUnits)
    finally:
        w.close()
        w.deleteLater()


# ---------------------------------------------------------------------------
# F4：谱波标记表幅度列相对口径
# ---------------------------------------------------------------------------


def test_F4_marks_table_mag_relative_header_and_tooltip(qapp):
    """第 5 列表头「相对幅度 (dBr)」+ 表头/单元格 tooltip + mag_db 公式不变。"""
    from acouscope.ui.widgets.spectrum import SpectrumWidget

    w = SpectrumWidget()
    try:
        hdr = w.marks_table.horizontalHeaderItem(4)
        assert hdr is not None
        assert hdr.text() == "相对幅度 (dBr)", hdr.text()
        assert "相对" in hdr.text() and "dBr" in hdr.text(), hdr.text()
        tip = hdr.toolTip()
        assert "相对" in tip and "最强峰" in tip, tip

        # 构造两个标记（最强峰幅度 1.0）→ 单元格 tooltip 与表头同源
        w._manual_peaks = [
            {"freq": 440.0, "magnitude": 1.0, "note": "A4", "cents": 0.0},
            {"freq": 880.0, "magnitude": 0.5, "note": "A5", "cents": 0.0},
        ]
        w._update_marks_table()
        cell = w.marks_table.item(0, 4)
        assert cell is not None
        assert cell.toolTip() == tip, (cell.toolTip(), tip)

        # mag_db 计算公式不得改：相对最强峰归一化 → 最强峰恒 0.0
        rows = w._build_table_rows()
        mags = [float(r[4]) for r in rows]
        assert max(mags) == 0.0, mags
        assert min(mags) < 0.0, mags
    finally:
        w.close()
        w.deleteLater()


# ---------------------------------------------------------------------------
# F6：MFCC 稳健动态范围（多色阶 + 三对象共用同一 lo,hi）
# ---------------------------------------------------------------------------


def _lut_distinct(finite, lo, hi):
    """按 (lo,hi) 线性映射到 256 级 LUT 后的去重索引数（模拟 ImageItem 映射）。"""
    idx = np.clip((finite - lo) / (hi - lo) * 255.0, 0, 255).astype(int)
    return int(np.unique(idx).size)


def test_F6_mfcc_robust_levels_and_shared_source(qapp):
    """lo<median<hi、LUT 去重索引 ≥8（打印实测数字）；NaN 退化稳健；三对象同源。"""
    from acouscope.ui.widgets.timbre import TimbreWidget, _mfcc_display_levels

    rng = np.random.default_rng(20261107)
    # 典型 MFCC 矩阵 A：13 阶 × 120 帧，连续时间渐变 + 第 0 阶能量偏置
    a = rng.normal(0, 20, (13, 120)) + np.linspace(-30, 30, 120)[None, :]
    a[0, :] += 80.0

    finite_a = a[np.isfinite(a)]
    med_a = float(np.median(finite_a))
    lo_a, hi_a = _mfcc_display_levels(a)
    assert np.isfinite(lo_a) and np.isfinite(hi_a), (lo_a, hi_a)
    assert lo_a < med_a < hi_a, (lo_a, med_a, hi_a)
    distinct_a = _lut_distinct(finite_a, lo_a, hi_a)
    print(f"F6 [A] lo={lo_a:.4f} median={med_a:.4f} hi={hi_a:.4f} "
          f"distinct_LUT_indices={distinct_a}")
    assert distinct_a >= 8, distinct_a  # 非全饱和：至少 8 个色阶

    # 退化矩阵 B：典型数据 + 15% NaN（真机边界 log(0) 场景）
    # 旧 np.percentile → [nan, nan]（饱和纯亮黄）；新 nanpercentile 稳健
    b = a.copy()
    b[np.random.default_rng(1).random(b.shape) < 0.15] = np.nan
    finite_b = b[np.isfinite(b)]
    med_b = float(np.median(finite_b))
    lo_b, hi_b = _mfcc_display_levels(b)
    assert np.isfinite(lo_b) and np.isfinite(hi_b), (lo_b, hi_b)  # 变异翻红点
    assert lo_b < med_b < hi_b, (lo_b, med_b, hi_b)
    distinct_b = _lut_distinct(finite_b, lo_b, hi_b)
    print(f"F6 [B/NaN] lo={lo_b:.4f} median={med_b:.4f} hi={hi_b:.4f} "
          f"distinct_LUT_indices={distinct_b}")
    assert distinct_b >= 8, distinct_b

    # 单一数据源：_update_mfcc 后 mfcc_img / bar_img / colorbar 共用同一组 lo,hi
    w = TimbreWidget()
    try:
        w._times = np.linspace(0.0, 1.0, a.shape[1])
        w._mfcc = a.T  # [n_frames, n_mfcc]；_update_mfcc 内部取 .T 显示
        w._update_mfcc()
        shown = w._mfcc.T
        lo_w, hi_w = _mfcc_display_levels(shown)
        assert np.allclose(w.mfcc_img.getLevels(), (lo_w, hi_w)), (
            w.mfcc_img.getLevels(), (lo_w, hi_w))
        assert np.allclose(w.mfcc_bar_img.getLevels(), (lo_w, hi_w)), (
            w.mfcc_bar_img.getLevels(), (lo_w, hi_w))
        assert np.allclose(w.mfcc_colorbar.viewRange()[1], (lo_w, hi_w)), (
            w.mfcc_colorbar.viewRange()[1], (lo_w, hi_w))
        # 三者彼此相等（禁两处各算一遍）
        assert np.allclose(w.mfcc_img.getLevels(), w.mfcc_bar_img.getLevels())
    finally:
        w.close()
        w.deleteLater()
