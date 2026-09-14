#!/usr/bin/env bash
# selftest.sh —— run_bg.sh 一键自测（6 用例）
# 时序机制化：等待 done 用轮询（上限 20s），非固定 sleep（任何负载下稳定）。断言本身不变。
set -uo pipefail
S="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$S/.." && pwd)"
RUNDIR="$ROOT/.runs"
PASS=0; FAIL=0
ok(){ echo "PASS: $1"; PASS=$((PASS+1)); }
bad(){ echo "FAIL: $1"; FAIL=$((FAIL+1)); }

# wait_done <任务名> [秒]: 从 .runs/<任务名>.latest 推导 rid → 轮询 <任务名>-<RID>.done 出现；等不到返回 1
wait_done(){
  local task="$1" secs="${2:-20}" rid donef i
  local latest="$RUNDIR/$task.latest"
  [ -f "$latest" ] || return 1
  rid="$(cat "$latest")"
  donef="$RUNDIR/$task-$rid.done"
  for i in $(seq 1 "$secs"); do
    [ -f "$donef" ] && return 0
    sleep 1
  done
  return 1
}

# 1) 正常跑通: STARTED → FINISHED/EXIT=0  （独立任务名 smoke1，避免与用例2/3 共享 smoke2 竞态）
"$S/run_bg.sh" smoke1 bash -c 'sleep 3; echo ok' >/dev/null || bad "用例1启动"
wait_done smoke1 20
"$S/debug_status.sh" smoke1 | grep "STATUS=FINISHED" >/dev/null && "$S/debug_status.sh" smoke1 | grep "EXIT=0" >/dev/null \
  && ok "用例1 正常跑通" || bad "用例1 正常跑通"

# 2) 防并发: 第二次启动必须被拒（exit 4）
"$S/run_bg.sh" smoke2 sleep 8 >/dev/null
"$S/run_bg.sh" smoke2 sleep 1 >/dev/null 2>&1 && bad "用例2 防并发" || ok "用例2 防并发"
"$S/run_bg.sh" stop smoke2 >/dev/null

# 3) stop 后 done 标记为 EXIT=killed
wait_done smoke2 20
"$S/debug_status.sh" smoke2 | grep "EXIT=killed" >/dev/null && ok "用例3 stop标记" || bad "用例3 stop标记"

# 4) 预检: 不存在的命令必须 exit 3
"$S/run_bg.sh" t0test /no/such/cmd >/dev/null 2>&1 && bad "用例4 预检" || ok "用例4 预检"

# 5) 环境兜底: QT_QPA_PLATFORM 默认 offscreen
"$S/run_bg.sh" envtest bash -c 'echo $QT_QPA_PLATFORM' >/dev/null
wait_done envtest 20
"$S/debug_status.sh" envtest | grep "offscreen" >/dev/null && ok "用例5 环境兜底" || bad "用例5 环境兜底"

# 6) DURATION: done 文件含 DURATION 且无空值
"$S/debug_status.sh" envtest | grep -E "^DURATION=[0-9]+s$" >/dev/null && ok "用例6 DURATION" || bad "用例6 DURATION"

echo "===== selftest: $PASS passed, $FAIL failed ====="
[ "$FAIL" -eq 0 ]
