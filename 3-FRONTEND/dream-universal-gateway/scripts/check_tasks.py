#!/usr/bin/env python3
import os, json

TASKS_DIR = '/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/dreambuddy/artifacts/tasks'

if not os.path.isdir(TASKS_DIR):
    print(f'TASKS_DIR not found: {TASKS_DIR}')
    exit(1)

files = [f for f in os.listdir(TASKS_DIR) if f.endswith('.json')]
print(f'Total task files: {len(files)}')

status_counts = {}
pending_files = []

for f in files:
    try:
        d = json.load(open(os.path.join(TASKS_DIR, f)))
        status = d.get('status', 'unknown')
        status_counts[status] = status_counts.get(status, 0) + 1
        if status == 'pending':
            pending_files.append({'file': f, 'updated_at': d.get('updated_at', '')})
    except Exception:
        pass

print('\nStatus distribution:')
for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
    print(f'  {status}: {count}')

print(f'\nPending: {len(pending_files)}')
if pending_files:
    pending_files.sort(key=lambda x: x['updated_at'], reverse=True)
    for p in pending_files[:5]:
        print(f'  {p["file"]}: updated_at={p["updated_at"]}')
