#!/usr/bin/env python3
"""清理超过15分钟的pending任务，避免压力测试导致的队列堵塞。"""
import os, json, time
from datetime import datetime, timezone

TASKS_DIR = '/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/dreambuddy/artifacts/tasks'
MAX_AGE_MINUTES = 15

if not os.path.isdir(TASKS_DIR):
    print(f'TASKS_DIR not found: {TASKS_DIR}')
    exit(1)

now = time.time()
cleaned = 0

for f in os.listdir(TASKS_DIR):
    if not f.endswith('.json'):
        continue
    filepath = os.path.join(TASKS_DIR, f)
    try:
        d = json.load(open(filepath))
        if d.get('status') != 'pending':
            continue

        # 检查任务是否过旧
        updated_at = d.get('updated_at', '')
        if not updated_at:
            continue

        # 解析 ISO 8601 时间
        try:
            dt = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
            age_minutes = (now - dt.timestamp()) / 60.0
        except Exception:
            continue

        if age_minutes > MAX_AGE_MINUTES:
            print(f'  清理过期任务: {f} (age={age_minutes:.0f}min, message={d.get("message","")[:50]})')
            # 删除任务文件
            os.remove(filepath)
            cleaned += 1

    except Exception as e:
        print(f'  错误处理 {f}: {e}')

print(f'\n已清理 {cleaned} 个过期 pending 任务')

# 重新统计
pending_remaining = 0
for f in os.listdir(TASKS_DIR):
    if not f.endswith('.json'):
        continue
    try:
        d = json.load(open(os.path.join(TASKS_DIR, f)))
        if d.get('status') == 'pending':
            pending_remaining += 1
    except Exception:
        pass

print(f'当前 pending 任务数: {pending_remaining} (limit=3)')
