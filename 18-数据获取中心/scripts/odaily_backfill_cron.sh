#!/bin/bash
# odaily 深度文章持续采集（后台定时运行，flock 防重叠）
# 用途：crontab 定时调用，每轮爬取 --target 篇深度文章正文，产出 contents.jsonl + 报告
# 日志：/tmp/odaily_backfill_cron.log
# 离线模式：FinBERT 使用本地模型，避免 HuggingFace 在线校验 401 阻塞

export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

exec 9>/tmp/odaily_backfill.lock
if ! flock -n 9; then
    echo "$(date '+%F %T') 上一轮仍在运行，跳过本轮"
    exit 0
fi

cd /home/luke/dreambuddy/18-数据获取中心 || exit 1
/home/luke/venv-trading/bin/python scripts/backfill_odaily_post_content.py --target 100 >> /tmp/odaily_backfill_cron.log 2>&1
/home/luke/venv-trading/bin/python scripts/merge_odaily_contents.py >> /tmp/odaily_backfill_cron.log 2>&1
exit $?
