# SPDX-License-Identifier: GPL-3.0-only
"""标注系统单元测试。

测试 TimeInstant、TimeRegion、AnnotationModel 的数据模型功能。
"""

import pytest

from acouscope.annotation import (
    AnnotationModel,
    TimeInstant,
    TimeRegion,
    REGION_PALETTE,
)


class TestTimeInstant:
    """TimeInstant 数据类测试。"""

    def test_create_basic(self):
        inst = TimeInstant(time=1.5)
        assert inst.time == 1.5
        assert inst.label == ""
        assert inst.color == "#ef4444"
        assert inst.show_label is True

    def test_create_with_label_and_color(self):
        inst = TimeInstant(time=2.0, label="onset", color="#10b981")
        assert inst.time == 2.0
        assert inst.label == "onset"
        assert inst.color == "#10b981"

    def test_negative_time_clamped_to_zero(self):
        inst = TimeInstant(time=-0.5)
        assert inst.time == 0.0

    def test_time_zero_is_valid(self):
        inst = TimeInstant(time=0.0)
        assert inst.time == 0.0


class TestTimeRegion:
    """TimeRegion 数据类测试。"""

    def test_create_basic(self):
        region = TimeRegion(start_time=1.0, end_time=2.0)
        assert region.start_time == 1.0
        assert region.end_time == 2.0
        assert region.label == ""
        assert region.color == "#3b82f6"
        assert region.show_label is True

    def test_duration_property(self):
        region = TimeRegion(start_time=0.5, end_time=2.5)
        assert abs(region.duration - 2.0) < 1e-9

    def test_duration_zero(self):
        region = TimeRegion(start_time=1.0, end_time=1.0)
        assert region.duration == 0.0

    def test_negative_times_clamped(self):
        region = TimeRegion(start_time=-1.0, end_time=-0.5)
        assert region.start_time == 0.0
        # 起始被裁为 0 后，结束时间被强制为至少 start + 0.01
        assert region.end_time == 0.01

    def test_contains(self):
        region = TimeRegion(start_time=1.0, end_time=2.0)
        assert region.contains(1.5)
        assert region.contains(1.0)
        assert region.contains(2.0)
        assert not region.contains(0.999)
        assert not region.contains(2.001)

    def test_create_with_label_and_color(self):
        region = TimeRegion(
            start_time=0.0,
            end_time=1.0,
            label="verse",
            color="#f59e0b",
        )
        assert region.label == "verse"
        assert region.color == "#f59e0b"


class TestAnnotationModel:
    """AnnotationModel 管理类测试。"""

    @pytest.fixture
    def model(self):
        return AnnotationModel()

    # ------ 时间点测试 ------

    def test_add_instant(self, model):
        inst = model.add_instant(1.5, "beat")
        assert inst.time == 1.5
        assert inst.label == "beat"
        assert len(model.instants) == 1

    def test_add_instant_default_label(self, model):
        inst = model.add_instant(0.5)
        assert inst.label == ""

    def test_add_instant_custom_color(self, model):
        inst = model.add_instant(1.0, color="#10b981")
        assert inst.color == "#10b981"

    def test_instants_sorted_by_time(self, model):
        model.add_instant(3.0)
        model.add_instant(1.0)
        model.add_instant(2.0)
        times = [i.time for i in model.instants]
        assert times == [1.0, 2.0, 3.0]

    def test_remove_instant(self, model):
        inst1 = model.add_instant(1.0)
        inst2 = model.add_instant(2.0)
        model.remove_instant(inst1)
        assert len(model.instants) == 1
        assert model.instants[0] is inst2

    def test_remove_nonexistent_instant_no_error(self, model):
        inst = TimeInstant(time=1.0)
        # 不在 model 中的实例
        model.remove_instant(inst)
        assert len(model.instants) == 0

    def test_clear_instants(self, model):
        model.add_instant(1.0)
        model.add_instant(2.0)
        model.clear_instants()
        assert len(model.instants) == 0

    def test_find_instant_near_exact(self, model):
        inst = model.add_instant(1.5, "target")
        result = model.find_instant_near(1.5, tolerance=0.01)
        assert result is inst

    def test_find_instant_near_within_tolerance(self, model):
        inst = model.add_instant(1.5, "target")
        result = model.find_instant_near(1.505, tolerance=0.01)
        assert result is inst

    def test_find_instant_near_outside_tolerance(self, model):
        model.add_instant(1.5, "target")
        result = model.find_instant_near(2.0, tolerance=0.01)
        assert result is None

    def test_find_instant_near_empty(self, model):
        assert model.find_instant_near(1.0, 0.1) is None

    def test_find_instant_near_returns_closest(self, model):
        inst1 = model.add_instant(1.0)
        inst2 = model.add_instant(2.0)
        result = model.find_instant_near(1.8, tolerance=1.0)
        assert result is inst2

    # ------ 区域测试 ------

    def test_add_region(self, model):
        region = model.add_region(1.0, 2.0, "verse")
        assert region.start_time == 1.0
        assert region.end_time == 2.0
        assert region.label == "verse"
        assert len(model.regions) == 1

    def test_add_region_auto_color_cycle(self, model):
        r1 = model.add_region(0, 1)
        r2 = model.add_region(1, 2)
        r3 = model.add_region(2, 3)
        assert r1.color != r2.color
        # 颜色取自 REGION_COLORS 轮盘
        assert r1.color == REGION_PALETTE[0]
        assert r2.color == REGION_PALETTE[1]
        assert r3.color == REGION_PALETTE[2]

    def test_add_region_custom_color(self, model):
        region = model.add_region(0, 1, color="#ff0000")
        assert region.color == "#ff0000"

    def test_add_region_swaps_if_start_after_end(self, model):
        region = model.add_region(2.0, 1.0)
        assert region.start_time == 1.0
        assert region.end_time == 2.0

    def test_regions_sorted_by_start(self, model):
        model.add_region(3.0, 4.0)
        model.add_region(1.0, 2.0)
        model.add_region(2.0, 3.0)
        starts = [r.start_time for r in model.regions]
        assert starts == [1.0, 2.0, 3.0]

    def test_remove_region(self, model):
        r1 = model.add_region(0, 1)
        r2 = model.add_region(1, 2)
        model.remove_region(r1)
        assert len(model.regions) == 1
        assert model.regions[0] is r2

    def test_remove_nonexistent_region_no_error(self, model):
        region = TimeRegion(start_time=0, end_time=1)
        model.remove_region(region)
        assert len(model.regions) == 0

    def test_clear_regions(self, model):
        model.add_region(0, 1)
        model.add_region(1, 2)
        model.clear_regions()
        assert len(model.regions) == 0

    def test_find_region_at(self, model):
        r1 = model.add_region(0, 1, "first")
        r2 = model.add_region(2, 3, "second")
        assert model.find_region_at(0.5) is r1
        assert model.find_region_at(2.5) is r2
        assert model.find_region_at(1.5) is None
        # 边界
        assert model.find_region_at(0.0) is r1
        assert model.find_region_at(1.0) is r1
        assert model.find_region_at(3.0) is r2

    def test_find_region_near_within_threshold(self, model):
        region = model.add_region(1.0, 2.0)
        # find_region_near 只检查边界附近，不检查区域内部
        # 靠近左边界（距离 0.05 < 阈值 0.1）
        assert model.find_region_near(0.95, 0.1) is region
        # 靠近右边界
        assert model.find_region_near(2.05, 0.1) is region
        # 正好在边界上
        assert model.find_region_near(1.0, 0.1) is region

    def test_find_region_near_outside_threshold(self, model):
        model.add_region(1.0, 2.0)
        assert model.find_region_near(0.5, 0.1) is None
        assert model.find_region_near(3.0, 0.1) is None

    def test_find_region_near_empty(self, model):
        assert model.find_region_near(1.0, 0.1) is None

    def test_find_region_near_returns_closest(self, model):
        r1 = model.add_region(0.0, 1.0)
        r2 = model.add_region(2.0, 3.0)
        # 离 r1 更近（距离 0.2）
        assert model.find_region_near(1.2, 1.0) is r1
        # 离 r2 更近（距离 0.3）
        assert model.find_region_near(1.7, 1.0) is r2

    # ------ 综合测试 ------

    def test_mixed_instants_and_regions(self, model):
        model.add_instant(0.5, "start")
        model.add_region(1.0, 2.0, "middle")
        model.add_instant(2.5, "end")
        model.add_region(3.0, 4.0, "outro")

        assert len(model.instants) == 2
        assert len(model.regions) == 2
        assert model.instants[0].label == "start"
        assert model.regions[0].label == "middle"

    def test_clear_all(self, model):
        model.add_instant(1.0)
        model.add_region(0, 1)
        model.clear_regions()
        model.clear_instants()
        assert len(model.instants) == 0
        assert len(model.regions) == 0

    def test_clear_regions_preserves_instants(self, model):
        model.add_instant(1.0)
        model.add_region(0, 1)
        model.clear_regions()
        assert len(model.instants) == 1
        assert len(model.regions) == 0

    def test_clear_instants_preserves_regions(self, model):
        model.add_instant(1.0)
        model.add_region(0, 1)
        model.clear_instants()
        assert len(model.instants) == 0
        assert len(model.regions) == 1
