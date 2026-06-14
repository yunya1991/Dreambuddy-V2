# Hermes Agent 架构

> Hermes Agent 是 Dreambuddy 交易系统的运行时引擎——负责调度 LLM 任务、管理技能插件、监听网关、维护状态机。

## 架构总览

```
用户 / 平台 (飞书/Telegram/CLI)
         │
    ┌────▼────┐
    │ Gateway │ ──── 端口监听 + cron 调度器 (60s tick)
    └────┬────┘
         │
    ┌────▼────┐
    │ Hermes  │ ──── 核心引擎：会话管理、skill 加载、工具注册
    │  Agent  │
    └────┬────┘
         │
    ┌────▼──────────────┐
    │ Provider Adapter  │ ──── 适配 DeepSeek / OpenAI / Anthropic 等
    └────┬──────────────┘
         │
    ┌────▼────┐
    │  Tools  │ ──── 文件/终端/搜索/飞书/浏览器 等工具集
    └─────────┘
```

## 核心概念

### Gateway（网关）

Gateway 是常驻后台进程，负责：
- **WebSocket / HTTP 端口监听**：接收飞书、Telegram 等平台的消息推送
- **Cron 调度器**：每 60 秒 tick 一次，检查 `~/.hermes/cron/jobs.json` 中到期的任务并执行
- **消息路由**：将平台消息分发到对应的 Hermes Agent 会话

### Cron 调度器

调度器是 Gateway 内部的后台线程：

```
tick() → get_due_jobs() → _execution_loop_guard() → run_job() → _record_execution_loop_result()
  (每60s)   (读 jobs.json)    (检查状态机)       (LLM/脚本)    (推进/回退状态)
```

- 支持两种任务模式：**Agent 任务**（加载 skill，走 LLM 推理）和 **no_agent 脚本**（直接执行 Python/Bash，零 Token）
- 输出文件写入 `~/.hermes/cron/output/<job_id>/`
- A 系列任务通过 `execution_loop` 元数据字段参与状态机管理

### Skill（技能）

Skill 是 Hermes 的可复用知识模块，存放于 `~/.hermes/skills/<category>/<name>/SKILL.md`：

```yaml
---
name: skill-name
description: 技能描述
category: trading|devops|governance|lark|productivity
triggers:
  - keyword: 触发词
---
```

- Agent 加载 skill 后获得完整的领域知识、命令参考、坑点清单
- A 系列的 cron 任务通过 skill 注入领域上下文到 LLM prompt
- 项目目录下还有交易专用的 Dreambuddy skills（不在 `.hermes/skills/` 下）

### Plugin（插件）

Plugin 位于 `~/.hermes/plugins/`，提供自定义工具集。与 Skill 的区别：

| 维度 | Skill | Plugin |
|:---|:---|:---|
| 内容 | 知识/指令/Prompt | 代码/工具函数 |
| 加载方式 | `skillView()` | Python import |
| 典型用途 | 领域知识注入 | 自定义 API 封装 |

### 配置文件

| 文件 | 用途 |
|:---|:---|
| `~/.hermes/config.yaml` | 主配置：provider、model、feishu、telegram |
| `~/.hermes/cron/jobs.json` | cron 任务注册表 |
| `~/.hermes/scripts/` | no_agent 脚本安全目录 |
| `~/.hermes/.env` | 环境变量（API Key 等） |
| `~/.workbuddy/memory/trading_execution_loop.json` | A 系列状态机状态 |

## 三层闭环架构

A 系列日内系统在 Hermes 调度器上实现了三层闭环：

1. **调度闭环**：Guard（检查）→ 执行（LLM/脚本）→ Record（推进/回退状态）
2. **监控闭环**：A6 产出 control_decision → scheduler 解析并路由（启停 A9、链路重跑）
3. **治理闭环**：A8 每日审查 → orchestrator 归档

## 关键路径

```
~/.hermes/hermes-agent/cron/
├── execution_loop.py           # 状态机定义
├── scheduler.py                # 调度器核心（guard/record/apply）
└── scripts/
    ├── cron_execution_loop_orchestrator.py  # 编排器
    └── cron_governance_a8_review.py         # A8 治理审查
```

最后更新：2026-06-13 | 来源：a-series-intraday-architecture, hermes-cron-maintenance
