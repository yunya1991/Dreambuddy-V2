#!/bin/bash
# 每日语料增量 + E3 定时重训（阶段一/二持续化，v1.1）
# 逻辑：统一处理器重跑（增量语料）→ 意图对数量变化时触发 E3 重训
# 由 crontab 每日 03:00 以 luke 用户运行，日志落盘 logs/daily_retrain.log
set -u
SYS34=/home/luke/dreambuddy/34-前端应用训练系统
PY=/home/luke/venv-trading/bin/python
LOG=$SYS34/logs/daily_retrain.log
STATE=$SYS34/logs/last_intent_pairs_count

echo "[$(date '+%F %T')] === daily_corpus_retrain 开始 ===" >> "$LOG"

# 1. 统一处理器重跑（增量语料：快讯/案例/文档）
cd "$SYS34" || exit 1
"$PY" scripts/unified_corpus_processor.py run >> "$LOG" 2>&1

# 2. 检查意图对数量是否变化
COUNT=$(wc -l < "$SYS34/corpus/intent_pairs.jsonl" 2>/dev/null || echo 0)
LAST=$(cat "$STATE" 2>/dev/null || echo 0)
echo "[$(date '+%F %T')] 意图对: $COUNT（上次 $LAST）" >> "$LOG"

if [ "$COUNT" != "$LAST" ] && [ "$COUNT" -gt 0 ]; then
    echo "$COUNT" > "$STATE"
    # 3. 语料有变化 → 触发 E3 重训（阶段二任务微调）
    if pgrep -f train_e3_baseline > /dev/null; then
        echo "[$(date '+%F %T')] 已有训练进程在运行，跳过本轮重训" >> "$LOG"
    else
        echo "[$(date '+%F %T')] 语料变化，启动 E3 重训" >> "$LOG"
        nohup "$PY" scripts/train_e3_baseline.py > /tmp/train_e3_scheduled.log 2>&1 &
        echo "[$(date '+%F %T')] E3 重训已启动（PID $!），日志 /tmp/train_e3_scheduled.log" >> "$LOG"
    fi
else
    echo "[$(date '+%F %T')] 语料无变化，跳过重训" >> "$LOG"
fi
echo "[$(date '+%F %T')] === daily_corpus_retrain 结束 ===" >> "$LOG"
