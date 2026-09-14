#!/usr/bin/env bash
# debug_status.sh —— 查询 run_bg.sh 启动的任务状态
# 用法: ./scripts/debug_status.sh <任务名> [rid|tail]
set -uo pipefail

TASK="${1:?用法: $0 <任务名> [rid|tail]}"
MODE="${2:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_DIR="$PROJECT_ROOT/.runs"

[ -f "$RUN_DIR/$TASK.latest" ] || { echo "NO_RUN: 从未用 run_bg.sh 启动过 '$TASK'"; exit 1; }

RID="$MODE"
if [ -z "$RID" ] || [ "$RID" = "tail" ]; then
  RID="$(cat "$RUN_DIR/$TASK.latest")"
fi

LOG="$RUN_DIR/$TASK-$RID.log"
DONE="$RUN_DIR/$TASK-$RID.done"

echo "=== run=$TASK rid=$RID ==="

if [ -f "$DONE" ]; then
  echo "STATUS=FINISHED"
  cat "$DONE"
  echo "--- 日志末尾 50 行 ---"
  tail -n 50 "$LOG" 2>/dev/null
  exit 0
fi

echo "STATUS=RUNNING_OR_DEAD (no done file)"
if pgrep -f "$TASK" > /dev/null 2>&1; then
  echo "--- 存活的相关进程 ---"
  pgrep -af "$TASK" | head -5
else
  echo "WARN: 未发现存活进程 —— 任务可能已崩溃且未写 done，建议重跑"
fi

if [ -f "$LOG" ]; then
  S1=$(stat -f%z "$LOG" 2>/dev/null || stat -c%s "$LOG" 2>/dev/null || echo 0)
  sleep 3
  S2=$(stat -f%z "$LOG" 2>/dev/null || stat -c%s "$LOG" 2>/dev/null || echo 0)
  echo "--- 日志 3 秒内变化: $S1 -> $S2 $([ "$S2" -gt "$S1" ] && echo '(增长中，继续等)' || echo '(无增长，可能卡住/已死)') ---"
  echo "--- 日志末尾 50 行 ---"
  tail -n 50 "$LOG"
else
  echo "WARN: 日志文件不存在: $LOG"
fi
