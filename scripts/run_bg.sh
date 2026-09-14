#!/usr/bin/env bash
# run_bg.sh —— 真后台执行长命令（run-id / 原子 done / 环境兜底 / 防并发 / stop / 产物清理）
# 用法:
#   ./scripts/run_bg.sh <任务名> <命令...>       启动
#   ./scripts/run_bg.sh stop <任务名>            停止该任务最新一次运行
#   ./scripts/run_bg.sh tail <任务名>            查看最新日志（转调 debug_status.sh tail）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_DIR="$PROJECT_ROOT/.runs"
mkdir -p "$RUN_DIR"

TASK="${1:?用法: $0 <任务名> <命令...> | $0 stop <任务名> | $0 tail <任务名>}"
MODE="${2:-}"

if [ "$TASK" = "tail" ]; then
  exec "$SCRIPT_DIR/debug_status.sh" "${MODE:?用法: $0 tail <任务名>}" tail
fi

if [ "$TASK" = "stop" ]; then
  [ -n "$MODE" ] || { echo "用法: $0 stop <任务名>" >&2; exit 2; }
  LATEST="$RUN_DIR/$MODE.latest"
  [ -f "$LATEST" ] || { echo "NO_RUN: '$MODE' 无运行记录" >&2; exit 1; }
  RID="$(cat "$LATEST")"; META="$RUN_DIR/$MODE-$RID.meta"
  [ -f "$META" ] || { echo "NO_META: '$MODE' ($RID) 无元数据" >&2; exit 1; }
  PID="$(awk -F= '/^pid=/{print $2}' "$META" 2>/dev/null || true)"
  REALPID="$(awk -F= '/^realpid=/{print $2}' "$META" 2>/dev/null || true)"
  if [ -z "${REALPID}" ]; then REALPID=""; fi
  if [ -z "${PID}" ]; then PID=""; fi
  # 先杀真实子进程（本任务精确记录的 PID，严禁任何全局匹配式清理）
  if [ -n "${REALPID}" ] && kill -0 "${REALPID}" 2>/dev/null; then
    kill "${REALPID}" 2>/dev/null || true; sleep 2
    if kill -0 "${REALPID}" 2>/dev/null; then
      kill -9 "${REALPID}" 2>/dev/null || true
    fi
  else
    echo "CHILD_NOT_RUNNING rid=${RID} realpid=${REALPID}"
  fi
  # 再杀 wrapper
  if [ -n "${PID}" ] && kill -0 "${PID}" 2>/dev/null; then
    kill "${PID}" 2>/dev/null || true; sleep 1
    kill -9 "${PID}" 2>/dev/null || true
  fi
  # kill -0 复查：子进程必须已消失
  if [ -n "${REALPID}" ] && kill -0 "${REALPID}" 2>/dev/null; then
    echo "STOP_FAIL: rid=${RID} realpid=${REALPID} 仍存活" >&2
    printf 'EXIT=killed\n' > "$RUN_DIR/$MODE-$RID.done"
    exit 1
  fi
  echo "STOPPED rid=${RID} realpid=${REALPID}(child gone) pid=${PID}"
  printf 'EXIT=killed\n' > "$RUN_DIR/$MODE-$RID.done"
  exit 0
fi

[ $# -ge 2 ] || { echo "用法: $0 <任务名> <命令...>" >&2; exit 2; }
shift

# 预检：命令必须存在（防 EXIT=127）
if [ ! -x "$1" ] && ! command -v "$1" >/dev/null 2>&1; then
  echo "ERROR: 命令不存在或无执行权限: $1" >&2; exit 3
fi

# 防并发：同任务名上一次运行未结束则拒绝
LATEST="$RUN_DIR/$TASK.latest"
if [ -f "$LATEST" ]; then
  OLD_RID="$(cat "$LATEST")"
  OLD_PID="$(awk -F= '/^pid=/{print $2}' "$RUN_DIR/$TASK-$OLD_RID.meta" 2>/dev/null || true)"
  if [ ! -f "$RUN_DIR/$TASK-$OLD_RID.done" ] && [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "ERROR: '$TASK' (rid=$OLD_RID) 仍在运行，先执行 $0 stop $TASK" >&2
    exit 4
  fi
fi

# 环境兜底（已有值不覆盖）
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
export TERM="${TERM:-xterm-256color}"
export LC_ALL="${LC_ALL:-C.UTF-8}"

RID="$(date +%s)-$$"
LOG="$RUN_DIR/$TASK-$RID.log"; DONE="$RUN_DIR/$TASK-$RID.done"; META="$RUN_DIR/$TASK-$RID.meta"
REALPID_TMP="$RUN_DIR/$TASK-$RID.realpid"
printf '%s\n' "$RID" > "$LATEST.tmp.$$"; mv "$LATEST.tmp.$$" "$LATEST"

export LOG DONE REALPID_TMP

T0=$(date +%s)
nohup bash -c '
  exit_code=78
  "$@" > "$LOG" 2>&1 &
  real=$!
  printf "%s\n" "$real" > "$REALPID_TMP"
  wait "$real"
  exit_code=$?
  printf "EXIT=%d\nDURATION=%ds\n" "$exit_code" "$(( $(date +%s) - '"$T0"' ))" > "$DONE.tmp.$$"
  mv "$DONE.tmp.$$" "$DONE"
' _ "$@" > /dev/null 2>&1 &
BG_PID=$!

# 等待真实子 PID 落盘（stop 据此精确终止，先子后 wrapper）
real=""
for _i in 1 2 3 4 5; do
  if [ -f "$REALPID_TMP" ]; then real="$(cat "$REALPID_TMP")"; fi
  [ -n "$real" ] && break
  sleep 0.1
done
rm -f "$REALPID_TMP"

printf 'cmd=%s\npid=%s\nrealpid=%s\nstarted=%s\n' "$(printf '%q ' "$@")" "$BG_PID" "$real" "$(date '+%F %T')" > "$META"

# 产物保留上限：每任务名留最近 10 次（无匹配时 ls 非0 + pipefail + set -e 会使脚本提前退出，故加 || true 兼容首跑）
ls -t "$RUN_DIR/$TASK"-*.log 2>/dev/null | tail -n +11 | while read -r f; do
  b="${f%.log}"; rm -f "$b.log" "$b.done" "$b.meta"
done || true

echo "STARTED rid=$RID pid=$BG_PID"
echo "  log=$LOG"
echo "  done=$DONE"
echo "查询: $SCRIPT_DIR/debug_status.sh $TASK | 停止: $0 stop $TASK"
