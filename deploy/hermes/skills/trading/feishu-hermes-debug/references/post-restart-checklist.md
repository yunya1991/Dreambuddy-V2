# Gateway 重启后完整检查清单

每次 `hermes gateway` 重启后，以下三个组件会静默丢失，必须逐一恢复。

## 快速诊断

```python
import os, json, time

# 1. Gateway 连接
log_path = os.path.expanduser("~/.hermes/logs/gateway.log")
with open(log_path, 'r', encoding='utf-8') as f:
    content = f.read()
gw_ok = "✓ feishu connected" in content

# 2. 频道目录
cd_path = os.path.expanduser("~/.hermes/channel_directory.json")
with open(cd_path, 'r', encoding='utf-8') as f:
    cd = json.load(f)
channels = cd.get("platforms", {}).get("feishu", [])
groups_ok = sum(1 for ch in channels if ch.get("type") == "group") >= 5

# 3. Poller 存活
state_path = os.path.expanduser("~/.hermes/feishu_poller_state.json")
poller_ok = os.path.exists(state_path) and (time.time() - os.path.getmtime(state_path)) < 30

print(f"Gateway: {'✓' if gw_ok else '✗'} | Groups: {'✓' if groups_ok else '✗'} ({len(channels)} channels) | Poller: {'✓' if poller_ok else '✗'}")

# 4. Cron deliver
jobs_path = os.path.expanduser("~/.hermes/cron/jobs.json")
with open(jobs_path, 'r', encoding='utf-8') as f:
    jobs = json.load(f)
deliver_issues = [j['name'] for j in jobs.get('jobs', []) if j.get('deliver', '') == 'local']
if deliver_issues:
    print(f"  ✗ {len(deliver_issues)} cron jobs have deliver=local")
```

## 一键修复

### Channel Directory
```python
groups = [
    {"id": "oc_36c575b6f39a8df3dd75057a96685a21", "name": "Trading-Research", "type": "group"},
    {"id": "oc_36c8543cea823b7546fcaad55d111f9f", "name": "Trading-Desk", "type": "group"},
    {"id": "oc_9cf9f141613b4e6a0f34651843cf8b9b", "name": "Trading-Management", "type": "group"},
    {"id": "oc_8868a5c84f3d8427afa9ed1a9ad7fb76", "name": "Trading-Review", "type": "group"},
    {"id": "oc_20fcedf0c35035568ea8fa947380f75d", "name": "Trading-RiskControl", "type": "group"},
]
# (完整修复代码见 SKILL.md Phase 6.1)
```

### Poller
```python
import subprocess
python_path = r"C:\Users\luke.zhang\AppData\Local\Programs\Python\Python312\python.exe"
proc = subprocess.Popen([python_path, r"C:\tmp\group_poller.py"], ...)
# (完整启动代码见 SKILL.md Phase 6.2)
```

### Cron Deliver
```python
deliver_str = "origin,feishu:oc_36c575b6f39a8df3dd75057a96685a21,feishu:oc_36c8543cea823b7546fcaad55d111f9f,..."
# (完整更新代码见 SKILL.md Phase 6.3)
```
