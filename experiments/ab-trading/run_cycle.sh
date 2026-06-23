#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# AB实验 单次触发脚本
# 同时运行 Agent A 和 Agent B，输出带时间戳的日志
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/config/.env"
LOG_DIR="$SCRIPT_DIR/logs/sessions"
TIMESTAMP=$(date -u +"%Y%m%d_%H%M%S")

# 加载环境变量
if [[ ! -f "$ENV_FILE" ]]; then
    echo "[ERROR] $ENV_FILE 不存在，请先填写 API keys"
    exit 1
fi
set -a; source "$ENV_FILE"; set +a

# 检查 keys 是否已填写
if [[ -z "$AGENT_A_OKX_KEY" || -z "$AGENT_B_OKX_KEY" ]]; then
    echo "[ERROR] .env 中 API keys 未填写，请先配置"
    exit 1
fi

mkdir -p "$LOG_DIR"

echo "============================================================"
echo "  AB实验 触发时间: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "  AUTO_EXECUTE=${AUTO_EXECUTE:-false}"
echo "============================================================"

# 并行运行两个 Agent
python3 "$SCRIPT_DIR/agents/agent_a_runner.py" \
    > "$LOG_DIR/${TIMESTAMP}_agent_a.log" 2>&1 &
PID_A=$!

python3 "$SCRIPT_DIR/agents/agent_b_runner.py" \
    > "$LOG_DIR/${TIMESTAMP}_agent_b.log" 2>&1 &
PID_B=$!

# 等待两个进程完成
wait $PID_A && echo "[✓] Agent A 完成" || echo "[✗] Agent A 异常，查看: $LOG_DIR/${TIMESTAMP}_agent_a.log"
wait $PID_B && echo "[✓] Agent B 完成" || echo "[✗] Agent B 异常，查看: $LOG_DIR/${TIMESTAMP}_agent_b.log"

# 打印本轮摘要
echo ""
echo "── Agent A 决策 ──"
tail -5 "$LOG_DIR/${TIMESTAMP}_agent_a.log" 2>/dev/null

echo ""
echo "── Agent B 决策 ──"
tail -5 "$LOG_DIR/${TIMESTAMP}_agent_b.log" 2>/dev/null

# 输出比分卡
echo ""
echo "── 当前记分卡 ──"
python3 "$SCRIPT_DIR/scoring/scorecard.py" 2>/dev/null || true

echo ""
echo "============================================================"
echo "  本轮结束: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "============================================================"
