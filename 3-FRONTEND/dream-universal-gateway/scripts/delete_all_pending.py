#!/usr/bin/env python3
import os, json

TASKS_DIR = '/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/dreambuddy/artifacts/tasks'

removed = 0
for f in os.listdir(TASKS_DIR):
    if not f.endswith('.json'): continue
    try:
        d = json.load(open(os.path.join(TASKS_DIR, f)))
        if d.get('status') == 'pending':
            print(f'  删除: {f}')
            os.remove(os.path.join(TASKS_DIR, f))
            removed += 1
    except Exception:
        pass

print(f'\n已删除 {removed} 个 pending 任务')
