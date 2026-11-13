#!/usr/bin/env bash
# 40 周期神经网络系统 · 日更流水线 runner（R0-1）
# 链序（按数据依赖）：
#   p1_real_cycle → p1_ma200_anchor → p2_asset_rotation → p2_divergence
#   → p3_sector_transmission → p3_fund_flow → p3_smart_money
#   → p3_stovall_breadth → p3_resonance_matrix → p3_cross_asset_matrix
#   → p3_washout_integration
#   → p3_meme_platform_monitor → p4_strategy_mapping
#   → factor_contradiction_priors → refresh_48_feedback（G13 网关刷新）
#   → consume_48_feedback（48→40 消费 + 双读校验）
# 任一步失败：告警接 15 并中止（下游会读到陈旧输入，宁停勿错）。
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_DIR="$(dirname "$SCRIPT_DIR")"
export DREAMBUDDY_ROOT="${DREAMBUDDY_ROOT:-$(dirname "$MODULE_DIR")}"
# G3：48→40 网关开关（2026-11-11 双读校验通过后启用；关闭设为 0 即回退直读）
export ENABLE_40_VIA_48="${ENABLE_40_VIA_48:-1}"

PYTHON_BIN="${PYTHON_BIN:-python3}"
LOG_DIR="$MODULE_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/daily_pipeline_$(date -u +%Y%m%d).log"

STEPS=(
  p1_real_cycle.py
  p1_ma200_anchor.py
  p2_asset_rotation.py
  p2_divergence.py
  p3_sector_transmission.py
  p3_fund_flow.py
  p3_smart_money.py
  p3_stovall_breadth.py
  p3_resonance_matrix.py
  p3_cross_asset_matrix.py
  p3_washout_integration.py
  p3_meme_platform_monitor.py
  p4_strategy_mapping.py
  factor_contradiction_priors.py
  refresh_48_feedback.py
  consume_48_feedback.py
)

alert_failure() {
  local step="$1" rc="$2"
  "$PYTHON_BIN" - "$step" "$rc" <<'PYEOF' >>"$LOG_FILE" 2>&1 || true
import os, sys
sys.path.insert(0, os.path.join(os.environ["DREAMBUDDY_ROOT"], "15-监控告警系统"))
try:
    from feishu_alert import send_alert
    send_alert(
        "trading", "critical",
        f"40 日更流水线失败: {sys.argv[1]} (exit={sys.argv[2]})",
        {"step": sys.argv[1], "exit_code": sys.argv[2]},
        system="40_cycle_pipeline",
    )
except Exception as e:
    print(f"[alert-failopen] feishu 告警发送失败: {e}")
PYEOF
}

echo "=== 40 daily pipeline start $(date -u +%FT%TZ) ===" | tee -a "$LOG_FILE"
for step in "${STEPS[@]}"; do
  echo "--- $step $(date -u +%FT%TZ) ---" >>"$LOG_FILE"
  "$PYTHON_BIN" "$SCRIPT_DIR/$step" >>"$LOG_FILE" 2>&1
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "!!! FAILED: $step (exit=$rc), abort pipeline $(date -u +%FT%TZ)" | tee -a "$LOG_FILE"
    alert_failure "$step" "$rc"
    exit $rc
  fi
  echo "ok: $step" >>"$LOG_FILE"
done
echo "=== 40 daily pipeline done $(date -u +%FT%TZ) ===" | tee -a "$LOG_FILE"
