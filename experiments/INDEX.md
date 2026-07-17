# Experiments 工程索引

> **路径**：`/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments`
> **最后更新**：2026-07-17
> **用途**：DreamBuddy v2 交易实验工程的完整目录与文件索引

---

## 目录结构总览

```
experiments/
├── ab-trading/              ← AB双Agent对比实验（核心）
│   ├── agents/              ← Agent 主流程
│   ├── core/                ← 核心引擎（记忆/链路/意图/进化/节点）
│   ├── execution/           ← 交易所执行层（Hyperliquid）
│   ├── scoring/             ← 评分与日志
│   ├── config/              ← 环境配置
│   ├── docs/                ← 技术文档
│   ├── skills/              ← SKILL 定义
│   ├── scripts/             ← 运维脚本
│   ├── tests/               ← 测试
│   ├── A系列研报/            ← 研报输出
│   └── *.py / *.html        ← 顶层脚本与监控页面
├── agent_c/                 ← Agent C（预留）
└── INDEX.md                 ← 本文件
```

---

## 一、ab-trading/ — AB 双 Agent 对比实验

### 1.1 agents/ — Agent 主流程

| 文件 | Agent | 功能 |
|------|-------|------|
| [agent_a_runner.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/agents/agent_a_runner.py) | A | Raw Claude 主流程（SOP 10步：记忆→超时检查→离场→扫描→LLM决策→连败保护→执行→日志→记忆更新） |
| [agent_b_runner.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/agents/agent_b_runner.py) | B | DreamBuddy v2 主流程（三层架构整合，实际余额资金分配） |

### 1.2 core/ — 核心引擎

#### 顶层核心模块

| 文件 | 功能 | 关键特性 |
|------|------|----------|
| [agent_a_llm.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/core/agent_a_llm.py) | Agent A LLM 决策 | SKILL框架调用，多Provider降级 |
| [agent_a_memory.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/core/agent_a_memory.py) | Agent A 记忆系统 | 教训管理、大师切换、连败保护48h超时、倒计时 |
| [chain_router.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/core/chain_router.py) | Agent B 链路执行引擎 | A0矛盾内置、做梦部、治理环、equity传参、动态追加 |
| [chain_planner.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/core/chain_planner.py) | 零Token链路规划器 | 四维过滤（预算/知识库/历史/标的） |
| [intent_gateway.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/core/intent_gateway.py) | 意图识别层 | 六种意图类型，本地零Token打分 |
| [classic_driver.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/core/classic_driver.py) | Classic模式驱动 | 使用实际余额进行资金分配 |
| [trading_memory.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/core/trading_memory.py) | Agent B 交易记忆 | 跨session记忆持久化 |
| [exit_module.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/core/exit_module.py) | 离场模块 | L1基础离场 + L2 LLM智能调仓 |
| [llm_client.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/core/llm_client.py) | LLM 客户端 | 多Provider（Trae/DeepSeek/Rule） |
| [graph_orchestrator.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/core/graph_orchestrator.py) | 图编排器 | A/C/F三链编排 |
| [graph_checkpointer.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/core/graph_checkpointer.py) | 图检查点 | 状态持久化 |

#### core/nodes/ — 节点定义

| 文件 | 节点 | 功能 |
|------|------|------|
| a0_contradiction.py | A0 | 矛盾检测与排序（内置于A2/A3） |
| a1_research.py | A1 | 调研节点 |
| a2_analysis.py | A2 | 分析节点（含A0） |
| a3_strategy.py | A3 | 策略设计（含A0） |
| a4_gate.py | A4 | 门禁节点（≥65%通过） |
| a9_exit.py | A9 | 离场节点 |
| c1_tech_scan.py | C1 | 技术扫描（零Token） |
| f1_news.py | F1 | 新闻情报 |
| f2_fund_flow.py | F2 | 资金流（零Token） |
| f3_sentiment.py | F3 | 情绪面（零Token） |
| oneirology.py | 做梦部 | 弗洛伊德机制分析 |
| node_registry.py | - | 节点注册表 |
| node_definitions.py | - | 节点定义 |

#### core/ 其他子目录

| 目录 | 功能 |
|------|------|
| `a_graph_orchestrator/` | 图编排器类型与实现 |
| `c_execution_layer/` | C层执行（动态链路融合、决策器、重规划、反射器） |
| `evolution/` | 进化引擎（A8知行合一、做梦进化、GitHub进化、回测） |
| `g_graph_storage/` | 图存储（桥接、压缩、展开、历史、管理） |
| `intent_engine/` | 意图引擎（三层：目标提取→OKR→蓝图） |
| `modules/` | 模块框架（适配器、经典指标、基本面API、注册表） |
| `shared/` | 共享类型与接口 |

### 1.3 execution/ — 交易所执行层

| 文件 | 功能 |
|------|------|
| [aster_spot.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/execution/aster_spot.py) | Hyperliquid 合约执行（开仓/平仓/查询） |
| okx_spot.py | OKX 现货执行（预留） |
| onchain_tpsl.py | 链上止盈止损 |
| `hyperliquid/utils/signing.py` | Hyperliquid 签名工具 |

### 1.4 scoring/ — 评分与日志

| 文件 | 功能 |
|------|------|
| [scorecard.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/scoring/scorecard.py) | DecisionLog 结构定义与保存 |

### 1.5 docs/ — 技术文档

| 文件 | 版本 | 内容 |
|------|------|------|
| [agent_a_trading_framework.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/docs/agent_a_trading_framework.md) | v2.1 | Agent A 框架文档（连败保护48h超时、执行异常保护、风控门禁） |
| [agent_b_trading_framework.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/docs/agent_b_trading_framework.md) | v2.1 | Agent B 框架文档（实际余额资金分配、equity传参） |
| [trend-screen-system-design.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/docs/trend-screen-system-design.md) | - | 三屏趋势系统设计 |

### 1.6 顶层脚本

| 文件 | 功能 |
|------|------|
| [monitor.html](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/monitor.html) | AB Trading 监控页面（风控门禁/倒计时/持仓/日志） |
| [orchestrator.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/orchestrator.py) | AB 调度器 |
| [export_state.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/export_state.py) | 状态导出（供监控页面读取） |
| [bridge_server.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/bridge_server.py) | FastAPI 桥接服务器 |
| [screen_engine.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/screen_engine.py) | 三屏趋势引擎 |
| [screen_executor.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/screen_executor.py) | 三屏执行器 |
| [screen_orchestrator.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/screen_orchestrator.py) | 三屏调度器 |
| [mode_manager.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/mode_manager.py) | 模式管理（AB/Screen切换） |
| [evolution_scheduler.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/evolution_scheduler.py) | 进化调度器 |
| [fundamental_bridge.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/fundamental_bridge.py) | 基本面数据桥接 |
| [indicator_library.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/indicator_library.py) | 指标库 |
| [ml_inference.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/ml_inference.py) | ML 推理 |

### 1.7 skills/ — SKILL 定义

| 文件 | 功能 |
|------|------|
| [agent-a-trading/SKILL.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/skills/agent-a-trading/SKILL.md) | Agent A SKILL 定义 |
| [screen-martin-trading/SKILL.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/skills/screen-martin-trading/SKILL.md) | Agent B SKILL 定义 |

### 1.8 config/ — 环境配置

| 文件 | 说明 |
|------|------|
| `.env.common` | 公共环境变量（API密钥等） |
| `.env.screen` | 三屏模式配置 |
| `.env.template` | 配置模板 |
| `experiment.json` | 实验参数 |

### 1.9 data/ — 运行时数据（自动维护）

| 文件 | 说明 |
|------|------|
| `agent_a_memory.json` | Agent A 记忆（教训/大师/连败保护状态） |
| `agent_b_memory.json` | Agent B 记忆 |
| `agent_b_graph.json` | Agent B 图压缩日志 |
| `skill_registry.md` | 能力清单（三环架构节点注册表） |
| `THREE_CHAIN_DISPATCH_CHECKLIST.md` | PR#48 官方能力清单 |

### 1.10 scripts/ — 运维脚本

| 文件 | 功能 |
|------|------|
| `run_agent_a.sh` | 启动 Agent A |
| `run_agent_b.sh` | 启动 Agent B |
| `cron_poll_fallback.py` | Cron 兜底轮询 |
| `sync_a_reports.py` | A系列研报同步 |
| `universe_screener.py` | 标的筛选器 |

---

## 二、agent_c/ — Agent C（预留）

| 文件 | 功能 |
|------|------|
| [agent_c.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/agent_c/agent_c.py) | Agent C 预留入口 |

---

## 三、关键机制速查

### v2.1 变更清单（2026-07-17）

| 变更 | Agent | 文件 | 说明 |
|------|-------|------|------|
| 连败保护48h超时 | A | agent_a_memory.py | 超时自动重置 loss_streak，避免无限保护 |
| 连败保护倒计时 | A | agent_a_runner.py + monitor.html | 页面显示剩余时间，决策日志含 countdown 字段 |
| 保留原始置信度 | A | agent_a_runner.py | 风控拦截不再覆盖 confidence，添加 risk_gate_blocked 标记 |
| 执行异常保护 | A | agent_a_runner.py | try/except 包裹交易执行，API失败不崩溃 |
| 实际余额资金分配 | B | chain_router.py + agent_b_runner.py | 移除 min(equity, 60) 截断，直接使用账户实际权益 |

### Agent A 风控流程

```
加载记忆 → check_loss_protection_timeout() → 连败≥3?
  ├─ 是 + 超过48h → 重置 loss_streak=0，继续正常决策
  ├─ 是 + 未超时 → LLM决策后强制HOLD，保留原始置信度，记录倒计时
  └─ 否 → 正常决策
```

### Agent B 资金分配流程

```
client.get_account() → equity = acct["equity"]（不截断）
  ├─ ChainRouter(equity=equity) → pos_usdt = equity × PER_TRADE_PCT
  └─ ClassicDriver(per_trade_usdc=equity × 0.05)
```
