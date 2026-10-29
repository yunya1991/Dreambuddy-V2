#!/bin/bash
# cloud-logs.sh — 云端日志速查（只读，无副作用）
# 用法:
#   ./cloud-logs.sh list                列出可查服务
#   ./cloud-logs.sh <服务名> [行数]      查看最近日志（默认 100 行）
#   ./cloud-logs.sh -f <服务名>          实时跟踪（Ctrl+C 退出）
#   ./cloud-logs.sh errors [行数]        汇总关键服务最近错误（默认各 20 行）
# 示例:
#   ./cloud-logs.sh polling 200         看轮询交易最近 200 行
#   ./cloud-logs.sh -f frontend         实时跟踪主前端
set -uo pipefail
REMOTE="dreambuddy-remote"

# 友好名 → systemd unit（case 实现，兼容 macOS 自带 bash 3.2）
resolve() {
  case "$1" in
    polling|trader) echo yijing-polling-trader ;;
    v15) echo v15-api ;;
    capital) echo v15-capital-api ;;
    yijing) echo yijing-data-server ;;
    frontend) echo dreambuddy-frontend ;;
    hub) echo product-hub ;;
    fundamental) echo fundamental ;;
    m25) echo m25-strategy-generation ;;
    m26) echo m26-strategy-lib ;;
    m27) echo m27-governance ;;
    m28) echo m28-signal-trigger ;;
    dreamos) echo dreamos-scheduler ;;
    evaluator) echo dreamos-dynamic-evaluator ;;
    datacenter) echo datacenter-scheduler ;;
    cognitive) echo cognitive-daemon ;;
    etl) echo etl-worker ;;
    hermes) echo hermes-gateway ;;
    poller) echo group-poller ;;
    dashboard) echo hermes-dashboard ;;
    scanner) echo signal-scanner ;;
    training) echo dreambuddy-continual-training ;;
    trailing) echo trailing-stop-runner ;;
    *) echo "$1" ;;
  esac
}

ALIASES="polling v15 capital yijing frontend hub fundamental m25 m26 m27 m28 dreamos evaluator datacenter cognitive etl hermes poller dashboard scanner training trailing"

# 关键服务（errors 汇总用）
KEY_UNITS=(yijing-polling-trader v15-api dreambuddy-frontend datacenter-scheduler dreamos-scheduler hermes-gateway)

usage() {
  sed -n '2,11p' "$0"
  echo ""
  echo "可查服务别名:"
  for k in $ALIASES; do printf "  %-12s → %s\n" "$k" "$(resolve "$k")"; done
  echo "  (也可直接传完整 unit 名)"
  exit 0
}

[ $# -eq 0 ] && usage

case "${1:-}" in
  list|-h|--help) usage ;;
  -f)
    [ -z "${2:-}" ] && usage
    UNIT="$(resolve "$2")"
    echo ">> 实时跟踪 $UNIT (Ctrl+C 退出)"
    ssh -t "$REMOTE" "journalctl -u $UNIT -f --no-hostname -o short-iso"
    ;;
  errors)
    N="${2:-20}"
    ssh "$REMOTE" "bash -s" <<EOF
for u in ${KEY_UNITS[*]}; do
  echo "===== \$u (最近 $N 条 warn/error) ====="
  journalctl -u "\$u" -n 500 --no-pager -o short-iso --no-hostname 2>/dev/null \
    | grep -iE "error|warn|exception|traceback|failed" | tail -"$N" || echo "(无)"
  echo ""
done
EOF
    ;;
  *)
    UNIT="$(resolve "$1")"
    N="${2:-100}"
    ssh "$REMOTE" "journalctl -u $UNIT -n $N --no-pager --no-hostname -o short-iso"
    ;;
esac
