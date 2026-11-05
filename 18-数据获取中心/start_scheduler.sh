#!/bin/bash
# 18 域调度器统一启动脚本：从本地 .env 注入 PG 凭据后启动（2026-11-05 固化）
cd "$(dirname "$0")"
if [ ! -f .env ]; then
  echo "ERROR: .env not found" >&2
  exit 1
fi
export DATA_CENTER_PG_PASSWORD=$(grep -oP "postgresql://[^:]+:\K[^@]+" .env | head -1)
if [ -z "$DATA_CENTER_PG_PASSWORD" ]; then
  echo "ERROR: password not found in .env" >&2
  exit 1
fi
exec /home/luke/venv-trading/bin/python data_center_scheduler.py >> logs/scheduler.log 2>&1
