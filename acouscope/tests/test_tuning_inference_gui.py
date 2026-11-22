# SPDX-License-Identifier: GPL-3.0-only
"""W-14-08／B6 律制推断 GUI 判据（``test_tuning_inference_gui.py``）。

四面（设计约定 §3.9）：
① 模板池 **8 项全列**（含 ``indian_22_shruti``／``arabic_24_tone``），「论文六模板」
  预设 6 项、「全部八模板」恢复 8 项；
② 推断可跑、结果按 ``score`` 降序、每项 ``template_source`` 非空、``margin`` 与
   ``top_k`` 生效；
③ 导出 JSON 与 GUI 表同源，且与 CLI helper（``infer_tuning_from_audio``）逐值一致；
④ 模板表守卫不变（本单不得改 ``templates.py``）、文案不含「符合某律」。
"""

import json

import numpy as np
import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("soundfile")

import soundfile as sf  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from acouscope.analysis.tuning_infer_audio import infer_tuning_from_audio  # noqa: E402
from acouscope.analysis.tunings.templates import (  # noqa: E402
    get_template,
    list_paper_templates,
    list_templates,
)
from acouscope.i18n import set_language  # noqa: E402
from acouscope.ui.widgets.tuning_inference_dialog import TuningInferenceDialog  # noqa: E402

SR = 22050


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    set_language("zh_CN")
    yield app


@pytest.fixture(scope="module")
def tone_wav(tmp_path_factory):
    """合成音（纯律大三和弦；只验链路与契约，不含真实录音）。"""
    path = tmp_path_factory.mktemp("infer") / "chord.wav"
    t = np.arange(int(SR * 1.2)) / SR
    sig = sum(
        0.12 * np.sin(2 * np.pi * 220.0 * ratio * t)
        for ratio in (1.0, 5 / 4, 3 / 2)
    )
    sf.write(str(path), sig, SR)
    return path


# ---------------------------------------------------------------- 面 ①
def test_template_pool_lists_all_eight(qapp, tone_wav):
    dlg = TuningInferenceDialog(audio_path=str(tone_wav))
    items = dlg.template_items()
    assert len(items) == 8 == len(list_templates())
    assert "indian_22_shruti" in items and "arabic_24_tone" in items
    assert dlg.checked_templates() == items          # 默认全选
    dlg.apply_paper_preset()
    paper = dlg.checked_templates()
    assert len(paper) == 6 == len(list_paper_templates())
    assert "indian_22_shruti" not in paper
    dlg.apply_all_preset()
    assert len(dlg.checked_templates()) == 8
    # 模板表 source 未被清空（B6 不得改模板表）
    assert all(get_template(key).source for key in list_templates())
    dlg.close()


# ---------------------------------------------------------------- 面 ②③
def test_inference_runs_and_matches_cli(qapp, tone_wav):
    dlg = TuningInferenceDialog(audio_path=str(tone_wav), top_k=3)
    payload = dlg.compute()
    matches = list(payload["matches"])
    assert matches and len(matches) <= 3
    assert [m["rank"] for m in matches] == list(range(1, len(matches) + 1))
    scores = [m["score"] for m in matches]
    assert scores == sorted(scores, reverse=True)
    assert all(m["template_source"] for m in matches)
    assert all("margin" in m for m in matches)
    # 与 CLI helper 同输入逐值一致
    cli = infer_tuning_from_audio(
        str(tone_wav), window_s=dlg.window_s(),
        template_keys=dlg.checked_templates(), top_k=3,
    )
    assert cli["matches"] == matches
    # GUI 表与 JSON 同源
    rows = dlg.table_rows()
    assert len(rows) == len(matches)
    for row, match in zip(rows, matches):
        assert row["rank"] == str(match["rank"])
        assert row["template_name"] == match["template_name"]
        assert float(row["score"]) == pytest.approx(match["score"], abs=5e-4)
    dlg.close()


def test_export_json_same_source(qapp, tone_wav, tmp_path):
    dlg = TuningInferenceDialog(audio_path=str(tone_wav), top_k=2)
    dlg.compute()
    out = dlg.export_json(tmp_path / "infer.json")
    back = json.loads(out.read_text(encoding="utf-8"))
    assert back["matches"] == dlg.payload["matches"]
    assert back["source"]["audio_sha256"] == dlg.payload["source"]["audio_sha256"]
    assert back["template_pool"] == dlg.template_items()
    dlg.close()


# ---------------------------------------------------------------- 面 ④
def test_claim_wording_and_guard_untouched(qapp, tone_wav):
    """文案只写候选/排序；模板表与既有守卫测试未被改动。"""
    dlg = TuningInferenceDialog(audio_path=str(tone_wav))
    text = " ".join(
        [dlg.lbl_note.text(), dlg.windowTitle(), dlg.lbl_summary.text()]
    )
    # 只允许「不作…断言」的否定式出现；不得出现肯定式归属断言
    assert "不作" in text and "断言" in text
    assert "属于某律" not in text and "为本律" not in text
    payload = dlg.compute()
    note = payload["claim_note"]
    assert "不称" in note
    # 肯定式断言不得单独出现（一律以「不称…」的否定式包裹）
    assert note.count("属于某律") == note.count("不称「该曲属于某律」")
    # 八模板与 source 守卫仍在（既有测试文件的守卫计数未被弱化）
    from pathlib import Path

    guard = Path(__file__).with_name("test_tunings_templates.py")
    body = guard.read_text(encoding="utf-8")
    assert body.count("indian_22_shruti") + body.count("arabic_24_tone") >= 12
    dlg.close()
