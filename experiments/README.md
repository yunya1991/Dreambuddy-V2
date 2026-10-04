# Experiments 工程索引

> **路径**：`experiments/`
> **版本**：v1.0
> **最后更新**：2026-09-30
> **用途**：DreamBuddy v2 交易实验工程的完整目录与文件索引

---

## 一、概述

`experiments/` 是 DreamBuddy v2 的交易实验工程，核心是 **AB 双 Agent 对比实验**：

- **Agent A** = Raw LLM 驱动实战交易（对照组，仅依赖模型原生推理）
- **Agent B** = Dreambuddy OS 架构验证（实验组，A0矛盾论+A2第一性原理+A3大师研讨+A7门禁+图压缩+记忆进化）
- **Agent C** = 基于 Dream OS 内核的交易分析应用（预留）

实验在 Hyperliquid 合约市场进行，A 用主账户、B 用子账户，同市场、不同决策框架。

---

## 二、目录结构

```
experiments/
├── ab-trading/              ← AB双Agent对比实验（核心）
│   ├── agents/              ← Agent 主流程（agent_a_runner / agent_b_runner）
│   ├── core/                ← 核心引擎（记忆/链路/意图/进化/节点/图存储）
│   ├── execution/           ← 交易所执行层（Hyperliquid / OKX / 链上TP-SL）
│   ├── scoring/             ← 评分与日志（DecisionLog）
│   ├── config/              ← 环境配置（experiment.json / .env）
│   ├── docs/                ← 技术文档（Agent A/B 框架、三屏系统设计）
│   ├── skills/              ← SKILL 定义（agent-a-trading / screen-martin-trading）
│   ├── scripts/             ← 运维脚本（启动 / cron / 标的筛选）
│   ├── tests/               ← 测试（stress_test / test_llm_fallback 等）
│   ├── A系列研报/            ← 研报输出（A1 环境扫描 / A6 情报 / 周报）
│   └── *.py / *.html        ← 顶层脚本与监控页面
├── agent_c/                 ← Agent C（预留，基于 Dream OS 内核）
├── docs/                    ← 工程文档（README / ENGINEERING_INDEX / TECHNICAL_DESIGN / API_SPEC / CHANGELOG）
└── INDEX.md                 ← 原工程索引
```

---

## 三、快速开始

### 1. 环境准备

```bash
cd experiments/ab-trading
cp config/.env.template config/.env
# 填入 Hyperliquid API、Trae/DeepSeek LLM Key 等
pip install -r requirements.txt
```

### 2. 启动 Agent A（Raw LLM 对照组）

```bash
bash scripts/run_agent_a.sh
```

### 3. 启动 Agent B（DreamBuddy 实验组）

```bash
bash scripts/run_agent_b.sh
```

### 4. 启动监控页面

打开 `ab-trading/monitor.html` 查看风控门禁、倒计时、持仓、决策日志。

### 5. 运行 Agent C

```bash
cd experiments/agent_c
python agent_c.py
```

---

## 四、核心功能

| 功能模块 | 核心类/函数 | 说明 |
|---------|------------|------|
| **Agent A 主流程** | `agents/agent_a_runner.py` | SOP 10步：记忆→超时检查→离场→扫描→LLM决策→连败保护→执行→日志→记忆更新 |
| **Agent B 主流程** | `agents/agent_b_runner.py` | Dreambuddy OS 验证：意图识别→BAC三层→动态执行→自我进化→D-Z-E开发链 |
| **图编排器** | `core/graph_orchestrator.py` | `GraphOrchestrator` 编排 A/C/F 三链；`NodeSelector` 动态选节点；`ExecutionGraph` 执行图 |
| **意图识别引擎** | `core/intent_engine/engine.py` | `IntentRecognitionEngine` 三层：目标提取→OKR→蓝图 |
| **统一节点执行器** | `core/c_execution_layer/unified_executor.py` | `UnifiedNodeExecutor` 整合注册表+适配器+重试+降级 |
| **图存储管理器** | `core/g_graph_storage/manager.py` | `GraphStorageManager` 管理 G.B/G.A/G.C 三层图，支持压缩/展开/版本 |
| **节点注册表** | `core/nodes/node_registry.py` | 粗-中-细三层（链→模块→节点），支持 skill/api/local/composite 节点 |
| **进化引擎** | `core/evolution/evolution_engine.py` | `EvolutionEngine` 三层进化：A8理论实践 / 做梦部 / GitHub成熟经验 |
| **离场模块** | `core/exit_module.py` | L1 基础离场 + L2 LLM 智能调仓 |
| **Classic 驱动** | `core/classic_driver.py` | `ClassicDriver` 使用实际余额进行资金分配 |
| **交易记忆** | `core/trading_memory.py` | `TradingMemory` 跨 session 记忆持久化 |
| **Agent A 记忆** | `core/agent_a_memory.py` | 教训管理、大师切换、连败保护 48h 超时、倒计时 |
| **Agent A LLM** | `core/agent_a_llm.py` | 三级 LLM 回退：Trae → DeepSeek V4 → 基本规则 |
| **链路路由器** | `core/chain_router.py` | A0矛盾内置、做梦部、治理环、equity 传参、动态追加 |
| **链路规划器** | `core/chain_planner.py` | 零 Token 四维过滤（预算/知识库/历史/标的） |
| **意图网关** | `core/intent_gateway.py` | 六种意图类型，本地零 Token 打分 |
| **Hyperliquid 执行** | `execution/aster_spot.py` | `HyperliquidClient` 开仓/平仓/查询；`scan_opportunities`；`get_candles` |
| **评分卡片** | `scoring/scorecard.py` | `DecisionLog` 决策日志结构与保存 |

---

## 五、配置说明

### experiment.json 核心参数

| 参数 | 值 | 说明 |
|------|-----|------|
| `experiment.id` | `ab-trading-v2` | 实验 ID |
| `experiment.start_date` | `2026-06-23` | 开始日期 |
| `experiment.target_cycles` | `84` | 目标周期数 |
| `experiment.cron_interval_hours` | `1` | Cron 间隔（小时） |
| `experiment.venue` | `hyperliquid` | 交易场所 |
| `experiment.market_type` | `perp` | 市场类型（永续合约） |
| `isolation.agent_a.account` | `main` | A 主账户 |
| `isolation.agent_b.account` | `sub` | B 子账户 |
| `position_sizing.per_trade_pct` | `0.05` | 单笔仓位比例 5% |
| `position_sizing.max_position_pct` | `0.20` | 最大持仓比例 20% |
| `position_sizing.max_leverage` | `5` | 最大杠杆 5x |
| `position_sizing.hard_stop_loss_pct` | `0.04` | 硬止损 4% |
| `position_sizing.take_profit_pct` | `0.08` | 止盈 8% |

### Agent A 运行时配置（agent_a_runner.py）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `AUTO_EXECUTE` | `false` | 是否自动执行交易 |
| `BUDGET_USDC` | `60.0` | 子账户预算（USDC） |
| `PER_TRADE_PCT` | `0.05` | 单笔仓位比例 |
| `DEFAULT_LEV` | `3` | 默认杠杆 |
| `STOP_LOSS_PCT` | `0.04` | 止损 4% |
| `TP_PCT` | `0.08` | 止盈 8% |
| `LOSS_PROTECTION_TRIGGER` | `3` | 连败保护触发阈值 |

### Agent B 运行时配置（agent_b_runner.py）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `AUTO_EXECUTE` | `false` | 是否自动执行交易 |
| `CONFIDENCE_GATE` | `0.55` | 置信度门禁阈值 |
| `MAX_LEVERAGE` | `5` | 最大杠杆 |
| `DEFAULT_LEVERAGE` | `5` | 默认杠杆 |
| `PR_NUMBER` | `"52"` | PR 评论编号 |

---

## 六、相关文档

| 文档 | 说明 |
|------|------|
| [docs/ENGINEERING_INDEX.md](docs/ENGINEERING_INDEX.md) | 工程索引：模块定位、目录地图、文件清单、核心流程、配置、测试、技术债务 |
| [docs/TECHNICAL_DESIGN.md](docs/TECHNICAL_DESIGN.md) | 技术设计：架构、算法、数据流、接口、状态、配置、错误处理、扩展性 |
| [docs/API_SPEC.md](docs/API_SPEC.md) | API 规范：接口概览、认证、接口详情、错误码、版本管理 |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | 版本变更记录 |
| [INDEX.md](INDEX.md) | 原工程索引（文件清单速查） |
| [ab-trading/docs/agent_a_trading_framework.md](ab-trading/docs/agent_a_trading_framework.md) | Agent A 框架文档（连败保护48h超时、风控门禁） |
| [ab-trading/docs/agent_b_trading_framework.md](ab-trading/docs/agent_b_trading_framework.md) | Agent B 框架文档（实际余额资金分配、equity传参） |
| [ab-trading/docs/trend-screen-system-design.md](ab-trading/docs/trend-screen-system-design.md) | 三屏趋势系统设计 |
