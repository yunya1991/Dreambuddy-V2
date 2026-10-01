#!/usr/bin/env python3
import os
import requests
import subprocess
import json
from datetime import datetime

gh_token = os.environ.get('GH_TOKEN', '') or os.environ.get('GITHUB_TOKEN', '')
if not gh_token:
    try:
        result = subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            gh_token = result.stdout.strip()
    except:
        pass
if not gh_token:
    print('GH_TOKEN not set')
    exit(1)

state_file = 'data/v15_state.json'
with open(state_file) as f:
    state = json.load(f)

positions = state.get('positions', {})
total_trades = state.get('total_trades', 0)
total_wins = state.get('total_wins', 0)
win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0

pos_summary = []
for coin, pos in positions.items():
    entry = pos.get('entry_price', 0)
    sl = pos.get('stop_loss_price', 0)
    tp_pct = pos.get('take_profit_pct', 0) * 100
    addons = pos.get('addons', 0)
    pos_summary.append('- {}: 入场=${:.2f} SL=${:.2f} TP={:.1f}% 加仓={}/3'.format(coin, entry, sl, tp_pct, addons))

body = '''## V15 经典马丁策略监控报告

### 系统状态
- 运行模式: 实盘自动交易 (AUTO_EXECUTE=True)
- 轮询间隔: 3600s
- 最大加仓: 3次
- 杠杆: 5x

### 当前持仓 ({}个)
{}

### 交易统计
- 总交易: {}
- 盈利: {}
- 胜率: {:.1f}%
- 连续亏损: {}次

### 监控文件
- 状态: data/v15_state.json
- 日志: logs/v15/

---
自动生成于 {}
'''.format(len(positions), '\n'.join(pos_summary), total_trades, total_wins, win_rate, state.get('consecutive_losses', 0), datetime.now().isoformat())

url = 'https://api.github.com/repos/yunya1991/Dreambuddy-V2/issues/52/comments'
headers = {
    'Authorization': 'token {}'.format(gh_token),
    'Accept': 'application/vnd.github.v3+json',
}
data = {'body': body}

try:
    resp = requests.post(url, headers=headers, json=data)
    if resp.status_code == 201:
        print('PR评论创建成功')
    else:
        print('创建失败: {} - {}'.format(resp.status_code, resp.text))
except Exception as e:
    print('错误: {}'.format(e))
