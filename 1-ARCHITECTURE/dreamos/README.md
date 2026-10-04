# Dreambuddy OS

> **路径**：`1-ARCHITECTURE/dreamos/`
> **版本**：v1.0
> **最后更新**：2026-09-30

---

## 一、概述

Dreambuddy OS 是 DreamBuddy v2 的系统级 SKILL 内核，将 **S-A-C-G 四层架构**串联为完整的交易 Agent：

- **S (Sense)** → 意图识别：用户输入/市场数据 → 交易意图
- **A (Arrange)** → 图编排：根据意图从注册表选节点、分配预算、构建执行图
- **C (Compute)** → 执行：运行节点、反射决策、结果聚合
- **G (GraphStore)** → 存储：状态快照、历史记录、上下文压缩

设计原则：节点可插拔（Registry 管理）、预算全局管控（GlobalBudgetManager）、状态可追溯（GraphStore）、自我进化（历史数据驱动）。

---

## 二、目录结构

```
dreamos/
├── apps/                      # 应用入口
│   ├── api_server.py          # Flask HTTP API 服务
│   ├── cli.py                 # CLI 命令行入口（向后兼容）
│   └── trading_agent/
│       └── agent.py           # TradingAgent 主类
├── cli/                       # CLI 命令
│   ├── commands.py            # status / nodes / history
│   ├── analyze_commands.py    # analyze / chat
│   ├── auto_commands.py       # auto / trade
│   ├── orchestration_commands.py  # orchestration-* 系列
│   ├── scheduler_commands.py  # schedule / cron / job
│   ├── dreamos_backtester.py  # 回测 CLI
│   └── ...
├── capabilities/trading/      # 交易能力
│   ├── nodes/                 # 节点定义（A/C/F/G 链）
│   ├── backtest/              # 回测引擎
│   ├── execution/             # 自动交易
│   ├── evaluators/            # 动态编排器/L4 粗筛/回测精调
│   ├── entry_strategy/        # 入场策略
│   ├── exit_strategy/         # 离场策略
│   └── ...
├── adapters/                  # 适配器
│   ├── base.py                # BaseAdapter / AdapterRegistry
│   ├── api_adapter.py         # HTTP API 适配器
│   ├── skill_adapter.py       # SKILL.md 适配器
│   └── function_adapter.py    # 本地函数适配器
├── budget/                    # 预算管理
│   ├── global_budget.py       # GlobalBudgetManager
│   └── cost_tracker.py        # 成本追踪
├── core/                      # 内核（sense/arrange/compute/graph_store）
├── registry/                  # 节点注册表
└── docs/                      # 文档
```

---

## 三、快速开始

### 1. CLI 使用

```bash
# 查看 Agent 状态
python -m dreamos status

# 列出已注册节点
python -m dreamos nodes --chain A

# 单次市场数据分析
python -m dreamos analyze --price 65000 --rsi 45 --regime TREND

# 对话式分析
python -m dreamos chat "BTC 现在怎么看？"

# 查看历史记录
python -m dreamos history -n 20
```

### 2. HTTP API 启动

```bash
python -m dreamos.apps.api_server
# 默认端口 8000
# Health: http://localhost:8000/api/v1/health
```

### 3. Python API

```python
from dreamos.apps.trading_agent import TradingAgent

agent = TradingAgent(budget_mode="standard")
result = agent.run(
    user_input="BTC 现在怎么看？",
    market_data={"price": 65000, "rsi14": 45},
)
print(result["action"], result["confidence"])
```

### 4. 回测

```bash
cd 1-ARCHITECTURE
python -m dreamos.cli.dreamos_backtester --symbols BTC,ETH,SOL --interval 1h
```

---

## 四、核心功能表格

| 功能模块 | 核心类/函数 | 说明 |
|---------|------------|------|
| **TradingAgent** | `apps/trading_agent/agent.py` | S-A-C-G 全链路编排主类 |
| **HTTP API** | `apps/api_server.py` | Flask RESTful API，暴露 TradingAgent 能力 |
| **CLI** | `cli/commands.py` 等 | 命令行工具（status/nodes/history/analyze/chat/auto/schedule） |
| **意图引擎** | `core/sense/intent_engine.py` | `IntentEngine` 意图识别 |
| **图规划器** | `core/arrange/graph_planner.py` | `GraphPlanner` 构建执行图 |
| **图执行器** | `core/compute/graph_executor.py` | `GraphExecutor` 执行节点 |
| **图存储** | `core/graph_store/` | `GraphStore` 状态持久化 |
| **全局预算** | `budget/global_budget.py` | `GlobalBudgetManager` 跨周期预算总控 |
| **成本追踪** | `budget/cost_tracker.py` | `CostTracker` Token 成本追踪 |
| **适配器基类** | `adapters/base.py` | `BaseAdapter` / `AdapterRegistry` |
| **回测引擎** | `capabilities/trading/backtest/engine.py` | `DreamOSBacktester` 端到端回测 |
| **自动交易** | `capabilities/trading/execution/auto_trader.py` | `AutoTrader` 自动化交易流程 |
| **动态编排器** | `capabilities/trading/evaluators/dynamic_orchestrator.py` | `DynamicOrchestrator` L4粗筛+回测精调 |
| **动态杠杆** | `capabilities/trading/execution/auto_trader.py` | `calc_dynamic_leverage()` 基于置信度计算杠杆 |

---

## 五、配置说明

### 5.1 预算档位（global_budget.py）

| 档位 | per_cycle | per_day | per_month |
|------|-----------|---------|-----------|
| `lean` | 3,000 | 30,000 | 500,000 |
| `standard` | 6,000 | 60,000 | 1,000,000 |
| `full` | 10,000 | 100,000 | 2,000,000 |

### 5.2 层预算分配比例（DEFAULT_LAYER_RATIOS）

| 层 | 比例 |
|----|------|
| S (sense) | 10% |
| A (arrange) | 5% |
| C (compute) | 75% |
| G (graph_store) | 5% |
| E (evolution) | 5% |

### 5.3 预算健康度（BudgetLevel）

| 级别 | 说明 | 降级策略 |
|------|------|---------|
| `healthy` | 充足 | 正常执行 |
| `warning` | 预警 | 减少可选节点 |
| `tight` | 紧张 | 跳过 LLM 识别，纯规则模式 |
| `critical` | 严重不足 | 进一步降级 |
| `exhausted` | 耗尽 | 切换到经典指标系统（零 Token） |

### 5.4 自动交易参数（auto_trader.py）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MIN_LEVERAGE` | 1 | 最小杠杆 |
| `MAX_LEVERAGE` | 5 | 最大杠杆 |
| `DEFAULT_LEVERAGE` | 3 | 默认杠杆 |
| `CONFIDENCE_THRESHOLD` | 0.4 (env `DREAMOS_CONFIDENCE_THRESHOLD`) | 置信度阈值 |
| `FALLBACK_SUSPEND_THRESHOLD` | 3 | 连续降级暂停 symbol 阈值 |

### 5.5 动态杠杆映射

| 置信度 | 杠杆 |
|--------|------|
| ≤ 0.4 | 1x |
| 0.6 | 约 3x |
| ≥ 0.8 | 5x |

### 5.6 回测参数（engine.py）

| 参数 | 值 | 说明 |
|------|-----|------|
| `WINDOW_SIZE` | 48 | 用前 48 根 K 线计算指标 |
| `STEP` | 4 | 每隔 4 根 K 线采样一次 |

---

## 六、相关文档

| 文档 | 说明 |
|------|------|
| [docs/ENGINEERING_INDEX.md](docs/ENGINEERING_INDEX.md) | 工程索引 |
| [docs/TECHNICAL_DESIGN.md](docs/TECHNICAL_DESIGN.md) | 技术设计 |
| [docs/API_SPEC.md](docs/API_SPEC.md) | API 规范 |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | 变更记录 |
