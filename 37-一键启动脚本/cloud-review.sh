#!/bin/bash
# cloud-review.sh — 云端评审日检（D2 运行健康 / D3 日志质量 / D6 风控行为）
# 原则：全部只读查询，FAIL-OPEN（单条命令失败标注"未采集"，不阻塞整体输出）
# 用法:
#   ./cloud-review.sh            执行日检，打印摘要并归档报告
#   ./cloud-review.sh --no-save  只打印，不归档
# 产出: .trae/documents/review-reports/YYYY-MM-DD-daily.md
set -uo pipefail
REMOTE="dreambuddy-remote"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPORT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)/.trae/documents/review-reports"
TODAY="$(date +%F)"
REPORT="$REPORT_DIR/$TODAY-daily.md"

# 日检覆盖的关键 unit（含风控线）
KEY_UNITS="yijing-polling-trader v15-api dreambuddy-frontend datacenter-scheduler dreamos-scheduler hermes-gateway dreambuddy-continual-training trailing-stop-runner"

collect() {
ssh -o ConnectTimeout=10 -o BatchMode=yes "$REMOTE" "bash -s" <<'EOF' 2>&1
set -uo pipefail
KEY_UNITS="yijing-polling-trader v15-api dreambuddy-frontend datacenter-scheduler dreamos-scheduler hermes-gateway dreambuddy-continual-training trailing-stop-runner"

echo "## D2 运行健康"
echo '```'
echo "-- failed units --"
systemctl list-units --failed --no-pager --no-legend 2>/dev/null || echo "(未采集)"
echo ""
echo "-- 关键服务状态 --"
for u in $KEY_UNITS; do
  st=$(systemctl is-active "$u" 2>/dev/null || echo "unknown")
  printf "%-38s %s\n" "$u" "$st"
done
echo ""
echo "-- timer 最近触发 --"
systemctl list-timers --all --no-pager 2>/dev/null | grep -Ei "dreambuddy|yijing|v15|datacenter|dreamos|continual|trailing|dal-backup" | head -20 || echo "(未采集)"
echo ""
echo "-- 监听端口数 --"
ss -tln 2>/dev/null | tail -n +2 | wc -l || echo "(未采集)"
echo '```'

# 日志文件路径解析：systemctl show 只返回 "append" 不含路径，必须读 unit 原文
logpath() { systemctl cat "$1" --no-pager 2>/dev/null | grep '^StandardOutput=append:' | tail -1 | cut -d: -f2-; }
logerr()  { systemctl cat "$1" --no-pager 2>/dev/null | grep '^StandardError=append:'  | tail -1 | cut -d: -f2-; }

echo "## D3 日志质量（近 24h）"
echo '```'
echo "-- 日志活跃度（单位: 路由按 StandardOutput 自动解析）--"
printf "%-32s %-10s %-10s %s\n" UNIT SIZE LAST_WRITE ERR
for u in $KEY_UNITS; do
  p=$(logpath "$u")
  if [ -n "$p" ] && [ -r "$p" ]; then
    sz=$(stat -c %s "$p" 2>/dev/null || echo 0)
    mt=$(stat -c %Y "$p" 2>/dev/null || echo 0)
    age=$(( ( $(date +%s) - mt ) / 3600 ))
    ec=$(tail -n 1000 "$p" 2>/dev/null | grep -icE "error|exception|traceback|failed" || true)
    printf "%-32s %-10s %-10s %s\n" "$u" "${sz}B" "${age}h前" "err=${ec:-0}(近1000行)"
  else
    jl=$(journalctl -u "$u" -n 1 -o short-iso --no-pager 2>/dev/null | awk '{print $1}')
    printf "%-32s %-10s %-10s %s\n" "$u" "(journal)" "${jl:-(无)}" "-"
  fi
done
echo ""
echo "-- 判读规则 --"
echo "1) append 路由的 unit：journal 停更属正常，以文件 mtime 为准"
echo "2) SIZE=0B 且 LAST_WRITE 超过 24h → 疑似真静默（服务无输出/日志未初始化）"
echo "3) 显示 (journal) → 该 unit 日志走 journald，或文件无读权限"
echo '```'

echo "## D6 风控行为（近 24h）"
echo '```'
trail_log="$(logpath trailing-stop-runner)"
yijing_log="$(logpath yijing-polling-trader)"
trail_err="$(logerr trailing-stop-runner)"

echo "-- trailing-stop-runner 触发记录（日志文件尾部）--"
for f in "$trail_log" "$trail_err"; do
  [ -n "$f" ] && [ -r "$f" ] && tail -n 3000 "$f" 2>/dev/null | grep -iE "stop|trigger|平仓|止损|breakeven" | tail -5 | cut -c1-160
done
echo "(-- 空表示近3000行无触发; 日志: ${trail_log:-无}, ${trail_err:-无} --)"
echo ""
echo "-- 实盘交易动作（buy/sell/下单，日志文件尾部）--"
if [ -n "$yijing_log" ] && [ -r "$yijing_log" ]; then
  tail -n 3000 "$yijing_log" 2>/dev/null | grep -iE "buy|sell|order|下单|成交" | tail -10 | cut -c1-160 || echo "(近3000行无交易动作)"
else
  echo "(日志不可读: ${yijing_log:-无 append 路由})"
fi
echo ""
echo "-- 熔断/风控拦截 --"
{ journalctl --since "24 hours ago" --no-pager 2>/dev/null | grep -iE "熔断|circuit|breaker|风控|alpha_decay" | tail -5 | cut -c1-160
  [ -n "$yijing_log" ] && [ -r "$yijing_log" ] && tail -n 3000 "$yijing_log" 2>/dev/null | grep -iE "熔断|circuit|breaker|风控|alpha_decay" | tail -5 | cut -c1-160
} | tail -10 || true
echo "(-- 空表示无记录 --)"
echo '```'
EOF
}

BODY="$(collect)"

REPORT_CONTENT="# 云端评审日报 — $TODAY

> 维度: D2 运行健康 / D3 日志质量 / D6 风控行为 | 采集: cloud-review.sh（只读）

$BODY

---
## 问题清单（评审人填写）

| 级别 | 维度 | 问题 | 处置 |
|---|---|---|---|
| - | - | （无异常则留空） | - |"

echo "$REPORT_CONTENT"

if [ "${1:-}" != "--no-save" ]; then
  mkdir -p "$REPORT_DIR"
  # 同日重复执行时保留上一版（含人工填写的问题清单）
  [ -f "$REPORT" ] && cp "$REPORT" "$REPORT_DIR/$TODAY-daily.prev.md" 2>/dev/null
  echo "$REPORT_CONTENT" > "$REPORT"
  echo ""
  echo ">> 报告已归档: $REPORT"
fi
