# 8-FEISHU — 飞书协作系统

Dreambuddy 飞书协作层的完整配置档案。本目录是**飞书侧所有配置的 source of truth**，任何飞书资源变更后须同步更新此处。

---

## 系统架构

```
人类决策者（你）
    │
    ├── 飞书群组（5个）← 接收报告/通知/审批
    ├── 飞书审批中心   ← Gate-C / A9 正式审批单
    ├── 飞书 OKR       ← 季度目标追踪（AI 自动更新进度）
    └── Wiki 知识库    ← 交易知识/策略/复盘档案
         │
    AI 执行层
    ├── Dream Bot（openclaw）  ← 分析引擎，推送报告
    │     App: cli_aa9442bde4b89be9
    │     用途: 消息推送/Wiki写入/Bitable/审批/任务/OKR
    │
    └── Hermes Bot（云涯Hermes） ← 执行引擎，接收指令
          App: cli_aa95b2dee3b85bd1
          用途: Hermes Gateway WebSocket，接收群消息执行 SKILL
```

---

## Bot 配置

| Bot | App ID | 角色 | 状态 |
|-----|--------|------|------|
| Dream (openclaw) | `cli_aa9442bde4b89be9` | 分析/推送/写入 | ✅ 激活 |
| 云涯Hermes | `cli_aa95b2dee3b85bd1` | 执行/接收指令 | ⚠️ 待后台激活机器人功能 |

---

## 飞书群组

| 群名 | chat_id | 职能 | 接收内容 |
|------|---------|------|---------|
| Trading-Research | `oc_36c575b6f39a8df3dd75057a96685a21` | 研究室 | Screen1完整报告+A1/A2/A3 |
| Trading-Desk | `oc_36c8543cea823b7546fcaad55d111f9f` | 交易台 | Screen2预设/执行日志/A6监控 |
| Trading-Management | `oc_9cf9f141613b4e6a0f34651843cf8b9b` | 管理看板 | 摘要/A9离场结论/P&L |
| Trading-Review | `oc_8868a5c84f3d8427afa9ed1a9ad7fb76` | 复盘室 | ProcessD复盘 |
| Trading-RiskControl | `oc_20fcedf0c35035568ea8fa947380f75d` | 风控审批 | Gate-C/A9审批单+AI代决通知 |
| Trading-Research-Team | `oc_c4b47c7d83d22a1e0f2770338d1826ca` | 多Agent研究 | Screen1多角色研判过程 |

---

## Hermes Gateway

- **连接方式**: WebSocket（无需公网 IP）
- **启动命令**: 已注册 Windows Startup，开机自启
- **配置文件**: `~/.hermes/config.yaml`
- **channel_prompts**: 已配置 RiskControl + Research-Team 两个群的系统提示

### Cron 任务注册表

| Job ID | 名称 | 触发 | SKILL |
|--------|------|------|-------|
| `718ba684cd56` | Screen1-weekly | 每周日 20:00 | screen1-trigger |
| `faf81794c30c` | Screen2-daily | 工作日 07:30 | screen2-trigger |
| `91117ffb9088` | A6-monitor-4h | 每 4 小时 | a6-monitor-trigger |
| `a3c5f632fbf4` | ApprovalTimeout-10min | 每 10 分钟 | approval-timeout-check |

---

## 多维表格（Bitable）

- **表格名**: Dreambuddy Trading Records
- **App Token**: `CMlnbvAKYafUL0sxLpFcxNfVnoc`
- **URL**: https://icnic28nu1x5.feishu.cn/base/CMlnbvAKYafUL0sxLpFcxNfVnoc
- **详细字段定义**: [bitable/trading-episodes.md](bitable/trading-episodes.md)

### 自动化 Workflow

| ID | 名称 | 触发 | 动作 |
|----|------|------|------|
| `wkfJb3iMDdm3jt4R` | 新 Episode 推送到交易台 | 新增记录 | → Trading-Desk |
| `wkfry9dSTdXjaNh9` | 离场 Episode 推送到管理看板 | Exit Price 更新 | → Trading-Management |

---

## 飞书审批

| 审批名 | Approval Code | 用途 |
|--------|--------------|------|
| Gate-C 入场审批 | `3901A0B3-5E7F-4A2F-A76E-74A5752BFD1F` | 入场信号人工确认 |
| A9 离场审批 | `1D4CB111-9E67-4430-AA05-3CD1C262E174` | 离场信号人工确认 |

**超时兜底**: 30 分钟未处理 → AI 自动决策（`approval_agent.py`）
- 详细规则: [approval/auto-decision-rules.md](approval/auto-decision-rules.md)

---

## Wiki 知识库

- **空间名**: 交易研究知识库
- **Space ID**: `7646891742737730517`
- **节点详情**: [wiki/node-registry.md](wiki/node-registry.md)

---

## 飞书 CLI

```bash
# 两个 profile 已配置
lark-cli profile list

# dream profile（日常操作）
lark-cli --profile dream <command> --as user

# 常用操作示例
lark-cli --profile dream wiki +node-create --space-id 7646891742737730517 --title "..." --obj-type docx
lark-cli --profile dream base +record-upsert --base-token CMlnbvAKYafUL0sxLpFcxNfVnoc ...
lark-cli --profile dream okr +progress-create --target-id <kr_id> --target-type key_result ...
```

---

## 通知脚本

所有飞书推送统一走 `6-TRADING/scripts/feishu_notify.py`：

```bash
python feishu_notify.py screen1       <session_dir>   # 研究室+管理看板
python feishu_notify.py screen2       <session_dir>   # 交易台
python feishu_notify.py execution     <session_dir>   # 交易台执行日志
python feishu_notify.py a6_monitor    <session_dir>   # 交易台A6监控
python feishu_notify.py a6_alert      <alert_json>    # 阈值预警
python feishu_notify.py a9            <session_dir>   # 管理看板+复盘室
python feishu_notify.py gate_c_approval <session_dir> # 正式Gate-C审批单
python feishu_notify.py a9_approval   <session_dir>   # 正式A9审批单
python feishu_notify.py review        <session_dir>   # 复盘室
python feishu_notify.py bitable       <session_dir>   # 写入多维表格
python feishu_notify.py task          <event> <session_dir>  # 任务追踪
```
