# SPDX-License-Identifier: GPL-3.0-only
"""TuningSystem 音律模型单元测试（T-918）。TUNINGS_SYSTEM_TEST_V1

期望数据 = 官方 .scl 格式说明页样例 meanquar.scl（字符串内联）与等价换算
（复用 dsp/units.py 的 cents_to_hz 作为独立对照）。
"""

import math

import pytest

pytest.importorskip("numpy")

from acouscope.analysis.tunings.tuning_system import TuningSystem  # noqa: E402
from acouscope.dsp.units import cents_to_hz  # noqa: E402

MEANQUAR_SCL = """! meanquar.scl
!
1/4-comma meantone scale. Pietro Aaron's temperament (1523)
 12
!
 76.04900
 193.15686
 310.26471
 5/4
 503.42157
 579.47057
 696.57843
 25/16
 889.73529
 1006.84314
 1082.89214
 2/1
"""

SOURCE = "Huygens-Fokker 官方 .scl 格式说明页样例 meanquar.scl（Pietro Aaron 1523）"


@pytest.fixture()
def meantone() -> TuningSystem:
    return TuningSystem.from_scl(MEANQUAR_SCL, source=SOURCE)


def test_from_scl_basic_shape(meantone):
    assert meantone.degree_count == 12
    assert len(meantone.degrees) == 13
    assert meantone.degrees[0] == 0.0
    assert meantone.degrees[-1] == pytest.approx(1200.0, abs=1e-9)
    assert meantone.is_octave_repeating is True
    assert meantone.reference_freq == pytest.approx(440.0, abs=1e-12)


def test_from_scl_name_defaults_to_description(meantone):
    assert meantone.name == "1/4-comma meantone scale. Pietro Aaron's temperament (1523)"

    renamed = TuningSystem.from_scl(MEANQUAR_SCL, source=SOURCE, name="中庸律")
    assert renamed.name == "中庸律"


def test_from_scl_requires_source_keyword():
    with pytest.raises(TypeError):
        TuningSystem.from_scl(MEANQUAR_SCL)  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        TuningSystem.from_scl(MEANQUAR_SCL, source="")


def test_degree_to_cents_matches_scl_values(meantone):
    """0 度＝隐含 1/1；第 4 度＝5/4；末度＝2/1；音分与 .scl 逐值一致。"""
    assert meantone.degree_to_cents(0) == 0.0
    assert meantone.degree_to_cents(1) == pytest.approx(76.04900, abs=1e-9)
    assert meantone.degree_to_cents(4) == pytest.approx(386.3137138648348, abs=1e-9)
    assert meantone.degree_to_cents(8) == pytest.approx(772.6274277296692, abs=1e-9)  # 25/16
    assert meantone.degree_to_cents(9) == pytest.approx(889.73529, abs=1e-9)  # 样例第 9 值
    assert meantone.degree_to_cents(12) == pytest.approx(1200.0, abs=1e-9)


def test_degree_to_cents_folds_out_of_range_by_octave(meantone):
    assert meantone.degree_to_cents(13) == pytest.approx(1200.0 + 76.04900, abs=1e-9)
    assert meantone.degree_to_cents(24) == pytest.approx(2400.0, abs=1e-9)
    assert meantone.degree_to_cents(-1) == pytest.approx(1082.89214 - 1200.0, abs=1e-9)
    assert meantone.degree_to_cents(-12) == pytest.approx(-1200.0, abs=1e-9)


def test_degree_to_cents_rejects_non_int(meantone):
    with pytest.raises(TypeError):
        meantone.degree_to_cents(1.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        meantone.degree_to_cents(True)  # type: ignore[arg-type]


def test_degree_to_freq_default_reference_is_440(meantone):
    assert meantone.degree_to_freq(0) == pytest.approx(440.0, rel=1e-12)
    assert meantone.degree_to_freq(12) == pytest.approx(880.0, rel=1e-12)
    assert meantone.degree_to_freq(4) == pytest.approx(550.0, rel=1e-9)  # 5/4 × 440


def test_degree_to_freq_reuses_units_conversion(meantone):
    """与 dsp/units.py 的 cents_to_hz 独立对照（不重复造换算）。"""
    for degree in range(13):
        want = float(cents_to_hz(meantone.degree_to_cents(degree), ref_freq=440.0))
        assert meantone.degree_to_freq(degree) == pytest.approx(want, rel=1e-12)


def test_reference_freq_is_injectable():
    tuning = TuningSystem.from_cents(
        name="十二平均律", source="等程十二音定义", cents=[100.0 * i for i in range(1, 13)],
        reference_freq=442.0,
    )
    assert tuning.reference_freq == pytest.approx(442.0, abs=1e-12)
    assert tuning.degree_to_freq(0) == pytest.approx(442.0, rel=1e-12)
    assert tuning.degree_to_freq(0, ref=432.0) == pytest.approx(432.0, rel=1e-12)


def test_cents_to_degree_nearest(meantone):
    assert meantone.cents_to_degree(0.0) == 0
    assert meantone.cents_to_degree(400.0) == 4  # 386.31 比 503.42 近
    assert meantone.cents_to_degree(300.0) == 3  # 310.26 比 193.16 近
    assert meantone.cents_to_degree(745.0) == 8  # 772.63 比 696.58 近
    assert meantone.cents_to_degree(1200.0) == 12
    assert meantone.cents_to_degree(-50.0) == 0
    assert meantone.cents_to_degree(1250.0) == 13
    assert meantone.cents_to_degree(2000.0) == 20  # 1972.63 比 2089.74 近


def test_cents_to_degree_roundtrip_on_all_degrees(meantone):
    for degree in range(meantone.degree_count + 1):
        assert meantone.cents_to_degree(meantone.degree_to_cents(degree)) == degree


def test_freq_to_degree_uses_reference(meantone):
    assert meantone.freq_to_degree(440.0) == 0
    assert meantone.freq_to_degree(880.0) == 12
    assert meantone.freq_to_degree(880.0, ref=440.0) == 12
    assert meantone.freq_to_degree(220.0) == -12


def test_cents_to_degree_rejects_non_finite(meantone):
    with pytest.raises(ValueError):
        meantone.cents_to_degree(float("nan"))
    with pytest.raises(ValueError):
        meantone.cents_to_degree(math.inf)


def test_from_ratios_converts_by_log2():
    tuning = TuningSystem.from_ratios(
        name="纯律大调", source="5-limit just intonation",
        ratios=["9/8", "5/4", "4/3", "3/2", "5/3", "15/8", "2/1"],
    )
    assert tuning.degree_count == 7
    assert tuning.degree_to_cents(1) == pytest.approx(1200.0 * math.log2(9 / 8), abs=1e-9)
    assert tuning.degree_to_cents(2) == pytest.approx(386.3137138648348, abs=1e-9)
    assert tuning.degree_to_cents(7) == pytest.approx(1200.0, abs=1e-9)


def test_from_ratios_rejects_non_positive():
    with pytest.raises(ValueError):
        TuningSystem.from_ratios(name="坏音律", source="测试", ratios=["-3/2"])


def test_from_cents_prepends_implicit_unison():
    tuning = TuningSystem.from_cents(name="三音", source="测试", cents=[100.0, 200.0, 300.0])
    assert tuning.degrees == (0.0, 100.0, 200.0, 300.0)
    assert tuning.degree_count == 3
    assert tuning.is_octave_repeating is False


def test_non_octave_scale_folding_still_works():
    """非八度音律（末值 ≠ 1200）外推口径：按 1200 音分步进折算（见模块 docstring）。"""
    tuning = TuningSystem.from_cents(name="非八度", source="测试", cents=[350.0, 700.0])
    assert tuning.is_octave_repeating is False
    assert tuning.degree_to_cents(3) == pytest.approx(1200.0 + 350.0, abs=1e-9)
    assert tuning.cents_to_degree(0.0) == 0
    assert tuning.cents_to_degree(350.0) == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "", "source": "测试", "degrees": (0.0, 1200.0)},
        {"name": "无名", "source": "", "degrees": (0.0, 1200.0)},
        {"name": "无名", "source": "测试", "degrees": ()},
        {"name": "无名", "source": "测试", "degrees": (100.0, 1200.0)},
        {"name": "无名", "source": "测试", "degrees": (0.0, float("inf"))},
        {"name": "无名", "source": "测试", "degrees": (0.0, 1200.0), "reference_freq": 0.0},
        {"name": "无名", "source": "测试", "degrees": (0.0, 1200.0), "reference_freq": -440.0},
    ],
)
def test_invalid_construction_raises(kwargs):
    with pytest.raises(ValueError):
        TuningSystem(**kwargs)


def test_zero_degree_scale_is_handled():
    tuning = TuningSystem.from_cents(name="单音", source="测试", cents=[])
    assert tuning.degree_count == 0
    assert tuning.degree_to_cents(0) == 0.0
    assert tuning.degree_to_cents(3) == pytest.approx(3600.0, abs=1e-9)
    assert tuning.cents_to_degree(1250.0) == 1
    assert tuning.degree_to_freq(1) == pytest.approx(880.0, rel=1e-12)
