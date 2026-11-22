# SPDX-License-Identifier: GPL-3.0-only
"""全局主题引擎：跟随系统 + 9 套配色，切换立即生效。

用法：
- apply_theme("dark")         → QPalette + 全局 QSS 一次到位，并通知所有动态控件
- colors()                    → 当前生效配色（自绘控件 paintEvent 里取色）
- style_when_theme(w, b)      → 注册动态样式（builder(c) 返回 QSS，主题变化时自动重设）

图表画布（matplotlib / pyqtgraph）不参与主题，保持学术图表白底。
"""

from __future__ import annotations

import atexit
import shutil
import tempfile
import weakref
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication, QColor, QFont, QFontDatabase, QIcon, QPalette, QPixmap

# 主题定义：每套为完整配色角色集（V1 视觉语言 §2.2/§2.3 收敛）。
# 骨架铁律：9 套共用同一中性阶，差异仅「明/暗 + 单一强调色相」。
#   bg0 应用底 · bg1 面板底 · bg2 控件底 · bg3 悬停 · border 唯一弱描边 · border_strong 焦点环
#   text 正文 · text_sub 次级 · text_faint 禁用 · accent 唯一强调色 · accent_text 强调底前景 · sel_bg 选区底
# 旧键 window/panel/input/btn/btn_hover/sub = 别名映射（值恒等，colors() 旧键继续可用）。
_DARK_NEUTRAL: dict[str, str] = {
    "bg0": "#101215", "bg1": "#171A1E", "bg2": "#1E2227", "bg3": "#262B31",
    "border": "#2E343B", "border_strong": "#3A4149",
    "text": "#E7E9EC", "text_sub": "#98A0A8", "text_faint": "#7A8188",
}
_LIGHT_NEUTRAL: dict[str, str] = {
    "bg0": "#F5F6F7", "bg1": "#FFFFFF", "bg2": "#FFFFFF", "bg3": "#ECEEF0",
    "border": "#DFE2E6", "border_strong": "#C3C8CE",
    "text": "#16181B", "text_sub": "#5F666D", "text_faint": "#7D848C",
}
# 内容色板（T-1036）：轨身份色 / 多序列内容色 —— 与「语义反馈色」分家（ARCH §2.1-3）。
# 骨架各 12 色，色相按 30° 等步进取色（顺序即轮转顺序），两两互异、与 semantic 四色零交集。
#   暗骨架：HSL(h, 55%, 68%)，逐色 vs 同骨架 bg1(#171A1E) 对比度 ≥ 3:1（实测 5.15~11.73）。
#   明骨架：按「vs 同骨架 bg1(#FFFFFF) 对比度 ≈ 3.3:1」取该色相可用的最大明度（HSL S 62%），
#          逐色对比度 ≥ 3:1（实测 3.30~3.34）。
_DARK_TRACKS: list[str] = [
    "#DA8881", "#DAB581", "#D3DA81", "#A6DA81", "#81DA88", "#81DAB5",
    "#81D3DA", "#81A6DA", "#8881DA", "#B581DA", "#DA81D3", "#DA81A6",
]
_LIGHT_TRACKS: list[str] = [
    "#DA6D63", "#BD812C", "#8B9423", "#589E25", "#26A230", "#26A06D",
    "#279BA6", "#5A8FD8", "#8A81E2", "#B172DE", "#D95BCE", "#DB6697",
]
# 相邻色最小色相间隔（度）：12 色均分 360° 的理想步进为 30°，阈值取 24°（理想值 80%），
# 容 HSV 取整误差，同时守「相邻色不得难辨」。
TRACK_HUE_GAP_MIN: float = 24.0
# 数据墨色（T-1038）：画布「测量轨迹 / 对照轨迹 / 游标 / 标记 / 参考线 / 区块底」六角色，
# 按用途命名、按骨架分两套。三权分立铁律：取值集合与 TOKENS["semantic"]（反馈色）、
# 各主题 accent（交互色）两两无交集；accent 的单强调色地位不变。
_DARK_DATA: dict[str, str] = {
    "trace": "#6FC3F0", "trace_alt": "#F0B860", "cursor": "#F2F4F7",
    "marker": "#D99BF2", "ref_line": "#8FA0B0", "tint": "#1B2830",
}
_LIGHT_DATA: dict[str, str] = {
    "trace": "#16588F", "trace_alt": "#A85A12", "cursor": "#0B0E12",
    "marker": "#7A3FA8", "ref_line": "#5A6570", "tint": "#E8EEF4",
}
# 键面（钢琴键）物理内容色阶（T-1042 → T-1042b v2 定形）：钢琴键是「物理约定面」
# （ARCH §2.1-5），白键恒亮、黑键恒暗，**明度不随主题骨架反转**（物理面铁律 §2.1-5/§六-10）。
# ★ v2：按项目负责人参考图改为**单套物理色**——明/暗骨架调用 key_faces() 返回**同一字典**。
# hex 唯一数据源在本文件（禁散落到 theme.py 之外）。四角色：
#   white       白键面 —— 恒亮（#D4D4D6，非纯白防刺眼）
#   black       黑键面 —— 恒暗（#1E1E1E，显著暗于 white）
#   white_seam  白键之间极细分隔 —— 比 white 暗一档；禁 border（那是壳色，会亮于键面）
#   label       键面音名文字 —— 深灰（#3A3A3A，非语义/强调色）
# 注：键带底/gutter（旧 strip 角色）随骨架 `bg2`（ARCH §五c v1.5），由两 widget 经
# theme.colors()["bg2"] 取，不再纳入 keys 令牌。
_KEYS_PHYSICAL: dict[str, str] = {
    "white": "#D4D4D6", "black": "#1E1E1E",
    "white_seam": "#C6C6C8", "label": "#3A3A3A",
}
# 旧键 → 新中性阶键（别名映射；TOKENS["neutral"]["alias"] 为同一份）
NEUTRAL_ALIAS: dict[str, str] = {
    "window": "bg0", "panel": "bg1", "input": "bg2", "btn": "bg2",
    "btn_hover": "bg3", "sub": "text_sub",
}


def _theme(label: str, neutral: dict[str, str], accent: str,
           accent_text: str, sel_bg: str, skeleton: str) -> dict[str, str]:
    """按中性骨架 + 单强调色装配一套主题（含旧键别名与骨架标记，值恒等）。"""
    entry = {"label": label, "skeleton": skeleton}
    entry.update(neutral)
    entry.update({"accent": accent, "accent_text": accent_text, "sel_bg": sel_bg})
    entry.update({alias: entry[src] for alias, src in NEUTRAL_ALIAS.items()})
    return entry


THEMES: dict[str, dict[str, str]] = {
    "default": _theme("默认", _LIGHT_NEUTRAL, "#2A726C", "#FFFFFF", "#CBE7E3", "light"),
    "light": _theme("浅色", _LIGHT_NEUTRAL, "#2F6E96", "#FFFFFF", "#D3E2EC", "light"),
    "dark": _theme("深色", _DARK_NEUTRAL, "#54A49C", "#08110F", "#1F3D3A", "dark"),
    "ocean": _theme("蓝调", _DARK_NEUTRAL, "#5B99C2", "#08110F", "#1B3A4D", "dark"),
    "forest": _theme("绿调", _LIGHT_NEUTRAL, "#2F6B4F", "#FFFFFF", "#D3E6DA", "light"),
    "sunset": _theme("橙调", _LIGHT_NEUTRAL, "#9A5323", "#FFFFFF", "#EEDCCB", "light"),
    "lavender": _theme("紫调", _LIGHT_NEUTRAL, "#6B5B95", "#FFFFFF", "#DFDAEC", "light"),
    "graphite": _theme("灰调", _DARK_NEUTRAL, "#7F9DB8", "#08110F", "#2A3540", "dark"),
    "sepia": _theme("棕调", _LIGHT_NEUTRAL, "#8A6033", "#FFFFFF", "#E7DCC9", "light"),
}

# ----------------------------------------------------------------------
# 设计令牌（V099_TOKENS_V1，UI 宪法条1）
# 8 点间距网格 / 圆角 / elevation / 字阶 / 语义反馈色。
# QSS 与自绘控件一律引用本令牌，严禁散落硬编码。
# ----------------------------------------------------------------------
TOKENS: dict = {
    "spacing": {"xxs": 2, "xs": 4, "sm": 8, "md": 16, "lg": 24, "xl": 32, "xxl": 48},
    "radius": {"sm": 4, "md": 8, "lg": 12, "pill": 999},
    "elevation": {"border": 1, "low": 2, "mid": 4, "high": 8},
    # 控件节拍（V1 视觉语言 §三/§七）：高度阶梯 + 内边距 + 控件间距
    "control": {"h_sm": 24, "h_md": 28, "h_lg": 32,
                "pad_x": 10, "pad_y": 4, "gap": 6},
    "typography": {
        "caption_sm": 10, "caption": 11, "body_sm": 12,
        "body": 13, "body_lg": 14, "h3": 16, "h2": 20, "h1": 24,
        # 跨平台回落链（T-1037）：顺序即优先级，macOS 目标仍在链首（不改 macOS 观感）；
        # 其后依次为 Windows 目标与 Linux 目标，末尾保留泛型兜底（数据源不删）。
        # 链不随主题变化（仅字号/字重随令牌）。
        "family": ("'PingFang SC', 'Helvetica Neue', 'Segoe UI', "
                   "'Microsoft YaHei UI', 'Microsoft YaHei', "
                   "'Noto Sans CJK SC', 'Source Han Sans SC', "
                   "'WenQuanYi Micro Hei', 'DejaVu Sans', sans-serif"),
        "mono": ("'SF Mono', 'Menlo', 'Consolas', "
                 "'DejaVu Sans Mono', 'Liberation Mono', "
                 "'Noto Sans Mono CJK SC', monospace"),
    },
    # 语义反馈色（暗色优先调色板，明暗主题下均保持可读）
    "semantic": {
        "warning": "#f59e0b", "warning_text": "#1f1600",
        "error": "#ef4444", "error_text": "#ffffff",
        "success": "#10b981", "success_text": "#022c22",
        "info": "#3b82f6", "info_text": "#ffffff",
    },
    # 中性阶角色表（V1 视觉语言 §七）：hex 唯一源在 THEMES（每套主题各一份），
    # 本项只声明角色名与旧键别名映射，避免双份色值漂移。
    "neutral": {
        "roles": ["bg0", "bg1", "bg2", "bg3", "border", "border_strong",
                  "text", "text_sub", "text_faint", "accent", "accent_text", "sel_bg"],
        "alias": dict(NEUTRAL_ALIAS),
    },
    # 内容色板角色表（T-1036）：轨身份色 / 多序列内容色，按骨架各一套；
    # hex 唯一源为上方 _DARK_TRACKS / _LIGHT_TRACKS，此处只做骨架索引。
    "track_palette": {"dark": _DARK_TRACKS, "light": _LIGHT_TRACKS},
    # 数据墨色角色表（T-1038）：画布墨色角色名 + 骨架索引；
    # hex 唯一源为上方 _DARK_DATA / _LIGHT_DATA。
    "data": {
        "roles": ["trace", "trace_alt", "cursor", "marker", "ref_line", "tint"],
        "dark": _DARK_DATA, "light": _LIGHT_DATA,
    },
    # 键面（钢琴键）物理内容色阶角色表（T-1042b）：**单套物理色**，明/暗骨架同款；
    # hex 唯一源为上方 _KEYS_PHYSICAL，此处只做角色索引。
    "keys": {
        "roles": ["white", "black", "white_seam", "label"],
        "physical": _KEYS_PHYSICAL,
    },
    # 参数控件规范构件（T-1047 · ARCH §五-7 三段式 / §五-8 范围可见性 /
    # §六-11 chip 激活态）：**尺寸与透明度唯一源**，本项只加不改
    # （semantic 四值 / THEME_ORDER / ICONS 零改动）。
    "param": {
        "led_dot": 8,        # 状态点直径
        "chip_alpha": 46,    # chip 激活态底色 = accent + 该 alpha（低 alpha 底）
        "chip_pad_x": 10,
        "chip_pad_y": 3,
        "col_gap": 24,       # 三段式列间距
        "tick_len": 4,       # 稀疏刻度线长
        "range_h": 18,       # 范围线索条高（刻度线 + 稀疏数值标签）
        "box_pad_x": 6,      # 读数内嵌框内边距
        "box_pad_y": 2,
    },
    # 内嵌图元尺寸（复选框指示器 / 下拉与微调箭头）：QSS 中 `::indicator` /
    # `::down-arrow` 的边长唯一源（禁在 _qss 写字面 px）。
    "glyph": {
        "indicator": 14,     # QCheckBox::indicator 边长
        "arrow": 9,          # 下拉/微调箭头位图边长
    },
}

# 设置对话框中的展示顺序（system 在首位）
THEME_ORDER = [
    "system", "default", "light", "dark",
    "ocean", "forest", "sunset", "lavender", "graphite", "sepia",
]

_current: dict[str, str] = dict(THEMES["dark"])
_theme_id: str = "dark"  # V099_TOKENS_V1：暗色优先默认
_system_watched = False
_dynamic: list[tuple] = []   # [(weakref.ref(widget), builder)]


# ----------------------------------------------------------------------
# 跟随系统
# ----------------------------------------------------------------------

def _resolve_system() -> str:
    """系统外观 → 实际配色 id（深色外观用 dark，否则 default）。"""
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return "dark"
    except Exception:
        pass
    try:
        lum = QGuiApplication.palette().color(QPalette.ColorRole.Window).lightness()
        if lum < 128:
            return "dark"
    except Exception:
        pass
    return "default"


def _watch_system(app) -> None:
    """跟随系统模式下，监听系统深浅色切换（Qt 6.5+）。"""
    global _system_watched
    if _system_watched:
        return
    _system_watched = True
    try:
        app.styleHints().colorSchemeChanged.connect(
            lambda _s: _theme_id == "system" and apply_theme("system"))
    except Exception:
        pass


# ----------------------------------------------------------------------
# 应用主题
# ----------------------------------------------------------------------

def _palette(c: dict) -> QPalette:
    pal = QPalette()
    roles = [
        (QPalette.ColorRole.Window, c["bg0"]),
        (QPalette.ColorRole.WindowText, c["text"]),
        (QPalette.ColorRole.Base, c["bg2"]),
        (QPalette.ColorRole.AlternateBase, c["bg1"]),
        (QPalette.ColorRole.Text, c["text"]),
        (QPalette.ColorRole.Button, c["bg2"]),
        (QPalette.ColorRole.ButtonText, c["text"]),
        (QPalette.ColorRole.ToolTipBase, c["bg1"]),
        (QPalette.ColorRole.ToolTipText, c["text"]),
        (QPalette.ColorRole.Highlight, c["accent"]),
        (QPalette.ColorRole.HighlightedText, c["accent_text"]),
        (QPalette.ColorRole.Link, c["accent"]),
        (QPalette.ColorRole.LinkVisited, c["accent"]),
        (QPalette.ColorRole.PlaceholderText, c["text_sub"]),
    ]
    # 文字类角色禁用时用次级色（可读），其余角色三态同色
    text_roles = {
        QPalette.ColorRole.Text, QPalette.ColorRole.WindowText,
        QPalette.ColorRole.ButtonText,
    }
    for role, hexcolor in roles:
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            pal.setColor(group, role, QColor(hexcolor))
        disabled_color = c["text_sub"] if role in text_roles else hexcolor
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(disabled_color))
    return pal


# ----------------------------------------------------------------------
# QSS 内嵌图元（G2）：QSS 的 `::down-arrow` / `::up-arrow` 只认位图路径，
# 而仓库 SVG 统一用 `currentColor`（Qt 渲染结果是黑色 → 深色主题下不可见），
# 故按当前主题的次级文字色预染色 + 落盘 PNG 后再喂给 QSS。
# 缓存键 = (逻辑名, 色值, 旋转角)；无 QGuiApplication / QtSvg 缺失时返回空串，
# 由调用方整段省略箭头规则（退化为无箭头，但绝不抛异常）。
# ----------------------------------------------------------------------
_glyph_dir: str = ""
_glyph_cache: dict[tuple, str] = {}


def _glyph_png(name: str, color: str, rotate: float = 0.0) -> str:
    """把 SVG 逻辑图元按 color 染色（可选旋转）渲染成 PNG，返回绝对路径；失败返回 ""。"""
    key = (name, str(color), float(rotate))
    hit = _glyph_cache.get(key)
    if hit is not None:
        return hit
    global _glyph_dir
    path = ""
    try:
        src = icon_path(name)
        if src is not None:
            text = src.read_text(encoding="utf-8").replace("currentColor", str(color))
            from PyQt6.QtCore import QByteArray, QRectF
            from PyQt6.QtGui import QImage, QPainter
            from PyQt6.QtSvg import QSvgRenderer

            renderer = QSvgRenderer(QByteArray(text.encode("utf-8")))
            if renderer.isValid():
                side = 24  # 源 SVG 画布 24×24（QSS 侧再按 glyph 令牌缩放）
                img = QImage(side, side, QImage.Format.Format_ARGB32)
                img.fill(Qt.GlobalColor.transparent)
                painter = QPainter(img)
                try:
                    if rotate:
                        painter.translate(side / 2, side / 2)
                        painter.rotate(float(rotate))
                        painter.translate(-side / 2, -side / 2)
                    renderer.render(painter, QRectF(0, 0, float(side), float(side)))
                finally:
                    painter.end()
                if not _glyph_dir:
                    _glyph_dir = tempfile.mkdtemp(prefix="acouscope_qss_")
                    # 每进程只建一个目录；退出时清理，避免 QSS 图元常驻 /tmp。
                    atexit.register(shutil.rmtree, _glyph_dir, ignore_errors=True)
                out = Path(_glyph_dir) / (
                    f"{name}_{str(color).lstrip('#')}_{int(rotate)}.png")
                if not out.exists():
                    img.save(str(out), "PNG")
                path = out.as_posix()
    except Exception:
        path = ""
    _glyph_cache[key] = path
    return path


def _qss(c: dict) -> str:
    """全局 QSS：padding/margin/border-radius/width/height 一律取自 TOKENS，禁散落字面量。"""
    rad = TOKENS["radius"]
    sem = TOKENS["semantic"]
    sp = TOKENS["spacing"]
    ctl = TOKENS["control"]
    el = TOKENS["elevation"]
    gl = TOKENS["glyph"]
    bd = f"{el['border']}px"                     # 全局唯一描边宽度
    r_sm = f"{rad['sm']}px"
    # 复选框指示器圆角：3 = spacing.xxs + 描边宽（令牌合成，禁字面量）
    r_ind = f"{sp['xxs'] + el['border']}px"
    pad = f"{ctl['pad_y']}px {ctl['pad_x']}px"   # 交互控件内边距
    pad_num = f"{sp['xxs']}px {sp['xs']}px"      # 数字框内边距（右留箭头位，窄档）
    # 下拉/微调箭头位图（SVG 源码用 currentColor，Qt 渲染成黑色 → 深色主题下隐形，
    # 故按当前主题次级文字色预先染色落盘；不可用时整段箭头规则省略，不抛异常）。
    arrow_down = _glyph_png("chevron_down", c["text_sub"])
    arrow_up = _glyph_png("chevron_down", c["text_sub"], 180.0)
    arrow_qss = ""
    if arrow_down:
        arrow_qss += (
            "QComboBox::down-arrow {"
            f" image: url({arrow_down});"
            f" width: {gl['arrow']}px; height: {gl['arrow']}px; }}"
            "QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {"
            f" image: url({arrow_down});"
            f" width: {gl['arrow']}px; height: {gl['arrow']}px; }}"
        )
    if arrow_up:
        arrow_qss += (
            "QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {"
            f" image: url({arrow_up});"
            f" width: {gl['arrow']}px; height: {gl['arrow']}px; }}"
        )
    return f"""
QWidget {{ background: {c["bg0"]}; color: {c["text"]}; }}
QMainWindow, QDialog {{ background: {c["bg0"]}; }}
QLabel, QCheckBox, QRadioButton {{ background: transparent; }}

/* 复选框指示器（G1）：未勾选态必须有可见描边——原生指示器取调色板色，
   深色骨架下与控件底同色系 → 完全看不见。此处显式给底/描边/悬停/勾选四态；
   勾选态用实心 accent 块（仓库无对勾图元资产，QSS 实心块 + 明显色差可判读）。 */
QCheckBox::indicator {{
    width: {gl["indicator"]}px; height: {gl["indicator"]}px;
    border: {bd} solid {c["border"]}; border-radius: {r_ind};
    background: {c["bg2"]}; }}
QCheckBox::indicator:hover {{ border-color: {c["text_sub"]}; background: {c["bg3"]}; }}
QCheckBox::indicator:checked {{
    background: {c["accent"]}; border-color: {c["accent"]}; }}
QCheckBox::indicator:checked:hover {{ border-color: {c["accent_text"]}; }}
QCheckBox::indicator:disabled {{
    background: {c["bg1"]}; border-color: {c["border"]}; }}
QCheckBox::indicator:checked:disabled {{
    background: {c["border_strong"]}; border-color: {c["border_strong"]}; }}

QToolBar {{ background: {c["bg1"]}; border: none;
           border-bottom: {bd} solid {c["border"]};
           padding: {sp["xxs"]}px; spacing: {sp["xs"]}px; }}
QMenuBar {{ background: {c["bg1"]}; color: {c["text"]}; }}
QMenuBar::item:selected {{ background: {c["bg3"]}; }}
QMenu {{ background: {c["bg1"]}; color: {c["text"]};
        border: {bd} solid {c["border"]}; padding: {sp["xs"]}px; }}
QMenu::item {{ padding: {ctl["pad_y"]}px {sp["lg"]}px; border-radius: {r_sm}; }}
QMenu::item:selected {{ background: {c["accent"]}; color: {c["accent_text"]}; }}
QMenu::separator {{ height: {bd}; background: {c["border"]};
                   margin: {sp["xs"]}px {sp["sm"]}px; }}

QPushButton {{ background: {c["bg2"]}; color: {c["text"]};
              border: {bd} solid {c["border"]}; border-radius: {r_sm};
              padding: {pad}; }}
QPushButton:hover {{ background: {c["bg3"]}; }}
QPushButton:pressed {{ background: {c["accent"]}; color: {c["accent_text"]}; }}
/* 开关型按钮的「已开启」态（G9）：accent 底 + accent_text 字 + accent 描边，
   与常态（bg2 底 / border 描边）和悬停态（bg3 底）三态互异。 */
QPushButton:checked {{
    background: {c["accent"]}; color: {c["accent_text"]};
    border: {bd} solid {c["accent"]}; }}
QPushButton:checked:hover {{ background: {c["accent"]}; color: {c["accent_text"]}; }}
QPushButton:disabled {{ color: {c["text_faint"]}; }}

QLineEdit, QTextEdit, QPlainTextEdit {{
    background: {c["bg2"]}; color: {c["text"]};
    border: {bd} solid {c["border"]}; border-radius: {r_sm}; padding: {pad};
    selection-background-color: {c["sel_bg"]}; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: {bd} solid {c["accent"]}; }}

QComboBox {{ background: {c["bg2"]}; color: {c["text"]};
            border: {bd} solid {c["border"]}; border-radius: {r_sm};
            padding: {pad}; }}
QComboBox:focus {{ border: {bd} solid {c["accent"]}; }}
/* 下拉区（G2）：加左边框 + 悬停底色，使箭头区与输入区可辨（原 border:none
   只剩一块空白灰块）；箭头位图由 arrow_qss 按当前主题染色给入。 */
QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: top right;
    width: {sp["md"]}px;
    border: none; border-left: {bd} solid {c["border"]};
    border-top-right-radius: {r_sm}; border-bottom-right-radius: {r_sm};
    background: {c["bg2"]}; }}
QComboBox::drop-down:hover {{ background: {c["bg3"]}; }}
QComboBox QAbstractItemView {{
    background: {c["bg1"]}; color: {c["text"]};
    border: {bd} solid {c["border"]};
    selection-background-color: {c["accent"]};
    selection-color: {c["accent_text"]}; }}

QSpinBox, QDoubleSpinBox {{
    background: {c["bg2"]}; color: {c["text"]};
    border: {bd} solid {c["border"]}; border-radius: {r_sm}; padding: {pad_num};
    selection-background-color: {c["sel_bg"]}; }}
QSpinBox:focus, QDoubleSpinBox:focus {{ border: {bd} solid {c["accent"]}; }}
/* 微调按钮（G2）：上/下按钮各自带可见底与描边，并给悬停反馈——原样式下两钮
   在深色骨架里退化成一块无差别灰块。 */
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border; subcontrol-position: top right;
    width: {sp["md"]}px;
    background: {c["bg2"]}; border-left: {bd} solid {c["border"]};
    border-bottom: {bd} solid {c["border"]}; border-top-right-radius: {r_sm}; }}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover {{
    background: {c["bg3"]}; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: {sp["md"]}px;
    background: {c["bg2"]}; border-left: {bd} solid {c["border"]};
    border-bottom-right-radius: {r_sm}; }}
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {c["bg3"]}; }}
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{
    background: {c["accent"]}; }}
{arrow_qss}

QTableWidget, QTableView, QTreeView, QTreeView.view, QListWidget {{
    background: {c["bg1"]}; color: {c["text"]};
    alternate-background-color: {c["bg0"]};
    border: {bd} solid {c["border"]};
    gridline-color: {c["border"]};
    selection-background-color: {c["accent"]};
    selection-color: {c["accent_text"]}; }}
QHeaderView::section {{
    background: {c["bg2"]}; color: {c["text"]}; border: none;
    border-right: {bd} solid {c["border"]};
    border-bottom: {bd} solid {c["border"]};
    padding: {ctl["pad_y"]}px {sp["sm"]}px; }}

QTabWidget::pane {{ border: {bd} solid {c["border"]}; top: -{bd}; }}
QTabBar::tab {{ background: {c["bg2"]}; color: {c["text"]};
               border: {bd} solid {c["border"]};
               padding: {ctl["pad_y"]}px {sp["md"]}px; }}
QTabBar::tab:selected {{ background: {c["accent"]}; color: {c["accent_text"]}; }}

QStatusBar {{ background: {c["bg1"]}; color: {c["text_sub"]};
             border-top: {bd} solid {c["border"]}; }}
QSplitter::handle {{ background: {c["border"]}; }}
QGroupBox {{ border: {bd} solid {c["border"]}; border-radius: {r_sm};
            margin-top: {sp["sm"]}px; background: transparent; }}
QGroupBox::title {{ subcontrol-origin: margin; left: {sp["sm"]}px;
                   padding: 0 {sp["xs"]}px;
                   color: {c["text_sub"]}; background: {c["bg0"]}; }}

QScrollBar:vertical {{ background: transparent; width: {ctl["pad_x"]}px;
                      margin: {sp["xxs"]}px; }}
QScrollBar::handle:vertical {{ background: {c["border"]};
                              border-radius: {r_sm}; min-height: {ctl["h_lg"]}px; }}
QScrollBar::handle:vertical:hover {{ background: {c["text_sub"]}; }}
QScrollBar:horizontal {{ background: transparent; height: {ctl["pad_x"]}px;
                        margin: {sp["xxs"]}px; }}
QScrollBar::handle:horizontal {{ background: {c["border"]};
                                border-radius: {r_sm}; min-width: {ctl["h_lg"]}px; }}
QScrollBar::handle:horizontal:hover {{ background: {c["text_sub"]}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QToolTip {{ background: {c["bg1"]}; color: {c["text"]};
           border: {bd} solid {c["border"]}; }}
QProgressBar {{ background: {c["bg2"]}; border: {bd} solid {c["border"]};
               border-radius: {r_sm}; text-align: center; color: {c["text"]}; }}
QProgressBar::chunk {{ background: {c["accent"]}; border-radius: {r_sm}; }}

/* 语义反馈色（V099_TOKENS_V1）：toast/内联提示按 level 属性引用 */
QFrame[level="warning"] {{ border-left: {el["low"]}px solid {sem["warning"]}; }}
QFrame[level="error"] {{ border-left: {el["low"]}px solid {sem["error"]}; }}
QFrame[level="success"] {{ border-left: {el["low"]}px solid {sem["success"]}; }}
QFrame[level="info"] {{ border-left: {el["low"]}px solid {sem["info"]}; }}
"""


def apply_theme(theme_id: str) -> None:
    """应用主题（QPalette + 全局 QSS + 动态控件通知），立即生效。"""
    global _theme_id
    if theme_id not in THEME_ORDER:
        theme_id = "default"
    _theme_id = theme_id
    pal_id = _resolve_system() if theme_id == "system" else theme_id
    _current.clear()
    _current.update(THEMES[pal_id])
    _current["id"] = pal_id

    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        app.setPalette(_palette(_current))
        app.setStyleSheet(_qss(_current))
        if theme_id == "system":
            _watch_system(app)
    _icon_cache.clear()  # 主题切换：图标缓存整体失效（T-601）
    refresh_icons()  # T-1078/IM-29：已挂载图标按新主题重染（工具栏/左右 ribbon 一行通修）
    _notify_dynamic()


def colors() -> dict[str, str]:
    """当前生效配色（含所有角色 + id）。"""
    return dict(_current)


# ----------------------------------------------------------------------
# 内容色板取用入口（T-1036；T-1038 多序列数据色复用同一入口）
# ----------------------------------------------------------------------

def _relative_luminance(hexcolor: str) -> float:
    """WCAG 相对亮度（骨架推断的兜底口径）。"""
    h = hexcolor.lstrip("#")
    chans = []
    for i in (0, 2, 4):
        v = int(h[i:i + 2], 16) / 255
        chans.append(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * chans[0] + 0.7152 * chans[1] + 0.0722 * chans[2]


def skeleton_of(colors_dict: dict | None = None) -> str:
    """骨架判定：优先取主题条目的显式 `skeleton`；缺省时按 bg0 相对亮度推断。"""
    c = _current if colors_dict is None else colors_dict
    sk = c.get("skeleton")
    if sk in ("dark", "light"):
        return str(sk)
    return "dark" if _relative_luminance(str(c["bg0"])) < 0.5 else "light"


def track_palette(colors_dict: dict | None = None) -> list[str]:
    """当前骨架的内容色板（轨身份色 / 多序列内容色，12 色轮转序）。"""
    return list(TOKENS["track_palette"][skeleton_of(colors_dict)])


def track_color(index: int) -> str:
    """轨身份色：内容色板按索引取模轮转（与 semantic 反馈色分家）。"""
    pal = track_palette()
    return str(pal[int(index) % len(pal)])


def data_ink(role: str, colors_dict: dict | None = None) -> str:
    """数据墨色：按用途角色取当前骨架色值（T-1038；与交互色/反馈色/身份色分家）。"""
    group = TOKENS["data"]
    palette = group[skeleton_of(colors_dict)]
    if role not in palette:
        raise KeyError(f"未知数据墨色角色：{role}")
    return str(palette[role])


def key_faces(colors_dict: dict | None = None) -> dict[str, str]:
    """键面（钢琴键）角色色值：**单套物理色**，明/暗骨架返回**同一字典**（T-1042b）。

    角色：white（白键面）/ black（黑键面）/ white_seam（白键间分隔）/ label（键面音名文字）。
    pyqtgraph 键面绘制与守卫测试共用此入口，键面色唯一源在 theme.py。
    """
    group = TOKENS["keys"]
    palette = group["physical"]
    return {role: str(palette[role]) for role in group["roles"]}


def key_face(role: str, colors_dict: dict | None = None) -> str:
    """键面单角色色值（T-1042 取色入口）。"""
    faces = key_faces(colors_dict)
    if role not in faces:
        raise KeyError(f"未知键面角色：{role}")
    return faces[role]


# ----------------------------------------------------------------------
# 字体族回落链（T-1037）：族链字面量唯一源在 typography 令牌，其余文件一律经
# 下列 helper 取链；泛型关键字须剔除，因 QFont.setFamilies 只接受具体族名。
# ----------------------------------------------------------------------
_GENERIC_FAMILIES = frozenset({
    "sans-serif", "serif", "monospace", "cursive", "fantasy", "system-ui",
})


def _parse_family_chain(raw: str) -> list[str]:
    """把 CSS 风格族链字符串解析为具体族名列表（去引号/空白 + 剔泛型关键字 + 去重保序）。"""
    chain: list[str] = []
    for part in str(raw).split(","):
        name = part.strip().strip("'\"").strip()
        if not name or name.lower() in _GENERIC_FAMILIES:
            continue
        if name not in chain:
            chain.append(name)
    return chain


def _installed_family_names() -> tuple[str, ...] | None:
    """已安装族名；无 QGuiApplication 时字体库不可查，返回 None 保留令牌链。"""
    if QGuiApplication.instance() is None:
        return None
    return tuple(QFontDatabase.families())


def _filter_installed(chain: list[str]) -> list[str]:
    # L4：缺失族进 setFamilies 会触发 qt.qpa.fonts 别名告警且回落不受控
    installed = _installed_family_names()
    if installed is None:
        return chain
    known = {name.casefold() for name in installed}
    return [name for name in chain if name.casefold() in known]


def ui_font_families() -> list[str]:
    """UI 正文字族回落链（具体族名；泛型剔除 + 按已安装族过滤，保序）。"""
    return _filter_installed(_parse_family_chain(TOKENS["typography"]["family"]))


def ui_mono_families() -> list[str]:
    """UI 等宽字族回落链（具体族名；泛型剔除 + 按已安装族过滤，保序）。"""
    return _filter_installed(_parse_family_chain(TOKENS["typography"]["mono"]))


def ui_font() -> QFont:
    """UI 正文字体（族 = ui_font_families()；字号由调用方按令牌补）。"""
    font = QFont()
    chain = ui_font_families()
    if chain:
        font.setFamilies(chain)
    return font


def ui_mono_font() -> QFont:
    """UI 等宽字体（族 = ui_mono_families()；字号/样式由调用方补）。"""
    font = QFont()
    chain = ui_mono_families()
    if chain:
        font.setFamilies(chain)
    return font


def ui_mono_family_qss() -> str:
    """QSS font-family 取值（已安装族过滤；无 app 时回落令牌原串）。

    QSS 里写死未安装族同样触发 qt.qpa.fonts 别名告警（真机：SF Mono）。
    """
    chain = ui_mono_families()
    return (", ".join(f"'{name}'" for name in chain)
            if chain else TOKENS["typography"]["mono"])


# ----------------------------------------------------------------------
# 动态样式：主题变化时自动重设的控件样式
# ----------------------------------------------------------------------

def style_when_theme(widget, builder):
    """注册随主题更新的控件样式，返回手动刷新函数。

    builder: (colors_dict) -> QSS 字符串；控件销毁后自动移除。
    返回的 refresh() 可在控件状态变化后按当前主题立即重设样式。
    """

    def refresh() -> None:
        try:
            widget.setStyleSheet(builder(colors()))
        except Exception:
            pass

    _dynamic.append((weakref.ref(widget), builder))
    refresh()
    return refresh


def _notify_dynamic() -> None:
    alive = []
    for ref, builder in _dynamic:
        w = ref()
        if w is None:
            continue
        alive.append((ref, builder))
        try:
            w.setStyleSheet(builder(colors()))
        except Exception:
            pass
    _dynamic[:] = alive
    _notify_callbacks()


# 主题变化回调（弱引用绑定方法，控件销毁自动移除）
_callbacks: list = []


def on_theme_change(method) -> None:
    """注册主题变化回调（须为绑定方法，随宿主对象自动失效）。"""
    _callbacks.append(weakref.WeakMethod(method))


def _notify_callbacks() -> None:
    alive = []
    for ref in _callbacks:
        m = ref()
        if m is None:
            continue
        alive.append(ref)
        try:
            m()
        except Exception:
            pass
    _callbacks[:] = alive


# ----------------------------------------------------------------------
# 主题色卡图标（设置下拉展示）
# ----------------------------------------------------------------------

def theme_swatch(theme_id: str, size: int = 18) -> QIcon:
    """生成主题色卡：左半应用底色 + 右半强调色（签名与语义不变，随新配色更新）。"""
    if theme_id == "system":
        c = THEMES["dark"]
        left = QColor(THEMES["default"]["bg0"])
        right = QColor(THEMES["dark"]["bg0"])
    else:
        c = THEMES.get(theme_id, THEMES["default"])
        left, right = QColor(c["bg0"]), QColor(c["accent"])
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    from PyQt6.QtGui import QPainter, QPen

    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    half = size // 2
    edge = TOKENS["elevation"]["border"]
    r_sm = TOKENS["radius"]["sm"]
    p.fillRect(edge, edge, half, size - 2 * edge, left)
    p.fillRect(half + 1, edge, size - half - 2, size - 2 * edge, right)
    p.setPen(QPen(QColor(c["border_strong"]), edge))
    p.drawRoundedRect(0, 0, size - 1, size - 1, r_sm, r_sm)
    p.end()
    return QIcon(pm)


# ----------------------------------------------------------------------
# 单一图标家族（SVG）：逻辑名 → resources/icons 下相对路径。
#   generic/   = 通用 UI（open/close/settings/chevron…，Lucide 24×24 单色）
#   signature/ = 专业业务（layer_stack/pitch_contour…，T-603 波启用，本波留空）
# SVG 统一使用 currentColor 单色；渲染时按控件状态替换为当前主题语义色（T-601）。
# 资源缺失时回退空 QIcon（不抛异常）；SVG 资源随各功能任务补入。
# 用法：btn.setIcon(get_icon("open"))；严禁各控件自绘/混用 QStyle 像素图。
# ----------------------------------------------------------------------
ICONS: dict[str, str] = {
    # 文件/编辑/导出（T-604 错峰：main_window 引用本波不动，仅备好资源与映射）
    "open": "generic/folder-open.svg",
    "save": "generic/save.svg",
    "export": "generic/download.svg",
    "undo": "generic/arrow-left.svg",
    "redo": "generic/arrow-right.svg",
    # 播放控制（T-1001 ②：generic 资源已由 scripts/derive_icon_styles.py 补齐）
    "play": "generic/play.svg",
    "stop": "generic/stop.svg",
    "record": "generic/record.svg",
    # 通用 UI（T-602 已入库 generic/，源自 Lucide）
    "ai": "generic/sparkles.svg", "settings": "generic/settings.svg",
    "layers": "generic/layers.svg", "inspect": "generic/search.svg",
    "files": "generic/folder.svg",
    "chevron_down": "generic/chevron-down.svg",
    "chevron_right": "generic/chevron-right.svg",
    "close": "generic/x.svg", "download": "generic/download.svg",
    "info": "generic/info.svg",
    # CB-011 B-2：左图标栏帮助入口（Lucide help-circle，与 info/settings 同族）
    "help-circle": "generic/help-circle.svg",
    # T-1048：面板类图元（授权扩容 19→21）——左右栏「面板可见性开关」专用，
    # 取代原右栏开关误用的 inspect（放大镜）语义
    "sidebar_left": "generic/sidebar-left.svg",
    "sidebar_right": "generic/sidebar-right.svg",
    # T-1025：图标补齐 9 名（授权扩容 21→30）——IM-10 多轨 6 名 + T-1054 批0 前置 3 名，
    # 均为 AcouScope 自有图元（derive_icon_styles.MISSING_GENERIC_PRIMITIVES），接线于批0/多轨任务。
    "track": "generic/track.svg",
    "add_track": "generic/add_track.svg",
    "solo": "generic/solo.svg",
    "mute": "generic/mute.svg",
    "align": "generic/align.svg",
    "volume": "generic/volume.svg",
    "room_modal": "generic/room_modal.svg",
    "room_acoustic": "generic/room_acoustic.svg",
    "chart_designer": "generic/chart_designer.svg",
    "tuning_ruler": "generic/tuning_ruler.svg",
    # T-1098：IM-10 呈现模式 2 名（授权扩容 31→33）——多轨呈现带「一图 / 多图」切换钮专用，
    # 与文字标签并存；AcouScope 自有图元，接线于 multitrack_view 自建工具栏。
    "mode_single": "generic/mode_single.svg",
    "mode_grid": "generic/mode_grid.svg",
    # T-1109 IM-31：音频设备设置标签图标（授权扩容 33→34）
    "audio_device": "generic/audio_device.svg",
    # T-1111「支持一下」常驻入口图标（授权扩容 34→35）
    "encourage": "generic/encourage.svg",
    # T-1112 微信群入口图标（授权扩容 35→36）
    "weixin_group": "generic/weixin_group.svg",
}

# 图标状态 → 当前主题语义色角色（值必须是 colors() 的既有键，禁硬编码 hex；
# 需新色一律先入 THEMES/TOKENS）。语义：
#   default  → text          正文/内容色（工具图标常态）
#   hover    → accent        悬停反馈（强调色）
#   active   → accent_text   按压/选中：QSS 按压约定 accent 底 + accent_text 前景
#   disabled → sub           次级灰（禁用态弱化）
_ICON_STATE_ROLE: dict[str, str] = {
    "default": "text",
    "hover": "accent",
    "active": "accent_text",
    "disabled": "sub",
}

# 图标缓存：(name, state, 风格, 主题指纹) → QIcon。主题/风格切换自动失效。
_icon_cache: dict[tuple, QIcon] = {}

# ----------------------------------------------------------------------
# 图标风格（T-1001）：脚本派生三套 + generic 基准兜底
#   resources/icons/{macos,win,mint}/ 由 scripts/derive_icon_styles.py 确定性派生
#   （以 generic/*.svg 为基准仅做描边属性改写 + 绕画布中心等比缩放；viewBox 24×24
#   不变、一律 currentColor；禁手绘、禁复制系统官方资产、禁网络）。
#   解析口径：当前风格目录命中则该名用之；缺名回退 generic；generic 亦缺 → None。
#   默认 generic → 既有调用零变化。风格取值持久化在 settings.json 的 icon_style。
# ----------------------------------------------------------------------
ICON_STYLES: list[str] = ["macos", "win", "mint", "generic"]  # 末位 generic = 兜底/默认
_DEFAULT_ICON_STYLE = "generic"

# 当前风格：None = 尚未确定 → 首次取用时从配置惰性自举（启动期无显式调用点）
_icon_style: str | None = None

# 图标实例反查表：QIcon.cacheKey() → (逻辑名, 状态)。供 refresh_icons 在风格切换后
# 把已挂到控件/QAction 上的图标按新风格重取（QIcon 拷贝共享 cacheKey，故可反查）。
_icon_origin: dict[int, tuple[str, str]] = {}


def _style_from_config() -> str:
    """配置中的图标风格；非法值 / 读取失败一律回落默认 generic。"""
    try:
        from acouscope.utils.config import Settings

        value = getattr(Settings.load(), "icon_style", _DEFAULT_ICON_STYLE)
    except Exception:
        return _DEFAULT_ICON_STYLE
    return value if value in ICON_STYLES else _DEFAULT_ICON_STYLE


def icon_style() -> str:
    """当前图标风格；未显式设置时惰性自举（settings.json → 默认 generic，仅读一次）。"""
    global _icon_style
    if _icon_style is None:
        _icon_style = _style_from_config()
    return _icon_style


def set_icon_style(style: str) -> bool:
    """设置图标风格：清图标缓存 + 刷新已挂载图标，立即生效。

    返回 False = 非法风格（原值不变）；同值调用为幂等空操作（不清缓存、不刷新）。
    """
    global _icon_style
    if style not in ICON_STYLES:
        return False
    if style == icon_style():
        return True
    _icon_style = style
    _icon_cache.clear()
    refresh_icons()
    return True


def refresh_icons(root=None) -> int:
    """按当前风格/主题重取已挂载图标（由 get_icon 生成者），返回刷新条目数。

    - root 缺省遍历 QApplication 全部顶层窗口，含各控件与其 QAction 的图标。
    - 非 get_icon 来源（系统/自绘）图标不在反查表内 → 原样保留。
    - 无 QApplication（导入期/纯逻辑）返回 0，不抛异常。
    """
    from PyQt6.QtWidgets import QAbstractButton, QApplication, QWidget

    app = QApplication.instance()
    if app is None:
        return 0
    roots = [root] if root is not None else list(app.topLevelWidgets())
    targets: list = []
    for w in roots:
        if not isinstance(w, QWidget):
            continue
        targets.append(w)
        targets.extend(w.findChildren(QWidget))
    count = 0
    seen_widget: set[int] = set()
    seen_action: set[int] = set()
    for widget in targets:
        if id(widget) in seen_widget:
            continue
        seen_widget.add(id(widget))
        try:
            if isinstance(widget, QAbstractButton):
                origin = _icon_origin.get(widget.icon().cacheKey())
                if origin is not None:
                    widget.setIcon(get_icon(*origin))
                    count += 1
            for action in widget.actions():
                if id(action) in seen_action:
                    continue
                seen_action.add(id(action))
                origin = _icon_origin.get(action.icon().cacheKey())
                if origin is not None:
                    action.setIcon(get_icon(*origin))
                    count += 1
        except RuntimeError:
            continue  # 控件/动作已在销毁路径（C++ 对象已回收），跳过不影响其余
    return count


def _icon_fingerprint() -> tuple:
    """主题指纹：图标四态所涉语义色的 hex 元组，主题切换即变化。"""
    c = colors()
    return tuple(c.get(role) for role in _ICON_STATE_ROLE.values())


def icon_state_color(state: str = "default") -> str:
    """state → 当前主题语义色（hex）；未知 state 回落 default。

    色值一律取自当前主题 colors() 角色，无硬编码 hex。供控件与测试引用。
    """
    c = colors()
    role = _ICON_STATE_ROLE.get(state, "text")
    return c.get(role, c.get("text", ""))


def _icon_file(name: str, style: str):
    """按风格解析图标文件：<style>/<资源名>.svg 命中即用；缺则回退 generic；再缺 None。

    T-1001：风格目录缺该名资源时回退 generic（禁空 QIcon 的单侧缺口），
    仍未命中才返回 None（由调用方空 QIcon 兜底，不抛异常）。
    """
    fname = ICONS.get(name)
    if fname is None:
        return None
    from pathlib import Path

    base = Path(__file__).resolve().parent.parent / "resources" / "icons"
    if style != _DEFAULT_ICON_STYLE:
        p = base / style / Path(fname).name
        if p.exists():
            return p
    p = base / fname
    return p if p.exists() else None


def icon_path(name: str):
    """返回当前图标风格下 SVG 的 Path；无映射 / 资源缺失（含回退 generic 后仍缺）返回 None。"""
    return _icon_file(name, icon_style())


def style_icon(style: str, name: str, size: int = 18) -> QIcon:
    """指定风格的图标预览（设置面板用）：不改当前风格、不入缓存。

    资源缺失回落 generic → 空 QIcon；无 QGuiApplication 时退化为文件延迟加载 QIcon。
    """
    p = _icon_file(name, style if style in ICON_STYLES else _DEFAULT_ICON_STYLE)
    if p is None:
        return QIcon()
    if QGuiApplication.instance() is None:
        return QIcon(str(p))
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return QIcon()
    svg = text.replace("currentColor", icon_state_color("default"))
    pm = _render_svg_bytes(svg.encode("utf-8"), 1.0)
    if pm is None or pm.isNull():
        return QIcon()
    return QIcon(pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation))


def _render_svg_bytes(svg_bytes: bytes, dpr: float):
    """把染色后的 SVG 字节经 QSvgRenderer 渲染为 QPixmap（含 @dpr 高 DPI）。

    返回 None = 渲染不可用（QtSvg 缺失 / SVG 无效 / 空），调用方回退空 QIcon。
    """
    try:
        from PyQt6.QtCore import QByteArray, QRectF
        from PyQt6.QtGui import QPainter
        from PyQt6.QtSvg import QSvgRenderer
    except Exception:
        return None
    renderer = QSvgRenderer(QByteArray(svg_bytes))
    if not renderer.isValid():
        return None
    logical = renderer.defaultSize()
    if logical.width() <= 0 or logical.height() <= 0:
        return None
    pw = max(1, int(round(logical.width() * dpr)))
    ph = max(1, int(round(logical.height() * dpr)))
    pm = QPixmap(pw, ph)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    try:
        renderer.render(p, QRectF(0, 0, float(logical.width()), float(logical.height())))
    finally:
        p.end()
    return pm


def get_icon(name: str, state: str = "default") -> QIcon:
    """获取图标：SVG 资源存在则按 (name, state) 染色渲染，否则空 QIcon 回退（不抛异常）。

    - state: default/hover/active/disabled → 语义色（icon_state_color）。
    - 方案 A：把 SVG 文本中 currentColor 替换为状态色 → QSvgRenderer 渲染到 QPixmap。
    - 资源：当前风格目录优先，缺名回退 generic（见 _icon_file）；两者皆缺 → 空 QIcon。
    - 缓存：(name, state, 当前风格, 主题指纹)；apply_theme / set_icon_style 时清空。
    - 兼容：get_icon(name)（state 缺省）行为不变；无 QGuiApplication 的纯逻辑/导入期
      退化为 QIcon(str(p)) 文件延迟加载，仍不抛异常。
    """
    key = (name, state, icon_style(), _icon_fingerprint())
    hit = _icon_cache.get(key)
    if hit is not None:
        return hit

    icon = QIcon()  # 回退空图标
    p = icon_path(name)
    if p is not None:
        app = QGuiApplication.instance()
        if app is None:
            # 无 GUI 应用实例：QPixmap/QPainter 不可用，保留历史 QIcon(str(p)) 行为
            icon = QIcon(str(p))
        else:
            try:
                text = p.read_text(encoding="utf-8")
            except OSError:
                text = ""
            if text:
                try:
                    dpr = float(app.devicePixelRatio())
                except Exception:
                    dpr = 1.0
                svg = text.replace("currentColor", icon_state_color(state))
                pm = _render_svg_bytes(svg.encode("utf-8"), dpr)
                if pm is not None and not pm.isNull():
                    icon = QIcon(pm)
    if not icon.isNull():
        # 反查登记（T-1001）：风格切换后据此把已挂载图标按新风格重取
        _icon_origin[icon.cacheKey()] = (name, state)
    _icon_cache[key] = icon
    return icon
