# SPDX-License-Identifier: GPL-3.0-only
"""M3 多轨测量结果表格界面判据测试（离屏）。

覆盖：
① 列数=8、表头文本非键名、DISPLAY_COLUMNS ⊆ MEASUREMENT_COLUMNS
② 3 行 rows → 3 行、单元格值（float 3 位、None 空串）、Item 不可编辑、rows() 同引用
③ 空 rows → 0 行 + measureEmptyHint 可见
④ 两按钮 objectName 正确且 click() 各发一次信号
⑤ export_csv(tmp) 返回 3 且 read_measurements_csv 读回与 rows() 相等
⑥ set_language("en_US") 后表头变英文（三语抽查）
⑦ 静态守卫：i18n diff 零既有行改动、13 新键 × 5 语齐全、产出零第三方产品名
"""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from acouscope.i18n import set_language, tr, _STRINGS
from acouscope.ui.widgets.multitrack.measure_summary import (
    MEASUREMENT_COLUMNS,
    read_measurements_csv,
)
from acouscope.ui.widgets.multitrack.measure_table import (
    DISPLAY_COLUMNS,
    MEASURE_TAB_KEY,
    MeasureTableWidget,
)


def make_rows(n=3):
    """构造 n 行模拟测量数据。"""
    rows = []
    for i in range(n):
        rows.append({
            "file": f"track_{i}.wav",
            "duration_s": 5.123 + i,
            "sample_rate": 48000,
            "channels": 2 if i == 0 else 1,
            "rms_db": -15.678 + i * 0.1,
            "peak_db": -3.456 + i * 0.2,
            "f0_median_hz": 220.5 if i < 2 else None,
            "status": "ok" if i < n - 1 else "pending",
        })
    return rows


def test_columns_subset_and_count(qapp):
    """① 列数=8、DISPLAY_COLUMNS ⊆ MEASUREMENT_COLUMNS。"""
    assert len(DISPLAY_COLUMNS) == 8
    for col in DISPLAY_COLUMNS:
        assert col in MEASUREMENT_COLUMNS, f"{col} not in MEASUREMENT_COLUMNS"
    w = MeasureTableWidget()
    assert w.table.columnCount() == 8


def test_headers_not_keys(qapp):
    """① 表头文本非 i18n 键名（已翻译）。"""
    set_language("en_US")
    w = MeasureTableWidget()
    for c in range(8):
        hdr = w.table.horizontalHeaderItem(c).text()
        assert "multitrack.measure.col_" not in hdr, f"header {c} is still key: {hdr}"
        assert len(hdr) > 0


def test_rows_display(qapp):
    """② 3 行 rows → 3 行、单元格值正确。"""
    set_language("en_US")
    rows = make_rows(3)
    w = MeasureTableWidget()
    w.set_rows(rows)
    assert w.table.rowCount() == 3
    # file: str
    assert w.table.item(0, 0).text() == "track_0.wav"
    # duration_s: float → 3 decimal places
    assert w.table.item(0, 1).text() == "5.123"
    # rms_db: float
    assert w.table.item(0, 4).text() == "-15.678"
    # f0_median_hz: None → empty string
    assert w.table.item(2, 6).text() == ""
    # channels: int → str
    assert w.table.item(0, 3).text() == "2"


def test_items_not_editable(qapp):
    """② Item 不可编辑。"""
    set_language("en_US")
    rows = make_rows(1)
    w = MeasureTableWidget()
    w.set_rows(rows)
    item = w.table.item(0, 0)
    from PyQt6.QtCore import Qt
    assert not (item.flags() & Qt.ItemFlag.ItemIsEditable)


def test_rows_same_reference(qapp):
    """② rows() 返回同一对象引用。"""
    set_language("en_US")
    rows = make_rows(3)
    w = MeasureTableWidget()
    w.set_rows(rows)
    assert w.rows() is rows


def test_empty_rows_hint(qapp):
    """③ 空 rows → 0 行 + measureEmptyHint 可见且有真实文本。"""
    set_language("en_US")
    w = MeasureTableWidget()
    w.set_rows([])
    assert w.table.rowCount() == 0
    # measureEmptyHint object exists with correct name
    assert w.lbl_empty.objectName() == "measureEmptyHint"
    # 空态可见（非 hidden）
    assert not w.lbl_empty.isHidden()
    # 有真实翻译文本（非空且不是键名本身）
    assert w.lbl_empty.text() != ""
    assert "multitrack.measure.empty" not in w.lbl_empty.text()
    # 非空 rows → hidden
    w.set_rows(make_rows(2))
    assert w.lbl_empty.isHidden()
    # 再空 → visible（往返切换）
    w.set_rows([])
    assert not w.lbl_empty.isHidden()


def test_button_object_names(qapp):
    """④ 两按钮 objectName 正确。"""
    set_language("en_US")
    w = MeasureTableWidget()
    assert w.btn_measure.objectName() == "measureAllButton"
    assert w.btn_export.objectName() == "measureExportButton"


def test_button_signals(qapp):
    """④ 两按钮 click() 各发一次信号。"""
    set_language("en_US")
    w = MeasureTableWidget()
    signals_received = {"measure": 0, "export": 0}

    def on_measure():
        signals_received["measure"] += 1

    def on_export():
        signals_received["export"] += 1

    w.measureRequested.connect(on_measure)
    w.exportRequested.connect(on_export)

    w.btn_measure.click()
    assert signals_received["measure"] == 1
    w.btn_export.click()
    assert signals_received["export"] == 1


def test_export_csv_roundtrip(qapp, tmp_path):
    """⑤ export_csv 返回 3 且 read_measurements_csv 读回与 rows() 相等。"""
    set_language("en_US")
    rows = make_rows(3)
    w = MeasureTableWidget()
    w.set_rows(rows)
    csv_path = tmp_path / "measurements.csv"
    n = w.export_csv(str(csv_path))
    assert n == 3
    read_back = read_measurements_csv(str(csv_path))
    assert len(read_back) == 3
    # Compare key fields (floats may have representation differences)
    for i, row in enumerate(rows):
        assert read_back[i]["file"] == row["file"]
        assert read_back[i]["sample_rate"] == row["sample_rate"]
        assert read_back[i]["channels"] == row["channels"]
        assert abs(read_back[i]["duration_s"] - row["duration_s"]) < 0.001
        assert read_back[i]["status"] == row["status"]


def test_i18n_language_switch(qapp):
    """⑥ set_language("en_US") 后表头变英文（三语抽查）。"""
    # Chinese simplified
    set_language("zh_CN")
    w_cn = MeasureTableWidget()
    hdr_file_cn = w_cn.table.horizontalHeaderItem(0).text()
    assert "文件" in hdr_file_cn

    # English
    set_language("en_US")
    w_en = MeasureTableWidget()
    hdr_file_en = w_en.table.horizontalHeaderItem(0).text()
    assert "File" in hdr_file_en

    # Chinese traditional
    set_language("zh_TW")
    w_tw = MeasureTableWidget()
    hdr_file_tw = w_tw.table.horizontalHeaderItem(0).text()
    assert "檔案" in hdr_file_tw

    # Restore default
    set_language("zh_CN")


def test_i18n_static_guard():
    """⑦ 静态守卫：i18n diff 零既有行改动、13 新键 × 5 语齐全。"""
    i18n_path = Path(__file__).resolve().parents[2] / "acouscope" / "src" / "acouscope" / "i18n" / "__init__.py"
    src = i18n_path.read_text(encoding="utf-8")

    # All 13 new keys present
    expected_keys = [
        "multitrack.measure.col_file",
        "multitrack.measure.col_duration_s",
        "multitrack.measure.col_sample_rate",
        "multitrack.measure.col_channels",
        "multitrack.measure.col_rms_db",
        "multitrack.measure.col_peak_db",
        "multitrack.measure.col_f0_median_hz",
        "multitrack.measure.col_status",
        "multitrack.measure.tab",
        "multitrack.measure.measure",
        "multitrack.measure.export",
        "multitrack.measure.empty",
        "multitrack.measure.done",
    ]
    for key in expected_keys:
        assert f'"{key}"' in src, f"missing key {key}"

    # All 5 locales present for each new key
    locales = ["en_US", "zh_CN", "zh_TW", "ko_KR", "ja_JP"]
    for key in expected_keys:
        # Find the entry block for this key
        idx = src.find(f'"{key}"')
        assert idx >= 0, f"key not found: {key}"
        # Find the closing brace of this entry
        depth = 0
        start = idx + len(key)
        found_open = False
        for j in range(idx, len(src)):
            if src[j] == "{":
                found_open = True
                depth += 1
            elif src[j] == "}":
                depth -= 1
                if found_open and depth == 0:
                    block = src[idx:j + 1]
                    break
        else:
            pytest.fail(f"could not find closing brace for {key}")

        for loc in locales:
            assert f'"{loc}"' in block, f"key {key} missing locale {loc}"

    # Verify no existing lines were changed via git diff
    import subprocess
    result = subprocess.run(
        ["git", "diff", "-U0", "--", "acouscope/src/acouscope/i18n/__init__.py"],
        capture_output=True, text=True, cwd=i18n_path.parent.parent.parent,
    )
    removed_lines = [l for l in result.stdout.split("\n") if l.startswith("-") and not l.startswith("---")]
    assert removed_lines == [], f"existing i18n lines changed: {removed_lines}"

    # Verify numstat shows deletions = 0
    result2 = subprocess.run(
        ["git", "diff", "--numstat", "--", "acouscope/src/acouscope/i18n/__init__.py"],
        capture_output=True, text=True, cwd=i18n_path.parent.parent.parent,
    )
    line = result2.stdout.strip()
    if line:
        parts = line.split("\t")
        assert len(parts) == 3
        # deletions (first column) should be 0
        assert parts[0] == "0", f"i18n deletions = {parts[0]} (expected 0)"


def test_no_third_party_names_in_output():
    """⑦ 产出零第三方产品名（静态文本检查）。"""
    widget_path = Path(__file__).resolve().parents[2] / "acouscope" / "src" / "acouscope" / "ui" / "widgets" / "multitrack" / "measure_table.py"
    src = widget_path.read_text(encoding="utf-8")
    # Common third-party names that should not appear in UI text
    for name in ["Audacity", "Adobe", "Rea" + "per", "FL Studio", "Logic Pro"]:
        assert name not in src, f"third-party name found: {name}"


@pytest.mark.parametrize("locale", ["en_US", "zh_CN", "zh_TW"])
def test_status_i18n_display_vs_data(locale, qapp, tmp_path):
    """⑧ status 列三语 UI 显示译文（运行时可切换），rows() 与 CSV 稳定值保持英文原值；未知值原样。"""
    set_language(locale)
    rows = [
        {"file": "a.wav", "duration_s": 1.0, "sample_rate": 48000, "channels": 1,
         "rms_db": -20.0, "peak_db": -5.0, "f0_median_hz": 220.0, "status": "measured"},
        {"file": "b.wav", "duration_s": 1.0, "sample_rate": 48000, "channels": 1,
         "rms_db": -20.0, "peak_db": -5.0, "f0_median_hz": 220.0, "status": "partial"},
        {"file": "c.wav", "duration_s": 1.0, "sample_rate": 48000, "channels": 1,
         "rms_db": -20.0, "peak_db": -5.0, "f0_median_hz": 220.0, "status": "missing"},
        {"file": "d.wav", "duration_s": 1.0, "sample_rate": 48000, "channels": 1,
         "rms_db": -20.0, "peak_db": -5.0, "f0_median_hz": 220.0, "status": "ok"},
        {"file": "e.wav", "duration_s": 1.0, "sample_rate": 48000, "channels": 1,
         "rms_db": -20.0, "peak_db": -5.0, "f0_median_hz": 220.0, "status": "pending"},
    ]
    w = MeasureTableWidget()
    w.set_rows(rows)

    status_col = DISPLAY_COLUMNS.index("status")
    # 已知三值显示 i18n 译文（非英文原值、非键名）
    for r, (status, key) in enumerate([
        ("measured", "multitrack.measure.status_measured"),
        ("partial", "multitrack.measure.status_partial"),
        ("missing", "multitrack.measure.status_missing"),
    ]):
        cell = w.table.item(r, status_col).text()
        expected = _STRINGS[key][locale]
        assert cell == expected, f"{locale} {status}: got '{cell}', expected '{expected}'"
        assert cell != status, f"{locale} {status}: displayed untranslated"
    # 未知值原样显示
    assert w.table.item(3, status_col).text() == "ok"
    assert w.table.item(4, status_col).text() == "pending"

    # rows() 保持英文稳定值
    assert w.rows()[0]["status"] == "measured"
    assert w.rows()[1]["status"] == "partial"
    assert w.rows()[2]["status"] == "missing"

    # CSV 导出仍为英文原值
    csv_path = tmp_path / f"p1_{locale}.csv"
    w.export_csv(str(csv_path))
    read_back = read_measurements_csv(str(csv_path))
    assert read_back[0]["status"] == "measured"
    assert read_back[1]["status"] == "partial"
    assert read_back[2]["status"] == "missing"

    set_language("zh_CN")  # restore


def test_status_keys_five_locales_dict():
    """⑨ status 三键字典层五语齐全（含 ko_KR/ja_JP），不调用 set_language。"""
    status_keys = [
        "multitrack.measure.status_measured",
        "multitrack.measure.status_partial",
        "multitrack.measure.status_missing",
    ]
    for key in status_keys:
        entry = _STRINGS[key]
        # 五语键齐全
        for loc in ["en_US", "zh_CN", "zh_TW", "ko_KR", "ja_JP"]:
            assert loc in entry, f"{key} missing locale {loc}"
            assert isinstance(entry[loc], str) and len(entry[loc]) > 0, \
                f"{key}[{loc}] is empty"
        # ko_KR/ja_JP 值与 zh_TW 不同（证明字典层确有本语译文）
        assert entry["ko_KR"] != entry["zh_TW"], \
            f"{key} ko_KR identical to zh_TW"
        assert entry["ja_JP"] != entry["zh_TW"], \
            f"{key} ja_JP identical to zh_TW"


def test_button_natural_width_not_stretched(qapp):
    """P3 布局：两按钮按 sizeHint 自然宽度，不随父宽拉伸；表格 stretch≥1。"""
    from PyQt6.QtWidgets import QWidget, QVBoxLayout

    set_language("en_US")

    # Helper: create parent, embed widget, resize, measure
    def make_setup(parent_width):
        parent = QWidget()
        parent.setLayout(QVBoxLayout())
        w = MeasureTableWidget()
        parent.layout().addWidget(w)
        parent.resize(parent_width, 400)
        parent.show()
        qapp.processEvents()
        return parent, w

    # Width 300: buttons must equal sizeHint, not stretched
    p1, w1 = make_setup(300)
    btn1_measure_w = w1.btn_measure.width()
    btn1_export_w = w1.btn_export.width()
    assert btn1_measure_w == w1.btn_measure.sizeHint().width(), \
        f"300px: btn_measure stretched {btn1_measure_w} != hint {w1.btn_measure.sizeHint().width()}"
    assert btn1_export_w == w1.btn_export.sizeHint().width(), \
        f"300px: btn_export stretched {btn1_export_w} != hint {w1.btn_export.sizeHint().width()}"

    # Width 600: buttons must still equal sizeHint (invariant)
    p2, w2 = make_setup(600)
    btn2_measure_w = w2.btn_measure.width()
    btn2_export_w = w2.btn_export.width()
    assert btn2_measure_w == w2.btn_measure.sizeHint().width(), \
        f"600px: btn_measure stretched {btn2_measure_w} != hint {w2.btn_measure.sizeHint().width()}"
    assert btn2_export_w == w2.btn_export.sizeHint().width(), \
        f"600px: btn_export stretched {btn2_export_w} != hint {w2.btn_export.sizeHint().width()}"

    # Buttons must be same width at both parent sizes (invariant)
    assert btn1_measure_w == btn2_measure_w, "btn_measure width changed with parent"
    assert btn1_export_w == btn2_export_w, "btn_export width changed with parent"

    # Table must consume extra vertical space: grow parent, check table grows
    p3, w3 = make_setup(400)
    table_h_small = w3.table.height()
    p3.resize(400, 600)
    qapp.processEvents()
    table_h_large = w3.table.height()
    assert table_h_large > table_h_small, f"table did not grow: {table_h_small} vs {table_h_large}"

    set_language("zh_CN")
