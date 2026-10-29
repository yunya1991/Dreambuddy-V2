#!/usr/bin/env bash
# ============================================================================
# Phase 11b: 云端实盘安全覆盖（凭据全量上云后的资金安全边界）
#
# 原则：凭据到位 ≠ 云端实盘。所有实盘下单路径强制 dry-run/停止，
#       直到用户明确指示"云端切实盘"。
#
# 依据：
#   - okx_simulated.py:65 优先读 os.environ["OKX_DRY_RUN"] → 单元环境变量可覆盖 .env 的 false
#   - 11-易经推理系统/.env:35 OKX_DRY_RUN=false（本地实盘中，云端不得双实盘）
#
# 用法（云端执行，或本地 ssh 执行）：
#   ./11-cloud-safety-overrides.sh apply
#   ./11-cloud-safety-overrides.sh revert   # 云端切实盘时人工评估后执行
# ============================================================================
set -euo pipefail
ACTION="${1:-apply}"
UNITS_DIR="/etc/systemd/system"

apply_overrides() {
  # 1) yijing-polling-trader：OKX dry-run（最高优先级，防双实盘）
  mkdir -p "$UNITS_DIR/yijing-polling-trader.service.d"
  cat > "$UNITS_DIR/yijing-polling-trader.service.d/safety-override.conf" <<'EOF'
[Service]
Environment="OKX_DRY_RUN=true"
EOF

  # 2) dreamos-scheduler：fail-open 禁实盘（代码若不读该变量则无副作用）
  mkdir -p "$UNITS_DIR/dreamos-scheduler.service.d"
  cat > "$UNITS_DIR/dreamos-scheduler.service.d/safety-override.conf" <<'EOF'
[Service]
Environment="AUTO_EXECUTE=false"
EOF

  # 3) trailing-stop-runner：停止（与本地对同一交易所账户双跑移动止损有竞态）
  systemctl stop trailing-stop-runner.service 2>/dev/null || true
  systemctl disable trailing-stop-runner.service 2>/dev/null || true

  systemctl daemon-reload
  systemctl restart yijing-polling-trader.service
  echo "[safety] 覆盖已应用: OKX_DRY_RUN=true / dreamos AUTO_EXECUTE=false / trailing-stop-runner 已停止"
}

revert_overrides() {
  rm -f "$UNITS_DIR/yijing-polling-trader.service.d/safety-override.conf"
  rm -f "$UNITS_DIR/dreamos-scheduler.service.d/safety-override.conf"
  systemctl daemon-reload
  systemctl restart yijing-polling-trader.service
  systemctl enable --now trailing-stop-runner.service 2>/dev/null || true
  echo "[safety] 覆盖已撤除 —— 云端进入实盘态（请确认本地实盘生产者已停止！）"
}

case "$ACTION" in
  apply)  apply_overrides ;;
  revert) revert_overrides ;;
  *) echo "用法: $0 [apply|revert]" >&2; exit 1 ;;
esac
