# SPDX-License-Identifier: GPL-3.0-only
"""T-1017 赞助致谢框（极温和启动问候）测试。

覆盖：
① 状态模块 acouscope/state.py（first_run 初始化 / 启动计数闸判定 / dismissed 持久化 / 容错）；
② SponsorDialog 形态（非模态 / 无 exec / 双二维码并排 / 缺失占位 / 两按钮 / Esc 关闭）；
③ 启动接线（错峰顺序 / 同启动内不双弹 / 达标后每次启动均弹 / dismissed 后不弹）；
④ 静态纪律（禁词 0 / 无 hex-px / QDialog 白名单登记 / 文案禁改字 / 不构造主窗口顶层显示）。

纪律：全部离屏，不构造主窗口顶层显示（GUI_backlog #6）；数据目录由 conftest
autouse fixture 统一重定向到 tmp_path。

T-1082 修订（受控设计反转，审计在案·承 T-1017 D1 范式）：
- 自动弹窗由「满 2h 每启动都弹」→「每安装至多自动弹一次」（旗标
  ``sponsor_prompt_shown``）；新增帮助菜单常驻入口「支持 AcouScope」；
- 引入离线**致谢码**（旗标 ``sponsor_acknowledged``，与 dismissed 同为停弹条件，
  只停弹、不解锁/不门控）；``test_no_countdown_or_code`` 边界重述为
  「无倒计时/无机器码/无『赞助码』字样——致谢码为可选荣誉确认」，
  原三项子断言（4 token）全数保留；定稿 heading/body verbatim 基线逐字零动。

T-1110 修订（受控设计反转 #3，审计在案）：
- 自动弹窗由「每安装至多自动弹一次」→「第 5 次启动起、此后每次启动均弹」
  （阈值常量 ``SPONSOR_PROMPT_LAUNCH_THRESHOLD`` = 5，计数键 ``launch_count``）；
- **致谢码全面下架**：常量/UI 行/槽/i18n 4 键/状态字段一并除，交互测整类删；
- 旧持久旗标 ``sponsor_prompt_shown`` / ``sponsor_acknowledged`` 不再读取、
  自然失效（反证测 ``test_legacy_flags_no_longer_suppress`` 在案）；
  2 小时装机延迟（``SPONSOR_REMINDER_DELAY``）整体废除，
  ``first_run_timestamp`` 转为纯装机记录、不参与判定。
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
    "action.sponsor",
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

    def test_should_show_false_below_threshold(self, tmp_path):
        _write_app_state(tmp_path, {"launch_count": 4})
        assert _state.should_show_sponsor_reminder() is False

    def test_should_show_true_from_threshold_onward(self, tmp_path):
        # 边界两侧都测（4 未达标 / 5 起达标），防只测单侧假绿
        for count in (5, 6, 7):
            _write_app_state(tmp_path, {"launch_count": count})
            assert _state.should_show_sponsor_reminder() is True

    def test_dismissed_persists_and_suppresses(self, tmp_path):
        base = datetime(2026, 1, 1, 9, 0, 0)
        _state.ensure_first_run(base)
        assert _state.is_sponsor_reminder_dismissed() is False
        assert _state.set_sponsor_reminder_dismissed(True) is True
        assert _state.is_sponsor_reminder_dismissed() is True
        assert _state.should_show_sponsor_reminder() is False
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

    def test_prompt_threshold_constant_is_five(self):
        assert _state.SPONSOR_PROMPT_LAUNCH_THRESHOLD == 5

    # ---- T-1110：启动计数闸（第 5 次起每次弹）+ 旧旗标失效 ----

    def test_prompt_repeats_every_launch_after_threshold(self, tmp_path):
        for _ in range(4):
            _state.bump_launch_count()
        assert _state.should_show_sponsor_reminder() is False  # 计数 4：未达标
        for expected in (5, 6, 7):
            assert _state.bump_launch_count() == expected
            assert _state.should_show_sponsor_reminder() is True  # 达标后逐次照弹
        # 跨进程持久：直接读盘同值
        raw = json.loads((tmp_path / "app_state.json").read_text(encoding="utf-8"))
        assert raw["launch_count"] == 7

    def test_dismissed_is_only_stop_path(self, tmp_path):
        _write_app_state(tmp_path, {"launch_count": 5})
        assert _state.should_show_sponsor_reminder() is True
        assert _state.set_sponsor_reminder_dismissed(True) is True
        assert _state.should_show_sponsor_reminder() is False  # 唯一停弹路径
        _state.set_sponsor_reminder_dismissed(False)
        assert _state.should_show_sponsor_reminder() is True  # 复位后照弹

    def test_legacy_flags_no_longer_suppress(self, tmp_path):
        # 反证（T-1110 R6）：旧残键不读不删、自然失效——计数 5 且无 dismissed 仍须弹
        _write_app_state(
            tmp_path,
            {
                "launch_count": 5,
                "sponsor_prompt_shown": True,
                "sponsor_acknowledged": True,
            },
        )
        assert _state.should_show_sponsor_reminder() is True

    def test_state_module_never_touches_license(self, tmp_path):
        # 行为口径：数据目录内的 license.json 不读不写不改，状态只落 app_state.json
        stale = tmp_path / "license.json"
        stale.write_text('{"code": "KEEP-AS-IS"}', encoding="utf-8")
        before = stale.read_text(encoding="utf-8")
        _state.ensure_first_run(datetime(2026, 1, 1, 9, 0, 0))
        _state.set_sponsor_reminder_dismissed(True)
        _state.bump_launch_count()
        assert stale.read_text(encoding="utf-8") == before
        assert _state.state_path().name == "app_state.json"
        assert (tmp_path / "app_state.json").exists()
        assert sorted(p.name for p in tmp_path.iterdir()) == [
            "app_state.json",
            "license.json",
        ]


class TestLaunchCount:
    """T-1110 启动计数守卫：递增落盘 / 键缺失与非整数容错（绝不抛）。"""

    def test_first_bump_returns_one_and_persists(self, tmp_path):
        assert _state.get_launch_count() == 0
        assert _state.bump_launch_count() == 1
        assert _state.get_launch_count() == 1
        raw = json.loads((tmp_path / "app_state.json").read_text(encoding="utf-8"))
        assert raw["launch_count"] == 1

    def test_bump_increments_to_three(self, tmp_path):
        for expected in (1, 2, 3):
            assert _state.bump_launch_count() == expected
        assert _state.get_launch_count() == 3
        raw = json.loads((tmp_path / "app_state.json").read_text(encoding="utf-8"))
        assert raw["launch_count"] == 3

    def test_bad_values_tolerated(self, tmp_path):
        _write_app_state(tmp_path, {"launch_count": "abc"})
        assert _state.get_launch_count() == 0
        assert _state.bump_launch_count() == 1  # 非整数按 0 起算，不抛
        _write_app_state(tmp_path, {"launch_count": -1})
        assert _state.get_launch_count() == -1  # 原样读出（可预期）
        assert _state.bump_launch_count() == 0  # -1 + 1，不抛


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
        # T-1082 边界重述（承 §〇-D①）：本框**无倒计时 / 无机器码 / 无「赞助码」字样**；
        # 「致谢码」为可选荣誉确认——不采集设备标识、不门控功能、只影响停弹。
        # 原三项子断言全数保留：
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
    def test_prompt_when_launch_count_reaches_threshold(self, window, tmp_path):
        _write_app_state(tmp_path, {"launch_count": 5})
        window._maybe_show_sponsor_dialog()
        dlg = getattr(window, "_sponsor_dialog", None)
        assert dlg is not None
        assert dlg.isModal() is False
        assert dlg.parent() is window

    def test_prompt_only_once_per_launch(self, window, tmp_path):
        _write_app_state(tmp_path, {"launch_count": 5})
        window._maybe_show_sponsor_dialog()
        first = window._sponsor_dialog
        window._maybe_show_sponsor_dialog()
        assert window._sponsor_dialog is first

    def test_no_prompt_below_threshold(self, window, tmp_path):
        _write_app_state(tmp_path, {"launch_count": 4})
        window._maybe_show_sponsor_dialog()
        assert not hasattr(window, "_sponsor_dialog")

    def test_no_prompt_when_dismissed(self, window, tmp_path):
        _write_app_state(
            tmp_path,
            {"first_run_timestamp": _first_run_ago(72), "sponsor_reminder_dismissed": True},
        )
        window._maybe_show_sponsor_dialog()
        assert not hasattr(window, "_sponsor_dialog")

    # ---- T-1110：达标后每次启动均弹 + dismissed 后帮助菜单仍可打开 ----

    def test_prompt_repeats_after_threshold(self, window, tmp_path):
        _write_app_state(tmp_path, {"launch_count": 5})
        window._maybe_show_sponsor_dialog()
        first = window._sponsor_dialog
        assert _state.should_show_sponsor_reminder() is True  # 达标后无「已弹过」抑制
        # 模拟「再启动」：清实例内存标志（仅防同启动内重弹），下次启动照弹新实例
        window._sponsor_prompt_shown = False
        window._maybe_show_sponsor_dialog()
        assert window._sponsor_dialog is not first
        raw = json.loads((tmp_path / "app_state.json").read_text(encoding="utf-8"))
        assert raw["launch_count"] == 5

    def test_manual_entry_still_opens_when_dismissed(self, window, tmp_path):
        _write_app_state(
            tmp_path, {"launch_count": 9, "sponsor_reminder_dismissed": True}
        )
        window._maybe_show_sponsor_dialog()
        assert not hasattr(window, "_sponsor_dialog")  # dismissed：唯一停弹路径
        assert _state.should_show_sponsor_reminder() is False
        window._on_show_sponsor()  # 帮助菜单常驻入口仍可打开同一框（R5）
        dlg = window._sponsor_dialog
        assert dlg.isModal() is False

    def test_help_menu_contains_sponsor_entry(self, window):
        menu_text = tr("menu.help")
        help_action = next(
            (a for a in window.menuBar().actions() if a.text() == menu_text), None
        )
        assert help_action is not None
        texts = [a.text() for a in help_action.menu().actions()]
        assert tr("action.sponsor") in texts
        # 既有相对序不破：访问网站仍在 关于 之前（T-1015 守卫同口径）
        assert texts.index(tr("action.visit_site")) < texts.index(tr("action.about"))
        assert window.action_sponsor.text() == tr("action.sponsor")

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
        assert "bump_launch_count()" in _MAIN_WINDOW_SRC


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
