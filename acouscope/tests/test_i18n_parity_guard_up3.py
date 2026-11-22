# SPDX-License-Identifier: GPL-3.0-only
"""i18n 五语齐备守卫（S-5b UP3）：缺口只准减不准增。

三条断言：
  ① en_US/zh_CN/zh_TW gap 必须为 0（真闸：三语已全齐，任何新键漏译立刻红）
  ② ko_KR/ja_JP gap 不得大于基线值（单调闸：只准减不准增）
  ③ 条目总数 >= 基线；若 gap < 基线则 print 提示下调（提示不失败）
"""
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
I18N_PATH = REPO_ROOT / "acouscope" / "src" / "acouscope" / "i18n" / "__init__.py"
BASELINE_PATH = REPO_ROOT / ".pi" / "knowledge" / "IM45_parity_baseline.json"

LOCALES = ("en_US", "zh_CN", "zh_TW", "ko_KR", "ja_JP")
FULL_LANGS = ("en_US", "zh_CN", "zh_TW")
PARTIAL_LANGS = ("ko_KR", "ja_JP")


def _scan(path):
    """按大括号深度扫描 i18n 源，返回 {"entries": N, "gap": {...}, "covered": {...}}。"""
    src = Path(path).read_text(encoding="utf-8")
    pat = re.compile(r'"([a-z][a-z0-9_]*(?:\.[a-zA-Z0-9_]+)+)"\s*:\s*\{')
    entries = []
    for m in pat.finditer(src):
        depth = 0
        for j in range(m.end() - 1, len(src)):
            if src[j] == '{':
                depth += 1
            elif src[j] == '}':
                depth -= 1
                if depth == 0:
                    entries.append((m.group(1), src[m.end() - 1:j + 1]))
                    break
    n = len(entries)
    result = {"entries": n, "gap": {}, "covered": {}}
    for loc in LOCALES:
        covered = sum(1 for k, b in entries if '"%s"' % loc in b)
        result["covered"][loc] = covered
        result["gap"][loc] = n - covered
    return result


@pytest.fixture(scope="module")
def scan_result():
    return _scan(I18N_PATH)


@pytest.fixture(scope="module")
def baseline():
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def test_full_languages_gap_zero(scan_result):
    """① 真闸：en_US/zh_CN/zh_TW 的 gap 必须为 0。"""
    for loc in FULL_LANGS:
        assert scan_result["gap"][loc] == 0, (
            f"{loc} gap={scan_result['gap'][loc]}（应为 0）"
        )


def test_partial_languages_monotone(scan_result, baseline):
    """② 单调闸：ko_KR/ja_JP 的 gap 不得大于基线值（只准减不准增）。"""
    for loc in PARTIAL_LANGS:
        actual = scan_result["gap"][loc]
        allowed = baseline["gap"][loc]
        assert actual <= allowed, (
            f"{loc} gap={actual} > 基线 {allowed}（缺口增大，守卫拦截）"
        )


def test_entries_count_and_hint(scan_result, baseline):
    """③ 条目总数 >= 基线；若 gap 收窄则 print 提示（提示不失败）。"""
    assert scan_result["entries"] >= baseline["entries"], (
        f"条目总数 {scan_result['entries']} < 基线 {baseline['entries']}（条目被删？）"
    )
    for loc in PARTIAL_LANGS:
        actual = scan_result["gap"][loc]
        allowed = baseline["gap"][loc]
        if actual < allowed:
            print(f"★ {loc} 缺口已收窄至 {actual}，请把 IM45_parity_baseline.json 下调")
