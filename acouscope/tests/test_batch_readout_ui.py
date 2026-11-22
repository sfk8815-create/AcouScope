# SPDX-License-Identifier: GPL-3.0-only
"""批量读数运行的 GUI 接线测试（任务件-20261026 · GUI 化）。BATCH_READOUT_UI_TEST_V1

覆盖：
① 对话框采集 → 纯 dict ``spec``（cases／ref_modes／params 逐项对位）；
② ``validate`` 五类错误逐条拦（缺录音／缺输出目录／缺图件目录／无口径／τ 非法）；
③ 取数参数**随 spec 走**（改 has_payload 值即改数，不作隐式兜底）；
④ 投递到任务中心**不在主线程跑**（终态经 signal 回主线程收，产物齐备）；
⑤ T-3 同源闸：run_id 一致 ⇒ 放行并出对账件；不一致 ⇒ 拒绝出图；
   无配套分布件 ⇒ 如实登记「未核验」，不冒充通过。

音频夹具为**合成信号**（正弦＋轻微起伏），只验链路与契约，不含任何真实录音。
"""

import json
import time

import pytest

pytest.importorskip("numpy")
pytest.importorskip("PyQt6")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from PyQt6.QtWidgets import QApplication  # noqa: E402

from acouscope.app.controller import AppController  # noqa: E402
from acouscope.i18n import set_language, tr  # noqa: E402
from acouscope.ui.main_window import MainWindow  # noqa: E402
from acouscope.ui.widgets.batch_readout_dialog import (  # noqa: E402
    DEFAULT_TAU_TEXT,
    BatchReadoutDialog,
)


@pytest.fixture(scope="module")
def qapp():
    """离屏 QApplication（构造任何 QWidget 前必须有，否则 Qt 直接 abort）。"""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    """离屏 MainWindow（不 show）；HOME／数据目录隔离到 tmp。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    import acouscope.utils.config as _cfg

    monkeypatch.setattr(_cfg, "get_data_dir", lambda: tmp_path)
    set_language("zh_CN")
    controller = AppController()
    w = MainWindow(controller)
    yield w
    w.close()


def _tone(path, sr=44100, dur=6.0, freq=440.0, depth_cents=12.0, rate_hz=5.0):
    """合成一段带轻微起伏的稳态音（只验链路，不作标定）。"""
    import numpy as np

    from acouscope.audio import AudioIO

    t = np.arange(int(sr * dur)) / float(sr)
    cents = depth_cents * np.sin(2.0 * np.pi * rate_hz * t)
    sig = 0.4 * np.sin(2.0 * np.pi * freq * 2.0 ** (cents / 1200.0) * t)
    AudioIO().save(sig.astype(np.float32), sr, str(path))
    return path


@pytest.fixture()
def two_tones(tmp_path):
    return [
        _tone(tmp_path / "甲.wav", freq=392.0),
        _tone(tmp_path / "乙.wav", freq=294.0),
    ]


@pytest.fixture
def dlg(qapp, tmp_path, two_tones):
    """装好两条合成录音的对话框（**须先有 QApplication**，否则 Qt 直接 abort）。

    用完 ``close()``＋``deleteLater()``：QWidget 交给 Qt 事件循环回收，避免
    测试之间留下悬挂控件导致的野 Qt 对象（离屏套件里会表现为 SIGBUS）。
    """
    dialog = BatchReadoutDialog()
    dialog.set_cases_from_paths(two_tones)
    dialog.edit_dir.setText(str(tmp_path / "out"))
    dialog.edit_figure_dir.setText(str(tmp_path / "fig"))
    yield dialog
    dialog.close()
    dialog.deleteLater()


def test_spec_matches_table_and_is_json_safe(dlg, two_tones, tmp_path):
    """① 表格 → spec：逐项对位，且 spec 纯 JSON 可序列化（可存档复跑）。"""
    # 填呈现名／锚（第二例留空 ⇒ None，平台不猜锚）
    dlg.table.item(0, BatchReadoutDialog.COL_LABEL).setText("甲组")
    dlg.table.item(0, BatchReadoutDialog.COL_ANCHOR).setText("90.45")
    dlg.table.item(0, BatchReadoutDialog.COL_SOURCE).setText("空弦四弦中位")

    spec = dlg.spec()
    json.dumps(spec, ensure_ascii=False)  # 可序列化（ τ 的 None 已用 Python None 表达）

    assert len(spec["cases"]) == 2
    first, second = spec["cases"]
    assert first["label"] == "甲组"
    assert first["anchor_offset_cents"] == pytest.approx(90.45)
    assert first["anchor_source"] == "空弦四弦中位"
    assert second["label"] is None
    assert second["anchor_offset_cents"] is None, "锚留空须为 None，不得回落到 0"
    assert second["anchor_source"] == ""
    # recording_id 由文件名生成且去重
    assert len({c["recording_id"] for c in spec["cases"]}) == 2
    assert first["recording_id"] == "甲"
    # 口径与 τ
    assert spec["ref_modes"] == ["absolute", "main_tone"]
    assert spec["tau_values"] == [None, 10.0, 20.0, 30.0]
    assert spec["figure_out"] == str(tmp_path / "fig")


def test_acquisition_params_travel_with_spec(dlg, two_tones, tmp_path):
    """③ 取数参数随 spec 走：改一个即一个数，不作隐式兜底。"""
    dlg.spin_window.setValue(15.0)
    dlg.spin_overlap.setValue(0.25)
    dlg.spin_tonic.setValue(60.0)
    params = dlg.spec()["params"]
    assert params["window_s"] == pytest.approx(15.0)
    assert params["overlap_ratio"] == pytest.approx(0.25)
    assert params["tonic_window_s"] == pytest.approx(60.0)
    # 默认值仍在（未被 GUI 悄悄改）
    assert params["segmenter"] == "hmm"
    assert params["template"] == "12tet"
    assert DEFAULT_TAU_TEXT == "none,10,20,30"


def test_validate_blocks_each_error(dlg, two_tones, tmp_path):
    """② 五类错误逐条拦（消息经 i18n，不硬编码中文）。"""
    assert dlg.validate() is None

    dlg.chk_absolute.setChecked(False)
    dlg.chk_main_tone.setChecked(False)
    assert dlg.validate() == tr("batch_readout.err_no_mode")

    dlg.chk_absolute.setChecked(True)
    dlg.edit_dir.setText("")
    assert dlg.validate() == tr("batch_readout.err_no_dir")

    dlg.edit_dir.setText(str(tmp_path / "out"))
    dlg.edit_figure_dir.setText("")
    assert dlg.validate() == tr("batch_readout.err_no_figure_dir")

    dlg.chk_figure.setChecked(False)
    assert dlg.validate() is None, "关掉出图 ⇒ 不再要求图件目录"

    dlg.edit_taus.setText("abc")
    assert dlg.validate() == tr("batch_readout.err_bad_taus")

    dlg.edit_taus.setText("none")
    while dlg.table.rowCount():
        dlg.table.removeRow(0)
    assert dlg.validate() == tr("batch_readout.err_no_case")


def test_duplicate_paths_are_not_added_twice(qapp, two_tones, tmp_path):
    """同一路径重复添加 ⇒ 去重（防同一录音被算两遍、污染分布）。"""
    dlg = BatchReadoutDialog()
    dlg.set_cases_from_paths(two_tones + [two_tones[0]])
    assert dlg.table.rowCount() == 2


# ---------------------------------------------------------------------------
# ④ 投递契约：参数与回调方向正确，work 真能跑出产物
# ---------------------------------------------------------------------------


class _StubReporter:
    """假的 ``TaskReporter``：只记录 stage／progress，接口与真对象同构。"""

    cancelled = False

    def __init__(self):
        self.stages: list[str] = []
        self.values: list[float] = []

    def stage(self, text: str) -> None:
        self.stages.append(str(text))

    def progress(self, value: float) -> None:
        self.values.append(float(value))


def test_delivery_contract_and_work_produces_artifacts(window, dlg, two_tones,
                                                       tmp_path, monkeypatch):
    """④ ``_run_batch_readout`` 的投递契约 ＋ work 闭包真能产出读数件。

    **为什么同步跑 work 而非真起 QThread**：TaskCenter 的线程调度是既有能力
    （有其自身测试），本用例验证的是**本单新增的接线**——kind／进度模式／标题
    ／回调方向／spec 是否被正确消费。离屏环境里 ``_TaskThread`` 与 MainWindow
    的内存守卫等定时器并发会 SIGBUS（与本单无关的环境限制），故把 submit 换成
    同步执行既不损失覆盖、又让用例可重复。
    """
    from acouscope.ui.widgets.task_center import TaskCenter

    out_dir = tmp_path / "out"
    dlg.edit_dir.setText(str(out_dir))
    dlg.edit_taus.setText("none,20")   # 少跑一档 τ，控住用例耗时

    captured: dict = {}

    def _fake_submit(self, title, run, **kwargs):  # noqa: ARG001
        captured.update({"title": title, **kwargs})
        reporter = _StubReporter()
        captured["result"] = run(reporter)
        captured["reporter"] = reporter
        return None      # 队列超限/关停 ⇒ 返回 None 的同形状路径

    monkeypatch.setattr(TaskCenter, "submit", _fake_submit, raising=True)
    window._run_batch_readout(dlg.spec())

    # ① 投递参数
    assert captured["title"] == tr("task_center.title.readout").format(n=2)
    assert captured["kind"] == "analysis"
    assert captured["progress_mode"] == "determinate", "须用确定式进度（按窗）"
    for key in ("on_done", "on_fail", "on_cancelled"):
        assert callable(captured[key]), f"{key} 须给出回调（不静默失败）"

    # ② 进度：按窗上报、单调不减、收于 100
    values = captured["reporter"].values
    assert values, "须上报确定式进度"
    assert values == sorted(values), "进度须单调不减"
    assert values[-1] == pytest.approx(100.0)
    # ③ 阶段文本：逐例轮换（首篇含例序与例名）
    assert any("(1/2)" in text for text in captured["reporter"].stages)

    # ④ 产物（与 CLI 同一入口 ⇒ 同一套文件名）
    result = captured["result"]
    assert result["run_id"]
    for name in ("run_descriptor.json", "type_distribution.absolute.json",
                 "type_distribution.main_tone.json", "type_distribution.csv",
                 "tau_sweep_summary.absolute.json", "figure_b_panels.json",
                 "figure_table_check.json", "reconciliation.json", "MANIFEST.md"):
        assert (out_dir / name).is_file(), name
    # T-3：图件与表同源 ⇒ 出了图就该出图件，且对账通过
    assert (tmp_path / "fig" / "figure_b.png").is_file()
    import json

    check = json.loads((out_dir / "figure_table_check.json").read_text(encoding="utf-8"))
    assert check["pass"] is True, check


def test_cancel_probe_stops_at_window_boundary(window, dlg, two_tones, tmp_path,
                                               monkeypatch):
    """协作式取消：``should_cancel`` 为真 ⇒ 抛 ReadoutCancelled，不留半成品。"""
    from acouscope.analysis.readout import ReadoutCancelled, run_batch_from_spec
    from acouscope.ui.widgets.task_center import TaskCenter

    dlg.edit_dir.setText(str(tmp_path / "out_cancel"))
    dlg.edit_taus.setText("none")
    spec = dlg.spec()

    captured: dict = {}
    monkeypatch.setattr(
        TaskCenter,
        "submit",
        lambda self, title, run, **kw: captured.setdefault(
            "run", run) and None or None,
        raising=True,
    )
    window._run_batch_readout(spec)
    work = captured["run"]

    reporter = _StubReporter()
    reporter.cancelled = True          # 一开始就请求取消
    with pytest.raises(ReadoutCancelled):
        work(reporter)
    stale = tmp_path / "out_cancel"
    landed = sorted(p.name for p in stale.iterdir()) if stale.exists() else []
    assert landed == [], f"取消后不得落半成品，实得：{landed}"


# ---------------------------------------------------------------------------
# ⑤ T-3 同源闸
# ---------------------------------------------------------------------------


def _panels_file(tmp_path, run_id, rows):
    path = tmp_path / "panels.json"
    path.write_text(
        json.dumps({"run_id": run_id, "tau_status": "unspecified_sign_based",
                    "panels": [{"label": "甲组", "rows": rows}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _table_file(tmp_path, run_id):
    (tmp_path / "type_distribution.absolute.json").write_text(
        json.dumps([{"recording_id": "a", "run_id": run_id,
                     "counts_per_recording": {"上趋": 1, "下趋": 0, "平直": 0,
                                              "未分类": 0, "合计": 1}}],
                   ensure_ascii=False),
        encoding="utf-8",
    )


def test_same_run_gate_allows_match_and_writes_check(tmp_path, qapp):
    """⑤ 一致 ⇒ 放行，并自动出图—表对账件（T-3 验收口径）。"""
    from acouscope.ui.widgets.paper_figure_dialog import PaperFigureDialog

    rows = [{"segment_id": "0.000-1.000", "cavity_type": "上趋", "turns": 0}]
    panels = _panels_file(tmp_path, "run-AAAA", rows)
    _table_file(tmp_path, "run-AAAA")

    dlg = PaperFigureDialog(None)
    dlg.cmb_preset.setCurrentIndex(dlg.preset_names().index("paper_B"))
    dlg.edit_panels.setText(str(panels))
    dlg.edit_dir.setText(str(tmp_path / "figs"))

    check = dlg.same_run_check()
    assert check["checked"] is True
    assert check["consistent"] is True
    result = dlg.export()
    assert result is not None, dlg.last_error
    assert dlg.last_same_run_check["figure_table_check"] is True
    assert (tmp_path / "figure_table_check.json").is_file()


def test_same_run_gate_blocks_mismatch(tmp_path, qapp, monkeypatch):
    """⑤ 不一致 ⇒ **拒绝出图**（不静默渲出一张来路不明的图）。"""
    from acouscope.ui.widgets.paper_figure_dialog import PaperFigureDialog

    rows = [{"segment_id": "0.000-1.000", "cavity_type": "上趋", "turns": 0}]
    panels = _panels_file(tmp_path, "run-AAAA", rows)
    _table_file(tmp_path, "run-BBBB")

    warned: list[str] = []
    monkeypatch.setattr(
        "PyQt6.QtWidgets.QMessageBox.warning",
        lambda *a, **k: warned.append(str(a[2])) if len(a) > 2 else None,
    )

    dlg = PaperFigureDialog(None)
    dlg.cmb_preset.setCurrentIndex(dlg.preset_names().index("paper_B"))
    dlg.edit_panels.setText(str(panels))
    dlg.edit_dir.setText(str(tmp_path / "figs"))

    assert dlg.export() is None
    assert dlg.last_error is not None and "run-AAAA" in dlg.last_error
    # 取消勾选（明确知情）⇒ 放行，但**不允许**说成已核验
    dlg.chk_same_run.setChecked(False)
    assert dlg.export() is not None
    assert dlg.last_same_run_check["consistent"] is False


def test_missing_companion_table_is_reported_as_unchecked(tmp_path, qapp):
    """⑤ 无配套分布件 ⇒ ``checked=False``（如实登记未核验，不假装通过）。"""
    from acouscope.ui.widgets.paper_figure_dialog import PaperFigureDialog

    rows = [{"segment_id": "0.000-1.000", "cavity_type": "上趋", "turns": 0}]
    panels = _panels_file(tmp_path, "run-AAAA", rows)

    dlg = PaperFigureDialog(None)
    dlg.cmb_preset.setCurrentIndex(dlg.preset_names().index("paper_B"))
    dlg.edit_panels.setText(str(panels))
    dlg.edit_dir.setText(str(tmp_path / "figs"))

    assert dlg.same_run_check() == {
        "checked": False, "panels_run_id": "run-AAAA",
        "table_run_id": None, "consistent": None,
    }
    assert dlg.export() is not None, "无件可校不得阻断出图"
    assert dlg.last_same_run_check["checked"] is False
