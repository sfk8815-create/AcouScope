#!/usr/bin/env bash
# 逐文件独立进程跑全部测试（项目口径），并给出可复算的汇总与对账。
#
# 为什么不用一条 `pytest tests`：单进程跑到底会在 Qt 用例处原生崩溃
# （faulthandler dump），故每个测试文件独立进程、共用同一个 --basetemp 前缀。
#
# 用法：
#   scripts/run_tests_per_file.sh                 # 输出到 /tmp/acouscope_per_file_<时间戳>
#   scripts/run_tests_per_file.sh /tmp/my_run     # 指定日志目录
#
# 输出：
#   <dir>/run.log      每文件一行：<文件> :: <pytest 摘要>
#   <dir>/collect.log  每文件一行：<文件> :: <收集数>
#   <dir>/summary.txt  汇总（passed/failed/skipped/error、失败清单、对账）
#
# 对账口径：逐文件实跑合计（passed+failed+skipped+error）应等于逐文件收集合计；
# 它与 `pytest --collect-only tests` 的差 = tests/conftest.py 默认隔离的诊断文件
# （test_cb005_diag_*.py，需 CB005_DIAG=1 才被目录收集，按路径显式跑仍收集）。
#
# 退出码：0 = 无 failed/error；1 = 有失败（明细见 run.log）。
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"          # acouscope/（pytest rootdir）
PY="$ROOT/.venv/bin/python"
LOG_DIR="${1:-/tmp/acouscope_per_file_$(date +%Y%m%d_%H%M%S)}"

cd "$ROOT" || exit 2
mkdir -p "$LOG_DIR"
export TERM=xterm-256color LC_ALL=C.UTF-8 LANG=C.UTF-8 QT_QPA_PLATFORM=offscreen

: >"$LOG_DIR/run.log"
: >"$LOG_DIR/collect.log"

for f in tests/test_*.py; do
  out=$("$PY" -m pytest -q "$f" --basetemp="$LOG_DIR/bt" 2>&1 | tail -3)
  last=$(echo "$out" | grep -E "passed|failed|error|no tests" | tail -1)
  echo "$f :: ${last:-NO_SUMMARY}" >>"$LOG_DIR/run.log"
  cnt=$("$PY" -m pytest -q --collect-only "$f" 2>/dev/null | grep -c "::")
  echo "$f :: $cnt" >>"$LOG_DIR/collect.log"
done

{
  echo "# 逐文件全量（独立进程）"
  echo "日志目录：$LOG_DIR"
  echo "测试文件数：$(grep -c '::' "$LOG_DIR/run.log")"
  echo
  echo "## 实跑合计"
  grep -oE "[0-9]+ passed|[0-9]+ failed|[0-9]+ skipped|[0-9]+ error" "$LOG_DIR/run.log" \
    | awk '{a[$2]+=$1} END {for (k in a) printf "%-8s %d\n", k, a[k]}'
  echo
  echo "## 逐文件收集合计"
  awk -F':: ' '{s+=$2} END {printf "%d（%d 个文件）\n", s, NR}' "$LOG_DIR/collect.log"
  echo
  echo "## 目录收集（对照）"
  "$PY" -m pytest -q --collect-only tests 2>/dev/null | tail -1
  echo
  echo "## 失败清单"
  grep "failed" "$LOG_DIR/run.log" || echo "（无）"
} >"$LOG_DIR/summary.txt"

cat "$LOG_DIR/summary.txt"
grep -q "failed" "$LOG_DIR/run.log" && exit 1
exit 0
