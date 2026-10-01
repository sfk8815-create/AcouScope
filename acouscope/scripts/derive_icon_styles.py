#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""T-1001：三风格图标派生脚本（确定性 / 幂等 / 完全离线）。

口径
----
* 基准（base）= ``src/acouscope/resources/icons/generic/*.svg``（既有 15 枚 + 本脚本按
  ``MISSING_GENERIC_PRIMITIVES`` 生成补齐的 3 枚）。
* 产物（derived）= ``icons/{macos,win,mint}/<基准同名>.svg``，viewBox 恒为 24×24、
  颜色恒为 ``currentColor``，供 ``acouscope.ui.theme`` 按当前图标风格取用。
* 变换仅限两类，**不改图元语义**（元素标签、属性、路径数据逐字保留，仅外裹
  ``<g transform>`` 与根元素描边属性改写）：
  1) 描边属性：``stroke-width`` / ``stroke-linecap`` / ``stroke-linejoin`` /
     ``stroke-miterlimit``（参数见 ``STYLE_PARAMS``）；
  2) 整体几何：绕画布中心 ``CENTER,CENTER`` 的等比缩放（同一参数表）。
* 幂等：文件枚举一律 ``sorted``；数值一律 ``_fmt`` 定点输出；无时间戳 / 无随机 /
  无绝对路径；换行统一 ``\\n``。故连续两次运行输出逐字节一致（④ 实证见报告）。

用法
----
    python acouscope/scripts/derive_icon_styles.py [--assets <图标根目录>] [--quiet]

``--assets`` 缺省为仓库内图标根目录；测试用临时目录运行以验证幂等（不触碰仓库）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径与画布常量（一律由本文件推导，禁绝对路径入产物）
# ---------------------------------------------------------------------------
SCRIPT_REL = "scripts/derive_icon_styles.py"
ICON_ROOT = Path(__file__).resolve().parents[1] / "src" / "acouscope" / "resources" / "icons"

BASE_STYLE = "generic"
DERIVED_STYLES = ("macos", "win", "mint")

VIEWBOX = "0 0 24 24"
CANVAS = 24.0
CENTER = CANVAS / 2.0
BASE_STROKE_WIDTH = 2.0

# ---------------------------------------------------------------------------
# ② generic 缺失名（ICONS 有映射、资源缺失）——模块级图元常量，禁散落手绘
#    play = 三角 / stop = 方 / record = 圆；T-1025 再补 9 枚（IM-10 多轨 6 + T-1054 批0 前置 3）。
#    结构须满足 test_cb007 的 generic 目录约束
#    （viewBox 24×24 / width+height / 仅 none|currentColor / stroke-width∈[1.5,2] /
#     含 Source: 与 License: 声明行）。
#    新图元一律自有原创（AcouScope 自有常量头），禁复制第三方路径数据。
# ---------------------------------------------------------------------------
MISSING_GENERIC_PRIMITIVES = {
    # -- 基础（T-1001） --
    "play": '<polygon points="7 4 20 12 7 20" />',
    "stop": '<rect x="6" y="6" width="12" height="12" />',
    "record": '<circle cx="12" cy="12" r="6.5" />',
    # -- T-1025 多轨 6 名（IM-10） --
    # track：单条音轨 —— 横向圆角轨条（左右各留白 ≥2px），语义=多轨时间线上的单轨。
    "track": '<rect x="3" y="10" width="18" height="4" rx="2" />',
    # add_track：新建音轨 —— 轨条 + 右上加号（十字），语义=在既有轨道旁追加一条新轨。
    # T-1076 O-1 修法(b)：加号右移（横笔 17→21 / 竖笔 x=19），轨条右缘 16 与加号起 17 间隙 ≥1px，消除 0.5px 相碰。
    "add_track": '<g><rect x="3" y="10" width="13" height="4" rx="2" /><path d="M19 8.5v7" /><path d="M17 12h4" /></g>',
    # solo：独奏/监听 —— 耳机轮廓（头带圆弧 + 左右耳罩），语义=只监听该轨；禁字母 S。
    "solo": '<g><path d="M3.5 13a8.5 8.5 0 0 1 17 0" /><rect x="3" y="13" width="3.5" height="6" rx="1.5" /><rect x="17.5" y="13" width="3.5" height="6" rx="1.5" /></g>',
    # mute：静音 —— 喇叭（方锥体）+ 贯穿斜杠，语义=此轨静音。
    "mute": '<g><path d="M5 9v6h3l4 3.5V5.5L8 9H5z" /><path d="M21 4L4 21" /></g>',
    # align：对齐 —— 三条左对齐横线（长短交替），语义=多轨时间对齐。
    "align": '<g><path d="M3 6h10" /><path d="M3 12h15" /><path d="M3 18h7" /></g>',
    # volume：音量 —— 喇叭（方锥体）+ 两条声波弧，语义=调节音量。
    "volume": '<g><path d="M4.5 9v6h3l4 3V6l-4 3h-3z" /><path d="M15 9.5a4 4 0 0 1 0 5" /><path d="M17.5 8a4 4 0 0 1 0 8" /></g>',
    # -- T-1025 批0 前置 3 名（T-1054 工作区开关组） --
    # room_modal：房间模态 —— 3×3 驻波节点 + 中央振幅标记（环），语义=简正模式/房间模态。
    # T-1076 O-2 修法(A)：去共用外框，与 room_acoustic（框+声波弧）轮廓级分化。
    "room_modal": '<g><circle cx="5" cy="5" r="1.2" /><circle cx="12" cy="5" r="1.2" /><circle cx="19" cy="5" r="1.2" /><circle cx="5" cy="12" r="1.2" /><circle cx="19" cy="12" r="1.2" /><circle cx="5" cy="19" r="1.2" /><circle cx="12" cy="19" r="1.2" /><circle cx="19" cy="19" r="1.2" /><circle cx="12" cy="12" r="1.2" /><circle cx="12" cy="12" r="4.5" /></g>',
    # room_acoustic：房间声学 —— 房间轮廓 + 扩散波弧（两段发散圆弧），语义=室内声学/混响。
    "room_acoustic": '<g><rect x="3" y="4" width="18" height="16" rx="1" /><path d="M6.5 12c2.8-2.6 8.2-2.6 11 0" /><path d="M6 8.5c3.5-3.2 8.5-3.2 12 0" /></g>',
    # chart_designer：图表设计器 —— 开放式 L 形坐标轴 + 三柱数据 + 顶部滑块（轨道+手柄），语义=图表设计与调节。
    # T-1077 O-3 重设计：去封闭外框 rect（"相框/图片"元凶），改"轴+柱+滑块"三簇开放式构图。
    "chart_designer": '<g><path d="M5 4v15h15" /><path d="M9 19v-4" /><path d="M13 19v-8" /><path d="M17 19v-6" /><path d="M8 7h10" /><path d="M15 5v4" /></g>',
    # -- T-1084 O-4（候选 A） --
    # tuning_ruler：音律标尺 —— 下基线 + 四等距刻度竖线 + 中刻度高亮（顶端实心点），语义=调音/标尺叠加层。
    "tuning_ruler": '<g><path d="M3 19h18" /><path d="M6 19v-5" /><path d="M14 19v-5" /><path d="M18 19v-5" /><path d="M10 19V6" /><circle cx="10" cy="6" r="1.6" fill="currentColor" /></g>',
    # -- T-1098 IM-10 呈现模式 2 名 --
    # mode_single：一图 —— 一条下基线上两条起伏折线同轴交叠，语义=多轨 F0 叠合成一张图。
    # 与 chart_designer（L 形轴+柱）、align（三条水平直线）逐簇分化：
    # 本枚无竖柱、无刻度、无外框，主体是「两条互相交叠的轨迹」。
    "mode_single": '<g><path d="M3.5 19.5h17" /><polyline points="4 15.5 8 8.5 12 12.5 16 5.5 20 9.5" /><polyline points="4 16 8 12.5 12 10 16 8 20 6" /></g>',
    # mode_grid：多图 —— 2×2 等距分离小格（四角各一，互不相连），语义=各轨分离成网格。
    # 与 room_modal（3×3 实心点 + 中央环）、layers（错位菱形堆叠）分化：本枚为空心方格阵列。
    "mode_grid": '<g><rect x="3" y="3" width="7" height="7" rx="2" /><rect x="14" y="3" width="7" height="7" rx="2" /><rect x="3" y="14" width="7" height="7" rx="2" /><rect x="14" y="14" width="7" height="7" rx="2" /></g>',
    # -- T-1109 IM-31 设置标签图标 --
    # audio_device：音频设备 —— 扬声器箱体轮廓 + 两条声波弧，语义=音频输入/输出设备设置。
    # 与 volume（喇叭锥体+声波）、solo（耳机轮廓）分化：本枚为矩形箱体+圆形单元+声波。
    "audio_device": '<g><rect x="3" y="5" width="12" height="14" rx="2" /><circle cx="9" cy="14" r="3" /><path d="M18 9a4 4 0 0 1 0 6" /><path d="M20.5 7a6 6 0 0 1 0 10" /></g>',
    # -- T-1111「支持一下」常驻入口 --
    # encourage：鼓励/支持 —— 心形描边轮廓（24×24 视框·右下留白收势），语义=自愿支持/致谢。
    # 与 ai（sparkles 星芒）、settings（齿轮）、audio_device（音箱）语义分化：本枚只画心形单线。
    "encourage": '<g><path d="M12 20.2C12 20.2 4.4 15.5 4.4 10.3A4.3 4.3 0 0 1 12 7.6A4.3 4.3 0 0 1 19.6 10.3C19.6 15.5 12 20.2 12 20.2Z" /></g>',
    # weixin_group：官方微信群 —— 两个交叠的圆角对话气泡 + 右下加号，语义=扫码入群/社区。
    # 与 ai（星芒）、encourage（心形）、settings（齿轮）语义分化：本枚只画气泡与加号。
    "weixin_group": '<g><rect x="3" y="4" width="12" height="9" rx="3" /><path d="M6 13v3l3-3" /><rect x="9" y="9" width="12" height="9" rx="3" /><path d="M27 13.5h-9m4.5-4.5v9" /></g>',
}

_PRIMITIVE_HEADER = (
    "<!-- SPDX-License-Identifier: GPL-3.0-only -->",
    "<!-- Source: AcouScope 自有图元常量（derive_icon_styles.MISSING_GENERIC_PRIMITIVES），非系统官方资产 -->",
    "<!-- License: GPL-3.0-only (c) AcouScope contributors -->",
)

# ---------------------------------------------------------------------------
# ③ 三风格参数表（模块级常量；改风格只需改此表）
#   stroke_width : 根元素 stroke-width（macOS 略细 / Windows 略粗 / Mint 中线）
#   linecap/join : 端点与拐角形态（macOS 圆头圆角 / Windows 直角尖角 / Mint 圆角折中）
#   miterlimit   : 拐角"方整度"（越大尖角越锐利；Windows 更方整，macOS 用默认）
#   scale        : 绕画布中心的等比缩放（macOS 略收 / Windows 略放 / Mint 折中）
# ---------------------------------------------------------------------------
STYLE_PARAMS: dict[str, dict] = {
    # 基准（generic）自身参数：供 render_base 复用同一套根元素属性拼装
    "generic": {
        "stroke_width": BASE_STROKE_WIDTH,
        "linecap": "round",
        "linejoin": "round",
        "miterlimit": None,
        "scale": 1.0,
        "note": "基准口径（Lucide 单色 24×24 + 本脚本补齐的三枚自有图元）",
    },
    "macos": {
        "stroke_width": 1.75,
        "linecap": "round",
        "linejoin": "round",
        "miterlimit": None,  # 用 SVG 默认 4（圆角场景无需收紧）
        "scale": 0.95,
        "note": "圆头圆角 + 略细笔画 + 略收几何（圆润观感）",
    },
    "win": {
        "stroke_width": 2.25,
        "linecap": "butt",
        "linejoin": "miter",
        "miterlimit": 10.0,
        "scale": 1.02,
        "note": "直角端点/尖角 + 略粗笔画 + 抬高 miterlimit 更方整 + 略放几何",
    },
    "mint": {
        "stroke_width": 2.0,
        "linecap": "round",
        "linejoin": "round",
        "miterlimit": 6.0,
        "scale": 0.985,
        "note": "圆角接头 + 中线宽 + miterlimit 折中 + 轻圆角（介于前两者）",
    },
}


# ---------------------------------------------------------------------------
# 文本工具
# ---------------------------------------------------------------------------
def _fmt(value: float) -> str:
    """定点小数格式化：去尾零、无科学计数（保证逐字节可复现）。"""
    text = f"{float(value):.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _split_svg(text: str) -> tuple[list[str], str]:
    """拆分为 (根元素前置注释行, 根元素内部原文)。"""
    start = text.index("<svg")
    inner_start = text.index(">", start) + 1
    inner_end = text.rindex("</svg>")
    comments = [ln for ln in text[:start].splitlines() if ln.strip()]
    return comments, text[inner_start:inner_end]


def _elements(text: str) -> list[str]:
    """取图元行（去首尾空白）——用于「禁改图元语义」自检。"""
    _comments, inner = _split_svg(text)
    return [ln.strip() for ln in inner.splitlines() if ln.strip().startswith("<")]


def _derived_comment(style: str) -> str:
    """派生说明行（单行、参数自描述、无时间戳 → 幂等）。"""
    p = STYLE_PARAMS[style]
    limit = "default" if p["miterlimit"] is None else _fmt(p["miterlimit"])
    return (
        f"<!-- Derived: {SCRIPT_REL} (style={style}"
        f"; stroke-width={_fmt(p['stroke_width'])}"
        f"; linecap={p['linecap']}; linejoin={p['linejoin']}"
        f"; miterlimit={limit}; scale={_fmt(p['scale'])}) -->"
    )


def _root_attrs(style: str) -> list[str]:
    p = STYLE_PARAMS[style]
    attrs = [
        "<svg",
        '  xmlns="http://www.w3.org/2000/svg"',
        '  width="24"',
        '  height="24"',
        f'  viewBox="{VIEWBOX}"',
        '  fill="none"',
        '  stroke="currentColor"',
        f'  stroke-width="{_fmt(p["stroke_width"])}"',
        f'  stroke-linecap="{p["linecap"]}"',
        f'  stroke-linejoin="{p["linejoin"]}"',
    ]
    if p["miterlimit"] is not None:
        attrs.append(f'  stroke-miterlimit="{_fmt(p["miterlimit"])}"')
    attrs.append(">")
    return attrs


# ---------------------------------------------------------------------------
# 生成 / 派生
# ---------------------------------------------------------------------------
def render_base(name: str) -> str:
    """② 生成 generic 缺失名 SVG（模块级图元常量）。"""
    lines = list(_PRIMITIVE_HEADER) + _root_attrs("generic")
    lines.append(f"  {MISSING_GENERIC_PRIMITIVES[name]}")
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def derive(text: str, style: str) -> str:
    """基准 SVG 文本 → 指定风格 SVG 文本（图元逐字保留，仅描边属性 + 等比缩放）。"""
    if style not in STYLE_PARAMS:
        raise ValueError(f"未知风格：{style!r}")
    comments, inner = _split_svg(text)
    body = [
        f"  {ln}" if ln.strip() else ln
        for ln in inner.strip("\n").splitlines()
    ]
    transform = (
        f"translate({_fmt(CENTER)} {_fmt(CENTER)})"
        f" scale({_fmt(STYLE_PARAMS[style]['scale'])})"
        f" translate(-{_fmt(CENTER)} -{_fmt(CENTER)})"
    )
    out = list(comments) + [_derived_comment(style)] + _root_attrs(style)
    out.append(f'  <g transform="{transform}">')
    out.extend(body)
    out.append("  </g>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


def _assert_semantics_preserved(base_text: str, out_text: str) -> None:
    """自检：派生件图元行（除新增 <g> 包裹）须与基准逐字一致。"""
    base_el = _elements(base_text)
    out_el = [e for e in _elements(out_text) if e != "</g>" and not e.startswith("<g ")]
    if base_el != out_el:
        raise ValueError("图元语义被改动：" f"{base_el!r} != {out_el!r}")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def build(root: Path) -> list[Path]:
    """产出基准补齐件 + 三套派生件；返回写入清单（枚举排序稳定）。"""
    base_dir = root / BASE_STYLE
    written: list[Path] = []
    for name in sorted(MISSING_GENERIC_PRIMITIVES):
        path = base_dir / f"{name}.svg"
        _write(path, render_base(name))
        written.append(path)
    bases = sorted(base_dir.glob("*.svg"))
    for style in DERIVED_STYLES:
        for base_path in bases:
            base_text = base_path.read_text(encoding="utf-8")
            out_text = derive(base_text, style)
            _assert_semantics_preserved(base_text, out_text)
            path = root / style / base_path.name
            _write(path, out_text)
            written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="T-1001 三风格图标派生（确定性 / 幂等 / 离线）")
    parser.add_argument("--assets", default=None,
                        help="图标资源根目录（缺省=仓库 src/acouscope/resources/icons）")
    parser.add_argument("--quiet", action="store_true", help="只输出汇总行")
    args = parser.parse_args(argv)

    root = Path(args.assets).resolve() if args.assets else ICON_ROOT
    written = build(root)
    if not args.quiet:
        print(f"icon root = {root}")
        print(f"styles    = {BASE_STYLE}(base) + {', '.join(DERIVED_STYLES)}")
    print(f"written   = {len(written)} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
