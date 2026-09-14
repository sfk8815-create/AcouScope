# SPDX-License-Identifier: GPL-3.0-only
"""T-1017 赞助致谢框（极温和启动问候）测试。

覆盖：
① 状态模块 acouscope/state.py（first_run 初始化 / 2h 判定 / dismissed 持久化 / 容错）；
② SponsorDialog 形态（非模态 / 无 exec / 双二维码并排 / 缺失占位 / 两按钮 / Esc 关闭）；
③ 启动接线（错峰顺序 / 单次启动只弹一次 / dismissed 后不弹）；
④ 静态纪律（禁词 0 / 无 hex-px / QDialog 白名单登记 / 文案禁改字 / 不构造主窗口顶层显示）。

纪律：全部离屏，不构造主窗口顶层显示（GUI_backlog #6）；数据目录由 conftest
autouse fixture 统一重定向到 tmp_path。
"""

from __future__ import annotations

import json
import pathlib
import re
from datetime import datetime, timedelta

import numpy as np
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

import acouscope.i18n as _i18n
import acouscope.state as _state
from acouscope.i18n import available_languages, set_language, tr
from acouscope.ui.widgets import sponsor_dialog as _sd

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src" / "acouscope"
_WIDGETS_DIR = _SRC / "ui" / "widgets"
_SPONSOR_SRC = (_WIDGETS_DIR / "sponsor_dialog.py").read_text(encoding="utf-8")
_STATE_SRC = (_SRC / "state.py").read_text(encoding="utf-8")
_MAIN_WINDOW_SRC = (_SRC / "ui" / "main_window.py").read_text(encoding="utf-8")

#: 用户定稿正文（禁改字基线）——逐字照录
_USER_HEADING_ZH = "感谢您支持 AcouScope·音析。"
_USER_BODY_ZH = (
    "AcouScope 为开源自由软件，所有功能永久免费可用。\n"
    "若它曾助益您的工作，我们诚挚欢迎您自愿予以支持。\n"
    "赞助金额与方式皆由您酌定（建议参考 12 元，无上限），完全自愿，不影响任何功能。\n"
    "\n"
    "您的每一份支持，都将用于推进 AcouScope 的持续进步！"
)

_SPONSOR_KEYS = [
    "sponsor.window_title",
    "sponsor.heading",
    "sponsor.body",
    "sponsor.qr_zhifubao",
    "sponsor.qr_weixin",
    "sponsor.qr_missing",
    "sponsor.continue",
    "sponsor.dismiss",
]


def _write_app_state(tmp_path: pathlib.Path, payload: dict) -> None:
    (tmp_path / "app_state.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _first_run_ago(hours: float) -> str:
    return (datetime.now() - timedelta(hours=hours)).isoformat(timespec="seconds")


@pytest.fixture
def zh_cn():
    """临时切到简体中文（断言用户定稿原文），用后恢复。"""
    original = _i18n.get_language()
    set_language("zh_CN")
    yield
    set_language(original)


# ---------------------------------------------------------------------------
# ① 状态模块
# ---------------------------------------------------------------------------


class TestState:
    def test_first_run_recorded_once(self, tmp_path):
        base = datetime(2026, 1, 1, 9, 0, 0)
        first = _state.ensure_first_run(base)
        assert first == base
        # 已存在则不覆盖（第二次传入更晚时间仍返回首次值）
        again = _state.ensure_first_run(base + timedelta(days=5))
        assert again == base
        assert _state.get_first_run_timestamp() == base
        assert _state.state_path() == tmp_path / "app_state.json"

    def test_should_show_before_two_hours_false(self, tmp_path):
        base = datetime(2026, 1, 1, 9, 0, 0)
        _state.ensure_first_run(base)
        assert _state.should_show_sponsor_reminder(base + timedelta(minutes=119)) is False

    def test_should_show_at_and_after_two_hours_true(self, tmp_path):
        base = datetime(2026, 1, 1, 9, 0, 0)
        _state.ensure_first_run(base)
        assert _state.should_show_sponsor_reminder(base + timedelta(hours=2)) is True
        assert _state.should_show_sponsor_reminder(base + timedelta(hours=26)) is True

    def test_dismissed_persists_and_suppresses(self, tmp_path):
        base = datetime(2026, 1, 1, 9, 0, 0)
        _state.ensure_first_run(base)
        assert _state.is_sponsor_reminder_dismissed() is False
        assert _state.set_sponsor_reminder_dismissed(True) is True
        assert _state.is_sponsor_reminder_dismissed() is True
        assert _state.should_show_sponsor_reminder(base + timedelta(hours=48)) is False
        # 跨进程持久化：重新读盘仍为 True
        raw = json.loads((tmp_path / "app_state.json").read_text(encoding="utf-8"))
        assert raw["sponsor_reminder_dismissed"] is True
        assert raw["first_run_timestamp"] == base.isoformat(timespec="seconds")

    def test_corrupt_state_tolerated(self, tmp_path):
        (tmp_path / "app_state.json").write_text("{ not json", encoding="utf-8")
        assert _state.load_state() == {}
        assert _state.get_first_run_timestamp() is None
        assert _state.is_sponsor_reminder_dismissed() is False
        # 损坏时判定为「不弹」，且 ensure_first_run 能自愈重写
        assert _state.should_show_sponsor_reminder() is False
        base = datetime(2026, 1, 1, 9, 0, 0)
        assert _state.ensure_first_run(base) == base
        assert _state.get_first_run_timestamp() == base

    def test_non_dict_and_missing_tolerated(self, tmp_path):
        (tmp_path / "app_state.json").write_text("[1, 2, 3]", encoding="utf-8")
        assert _state.load_state() == {}
        (tmp_path / "app_state.json").unlink()
        assert _state.load_state() == {}

    def test_bad_timestamp_and_unwritable_tolerated(self, tmp_path):
        _write_app_state(tmp_path, {"first_run_timestamp": "not-a-date"})
        assert _state.get_first_run_timestamp() is None
        assert _state.should_show_sponsor_reminder() is False
        # 写入路径不可用时返回 False，不抛
        blocker = tmp_path / "app_state.json"
        blocker.unlink()
        blocker.mkdir()
        assert _state.save_state({"first_run_timestamp": _first_run_ago(3)}) is False

    def test_delay_constant_is_two_hours(self):
        assert _state.SPONSOR_REMINDER_DELAY == timedelta(hours=2)

    def test_state_module_never_touches_license(self, tmp_path):
        # 行为口径：数据目录内的 license.json 不读不写不改，状态只落 app_state.json
        stale = tmp_path / "license.json"
        stale.write_text('{"code": "KEEP-AS-IS"}', encoding="utf-8")
        before = stale.read_text(encoding="utf-8")
        _state.ensure_first_run(datetime(2026, 1, 1, 9, 0, 0))
        _state.set_sponsor_reminder_dismissed(True)
        assert stale.read_text(encoding="utf-8") == before
        assert _state.state_path().name == "app_state.json"
        assert (tmp_path / "app_state.json").exists()
        assert sorted(p.name for p in tmp_path.iterdir()) == [
            "app_state.json",
            "license.json",
        ]


# ---------------------------------------------------------------------------
# ② SponsorDialog 形态
# ---------------------------------------------------------------------------


class TestSponsorDialog:
    def test_non_modal_no_exec(self, qapp):
        dlg = _sd.SponsorDialog()
        try:
            assert dlg.isModal() is False
            assert "setModal(False)" in _SPONSOR_SRC
            assert ".exec(" not in _SPONSOR_SRC
        finally:
            dlg.close()

    def test_two_qr_codes_side_by_side_with_resource(self, qapp):
        dlg = _sd.SponsorDialog()
        try:
            labels = dlg.qr_labels()
            assert len(labels) == 2  # 支付宝 / 微信并排
            for label in labels:
                pix = label.pixmap()
                assert pix is not None and not pix.isNull()
                # 缩放走 QPixmap.scaled 整数参数（不超过声明边长）
                assert pix.width() <= _sd.QR_CODE_SIZE
                assert pix.height() <= _sd.QR_CODE_SIZE
        finally:
            dlg.close()

    def test_missing_image_shows_placeholder(self, qapp, monkeypatch, tmp_path):
        empty = tmp_path / "no_payments"
        empty.mkdir()
        monkeypatch.setattr(_sd, "PAYMENTS_DIR", empty)
        assert _sd.load_qr_pixmap("zhifubao.JPG") is None
        dlg = _sd.SponsorDialog()
        try:
            labels = dlg.qr_labels()
            assert len(labels) == 2
            for label in labels:
                assert label.text() == tr("sponsor.qr_missing")
        finally:
            dlg.close()

    def test_two_buttons_present(self, qapp):
        dlg = _sd.SponsorDialog()
        try:
            assert dlg.btn_continue.text() == tr("sponsor.continue")
            assert dlg.btn_dismiss.text() == tr("sponsor.dismiss")
            assert dlg.btn_continue.isDefault() is True  # 默认焦点
        finally:
            dlg.close()

    def test_continue_closes_without_dismiss(self, qapp):
        dlg = _sd.SponsorDialog()
        dlg.show()
        assert dlg.isVisible()
        dlg.btn_continue.click()
        assert not dlg.isVisible()
        assert _state.is_sponsor_reminder_dismissed() is False

    def test_dismiss_writes_state(self, qapp):
        dlg = _sd.SponsorDialog()
        dlg.show()
        dlg.btn_dismiss.click()
        assert not dlg.isVisible()
        assert _state.is_sponsor_reminder_dismissed() is True

    def test_esc_closes(self, qapp):
        dlg = _sd.SponsorDialog()
        dlg.show()
        assert dlg.isVisible()
        QTest.keyClick(dlg, Qt.Key.Key_Escape)
        assert not dlg.isVisible()

    def test_no_countdown_or_code(self):
        # 无倒计时 / 无赞助码 / 无机器码 / 无 5 秒等待（拼接避免自命中）
        for token in (
            "倒计" + "时",
            "count" + "down",
            "赞助" + "码",
            "机器" + "码",
        ):
            assert token not in _SPONSOR_SRC, f"sponsor_dialog.py 命中 {token}"


# ---------------------------------------------------------------------------
# ③ 启动接线（不 show 主窗口）
# ---------------------------------------------------------------------------


@pytest.fixture
def window(qapp, tmp_path):
    from acouscope.app.controller import AppController
    from acouscope.ui.main_window import MainWindow

    controller = AppController()
    sr = 8000
    t = np.arange(int(sr * 5.0)) / sr
    controller.load_from_array(0.5 * np.sin(2 * np.pi * (200 + 300 * t) * t), sr)
    w = MainWindow(controller)
    yield w
    w.close()


class TestStartupWiring:
    def test_prompt_after_two_hours(self, window, tmp_path):
        _write_app_state(tmp_path, {"first_run_timestamp": _first_run_ago(3)})
        window._maybe_show_sponsor_dialog()
        dlg = getattr(window, "_sponsor_dialog", None)
        assert dlg is not None
        assert dlg.isModal() is False
        assert dlg.parent() is window

    def test_prompt_only_once_per_launch(self, window, tmp_path):
        _write_app_state(tmp_path, {"first_run_timestamp": _first_run_ago(3)})
        window._maybe_show_sponsor_dialog()
        first = window._sponsor_dialog
        window._maybe_show_sponsor_dialog()
        assert window._sponsor_dialog is first

    def test_no_prompt_before_two_hours(self, window, tmp_path):
        _write_app_state(tmp_path, {"first_run_timestamp": _first_run_ago(0.5)})
        window._maybe_show_sponsor_dialog()
        assert not hasattr(window, "_sponsor_dialog")

    def test_no_prompt_when_dismissed(self, window, tmp_path):
        _write_app_state(
            tmp_path,
            {"first_run_timestamp": _first_run_ago(72), "sponsor_reminder_dismissed": True},
        )
        window._maybe_show_sponsor_dialog()
        assert not hasattr(window, "_sponsor_dialog")

    def test_trigger_staggered_after_restore_prompt(self):
        restore_at = _MAIN_WINDOW_SRC.index(
            "QTimer.singleShot(0, self._prompt_restore_autosave)"
        )
        sponsor_at = _MAIN_WINDOW_SRC.index("self._maybe_show_sponsor_dialog)")
        assert sponsor_at > restore_at, "赞助致谢框判定须排在恢复确认之后（错峰）"
        assert "_SPONSOR_PROMPT_DELAY_MS" in _MAIN_WINDOW_SRC
        from acouscope.ui.main_window import _SPONSOR_PROMPT_DELAY_MS

        assert _SPONSOR_PROMPT_DELAY_MS > 0  # 正延迟：不同帧抢焦点
        assert "ensure_first_run()" in _MAIN_WINDOW_SRC


# ---------------------------------------------------------------------------
# ④ 静态纪律 / i18n / 白名单登记
# ---------------------------------------------------------------------------


class TestCompliance:
    def test_i18n_three_languages_and_verbatim_zh(self, zh_cn):
        for key in _SPONSOR_KEYS:
            entry = _i18n._STRINGS.get(key)
            assert entry is not None, f"缺少 i18n 键 {key}"
            for lang in available_languages():
                assert entry.get(lang), f"{key} 缺 {lang}"
        assert tr("sponsor.heading") == _USER_HEADING_ZH
        assert tr("sponsor.body") == _USER_BODY_ZH
        assert tr("sponsor.continue") == "继续使用"
        assert tr("sponsor.dismiss") == "已支持，不再提醒"
        assert tr("sponsor.qr_zhifubao") == "支付宝"
        assert tr("sponsor.qr_weixin") == "微信"

    def test_no_hex_no_px_in_sources(self):
        for name, text in (
            ("sponsor_dialog.py", _SPONSOR_SRC),
            ("state.py", _STATE_SRC),
        ):
            assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", text), f"{name} 含硬编码 hex"
            assert not re.findall(r"\b\d+px\b", text), f"{name} 含 px 字面量"

    def test_forbidden_brand_word_absent(self):
        for name, text in (
            ("sponsor_dialog.py", _SPONSOR_SRC),
            ("state.py", _STATE_SRC),
            ("main_window.py", _MAIN_WINDOW_SRC),
        ):
            assert ("Melod" + "yne") not in text, f"{name} 命中禁词"

    def test_dialog_whitelist_registered(self):
        # test_ui_smoke.py 按其机制同步登记（QDialog 白名单分支）
        smoke = (_REPO_ROOT / "tests" / "test_ui_smoke.py").read_text(encoding="utf-8")
        assert "sponsor_dialog.py" in smoke
        assert "class SponsorDialog(QDialog)" in _SPONSOR_SRC
        assert "setModal(False)" in _SPONSOR_SRC
        assert "sponsor_dialog" not in _converted_dialog_names()

    def test_no_main_window_show_in_this_file(self):
        this = pathlib.Path(__file__).read_text(encoding="utf-8")
        assert ("MainWindow" + ".show()") not in this


def _converted_dialog_names() -> str:
    """_CONVERTED_DIALOGS 清单源码文本（zz-转 QWidget 名单，SponsorDialog 不得混入）。"""
    smoke = (_REPO_ROOT / "tests" / "test_ui_smoke.py").read_text(encoding="utf-8")
    start = smoke.index("_CONVERTED_DIALOGS = [")
    return smoke[start : smoke.index("]", start)]
