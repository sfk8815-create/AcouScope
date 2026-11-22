# SPDX-License-Identifier: GPL-3.0-only
"""平台 README 五语新能力守卫（PI-P5-B3-01k）：防漂移。

四类断言（五个 README 一律同套，任一语言漏写即红）：

  ① 五个文件都存在，且都含五组关键标记 —— 模块名与标识符串一律保持源码原样，
     不因语言改写法（``paper_A``／``calibration_report``／``profile_field_table``
     ／``fit_tonic_from_audio``／``degree_rows_both``／``300 dpi`` …）。
  ② 都不得出现夸大／伪标表述（防漂移正则，至少覆盖 accuracy guaranteed、
     精度已获保证、已获保证）。
  ③ 新增段落的标题行存在（各语言各自表述），且**既有顶层章节标题一个不少**
     —— 基线 ``## `` 集合写在常量里做子集断言（只增不改）。
  ④ 平台文档不认具体录音：四例人名与锚值零出现。
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
README_DIR = REPO_ROOT / "acouscope"

#: 五语文件名（locale → 文件名）
READMES = {
    "en_US": "README.md",
    "zh_CN": "README.zh.md",
    "zh_TW": "README.zh-TW.md",
    "ko_KR": "README.ko.md",
    "ja_JP": "README.ja.md",
}

# ---------------------------------------------------------------------------
# ① 关键标记：五组事实的最小可机检面（标识符不译，逐字比对）
# ---------------------------------------------------------------------------
REQUIRED_MARKERS = (
    # 论文图导出（三预设）
    "visualization.figures",
    "paper_A",
    "paper_B",
    "paper_C",
    "segment_curve",
    "type_oscillation",
    "reference_comparison",
    "300 dpi",
    "window_start_s",
    # 精度标定导出
    "calibration_report",
    "pending",
    "measured",
    "chain_only",
    "analysis_params_snapshot",
    # 元数据字段表
    "profile_field_table",
    "check_profile_field_table",
    "DAT63",
    "GBT31219.4",
    "IMDI",
    "custom",
    "ref_mode",
    # 主音两阶段与双口径
    "fit_tonic_from_audio",
    "degree_rows_both",
    "isfinite(f0)&f0>0",
    'stage="joint"',
    # 逐文件跑测试
    "scripts/run_tests_per_file.sh",
)

# ---------------------------------------------------------------------------
# ② 禁用表述（夸大／伪标）：命中即红
# ---------------------------------------------------------------------------
FORBIDDEN_PATTERNS = (
    re.compile(r"accuracy\s+guaranteed", re.IGNORECASE),
    re.compile(r"精度已获保证"),
    re.compile(r"已获保证"),
)

# ---------------------------------------------------------------------------
# ③ 章节基线：改动前各文件 ``## `` 顶层标题集合（只增不改 ⇒ 必须是子集）
# ---------------------------------------------------------------------------
BASELINE_H2 = {
    "en_US": (
        "Features", "Modules", "Install", "Requirements", "Project structure",
        "Tech stack", "Roadmap", "Acknowledgments", "License",
    ),
    "zh_CN": (
        "核心特性", "功能模块", "安装", "环境要求", "项目结构",
        "技术栈", "路线图", "致谢", "许可证",
    ),
    "zh_TW": (
        "核心特性", "功能模組", "安裝", "環境需求", "專案結構",
        "技術棧", "路線圖", "致謝", "授權條款",
    ),
    "ko_KR": (
        "주요 기능", "기능 모듈", "설치", "요구 사항", "프로젝트 구조",
        "기술 스택", "로드맵", "감사의 글", "라이선스",
    ),
    "ja_JP": (
        "主な機能", "機能モジュール", "インストール", "動作環境", "プロジェクト構成",
        "技術スタック", "ロードマップ", "謝辞", "ライセンス",
    ),
}

#: 本单新增段落的标题行（各语言各自表述，语义一致）
ADDED_HEADINGS = {
    "en_US": (
        "### Publication figure export (presets)",
        "### Reference-tone calibration export",
        "### Metadata field table",
        "### Tonic fitting: two stages and two reference modes",
        "#### Running tests per file",
    ),
    "zh_CN": (
        "### 论文图导出（三预设）",
        "### 精度标定导出",
        "### 元数据字段表",
        "### 主音两阶段与双口径",
        "#### 逐文件跑测试",
    ),
    "zh_TW": (
        "### 論文圖匯出（三預設）",
        "### 精度標定匯出",
        "### 中繼資料欄位表",
        "### 主音兩階段與雙口徑",
        "#### 逐檔案跑測試",
    ),
    "ko_KR": (
        "### 논문 그림 내보내기(세 프리셋)",
        "### 정밀 교정 내보내기",
        "### 메타데이터 필드 표",
        "### 주음 추정: 2단계와 두 기준",
        "#### 파일별 테스트 실행",
    ),
    "ja_JP": (
        "### 論文図の書き出し（3 プリセット）",
        "### 精度キャリブレーションの書き出し",
        "### メタデータ項目表",
        "### 主音推定: 二段階と二つの基準",
        "#### ファイル単位でのテスト実行",
    ),
}

# ---------------------------------------------------------------------------
# ④ 平台文档不认具体录音：四例人名／锚值零出现
# ---------------------------------------------------------------------------
FORBIDDEN_FACTS = (
    "溥雪斋",
    "管平湖",
    "闵惠芬",
    "阿炳",
    re.compile(r"90\.45"),
)


def _read(locale: str) -> str:
    return (README_DIR / READMES[locale]).read_text(encoding="utf-8")


@pytest.mark.parametrize("locale", sorted(READMES))
def test_readme_exists(locale):
    """① 五个 README 文件均存在且非空。"""
    path = README_DIR / READMES[locale]
    assert path.is_file(), f"{locale} README 不存在：{path}"
    assert path.stat().st_size > 0, f"{locale} README 为空：{path}"


@pytest.mark.parametrize("locale", sorted(READMES))
@pytest.mark.parametrize("marker", REQUIRED_MARKERS)
def test_required_marker_present(locale, marker):
    """① 每个 README 都含全部关键标记（标识符不译，逐字比对）。"""
    text = _read(locale)
    assert marker in text, f"{locale}（{READMES[locale]}）缺标记：{marker!r}"


@pytest.mark.parametrize("locale", sorted(READMES))
@pytest.mark.parametrize("pattern", FORBIDDEN_PATTERNS)
def test_no_overclaim_wording(locale, pattern):
    """② 不得出现夸大／伪标表述。"""
    text = _read(locale)
    hit = pattern.search(text)
    assert hit is None, (
        f"{locale}（{READMES[locale]}）出现禁用表述：{pattern.pattern!r} → {hit.group(0)!r}"
    )


@pytest.mark.parametrize("locale", sorted(READMES))
def test_baseline_h2_headings_still_present(locale):
    """③ 既有顶层（``## ``）章节标题一个不少 —— 基线集合是现行集合的子集。"""
    text = _read(locale)
    current = set(re.findall(r"^##(?!#)\s*(.*)$", text, re.MULTILINE))
    missing = [h for h in BASELINE_H2[locale] if h not in current]
    assert not missing, f"{locale}（{READMES[locale]}）顶层章节标题缺失：{missing}"


@pytest.mark.parametrize("locale", sorted(READMES))
def test_added_headings_all_present(locale):
    """③ 逐个语言核对：本语言应新增的 5 条标题一条不少。"""
    text = _read(locale)
    missing = [h for h in ADDED_HEADINGS[locale] if h not in text]
    assert not missing, f"{locale}（{READMES[locale]}）新增段落标题缺失：{missing}"


@pytest.mark.parametrize("locale", sorted(READMES))
@pytest.mark.parametrize("fact", FORBIDDEN_FACTS)
def test_no_example_recording_facts(locale, fact):
    """④ 平台文档不认具体录音：四例人名与锚值零出现。"""
    text = _read(locale)
    if isinstance(fact, re.Pattern):
        hit = fact.search(text)
        assert hit is None, (
            f"{locale}（{READMES[locale]}）出现具体录音锚值：{hit.group(0)!r}"
        )
    else:
        assert fact not in text, f"{locale}（{READMES[locale]}）出现具体录音人名：{fact!r}"
