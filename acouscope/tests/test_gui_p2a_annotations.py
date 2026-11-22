# SPDX-License-Identifier: GPL-3.0-only
"""PI-P2a：色条/电平表 dB 标注 + 文件浏览器空结果提示与类型图标。

口径：全离屏（conftest 已设 QT_QPA_PLATFORM=offscreen）；看门狗 signal.alarm +
os._exit 防长驻；禁真 GUI / app.exec。
"""

import os
import signal
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_WATCHDOG_S = 90


def _on_alarm(signum, frame):  # noqa: ARG001
    os._exit(99)


signal.signal(signal.SIGALRM, _on_alarm)


@pytest.fixture(scope="module", autouse=True)
def _watchdog():
    signal.alarm(_WATCHDOG_S)
    yield
    signal.alarm(0)


def test_a1_mfcc_colorbar_unit_label(qapp):
    """A1：MFCC 色条左轴标签 = 「系数值」新键取值（H5b：系数不是分贝，禁 dB）。"""
    from acouscope.i18n import tr
    from acouscope.ui.widgets.timbre import TimbreWidget

    w = TimbreWidget()
    try:
        axis = w.mfcc_colorbar.getAxis("left")
        assert axis.labelText == tr("timbre.colorbar.unit")
        assert w.mfcc_colorbar.getPlotItem().axes["left"]["item"].labelText == tr("timbre.colorbar.unit")
        # M2：总宽 = 左轴 30 + 渐变 14（旧 30 会把渐变压没）
        assert w.mfcc_colorbar.minimumSizeHint().width() == 44
        assert w.mfcc_colorbar.minimumSizeHint().height() == 60
        assert w.mfcc_colorbar.maximumWidth() == 44
    finally:
        w.close()


def test_a2_vu_meter_tick_constants(qapp):
    """A2：电平表单位常量与刻度标签常量（至少四档；运行时绘制由 A8 覆盖）。"""
    from acouscope.ui.widgets.waveform import VUMeter

    assert VUMeter._UNIT_LABEL == "dB"
    assert len(VUMeter._TICK_LABELS) >= 4
    assert "0" in VUMeter._TICK_LABELS
    assert "-20" in VUMeter._TICK_LABELS
    assert "-40" in VUMeter._TICK_LABELS
    assert "-60" in VUMeter._TICK_LABELS
    vm = VUMeter()
    try:
        assert vm.sizeHint().width() == 32
        assert vm.sizeHint().height() == 200
        assert vm.minimumSizeHint().width() == 24
        assert vm.minimumSizeHint().height() == 80
    finally:
        vm.stop_animation()
        vm.close()


def test_a3_vu_meter_draws_tick_text(qapp):
    """A3：200 高离屏 grab，bar 右侧 12px 带内（剔除刻度线行）有文字像素。"""
    from acouscope.ui.widgets.waveform import VUMeter

    vm = VUMeter()
    try:
        vm.resize(32, 200)
        img = vm.grab().toImage()
        assert img.width() == 32
        assert img.height() == 200

        bg = img.pixelColor(img.width() - 1, img.height() - 1)
        bar_right = VUMeter._BAR_X + VUMeter._BAR_W
        band = range(bar_right, min(bar_right + 12, img.width()))
        tick_ys = [
            int(min((float(s) / VUMeter._DB_FLOOR) * 200, 199))
            for s in VUMeter._TICK_LABELS
        ]
        ink = sum(
            1
            for y in range(img.height())
            for x in band
            if img.pixelColor(x, y) != bg
            and not any(abs(y - t) <= 2 for t in tick_ys)
        )
        assert ink > 0, "刻度文字区无文字像素（只加了常量、未真画出）"
    finally:
        vm.stop_animation()
        vm.close()


def test_a7_vu_meter_fill_orientation(qapp):
    """A7：0 dB 满填（柱顶 y=3 非底色）、reset 后柱顶回底色（不填）。"""
    from PyQt6.QtGui import QColor
    from acouscope.ui import theme
    from acouscope.ui.widgets.waveform import VUMeter

    vm = VUMeter()
    try:
        vm.resize(32, 200)
        border = QColor(theme.colors()["border"])
        x = VUMeter._BAR_X + VUMeter._BAR_W // 2

        vm.set_level(1.0)
        vm._tick()
        top_full = vm.grab().toImage().pixelColor(x, 3)

        vm.reset()
        top_reset = vm.grab().toImage().pixelColor(x, 3)

        assert top_full != border and top_reset == border, (
            f"y=3 柱顶：满电={top_full.name()}（应≠底色 {border.name()}）；"
            f"reset 后={top_reset.name()}（应=底色 {border.name()}）"
        )
    finally:
        vm.stop_animation()
        vm.close()


def test_a8_vu_meter_tick_lines_top_bottom(qapp):
    """A8：0 档刻度线在顶部 y≈0、-60 档在底部 y≈h-1 真有墨迹。"""
    from acouscope.ui.widgets.waveform import VUMeter

    vm = VUMeter()
    try:
        vm.resize(32, 200)
        img = vm.grab().toImage()
        h = img.height()
        cols = range(
            VUMeter._BAR_X + VUMeter._BAR_W,
            VUMeter._BAR_X + VUMeter._BAR_W + VUMeter._TICK_LEN,
        )
        bg = img.pixelColor(cols.start, 100)
        inked = [
            y
            for y in range(h)
            if any(img.pixelColor(x, y) != bg for x in cols)
        ]
        assert inked, "刻度线三列整列无墨迹"
        top_y, bottom_y = min(inked), max(inked)
        top_ink = sum(1 for x in cols if img.pixelColor(x, 0) != bg)
        bottom_ink = sum(1 for x in cols if img.pixelColor(x, h - 1) != bg)
        assert top_y <= 1 and bottom_y >= h - 2, (
            f"刻度线纵向范围 [{top_y},{bottom_y}]（应≈[0,{h - 1}]）；"
            f"y=0 墨迹={top_ink}/3，y={h - 1} 墨迹={bottom_ink}/3"
        )
        assert top_ink > 0 and bottom_ink > 0
    finally:
        vm.stop_animation()
        vm.close()


def _browser_for(directory: Path, current_name: str):
    from acouscope.ui.widgets.file_browser import FileBrowser

    return FileBrowser(manager=None, current_file=directory / current_name)


def test_a4_empty_directory_shows_empty_state(qapp, tmp_path):
    """A4：目录存在但无文件（仅有子目录）→ 空态提示出现、列表隐藏。"""
    d = tmp_path / "only_subdir"
    d.mkdir()
    (d / "sub").mkdir()

    b = _browser_for(d, "probe.wav")
    try:
        assert b.list.count() == 0
        assert b._lbl_empty.isVisibleTo(b) is True
        assert b.list.isVisibleTo(b) is False
    finally:
        b.close()


def test_a5_nonempty_directory_lists_files(qapp, tmp_path):
    """A5（正对照）：目录含 a.wav → 列表可见、空态不出现。"""
    d = tmp_path / "with_audio"
    d.mkdir()
    (d / "a.wav").write_bytes(b"")

    b = _browser_for(d, "a.wav")
    try:
        assert b.list.count() > 0
        assert b._lbl_empty.isVisibleTo(b) is False
        assert b.list.isVisibleTo(b) is True
    finally:
        b.close()


def test_a6_file_type_icons(qapp, tmp_path):
    """A6：白名单后在列两类（音频/项目）item 均有非空类型图标；n.txt 被滤除。"""
    d = tmp_path / "types"
    d.mkdir()
    (d / "a.wav").write_bytes(b"")
    (d / "p.acouproj").write_text("{}")
    (d / "n.txt").write_text("x")

    b = _browser_for(d, "a.wav")
    try:
        by_name = {
            b.list.item(i).text(): b.list.item(i)
            for i in range(b.list.count())
        }
        assert set(by_name) == {"a.wav", "p.acouproj"}
        assert by_name["a.wav"].icon().isNull() is False
        for name in ("a.wav", "p.acouproj"):
            assert by_name[name].icon().isNull() is False, name
    finally:
        b.close()


def test_a7b_vu_meter_mid_level_proves_fill_from_top(qapp):
    """A7b：中间电平（−6 dB）墨迹**自顶连续** ⇒ 正面证明「自顶填」。

    A7 盲区成因：原 A7 只测 0 dB（满填）与 reset（不填）两极，两极处
    fillRect 的 y 坐标不可分辨（满填/不填与位置无关）⇒ 「自顶填」与
    「自底填」都能通过原判据。本条以**中间电平**补上区分力。

    手法：照 A8 的「列内相对差异」（离屏 grab 整列是 border 底色，
    不可与 theme border 绝对比色；取同列底部行作参照）。
    注意：VUMeter.set_level() 收的是**线性电平 0.0–1.0**（内部 _to_db 转 dB），
    0.5 ⇒ −6.02 dB。
    """
    from acouscope.ui.widgets.waveform import VUMeter

    vm = VUMeter()
    try:
        vm.resize(32, 200)
        img = vm.grab().toImage()
        h = img.height()
        x = VUMeter._BAR_X + VUMeter._BAR_W // 2
        bg = img.pixelColor(x, h - 1)          # 底部 = 无填充处（参照色）

        vm.reset()
        vm.set_level(0.5)                       # 线性 0.5 ⇒ −6.02 dB（中间电平）
        vm._tick()
        img = vm.grab().toImage()
        inked = [y for y in range(h) if img.pixelColor(x, y) != bg]

        assert inked, "中间电平应画出电平柱（无墨迹 ⇒ 电平链断了）"
        assert min(inked) == 0, (
            f"中间电平墨迹应自顶起（min_inked={min(inked)}，期望 0）"
        )
        assert all(y in inked for y in range(0, max(inked) + 1)), (
            f"中间电平墨迹应自顶连续（否则是自底填，max_inked={max(inked)}）"
        )
        assert max(inked) < h - 1, (
            f"中间电平不应满填（max_inked={max(inked)}，期望 < {h - 1}）"
        )
    finally:
        vm.stop_animation()
        vm.close()


def test_a9_vu_meter_peak_gate_excludes_silence_floor(qapp):
    """A9：peak 门控为**严格大于**底噪下限 ⇒ −60 dB（静音）不画峰线。

    语义依据（P2a 审计已判 `>` 合理）：静音无峰可画；若门控误改为 `>=`，
    −60 dB 会在贴底处画出一条「假峰线」。
    口径：**源码锚定 + 决策口径双锁**——离屏 grab 取不到峰线（本席实测），
    故以 inspect.getsource 抓 waveform.py 门控算符（随实现同源，变异必翻红），
    并以同源决策式佐证语义。禁硬编码 True/False。
    """
    import inspect
    import re

    from acouscope.ui.widgets.waveform import VUMeter

    floor = VUMeter._DB_FLOOR
    assert floor == -60.0
    src = inspect.getsource(VUMeter.paintEvent)
    m = re.search(r"_paint_peak_db\s*(>=|>)\s*floor", src)
    assert m, f"未找到 peak 门控表达式（形态已变？）：{src!r}"
    assert m.group(1) == ">", (
        f"peak 门控须为严格大于（`> floor`），实际为 `{m.group(1)} floor`；"
        "`>=` 会在 −60 dB 静音处画假峰线"
    )
    # 决策口径佐证：−60 dB 不满足严格门控，略高于底噪的电平满足
    assert not (floor > floor), "−60 dB（静音）不应满足 peak 门控"
    assert (floor + 0.1) > floor, "略高于底噪的电平应满足 peak 门控"
