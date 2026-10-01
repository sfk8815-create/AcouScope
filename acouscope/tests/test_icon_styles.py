# SPDX-License-Identifier: GPL-3.0-only
"""T-1001：三风格图标系统（脚本派生口径）回归测试。

覆盖（任务书测试段）：
  ① 三套资源存在性：总表每名 × 每风格命中（或入回落白名单——本波为空）；
  ② set_icon_style 前后 icon_path 风格前缀变化 + 图标缓存失效 + 非法值忽略；
  ③ 缺名回退：无映射 → None；风格目录缺该名 → 回落 generic；两处皆缺 → None；
  ④ config icon_style 往返 + 缺省 generic；设置面板含下拉（三风格 + generic 兜底）、
     切换即预览、应用即持久化、取消回滚；
  ⑤ 派生脚本幂等（临时目录连续两次运行输出逐字节一致）+ 派生参数/图元语义保留；
  ⑥ 静态纪律自断言（禁词 0 / 图标与新增行零 hex·px / 未新增模态对话框类 /
     本文件不构造主窗 show()）。

纪律：全程离屏、零子进程、零网络；不构造 MainWindow。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

pytest.importorskip("PyQt6")

import hashlib  # noqa: E402
import importlib.util  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402

from acouscope.i18n import tr  # noqa: E402
from acouscope.ui import theme  # noqa: E402
from acouscope.utils.config import Settings  # noqa: E402

_SRC = Path(__file__).resolve().parents[1] / "src"
_ACOU = _SRC / "acouscope"
_ICON_ROOT = _ACOU / "resources" / "icons"
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "derive_icon_styles.py"
_DERIVED = ("macos", "win", "mint")

# 禁词以拼接构造，避免本文件自身被扫中（同 test_project_autosave.py 口径）
_BANNED = "Mel" + "odyne"
_QDIALOG = "Q" + "Dialog"
_SHOW = "." + "show()"

# 回落白名单：确无法派生的逻辑名（本波为空 = 全名 × 三套齐备）
_FALLBACK_WHITELIST: tuple = ()


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_icon_style():
    """本模块用例统一从默认 generic 出发，结束后复原（防跨文件污染）。"""
    theme._icon_style = "generic"
    theme._icon_cache.clear()
    yield
    theme._icon_style = "generic"
    theme._icon_cache.clear()


@pytest.fixture
def _isolated_config(tmp_path, monkeypatch):
    """把 settings.json 读写钉进临时目录（涉及持久化的用例专用）。

    注：conftest 的 autouse 隔离只重定向 get_data_dir，而 Settings 走
    get_config_dir / config_dir_candidates（各自独立推导），故此处显式再隔离。
    """
    import acouscope.utils.config as cfg

    monkeypatch.setattr(cfg, "get_config_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "config_dir_candidates", lambda: [tmp_path])
    return tmp_path


@pytest.fixture
def dlg(qapp, monkeypatch):
    """设置面板（引擎探活打桩：零网络）。"""
    from acouscope.ui.widgets import settings_dialog as sd
    import acouscope.ai.backends.local_registry as lr

    monkeypatch.setattr(lr, "probe_ollama", lambda *a, **k: (False, []))
    return sd.SettingsDialog(ai_config={})


def _names() -> list:
    """图标需求总表（逻辑名全集 = ICONS 映射键）。"""
    return sorted(theme.ICONS)


def _file(style: str, name: str) -> Path:
    """某风格下该逻辑名对应的资源文件路径（按派生命名规则推算）。"""
    return _ICON_ROOT / style / Path(theme.ICONS[name]).name


# ---------------------------------------------------------------------------
# ① 三套资源存在性（总表 × 每风格）
# ---------------------------------------------------------------------------

def test_catalog_covers_every_logical_name_in_every_style():
    """总表每名 × 三套均有资源（除白名单外禁空缺口 → 禁空 QIcon）。"""
    missing = [(s, n) for s in _DERIVED for n in _names() if not _file(s, n).exists()]
    unexpected = [m for m in missing if m[1] not in _FALLBACK_WHITELIST]
    assert unexpected == [], f"三套缺资源（未入白名单）：{unexpected}"
    assert _FALLBACK_WHITELIST == (), "本波应为零回落（全 31 名 × 3 套齐备）"


def test_generic_style_backfills_stop_play_record():
    """② generic 已补齐 play/stop/record（映射指向 generic/ 真实文件）。"""
    for name in ("play", "stop", "record"):
        assert name in theme.ICONS
        assert theme.ICONS[name] == f"generic/{name}.svg"
        assert _file("generic", name).exists()


def test_every_style_covers_same_name_set():
    """三套风格与 generic 基准同名同数（派生口径：基准有则三套有）。"""
    base = {p.name for p in (_ICON_ROOT / "generic").glob("*.svg")}
    for style in _DERIVED:
        assert {p.name for p in (_ICON_ROOT / style).glob("*.svg")} == base


# ---------------------------------------------------------------------------
# ② 风格解析层：icon_path 随风格变化 + 缓存失效
# ---------------------------------------------------------------------------

def test_set_icon_style_switches_icon_path_and_invalidates_cache(qapp):
    """set_icon_style：icon_path 前缀切风格；get_icon 缓存随风格失效重建。"""
    assert theme.set_icon_style("generic") is True
    before = theme.icon_path("settings")
    assert before is not None and before.parent.name == "generic"
    icon_before = theme.get_icon("settings")

    assert theme.set_icon_style("macos") is True
    assert theme.icon_style() == "macos"
    after = theme.icon_path("settings")
    assert after is not None and after.parent.name == "macos"
    assert after.read_text(encoding="utf-8") != before.read_text(encoding="utf-8")
    assert theme.get_icon("settings") is not icon_before

    # 非法风格：忽略且不动当前风格
    assert theme.set_icon_style("__bogus__") is False
    assert theme.icon_style() == "macos"


def test_icon_styles_order_and_default(qapp, _isolated_config):
    """风格全集含三套 + generic 兜底；缺省（未显式设置）即 generic。"""
    assert theme.ICON_STYLES[:3] == list(_DERIVED)
    assert theme.ICON_STYLES[-1] == "generic"
    theme._icon_style = None  # 模拟未显式设置 → 惰性自举（隔离目录内无配置）
    assert theme.icon_style() == "generic"


def test_refresh_icons_reapplies_mounted_icons(qapp):
    """已挂载控件图标随风格切换被重取（全窗刷新入口可用）。"""
    from PyQt6.QtWidgets import QPushButton

    btn = QPushButton()
    theme.set_icon_style("generic")
    btn.setIcon(theme.get_icon("settings"))
    key_before = btn.icon().cacheKey()

    assert theme.set_icon_style("win") is True
    assert theme.refresh_icons(btn) >= 1
    assert btn.icon().cacheKey() != key_before
    btn.deleteLater()


def test_style_icon_preview_does_not_switch_style(qapp):
    """指定风格预览：渲染不改变当前风格；非法风格回落 generic。"""
    theme.set_icon_style("generic")
    assert not theme.style_icon("win", "play").isNull()
    assert theme.icon_style() == "generic"
    assert not theme.style_icon("__bogus__", "play").isNull()  # 回落 generic
    assert theme.style_icon("win", "__no_such__").isNull()


# ---------------------------------------------------------------------------
# ③ 缺名 / 缺资源回退
# ---------------------------------------------------------------------------

def test_missing_name_returns_none_and_empty_icon(qapp):
    """无映射 → icon_path None + 空 QIcon（不抛异常）。"""
    assert theme.icon_path("__no_such__") is None
    assert theme.get_icon("__no_such__").isNull()


def test_style_gap_falls_back_to_generic(qapp, tmp_path, monkeypatch):
    """风格目录缺该名 → 回落 generic；两处皆缺 → None（禁单套留空）。"""
    fake_ui = tmp_path / "src" / "acouscope" / "ui"
    fake_ui.mkdir(parents=True)
    (fake_ui / "theme.py").write_text("", encoding="utf-8")
    icons = tmp_path / "src" / "acouscope" / "resources" / "icons"
    (icons / "generic").mkdir(parents=True)
    (icons / "macos").mkdir(parents=True)
    (icons / "generic" / "only-generic.svg").write_text("<svg/>", encoding="utf-8")

    monkeypatch.setattr(theme, "__file__", str(fake_ui / "theme.py"))
    monkeypatch.setitem(theme.ICONS, "__gap__", "generic/only-generic.svg")
    monkeypatch.setitem(theme.ICONS, "__gap_absent__", "generic/absent.svg")
    assert theme.set_icon_style("macos") is True

    fell_back = theme.icon_path("__gap__")
    assert fell_back is not None and fell_back.parent.name == "generic"
    assert theme.icon_path("__gap_absent__") is None


# ---------------------------------------------------------------------------
# ④ config 持久化 + 设置面板
# ---------------------------------------------------------------------------

def test_config_icon_style_default_and_roundtrip(tmp_path):
    """缺省 generic；显式写入后可原样读回（含非法值回落由 theme 侧负责）。"""
    assert Settings().icon_style == "generic"
    path = tmp_path / "settings.json"
    s = Settings()
    s.icon_style = "win"
    s.save(path)
    assert Settings.load(path).icon_style == "win"


def test_settings_dialog_has_icon_style_combo(dlg):
    """界面 tab 含「图标风格」下拉：三风格 + generic 兜底，且 i18n 三语齐备。"""
    cmb = dlg.cmb_icon_style
    assert [cmb.itemData(i) for i in range(cmb.count())] == theme.ICON_STYLES
    for sid in theme.ICON_STYLES:
        key = f"settings.icon_style.{sid}"
        assert tr(key) != key, f"{key} 缺 i18n"
    assert tr("settings.icon_style") != "settings.icon_style"
    assert len(dlg._icon_preview_labels) == len(dlg._ICON_PREVIEW_NAMES)


def test_settings_dialog_previews_on_switch_and_reverts_on_cancel(dlg):
    """切换下拉 = 即时预览（全窗生效）；未应用即关闭 = 回滚到打开时风格。"""
    start = dlg.icon_style()
    assert theme.icon_style() == start
    idx = dlg.cmb_icon_style.findData("mint")
    assert idx >= 0
    dlg.cmb_icon_style.setCurrentIndex(idx)
    assert dlg.icon_style() == "mint"
    assert theme.icon_style() == "mint"

    dlg.cancelled.emit()
    assert theme.icon_style() == start
    assert dlg.icon_style() == start


def test_settings_dialog_apply_persists_icon_style(dlg, _isolated_config):
    """「应用」= 当前风格写入 settings.json（隔离目录内往返验证）。"""
    idx = dlg.cmb_icon_style.findData("win")
    assert idx >= 0
    dlg.cmb_icon_style.setCurrentIndex(idx)
    dlg.applied.emit()
    assert Settings.load().icon_style == "win"


# ---------------------------------------------------------------------------
# ⑤ 派生脚本：幂等 + 参数/图元语义
# ---------------------------------------------------------------------------

def _load_script():
    """按文件路径加载派生脚本（scripts/ 非包 → 显式 spec 加载）。"""
    spec = importlib.util.spec_from_file_location(
        "t1001_derive_icon_styles", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _digest(root: Path) -> str:
    """目录内全部 SVG 的内容摘要（排序稳定；文件名 + 字节入哈希）。"""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*.svg")):
        h.update(str(p.relative_to(root)).encode("utf-8"))
        h.update(p.read_bytes())
    return h.hexdigest()


def test_derive_script_is_idempotent(tmp_path):
    """④ 临时目录连续两次运行：输出逐字节一致（无时间戳/随机/绝对路径）。"""
    mod = _load_script()
    root = tmp_path / "icons"
    shutil.copytree(_ICON_ROOT / "generic", root / "generic")
    first_files = mod.build(root)
    first = _digest(root)
    second_files = mod.build(root)
    second = _digest(root)
    assert first == second
    assert [p.name for p in first_files] == [p.name for p in second_files]
    # 三套与基准同名同数（含新补三枚）
    base_count = len(list((root / "generic").glob("*.svg")))
    for style in _DERIVED:
        assert len(list((root / style).glob("*.svg"))) == base_count


@pytest.mark.parametrize("style", _DERIVED)
def test_derived_style_conforms_and_keeps_primitives(style):
    """派生件：参数表落到根属性；图元逐字保留；单色纪律（无 hex / 无 px）。"""
    mod = _load_script()
    params = mod.STYLE_PARAMS[style]
    text = _file(style, "settings").read_text(encoding="utf-8")
    assert 'viewBox="0 0 24 24"' in text and "currentColor" in text
    assert f'stroke-width="{mod._fmt(params["stroke_width"])}"' in text
    assert f'stroke-linecap="{params["linecap"]}"' in text
    assert f'stroke-linejoin="{params["linejoin"]}"' in text
    base = (_ICON_ROOT / theme.ICONS["settings"]).read_text(encoding="utf-8")
    for element in mod._elements(base):
        assert element in text, f"{style}/settings.svg 图元语义被改动：{element}"


# ---------------------------------------------------------------------------
# ⑥ 静态纪律自断言
# ---------------------------------------------------------------------------

def test_static_discipline_no_banned_word_no_hex_px_no_new_dialog():
    """禁词 0 / 新文件零 hex·px / 未新增模态对话框类 / 本文件不 show 主窗。"""
    for path in (_SCRIPT, Path(__file__)):
        text = path.read_text(encoding="utf-8")
        assert _BANNED not in text, f"{path.name} 命中禁词"
        assert _QDIALOG not in text, f"{path.name} 引入模态对话框"
        assert _SHOW not in text, f"{path.name} 出现 show()"

    # 图标资源（基准 + 三套）：仅 none|currentColor，零 hex 色值、零 px 单位
    files = [_ICON_ROOT / theme.ICONS[n] for n in _names()]
    for style in _DERIVED:
        files += [_file(style, n) for n in _names()]
    for p in files:
        text = p.read_text(encoding="utf-8")
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", text), f"{p} 含硬编码色值"
        assert "px" not in text, f"{p} 含 px 单位"
        for m in re.finditer(r'(?:fill|stroke)="([^"]+)"', text):
            assert m.group(1) in ("none", "currentColor"), f"{p} 残留色值 {m.group(1)}"

    # T-1001 新增行（theme/settings/config/i18n）：零 hex、零 px
    for path in (
        Path(theme.__file__),
        _ACOU / "ui" / "widgets" / "settings_dialog.py",
        _ACOU / "utils" / "config.py",
        _ACOU / "i18n" / "__init__.py",
    ):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "T-1001" not in line:
                continue
            assert not re.search(r"#[0-9a-fA-F]{3,8}\b", line), line
            assert not re.search(r"\d+px", line), line
