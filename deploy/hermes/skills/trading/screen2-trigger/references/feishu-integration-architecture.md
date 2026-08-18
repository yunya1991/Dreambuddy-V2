# 6-TRADING 飞书集成完整架构

> 源文件: `scripts/feishu_notify.py` (~29KB)
> 最后更新: 2026-06-03 (新增 Hermes Bot 通信诊断、Bitable Workflow 设计、审批机器人方案、混合架构评估)

---

## 一、五群组交易部门模型

`feishu_notify.py` 构建了一个完整的虚拟交易部门，五个飞书群各司其职：

| 群组 | channel key | chat_id | 职责 |
|------|------------|---------|------|
| 交易部-研究室 | `research` | `oc_36c575b6f39a8df3dd75057a96685a21` | Screen1 七维研判（完整）+ A1/A2/A3 摘要 |
| 交易部-交易台 | `trading` | `oc_36c8543cea823b7546fcaad55d111f9f` | Screen2 日线预设 / Screen3 入场/跳过 / A6 监控/预警 |
| 交易部-管理看板 | `management` | `oc_9cf9f141613b4e6a0f34651843cf8b9b` | Screen1 摘要 / A9 离场评估 / 多维表格归档确认 |
| 交易部-复盘室 | `review` | `oc_8868a5c84f3d8427afa9ed1a9ad7fb76` | A9 离场复盘 / ProcessD 周复盘 |
| 交易部-风控审批 | `risk` | `oc_20fcedf0c35035568ea8fa947380f75d` | ESCALATE_TO_HUMAN 强制上报 |

---

## 二、10 种通知类型全览

| CLI 命令 | 目标群 | 触发时机 | 输入 |
|----------|--------|---------|------|
| `screen1` | 研究室（完整卡片） + 管理看板（摘要） | Screen1 周线研判完成 | session_dir |
| `screen2` | 交易台 | Screen2 日线预设生成 | session_dir |
| `execution` | 交易台 | Screen3 Gate C 裁决 (ENTER/SKIP) | session_dir |
| `a6_monitor` | 交易台 | 每 4h 定时监控 | session_dir |
| `a6_alert` | 交易台（可能升级风控） | 马丁触发/止损预警/费率异常/象限切换 | alert_json |
| `a9` | 管理看板 + 复盘室 | 离场决策完成 | session_dir |
| `escalate` | 风控审批 | 触发升级规则 | reason_json |
| `review` | 复盘室 | ProcessD 周复盘完成 | session_dir |
| `bitable` | 管理看板 | 多维表格写入完成 | session_dir |
| `task <event>` | 飞书任务系统 | 创建/完成追踪任务 | event + session_dir |

### screen1 特殊行为
- **研究室**：完整卡片（七维度信号 + A1/A2/A3 摘要 + 配置）
- **管理看板**：仅摘要一行（方向 + 得分 + 象限 + 价格 + 有效期）

### a9 特殊行为
- **管理看板**：摘要（决策 + 离场分 + 已实现盈亏）
- **复盘室**：完整分析
- 若 decision = `ESCALATE_TO_HUMAN`：额外推送到风控审批

### a6_alert 特殊行为
- 基础推送交易台
- 自动检查升级规则，触发则连带推送风控审批

---

## 三、风控升级规则 (ESCALATE_RULES)

| 规则 | 阈值 | 说明 |
|------|------|------|
| `single_loss_usdt` | 500 USDT | 单笔浮亏超过此值 |
| `consecutive_sl` | 3 次 | 连续止损次数 |
| `quadrant_switch` | True | Regime 象限切换 |

触发任一 → `notify_escalate()` → 推送到 `risk` 群

---

## 四、飞书任务自动流转

```
Screen1完成 → task screen1_done → 创建 "[Screen1] 本周研判" 任务（due 7天）
Screen2完成 → task screen2_done → 创建 "[Screen2] 日线预设" 任务（due 1天）
ENTER入场   → task enter        → 完成 screen2 任务 + 创建 "[持仓] 监控中" 任务（due 30天）
SKIP跳过    → task skip         → 完成 screen2 任务（无新任务）
EXIT出场    → task exit         → 完成 position 任务 + 创建 "[复盘] 待复盘" 任务（due 3天）
ProcessD完成 → task process_d_done → 完成 review + screen1 任务
```

任务状态持久化在 `task_state.json`（与 feishu_notify.py 同目录）。

---

## 五、多维表格 (Bitable) 集成

- Table ID: `tblSDdfk2sbBAVsr` (Trading Episodes)
- 操作: `bitable_upsert()` — 先 search 再 insert/update
- 写入字段: Session ID, Date, Direction, Gate C Result, Screen1 Score, Entry/Exit Price, Realized PnL, PnL Pct, Martin Layers, Position Cap USDT, A8 Score, Red Team Flag, Clock Stage, Skill Regime, Signal Score, Exit Reason, Notes, GitHub URL
- 缺失字段静默跳过，不会因数据不完整而失败

---

## 六、Session 产物依赖关系

```
notify_screen1:
  ├── meta.json                          (session_id, screen1_price, ...)
  ├── team-a/screen1/strategy-type.json  (direction, weighted_total, confidence_breakdown)
  └── team-a/screen1/weekly-direction.md (提取 A1/A2/A3 摘要)

notify_screen2:
  ├── meta.json                          (session_id, screen1_direction 回退)
  ├── team-a/screen2/daily-presets.json  (direction, entry_price, take_profit, stop_loss)
  └── team-a/screen2/martingale-grid.json (max_layers, interval_pct)

notify_execution:
  ├── team-b/episode.json                (outcome, direction, entry_price, signal_score)
  └── team-b/gate-c/pretrade-check.json  (ach_summary)

notify_a6_monitor:
  └── team-a/screen3/a6-monitor.json     回退: a6-monitor.json

notify_a9:
  └── team-a/screen3/a9-exit.json        回退: a9-exit.json

notify_review:
  └── review/a8-reflection.md            回退: review/a8-reflection.json
```

---

## 七、公司制团队映射

飞书群组 ↔ 6-TRADING 内部团队：

```
研究室 (research)    ← Team A (Screen1/Screen2 研究产物)
交易台 (trading)     ← Team B (A5执行/A6监控) + Gate C (入场裁决)
管理看板 (management) ← 管理层视角（摘要 + 归档确认）
复盘室 (review)      ← Process D (A8复盘 + 周进化提案)
风控审批 (risk)      ← Governance G2/G4 (人工审批升级)
```

---

## 八、两套飞书凭证架构

6-TRADING 中存在两套独立的飞书集成，使用不同的 App 凭证:

| 组件 | App ID | 通信方式 | 方向 | 凭证位置 | 当前状态 |
|------|--------|---------|------|---------|---------|
| **feishu_notify.py** | `cli_aa9442bde4b89be9` | REST API (HTTP POST) | 单向推送 | 硬编码在脚本顶部 | ❌ `app secret invalid` |
| **Hermes Bot** | `cli_aa95b2dee3b85bd1` | WebSocket + REST API | 双向 | `~/.hermes/.env` | ✅ WebSocket 已连接 |

Bitable `CMlnbvAKYafUL0sxLpFcxNfVnoc` (Trading Episodes) 由 feishu_notify.py 的 App 创建。
Hermes Bot 需要: (1) 在开发者后台添加 `bitable:app` scope, (2) 将 Bitable 分享给 Hermes Bot。

### REST API 直接发消息（绕开 send_message 工具）

当 `send_message(action='list')` 返回 "No messaging platforms connected" 时，可用 REST API 直接发送:
```python
# 所有五个交易群 + 三个研究群的 chat_id 已确认可用
TOKEN_URL="http...
MSG_URL = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
# 获取 tenant_access_token → POST {receive_id, msg_type, content}
```

## 九、Hermes Gateway 通信诊断（已验证的三层排查法）

### 三层诊断法

| 层 | 检查点 | 方法 | 通过标志 |
|----|--------|------|---------|
| 凭证层 | Token 是否有效 | REST API POST `tenant_access_token` | `code: 0, msg: ok` |
| WebSocket 层 | 连接是否建立 | `gateway.log` 搜索 `[Feishu]` | `Connected in websocket mode` |
| Gateway 配置层 | 平台是否注册 | `gateway.log` 最后几行 | `✓ feishu connected` + `Gateway running with 1 platform(s)` |

### 已知故障模式与修复

| 故障 | 日志特征 | 根因 | 修复 |
|------|---------|------|------|
| Gateway 报告 "No messaging platforms enabled" | `errors.log` 中反复出现 | `config.yaml` 解析崩溃导致平台未注册 | `hermes gateway restart`（先 stop 再 run --replace） |
| `send_message` 无频道 | `Channel directory built: 0 target(s)` | `sessions.json` 不存在 | 方案A: 在任意飞书群 @Bot 发一条消息触发注册；方案B: 直接写 `channel_directory.json` |
| WebSocket 断连 | `ERROR Lark: receive message loop exit` | 网络波动 | Bot 自动重连，无需干预 |
| 凭证失效 | REST API 返回 `code: 10014` | App Secret 已轮换 | 更新 `~/.hermes/.env` 中 `FEISHU_APP_SECRET` |
| **Bot 不回复群消息（入站静默）** | `gateway.log` 有 `bot.added_v1` 事件但 **0 条** `im.message.receive_v1` 事件 | App 已激活但**未发布**（开发模式不推送消息事件） | 飞书开发者后台 → 创建版本 → 提交发布审核 → 管理员审批 |

### channel_directory.json 直接引导技术

当 `sessions.json` 不存在且无法立即触发入站消息时，可直接写入 `~/.hermes/channel_directory.json`：

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

写入后 `send_message(action='list')` 立即可用。Gateway 重启后会被覆盖，届时若 `sessions.json` 已建立则自动恢复。

### 入站/出站通信独立性

Hermes Bot 的出站（Bot→飞书群）和入站（飞书群→Bot）走不同的机制：

| 方向 | 机制 | 失败时的降级方案 |
|------|------|----------------|
| 出站 (send) | `send_message` 工具 / REST API | REST API 直接 POST 始终可用 |
| 入站 (receive) | WebSocket `im.message.receive_v1` 事件 | 需 App 发布；发布前只能用 REST API 轮询消息列表 |

诊断入站是否正常的关键指标：`gateway.log` 中 `im.message.receive_v1` 事件的条数。如果 `bot.added_v1` 有但 `im.message.receive_v1` 为 0，100% 是 App 未发布。

---

## 十、飞书原生自动化方案（混合架构设计）

### 多维表格 Workflow（推荐优先实施）
Trading Episodes 表新增记录 → 自动推群通知:
- **前置**: Hermes Bot 需 `bitable:app` + `base:workflow:write` scope + Bitable 分享给 Bot
- **设计**: `AddRecordTrigger` → `IfElseBranch`(按 Gate C/direction/PnL 分流) → `LarkMessageAction`
- **部署**: `lark-cli base +workflow-create` 一键创建
- **前置步骤**: `lark-cli config bind --source hermes --identity bot-only`

### 审批机器人（替代 ESCALATE 卡片）
飞书后台创建审批模板后，Bot 通过 API 创建审批实例:
- `6TRADING_GATEC_ENTRY`: Red Team Flag 时的入场确认
- `6TRADING_ESCALATE`: 单笔浮亏≥500U / 连损≥3次 / 象限切换
- Bot scope 需要: `approval:instance:write`

### 飞书「流程」模块评估
| 适合自动化 | 不适合 |
|-----------|--------|
| Gate-C 条件分支 (ENTER/SKIP/ESCALATE) | A1/A2/A3 复杂分析 |
| A6 定时监控 (TimerTrigger + HTTPClientAction) | 三屏全流程编排 |
| 马丁加仓触发 (价格阈值 → 推群) | |
| Bitable 变更 → 自动通知 | |

**结论**: Hermes 做分析引擎 + 飞书原生做通知/审批/记录流转（混合架构）

---

## 十一、常见问题速查

| 问题 | 原因 | 解决 |
|------|------|------|
| Screen1 卡片字段为空 | `strategy-type.json` 缺少 `confidence_breakdown` | 确保 Screen1 Phase-2 合成完整 |
| Screen2 卡片显示 `?` | `daily-presets.json` 缺少 `direction`/`entry_price` | 参考 `feishu-screen2-format.md` |
| `send_message` 无频道 | `sessions.json` 不存在 | 在任意飞书群 @Bot 发一条消息触发注册 |
| Gateway 显示 "No messaging platforms enabled" | config.yaml 解析崩溃 | `hermes gateway restart` |
| Bitable API 返回 `99991672` | Bot 缺少 scope | 开发者后台添加 `bitable:app` / `base:app:read` |
| lark-cli 未配置 | Hermes 未绑定 | `lark-cli config bind --source hermes --identity bot-only` |
| feishu_notify.py 凭证失效 | App Secret 已轮换 | 更新 `FEISHU_APP_ID`/`FEISHU_APP_SECRET` 为 Hermes Bot 凭证 |
| `base +workflow-create` 失败 | Bot 缺少 `base:workflow:write` | 开发者后台添加 scope |
