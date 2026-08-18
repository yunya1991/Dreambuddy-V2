# Hermes Gateway 飞书通信故障排查

> 基于 2026-06-03 实际排障经验
> 适用: Hermes Bot 在飞书中不能收发消息时

---

## 诊断三步法

### Step 1: 验证凭证层

```bash
# 测试 Hermes Bot 的飞书 App 凭证是否有效
python -c "
import requests
resp = requests.post('https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
    json={'app_id': 'YOUR_APP_ID', 'app_secret': 'YOUR_APP_SECRET'})
print(resp.json())
"
```

**期望**: `code: 0, msg: ok`
**失败**: `code: 10014` → App Secret 无效，需在飞书开发者后台重新获取

同时验证 Bot 所在群:
```bash
curl -H "Authorization: Bearer <token>" \
  "https://open.feishu.cn/open-apis/im/v1/chats?page_size=20"
```

---

### Step 2: 检查 Gateway 平台状态

关键日志文件（均在 `~/.hermes/logs/`）:

| 日志文件 | 内容 | 关键信号 |
|---------|------|---------|
| `gateway.log` | Gateway 运行状态 | `✓ feishu connected` / `No messaging platforms enabled` |
| `errors.log` | 错误和警告 | `No messaging platforms enabled` / Lark WebSocket 断连 |
| `gateway-exit-diag.log` | Gateway 启动崩溃诊断 | `TypeError` / 配置解析错误 |

**健康状态**:
```
INFO gateway.run: Connecting to feishu...
INFO gateway.platforms.feishu: [Feishu] Connected in websocket mode
INFO gateway.run: ✓ feishu connected
INFO gateway.run: Gateway running with 1 platform(s)
```

**故障状态**:
```
WARNING gateway.run: No messaging platforms enabled.
ERROR Lark: receive message loop exit, err: no close frame received or sent
```

---

### Step 3: 修复与验证

#### 3a. Gateway 配置解析崩溃

`gateway-exit-diag.log` 中出现 `TypeError` 在 `PlatformConfig.from_dict` / `HomeChannel.from_dict` → Gateway 启动时无法注册 Feishu 平台。

**修复**: 重启 Gateway。
```bash
# Windows — 使用 hermes CLI
hermes gateway restart

# 或手动重启
hermes gateway stop
hermes gateway run --replace
```

**注意**: `gateway run` 是前台阻塞进程。生产环境应使用 Windows 计划任务（`Hermes_Gateway`）或后台运行。

#### 3b. send_message 显示 "No messaging platforms connected"

即使 Gateway 显示 `✓ feishu connected`，`send_message(action='list')` 仍可能返回空。

**根因**: `send_message` 依赖 `channel_directory`，后者从 `~/.hermes/sessions/sessions.json` 中读取已知频道。Feishu（非 Discord/Slack）平台的频道通过 session 数据发现，而非主动枚举。

**修复**: 在任意飞书群中 @Hermes Bot 发一条消息。Gateway 收到消息后会自动在 `sessions.json` 中注册该频道，之后 `send_message` 就能发现所有已注册的飞书群。

---

## 两套飞书凭证架构

6-TRADING 中存在两套独立的飞书集成，使用不同的 App 凭证:

| 组件 | 通信方式 | 方向 | 凭证位置 |
|------|---------|------|---------|
| **feishu_notify.py** | REST API (HTTP POST) | 单向推送 | 硬编码在脚本顶部 |
| **Hermes Bot** | WebSocket | 双向通信 | `~/.hermes/.env` |

**常见故障**:
- `feishu_notify.py` 返回 `code: 10014, msg: app secret invalid` → 该 App 的 Secret 已失效
- Hermes Bot WebSocket 断连 → 见 Step 2-3 排查流程

两者可使用相同或不同的飞书应用。建议统一为一个 App 以简化凭证管理。

---

## 快速诊断脚本

```python
# check_feishu.py — 一键诊断 Hermes 飞书通信状态
import os, json, requests
from pathlib import Path

hermes_home = Path(os.path.expanduser("~/.hermes"))

# 1. 凭证测试
env_vars = {}
env_path = hermes_home / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            env_vars[k.strip()] = v.strip()

app_id = env_vars.get('FEISHU_APP_ID', '')
app_secret = env_vars.get('FEISHU_APP_SECRET', '')

if app_id and app_secret:
    r = requests.post(
        'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
        json={'app_id': app_id, 'app_secret': app_secret}, timeout=10)
    result = r.json()
    print(f"凭证: {'OK' if result.get('code') == 0 else 'FAIL: ' + result.get('msg', '')}")
else:
    print("凭证: NOT CONFIGURED")

# 2. Gateway 日志状态
log_path = hermes_home / "logs" / "gateway.log"
if log_path.exists():
    last_lines = log_path.read_text().splitlines()[-30:]
    connected = any('feishu connected' in l for l in last_lines)
    no_platforms = any('No messaging platforms enabled' in l for l in last_lines)
    print(f"Gateway: {'CONNECTED' if connected else 'NOT IN RECENT LOGS'}")
    if no_platforms:
        print(f"  WARNING: 'No messaging platforms enabled' detected")

# 3. sessions.json
sessions_path = hermes_home / "sessions" / "sessions.json"
if sessions_path.exists():
    data = json.loads(sessions_path.read_text())
    feishu = [k for k, v in data.items() 
              if v.get('origin', {}).get('platform') == 'feishu']
    print(f"sessions.json: {len(feishu)} Feishu entries")
else:
    print("sessions.json: MISSING -> send_message channel directory empty")

# 4. 网关崩溃诊断
diag_path = hermes_home / "logs" / "gateway-exit-diag.log"
if diag_path.exists():
    content = diag_path.read_text()
    if 'TypeError' in content:
        print("gateway-exit-diag: TypeError crash detected -> restart needed")
```
