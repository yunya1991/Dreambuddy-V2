---
name: feishu-hermes-debug
description: Diagnose and fix Hermes Agent ↔ Feishu Bot communication issues. Covers WebSocket connectivity, send_message tool, channel directory, inbound message events, app publishing, scope management, and gateway restart procedures.
category: trading
triggers:
  - "飞书不通信"
  - "hermes bot 收不到消息"
  - "send_message 报错"
  - "飞书连通"
  - "feishu disconnect"
  - "channel directory"
  - "gateway restart"
  - "app publish"
---

# Feishu ↔ Hermes 通信调试 Skill

## 核心诊断流程（按顺序执行）

### Phase 0: 快速连通性测试

```python
import requests, os, json

domain = "open.feishu.cn"
env_path = os.path.expanduser("~/.hermes/.env")
env_vars = {}
with open(env_path, 'r') as f:
    for line in f:
        if line.strip() and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            env_vars[k.strip()] = v.strip()

token_url = f"https://{domain}/open-apis/auth/v3/tenant_access_token/internal"
resp = requests.post(token_url, json={
    "app_id": env_vars['FEISHU_APP_ID'],
    "app_secret": env_vars['FEISHU_APP_SECRET']
}, timeout=10).json()
```

如果 `code != 0`：App Secret 错误 → 检查 `.env` 中 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`

### Phase 1: Gateway 连接状态

```bash
# 查看 Gateway 日志最后 30 行
tail -30 ~/.hermes/logs/gateway.log

# 检查关键信号
grep "feishu connected" ~/.hermes/logs/gateway.log    # 应有最近一条
grep "No messaging platforms" ~/.hermes/logs/errors.log  # 不应出现
```

**关键指标**:
- `✓ feishu connected` → WebSocket 已连接
- `Gateway running with 1 platform(s)` → 平台已注册
- `No messaging platforms enabled` → 配置解析崩溃，需重启 Gateway

### Phase 2: outbound 测试（Hermes → 飞书）

```python
# 直接 REST API 发消息测试
msg_content = json.dumps({"text": "连通测试"})
requests.post(
    f"https://{domain}/open-apis/im/v1/messages?receive_id_type=chat_id",
    headers={**headers, "Content-Type": "application/json"},
    json={"receive_id": "oc_36c8543cea823b7546fcaad55d111f9f", "msg_type": "text", "content": msg_content},
    timeout=10
)
```

**如果失败**: 检查 `im:message:send_as_bot` scope

### Phase 3: `send_message` 工具与频道目录诊断

`send_message(action='list')` 返回 "No messaging platforms" 的原因链:

1. Gateway 启动时 `channel_directory.json` 从 `sessions.json` 构建频道列表
2. Feishu 频道通过 `_build_from_sessions("feishu")` 发现
3. `sessions.json` 不存在 OR 其中无 `origin.platform="feishu"` 的条目 → 频道列表为空

**⚠️ 关键：sessions.json 是真正的数据源，channel_directory.json 是派生文件！**

Gateway 启动时从 `sessions.json` **重建** `channel_directory.json`。只写 `channel_directory.json` 不写 `sessions.json` = 重启后丢失。必须**两个文件都写**，且**Gateway 停止时写入**（运行时写入会在 Gateway 关闭时被自身状态覆盖）。

**修复步骤（必须在 Gateway 停止时执行）**:

1. 用户先停止 Gateway
2. 写入 `sessions.json`（数据源），格式如下：
3. 写入 `channel_directory.json`（派生文件）
4. 用户重启 Gateway

**sessions.json 群组条目格式**（key: `agent:main:feishu:group:<chat_id>`）:

```python
import json, uuid
from datetime import datetime

now = datetime.now().isoformat()
sid = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]

group_entry = {
    "session_key": f"agent:main:feishu:group:{chat_id}",
    "session_id": sid,
    "created_at": now,
    "updated_at": now,
    "display_name": "Trading-Research",
    "platform": "feishu",
    "chat_type": "group",
    "input_tokens": 0, "output_tokens": 0,
    "cache_read_tokens": 0, "cache_write_tokens": 0,
    "total_tokens": 0, "last_prompt_tokens": 0,
    "estimated_cost_usd": 0.0, "cost_status": "unknown",
    "expiry_finalized": False, "suspended": False,
    "resume_pending": False, "resume_reason": None,
    "last_resume_marked_at": None, "is_fresh_reset": False,
    "was_auto_reset": False, "auto_reset_reason": None,
    "reset_had_activity": False,
    "origin": {
        "platform": "feishu", "chat_id": chat_id,
        "chat_name": "Trading-Research", "chat_type": "group",
        "user_id": None, "user_name": None,
        "thread_id": None, "chat_topic": None, "user_id_alt": None
    }
}
```

**channel_directory.json 格式**（与 sessions.json 同步写入）:

```json
{
  "platforms": {
    "feishu": [
      {"id": "oc_36c575b6f39a8df3dd75057a96685a21", "name": "Trading-Research", "type": "group"},
      {"id": "oc_36c8543cea823b7546fcaad55d111f9f", "name": "Trading-Desk", "type": "group"},
      {"id": "oc_9cf9f141613b4e6a0f34651843cf8b9b", "name": "Trading-Management", "type": "group"},
      {"id": "oc_8868a5c84f3d8427afa9ed1a9ad7fb76", "name": "Trading-Review", "type": "group"},
      {"id": "oc_20fcedf0c35035568ea8fa947380f75d", "name": "Trading-RiskControl", "type": "group"}
    ]
  }
}
```

### Phase 3.5: channel_directory.json ↔ config.yaml 一致性检查

`channel_directory.json` 的群组列表必须与 `config.yaml` 中 `group_rules` 的 key 保持一致。不一致时 `send_message` 可能列出群组但消息路由失败。

**检查脚本**:
```python
import json, os

# 读取两份配置
with open(os.path.expanduser("~/.hermes/channel_directory.json"), 'r') as f:
    cd = json.load(f)
with open(os.path.expanduser("~/.hermes/config.yaml"), 'r') as f:
    cfg = f.read()

cd_ids = {ch['id'] for ch in cd['platforms']['feishu']}
# 从 config.yaml 提取 group_rules 中所有 chat_id
import re
gr_ids = set(re.findall(r'"oc_[a-f0-9]+"', cfg.split('group_rules:')[1].split('channel_prompts')[0] if 'channel_prompts' in cfg else cfg.split('group_rules:')[1]))

missing_in_cd = gr_ids - cd_ids
missing_in_gr = cd_ids - gr_ids - {'oc_0b8badf8770b13c9359145a939a3eb8c'}  # 排除 DM
if missing_in_cd: print(f"❌ group_rules 有但 channel_directory 缺: {missing_in_cd}")
if missing_in_gr: print(f"❌ channel_directory 有但 group_rules 缺: {missing_in_gr}")
if not missing_in_cd and not missing_in_gr: print("✅ 一致")
```

**已知的群组 ID（6-TRADING）**: 参见 `references/trading-group-chat-ids.md`

### Phase 4: Inbound 诊断（飞书 → Hermes）

**症状**: Gateway 收到 `bot.added_v1` 事件但收不到 `im.message.receive_v1`

**诊断步骤**:

1. 查看 Gateway 日志中是否有人消息事件:
```bash
grep "im.message.receive" ~/.hermes/logs/gateway.log
grep "_on_message_event" ~/.hermes/logs/gateway.log
```
如果 0 条 → 事件未推送到 WebSocket

2. 检查 App 权限:
```python
# 获取 App 完整权限列表
r = requests.get(
    f"https://{domain}/open-apis/application/v6/applications/{app_id}?lang=zh_cn",
    headers=headers, timeout=10
)
scopes = r.json()['data']['app']['scopes']
```

**必需权限**: `im:message.group_at_msg:readonly`（获取群组中用户@机器人消息）

3. 检查 App 发布状态:
```python
# App status: 1=开发中, 2=已发布
app_status = r.json()['data']['app']['status']
```

**根因**: `app_status=1`（开发中）时，飞书 WebSocket 只推送管理类事件（`bot.added/deleted`），不推送消息内容事件（`im.message.receive_v1`）。**必须发布 App 后才推送。**

**⚠️ P2P vs 群聊差异**: App 未发布时，DM（P2P）消息**可能**仍能送达，但群聊消息**确定不会**推送。典型症状「DM 通群聊不通」就是 App 未发布的确诊信号——不需要怀疑权限或 WebSocket。\n\n**重要**: `/open-apis/application/v6/applications/{app_id}` 返回的 `status` 字段在发布后可能**延迟更新**或保持为 `1`。不要在 API 返回值上死等。可靠的验证信号是：版本数增加（`app_versions` 从 N→N+1），加上实测消息接收。\n\n4. 发布 App（Console 操作，无 REST API 可用）:\n   - 步骤 1: `https://open.feishu.cn/app/{app_id}/auth` — 确认 `im:message.group_at_msg:readonly` 或 `im:message.group_msg` 已添加\n   - 步骤 2: `https://open.feishu.cn/app/{app_id}/event` — 先配订阅方式为「长连接」，再点「添加事件」勾选「接收消息」\n     - 若「接收消息」复选框灰掉：说明没先配订阅方式\n     - 若事件列表中找不到「接收消息」：说明缺对应权限 → 回到步骤 1\n   - 步骤 3: `https://open.feishu.cn/app/{app_id}/version` — 创建版本（填版本号 + 可用范围「全体成员」）→ 保存 → 提交发布 → 等管理员审批\n   - 步骤 4: 审批通过后 `hermes gateway restart` + 在群里 @Bot 发消息验证 `gateway.log` 出现 `im.message.receive_v1`

### Phase 5: Gateway 重启

**⚠️ 关键限制：Hermes bash 终端无法启动 Windows hermes.exe**

Hermes 的 `terminal` 工具运行在 bash (git-bash/MSYS) 环境中。当 Windows 用户名含 `.`（如 `luke.zhang`）时，bash 路径解析会失败。直接用 `hermes gateway run --replace` 也会因为 bash 环境找不到 Windows 侧的 `.env` 凭证文件而导致飞书适配器无法加载。

**✅ 正确方式：通过 execute_code + Python subprocess 启动**

```python
import subprocess, os

hermes_path = r"C:\Users\xxx\AppData\Local\Programs\Python\Python312\Scripts\hermes.exe"
env = os.environ.copy()
env["HOME"] = os.path.expanduser("~")  # 确保 hermes 找到正确 home

proc = subprocess.Popen(
    [hermes_path, "gateway", "run", "--replace"],
    env=env,
    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
)
# proc.pid 即为 Gateway 进程 PID
```

**定位 hermes.exe**：`where hermes`（在 bash 中可用）或 `C:\Users\<user>\AppData\Local\Programs\Python\Python312\Scripts\hermes.exe`

**重启后检查**（用 execute_code 读日志）:
```python
import os
log_path = os.path.expanduser("~/.hermes/logs/gateway.log")
with open(log_path, 'r', encoding='utf-8') as f:
    content = f.read()
# 检查 "✓ feishu connected" 和 "Gateway running with 1 platform(s)"
```

### Phase 6: Post-Restart 完整检查清单（Gateway 重启后必做）

Gateway 重启会导致三个组件静默丢失，必须逐一恢复：

#### 6.1 频道目录群组恢复

重启后 `channel_directory.json` 被从 sessions.json 重建，**群组条目丢失，只剩 DM**。

诊断: `len(cd["platforms"]["feishu"])` ≤ 2 → 只有 DM，缺群组。

修复（用 execute_code）:
```python
import json, os
cd_path = os.path.expanduser("~/.hermes/channel_directory.json")
with open(cd_path, 'r', encoding='utf-8') as f:
    cd = json.load(f)

groups = [
    {"id": "oc_36c575b6f39a8df3dd75057a96685a21", "name": "Trading-Research", "type": "group"},
    {"id": "oc_36c8543cea823b7546fcaad55d111f9f", "name": "Trading-Desk", "type": "group"},
    {"id": "oc_9cf9f141613b4e6a0f34651843cf8b9b", "name": "Trading-Management", "type": "group"},
    {"id": "oc_8868a5c84f3d8427afa9ed1a9ad7fb76", "name": "Trading-Review", "type": "group"},
    {"id": "oc_20fcedf0c35035568ea8fa947380f75d", "name": "Trading-RiskControl", "type": "group"},
]
existing_ids = {ch['id'] for ch in cd['platforms']['feishu']}
for g in groups:
    if g['id'] not in existing_ids:
        cd['platforms']['feishu'].append(g)

with open(cd_path, 'w', encoding='utf-8') as f:
    json.dump(cd, f, indent=2, ensure_ascii=False)
```

#### 6.2 Group Poller 恢复

`group_poller.py` 是独立 `while True` 循环脚本（非 cron job），通过 REST API 轮询 5 个群聊的 @mention。**v2 架构**：poller 检测到 @mention → 写入 `pending_group_mentions.jsonl` + 发送 ack → `GroupMentionProcessor-60s` cron（每分钟）读取 pending → Agent 处理 → REST API 回复到群。Gateway 重启时 poller 随之前进程一起被杀，需单独重启。

诊断: 
- `feishu_poller_state.json` 修改时间早于 Gateway 重启时间 → poller 已死
- 或 `tasklist /FI "IMAGENAME eq python.exe"` 中没有对应进程

修复（用 execute_code + subprocess）:
```python
import subprocess, os
python_path = r"C:\Users\luke.zhang\AppData\Local\Programs\Python\Python312\python.exe"
poller_path = r"C:\tmp\group_poller.py"
env = os.environ.copy()
env["HOME"] = os.path.expanduser("~")

proc = subprocess.Popen(
    [python_path, poller_path],
    env=env,
    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
)
```

验证: 等 15 秒后检查 `feishu_poller_state.json` 修改时间是否更新。

#### 6.3 Cron Jobs deliver 检查

重启后 cron jobs 的 `deliver` 可能被重置为 `local`，导致输出不发飞书。

检查: 读 `~/.hermes/cron/jobs.json`，确认每个 job 的 `deliver` 字段。

修复: 批量更新为 `origin` + 所有群组飞书 ID:
```python
deliver_str = "origin,feishu:oc_36c575b6f39a8df3dd75057a96685a21,feishu:oc_36c8543cea823b7546fcaad55d111f9f,..."
with open(jobs_path, 'r', encoding='utf-8') as f:
    data = json.load(f)
for job in data["jobs"]:
    job["deliver"] = deliver_str
with open(jobs_path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
```

#### 6.4 完整检查脚本与参考

- **检查+修复脚本**: 参见 `references/post-restart-checklist.md` — 一键检查+修复脚本（含 4 个子步骤）。
- **Poller 架构文档**: 参见 `references/group-poller.md` — v2 架构、poller+cron 链路、pending 文件格式。
- **Poller 可执行脚本**: 存档于 `scripts/group_poller.py` — 与 `C:\tmp\group_poller.py` 保持同步。

## 常见故障速查表

| 症状 | 根因 | 修复 |
|------|------|------|
| Gateway 启动崩溃 | `home_channel` 格式导致 `PlatformConfig` 解析 TypeError | 重启 Gateway (config.yaml 格式正确，重启自动修复) |
| `send_message` list 为空 | `channel_directory.json` 中 feishu 为空 | 手动写入频道列表 |
| 能发消息但收不到 | App 未发布 (`status=1`) | 开发者后台发布 App（见 Phase 4 完整 SOP） |
| **群聊不通但 DM 通** | App 未发布 — P2P 消息可透传但群聊事件被阻断（确诊信号） | 发布 App，不需要排查权限或 WebSocket |
| REST API 能读消息但事件不推送 | `im:message:readonly` 有但 App 未发布 | 同上 |
| lark-cli `--as user` 报错 | 未绑定到 Hermes 或未做用户认证 | `lark-cli config bind --source hermes --identity bot-only` |
| Bitable access denied | 缺 `bitable:app` 或 `base:app:read` scope | 开发者后台添加权限 |
| `feishu_notify.py` 报 app secret invalid | 使用了不同的 App（cli_aa9442...）与 Hermes Bot 不同 | 统一使用 Hermes Bot 凭证 |
| `lark-cli apps +access-scope-get` 报 command_denied | strict mode=bot，该命令需 user 身份 | 用 REST API 替代: `GET /open-apis/application/v6/applications/{app_id}?lang=zh_cn` |
| Console 搜不到 `im:message:read_as_bot` | 该 scope 名称不存在，消息事件通过 `im.message.receive_v1` 订阅 + `im:message.group_at_msg:readonly` 权限实现 | 添加 `im:message.group_at_msg:readonly` + 发布 App 即可 |
| Gateway 重启后静默死亡（log 停在某时刻不再更新） | 前台进程随终端会话结束而终止 | 用 execute_code + subprocess 以独立进程方式启动（见 Phase 5） |
| 用 bash `hermes gateway run` 启动后飞书不连接 | bash 环境找不到 Windows .env，`FEISHU_APP_ID/SECRET` 未设置 | 用 execute_code + subprocess 启动，显式设 `HOME`（见 Phase 5） |
| `hermes` 命令在 bash 中指向 `/home/xxx/.local/bin/hermes` 而非 Windows hermes.exe | PATH 中 Linux 版 hermes 在前 | 使用完整 Windows 路径 `C:\Users\...\hermes.exe` |
| Gateway 重启后群聊 @mention 不响应 | `group_poller.py` 独立进程随 Gateway 一起被杀，未自动重启 | 用 execute_code + subprocess 重启 poller（见 Phase 6.2） |
| Gateway 重启后 cron 输出不发飞书群 | `deliver` 被重置为 `local` | 批量更新 jobs.json 的 deliver 字段（见 Phase 6.3） |
| `feishu_notify.py` 或 `approval_agent.py` 报 token 无效 | 两个文件硬编码了旧 App ID `cli_aa9442...`，与当前 Hermes Bot `cli_aa95b2...` 不一致 | 统一改为当前 Bot 的 App ID/Secret，或改为从 `.env` 读取 |
| 审批单创建成功但 AI 兜底不触发 | `approval_agent.py` 使用旧 App token，`get_approval_status()` 返回错误 | 将 `get_approval_status`/`send_msg` 改为 lark-cli 调用（见 Phase 8） |
| Dashboard `http://127.0.0.1:9119` 不显示 | Dashboard 是独立服务，需单独启动；首次需 npm build | `hermes dashboard --port 9119`（首次 30-60s build，后续 `--skip-build` 秒起） |
| Cron 每10分钟往所有群推"无待处理审批单" | cron deliver 设了群组列表，但脚本内部已有通知逻辑 | 将 deliver 改为 `local`；脚本内部的 send_msg 负责真正通知 |
| 飞书审批/任务/OKR 机器人"未集成" | 误把平台内置机器人当成需手动集成的功能 | 审批/任务/OKR 是飞书平台内置——API 创建后自动推送，无需额外配置 |

### Phase 6.5: Hermes Dashboard Web UI

Dashboard 是独立服务，不属于 Gateway。端口 9119 无响应 = dashboard 未启动。

**诊断**:
```bash
hermes dashboard --status
netstat -ano | findstr :9119
```

**启动**:
```bash
# 首次需 npm build (30-60s), 后续 --skip-build 秒起
hermes dashboard --port 9119 --no-open
# 已 build 过: hermes dashboard --port 9119 --no-open --skip-build
```

**Windows 注意**: bash terminal 无法启动，用 execute_code + subprocess（同 Phase 5 方式）。

**云上注意**: Dashboard 默认只绑 127.0.0.1，外网访问需 `--host 0.0.0.0 --insecure`（暴露 API keys，仅在内网/SSH tunnel 使用）。

### Phase 7: send_message 工具不可用时的回退

CLI 模式下 `send_message` 工具可能不在可用工具列表中（与 cron/feishu session 不同）。此时用 execute_code + Feishu REST API 直接发送：

```python
import json, os, requests

# 1. 获取 token
env_path = os.path.expanduser("~/.hermes/.env")
env = {}
with open(env_path, 'r') as f:
    for line in f:
        if line.strip() and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip()

r = requests.post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
    json={"app_id": env["FEISHU_APP_ID"], "app_secret": env["FEISHU_APP_SECRET"]}, timeout=10).json()
token = r["tenant_access_token"]

# 2. 发送消息
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
content = json.dumps({"text": "你的消息内容"})
r = requests.post(
    f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
    headers=headers,
    json={"receive_id": "oc_xxxxxxxx", "msg_type": "text", "content": content},
    timeout=10
).json()
# code=0 = 成功, message_id 在 r["data"]["message_id"]
```

此模式适用于：CLI 会话中需要回复群聊、群聊轮询处理器（GroupMentionProcessor cron）中 send_message 不可用时。

### Phase 8: 审批工作流 — lark-cli 局限与 REST API 回退

审批流程（`approval_agent.py` + `feishu_notify.py`）的 lark-cli 集成有以下已验证局限：

| 能力 | lark-cli 状态 | 实际方案 |
|------|-------------|---------|
| 创建审批实例 | ❌ `instances create` 不存在 | REST API `POST /approval/v4/instances` |
| 查询审批状态 | ❌ `instances get` 被 strict-mode=bot 阻止 | REST API `GET /approval/v4/instances/{code}` |
| 执行审批 | ✅ `tasks approve/reject --as user` | 可用，但需 profile 名匹配 |
| 推送通知 | ✅ `im message send` | 可用，或用 REST API 兜底 |

**结论**: `approval_agent.py` 全链路使用 REST API（从 `~/.hermes/.env` 读凭证），不依赖 lark-cli。

**已验证的审批 scope**（cli_aa95b2）: `approval:instance`, `approval:task`, `approval:approval` 等 15 个全部到位。

**App ID 统一**: `feishu_notify.py` 和 `approval_agent.py` 必须使用 `cli_aa95b2dee3b85bd1`（云涯Hermes），不能用已失效的旧 App `cli_aa9442...`。

## 工具使用技巧

**`read_file` / `write_file` 在 Windows 路径失败时的回退**: 当 `read_file` 返回 `"File not found"` 但文件确实存在，或 `write_file` 因路径问题失败时，使用 `execute_code` 中的 Python `open()` 直接读写文件：

```python
# 读取
with open("C:/Users/luke.zhang/.hermes/config.yaml", 'r', encoding='utf-8') as f:
    content = f.read()

# 写入
with open("C:/Users/luke.zhang/.hermes/channel_directory.json", 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
```

注意：`execute_code` 中的 `read_file` (hermes_tools) 与工具直接调用的 `read_file` 行为相同——返回 dict 而非字符串。直接用 Python `open()` 更可靠。

## 关键配置路径
|------|------|
| `~/.hermes/config.yaml` | `platforms.feishu` 配置（group_rules, channel_prompts, home_channel） |
| `~/.hermes/.env` | `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_DOMAIN` |
| `~/.hermes/logs/gateway.log` | Gateway 运行日志（含 WebSocket 事件） |
| `~/.hermes/logs/errors.log` | 错误日志 |
| `~/.hermes/logs/gateway-exit-diag.log` | Gateway 崩溃诊断 |
| `~/.hermes/channel_directory.json` | `send_message` 频道列表 |
| `~/.hermes/sessions/sessions.json` | Session 记录（频道发现的数据源） |

## References

- `references/feishu-app-permissions.md` — App 权限完整清单与含义
- `references/group-poller.md` — group_poller.py v2 架构与链路文档
- `references/group-poller-v2.md` — Poller v2 详细文档（pending file + cron 链路 + 去重 + 启动方式）
- `references/post-restart-checklist.md` — Gateway 重启后完整检查+修复脚本
- `references/trading-group-chat-ids.md` — 已知的群组 ID

## Scripts

- `scripts/group_poller.py` — v2 可执行脚本（与 C:\tmp\group_poller.py 同步）
