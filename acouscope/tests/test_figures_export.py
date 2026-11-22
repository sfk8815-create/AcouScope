# SPDX-License-Identifier: GPL-3.0-only
"""通用图形与预设层判据（任务-20261025-平台图导出 甲，2026-10-25 通用化返工）。

三条要点：

1. **数值同源**：``segment_curve_data`` 的统计量须等于平台分析模块对同一段现算的
   读数（另建一次模型独立复核，防图与数据各说各话）；
2. **出版参数在预设层**：通用图形不含论文裁剪，``paper_A`` 只给裁剪／轴／图注参数；
3. **图 C 的锚定偏移与中位偏离必须分开**：锚定偏移由调用方给（论文 §三 口径），
   中位偏离只是描述量；``paper_C`` 缺锚即拒。
"""

import json

import numpy as np
import pytest
import soundfile as sf

from acouscope.analysis.cavity_type import repeat_degree_v2
from acouscope.analysis.pitch_grid import build_pitch_grid
from acouscope.analysis.pitch_stream import stream_pitch
from acouscope.analysis.tunings.templates import get_template, list_templates
from acouscope.visualization.figures import (
    DEFAULT_AXIS_LABELS,
    TYPE_LABELS,
    TURN_BINS,
    main,
    reference_comparison,
    reference_comparison_data,
    segment_curve,
    segment_curve_data,
    type_oscillation,
    type_oscillation_data,
)
from acouscope.visualization.presets import PAPER_PRESETS, get_preset, list_presets

SR = 44100


def _vibrato_wav(path, *, freq_hz=330.0, vib_hz=4.0, pp_cents=100.0, dur=4.0):
    t = np.arange(int(SR * dur)) / SR
    cents = (pp_cents / 2.0) * np.sin(2 * np.pi * vib_hz * t)
    sig = 0.2 * np.sin(2 * np.pi * freq_hz * t * 2.0 ** (cents / 1200.0))
    sf.write(str(path), sig, SR)
    return path


def _window_model(path, template="12tet"):
    info = sf.info(str(path))
    sr = int(info.samplerate)
    data, _ = sf.read(str(path), dtype="float64", always_2d=True)
    sig = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]
    tr = stream_pitch(signal=sig, sr=sr, fmin=60.0, fmax=1500.0, block_seconds=30.0)
    f0 = np.asarray(tr.f0_hz, dtype=float)
    model = build_pitch_grid(
        tr.times, f0, tr.confidence, segmenter="hmm", tuning=get_template(template)
    )
    return tr, f0, model


@pytest.fixture()
def wav(tmp_path):
    return _vibrato_wav(tmp_path / "vib.wav")


# ---------------- 预设层：只放呈现参数 ----------------


def test_presets_only_carry_presentation_params():
    """预设层不得含数据／算法字段（只呈现：裁剪、轴、图注槽位、出版参数）。"""
    allowed = {
        "figure", "dpi", "formats", "labels", "caption", "title", "style",
        "pad_left", "pad_right", "window_s", "segmenter", "tuning_template",
        "annotate_segment", "limit", "require_anchor", "templates",
    }
    assert set(list_presets()) >= {"paper_A", "paper_B", "paper_C"}
    for name in list_presets():
        preset = get_preset(name)
        assert set(preset) <= allowed, f"{name} 含非呈现参数：{set(preset) - allowed}"
        assert preset["figure"] in {"segment_curve", "type_oscillation", "reference_comparison"}
        assert preset["formats"] == ("png", "pdf") and preset["dpi"] == 300
        assert preset.get("caption") is None, "图注归写作侧，预设不得内置文字"


def test_preset_is_a_copy():
    preset = get_preset("paper_A")
    preset["dpi"] = 1
    assert get_preset("paper_A")["dpi"] == 300
    assert PAPER_PRESETS["paper_A"]["dpi"] == 300


# ---------------- 段曲线：数值同源 ----------------


def test_segment_curve_stats_match_platform_rows(wav):
    """turns／pp／rate 须等于平台 repeat_degree_v2 的同段读数；net＝尾−首。"""
    _tr, f0, model = _window_model(wav)
    note = model.notes[0]
    data = segment_curve_data(wav, note.start_s, note.end_s)

    seg_id = f"{note.start_s:.3f}-{note.end_s:.3f}"
    row = {r["segment_id"]: r for r in repeat_degree_v2(model, f0, mode="fixed")}[seg_id]
    assert data["stats"]["turns"] == row["turns"]
    assert data["stats"]["pp_cents"] == pytest.approx(row["pp_cents"])
    assert data["stats"]["rate_hz"] == pytest.approx(row["rate_hz"])
    assert data["stats"]["thr_cents"] == 10.0

    expected_net = float(note.tail_deviation_cents) - float(note.head_deviation_cents)
    assert data["stats"]["net_cents"] == pytest.approx(round(expected_net, 2))


def test_segment_curve_rejects_unknown_segment(wav):
    """段不在平台分段结果中 ⇒ 报错（不臆造曲线与统计）。"""
    with pytest.raises(ValueError):
        segment_curve_data(wav, 1.234, 1.777)


def test_segment_curve_publication_contract(wav, tmp_path):
    """通用图形亦按出版参数落盘：PNG 300 dpi ＋ PDF、中文轴。"""
    from PIL import Image

    _tr, _f0, model = _window_model(wav)
    note = model.notes[0]
    data = segment_curve_data(wav, note.start_s, note.end_s)
    result = segment_curve(data, tmp_path, title="示例曲名")
    assert result["dpi"] == 300
    assert set(result["formats"]) == {"png", "pdf"}
    assert result["labels"] == DEFAULT_AXIS_LABELS
    assert all(not v.isascii() for v in DEFAULT_AXIS_LABELS.values())
    with Image.open(result["paths"]["png"]) as im:
        assert tuple(round(float(v)) for v in im.info.get("dpi", (0, 0))) == (300, 300)


def test_generic_curve_can_drop_segment_annotation(wav, tmp_path):
    """通用图形不绑定「段界／底色」（那是预设的选择，不是图形的定义）。"""
    _tr, _f0, model = _window_model(wav)
    note = model.notes[0]
    data = segment_curve_data(wav, note.start_s, note.end_s)
    result = segment_curve(data, tmp_path, annotate_segment=False)
    assert result["paths"]["png"].endswith(".png")


# ---------------- 形态×往复度 ----------------


def test_type_oscillation_bins_and_exclusions():
    rows = [
        {"cavity_type": "上趋", "turns": 0},
        {"cavity_type": "上趋", "turns": 2},
        {"cavity_type": "下趋", "turns": 5},
        {"cavity_type": "平直", "turns": 6},
        {"cavity_type": "未分类", "turns": 9},
        {"cavity_type": "平直", "turns": ""},
    ]
    data = type_oscillation_data([{"label": "例一", "rows": rows}])
    panel = data["panels"][0]
    assert data["types"] == list(TYPE_LABELS) and len(TYPE_LABELS) == 3
    assert data["bins"] == list(TURN_BINS)
    assert panel["counts"][TYPE_LABELS.index("上趋")] == [1, 1, 0, 0]
    assert panel["counts"][TYPE_LABELS.index("下趋")] == [0, 0, 1, 0]
    assert panel["counts"][TYPE_LABELS.index("平直")] == [0, 0, 0, 1]
    assert panel["excluded"] == 2
    assert panel["n_plotted"] == 4


def test_type_oscillation_files(tmp_path):
    rows = [{"cavity_type": "平直", "turns": 7}]
    data = type_oscillation_data([{"label": "例一", "rows": rows}])
    result = type_oscillation(data, tmp_path, title="例")
    assert result["paths"]["pdf"].endswith(".pdf")
    assert result["dpi"] == 300


# ---------------- 参照系对比：锚定偏移 vs 中位偏离 ----------------


def test_reference_comparison_separates_anchor_from_median_deviation(wav):
    """锚定偏移须原样登记（调用方给），中位偏离只作描述量，两者字段分离。"""
    _tr, _f0, model = _window_model(wav)
    data = reference_comparison_data(
        model, anchor_offset_cents=90.45, anchor_source="空弦四弦中位", limit=5
    )
    assert data["anchor"] == {"offset_cents": 90.45, "source": "空弦四弦中位"}
    assert data["anchor_state"] == "given"
    assert set(data["median_deviation_cents"]) == set(data["templates"])
    assert len(data["templates"]) == len(list_templates())
    assert data["ref_mode"] == "absolute"
    assert data["changed_share"][data["templates"][0]] == 0.0


def test_reference_comparison_pending_anchor_is_explicit(wav):
    """未给锚 ⇒ state=pending，不得把中位偏离冒充整体偏移。"""
    _tr, _f0, model = _window_model(wav)
    data = reference_comparison_data(model, limit=3)
    assert data["anchor"] is None
    assert data["anchor_state"] == "pending"


def test_paper_c_requires_anchor(wav, tmp_path):
    """论文预设缺锚即拒（不出「整体偏移已定」的图）。"""
    _tr, _f0, model = _window_model(wav)
    data = reference_comparison_data(model, limit=3)
    with pytest.raises(ValueError):
        reference_comparison(data, tmp_path, require_anchor=True)


def test_paper_c_chinese_tick_labels_keep_internal_keys(wav, tmp_path):
    """图 C 呈现层：刻度显示中文名，内部 key／JSON 仍英文 ID（PI-P5-B3-01g）。"""
    _tr, _f0, model = _window_model(wav)
    data = reference_comparison_data(model, anchor_offset_cents=90.45, limit=3)
    labels = get_preset("paper_C")["labels"]
    result = reference_comparison(data, tmp_path, require_anchor=True, labels=labels)

    mapping = labels["template_labels"]
    assert set(mapping) == set(list_templates()), "内置模板须一一对应中文名"
    assert result["tick_labels"] == [mapping[name] for name in result["matrix"]["templates"]]
    assert all(not name.isascii() for name in result["tick_labels"]), result["tick_labels"]
    # 内部 key 不被改名（JSON／API 不变）
    assert result["matrix"]["templates"] == list_templates()
    assert set(result["matrix"]["median_deviation_cents"]) == set(list_templates())
    # 口径名图面写法：绝对口径；不出现 absolute
    assert "绝对口径" in result["note"] and "absolute" not in result["note"]
    assert "音级序号" == labels["colorbar"], "色条标签不得改成音分"

    # 无预设时退回内部 key（通用层不硬编码中文名）
    plain = reference_comparison(data, tmp_path / "plain", require_anchor=False)
    assert plain["tick_labels"] == list_templates()


def test_reference_comparison_files_with_anchor(wav, tmp_path):
    _tr, _f0, model = _window_model(wav)
    data = reference_comparison_data(model, anchor_offset_cents=12.5, limit=4)
    result = reference_comparison(data, tmp_path, require_anchor=True, title="参照系对比")
    assert result["anchor"]["offset_cents"] == 12.5
    assert result["paths"]["png"].endswith(".png")
    assert result["dpi"] == 300


# ---------------- CLI：--preset ----------------


def test_cli_uses_preset_name(wav, tmp_path, capsys):
    """CLI 以 --preset 选图，不得以 {a,b,c} 硬编码论文名。"""
    _tr, _f0, model = _window_model(wav)
    note = model.notes[0]
    rc = main(
        [
            "--preset", "paper_A",
            "--audio", str(wav),
            "--start", f"{note.start_s:.3f}",
            "--end", f"{note.end_s:.3f}",
            "--out", str(tmp_path / "figs"),
            "--title", "示例曲名",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["kind"] == "segment_curve"
    assert (tmp_path / "figs" / "paper_a.png").is_file()


def test_cli_paper_c_requires_anchor(wav, tmp_path):
    with pytest.raises(SystemExit):
        main(["--preset", "paper_C", "--audio", str(wav), "--out", str(tmp_path / "c")])


# ---------------- 公开入口（PI-P5-B3-01j：私有名公开化 ＋ 窗起点）----------------


def test_load_panels_public_and_alias_equivalent(tmp_path):
    """分面读取是公开名：``_load_panels`` 只是同一函数对象的别名（非第二份实现）。"""
    from acouscope.visualization import figures

    payload = {"panels": [{"label": "甲组", "rows": [{"cavity_type": "平直", "turns": 3}]}]}
    json_path = tmp_path / "panels.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    csv_path = tmp_path / "panels.csv"
    csv_path.write_text(
        "label,cavity_type,turns\n乙组,上趋,1\n乙组,平直,6\n", encoding="utf-8"
    )

    assert "load_panels" in figures.__all__, "公开名须进 __all__"
    assert figures._load_panels is figures.load_panels, "旧私有名须是别名（同一函数对象）"
    assert figures.load_panels(json_path) == payload["panels"]

    # CSV 支路：按 label 分组，rows 为原始行（字符串值由读数层自己转）
    csv_panels = figures.load_panels(csv_path)
    assert [p["label"] for p in csv_panels] == ["乙组"]
    assert len(csv_panels[0]["rows"]) == 2

    # 与读数层对接：返回结构可直接喂 type_oscillation_data
    data = type_oscillation_data(figures.load_panels(json_path))
    assert data["panels"][0]["label"] == "甲组"
    assert data["panels"][0]["counts"][TYPE_LABELS.index("平直")] == [0, 0, 1, 0]
    assert data["panels"][0]["n_plotted"] == 1


def _two_window_wav(path, *, dur=2.0, f_base=330.0, detune_cents=40.0):
    """两个 2 s 窗：第二窗整体升 detune_cents（换窗即换数，判据可分辨）。"""
    t = np.arange(int(SR * dur)) / SR
    vib = 25.0 * np.sin(2 * np.pi * 4.0 * t)
    first = 0.2 * np.sin(2 * np.pi * f_base * t * 2.0 ** (vib / 1200.0))
    second = 0.2 * np.sin(
        2 * np.pi * f_base * 2.0 ** (detune_cents / 1200.0) * t * 2.0 ** (vib / 1200.0)
    )
    sf.write(str(path), np.concatenate([first, second]), SR)
    return path


def test_reference_comparison_from_audio_honours_window_start(tmp_path):
    """换窗即换数：窗起点不同 ⇒ 取到不同音频；三键登记；锚定偏移原样。"""
    from acouscope.visualization import figures

    wav = _two_window_wav(tmp_path / "two_windows.wav")
    assert "reference_comparison_from_audio" in figures.__all__, "公开入口须进 __all__"

    w_first = figures.reference_comparison_from_audio(
        wav,
        tmp_path / "w0",
        window_start_s=0.0,
        window_s=2.0,
        anchor_offset_cents=90.45,
        anchor_source="空弦四弦中位",
        limit=5,
    )
    w_second = figures.reference_comparison_from_audio(
        wav,
        tmp_path / "w2",
        window_start_s=2.0,
        window_s=2.0,
        anchor_offset_cents=90.45,
        anchor_source="空弦四弦中位",
        limit=5,
    )

    for result in (w_first, w_second):
        assert {"window_start_s", "window_s", "tuning_template"} <= set(result)
        assert result["kind"] == "reference_comparison"
        assert result["window_s"] == 2.0
        assert result["tuning_template"] == "12tet"
        # 锚定偏移原样登记（平台不猜）
        assert result["anchor"] == {"offset_cents": 90.45, "source": "空弦四弦中位"}
        assert result["anchor_state"] == "given"
        # 出版参数不降级
        assert result["dpi"] == 300 and set(result["formats"]) == {"png", "pdf"}
        assert result["paths"]["png"].endswith(".png")
    # 窗起点不同 ⇒ 各自落盘目录不同（互不覆盖）
    assert w_first["paths"]["png"].startswith(str(tmp_path / "w0"))
    assert w_second["paths"]["png"].startswith(str(tmp_path / "w2"))

    assert (w_first["window_start_s"], w_second["window_start_s"]) == (0.0, 2.0)

    # 换窗确实换了数：两窗音高差 40 音分 ⇒ 到最近律位的偏离中位数不同
    dev_first = w_first["matrix"]["median_deviation_cents"]["12tet"]
    dev_second = w_second["matrix"]["median_deviation_cents"]["12tet"]
    assert dev_first is not None and dev_second is not None
    assert abs(dev_first - dev_second) > 5.0, (dev_first, dev_second)


# ---------------------------------------------------------------------------
# W-14-03／W-14-04（2026-11-01）：音名口径与图件分母口径
# ---------------------------------------------------------------------------


def test_degree_to_note_name_display_convention():
    """W-14-03：degree → 音名只作显示/索引约定（最近十二平均律半音，升号）。"""
    from acouscope.visualization.figures import NOTE_NAMES_SHARP, degree_to_note_name

    twelve = get_template("12tet")
    assert [degree_to_note_name(twelve, d) for d in range(12)] == list(NOTE_NAMES_SHARP)
    # 八度折叠：第 12 音级回到 C
    assert degree_to_note_name(twelve, 12) == "C"
    # 非十二音级模板同样只用十二平均律作显示约定（不断言律学归属）
    qin = get_template("qin_lu")
    names = [degree_to_note_name(qin, d) for d in range(len(qin.degrees))]
    assert all(name in NOTE_NAMES_SHARP for name in names)
    assert degree_to_note_name(qin, None) is None


def _note_model(f0_list):
    """合成音高网格模型（只含段级 f0 与音级归属，供口径测试）。"""
    from acouscope.analysis.pitch_grid import PitchGridModel, PitchNote

    notes = []
    for index, f0 in enumerate(f0_list):
        notes.append(
            PitchNote(
                start_s=float(index), end_s=float(index) + 0.5, f0_hz=float(f0),
                conf=0.9, state="stable",
                state_runs=((0, 10, float(index), float(index) + 0.5, "stable"),),
            )
        )
    return PitchGridModel(notes=notes)


def test_reference_comparison_note_name_calibre():
    """W-14-03：音名口径与 degree 口径并陈，旧键语义不变。"""
    model = _note_model([220.0, 246.94, 293.66, 329.63, 440.0])
    from acouscope.analysis.pitch_grid import _segment_degree

    for note in model.notes:
        note.degree_index, note.degree_deviation_cents = _segment_degree(
            note.f0_hz, get_template("12tet")
        )
    plain = reference_comparison_data(model, templates=["12tet", "qin_lu"], limit=10)
    rich = reference_comparison_data(
        model, templates=["12tet", "qin_lu"], limit=10, note_name=True
    )
    # 旧键语义不变：两口径并存时 changed_share 与 changed_share_degree 逐位相同
    assert rich["changed_share"] == plain["changed_share"]
    assert rich["changed_share_degree"] == plain["changed_share"]
    # 音名口径字段齐备
    for key in (
        "note_names", "changed_count_note", "changed_share_note",
        "changed_indices_note", "comparable_segments_note",
    ):
        assert key in rich
    assert set(rich["note_names"]) == {"12tet", "qin_lu"}
    assert len(rich["note_names"]["qin_lu"]) == rich["n_segments"]
    assert rich["comparable_segments_note"]["qin_lu"] <= rich["n_segments"]
    # 改判计数与索引一致；占比按「两者均非 None」分母
    for name in ("12tet", "qin_lu"):
        assert rich["changed_count_note"][name] == len(rich["changed_indices_note"][name])
        denom = rich["comparable_segments_note"][name]
        if denom:
            assert rich["changed_share_note"][name] == round(
                rich["changed_count_note"][name] / denom, 4
            )
    # 首模板自比恒 0
    assert rich["changed_count_note"]["12tet"] == 0
    # 口径声明随件（不是律学断言）
    assert "显示" in rich["note_name_note"] and "不可跨音级数" in rich["note_name_note"]


def test_type_oscillation_denominators():
    """W-14-04：all／judgable／body 三档分母与原因分列。"""
    panels = [
        {
            "label": "P",
            "rows": [
                {"cavity_type": "平直", "turns": 0, "valid": True,
                 "low_frequency_unreliable": False},
                {"cavity_type": "平直", "turns": 2, "valid": True,
                 "low_frequency_unreliable": True},   # body 剔除
                {"cavity_type": "上趋", "turns": 1, "valid": False,
                 "low_frequency_unreliable": False},  # judgable 剔除
                {"cavity_type": "未分类", "turns": 3, "valid": True,
                 "low_frequency_unreliable": True},   # composite（同时低频）
                {"cavity_type": "下趋", "turns": None, "valid": True,
                 "low_frequency_unreliable": False},  # no_turns
            ],
        }
    ]
    all_ = type_oscillation_data(panels, denominator="all")
    judg = type_oscillation_data(panels, denominator="judgable")
    body = type_oscillation_data(panels, denominator="body")
    # all＝现行为：只剔非三型/无 turns（valid=False 仍计入）
    assert all_["panels"][0]["n_plotted"] == 3
    # judgable：再剔 osc_invalid（上趋那条）⇒ 平直×2
    assert judg["panels"][0]["n_plotted"] == 2
    # body：再剔低频不可靠 ⇒ 平直×1
    assert body["panels"][0]["n_plotted"] == 1
    assert all_["panels"][0]["denominator"] == "all"
    assert body["panels"][0]["denominator"] == "body"
    # 每型分母与 counts 行和一致
    for payload in (all_, judg, body):
        panel = payload["panels"][0]
        assert panel["denominators_by_type"] == {
            label: sum(panel["counts"][index])
            for index, label in enumerate(payload["types"])
        }
    # 原因独立计数（composite 与 low_frequency 可重叠，不得相加当排除数）
    body_panel = body["panels"][0]
    assert body_panel["reason_totals"] == {
        "composite": 1, "no_turns": 1, "osc_invalid": 1, "low_frequency": 2,
    }
    assert body_panel["excluded_by_reason"] == {
        "composite": 1, "no_turns": 1, "osc_invalid": 1, "low_frequency": 1,
    }
    assert body_panel["n_excluded_total"] == body_panel["excluded"] == 4
    with pytest.raises(ValueError):
        type_oscillation_data(panels, denominator="bogus")
