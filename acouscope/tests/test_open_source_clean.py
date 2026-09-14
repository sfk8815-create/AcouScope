# SPDX-License-Identifier: GPL-3.0-only
"""T-1016 开源化守卫：授权逻辑已完全移除（纯静态断言，零 Qt 依赖）。

覆盖：
- licensing.py / support_dialog.py / test_cb003_support_reminder.py 已删除；
- main_window.py 无授权方法/启动提醒/门控调用；
- ai_interpret.py 无赞助横幅 / 支付按钮 / 锁定状态机；
- about_dialog.py 不再展示机器码；
- 全仓 py 无 licensing / trial 字样（本文件自身除外）；
- sponsor 字样收窄为「仅限 T-1017 白名单文件」（2026-09-09 定稿：开源化后
  极温和赞助致谢框为合法功能，见 test_sponsor_wording_confined_to_whitelist）。

T-1017 修订（审计在案，非静默）：原断言「全仓含 sponsor 即失败」与 2026-09-09
最高指挥定稿的赞助致谢框直接冲突——赞助功能系**本轮显式复归**，而授权/门控
（licensing / trial）仍全仓禁止。故把 sponsor 由「全仓禁字」收窄为
「白名单外禁字」，守卫强度不降（限制更精确）。
"""

import importlib.util
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = _ROOT / "src" / "acouscope"
TESTS = _ROOT / "tests"
_THIS = pathlib.Path(__file__).resolve()

_MW_FORBIDDEN = (
    "_check_feature_unlocked",
    "_show_support_dialog",
    "_setup_support",
    "_on_support_dialog_finished",
    "_support_dialog",
    "_support_timer",
    "_support_status",
    "_support_started",
    "support_dialog",
    "from acouscope.ai import licensing",
)
_AI_FORBIDDEN = (
    "lock_banner",
    "btn_pay",
    "banner_widget",
    "_refresh_lock_state",
    "_on_pay",
    "support_dialog",
    "licensing",
)

# T-1017 白名单：赞助致谢框（2026-09-09 最高指挥定稿）的产出文件，
# sponsor 字样仅允许出现在此处；其余文件一律禁用（见 test_sponsor_wording_confined_to_whitelist）。
_SPONSOR_ALLOWED = {
    (SRC / "state.py").resolve(),
    (SRC / "i18n" / "__init__.py").resolve(),
    (SRC / "ui" / "main_window.py").resolve(),
    (SRC / "ui" / "widgets" / "sponsor_dialog.py").resolve(),
    (TESTS / "test_ui_smoke.py").resolve(),
    (TESTS / "test_sponsor_dialog.py").resolve(),
}


def test_licensing_module_removed():
    assert importlib.util.find_spec("acouscope.ai.licensing") is None


def test_support_dialog_module_removed():
    assert importlib.util.find_spec("acouscope.ui.widgets.support_dialog") is None


def test_deleted_files_absent():
    assert not (SRC / "ai" / "licensing.py").exists()
    assert not (SRC / "ui" / "widgets" / "support_dialog.py").exists()
    assert not (TESTS / "test_cb003_support_reminder.py").exists()


def test_main_window_has_no_licensing_api():
    text = (SRC / "ui" / "main_window.py").read_text(encoding="utf-8")
    for token in _MW_FORBIDDEN:
        assert token not in text, f"main_window.py 仍含 {token}"


def test_ai_interpret_has_no_banner_or_gate():
    text = (SRC / "ui" / "widgets" / "ai_interpret.py").read_text(encoding="utf-8")
    for token in _AI_FORBIDDEN:
        assert token not in text, f"ai_interpret.py 仍含 {token}"


def test_about_dialog_has_no_machine_id():
    text = (SRC / "ui" / "widgets" / "about_dialog.py").read_text(encoding="utf-8")
    assert "machine_id" not in text
    assert "about.machine_id" not in text


def test_repo_free_of_authorization_wording():
    tokens = ("licensing", "trial")
    for root in (SRC, TESTS):
        for py in root.rglob("*.py"):
            if py.resolve() == _THIS:
                continue
            low = py.read_text(encoding="utf-8").lower()
            for tok in tokens:
                assert tok not in low, f"{py} 仍含 {tok}"


def test_sponsor_wording_confined_to_whitelist():
    """T-1017：sponsor 字样只允许出现在该任务的产出文件内（白名单外禁字）。"""
    offenders = []
    for root in (SRC, TESTS):
        for py in root.rglob("*.py"):
            resolved = py.resolve()
            if resolved == _THIS or resolved in _SPONSOR_ALLOWED:
                continue
            if "sponsor" in py.read_text(encoding="utf-8").lower():
                offenders.append(str(py))
    assert not offenders, f"白名单外文件仍含 sponsor: {offenders}"
