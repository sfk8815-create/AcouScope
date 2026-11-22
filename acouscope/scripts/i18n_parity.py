# SPDX-License-Identifier: GPL-3.0-only
"""i18n 五语覆盖扫描器（S-5b 守卫数据源）。

按条目大括号深度扫描 acouscope/src/acouscope/i18n/__init__.py，
输出 entries 总数与每个 locale 的 covered / gap。
--json 输出机读 JSON 结果。
"""
import argparse
import json
import pathlib
import re

LOCALES = ("en_US", "zh_CN", "zh_TW", "ko_KR", "ja_JP")


def scan(path):
    """扫描 i18n 源文件，返回 {"entries": N, "gap": {...}, "covered": {...}}。"""
    src = pathlib.Path(path).read_text(encoding="utf-8")
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


def main():
    ap = argparse.ArgumentParser(description="i18n 五语覆盖扫描器")
    ap.add_argument("path", nargs="?",
                    default="acouscope/src/acouscope/i18n/__init__.py",
                    help="i18n 源文件路径（默认 acouscope/src/acouscope/i18n/__init__.py）")
    ap.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = ap.parse_args()
    r = scan(args.path)
    if args.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
    else:
        print("i18n entries: %d" % r["entries"])
        for loc in LOCALES:
            print("  %-6s covered=%d  gap=%d" % (loc, r["covered"][loc], r["gap"][loc]))


if __name__ == "__main__":
    main()