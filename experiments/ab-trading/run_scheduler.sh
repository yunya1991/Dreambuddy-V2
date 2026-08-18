#!/bin/bash
# 交易系统调度器 — 增强版（整合监控+自进化）
# 用法: nohup ./run_scheduler.sh > logs/scheduler.log 2>&1 &
# 特点: 退出TRAE账号后仍会继续运行（后台进程）

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$BASE_DIR/logs"
mkdir -p "$LOG_DIR"

INTERVAL=600  # 10分钟 = 600秒（放宽验证阶段）
EVOLVE_INTERVAL=14400  # 4小时 = 14400秒
LAST_EVOLVE=0

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 交易调度器启动，间隔 ${INTERVAL}s，自进化间隔 ${EVOLVE_INTERVAL}s"

while true; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] === 开始新一轮调度 ==="

    # ── 1. Agent A/B 编排器 ──
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 运行 Agent A/B 编排器..."
    cd "$BASE_DIR" && python3 orchestrator.py >> "$LOG_DIR/orchestrator_cron.log" 2>&1
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Agent A/B 编排器完成 (exit: $?)"

    # ── 2. 三屏马丁编排器 ──
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 运行三屏马丁编排器..."
    cd "$BASE_DIR" && python3 screen_orchestrator.py >> "$LOG_DIR/screen_orchestrator_cron.log" 2>&1
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 三屏马丁编排器完成 (exit: $?)"

    # ── 3. 每4小时执行监控+自进化+PR评论 ──
    NOW=$(date +%s)
    ELAPSED=$((NOW - LAST_EVOLVE))
    if [ $ELAPSED -ge $EVOLVE_INTERVAL ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] === 执行监控+自进化+PR评论 ==="

        # Agent A/B 监控+复盘+PR
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] 运行 Agent A/B 监控..."
        cd "$BASE_DIR" && python3 auto_monitor.py >> "$LOG_DIR/auto_monitor_cron.log" 2>&1
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Agent A/B 监控完成 (exit: $?)"

        # 三屏马丁监控+自进化+PR
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] 运行三屏马丁监控..."
        cd "$BASE_DIR" && python3 screen_monitor.py >> "$LOG_DIR/screen_monitor_cron.log" 2>&1
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] 三屏马丁监控完成 (exit: $?)"

        # 易经推理监控+自进化+PR
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] 运行易经推理监控..."
        cd "$BASE_DIR/../11-易经推理系统" && python -m scripts.memory_l4.yijing_monitor >> "$LOG_DIR/yijing_monitor_cron.log" 2>&1
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] 易经推理监控完成 (exit: $?)"

        LAST_EVOLVE=$NOW
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] === 监控+自进化+PR评论完成 ==="
    fi

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] === 本轮调度完成，等待 ${INTERVAL}s ==="
    echo ""

    sleep $INTERVAL
done