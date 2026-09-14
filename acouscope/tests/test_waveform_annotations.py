# SPDX-License-Identifier: GPL-3.0-only
"""波形控件标注功能单元测试。"""

import numpy as np
import pytest


@pytest.fixture
def waveform_widget(qapp):
    """创建带测试数据的波形控件。"""
    from acouscope.ui.widgets.waveform import WaveformWidget

    w = WaveformWidget()
    sr = 44100
    duration = 2.0
    t = np.linspace(0, duration, int(sr * duration))
    # 440Hz 正弦波 + 指数衰减
    signal = np.sin(2 * np.pi * 440 * t) * np.exp(-t * 0.5)
    w.set_data(t, signal, sample_rate=sr)
    return w


class TestWaveformAnnotations:
    """波形控件标注功能测试。"""

    def test_initial_empty(self, waveform_widget):
        assert len(waveform_widget.annotations.regions) == 0
        assert len(waveform_widget.annotations.instants) == 0

    def test_add_region(self, waveform_widget):
        region = waveform_widget.add_region(0.5, 1.0, "verse")
        assert region.start_time == 0.5
        assert region.end_time == 1.0
        assert region.label == "verse"
        assert len(waveform_widget.annotations.regions) == 1
        # 可视化 item 应已创建
        assert len(waveform_widget._region_items) == 1

    def test_add_multiple_regions(self, waveform_widget):
        waveform_widget.add_region(0.0, 0.5, "intro")
        waveform_widget.add_region(0.5, 1.5, "verse")
        waveform_widget.add_region(1.5, 2.0, "outro")
        assert len(waveform_widget.annotations.regions) == 3
        assert len(waveform_widget._region_items) == 3

    def test_add_instant(self, waveform_widget):
        inst = waveform_widget.add_instant(0.75, "onset")
        assert inst.time == 0.75
        assert inst.label == "onset"
        assert len(waveform_widget.annotations.instants) == 1
        assert len(waveform_widget._instant_items) == 1

    def test_clear_regions(self, waveform_widget):
        waveform_widget.add_region(0, 1, "a")
        waveform_widget.add_region(1, 2, "b")
        waveform_widget.add_instant(0.5, "x")

        waveform_widget.clear_regions()

        assert len(waveform_widget.annotations.regions) == 0
        assert len(waveform_widget._region_items) == 0
        # 时间点不受影响
        assert len(waveform_widget.annotations.instants) == 1

    def test_clear_instants(self, waveform_widget):
        waveform_widget.add_region(0, 1, "a")
        waveform_widget.add_instant(0.5, "x")
        waveform_widget.add_instant(1.5, "y")

        waveform_widget.clear_instants()

        assert len(waveform_widget.annotations.instants) == 0
        assert len(waveform_widget._instant_items) == 0
        # 区域不受影响
        assert len(waveform_widget.annotations.regions) == 1

    def test_selected_region_initially_none(self, waveform_widget):
        assert waveform_widget.selected_region() is None

    def test_region_dragged_updates_model(self, waveform_widget):
        """拖动区域边界应更新模型数据。"""
        region = waveform_widget.add_region(0.5, 1.0, "test")
        item = waveform_widget._region_items[id(region)]

        # 模拟拖动：设置新的区域范围
        item.setRegion([0.6, 1.2])

        # 模型数据应已更新
        assert abs(region.start_time - 0.6) < 1e-6
        assert abs(region.end_time - 1.2) < 1e-6

    def test_region_dragged_triggers_callback(self, waveform_widget):
        """拖动区域应触发选中回调。"""
        called = []
        def on_selected(r):
            called.append(r)
        waveform_widget.region_selected_callback = on_selected

        region = waveform_widget.add_region(0.5, 1.0, "test")
        item = waveform_widget._region_items[id(region)]
        item.setRegion([0.6, 1.2])

        assert len(called) >= 1
        assert called[-1] is region

    def test_instant_dragged_updates_model(self, waveform_widget):
        """拖动时间点应更新模型数据。"""
        inst = waveform_widget.add_instant(1.0, "test")
        item = waveform_widget._instant_items[id(inst)]

        item.setPos(1.5)

        assert abs(inst.time - 1.5) < 1e-6

    def test_annotation_model_shared(self, waveform_widget):
        """设置共享标注模型。"""
        from acouscope.annotation import AnnotationModel
        model = AnnotationModel()
        model.add_region(0, 1, "shared")

        waveform_widget.set_annotation_model(model)
        assert waveform_widget.annotations is model
        assert len(waveform_widget._region_items) == 1

    def test_clear_on_clear_method(self, waveform_widget):
        """clear() 方法应清除标注。"""
        waveform_widget.add_region(0, 1, "test")
        waveform_widget.add_instant(0.5, "test")

        waveform_widget.clear()

        assert len(waveform_widget.annotations.regions) == 0
        assert len(waveform_widget.annotations.instants) == 0

    def test_loop_request_callback(self, waveform_widget):
        """循环播放请求回调。"""
        requests = []
        def on_loop(enabled, region):
            requests.append((enabled, region))
        waveform_widget.loop_request_callback = on_loop

        region = waveform_widget.add_region(0.5, 1.0, "test")
        waveform_widget._loop_play_region(region)

        assert len(requests) == 1
        assert requests[0][0] is True
        assert requests[0][1] is region

    def test_multiple_regions_different_colors(self, waveform_widget):
        """多个区域应有不同颜色。"""
        r1 = waveform_widget.add_region(0, 0.5)
        r2 = waveform_widget.add_region(0.5, 1.0)
        r3 = waveform_widget.add_region(1.0, 1.5)
        assert r1.color != r2.color
        assert r2.color != r3.color
